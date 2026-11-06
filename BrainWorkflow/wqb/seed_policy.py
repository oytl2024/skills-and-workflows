"""Pure, opt-in research policy; no runtime or submission authority."""
from copy import deepcopy
from datetime import date
import math
from pathlib import Path

from wqb.benchmark import benchmark_alpha_record
from wqb.benchmark_rules import (BenchmarkRule, benchmark_rule_to_dict,
                                default_benchmark_rules, validate_benchmark_rule_row)
from wqb.checker import SUBMISSION_ONLY_CHECKS


SCHEMA_VERSION = 1
DEFAULT_SEED_POLICY = {'schema_version': SCHEMA_VERSION, 'sharpe_floor': 1.25,
                       'turnover_max': .40, 'minimum_score': .55, 'seed_selection_limit': 8}
REQUIRED_METRICS = ('sharpe', 'fitness', 'returns', 'turnover')
SCOPE_KEYS = ('region', 'delay', 'universe')
TARGET_DIRECTIONS = {'sharpe': 'increase', 'fitness': 'increase', 'turnover': 'decrease'}
CONTROLLED_SETTINGS = ('decay', 'neutralization', 'truncation')
COMPARISON_KEYS = {'schema_version', 'target_metric', 'target_direction', 'edit',
                   'value', 'turnover_max', 'comparison_tolerance'}


def _finite(value) -> bool:
    """Input: arbitrary value. Output: bool indicating a finite non-boolean numeric metric."""
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def _text(value) -> bool:
    """Input: arbitrary value. Output: bool indicating a nonempty canonical string."""
    return isinstance(value, str) and bool(value.strip()) and value == value.strip()


def _identity(row: dict) -> dict:
    """Input: measured row/dict. Output: dict of stable measured identity, with default lane."""
    return {key: row.get(key, 'default' if key == 'lane_id' else None)
            for key in ('lane_id', 'alpha_id', 'expression_hash')}


def _check_names(items, expected: str) -> set | None:
    """Input: check list/object and expected status/str. Output: name set or None if invalid."""
    if not isinstance(items, list):
        return None
    names = set()
    for item in items:
        name = item.get('name') if isinstance(item, dict) else item
        if not _text(name) or (isinstance(item, dict) and item.get('result', expected) != expected):
            return None
        names.add(name)
    return names


def _research_errors(row) -> list[str]:
    """Input: measured row/object. Output: list[str] of invalid or incomplete baseline evidence."""
    if not isinstance(row, dict):
        return ['invalid_row']
    reasons = []
    if not all(_text(value) for value in _identity(row).values()):
        reasons.append('missing_identity')
    if row.get('status', 'CHECKED') != 'CHECKED':
        reasons.append('not_checked')
    metrics = row.get('metrics')
    if not isinstance(metrics, dict) or not all(_finite(metrics.get(key)) for key in REQUIRED_METRICS):
        reasons.append('invalid_baseline_metrics')
    failed = _check_names(row.get('failed'), 'FAIL')
    pending = _check_names(row.get('pending'), 'PENDING')
    if failed is None or pending is None:
        reasons.append('invalid_check_evidence')
    elif pending - SUBMISSION_ONLY_CHECKS or failed & pending:
        reasons.append('incomplete_baseline_checks')
    if 'hard_pass' in row and type(row['hard_pass']) is not bool:
        reasons.append('invalid_hard_pass')
    elif row.get('hard_pass') and (row.get('failed') or row.get('pending')):
        reasons.append('contradictory_hard_pass')
    return reasons


def _seed_policy(policy: dict) -> dict:
    """Input: frozen policy/dict. Output: resolved dict; raise ValueError for widening/unknown policy."""
    if not isinstance(policy, dict) or policy.keys() - DEFAULT_SEED_POLICY.keys():
        raise ValueError('Unknown Seed policy fields')
    resolved = DEFAULT_SEED_POLICY | policy
    if type(resolved['schema_version']) is not int or resolved['schema_version'] != SCHEMA_VERSION:
        raise ValueError('Unsupported Seed policy version')
    limit = resolved['seed_selection_limit']
    if type(limit) is not int or not 1 <= limit <= DEFAULT_SEED_POLICY['seed_selection_limit']:
        raise ValueError('Seed limit must be an integer from 1 to 8 per lane')
    for key in ('sharpe_floor', 'turnover_max', 'minimum_score'):
        if not _finite(resolved[key]):
            raise ValueError('Seed thresholds must be finite numbers')
    if (resolved['sharpe_floor'] < DEFAULT_SEED_POLICY['sharpe_floor'] or
            not 0 < resolved['turnover_max'] <= DEFAULT_SEED_POLICY['turnover_max'] or
            not DEFAULT_SEED_POLICY['minimum_score'] <= resolved['minimum_score'] <= 1):
        raise ValueError('Seed thresholds may only be tightened')
    return resolved


def _benchmark_rules(rules) -> list[BenchmarkRule]:
    """Input: list[BenchmarkRule] or None. Output: validated copied rules; [] stays empty."""
    rules = default_benchmark_rules() if rules is None else rules
    if not isinstance(rules, list) or any(not isinstance(rule, BenchmarkRule) for rule in rules):
        raise ValueError('Frozen benchmark rules must be a list of BenchmarkRule')
    for index, rule in enumerate(rules, 1):
        validate_benchmark_rule_row(benchmark_rule_to_dict(rule), Path('frozen_benchmark_rules'), index)
    return deepcopy(rules)


def _period(value) -> tuple[date, date] | None:
    """Input: {start,end} ISO-date dict or YYYY-YYYY str. Output: ordered dates tuple or None."""
    try:
        if isinstance(value, str) and len(value) == 9 and value[4] == '-':
            if any(char not in '0123456789' for char in value[:4] + value[5:]):
                return None
            start, end = date(int(value[:4]), 1, 1), date(int(value[5:]), 12, 31)
        elif isinstance(value, dict) and value.keys() == {'start', 'end'}:
            start, end = (_canonical_date(value[key]) for key in ('start', 'end'))
            if start is None or end is None:
                return None
        else:
            return None
        return (start, end) if start <= end else None
    except (TypeError, ValueError):
        return None


def _canonical_date(value) -> date | None:
    """Input: arbitrary value. Output: date or None; accept only actual canonical YYYY-MM-DD."""
    if not isinstance(value, str):
        return None
    try:
        parsed = date.fromisoformat(value)
        return parsed if parsed.isoformat() == value else None
    except ValueError:
        return None


def _measured_period(row: dict) -> tuple[date, date] | None:
    """Input: measured row/dict. Output: reconciled dates tuple or None for incomplete/conflicting dates."""
    declared = _period(row.get('test_period'))
    if declared is None:
        return None
    metrics = row['metrics']
    if not any(key in metrics for key in ('startDate', 'endDate')):
        return declared
    start, end = (_canonical_date(metrics.get(key)) for key in ('startDate', 'endDate'))
    if start is None or end is None or start > end:
        return None
    reported = (start, end)
    if isinstance(row['test_period'], str):
        # Legacy year labels have year precision, not invented January/December measurements.
        return reported if (start.year, end.year) == (declared[0].year, declared[1].year) else None
    return reported if reported == declared else None


def _settings_scope(settings) -> bool:
    """Input: settings/object. Output: bool requiring explicit CLI region, universe and delay."""
    return (isinstance(settings, dict) and _text(settings.get('region')) and
            _text(settings.get('universe')) and type(settings.get('delay')) is int and
            settings['delay'] >= 0)


def _measurement_errors(row: dict) -> list[str]:
    """Input: baseline-valid row/dict. Output: list[str] of missing context/CLI identity defects."""
    if not _text(row.get('expression')) or not _settings_scope(row.get('settings')):
        return ['invalid_expression_or_settings']
    if not _context(row.get('measurement_scope')):
        return ['invalid_measurement_scope']
    if _measured_period(row) is None:
        return ['invalid_measurement_period']
    from wqb.cli import simulation_identity_hash

    try:
        identity = simulation_identity_hash(row['expression'], row['settings'])
    except (TypeError, ValueError, OverflowError):
        return ['invalid_simulation_identity']
    return [] if row.get('simulation_identity') == identity else ['invalid_simulation_identity']


def select_seeds(rows: list[dict], policy: dict, *, benchmark_rules: list[BenchmarkRule] | None = None) -> dict:
    """Input: checked rows/list[dict], frozen policy/dict. Output: ranked research-only envelope/dict.

    Policy defaults are DEFAULT_SEED_POLICY; only stricter thresholds/limits are accepted.
    Rows require expression/settings, CLI simulation_identity, measurement_scope and test_period.
    benchmark_rules explicitly freezes triage rules; [] disables them, None uses pure defaults.
    Only existing hard_pass/repairable_signal labels are eligible before score ranking.
    Scores are recomputed using the existing triage benchmark, never a supplied score.
    No files, active policy, submission checks or runtime state are read or modified.
    """
    resolved = _seed_policy(policy)
    rules = _benchmark_rules(benchmark_rules)
    if not isinstance(rows, list):
        raise ValueError('Seed rows must be a list')
    rejected, eligible = [], []
    groups = {}
    for row in rows:
        identity = _identity(row) if isinstance(row, dict) else None
        if identity is None or not all(_text(value) for value in identity.values()):
            rejected.append({'identity': identity, 'reasons': _research_errors(row)})
            continue
        key = tuple(identity.values())
        groups.setdefault(key, []).append(row)
    for key, versions in sorted(groups.items()):
        row = versions[0]
        identity = _identity(row)
        if any(other != row for other in versions[1:]):
            rejected.append({'identity': identity, 'reasons': ['conflicting_identity']})
            continue
        errors = _research_errors(row)
        if not errors:
            errors = _measurement_errors(row)
        if errors:
            rejected.append({'identity': identity, 'reasons': errors})
            continue
        metrics = row['metrics']
        reasons = []
        if metrics['sharpe'] <= resolved['sharpe_floor']:
            reasons.append('sharpe_not_above_floor')
        if not 0 <= metrics['turnover'] < resolved['turnover_max']:
            reasons.append('turnover_out_of_bounds')
        if reasons:
            rejected.append({'identity': identity, 'reasons': reasons})
            continue
        # Correlations may be deferred for research, but persisted evidence stays unchanged.
        assessment = {**row, 'pending': [item for item in row['pending']
                      if (item.get('name') if isinstance(item, dict) else item) not in SUBMISSION_ONLY_CHECKS]}
        benchmark = benchmark_alpha_record(assessment, benchmark_rules=rules, consumer='triage')
        entry = {'identity': identity, 'score': benchmark.score,
                 'benchmark_label': benchmark.label, 'metrics': deepcopy(metrics),
                 'reasons': list(benchmark.reasons), 'submission_qualified': False}
        if benchmark.score < resolved['minimum_score']:
            rejected.append(entry | {'reasons': ['score_below_minimum'] + entry['reasons']})
        elif benchmark.label not in ('hard_pass', 'repairable_signal'):
            rejected.append(entry | {'reasons': ['benchmark_not_research_eligible'] + entry['reasons']})
        else:
            eligible.append(entry)
    eligible.sort(key=lambda entry: (entry['identity']['lane_id'], -entry['score'],
                                    -entry['metrics']['sharpe'], entry['identity']['alpha_id'],
                                    entry['identity']['expression_hash']))
    selected, counts = [], {}
    for entry in eligible:
        lane = entry['identity']['lane_id']
        if counts.get(lane, 0) >= resolved['seed_selection_limit']:
            rejected.append(entry | {'reasons': ['lane_limit']})
        else:
            selected.append(entry)
            counts[lane] = counts.get(lane, 0) + 1
    rejected.sort(key=lambda entry: tuple(str((entry['identity'] or {}).get(key, ''))
                                         for key in ('lane_id', 'alpha_id', 'expression_hash')))
    return {'schema_version': SCHEMA_VERSION, 'policy': resolved,
            'status': 'selected' if selected else 'no_seed', 'selected': selected,
            'rejected': rejected, 'submission_qualified': False,
            'next_action': 'repair_selected_seeds' if selected else 'rotate_research_choice'}


def _comparison_policy(policy) -> list[str]:
    """Input: comparison policy/object. Output: list[str] of missing/unsupported declarations."""
    if not isinstance(policy, dict) or policy.keys() - COMPARISON_KEYS:
        return ['invalid_comparison_policy']
    if (type(policy.get('schema_version', SCHEMA_VERSION)) is not int or
            policy.get('schema_version', SCHEMA_VERSION) != SCHEMA_VERSION):
        return ['unsupported_policy_version']
    metric = policy.get('target_metric')
    if not isinstance(metric, str) or metric not in TARGET_DIRECTIONS:
        return ['unsupported_target']
    if policy.get('target_direction') != TARGET_DIRECTIONS[metric]:
        return ['invalid_target_direction']
    if not _finite(policy.get('turnover_max')) or policy['turnover_max'] <= 0:
        return ['missing_declared_turnover_bound']
    tolerance = policy.get('comparison_tolerance', 0)
    if not _finite(tolerance) or tolerance != 0:
        return ['unsupported_comparison_tolerance']
    if policy.get('edit') == 'feature':
        return [] if 'value' not in policy else ['unsupported_controlled_value']
    if policy.get('edit') == 'transform':
        return [] if _finite(policy.get('value')) else ['unsupported_controlled_value']
    if policy.get('edit') not in CONTROLLED_SETTINGS or 'value' not in policy:
        return ['unsupported_controlled_edit']
    edit, value = policy['edit'], policy['value']
    if ((edit == 'decay' and (type(value) is not int or value < 0)) or
            (edit == 'neutralization' and not _text(value)) or
            (edit == 'truncation' and (not _finite(value) or not 0 <= value <= 1))):
        return ['invalid_controlled_value']
    return []


def _context(value) -> bool:
    """Input: scope/period object. Output: bool requiring an explicit label or nonempty scalar mapping."""
    return _text(value) or (isinstance(value, dict) and bool(value) and
                           all(_text(key) and (_text(item) or _finite(item))
                               for key, item in value.items()))


def _comparison_context_errors(parent: dict, child: dict, policy: dict) -> list[str]:
    """Input: validated rows and policy dicts. Output: list[str] of comparability/control defects."""
    if (parent['alpha_id'] == child['alpha_id'] or
            _identity(parent)['lane_id'] != _identity(child)['lane_id'] or
            child.get('parent_alpha_id') != parent['alpha_id'] or
            child.get('parent_expression_hash') != parent['expression_hash']):
        return ['parent_lineage_mismatch']
    before, after = parent.get('settings'), child.get('settings')
    if not isinstance(before, dict) or not isinstance(after, dict):
        return ['missing_settings']
    for settings in (before, after):
        if not _settings_scope(settings):
            return ['invalid_measurement_scope']
    if any(before[key] != after[key] for key in SCOPE_KEYS):
        return ['measurement_scope_mismatch']
    if not _context(parent.get('measurement_scope')) or parent['measurement_scope'] != child.get('measurement_scope'):
        return ['measurement_scope_mismatch']
    if (_period(parent.get('test_period')) is None or
            _period(parent.get('test_period')) != _period(child.get('test_period'))):
        return ['measurement_period_mismatch']
    periods = [_measured_period(row) for row in (parent, child)]
    if None in periods or periods[0] != periods[1]:
        return ['measurement_period_mismatch']
    if policy['edit'] in ('feature', 'transform'):
        return [] if before == after else ['not_exact_controlled_change']
    expected = before | {policy['edit']: policy['value']}
    if (not _text(parent.get('expression')) or child.get('expression') != parent['expression'] or
            expected != after or before == after):
        return ['not_exact_controlled_change']
    return []


def _feature_errors(parent: dict, child: dict, node) -> list[str]:
    """Input: measured rows and authenticated frozen node/dict. Output: list[str] of Scout control defects.

    Caller must authenticate the owning run's approved tree_digest and compiler provenance,
    as with experiment_tree. A digest detects drift; it does not certify arbitrary new expressions.
    """
    from wqb.experiment_tree import route_pair

    if route_pair(node, [])['node_id'] is None:
        return ['invalid_frozen_feature_node']
    try:
        receipt = node['pair_receipt']
        if receipt['status'] != 'compiled' or not _text(receipt['experiment']['compilation_digest']):
            return ['invalid_compiler_receipt']
        arms = receipt['experiment']['arms']
        if (not isinstance(arms, list) or len(arms) != 2 or
                {arm['arm_id'] for arm in arms} != {'baseline', 'treatment'}):
            return ['incomplete_compiler_pair']
        compiled = {arm['arm_id']: arm for arm in arms}
        for arm_id, row in (('baseline', parent), ('treatment', child)):
            errors = _measurement_errors(row)
            if errors:
                return errors
            expected = node['expected'][arm_id]
            arm = compiled[arm_id]
            if (row['simulation_identity'] != expected['simulation_identity'] or
                    node['expected_simulation_identities'][arm_id] != row['simulation_identity'] or
                    row['expression'] != expected['expression'] or
                    row['settings'] != expected['settings'] or
                    expected['expression'] != arm['binding']['bound_expression'] or
                    expected['settings'] != arm['settings'] or
                    expected['scope'] != arm['scope'] or expected['scope'] != node['scope'] or
                    expected['period'] != node['period'] or
                    _period(row['test_period']) != _period(node['period']) or
                    _measured_period(row) != _period(node['period']) or
                    any(row['settings'][key] != node['scope'][key] for key in SCOPE_KEYS)):
                return ['frozen_feature_identity_mismatch']
        if parent['expression'] == child['expression']:
            return ['not_exact_controlled_change']
    except (KeyError, TypeError, ValueError):
        return ['invalid_frozen_feature_node']
    return []


def _transform_errors(parent: dict, child: dict, policy: dict, frozen_search: dict | None) -> list[str]:
    """Input: measured rows/comparison policy/frozen search dicts. Output: deterministic transform proof errors."""
    from pathlib import Path
    from wqb.repair_search import prepare_search
    if not isinstance(frozen_search, dict) or set(frozen_search) != {'policy', 'history'}:
        return ['missing_frozen_transform_search']
    result = prepare_search(Path('.'), parent, frozen_search['history'], 1, frozen_search['policy'])
    if result['status'] != 'validated' or len(result['variants']) != 1:
        return ['invalid_frozen_transform_search']
    expected = result['variants'][0]
    if (expected['decision']['edit'] != 'transform'
            or any(expected['decision'][key] != policy[key] for key in ('edit', 'value', 'target_metric', 'target_direction'))
            or any(expected[key] != child.get(key) for key in ('expression', 'settings', 'expression_hash'))):
        return ['transform_differs_from_verified_search']
    return _measurement_errors(parent) + _measurement_errors(child)


def compare_versions(parent: dict, child: dict, policy: dict, *, frozen_node: dict | None = None,
                     frozen_search: dict | None = None) -> dict:
    """Input: measured parent/child dicts, declared policy/dict. Output: comparison envelope/dict.

    Policy requires target_metric/direction, edit/value and exclusive turnover_max;
    schema_version defaults to 1, comparison_tolerance to 0 (only supported value).
    Only declared decay/neutralization/truncation changes with fixed expression,
    lane, scope and period are comparable. Missing evidence is inconclusive.
    Opt-in edit='feature' (no value) requires frozen_node from validate_tree, authenticated
    against the approved run by the caller. Both complete compiled arms, CLI identities,
    expressions and identical settings must match; no arbitrary expression flags accepted.
    edit='transform' requires a frozen_search re-executed through the typed finite
    provider. Its caller must authenticate policy/resources against run provenance.
    All results retain both measurements; only accepted children replace incumbent.
    This does not call or change legacy repair_trace or confer candidate eligibility.
    """
    result = {'schema_version': SCHEMA_VERSION, 'policy': deepcopy(policy),
              'baseline': deepcopy(parent), 'measured_child': deepcopy(child),
              'outcome': 'inconclusive', 'incumbent': _identity(parent) if isinstance(parent, dict) else None,
              'metric_changes': {}, 'reasons': [], 'new_baseline_failures': [],
              'metric_regressions': [], 'submission_qualified': False}
    errors = _comparison_policy(policy)
    for label, row in (('parent', parent), ('child', child)):
        errors.extend(label + ':' + reason for reason in _research_errors(row))
    if errors:
        return result | {'reasons': errors}
    if parent['metrics']['turnover'] < 0:
        return result | {'reasons': ['invalid_parent_turnover']}
    errors = _comparison_context_errors(parent, child, policy)
    if not errors and policy['edit'] == 'feature':
        errors = _feature_errors(parent, child, frozen_node)
    if not errors and policy['edit'] == 'transform':
        errors = _transform_errors(parent, child, policy, frozen_search)
    if errors:
        return result | {'reasons': errors}
    for metric in REQUIRED_METRICS:
        a, b = parent['metrics'][metric], child['metrics'][metric]
        delta = b - a
        if not _finite(delta):
            return result | {'reasons': ['nonfinite_metric_delta']}
        result['metric_changes'][metric] = {'before': a, 'after': b, 'delta': delta}
    metric = policy['target_metric']
    a, b = parent['metrics'][metric], child['metrics'][metric]
    improved = b > a if policy['target_direction'] == 'increase' else b < a
    regressions = [key for key in ('sharpe', 'fitness') if child['metrics'][key] < parent['metrics'][key]]
    failures = (_check_names(child['failed'], 'FAIL') -
                _check_names(parent['failed'], 'FAIL') - SUBMISSION_ONLY_CHECKS)
    reasons = []
    if not improved:
        reasons.append('objective_not_improved')
    if regressions:
        reasons.append('sharpe_or_fitness_regressed')
    if failures:
        reasons.append('new_baseline_failures')
    if not 0 <= child['metrics']['turnover'] < policy['turnover_max']:
        reasons.append('turnover_out_of_declared_bounds')
    accepted = not reasons
    result.update(outcome='accepted' if accepted else 'rejected',
                  incumbent=_identity(child if accepted else parent),
                  reasons=reasons or ['objective_improved_without_baseline_regression'],
                  new_baseline_failures=sorted(failures), metric_regressions=regressions)
    return result
