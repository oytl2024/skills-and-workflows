# Workflow Console Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local browser Workflow Console that operates the existing BrainWorkflow CLI, displays durable workflow state, records workflow-change proposals, and writes context recovery artifacts.

**Architecture:** Use a small standard-library Python web server that wraps existing `wqb` modules and CLI commands. Keep alpha research logic in the existing modules; add focused console modules for state aggregation, job execution, proposal input, context updates, and HTML routes.

**Tech Stack:** Python standard library (`http.server`, `subprocess`, `json`, `html`, `urllib.parse`, `webbrowser`), existing `unittest` test suite, existing BrainWorkflow CLI and knowledge artifacts.

## Global Constraints

- Do not implement a cloud service or remote multi-user system.
- Do not store credentials in files.
- Do not auto-submit alphas.
- Do not bypass existing readiness gates.
- Do not rewrite the Scout, Seed, Discovery, Repair, or Submit workflow.
- Do not run broad Learn/forum recapture as a hidden side effect of opening the UI.
- Do not require a heavy JavaScript application for the first version.
- Use `unittest`, matching the existing project.
- `plan-only` is always available.
- `research` requires an explicit `enable_live_api` checkbox.
- `submit-candidate` requires both `enable_live_api` and a separate `confirm_submit` control.
- Every UI-triggered action writes durable job and context artifacts.
- Console Task 2 and later must use Orchestrator-owned state and `workflow-*` commands when controlling official research runs.

---

## File Structure

- Create `BrainWorkflow/wqb/console_state.py`: resolve project paths and aggregate read-only dashboard state from knowledge, runs, proposals, and milestone files.
- Create `BrainWorkflow/tests/test_console_state.py`: unit tests for state aggregation from fixture folders.
- Create `BrainWorkflow/wqb/console_jobs.py`: job dataclass, command builder, synchronous subprocess runner, and job history loader.
- Create `BrainWorkflow/tests/test_console_jobs.py`: unit tests for job record lifecycle and success/failure command execution.
- Modify `BrainWorkflow/wqb/workflow_proposals.py`: expose proposal row loading, row writing, and decision updates.
- Create `BrainWorkflow/wqb/console_proposals.py`: convert UI form data into `WorkflowChangeProposal` records and proposal decisions.
- Create `BrainWorkflow/tests/test_console_proposals.py`: unit tests for proposal creation and decision updates.
- Create `BrainWorkflow/wqb/console_context.py`: append concise job context to `milestone.md`, `todo.md`, and job summaries.
- Create `BrainWorkflow/tests/test_console_context.py`: unit tests for context guard writes.
- Create `BrainWorkflow/wqb/console_server.py`: standard-library local HTTP server, HTML renderers, routes, action handlers, and safety gates.
- Create `BrainWorkflow/tests/test_console_server.py`: unit tests for HTML rendering, action command construction, safety refusal, and server construction.
- Modify `BrainWorkflow/wqb/cli.py`: add `launch-console` command and console arguments.
- Modify `BrainWorkflow/tests/test_cli.py`: test `launch-console` argument parsing and dispatch.
- Modify `BrainWorkflow/README.md`: add console startup and safety instructions.

---

### Task 1: Console State Aggregation

**Files:**
- Create: `BrainWorkflow/wqb/console_state.py`
- Test: `BrainWorkflow/tests/test_console_state.py`

**Interfaces:**
- Produces: `ConsolePaths` dataclass.
- Produces: `default_console_paths(knowledge_root: str | Path | None = None, runs_root: str | Path | None = None) -> ConsolePaths`
- Produces: `load_console_state(paths: ConsolePaths) -> dict[str, Any]`
- Consumes: `wqb.knowledge_freshness.load_freshness_manifest`, `wqb.knowledge_freshness.evaluate_freshness`

- [ ] **Step 1: Write failing state aggregation tests**

Create `BrainWorkflow/tests/test_console_state.py`:

```python
import json
import tempfile
import unittest
from pathlib import Path

from wqb.console_state import ConsolePaths, load_console_state


class ConsoleStateTests(unittest.TestCase):
    def test_load_console_state_aggregates_readiness_options_schedule_jobs_and_proposals(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            knowledge = root / "knowledge"
            runs = root / "runs"
            decisions = knowledge / "wiki" / "70_decisions"
            maintenance = knowledge / "wiki" / "80_maintenance"
            decisions.mkdir(parents=True)
            maintenance.mkdir(parents=True)
            readiness_dir = runs / "readiness_latest"
            readiness_dir.mkdir(parents=True)
            job_dir = runs / "console_jobs" / "job-1"
            job_dir.mkdir(parents=True)

            (readiness_dir / "readiness_report.json").write_text(
                json.dumps({"mode": "plan-only", "passed": True, "blocked": False, "issues": []}),
                encoding="utf-8",
            )
            (maintenance / "freshness_manifest.json").write_text(
                json.dumps([{"name": "data_ledger", "path": "wiki/20_semantics/data_ledger.jsonl", "updated_at": "2026-07-12", "max_age_days": 7}]),
                encoding="utf-8",
            )
            (decisions / "research_option_cards.jsonl").write_text(
                json.dumps({"title": "Explore current Power Pool boards", "score": {"total": 10.5}}) + "\n",
                encoding="utf-8",
            )
            (decisions / "research_schedule.md").write_text("# Research Schedule\n\n- Option: Power Pool\n", encoding="utf-8")
            (decisions / "workflow_change_proposals.jsonl").write_text(
                json.dumps({"proposal_id": "p1", "status": "proposed", "title": "Down-rank crowded templates"}) + "\n",
                encoding="utf-8",
            )
            (job_dir / "job.json").write_text(
                json.dumps({"job_id": "job-1", "status": "completed", "action": "readiness-check"}),
                encoding="utf-8",
            )
            milestone = root / "milestone.md"
            milestone.write_text("## Active Loop\n\nLoop name: `workflow-console`\n", encoding="utf-8")
            todo = root / "todo.md"
            todo.write_text("# todo\n", encoding="utf-8")

            state = load_console_state(
                ConsolePaths(
                    project_root=root,
                    workflow_root=root / "BrainWorkflow",
                    knowledge_root=knowledge,
                    runs_root=runs,
                    milestone_path=milestone,
                    todo_path=todo,
                    job_root=runs / "console_jobs",
                )
            )

        self.assertTrue(state["readiness"]["passed"])
        self.assertEqual(state["freshness"]["record_count"], 1)
        self.assertEqual(state["option_cards"][0]["title"], "Explore current Power Pool boards")
        self.assertIn("Research Schedule", state["schedule"]["preview"])
        self.assertEqual(state["jobs"][0]["job_id"], "job-1")
        self.assertEqual(state["proposal_counts"]["proposed"], 1)
        self.assertEqual(state["milestone"]["active_loop"], "workflow-console")

    def test_load_console_state_handles_missing_optional_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            knowledge = root / "knowledge"
            runs = root / "runs"
            knowledge.mkdir()
            runs.mkdir()
            state = load_console_state(
                ConsolePaths(
                    project_root=root,
                    workflow_root=root / "BrainWorkflow",
                    knowledge_root=knowledge,
                    runs_root=runs,
                    milestone_path=root / "milestone.md",
                    todo_path=root / "todo.md",
                    job_root=runs / "console_jobs",
                )
            )

        self.assertFalse(state["readiness"]["exists"])
        self.assertEqual(state["option_cards"], [])
        self.assertEqual(state["jobs"], [])
        self.assertEqual(state["proposal_counts"], {})
```

- [ ] **Step 2: Run state tests and verify failure**

Run:

```powershell
cd C:\Users\oytl\Desktop\pyproject\brain\skills-and-workflows\BrainWorkflow
python -m unittest tests.test_console_state -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'wqb.console_state'`.

- [ ] **Step 3: Implement console state module**

Create `BrainWorkflow/wqb/console_state.py`:

```python
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date
import json
from pathlib import Path
from typing import Any

from wqb.knowledge_freshness import evaluate_freshness, load_freshness_manifest


@dataclass(frozen=True)
class ConsolePaths:
    project_root: Path
    workflow_root: Path
    knowledge_root: Path
    runs_root: Path
    milestone_path: Path
    todo_path: Path
    job_root: Path


def default_console_paths(
    knowledge_root: str | Path | None = None,
    runs_root: str | Path | None = None,
) -> ConsolePaths:
    """Input: optional roots. Output: ConsolePaths. Resolve default local console paths."""
    workflow_root = Path(__file__).resolve().parents[1]
    project_root = workflow_root.parents[1]
    knowledge = Path(knowledge_root) if knowledge_root is not None else project_root / "knowledge"
    runs = Path(runs_root) if runs_root is not None else project_root / "runs"
    return ConsolePaths(
        project_root=project_root,
        workflow_root=workflow_root,
        knowledge_root=knowledge,
        runs_root=runs,
        milestone_path=project_root / "milestone.md",
        todo_path=project_root / "todo.md",
        job_root=runs / "console_jobs",
    )


def _read_json(path: Path) -> dict[str, Any]:
    """Input: JSON path. Output: dict. Return empty dict for absent or invalid files."""
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Input: JSONL path. Output: rows. Skip blank and invalid lines."""
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _latest_readiness(runs_root: Path) -> dict[str, Any]:
    """Input: runs root. Output: readiness summary. Read newest readiness report."""
    reports = sorted(runs_root.glob("**/readiness_report.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not reports:
        return {"exists": False}
    payload = _read_json(reports[0])
    payload["exists"] = True
    payload["path"] = str(reports[0])
    return payload


def _freshness_summary(knowledge_root: Path) -> dict[str, Any]:
    """Input: knowledge root. Output: freshness counts. Evaluate the manifest when present."""
    manifest = knowledge_root / "wiki" / "80_maintenance" / "freshness_manifest.json"
    if not manifest.exists():
        return {"exists": False, "record_count": 0, "stale_count": 0, "missing_count": 0, "records": []}
    try:
        records = load_freshness_manifest(manifest, strict=False)
        statuses = evaluate_freshness(records, date.today(), artifact_root=knowledge_root)
    except (OSError, ValueError, json.JSONDecodeError):
        return {"exists": True, "record_count": 0, "stale_count": 0, "missing_count": 0, "records": []}
    return {
        "exists": True,
        "record_count": len(statuses),
        "stale_count": len([status for status in statuses if status.stale]),
        "missing_count": len([status for status in statuses if not status.artifact_exists]),
        "records": [status.__dict__ for status in statuses],
    }


def _schedule_summary(knowledge_root: Path) -> dict[str, Any]:
    """Input: knowledge root. Output: schedule preview. Read current schedule Markdown."""
    path = knowledge_root / "wiki" / "70_decisions" / "research_schedule.md"
    if not path.exists():
        return {"exists": False, "path": str(path), "preview": ""}
    text = path.read_text(encoding="utf-8")
    return {"exists": True, "path": str(path), "preview": text[:2000]}


def _job_rows(job_root: Path) -> list[dict[str, Any]]:
    """Input: job root. Output: job rows. Read job records newest first."""
    rows = [_read_json(path) for path in job_root.glob("*/job.json")]
    rows = [row for row in rows if row]
    return sorted(rows, key=lambda row: str(row.get("updated_at", row.get("created_at", ""))), reverse=True)


def _milestone_summary(path: Path) -> dict[str, str]:
    """Input: milestone path. Output: active loop summary. Extract a readable recovery anchor."""
    if not path.exists():
        return {"exists": "false", "active_loop": "", "path": str(path)}
    text = path.read_text(encoding="utf-8")
    active_loop = ""
    for line in text.splitlines():
        if line.startswith("Loop name:"):
            active_loop = line.split("`")[1] if "`" in line else line.replace("Loop name:", "").strip()
            break
    return {"exists": "true", "active_loop": active_loop, "path": str(path)}


def load_console_state(paths: ConsolePaths) -> dict[str, Any]:
    """Input: console paths. Output: JSON-safe state dict. Aggregate dashboard data."""
    decisions = paths.knowledge_root / "wiki" / "70_decisions"
    proposals = _read_jsonl(decisions / "workflow_change_proposals.jsonl")
    proposal_counts = Counter(str(row.get("status", "unclassified")) for row in proposals)
    return {
        "readiness": _latest_readiness(paths.runs_root),
        "freshness": _freshness_summary(paths.knowledge_root),
        "option_cards": _read_jsonl(decisions / "research_option_cards.jsonl"),
        "schedule": _schedule_summary(paths.knowledge_root),
        "jobs": _job_rows(paths.job_root),
        "proposals": proposals,
        "proposal_counts": dict(proposal_counts),
        "milestone": _milestone_summary(paths.milestone_path),
    }
```

- [ ] **Step 4: Run state tests and verify pass**

Run:

```powershell
python -m unittest tests.test_console_state -v
```

Expected: PASS with `Ran 2 tests`.

- [ ] **Step 5: Commit state aggregation**

Run:

```powershell
git add BrainWorkflow/wqb/console_state.py BrainWorkflow/tests/test_console_state.py
git commit -m "add console state aggregation"
```

Expected: commit created.

---

### Task 2: Console Job Runner

**Files:**
- Create: `BrainWorkflow/wqb/console_jobs.py`
- Test: `BrainWorkflow/tests/test_console_jobs.py`

**Interfaces:**
- Consumes: `ConsolePaths` from `wqb.console_state`.
- Produces: `ConsoleJob` dataclass.
- Produces: `build_cli_command(workflow_root: Path, args: list[str]) -> list[str]`
- Produces: `create_job(job_root: Path, action: str, command: list[str], cwd: Path, inputs: dict[str, Any]) -> ConsoleJob`
- Produces: `run_job(job: ConsoleJob, timeout_seconds: int | None = None) -> ConsoleJob`
- Produces: `load_job_history(job_root: Path) -> list[dict[str, Any]]`

- [ ] **Step 1: Write failing job runner tests**

Create `BrainWorkflow/tests/test_console_jobs.py`:

```python
import json
import sys
import tempfile
import unittest
from pathlib import Path

from wqb.console_jobs import build_cli_command, create_job, load_job_history, run_job


class ConsoleJobsTests(unittest.TestCase):
    def test_create_and_run_successful_job_writes_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            command = [sys.executable, "-c", "print('ok')"]
            job = create_job(root / "jobs", "smoke", command, root, {"mode": "test"})
            finished = run_job(job, timeout_seconds=10)
            payload = json.loads(Path(finished.job_path).read_text(encoding="utf-8"))
            stdout = Path(finished.stdout_path).read_text(encoding="utf-8")

        self.assertEqual(finished.status, "completed")
        self.assertEqual(payload["exit_code"], 0)
        self.assertIn("ok", stdout)
        self.assertTrue(Path(finished.summary_path).exists())

    def test_failed_job_records_exit_code_and_stderr(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            command = [sys.executable, "-c", "import sys; print('bad', file=sys.stderr); sys.exit(3)"]
            job = create_job(root / "jobs", "fail", command, root, {})
            finished = run_job(job, timeout_seconds=10)
            stderr = Path(finished.stderr_path).read_text(encoding="utf-8")

        self.assertEqual(finished.status, "failed")
        self.assertEqual(finished.exit_code, 3)
        self.assertIn("bad", stderr)

    def test_build_cli_command_uses_python_module_entrypoint(self):
        command = build_cli_command(Path("BrainWorkflow"), ["readiness-check", "--readiness-mode", "plan-only"])

        self.assertEqual(command[:3], [sys.executable, "-m", "wqb.cli"])
        self.assertIn("readiness-check", command)

    def test_load_job_history_orders_newest_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = create_job(root / "jobs", "first", [sys.executable, "-c", "print(1)"], root, {})
            second = create_job(root / "jobs", "second", [sys.executable, "-c", "print(2)"], root, {})
            history = load_job_history(root / "jobs")

        self.assertEqual(history[0]["job_id"], second.job_id)
        self.assertEqual(history[1]["job_id"], first.job_id)
```

- [ ] **Step 2: Run job tests and verify failure**

Run:

```powershell
python -m unittest tests.test_console_jobs -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'wqb.console_jobs'`.

- [ ] **Step 3: Implement job runner**

Create `BrainWorkflow/wqb/console_jobs.py`:

```python
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
from typing import Any
from uuid import uuid4


@dataclass(frozen=True)
class ConsoleJob:
    job_id: str
    created_at: str
    updated_at: str
    status: str
    action: str
    command: list[str]
    cwd: str
    inputs: dict[str, Any]
    outputs: dict[str, str]
    exit_code: int | None
    job_path: str
    summary_path: str
    stdout_path: str
    stderr_path: str


def _now() -> str:
    """Input: none. Output: ISO timestamp. Use UTC for durable job records."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _write_job(job: ConsoleJob) -> None:
    """Input: job. Output: none. Persist job JSON."""
    Path(job.job_path).write_text(json.dumps(asdict(job), ensure_ascii=False, indent=2), encoding="utf-8")


def _replace(job: ConsoleJob, **changes: Any) -> ConsoleJob:
    """Input: job and changes. Output: ConsoleJob. Build an updated immutable job."""
    data = asdict(job)
    data.update(changes)
    data["updated_at"] = _now()
    return ConsoleJob(**data)


def build_cli_command(workflow_root: Path, args: list[str]) -> list[str]:
    """Input: workflow root and CLI args. Output: command list. Build a module command."""
    return [sys.executable, "-m", "wqb.cli", *args]


def create_job(job_root: Path, action: str, command: list[str], cwd: Path, inputs: dict[str, Any]) -> ConsoleJob:
    """Input: job root, action, command, cwd, inputs. Output: job. Create a pending job record."""
    created = _now()
    job_id = f"{created[:10]}-{uuid4().hex[:12]}-{action.replace('_', '-')}"
    job_dir = job_root / job_id
    job_dir.mkdir(parents=True, exist_ok=False)
    job = ConsoleJob(
        job_id=job_id,
        created_at=created,
        updated_at=created,
        status="not_started",
        action=action,
        command=[str(item) for item in command],
        cwd=str(cwd),
        inputs=inputs,
        outputs={},
        exit_code=None,
        job_path=str(job_dir / "job.json"),
        summary_path=str(job_dir / "summary.md"),
        stdout_path=str(job_dir / "stdout.txt"),
        stderr_path=str(job_dir / "stderr.txt"),
    )
    _write_job(job)
    return job


def _write_summary(job: ConsoleJob) -> None:
    """Input: job. Output: none. Persist a Markdown job summary."""
    lines = [
        "# Console Job Summary",
        "",
        f"- Job ID: `{job.job_id}`",
        f"- Status: `{job.status}`",
        f"- Action: `{job.action}`",
        f"- Exit Code: `{job.exit_code}`",
        f"- CWD: `{job.cwd}`",
        f"- Command: `{' '.join(job.command)}`",
        f"- Stdout: `{job.stdout_path}`",
        f"- Stderr: `{job.stderr_path}`",
    ]
    Path(job.summary_path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_job(job: ConsoleJob, timeout_seconds: int | None = None) -> ConsoleJob:
    """Input: job and timeout. Output: finished job. Run a subprocess and capture artifacts."""
    running = _replace(job, status="running")
    _write_job(running)
    try:
        completed = subprocess.run(
            running.command,
            cwd=running.cwd,
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
        )
        Path(running.stdout_path).write_text(completed.stdout, encoding="utf-8")
        Path(running.stderr_path).write_text(completed.stderr, encoding="utf-8")
        status = "completed" if completed.returncode == 0 else "failed"
        finished = _replace(running, status=status, exit_code=completed.returncode)
    except subprocess.TimeoutExpired as error:
        Path(running.stdout_path).write_text(error.stdout or "", encoding="utf-8")
        Path(running.stderr_path).write_text(error.stderr or "console job timed out", encoding="utf-8")
        finished = _replace(running, status="failed", exit_code=-1)
    _write_summary(finished)
    _write_job(finished)
    return finished


def load_job_history(job_root: Path) -> list[dict[str, Any]]:
    """Input: job root. Output: job rows newest first. Read durable console jobs."""
    rows: list[dict[str, Any]] = []
    for path in job_root.glob("*/job.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return sorted(rows, key=lambda row: str(row.get("created_at", "")), reverse=True)
```

- [ ] **Step 4: Run job tests and verify pass**

Run:

```powershell
python -m unittest tests.test_console_jobs -v
```

Expected: PASS with `Ran 4 tests`.

- [ ] **Step 5: Commit job runner**

Run:

```powershell
git add BrainWorkflow/wqb/console_jobs.py BrainWorkflow/tests/test_console_jobs.py
git commit -m "add console job runner"
```

Expected: commit created.

---

### Task 3: Workflow Proposal Inbox Helpers

**Files:**
- Modify: `BrainWorkflow/wqb/workflow_proposals.py`
- Create: `BrainWorkflow/wqb/console_proposals.py`
- Test: `BrainWorkflow/tests/test_console_proposals.py`
- Modify: `BrainWorkflow/tests/test_workflow_proposals.py`

**Interfaces:**
- Consumes: `proposal_from_issue`, `write_workflow_proposals`
- Produces: `load_workflow_proposal_rows(output_dir: Path) -> list[dict[str, Any]]`
- Produces: `write_workflow_proposal_rows(output_dir: Path, rows: list[dict[str, Any]]) -> tuple[Path, Path]`
- Produces: `update_workflow_proposal_decision(output_dir: Path, proposal_id: str, status: str, user_decision: str) -> dict[str, Any]`
- Produces: `create_proposal_from_form(output_dir: Path, form: dict[str, str], generated_at: str) -> dict[str, Any]`

- [ ] **Step 1: Write failing proposal helper tests**

Create `BrainWorkflow/tests/test_console_proposals.py`:

```python
import json
import tempfile
import unittest
from pathlib import Path

from wqb.console_proposals import create_proposal_from_form
from wqb.workflow_proposals import load_workflow_proposal_rows, update_workflow_proposal_decision


class ConsoleProposalTests(unittest.TestCase):
    def test_create_proposal_from_form_writes_jsonl_and_markdown(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            row = create_proposal_from_form(
                output_dir,
                {
                    "issue_type": "prod_correlation",
                    "summary": "News templates clustered in production correlation.",
                    "trigger": "Two batches failed PROD_CORRELATION.",
                    "evidence_paths": "runs/a.json\nruns/b.json",
                    "affected_modules": "template_library\nbenchmark",
                    "proposed_rule_change": "Down-rank the clustered template-data pairs.",
                    "expected_benefit": "Spend fewer correlation checks on crowded structures.",
                    "risk": "May skip a repairable variant.",
                    "required_code_changes": "wqb/template_library.py",
                    "required_knowledge_updates": "knowledge/wiki/50_benchmarks/correlation_and_novelty.md",
                },
                "2026-07-12T00:00:00Z",
            )
            rows = load_workflow_proposal_rows(output_dir)
            markdown = (output_dir / "workflow_change_proposals.md").read_text(encoding="utf-8")

        self.assertEqual(row["status"], "proposed")
        self.assertEqual(rows[0]["proposal_id"], row["proposal_id"])
        self.assertIn("News templates", markdown)
        self.assertIn("runs/a.json", markdown)

    def test_update_workflow_proposal_decision_changes_status_and_preserves_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            row = create_proposal_from_form(
                output_dir,
                {"issue_type": "manual_review", "summary": "Add a data schedule rule."},
                "2026-07-12T00:00:00Z",
            )
            updated = update_workflow_proposal_decision(output_dir, row["proposal_id"], "accepted", "accept")
            rows = [json.loads(line) for line in (output_dir / "workflow_change_proposals.jsonl").read_text(encoding="utf-8").splitlines()]

        self.assertEqual(updated["status"], "accepted")
        self.assertEqual(updated["user_decision"], "accept")
        self.assertEqual(rows[0]["status"], "accepted")
```

Modify `BrainWorkflow/tests/test_workflow_proposals.py` by adding:

```python
    def test_update_workflow_proposal_decision_rejects_invalid_status(self):
        proposal = proposal_from_issue(
            {"issue_type": "manual_review", "summary": "Review a new rule."},
            "2026-07-12T00:00:00Z",
        )
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            write_workflow_proposals(output_dir, [proposal])
            from wqb.workflow_proposals import update_workflow_proposal_decision

            with self.assertRaisesRegex(ValueError, "unsupported proposal status"):
                update_workflow_proposal_decision(output_dir, proposal.proposal_id, "bad_status", "bad")
```

- [ ] **Step 2: Run proposal tests and verify failure**

Run:

```powershell
python -m unittest tests.test_console_proposals tests.test_workflow_proposals -v
```

Expected: FAIL because `wqb.console_proposals` and exported decision helpers do not exist.

- [ ] **Step 3: Extend workflow proposal persistence**

Modify `BrainWorkflow/wqb/workflow_proposals.py` by adding these functions after `_proposal_from_dict`:

```python
SUPPORTED_PROPOSAL_STATUSES = {"proposed", "accepted", "rejected", "revise", "deferred", "applied"}


def load_workflow_proposal_rows(output_dir: Path) -> list[dict[str, Any]]:
    """Input: output dir. Output: proposal rows. Load persisted workflow proposal records."""
    jsonl_path = output_dir / PROPOSAL_JSONL
    rows: list[dict[str, Any]] = []
    if not jsonl_path.exists():
        return rows
    for line in jsonl_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if isinstance(row, dict):
            rows.append(row)
    return rows


def write_workflow_proposal_rows(output_dir: Path, rows: list[dict[str, Any]]) -> tuple[Path, Path]:
    """Input: output dir and rows. Output: JSONL and Markdown paths. Persist proposal rows."""
    output_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = output_dir / PROPOSAL_JSONL
    markdown_path = output_dir / PROPOSAL_MARKDOWN
    with jsonl_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    markdown = ["# Workflow Change Proposals", ""]
    for row in rows:
        markdown.append(_proposal_markdown(_proposal_from_dict(row)))
    markdown_path.write_text("\n\n".join(markdown), encoding="utf-8")
    return jsonl_path, markdown_path


def update_workflow_proposal_decision(output_dir: Path, proposal_id: str, status: str, user_decision: str) -> dict[str, Any]:
    """Input: output dir, proposal id, status, decision. Output: updated row. Persist a user decision."""
    if status not in SUPPORTED_PROPOSAL_STATUSES:
        raise ValueError(f"unsupported proposal status: {status}")
    rows = load_workflow_proposal_rows(output_dir)
    for row in rows:
        if str(row.get("proposal_id", "")) == proposal_id:
            row["status"] = status
            row["user_decision"] = user_decision
            write_workflow_proposal_rows(output_dir, rows)
            return row
    raise ValueError(f"workflow proposal not found: {proposal_id}")
```

Modify `write_workflow_proposals` so it starts with:

```python
    rows = load_workflow_proposal_rows(output_dir)
```

and ends with:

```python
    return write_workflow_proposal_rows(output_dir, rows)
```

- [ ] **Step 4: Implement console proposal form conversion**

Create `BrainWorkflow/wqb/console_proposals.py`:

```python
from __future__ import annotations

from pathlib import Path
from typing import Any

from wqb.workflow_proposals import proposal_from_issue, workflow_change_proposal_to_dict, write_workflow_proposals


def _lines(value: str) -> list[str]:
    """Input: text area value. Output: non-empty stripped lines."""
    return [line.strip() for line in value.splitlines() if line.strip()]


def create_proposal_from_form(output_dir: Path, form: dict[str, str], generated_at: str) -> dict[str, Any]:
    """Input: output dir, form fields, timestamp. Output: proposal row. Persist a proposal from UI data."""
    summary = form.get("summary", "").strip() or "Manual workflow proposal"
    issue = {
        "issue_type": form.get("issue_type", "manual_review").strip() or "manual_review",
        "summary": summary,
        "trigger": form.get("trigger", summary).strip() or summary,
        "evidence_paths": _lines(form.get("evidence_paths", "")),
        "affected_modules": _lines(form.get("affected_modules", "")),
    }
    proposal = proposal_from_issue(issue, generated_at)
    row = workflow_change_proposal_to_dict(proposal)
    for field_name in (
        "proposed_rule_change",
        "expected_benefit",
        "risk",
    ):
        value = form.get(field_name, "").strip()
        if value:
            row[field_name] = value
    required_code_changes = _lines(form.get("required_code_changes", ""))
    required_knowledge_updates = _lines(form.get("required_knowledge_updates", ""))
    if required_code_changes:
        row["required_code_changes"] = required_code_changes
    if required_knowledge_updates:
        row["required_knowledge_updates"] = required_knowledge_updates
    write_workflow_proposals(output_dir, [proposal])
    rows = [row]
    jsonl_path = output_dir / "workflow_change_proposals.jsonl"
    if jsonl_path.exists():
        import json

        existing_rows = [json.loads(line) for line in jsonl_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        rows = [existing if existing.get("proposal_id") != row["proposal_id"] else row for existing in existing_rows]
        from wqb.workflow_proposals import write_workflow_proposal_rows

        write_workflow_proposal_rows(output_dir, rows)
    return row
```

- [ ] **Step 5: Run proposal tests and verify pass**

Run:

```powershell
python -m unittest tests.test_console_proposals tests.test_workflow_proposals -v
```

Expected: PASS.

- [ ] **Step 6: Commit proposal helpers**

Run:

```powershell
git add BrainWorkflow/wqb/workflow_proposals.py BrainWorkflow/wqb/console_proposals.py BrainWorkflow/tests/test_console_proposals.py BrainWorkflow/tests/test_workflow_proposals.py
git commit -m "add console proposal inbox helpers"
```

Expected: commit created.

---

### Task 4: Context Guard

**Files:**
- Create: `BrainWorkflow/wqb/console_context.py`
- Test: `BrainWorkflow/tests/test_console_context.py`

**Interfaces:**
- Consumes: `ConsolePaths` from `wqb.console_state`
- Consumes: `ConsoleJob` from `wqb.console_jobs`
- Produces: `record_console_job_context(paths: ConsolePaths, job: ConsoleJob, next_command: str, blocker: str = "") -> dict[str, str]`

- [ ] **Step 1: Write failing context guard tests**

Create `BrainWorkflow/tests/test_console_context.py`:

```python
import sys
import tempfile
import unittest
from pathlib import Path

from wqb.console_context import record_console_job_context
from wqb.console_jobs import create_job, run_job
from wqb.console_state import ConsolePaths


class ConsoleContextTests(unittest.TestCase):
    def test_record_console_job_context_appends_milestone_todo_and_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runs = root / "runs"
            runs.mkdir()
            milestone = root / "milestone.md"
            todo = root / "todo.md"
            milestone.write_text("# Milestone\n", encoding="utf-8")
            todo.write_text("# Todo\n", encoding="utf-8")
            job = create_job(runs / "console_jobs", "readiness-check", [sys.executable, "-c", "print('ok')"], root, {})
            finished = run_job(job, timeout_seconds=10)
            paths = ConsolePaths(root, root / "BrainWorkflow", root / "knowledge", runs, milestone, todo, runs / "console_jobs")

            result = record_console_job_context(paths, finished, "python -m wqb.cli readiness-check", blocker="")
            milestone_text = milestone.read_text(encoding="utf-8")
            todo_text = todo.read_text(encoding="utf-8")
            summary_text = Path(finished.summary_path).read_text(encoding="utf-8")

        self.assertIn("Console Job Context", milestone_text)
        self.assertIn(finished.job_id, milestone_text)
        self.assertIn("readiness-check", todo_text)
        self.assertIn("Next Command", summary_text)
        self.assertEqual(result["milestone_path"], str(milestone))
```

- [ ] **Step 2: Run context tests and verify failure**

Run:

```powershell
python -m unittest tests.test_console_context -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'wqb.console_context'`.

- [ ] **Step 3: Implement context guard**

Create `BrainWorkflow/wqb/console_context.py`:

```python
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from wqb.console_jobs import ConsoleJob
from wqb.console_state import ConsolePaths


def _append(path: Path, text: str) -> None:
    """Input: path and text. Output: none. Append UTF-8 text, creating parents."""
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    path.write_text(existing.rstrip() + "\n\n" + text.rstrip() + "\n", encoding="utf-8")


def record_console_job_context(paths: ConsolePaths, job: ConsoleJob, next_command: str, blocker: str = "") -> dict[str, str]:
    """Input: paths, job, next command, blocker. Output: written paths. Persist recovery context."""
    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    blocker_line = blocker or "none"
    milestone_entry = (
        "## Console Job Context\n\n"
        f"- Updated At: `{generated_at}`\n"
        f"- Job ID: `{job.job_id}`\n"
        f"- Action: `{job.action}`\n"
        f"- Status: `{job.status}`\n"
        f"- Summary: `{job.summary_path}`\n"
        f"- Blocker: {blocker_line}\n"
        f"- Next Command: `{next_command}`\n"
    )
    todo_entry = (
        "## Console Job Update\n\n"
        f"- Job ID: `{job.job_id}`\n"
        f"- Action: `{job.action}`\n"
        f"- Status: `{job.status}`\n"
        f"- Summary: `{job.summary_path}`\n"
    )
    _append(paths.milestone_path, milestone_entry)
    _append(paths.todo_path, todo_entry)
    _append(
        Path(job.summary_path),
        (
            "## Recovery\n\n"
            f"- Blocker: {blocker_line}\n"
            f"- Next Command: `{next_command}`\n"
        ),
    )
    return {"milestone_path": str(paths.milestone_path), "todo_path": str(paths.todo_path), "summary_path": job.summary_path}
```

- [ ] **Step 4: Run context tests and verify pass**

Run:

```powershell
python -m unittest tests.test_console_context -v
```

Expected: PASS with `Ran 1 test`.

- [ ] **Step 5: Commit context guard**

Run:

```powershell
git add BrainWorkflow/wqb/console_context.py BrainWorkflow/tests/test_console_context.py
git commit -m "add console context guard"
```

Expected: commit created.

---

### Task 5: Local Web Server And Read-Only Pages

**Files:**
- Create: `BrainWorkflow/wqb/console_server.py`
- Test: `BrainWorkflow/tests/test_console_server.py`

**Interfaces:**
- Consumes: `ConsolePaths`, `load_console_state`
- Produces: `render_dashboard(state: dict[str, Any]) -> str`
- Produces: `render_proposals(state: dict[str, Any]) -> str`
- Produces: `make_console_server(host: str, port: int, paths: ConsolePaths) -> ThreadingHTTPServer`

- [ ] **Step 1: Write failing read-only server tests**

Create `BrainWorkflow/tests/test_console_server.py`:

```python
import tempfile
import unittest
from pathlib import Path

from wqb.console_server import make_console_server, render_dashboard, render_proposals
from wqb.console_state import ConsolePaths


class ConsoleServerTests(unittest.TestCase):
    def test_render_dashboard_contains_core_sections(self):
        html = render_dashboard(
            {
                "readiness": {"exists": True, "passed": True, "blocked": False, "path": "runs/readiness/readiness_report.json"},
                "freshness": {"record_count": 2, "stale_count": 0, "missing_count": 0},
                "option_cards": [{"title": "Explore current Power Pool boards", "score": {"total": 10.5}}],
                "schedule": {"exists": True, "preview": "# Research Schedule"},
                "jobs": [{"job_id": "job-1", "status": "completed", "action": "readiness-check"}],
                "proposal_counts": {"proposed": 1},
                "milestone": {"active_loop": "workflow-console"},
            }
        )

        self.assertIn("Workflow Console", html)
        self.assertIn("Explore current Power Pool boards", html)
        self.assertIn("readiness-check", html)

    def test_render_proposals_contains_form_and_existing_rows(self):
        html = render_proposals({"proposals": [{"proposal_id": "p1", "title": "Rule change", "status": "proposed"}]})

        self.assertIn("<form", html)
        self.assertIn("Rule change", html)
        self.assertIn("proposal_id", html)

    def test_make_console_server_constructs_local_server(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = ConsolePaths(root, root / "BrainWorkflow", root / "knowledge", root / "runs", root / "milestone.md", root / "todo.md", root / "runs" / "console_jobs")
            server = make_console_server("127.0.0.1", 0, paths)
            port = server.server_address[1]
            server.server_close()

        self.assertGreater(port, 0)
```

- [ ] **Step 2: Run server tests and verify failure**

Run:

```powershell
python -m unittest tests.test_console_server -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'wqb.console_server'`.

- [ ] **Step 3: Implement read-only server and HTML renderers**

Create `BrainWorkflow/wqb/console_server.py` with:

```python
from __future__ import annotations

from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

from wqb.console_state import ConsolePaths, default_console_paths, load_console_state


def _page(title: str, body: str) -> str:
    """Input: title and body. Output: HTML page."""
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<title>{escape(title)}</title>"
        "<style>"
        "body{font-family:Segoe UI,Arial,sans-serif;margin:24px;background:#f7f7f4;color:#1f2933}"
        "nav a{margin-right:16px;color:#1d4ed8;text-decoration:none}"
        "section{border:1px solid #d8d8d0;background:white;padding:16px;margin:16px 0;border-radius:6px}"
        "table{border-collapse:collapse;width:100%}td,th{border-bottom:1px solid #e5e7eb;padding:8px;text-align:left}"
        "button{padding:8px 12px;border:1px solid #374151;background:#111827;color:white;border-radius:4px}"
        "input,select,textarea{width:100%;padding:8px;margin:4px 0 12px;border:1px solid #cbd5e1;border-radius:4px}"
        "</style></head><body>"
        "<nav><a href='/'>Dashboard</a><a href='/research'>Research</a><a href='/knowledge'>Knowledge</a><a href='/jobs'>Jobs</a><a href='/proposals'>Proposals</a></nav>"
        f"<h1>{escape(title)}</h1>{body}</body></html>"
    )


def _value(value: Any) -> str:
    """Input: any value. Output: escaped display string."""
    return escape(str(value))


def render_dashboard(state: dict[str, Any]) -> str:
    """Input: console state. Output: dashboard HTML."""
    readiness = state.get("readiness", {})
    freshness = state.get("freshness", {})
    options = state.get("option_cards", [])
    jobs = state.get("jobs", [])
    proposal_counts = state.get("proposal_counts", {})
    milestone = state.get("milestone", {})
    option_rows = "".join(f"<li>{_value(row.get('title', 'untitled'))}</li>" for row in options[:5])
    job_rows = "".join(f"<tr><td>{_value(row.get('job_id', ''))}</td><td>{_value(row.get('action', ''))}</td><td>{_value(row.get('status', ''))}</td></tr>" for row in jobs[:10])
    body = (
        "<section><h2>Readiness</h2>"
        f"<p>Exists: {_value(readiness.get('exists', False))} Passed: {_value(readiness.get('passed', ''))} Blocked: {_value(readiness.get('blocked', ''))}</p></section>"
        "<section><h2>Freshness</h2>"
        f"<p>Records: {_value(freshness.get('record_count', 0))} Stale: {_value(freshness.get('stale_count', 0))} Missing: {_value(freshness.get('missing_count', 0))}</p></section>"
        f"<section><h2>Research Options</h2><ul>{option_rows}</ul></section>"
        f"<section><h2>Milestone</h2><p>{_value(milestone.get('active_loop', ''))}</p></section>"
        f"<section><h2>Proposal Counts</h2><p>{_value(proposal_counts)}</p></section>"
        f"<section><h2>Recent Jobs</h2><table><tr><th>Job</th><th>Action</th><th>Status</th></tr>{job_rows}</table></section>"
    )
    return _page("Workflow Console", body)


def render_proposals(state: dict[str, Any]) -> str:
    """Input: console state. Output: proposal inbox HTML."""
    rows = state.get("proposals", [])
    proposal_rows = "".join(
        f"<tr><td>{_value(row.get('proposal_id', ''))}</td><td>{_value(row.get('title', ''))}</td><td>{_value(row.get('status', ''))}</td></tr>"
        for row in rows
    )
    body = (
        "<section><h2>New Proposal</h2>"
        "<form method='post' action='/proposals/create'>"
        "<label>Issue Type</label><input name='issue_type' value='manual_review'>"
        "<label>Summary</label><textarea name='summary'></textarea>"
        "<label>Evidence Paths</label><textarea name='evidence_paths'></textarea>"
        "<button type='submit'>Create Proposal</button></form></section>"
        f"<section><h2>Existing Proposals</h2><table><tr><th>proposal_id</th><th>Title</th><th>Status</th></tr>{proposal_rows}</table></section>"
    )
    return _page("Workflow Proposals", body)


class ConsoleRequestHandler(BaseHTTPRequestHandler):
    paths: ConsolePaths

    def _send(self, html: str, status: int = 200) -> None:
        """Input: HTML and status. Output: none. Send a UTF-8 response."""
        payload = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:
        """Input: HTTP GET. Output: response. Route read-only console pages."""
        state = load_console_state(self.paths)
        if self.path.startswith("/proposals"):
            self._send(render_proposals(state))
            return
        self._send(render_dashboard(state))

    def do_POST(self) -> None:
        """Input: HTTP POST. Output: response. Reject action routes until Task 6 wires them."""
        self._send(_page("Action Not Wired", "<p>Action routes are added in the next task.</p>"), status=400)


def make_console_server(host: str, port: int, paths: ConsolePaths) -> ThreadingHTTPServer:
    """Input: host, port, paths. Output: server. Construct a local console server."""
    handler = type("BoundConsoleRequestHandler", (ConsoleRequestHandler,), {"paths": paths})
    return ThreadingHTTPServer((host, port), handler)


def run_console(host: str = "127.0.0.1", port: int = 8765, knowledge_root: str | Path | None = None, runs_root: str | Path | None = None) -> None:
    """Input: host, port, optional roots. Output: none. Run the local console until interrupted."""
    paths = default_console_paths(knowledge_root=knowledge_root, runs_root=runs_root)
    server = make_console_server(host, port, paths)
    print(f"Workflow Console: http://{host}:{server.server_address[1]}")
    server.serve_forever()
```

- [ ] **Step 4: Run server tests and verify pass**

Run:

```powershell
python -m unittest tests.test_console_server -v
```

Expected: PASS with `Ran 3 tests`.

- [ ] **Step 5: Commit read-only server**

Run:

```powershell
git add BrainWorkflow/wqb/console_server.py BrainWorkflow/tests/test_console_server.py
git commit -m "add read-only workflow console server"
```

Expected: commit created.

---

### Task 6: Console Action Routes And Safety Gates

**Files:**
- Modify: `BrainWorkflow/wqb/console_server.py`
- Modify: `BrainWorkflow/tests/test_console_server.py`

**Interfaces:**
- Consumes: `build_cli_command`, `create_job`, `run_job`
- Consumes: `record_console_job_context`
- Consumes: `create_proposal_from_form`, `update_workflow_proposal_decision`
- Produces: `build_action_command(action: str, form: dict[str, str], paths: ConsolePaths) -> tuple[list[str], Path, dict[str, Any], str]`
- Produces: POST routes for research, knowledge, readiness, launcher, proposal creation, and proposal decisions.

- [ ] **Step 1: Add failing action command tests**

Append to `BrainWorkflow/tests/test_console_server.py`:

```python
    def test_build_action_command_refuses_research_without_live_api(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = ConsolePaths(root, root / "BrainWorkflow", root / "knowledge", root / "runs", root / "milestone.md", root / "todo.md", root / "runs" / "console_jobs")
            from wqb.console_server import build_action_command

            with self.assertRaisesRegex(ValueError, "live API"):
                build_action_command("readiness-check", {"readiness_mode": "research"}, paths)

    def test_build_action_command_refuses_submit_without_confirmation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = ConsolePaths(root, root / "BrainWorkflow", root / "knowledge", root / "runs", root / "milestone.md", root / "todo.md", root / "runs" / "console_jobs")
            from wqb.console_server import build_action_command

            with self.assertRaisesRegex(ValueError, "submit confirmation"):
                build_action_command("readiness-check", {"readiness_mode": "submit-candidate", "enable_live_api": "on"}, paths)

    def test_build_action_command_creates_plan_only_readiness_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = ConsolePaths(root, root / "BrainWorkflow", root / "knowledge", root / "runs", root / "milestone.md", root / "todo.md", root / "runs" / "console_jobs")
            from wqb.console_server import build_action_command

            command, cwd, inputs, next_command = build_action_command("readiness-check", {"readiness_mode": "plan-only"}, paths)

        self.assertIn("readiness-check", command)
        self.assertIn("--readiness-mode", command)
        self.assertEqual(inputs["readiness_mode"], "plan-only")
        self.assertIn("readiness-check", next_command)
```

- [ ] **Step 2: Run action tests and verify failure**

Run:

```powershell
python -m unittest tests.test_console_server -v
```

Expected: FAIL because `build_action_command` does not exist.

- [ ] **Step 3: Implement action command builder and safety checks**

Add to `BrainWorkflow/wqb/console_server.py`:

```python
from datetime import datetime, timezone
from wqb.console_context import record_console_job_context
from wqb.console_jobs import build_cli_command, create_job, run_job
from wqb.console_proposals import create_proposal_from_form
from wqb.workflow_proposals import update_workflow_proposal_decision


def _is_checked(form: dict[str, str], key: str) -> bool:
    """Input: form and key. Output: bool. Interpret HTML checkbox values."""
    return form.get(key, "").lower() in {"on", "true", "1", "yes"}


def build_action_command(action: str, form: dict[str, str], paths: ConsolePaths) -> tuple[list[str], Path, dict[str, Any], str]:
    """Input: action, form, paths. Output: command, cwd, inputs, next command. Build a safe CLI action."""
    knowledge_root = str(paths.knowledge_root)
    workflow_root = paths.workflow_root
    if action == "plan-research-options":
        args = ["plan-research-options", "--knowledge-root", knowledge_root, "--max-options", form.get("max_options", "3"), "--option-output-dir", str(paths.knowledge_root / "wiki" / "70_decisions")]
    elif action == "schedule-research":
        args = [
            "schedule-research",
            "--knowledge-root",
            knowledge_root,
            "--option-json",
            str(paths.knowledge_root / "wiki" / "70_decisions" / "research_option_cards.jsonl"),
            "--option-index",
            form.get("option_index", "1"),
        ]
    elif action == "readiness-check":
        mode = form.get("readiness_mode", "plan-only")
        live_api = _is_checked(form, "enable_live_api")
        submit_confirmed = _is_checked(form, "confirm_submit")
        if mode == "research" and not live_api:
            raise ValueError("research readiness requires explicit live API enablement")
        if mode == "submit-candidate" and not submit_confirmed:
            raise ValueError("submit-candidate readiness requires explicit submit confirmation")
        args = ["readiness-check", "--knowledge-root", knowledge_root, "--readiness-mode", mode, "--batch-size", form.get("batch_size", "30"), "--readiness-output-dir", str(paths.runs_root / "console_readiness")]
        if live_api:
            args.append("--enable-live-api")
        if submit_confirmed:
            args.append("--confirm-submit")
    elif action == "bootstrap-knowledge":
        args = ["bootstrap-knowledge", "--knowledge-root", knowledge_root]
    elif action == "knowledge-health-check":
        args = ["knowledge-health-check", "--knowledge-root", knowledge_root]
    elif action == "launch-workflow":
        mode = form.get("workflow_mode", "plan-only")
        live_api = _is_checked(form, "enable_live_api")
        confirm_submit = _is_checked(form, "confirm_submit")
        if mode == "research" and not live_api:
            raise ValueError("research launch requires explicit live API enablement")
        if mode == "submit-candidate" and not confirm_submit:
            raise ValueError("submit-candidate launch requires explicit submit confirmation")
        args = ["launch-workflow", "--knowledge-root", knowledge_root, "--workflow-mode", mode]
        if live_api:
            args.append("--enable-live-api")
        if confirm_submit:
            args.append("--confirm-submit")
    else:
        raise ValueError(f"unsupported console action: {action}")
    command = build_cli_command(workflow_root, args)
    inputs = dict(form)
    inputs["action"] = action
    next_command = " ".join(command)
    return command, workflow_root, inputs, next_command
```

- [ ] **Step 4: Wire POST routes**

Replace `ConsoleRequestHandler.do_POST` in `BrainWorkflow/wqb/console_server.py` with:

```python
    def _form(self) -> dict[str, str]:
        """Input: POST body. Output: form dict. Parse URL-encoded fields."""
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8")
        parsed = parse_qs(raw, keep_blank_values=True)
        return {key: values[-1] for key, values in parsed.items()}

    def do_POST(self) -> None:
        """Input: HTTP POST. Output: response. Run approved actions and persist records."""
        form = self._form()
        try:
            if self.path == "/proposals/create":
                row = create_proposal_from_form(
                    self.paths.knowledge_root / "wiki" / "70_decisions",
                    form,
                    datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                )
                self._send(_page("Proposal Created", f"<p>Created proposal {_value(row.get('proposal_id', ''))}</p><p><a href='/proposals'>Back to proposals</a></p>"))
                return
            if self.path == "/proposals/decision":
                row = update_workflow_proposal_decision(
                    self.paths.knowledge_root / "wiki" / "70_decisions",
                    form.get("proposal_id", ""),
                    form.get("status", "proposed"),
                    form.get("user_decision", ""),
                )
                self._send(_page("Proposal Updated", f"<p>Updated proposal {_value(row.get('proposal_id', ''))}</p><p><a href='/proposals'>Back to proposals</a></p>"))
                return
            action = self.path.removeprefix("/actions/")
            command, cwd, inputs, next_command = build_action_command(action, form, self.paths)
            job = create_job(self.paths.job_root, action, command, cwd, inputs)
            finished = run_job(job)
            record_console_job_context(self.paths, finished, next_command, blocker="" if finished.status == "completed" else "console action failed")
            self._send(_page("Job Finished", f"<p>Job {_value(finished.job_id)} finished with status {_value(finished.status)}</p><p><a href='/jobs'>View jobs</a></p>"))
        except ValueError as error:
            self._send(_page("Action Blocked", f"<p>{_value(error)}</p>"), status=400)
```

- [ ] **Step 5: Add action forms to rendered pages**

In `render_dashboard`, add this section before the recent jobs section:

```python
        "<section><h2>Quick Actions</h2>"
        "<form method='post' action='/actions/plan-research-options'><button type='submit'>Refresh Research Options</button></form>"
        "<form method='post' action='/actions/readiness-check'><input type='hidden' name='readiness_mode' value='plan-only'><button type='submit'>Run Plan-Only Readiness</button></form>"
        "</section>"
```

In `render_proposals`, add a decision form row for each proposal:

```python
        f"<td><form method='post' action='/proposals/decision'>"
        f"<input type='hidden' name='proposal_id' value='{_value(row.get('proposal_id', ''))}'>"
        "<select name='status'><option>accepted</option><option>rejected</option><option>revise</option><option>deferred</option><option>applied</option></select>"
        "<input name='user_decision' value=''>"
        "<button type='submit'>Save</button></form></td>"
```

- [ ] **Step 6: Run action tests and verify pass**

Run:

```powershell
python -m unittest tests.test_console_server -v
```

Expected: PASS.

- [ ] **Step 7: Commit action routes**

Run:

```powershell
git add BrainWorkflow/wqb/console_server.py BrainWorkflow/tests/test_console_server.py
git commit -m "wire workflow console actions"
```

Expected: commit created.

---

### Task 7: CLI Entry Point, Docs, And Verification

**Files:**
- Modify: `BrainWorkflow/wqb/cli.py`
- Modify: `BrainWorkflow/tests/test_cli.py`
- Modify: `BrainWorkflow/README.md`

**Interfaces:**
- Consumes: `run_console` from `wqb.console_server`
- Produces: CLI command `launch-console`
- Produces: CLI options `--console-host`, `--console-port`, `--console-open-browser`

- [ ] **Step 1: Write failing CLI tests**

Append to `BrainWorkflow/tests/test_cli.py`:

```python
    def test_parse_args_accepts_launch_console(self):
        with patch("sys.argv", ["wqb", "launch-console", "--console-host", "127.0.0.1", "--console-port", "8765"]):
            args = parse_args()

        self.assertEqual(args.command, "launch-console")
        self.assertEqual(args.console_host, "127.0.0.1")
        self.assertEqual(args.console_port, 8765)

    def test_launch_console_main_dispatches_without_running_server(self):
        output = io.StringIO()
        with patch("sys.argv", ["wqb", "launch-console", "--console-port", "0"]), patch(
            "wqb.cli.run_console",
        ) as console, redirect_stdout(output):
            main()

        console.assert_called_once()
```

Ensure `io`, `redirect_stdout`, and `patch` are already imported in `tests/test_cli.py`; if any are missing, import them at the top using the existing test style.

- [ ] **Step 2: Run CLI tests and verify failure**

Run:

```powershell
python -m unittest tests.test_cli -v
```

Expected: FAIL because `launch-console` is not in command choices.

- [ ] **Step 3: Add CLI import and parser options**

Modify `BrainWorkflow/wqb/cli.py` imports:

```python
from wqb.console_server import run_console
```

Add `launch-console` to the positional command choices in `parse_args`.

Add parser arguments near other workflow arguments:

```python
    parser.add_argument("--console-host", default="127.0.0.1")
    parser.add_argument("--console-port", type=int, default=8765)
    parser.add_argument("--console-open-browser", action="store_true")
```

- [ ] **Step 4: Add CLI dispatch**

In `main()`, add this branch before commands that require stage config:

```python
    if args.command == "launch-console":
        if args.console_open_browser:
            import webbrowser

            webbrowser.open(f"http://{args.console_host}:{args.console_port}")
        run_console(
            host=args.console_host,
            port=args.console_port,
            knowledge_root=args.knowledge_root,
            runs_root=args.run_dir,
        )
        return
```

- [ ] **Step 5: Update README**

Add to `BrainWorkflow/README.md` after the Startup Layer section:

```markdown
## Workflow Console

The local Workflow Console is the browser control surface for the existing CLI
workflow. It reads the shared knowledge vault, recent readiness reports, current
research option cards, schedules, console jobs, and workflow-change proposals.

Start it from `BrainWorkflow/`:

```powershell
python -m wqb.cli launch-console --knowledge-root C:\Users\oytl\Desktop\pyproject\brain\knowledge --run-dir C:\Users\oytl\Desktop\pyproject\brain\runs --console-port 8765
```

Open `http://127.0.0.1:8765`.

Safety rules:

- Plan-only actions are available by default.
- Research actions require explicit live API enablement.
- Submit-candidate actions require explicit submit confirmation.
- The console records each action in `runs/console_jobs/` and updates recovery
  context in `milestone.md` and `todo.md`.
```

- [ ] **Step 6: Run focused console and CLI tests**

Run:

```powershell
python -m unittest tests.test_console_state tests.test_console_jobs tests.test_console_proposals tests.test_console_context tests.test_console_server tests.test_cli -v
```

Expected: PASS.

- [ ] **Step 7: Run full verification**

Run:

```powershell
python -m unittest discover -s tests -v
python -m py_compile wqb\console_state.py wqb\console_jobs.py wqb\console_proposals.py wqb\console_context.py wqb\console_server.py wqb\cli.py
git diff --check
```

Expected:

- unittest reports `OK`;
- `py_compile` exits 0;
- `git diff --check` exits 0.

- [ ] **Step 8: Commit CLI and docs**

Run:

```powershell
git add BrainWorkflow/wqb/cli.py BrainWorkflow/tests/test_cli.py BrainWorkflow/README.md
git commit -m "add workflow console cli"
```

Expected: commit created.

---

## Final Manual Smoke Check

After all tasks are implemented, run:

```powershell
cd C:\Users\oytl\Desktop\pyproject\brain\skills-and-workflows\BrainWorkflow
python -m wqb.cli launch-console --knowledge-root C:\Users\oytl\Desktop\pyproject\brain\knowledge --run-dir C:\Users\oytl\Desktop\pyproject\brain\runs --console-port 8765
```

Open:

```text
http://127.0.0.1:8765
```

Expected:

- Dashboard shows readiness, freshness, option cards, jobs, milestone, and proposal counts.
- Proposals page renders a proposal form.
- Plan-only readiness action creates a job under `C:\Users\oytl\Desktop\pyproject\brain\runs\console_jobs`.
- The job summary includes a recovery section.
- `milestone.md` and `todo.md` receive a console job update.

---

## Self-Review

- Spec coverage: Dashboard is covered by Tasks 1 and 5; Research Control by Tasks 6 and 7; Progress Board by Tasks 1, 2, and 5; Knowledge Control by Task 6; Workflow Proposal Inbox by Tasks 3 and 6; Context Guard by Task 4; CLI startup by Task 7.
- Red-flag scan: search this plan for incomplete-work markers and vague implementation instructions; no matches should remain.
- Type consistency: `ConsolePaths`, `ConsoleJob`, `load_console_state`, `build_cli_command`, `create_job`, `run_job`, `create_proposal_from_form`, `record_console_job_context`, `render_dashboard`, `render_proposals`, `build_action_command`, `make_console_server`, and `run_console` are defined before downstream tasks consume them.
