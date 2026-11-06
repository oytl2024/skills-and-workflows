"""Compile project-owned finite Repair hypotheses against certified data facts."""

from copy import deepcopy
import json
from pathlib import Path


RULEBOOK_PATH = Path(__file__).resolve().parents[1] / 'configs' / 'repair_rulebook.json'
MAX_RULEBOOK_BYTES = 64_000
RULEBOOK_KEYS = {'schema_version', 'rulebook_id', 'basis', 'decay_grid', 'truncation_grid', 'rules'}
CATALOG_RULE_KEYS = {'rule_id', 'edit', 'priority', 'target_metric', 'target_direction',
                     'parameter_direction', 'trigger', 'rationale'}


def _validate_catalog(value: dict) -> None:
    """Input: catalog dict. Output: None or ValueError. Bound public configuration before compiling source facts."""
    if (not isinstance(value, dict) or set(value) != RULEBOOK_KEYS
            or type(value['schema_version']) is not int or value['schema_version'] != 1
            or value['basis'] != 'project_hypothesis' or not isinstance(value['rules'], list)
            or not value['rules'] or len(value['rules']) > 32
            or not isinstance(value['rulebook_id'], str) or not value['rulebook_id'].strip()
            or len(value['rulebook_id']) > 1600):
        raise ValueError('invalid project Repair rulebook contract')
    for name in ('decay_grid', 'truncation_grid'):
        if not isinstance(value[name], list) or not 1 <= len(value[name]) <= 32:
            raise ValueError('invalid finite Repair parameter grid')


def load_repair_rulebook() -> dict:
    """Input: none. Output: versioned project rulebook dict. Read a bounded non-secret application resource."""
    if RULEBOOK_PATH.is_symlink() or RULEBOOK_PATH.is_junction() or RULEBOOK_PATH.stat().st_size > MAX_RULEBOOK_BYTES:
        raise ValueError('invalid project Repair rulebook path or size')
    from wqb.knowledge_contracts import _capture_json_object
    value = json.loads(RULEBOOK_PATH.read_text(encoding='utf-8'), object_pairs_hook=_capture_json_object)
    _validate_catalog(value)
    return value


def build_default_repair_policy(resources: dict, rulebook: dict | None = None) -> dict:
    """Input: certified resource dict and optional project catalog. Output: frozen finite policy v2 dict.

    Source references establish data properties only; proposed setting effects
    remain project hypotheses and require measured before/after comparisons.
    """
    from wqb.repair_search import compile_repair_search_policy, _policy
    catalog = load_repair_rulebook() if rulebook is None else deepcopy(rulebook)
    _validate_catalog(catalog)
    certified = compile_repair_search_policy(resources, dict(compile_version=1, rules=[], traits={}))
    facts = deepcopy(certified['traits'])
    fields = certified['resources']['field_rows']
    if not fields or any(row['field_type'] not in {'MATRIX', 'VECTOR'} for row in fields):
        raise ValueError('default Repair requires sourced numeric fields')
    paths = sorted({path for row in fields for path in row['source_paths']})
    references = [dict(source_path=path, sha256=resources['source_index'][path]['content_hash'],
                       capture_date=resources['source_index'][path]['captured_at'][:10],
                       kind='documented', experiment_refs=[]) for path in paths]
    facts['numeric_observation'] = dict(basis='source', value=True, evidence_refs=deepcopy(references))
    rules = []
    for item in catalog['rules']:
        if not isinstance(item, dict) or set(item) != CATALOG_RULE_KEYS or item['edit'] not in {'decay', 'truncation'}:
            raise ValueError('invalid default Repair rule')
        grid = catalog['decay_grid'] if item['edit'] == 'decay' else catalog['truncation_grid']
        rules.append(dict(deepcopy(item), effect='smoothing' if item['edit'] == 'decay' else 'bounded_weights',
            grid=deepcopy(grid), requires={'numeric_observation': True}, evidence_refs=deepcopy(references),
            basis='project_hypothesis'))
    compiled = _policy(dict(schema_version=2, rulebook_id=catalog['rulebook_id'], rules=rules, traits=facts))
    compiled['resources'] = {key: deepcopy(certified['resources'][key]) for key in (
        'resource_contract_version', 'field_rows', 'operator_rows', 'scope', 'evidence_context')}
    return compiled
