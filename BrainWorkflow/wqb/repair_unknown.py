"""Original-submission quarantine; no platform requests or resubmission authority."""

import hashlib
import json
from pathlib import Path

from wqb.runtime_control import _write
from wqb.repair_identity import identity_hash_scheme


UNKNOWN_FILE = 'result_unknown.json'
LEGACY_POLL_404 = 'RuntimeError: repair poll terminal HTTP 404; preserve submitted identity'


def bound_unknown_evidence(subrun: Path, parent_id: str, parent_hash: str, *, completed: bool = False) -> dict:
    """Input: source Path/parent identifiers. Output: bound evidence dict. Require exactly one original submission and no completion."""
    plan_path, events_path = subrun / 'repair_plan.json', subrun / 'simulation_events.jsonl'
    plan = json.loads(plan_path.read_text(encoding='utf-8'))
    if (plan.get('parent_alpha_id') != parent_id or plan.get('parent_expression_hash') != parent_hash
            or plan.get('maximum') != 1 or len(plan.get('variants', [])) != 1):
        raise ValueError('Unknown-result plan identity differs')
    variant = plan['variants'][0]
    if (not identity_hash_scheme(variant) or variant.get('parent_alpha_id') != parent_id
            or variant.get('parent_expression_hash') != parent_hash):
        raise ValueError('Unknown-result variant identity differs')
    events = [json.loads(line) for line in events_path.read_text(encoding='utf-8').splitlines() if line.strip()]
    relevant = [event for event in events if event.get('expression_hash') == variant['expression_hash']]
    submitted = [event for event in relevant if event.get('event') == 'SUBMITTED']
    completion = [event for event in relevant if event.get('event') == 'SIMULATION_COMPLETED']
    if (len(submitted) != 1 or not isinstance(submitted[0].get('progress_url'), str)
            or not submitted[0]['progress_url'] or not identity_hash_scheme(submitted[0])):
        raise ValueError('Unknown-result submission missing, duplicated or already completed')
    if completed:
        alpha_ids = {event.get('alpha_id') for event in completion}
        if (len(alpha_ids) != 1 or not all(isinstance(value, str) and value.isalnum() for value in alpha_ids)
                or any(not identity_hash_scheme(event) or event.get('parent_alpha_id') != parent_id
                       or event.get('parent_expression_hash') != parent_hash for event in completion)):
            raise ValueError('Exact original completion is unavailable')
    elif any(event.get('alpha_id') or event.get('event') in {'SIMULATION_COMPLETED', 'CHECKED'} for event in relevant):
        raise ValueError('Original result already has completion evidence')
    if any(submitted[0].get(key) != variant.get(key) for key in
            ('expression', 'settings', 'parent_alpha_id', 'parent_expression_hash')):
        raise ValueError('Unknown-result submission differs from plan')
    if not completed and (subrun / 'all_alphas.jsonl').exists():
        if any(json.loads(line).get('expression_hash') == variant['expression_hash']
               for line in (subrun / 'all_alphas.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()):
            raise ValueError('Unknown-result checked evidence already exists')
    return {'schema_version': 1, 'status': 'result_unknown', 'http_status': 404, 'phase': 'poll',
        'parent_alpha_id': parent_id, 'parent_expression_hash': parent_hash,
        'expression_hash': variant['expression_hash'], 'progress_url': submitted[0]['progress_url'],
        'plan_sha256': hashlib.sha256(plan_path.read_bytes()).hexdigest(),
        'events_sha256': hashlib.sha256(events_path.read_bytes()).hexdigest(),
        'automatic_resubmission_allowed': False, 'budget_refunded': False,
        'remeasurement_requires_separate_authorization': True, 'remeasurement_attempt_limit_if_authorized': 1}


def record_unknown(subrun: Path, parent_id: str, parent_hash: str) -> Path:
    """Input: original source and parent identities. Output: immutable receipt Path. Do not alter journals or quota."""
    payload = bound_unknown_evidence(subrun, parent_id, parent_hash)
    path = subrun / UNKNOWN_FILE
    if path.exists():
        if json.loads(path.read_text(encoding='utf-8')) != payload:
            raise ValueError('Unknown-result evidence changed')
    else:
        _write(path, payload)
    return path


def _attempt_source(root: Path, attempt: dict) -> Path:
    """Input: run and attempt. Output: exact source Path. Bind legacy base or AI iteration plus full variant."""
    base = (root / 'stages/repair/parents' /
        (attempt['parent_alpha_id'] + '-' + attempt['parent_expression_hash'][:12])).resolve()
    subrun = Path(attempt['source_run_dir']).resolve()
    if not subrun.is_relative_to((root / 'stages/repair/parents').resolve()) or attempt.get('max_simulations') != 1:
        raise ValueError('Unknown-result source outside attempt')
    if attempt.get('legacy') is True:
        if subrun != base:
            raise ValueError('Legacy attempt cannot use another iteration')
    else:
        plan = attempt.get('plan', {})
        digest = plan.get('evidence_digest', '')
        if not isinstance(digest, str) or len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
            raise ValueError('Unknown-result AI iteration identity missing')
        if subrun != (base / 'iterations' / digest).resolve():
            raise ValueError('Unknown-result AI iteration differs')
        source_plan = json.loads((subrun / 'repair_plan.json').read_text(encoding='utf-8'))
        if json.dumps(source_plan.get('variants'), sort_keys=True, allow_nan=False) != json.dumps(plan.get('variants'), sort_keys=True, allow_nan=False):
            raise ValueError('Unknown-result attempt variant differs')
    return subrun


def quarantine_source(root: Path, attempt: dict) -> Path | None:
    """Input: run Path and attempt dict. Output: validated source or None. Read-only eligibility, never treats404 as failure."""
    if not (attempt.get('phase') == 'result_unknown' or
            (attempt.get('phase') == 'blocked' and attempt.get('blocker') == LEGACY_POLL_404)):
        return None
    try:
        subrun = _attempt_source(root, attempt)
        payload = bound_unknown_evidence(subrun, attempt['parent_alpha_id'], attempt['parent_expression_hash'])
        if attempt.get('phase') == 'result_unknown' or (subrun / UNKNOWN_FILE).exists():
            if json.loads((subrun / UNKNOWN_FILE).read_text(encoding='utf-8')) != payload:
                return None
        return subrun
    except (OSError, ValueError, KeyError, TypeError):
        return None


def local_completion_source(root: Path, attempt: dict) -> Path | None:
    """Input: run and exact blocked404 attempt. Output: bound completion source or None. Never polls or submits."""
    if attempt.get('phase') != 'blocked' or attempt.get('blocker') != LEGACY_POLL_404:
        return None
    try:
        subrun = _attempt_source(root, attempt)
        bound_unknown_evidence(subrun, attempt['parent_alpha_id'], attempt['parent_expression_hash'], completed=True)
        return subrun
    except (OSError, ValueError, KeyError, TypeError):
        return None
