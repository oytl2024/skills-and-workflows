"""Two-phase local group preparation; model planning precedes any executable lane."""

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from uuid import uuid4

from wqb.benchmark_rules import START_SNAPSHOT_VERSION, load_benchmark_rules, benchmark_rule_to_dict, benchmark_rulebook_digest
from wqb.exploration_eligibility import certify_exploration_resources, validate_operational_exploration
from wqb.research_group import create_group, read_group
from wqb.runtime_control import _write


GROUP_POLICY_VERSION = 1
TREE_COMPARISON_POLICY = dict(schema_version=1, edit='feature', target_metric='fitness',
                              target_direction='increase', turnover_max=.4)


def _digest(value: dict) -> str:
    """Input: finite resource/plan dict. Output: stable str digest, not a new simulation identity."""
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def prepare_group_lanes(paths, resources: list[dict], scope: dict, selected_option: dict,
                        authority: dict, *, plan_depth: int = 2, initial_hypotheses: int = 4) -> dict:
    """Input: existing paths, lane resources/scope/option/authority dicts and depth/width ints.

    Output: paused group and pre-model source certificates. No model, live request,
    knowledge publication or worker is started. Resources must already exist in raw.
    """
    from wqb.benchmark_rules import benchmark_rules_path_for_knowledge
    if any(type(value) is not int or not 1 <= value <= 16 for value in (plan_depth, initial_hypotheses)):
        raise ValueError('bounded positive depth and initial hypothesis count required')
    if not isinstance(resources, list) or not resources:
        raise ValueError('at least one sourced lane resource plan required')
    field_sets = [sorted((row.get('dataset_id'), row.get('field_id')) for row in item['field_rows']) for item in resources]
    if any(not rows for rows in field_sets) or len({_digest({'fields': rows}) for rows in field_sets}) != len(resources):
        raise ValueError('parallel lanes require distinct sourced data selections')
    rule_path = benchmark_rules_path_for_knowledge(paths.knowledge_root)
    rules = load_benchmark_rules(rule_path)
    if not rules:
        raise ValueError('group preparation requires existing benchmark rules')
    policy = dict(paired_scout=True, exploration_scout=True, exploration_policy_version=1,
                  preplanned_tree_version=GROUP_POLICY_VERSION, deterministic_repair=True,
                  plan_depth=plan_depth, initial_hypotheses=initial_hypotheses,
                  parallel_workflows=len(resources), seed_selection_limit=8)
    plans = [dict(run_id='lane-' + uuid4().hex, plan_digest=_digest(item)) for item in resources]
    group = create_group(paths.run_root, plans, authority)
    certificates = []
    now = datetime.now(timezone.utc).isoformat()
    for lane, resource in zip(group['lanes'], resources):
        run = Path(paths.run_root) / lane['run_id']
        snapshot = dict(artifact_binding_version=START_SNAPSHOT_VERSION, selected_option=deepcopy(selected_option),
            selected_scope=deepcopy(scope), research_policy=deepcopy(policy),
            tree_comparison_policy=deepcopy(TREE_COMPARISON_POLICY),
            benchmark_rulebook=dict(path=rule_path.relative_to(paths.knowledge_root).as_posix(),
                sha256=benchmark_rulebook_digest(rules), rules=[benchmark_rule_to_dict(rule) for rule in rules]))
        manifest = dict(run_id=run.name, knowledge_root=str(Path(paths.knowledge_root).resolve()),
                        selected_option_id=selected_option['option_id'], selected_scope=scope,
                        objective=selected_option.get('title', selected_option['option_id']),
                        created_at=now, start_snapshot=snapshot)
        _write(run / 'run_manifest.json', manifest)
        certificates.append(certify_exploration_resources(run, paths.knowledge_root, resource, scope))
    return dict(group=group, certificates=certificates, research_policy=policy)


def complete_group_lanes(paths, group_path: Path, snapshots: list[dict]) -> dict:
    """Input: paths, paused group Path and complete compiled snapshots list. Output: prepared group dict.

    Preserve original Start policy; only attach locally validated compiled results.
    Publication of an active pointer or Start is intentionally a separate command.
    """
    from wqb.workflow_stage_adapters import _snapshot_schedule_inputs
    from wqb.workflow_state import create_initial_state, write_run_state
    group = read_group(group_path)
    if group['desired_state'] != 'paused' or len(snapshots) != len(group['lanes']):
        raise ValueError('group must remain paused until every lane is prepared')
    manifests = []
    for lane, compiled in zip(group['lanes'], snapshots):
        run = Path(paths.run_root) / lane['run_id']
        manifest = json.loads((run / 'run_manifest.json').read_text(encoding='utf-8'))
        before = manifest['start_snapshot']
        if compiled.get('research_policy') != before['research_policy']:
            raise ValueError('compiled lane cannot change frozen Start policy')
        attached = {**before, **deepcopy(compiled)}
        attached['compatible_template_ids'] = sorted(row['template_id'] for row in attached['template_rows'])
        validate_operational_exploration(run, paths.knowledge_root, attached)
        _snapshot_schedule_inputs(attached, manifest['selected_option_id'], manifest['selected_scope'])
        manifests.append((run, {**manifest, 'start_snapshot': attached}))
    for run, manifest in manifests:
        path = run / 'run_state.json'
        if path.exists():
            if json.loads((run / 'run_manifest.json').read_text(encoding='utf-8')) != manifest:
                raise ValueError('prepared lane identity changed')
            continue
        _write(run / 'run_manifest.json', manifest)
        state = create_initial_state(run.name, run, manifest['objective'], manifest['created_at'])
        stages = dict(state.stages)
        stages['objective_selected'] = replace(stages['objective_selected'], status='completed',
            started_at=manifest['created_at'], completed_at=manifest['created_at'])
        state = replace(state, stages=stages, current_stage='objective_selected',
                        last_completed_stage='objective_selected', next_action='workflow-continue')
        write_run_state(path, state)
    return dict(group, preparation_status='completed')
