"""Owned pre-mission resource preparation, independent of research runtime authority."""
from __future__ import annotations

import argparse
import math
from pathlib import Path
import subprocess
import sys
import time
from uuid import uuid4

from wqb.desktop_application import packaged_worker_command
from wqb.lockfile import exclusive_json_lock
from wqb.multiplier_preparation import _load, _save, _safe, prepare_multiplier_fields, validated_preparation_policy
from wqb.owned_network_deadline import OwnedExecutionTree

POLL_SECONDS = .05
ADMISSION_SECONDS = 10


def supervise_command(command: list[str], *, cwd: Path, deadline: float,
        check_cancelled: callable, progress: callable, permit: callable) -> int:
    """Input: owned argv/cwd/deadline/callbacks. Output: exit code; terminate all owned work before returning."""
    if type(deadline) not in (int, float) or not math.isfinite(deadline):
        raise ValueError('invalid preparation deadline')
    remaining = deadline - time.time()
    monotonic_deadline = time.monotonic() + remaining
    owner = OwnedExecutionTree()
    try:
        check_cancelled()
        if remaining <= 0:
            raise TimeoutError('preparation deadline exhausted')
        process = subprocess.Popen(command, cwd=cwd, stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **owner.spawn_kwargs)
        owner.attach(process)
        check_cancelled()
        permit()
        while True:
            check_cancelled()
            if time.time() >= deadline or time.monotonic() >= monotonic_deadline:
                raise TimeoutError('preparation deadline exhausted')
            progress()
            code = owner.poll()
            if code is not None:
                return code
            time.sleep(POLL_SECONDS)
    finally:
        try:
            if not owner.terminate_and_confirm():
                raise RuntimeError('cannot confirm preparation process termination')
        finally:
            owner.close()


def prepare_multiplier_fields_supervised(knowledge_root: Path, job_dir: Path, scope: dict, *,
        check_cancelled: callable, progress: callable, policy: dict | None = None,
        allow_network: bool = True) -> dict:
    """Input: original vault/job/scope/bounds/Stop callbacks. Output: worker receipt under a persistent total deadline."""
    bounds = validated_preparation_policy(policy)
    root, job = _safe(Path(knowledge_root)), _safe(Path(job_dir))
    check_cancelled()
    job.mkdir(parents=True, exist_ok=True)
    with exclusive_json_lock(job / '.supervisor.lock', 1, .05, 3600, 'preparation supervisor is busy'):
        path = job / 'supervisor.json'
        if path.exists():
            row = _load(path)
            if (row.get('scope') != scope or row.get('knowledge_root') != str(root)
                    or row.get('policy') != bounds or row.get('allow_network') is not allow_network
                    or type(row.get('started')) not in (int, float) or not math.isfinite(row['started'])
                    or row.get('deadline') != row['started'] + bounds['total_seconds']):
                raise ValueError('supervisor identity or original bounds changed')
        else:
            started = time.time()
            row = dict(scope=scope, knowledge_root=str(root), policy=bounds, allow_network=allow_network,
                       started=started, deadline=started + bounds['total_seconds'])
        row.update(nonce=uuid4().hex, permitted=False)
        _save(path, row)

        def permit():
            """Input: none. Output: permit only this attached child and original intent."""
            check_cancelled()
            row['permitted'] = True
            _save(path, row)

        last_progress = None

        def update():
            """Input: none. Output: forward bounded durable progress without replaying requests."""
            nonlocal last_progress
            target = job / 'worker_progress.json'
            if target.exists():
                current = _load(target)
                if current != last_progress:
                    progress(current)
                    last_progress = current

        command = packaged_worker_command([sys.executable, '-m', 'wqb.multiplier_supervision',
            '--job-dir', str(job), '--nonce', row['nonce']])
        try:
            code = supervise_command(command, cwd=Path(__file__).resolve().parents[1], deadline=row['deadline'],
                check_cancelled=check_cancelled, progress=update, permit=permit)
        finally:
            row['permitted'] = False
            _save(path, row)
        check_cancelled()
        if code != 0:
            raise RuntimeError('preparation worker failed; inspect preserved capture and attempt evidence')
        # Shared multi-file publication runs in the owning parent, never in the
        # forcibly terminated network worker. Stop checks bracket each phase.
        from wqb.multiplier_scope import publish_scope_catalog
        pending = job / 'scope_options.json'
        if pending.exists():
            check_cancelled()
            options = _load(pending)
            publish_scope_catalog(root, options['payload'], options['captured_at'])
        state_path = job / 'state.json'
        if state_path.exists():
            state = _load(state_path)
            if state.get('capture'):
                from wqb.data_field_capture import _write_index
                from wqb.multiplier_preparation import _verify_refs
                check_cancelled()
                capture = _safe(Path(state['capture']['capture_dir']))
                if not capture.is_relative_to(root / 'raw/platform/data_fields'):
                    raise ValueError('capture outside original raw boundary')
                _verify_refs(capture, state['capture_refs'])
                _write_index(capture, state['capture'], root)
        check_cancelled()
        def offline_client(**kwargs):
            """Input: client kwargs. Output: refusal; parent publication can never issue transport."""
            raise PermissionError('parent publication cannot call platform')
        result = prepare_multiplier_fields(root, job, scope, check_cancelled=check_cancelled,
            progress=progress, policy=bounds, client_factory=offline_client)
        if result.get('scope') != scope or result.get('status') != 'completed':
            raise ValueError('preparation result identity differs')
        return result


def main() -> None:
    """Input: internal job/nonce argv. Output: no research; execute preparation only after owned admission."""
    parser = argparse.ArgumentParser(description='Owned exact-scope preparation worker')
    parser.add_argument('--job-dir', type=Path, required=True)
    parser.add_argument('--nonce', required=True)
    args = parser.parse_args()
    job = _safe(args.job_dir)
    end = time.monotonic() + ADMISSION_SECONDS
    while True:
        row = _load(job / 'supervisor.json')
        if row.get('nonce') != args.nonce:
            raise ValueError('preparation admission changed')
        if row.get('permitted') is True:
            break
        if time.monotonic() >= end:
            raise TimeoutError('preparation admission timed out')
        time.sleep(POLL_SECONDS)

    def check():
        """Input: none. Output: reject revoked admission or elapsed original deadline."""
        current = _load(job / 'supervisor.json')
        if current.get('nonce') != args.nonce or current.get('permitted') is not True:
            raise InterruptedError('preparation permit revoked')
        if time.time() >= row['deadline']:
            raise TimeoutError('preparation deadline exhausted')

    def offline_client(**kwargs):
        """Input: client kwargs. Output: refusal; no-network starts cannot acquire missing resources."""
        raise PermissionError('enable-live-api is required for missing resources')

    prepare_multiplier_fields(Path(row['knowledge_root']), job, row['scope'],
        check_cancelled=check, progress=lambda update: _save(job / 'worker_progress.json', update),
        policy=row['policy'], defer_shared_publication=True,
        **({} if row['allow_network'] else {'client_factory': offline_client}))


if __name__ == '__main__':
    main()
