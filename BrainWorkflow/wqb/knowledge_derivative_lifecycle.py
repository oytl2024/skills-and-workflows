"""Bounded, read-only P4 sidecar. No deletion authority is implemented.

Integration API:
* audit_semantic_derivative(root, plan_path, replacement_plan_path=...) checks
  explicit paths only; it never discovers/scans a vault. ``eligible`` is always
  False. ``validated`` means local manifest/inventory validation, not safe GC.
* check_semantic_retirement(root, plan_path) is a check-only execution guard:
  callers must reject ``blocked`` before loading/executing a plan. Presence of
  retirement.json (even malformed) blocks; absence grants no execution authority.
* apply_semantic_retirement always refuses, including explicit calls.

Plans remain limited to 16MB. Inventories have no total-byte cap: JSONL is
streamed with the coverage validator's 16MB row bound and at most one million
compact target IDs. Counts and hashes cover the full stream, not a prefix.
Job checks are exact-directory, count bounded observations, not raw certification.
``validated`` covers plan/inventory; consult ``job_evidence`` independently.

Apply needs a separately reviewed shared execution/publication lock protocol,
structured external-root assessment, authenticated newer replacement ordering,
candidate revalidation and durable journal/receipt recovery. Existing locks do
not by themselves prove all writers participate. No timestamps, audit results or
caller assertions substitute for those proofs. No retirement receipts are made.
"""

import os
import hashlib
from pathlib import Path
import re

from wqb.full_semantic_compile import _bytes, _digest, _hash, _json, inventory_reference_base
from wqb.knowledge_clean_compile import _safe_local_path


MAX_AUDIT_BYTES = 16 * 1024 * 1024
MAX_INVENTORY_LINE_BYTES = 16 * 1024 * 1024
MAX_INVENTORY_TARGETS = 1_000_000
MAX_JOB_CHECKS = 4096
MAX_OWNER_ENTRIES = 8
PLAN_PATH = re.compile(r'machine/semantic_jobs/[a-f0-9]{64}/plan\.json\Z')
RETIREMENT_MARKER = 'retirement.json'
HASH = re.compile(r'[a-f0-9]{64}\Z')


def _stamp(path: Path) -> tuple:
    """Input: Path. Output: file identity/size/time tuple for advisory race detection."""
    info = path.stat()
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def _inventory(root: Path, plan: dict) -> dict:
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
    path = _path(root, plan['inventory_ref']['path'])
    before = _stamp(path)
    counts = dict(target_count=0, prepared_targets=0, blocked_targets=0, source_validated_targets=0)
    digest, ids = hashlib.sha256(), set()
    with path.open('rb') as stream:
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


def _job_evidence(root: Path, plan: dict) -> dict:
    """Input: vault/bound plan. Output: bounded exact-directory evidence observations.

    No source reconstruction or recursive scan: absence is only an observation,
    never execution or deletion authority. Unknown entries and limits protect.
    """
    checked = 0
    reasons = ['job_content_validation_unsupported'] if plan['jobs'] else []
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
                if _safe_local_path(root, entry) or entry.name not in {'run_manifest.json', 'input.json', 'brief.txt'}:
                    reasons.append('job_execution_or_unknown_artifact_present')
                    break
                if not entry.is_file():
                    reasons.append('job_preparation_artifact_invalid')
                    break
                seen.add(entry.name)
            if seen != {'run_manifest.json', 'input.json', 'brief.txt'}:
                reasons.append('job_preparation_incomplete_or_unverified')
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


def _read_plan(root: Path, relative: str) -> tuple:
    """Input: root/explicit plan path. Output: authenticated plan/summary; bounded reads."""
    path = _plan_path(root, relative)
    if check_semantic_retirement(root, relative)['blocked']:
        raise ValueError('retired_or_uncertain_plan')
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
    counts = _inventory(root, plan)
    if _safe_local_path(root, path):
        raise ValueError('candidate_changed')
    with path.open('rb') as handle:
        if handle.read(MAX_AUDIT_BYTES + 1) != raw:
            raise ValueError('candidate_changed')
    return plan, dict(plan_path=relative, plan_sha256=_hash(raw), content_key=plan['content_key'],
                      inventory=dict(plan['inventory_ref']), target_count=counts['target_count'], inventory_counts=counts,
                      source_digests=plan['identity'].get('sources', []))


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


def apply_semantic_retirement(root: str | Path, plan_path: str, *,
                               replacement_plan_path: str | None = None) -> None:
    """Input: explicit paths. Output: never returns; refuse before any reads or writes."""
    raise ValueError('audit-only: retirement apply requires reviewed serialization and recovery design')
