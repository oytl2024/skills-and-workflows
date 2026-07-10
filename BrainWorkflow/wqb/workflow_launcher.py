from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any


DEFAULT_KNOWLEDGE_ARTIFACTS = {
    "data_ledger": "wiki/20_semantics/data_ledger.jsonl",
    "template_library": "wiki/30_templates/template_library.jsonl",
    "freshness_manifest": "wiki/80_maintenance/freshness_manifest.json",
    "benchmark_rules": "wiki/50_benchmarks/correlation_and_novelty.md",
    "activity_snapshot": "wiki/10_foundations/activity_snapshot.md",
}


@dataclass(frozen=True)
class WorkflowLaunchConfig:
    knowledge_root: str
    run_root: str = "runs"
    objective: str = "current-incentives"
    region: str = "USA"
    universe: str = "TOP3000"
    delay: int = 1
    instrument_type: str = "EQUITY"
    mode: str = "plan-only"
    batch_size: int = 30
    max_simulation_budget: int = 30
    live_api_enabled: bool = False
    submit_policy: str = "blocked"
    lanes: list[str] = field(default_factory=lambda: ["knowledge-readiness", "data-scheduling", "template-selection"])


@dataclass(frozen=True)
class WorkflowRunManifest:
    run_id: str
    generated_at: str
    run_dir: str
    objective: str
    region: str
    universe: str
    delay: int
    instrument_type: str
    mode: str
    batch_size: int
    max_simulation_budget: int
    live_api_enabled: bool
    submit_policy: str
    knowledge_root: str
    knowledge_artifacts: dict[str, str]
    readiness_report_path: str
    handoff_dir: str
    lanes: list[str]


def _load_json(path: Path) -> dict[str, Any]:
    """Input: JSON path. Output: dict. Load optional config file."""
    if not path or not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"workflow config must be a JSON object: {path}")
    return payload


def load_workflow_launch_config(
    defaults_path: Path,
    local_path: Path | None = None,
    overrides: dict[str, Any] | None = None,
) -> WorkflowLaunchConfig:
    """Input: config paths and overrides. Output: launch config. Merge launcher settings."""
    data: dict[str, Any] = {}
    data.update(_load_json(defaults_path))
    if local_path is not None:
        data.update(_load_json(local_path))
    data.update({key: value for key, value in (overrides or {}).items() if value is not None})
    if "knowledge_root" not in data:
        data["knowledge_root"] = "knowledge"
    if "live_api_enabled" in data and not isinstance(data["live_api_enabled"], bool):
        raise ValueError("workflow config live_api_enabled must be a boolean")
    return WorkflowLaunchConfig(**{key: value for key, value in data.items() if key in WorkflowLaunchConfig.__dataclass_fields__})


def _slug(value: str) -> str:
    """Input: string. Output: slug. Build stable run id fragments."""
    cleaned = "".join(char.lower() if char.isalnum() else "-" for char in value).strip("-")
    return "-".join(part for part in cleaned.split("-") if part) or "workflow"


def create_run_manifest(config: WorkflowLaunchConfig, generated_at: str | None = None) -> WorkflowRunManifest:
    """Input: launch config and timestamp. Output: run manifest. Create one auditable run manifest."""
    generated = generated_at or datetime.now(timezone.utc).isoformat(timespec="microseconds")
    timestamp_slug = "".join(char for char in generated if char.isalnum())
    run_id = f"{timestamp_slug}-{_slug(config.objective)}"
    run_dir = str(Path(config.run_root) / run_id)
    readiness_path = str(Path(run_dir) / "readiness_report.md")
    handoff_dir = str(Path(run_dir) / "handoffs")
    return WorkflowRunManifest(
        run_id=run_id,
        generated_at=generated,
        run_dir=run_dir,
        objective=config.objective,
        region=config.region,
        universe=config.universe,
        delay=int(config.delay),
        instrument_type=config.instrument_type,
        mode=config.mode,
        batch_size=int(config.batch_size),
        max_simulation_budget=int(config.max_simulation_budget),
        live_api_enabled=bool(config.live_api_enabled),
        submit_policy=config.submit_policy,
        knowledge_root=config.knowledge_root,
        knowledge_artifacts=dict(DEFAULT_KNOWLEDGE_ARTIFACTS),
        readiness_report_path=readiness_path,
        handoff_dir=handoff_dir,
        lanes=list(config.lanes),
    )


def workflow_run_manifest_to_dict(manifest: WorkflowRunManifest) -> dict[str, Any]:
    """Input: manifest. Output: dict. Convert launch manifest to JSON-safe data."""
    return asdict(manifest)


def write_run_manifest(path: Path, manifest: WorkflowRunManifest) -> Path:
    """Input: output path and manifest. Output: path. Write run manifest JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(workflow_run_manifest_to_dict(manifest), ensure_ascii=False, indent=2), encoding="utf-8")
    return path
