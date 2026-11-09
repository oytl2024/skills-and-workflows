"""Shared deterministic Repair limits and receipt verification; no model route."""

import json
from pathlib import Path


DECAY_LIMIT = 32
TRUNCATION_LIMIT = 0.15
NEUTRALIZATIONS = ('SUBINDUSTRY', 'INDUSTRY', 'SECTOR', 'MARKET')


def benchmark_resource_run(run: Path, subrun: Path) -> Path:
    """Input: owner/subrun Paths. Output: benchmark Path; new mode verifies the sealed owner, legacy stays local."""
    from wqb.execution_package import package_enabled, load_execution_package
    manifest_path = Path(run) / 'run_manifest.json'
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        if package_enabled(manifest.get('start_snapshot', {})):
            load_execution_package(Path(run))
            return Path(run)
    return Path(subrun)


def verify_consumed_plan(run: Path, plan: dict) -> dict:
    """Input: owning run Path and plan dict. Output: verified deterministic receipt or ValueError."""
    if not isinstance(plan, dict) or plan.get('planner_kind') != 'deterministic':
        raise ValueError('model-driven Repair is retired; historical evidence is read-only')
    from wqb.repair_search import verify_persisted_search
    return verify_persisted_search(run, plan)
