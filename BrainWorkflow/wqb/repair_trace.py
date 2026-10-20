"""Offline experiment evidence; never authorizes simulation or submission."""
import math


TARGET_DIRECTIONS = {'sharpe': 'increase', 'fitness': 'increase', 'turnover': 'decrease'}
SCOPE_KEYS = ('region', 'delay', 'universe')


def _number(value):
    """Input: object. Output: bool. Require a finite real metric, excluding booleans."""
    return type(value) in (int, float) and math.isfinite(value)


def validate_experiment_target(decision: dict, parent: dict) -> None:
    """Input: decision/parent dicts. Output: None. Reject unmeasured or ambiguous targets."""
    metric = decision.get('target_metric')
    if not isinstance(parent.get('metrics'), dict):
        raise ValueError('Repair baseline metrics unavailable')
    if metric not in TARGET_DIRECTIONS or decision.get('target_direction') != TARGET_DIRECTIONS[metric]:
        raise ValueError('Repair requires a supported metric and its explicit improvement direction')
    if not _number((parent.get('metrics') or {}).get(metric)):
        raise ValueError('Repair target requires a finite measured baseline')
    for key in ('falsification', 'applicability'):
        if not isinstance(decision.get(key), str) or not decision[key].strip() or len(decision[key]) > 1600:
            raise ValueError('Repair requires bounded ' + key)


def compare_repair_experiment(parent: dict, child: dict, decision: dict) -> dict:
    """Input: measured rows/decision dicts. Output: trace dict. Compare evidence, not qualification."""
    result = {'schema_version': 1, 'baseline': parent, 'measured_child': child,
              'decision': decision, 'outcome': 'inconclusive', 'metric_changes': {},
              'submission_qualified': False, 'interpretation': 'Local measured comparison; not causal proof.'}
    try:
        validate_experiment_target(decision, parent)
    except ValueError as exc:
        return result | {'reason': str(exc)}
    if not isinstance(child.get('metrics'), dict):
        return result | {'reason': 'Measured child metrics unavailable'}
    missing_metrics = []
    for metric in TARGET_DIRECTIONS:
        a, b = parent['metrics'].get(metric), child['metrics'].get(metric)
        if _number(a) and _number(b):
            result['metric_changes'][metric] = {'before': a, 'after': b, 'delta': b - a}
        elif _number(a):
            missing_metrics.append(metric)
    if missing_metrics:
        return result | {'reason': 'Existing baseline metrics missing/nonfinite in child: ' + ', '.join(missing_metrics)}
    before, after = parent.get('settings', {}), child.get('settings', {})
    if not isinstance(before, dict) or not isinstance(after, dict):
        return result | {'reason': 'Missing measurement settings'}
    if any(key not in before or key not in after or before[key] != after[key] for key in SCOPE_KEYS):
        return result | {'reason': 'Measurement scope missing or changed'}
    if (child.get('parent_alpha_id') != parent.get('alpha_id') or
            child.get('parent_expression_hash') != parent.get('expression_hash')):
        return result | {'reason': 'Parent lineage mismatch'}
    edit = decision.get('edit')
    expected = dict(before)
    expression = parent.get('expression')
    if edit in ('decay', 'neutralization', 'truncation'):
        expected[edit] = decision.get('value')
    elif edit == 'flip_direction' and decision.get('value') == -1:
        expression = '-(' + str(expression) + ')'
    else:
        return result | {'reason': 'Unsupported controlled edit'}
    if expected != after or child.get('expression') != expression or (before == after and expression == parent.get('expression')):
        return result | {'reason': 'Not exactly the planned single edit; defaults or measurement settings differ'}
    for key in ('measurement_scope', 'test_period'):
        if parent.get(key) != child.get(key):
            return result | {'reason': 'Measurement period differs'}
    for key in ('startDate', 'endDate'):
        if (parent.get('metrics') or {}).get(key) != (child.get('metrics') or {}).get(key):
            return result | {'reason': 'Reported measurement dates differ or are missing on one side'}
    if not parent.get('test_period') and not all(parent['metrics'].get(key) for key in ('startDate', 'endDate')):
        return result | {'reason': 'Measurement period unavailable; do not infer comparability'}
    metric = decision['target_metric']
    if metric not in result['metric_changes']:
        return result | {'reason': 'Measured target missing or nonfinite'}
    delta = result['metric_changes'][metric]['delta']
    improved = delta > 0 if decision['target_direction'] == 'increase' else delta < 0
    new_failures = set(child.get('failed') or []) - set(parent.get('failed') or [])
    regressions = [name for name, change in result['metric_changes'].items()
                   if name != metric and (change['delta'] < 0 if TARGET_DIRECTIONS[name] == 'increase'
                                          else change['delta'] > 0)]
    accepted = improved and not new_failures and not regressions
    result.update(outcome='accept' if accepted else 'reject',
                  reason='Target improved without measured regressions or new failed checks' if accepted
                  else 'Target did not improve, another metric regressed, or new checks failed',
                  metric_regressions=regressions, remaining_checks=child.get('failed', []),
                  falsification_status='target_test_passed' if improved else 'target_test_failed')
    return result
