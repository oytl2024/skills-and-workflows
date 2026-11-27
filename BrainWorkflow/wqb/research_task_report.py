"""Script-owned terminal Markdown report; no model calls or parallel research ledger."""
import json
import math
import os
from pathlib import Path
import re
from uuid import uuid4

from wqb.lockfile import json_lock_transition_guard
from wqb.research_tasks import read_task, update_task, TERMINAL, _safe


POINT_FILES = frozenset({'all_alphas.jsonl', 'repair_attempts.jsonl'})
ERROR_FILES = frozenset({'run_errors.jsonl'})
POINT_KEYS = frozenset({'expression', 'regular', 'settings', 'alpha_id', 'expression_hash', 'parent_alpha_id',
    'parent_expression_hash', 'metrics', 'is', 'checks', 'failed', 'pending', 'hard_pass', 'score', 'signal',
    'status', 'outcome', 'decision', 'comparison', 'reason', 'node_id', 'arm_id', 'timestamp', 'created_at',
    'error', 'errors', 'benchmark_label', 'classification', 'check_summary'})
SECRET_KEYS = re.compile(r'password|credential|cookie|authorization|api_key|access_token|secret', re.I)


def _clean(value):
    """Input: report JSON value. Output: recursively sanitized JSON; do not export credentials or request URLs."""
    if type(value) is float and not math.isfinite(value):
        return 'UNDEFINED(' + str(value) + ')'
    if isinstance(value, dict):
        return {key: _clean(part) for key, part in value.items() if not SECRET_KEYS.search(str(key))}
    if isinstance(value, list):
        return [_clean(part) for part in value]
    if isinstance(value, str):
        value = re.sub(r'https?://\S+', '[request URL omitted]', value)
        return re.sub(r'(?i)(password|token|secret|api_key)\s*[:=]\s*[^\s,;]+', r'\1=[redacted]', value)
    return value


def _json_block(value) -> str:
    """Input: report JSON value. Output: complete safe Markdown JSON block; no point-count truncation."""
    return '\n```json\n' + json.dumps(_clean(value), ensure_ascii=False, indent=2, allow_nan=False).replace('```', '\\u0060\\u0060\\u0060') + '\n```\n'


def render_report(task: dict) -> str:
    """Input: terminal task dict. Output: Markdown trajectory/errors with explicit missing or unknown observations."""
    root = _safe(Path(task['runs_root']))
    points, errors, trees, repairs, finals, routing = [], [], [], [], [], []
    for path in sorted(root.rglob('*')):
        if path.is_symlink() or path.is_junction():
            raise ValueError('linked report evidence')
        if not path.is_file():
            continue
        if path.name in POINT_FILES | ERROR_FILES:
            with path.open(encoding='utf-8') as stream:
                for number, line in enumerate(stream, 1):
                    if not line.strip():
                        continue
                    try:
                        row = json.loads(line)
                        if not isinstance(row, dict):
                            raise ValueError('not an object')
                    except (ValueError, UnicodeError):
                        errors.append(dict(code='unreadable_observation', path=str(path.relative_to(root)), line=number))
                        continue
                    source = dict(path=str(path.relative_to(root)), line=number)
                    if path.name in POINT_FILES:
                        points.append(dict(source=source, **{key: row[key] for key in POINT_KEYS if key in row}))
                    else:
                        errors.append(dict(source=source, **{key: row[key] for key in ('code', 'error', 'error_type', 'exception_type', 'message', 'reason', 'stage', 'status', 'timestamp') if key in row}))
        elif path.name.startswith('tree-decision-') and path.suffix == '.json':
            try:
                row = json.loads(path.read_text(encoding='utf-8'))
                routing.append(dict(path=str(path.relative_to(root)), **{key: row[key] for key in
                    ('routes', 'comparisons', 'selected_node_ids', 'status', 'stop_reason') if key in row}))
            except (ValueError, TypeError):
                errors.append(dict(code='unreadable_routing_decision', path=str(path.relative_to(root))))
        elif path.name == 'experiment_tree.json' and path.parent.name == 'runtime':
            try:
                row = json.loads(path.read_text(encoding='utf-8'))
                trees.append(dict(path=str(path.relative_to(root)), tree={key: row[key]
                    for key in ('plan', 'tree', 'nodes', 'roots', 'node_states', 'status') if key in row}))
            except (ValueError, UnicodeError, TypeError):
                errors.append(dict(code='unreadable_tree', path=str(path.relative_to(root))))
        elif path.name == 'task.json' and path.parent.name == 'retrieval_research_planning':
            try:
                row = json.loads(path.read_text(encoding='utf-8'))
                answer = row.get('answer')
                if isinstance(answer, dict):
                    trees.append(dict(path=str(path.relative_to(root)), initial_design={key: answer[key]
                        for key in ('summary', 'designs', 'tree', 'data_characteristics') if key in answer}))
            except (ValueError, UnicodeError, TypeError):
                errors.append(dict(code='unreadable_initial_design', path=str(path.relative_to(root))))
        elif path.name in {'research_record.json', 'repair_execution.json', 'runtime_status.json'}:
            try:
                row = json.loads(path.read_text(encoding='utf-8'))
                if path.name == 'research_record.json':
                    finals.append(dict(path=str(path.relative_to(root)), **{key: row[key] for key in
                        ('candidate_gate', 'approved_queue', 'user_approval', 'manual_submission_status') if key in row}))
                    if isinstance(row.get('repair'), dict):
                        repairs.append(dict(path=str(path.relative_to(root)), repair=row['repair']))
                elif path.name == 'runtime_status.json' and row.get('status') in {'blocked', 'failed'}:
                    errors.append(dict(path=str(path.relative_to(root)), **{key: row[key] for key in ('status', 'reason', 'current_stage', 'recovery_case') if key in row}))
                elif path.name == 'repair_execution.json':
                    for attempt in row.get('attempts', []):
                        plan = attempt.get('plan', {})
                        repairs.append(dict(path=str(path.relative_to(root)),
                            **{key: attempt[key] for key in ('phase', 'status', 'trace', 'comparison', 'reason') if key in attempt},
                            variants=[{key: variant[key] for key in POINT_KEYS if key in variant} for variant in plan.get('variants', [])],
                            children=[{key: child[key] for key in POINT_KEYS if key in child} for child in attempt.get('children', [])]))
            except (ValueError, TypeError, KeyError):
                errors.append(dict(code='unreadable_runtime_record', path=str(path.relative_to(root))))
    metadata = {key: task[key] for key in ('task_id', 'selection', 'status', 'reason', 'created_at', 'ended_at')}
    metadata.update(report_version=1, point_count=len(points), error_count=len(errors))
    lines = ['<!-- research-task-report:v1 -->', '# ' + task['task_id'], _json_block(metadata),
        '## Initial Hypotheses And Planned Tree', _json_block(trees) if trees else 'No sealed tree was recorded.',
        '## Optimization Trajectory',
        'Every point below is a recorded observation, not proof of economic causality. Missing metrics or Alpha IDs remain unknown.']
    if not points:
        lines.append('No measured experiment was recorded; this is not evidence of no signal.')
    for index, point in enumerate(points, 1):
        lines.extend(['### Point ' + str(index), _json_block(point)])
    lines.extend(['## Branch Decisions And Fallbacks', _json_block(routing),
        '## Repair Decisions And Rollbacks', _json_block(repairs),
        '## Errors And Blockers', _clean(task.get('reason', '')) or 'No terminal cause recorded.',
        _json_block(errors), '## Final Outcome And Limitations',
        'Terminal status: ' + task['status'] + '. Qualification is only established by complete valid check evidence. '
        'Unknown external outcomes remain unresolved; this report grants no submission permission.', _json_block(finals)])
    return '\n\n'.join(lines) + '\n'


def publish_report(root: Path, task_id: str, knowledge: Path) -> Path:
    """Input: workspace runs Path/task ID/vault Path. Output: one idempotent terminal report Path, without models or raw copies."""
    task = read_task(root, task_id)
    if task['status'] not in TERMINAL:
        raise ValueError('report requires a terminal task')
    directory = _safe(Path(knowledge) / 'machine/researchreport')
    directory.mkdir(parents=True, exist_ok=True)
    path = _safe(directory / (task_id + '.md'))
    with json_lock_transition_guard(Path(task['runs_root']).parent / 'report', 5, .02, 'report publication busy'):
        if not path.exists():
            body = render_report(task)
            temporary = _safe(directory / ('.' + uuid4().hex + '.tmp'))
            try:
                temporary.write_text(body, encoding='utf-8')
                os.replace(temporary, path)
            finally:
                temporary.unlink(missing_ok=True)
        update_task(root, task_id, report_path=str(path), report_error='')
    return path


def load_report_records(knowledge: Path) -> list[dict]:
    """Input: vault Path. Output: in-memory research rows for existing summary readers; no duplicate ledger writes."""
    directory = _safe(Path(knowledge) / 'machine/researchreport')
    if not directory.exists():
        return []
    rows = []
    for path in sorted(directory.glob('*.md')):
        _safe(path)
        text = path.read_text(encoding='utf-8')
        if not text.startswith('<!-- research-task-report:v1 -->'):
            continue
        try:
            first = re.search(r'```json\n(.*?)\n```', text, re.S)
            metadata = json.loads(first.group(1))
            points = [json.loads(match) for match in re.findall(r'### Point \d+\s+```json\n(.*?)\n```', text, re.S)]
            if metadata['task_id'] != path.stem or metadata['status'] not in TERMINAL or len(points) != metadata['point_count']:
                raise ValueError('report metadata/point count mismatch')
            rows.append(dict(run_id=path.stem, objective=json.dumps(metadata['selection'], ensure_ascii=False),
                final_state=metadata['status'], synced_at=metadata['ended_at'], task_report_path=path.relative_to(knowledge).as_posix(),
                backtest=points, triage=[point for point in points if point.get('hard_pass') is False], repair={},
                candidate_gate=[point for point in points if point.get('hard_pass') is True],
                case_reason='near_miss' if points else 'representative_failure'))
        except (ValueError, KeyError, TypeError, AttributeError) as error:
            rows.append(dict(run_id=path.stem, final_state='report_parse_error', backtest=[], repair={},
                task_report_path=path.relative_to(knowledge).as_posix(), reason=str(error)))
    return rows
