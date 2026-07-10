# Workflow Launcher Bootstrap Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a reliable startup layer that materializes required knowledge artifacts, checks run readiness, writes launch manifests, and creates bounded subagent handoff packets before research execution.

**Architecture:** Add small modules around the existing BrainWorkflow foundation rather than changing Stage 1 simulation logic. `run_readiness` validates compiled knowledge and run safety, `knowledge_bootstrap` writes formal vault artifacts, `workflow_launcher` writes run manifests, and `subagent_handoff` writes per-lane packets. `wqb.cli` exposes these as explicit commands.

**Tech Stack:** Python standard library, dataclasses, JSON/JSONL, Markdown files, `unittest`, existing `wqb.data_ledger`, `wqb.template_library`, and `wqb.knowledge_freshness`.

## Global Constraints

- Do not build a graphical web application in this slice.
- Do not submit alphas automatically.
- Do not automatically change accepted workflow rules.
- Do not crawl every platform document on every research run.
- Do not fabricate platform data coverage as fact when raw sources are missing.
- Do not require subagents to share the main conversation context.
- Research startup must not trigger full Learn/forum/operator recapture or full wiki compilation.
- Batch size defaults to 30 for discovery-style research generation.
- Sensitive values must remain outside tracked files. API credentials are never written into run manifests.
- Use `unittest` because the existing suite is `python -m unittest discover -s tests -q`.

---

## File Structure

- Create `wqb/run_readiness.py`
  - Owns readiness artifact contracts, parse checks, stale checks, mode-specific blocking, and Markdown/JSON report writing.
- Create `tests/test_run_readiness.py`
  - Covers missing artifacts, maintenance mode, parse failures, batch-size gate, live API gate, submit confirmation gate, and report output.
- Modify `wqb/cli.py`
  - Adds `readiness-check`, `bootstrap-knowledge`, and `launch-workflow` command dispatch.
- Modify `tests/test_cli.py`
  - Covers argument parsing and dispatch for the new commands without live API calls.
- Create `wqb/knowledge_bootstrap.py`
  - Owns root vault materialization for Data Ledger, Template Library, Freshness Manifest, activity snapshot note, and bootstrap report.
- Create `tests/test_knowledge_bootstrap.py`
  - Covers creation of required files and source-quality labels.
- Create `wqb/workflow_launcher.py`
  - Owns layered config loading, conservative defaults, run id creation, run manifest serialization, and launch result structure.
- Create `tests/test_workflow_launcher.py`
  - Covers defaults, local config merge, manifest writing, and live API/submit safety flags.
- Create `wqb/subagent_handoff.py`
  - Owns lane definitions and Markdown/JSON handoff packet rendering.
- Create `tests/test_subagent_handoff.py`
  - Covers required packet fields and lane selection.
- Create `configs/workflow_defaults.example.json`
  - Documents tracked non-secret launcher defaults.

---

### Task 1: Run Readiness Core

**Files:**
- Create: `wqb/run_readiness.py`
- Test: `tests/test_run_readiness.py`

**Interfaces:**
- Consumes: `wqb.knowledge_freshness.load_freshness_manifest(path: Path, strict: bool)`, `wqb.knowledge_freshness.evaluate_freshness(records, today, artifact_root)`
- Produces:
  - `ReadinessIssue`
  - `ReadinessReport`
  - `evaluate_run_readiness(knowledge_root: str | Path, mode: str, batch_size: int = 30, live_api_enabled: bool = False, submit_confirmed: bool = False, today_value: str | None = None) -> ReadinessReport`
  - `readiness_report_to_dict(report: ReadinessReport) -> dict[str, Any]`
  - `write_readiness_reports(output_dir: Path, report: ReadinessReport) -> tuple[Path, Path]`

- [ ] **Step 1: Write failing tests for missing artifact behavior**

Create `tests/test_run_readiness.py`:

```python
import json
import tempfile
import unittest
from pathlib import Path

from wqb.run_readiness import evaluate_run_readiness, write_readiness_reports


class RunReadinessTests(unittest.TestCase):
    def write_manifest(self, root: Path) -> None:
        manifest = root / "wiki" / "80_maintenance" / "freshness_manifest.json"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(
            json.dumps(
                [
                    {"name": "data_ledger", "path": "wiki/20_semantics/data_ledger.jsonl", "updated_at": "2026-07-10", "max_age_days": 1},
                    {"name": "template_library", "path": "wiki/30_templates/template_library.jsonl", "updated_at": "2026-07-10", "max_age_days": 7},
                    {"name": "benchmark_rules", "path": "wiki/50_benchmarks/correlation_and_novelty.md", "updated_at": "2026-07-10", "max_age_days": 7},
                    {"name": "activity_snapshot", "path": "wiki/10_foundations/activity_snapshot.md", "updated_at": "2026-07-10", "max_age_days": 1},
                ]
            ),
            encoding="utf-8",
        )

    def test_research_mode_blocks_missing_compiled_knowledge(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_manifest(root)

            report = evaluate_run_readiness(root, mode="research", today_value="2026-07-10")

        self.assertFalse(report.passed)
        self.assertTrue(report.blocked)
        self.assertIn("missing_artifact", {issue.code for issue in report.issues})

    def test_maintenance_mode_allows_missing_compiled_knowledge(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_manifest(root)

            report = evaluate_run_readiness(root, mode="maintenance", today_value="2026-07-10")

        self.assertTrue(report.passed)
        self.assertFalse(report.blocked)
        self.assertIn("missing_artifact", {issue.code for issue in report.issues})
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
python -m unittest tests.test_run_readiness -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'wqb.run_readiness'`.

- [ ] **Step 3: Implement minimal readiness dataclasses and missing artifact checks**

Create `wqb/run_readiness.py`:

```python
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
import json
from pathlib import Path
from typing import Any

from wqb.knowledge_freshness import evaluate_freshness, load_freshness_manifest


READINESS_MODES = {"maintenance", "plan-only", "research", "submit-candidate"}
STRICT_BLOCKING_MODES = {"research", "submit-candidate"}
FRESHNESS_MANIFEST_PATH = Path("wiki") / "80_maintenance" / "freshness_manifest.json"


@dataclass(frozen=True)
class ReadinessIssue:
    level: str
    code: str
    message: str
    path: str = ""
    action: str = ""


@dataclass(frozen=True)
class ReadinessReport:
    mode: str
    generated_at: str
    passed: bool
    blocked: bool
    issues: list[ReadinessIssue]


def _issue(level: str, code: str, message: str, path: Path | str = "", action: str = "") -> ReadinessIssue:
    """Input: issue fields. Output: ReadinessIssue. Create one actionable readiness issue."""
    return ReadinessIssue(level=level, code=code, message=message, path=str(path), action=action)


def readiness_report_to_dict(report: ReadinessReport) -> dict[str, Any]:
    """Input: ReadinessReport. Output: dict. Convert readiness report to JSON-safe data."""
    row = asdict(report)
    row["issues"] = [asdict(issue) for issue in report.issues]
    return row


def evaluate_run_readiness(
    knowledge_root: str | Path,
    mode: str,
    batch_size: int = 30,
    live_api_enabled: bool = False,
    submit_confirmed: bool = False,
    today_value: str | None = None,
) -> ReadinessReport:
    """Input: root, mode, safety flags. Output: report. Check whether a run may start."""
    if mode not in READINESS_MODES:
        raise ValueError(f"unsupported readiness mode: {mode}")
    root = Path(knowledge_root)
    current = date.fromisoformat(today_value) if today_value else date.today()
    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    issues: list[ReadinessIssue] = []
    manifest = root / FRESHNESS_MANIFEST_PATH
    if not manifest.exists():
        issues.append(_issue("block" if mode in STRICT_BLOCKING_MODES else "warn", "missing_manifest", "Freshness manifest is missing.", manifest, "Run bootstrap-knowledge."))
    else:
        records = load_freshness_manifest(manifest, strict=True)
        for status in evaluate_freshness(records, current, artifact_root=root):
            if not status.artifact_exists:
                issues.append(_issue("block" if mode in STRICT_BLOCKING_MODES else "warn", "missing_artifact", f"Required artifact is missing: {status.name}", status.path, "Run bootstrap-knowledge."))
            elif status.stale:
                issues.append(_issue("block" if mode in STRICT_BLOCKING_MODES else "warn", "stale_artifact", f"Required artifact is stale: {status.name}", status.path, "Run knowledge maintenance."))
    blocked = any(issue.level == "block" for issue in issues)
    return ReadinessReport(mode=mode, generated_at=generated_at, passed=not blocked, blocked=blocked, issues=issues)


def write_readiness_reports(output_dir: Path, report: ReadinessReport) -> tuple[Path, Path]:
    """Input: output dir and report. Output: JSON and Markdown paths. Persist readiness reports."""
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "readiness_report.json"
    md_path = output_dir / "readiness_report.md"
    json_path.write_text(json.dumps(readiness_report_to_dict(report), ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# Run Readiness Report", "", f"Generated at: `{report.generated_at}`", f"Mode: `{report.mode}`", f"Passed: `{report.passed}`", ""]
    lines.extend(["| Level | Code | Message | Path | Action |", "| --- | --- | --- | --- | --- |"])
    for issue in report.issues:
        lines.append(f"| {issue.level} | {issue.code} | {issue.message} | `{issue.path}` | {issue.action} |")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, md_path
```

- [ ] **Step 4: Run tests to verify missing artifact behavior passes**

Run:

```powershell
python -m unittest tests.test_run_readiness -v
```

Expected: PASS for the two tests in `RunReadinessTests`.

- [ ] **Step 5: Add failing tests for parse, batch, live API, submit, and report output**

Append to `tests/test_run_readiness.py` inside `RunReadinessTests`:

```python
    def create_minimal_artifacts(self, root: Path) -> None:
        self.write_manifest(root)
        (root / "wiki" / "20_semantics").mkdir(parents=True, exist_ok=True)
        (root / "wiki" / "30_templates").mkdir(parents=True, exist_ok=True)
        (root / "wiki" / "50_benchmarks").mkdir(parents=True, exist_ok=True)
        (root / "wiki" / "10_foundations").mkdir(parents=True, exist_ok=True)
        (root / "wiki" / "20_semantics" / "data_ledger.jsonl").write_text(json.dumps({"field_id": "f1"}) + "\n", encoding="utf-8")
        (root / "wiki" / "30_templates" / "template_library.jsonl").write_text(json.dumps({"template_id": "t1"}) + "\n", encoding="utf-8")
        (root / "wiki" / "50_benchmarks" / "correlation_and_novelty.md").write_text("# Benchmarks\n", encoding="utf-8")
        (root / "wiki" / "10_foundations" / "activity_snapshot.md").write_text("# Activity Snapshot\n", encoding="utf-8")

    def test_discovery_batch_smaller_than_30_blocks_research(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.create_minimal_artifacts(root)

            report = evaluate_run_readiness(root, mode="research", batch_size=12, today_value="2026-07-10")

        self.assertFalse(report.passed)
        self.assertIn("batch_size_too_small", {issue.code for issue in report.issues})

    def test_live_api_requires_explicit_enablement_for_research(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.create_minimal_artifacts(root)

            report = evaluate_run_readiness(root, mode="research", live_api_enabled=False, today_value="2026-07-10")

        self.assertFalse(report.passed)
        self.assertIn("live_api_disabled", {issue.code for issue in report.issues})

    def test_submit_candidate_requires_user_confirmation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.create_minimal_artifacts(root)

            report = evaluate_run_readiness(root, mode="submit-candidate", live_api_enabled=True, submit_confirmed=False, today_value="2026-07-10")

        self.assertFalse(report.passed)
        self.assertIn("submit_not_confirmed", {issue.code for issue in report.issues})

    def test_invalid_jsonl_blocks_research(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.create_minimal_artifacts(root)
            (root / "wiki" / "20_semantics" / "data_ledger.jsonl").write_text("{invalid\n", encoding="utf-8")

            report = evaluate_run_readiness(root, mode="research", live_api_enabled=True, today_value="2026-07-10")

        self.assertFalse(report.passed)
        self.assertIn("parse_error", {issue.code for issue in report.issues})

    def test_write_readiness_reports_creates_json_and_markdown(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.create_minimal_artifacts(root)
            report = evaluate_run_readiness(root, mode="plan-only", today_value="2026-07-10")
            json_path, md_path = write_readiness_reports(root / "runs" / "run1", report)

            payload = json.loads(json_path.read_text(encoding="utf-8"))
            markdown = md_path.read_text(encoding="utf-8")

        self.assertEqual(payload["mode"], "plan-only")
        self.assertIn("# Run Readiness Report", markdown)
```

- [ ] **Step 6: Run tests to verify new checks fail**

Run:

```powershell
python -m unittest tests.test_run_readiness -v
```

Expected: FAIL with missing issue codes such as `batch_size_too_small`, `live_api_disabled`, `submit_not_confirmed`, or `parse_error`.

- [ ] **Step 7: Implement parse and safety checks**

Modify `wqb/run_readiness.py`:

```python
def _jsonl_row_count(path: Path) -> tuple[int, str]:
    """Input: JSONL path. Output: row count and error. Validate JSONL parseability."""
    count = 0
    try:
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if line.strip():
                json.loads(line)
                count += 1
    except json.JSONDecodeError as error:
        return count, f"{path}:{line_number}: {error.msg}"
    return count, ""


def _check_jsonl_artifact(path: Path, code_name: str, issues: list[ReadinessIssue], mode: str) -> None:
    """Input: path, artifact name, issues, mode. Output: none. Add JSONL parse and empty-file issues."""
    if not path.exists():
        return
    row_count, error = _jsonl_row_count(path)
    if error:
        issues.append(_issue("block" if mode in STRICT_BLOCKING_MODES else "warn", "parse_error", f"Cannot parse {code_name}.", error, "Fix JSONL before running research."))
    elif row_count == 0:
        issues.append(_issue("block" if mode in STRICT_BLOCKING_MODES else "warn", "empty_artifact", f"{code_name} has no records.", path, "Run bootstrap-knowledge or refresh knowledge."))
```

Add these checks before computing `blocked` in `evaluate_run_readiness`:

```python
    _check_jsonl_artifact(root / "wiki" / "20_semantics" / "data_ledger.jsonl", "data_ledger", issues, mode)
    _check_jsonl_artifact(root / "wiki" / "30_templates" / "template_library.jsonl", "template_library", issues, mode)
    if mode == "research" and batch_size < 30:
        issues.append(_issue("block", "batch_size_too_small", "Research discovery batch size must be at least 30.", "", "Set batch_size to 30 or higher."))
    if mode == "research" and not live_api_enabled:
        issues.append(_issue("block", "live_api_disabled", "Research mode requires explicit live API enablement.", "", "Pass live_api_enabled=True or use plan-only mode."))
    if mode == "submit-candidate" and not submit_confirmed:
        issues.append(_issue("block", "submit_not_confirmed", "Submit-candidate mode requires explicit user confirmation.", "", "Collect user confirmation before submit."))
```

- [ ] **Step 8: Run focused and full tests**

Run:

```powershell
python -m unittest tests.test_run_readiness -v
python -m unittest discover -s tests -q
```

Expected: both commands PASS.

- [ ] **Step 9: Commit Task 1**

```powershell
git add BrainWorkflow/wqb/run_readiness.py BrainWorkflow/tests/test_run_readiness.py
git commit -m "add run readiness checks"
```

---

### Task 2: Readiness CLI Command

**Files:**
- Modify: `wqb/cli.py`
- Modify: `tests/test_cli.py`

**Interfaces:**
- Consumes: `evaluate_run_readiness(...) -> ReadinessReport`, `write_readiness_reports(output_dir, report) -> tuple[Path, Path]`
- Produces:
  - `readiness_check(knowledge_root: str | Path, output_dir: str | Path, mode: str, batch_size: int, live_api_enabled: bool, submit_confirmed: bool, today_value: str | None = None) -> dict[str, Any]`
  - CLI command `readiness-check`

- [ ] **Step 1: Write failing CLI tests**

Append to `tests/test_cli.py` inside `CliTests`:

```python
    def test_readiness_check_function_writes_reports(self):
        from wqb.cli import readiness_check
        from wqb.run_readiness import ReadinessReport

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_dir = root / "runs" / "run1"
            fake_report = ReadinessReport(mode="plan-only", generated_at="2026-07-10T00:00:00Z", passed=True, blocked=False, issues=[])
            with patch("wqb.cli.evaluate_run_readiness", return_value=fake_report), patch("wqb.cli.write_readiness_reports", return_value=(output_dir / "readiness_report.json", output_dir / "readiness_report.md")) as writer:
                result = readiness_check(root, output_dir, "plan-only", 30, False, False, today_value="2026-07-10")

        writer.assert_called_once()
        self.assertTrue(result["passed"])
        self.assertEqual(result["mode"], "plan-only")

    def test_parse_args_accepts_readiness_check(self):
        with patch("sys.argv", ["wqb", "readiness-check", "--readiness-mode", "research", "--batch-size", "30", "--enable-live-api"]):
            args = parse_args()

        self.assertEqual(args.command, "readiness-check")
        self.assertEqual(args.readiness_mode, "research")
        self.assertTrue(args.enable_live_api)

    def test_readiness_check_main_dispatches_without_simulation(self):
        output = io.StringIO()
        with patch("sys.argv", ["wqb", "readiness-check"]), patch(
            "wqb.cli.readiness_check",
            return_value={"mode": "plan-only", "passed": True, "blocked": False, "issue_count": 0, "json_path": "readiness_report.json", "markdown_path": "readiness_report.md"},
        ) as readiness, redirect_stdout(output):
            main()

        readiness.assert_called_once()
        self.assertEqual(json.loads(output.getvalue())["json_path"], "readiness_report.json")
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```powershell
python -m unittest tests.test_cli.CliTests.test_readiness_check_function_writes_reports tests.test_cli.CliTests.test_parse_args_accepts_readiness_check tests.test_cli.CliTests.test_readiness_check_main_dispatches_without_simulation -v
```

Expected: FAIL with import or argparse command errors.

- [ ] **Step 3: Add CLI helper and command arguments**

Modify imports in `wqb/cli.py`:

```python
from wqb.run_readiness import evaluate_run_readiness, write_readiness_reports
```

Add helper near `knowledge_health_check`:

```python
def readiness_check(
    knowledge_root: str | Path,
    output_dir: str | Path,
    mode: str,
    batch_size: int,
    live_api_enabled: bool,
    submit_confirmed: bool,
    today_value: str | None = None,
) -> dict[str, Any]:
    """Input: root, output dir, mode, safety flags. Output: summary dict. Run startup readiness checks."""
    report = evaluate_run_readiness(
        knowledge_root,
        mode=mode,
        batch_size=batch_size,
        live_api_enabled=live_api_enabled,
        submit_confirmed=submit_confirmed,
        today_value=today_value,
    )
    json_path, markdown_path = write_readiness_reports(Path(output_dir), report)
    return {
        "mode": report.mode,
        "passed": report.passed,
        "blocked": report.blocked,
        "issue_count": len(report.issues),
        "json_path": str(json_path),
        "markdown_path": str(markdown_path),
    }
```

Add command choice and parser args:

```python
"readiness-check",
```

```python
    parser.add_argument("--knowledge-root", default=str(default_knowledge_root()))
    parser.add_argument("--readiness-output-dir", default="")
    parser.add_argument("--readiness-mode", choices=["maintenance", "plan-only", "research", "submit-candidate"], default="plan-only")
    parser.add_argument("--batch-size", type=int, default=30)
    parser.add_argument("--enable-live-api", action="store_true", default=False)
    parser.add_argument("--confirm-submit", action="store_true", default=False)
```

Add dispatch before `schedule-research`:

```python
    elif args.command == "readiness-check":
        output_dir = args.readiness_output_dir or str(Path(config["run_root"]) / "readiness")
        result = readiness_check(
            args.knowledge_root,
            output_dir,
            args.readiness_mode,
            args.batch_size,
            args.enable_live_api,
            args.confirm_submit,
            today_value=args.today or None,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
```

- [ ] **Step 4: Run CLI tests**

Run:

```powershell
python -m unittest tests.test_cli.CliTests.test_readiness_check_function_writes_reports tests.test_cli.CliTests.test_parse_args_accepts_readiness_check tests.test_cli.CliTests.test_readiness_check_main_dispatches_without_simulation -v
python -m unittest discover -s tests -q
```

Expected: both commands PASS.

- [ ] **Step 5: Commit Task 2**

```powershell
git add BrainWorkflow/wqb/cli.py BrainWorkflow/tests/test_cli.py
git commit -m "add readiness cli command"
```

---

### Task 3: Knowledge Bootstrap Core

**Files:**
- Create: `wqb/knowledge_bootstrap.py`
- Test: `tests/test_knowledge_bootstrap.py`

**Interfaces:**
- Consumes:
  - `wqb.data_ledger.load_data_ledger(path: Path) -> list[DataLedgerRecord]`
  - `wqb.data_ledger.write_data_ledger_markdown(path: Path, records, generated_at) -> Path`
  - `wqb.template_library.load_template_library(path: Path) -> list[TemplateRecord]`
  - `wqb.template_library.write_template_library_markdown(path: Path, templates, generated_at) -> Path`
- Produces:
  - `BootstrapSummary`
  - `bootstrap_knowledge(knowledge_root: str | Path, seed_root: str | Path, generated_at: str | None = None) -> BootstrapSummary`
  - `bootstrap_summary_to_dict(summary: BootstrapSummary) -> dict[str, Any]`

- [ ] **Step 1: Write failing bootstrap tests**

Create `tests/test_knowledge_bootstrap.py`:

```python
import json
import tempfile
import unittest
from pathlib import Path

from wqb.knowledge_bootstrap import bootstrap_knowledge, bootstrap_summary_to_dict


class KnowledgeBootstrapTests(unittest.TestCase):
    def create_seed_files(self, seed_root: Path) -> None:
        seed_root.mkdir(parents=True, exist_ok=True)
        (seed_root / "data_ledger.example.jsonl").write_text(
            json.dumps(
                {
                    "dataset_id": "news12",
                    "dataset_name": "News Events",
                    "field_id": "news12_sentiment_fast_d1",
                    "field_type": "MATRIX",
                    "region": "USA",
                    "delay": 1,
                    "universe": "TOP3000",
                    "semantic_tags": ["event", "sentiment", "power_pool"],
                    "coverage": 0.82,
                    "alpha_count": 12,
                    "user_count": 4,
                    "simulation_usage_count": 1,
                    "submitted_usage_count": 0,
                    "last_used_at": "2026-07-09",
                    "best_result_label": "repairable_signal",
                    "correlation_risk": "medium",
                    "source_paths": ["seed"],
                }
            )
            + "\n",
            encoding="utf-8",
        )
        (seed_root / "template_library.example.jsonl").write_text(
            json.dumps(
                {
                    "template_id": "event_fast_delta_rank",
                    "hypothesis": "Fast event sentiment changes are incorporated gradually.",
                    "skeleton": "rank(ts_delta({field}, 1))",
                    "required_field_types": ["MATRIX"],
                    "compatible_semantic_tags": ["event", "sentiment", "power_pool"],
                    "operator_tags": ["time_series_surprise"],
                    "status": "seed",
                    "correlation_risk": "low",
                    "repair_levers": ["group_neutralize"],
                    "source_paths": ["seed"],
                }
            )
            + "\n",
            encoding="utf-8",
        )

    def test_bootstrap_creates_formal_vault_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "knowledge"
            seed_root = Path(tmp) / "seed"
            self.create_seed_files(seed_root)

            summary = bootstrap_knowledge(root, seed_root, generated_at="2026-07-10T00:00:00Z")

            expected = [
                root / "wiki" / "20_semantics" / "data_ledger.jsonl",
                root / "wiki" / "20_semantics" / "data_ledger.md",
                root / "wiki" / "30_templates" / "template_library.jsonl",
                root / "wiki" / "30_templates" / "template_library.md",
                root / "wiki" / "80_maintenance" / "freshness_manifest.json",
                root / "wiki" / "80_maintenance" / "bootstrap_report.md",
                root / "wiki" / "10_foundations" / "activity_snapshot.md",
            ]

            self.assertTrue(all(path.exists() for path in expected))
            self.assertEqual(summary.data_ledger_count, 1)
            self.assertEqual(summary.template_count, 1)

    def test_bootstrap_marks_seed_rows_as_schema_seed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "knowledge"
            seed_root = Path(tmp) / "seed"
            self.create_seed_files(seed_root)

            summary = bootstrap_knowledge(root, seed_root, generated_at="2026-07-10T00:00:00Z")
            ledger_text = (root / "wiki" / "20_semantics" / "data_ledger.jsonl").read_text(encoding="utf-8")
            template_text = (root / "wiki" / "30_templates" / "template_library.jsonl").read_text(encoding="utf-8")
            manifest = json.loads((root / "wiki" / "80_maintenance" / "freshness_manifest.json").read_text(encoding="utf-8"))
            payload = bootstrap_summary_to_dict(summary)

        self.assertIn('"source_quality": "schema_seed"', ledger_text)
        self.assertIn('"source_quality": "schema_seed"', template_text)
        self.assertIn("freshness_manifest.json", payload["artifact_paths"])
        self.assertIn("data_ledger", {row["name"] for row in manifest})
        self.assertIn("template_library", {row["name"] for row in manifest})
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```powershell
python -m unittest tests.test_knowledge_bootstrap -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'wqb.knowledge_bootstrap'`.

- [ ] **Step 3: Implement bootstrap module**

Create `wqb/knowledge_bootstrap.py`:

```python
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from wqb.data_ledger import load_data_ledger, write_data_ledger_markdown
from wqb.template_library import load_template_library, write_template_library_markdown


DATA_LEDGER_JSONL = Path("wiki") / "20_semantics" / "data_ledger.jsonl"
DATA_LEDGER_MD = Path("wiki") / "20_semantics" / "data_ledger.md"
TEMPLATE_LIBRARY_JSONL = Path("wiki") / "30_templates" / "template_library.jsonl"
TEMPLATE_LIBRARY_MD = Path("wiki") / "30_templates" / "template_library.md"
FRESHNESS_MANIFEST = Path("wiki") / "80_maintenance" / "freshness_manifest.json"
BOOTSTRAP_REPORT = Path("wiki") / "80_maintenance" / "bootstrap_report.md"
ACTIVITY_SNAPSHOT = Path("wiki") / "10_foundations" / "activity_snapshot.md"


@dataclass(frozen=True)
class BootstrapSummary:
    generated_at: str
    knowledge_root: str
    data_ledger_count: int
    template_count: int
    artifact_paths: list[str]
    warnings: list[str]


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Input: JSONL path. Output: dict rows. Load seed records from disk."""
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> Path:
    """Input: path and rows. Output: path. Write deterministic JSONL rows."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    return path


def _stamp_rows(rows: list[dict[str, Any]], source_quality: str, coverage_status: str) -> list[dict[str, Any]]:
    """Input: rows and labels. Output: copied rows with source labels."""
    stamped = []
    for row in rows:
        copied = dict(row)
        copied["source_quality"] = source_quality
        copied["coverage_status"] = coverage_status
        stamped.append(copied)
    return stamped


def _write_activity_snapshot(path: Path, generated_at: str) -> Path:
    """Input: output path and timestamp. Output: path. Write non-live activity snapshot note."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "# Activity Snapshot\n\n"
        f"Generated at: `{generated_at}`\n\n"
        "No live platform activity refresh was executed by bootstrap. "
        "Run the research planner or maintenance refresh before activity-driven scheduling.\n",
        encoding="utf-8",
    )
    return path


def _write_manifest(path: Path, generated_at: str) -> Path:
    """Input: manifest path and timestamp. Output: path. Write required freshness manifest."""
    path.parent.mkdir(parents=True, exist_ok=True)
    day = generated_at[:10]
    rows = [
        {"name": "data_ledger", "path": str(DATA_LEDGER_JSONL).replace("\\", "/"), "updated_at": day, "max_age_days": 1},
        {"name": "template_library", "path": str(TEMPLATE_LIBRARY_JSONL).replace("\\", "/"), "updated_at": day, "max_age_days": 7},
        {"name": "benchmark_rules", "path": "wiki/50_benchmarks/correlation_and_novelty.md", "updated_at": day, "max_age_days": 7},
        {"name": "activity_snapshot", "path": str(ACTIVITY_SNAPSHOT).replace("\\", "/"), "updated_at": day, "max_age_days": 1},
        {"name": "operator_catalog", "path": "wiki/20_semantics/operator_catalog_official.md", "updated_at": day, "max_age_days": 30},
        {"name": "research_option_cards", "path": "wiki/70_decisions/research_option_cards.jsonl", "updated_at": day, "max_age_days": 7},
    ]
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def bootstrap_summary_to_dict(summary: BootstrapSummary) -> dict[str, Any]:
    """Input: BootstrapSummary. Output: dict. Convert bootstrap summary to JSON-safe data."""
    return asdict(summary)


def bootstrap_knowledge(knowledge_root: str | Path, seed_root: str | Path, generated_at: str | None = None) -> BootstrapSummary:
    """Input: knowledge root and seed root. Output: summary. Materialize formal knowledge artifacts."""
    generated = generated_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    root = Path(knowledge_root)
    seed = Path(seed_root)
    ledger_rows = _stamp_rows(_read_jsonl(seed / "data_ledger.example.jsonl"), "schema_seed", "partial")
    template_rows = _stamp_rows(_read_jsonl(seed / "template_library.example.jsonl"), "schema_seed", "partial")
    ledger_jsonl = _write_jsonl(root / DATA_LEDGER_JSONL, ledger_rows)
    template_jsonl = _write_jsonl(root / TEMPLATE_LIBRARY_JSONL, template_rows)
    ledger_md = write_data_ledger_markdown(root / DATA_LEDGER_MD, load_data_ledger(ledger_jsonl), generated)
    template_md = write_template_library_markdown(root / TEMPLATE_LIBRARY_MD, load_template_library(template_jsonl), generated)
    activity = _write_activity_snapshot(root / ACTIVITY_SNAPSHOT, generated)
    manifest = _write_manifest(root / FRESHNESS_MANIFEST, generated)
    report = root / BOOTSTRAP_REPORT
    report.parent.mkdir(parents=True, exist_ok=True)
    warnings = ["Data ledger is schema-seeded and partial until platform metadata refresh runs."]
    artifact_paths = [str(path) for path in [ledger_jsonl, ledger_md, template_jsonl, template_md, manifest, activity, report]]
    report.write_text(
        "# Knowledge Bootstrap Report\n\n"
        f"Generated at: `{generated}`\n\n"
        f"- Data Ledger Records: {len(ledger_rows)}\n"
        f"- Template Records: {len(template_rows)}\n"
        "- Source Quality: `schema_seed`\n"
        "- Coverage Status: `partial`\n",
        encoding="utf-8",
    )
    return BootstrapSummary(generated, str(root), len(ledger_rows), len(template_rows), artifact_paths, warnings)
```

- [ ] **Step 4: Run bootstrap tests**

Run:

```powershell
python -m unittest tests.test_knowledge_bootstrap -v
python -m unittest discover -s tests -q
```

Expected: both commands PASS.

- [ ] **Step 5: Commit Task 3**

```powershell
git add BrainWorkflow/wqb/knowledge_bootstrap.py BrainWorkflow/tests/test_knowledge_bootstrap.py
git commit -m "add knowledge bootstrap materialization"
```

---

### Task 4: Bootstrap CLI Command

**Files:**
- Modify: `wqb/cli.py`
- Modify: `tests/test_cli.py`

**Interfaces:**
- Consumes: `bootstrap_knowledge(knowledge_root, seed_root, generated_at=None) -> BootstrapSummary`
- Produces:
  - `bootstrap_knowledge_command(knowledge_root: str | Path, seed_root: str | Path) -> dict[str, Any]`
  - CLI command `bootstrap-knowledge`

- [ ] **Step 1: Write failing CLI tests**

Append to `tests/test_cli.py` inside `CliTests`:

```python
    def test_bootstrap_knowledge_command_returns_summary(self):
        from wqb.cli import bootstrap_knowledge_command
        from wqb.knowledge_bootstrap import BootstrapSummary

        fake_summary = BootstrapSummary(
            generated_at="2026-07-10T00:00:00Z",
            knowledge_root="knowledge",
            data_ledger_count=1,
            template_count=1,
            artifact_paths=["knowledge/wiki/20_semantics/data_ledger.jsonl"],
            warnings=[],
        )
        with patch("wqb.cli.bootstrap_knowledge", return_value=fake_summary):
            result = bootstrap_knowledge_command("knowledge", "docs/knowledge")

        self.assertEqual(result["data_ledger_count"], 1)
        self.assertEqual(result["template_count"], 1)

    def test_bootstrap_knowledge_main_dispatches_without_simulation(self):
        output = io.StringIO()
        with patch("sys.argv", ["wqb", "bootstrap-knowledge"]), patch(
            "wqb.cli.bootstrap_knowledge_command",
            return_value={"generated_at": "2026-07-10T00:00:00Z", "knowledge_root": "knowledge", "data_ledger_count": 1, "template_count": 1, "artifact_paths": [], "warnings": []},
        ) as bootstrap, redirect_stdout(output):
            main()

        bootstrap.assert_called_once()
        self.assertEqual(json.loads(output.getvalue())["data_ledger_count"], 1)
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```powershell
python -m unittest tests.test_cli.CliTests.test_bootstrap_knowledge_command_returns_summary tests.test_cli.CliTests.test_bootstrap_knowledge_main_dispatches_without_simulation -v
```

Expected: FAIL with missing import or argparse command errors.

- [ ] **Step 3: Add bootstrap command to CLI**

Modify imports in `wqb/cli.py`:

```python
from wqb.knowledge_bootstrap import bootstrap_knowledge, bootstrap_summary_to_dict
```

Add helper:

```python
def bootstrap_knowledge_command(knowledge_root: str | Path, seed_root: str | Path) -> dict[str, Any]:
    """Input: knowledge root and seed root. Output: summary dict. Materialize formal knowledge artifacts."""
    summary = bootstrap_knowledge(knowledge_root, seed_root)
    return bootstrap_summary_to_dict(summary)
```

Add command choice and parser arg:

```python
"bootstrap-knowledge",
```

```python
    parser.add_argument("--knowledge-seed-root", default="docs/knowledge")
```

Add dispatch:

```python
    elif args.command == "bootstrap-knowledge":
        result = bootstrap_knowledge_command(args.knowledge_root, args.knowledge_seed_root)
        print(json.dumps(result, ensure_ascii=False, indent=2))
```

- [ ] **Step 4: Run CLI and full tests**

Run:

```powershell
python -m unittest tests.test_cli.CliTests.test_bootstrap_knowledge_command_returns_summary tests.test_cli.CliTests.test_bootstrap_knowledge_main_dispatches_without_simulation -v
python -m unittest discover -s tests -q
```

Expected: both commands PASS.

- [ ] **Step 5: Commit Task 4**

```powershell
git add BrainWorkflow/wqb/cli.py BrainWorkflow/tests/test_cli.py
git commit -m "add knowledge bootstrap cli"
```

---

### Task 5: Workflow Launcher Manifest And Config

**Files:**
- Create: `wqb/workflow_launcher.py`
- Create: `tests/test_workflow_launcher.py`
- Create: `configs/workflow_defaults.example.json`

**Interfaces:**
- Consumes: existing config paths and knowledge root path.
- Produces:
  - `WorkflowLaunchConfig`
  - `WorkflowRunManifest`
  - `load_workflow_launch_config(defaults_path: Path, local_path: Path | None = None, overrides: dict[str, Any] | None = None) -> WorkflowLaunchConfig`
  - `create_run_manifest(config: WorkflowLaunchConfig, generated_at: str | None = None) -> WorkflowRunManifest`
  - `write_run_manifest(path: Path, manifest: WorkflowRunManifest) -> Path`
  - `workflow_run_manifest_to_dict(manifest: WorkflowRunManifest) -> dict[str, Any]`

- [ ] **Step 1: Write failing launcher tests**

Create `tests/test_workflow_launcher.py`:

```python
import json
import tempfile
import unittest
from pathlib import Path

from wqb.workflow_launcher import (
    create_run_manifest,
    load_workflow_launch_config,
    workflow_run_manifest_to_dict,
    write_run_manifest,
)


class WorkflowLauncherTests(unittest.TestCase):
    def test_load_workflow_launch_config_merges_defaults_local_and_overrides(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            defaults = root / "defaults.json"
            local = root / "local.json"
            defaults.write_text(json.dumps({"knowledge_root": "knowledge", "region": "USA", "delay": 1, "batch_size": 30, "mode": "plan-only"}), encoding="utf-8")
            local.write_text(json.dumps({"region": "EUR", "universe": "TOP2500"}), encoding="utf-8")

            config = load_workflow_launch_config(defaults, local, overrides={"delay": 0, "objective": "Power Pool"})

        self.assertEqual(config.region, "EUR")
        self.assertEqual(config.delay, 0)
        self.assertEqual(config.batch_size, 30)
        self.assertEqual(config.objective, "Power Pool")
        self.assertFalse(config.live_api_enabled)
        self.assertEqual(config.submit_policy, "blocked")

    def test_create_run_manifest_uses_conservative_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            defaults = root / "defaults.json"
            defaults.write_text(json.dumps({"knowledge_root": "knowledge", "run_root": str(root / "runs"), "objective": "Power Pool", "region": "USA", "delay": 1}), encoding="utf-8")
            config = load_workflow_launch_config(defaults)

            manifest = create_run_manifest(config, generated_at="2026-07-10T00:00:00Z")
            payload = workflow_run_manifest_to_dict(manifest)

        self.assertEqual(payload["batch_size"], 30)
        self.assertEqual(payload["mode"], "plan-only")
        self.assertEqual(payload["submit_policy"], "blocked")
        self.assertFalse(payload["live_api_enabled"])
        self.assertIn("data_ledger", payload["knowledge_artifacts"])

    def test_write_run_manifest_creates_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            defaults = root / "defaults.json"
            defaults.write_text(json.dumps({"knowledge_root": "knowledge", "run_root": str(root / "runs"), "objective": "Power Pool", "region": "USA", "delay": 1}), encoding="utf-8")
            config = load_workflow_launch_config(defaults)
            manifest = create_run_manifest(config, generated_at="2026-07-10T00:00:00Z")

            path = write_run_manifest(Path(manifest.run_dir) / "run_manifest.json", manifest)
            payload = json.loads(path.read_text(encoding="utf-8"))

            self.assertEqual(payload["objective"], "Power Pool")
            self.assertTrue(path.exists())
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```powershell
python -m unittest tests.test_workflow_launcher -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'wqb.workflow_launcher'`.

- [ ] **Step 3: Implement launcher config and manifest module**

Create `wqb/workflow_launcher.py`:

```python
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
    return WorkflowLaunchConfig(**{key: value for key, value in data.items() if key in WorkflowLaunchConfig.__dataclass_fields__})


def _slug(value: str) -> str:
    """Input: string. Output: slug. Build stable run id fragments."""
    cleaned = "".join(char.lower() if char.isalnum() else "-" for char in value).strip("-")
    return "-".join(part for part in cleaned.split("-") if part) or "workflow"


def create_run_manifest(config: WorkflowLaunchConfig, generated_at: str | None = None) -> WorkflowRunManifest:
    """Input: launch config and timestamp. Output: run manifest. Create one auditable run manifest."""
    generated = generated_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    run_id = f"{generated[:10].replace('-', '')}-{_slug(config.objective)}"
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
```

- [ ] **Step 4: Add tracked example config**

Create `configs/workflow_defaults.example.json`:

```json
{
  "knowledge_root": "C:/Users/oytl/Desktop/pyproject/brain/knowledge",
  "run_root": "runs",
  "objective": "current-incentives",
  "region": "USA",
  "universe": "TOP3000",
  "delay": 1,
  "instrument_type": "EQUITY",
  "mode": "plan-only",
  "batch_size": 30,
  "max_simulation_budget": 30,
  "live_api_enabled": false,
  "submit_policy": "blocked",
  "lanes": [
    "knowledge-readiness",
    "data-scheduling",
    "template-selection"
  ]
}
```

- [ ] **Step 5: Run launcher tests**

Run:

```powershell
python -m unittest tests.test_workflow_launcher -v
python -m unittest discover -s tests -q
```

Expected: both commands PASS.

- [ ] **Step 6: Commit Task 5**

```powershell
git add BrainWorkflow/wqb/workflow_launcher.py BrainWorkflow/tests/test_workflow_launcher.py BrainWorkflow/configs/workflow_defaults.example.json
git commit -m "add workflow launcher manifest"
```

---

### Task 6: Subagent Handoff Packets

**Files:**
- Create: `wqb/subagent_handoff.py`
- Create: `tests/test_subagent_handoff.py`

**Interfaces:**
- Consumes: `WorkflowRunManifest`
- Produces:
  - `HandoffPacket`
  - `build_handoff_packets(manifest: WorkflowRunManifest, lanes: list[str] | None = None) -> list[HandoffPacket]`
  - `write_handoff_packets(output_dir: Path, packets: list[HandoffPacket]) -> list[dict[str, str]]`

- [ ] **Step 1: Write failing handoff tests**

Create `tests/test_subagent_handoff.py`:

```python
import json
import tempfile
import unittest
from pathlib import Path

from wqb.subagent_handoff import build_handoff_packets, write_handoff_packets
from wqb.workflow_launcher import WorkflowRunManifest


class SubagentHandoffTests(unittest.TestCase):
    def manifest(self) -> WorkflowRunManifest:
        return WorkflowRunManifest(
            run_id="20260710-power-pool",
            generated_at="2026-07-10T00:00:00Z",
            run_dir="runs/20260710-power-pool",
            objective="Power Pool",
            region="USA",
            universe="TOP3000",
            delay=1,
            instrument_type="EQUITY",
            mode="plan-only",
            batch_size=30,
            max_simulation_budget=30,
            live_api_enabled=False,
            submit_policy="blocked",
            knowledge_root="knowledge",
            knowledge_artifacts={"data_ledger": "wiki/20_semantics/data_ledger.jsonl"},
            readiness_report_path="runs/20260710-power-pool/readiness_report.md",
            handoff_dir="runs/20260710-power-pool/handoffs",
            lanes=["knowledge-readiness", "data-scheduling"],
        )

    def test_build_handoff_packets_contains_required_fields(self):
        packets = build_handoff_packets(self.manifest())

        self.assertEqual([packet.lane for packet in packets], ["knowledge-readiness", "data-scheduling"])
        self.assertTrue(all(packet.allowed_files for packet in packets))
        self.assertTrue(all(packet.expected_output for packet in packets))
        self.assertTrue(all(packet.verification_command for packet in packets))
        self.assertIn("Do not submit alphas", packets[0].forbidden_actions)

    def test_write_handoff_packets_creates_markdown_and_json(self):
        packets = build_handoff_packets(self.manifest())
        with tempfile.TemporaryDirectory() as tmp:
            outputs = write_handoff_packets(Path(tmp), packets)
            first_json = Path(outputs[0]["json_path"])
            first_md = Path(outputs[0]["markdown_path"])
            payload = json.loads(first_json.read_text(encoding="utf-8"))
            markdown = first_md.read_text(encoding="utf-8")

        self.assertEqual(payload["lane"], "knowledge-readiness")
        self.assertIn("# Subagent Handoff", markdown)
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```powershell
python -m unittest tests.test_subagent_handoff -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'wqb.subagent_handoff'`.

- [ ] **Step 3: Implement handoff module**

Create `wqb/subagent_handoff.py`:

```python
from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any

from wqb.workflow_launcher import WorkflowRunManifest


LANE_TEMPLATES = {
    "knowledge-readiness": {
        "task_title": "Inspect knowledge readiness",
        "expected_output": "readiness_notes.md",
        "verification_command": "python -m unittest tests.test_run_readiness -v",
    },
    "data-scheduling": {
        "task_title": "Rank data candidates",
        "expected_output": "data_schedule_notes.md",
        "verification_command": "python -m unittest tests.test_data_ledger tests.test_research_scheduler -v",
    },
    "template-selection": {
        "task_title": "Rank compatible templates",
        "expected_output": "template_selection_notes.md",
        "verification_command": "python -m unittest tests.test_template_library tests.test_research_scheduler -v",
    },
    "batch-construction": {
        "task_title": "Construct 30-alpha candidate batch",
        "expected_output": "candidate_batch.jsonl",
        "verification_command": "python -m unittest tests.test_generator tests.test_research_workflow -v",
    },
    "simulation-monitor": {
        "task_title": "Monitor simulations",
        "expected_output": "simulation_monitor_summary.md",
        "verification_command": "python -m unittest tests.test_simulator tests.test_cli -v",
    },
    "triage": {
        "task_title": "Triage results",
        "expected_output": "triage_summary.md",
        "verification_command": "python -m unittest tests.test_benchmark tests.test_checker -v",
    },
    "workflow-proposal": {
        "task_title": "Draft workflow rule proposals",
        "expected_output": "workflow_proposals.md",
        "verification_command": "python -m unittest tests.test_workflow_proposals -v",
    },
}


@dataclass(frozen=True)
class HandoffPacket:
    lane: str
    task_title: str
    objective: str
    allowed_files: list[str]
    forbidden_actions: list[str]
    input_artifacts: list[str]
    expected_output: str
    stop_condition: str
    verification_command: str
    summary_schema: dict[str, str]


def _packet_to_dict(packet: HandoffPacket) -> dict[str, Any]:
    """Input: packet. Output: dict. Convert handoff packet to JSON-safe data."""
    return asdict(packet)


def build_handoff_packets(manifest: WorkflowRunManifest, lanes: list[str] | None = None) -> list[HandoffPacket]:
    """Input: manifest and lanes. Output: handoff packets. Build bounded subagent assignments."""
    selected = lanes or manifest.lanes
    packets: list[HandoffPacket] = []
    for lane in selected:
        if lane not in LANE_TEMPLATES:
            raise ValueError(f"unsupported handoff lane: {lane}")
        template = LANE_TEMPLATES[lane]
        packets.append(
            HandoffPacket(
                lane=lane,
                task_title=template["task_title"],
                objective=manifest.objective,
                allowed_files=[manifest.knowledge_root, manifest.run_dir, "BrainWorkflow/wqb", "BrainWorkflow/tests"],
                forbidden_actions=["Do not submit alphas", "Do not change API credentials", "Do not edit unrelated workflow rules"],
                input_artifacts=[manifest.readiness_report_path, *manifest.knowledge_artifacts.values()],
                expected_output=str(Path(manifest.handoff_dir) / lane / template["expected_output"]),
                stop_condition="Stop after writing the expected output and verification summary.",
                verification_command=template["verification_command"],
                summary_schema={"status": "pass|fail|blocked", "output_path": "string", "notes": "string"},
            )
        )
    return packets


def _packet_markdown(packet: HandoffPacket) -> str:
    """Input: packet. Output: Markdown. Render a subagent handoff packet."""
    lines = [
        "# Subagent Handoff",
        "",
        f"- Lane: `{packet.lane}`",
        f"- Task: {packet.task_title}",
        f"- Objective: {packet.objective}",
        f"- Expected Output: `{packet.expected_output}`",
        f"- Stop Condition: {packet.stop_condition}",
        f"- Verification Command: `{packet.verification_command}`",
        "",
        "## Allowed Files",
    ]
    lines.extend(f"- `{item}`" for item in packet.allowed_files)
    lines.extend(["", "## Forbidden Actions"])
    lines.extend(f"- {item}" for item in packet.forbidden_actions)
    lines.extend(["", "## Input Artifacts"])
    lines.extend(f"- `{item}`" for item in packet.input_artifacts)
    return "\n".join(lines) + "\n"


def write_handoff_packets(output_dir: Path, packets: list[HandoffPacket]) -> list[dict[str, str]]:
    """Input: output dir and packets. Output: path rows. Persist Markdown and JSON handoff files."""
    outputs: list[dict[str, str]] = []
    for packet in packets:
        lane_dir = output_dir / packet.lane
        lane_dir.mkdir(parents=True, exist_ok=True)
        json_path = lane_dir / "handoff.json"
        markdown_path = lane_dir / "handoff.md"
        json_path.write_text(json.dumps(_packet_to_dict(packet), ensure_ascii=False, indent=2), encoding="utf-8")
        markdown_path.write_text(_packet_markdown(packet), encoding="utf-8")
        outputs.append({"lane": packet.lane, "json_path": str(json_path), "markdown_path": str(markdown_path)})
    return outputs
```

- [ ] **Step 4: Run handoff tests**

Run:

```powershell
python -m unittest tests.test_subagent_handoff -v
python -m unittest discover -s tests -q
```

Expected: both commands PASS.

- [ ] **Step 5: Commit Task 6**

```powershell
git add BrainWorkflow/wqb/subagent_handoff.py BrainWorkflow/tests/test_subagent_handoff.py
git commit -m "add subagent handoff packets"
```

---

### Task 7: Launch Workflow CLI

**Files:**
- Modify: `wqb/cli.py`
- Modify: `tests/test_cli.py`

**Interfaces:**
- Consumes:
  - `load_workflow_launch_config(...) -> WorkflowLaunchConfig`
  - `create_run_manifest(...) -> WorkflowRunManifest`
  - `write_run_manifest(...) -> Path`
  - `evaluate_run_readiness(...) -> ReadinessReport`
  - `write_readiness_reports(...) -> tuple[Path, Path]`
  - `build_handoff_packets(...) -> list[HandoffPacket]`
  - `write_handoff_packets(...) -> list[dict[str, str]]`
- Produces:
  - `launch_workflow(defaults_path: str | Path, local_path: str | Path | None, overrides: dict[str, Any], write_handoffs: bool = True, today_value: str | None = None) -> dict[str, Any]`
  - CLI command `launch-workflow`

- [ ] **Step 1: Write failing CLI tests**

Append to `tests/test_cli.py` inside `CliTests`:

```python
    def test_launch_workflow_writes_manifest_readiness_and_handoffs(self):
        from wqb.cli import launch_workflow

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            defaults = root / "workflow_defaults.json"
            defaults.write_text(
                json.dumps(
                    {
                        "knowledge_root": str(root / "knowledge"),
                        "run_root": str(root / "runs"),
                        "objective": "Power Pool",
                        "region": "USA",
                        "delay": 1,
                        "mode": "plan-only",
                    }
                ),
                encoding="utf-8",
            )

            result = launch_workflow(defaults, None, overrides={}, write_handoffs=True, today_value="2026-07-10")

            self.assertTrue(Path(result["manifest_path"]).exists())
            self.assertTrue(Path(result["readiness_json_path"]).exists())
            self.assertGreaterEqual(len(result["handoffs"]), 1)
            self.assertEqual(result["mode"], "plan-only")

    def test_launch_workflow_main_dispatches_without_simulation(self):
        output = io.StringIO()
        with patch("sys.argv", ["wqb", "launch-workflow"]), patch(
            "wqb.cli.launch_workflow",
            return_value={"run_id": "run1", "mode": "plan-only", "manifest_path": "run_manifest.json", "readiness_json_path": "readiness_report.json", "readiness_markdown_path": "readiness_report.md", "handoffs": []},
        ) as launcher, redirect_stdout(output):
            main()

        launcher.assert_called_once()
        self.assertEqual(json.loads(output.getvalue())["run_id"], "run1")
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```powershell
python -m unittest tests.test_cli.CliTests.test_launch_workflow_writes_manifest_readiness_and_handoffs tests.test_cli.CliTests.test_launch_workflow_main_dispatches_without_simulation -v
```

Expected: FAIL with missing `launch_workflow` or missing command.

- [ ] **Step 3: Add launch helper imports and function**

Modify imports in `wqb/cli.py`:

```python
from wqb.subagent_handoff import build_handoff_packets, write_handoff_packets
from wqb.workflow_launcher import create_run_manifest, load_workflow_launch_config, write_run_manifest
```

Add helper:

```python
def launch_workflow(
    defaults_path: str | Path,
    local_path: str | Path | None,
    overrides: dict[str, Any],
    write_handoffs: bool = True,
    today_value: str | None = None,
) -> dict[str, Any]:
    """Input: config paths and overrides. Output: launch summary. Write manifest, readiness reports, and handoffs."""
    local = Path(local_path) if local_path else None
    config = load_workflow_launch_config(Path(defaults_path), local, overrides=overrides)
    manifest = create_run_manifest(config)
    manifest_path = write_run_manifest(Path(manifest.run_dir) / "run_manifest.json", manifest)
    readiness_report = evaluate_run_readiness(
        manifest.knowledge_root,
        mode=manifest.mode,
        batch_size=manifest.batch_size,
        live_api_enabled=manifest.live_api_enabled,
        submit_confirmed=manifest.submit_policy == "ask",
        today_value=today_value,
    )
    readiness_json, readiness_md = write_readiness_reports(Path(manifest.run_dir), readiness_report)
    handoff_outputs = []
    if write_handoffs:
        handoff_outputs = write_handoff_packets(Path(manifest.handoff_dir), build_handoff_packets(manifest))
    return {
        "run_id": manifest.run_id,
        "mode": manifest.mode,
        "manifest_path": str(manifest_path),
        "readiness_json_path": str(readiness_json),
        "readiness_markdown_path": str(readiness_md),
        "readiness_passed": readiness_report.passed,
        "handoffs": handoff_outputs,
    }
```

- [ ] **Step 4: Add parser args and dispatch**

Add command choice:

```python
"launch-workflow",
```

Add parser args:

```python
    parser.add_argument("--workflow-defaults", default="configs/workflow_defaults.example.json")
    parser.add_argument("--workflow-local", default="")
    parser.add_argument("--workflow-objective", default="")
    parser.add_argument("--workflow-mode", choices=["maintenance", "plan-only", "research", "submit-candidate"], default="")
    parser.add_argument("--workflow-region", default="")
    parser.add_argument("--workflow-universe", default="")
    parser.add_argument("--workflow-delay", type=int, default=None)
    parser.add_argument("--skip-handoffs", action="store_true", default=False)
```

Add dispatch:

```python
    elif args.command == "launch-workflow":
        launch_overrides = {
            "knowledge_root": args.knowledge_root,
            "objective": args.workflow_objective or None,
            "mode": args.workflow_mode or None,
            "region": args.workflow_region or None,
            "universe": args.workflow_universe or None,
            "delay": args.workflow_delay,
            "batch_size": args.batch_size,
            "live_api_enabled": args.enable_live_api,
            "submit_policy": "ask" if args.confirm_submit else None,
        }
        result = launch_workflow(
            args.workflow_defaults,
            args.workflow_local or None,
            overrides=launch_overrides,
            write_handoffs=not args.skip_handoffs,
            today_value=args.today or None,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
```

- [ ] **Step 5: Run CLI and full tests**

Run:

```powershell
python -m unittest tests.test_cli.CliTests.test_launch_workflow_writes_manifest_readiness_and_handoffs tests.test_cli.CliTests.test_launch_workflow_main_dispatches_without_simulation -v
python -m unittest discover -s tests -q
```

Expected: both commands PASS.

- [ ] **Step 6: Commit Task 7**

```powershell
git add BrainWorkflow/wqb/cli.py BrainWorkflow/tests/test_cli.py
git commit -m "add workflow launch command"
```

---

### Task 8: Documentation And Final Verification

**Files:**
- Modify: `README.md`
- Modify: `docs/superpowers/plans/2026-07-10-workflow-launcher-bootstrap-readiness-implementation.md`

**Interfaces:**
- Consumes all commands added in Tasks 1-7.
- Produces documented command examples and verified implementation.

- [ ] **Step 1: Add README command section**

Modify `README.md` under `## Long-Term Workflow Foundation`:

```markdown
### Startup Layer

The startup layer separates maintenance from research execution:

- `bootstrap-knowledge` materializes Data Ledger, Template Library, Freshness Manifest, and bootstrap reports into the shared Obsidian vault.
- `readiness-check` validates required artifacts, parseability, freshness, batch size, live API permission, and submit confirmation.
- `launch-workflow` writes a run manifest, readiness report, and subagent handoff packets before research execution.

Example:

```powershell
python -m wqb.cli bootstrap-knowledge --knowledge-root C:\Users\oytl\Desktop\pyproject\brain\knowledge
python -m wqb.cli readiness-check --knowledge-root C:\Users\oytl\Desktop\pyproject\brain\knowledge --readiness-mode plan-only
python -m wqb.cli launch-workflow --workflow-objective current-incentives --workflow-mode plan-only
```
```

- [ ] **Step 2: Run focused verification commands**

Run:

```powershell
python -m unittest tests.test_run_readiness tests.test_knowledge_bootstrap tests.test_workflow_launcher tests.test_subagent_handoff -v
python -m unittest tests.test_cli -v
python -m py_compile wqb\run_readiness.py wqb\knowledge_bootstrap.py wqb\workflow_launcher.py wqb\subagent_handoff.py wqb\cli.py
```

Expected: all commands PASS.

- [ ] **Step 3: Run full verification commands**

Run:

```powershell
python -m unittest discover -s tests -q
git diff --check main...HEAD
```

Expected:

- unittest reports `OK`;
- `git diff --check main...HEAD` exits 0 with no output.

- [ ] **Step 4: Smoke the non-live commands in a temporary workspace**

Run:

```powershell
$tmp = Join-Path $env:TEMP ("brain_startup_" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force -Path $tmp | Out-Null
python -m wqb.cli bootstrap-knowledge --knowledge-root "$tmp\knowledge" --knowledge-seed-root docs\knowledge
python -m wqb.cli readiness-check --knowledge-root "$tmp\knowledge" --readiness-mode plan-only --readiness-output-dir "$tmp\run"
python -m wqb.cli launch-workflow --knowledge-root "$tmp\knowledge" --workflow-mode plan-only --workflow-defaults configs\workflow_defaults.example.json
```

Expected:

- `bootstrap-knowledge` prints JSON containing `"data_ledger_count"`;
- `readiness-check` prints JSON containing `"mode": "plan-only"`;
- `launch-workflow` prints JSON containing `"manifest_path"`;
- no live platform API calls are made.

- [ ] **Step 5: Update this plan status after implementation**

Add a short completion note at the bottom of this plan:

```markdown
## Implementation Result

- Verification command: `python -m unittest discover -s tests -q`
- Verification command: `python -m py_compile wqb\run_readiness.py wqb\knowledge_bootstrap.py wqb\workflow_launcher.py wqb\subagent_handoff.py wqb\cli.py`
- Verification command: `git diff --check main...HEAD`
- Non-live smoke commands completed without platform API calls.
```

- [ ] **Step 6: Commit Task 8**

```powershell
git add BrainWorkflow/README.md BrainWorkflow/docs/superpowers/plans/2026-07-10-workflow-launcher-bootstrap-readiness-implementation.md
git commit -m "document startup workflow commands"
```

- [ ] **Step 7: Push branch**

```powershell
git push origin agent/brainworkflow-phase2
```

Expected: remote branch updates successfully.

---

## Self-Review Checklist

- Spec coverage:
  - Workflow Launcher is covered by Tasks 5 and 7.
  - Knowledge Bootstrap/Materialize is covered by Tasks 3 and 4.
  - Run Readiness Gate is covered by Tasks 1 and 2.
  - Subagent Handoff Packets are covered by Task 6.
  - Configuration Model is covered by Task 5.
  - Error handling is covered by Tasks 1, 3, and 7.
  - Testing strategy is covered by Tasks 1-8.
- Type consistency:
  - `ReadinessReport` is produced by `evaluate_run_readiness` and consumed by CLI launch/readiness helpers.
  - `BootstrapSummary` is produced by `bootstrap_knowledge` and converted by `bootstrap_summary_to_dict`.
  - `WorkflowRunManifest` is produced by `create_run_manifest` and consumed by `build_handoff_packets`.
  - CLI commands use the same mode names as the spec: `maintenance`, `plan-only`, `research`, `submit-candidate`.
- Execution order:
  - Implement readiness before launcher because launcher depends on readiness reports.
  - Implement bootstrap before launch smoke tests because root knowledge artifacts are required inputs.
  - Implement handoff packets before launch command so launch output can include bounded subagent assignments.
