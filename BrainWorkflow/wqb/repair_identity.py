"""Verified simulation identities; activity snapshots never confer qualification."""

import hashlib
import json

from wqb.expression import expression_hash


ACTIVITY_SNAPSHOT_CHECKS = {'MATCHES_COMPETITION', 'MATCHES_THEMES'}


def _same_json(left: object, right: object) -> bool:
    """Input: JSON evidence values. Output: bool. Preserve numeric/boolean types and reject nonfinite evidence."""
    try:
        return json.dumps(left, sort_keys=True, allow_nan=False) == json.dumps(right, sort_keys=True, allow_nan=False)
    except (TypeError, ValueError):
        return False


def identity_hash_scheme(row: dict) -> str:
    """Input: result/variant dict. Output: verified scheme str or empty. Recompute only known hash algorithms."""
    if not isinstance(row.get('expression'), str) or not isinstance(row.get('settings'), dict) or not row['settings']:
        return ''
    canonical = hashlib.sha256(json.dumps([row['expression'], row['settings']], sort_keys=True).encode()).hexdigest()
    if row.get('expression_hash') == canonical:
        return 'repair_json_pair'
    legacy = expression_hash(row['expression'] + '\n' + json.dumps(row['settings'], ensure_ascii=False, sort_keys=True))
    return 'legacy_simulation' if row.get('expression_hash') == legacy else ''


def _metrics(row: dict, research_only: bool) -> dict | None:
    """Input: measured row and research-only bool. Output: comparison dict or None. Retain all nonactivity evidence."""
    raw = row.get('metrics', {})
    if not isinstance(raw, dict):
        return None
    metrics = {key: value for key, value in raw.items() if key != 'candidate_evidence'}
    if research_only and 'checks' in metrics:
        checks = metrics['checks']
        if not isinstance(checks, list) or any(not isinstance(check, dict) for check in checks):
            return None
        if any(check.get('name') in ACTIVITY_SNAPSHOT_CHECKS and check.get('result') not in ('PASS', 'WARNING')
               for check in checks):
            return None
        metrics['checks'] = [check for check in checks if check.get('name') not in ACTIVITY_SNAPSHOT_CHECKS]
    return metrics


def verified_platform_alias(saved: dict, child: dict) -> bool:
    """Input: checked rows. Output: bool. Separate proven simulation identity from nonqualifying activity snapshots."""
    if not saved.get('alpha_id') or saved.get('alpha_id') != child.get('alpha_id') or saved.get('expression') != child.get('expression'):
        return False
    schemes = [identity_hash_scheme(row) for row in (saved, child)]
    if not all(schemes):
        return False
    left, right = saved['settings'], child['settings']
    if 'legacy_simulation' in schemes and not _same_json(left, right):
        return False
    if not (set(left) <= set(right) or set(right) <= set(left)) or any(not _same_json(left[k], right[k]) for k in set(left) & set(right)):
        return False
    if any(saved.get(key) != child.get(key) for key in ('status', 'failed', 'pending', 'hard_pass')):
        return False
    research_only = saved.get('hard_pass') is False and child.get('hard_pass') is False
    before, after = _metrics(saved, research_only), _metrics(child, research_only)
    return before is not None and after is not None and _same_json(before, after)


def matching_simulation_rows(known: list, variant: dict) -> list | None:
    """Input: published rows and planned variant. Output: exact compatible matches, [] absent, None conflicted."""
    from wqb.stage_outcomes import validate_checked_rows
    matches = [row for row in known if row.get('expression') == variant.get('expression')
               and row.get('settings') == variant.get('settings') and isinstance(variant.get('settings'), dict)]
    if not matches:
        return []
    if not identity_hash_scheme(variant) or any(not identity_hash_scheme(row) for row in matches):
        return None
    if any(not _same_json(row['settings'], variant['settings']) for row in matches):
        return None
    if len(validate_checked_rows(matches)) != len(matches):
        return None
    if any(not verified_platform_alias(matches[0], row) for row in matches):
        return None
    return matches
