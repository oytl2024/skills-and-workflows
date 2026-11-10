"""Identity-bound IS observation windows, not reported end dates or research authority."""
from copy import deepcopy
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
import hashlib
import json
import math
import os
from pathlib import Path
import re
import time

import requests

from wqb.runtime_control import CONTROL_ENV, _write, check_submission_allowed, cooperative_sleep
from wqb.semantic_compilation import _safe


SCHEMA_VERSION = 1
METHOD = 'alpha_is_start_pnl_last_is_observation_v1'
MAX_ATTEMPTS = 3
MAX_SECONDS = 12.0
MAX_BYTES = 2_000_000
MAX_RECORDS = 100_000
PENDING_DELAY_SECONDS = 1.0
EVIDENCE_KEY = 'measurement_window_evidence'
RECEIPT_KEYS = {'schema_version', 'method', 'alpha_id', 'simulation_identity', 'period',
                'first_observation', 'last_observation', 'observations', 'os_start',
                'alpha_sha256', 'pnl_sha256', 'evidence_sha256',
                'reported_expression', 'reported_settings'}


def _bytes(value: object) -> bytes:
    """Input: JSON-compatible object. Output: canonical UTF-8 bytes; reject nonfinite JSON."""
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                      separators=(',', ':')).encode('utf-8')


def _hash(value: object) -> str:
    """Input: JSON-compatible object. Output: canonical JSON SHA-256 string."""
    return hashlib.sha256(_bytes(value)).hexdigest()


def _same_json(left: object, right: object) -> bool:
    """Input: two JSON values. Output: exact recursive equality, including numeric/bool types."""
    if type(left) is not type(right):
        return False
    if type(left) is dict:
        return (all(type(key) is str for key in left)
                and all(type(key) is str for key in right) and left.keys() == right.keys()
                and all(_same_json(left[key], right[key]) for key in left))
    if type(left) is list:
        return len(left) == len(right) and all(_same_json(a, b) for a, b in zip(left, right))
    return (type(left) in (str, int, float, bool, type(None)) and left == right
            and (type(left) is not float or math.isfinite(left)))


def _date(value: object) -> date:
    """Input: date candidate. Output: canonical ISO date, or ValueError; no inferred precision."""
    if type(value) is not str:
        raise ValueError('window date must be a canonical ISO string')
    parsed = date.fromisoformat(value)
    if parsed.isoformat() != value:
        raise ValueError('window date must be canonical YYYY-MM-DD')
    return parsed


def _alpha_parts(alpha_id: str, detail: dict) -> tuple[str, dict, dict]:
    """Input: Alpha ID/detail dict. Output: exact expression/settings/IS metrics, or ValueError."""
    if (type(alpha_id) is not str or re.fullmatch(r'[A-Za-z0-9_-]{1,128}', alpha_id) is None
            or type(detail) is not dict or detail.get('id') != alpha_id):
        raise ValueError('window Alpha identity is missing or conflicting')
    regular, settings, metrics = detail.get('regular'), detail.get('settings'), detail.get('is')
    if (type(regular) is not dict or type(regular.get('code')) is not str
            or not regular['code'].strip() or type(settings) is not dict or not settings
            or type(metrics) is not dict):
        raise ValueError('window requires actual regular expression, settings and IS metrics')
    if len(_bytes(detail)) > MAX_BYTES:
        raise ValueError('Alpha detail exceeds window evidence bound')
    _date(metrics.get('startDate'))
    return regular['code'], settings, metrics


def make_window_evidence(alpha_id: str, alpha_detail: dict, pnl_recordset: dict) -> dict:
    """Input: same Alpha ID/detail and actual PNL dict. Output: detached compact IS-window receipt.

    period.start is the reported IS start; period.end is the last observed IS
    trading date, not a fabricated is.endDate. Raw hashes use canonical JSON.
    OS dates are excluded only by that Alpha's explicit os.startDate.
    reported_expression/settings retain the full response; simulation_identity
    hashes those reported values, not an inferred or normalized submission.
    """
    from wqb.cli import simulation_identity_hash

    expression, settings, metrics = _alpha_parts(alpha_id, alpha_detail)
    if type(pnl_recordset) is not dict or len(_bytes(pnl_recordset)) > MAX_BYTES:
        raise ValueError('missing or oversized PNL recordset')
    schema, records = pnl_recordset.get('schema'), pnl_recordset.get('records')
    if type(schema) is not dict or schema.get('name') != 'pnl':
        raise ValueError('actual pnl schema required')
    properties = schema.get('properties')
    if (type(properties) is not list or not properties
            or any(type(item) is not dict or type(item.get('name')) is not str
                   or not item['name'] for item in properties)):
        raise ValueError('invalid PNL columns')
    names = [item['name'] for item in properties]
    if len(names) != len(set(names)) or names.count('date') != 1 or 'pnl' not in names:
        raise ValueError('PNL requires unique named columns including date and pnl')
    column = names.index('date')
    if properties[column].get('type') != 'date':
        raise ValueError('PNL date column requires explicit date type')
    if type(records) is not list or not 1 <= len(records) <= MAX_RECORDS:
        raise ValueError('PNL requires bounded nonempty records')
    start = _date(metrics['startDate'])
    os_metrics = alpha_detail.get('os')
    if os_metrics is not None and type(os_metrics) is not dict:
        raise ValueError('invalid OS metadata')
    os_start = os_metrics.get('startDate') if os_metrics else None
    cutoff = _date(os_start) if os_start is not None else None
    if cutoff is not None and cutoff <= start:
        raise ValueError('OS cutoff conflicts with IS start')
    observed, previous = [], None
    for record in records:
        if type(record) is not list or len(record) != len(properties):
            raise ValueError('PNL record width differs from schema')
        current = _date(record[column])
        if current < start or (previous is not None and current <= previous):
            raise ValueError('PNL dates precede IS start or are duplicated/unsorted')
        if record[names.index('pnl')] is None:
            raise ValueError('primary PNL observation is missing')
        for index, value in enumerate(record):
            if index != column and value is not None and (
                    type(value) not in (int, float) or not math.isfinite(value)):
                raise ValueError('PNL observations must be finite numeric values or null')
        previous = current
        if cutoff is None or current < cutoff:
            observed.append(current)
    if not observed:
        raise ValueError('PNL has no IS observations')
    last = observed[-1].isoformat()
    if 'endDate' in metrics and _date(metrics['endDate']).isoformat() != last:
        raise ValueError('reported IS end conflicts with observed IS endpoint')
    receipt = dict(schema_version=SCHEMA_VERSION, method=METHOD, alpha_id=alpha_id,
        simulation_identity=simulation_identity_hash(expression, settings),
        reported_expression=expression, reported_settings=deepcopy(settings),
        period=dict(start=start.isoformat(), end=last),
        first_observation=observed[0].isoformat(), last_observation=last,
        observations=len(observed), os_start=os_start,
        alpha_sha256=_hash(alpha_detail), pnl_sha256=_hash(pnl_recordset))
    receipt['evidence_sha256'] = _hash(receipt)
    return receipt


def verified_window_period(row: dict) -> dict | None:
    """Input: checked result dict. Output: copied verified receipt period or None, never plan dates.

    This validates compact metadata integrity/identity, not a global source or
    permission grant. The fetching owner verifies the raw-backed cache separately.
    The reported identity is checked against full reported expression/settings.
    The submitted expression must match exactly, and every submitted setting
    must exist in the response with identical JSON value AND type. Extra response
    settings remain evidence, never implicit submission defaults. Submitted scope
    requires nonempty region/universe and an explicit nonnegative integer delay.
    Optional row identity fields bind ORIGINAL submitted settings, not the full
    reported settings. No immutable identity is rewritten or normalized.
    """
    from wqb.cli import simulation_identity_hash

    try:
        if type(row) is not dict or type(row.get('metrics')) is not dict:
            return None
        metrics = row['metrics']
        receipt = metrics.get(EVIDENCE_KEY)
        if type(receipt) is not dict or set(receipt) != RECEIPT_KEYS:
            return None
        if (type(receipt['schema_version']) is not int or receipt['schema_version'] != SCHEMA_VERSION
                or receipt['method'] != METHOD or receipt['alpha_id'] != row.get('alpha_id')
                or re.fullmatch(r'[A-Za-z0-9_-]{1,128}', receipt['alpha_id']) is None):
            return None
        for key in ('simulation_identity', 'alpha_sha256', 'pnl_sha256', 'evidence_sha256'):
            if type(receipt[key]) is not str or re.fullmatch('[0-9a-f]{64}', receipt[key]) is None:
                return None
        unsigned = {key: value for key, value in receipt.items() if key != 'evidence_sha256'}
        if _hash(unsigned) != receipt['evidence_sha256']:
            return None
        expression, settings = row.get('expression'), row.get('settings')
        reported_expression, reported_settings = receipt['reported_expression'], receipt['reported_settings']
        if (type(expression) is not str or not expression.strip()
                or type(reported_expression) is not str or expression != reported_expression
                or type(settings) is not dict or not settings
                or type(reported_settings) is not dict or not reported_settings
                or not _same_json(reported_settings, reported_settings)
                or simulation_identity_hash(reported_expression, reported_settings) != receipt['simulation_identity']):
            return None
        if (any(type(settings.get(key)) is not str or not settings[key].strip()
                for key in ('region', 'universe'))
                or type(settings.get('delay')) is not int or settings['delay'] < 0
                or any(type(key) is not str or key not in reported_settings
                       or not _same_json(value, reported_settings[key]) for key, value in settings.items())):
            return None
        submitted_identity = simulation_identity_hash(expression, settings)
        for key in ('expression_hash', 'simulation_identity'):
            if key in row and row[key] != submitted_identity:
                return None
        period = receipt['period']
        if type(period) is not dict or set(period) != {'start', 'end'}:
            return None
        start, end = _date(period['start']), _date(period['end'])
        first, last = _date(receipt['first_observation']), _date(receipt['last_observation'])
        count = receipt['observations']
        if (not start <= first <= last == end or type(count) is not int
                or not 1 <= count <= min(MAX_RECORDS, (last - first).days + 1)
                or (first == last) != (count == 1)
                or _date(metrics.get('startDate')) != start):
            return None
        if receipt['os_start'] is not None and _date(receipt['os_start']) <= end:
            return None
        if 'endDate' in metrics and _date(metrics['endDate']) != end:
            return None
        return deepcopy(period)
    except (KeyError, TypeError, ValueError, OverflowError, RecursionError):
        return None


def _pending(alpha_id: str, reason: str) -> requests.RequestException:
    """Input: Alpha ID/reason strings. Output: recoverable error retaining the existing Alpha identity."""
    error = requests.RequestException('measurement window pending: ' + reason)
    error.alpha_id = alpha_id
    error.measurement_window_pending = True
    return error


def _cache_path(client, alpha_id: str) -> Path | None:
    """Input: client/validated Alpha ID. Output: link-guarded owner cache path or None.

    CONTROL_ENV takes precedence; run roots use runtime/measurement_windows.
    An explicit measurement_window_cache_root is already the cache directory.
    """
    owner = os.environ.get(CONTROL_ENV)
    explicit = getattr(client, 'measurement_window_cache_root', None)
    root = owner or explicit or getattr(client, 'metrics_run_dir', None)
    if not root:
        return None
    root = Path(root).absolute()
    if any(part.is_symlink() or (hasattr(part, 'is_junction') and part.is_junction())
           for part in (root, *root.parents)):
        raise ValueError('measurement cache root cannot traverse links')
    relative = alpha_id + '.json' if explicit and not owner else 'runtime/measurement_windows/' + alpha_id + '.json'
    return _safe(root, relative)


def _cached(path: Path, alpha_id: str, detail: dict) -> dict | None:
    """Input: safe cache path/current Alpha. Output: rebuilt receipt only for exact raw Alpha match."""
    if not path.exists():
        return None
    if path.stat().st_size > MAX_BYTES * 2 + 16_384:
        raise ValueError('measurement cache exceeds read bound')
    cached = json.loads(path.read_text(encoding='utf-8'))
    if type(cached) is not dict or set(cached) != {'alpha_detail', 'pnl_recordset', 'receipt'}:
        raise ValueError('invalid measurement cache envelope')
    receipt = make_window_evidence(alpha_id, cached['alpha_detail'], cached['pnl_recordset'])
    if receipt != cached['receipt']:
        raise ValueError('measurement cache raw/receipt integrity mismatch')
    return receipt if receipt['alpha_sha256'] == _hash(detail) else None


def _delay(value: str | None) -> float:
    """Input: Retry-After string or None. Output: bounded-by-caller wait seconds; support HTTP dates."""
    if value is None:
        return PENDING_DELAY_SECONDS
    try:
        seconds = float(value)
    except ValueError:
        parsed = parsedate_to_datetime(value)
        if parsed.tzinfo is None:
            raise ValueError('Retry-After HTTP date requires timezone')
        seconds = max(0.0, (parsed - datetime.now(timezone.utc)).total_seconds())
    if not math.isfinite(seconds) or seconds < 0:
        raise ValueError('invalid Retry-After')
    return seconds


def fetch_window_evidence(client, alpha_id: str, alpha_detail: dict) -> dict:
    """Input: existing client/Alpha detail. Output: verified receipt or recoverable RequestException.

    Caller alone opts in for new preplanned results lacking reported endDate.
    At most three logical PNL GETs use a local 12-second attempt/wait budget;
    this is NOT an end-to-end hard deadline. Client authentication/account checks,
    transport and cache I/O can outlast it. The 2MB body limit is checked after
    buffering, not a download cap. No research POST, correlation, model, global
    knowledge write or reported-metric mutation occurs; the existing client may
    authenticate independently under its own guards and configured limits.
    Cache holds one atomic private JSON with raw Alpha, raw PNL and receipt.
    """
    check_submission_allowed()
    deadline = time.monotonic() + MAX_SECONDS
    try:
        _alpha_parts(alpha_id, alpha_detail)
        path = _cache_path(client, alpha_id)
        if path is not None:
            receipt = _cached(path, alpha_id, alpha_detail)
            if receipt is not None:
                check_submission_allowed()
                return receipt
    except (OSError, ValueError, TypeError, OverflowError, RecursionError) as error:
        raise _pending(alpha_id, 'invalid Alpha or local cache') from error
    consumed = 0
    for attempt in range(MAX_ATTEMPTS):
        check_submission_allowed()
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise _pending(alpha_id, 'total deadline exhausted')
        timeout = min(MAX_SECONDS, remaining, getattr(client, 'timeout_seconds', MAX_SECONDS))
        if not math.isfinite(timeout) or timeout <= 0:
            raise _pending(alpha_id, 'invalid request timeout')
        wait = PENDING_DELAY_SECONDS
        try:
            response = client.request('GET', f'/alphas/{alpha_id}/recordsets/pnl',
                respect_retry_after=False, max_attempts=1, request_timeout_seconds=timeout)
        except (requests.Timeout, requests.ConnectionError) as error:
            if attempt == MAX_ATTEMPTS - 1:
                raise _pending(alpha_id, 'GET attempts exhausted') from error
        else:
            check_submission_allowed()
            if time.monotonic() >= deadline:
                raise _pending(alpha_id, 'GET exceeded total deadline')
            response.raise_for_status()
            body = response.content
            consumed += len(body)
            if consumed > MAX_BYTES:
                raise _pending(alpha_id, 'PNL response byte budget exceeded')
            retry_after = response.headers.get('Retry-After')
            try:
                if retry_after is None and body.strip():
                    recordset = json.loads(body)
                    receipt = make_window_evidence(alpha_id, alpha_detail, recordset)
                    if path is not None:
                        # Recheck link containment immediately before atomic publication.
                        checked_path = _cache_path(client, alpha_id)
                        if checked_path != path:
                            raise ValueError('measurement cache owner changed')
                        check_submission_allowed()
                        _write(path, dict(alpha_detail=deepcopy(alpha_detail),
                                          pnl_recordset=recordset, receipt=receipt))
                    return receipt
                wait = _delay(retry_after)
            except (OSError, ValueError, TypeError, OverflowError, RecursionError) as error:
                raise _pending(alpha_id, 'invalid PNL response or cache write') from error
        if attempt == MAX_ATTEMPTS - 1 or wait >= deadline - time.monotonic():
            raise _pending(alpha_id, 'PNL not ready within bounded attempts/deadline')
        cooperative_sleep(wait)
    raise _pending(alpha_id, 'PNL not ready')
