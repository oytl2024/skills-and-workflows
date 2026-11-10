"""Run-local, secret-free dispatch receipts for an owning lane supervisor.

An environment variable alone does not enable supervision. The supervisor binds
its retained child handle to a fresh job/nonce before granting execution. Legacy
and injected clients without that context keep their ordinary requests behavior.
"""

from contextlib import contextmanager
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import time
from urllib.parse import urlsplit
from uuid import uuid4

from wqb.lockfile import json_lock_transition_guard
from wqb.runtime_control import CONTROL_ENV, DEADLINE_ENV
from wqb.research_group import _read, _write


JOB_ENV = 'BRAIN_WORKFLOW_NETWORK_JOB'
NONCE_ENV = 'BRAIN_WORKFLOW_NETWORK_NONCE'
DEFAULT_REQUEST_TIMEOUT_SECONDS = 30.0
SUPERVISION_POLL_SECONDS = .02
TERMINATION_WAIT_SECONDS = 5.0
ADMISSION_WAIT_SECONDS = 10.0


class OwnedExecutionTree:
    """A retained Popen tree, never a process recovered from a saved PID."""

    def __init__(self):
        """Input: none. Output: owner object; prepare OS containment before dispatch permission."""
        self.process = None
        self.job = None
        self.posix_signalled = False
        self.spawn_kwargs = ({'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt'
                             else {'start_new_session': True})
        if os.name == 'nt':
            self._windows_job()

    def _windows_job(self):
        """Input: self. Output: None; create a kill-on-owner-close Windows Job Object."""
        import ctypes
        from ctypes import wintypes
        class BasicLimits(ctypes.Structure):
            _fields_ = [('ProcessTime', ctypes.c_int64), ('JobTime', ctypes.c_int64),
                ('Flags', wintypes.DWORD), ('MinWorkingSet', ctypes.c_size_t), ('MaxWorkingSet', ctypes.c_size_t),
                ('ActiveLimit', wintypes.DWORD), ('Affinity', ctypes.c_size_t),
                ('Priority', wintypes.DWORD), ('Scheduling', wintypes.DWORD)]
        class IOLimits(ctypes.Structure):
            _fields_ = [(name, ctypes.c_uint64) for name in
                ('ReadOps', 'WriteOps', 'OtherOps', 'ReadBytes', 'WriteBytes', 'OtherBytes')]
        class ExtendedLimits(ctypes.Structure):
            _fields_ = [('Basic', BasicLimits), ('IO', IOLimits), ('ProcessMemory', ctypes.c_size_t),
                ('JobMemory', ctypes.c_size_t), ('PeakProcessMemory', ctypes.c_size_t), ('PeakJobMemory', ctypes.c_size_t)]
        class Accounting(ctypes.Structure):
            _fields_ = [(name, ctypes.c_int64) for name in ('UserTime', 'KernelTime', 'PeriodUser', 'PeriodKernel')] + [
                (name, wintypes.DWORD) for name in ('PageFaults', 'TotalProcesses', 'ActiveProcesses', 'TerminatedProcesses')]
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        signatures = {
            'CreateJobObjectW': ([ctypes.c_void_p, wintypes.LPCWSTR], wintypes.HANDLE),
            'SetInformationJobObject': ([wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD], wintypes.BOOL),
            'AssignProcessToJobObject': ([wintypes.HANDLE, wintypes.HANDLE], wintypes.BOOL),
            'TerminateJobObject': ([wintypes.HANDLE, wintypes.UINT], wintypes.BOOL),
            'QueryInformationJobObject': ([wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
                wintypes.DWORD, ctypes.c_void_p], wintypes.BOOL),
            'CloseHandle': ([wintypes.HANDLE], wintypes.BOOL)}
        for name, (args, result) in signatures.items():
            function = getattr(kernel, name)
            function.argtypes, function.restype = args, result
        self.kernel, self.accounting_type = kernel, Accounting
        job = kernel.CreateJobObjectW(None, None)
        if not job:
            raise OSError('cannot create owned execution job')
        limits = ExtendedLimits()
        limits.Basic.Flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE; no breakaway permission.
        if not kernel.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            kernel.CloseHandle(job)
            raise OSError('cannot contain owned execution job')
        self.job = job

    def attach(self, process):
        """Input: actual Popen handle. Output: None; enroll the still-unpermitted execution tree."""
        self.process = process
        if os.name == 'nt' and not self.kernel.AssignProcessToJobObject(self.job, int(process._handle)):
            # Execution has no permit yet, so no descendant/network work is legal.
            process.kill()
            process.wait(timeout=TERMINATION_WAIT_SECONDS)
            raise OSError('cannot enroll owned execution process')

    def poll(self):
        """Input: self. Output: exit code/None; inspect only the retained child handle."""
        if os.name != 'nt':
            # WNOWAIT keeps the group leader unreaped, preventing PID/PGID reuse
            # until its entire session is terminated below.
            event = os.waitid(os.P_PID, self.process.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
            if event is None:
                return None
            return event.si_status if event.si_code == os.CLD_EXITED else -event.si_status
        return self.process.poll()

    def terminate_and_confirm(self) -> bool:
        """Input: self. Output: bool; kill only enrolled work and confirm all owned senders are dead."""
        if self.process is None:
            return True
        if os.name == 'nt':
            import ctypes
            if not self.kernel.TerminateJobObject(self.job, 1):
                return False
            end = time.monotonic() + TERMINATION_WAIT_SECONDS
            while True:
                counts = self.accounting_type()
                if not self.kernel.QueryInformationJobObject(self.job, 1, ctypes.byref(counts), ctypes.sizeof(counts), None):
                    return False
                if counts.ActiveProcesses == 0:
                    self.process.wait(timeout=TERMINATION_WAIT_SECONDS)
                    return True
                if time.monotonic() >= end:
                    return False
                time.sleep(SUPERVISION_POLL_SECONDS)
        # The unreaped leader still pins this PGID; never reconstruct it from disk.
        if not self.posix_signalled:
            try:
                os.killpg(self.process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            self.posix_signalled = True
        self.process.wait(timeout=TERMINATION_WAIT_SECONDS)
        end = time.monotonic() + TERMINATION_WAIT_SECONDS
        while True:
            try:
                os.killpg(self.process.pid, 0)
            except ProcessLookupError:
                return True
            if time.monotonic() >= end:
                return False
            time.sleep(SUPERVISION_POLL_SECONDS)

    def close(self):
        """Input: self. Output: None; close the retained containment handle, never attach to another PID."""
        if self.job is not None:
            self.kernel.CloseHandle(self.job)
            self.job = None


class OwnedSubmissionFence:
    """Supervisor-held original POST fence; this adds no reservation or retry authority."""

    def __init__(self, run: Path, job: Path, owner: dict):
        """Input: authenticated run/job Paths and retained owner dict. Output: fence broker with no active lease."""
        self.run, self.job, self.owner = run, job, owner
        self.gate, self.gate_id = None, ''

    def step(self):
        """Input: self. Output: None; admit one waiting POST through the existing fair OS gate."""
        if self.gate is not None:
            released = safe_path(self.job / 'network_admissions' / (self.gate_id + '.released.json'))
            if not released.exists():
                return
            self._validate(_read(released))
            self.release()
        path = safe_path(self.job / 'network_admission.json')
        if not path.exists():
            return
        row = _read(path)
        self._validate(row)
        directory = safe_path(self.job / 'network_admissions')
        if (directory / (row['gate_id'] + '.released.json')).exists():
            return
        from wqb.runtime_control import submission_request_gate
        gate = submission_request_gate(self.run, fair=True)
        gate.__enter__()
        self.gate, self.gate_id = gate, row['gate_id']
        _write(safe_path(directory / (self.gate_id + '.granted.json')), row)

    def _validate(self, row):
        """Input: untrusted admission dict. Output: None; authenticate against the actual enrolled execution."""
        if (set(row) != {'gate_id', 'owner_nonce', 'execution_pid'} or not hex_identity(row.get('gate_id'))
                or row.get('owner_nonce') != self.owner['owner_nonce']
                or row.get('execution_pid') != self.owner['execution_pid']
                or self.gate is not None and row['gate_id'] != self.gate_id):
            raise ValueError('owned POST admission mismatch')

    def release(self):
        """Input: self. Output: None; called only after dispatch exits or whole-tree termination is confirmed."""
        if self.gate is not None:
            gate = self.gate
            self.gate, self.gate_id = None, ''
            gate.__exit__(None, None, None)


@contextmanager
def owned_submission_gate(run: Path):
    """Input: owning run Path. Output: context; let its supervisor retain the existing fair POST fence."""
    context = authenticated_context()
    if context is None:
        from wqb.runtime_control import submission_request_gate
        with submission_request_gate(run, fair=True):
            yield
        return
    job, owner = context
    if safe_path(run) != safe_path(owner['run_dir']):
        raise ValueError('owned POST run mismatch')
    directory = safe_path(job / 'network_admissions')
    directory.mkdir(exist_ok=True)
    row = dict(gate_id=uuid4().hex, owner_nonce=owner['owner_nonce'], execution_pid=owner['execution_pid'])
    _write(safe_path(job / 'network_admission.json'), row)
    try:
        grant = safe_path(directory / (row['gate_id'] + '.granted.json'))
        while not grant.exists():
            from wqb.runtime_control import check_submission_allowed
            check_submission_allowed()
            if time.monotonic() >= owner['runtime_deadline']:
                raise ValueError('owned POST admission runtime expired')
            time.sleep(SUPERVISION_POLL_SECONDS)
        if _read(grant) != row:
            raise ValueError('owned POST grant mismatch')
        yield
    finally:
        _write(safe_path(directory / (row['gate_id'] + '.released.json')), row)


def safe_path(value) -> Path:
    """Input: absolute str/Path. Output: Path; reject traversal, symlinks and junctions."""
    path = Path(value)
    if (not path.is_absolute() or '..' in path.parts
            or any(p.is_symlink() or p.is_junction() for p in (path, *path.parents))):
        raise ValueError('invalid owned network path')
    return path.resolve()


def positive_number(value) -> float:
    """Input: untrusted scalar. Output: finite positive float or ValueError."""
    if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
        raise ValueError('invalid owned network deadline')
    return float(value)


def hex_identity(value, size=32) -> bool:
    """Input: unknown value/size int. Output: bool; accept only opaque lowercase hex identities."""
    return isinstance(value, str) and len(value) == size and all(c in '0123456789abcdef' for c in value)


def authenticated_context() -> tuple[Path, dict] | None:
    """Input: inherited env plus run-local owner. Output: (job Path, owner dict) or None for unmanaged use."""
    job_value, nonce = os.environ.get(JOB_ENV), os.environ.get(NONCE_ENV)
    if not job_value and not nonce:
        return None
    if not job_value or not hex_identity(nonce) or not os.environ.get(CONTROL_ENV):
        raise ValueError('incomplete owned network context')
    job, run = safe_path(job_value), safe_path(os.environ[CONTROL_ENV])
    if job.parent != run / 'runtime/group_workers' or not hex_identity(job.name):
        raise ValueError('owned network context outside lane')
    owner = _read(safe_path(job / 'network_owner.json'))
    worker = _read(safe_path(run / 'runtime/group_worker.json'))
    if (owner.get('owner_nonce') != nonce or owner.get('run_dir') != str(run)
            or owner.get('job_id') != job.name or worker.get('job_id') != job.name
            or worker.get('status') != 'running' or worker.get('pid') != os.getppid()
            or owner.get('supervisor_pid') != os.getppid() or owner.get('execution_pid') != os.getpid()):
        raise ValueError('owned network identity mismatch')
    positive_number(owner.get('runtime_deadline'))
    positive_number(owner.get('request_timeout_seconds'))
    return job, owner


def _event(job: Path, row: dict) -> None:
    """Input: authenticated job Path/allowlisted record dict. Output: None; durably append an immutable event."""
    directory = safe_path(job / 'network_requests')
    directory.mkdir(exist_ok=True)
    path = safe_path(directory / (row['request_id'] + '.' + row['state'] + '.json'))
    with path.open('x', encoding='utf-8') as handle:
        json.dump(row, handle, allow_nan=False)
        handle.flush()
        os.fsync(handle.fileno())


@contextmanager
def owned_request(method: str, url: str, timeout_seconds, identities=None, *, stream=False):
    """Input: HTTP method/URL, bound seconds and digest list. Output: request dict/None context; never persist URL/payload."""
    context = authenticated_context()
    if context is None:
        yield None
        return
    if stream:
        raise ValueError('owned requests must consume responses inside the total deadline')
    job, owner = context
    identities = identities or []
    if not isinstance(identities, list) or any(not hex_identity(v, 64) for v in identities):
        raise ValueError('invalid owned simulation identities')
    with json_lock_transition_guard(safe_path(job / 'network_dispatch'), ADMISSION_WAIT_SECONDS,
            SUPERVISION_POLL_SECONDS, 'owned network dispatch busy'):
        # Fair POST admission and accounting have already completed at this point.
        authenticated_context()
        started = time.monotonic()
        bound = min(positive_number(timeout_seconds), owner['request_timeout_seconds'])
        deadline = min(started + bound, owner['runtime_deadline'])
        if os.environ.get(DEADLINE_ENV):
            deadline = min(deadline, positive_number(float(os.environ[DEADLINE_ENV])))
        if deadline <= started:
            raise ValueError('owned network runtime expired before dispatch')
        verb = method.upper()
        operation = ('simulation_submit' if verb == 'POST' and urlsplit(url).path.rstrip('/') == '/simulations'
                     else 'authentication' if urlsplit(url).path.rstrip('/') == '/authentication' else 'request')
        row = dict(request_id=uuid4().hex, owner_nonce=owner['owner_nonce'],
            execution_pid=owner['execution_pid'], supervisor_pid=owner['supervisor_pid'],
            method=verb if verb in {'GET', 'POST', 'OPTIONS', 'PUT', 'DELETE', 'PATCH', 'HEAD'} else 'OTHER',
            operation=operation, simulation_identities=list(identities), started=started,
            deadline=deadline, state='entered')
        _event(job, row)
        _write(safe_path(job / 'network_current.json'), row)
        try:
            yield row
        except BaseException:
            finished = {**row, 'state': 'transport_error'}
            raise
        else:
            finished = {**row, 'state': 'completed'}
        finally:
            # A diagnostic write failure must not turn an accepted POST into a retry.
            try:
                _event(job, finished)
                _write(safe_path(job / 'network_current.json'), finished)
            except (OSError, ValueError):
                pass
