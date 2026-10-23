"""Evidence-bound Repair judgments; no platform requests or authority changes."""

import hashlib
import json
import os
import re
from pathlib import Path

from wqb.ai_checkpoints import append_ai_checkpoint, run_ai_checkpoint
from wqb.runtime_control import _write, check_submission_allowed


MAX_HISTORY_ROWS = 8
MAX_KNOWLEDGE_ROWS = 4
MAX_CONTEXT_CHARS = 9000
MAX_PNL_POINTS = 120
DECAY_LIMIT = 32
TRUNCATION_LIMIT = 0.15
NEUTRALIZATIONS = ('SUBINDUSTRY', 'INDUSTRY', 'SECTOR', 'MARKET')
SEMANTIC_TEXT_CHARS = 320
SEMANTIC_LIST_ITEMS = 4
FIELD_SEMANTIC_KEYS = ('field_id', 'dataset_id', 'field_type', 'field_description', 'data_category',
                       'semantic_tags', 'region', 'delay', 'universe', 'source_quality', 'correlation_risk')
TEMPLATE_SEMANTIC_KEYS = ('template_id', 'hypothesis', 'interpretation', 'skeleton',
                          'required_field_types', 'operator_tags', 'repair_levers',
                          'known_antipatterns', 'correlation_risk', 'intended_direction')


class RepairPlanningBlocked(RuntimeError):
    """Input: explanation str. Output: exception. Required model judgment cannot safely execute."""


def _digest(value: object) -> str:
    """Input: JSON value. Output: SHA256 str. Bind a decision to immutable measured evidence."""
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def _verify_support(run: Path, evidence: dict) -> None:
    """Input: run Path and input dict. Output: None. Validate new supporting evidence, leaving legacy inputs intact."""
    support = evidence.get('supporting_evidence')
    if support is None:
        return
    if not isinstance(support, dict):
        raise RepairPlanningBlocked('AI Repair supporting evidence invalid')
    path = Path(str(support.get('path', ''))).resolve()
    if not path.is_relative_to((Path(run) / 'runtime/repair_decisions').resolve()) or not path.is_file():
        raise RepairPlanningBlocked('AI Repair supporting evidence outside bound directory or missing')
    if hashlib.sha256(path.read_bytes()).hexdigest() != support.get('sha256'):
        raise RepairPlanningBlocked('AI Repair supporting evidence changed')
    knowledge = evidence.get('knowledge') or {}
    if knowledge.get('sha256'):
        manifest = Path(run) / 'run_manifest.json'
        if not manifest.is_file() or hashlib.sha256(manifest.read_bytes()).hexdigest() != knowledge['sha256']:
            raise RepairPlanningBlocked('AI Repair immutable knowledge snapshot changed')


def _semantic_preview(row: dict, keys: tuple) -> dict:
    """Input: immutable row dict and allowed key tuple. Output: bounded semantic dict. Preserve provenance and explicitly mark lossy previews."""
    preview = {}
    shortened = []
    for key in keys:
        if key not in row:
            continue
        value = row[key]
        if isinstance(value, list):
            value = value[:SEMANTIC_LIST_ITEMS]
        if len(json.dumps(value)) > SEMANTIC_TEXT_CHARS:
            value = json.dumps(value)[:SEMANTIC_TEXT_CHARS]
        if value != row[key]:
            shortened.append(key)
        preview[key] = value
    preview.update(source_row_sha256=_digest(row), omitted_key_count=len(set(row) - set(keys)),
                   preview_only=True, shortened_keys=shortened)
    return preview


def _knowledge(run: Path, parent: dict) -> dict:
    """Input: run Path and parent dict. Output: bounded local context dict with source digest."""
    manifest = run / 'run_manifest.json'
    if not manifest.exists():
        return {'status': 'unavailable', 'reason': 'No immutable knowledge snapshot'}
    raw = manifest.read_bytes()
    snapshot = json.loads(raw).get('start_snapshot', {})
    identifiers = set(re.findall(r'[A-Za-z_][A-Za-z_0-9]*', parent['expression']))
    fields = [_semantic_preview(row, FIELD_SEMANTIC_KEYS) for row in snapshot.get('data_ledger_rows', [])
              if isinstance(row, dict) and row.get('field_id') in identifiers][:MAX_KNOWLEDGE_ROWS]
    compatible = set(snapshot.get('compatible_template_ids', []))
    templates = [_semantic_preview(row, TEMPLATE_SEMANTIC_KEYS) for row in snapshot.get('template_rows', [])
                 if isinstance(row, dict) and (not compatible or row.get('template_id') in compatible)][:MAX_KNOWLEDGE_ROWS]
    # No names inferred from expressions are treated as authoritative operator signatures.
    return {'status': 'available' if fields or templates else 'unavailable',
            'source_path': str(manifest), 'sha256': hashlib.sha256(raw).hexdigest(),
            'fields': fields, 'templates': templates, 'operator_signatures': 'unavailable'}


def validate_repair_decision(decision: dict, evidence: dict, *, strict_commands: bool = False) -> dict:
    """Input: model decision/evidence dicts. Output: validated child dict or stop. Reject unsupported edits."""
    parent = evidence['parent']
    if not isinstance(decision, dict) or any(decision.get(key) != parent[key]
            for key in ('parent_alpha_id', 'parent_expression_hash')):
        raise RepairPlanningBlocked('AI Repair parent identity differs from measured evidence')
    for key in ('diagnosis', 'economic_rationale', 'hypothesis', 'expected_improvement', 'risks'):
        if not isinstance(decision.get(key), str) or not decision[key].strip() or len(decision[key]) > 1600:
            raise RepairPlanningBlocked('AI Repair explanation missing or oversized: ' + key)
    if decision.get('action') == 'stop' and decision.get('edit') == 'none':
        if strict_commands and (type(decision.get('value')) not in (int, float) or decision['value'] != 0):
            raise RepairPlanningBlocked('AI Repair stop must use edit=none and value=0')
        return {'action': 'stop'}
    if decision.get('action') != 'test':
        raise RepairPlanningBlocked('AI Repair action must be test or stop')
    if evidence.get('schema_version', 1) >= 2:
        from wqb.repair_trace import validate_experiment_target
        try:
            validate_experiment_target(decision, parent)
        except ValueError as exc:
            raise RepairPlanningBlocked(str(exc)) from exc
    settings = dict(parent['settings'])
    expression = parent['expression']
    edit, value = decision.get('edit'), decision.get('value')
    if edit == 'decay' and type(value) in (int, float) and 0 <= value <= DECAY_LIMIT and value == int(value):
        settings['decay'] = int(value)
    elif edit == 'neutralization' and value in NEUTRALIZATIONS:
        settings['neutralization'] = value
    elif edit == 'truncation' and type(value) in (float, int) and 0 < value <= TRUNCATION_LIMIT:
        settings['truncation'] = value
    elif edit == 'flip_direction' and value == -1 and type(value) in (int, float):
        expression = '-(' + expression + ')'
    else:
        raise RepairPlanningBlocked('Unsupported or unproven AI Repair edit')
    identity = _digest([expression, settings])
    used = {_digest([parent['expression'], parent['settings']])}
    used.update(row.get('expression_hash') for row in evidence['history'])
    if identity in used:
        raise RepairPlanningBlocked('AI Repair plan duplicates parent or a measured child')
    return {'expression': expression, 'settings': settings, 'expression_hash': identity,
            'parent_alpha_id': parent['parent_alpha_id'],
            'parent_expression_hash': parent['parent_expression_hash'], 'repair_action': 'ai_' + edit}


def _judgment_matches(saved: dict, evidence: dict, source_path: Path) -> bool:
    """Input: saved receipt/evidence dicts and original path. Output: bool. Bind raw or derived decisions."""
    judgment = saved.get('judgment', {})
    if judgment.get('status') != 'completed':
        return False
    normalization = saved.get('normalization')
    if normalization is None:
        return judgment.get('decision') == saved.get('decision')
    if (not isinstance(normalization, dict)
            or not isinstance(normalization.get('source_path'), str)
            or not isinstance(normalization.get('source_sha256'), str)):
        return False
    from wqb.repair_output_contract import normalize_legacy_decision, NORMALIZATION_POLICY
    if (normalization.get('policy') != NORMALIZATION_POLICY
            or Path(normalization.get('source_path', '')).resolve() != source_path.resolve()
            or not source_path.is_file()
            or hashlib.sha256(source_path.read_bytes()).hexdigest() != normalization.get('source_sha256')):
        return False
    original = json.loads(source_path.read_text(encoding='utf-8'))
    if (original.get('status') != 'blocked' or original.get('evidence_digest') != _digest(evidence)
            or original.get('judgment') != judgment):
        return False
    try:
        return normalize_legacy_decision(judgment['decision'], evidence['parent'],
            evidence['history'], evidence['allowance']) == saved.get('decision')
    except (KeyError, ValueError, TypeError):
        return False


def _recover_format_receipt(source_path: Path, saved: dict, evidence: dict) -> dict:
    """Input: rejected receipt path/dict and evidence. Output: validated derived receipt. Never overwrite original judgment."""
    from wqb.repair_output_contract import normalize_legacy_decision, NORMALIZATION_POLICY
    if (saved.get('evidence_digest') != _digest(evidence) or saved.get('status') != 'blocked'
            or saved.get('reason') != 'AI Repair action must be test or stop'
            or saved.get('judgment', {}).get('status') != 'completed'):
        raise RepairPlanningBlocked('AI Repair receipt invalid or failed; maintenance required')
    try:
        decision = normalize_legacy_decision(saved['judgment']['decision'], evidence['parent'],
            evidence['history'], evidence['allowance'])
    except (KeyError, TypeError, ValueError) as exc:
        raise RepairPlanningBlocked('AI Repair output cannot be safely normalized') from exc
    variant = validate_repair_decision(decision, evidence, strict_commands=True)
    derived_path = source_path.with_name(source_path.stem + '.normalized.json')
    expected = {'evidence_digest': _digest(evidence), 'status': 'validated', 'decision': decision,
        'judgment': saved['judgment'], 'receipt_path': str(derived_path), 'command_contract_version': 1,
        'variants': [] if variant.get('action') == 'stop' else [variant],
        'normalization': {'policy': NORMALIZATION_POLICY, 'source_path': str(source_path),
                          'source_sha256': hashlib.sha256(source_path.read_bytes()).hexdigest()}}
    if derived_path.exists():
        existing = json.loads(derived_path.read_text(encoding='utf-8'))
        if (existing.get('status') not in {'validated', 'consumed'}
                or {k: v for k, v in existing.items() if k != 'status'} !=
                   {k: v for k, v in expected.items() if k != 'status'}):
            raise RepairPlanningBlocked('AI Repair normalized receipt changed')
        return existing
    _write(derived_path, expected)
    return expected


def prepare_repair_decision(run: Path, parent: dict, history: list[dict], allowance: int, config: dict, now: str) -> dict:
    """Input: run/parent/history/budget/config/time. Output: persisted validated single-change decision."""
    from wqb.workflow_driver import resolve_ai_executor_argv
    check_submission_allowed()
    if type(allowance) is not int or allowance < 1 or allowance > 8:
        raise RepairPlanningBlocked('AI Repair allowance must be 1..8')
    clean_parent = {key: parent.get(key) for key in ('expression', 'settings', 'metrics', 'failed')}
    clean_parent.update(parent_alpha_id=parent['alpha_id'], parent_expression_hash=parent['expression_hash'])
    if not isinstance(clean_parent['settings'], dict) or not isinstance(clean_parent['expression'], str):
        raise RepairPlanningBlocked('AI Repair requires exact parent settings and expression')
    clean_history = [{key: row.get(key) for key in ('alpha_id', 'expression_hash', 'expression', 'settings', 'metrics', 'failed', 'hard_pass')}
                     for row in history[-MAX_HISTORY_ROWS:]]
    pnl = parent.get('pnl')
    pnl_evidence = {'status': 'unavailable'}
    if isinstance(pnl, list) and all(type(point) in (int, float) for point in pnl):
        pnl_evidence = {'status': 'available', 'source': 'checked_parent.pnl', 'points': pnl[-MAX_PNL_POINTS:]}
    evidence = {'schema_version': 2, 'parent': clean_parent, 'history': clean_history, 'allowance': allowance,
                'knowledge': _knowledge(Path(run), parent), 'pnl': pnl_evidence,
                'allowed_edits': {'decay': [0, DECAY_LIMIT], 'neutralization': NEUTRALIZATIONS,
                                  'truncation': [0, TRUNCATION_LIMIT], 'flip_direction': -1}}
    directory = Path(run) / 'runtime/repair_decisions'
    from wqb.repair_brief import build_repair_brief
    # Full measured payload is durable evidence, not the default model prompt.
    supporting_raw = json.loads(json.dumps(evidence | {'raw_parent': parent, 'raw_history': history}, sort_keys=True))
    raw_digest = _digest(supporting_raw)
    supporting_path = directory / (raw_digest + '.support.json')
    if supporting_path.exists():
        expected_bytes = json.dumps(supporting_raw, ensure_ascii=False, indent=2).replace('\n', os.linesep).encode('utf-8')
        if supporting_path.read_bytes() != expected_bytes:
            raise RepairPlanningBlocked('AI Repair supporting evidence changed')
    else:
        _write(supporting_path, supporting_raw)
    evidence['brief'] = build_repair_brief(evidence)
    evidence['supporting_evidence'] = {'path': str(supporting_path),
        'sha256': hashlib.sha256(supporting_path.read_bytes()).hexdigest()}
    _verify_support(Path(run), evidence)
    if len(json.dumps(evidence['brief'])) > MAX_CONTEXT_CHARS:
        raise RepairPlanningBlocked('AI Repair brief exceeds bounded evidence input')
    digest = _digest(evidence)
    path = directory / (digest + '.json')
    if path.exists():
        saved = json.loads(path.read_text(encoding='utf-8'))
        if saved.get('status') == 'blocked':
            return _recover_format_receipt(path, saved, evidence)
        if saved.get('evidence_digest') != digest or saved.get('status') not in {'validated', 'consumed'}:
            raise RepairPlanningBlocked('AI Repair receipt invalid or failed; maintenance required')
        if not _judgment_matches(saved, evidence, path):
            raise RepairPlanningBlocked('AI Repair receipt differs from completed model judgment')
        variant = validate_repair_decision(saved['decision'], evidence, strict_commands=saved.get('command_contract_version') == 1)
        if saved['variants'] != ([] if variant.get('action') == 'stop' else [variant]):
            raise RepairPlanningBlocked('AI Repair validated payload was changed')
        return saved
    argv = resolve_ai_executor_argv(config)
    if not argv:
        raise RepairPlanningBlocked('AI Repair executor is required; no silent rule fallback')
    input_path = directory / (digest + '.input.json')
    _write(input_path, evidence)
    checkpoint = append_ai_checkpoint(Path(run) / 'stages/ai', 'repair_decision',
        'Read the supporting evidence for exact parent identity/expression/settings, failed checks and '
        'previous edits before deciding; consult immutable run_manifest knowledge when semantics are unclear. '
        'Diagnose this near miss using measured results and local semantics. Return decision with exact '
        'parent_alpha_id, parent_expression_hash, diagnosis, economic_rationale, hypothesis, '
        'expected_improvement, risks, action(test/stop), edit(decay/neutralization/truncation/flip_direction/none), '
        'value, target_metric(sharpe/fitness/turnover), target_direction(increase/increase/decrease respectively), '
        'falsification, applicability. Target must have a finite measured baseline. Falsification states '
        'what would refute the hypothesis; applicability states data/template conditions and counterexamples. '
        'Change exactly one property, compare previous tests, or stop. Concise evidence-based rationale only; '
        'no private reasoning transcript. No platform or authority changes.',
        [str(input_path)], now)
    judgment = run_ai_checkpoint(Path(run) / 'stages/ai', checkpoint.checkpoint_id, argv, cancel_on_pause=True)
    decision = judgment.get('decision')
    try:
        if judgment.get('status') != 'completed':
            raise RepairPlanningBlocked('AI Repair worker did not complete')
        _verify_support(Path(run), evidence)
        variant = validate_repair_decision(decision, evidence, strict_commands=True)
    except RepairPlanningBlocked as exc:
        _write(path, {'evidence_digest': digest, 'status': 'blocked', 'judgment': judgment, 'reason': str(exc)})
        if str(exc) == 'AI Repair action must be test or stop':
            return _recover_format_receipt(path, json.loads(path.read_text(encoding='utf-8')), evidence)
        raise
    receipt = {'evidence_digest': digest, 'status': 'validated', 'decision': decision,
               'judgment': judgment, 'receipt_path': str(path), 'command_contract_version': 1,
               'variants': [] if variant.get('action') == 'stop' else [variant]}
    _write(path, receipt)
    return receipt


def verify_consumed_plan(run: Path, plan: dict) -> dict:
    """Input: run Path and scheduled plan dict. Output: verified receipt. Reconcile lifecycle only, never payload edits."""
    if plan.get('planner_kind') == 'deterministic':
        from wqb.repair_search import verify_persisted_search
        return verify_persisted_search(run, plan)
    digest = str(plan.get('evidence_digest', ''))
    if len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
        raise RepairPlanningBlocked('AI Repair evidence digest invalid')
    directory = Path(run) / 'runtime/repair_decisions'
    path = directory / (digest + '.json')
    receipt_path = directory / (digest + '.normalized.json') if plan.get('normalization') else path
    if Path(plan.get('receipt_path', '')).resolve() != receipt_path.resolve():
        raise RepairPlanningBlocked('AI Repair receipt outside expected identity')
    saved = json.loads(receipt_path.read_text(encoding='utf-8'))
    evidence = json.loads((directory / (digest + '.input.json')).read_text(encoding='utf-8'))
    _verify_support(Path(run), evidence)
    if _digest(evidence) != digest or saved.get('evidence_digest') != digest:
        raise RepairPlanningBlocked('AI Repair evidence changed')
    if any(saved.get(k) != v for k, v in plan.items() if k != 'status') or saved.get('status') not in {'validated', 'consumed'}:
        raise RepairPlanningBlocked('AI Repair immutable payload changed')
    if not _judgment_matches(saved, evidence, path):
        raise RepairPlanningBlocked('AI Repair judgment binding changed')
    variant = validate_repair_decision(saved['decision'], evidence, strict_commands=saved.get('command_contract_version') == 1)
    if saved['variants'] != ([] if variant.get('action') == 'stop' else [variant]):
        raise RepairPlanningBlocked('AI Repair variants differ from validated judgment')
    return saved
