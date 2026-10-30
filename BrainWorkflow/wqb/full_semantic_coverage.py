"""Read-only K5 measurements; only machine/reports is an output boundary.

An explanation is not a publication, a binder result or a frozen Start lane.
There is deliberately no invented binder/Start receipt protocol in this helper.
"""

from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from uuid import uuid4

from wqb.full_semantic_compile import _bytes, _digest, _hash, _json
from wqb.full_semantic_execution import (
    HASH, _read, _ref, _root, _verify_state,
    load_bound_explanation_job, validate_full_semantic_output,
)
from wqb.knowledge_age_policy import KNOWLEDGE_MAX_AGE_DAYS
from wqb.semantic_compilation import MAX_OUTPUT_BYTES, _safe


REPORT_VERSION = 1
MAX_REASON_CHARS = 600
MAX_INVENTORY_LINE_BYTES = 16 * 1024 * 1024
REPORT_PREFIX = 'machine/reports/full_semantic_coverage_'
ARTIFACT_ERRORS = (OSError, ValueError, TypeError, KeyError, RuntimeError, UnicodeError)


def _report_inventory(root: Path, plan: dict) -> tuple:
    """Input: vault Path/supplied plan dict. Output: authenticated saved plan and compact target dict.

    Match execution's plan authority checks without deepcopying the plan or
    materializing raw inventory bytes/occurrences. Memory is compact targets plus
    one bounded JSONL row, not a second full inventory or per-row source proofs.
    """
    if not isinstance(plan, dict) or plan.get('root') != str(root) or not HASH.fullmatch(str(plan.get('content_key', ''))):
        raise ValueError('plan root/key mismatch')
    base = 'machine/semantic_jobs/' + plan['content_key']
    if plan.get('plan_path') != base + '/plan.json':
        raise ValueError('plan path mismatch')
    path = _safe(root, plan['plan_path'])
    saved = _read(path, max(path.stat().st_size, 1), canonical=True)
    observed = dict(plan['estimates'])
    expected = dict(saved['estimates'])
    for key in ('cached_jobs', 'changed_jobs'):
        observed.pop(key, None)
        expected.pop(key, None)
    if (dict(plan, estimates=observed) != dict(saved, estimates=expected)
            or _digest(saved['identity']) != saved['content_key']
            or saved['identity']['root'] != str(root) or saved['identity']['jobs'] != saved['jobs']):
        raise ValueError('saved plan identity/authority differs from supplied plan')
    config = saved['identity']['config']
    budget = config['model_call_budget']
    if (type(budget) is not int or budget < 0 or saved['budget']['model_call_budget'] != budget
            or type(config['max_runtime_seconds']) is not int or config['max_runtime_seconds'] < 1):
        raise ValueError('invalid finite plan budget/runtime')
    ref = saved['inventory_ref']
    if (set(ref) != {'path', 'sha256'} or not HASH.fullmatch(str(ref['sha256']))
            or not ref['path'].startswith(base + '/') or ref['sha256'] != saved['identity']['inventory_sha256']):
        raise ValueError('invalid bound inventory reference')
    assigned = [tid for job in saved['jobs'] for tid in job['target_ids']]
    if len(assigned) != len(set(assigned)):
        raise ValueError('duplicate job targets')
    prepared, targets, digest = set(), {}, hashlib.sha256()
    with _safe(root, ref['path']).open('rb') as stream:
        while raw := stream.readline(MAX_INVENTORY_LINE_BYTES + 1):
            if len(raw) > MAX_INVENTORY_LINE_BYTES:
                raise ValueError('inventory row exceeds report streaming bound')
            digest.update(raw)
            if not raw.strip():
                continue
            row = _json(raw.decode('utf-8'))
            tid = row['target_id']
            if tid in targets:
                raise ValueError('duplicate inventory target')
            if row['status'] == 'prepared':
                prepared.add(tid)
            targets[tid] = dict(target_id=tid, kind=row['kind'], identity=row['identity'],
                scope_count=len(row['scopes']), indexed_scope_count=len(row['source_validated_scopes']),
                source_bytes_validated=False, freshness_status='not_evaluated',
                processing_status='unattempted' if row['status'] == 'prepared' else 'blocked',
                explanation_validated=False, documented=False, hypothesis=False,
                missing_facts=[], conflicting_facts=[], reasons=[dict(code=g.get('code', 'inventory_gap'),
                    reason=str(g.get('message', g.get('code', 'inventory_gap')))[:MAX_REASON_CHARS]) for g in row.get('gaps', [])])
    if digest.hexdigest() != ref['sha256'] or set(assigned) != prepared:
        raise ValueError('inventory digest/job target coverage mismatch')
    return saved, targets


def _write_report(path: Path, report: dict) -> None:
    """Input: safe JSON Path/report dict. Output: None; stream JSON atomically without a second full string copy."""
    path.parent.mkdir(parents=True, exist_ok=True)
    staged = path.with_name(path.name + '.' + uuid4().hex + '.tmp')
    try:
        with staged.open('w', encoding='utf-8', newline='\n') as stream:
            json.dump(report, stream, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        staged.replace(path)
    finally:
        staged.unlink(missing_ok=True)


def _report_state(root: Path, state: dict, ref: dict, plans: dict) -> None:
    """Input: root/state/ref/local plan cache. Output: None; reuse canonical authority and stream each owner once."""
    def owner_plan(owner_root: Path, plan: dict) -> tuple:
        """Input: owning vault/plan. Output: authenticated plan and unused rows, bound to this report invocation."""
        key = plan['content_key']
        if key not in plans:
            plans[key], _ = _report_inventory(owner_root, plan)
        if plan != plans[key]:
            raise ValueError('owner plan changed during report')
        return plans[key], None
    _verify_state(root, state, ref, _plan_loader=owner_plan)


def _freshness(index: dict, now: datetime) -> str:
    """Input: authenticated source index dict/UTC datetime. Output: current, stale or invalid_date str."""
    for source in index.values():
        try:
            captured = datetime.fromisoformat(source['captured_at'].replace('Z', '+00:00'))
            if captured.tzinfo is None or captured > now:
                return 'invalid_date'
            if (now.date() - captured.astimezone(timezone.utc).date()).days > KNOWLEDGE_MAX_AGE_DAYS:
                return 'stale'
        except (ValueError, TypeError, KeyError):
            return 'invalid_date'
    return 'current' if index else 'not_evaluated'


def _validate_explanation(root: Path, job: dict, cached: dict) -> dict:
    """Input: vault/authenticated job/cached result dict. Output: canonical read-only validated targets by ID."""
    reconstructed = validate_full_semantic_output(root, job,
        dict(summary=cached['summary'], targets=cached['targets']), persist_field_results=False)
    if _bytes(reconstructed) != _bytes(cached):
        raise ValueError('completed explanation envelope differs from canonical validation')
    return {target['target_id']: target for target in reconstructed['targets']}


def _markdown(report: dict) -> str:
    """Input: report dict. Output: bounded summary Markdown str, never a full field ledger."""
    inventory, explanations = report['inventory'], report['explanations']
    lines = ['# Full Semantic Coverage', '',
        '| Layer | Measured numerator / denominator | Status |',
        '| --- | --- | --- |',
        f"| Inventory: source-byte-validated targets | {inventory['numerator']} / {inventory['denominator']} | {inventory['status']} |",
        f"| Current validated explanations | {explanations['numerator']} / {explanations['denominator']} | {explanations['status']} |",
        '| Compiler/binder candidate operations | 0 / unknown | not_evaluated |',
        '| Actual frozen Start lanes | 0 / unknown | not_evaluated |', '',
        f"Processed: {explanations['processed']}; documented targets: {explanations['documented_targets']}; "
        f"hypothesis targets: {explanations['hypothesis_targets']}; unattempted: {explanations['unattempted']}.", '',
        'Inventory includes blocked and unattempted identities. Byte validation is not freshness or scope certification.',
        'Processing is not semantic completeness. Hypotheses are not documented facts.',
        'Compiler/binder coverage requires measured operation-specific existing compiler/binder results; not evaluated here.',
        'Start coverage requires validated source-bound frozen consumption evidence; no consumer artifact validator is wired here.',
        'Unknown denominators are not zero-sized success. No publication, Start, model or platform calls occurred.', '',
        f"Detailed evidence: [{Path(report['report_paths']['json']).name}]({Path(report['report_paths']['json']).name})", '']
    return '\n'.join(lines)


def build_full_semantic_report(root: Path, plan: dict) -> dict:
    """Input: knowledge-root Path/authenticated K4 plan dict. Output: four-level report dict and JSON/Markdown files.

    Only machine/reports is written. Invalid plans raise before report creation;
    individual missing/stale/tampered jobs remain explicit denominator entries.
    Binder and Start denominators stay unknown until existing consumer validators
    are integrated; claimed flags or execution_result summaries are never evidence.
    """
    root = _root(root)
    saved, targets = _report_inventory(root, plan)
    plans = {saved['content_key']: saved}
    now = datetime.now(timezone.utc)
    diagnostics = list(saved.get('diagnostics', []))
    for ref in saved['jobs']:
        base = 'machine/semantic_jobs/' + ref['job_id']
        ids = ref['target_ids']
        try:
            raw = _ref(root, dict(path=ref['path'], sha256=ref['sha256']), MAX_OUTPUT_BYTES, base)
            job = load_bound_explanation_job(_safe(root, base))
            manifest = job['manifest']
            if (manifest['target_ids'] != ids or _hash(raw) != ref['sha256']
                    or manifest['input_ref']['sha256'] != ref['input_sha256']
                    or manifest['brief_ref']['sha256'] != ref['brief_sha256']):
                raise ValueError('plan job reference mismatch')
            freshness = _freshness(job['source_index'], now)
            for tid in ids:
                targets[tid].update(source_bytes_validated=True, freshness_status=freshness)
            state_path = _safe(root, base + '/execution_state.json')
            if not state_path.exists():
                continue
            state = _read(state_path)
            if not isinstance(state, dict):
                raise ValueError('execution state must be an object')
            _report_state(root, state, ref, plans)
            status = state.get('status', 'unattempted')
            for tid in ids:
                targets[tid]['processing_status'] = status
            if status != 'completed':
                continue
            result_raw = _ref(root, state['result_ref'], MAX_OUTPUT_BYTES, base)
            cached = _json(result_raw.decode('utf-8'))
            checked = _validate_explanation(root, job, cached)
            try:
                if load_bound_explanation_job(_safe(root, base)) != job:
                    raise ValueError('source/job changed during report validation')
            except ARTIFACT_ERRORS:
                for tid in ids:
                    targets[tid].update(source_bytes_validated=False, freshness_status='invalid')
                raise
            if (_ref(root, state['result_ref'], MAX_OUTPUT_BYTES, base) != result_raw
                    or _read(state_path) != state):
                raise ValueError('result/state changed during report validation')
            for tid, target in checked.items():
                current = freshness == 'current'
                documented = target['literal_fact_summary'] is not None and any(
                    r['kind'] == 'documented' for r in target['evidence_refs'])
                hypothesis = bool(target['hypothesis_cards'] or target['conditional_uses'])
                targets[tid].update(processing_status='validated', explanation_validated=current and (
                    target['literal_fact_summary'] is not None or hypothesis), documented=current and documented,
                    hypothesis=current and hypothesis, missing_facts=target['missing_facts'],
                    conflicting_facts=target['conflicting_facts'])
                if not current:
                    targets[tid]['reasons'].append(dict(code='source_' + freshness))
        except ARTIFACT_ERRORS as exc:
            reason = str(exc)[:MAX_REASON_CHARS]
            diagnostics.append(dict(job_id=ref['job_id'], code='coverage_validation_failed', reason=reason))
            for tid in ids:
                targets[tid].update(processing_status='invalid', explanation_validated=False, documented=False, hypothesis=False)
                targets[tid]['reasons'].append(dict(code='coverage_validation_failed', reason=reason))
    for owner in plans.values():
        reference = owner['inventory_ref']
        with _safe(root, reference['path']).open('rb') as stream:
            current_digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        if current_digest != reference['sha256']:
            raise ValueError('inventory changed during report validation')
    values = list(targets.values())
    counts = Counter(t['processing_status'] for t in values)
    total = len(values)
    explained = sum(t['explanation_validated'] for t in values)
    complete = saved['coverage'].get('inventory_complete', False)
    paths = dict(json=REPORT_PREFIX + saved['content_key'] + '.json',
                 markdown=REPORT_PREFIX + saved['content_key'] + '.md')
    report = dict(schema_version=REPORT_VERSION, kind='full_semantic_coverage', plan_key=saved['content_key'],
        generated_at=now.isoformat(), report_paths=paths, inventory_ref=saved['inventory_ref'],
        inventory=dict(numerator=sum(t['source_bytes_validated'] for t in values), denominator=total,
            denominator_unit='local_inventory_targets', inventory_complete=complete,
            measurement_scope='authenticated_plan_snapshot_not_live_rediscovery',
            status='measured' if complete else 'partial', scope_certification='not_evaluated',
            scope_rows=dict(denominator=sum(t['scope_count'] for t in values),
                numerator=sum(t['indexed_scope_count'] for t in values if t['source_bytes_validated']),
                denominator_unit='distinct_target_scope_rows', measurement='indexed_bytes_only'),
            unresolved_sources=saved['coverage'].get('unresolved_inventory_sources', [])),
        explanations=dict(numerator=explained, denominator=total, denominator_unit='local_explanation_targets',
            status='measured' if complete else 'partial', processed=counts['validated'],
            documented_targets=sum(t['documented'] for t in values),
            hypothesis_targets=sum(t['hypothesis'] for t in values), unattempted=counts['unattempted'],
            processing_counts=dict(counts), unresolved_targets=total - explained),
        compiler_binder=dict(status='not_evaluated', numerator=0, denominator=None,
            denominator_unit='candidate_operation_bindings', reasons=[
                'No operation-specific existing compiler/binder measurement performed; typed explanations alone are not bindings.']),
        start_consumption=dict(status='not_evaluated', numerator=0, denominator=None,
            denominator_unit='frozen_start_lanes', reasons=[
                'No validated source-bound Start consumption artifact reader integrated; no inferred lanes or Start invocation.']),
        targets=values, diagnostics=diagnostics, model_calls=0, platform_calls=0,
        publication_authorized=False, research_authorized=False, research_ready=False)
    json_path = _safe(root, paths['json'])
    markdown_path = _safe(root, paths['markdown'])
    markdown = _markdown(report)
    _write_report(json_path, report)
    markdown_path.write_text(markdown, encoding='utf-8')
    return report
