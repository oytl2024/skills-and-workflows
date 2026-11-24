"""One durable pre-execution design task with bounded local knowledge tools."""
from copy import deepcopy
from datetime import datetime, timezone
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

from wqb.lockfile import json_lock_transition_guard
from wqb.runtime_control import _write
from wqb.semantic_compilation import _check_schema, _digest, _safe


TASK_PATH = 'runtime/retrieval_research_planning/task.json'
CHECKPOINT_TYPE = 'retrieval_research_plan'
MAX_TASK_BYTES = 16_000_000
MAX_TOOL_ARGUMENT_BYTES = 64_000
MAX_SELECTION = 30
MAX_HISTORY_SELECTION = 12
LOCK_SECONDS = 5.0
LOCK_POLL_SECONDS = 0.05
CONFIG_KEYS = ('instrument_type', 'region', 'delay', 'universe', 'decay', 'neutralization',
    'truncation', 'pasteurization', 'unit_handling', 'nan_handling', 'language',
    'measurement_period', 'research_policy', 'repair_search_policy',
    'retrieval_excluded_selections', 'retrieval_owner', 'retrieval_max_queries',
    'retrieval_max_validations', 'retrieval_max_returned_bytes')
TOOL_CONTRACTS = {
    'fields': dict(arguments=dict(query='AND-matched text tokens; empty enumerates catalog',
        field_type='optional MATRIX/VECTOR/GROUP', offset='integer >=0', limit='integer 1..50',
        identities='optional exact [[dataset_id,field_id]], excludes query/type'),
        purpose='Exact-scope field cards; role_selector is an identity, not economic meaning.'),
    'operators': dict(arguments=dict(query='text', operator='optional exact name', offset='integer >=0', limit='1..50'),
        purpose='Current account catalog with source references; unknown typed signature is not fabricated.'),
    'templates': dict(arguments=dict(query='text', template_id='optional exact ID', offset='integer >=0', limit='1..50'),
        purpose='Existing mechanism/condition templates; review status is preserved, not granted.'),
    'experience': dict(arguments=dict(query='text', mechanism_family='optional exact mechanism',
        experiment_id='optional exact ID', include_other_scopes='optional boolean; default false',
        offset='integer >=0', limit='1..50'),
        purpose='Include failures/inconclusive results. Cross-scope results are transfer ideas, not target-scope proof.'),
    'source': dict(arguments=dict(path='indexed raw source path', start='character offset >=0', length='1..8000'),
        purpose='Verified source excerpt and provenance; follow next_start for more.'),
    'validate': dict(arguments=dict(selection='[{dataset_id,field_id}]',
        design='optional one structured hypothesis', answer='optional complete answer excluding selection',
        history_selection='optional [{group_id,view_sha256}]; context, never causal proof'),
        purpose='Without a design returns resource/trait context only; with draft compiles offline, never simulates.'),
}


def design_schema() -> dict:
    """Input: none. Output: strict complete-tree schema plus exact selected field identities."""
    from wqb.initial_research_planning import _output_schema, _annotation_schema
    schema = _output_schema(2, include_vector=True)
    text = {'type': 'string'}
    schema['properties']['selection'] = dict(type='array', minItems=1, maxItems=MAX_SELECTION,
        items=dict(type='object', properties=dict(dataset_id=text, field_id=text),
                   required=['dataset_id', 'field_id'], additionalProperties=False))
    schema['properties']['data_characteristics'] = _annotation_schema()
    schema['properties']['history_selection'] = dict(type='array', maxItems=MAX_HISTORY_SELECTION,
        items=dict(type='object', properties=dict(group_id=text,
            view_sha256=dict(type='string', pattern='^[a-f0-9]{64}$')),
            required=['group_id', 'view_sha256'], additionalProperties=False))
    schema['required'].extend(['selection', 'data_characteristics', 'history_selection'])
    return schema


def _generation(root: Path, config: dict) -> str:
    """Input: vault Path/config dict. Output: prepared or validated read-only catalog generation str."""
    from wqb.research_query_index import prepare_query_index, validate_query_generation
    if config.get('retrieval_catalog_generation'):
        token = config['retrieval_catalog_generation']
        validate_query_generation(root, token)
        return token
    return prepare_query_index(root)['generation']


def _save(directory: Path, task: dict) -> None:
    """Input: task owner Path/state dict. Output: None; atomically save state with integrity digest."""
    value = deepcopy(task)
    value.pop('state_sha256', None)
    value['state_sha256'] = _digest(value)
    _write(_safe(directory, TASK_PATH), value)


def read_design_task(directory: Path) -> dict:
    """Input: task owner Path. Output: complete verified task dict; reject links, corruption and oversized input."""
    directory = Path(directory).absolute()
    path = _safe(directory, TASK_PATH)
    if path.stat().st_size > MAX_TASK_BYTES:
        raise ValueError('retrieval task exceeds byte bound')
    value = json.loads(path.read_text(encoding='utf-8'))
    if (not isinstance(value, dict)
            or value.get('state_sha256') != _digest({k: v for k, v in value.items() if k != 'state_sha256'})
            or value.get('input_sha256') != _digest(value.get('identity'))):
        raise ValueError('retrieval task identity or integrity mismatch')
    return value


def authenticated_design_task(directory: Path) -> dict:
    """Input: owning task Path. Output: running task with original catalog/Start binding; never grant Resume."""
    from wqb.research_query_index import validate_query_generation
    task = read_design_task(directory)
    if task['status'] != 'running':
        raise ValueError('query requires the owning running design task')
    identity = task['identity']
    validate_query_generation(Path(identity['knowledge_root']), identity['generation'])
    owner = identity['config'].get('retrieval_owner')
    if owner:
        from wqb.console_start import read_start_request, PREPARING_STATUSES, _source_intent
        runs = Path(owner['runs_root'])
        request = read_start_request(runs)
        if (request.get('request_id') != owner['request_id']
                or request.get('status') not in PREPARING_STATUSES
                or request.get('source_intent') != _source_intent(runs)):
            raise InterruptedError('retrieval task Start stopped, superseded or changed')
    return task


def _identities(answer: dict) -> list[tuple[str, str]]:
    """Input: proposed answer dict. Output: distinct bounded dataset/field pairs, never arbitrary formulas."""
    selection = answer.get('selection')
    if (not isinstance(selection, list) or not 1 <= len(selection) <= MAX_SELECTION
            or any(not isinstance(row, dict) or set(row) != {'dataset_id', 'field_id'}
                   or any(not isinstance(v, str) or not v for v in row.values()) for row in selection)):
        raise ValueError('invalid bounded field selection')
    pairs = [(row['dataset_id'], row['field_id']) for row in selection]
    if len(set(pairs)) != len(pairs):
        raise ValueError('duplicate selected field identity')
    return pairs


def _design_source_refs(designs: list) -> list[dict]:
    """Input: structured design list. Output: deduplicated exact cited references, without trusting their claims."""
    refs = {}
    for design in designs:
        if not isinstance(design, dict) or not isinstance(design.get('evidence_refs'), list):
            raise ValueError('design evidence references must be explicit')
        for ref in design['evidence_refs']:
            if not isinstance(ref, dict):
                raise ValueError('invalid supporting source reference')
            refs[_digest(ref)] = deepcopy(ref)
    return list(refs.values())


def _attach_cited_sources(root: Path, resources: dict, refs: list[dict]) -> dict:
    """Input: vault/resource/cited refs. Output: copied resource with independently verified original supporting materials."""
    from wqb.research_queries import _source_index, _material
    result = deepcopy(resources)
    registered = _source_index(root)
    for ref in refs:
        path = ref.get('source_path')
        if path not in registered:
            raise ValueError('cited supporting source is not indexed')
        row = registered[path]
        if (ref.get('sha256') != row.get('content_hash')
                or ref.get('capture_date') != str(row.get('captured_at', ''))[:10]):
            raise ValueError('cited supporting source hash or capture date changed')
        if path in result['source_index']:
            continue
        source, text = _material(root, row)
        result['source_index'][path] = source
        result['source_texts'][path] = text
        result['evidence_pack']['source_index'][path] = deepcopy(source)
        result['evidence_pack']['source_texts'][path] = text
    return result


def _resolved_context(task: dict, selection: list[tuple[str, str]], refs: list[dict] | None = None) -> tuple[dict, dict, dict]:
    """Input: authenticated task/selected pairs. Output: actual resource, annotation context and finite Repair policy."""
    from wqb.generator import build_settings
    from wqb.research_resource_catalog import read_selected_catalog_resources
    from wqb.preplanned_start import _repair_policy
    from wqb.initial_research_planning import _annotation_context
    identity = task['identity']
    config = identity['config']
    resources, diagnostics = read_selected_catalog_resources(Path(identity['knowledge_root']),
        identity['scope'], selection, generation=identity['generation'], settings=build_settings(
            {**config, **{key: identity['scope'][key] for key in ('instrument_type', 'region', 'delay', 'universe')}}))
    if refs:
        resources = _attach_cited_sources(Path(identity['knowledge_root']), resources, refs)
    repair = _repair_policy(resources, config.get('repair_search_policy'))
    manifest = dict(start_snapshot=dict(repair_search_policy=repair))
    context = _annotation_context(resources, manifest)
    return resources, context, repair


def _selected_history(task: dict, selected: list) -> dict:
    """Input: task/selected group hashes. Output: original bounded observation context with actual view identity."""
    if not isinstance(selected, list) or len(selected) > MAX_HISTORY_SELECTION:
        raise ValueError('invalid bounded history selection')
    if not selected:
        return dict(schema_version=1, groups=[])
    from wqb.research_queries import _read
    from wqb.research_query_index import validate_query_generation
    root = Path(task['identity']['knowledge_root'])
    generation = task['identity']['generation']
    validate_query_generation(root, generation)
    path = 'machine/mechanism_evidence.json'
    raw = _read(root, path)
    digest = hashlib.sha256(raw).hexdigest()
    view = json.loads(raw)
    groups = {}
    for group in view['groups']:
        identity = group['group_id']
        if identity in groups:
            raise ValueError('ambiguous historical group identity')
        groups[identity] = group
    result, seen = [], set()
    for ref in selected:
        if (not isinstance(ref, dict) or set(ref) != {'group_id', 'view_sha256'}
                or ref['view_sha256'] != digest or ref['group_id'] not in groups
                or ref['group_id'] in seen):
            raise ValueError('selected historical evidence changed, missing or duplicated')
        seen.add(ref['group_id'])
        result.append(deepcopy(groups[ref['group_id']]))
    validate_query_generation(root, generation)
    return dict(schema_version=1, source_view=dict(path=path, sha256=digest,
        input_digest=view['input_digest']), requested_scope=deepcopy(task['identity']['scope']), groups=result)


def _resolve_answer(task: dict, answer: dict) -> dict:
    """Input: task/proposed complete answer. Output: validated selected resources/answer/Repair, without writing a package."""
    from wqb.initial_research_planning import _compiled_graph
    from wqb.research_query_index import validate_query_generation
    identity = task['identity']
    root = Path(identity['knowledge_root'])
    validate_query_generation(root, identity['generation'])
    _check_schema(task['brief']['output_schema'], answer)
    resources, annotation, repair = _resolved_context(task, _identities(answer), _design_source_refs(answer['designs']))
    selected_context = _selected_history(task, answer['history_selection'])
    if selected_context['groups']:
        from wqb.semantic_compilation import _mechanism_summary
        resources['evidence_pack']['mechanism_context'] = [
            _mechanism_summary(group) for group in selected_context['groups']]
    identity = task['identity']
    brief = dict(scope=identity['scope'], plan_depth=identity['policy']['plan_depth'],
        max_width=identity['policy']['initial_hypotheses'],
        measurement_period=identity['config']['measurement_period'],
        output_schema={key: deepcopy(value) for key, value in task['brief']['output_schema'].items()},
        compatible_template_receipts=[], annotation_context=annotation)
    brief['output_schema']['properties'].pop('selection')
    brief['output_schema']['required'].remove('selection')
    actual_answer = {key: deepcopy(value) for key, value in answer.items()
                     if key not in ('selection', 'history_selection')}
    brief['output_schema']['properties'].pop('history_selection')
    brief['output_schema']['required'].remove('history_selection')
    _, _, receipts, _ = _compiled_graph(actual_answer, resources, identity['scope'], brief)
    used = {(b['dataset_id'], b['field_id']) for item in receipts
            for b in item['compiled']['experiment']['context_bindings'].values()}
    used.update((b['dataset_id'], b['field_id']) for item in receipts
        for arm in item['compiled']['experiment']['arms'] for b in arm['binding']['bindings'].values())
    if used != set(_identities(answer)):
        raise ValueError('final selection must contain exactly the fields used by the tree')
    validate_query_generation(root, identity['generation'])
    return dict(resources=resources, answer=actual_answer, repair_search_policy=repair,
                selected_context=selected_context)


def prepare_retrieval_design(directory: Path, knowledge: Path, scope: dict, option: dict,
                             config: dict, *, model_runner, check_cancelled) -> dict:
    """Input: local task/vault/scope/objective/config and callbacks. Output: durable complete or blocked design result.

    Save running before a single model task; interruption never replays unknown
    outcomes. Completed answers are locally revalidated, not regenerated.
    """
    directory, knowledge = Path(directory).absolute(), Path(knowledge).absolute()
    check_cancelled()
    directory.mkdir(parents=True, exist_ok=True)
    generation = _generation(knowledge, config)
    policy = dict(plan_depth=config.get('plan_depth', 2), initial_hypotheses=config.get('initial_hypotheses', 4))
    from wqb.initial_research_planning import _policy
    _policy(dict(schema_version=1, **policy))
    selected_config = {key: deepcopy(config[key]) for key in CONFIG_KEYS if key in config}
    from wqb.research_tool_service import tool_limits
    limits = tool_limits(selected_config)
    contract = dict(version=1, output_schema=design_schema(), tools=deepcopy(TOOL_CONTRACTS), tool_limits=limits)
    identity = dict(schema_version=1, knowledge_root=str(knowledge), scope=deepcopy(scope),
        objective=deepcopy(option), generation=generation, policy=policy, config=selected_config,
        design_contract=contract)
    expected = _digest(identity)
    with json_lock_transition_guard(directory / 'retrieval_guard', LOCK_SECONDS, LOCK_POLL_SECONDS,
                                    'retrieval planning task busy'):
        path = _safe(directory, TASK_PATH)
        if path.exists():
            task = read_design_task(directory)
            if task['input_sha256'] != expected:
                raise ValueError('retrieval planning input identity changed')
            if task['status'] == 'completed':
                check_cancelled()
                _resolve_answer(task, task['answer'])
                return deepcopy(task['result'])
            return dict(status='blocked', reason=task.get('reason', 'model_outcome_unknown'),
                        input_sha256=expected, task_dir=str(directory))
        from wqb import initial_research_planning as initial
        brief = dict(schema_version=1, objective=option, scope=scope, generation=generation,
            plan_depth=policy['plan_depth'], max_width=policy['initial_hypotheses'],
            measurement_period=config['measurement_period'], output_schema=deepcopy(contract['output_schema']),
            tools=['fields', 'operators', 'templates', 'experience', 'source', 'validate'],
            tool_contracts=deepcopy(TOOL_CONTRACTS),
            tool_limits=deepcopy(limits),
            excluded_selections=deepcopy(config.get('retrieval_excluded_selections', [])),
            composition_contract=initial.__doc__,
            instructions=('Research meaning, mechanisms, conditions, alternatives and falsifiable experiments. '
                'Retrieve relevant templates and historical evidence; report absence honestly. '
                'Unknown traits remain unknown. Select exact fields, explicitly choose VECTOR reductions, '
                'validate drafts locally, and return the complete bounded tree. No formulas, '
                'simulation, capture, credentials, publication or budget changes.'))
        task = dict(identity=identity, input_sha256=expected, status='running', brief=brief)
        check_cancelled()
        _save(directory, task)
    try:
        from wqb.research_tool_service import local_tool_service
        with local_tool_service(directory, task):
            answer = model_runner(deepcopy(brief))
    except Exception as error:
        task.update(status='unknown', reason='model_outcome_unknown: ' + type(error).__name__ + ': ' + str(error)[:500])
        _save(directory, task)
        return dict(status='blocked', reason=task['reason'], input_sha256=expected, task_dir=str(directory))
    task.update(status='outcome_received', answer=deepcopy(answer))
    _save(directory, task)
    try:
        check_cancelled()
        resolved = _resolve_answer(task, answer)
    except (ValueError, TypeError, KeyError, OSError) as error:
        task.update(status='blocked', reason=str(error))
        _save(directory, task)
        return dict(status='blocked', reason=str(error), input_sha256=expected, task_dir=str(directory))
    result = dict(status='completed', input_sha256=expected, task_dir=str(directory),
                  generation=generation, result_sha256=_digest(answer), **resolved)
    task.update(status='completed', result=deepcopy(result))
    _save(directory, task)
    return result


def query_design_task(directory: Path, operation: str, arguments: dict) -> dict:
    """Input: task Path/op/args. Output: quota-accounted local response; no client-side file writes."""
    from wqb.research_tool_service import request_tool
    return request_tool(directory, operation, arguments)


def _query_design_task_local(directory: Path, operation: str, arguments: dict) -> dict:
    """Input: running task Path/op/JSON arguments. Output: bounded read-only knowledge or offline validation result."""
    task = authenticated_design_task(directory)
    if (not isinstance(arguments, dict)
            or len(json.dumps(arguments, ensure_ascii=False).encode()) > MAX_TOOL_ARGUMENT_BYTES):
        raise ValueError('oversized or invalid local query arguments')
    identity = task['identity']
    if operation != 'validate':
        from wqb.research_queries import query_knowledge
        return query_knowledge(Path(identity['knowledge_root']), identity['generation'],
                               identity['scope'], operation, arguments)
    try:
        if set(arguments) - {'selection', 'design', 'answer', 'history_selection'} or (
                'design' in arguments and 'answer' in arguments):
            raise ValueError('unknown or conflicting draft validation arguments')
        selection = _identities(arguments)
        designs = ([arguments['design']] if 'design' in arguments else
                   arguments.get('answer', {}).get('designs', []))
        resources, context, _ = _resolved_context(task, selection, _design_source_refs(designs))
        selected_context = _selected_history(task, arguments.get('history_selection', []))
        if selected_context['groups']:
            from wqb.semantic_compilation import _mechanism_summary
            resources['evidence_pack']['mechanism_context'] = [
                _mechanism_summary(group) for group in selected_context['groups']]
        if 'design' in arguments:
            from wqb.hypothesis_design import validate_hypothesis_design
            from wqb.semantic_contracts import SemanticPolicy
            from wqb.exploration_eligibility import validate_exploration
            normalized = validate_hypothesis_design(dict(summary='Offline proposed experiment.',
                designs=[arguments['design']]), resources['evidence_pack'], SemanticPolicy())['designs'][0]
            receipt = validate_exploration(normalized, resources, identity['scope'])
            expressions = [arm['binding']['bound_expression'] for arm in receipt['compiled']['experiment']['arms']]
        elif 'answer' in arguments:
            _resolve_answer(task, dict(arguments['answer'], selection=arguments['selection']))
            expressions = []
        else:
            expressions = []
        kind = 'design' if 'design' in arguments else 'tree' if 'answer' in arguments else 'resource_context_only'
        return dict(valid=True, validated_kind=kind, expressions=expressions, annotation_context=context,
                    diagnostics=[], authority='offline_only')
    except (ValueError, TypeError, KeyError, OSError) as error:
        return dict(valid=False, diagnostics=[dict(code=type(error).__name__, message=str(error))],
                    authority='offline_only')


def retrieval_projection(directory: Path) -> dict:
    """Input: running task Path. Output: compact tool/contract references, not inline raw or copied scientific evidence."""
    task = authenticated_design_task(directory)
    if getattr(sys, 'frozen', False):
        command = [sys.executable, '--worker-module', 'wqb.retrieval_research_planning']
    else:
        command = [sys.executable, '-B', str(Path(__file__).resolve().parents[1] / 'scripts/research_query.py')]
    brief = task['brief']
    return dict(task_path=TASK_PATH, input_sha256=task['input_sha256'],
        objective=brief['objective'], scope=brief['scope'], measurement_period=brief['measurement_period'],
        plan_depth=brief['plan_depth'], max_width=brief['max_width'],
        excluded_selections=brief['excluded_selections'],
        tool_limits=brief['tool_limits'],
        query_command=command + ['query', '--task-dir', str(Path(directory).absolute()),
            '--operation', '<fields|operators|templates|experience|source|validate>', '--arguments', '<JSON object>'],
        stdio_hint='For a windowed helper in PowerShell, pipe its command to Out-String to wait and capture UTF-8 JSON.',
        references=dict(output_schema='/brief/output_schema', composition_contract='/brief/composition_contract',
                        instructions='/brief/instructions', tool_contracts='/brief/tool_contracts'))


def create_retrieval_model_runner(directory: Path, config: dict, check_cancelled):
    """Input: task owner/config/cancellation callback. Output: one existing Codex checkpoint runner, never WQB execution."""
    from wqb import ai_checkpoints
    from wqb.workflow_driver import resolve_ai_executor_argv
    if config.get('ai_executor') != 'codex':
        raise ValueError('retrieval design requires the existing read-only Codex executor')
    argv = resolve_ai_executor_argv(dict(ai_executor='codex'))

    def cancelled() -> bool:
        """Input: none. Output: bool; preserve original Start cancellation in the owned model process."""
        try:
            check_cancelled()
            authenticated_design_task(directory)
            return False
        except (InterruptedError, ValueError, OSError):
            return True

    def runner(brief: dict) -> dict:
        """Input: exact saved compact brief. Output: complete strict design answer after a single checkpoint."""
        check_cancelled()
        task = authenticated_design_task(directory)
        if task['brief'] != brief:
            raise ValueError('retrieval model brief changed')
        decisions = directory / 'stages/ai'
        decisions.mkdir(parents=True, exist_ok=True)
        with json_lock_transition_guard(decisions / 'retrieval_model_guard', LOCK_SECONDS,
                                        LOCK_POLL_SECONDS, 'retrieval model busy'):
            if ai_checkpoints.load_ai_checkpoints(decisions):
                raise ValueError('retrieval checkpoint exists; no blind model replay')
            checkpoint = ai_checkpoints.append_ai_checkpoint(decisions, CHECKPOINT_TYPE,
                'Retrieve local knowledge and design the entire experiment tree.', [TASK_PATH],
                datetime.now(timezone.utc).isoformat())
        result = ai_checkpoints.run_ai_checkpoint(decisions, checkpoint.checkpoint_id, argv,
            cancellation_check=cancelled, cancel_on_pause=False)
        if result['status'] != 'completed':
            raise RuntimeError('retrieval model ' + result['status'] + ': ' + str(result.get('error', '')))
        check_cancelled()
        authenticated_design_task(directory)
        return {key: deepcopy(result[key]) for key in brief['output_schema']['required']}

    return runner


def emit_query_result(value: dict) -> None:
    """Input: tool result dict. Output: UTF-8 JSON to inherited stdout, including a windowed Windows executable."""
    raw = (json.dumps(value, ensure_ascii=False, allow_nan=False) + '\n').encode('utf-8')
    if sys.stdout is not None:
        sys.stdout.write(raw.decode('utf-8'))
        sys.stdout.flush()
        return
    if os.name != 'nt':
        raise RuntimeError('local query requires a captured stdout channel')
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.GetStdHandle.argtypes = [wintypes.DWORD]
    kernel.GetStdHandle.restype = wintypes.HANDLE
    kernel.WriteFile.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
                                ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
    kernel.WriteFile.restype = wintypes.BOOL
    handle = kernel.GetStdHandle(0xFFFFFFF5)
    if not handle or handle == ctypes.c_void_p(-1).value:
        raise RuntimeError('windowed query has no inherited stdout pipe')
    offset = 0
    while offset < len(raw):
        written = wintypes.DWORD()
        buffer = ctypes.create_string_buffer(raw[offset:])
        if not kernel.WriteFile(handle, buffer, len(raw) - offset, ctypes.byref(written), None) or not written.value:
            raise OSError('windowed query stdout write failed')
        offset += written.value


def main(argv: list[str] | None = None) -> int:
    """Input: local query CLI arguments. Output: JSON/exit code; never create a task, compile knowledge or call WQB."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['query'])
    parser.add_argument('--task-dir', required=True, type=Path)
    parser.add_argument('--operation', required=True,
                        choices=['fields', 'operators', 'templates', 'experience', 'source', 'validate'])
    parser.add_argument('--arguments', default='{}')
    args = parser.parse_args(argv)
    try:
        value = query_design_task(args.task_dir, args.operation, json.loads(args.arguments))
        emit_query_result(value)
        return 0
    except (ValueError, TypeError, KeyError, OSError) as error:
        emit_query_result(dict(error=type(error).__name__, message=str(error)))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
