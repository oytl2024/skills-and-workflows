"""Bounded exact-scope acquisition; no research, semantic publication or submit authority."""
from __future__ import annotations

from datetime import date, datetime, timezone
import argparse
import hashlib
import json
import math
from pathlib import Path
import stat
import time
from urllib.parse import parse_qs, urlsplit

import requests

from wqb.client import BASE_URL, WQBClient
from wqb.data_field_capture import capture_platform_data_fields
from wqb.data_ledger_compile import compile_data_ledger_from_raw
from wqb.knowledge_age_policy import KNOWLEDGE_MAX_AGE_DAYS
from wqb.knowledge_paths import existing_machine_resource_path
from wqb.lockfile import exclusive_json_lock


DEFAULT_PREPARATION_POLICY = dict(request_limit=24, total_seconds=300,
    request_timeout_seconds=12, max_fields=100, max_datasets=2,
    max_fields_per_dataset=50, max_retries=0)
JOB_FILES = {'state.json', 'attempts.jsonl', 'completed.json', '.preparation.lock', '.preparation.lock.guard'}
JOB_FILES |= {'supervisor.json', 'worker_progress.json', 'scope_options.json', '.supervisor.lock', '.supervisor.lock.guard'}
CAPTURE_FILES = {'manifest.json', 'scopes.jsonl', 'data_sets.jsonl', 'data_fields.jsonl',
                 'operators.json', 'errors.jsonl', 'index.md'}


def validated_preparation_policy(value=None) -> dict:
    """Input: optional dict of reduced bounds. Output: dict; reject widening and retries."""
    if value is not None and (not isinstance(value, dict) or set(value) - DEFAULT_PREPARATION_POLICY.keys()):
        raise ValueError('invalid preparation policy keys')
    result = {**DEFAULT_PREPARATION_POLICY, **(value or {})}
    for key, cap in DEFAULT_PREPARATION_POLICY.items():
        number = result[key]
        if type(number) is not int or not (0 <= number <= cap if key == 'max_retries' else 1 <= number <= cap):
            raise ValueError('invalid preparation policy bound: ' + key)
    return result


def _now() -> str:
    """Input: none. Output: actual UTC timestamp str for source provenance."""
    return datetime.now(timezone.utc).isoformat()


def _digest(value: dict) -> str:
    """Input: JSON dict. Output: SHA256 str; detect altered checkpoint contents."""
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def _safe(path: Path) -> Path:
    """Input: Path. Output: absolute Path; reject symlinks, junctions and hardlinked files."""
    if '..' in path.parts:
        raise ValueError('path traversal is forbidden')
    path = path.absolute()
    for part in (path, *path.parents):
        if part.is_symlink():
            raise ValueError('links are not allowed: ' + str(part))
        if part.exists():
            info = part.lstat()
            if getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                raise ValueError('reparse paths are not allowed')
            if part.is_file() and info.st_nlink != 1:
                raise ValueError('hardlinked files are not allowed')
    return path


def _hash_file(path: Path) -> str:
    """Input: safe file Path. Output: streaming SHA256 str, without loading large raw sources."""
    digest = hashlib.sha256()
    with _safe(path).open('rb') as handle:
        for chunk in iter(lambda: handle.read(65536), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _save(path: Path, value: dict) -> None:
    """Input: Path/dict. Output: none; atomically record checksummed job state, never secrets."""
    temporary = _safe(path.with_suffix('.tmp'))
    _safe(path)
    with temporary.open('x', encoding='utf-8') as handle:
        json.dump(dict(payload=value, sha256=_digest(value)), handle, sort_keys=True, allow_nan=False)
        handle.flush()
        import os
        os.fsync(handle.fileno())
    temporary.replace(path)


def _load(path: Path) -> dict:
    """Input: checkpoint Path. Output: validated dict; incomplete/tampered records fail closed."""
    envelope = json.loads(_safe(path).read_text(encoding='utf-8'))
    if (not isinstance(envelope, dict) or set(envelope) != {'payload', 'sha256'}
            or not isinstance(envelope['payload'], dict) or _digest(envelope['payload']) != envelope['sha256']):
        raise ValueError('checkpoint digest changed/tampered')
    return envelope['payload']


def _lines(path: Path):
    """Input: JSONL Path. Output: dict iterator; stream rather than load the entire ledger."""
    if path.exists():
        with _safe(path).open(encoding='utf-8') as handle:
            for line in handle:
                if line.strip():
                    row = json.loads(line)
                    if not isinstance(row, dict):
                        raise ValueError('expected JSON object row')
                    yield row


def _scope(scope: dict) -> dict:
    """Input: parent-validated dict. Output: copied scope; reject malformed local calls, not eligibility."""
    if (not isinstance(scope, dict) or set(scope) - {'region', 'delay', 'universe', 'instrument_type'}
            or type(scope.get('delay')) is not int or scope['delay'] < 0
            or any(not isinstance(scope.get(k), str) or not scope[k] for k in ('region', 'universe'))
            or scope.get('instrument_type', 'EQUITY') != 'EQUITY'):
        raise ValueError('invalid exact scope')
    return dict(scope)


def _raw_evidence(root: Path, row: dict, scope: dict) -> dict | None:
    """Input: vault Path/ledger row/exact scope. Output: raw-certified reference or None; no semantics."""
    full_scope = {'instrument_type': 'EQUITY', **scope}
    for source in row.get('source_paths', []):
        if not isinstance(source, str):
            continue
        raw = _safe(root / source)
        if not raw.is_relative_to(root) or raw.name != 'data_fields.jsonl':
            continue
        if raw.relative_to(root).parts[:3] != ('raw', 'platform', 'data_fields') or not raw.is_file():
            continue
        manifest = raw.parent / 'manifest.json'
        if not manifest.exists():
            continue
        metadata = json.loads(_safe(manifest).read_text(encoding='utf-8'))
        if str(metadata.get('generated_at', ''))[:10] != row.get('source_updated_at'):
            continue
        latest = None
        for event in _lines(raw.parent / 'scopes.jsonl'):
            if event.get('scope') == full_scope:
                latest = event
        if not latest or latest.get('status') not in {'completed', 'partial'}:
            continue
        for observed in _lines(raw):
            field, dataset = observed.get('field', {}), observed.get('data_set', {})
            coverage = field.get('coverage')
            if (observed.get('scope') == full_scope and dataset.get('id') == row.get('dataset_id')
                    and field.get('id') == row.get('field_id') and field.get('type') == row.get('field_type')
                    and type(coverage) in (float, int) and math.isfinite(coverage) and coverage > 0
                    and coverage == row.get('coverage')
                    and observed.get('capture_generation_id') == latest.get('capture_generation_id')
                    and latest.get('capture_generation_id') == metadata.get('capture_generation_id')):
                return dict(path=str(raw), sha256=_hash_file(raw), field_id=field['id'],
                            dataset_id=dataset['id'], captured_at=metadata['generated_at'])
    return None


def _ready(root: Path, scope: dict, check_cancelled) -> dict | None:
    """Input: vault/scope/cancel callback. Output: first fresh measured typed positive field proof or None."""
    full_scope = {'instrument_type': 'EQUITY', **scope}
    ledger = _safe(existing_machine_resource_path(root, 'data_ledger'))
    for row in _lines(ledger):
        check_cancelled()
        if (row.get('coverage_status') != 'measured_raw' or row.get('source_quality') != 'platform_raw_capture'
                or row.get('field_type') not in {'MATRIX', 'VECTOR', 'GROUP'}
                or type(row.get('coverage')) not in (float, int) or not math.isfinite(row['coverage'])
                or row['coverage'] <= 0):
            continue
        scopes = row.get('available_scopes') or [{k: row.get(k) for k in full_scope}]
        if full_scope not in scopes:
            continue
        try:
            age = (datetime.now(timezone.utc).date() - date.fromisoformat(row['source_updated_at'])).days
        except (KeyError, TypeError, ValueError):
            continue
        if 0 <= age <= KNOWLEDGE_MAX_AGE_DAYS:
            proof = _raw_evidence(root, row, scope)
            if proof:
                return dict(ledger_path=str(ledger), source=proof)
    return None


class _Transport(requests.Session):
    def __init__(self, state, job, scope, check_cancelled, progress):
        """Input: durable state, Paths, scope/callbacks. Output: session guarding each adapter send."""
        super().__init__()
        self.trust_env = False
        self.state, self.job, self.scope = state, job, scope
        self.check_cancelled, self.progress = check_cancelled, progress
        self.failure = None

    def check(self):
        """Input: none. Output: none; enforce Stop, sticky errors and original wall deadline."""
        self.check_cancelled()
        if self.failure:
            raise RuntimeError(self.failure)
        remaining = self.state['deadline'] - time.time()
        if remaining <= 0 or time.time() < self.state['started']:
            raise RuntimeError('preparation deadline exhausted')
        return remaining

    def send(self, request, **kwargs):
        """Input: PreparedRequest/kwargs. Output: Response; reserve one actual attempt before transport."""
        remaining = self.check()
        parsed, base = urlsplit(request.url), urlsplit(BASE_URL)
        method = request.method.upper()
        allowed = ((method == 'POST' and parsed.path == '/authentication')
                   or (method == 'OPTIONS' and parsed.path == '/simulations')
                   or (method == 'GET' and parsed.path in {'/data-fields', '/data-sets', '/operators'}))
        if not allowed or parsed.scheme != base.scheme or parsed.netloc != base.netloc or parsed.fragment:
            raise ValueError('transport endpoint is not allowlisted')
        if parsed.path in {'/data-fields', '/data-sets'}:
            query = parse_qs(parsed.query)
            for key, value in dict(instrumentType='EQUITY', **self.scope).items():
                if key == 'instrument_type':
                    continue
                if query.get(key) != [str(value)]:
                    raise ValueError('transport exact scope mismatch')
        adapter = self.get_adapter(request.url)
        if getattr(adapter.max_retries, 'total', None) != 0:
            raise ValueError('hidden adapter retries are forbidden')
        count = self.state['requests_used']
        if count >= self.state['policy']['request_limit']:
            raise RuntimeError('preparation transport attempt budget exhausted')
        self.check_cancelled()
        entry = dict(attempt=count + 1, method=method, path=parsed.path,
                     at=time.time(), previous=self.state['attempt_digest'])
        encoded = json.dumps(entry, sort_keys=True)
        with _safe(self.job / 'attempts.jsonl').open('a', encoding='utf-8') as handle:
            handle.write(encoded + '\n')
            handle.flush()
            import os
            os.fsync(handle.fileno())
        self.state.update(requests_used=count + 1, attempt_digest=_digest(entry))
        _save(self.job / 'state.json', self.state)
        self.check_cancelled()
        self.progress(dict(stage='transport', requests_used=count + 1, field_count=0))
        kwargs['allow_redirects'] = False
        kwargs['timeout'] = min(self.state['policy']['request_timeout_seconds'], self.check())
        try:
            response = super().send(request, **kwargs)
        except Exception:
            self.check_cancelled()
            raise
        self.check()
        if response.status_code == 429 or response.status_code >= 500 or 300 <= response.status_code < 400:
            self.failure = 'preparation transport blocked: HTTP ' + str(response.status_code)
            raise RuntimeError(self.failure)
        return response


def _capture_refs(capture: Path) -> dict:
    """Input: isolated capture Path. Output: file digests; reject unexpected contents or links."""
    if {p.name for p in capture.iterdir()} - CAPTURE_FILES:
        raise ValueError('unexpected capture paths')
    return {p.name: _hash_file(p) for p in capture.iterdir()}


def _verify_refs(capture: Path, refs: dict):
    """Input: capture Path/recorded digests. Output: none; refuse changed capture evidence."""
    if _capture_refs(capture) != refs:
        raise ValueError('capture digest changed/tampered')


def prepare_multiplier_fields(knowledge_root: Path, job_dir: Path, scope: dict, *,
        check_cancelled: callable, progress: callable, policy: dict | None = None,
        client_factory=None, defer_shared_publication: bool = False) -> dict:
    """Input: vault/job Paths, validated scope, callbacks/bounds/factory. Output: resource receipt dict.

    Factory accepts WQBClient constructor keywords and must retain the supplied session.
    Parent owns Start CAS, readiness, event routing and any research/publication authority.
    An in-progress capture write/compiler may finish; Stop prevents the next phase/handoff.
    """
    check_cancelled()
    root, job = _safe(Path(knowledge_root)), _safe(Path(job_dir))
    scope, bounds = _scope(scope), validated_preparation_policy(policy)
    for relative in ('machine/data_ledger.jsonl', 'machine/freshness_manifest.json',
                     'machine/previews/data_ledger.md', 'machine/source_index.jsonl',
                     'raw/source_index.md', '.data_capture_compile.lock', '.data_capture_compile.lock.guard'):
        _safe(root / relative)
    if job.exists() and (not job.is_dir() or any(_safe(p).name not in JOB_FILES or not p.is_file() for p in job.iterdir())):
        raise ValueError('unexpected preparation job paths')
    check_cancelled()
    job.mkdir(parents=True, exist_ok=True)
    check_cancelled()
    with exclusive_json_lock(job / '.preparation.lock', 1, 0.05, 3600, 'preparation job is busy'):
        return _prepare(root, job, scope, bounds, check_cancelled, progress, client_factory, defer_shared_publication)


def _prepare(root, job, scope, bounds, check_cancelled, progress, client_factory, defer_shared_publication):
    """Input: safe Paths, scope/bounds/callbacks/factory. Output: guarded exact preparation receipt dict."""
    from wqb.multiplier_scope import compile_scope_choices, publish_scope_catalog, read_scope_catalog

    state_path = job / 'state.json'
    capture_id = hashlib.sha256(str(job).encode()).hexdigest()[:32]
    if state_path.exists():
        state = _load(state_path)
        if state['scope'] != scope or state['policy'] != bounds or state['knowledge_root'] != str(root):
            raise ValueError('preparation scope/root/policy cannot change on resume')
        if (state['capture_id'] != capture_id or type(state['requests_used']) is not int
                or not 0 <= state['requests_used'] <= bounds['request_limit']
                or type(state['started']) not in (int, float) or not math.isfinite(state['started'])
                or state['deadline'] != state['started'] + bounds['total_seconds']):
            raise ValueError('preparation state identity/bounds changed')
    else:
        if (job / 'attempts.jsonl').exists() or (job / 'completed.json').exists():
            raise ValueError('missing preparation state with existing evidence')
        started = time.time()
        state = dict(scope=scope, policy=bounds, knowledge_root=str(root), started=started,
                     deadline=started + bounds['total_seconds'], generated_at=_now(),
                     capture_id=capture_id, requests_used=0, attempt_digest='', capture=None)
        check_cancelled()
        _save(state_path, state)
    previous, count = '', 0
    for entry in _lines(job / 'attempts.jsonl'):
        count += 1
        if entry.get('attempt') != count or entry.get('previous') != previous:
            raise ValueError('attempt journal changed/tampered')
        previous = _digest(entry)
    if count != state['requests_used'] or previous != state['attempt_digest']:
        raise ValueError('attempt journal digest changed/tampered')
    capture = _safe(root / 'raw/platform/data_fields' / (state['generated_at'][:10] + '-' + capture_id))
    if state.get('capture'):
        _verify_refs(capture, state['capture_refs'])
    elif capture.exists() and any(_lines(capture / 'data_fields.jsonl')):
        # The existing sampler cannot resume a partly observed generation losslessly.
        # Preserve it for the parent's maintenance outbox instead of appending duplicates.
        if state.get('partial_refs'):
            _verify_refs(capture, state['partial_refs'])
        raise RuntimeError('partial field capture preserved; lossless recovery requires maintenance')
    completed = _load(job / 'completed.json') if (job / 'completed.json').exists() else None
    if completed and (completed.get('scope') != scope or completed.get('status') != 'completed'
            or completed.get('requests_used') != state['requests_used']
            or type(completed.get('field_count')) is not int
            or not 1 <= completed['field_count'] <= bounds['max_fields']
            or completed.get('capture') != state.get('capture')):
        raise ValueError('completed receipt differs from original preparation identity')
    ready = _ready(root, scope, check_cancelled)
    try:
        catalog = read_scope_catalog(root)
        catalog_fresh = catalog['stale'] is False and {k: scope[k] for k in ('region', 'delay', 'universe')} in catalog['scopes']
    except FileNotFoundError:
        catalog_fresh = False
    except ValueError:
        if _safe(root / 'machine/multiplier_scope_catalog.json').exists():
            raise
        catalog_fresh = False
    if completed and ready and catalog_fresh:
        if completed.get('provenance') != ready or completed.get('compile', {}).get('ledger_path') != ready['ledger_path']:
            raise ValueError('completed receipt provenance changed')
        check_cancelled()
        return {**completed, 'reused': True}
    need_capture = ready is None and state.get('capture') is None
    transport = _Transport(state, job, scope, check_cancelled, progress)
    try:
        if need_capture or not catalog_fresh:
            transport.check()
            check_cancelled()
            client = (client_factory or WQBClient)(session=transport,
                timeout_seconds=bounds['request_timeout_seconds'], max_retries=0)
            if client.session is not transport or client.max_retries != 0:
                raise ValueError('client factory must retain guarded session and zero retries')
            check_cancelled()
            response = client.request('OPTIONS', '/simulations', respect_retry_after=False)
            response.raise_for_status()
            payload = response.json()
            check_cancelled()
            choices = compile_scope_choices(payload, instrument_type='EQUITY')
            if {k: scope[k] for k in ('region', 'delay', 'universe')} not in choices:
                raise ValueError('selected scope absent from fresh official settings')
            check_cancelled()
            if defer_shared_publication:
                _save(job / 'scope_options.json', dict(payload=payload, captured_at=_now()))
            else:
                publish_scope_catalog(root, payload, _now())
            check_cancelled()
        if need_capture:
            check_cancelled()
            progress(dict(stage='capture', requests_used=state['requests_used'], field_count=0))
            check_cancelled()
            summary = capture_platform_data_fields(client, root, generated_at=state['generated_at'],
                instrument_types=['EQUITY'], regions=[scope['region']], delays=[scope['delay']],
                universes=[scope['universe']], max_scopes=1,
                max_datasets_per_scope=bounds['max_datasets'],
                max_fields_per_dataset=bounds['max_fields_per_dataset'],
                fields_per_scope=bounds['max_fields'], resume_capture=True, capture_id=capture_id,
                publish_source_index=not defer_shared_publication)
            # Finishing phase evidence is allowed after Stop; compilation/handoff is not.
            if summary['status'] == 'completed' and 0 < summary['field_count'] <= bounds['max_fields']:
                state.update(capture=summary, capture_refs=_capture_refs(capture))
                _save(state_path, state)
            elif summary['field_count']:
                state['partial_refs'] = _capture_refs(capture)
                _save(state_path, state)
            transport.check()
            if state['capture'] is None:
                raise RuntimeError('bounded field capture incomplete; preserve partial evidence')
        if defer_shared_publication:
            return dict(status='staged', scope=scope, requests_used=state['requests_used'])
        compiled = None
        if ready is None:
            transport.check()
            check_cancelled()
            progress(dict(stage='compile', requests_used=state['requests_used'],
                          field_count=state['capture']['field_count']))
            check_cancelled()
            compiled = compile_data_ledger_from_raw(root, capture_dir=capture)
            transport.check()
            ready = _ready(root, scope, check_cancelled)
            if ready is None:
                raise RuntimeError('compiled capture lacks fresh raw-certified positive typed exact-scope fields')
        transport.check()
        receipt = dict(status='completed', scope=scope, reused=not need_capture,
            field_count=state['capture']['field_count'] if state.get('capture') else 1,
            requests_used=state['requests_used'], provenance=ready,
            capture=state.get('capture'), compile=compiled or {'ledger_path': ready['ledger_path']})
        check_cancelled()
        _save(job / 'completed.json', receipt)
        check_cancelled()
        progress(dict(stage='completed', field_count=receipt['field_count'], requests_used=state['requests_used']))
        check_cancelled()
        return receipt
    finally:
        transport.close()


def main() -> None:
    """Input: explicit maintenance CLI arguments. Output: printed receipt; never starts research."""
    parser = argparse.ArgumentParser(description='Explicit bounded exact-scope field maintenance')
    parser.add_argument('--knowledge-root', type=Path, required=True)
    parser.add_argument('--job-dir', type=Path, required=True)
    parser.add_argument('--region', required=True)
    parser.add_argument('--delay', required=True, type=int)
    parser.add_argument('--universe', required=True)
    for name, default in DEFAULT_PREPARATION_POLICY.items():
        parser.add_argument('--' + name.replace('_', '-'), type=int, default=default)
    args = parser.parse_args()
    from wqb.multiplier_supervision import prepare_multiplier_fields_supervised
    receipt = prepare_multiplier_fields_supervised(args.knowledge_root, args.job_dir,
        dict(region=args.region, delay=args.delay, universe=args.universe),
        policy={key: getattr(args, key) for key in DEFAULT_PREPARATION_POLICY},
        check_cancelled=lambda: None, progress=lambda row: print(json.dumps(row), flush=True))
    print(json.dumps(receipt, sort_keys=True))


if __name__ == '__main__':
    main()
