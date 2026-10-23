"""Workspace-shared local submission allowance; never platform quota or Start authority."""

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from uuid import uuid4

from wqb.lockfile import json_lock_transition_guard
from wqb.runtime_control import _read, _write


DAILY_SIMULATION_LIMIT = 4000
BUDGET_TIMEZONE = 'Asia/Shanghai'
SHANGHAI = timezone(timedelta(hours=8), BUDGET_TIMEZONE)
BUDGET_SCHEMA_VERSION = 1
BUDGET_LOCK_SECONDS = 10.0
BUDGET_LOCK_SLEEP = 0.02
STORE_NAME = 'daily_simulation_budget'


class DailyBudgetUnavailable(RuntimeError):
    """A complete new submission cannot fit; existing identities remain recoverable."""

    def __init__(self, budget: dict):
        """Input: validated budget dict. Output: exception. Carry the next safe local reset time."""
        super().__init__('daily simulation allowance exhausted')
        self.budget = budget


def _digest(row: dict) -> str:
    """Input: JSON object dict. Output: SHA256 str. Bind complete canonical accounting bytes."""
    return hashlib.sha256(json.dumps(row, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def _safe(path: Path) -> Path:
    """Input: Path. Output: absolute Path. Refuse links/junctions before local budget access."""
    path = path.absolute()
    for parent in (path, *path.parents):
        if parent.is_symlink() or parent.is_junction():
            raise ValueError('linked daily budget path refused')
    return path


def _store(runs_root: Path) -> Path:
    """Input: canonical runs Path. Output: shared store Path. Keep accounting out of source subruns."""
    return _safe(_safe(runs_root) / STORE_NAME)


def _clock(now: str | None) -> datetime:
    """Input: optional timezone-aware ISO str. Output: Shanghai datetime. Accept an injectable offline clock."""
    value = datetime.fromisoformat(now.replace('Z', '+00:00')) if now else datetime.now(timezone.utc)
    if value.tzinfo is None:
        raise ValueError('daily budget clock requires timezone')
    return value.astimezone(SHANGHAI)


def _nonnegative(value) -> bool:
    """Input: arbitrary value. Output: bool. Reject booleans/coercions in resource accounting."""
    return type(value) is int and value >= 0


def _save(root: Path, ledger: dict) -> None:
    """Input: store Path and ledger dict. Output: None. Seal and atomically commit one authoritative snapshot."""
    row = dict(ledger)
    row.pop('content_sha256', None)
    row['content_sha256'] = _digest(row)
    _write(_safe(root / 'ledger.json'), row)


def _load(root: Path) -> tuple[dict, dict]:
    """Input: store Path. Output: policy/ledger dicts. Fail closed on lost, conflicting or corrupt state."""
    policy = _read(_safe(root / 'policy.json'))
    fields = {'schema_version', 'limit', 'timezone', 'runs_root'}
    if (set(policy) != fields | {'policy_id'} or policy.get('schema_version') != BUDGET_SCHEMA_VERSION
            or not _nonnegative(policy.get('limit')) or policy['limit'] < 1
            or policy.get('timezone') != BUDGET_TIMEZONE
            or policy.get('runs_root') != str(root.parent)
            or policy.get('policy_id') != _digest({key: policy[key] for key in fields})):
        raise ValueError('invalid or missing daily budget policy')
    row = _read(_safe(root / 'ledger.json'))
    sealed = dict(row)
    seal = sealed.pop('content_sha256', None)
    required = {'schema_version', 'policy_id', 'budget_date', 'used', 'charges', 'run_totals', 'baselines', 'archives'}
    if (set(sealed) != required or row.get('policy_id') != policy['policy_id']
            or row.get('schema_version') != BUDGET_SCHEMA_VERSION or seal != _digest(sealed)
            or not _nonnegative(row.get('used'))
            or any(not isinstance(row.get(key), dict) for key in ('charges', 'run_totals', 'baselines', 'archives'))
            or any(not _nonnegative(v) for v in row['run_totals'].values())):
        raise ValueError('invalid or missing daily budget ledger')
    if row['budget_date'] is not None:
        datetime.strptime(row['budget_date'], '%Y-%m-%d')
    charged = 0
    for item in row['charges'].values():
        if (not isinstance(item, dict) or set(item) != {'run_id', 'count'}
                or not isinstance(item['run_id'], str) or not _nonnegative(item['count']) or item['count'] == 0):
            raise ValueError('invalid daily charge receipt')
        charged += item['count']
    for item in row['baselines'].values():
        if not isinstance(item, dict) or not _nonnegative(item.get('count')) or not isinstance(item.get('date'), str):
            raise ValueError('invalid daily migration baseline')
        if item['date'] == row['budget_date']:
            charged += item['count']
    if charged != row['used']:
        raise ValueError('daily charge total differs from receipts')
    for day, digest in row['archives'].items():
        if not isinstance(day, str) or datetime.strptime(day, '%Y-%m-%d').date().isoformat() != day:
            raise ValueError('invalid daily archive date')
        archived = _read(_safe(root / 'archive' / (day + '.json')))
        if not archived or _digest(archived) != digest:
            raise ValueError('missing or corrupt daily archive')
    return policy, row


def policy_transition_gate(runs_root: Path):
    """Input: canonical runs Path. Output: OS lock context. Serialize policy establishment with every managed accounting route."""
    root = _store(runs_root)
    return json_lock_transition_guard(root.parent / (STORE_NAME + '.route'), BUDGET_LOCK_SECONDS,
                                     BUDGET_LOCK_SLEEP, 'daily policy transition busy')


def ensure_daily_policy(runs_root: Path) -> dict:
    """Input: runs Path. Output: policy dict. Establish the shared policy without racing another run's legacy charge."""
    with policy_transition_gate(runs_root):
        return _ensure_daily_policy_locked(runs_root)


def _ensure_daily_policy_locked(runs_root: Path) -> dict:
    """Input: runs Path. Output: policy dict. Initialize only a fresh store, never replace established evidence."""
    root = _store(runs_root)
    established = _safe(root.parent / (STORE_NAME + '.init.guard')).exists()
    with json_lock_transition_guard(root.parent / (STORE_NAME + '.init'), BUDGET_LOCK_SECONDS,
                                    BUDGET_LOCK_SLEEP, 'daily policy busy'):
        if root.exists():
            return _load(root)[0]
        if established:
            raise ValueError('established daily budget store is missing')
        policy = dict(schema_version=BUDGET_SCHEMA_VERSION, limit=DAILY_SIMULATION_LIMIT,
                      timezone=BUDGET_TIMEZONE, runs_root=str(root.parent))
        policy['policy_id'] = _digest(policy)
        _write(_safe(root / 'policy.json'), policy)
        _save(root, dict(schema_version=BUDGET_SCHEMA_VERSION, policy_id=policy['policy_id'],
            budget_date=None, used=0, charges={}, run_totals={}, baselines={}, archives={}))
        return policy


def _snapshot(policy: dict, ledger: dict, run: Path, now: str | None) -> dict:
    """Input: policy/ledger dicts, run Path, ISO clock. Output: readonly daily balance and lifetime projection."""
    clock = _clock(now)
    day = clock.date().isoformat()
    if ledger['budget_date'] and day < ledger['budget_date']:
        raise ValueError('daily budget clock moved backwards')
    used = ledger['used'] if ledger['budget_date'] == day else 0
    midnight = datetime.combine(clock.date() + timedelta(days=1), datetime.min.time(), SHANGHAI)
    status = _read(run / 'runtime_status.json')
    recorded = status.get('simulation_attempts', 0)
    if not _nonnegative(recorded):
        raise ValueError('invalid lifetime submission count')
    return dict(mode='daily', budget_date=day, timezone=BUDGET_TIMEZONE,
        limit=policy['limit'], used=used, remaining=max(0, policy['limit'] - used),
        next_reset_at=midnight.astimezone(timezone.utc).isoformat(),
        lifetime_attempts=max(recorded, ledger['run_totals'].get(run.name, 0)), policy_id=policy['policy_id'])


def read_daily_budget(run_dir: Path, now: str | None = None) -> dict:
    """Input: owning run Path and optional ISO clock. Output: budget dict. Read complete atomic files without writes."""
    run = _safe(run_dir)
    policy, ledger = _load(_store(run.parent))
    control = _read(run / 'runtime_control.json')
    if control.get('simulation_budget_mode') == 'daily':
        baseline = ledger['baselines'].get(run.name, {})
        if (control.get('daily_budget_policy_id') != policy['policy_id']
                or not control.get('daily_budget_activation_id')
                or control.get('daily_budget_activation_id') != baseline.get('activation_id')):
            raise ValueError('daily budget activation does not match owning run')
    return _snapshot(policy, ledger, run, now)


def _archive(root: Path, ledger: dict) -> None:
    """Input: store Path/ledger dict. Output: None. Retain a complete immutable day before rollover."""
    day = ledger['budget_date']
    if not day:
        return
    path = _safe(root / 'archive' / (day + '.json'))
    if path.exists():
        if _read(path) != ledger:
            raise ValueError('daily archive conflicts with rollover evidence')
    else:
        _write(path, ledger)


def _rollover(root: Path, ledger: dict, day: str) -> dict:
    """Input: store Path, validated ledger dict/new day str. Output: current mutable ledger. Archive before replacing."""
    if ledger['budget_date'] == day:
        return ledger
    if ledger['budget_date'] and day < ledger['budget_date']:
        raise ValueError('daily budget clock moved backwards')
    _archive(root, ledger)
    if ledger['budget_date']:
        ledger['archives'][ledger['budget_date']] = _digest(ledger)
    ledger.update(budget_date=day, used=0, charges={})
    return ledger


def _existing_charge(root: Path, ledger: dict, charge_id: str) -> dict | None:
    """Input: store/ledger/id. Output: receipt dict or None. Resolve dated IDs directly, retaining opaque test/client replay."""
    if charge_id in ledger['charges']:
        return ledger['charges'][charge_id]
    prefix = charge_id.partition(':')[0]
    dates = [prefix] if prefix in ledger['archives'] else ledger['archives']
    for day in dates:
        previous = _read(_safe(root / 'archive' / (day + '.json')))
        if _digest(previous) != ledger['archives'][day]:
            raise ValueError('missing or corrupt daily archive')
        if charge_id in previous.get('charges', {}):
            return previous['charges'][charge_id]
    return None


def charge_daily_budget(run_dir: Path, count: int, charge_id: str | None = None, now: str | None = None) -> dict:
    """Input: run Path/count int/optional replay ID/ISO clock. Output: budget dict. Assign production IDs inside the atomic day boundary."""
    if not _nonnegative(count) or count == 0 or (charge_id is not None and (
            not isinstance(charge_id, str) or not charge_id or len(charge_id) > 128)):
        raise ValueError('positive count and bounded charge identity required')
    run = _safe(run_dir)
    root = _store(run.parent)
    with json_lock_transition_guard(root.parent / (STORE_NAME + '.charge'), BUDGET_LOCK_SECONDS,
                                    BUDGET_LOCK_SLEEP, 'daily budget busy'):
        policy, ledger = _load(root)
        result = _snapshot(policy, ledger, run, now)
        if charge_id is None:
            charge_id = result['budget_date'] + ':' + uuid4().hex
        previous = _existing_charge(root, ledger, charge_id)
        receipt = dict(run_id=run.name, count=count)
        if previous:
            if previous != receipt:
                raise ValueError('conflicting daily charge replay')
            return result
        prefix = charge_id.partition(':')[0]
        try:
            dated = datetime.strptime(prefix, '%Y-%m-%d').date().isoformat() == prefix
        except ValueError:
            dated = False
        if dated and prefix != result['budget_date']:
            raise ValueError('new dated charge must match its storage day')
        control = _read(run / 'runtime_control.json')
        if control and control.get('simulation_budget_mode') != 'daily':
            from wqb.runtime_control import RuntimePaused
            limit = control.get('max_simulations')
            if not _nonnegative(limit) or result['lifetime_attempts'] + count > limit:
                raise RuntimePaused('simulation attempt budget exhausted')
        if count > result['remaining']:
            raise DailyBudgetUnavailable({**result, 'required_count': count})
        ledger = _rollover(root, ledger, result['budget_date'])
        ledger['run_totals'][run.name] = result['lifetime_attempts'] + count
        ledger['charges'][charge_id] = receipt
        ledger['used'] += count
        _save(root, ledger)
        return _snapshot(policy, ledger, run, now)


def reconcile_lifetime_attempts(run_dir: Path) -> int:
    """Input: owning run Path. Output: int. Rebuild its lifetime projection without charging or submitting."""
    from wqb.runtime_control import update_runtime_status
    run = _safe(run_dir)
    root = _store(run.parent)
    with json_lock_transition_guard(root.parent / (STORE_NAME + '.charge'), BUDGET_LOCK_SECONDS,
                                    BUDGET_LOCK_SLEEP, 'daily budget projection busy'):
        _, ledger = _load(root)
        status = _read(run / 'runtime_status.json')
        previous = status.get('simulation_attempts', 0)
        if not _nonnegative(previous):
            raise ValueError('invalid lifetime submission count')
        count = max(previous, ledger['run_totals'].get(run.name, 0))
        update_runtime_status(run, simulation_attempts=count)
        return count


def has_shared_policy(run_dir: Path) -> bool:
    """Input: owning run Path. Output: bool. An established incomplete store must not silently fall back to legacy."""
    root = _store(_safe(run_dir).parent)
    return root.exists() or _safe(root.parent / (STORE_NAME + '.init.guard')).exists()


def remaining_submission_allowance(run_dir: Path, now: str | None = None) -> int:
    """Input: owning run Path and ISO clock. Output: nonnegative int. Combine daily and any stricter legacy authority."""
    from wqb.runtime_control import read_runtime_control
    run = _safe(run_dir)
    control = read_runtime_control(run)
    if control.get('invalid'):
        raise ValueError('invalid submission budget authority')
    if control.get('simulation_budget_mode') == 'daily':
        return read_daily_budget(run, now)['remaining']
    limit, used = control.get('max_simulations'), control.get('simulation_attempts', 0)
    if not _nonnegative(limit) or not _nonnegative(used):
        raise ValueError('invalid legacy submission budget')
    remaining = max(0, limit - used)
    if has_shared_policy(run):
        daily = read_daily_budget(run, now)
        remaining = min(remaining, max(0, limit - daily['lifetime_attempts']), daily['remaining'])
    return remaining


def activate_daily_policy(run_dir: Path, expected_revision: str, confirmation_reference: str,
                          now: str | None = None) -> dict:
    """Input: run/revision/confirmation/clock. Output: control dict. Serialize migration against all run accounting."""
    run = _safe(run_dir)
    with json_lock_transition_guard(run / 'runtime/submission_accounting', BUDGET_LOCK_SECONDS,
                                   BUDGET_LOCK_SLEEP, 'daily activation accounting busy'):
        return _activate_daily_policy_locked(run, expected_revision, confirmation_reference, now)


def _activate_daily_policy_locked(run_dir: Path, expected_revision: str, confirmation_reference: str,
                          now: str | None = None) -> dict:
    """Input: owning run Path/revision/human reference/ISO clock. Output: control dict. Activate locally without Start or quota refund."""
    from wqb.runtime_control import read_runtime_control, runtime_authority_is_complete
    from wqb.recovery_cases import read_current_recovery_case, MAINTENANCE_BLOCKING_STATUSES
    if not expected_revision or not confirmation_reference.strip() or len(confirmation_reference) > 256:
        raise ValueError('explicit bounded confirmation and runtime revision required')
    run = _safe(run_dir)
    receipt_path = _safe(run / 'runtime/daily_budget_activation.json')
    with json_lock_transition_guard(run / 'runtime/control_intent', BUDGET_LOCK_SECONDS,
                                    BUDGET_LOCK_SLEEP, 'daily activation busy'):
        control = _read(run / 'runtime_control.json')
        receipt = _read(receipt_path)
        if control.get('simulation_budget_mode') == 'daily':
            if (receipt.get('expected_revision') != expected_revision
                    or receipt.get('request_revision') != control.get('request_revision')
                    or receipt.get('confirmation_reference') != confirmation_reference):
                raise ValueError('stale daily activation; newer intent exists')
            read_daily_budget(run, now)
            if receipt.get('status') not in {'authorized', 'applied'}:
                raise ValueError('invalid daily activation receipt status')
            if receipt['status'] == 'authorized':
                _write(receipt_path, dict(receipt, status='applied'))
            return read_runtime_control(run)
        if (not runtime_authority_is_complete(control) or control.get('request_revision') != expected_revision
                or control.get('original_batch_scope_id') or (run / 'runtime/original_batch_scope.json').exists()
                or _read(run / 'run_manifest.json').get('run_id') != run.name):
            raise ValueError('stale, restricted or unowned daily activation')
        if read_current_recovery_case(run).get('status') in MAINTENANCE_BLOCKING_STATUSES:
            raise ValueError('maintenance verification required before activation')
        if not _nonnegative(_read(run / 'runtime_status.json').get('simulation_attempts')):
            raise ValueError('historical simulation usage must be known before daily activation')
        policy = ensure_daily_policy(run.parent)
        if not receipt:
            receipt = dict(expected_revision=expected_revision, request_revision=uuid4().hex,
                confirmation_reference=confirmation_reference, activation_id=uuid4().hex,
                policy_id=policy['policy_id'], status='authorized', authorized_at=_clock(now).isoformat())
            _write(receipt_path, receipt)
        if (receipt.get('expected_revision') != expected_revision
                or receipt.get('confirmation_reference') != confirmation_reference
                or receipt.get('policy_id') != policy['policy_id']):
            raise ValueError('conflicting pending daily activation')
        root = _store(run.parent)
        with json_lock_transition_guard(root.parent / (STORE_NAME + '.charge'), BUDGET_LOCK_SECONDS,
                                        BUDGET_LOCK_SLEEP, 'daily migration busy'):
            policy, ledger = _load(root)
            snapshot = _snapshot(policy, ledger, run, now)
            baseline = ledger['baselines'].get(run.name)
            if baseline and baseline.get('activation_id') != receipt['activation_id']:
                raise ValueError('conflicting daily migration baseline')
            if not baseline:
                ledger = _rollover(root, ledger, snapshot['budget_date'])
                accounted = sum(c['count'] for c in ledger['charges'].values() if c['run_id'] == run.name)
                carried = max(0, snapshot['lifetime_attempts'] - accounted)
                ledger['baselines'][run.name] = dict(count=carried, date=snapshot['budget_date'],
                    activation_id=receipt['activation_id'], classification='conservative_legacy_carryforward')
                ledger['used'] += carried
                ledger['run_totals'][run.name] = snapshot['lifetime_attempts']
                _save(root, ledger)
        updated = dict(control, simulation_budget_mode='daily', daily_budget_policy_id=policy['policy_id'],
            daily_budget_activation_id=receipt['activation_id'], request_revision=receipt['request_revision'],
            requested_at=receipt['authorized_at'])
        _write(run / 'runtime_control.json', updated)
        _write(receipt_path, dict(receipt, status='applied'))
        return read_runtime_control(run)


def main() -> None:
    """Input: local maintenance CLI args. Output: stdout JSON. Activate only; never create a worker or call WQB."""
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['activate'])
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--expected-revision', required=True)
    parser.add_argument('--confirmation-reference', required=True)
    args = parser.parse_args()
    row = activate_daily_policy(args.run_dir, args.expected_revision, args.confirmation_reference)
    print(json.dumps({key: row.get(key) for key in ('request_revision', 'simulation_budget_mode', 'daily_simulation_budget')}))


if __name__ == '__main__':
    main()
