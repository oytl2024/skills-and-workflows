"""Authenticated, one-shot initial planning through the existing readonly worker."""

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from wqb import ai_checkpoints, initial_research_planning as planning
from wqb.exploration_eligibility import _digest, _resource_certificate, verify_exploration
from wqb.lockfile import json_lock_transition_guard
from wqb.semantic_compilation import _check_schema, _safe


MAX_PROJECTION_BYTES = 12000
CHECKPOINT_TYPE = 'initial_research_plan'


def _authenticated_task(run: Path) -> dict:
    """Input: owning run Path. Output: task dict; verify running state, raw, certificate and schema."""
    task = planning._load_task(_safe(run, planning.TASK_PATH))
    if task is None or task['status'] != 'running':
        raise ValueError('initial planning requires a running coordinator task')
    manifest, brief, certificate = task['manifest'], task['brief'], task['certificate']
    if planning._read(_safe(run, 'run_manifest.json')) != manifest:
        raise ValueError('initial planning manifest changed')
    if (task.get('schema_version') != 1 or not isinstance(task.get('input_sha256'), str)
            or len(task['input_sha256']) != 64):
        raise ValueError('invalid initial planning task identity')
    int(task['input_sha256'], 16)
    cert_hash = certificate['content_sha256']
    if cert_hash != _digest({k: v for k, v in certificate.items() if k != 'content_sha256'}):
        raise ValueError('initial planning certificate hash mismatch')
    if planning._read(_safe(run, 'runtime/exploration/resources/' + cert_hash + '.json')) != certificate:
        raise ValueError('initial planning stored certificate changed')
    resources = dict(source_index=brief['sources'], source_texts=brief['source_texts'],
        field_rows=brief['data_traits'], operator_rows=brief['operator_rows'], evidence_pack=brief['evidence_pack'])
    version = resources['evidence_pack'].get('resource_contract_version', 1)
    if version != 1:
        resources['resource_contract_version'] = version
    current = _resource_certificate(run, Path(manifest['knowledge_root']), resources, manifest['selected_scope'])
    for key in ('owning_run', 'policy', 'scope', 'sources', 'source_index_sha256'):
        if current[key] != certificate[key]:
            raise ValueError('initial planning raw certification changed: ' + key)
    expected = planning._brief(resources, manifest, certificate, [],
        planning._policy(dict(plan_depth=brief['plan_depth'], initial_hypotheses=brief['max_width'])))
    receipts = brief['compatible_template_receipts']
    if not isinstance(receipts, list):
        raise ValueError('initial planning template receipts must be a list')
    for claimed in receipts:
        receipt = verify_exploration(claimed)
        inputs = receipt['compiler_input']
        if (inputs['scope'] != certificate['scope']
                or _digest(inputs['resources']) != certificate['resources_sha256']
                or any(inputs['resources'].get(key) != value for key, value in resources.items())):
            raise ValueError('initial planning template differs from certified resources')
        expected['compatible_template_receipts'].append(receipt)
    if expected != brief:
        raise ValueError('initial planning brief or output schema changed')
    return task


def initial_model_projection(run: Path) -> dict:
    """Input: owning run Path. Output: bounded JSON-pointer index; never inline full raw or designs."""
    run = Path(run).resolve(strict=True)
    task = _authenticated_task(run)
    brief = task['brief']
    path = _safe(run, planning.TASK_PATH)
    references = {}
    for key in ('source_texts', 'sources', 'data_traits', 'operator_rows', 'evidence_pack',
                'compatible_template_receipts', 'composition_contract', 'output_schema'):
        references[key] = '/brief/' + key
    references['source_texts'] = {name: '/brief/source_texts/' + name.replace('~', '~0').replace('/', '~1')
                                for name in brief['source_texts']}
    projection = dict(task=dict(path=planning.TASK_PATH, sha256=hashlib.sha256(path.read_bytes()).hexdigest()),
        input_sha256=task['input_sha256'], scope=brief['scope'], measurement_period=brief['measurement_period'],
        plan_depth=brief['plan_depth'], max_width=brief['max_width'], references=references)
    if len(json.dumps(projection, ensure_ascii=False).encode('utf-8')) > MAX_PROJECTION_BYTES:
        raise ValueError('oversized initial model reference index')
    return projection


def create_initial_model_runner(run: Path, config: dict):
    """Input: owning run Path/config dict. Output: callable(dict)->dict; one cancellable readonly model task."""
    from wqb.workflow_driver import resolve_ai_executor_argv
    run = Path(run).absolute()
    if any(p.is_symlink() or p.is_junction() for p in (run, *run.parents)):
        raise ValueError('initial model run cannot traverse links')
    run = run.resolve(strict=True)
    if config.get('ai_executor') != 'codex':
        raise ValueError('initial planning requires the readonly Codex executor')
    argv = resolve_ai_executor_argv(dict(ai_executor='codex'))
    request_path = _safe(run.parent, 'console_start/request.json')
    request = planning._read(request_path) if request_path.exists() else None
    from wqb.research_group import group_for_run
    group_intent = group_for_run(run)

    def cancelled() -> bool:
        """Input: none. Output: bool; preserve planning Stop and bound Start identity, not initial runtime Pause."""
        if group_intent is not None:
            current_group = group_for_run(run)
            if (current_group is None or current_group.get('group_id') != group_intent.get('group_id')
                    or current_group.get('request_revision') != group_intent.get('request_revision')):
                return True
        control = _safe(run, 'runtime/initial_research_planning/control.json')
        if control.exists() and planning._read(control).get('cancelled'):
            return True
        if request is not None:
            if not request_path.exists():
                return True
            current = planning._read(_safe(run.parent, 'console_start/request.json'))
            return (current.get('request_id') != request.get('request_id')
                    or current.get('status') not in ('preparing', 'validating'))
        return request_path.exists()

    def runner(brief: dict) -> dict:
        """Input: coordinator brief dict. Output: full strict answer dict; never replay an existing checkpoint."""
        if cancelled():
            raise RuntimeError('initial planning cancelled')
        task = _authenticated_task(run)
        if brief != task['brief']:
            raise ValueError('callback brief differs from authenticated task')
        directory = _safe(run, 'stages/ai')
        directory.mkdir(parents=True, exist_ok=True)
        with json_lock_transition_guard(directory / 'initial_model_guard', 5.0, 0.05, 'initial model busy'):
            if any(row['checkpoint_type'] == CHECKPOINT_TYPE for row in ai_checkpoints.load_ai_checkpoints(directory)):
                raise ValueError('initial model checkpoint already exists; no replay')
            checkpoint = ai_checkpoints.append_ai_checkpoint(directory, CHECKPOINT_TYPE,
                'Plan the entire sourced experiment tree before execution.', [planning.TASK_PATH],
                datetime.now(timezone.utc).isoformat())
        result = ai_checkpoints.run_ai_checkpoint(directory, checkpoint.checkpoint_id, argv,
            cancellation_check=cancelled, cancel_on_pause=False)
        if result['status'] != 'completed':
            raise RuntimeError('initial model checkpoint ' + result['status'] + ': ' + str(result.get('error', '')))
        _authenticated_task(run)
        answer = {key: deepcopy(result[key]) for key in ('summary', 'designs', 'tree')}
        _check_schema(task['brief']['output_schema'], answer)
        return answer

    return runner
