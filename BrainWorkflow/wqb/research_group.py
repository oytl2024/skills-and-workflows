"""Thin N-lane coordination; child runs retain stage truth and shared accounting."""

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import time
from uuid import uuid4

from wqb.lockfile import json_lock_transition_guard
from wqb.runtime_control import _write as _atomic_write


GROUP_VERSION = 1
MAX_LANES = 32
SAFE_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z')
DIGEST = re.compile(r'[a-f0-9]{64}\Z')
REVISION = re.compile(r'[a-f0-9]{32}\Z')
SUBMISSION_WAIT_SECONDS = 30.0
SUBMISSION_POLL_SECONDS = 0.01
GROUP_IO_WAIT_SECONDS = 1.0


def _digest(row: dict) -> str:
    """Input: finite JSON dict. Output: str digest of an immutable group manifest."""
    return hashlib.sha256(json.dumps(row, sort_keys=True, allow_nan=False).encode()).hexdigest()


def _read(path: Path) -> dict:
    """Input: local JSON Path. Output: dict, rejecting links or malformed records."""
    if path.is_symlink() or path.is_junction() or path.stat().st_size > 2_000_000:
        raise ValueError('invalid group record path or size')
    deadline = time.monotonic() + GROUP_IO_WAIT_SECONDS
    while True:
        try:
            row = json.loads(path.read_text(encoding='utf-8'))
            break
        except PermissionError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(SUBMISSION_POLL_SECONDS)
    if not isinstance(row, dict):
        raise ValueError('group record must be an object')
    return row


def _write(path: Path, row: dict) -> None:
    """Input: local Path/JSON dict. Output: None; bounded sharing retry, preserving atomic publication."""
    deadline = time.monotonic() + GROUP_IO_WAIT_SECONDS
    while True:
        try:
            _atomic_write(path, row)
            return
        except PermissionError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(SUBMISSION_POLL_SECONDS)


def _root(group: Path) -> Path:
    """Input: group Path. Output: absolute safe path inside its owning research_groups directory."""
    group = Path(group).absolute()
    if (group.parent.name != 'research_groups' or not SAFE_ID.fullmatch(group.name)
            or any(p.is_symlink() or p.is_junction() for p in (group, group.parent))):
        raise ValueError('invalid group directory')
    return group


def _guard(group: Path):
    """Input: group Path. Output: serialized coordination context, not a network lock."""
    return json_lock_transition_guard(group / 'intent_guard', 5.0, 0.05, 'group intent busy')


def create_group(runs_root: Path, plans: list[dict], authority: dict) -> dict:
    """Input: runs Path, distinct lane plans list, finite authority dict. Output: paused group dict.

    This freezes membership only. It cannot adopt existing runs, invoke workers,
    establish new quota, grant live access or replace an active legacy mission.
    """
    root = Path(runs_root).absolute()
    if root.is_symlink() or root.is_junction():
        raise ValueError('runs root cannot be a link')
    if not isinstance(plans, list) or not 1 <= len(plans) <= MAX_LANES:
        raise ValueError('expected bounded positive lane count')
    if (not isinstance(authority, dict) or set(authority) != {
            'enable_live_api', 'max_runtime_seconds', 'max_recoveries'}
            or type(authority['enable_live_api']) is not bool
            or any(type(authority[k]) is not int or authority[k] <= 0
                   for k in ('max_runtime_seconds', 'max_recoveries'))):
        raise ValueError('explicit bounded group authority required')
    lanes = []
    for plan in plans:
        if (not isinstance(plan, dict) or not SAFE_ID.fullmatch(str(plan.get('run_id', '')))
                or not DIGEST.fullmatch(str(plan.get('plan_digest', '')))):
            raise ValueError('invalid lane identity or frozen plan digest')
        lanes.append(dict(run_id=plan['run_id'], plan_digest=plan['plan_digest']))
    if (len({p['run_id'] for p in lanes}) != len(lanes)
            or len({p['plan_digest'] for p in lanes}) != len(lanes)):
        raise ValueError('duplicate lane or plan')
    directory = root / 'research_groups'
    if directory.is_symlink() or directory.is_junction():
        raise ValueError('group storage cannot be a link')
    directory.mkdir(parents=True, exist_ok=True)
    with json_lock_transition_guard(directory / 'create_guard', 5.0, 0.05, 'group creation busy'):
        if any((root / row['run_id']).exists() for row in lanes):
            raise ValueError('group cannot adopt an existing research run')
        group = directory / uuid4().hex
        group.mkdir()
        manifest = dict(schema_version=GROUP_VERSION, group_id=group.name,
                        lanes=lanes, authority=dict(authority),
                        budget_reference='workspace_daily_simulation_budget',
                        created_at=datetime.now(timezone.utc).isoformat())
        _write(group / 'group_manifest.json', manifest)
        _write(group / 'group_intent.json', dict(manifest_sha256=_digest(manifest),
            desired_state='paused', request_revision=uuid4().hex,
            cursor=0, elapsed_seconds=0.0, recoveries_used=0))
        for lane in lanes:
            run = root / lane['run_id']
            run.mkdir()
            _write(run / 'research_group_binding.json', dict(group_id=group.name,
                manifest_sha256=_digest(manifest), run_id=lane['run_id'], plan_digest=lane['plan_digest']))
    return read_group(group)


def read_group(group: Path) -> dict:
    """Input: owning group Path. Output: verified group/intent dict; no stage projection side effects."""
    group = _root(group)
    manifest = _read(group / 'group_manifest.json')
    intent = _read(group / 'group_intent.json')
    if (manifest.get('schema_version') != GROUP_VERSION or manifest.get('group_id') != group.name
            or intent.get('manifest_sha256') != _digest(manifest)
            or intent.get('desired_state') not in {'paused', 'running'}):
        raise ValueError('group manifest/authority changed')
    for lane in manifest['lanes']:
        if not SAFE_ID.fullmatch(lane['run_id']):
            raise ValueError('unsafe group member')
        run = group.parent.parent / lane['run_id']
        if run.is_symlink() or run.is_junction():
            raise ValueError('group member cannot be a link')
        binding = _read(run / 'research_group_binding.json')
        if binding != dict(group_id=group.name, manifest_sha256=_digest(manifest), **lane):
            raise ValueError('group membership binding changed')
    return {**manifest, **intent, 'group_dir': str(group)}


def stop_group(group: Path, expected_revision: str) -> dict:
    """Input: group Path/current revision str. Output: durable paused group after POST fence acknowledgment."""
    group = _root(group)
    with _guard(group):
        row = read_group(group)
        if row['request_revision'] != expected_revision:
            raise ValueError('stale group intent')
        intent = _read(group / 'group_intent.json')
        elapsed = intent.get('elapsed_seconds', 0.0)
        if intent.get('active_since'):
            elapsed += max(0.0, (datetime.now(timezone.utc) - datetime.fromisoformat(intent['active_since'])).total_seconds())
        _write(group / 'group_intent.json', {**intent, 'desired_state': 'paused',
            'elapsed_seconds': elapsed, 'active_since': None,
            'request_revision': uuid4().hex})
    # Pause persists before waiting for any already-entered POST; UI must distinguish both stages.
    with json_lock_transition_guard(group / 'submission_fence', 30.0, 0.05, 'group POST fence busy'):
        pass
    return read_group(group)


def resume_group(group: Path, expected_revision: str, *, request_revision: str | None = None) -> dict:
    """Input: group Path/current str and optional planned 32hex str. Output: durable running receipt."""
    from wqb.runtime_control import has_runtime_authority
    group = _root(group)
    with _guard(group):
        row = read_group(group)
        if row['request_revision'] != expected_revision:
            raise ValueError('stale group intent')
        revision = uuid4().hex if request_revision is None else request_revision
        if (not isinstance(revision, str) or not REVISION.fullmatch(revision)
                or revision == row['request_revision']):
            raise ValueError('invalid new group request revision')
        if row['elapsed_seconds'] >= row['authority']['max_runtime_seconds']:
            raise ValueError('group runtime authority exhausted')
        if any(not has_runtime_authority(group.parent.parent / lane['run_id']) for lane in row['lanes']):
            raise ValueError('each lane requires existing validated runtime authority')
        intent = _read(group / 'group_intent.json')
        _write(group / 'group_intent.json', {**intent, 'desired_state': 'running',
            'active_since': intent.get('active_since') or datetime.now(timezone.utc).isoformat(),
            'request_revision': revision})
        return read_group(group)


def group_for_run(run: Path) -> dict | None:
    """Input: child run Path. Output: verified group dict or None for an ungrouped legacy run."""
    run = Path(run).absolute()
    path = run / 'research_group_binding.json'
    if not path.exists():
        return None
    binding = _read(path)
    if not SAFE_ID.fullmatch(str(binding.get('group_id', ''))):
        raise ValueError('invalid group binding')
    if binding.get('run_id') != run.name:
        raise ValueError('group member identity mismatch')
    row = read_group(run.parent / 'research_groups' / binding['group_id'])
    if not any(lane['run_id'] == run.name and lane['plan_digest'] == binding.get('plan_digest')
               for lane in row['lanes']):
        raise ValueError('run is not a frozen group member')
    return row


def require_group_running(run: Path) -> None:
    """Input: child run Path. Output: None or RuntimePaused; apply shared Stop/time authority."""
    row = group_for_run(run)
    if row is None:
        return
    from wqb.runtime_control import RuntimePaused, RuntimeBudgetExhausted
    if row['desired_state'] != 'running':
        raise RuntimePaused('research group is paused')
    if not row['authority']['enable_live_api']:
        raise RuntimePaused('group live API permission required')
    elapsed = row['elapsed_seconds']
    if row.get('active_since'):
        elapsed += max(0.0, (datetime.now(timezone.utc) - datetime.fromisoformat(row['active_since'])).total_seconds())
    if elapsed >= row['authority']['max_runtime_seconds']:
        raise RuntimeBudgetExhausted('group runtime budget exhausted')


def next_lane(group: Path, ready: list[str]) -> str | None:
    """Input: group Path and ready lane IDs list. Output: fair lane ID or None; never starts a worker."""
    group = _root(group)
    with _guard(group):
        row = read_group(group)
        ids = [lane['run_id'] for lane in row['lanes']]
        if not isinstance(ready, list) or any(item not in ids for item in ready):
            raise ValueError('unknown ready lane')
        if row['desired_state'] != 'running':
            return None
        index = _ready_lane_index(row, ready)
        if index is not None:
            intent = _read(group / 'group_intent.json')
            _write(group / 'group_intent.json', {**intent, 'cursor': (index + 1) % len(ids)})
            return ids[index]
    return None


def _ready_lane_index(row: dict, ready) -> int | None:
    """Input: verified group dict/ready lane collection. Output: cursor-selected index int or None."""
    ids = [lane['run_id'] for lane in row['lanes']]
    for offset in range(len(ids)):
        index = (row['cursor'] + offset) % len(ids)
        if ids[index] in ready:
            return index
    return None


def _live_submission_waiters(group: Path, row: dict, own: str) -> dict:
    """Input: group Path/verified dict/own lane str. Output: current OS-leased waiters dict, no expiry grants."""
    waiting = {}
    for lane in row['lanes']:
        run_id = lane['run_id']
        lease = row.get('waiting_submissions', {}).get(run_id)
        if not lease or lease.get('revision') != row['request_revision']:
            continue
        if run_id == own:
            waiting[run_id] = lease
            continue
        try:
            with json_lock_transition_guard(group / f'waiting_{run_id}', 0, 0, 'waiting lease held'):
                pass
        except ValueError as error:
            if str(error) != 'waiting lease held':
                raise
            waiting[run_id] = lease
    return waiting


def reserve_identity(group: Path, run_id: str, identity: str) -> bool:
    """Input: group Path, member ID and simulation digest strings. Output: bool global claim/replay result."""
    return _reserve_identities(group, run_id, [identity], submission=False)


def _reserve_identities(group: Path, run_id: str, identities: list[str], *, submission: bool) -> bool:
    """Input: group/member/digests and attempt bool. Output: atomic all-or-none durable claim bool."""
    group = _root(group)
    row = read_group(group)
    if (run_id not in {lane['run_id'] for lane in row['lanes']} or not identities
            or len(set(identities)) != len(identities)
            or any(not DIGEST.fullmatch(identity) for identity in identities)):
        raise ValueError('invalid simulation reservation owner or identity')
    directory = group.parent
    path = directory / 'simulation_reservations.json'
    with json_lock_transition_guard(directory / 'identity_guard', 5.0, 0.05, 'group identity busy'):
        claims = _read(path) if path.exists() else {}
        owner = dict(group_id=group.name, run_id=run_id)
        for identity in identities:
            prior = claims.get(identity)
            if prior is not None and (any(prior.get(k) != v for k, v in owner.items())
                    or submission and prior.get('submission_status') not in (None, 'not_sent', 'rejected_429')):
                return False
        for identity in identities:
            claims[identity] = {**claims.get(identity, {}), **owner}
            if submission:
                claims[identity]['submission_status'] = 'unknown'
        _write(path, claims)
        return True


def reserve_payloads(run: Path, payload) -> list[str]:
    """Input: child Path and actual JSON payload. Output: CLI identity digests, durably fenced before POST."""
    from wqb.cli import simulation_identity_hash
    from wqb.runtime_control import RuntimePaused
    row = group_for_run(run)
    if row is None:
        return []
    payloads = payload if isinstance(payload, list) else [payload]
    if not payloads or any(not isinstance(p, dict) or not isinstance(p.get('regular'), str)
                           or not p['regular'] or not isinstance(p.get('settings'), dict) for p in payloads):
        raise ValueError('group simulation requires expression/settings identity')
    identities = [simulation_identity_hash(p['regular'], p['settings']) for p in payloads]
    if not _reserve_identities(Path(row['group_dir']), run.name, identities, submission=True):
        raise RuntimePaused('simulation identity already reserved or outcome unknown; reconcile before retry')
    return identities


def record_payload_outcome(run: Path, identities: list[str], response) -> None:
    """Input: member Path/digests/response or None before dispatch. Output: None; retain replay evidence."""
    if not identities:
        return
    row = group_for_run(run)
    directory = Path(row['group_dir']).parent
    path = directory / 'simulation_reservations.json'
    with json_lock_transition_guard(directory / 'identity_guard', 5.0, 0.05, 'group identity busy'):
        claims = _read(path)
        for identity in identities:
            if response is None:
                claims[identity]['submission_status'] = 'not_sent'
            else:
                status = ('rejected_429' if response.status_code == 429 else
                          'unknown' if response.status_code >= 500 else 'sent')
                claims[identity].update(submission_status=status, status_code=response.status_code,
                                       progress_url=response.headers.get('Location', ''))
        _write(path, claims)


def account_cooldown_source(run: Path) -> Path | None:
    """Input: child Path. Output: account-shared rate state directory Path, or None for legacy."""
    row = group_for_run(run)
    return Path(row['group_dir']).parent / 'account_cooldown' if row else None


def check_account_cooldown(source: Path, *, submission: bool = False) -> None:
    """Input: shared source Path/POST bool. Output: None or existing rate boundary; GET retains its threshold."""
    from wqb.rate_limit_state import (check_source_retry_authorization, read_rate_limit_state,
        cooldown_is_active, rate_limit_requires_maintenance, RateLimitRecoveryRequired)
    if submission:
        try:
            check_source_retry_authorization(source)
        except RateLimitRecoveryRequired as error:
            error.simulation_submit = True
            raise
        return
    state = read_rate_limit_state(source / 'rate_limit_state.json')
    if state.get('status') == 'invalid':
        raise ValueError('invalid shared cooldown evidence')
    now = datetime.now(timezone.utc).isoformat()
    if cooldown_is_active(state, now) or rate_limit_requires_maintenance(state, now):
        error = RateLimitRecoveryRequired(source, state)
        error.simulation_submit = False
        raise error


def record_account_429(run: Path, response, method: str) -> None:
    """Input: lane Path/actual 429 response/method str. Output: None; retain existing bounded rate policy."""
    from wqb.rate_limit_state import record_rate_limit
    import requests
    source = account_cooldown_source(run)
    if source is None:
        return
    with json_lock_transition_guard(source.parent / 'cooldown_guard', 5.0, 0.05, 'account cooldown busy'):
        record_rate_limit(source, method, requests.HTTPError(response=response), {},
                          datetime.now(timezone.utc).isoformat())


def record_account_progress(run: Path, prior: dict, reason: str) -> None:
    """Input: member Path/pre-request state dict/verified progress reason str. Output: None; reset unchanged evidence."""
    from wqb.rate_limit_state import read_rate_limit_state, reset_rate_limit
    source = account_cooldown_source(run)
    if source is None or prior.get('status') != 'cooldown':
        return
    with json_lock_transition_guard(source.parent / 'cooldown_guard', 5.0, 0.05, 'account cooldown busy'):
        if read_rate_limit_state(source / 'rate_limit_state.json') == prior:
            reset_rate_limit(source, reason, datetime.now(timezone.utc).isoformat())


def authorize_group_retry(run: Path, source: Path, now: str) -> None:
    """Input: lane/source Paths/time str. Output: None; atomically charge one shared recovery before leasing."""
    from wqb.runtime_control import RuntimePaused
    from wqb.rate_limit_state import (authorize_bounded_retry, read_rate_limit_state,
        MAX_CONSECUTIVE_429, bounded_retry_is_authorized, cooldown_is_active)
    row = group_for_run(run)
    if row is None:
        authorize_bounded_retry(source, now)
        return
    group = Path(row['group_dir'])
    with _guard(group):
        require_group_running(run)
        row = read_group(group)
        if row['recoveries_used'] >= row['authority']['max_recoveries']:
            raise RuntimePaused('automatic_recovery_budget_exhausted')
        intent = _read(group / 'group_intent.json')
        _write(group / 'group_intent.json', {**intent, 'recoveries_used': row['recoveries_used'] + 1})
        # Never wait for the POST fence while holding intent; admission briefly takes fence -> intent.
        with json_lock_transition_guard(group.parent / 'cooldown_guard', 5.0, 0.05, 'account cooldown busy'):
            authorize_bounded_retry(source, now)
            shared = group.parent / 'account_cooldown'
            state = read_rate_limit_state(shared / 'rate_limit_state.json')
            if (source.resolve() != shared.resolve() and state.get('status') == 'cooldown'
                    and int(state.get('consecutive_429_count', 0)) >= MAX_CONSECUTIVE_429 - 1
                    and not cooldown_is_active(state, now) and not bounded_retry_is_authorized(state, now)):
                # Source and account describe the same recovery, not two independent lane credits.
                authorize_bounded_retry(shared, now)


@contextmanager
def group_submission_gate(run: Path, *, fair: bool = False):
    """Input: run Path/actual POST bool. Output: fence context; no quota, identity or retry authority.

    Ready means an active gate caller holding its lane OS lease. Cursor advances once per
    admission, not per payload child. Dead processes lose that lease without a PID/TTL guess.
    No intent lock is held while waiting for a fence, run lock, cooldown or network response.
    """
    from wqb.runtime_control import RuntimePaused
    run = Path(run).absolute()
    row = group_for_run(run)
    if row is None:
        yield
        return
    group = Path(row['group_dir'])
    if not fair:
        with json_lock_transition_guard(group / 'submission_fence',
                SUBMISSION_WAIT_SECONDS, SUBMISSION_POLL_SECONDS, 'group POST fence busy'):
            read_group(group)
            yield
        return
    revision = row['request_revision']
    token = uuid4().hex
    with json_lock_transition_guard(group / f'waiting_{run.name}',
            SUBMISSION_WAIT_SECONDS, SUBMISSION_POLL_SECONDS, 'lane POST admission busy'):
        try:
            with _guard(group):
                require_group_running(run)
                row = read_group(group)
                if row['request_revision'] != revision:
                    raise RuntimePaused('group POST admission revision changed')
                waiting = _live_submission_waiters(group, row, run.name)
                waiting[run.name] = dict(token=token, revision=revision)
                intent = _read(group / 'group_intent.json')
                _write(group / 'group_intent.json', {**intent, 'waiting_submissions': waiting})
            while True:
                require_group_running(run)
                if read_group(group)['request_revision'] != revision:
                    raise RuntimePaused('group POST admission revision changed')
                admitted = False
                try:
                    with json_lock_transition_guard(group / 'submission_fence', 0, 0, 'group POST fence busy'):
                        with json_lock_transition_guard(group / 'intent_guard', 0, 0, 'group intent busy'):
                            require_group_running(run)
                            row = read_group(group)
                            if row['request_revision'] != revision:
                                raise RuntimePaused('group POST admission revision changed')
                            waiting = _live_submission_waiters(group, row, run.name)
                            index = _ready_lane_index(row, waiting)
                            admitted = index is not None and row['lanes'][index]['run_id'] == run.name
                            intent = _read(group / 'group_intent.json')
                            if admitted:
                                waiting.pop(run.name)
                                intent['cursor'] = (index + 1) % len(row['lanes'])
                            if admitted or waiting != intent.get('waiting_submissions', {}):
                                _write(group / 'group_intent.json', {**intent, 'waiting_submissions': waiting})
                        if admitted:
                            yield
                            return
                except ValueError as error:
                    if admitted or str(error) not in {'group POST fence busy', 'group intent busy'}:
                        raise
                # Queue latency is not a failed POST. The group runtime deadline,
                # durable Stop and revision checks above bound this paced wait.
                time.sleep(SUBMISSION_POLL_SECONDS)
        finally:
            with _guard(group):
                intent = _read(group / 'group_intent.json')
                waiting = dict(intent.get('waiting_submissions', {}))
                if waiting.get(run.name, {}).get('token') == token:
                    waiting.pop(run.name)
                    _write(group / 'group_intent.json', {**intent, 'waiting_submissions': waiting})


def discover_group_lane(runs_root: Path, run: Path):
    """Input: owning runs root and explicit lane Paths. Output: existing WorkflowStateDiscovery; no pointer rewrite."""
    from wqb.workflow_state import WorkflowStateDiscovery, load_run_state, diagnose_state_consistency
    root, run = Path(runs_root).resolve(), Path(run).absolute()
    if run.parent != root or group_for_run(run) is None:
        raise ValueError('explicit lane must belong to its owning research group')
    state = load_run_state(run / 'run_state.json')
    if state.run_id != run.name or Path(state.run_dir).resolve() != run.resolve():
        raise ValueError('explicit lane state identity mismatch')
    return WorkflowStateDiscovery(state, run, state.run_id, diagnose_state_consistency(run, state))
