from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
from typing import Any

from wqb.knowledge_paths import existing_machine_resource_path

BENCHMARK_RULES_PATH = Path("machine") / "benchmark_rules.jsonl"
BENCHMARK_RULE_REQUIRED_FIELDS = {
    "rule_id",
    "issue_types",
    "description",
    "promotion_condition",
    "action",
    "evidence_paths",
    "consumed_by",
    "risk",
}
OFFICIAL_WORKFLOW_MARKER_FILES = ("run_state.json", "workflow_events.jsonl")
START_SNAPSHOT_VERSION = 2
LEGACY_START_SNAPSHOT_BENCHMARK_RULES_PATHS = (
    Path("wiki") / "50_benchmarks" / "benchmark_rules.jsonl",
)


@dataclass(frozen=True)
class BenchmarkRule:
    rule_id: str
    issue_types: list[str]
    description: str
    promotion_condition: str
    action: str
    evidence_paths: list[str]
    consumed_by: list[str]
    risk: str


def benchmark_rule_from_dict(row: dict[str, Any]) -> BenchmarkRule:
    """Input: dict row. Output: BenchmarkRule. Normalize one active benchmark rule."""
    return BenchmarkRule(
        rule_id=str(row.get("rule_id", "")),
        issue_types=[str(item) for item in row.get("issue_types", []) if str(item)],
        description=str(row.get("description", "")),
        promotion_condition=str(row.get("promotion_condition", "")),
        action=str(row.get("action", "")),
        evidence_paths=[str(item) for item in row.get("evidence_paths", []) if str(item)],
        consumed_by=[str(item) for item in row.get("consumed_by", []) if str(item)],
        risk=str(row.get("risk", "")),
    )


def benchmark_rule_to_dict(rule: BenchmarkRule) -> dict[str, Any]:
    """Input: BenchmarkRule. Output: dict. Convert rule to JSON-safe row."""
    return asdict(rule)


def benchmark_rulebook_digest(rules: list[BenchmarkRule]) -> str:
    """Input: benchmark rules. Output: SHA-256 string. Hash normalized rule rows for run binding."""
    payload = json.dumps(
        [benchmark_rule_to_dict(rule) for rule in rules],
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def default_benchmark_rules() -> list[BenchmarkRule]:
    """Input: none. Output: default benchmark rules. Seed active rules from Stage 1 lessons."""
    return [
        BenchmarkRule(
            rule_id="near_miss_stable_pnl_promotion",
            issue_types=["pnl_signal", "near_miss"],
            description="Stable PnL shape should promote an alpha into repair review even when one metric misses threshold.",
            promotion_condition="PnL is visually stable or monotonic enough to resemble the 3q7OQaog signal-recognition case.",
            action="Create a repair candidate and test one lever at a time before abandoning.",
            evidence_paths=[
                "knowledge/machine/benchmark_rules.jsonl",
                "knowledge/wiki/40_benchmark_and_repair_rules.md",
                "knowledge/wiki/50_engineering_lessons.md",
            ],
            consumed_by=["triage", "repair_loop", "candidate_gate", "workflow_proposals"],
            risk="May spend repair budget on fragile in-sample signals.",
        ),
        BenchmarkRule(
            rule_id="prod_correlation_novelty_required",
            issue_types=["prod_correlation", "correlation"],
            description="Repeated production-correlation failures require a distinct data source, operator skeleton, or economic hypothesis.",
            promotion_condition="Candidate or family fails production correlation after otherwise acceptable metrics.",
            action="Down-rank the data-template pair and request template or data novelty before another batch.",
            evidence_paths=[
                "knowledge/machine/benchmark_rules.jsonl",
                "knowledge/wiki/40_benchmark_and_repair_rules.md",
                "knowledge/wiki/50_engineering_lessons.md",
            ],
            consumed_by=["research_planner", "candidate_gate", "repair_loop"],
            risk="May suppress a family that could pass with a large quality improvement.",
        ),
    ]


def load_benchmark_rules(path: Path) -> list[BenchmarkRule]:
    """Input: JSONL path. Output: benchmark rules. Load active rulebook."""
    if not path.exists():
        return []
    rules: list[BenchmarkRule] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        row = json.loads(line)
        validate_benchmark_rule_row(row, path, line_number)
        rules.append(benchmark_rule_from_dict(row))
    return rules


def validate_benchmark_rule_row(row: Any, path: Path, line_number: int) -> None:
    """Input: JSON value, path, line number. Output: none. Validate one runtime benchmark rule row."""
    location = f"{path}:{line_number}"
    if not isinstance(row, dict):
        raise ValueError(f"{location}: benchmark rule must be an object")
    missing = sorted(BENCHMARK_RULE_REQUIRED_FIELDS - row.keys())
    if missing:
        raise ValueError(f"{location}: benchmark rule missing required fields: {', '.join(missing)}")
    for field_name in ("rule_id", "description", "promotion_condition", "action", "risk"):
        if not isinstance(row[field_name], str) or not row[field_name].strip():
            raise ValueError(f"{location}: benchmark rule field {field_name} must be a non-empty string")
    for field_name in ("issue_types", "evidence_paths", "consumed_by"):
        value = row[field_name]
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            raise ValueError(f"{location}: benchmark rule field {field_name} must be a string list")
    for field_name in ("issue_types", "consumed_by"):
        if not row[field_name] or any(not item.strip() for item in row[field_name]):
            raise ValueError(f"{location}: benchmark rule field {field_name} must contain non-empty strings")


def load_active_benchmark_rules(
    knowledge_root: str | Path, fallback_to_defaults: bool = True
) -> list[BenchmarkRule]:
    """Input: vault root and fallback flag. Output: active rules. Prefer the persisted benchmark rulebook."""
    path = benchmark_rules_path_for_knowledge(knowledge_root)
    if path.exists():
        return load_benchmark_rules(path)
    if not fallback_to_defaults:
        return []
    return default_benchmark_rules()


def benchmark_rules_path_for_knowledge(knowledge_root: str | Path) -> Path:
    """Input: knowledge root. Output: Path. Return the current benchmark-rule authority path."""
    return existing_machine_resource_path(knowledge_root, "benchmark_rules")


def _is_accepted_start_snapshot_rulebook_path(path_value: Any) -> bool:
    """Input: snapshot path value. Output: bool. Accept current path plus immutable legacy snapshot aliases."""
    if not isinstance(path_value, str):
        return False
    accepted = {
        BENCHMARK_RULES_PATH.as_posix(),
        *(path.as_posix() for path in LEGACY_START_SNAPSHOT_BENCHMARK_RULES_PATHS),
    }
    return path_value in accepted


def benchmark_rules_from_start_snapshot(snapshot: Any) -> list[BenchmarkRule]:
    """Input: start snapshot value. Output: bound rules. Validate immutable benchmark rule authority."""
    if not isinstance(snapshot, dict):
        raise ValueError("start snapshot is required for benchmark rule authority")
    version = snapshot.get("artifact_binding_version")
    if isinstance(version, bool) or not isinstance(version, int):
        raise ValueError("start snapshot version is unsupported")
    if version != START_SNAPSHOT_VERSION:
        raise ValueError("start snapshot version is unsupported")
    authority = snapshot.get("benchmark_rulebook")
    if not isinstance(authority, dict):
        raise ValueError("start snapshot benchmark rulebook is missing")
    if not _is_accepted_start_snapshot_rulebook_path(authority.get("path", "")):
        raise ValueError("start snapshot benchmark rulebook path is not canonical")
    rows = authority.get("rules")
    if not isinstance(rows, list) or not rows:
        raise ValueError("start snapshot benchmark rule rows are required")
    rules: list[BenchmarkRule] = []
    snapshot_path = Path("run_manifest.json") / "start_snapshot" / "benchmark_rulebook"
    for line_number, row in enumerate(rows, start=1):
        validate_benchmark_rule_row(row, snapshot_path, line_number)
        rules.append(benchmark_rule_from_dict(row))
    expected_digest = str(authority.get("sha256", ""))
    if not expected_digest or benchmark_rulebook_digest(rules) != expected_digest:
        raise ValueError("start snapshot benchmark rulebook digest mismatch")
    return rules


def load_run_benchmark_rules(run_dir: str | Path) -> list[BenchmarkRule] | None:
    """Input: run directory. Output: bound rules or none. Load official snapshot authority when present."""
    root = Path(run_dir)
    manifest_path = root / "run_manifest.json"
    if not manifest_path.exists():
        if any((root / marker).exists() for marker in OFFICIAL_WORKFLOW_MARKER_FILES):
            raise ValueError("start snapshot benchmark rule authority is missing")
        return None
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("run manifest must be a JSON object")
    if "start_snapshot" not in manifest:
        raise ValueError("start snapshot benchmark rule authority is missing")
    try:
        return benchmark_rules_from_start_snapshot(manifest.get("start_snapshot"))
    except ValueError as exc:
        raise ValueError(f"start snapshot benchmark rule authority is invalid: {exc}") from exc


def write_benchmark_rules_jsonl(path: Path, rules: list[BenchmarkRule]) -> Path:
    """Input: path and rules. Output: path. Write deterministic benchmark JSONL."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for rule in sorted(rules, key=lambda item: item.rule_id):
            handle.write(json.dumps(benchmark_rule_to_dict(rule), ensure_ascii=False, sort_keys=True) + "\n")
    return path


def write_benchmark_rules_markdown(path: Path, rules: list[BenchmarkRule], generated_at: str) -> Path:
    """Input: path, rules, timestamp. Output: path. Write readable active benchmark rules."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Benchmark Rules", "", f"Generated at: `{generated_at}`", ""]
    for rule in sorted(rules, key=lambda item: item.rule_id):
        lines.extend(
            [
                f"## {rule.rule_id}",
                "",
                f"- Issue Types: {', '.join(rule.issue_types)}",
                f"- Description: {rule.description}",
                f"- Promotion Condition: {rule.promotion_condition}",
                f"- Action: {rule.action}",
                f"- Consumed By: {', '.join(rule.consumed_by)}",
                f"- Risk: {rule.risk}",
                "- Evidence:",
                *[f"  - `{path}`" for path in rule.evidence_paths],
                "",
            ]
        )
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def rules_for_issue_type(rules: list[BenchmarkRule], issue_type: str) -> list[BenchmarkRule]:
    """Input: rules and issue type. Output: matching rules. Find active rules for a failure class."""
    normalized = issue_type.lower()
    return [rule for rule in rules if normalized in {item.lower() for item in rule.issue_types}]


def rules_for_consumer(rules: list[BenchmarkRule], consumer: str) -> list[BenchmarkRule]:
    """Input: rules and consumer name. Output: applicable rules. Select active authority for one workflow component."""
    normalized = consumer.lower()
    return [rule for rule in rules if normalized in {item.lower() for item in rule.consumed_by}]
