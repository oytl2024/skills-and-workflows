"""Rebuildable observations, not simulation authority or causal/statistical proof."""
from copy import deepcopy
from datetime import date
import hashlib
import json
import math


MAX_CONTEXT = 12
OBSERVATION_KEYS = ('alpha_id', 'simulation_id', 'expression_hash', 'expression', 'scope', 'settings',
                    'measurement_period', 'metrics', 'status', 'hard_pass', 'failed', 'pending', 'checks', 'error',
                    'hypothesis_id', 'hypothesis_version', 'template_id', 'template_provenance', 'bindings',
                    'operator_provenance', 'source_provenance', 'semantic_release', 'mechanism_source',
                    'resource_contract_version', 'status_code', 'error_type', 'warnings')
COHORT_KEYS = ('hypothesis_id', 'hypothesis_version', 'resource_contract_version', 'semantic_release', 'scope', 'settings')
MEASUREMENT_KEYS = ('alpha_id', 'simulation_id', 'expression_hash', 'expression', 'scope', 'settings',
                    'measurement_period', 'metrics', 'status', 'hard_pass', 'failed', 'pending', 'checks',
                    'error', 'status_code', 'error_type', 'warnings')


def _json(value: object) -> str:
    """Input: JSON value. Output: canonical str; reject nonfinite/non-JSON evidence."""
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False)


def _digest(value: object) -> str:
    """Input: JSON value. Output: SHA256 str of exact canonical evidence."""
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _unique(rows: list[dict]) -> list[dict]:
    """Input: dict list. Output: detached deterministic unique dict list."""
    return [json.loads(value) for value in sorted({_json(row) for row in rows})]


def _known_period(value: object) -> bool:
    """Input: period object. Output: bool; require explicit ordered ISO dates."""
    try:
        return (isinstance(value, dict) and set(value) == {'start', 'end'}
                and date.fromisoformat(value['start']) <= date.fromisoformat(value['end']))
    except (ValueError, TypeError):
        return False


def _operational(row: dict) -> bool:
    """Input: observation dict. Output: bool; classify transport failures, never economics."""
    text = str(row.get('error', '')).lower() + ' ' + str(row.get('error_type', '')).lower()
    status = str(row.get('status', '')).lower()
    return (row.get('status_code') == 429 or status in ('operational_failure', 'timeout', 'rate_limited')
            or any(word in text for word in ('429', 'timeout', 'timed out', 'rate limit')))


def _check_evidence(row: dict) -> tuple[list[dict], set[str]]:
    """Input: observation dict. Output: valid raw check list and limitation set; reject malformed or contradictory evidence."""
    limits = set()
    checks = row.get('checks', [])
    if not isinstance(checks, list) or any(
            not isinstance(c, dict) or not isinstance(c.get('name'), str) or not c['name']
            or c.get('result') not in ('PASS', 'FAIL', 'WARNING', 'PENDING') for c in checks):
        return [], {'measurement_or_checks_incomplete'}
    failed = row.get('failed', [])
    if not isinstance(failed, list) or not isinstance(row.get('pending', []), list):
        return checks, {'measurement_or_checks_incomplete'}
    failed_names = set()
    for item in failed:
        name = item.get('name') if isinstance(item, dict) else item
        if not isinstance(name, str) or not name:
            limits.add('measurement_or_checks_incomplete')
        else:
            failed_names.add(name)
    if 'hard_pass' in row and type(row['hard_pass']) is not bool:
        limits.add('measurement_or_checks_incomplete')
    for check in checks:
        if check['result'] == 'PENDING':
            limits.add('measurement_or_checks_incomplete')
        if (check['result'] == 'FAIL' and row.get('hard_pass') is True
                or 'failed' in row and check['result'] in ('PASS', 'FAIL')
                and (check['result'] == 'FAIL') != (check['name'] in failed_names)):
            limits.add('conflicting_checks')
    return checks, limits


def _group(experiment: dict, observations: list[dict], period: object, conflicting: bool, cohort: dict) -> dict:
    """Input: exact experiment, observations, period, conflict bool. Output: conservative paired group dict."""
    limits = set()
    arms = {arm['arm_id']: arm for arm in experiment.get('arms', [])}
    selected = []
    for row in observations:
        if row.get('measurement_period') == period or not _known_period(row.get('measurement_period')):
            selected.append(row)
    if conflicting:
        limits.add('conflicting_experiment_definitions')
    if not _known_period(period):
        limits.add('known_period_absent')
    if not experiment.get('controls') or set(arms) != {'baseline', 'treatment'}:
        limits.add('control_absent')
    by_arm = {}
    for row in selected:
        name = row['arm_id']
        arm = arms.get(name, {})
        if (row.get('scope') != arm.get('scope') or row.get('settings') != arm.get('settings')
                or row.get('expression') != arm.get('binding', {}).get('bound_expression')):
            limits.add('incompatible_arm_identity_scope_or_settings')
        if not row.get('alpha_id') and not row.get('simulation_id'):
            limits.add('simulation_identity_absent')
        if not row.get('checks') and not {'failed', 'pending', 'hard_pass'} <= set(row):
            limits.add('measurement_or_checks_incomplete')
        if 'bindings' in row and row['bindings'] != arm.get('binding', {}).get('bindings'):
            limits.add('incompatible_data_roles')
        if 'template_id' in row and row['template_id'] != arm.get('template_id'):
            limits.add('incompatible_template_version')
        provenance = row.get('template_provenance', {})
        if any(key in row and key in provenance and row[key] != provenance[key]
               for key in ('template_id', 'hypothesis_id', 'hypothesis_version')):
            limits.add('incompatible_template_version')
        if not _known_period(row.get('measurement_period')):
            limits.add('known_period_absent')
        if row.get('pending') or str(row.get('status', '')).lower() not in ('measured', 'checked'):
            limits.add('measurement_or_checks_incomplete')
        if row.get('hard_pass') is True and row.get('failed'):
            limits.add('conflicting_checks')
        checks, check_limits = _check_evidence(row)
        limits.update(check_limits)
        if any(isinstance(c, dict) and c.get('result') not in ('PASS', 'FAIL', 'WARNING') for c in checks):
            limits.add('measurement_or_checks_incomplete')
        check_results = {}
        for check in checks:
            if isinstance(check, dict):
                check_results.setdefault(check.get('name'), set()).add(check.get('result'))
        if any(len(results) > 1 for results in check_results.values()):
            limits.add('conflicting_checks')
        by_arm.setdefault(name, []).append(row)
    if not all(by_arm.get(name) for name in ('baseline', 'treatment')):
        limits.add('control_or_treatment_measurement_absent')
    identities = {}
    for row in selected:
        if not row.get('simulation_id') and not row.get('alpha_id'):
            continue
        identity = _json([row.get('simulation_id') or row.get('alpha_id'), row.get('expression_hash')])
        identities.setdefault(identity, set()).add(_json({k: v for k, v in row.items() if k not in ('arm_id', 'measurement_origin')}))
    if any(len(values) != 1 for values in identities.values()):
        limits.add('conflicting_simulation_evidence')
    if any(len({_json(r.get('metrics')) for r in rows}) != 1 for rows in by_arm.values()):
        limits.add('conflicting_metrics')
    for rows in by_arm.values():
        if len({_json({k: r.get(k) for k in ('checks', 'failed', 'pending', 'hard_pass')}) for r in rows}) > 1:
            limits.add('conflicting_checks')
    if len(arms) == 2:
        baseline, treatment = arms.get('baseline', {}), arms.get('treatment', {})
        if (baseline.get('scope') != treatment.get('scope') or baseline.get('settings') != treatment.get('settings')
                or baseline.get('binding', {}).get('bound_expression') == treatment.get('binding', {}).get('bound_expression')):
            limits.add('incompatible_controls')
        shared = set(baseline.get('binding', {}).get('bindings', {})) & set(treatment.get('binding', {}).get('bindings', {}))
        if any(baseline['binding']['bindings'][key] != treatment['binding']['bindings'][key] for key in shared):
            limits.add('incompatible_data_roles')
    differences = {}
    if all(len(by_arm.get(name, [])) == 1 for name in ('baseline', 'treatment')):
        baseline = by_arm['baseline'][0].get('metrics') or {}
        treatment = by_arm['treatment'][0].get('metrics') or {}
        for key in sorted(set(baseline) & set(treatment)):
            if all(type(v) in (int, float) and math.isfinite(v) for v in (baseline[key], treatment[key])):
                differences[key] = treatment[key] - baseline[key]
    # Compiler prediction_direction concerns the underlying field, not a metric.
    comparison = experiment.get('prediction_comparison')
    if (not isinstance(comparison, dict) or set(comparison) != {'metric', 'direction', 'control_arm'}
            or comparison.get('direction') not in ('greater', 'less') or comparison.get('control_arm') != 'baseline'):
        limits.add('explicit_comparison_absent')
    elif comparison.get('metric') not in differences:
        limits.add('comparison_metric_absent')
    label = 'inconclusive'
    if not limits:
        delta = differences[comparison['metric']]
        if delta:
            label = ('supports_prediction_in_scope' if (delta > 0) == (comparison['direction'] == 'greater')
                     else 'contradicts_prediction_in_scope')
        else:
            limits.add('comparison_tied')
    if any(_operational(row) for row in selected):
        label = 'operational_failure'
        limits.add('transport_failure_not_economic_falsification')
    families = sorted({r.get('template_provenance', {}).get('template_family') for r in selected
                       if r.get('template_provenance', {}).get('template_family')})
    return dict(group_id=_digest([experiment, period, cohort]), experiment_id=experiment.get('experiment_id'),
                cohort=deepcopy(cohort), mechanism_families=families,
                experiment=deepcopy(experiment), measurement_period=deepcopy(period), observations=_unique(selected),
                unique_simulations=len(identities), label=label, observed_differences=differences,
                limitations=sorted(limits), claims='Scoped observations only; no causal or statistical proof.')


def build_mechanism_evidence(records: list[dict], experiments: list[dict]) -> dict:
    """Input: caller-verified record/experiment dict lists. Output: reproducible derived view dict; no IO.

    Compiler prose/direction never supplies a numerical test. Only an already
    recorded prediction_comparison={metric, direction:greater|less,
    control_arm:baseline} can label a comparable measured pair. Current compiler
    experiments omit it and therefore remain inconclusive, retaining deltas.
    """
    if not isinstance(records, list) or not isinstance(experiments, list) or any(not isinstance(r, dict) for r in records + experiments):
        raise ValueError('records and experiments must be lists of objects')
    definitions = _unique(experiments + [exp for record in records for row in record.get('backtest', [])
                                       for exp in row.get('mechanism_experiments', [])])
    observations, reused, exclusions = [], [], []
    for record in records:
        for row in record.get('backtest', []):
            links = row.get('experiment_arms', [])
            if not links:
                exclusions.append(dict(reason='experiment_lineage_absent', expression_hash=row.get('expression_hash')))
            for link in links:
                if link.get('expression_hash') != row.get('expression_hash'):
                    exclusions.append(dict(reason='arm_identity_mismatch', link=link))
                    continue
                observations.append(dict({key: deepcopy(row[key]) for key in OBSERVATION_KEYS if key in row},
                                         experiment_id=link.get('experiment_id'), arm_id=link.get('arm_id')))
            for link in row.get('mechanism_reused_measurements', []):
                measurement = link.get('measurement')
                if not link.get('reused') or not isinstance(measurement, dict) or measurement.get('expression_hash') != link.get('expression_hash'):
                    exclusions.append(dict(reason='invalid_reused_measurement', link=link))
                    continue
                reused_row = {key: deepcopy(row[key]) for key in COHORT_KEYS if key in row and key not in ('scope', 'settings')}
                reused_row.update({key: deepcopy(measurement[key]) for key in OBSERVATION_KEYS if key in measurement})
                reused_row.update(experiment_id=link.get('experiment_id'), arm_id=link.get('arm_id'), measurement_origin='reused_control')
                reused.append(reused_row)
    # Drop only compatible sidecar copies; contradictory copies remain evidence.
    actual = {}
    for row in observations:
        key = (row['experiment_id'], row['arm_id'], row.get('expression_hash'), _json(row.get('measurement_period')))
        actual.setdefault(key, []).append(row)
    for row in reused:
        key = (row['experiment_id'], row['arm_id'], row.get('expression_hash'), _json(row.get('measurement_period')))
        matches = actual.get(key, [])
        measured = {k: row[k] for k in MEASUREMENT_KEYS if k in row}
        if not matches or any(measured != {k: original[k] for k in MEASUREMENT_KEYS if k in original} for original in matches):
            observations.append(row)
    observations = _unique(observations)
    groups = []
    for experiment in definitions:
        identifier = experiment.get('experiment_id')
        relevant = [r for r in observations if r['experiment_id'] == identifier]
        conflict = sum(e.get('experiment_id') == identifier for e in definitions) > 1
        cohorts = _unique([{key: r[key] for key in COHORT_KEYS if key in r} for r in relevant]) or [{}]
        for cohort in cohorts:
            rows = [r for r in relevant if {key: r[key] for key in COHORT_KEYS if key in r} == cohort]
            periods = _unique([r['measurement_period'] for r in rows if _known_period(r.get('measurement_period'))]) or [None]
            for period in periods:
                groups.append(_group(experiment, rows, period, conflict, cohort))
    known = {e.get('experiment_id') for e in definitions}
    exclusions.extend(dict(reason='experiment_definition_absent', observation=r) for r in observations if r['experiment_id'] not in known)
    return dict(schema_version=1, input_digest=_digest(dict(experiments=definitions, observations=observations,
                exclusions=_unique(exclusions))), groups=sorted(groups, key=lambda g: g['group_id']), exclusions=_unique(exclusions))


def select_mechanism_context(view: dict, query: dict, maximum: int = MAX_CONTEXT) -> dict:
    """Input: derived view/query dicts, exact int0..12. Output: bounded relevant observations and omitted count."""
    if type(maximum) is not int or not 0 <= maximum <= MAX_CONTEXT:
        raise ValueError('maximum must be an exact integer from 0 through 12')
    if not isinstance(view, dict) or not isinstance(query, dict):
        raise ValueError('view and query must be objects')
    eligible = []
    for group in view.get('groups', []):
        experiment = group['experiment']
        first_arm = next(iter(experiment.get('arms', [])), {})
        facts = dict(experiment, scope=first_arm.get('scope'), settings=first_arm.get('settings'))
        facts.update(group.get('cohort', {}))
        facts.update(experiment_id=group['experiment_id'], measurement_period=group['measurement_period'])
        if 'mechanism_family' in query and query['mechanism_family'] in group.get('mechanism_families', []):
            facts['mechanism_family'] = query['mechanism_family']
        if all(facts.get(key) == value for key, value in query.items()):
            eligible.append(group)
    eligible.sort(key=lambda g: (g['label'] == 'supports_prediction_in_scope', g['group_id']))
    return dict(input_digest=view['input_digest'], items=deepcopy(eligible[:maximum]), omitted_count=max(0, len(eligible) - maximum))
