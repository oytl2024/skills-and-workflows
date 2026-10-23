"""Opt-in Seed projection from authenticated checked records; no model or network."""

from copy import deepcopy
from datetime import date
import json
from pathlib import Path

from wqb.benchmark_rules import load_run_benchmark_rules
from wqb.cli import simulation_identity_hash
from wqb.runtime_control import _write
from wqb.seed_policy import select_seeds


def preplanned_research_enabled(run: Path) -> bool:
    """Input: run Path. Output: bool from frozen manifest policy, never new global config."""
    path = Path(run) / 'run_manifest.json'
    if not path.exists():
        return False
    policy = json.loads(path.read_text(encoding='utf-8')).get('start_snapshot', {}).get('research_policy', {})
    version = policy.get('preplanned_tree_version')
    return type(version) is int and version == 1


def normalize_measured_row(row: dict, lane_id: str) -> dict:
    """Input: checked row dict and lane ID str. Output: copied row with only derivable measurement metadata.

    Scope derives from exact submitted settings; missing dates stay missing. Do
    not invent the measurement period from requested plan dates or fill metrics.
    """
    result = deepcopy(row)
    settings, metrics = result.get('settings'), result.get('metrics')
    if not isinstance(settings, dict) or not isinstance(metrics, dict) or not isinstance(result.get('expression'), str):
        return result
    identity = simulation_identity_hash(result['expression'], settings)
    if result.get('expression_hash') != identity:
        return result
    result['simulation_identity'] = identity
    result.setdefault('lane_id', lane_id)
    scope_keys = ('region', 'delay', 'universe')
    if all(key in settings for key in scope_keys):
        result.setdefault('measurement_scope', {key: settings[key] for key in scope_keys})
    if 'test_period' not in result and all(isinstance(metrics.get(key), str) for key in ('startDate', 'endDate')):
        try:
            start, end = [date.fromisoformat(metrics[key]) for key in ('startDate', 'endDate')]
            if start <= end and start.isoformat() == metrics['startDate'] and end.isoformat() == metrics['endDate']:
                result['test_period'] = dict(start=metrics['startDate'], end=metrics['endDate'])
        except ValueError:
            pass
    return result


def prepare_seed_selection(run: Path, rows: list[dict]) -> dict:
    """Input: owning run Path and checked rows list. Output: persisted hard-gated/ranked seed selection dict."""
    run = Path(run)
    if not preplanned_research_enabled(run):
        raise ValueError('new Seed policy requires frozen preplanned mode')
    tree_path = run / 'runtime/tree_execution.json'
    tree = json.loads(tree_path.read_text(encoding='utf-8'))
    if tree.get('status') not in {'completed', 'finished'}:
        raise ValueError('Seed selection requires completed tree evidence')
    rules = load_run_benchmark_rules(run)
    if rules is None:
        raise ValueError('Seed ranking requires frozen benchmark authority')
    normalized = [normalize_measured_row(row, run.name) for row in rows]
    retained = tree.get('retained_expression_hashes')
    if not isinstance(retained, list) or not all(isinstance(value, str) for value in retained):
        raise ValueError('completed tree must identify retained expressions')
    eligible = [row for row in normalized if row.get('expression_hash') in retained]
    selection = select_seeds(eligible, {}, benchmark_rules=rules)
    selected = {entry['identity']['expression_hash'] for entry in selection['selected']}
    selection['seed_rows'] = [row for row in eligible if row.get('expression_hash') in selected]
    selection['run_id'] = run.name
    selection['tree_digest'] = tree.get('tree_digest')
    _write(run / 'stages/scout_seed/seed_selection.json', selection)
    return selection
