"""Shared deterministic Repair limits and receipt verification; no model route."""

from pathlib import Path


DECAY_LIMIT = 32
TRUNCATION_LIMIT = 0.15
NEUTRALIZATIONS = ('SUBINDUSTRY', 'INDUSTRY', 'SECTOR', 'MARKET')


def verify_consumed_plan(run: Path, plan: dict) -> dict:
    """Input: owning run Path and plan dict. Output: verified deterministic receipt or ValueError."""
    if not isinstance(plan, dict) or plan.get('planner_kind') != 'deterministic':
        raise ValueError('model-driven Repair is retired; historical evidence is read-only')
    from wqb.repair_search import verify_persisted_search
    return verify_persisted_search(run, plan)
