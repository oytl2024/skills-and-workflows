"""Bounded retirement of unexecuted knowledge plans; never research authority.

Intent publication makes a plan read-only. Lossless bytes live once in the new
shared store; only explicitly approved, identity-verified legacy copies can be
collected. Audit remains read-only and never itself grants collection authority.
"""

import os
import hashlib
from pathlib import Path
import re
from contextlib import ExitStack

from wqb.full_semantic_compile import _bytes, _digest, _hash, _json, inventory_reference_base
from wqb.knowledge_clean_compile import _safe_local_path


MAX_AUDIT_BYTES = 16 * 1024 * 1024
MAX_INVENTORY_LINE_BYTES = 16 * 1024 * 1024
MAX_INVENTORY_TARGETS = 1_000_000
MAX_JOB_CHECKS = 4096
MAX_OWNER_ENTRIES = 8
RETIREMENT_SCAN_BYTES = 2 * 1024**3
RETIREMENT_SCAN_SECONDS = 180.0
LIFECYCLE_LOCK_SECONDS = 1.0
LIFECYCLE_VERSION = 1
PLAN_PATH = re.compile(r'machine/semantic_jobs/[a-f0-9]{64}/plan\.json\Z')
RETIREMENT_MARKER = 'retirement.json'
HASH = re.compile(r'[a-f0-9]{64}\Z')
INTENT_KEYS = {'schema_version', 'kind', 'root', 'plan_ref', 'inventory_ref',
               'replacement_ref', 'archive_ref', 'inventory_counts', 'coverage_proof', 'source_digest'}


def _stamp(path: Path) -> tuple:
    """Input: Path. Output: file identity/size/time tuple for advisory race detection."""
    info = path.stat()
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def _inventory(root: Path, plan: dict, *, archive_ref=None, scopes=None) -> dict:
    """Input: vault Path/bound plan dict. Output: streamed hash/counts; keep IDs, never raw rows.

    Matches coverage's streaming digest/unique target/assignment checks, adding
    schema, per-job assignments and measured coverage counts. Memory is bounded
    by one row plus MAX_INVENTORY_TARGETS compact IDs and the bounded plan.
    """
    assigned = {}
    jobs = set()
    version = plan['identity'].get('inventory_format_version', 1)
    if type(version) is not int or version not in (1, 2, 3) or not isinstance(plan['jobs'], list):
        raise ValueError('unsupported_inventory_schema')
    for job in plan['jobs']:
        key = job['job_id']
        if (not isinstance(key, str) or not HASH.fullmatch(key) or key in jobs
                or job['path'] != 'machine/semantic_jobs/' + key + '/run_manifest.json'
                or not isinstance(job['target_ids'], list) or not job['target_ids']
                or any(not isinstance(job[name], str) or not HASH.fullmatch(job[name])
                       for name in ('sha256', 'input_sha256', 'brief_sha256'))):
            raise ValueError('invalid_job_identity')
        jobs.add(key)
        for tid in job['target_ids']:
            if not isinstance(tid, str) or tid in assigned:
                raise ValueError('duplicate_job_target')
            assigned[tid] = key
    path = _path(root, archive_ref['path'] if archive_ref else plan['inventory_ref']['path'])
    before = _stamp(path)
    counts = dict(target_count=0, prepared_targets=0, blocked_targets=0, source_validated_targets=0)
    digest, ids = hashlib.sha256(), set()
    if archive_ref is None:
        stream = path.open('rb')
    else:
        from wqb.semantic_inventory_archive import open_verified_inventory_archive
        stream = open_verified_inventory_archive(root, archive_ref)
    with stream:
        while raw := stream.readline(MAX_INVENTORY_LINE_BYTES + 1):
            if len(raw) > MAX_INVENTORY_LINE_BYTES:
                raise ValueError('inventory_row_bound')
            digest.update(raw)
            if not raw.strip():
                continue
            row = _json(raw.decode('utf-8'))
            kind, identity, tid = row['kind'], row['identity'], row['target_id']
            keys = {'dataset_id', 'field_id'} if kind == 'field' else {'operator'}
            if (kind not in {'field', 'operator'} or not isinstance(identity, dict)
                    or set(identity) != keys or any(not isinstance(v, str) or not v for v in identity.values())
                    or tid != kind + ':' + _digest(identity) or tid in ids
                    or row['status'] not in {'prepared', 'blocked'}
                    or type(row['source_validated']) is not bool
                    or any(not isinstance(row[name], list) for name in ('scopes', 'source_validated_scopes', 'gaps'))):
                raise ValueError('invalid_inventory_schema_or_identity')
            ids.add(tid)
            if scopes is not None:
                from wqb.semantic_contracts import resource_scope_from_dict
                scopes[tid] = {_bytes(resource_scope_from_dict(scope)).decode('utf-8') for scope in row['scopes']}
            counts['target_count'] += 1
            if counts['target_count'] > MAX_INVENTORY_TARGETS:
                raise ValueError('inventory_target_bound')
            counts['source_validated_targets'] += int(row['source_validated'])
            counts[row['status'] + '_targets'] += 1
            if row['status'] == 'prepared':
                if tid not in assigned:
                    raise ValueError('inventory_job_assignment_mismatch')
                job_id = assigned.pop(tid)
                if plan['identity'].get('inventory_format_version', 1) < 3 and row.get('job_id') != job_id:
                    raise ValueError('inventory_job_assignment_mismatch')
            elif row.get('job_id') is not None or tid in assigned:
                raise ValueError('blocked_target_has_job')
    if assigned or digest.hexdigest() != plan['inventory_ref']['sha256']:
        raise ValueError('inventory_digest_or_coverage_mismatch')
    if any(type(plan['coverage'][key]) is not int or plan['coverage'][key] != value
           for key, value in counts.items()):
        raise ValueError('inventory_count_mismatch')
    if _safe_local_path(root, path) or _stamp(path) != before:
        raise ValueError('inventory_changed')
    return counts


def _job_evidence(root: Path, plan: dict, *, verify_content=False) -> dict:
    """Input: vault/bound plan. Output: bounded exact-directory evidence observations.

    No source reconstruction or recursive scan: absence is only an observation,
    never execution or deletion authority. Unknown entries and limits protect.
    """
    checked = 0
    reasons = ['job_content_validation_not_requested'] if plan['jobs'] and not verify_content else []
    for job in plan['jobs']:
        if checked >= MAX_JOB_CHECKS:
            reasons.append('job_evidence_check_bound')
            break
        try:
            folder = _path(root, 'machine/semantic_jobs/' + job['job_id'])
            before = _stamp(folder)
            seen = set()
            checked += 1
            for index, entry in enumerate(folder.iterdir()):
                if index >= MAX_OWNER_ENTRIES:
                    reasons.append('job_directory_entry_bound')
                    break
                if _safe_local_path(root, entry) or entry.name not in {'run_manifest.json', 'input.json', 'brief.txt', 'execution_guard.guard'}:
                    reasons.append('job_execution_or_unknown_artifact_present')
                    break
                if not entry.is_file():
                    reasons.append('job_preparation_artifact_invalid')
                    break
                seen.add(entry.name)
            if not {'run_manifest.json', 'input.json', 'brief.txt'} <= seen:
                reasons.append('job_preparation_incomplete_or_unverified')
            if verify_content:
                from wqb.full_semantic_execution import _ref
                base = folder.relative_to(root).as_posix()
                raw = _ref(root, dict(path=job['path'], sha256=job['sha256']), MAX_AUDIT_BYTES, base)
                manifest = _json(raw.decode('utf-8'))
                input_ref = dict(path=base + '/input.json', sha256=job['input_sha256'])
                brief_ref = dict(path=base + '/brief.txt', sha256=job['brief_sha256'])
                if (raw != _bytes(manifest) or manifest['kind'] != 'full_semantic_explanation'
                        or manifest['schema_version'] != 1 or manifest['root'] != str(root)
                        or manifest['content_key'] != job['job_id'] or manifest['target_ids'] != job['target_ids']
                        or manifest['input_ref'] != input_ref or manifest['brief_ref'] != brief_ref
                        or _digest(dict(input_sha256=job['input_sha256'], contracts=manifest['contracts'], root=str(root))) != job['job_id']):
                    raise ValueError('prepared job identity differs from original bound references')
                _ref(root, input_ref, MAX_AUDIT_BYTES, base)
                _ref(root, brief_ref, MAX_AUDIT_BYTES, base)
            if _safe_local_path(root, folder) or _stamp(folder) != before:
                reasons.append('job_directory_changed')
        except (OSError, ValueError, TypeError, KeyError, AttributeError, UnicodeError, RecursionError) as exc:
            reasons.append('job_evidence_unverified:' + str(exc)[:160])
            break
    return dict(checked_jobs=checked, total_jobs=len(plan['jobs']),
                status='protected' if reasons else 'no_execution_evidence_observed', reasons=reasons)


def _path(root: Path, relative: str) -> Path:
    """Input: root Path/relative str. Output: safe local Path; reject links/escapes."""
    if not isinstance(relative, str) or '\\' in relative or ':' in relative:
        raise ValueError('invalid relative path')
    parts = relative.split('/')
    if any(part in ('', '.', '..') for part in parts):
        raise ValueError('invalid relative path')
    path = root / relative
    reason = _safe_local_path(root, path)
    if reason:
        raise ValueError(reason)
    return path


def _root(value: str | Path) -> Path:
    """Input: vault path. Output: absolute existing Path without following unsafe links."""
    root = Path(os.path.abspath(value))
    if _safe_local_path(root, root) or not root.is_dir():
        raise ValueError('unsafe vault root')
    return root


def _plan_path(root: Path, relative: str) -> Path:
    """Input: root Path/plan path str. Output: exact allowlisted plan Path."""
    if not isinstance(relative, str) or not PLAN_PATH.fullmatch(relative):
        raise ValueError('invalid plan path')
    return _path(root, relative)


def check_semantic_retirement(root: str | Path, plan_path: str) -> dict:
    """Input: vault path/plan path str. Output: read-only dict; uncertainty blocks use."""
    try:
        root = _root(root)
        path = _plan_path(root, plan_path)
        marker = path.parent / RETIREMENT_MARKER
        if _safe_local_path(root, marker):
            return dict(blocked=True, reason='unsafe_retirement_marker')
        if os.path.lexists(marker):
            return dict(blocked=True, reason='retirement_marker_present')
        if not path.is_file():
            return dict(blocked=True, reason='missing_plan')
        return dict(blocked=False, reason='no_retirement_marker')
    except (OSError, ValueError, TypeError):
        return dict(blocked=True, reason='retirement_check_uncertain')


def _manifest(root: Path, relative: str) -> tuple:
    """Input: vault Path/exact plan str. Output: original zero-budget manifest and byte-bound metadata."""
    path = _plan_path(root, relative)
    if path.stat().st_size > MAX_AUDIT_BYTES:
        raise ValueError('plan_read_bound')
    with path.open('rb') as handle:
        raw = handle.read(MAX_AUDIT_BYTES + 1)
    if len(raw) > MAX_AUDIT_BYTES:
        raise ValueError('plan_read_bound')
    plan = _json(raw.decode('utf-8'))
    if (not isinstance(plan, dict) or plan.get('kind') != 'full_semantic_compile_plan'
            or type(plan.get('schema_version')) is not int
            or plan.get('schema_version') != 1):
        raise ValueError('unsupported_plan')
    inventory_reference_base(plan)
    if (raw != _bytes(plan) or plan['root'] != str(root)
            or plan['identity']['root'] != str(root) or plan['plan_path'] != relative
            or plan['identity']['jobs'] != plan['jobs']
            or _digest(plan['identity']) != plan['content_key']
            or relative != 'machine/semantic_jobs/' + plan['content_key'] + '/plan.json'):
        raise ValueError('plan_or_inventory_identity_mismatch')
    if (type(plan['budget']['model_call_budget']) is not int
            or plan['budget']['model_call_budget'] != 0
            or type(plan['identity']['config']['model_call_budget']) is not int
            or plan['identity']['config']['model_call_budget'] != 0
            or type(plan['identity']['config']['max_runtime_seconds']) is not int
            or plan['identity']['config']['max_runtime_seconds'] < 1
            or type(plan.get('model_calls')) is not int or plan['model_calls'] != 0
            or plan['budget'].get('execution_authorized') is not False):
        raise ValueError('not_unexecuted_zero_budget')
    if _safe_local_path(root, path):
        raise ValueError('candidate_changed')
    with path.open('rb') as handle:
        if handle.read(MAX_AUDIT_BYTES + 1) != raw:
            raise ValueError('candidate_changed')
    return plan, dict(plan_path=relative, plan_sha256=_hash(raw), content_key=plan['content_key'],
                      inventory=dict(plan['inventory_ref']),
                      source_digests=plan['identity'].get('sources', []))


def _read_plan(root: Path, relative: str) -> tuple:
    """Input: vault Path/active plan path. Output: authenticated plan and streamed inventory summary."""
    assert_semantic_plan_active(root, relative)
    plan, metadata = _manifest(root, relative)
    counts = _inventory(root, plan)
    if _manifest(root, relative)[1] != metadata:
        raise ValueError('plan changed during inventory verification')
    return plan, dict(metadata, target_count=counts['target_count'], inventory_counts=counts)


def audit_semantic_derivative(root: str | Path, plan_path: str, *,
                              replacement_plan_path: str | None = None) -> dict:
    """Input: explicit vault/old/replacement paths. Output: protected plan-only audit dict.

    No recursive scans, locks (which would write), journaling, network or mutation.
    Distinct replacement validation does NOT prove newer/superseding content.
    Local snapshots are advisory: concurrent changes can invalidate any finding.
    """
    result = dict(mode='audit_only', eligible=False, validated=False, disposition='protected',
                  reasons=[], plan_path=plan_path, model_calls=0)
    try:
        root = _root(root)
        plan, summary = _read_plan(root, plan_path)
        result.update(summary)
        result['validated'] = True
        base = 'machine/semantic_jobs/' + plan['content_key']
        if plan['inventory_ref']['path'] != base + '/inventory.jsonl':
            result['reasons'].append('shared_inventory_protected')
        owner = _plan_path(root, plan_path).parent
        # Even empty execution/reservation directories and unknown artifacts protect.
        for index, entry in enumerate(owner.iterdir()):
            if index >= MAX_OWNER_ENTRIES:
                result['reasons'].append('owner_entry_bound')
                break
            if _safe_local_path(root, entry) or entry.name not in {'plan.json', 'inventory.jsonl'}:
                result['reasons'].append('owner_has_additional_artifacts')
                break
        result['job_evidence'] = _job_evidence(root, plan)
        result['reasons'].extend(result['job_evidence']['reasons'])
        if not replacement_plan_path or replacement_plan_path == plan_path:
            result['reasons'].append('replacement_required')
        else:
            _, replacement = _read_plan(root, replacement_plan_path)
            result['replacement'] = replacement
            result['reasons'].append('replacement_order_unproven')
        result['reasons'].extend(['external_references_not_verified',
                                  'shared_writer_serialization_not_verified', 'audit_only_no_retirement'])
    except (OSError, ValueError, TypeError, KeyError, AttributeError, UnicodeError, RecursionError) as exc:
        result['validated'] = False
        result['reasons'].append('invalid_or_uncertain_candidate:' + type(exc).__name__ + ':' + str(exc)[:160])
    return result


def plan_guard(root: Path, plan_path: str):
    """Input: vault Path/exact plan str. Output: existing OS guard context, shared by prepare/run/report/retire."""
    from wqb.lockfile import json_lock_transition_guard
    root = _root(root)
    base = _plan_path(root, plan_path).parent
    guard = _path(root, (base / 'execution_guard').relative_to(root).as_posix())
    _path(root, (base / 'execution_guard.guard').relative_to(root).as_posix())
    return json_lock_transition_guard(guard, LIFECYCLE_LOCK_SECONDS, .02, 'semantic plan lifecycle busy')


def assert_semantic_plan_active(root: Path, plan_path: str) -> None:
    """Input: vault Path/exact plan str. Output: None or rejection; a marker never grants renewed authority."""
    marker = _plan_path(root, plan_path).parent / RETIREMENT_MARKER
    if _safe_local_path(root, marker) or os.path.lexists(marker):
        raise ValueError('retired semantic plan is read-only; execution/publication refused')


def _file_digest(path: Path) -> str:
    """Input: checked Path. Output: bounded stream SHA; refuse growth or replacement, not unknown bytes."""
    before = _stamp(path)
    if before[2] > RETIREMENT_SCAN_BYTES:
        raise ValueError('retirement reference byte bound')
    digest, count = hashlib.sha256(), 0
    with path.open('rb') as stream:
        while data := stream.read(1024 * 1024):
            count += len(data)
            if count > RETIREMENT_SCAN_BYTES:
                raise ValueError('retirement reference byte bound')
            digest.update(data)
    if _stamp(path) != before or count != before[2]:
        raise ValueError('retirement evidence changed')
    return digest.hexdigest()


def _owner_unexecuted(root: Path, plan: dict, *, retired=False) -> None:
    """Input: original zero-budget plan. Output: None; unknown execution/state protects this candidate."""
    base = _plan_path(root, plan['plan_path']).parent
    if plan['inventory_ref']['path'] != base.relative_to(root).as_posix() + '/inventory.jsonl':
        raise ValueError('shared inventory is protected')
    allowed = {'plan.json', 'inventory.jsonl', 'execution_guard.guard'}
    if retired:
        allowed.update({RETIREMENT_MARKER, 'retirement_completed.json'})
    for index, item in enumerate(base.iterdir()):
        if index >= MAX_OWNER_ENTRIES or _safe_local_path(root, item) or item.name not in allowed or not item.is_file():
            raise ValueError('execution or unknown artifact protects semantic plan')
    evidence = _job_evidence(root, plan, verify_content=True)
    if evidence['reasons']:
        raise ValueError('job execution/artifact evidence protects plan: ' + '; '.join(evidence['reasons']))


def _commit_guards(root: Path, plan: dict):
    """Input: vault/original plan. Output: stack of job -> publication -> source-index guards; no model work."""
    from wqb.lockfile import json_lock_transition_guard
    from wqb.semantic_publication import _acquire_lock, _release_lock
    from wqb.knowledge_contracts import _source_index_guard
    stack = ExitStack()
    try:
        for key in sorted({job['job_id'] for job in plan['jobs']}):
            base = 'machine/semantic_jobs/' + key
            guard = _path(root, base + '/execution_guard')
            _path(root, base + '/execution_guard.guard')
            stack.enter_context(json_lock_transition_guard(guard, LIFECYCLE_LOCK_SECONDS, .02, 'semantic job evidence busy'))
        handle = _acquire_lock(root)
        stack.callback(_release_lock, handle)
        stack.enter_context(_source_index_guard(root))
        return stack
    except BaseException:
        stack.close()
        raise


def _replacement(root: Path, plan: dict, replacement_path: str, *, archive_ref=None) -> tuple:
    """Input: old plan/explicit new path/optional migrated bytes. Output: verified counts and identity/scope coverage."""
    if replacement_path == plan['plan_path']:
        raise ValueError('replacement must be a different current plan')
    assert_semantic_plan_active(root, replacement_path)
    replacement, metadata = _manifest(root, replacement_path)
    if (replacement['identity'].get('inventory_format_version') != 3
            or not replacement['inventory_ref']['path'].startswith('machine/semantic_inventories/')):
        raise ValueError('replacement must use the current shared inventory format')
    previous_scopes, current_scopes = {}, {}
    counts = _inventory(root, plan, archive_ref=archive_ref, scopes=previous_scopes)
    _inventory(root, replacement, scopes=current_scopes)
    if any(key not in current_scopes or not scopes <= current_scopes[key] for key, scopes in previous_scopes.items()):
        raise ValueError('replacement does not cover every original identity and exact scope')
    if _manifest(root, replacement_path)[1] != metadata:
        raise ValueError('replacement changed during coverage verification')
    proof = dict(target_count=len(previous_scopes), identity_scope_sha256=_digest(
        {key: sorted(value) for key, value in sorted(previous_scopes.items())}),
        replacement_inventory_ref=replacement['inventory_ref'])
    return counts, dict(path=replacement_path, sha256=metadata['plan_sha256']), proof


def _references(root: Path, plan: dict) -> dict:
    """Input: target plan. Output: consumed owner digests; only authenticated self/history views are excluded."""
    from wqb.knowledge_clean_compile import _reference_refusal
    base = str(Path(plan['plan_path']).parent).replace('\\', '/')
    ignored = {plan['plan_path'], base + '/' + RETIREMENT_MARKER, base + '/retirement_completed.json',
        'machine/reports/full_semantic_coverage_' + plan['content_key'] + '.json'}
    snapshots = {}
    target = _path(root, plan['inventory_ref']['path'])
    reason = _reference_refusal(root, target, plan['inventory_ref']['sha256'],
        ignored_owners=ignored, snapshots=snapshots, historical_reports=True,
        max_file_bytes=RETIREMENT_SCAN_BYTES, max_total_bytes=RETIREMENT_SCAN_BYTES,
        max_seconds=RETIREMENT_SCAN_SECONDS)
    if reason:
        raise ValueError('retirement reference protection: ' + reason)
    return snapshots


def _check_snapshots(root: Path, snapshots: dict) -> None:
    """Input: consumed owner SHA map. Output: None; reject changed/unsafe owners before intent or collection."""
    for name, expected in snapshots.items():
        path = Path(name)
        boundary = root if path.is_relative_to(root) else root.parent
        if (not path.is_absolute() or not (path.is_relative_to(root)
                or root.name == 'knowledge' and path.is_relative_to(root.parent / 'runs'))
                or _safe_local_path(boundary, path) or _file_digest(path) != expected):
            raise ValueError('retirement reference snapshot changed')


def _record(root: Path, relative: str) -> dict:
    """Input: canonical bounded record path. Output: exact JSON object; no status-only trust."""
    path = _path(root, relative)
    with path.open('rb') as stream:
        raw = stream.read(MAX_AUDIT_BYTES + 1)
    if len(raw) > MAX_AUDIT_BYTES:
        raise ValueError('retirement record exceeds byte bound')
    value = _json(raw.decode('utf-8'))
    if not isinstance(value, dict) or _bytes(value) != raw:
        raise ValueError('retirement record is not canonical')
    return value


def _retired_context(root: Path, plan_path: str) -> tuple:
    """Input: retired plan path. Output: original plan, authenticated intent and archived inventory counts."""
    plan, metadata = _manifest(root, plan_path)
    relative = str(Path(plan_path).parent / RETIREMENT_MARKER).replace('\\', '/')
    intent = _record(root, relative)
    if (set(intent) != INTENT_KEYS or type(intent['schema_version']) is not int
            or intent['schema_version'] != LIFECYCLE_VERSION or intent['kind'] != 'semantic_plan_retirement'
            or intent['root'] != str(root) or intent['plan_ref'] != dict(path=plan_path, sha256=metadata['plan_sha256'])
            or intent['inventory_ref'] != plan['inventory_ref']
            or intent['archive_ref'].get('uncompressed_sha256') != plan['inventory_ref']['sha256']
            or intent['source_digest'] != _digest(plan['identity'].get('sources', []))):
        raise ValueError('retirement intent differs from original evidence')
    replacement_path = intent['replacement_ref']['path']
    counts, reference, proof = _replacement(root, plan, replacement_path, archive_ref=intent['archive_ref'])
    if (counts != intent['inventory_counts'] or reference != intent['replacement_ref'] or proof != intent['coverage_proof']):
        raise ValueError('retirement coverage or replacement evidence differs')
    return plan, intent, counts


def read_retired_semantic_plan(root: str | Path, plan_path: str) -> dict:
    """Input: historical plan selector. Output: verified read-only history, never live coverage or execution authority."""
    root = _root(root)
    with plan_guard(root, plan_path):
        plan, intent, counts = _retired_context(root, plan_path)
        return _retired_summary(plan, intent, counts)


def _retired_summary(plan: dict, intent: dict, counts: dict) -> dict:
    """Input: verified historical context. Output: summary with no live coverage or execution claims."""
    return dict(kind='retired_semantic_plan', status='retired', read_only=True,
        plan_path=plan['plan_path'], inventory_ref=plan['inventory_ref'], archive_ref=intent['archive_ref'],
        inventory_counts=counts, model_calls=0, execution_authorized=False,
        publication_authorized=False, research_ready=False)


def prepare_semantic_retirement(root: str | Path, plan_path: str, *, replacement_plan_path: str) -> dict:
    """Input: explicit old/current plans. Output: durable read-only intent; original expanded bytes are not removed."""
    from wqb.semantic_inventory_archive import prepare_inventory_archive
    from wqb.knowledge_contracts import _write_immutable_source
    root = _root(root)
    with plan_guard(root, plan_path):
        marker = _plan_path(root, plan_path).parent / RETIREMENT_MARKER
        if marker.exists():
            _, intent, _ = _retired_context(root, plan_path)
            if intent['replacement_ref']['path'] != replacement_plan_path:
                raise ValueError('saved retirement replacement cannot change')
            return dict(status='prepared', archive_ref=intent['archive_ref'], removed_count=0)
        plan, metadata = _manifest(root, plan_path)
        _owner_unexecuted(root, plan)
        counts, replacement, proof = _replacement(root, plan, replacement_plan_path)
        with _commit_guards(root, plan):
            _owner_unexecuted(root, plan)
            _references(root, plan)
        archive = prepare_inventory_archive(root, plan['inventory_ref']['path'], plan['inventory_ref']['sha256'])
        intent = dict(schema_version=LIFECYCLE_VERSION, kind='semantic_plan_retirement', root=str(root),
            plan_ref=dict(path=plan_path, sha256=metadata['plan_sha256']), inventory_ref=plan['inventory_ref'],
            replacement_ref=replacement, archive_ref=archive, inventory_counts=counts,
            coverage_proof=proof, source_digest=_digest(plan['identity'].get('sources', [])))
        with _commit_guards(root, plan):
            _owner_unexecuted(root, plan)
            snapshots = _references(root, plan)
            if (_manifest(root, plan_path)[1] != metadata
                    or _manifest(root, replacement_plan_path)[1]['plan_sha256'] != replacement['sha256']
                    or _file_digest(_path(root, plan['inventory_ref']['path'])) != plan['inventory_ref']['sha256']):
                raise ValueError('retirement inputs changed before intent')
            _check_snapshots(root, snapshots)
            _write_immutable_source(_path(root, marker.relative_to(root).as_posix()), _bytes(intent))
        return dict(status='prepared', archive_ref=archive, removed_count=0)


def _remove_expanded_inventory(root: Path, plan: dict) -> int:
    """Input: approved original plan. Output: 0/1 removed copy; reject a changed or unsafe logical inventory."""
    path = _path(root, plan['inventory_ref']['path'])
    if not path.exists():
        return 0
    before = _stamp(path)
    if _file_digest(path) != plan['inventory_ref']['sha256']:
        raise ValueError('expanded inventory changed; original is protected')
    if _safe_local_path(root, path) or _stamp(path) != before:
        raise ValueError('expanded inventory replaced before collection')
    path.unlink()
    return 1


def _complete_retirement(root: Path, plan: dict, intent: dict, approval_reference: str) -> None:
    """Input: verified transaction and caller audit reference. Output: immutable completion; no quota/state changes."""
    from wqb.knowledge_contracts import _write_immutable_source
    path = str(Path(plan['plan_path']).parent / 'retirement_completed.json').replace('\\', '/')
    value = dict(kind='semantic_plan_retirement_completed', schema_version=1,
        intent_sha256=_digest(intent), approval_reference=approval_reference, inventory_removed=True)
    _write_immutable_source(_path(root, path), _bytes(value))


def apply_semantic_retirement(root: str | Path, plan_path: str, *,
                               replacement_plan_path: str | None = None,
                               approved_inventory_paths=None, approval_reference: str = '') -> dict:
    """Input: saved intent plus exact operator-approved path/reference. Output: idempotent collection result.

    The reference is audit metadata, not an authorization channel. This library
    is not wired to implicit Start/cleanup; the operator must obtain real scope
    approval and verify deployment/Git evidence before calling it on real data.
    """
    if (not isinstance(approval_reference, str) or not approval_reference.strip() or len(approval_reference) > 512
            or not isinstance(approved_inventory_paths, list) or len(approved_inventory_paths) != 1):
        raise ValueError('explicit path-bound collection approval required')
    root = _root(root)
    with plan_guard(root, plan_path):
        plan, intent, _ = _retired_context(root, plan_path)
        if approved_inventory_paths != [plan['inventory_ref']['path']]:
            raise ValueError('collection approval does not match original inventory')
        if replacement_plan_path is not None and replacement_plan_path != intent['replacement_ref']['path']:
            raise ValueError('saved retirement replacement cannot change')
        completion = str(Path(plan_path).parent / 'retirement_completed.json').replace('\\', '/')
        with _commit_guards(root, plan):
            _owner_unexecuted(root, plan, retired=True)
            snapshots = _references(root, plan)
            if _path(root, completion).exists():
                row = _record(root, completion)
                if (set(row) != {'kind', 'schema_version', 'intent_sha256', 'approval_reference', 'inventory_removed'}
                        or row['kind'] != 'semantic_plan_retirement_completed' or type(row['schema_version']) is not int
                        or row['schema_version'] != 1 or row['intent_sha256'] != _digest(intent)
                        or row['inventory_removed'] is not True or not isinstance(row['approval_reference'], str)
                        or not row['approval_reference'].strip()):
                    raise ValueError('invalid retirement completion evidence')
                if _path(root, plan['inventory_ref']['path']).exists():
                    raise ValueError('completed legacy inventory reappeared; maintenance required')
                return dict(status='collected', removed_count=0, archive_ref=intent['archive_ref'])
            from wqb.semantic_inventory_archive import verify_inventory_archive
            verify_inventory_archive(root, intent['archive_ref'])
            _check_snapshots(root, snapshots)
            removed = _remove_expanded_inventory(root, plan)
            _complete_retirement(root, plan, intent, approval_reference)
        return dict(status='collected', removed_count=removed, archive_ref=intent['archive_ref'])
