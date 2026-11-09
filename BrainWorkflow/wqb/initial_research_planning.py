"""One pre-execution model task per opted-in owning lane, never a live executor.

prepare_initial_research returns status completed|blocked (reason on blocked).
tree_policy accepts schema_version=1, plan_depth=1..16, initial_hypotheses=1..16
(defaults 1/2/4 respectively; unknown keys reject);
comparison period comes from start_snapshot.measurement_period, not the model.
model_runner(brief:dict) returns exactly {summary, designs, tree}. Designs use
design_output_schema, WITHOUT generated design_id. Graph is {roots:[node_id],
nodes:[{node_id,parent_id,parent_arm_id,design_index,targets,fallback,reverse}]}.
targets is {baseline:[node_id],treatment:[node_id]}; fallback is an explicit list
(empty means finish). reverse optionally declares either arm, each as
{design_index,arm_id,interpretation,targets}; actual reverse measurements remain
mandatory when a reverse is declared. An absent reverse retains the existing
inconclusive negative-signal outcome, never inventing a reversal. Reverse designs must compile to the exact opposite orientation of
the primary arm, not an unrelated expression. References are zero-based indexes
into designs. No expressions/settings/hashes/source labels are model inputs.
Every design must be referenced; roots must be distinct sourced hypotheses;
positive continuation lists may be empty (finish) or up to two planned children.
validate_tree enforces measured-parent reuse, exhaustive existing routing and
depth/width bounds. No model calls between layers or during Repair.

All proposal receipts, certificates and snapshots are run-local exploratory
evidence. This module never publishes reviewed/global knowledge. The owning
manifest gains only a validated snapshot attachment, retaining frozen policy.
freeze_tree is used if installed; otherwise tree/resources are returned for the
parent. Lane distinctions, group authority and live dispatch belong to parent.
"""

from copy import deepcopy
import importlib
import hashlib
import json
from pathlib import Path

from wqb.cli import simulation_identity_hash
from wqb.experiment_tree import validate_tree
from wqb.exploration_eligibility import (
    _digest, _store_immutable, build_exploration_snapshot,
    certify_exploration_resources, freeze_exploration, match_exploration,
    validate_exploration, validate_operational_exploration, verify_exploration,
)
from wqb.hypothesis_design import design_output_schema, validate_hypothesis_design, _pack
from wqb.lockfile import json_lock_transition_guard
from wqb.runtime_control import _write
from wqb.semantic_compilation import _check_schema, _safe
from wqb.resource_evidence import knowledge_catalog_admission
from wqb.semantic_contracts import SemanticPolicy


TASK_PATH = 'runtime/initial_research_planning/task.json'
SNAPSHOT_PATH = 'runtime/initial_research_planning/snapshot.json'
DATA_CHARACTERISTICS_PATH = 'runtime/initial_research_planning/data_characteristics.json'
MAX_ANNOTATION_TEXT = 1600
MAX_ANNOTATION_FIELDS = 64
TRAIT_KEYS = ('field_type', 'field_description', 'units', 'available_at', 'vector_grain',
              'sampling_frequency_sessions', 'semantic_tags')
MAX_DESIGNS = 30
DEFAULT_WIDTH = 4
DEFAULT_DEPTH = 2
MAX_ROOTS = 16
MAX_DEPTH = 16
LOCK_SECONDS = 5.0
LOCK_POLL_SECONDS = 0.05
ARMS = ('baseline', 'treatment')


def _object(properties: dict) -> dict:
    """Input: property schemas dict. Output: strict required-key object schema dict."""
    return dict(type='object', properties=properties, required=list(properties), additionalProperties=False)


def _output_schema(version: int) -> dict:
    """Input: verified resource version int. Output: strict structured answer schema dict."""
    text = dict(type='string')
    ids = dict(type='array', items=text)
    reverse = _object(dict(design_index=dict(type='integer'), arm_id=dict(type='string', enum=list(ARMS)),
        interpretation=text, targets=ids))
    reverse_arms = dict(type='object', properties={arm: reverse for arm in ARMS},
        required=[], additionalProperties=False)
    node = _object(dict(node_id=text, parent_id=dict(anyOf=[text, dict(type='null')]),
        parent_arm_id=dict(anyOf=[text, dict(type='null')]), design_index=dict(type='integer'),
        targets=_object({arm: ids for arm in ARMS}), fallback=ids,
        reverse=reverse_arms))
    schema = design_output_schema(version, include_conditioned=True)
    schema['properties']['tree'] = _object(dict(roots=ids, nodes=dict(type='array', items=node)))
    schema['required'].append('tree')
    return schema


def _annotation_mode(manifest: dict) -> bool:
    """Input: frozen manifest dict. Output: bool; only exact new policy opts into annotations."""
    policy = manifest['start_snapshot'].get('research_policy', {})
    if 'execution_package_version' not in policy:
        return False
    if any(type(policy.get(key)) is not int or policy[key] != 1
           for key in ('execution_package_version', 'preplanned_tree_version')):
        raise ValueError('annotations require execution package and preplanned tree version 1')
    return True


def _annotation_context(resources: dict, manifest: dict) -> dict:
    """Input: certified resources/frozen manifest dicts. Output: raw-backed traits and frozen rule IDs."""
    from wqb.knowledge_compile import _coverage_source_fields
    from wqb.repair_search import _policy as repair_policy, _field_source_paths
    frozen = repair_policy(manifest['start_snapshot']['repair_search_policy'])
    rules = [rule['rule_id'] for rule in frozen['rules']]
    if len(set(rules)) != len(rules):
        raise ValueError('ambiguous frozen Repair rule IDs')
    scope = resources['evidence_pack']['scope']
    fields = []
    for row in resources['field_rows']:
        paths = _field_source_paths(row, resources['source_index'], resources['source_texts'],
            scope, knowledge_catalog_admission(resources))
        raw = [(field, path) for path in paths
            for field, dataset, captured in _coverage_source_fields(resources['source_texts'][path])
            if field.get('id') == row['field_id'] and dataset.get('id') == row['dataset_id']
            and all(type(captured.get(key)) is type(scope[key]) and captured.get(key) == scope[key]
                    for key in ('instrument_type', 'region', 'delay', 'universe'))]
        facts = {}
        for key in TRAIT_KEYS:
            raw_key = {'field_type': 'type', 'field_description': 'description'}.get(key, key)
            values = [(field[raw_key], path) for field, path in raw
                      if field.get(raw_key) not in (None, '', [], {})]
            if not values:
                continue
            if any(_digest(dict(value=value)) != _digest(dict(value=values[0][0])) for value, _ in values):
                raise ValueError('conflicting raw annotation trait: ' + key)
            facts[key] = dict(value=deepcopy(values[0][0]), basis='documented', evidence_refs=[
                dict(source_path=path, sha256=resources['source_index'][path]['content_hash'],
                     capture_date=resources['source_index'][path]['captured_at'][:10])
                for path in sorted({path for _, path in values})])
        fields.append(dict(dataset_id=row['dataset_id'], field_id=row['field_id'], known_facts=facts,
            unknown_trait_keys=sorted(set(TRAIT_KEYS) - set(facts))))
    identities = [(row['dataset_id'], row['field_id']) for row in fields]
    if len(set(identities)) != len(identities):
        raise ValueError('ambiguous annotation field identity')
    return dict(schema_version=1, fields=fields, repair_rule_ids=sorted(rules),
        repair_resources=[dict(rule_id=rule['rule_id'], edit=rule['edit'],
            target_metric=rule['target_metric'], requires=deepcopy(rule['requires']),
            purpose='documentation_only') for rule in frozen['rules']],
        compilation_settings=deepcopy(resources['settings']),
        repair_search_policy_sha256=_digest(manifest['start_snapshot']['repair_search_policy']))


def _annotation_schema() -> dict:
    """Input: none. Output: strict reference-only annotation array schema dict."""
    text = dict(type='string')
    keys = dict(type='array', items=dict(type='string', enum=list(TRAIT_KEYS)))
    return dict(type='array', items=_object(dict(dataset_id=text, field_id=text,
        known_trait_keys=keys, unknown_trait_keys=keys,
        hypotheses=dict(type='array', items=_object(dict(
            trait_key=dict(type='string', enum=list(TRAIT_KEYS)), hypothesis=text))),
        suggested_repair_rule_ids=dict(type='array', items=text))))


def _annotation_fields(answer: dict, brief: dict, used: set) -> list:
    """Input: validated answer/brief dicts and used identity tuples. Output: script-resolved annotation rows."""
    context = brief['annotation_context']
    available = {(row['dataset_id'], row['field_id']): row for row in context['fields']}
    annotations = answer['data_characteristics']
    if not 1 <= len(annotations) <= MAX_ANNOTATION_FIELDS:
        raise ValueError('annotation field count exceeds bounds')
    seen, result = set(), []
    for annotation in annotations:
        identity = (annotation['dataset_id'], annotation['field_id'])
        if identity not in used or identity in seen or identity not in available:
            raise ValueError('annotations require each used canonical field exactly once')
        seen.add(identity)
        facts = available[identity]
        for key, allowed in (('known_trait_keys', facts['known_facts']),
                ('unknown_trait_keys', facts['unknown_trait_keys']),
                ('suggested_repair_rule_ids', context['repair_rule_ids'])):
            refs = annotation[key]
            if len(refs) > 32 or len(set(refs)) != len(refs) or any(ref not in allowed for ref in refs):
                raise ValueError('invalid annotation reference: ' + key)
        hypotheses = annotation['hypotheses']
        if len(hypotheses) > len(TRAIT_KEYS) or len({h['trait_key'] for h in hypotheses}) != len(hypotheses):
            raise ValueError('duplicate or oversized annotation hypotheses')
        if any(not h['hypothesis'].strip() or len(h['hypothesis']) > MAX_ANNOTATION_TEXT for h in hypotheses):
            raise ValueError('annotation hypothesis text exceeds bounds')
        result.append(dict(deepcopy(facts), referenced_trait_keys=annotation['known_trait_keys'],
            hypotheses=deepcopy(hypotheses), suggested_repair_rule_ids=annotation['suggested_repair_rule_ids'],
            repair_resource_hints=[deepcopy(rule) for rule in context.get('repair_resources', [])
                if rule['rule_id'] in annotation['suggested_repair_rule_ids']]))
    if seen != used:
        raise ValueError('missing used field annotations')
    return sorted(result, key=lambda row: (row['dataset_id'], row['field_id']))


def _read(path: Path) -> dict:
    """Input: safe JSON Path. Output: dict; malformed durable evidence fails closed."""
    value = json.loads(path.read_text(encoding='utf-8'))
    if type(value) is not dict:
        raise ValueError('expected durable JSON object')
    _digest(value)
    return value


def _save_task(path: Path, task: dict) -> None:
    """Input: safe task Path and state dict. Output: None; persist canonical state integrity."""
    task.pop('state_sha256', None)
    task['state_sha256'] = _digest(task)
    _write(path, task)


def _load_task(path: Path) -> dict | None:
    """Input: safe task Path. Output: saved task dict or None; never ignore corrupt tasks."""
    if not path.exists():
        return None
    task = _read(path)
    if task.get('state_sha256') != _digest({k: v for k, v in task.items() if k != 'state_sha256'}):
        raise ValueError('initial model task integrity mismatch')
    if task.get('status') not in ('running', 'unknown', 'outcome_received', 'blocked', 'completed'):
        raise ValueError('unsupported initial model task status')
    return task


def _policy(policy: dict) -> dict:
    """Input: optional-setting policy dict. Output: defaulted v1 config dict, bounded positive integers."""
    if type(policy) is not dict or set(policy) - {'schema_version', 'plan_depth', 'initial_hypotheses'}:
        raise ValueError('unknown tree policy settings')
    normalized = dict(schema_version=1, plan_depth=DEFAULT_DEPTH, initial_hypotheses=DEFAULT_WIDTH)
    normalized.update(policy)
    if (type(normalized['schema_version']) is not int or normalized['schema_version'] != 1
            or type(normalized['plan_depth']) is not int or not 1 <= normalized['plan_depth'] <= MAX_DEPTH
            or type(normalized['initial_hypotheses']) is not int
            or not 1 <= normalized['initial_hypotheses'] <= MAX_ROOTS):
        raise ValueError('expected v1 tree policy: depth and initial_hypotheses in 1..16')
    return normalized


def _brief(resources: dict, manifest: dict, certificate: dict, receipts: list, policy: dict) -> dict:
    """Input: certified resource/owner/policy dicts and trusted receipts. Output: bounded model brief dict."""
    pack = _pack(resources['evidence_pack'])
    if (pack['scope'] != certificate['scope'] or pack['source_index'] != resources['source_index']
            or resources['evidence_pack'].get('source_texts') != resources['source_texts']):
        raise ValueError('model pack differs from certified resource context')
    if type(receipts) is not list:
        raise ValueError('template_receipts must be a trusted local list')
    compatible = []
    for claimed in receipts:
        receipt = verify_exploration(claimed)
        inputs = receipt['compiler_input']
        if inputs['scope'] == certificate['scope'] and inputs['resources'] == resources:
            compatible.append(receipt)
    composition = __doc__
    if knowledge_catalog_admission(resources):
        composition += ('\nResource policy knowledge_catalog_v1: all supplied catalog resources are eligible for exploration. '
            'Unknown economic meaning, cadence, units, timing or vector grain remain unknown, not established facts. '
            'Use field:<dataset_id>/<field_id> role selectors for exact identity binding; these are not economic meanings. '
            'Express interpretations as hypotheses and competing explanations. Keep existing feature, type and tree rules. '
            'An operator with no technical signature remains visible, but do not invent its signature or claim it compiled.\n')
    brief = dict(schema_version=1, scope=certificate['scope'],
        measurement_period=manifest['start_snapshot']['measurement_period'],
        plan_depth=policy['plan_depth'], max_width=policy['initial_hypotheses'],
        sources=deepcopy(resources['source_index']), source_texts=deepcopy(resources['source_texts']),
        data_traits=deepcopy(resources['field_rows']), operator_rows=deepcopy(resources['operator_rows']),
        evidence_pack=deepcopy(resources['evidence_pack']),
        compatible_template_receipts=compatible,
        resource_certificate_sha256=certificate['content_sha256'],
        composition_contract=composition,
        output_schema=_output_schema(resources.get('resource_contract_version', 1)))
    if _annotation_mode(manifest):
        brief['annotation_context'] = _annotation_context(resources, manifest)
        brief['output_schema']['properties']['data_characteristics'] = _annotation_schema()
        brief['output_schema']['required'].append('data_characteristics')
        brief['composition_contract'] += ('\nNew package mode: data_characteristics must annotate every USED '
            'canonical dataset_id/field_id exactly once. Reference only known trait KEYS from annotation_context; '
            'never supply factual values. Label unknown keys and hypotheses explicitly. Suggest only frozen '
            'repair_rule_ids. Suggestions are documentation only; metric rules still select actual Repair. '
            'Scripts own all files, facts and resource resolution.\n')
    return brief


def _compiled_graph(answer: dict, resources: dict, scope: dict, brief: dict) -> tuple[dict, dict, list, list]:
    """Input: strict answer/certified resources/scope/brief dicts. Output: graph, resources, receipts, origins."""
    _check_schema(brief['output_schema'], answer)
    if not 1 <= len(answer['designs']) <= MAX_DESIGNS:
        raise ValueError('one to thirty referenced designs required')
    graph = answer['tree']
    if not 1 <= len(graph['roots']) <= brief['max_width']:
        raise ValueError('root count exceeds initial_hypotheses')
    # Layer variants may share a mechanism/condition while changing a horizon.
    # Validate each design independently; apply cross-hypothesis dedup to roots.
    normalized = [validate_hypothesis_design(dict(summary=answer['summary'], designs=[design]),
        resources['evidence_pack'], SemanticPolicy())['designs'][0] for design in answer['designs']]
    nodes = {node['node_id']: node for node in graph['nodes']}
    if len(nodes) != len(graph['nodes']) or any(root not in nodes for root in graph['roots']):
        raise ValueError('duplicate nodes or missing roots')
    used = set()

    def reference(index: int) -> str:
        """Input: design index int. Output: deterministic pair ref str; bounds checked before indexing."""
        if type(index) is not int or not 0 <= index < len(normalized):
            raise ValueError('invalid design_index')
        used.add(index)
        return str(index)

    root_designs = []
    for root in graph['roots']:
        index = nodes[root]['design_index']
        reference(index)
        root_designs.append(answer['designs'][index])
    validate_hypothesis_design(dict(summary=answer['summary'], designs=root_designs),
        resources['evidence_pack'], SemanticPolicy(max_mechanisms=MAX_ROOTS))
    receipts, origins = [], []
    for design in normalized:
        receipt = match_exploration(brief['compatible_template_receipts'], design, scope, resources)
        origins.append('template' if receipt is not None else 'generated')
        receipts.append(receipt if receipt is not None else validate_exploration(design, resources, scope))
    if len({row['content_sha256'] for row in receipts}) != len(receipts):
        raise ValueError('duplicate designs are not padded planning slots')
    pairs = {str(i): row['compiled'] for i, row in enumerate(receipts)}

    def identity(ref: str, arm_id: str) -> str:
        """Input: compiled pair ref/arm ID strings. Output: existing CLI simulation hash str."""
        arm = next(row for row in pairs[ref]['experiment']['arms'] if row['arm_id'] == arm_id)
        return simulation_identity_hash(arm['binding']['bound_expression'], arm['settings'])

    proposed = []
    for raw in graph['nodes']:
        node = deepcopy(raw)
        ref = reference(node.pop('design_index'))
        node['pair_ref'] = ref
        node['expected_simulation_identities'] = {arm: identity(ref, arm) for arm in ARMS}
        for arm_id, reverse in node['reverse'].items():
            reverse_ref = reference(reverse.pop('design_index'))
            primary = normalized[int(ref)]
            opposite = deepcopy(primary)
            opposite['prediction_direction'] = ('negative' if primary['prediction_direction'] == 'positive' else 'positive')
            # Prose/IDs may differ, but executable economic roles, features,
            # conditions and settings must be the exact predeclared reversal.
            candidate = normalized[int(reverse_ref)]
            for key in ('prediction_direction', 'field_roles', 'feature_plan', 'experiment_plan',
                        'conditions', 'mechanism_family', 'condition_id'):
                if candidate[key] != opposite[key]:
                    raise ValueError('reverse must preserve primary economic roles and features')
            if reverse['arm_id'] != arm_id:
                raise ValueError('reverse must confirm the same primary arm')
            reverse.update(pair_ref=reverse_ref,
                simulation_identity=identity(reverse_ref, reverse['arm_id']))
        proposed.append(node)
    if used != set(range(len(receipts))):
        raise ValueError('unreferenced designs are not allowed')
    tree_resources = dict(compiled_pairs=pairs, sources=deepcopy(resources['source_index']))
    proposed = dict(schema_version=1, scope=scope, period=brief['measurement_period'],
        source_ids=sorted(resources['source_index']), roots=graph['roots'], nodes=proposed,
        limits=dict(max_depth=brief['plan_depth'], max_width=brief['max_width']))
    validated = validate_tree(proposed, tree_resources)
    if validated['status'] != 'validated':
        raise ValueError('invalid compiled tree: ' + str(validated['reasons']))
    if 'annotation_context' in brief:
        bindings = [binding for pair in pairs.values()
            for binding in pair['experiment']['context_bindings'].values()]
        bindings.extend(binding for pair in pairs.values() for arm in pair['experiment']['arms']
            for binding in arm['binding']['bindings'].values())
        _annotation_fields(answer, brief, {(b['dataset_id'], b['field_id']) for b in bindings})
    return proposed, tree_resources, receipts, origins


def freeze_initial_research_snapshot(run: Path, knowledge: Path, manifest: dict,
                                     snapshot: dict, certificate: dict) -> dict:
    """Input: owning Paths/base manifest/new snapshot/cert dicts. Output: attached manifest dict.

    Called under the coordinator task guard. Never replace policy or unrelated
    frozen Start fields. Both snapshot receipt and source certification survive
    restart; the immutable run-local snapshot is not a global publication.
    """
    if snapshot['research_policy'] != manifest['start_snapshot']['research_policy']:
        raise ValueError('initial planning cannot change frozen policy identity')
    expected = deepcopy(manifest)
    for key, value in snapshot.items():
        if key in expected['start_snapshot'] and expected['start_snapshot'][key] != value:
            raise ValueError('initial snapshot conflicts with frozen Start: ' + key)
        expected['start_snapshot'][key] = deepcopy(value)
    path = _safe(run, 'run_manifest.json')
    current = _read(path)
    if current != manifest and current != expected:
        raise ValueError('owning manifest changed before initial snapshot freeze')
    if _annotation_mode(manifest):
        # Producer recovery must authenticate raw even if the tree preceded its seal.
        from wqb.exploration_eligibility import _validate_operational_exploration_sources
        _validate_operational_exploration_sources(run, knowledge, expected['start_snapshot'])
    else:
        validate_operational_exploration(run, knowledge, expected['start_snapshot'])
    if any(cert != certificate for cert in snapshot['exploration_context']['resource_certificates']):
        raise ValueError('snapshot differs from pre-model certificate')
    _store_immutable(run, SNAPSHOT_PATH, expected['start_snapshot'])
    if _read(path) != current:
        raise ValueError('owning manifest changed during initial snapshot freeze')
    if current != expected:
        _write(path, expected)
    return expected


def _finish(run: Path, knowledge: Path, resources: dict, task: dict, path: Path,
            package: dict | None = None) -> dict:
    """Input: locked owner/resources/task and optional verified package dict. Output: frozen result, no callback."""
    certificate = (task['certificate'] if package is not None else
        certify_exploration_resources(run, knowledge, resources, task['certificate']['scope']))
    if certificate != task['certificate']:
        raise ValueError('raw resources or owning Start context changed after model dispatch')
    proposed, tree_resources, receipts, origins = _compiled_graph(task['answer'], resources,
        certificate['scope'], task['brief'])
    if package is None:
        for receipt in receipts:
            freeze_exploration(run, receipt, knowledge_root=knowledge, certificate=certificate)
    snapshot = build_exploration_snapshot(receipts, resource_certificates=[certificate] * len(receipts))
    snapshot['compatible_template_ids'] = sorted(row['template_id'] for row in snapshot['template_rows'])
    expected = deepcopy(task['manifest'])
    expected['start_snapshot'].update(snapshot)
    if package is not None:
        manifest = package['manifest']
        if expected != manifest or task.get('attached_manifest') != manifest:
            raise ValueError('sealed package differs from initial planning task')
    else:
        task['attached_manifest'] = expected
        _save_task(path, task)
        manifest = freeze_initial_research_snapshot(run, knowledge, task['manifest'], snapshot, certificate)
    try:
        module = importlib.import_module('wqb.research_tree')
    except ModuleNotFoundError as error:
        if error.name != 'wqb.research_tree':
            raise
        module = None
    freezer = getattr(module, 'freeze_tree', None)
    annotation_hash = None
    if _annotation_mode(task['manifest']):
        used = {(binding['dataset_id'], binding['field_id']) for receipt in receipts
            for binding in receipt['compiled']['experiment']['context_bindings'].values()}
        used.update((binding['dataset_id'], binding['field_id']) for receipt in receipts
            for arm in receipt['compiled']['experiment']['arms']
            for binding in arm['binding']['bindings'].values())
        artifact = dict(schema_version=1, input_sha256=task['input_sha256'],
            resource_certificate_sha256=certificate['content_sha256'],
            repair_search_policy_sha256=task['brief']['annotation_context']['repair_search_policy_sha256'],
            purpose='documentation_only', fields=_annotation_fields(task['answer'], task['brief'], used))
        if package is not None:
            artifact_path = _safe(run, DATA_CHARACTERISTICS_PATH)
            if _read(artifact_path) != artifact:
                raise ValueError('sealed annotations differ from initial planning answer')
        else:
            artifact_path = _store_immutable(run, DATA_CHARACTERISTICS_PATH, artifact)
        annotation_hash = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
    if package is not None:
        tree = package['attachment']
        if tree['proposed_tree'] != proposed or tree['resources'] != tree_resources:
            raise ValueError('sealed tree differs from initial planning answer')
    else:
        tree = (freezer(run, proposed, tree_resources) if freezer is not None
                else validate_tree(proposed, tree_resources))
    if _read(_safe(run, 'run_manifest.json')) != manifest:
        raise ValueError('owning manifest changed during tree freeze')
    result = dict(schema_version=1, status='completed', knowledge_status='exploratory',
        input_sha256=task['input_sha256'], receipts=receipts, receipt_origins=origins,
        snapshot=deepcopy(manifest['start_snapshot']), tree=tree,
        proposed_tree=proposed, tree_resources=tree_resources)
    if annotation_hash is not None:
        result['data_characteristics_sha256'] = annotation_hash
    if task.get('result') is not None and task['result'] != result:
        raise ValueError('completed planning evidence changed')
    task.update(status='completed', result=result)
    _save_task(path, task)
    return deepcopy(result)


def prepare_initial_research(run: Path, knowledge: Path, resources: dict, *,
                            model_runner, template_receipts: list, tree_policy: dict) -> dict:
    """Input: owning Paths, certified resources, injected callback, library/policy. Output: result dict.

    Persist task input hash/status BEFORE exactly one callback. A running or
    uncertain task never auto-replays. Strict schema errors are durable blockers;
    saved completed outputs are revalidated and reused, not regenerated. This
    entry point is only for initial opt-in planning, not layer/Repair scheduling.
    """
    task = None
    path = None
    persist_failure = False
    try:
        run, knowledge = Path(run).absolute(), Path(knowledge).absolute()
        if any(p.is_symlink() or p.is_junction() for root in (run, knowledge) for p in (root, *root.parents)):
            raise ValueError('initial planning roots cannot traverse links')
        run = run.resolve(strict=True)
        tree_policy = _policy(tree_policy)
        resources, template_receipts, tree_policy = deepcopy((resources, template_receipts, tree_policy))
        path = _safe(run, TASK_PATH)
        guard = _safe(run, 'runtime/initial_research_planning/task_guard')
        with json_lock_transition_guard(guard, LOCK_SECONDS, LOCK_POLL_SECONDS, 'initial planning busy'):
            task = _load_task(path)
            current = _read(_safe(run, 'run_manifest.json'))
            if task is None and ('exploration_context' in current.get('start_snapshot', {})
                    or _safe(run, SNAPSHOT_PATH).exists()
                    or _safe(run, 'runtime/experiment_tree.json').exists()):
                raise ValueError('existing initial planning evidence without its model task; manual reconciliation required')
            manifest = current if task is None else task['manifest']
            if current != manifest and (task is None or current != task.get('attached_manifest')):
                raise ValueError('owning manifest differs from original initial planning context')
            package = None
            if task is not None and _annotation_mode(manifest):
                from wqb.execution_package import load_execution_package, SEAL_PATH
                if _safe(run, SEAL_PATH).exists():
                    if task['status'] not in ('completed', 'outcome_received'):
                        raise ValueError('sealed package requires a received initial planning outcome')
                    package = load_execution_package(run)
                    if str(knowledge) != manifest['knowledge_root']:
                        raise ValueError('sealed package knowledge owner changed')
                elif task['status'] == 'completed':
                    raise ValueError('completed initial planning package seal is missing')
            if package is None:
                knowledge = knowledge.resolve(strict=True)
            certificate = (task['certificate'] if package is not None else
                certify_exploration_resources(run, knowledge, resources, manifest['selected_scope']))
            brief = _brief(resources, manifest, certificate, template_receipts, tree_policy)
            input_hash = _digest(dict(manifest=manifest, brief=brief, tree_policy=tree_policy,
                template_receipts=template_receipts, certificate=certificate))
            if task is not None:
                if task['input_sha256'] != input_hash or (package is not None and task['brief'] != brief):
                    raise ValueError('initial planning input context changed; no automatic replay')
                if package is not None and task['status'] == 'completed' and type(task.get('result')) is not dict:
                    raise ValueError('completed initial planning result is missing')
                if task['status'] in ('running', 'unknown'):
                    return dict(status='blocked', reason='model_outcome_unknown', input_sha256=input_hash)
                if task['status'] == 'blocked':
                    return dict(status='blocked', reason=task['reason'], input_sha256=input_hash)
                persist_failure = task['status'] == 'outcome_received'
                return _finish(run, knowledge, resources, task, path, package)
            if not callable(model_runner):
                raise ValueError('model_runner must be an injected callable')
            task = dict(schema_version=1, status='running', input_sha256=input_hash,
                manifest=manifest, certificate=certificate, brief=brief)
            if (certify_exploration_resources(run, knowledge, resources, manifest['selected_scope']) != certificate
                    or _read(_safe(run, 'run_manifest.json')) != manifest):
                raise ValueError('resources or owning Start changed before model dispatch')
            _save_task(path, task)
            persist_failure = True
        # Never retain the state lock across model IO. Concurrent/reentrant callers
        # observe running and cannot issue another model invocation.
        try:
            answer = model_runner(deepcopy(brief))
        except Exception as error:
            with json_lock_transition_guard(guard, LOCK_SECONDS, LOCK_POLL_SECONDS, 'initial planning busy'):
                task.update(status='unknown', reason='model_outcome_unknown:' + type(error).__name__)
                _save_task(path, task)
            return dict(status='blocked', reason=task['reason'], input_sha256=input_hash)
        with json_lock_transition_guard(guard, LOCK_SECONDS, LOCK_POLL_SECONDS, 'initial planning busy'):
            _check_schema(brief['output_schema'], answer)
            _digest(answer)
            task.update(status='outcome_received', answer=deepcopy(answer))
            _save_task(path, task)
            return _finish(run, knowledge, resources, task, path)
    except (ValueError, TypeError, KeyError, OSError, RecursionError, OverflowError) as error:
        reason = 'initial_planning_blocked:' + str(error)
        # Do not overwrite another invocation's running record or its context.
        if persist_failure and task is not None and path is not None:
            with json_lock_transition_guard(guard, LOCK_SECONDS, LOCK_POLL_SECONDS, 'initial planning busy'):
                saved = _load_task(path)
                if saved is not None and saved['state_sha256'] == task.get('state_sha256'):
                    task.update(status='blocked', reason=reason)
                    _save_task(path, task)
        return dict(status='blocked', reason=reason)
