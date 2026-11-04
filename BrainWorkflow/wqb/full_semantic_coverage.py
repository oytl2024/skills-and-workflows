"""Read-only K5 measurements; only machine/reports is an output boundary.

An explanation is not a publication, a binder result or a frozen Start lane.
There is deliberately no invented binder/Start receipt protocol in this helper.
"""

from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4

from wqb.full_semantic_compile import _bytes, _digest, _hash, _json, inventory_reference_base
from wqb.full_semantic_execution import (
    HASH, _read, _ref, _root, _verify_state,
    load_bound_explanation_job, validate_full_semantic_output,
)
from wqb.knowledge_age_policy import KNOWLEDGE_MAX_AGE_DAYS
from wqb.semantic_compilation import MAX_OUTPUT_BYTES, _safe


REPORT_VERSION = 2
MAX_REASON_CHARS = 600
MAX_INVENTORY_LINE_BYTES = 16 * 1024 * 1024
MAX_CONSUMER_REQUESTS = 32
MAX_CONSUMER_TEMPLATES = 30
MAX_CONSUMER_MANIFEST_BYTES = 16 * 1024 * 1024
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
    inventory_reference_base(saved)
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


def _shared_targets(root: Path, values: list[dict]) -> dict:
    """Input: safe vault Path/validated targets list. Output: immutable JSONL reference; share unchanged details."""
    directory = _safe(root, 'machine/reports/semantic_targets')
    directory.mkdir(parents=True, exist_ok=True)
    staged = _safe(root, 'machine/reports/semantic_targets/' + uuid4().hex + '.tmp')
    digest = hashlib.sha256()
    try:
        with staged.open('xb') as stream:
            for row in values:
                raw = _bytes(row) + b'\n'
                digest.update(raw)
                stream.write(raw)
        sha256 = digest.hexdigest()
        relative = 'machine/reports/semantic_targets/' + sha256 + '.jsonl'
        target = _safe(root, relative)
        try:
            os.link(staged, target)
        except FileExistsError:
            with _safe(root, relative).open('rb') as stream:
                if hashlib.file_digest(stream, 'sha256').hexdigest() != sha256:
                    raise ValueError('immutable coverage target details differ')
        return dict(path=relative, sha256=sha256, row_count=len(values))
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


def _validate_explanation(root: Path, job: dict, cached: dict, *, verification_session=None) -> dict:
    """Input: vault/authenticated job/cached result dict. Output: canonical read-only validated targets by ID."""
    reconstructed = validate_full_semantic_output(root, job,
        dict(summary=cached['summary'], targets=cached['targets']), persist_field_results=False,
        _verification_session=verification_session)
    if _bytes(reconstructed) != _bytes(cached):
        raise ValueError('completed explanation envelope differs from canonical validation')
    return {target['target_id']: target for target in reconstructed['targets']}


def _report_field_session(root: Path, jobs: list):
    """Input: vault Path/bound job references. Output: shared extraction session or None; authentication remains per job."""
    from wqb.knowledge_contracts import verify_field_source_extracts
    paths = set()
    for ref in jobs:
        try:
            raw = _ref(root, dict(path=ref['path'], sha256=ref['sha256']),
                       MAX_OUTPUT_BYTES, 'machine/semantic_jobs/' + ref['job_id'])
            manifest = _json(raw.decode('utf-8'))
            for material in manifest['materials']:
                path = material['source_index']['path']
                if isinstance(path, str) and Path(path).name.startswith('semantic-subset-'):
                    paths.add(path)
        except ARTIFACT_ERRORS:
            # Normal per-job verification below retains the precise rejection.
            continue
    return verify_field_source_extracts(root, sorted(paths)) if paths else None


def _consumer_measurements(root: Path, targets: dict, binding_requests, consumer_run_dirs) -> tuple[dict, dict]:
    """Input: vault/inventory/optional explicit operation and run lists. Output: read-only binder and frozen-Start measurements."""
    from wqb.knowledge_compile import _audit_resource_rows, semantic_resource_coverage
    from wqb.knowledge_paths import machine_resource_path
    from wqb.preplanned_start import _source_context
    from wqb.research_tree import _load
    from wqb.template_binding import _scope_matches
    bindings = dict(status='not_evaluated', numerator=0, denominator=None,
        denominator_unit='candidate_operation_bindings', reasons=['No explicit source-bound binding requests supplied.'])
    starts = dict(status='not_evaluated', numerator=0, denominator=None,
        denominator_unit='frozen_start_lanes', reasons=['No explicit existing frozen Start lanes supplied.'])
    for requests in (binding_requests, consumer_run_dirs):
        if requests is not None and (not isinstance(requests, list) or len(requests) > MAX_CONSUMER_REQUESTS):
            raise ValueError('consumer requests require a bounded explicit list')
    if binding_requests is not None:
        wanted, canonical, index, seen = set(), {}, {}, set()
        for request in binding_requests:
            if (not isinstance(request, dict) or set(request) != {'resources', 'templates'}
                    or not isinstance(request['templates'], list) or len(request['templates']) > MAX_CONSUMER_TEMPLATES):
                raise ValueError('binding request requires bounded resources/templates')
            for row in request['resources']['field_rows']:
                wanted.add((row['dataset_id'], row['field_id']))
        for row in _audit_resource_rows(machine_resource_path(root, 'data_ledger'), root):
            key = (row.get('dataset_id'), row.get('field_id'))
            if key in wanted:
                canonical.setdefault(key, []).append(row)
        for source in _audit_resource_rows(machine_resource_path(root, 'source_index'), root):
            if source['path'] in index:
                raise ValueError('duplicate canonical source index path')
            index[source['path']] = source
        bindings.update(status='measured', denominator=0, reasons=[])
        for request in binding_requests:
            resources = request['resources']
            consumed = {key: resources[key] for key in ('field_rows', 'operator_rows',
                'source_index', 'source_texts')}
            consumed['scope'] = resources['evidence_pack']['scope']
            consumed['resource_contract_version'] = resources.get('resource_contract_version', 1)
            templates = []
            for template in request['templates']:
                identity = _digest(dict(resources=consumed, template=template))
                if identity not in seen:
                    seen.add(identity)
                    templates.append(template)
            bindings['denominator'] += len(templates)
            if not templates:
                continue
            try:
                scope = resources['evidence_pack']['scope']
                for row in resources['field_rows']:
                    rows = [r for r in canonical.get((row['dataset_id'], row['field_id']), []) if _scope_matches(r, scope)]
                    if len(rows) != 1 or _digest(rows[0]) != _digest(row):
                        raise ValueError('binding field differs from exact canonical selection')
                texts = _source_context(root, resources['source_index'], index)
                if texts != resources['source_texts']:
                    raise ValueError('binding material differs from current source bytes')
                if _freshness(resources['source_index'], datetime.now(timezone.utc)) != 'current':
                    raise ValueError('binding sources are stale or have invalid capture dates')
                measured = semantic_resource_coverage(dict(knowledge_root=root,
                    resource_contract_version=resources.get('resource_contract_version', 1),
                    field_rows=resources['field_rows'], operator_rows=resources['operator_rows'],
                    template_rows=templates, source_index=list(resources['source_index'].values())), scope)
                bindings['numerator'] += measured['executable_bindings']
                bindings['reasons'].extend(measured['reasons'])
            except ARTIFACT_ERRORS as error:
                bindings['reasons'].append(dict(reason=str(error)[:MAX_REASON_CHARS]))
    if consumer_run_dirs is not None:
        starts.update(status='measured', denominator=0, reasons=[])
        seen = set()
        for supplied in consumer_run_dirs:
            run = Path(supplied).absolute()
            try:
                key = _root(run)
            except ARTIFACT_ERRORS:
                key = ('invalid', run)
            if key in seen:
                continue
            seen.add(key)
            starts['denominator'] += 1
            try:
                run = _root(run)
                if not run.is_relative_to(root.parent / 'runs'):
                    raise ValueError('consumer run must be in the owning workspace runs directory')
                manifest_path = _safe(run, 'run_manifest.json')
                if manifest_path.stat().st_size > MAX_CONSUMER_MANIFEST_BYTES:
                    raise ValueError('consumer manifest exceeds safe read bound')
                before = manifest_path.read_bytes()
                if len(before) > MAX_CONSUMER_MANIFEST_BYTES:
                    raise ValueError('consumer manifest exceeds safe read bound')
                manifest = _json(before.decode('utf-8'))
                if _root(Path(manifest['knowledge_root'])) != root:
                    raise ValueError('consumer run belongs to a different knowledge vault')
                attachment, snapshot = _load(run)
                for row in snapshot['data_ledger_rows']:
                    identity = dict(dataset_id=row['dataset_id'], field_id=row['field_id'])
                    if 'field:' + _digest(identity) not in targets:
                        raise ValueError('consumer field is outside the measured inventory')
                if manifest_path.read_bytes() != before or _load(run) != (attachment, snapshot):
                    raise ValueError('consumer evidence changed during validation')
                starts['numerator'] += 1
            except ARTIFACT_ERRORS as error:
                starts['reasons'].append(dict(run_id=run.name, reason=str(error)[:MAX_REASON_CHARS]))
    return bindings, starts


def _markdown(report: dict) -> str:
    """Input: report dict. Output: bounded summary Markdown str, never a full field ledger."""
    inventory, explanations = report['inventory'], report['explanations']
    lines = ['# Full Semantic Coverage', '',
        '| Layer | Measured numerator / denominator | Status |',
        '| --- | --- | --- |',
        f"| Inventory: source-byte-validated targets | {inventory['numerator']} / {inventory['denominator']} | {inventory['status']} |",
        f"| Current validated explanations | {explanations['numerator']} / {explanations['denominator']} | {explanations['status']} |",
        f"| Compiler/binder candidate operations | {report['compiler_binder']['numerator']} / {report['compiler_binder']['denominator']} | {report['compiler_binder']['status']} |",
        f"| Actual frozen Start lanes | {report['start_consumption']['numerator']} / {report['start_consumption']['denominator']} | {report['start_consumption']['status']} |", '',
        f"Processed: {explanations['processed']}; documented targets: {explanations['documented_targets']}; "
        f"hypothesis targets: {explanations['hypothesis_targets']}; unattempted: {explanations['unattempted']}.", '',
        'Inventory includes blocked and unattempted identities. Byte validation is not freshness or scope certification.',
        'Processing is not semantic completeness. Hypotheses are not documented facts.',
        'Compiler/binder coverage measures only explicit source-bound operation requests, not all possible formulas.',
        'Start coverage validates explicit existing frozen lane artifacts without starting or resuming a mission.',
        'Unknown denominators are not zero-sized success. No publication, Start, model or platform calls occurred.', '',
        f"Detailed evidence: [{Path(report['report_paths']['json']).name}]({Path(report['report_paths']['json']).name})", '']
    return '\n'.join(lines)


def build_full_semantic_report(root: Path, plan: dict, *, binding_requests=None, consumer_run_dirs=None,
                               detailed: bool = False) -> dict:
    """Input: knowledge-root Path/authenticated K4 plan dict. Output: four-level report dict and JSON/Markdown files.

    Only machine/reports is written. Invalid plans raise before report creation;
    individual missing/stale/tampered jobs remain explicit denominator entries.
    Binder and Start denominators stay unknown until existing consumer validators
    are integrated; claimed flags or execution_result summaries are never evidence.
    """
    if type(detailed) is not bool:
        raise ValueError('detailed must be boolean')
    root = _root(root)
    saved, targets = _report_inventory(root, plan)
    plans = {saved['content_key']: saved}
    now = datetime.now(timezone.utc)
    diagnostics = list(saved.get('diagnostics', []))
    field_session = _report_field_session(root, saved['jobs'])
    for ref in saved['jobs']:
        base = 'machine/semantic_jobs/' + ref['job_id']
        ids = ref['target_ids']
        try:
            raw = _ref(root, dict(path=ref['path'], sha256=ref['sha256']), MAX_OUTPUT_BYTES, base)
            job = load_bound_explanation_job(_safe(root, base), _verification_session=field_session)
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
            checked = _validate_explanation(root, job, cached, verification_session=field_session)
            try:
                if load_bound_explanation_job(_safe(root, base), _verification_session=field_session) != job:
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
    bindings, consumption = _consumer_measurements(root, targets, binding_requests, consumer_run_dirs)
    if field_session is not None:
        field_session.finalize()
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
        compiler_binder=bindings,
        start_consumption=consumption,
        targets_ref=_shared_targets(root, values), diagnostics=diagnostics, model_calls=0, platform_calls=0,
        publication_authorized=False, research_authorized=False, research_ready=False)
    json_path = _safe(root, paths['json'])
    markdown_path = _safe(root, paths['markdown'])
    markdown = _markdown(report)
    _write_report(json_path, report)
    markdown_path.write_text(markdown, encoding='utf-8')
    if detailed:
        report['targets'] = values
    return report
