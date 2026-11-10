# BrainWorkflow Orchestrator State Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Orchestrator-owned Workflow State layer that makes BrainWorkflow resumable without Codex chat context while preserving the existing research workflow.

**Architecture:** Add a thin Orchestrator and focused support modules around the existing planner, scheduler, generator, simulator, checker, benchmark, repair, and recorder modules. The Orchestrator is the only owner of official run state transitions; existing research modules remain independently testable tools. Knowledge workflow contracts are written into the Obsidian vault so the long-term workflow is not stored only in code or conversation history.

**Tech Stack:** Python standard library, dataclasses, JSON/JSONL, Markdown, `unittest`, existing `wqb` modules, root Obsidian vault at `C:\Users\oytl\Desktop\pyproject\brain\knowledge`.

## Global Constraints

- Do not change the research framework.
- Do not rewrite the existing generator, simulator, checker, benchmark, repair, planner, data ledger, template library, or API client.
- Do not make Codex conversation memory part of workflow state.
- Do not automatically submit alphas.
- Do not run full knowledge recapture during normal research startup.
- Do not hide live API use behind plan-only commands.
- Do not make the UI the source of truth. The UI must read and control the Orchestrator.
- Only the Orchestrator may write official `run_state.json`.
- Use `unittest`; run focused tests first and full discovery before final completion.
- Keep API credentials outside tracked files and run artifacts.
- Keep root `milestone.md` current before any interruption or usage-limit stop.

---

## File Structure

- Create `wqb/workflow_contract.py`
  - Owns workflow vocabulary constants, contract page rendering, and contract consistency helpers.
- Create `tests/test_workflow_contract.py`
  - Verifies contract constants and contract page generation.
- Create or update root vault files:
  - `C:\Users\oytl\Desktop\pyproject\brain\knowledge\wiki\60_workflows\long_term_workflow_contract.md`
  - `C:\Users\oytl\Desktop\pyproject\brain\knowledge\wiki\60_workflows\workflow_state_machine.md`
  - `C:\Users\oytl\Desktop\pyproject\brain\knowledge\wiki\60_workflows\research_record_schema.md`
  - `C:\Users\oytl\Desktop\pyproject\brain\knowledge\wiki\60_workflows\candidate_approval_policy.md`
- Create `wqb/workflow_state.py`
  - Owns state dataclasses, atomic state writes, active-run pointer, legal transition checks, and consistency diagnostics.
- Create `tests/test_workflow_state.py`
  - Verifies state creation, legal and illegal transitions, atomic writes, active-run recovery, and contradiction detection.
- Create `wqb/workflow_events.py`
  - Owns append-only workflow event records and event timeline loading.
- Create `tests/test_workflow_events.py`
  - Verifies append-only event behavior and event-driven state evidence.
- Create `wqb/research_record.py`
  - Owns machine-readable and Markdown research record creation, update, rendering, and raw vault sync.
- Create `tests/test_research_record.py`
  - Verifies failed alpha summaries, repair version history, candidate decisions, Markdown rendering, and idempotent sync.
- Create `wqb/candidate_queue.py`
  - Owns candidate approvals, approval invalidation, queue deduplication, and status updates.
- Create `tests/test_candidate_queue.py`
  - Verifies exact hash/version binding, duplicate prevention, invalidation, and queue status changes.
- Create `wqb/orchestrator.py`
  - Owns `start`, `status`, `resume`, `abort`, `continue`, approval, and queue operations.
- Create `tests/test_orchestrator.py`
  - Verifies plan-only start, status, resume idempotency, abort, candidate gate pause, approval, and queue behavior using fake adapters.
- Create `wqb/workflow_stage_adapters.py`
  - Provides narrow adapter functions from Orchestrator to existing scheduler, batch, recovery, triage, and repair functions.
- Create `tests/test_workflow_stage_adapters.py`
  - Verifies adapters call existing modules with expected inputs and do not write official state.
- Modify `wqb/cli.py`
  - Adds high-level workflow commands that call the Orchestrator.
- Modify `tests/test_cli.py`
  - Adds parse and dispatch coverage for new workflow commands.
- Modify `wqb/console_state.py`
  - Reads `active_run.json`, `run_state.json`, workflow events, Research Record summaries, and approved queue summaries.
- Modify `tests/test_console_state.py`
  - Adds state-backed dashboard coverage.
- Modify `README.md`
  - Explains Orchestrator-first operation and legacy low-level command role.
- Modify `docs/superpowers/specs/2026-07-12-workflow-console-design.md`
  - Clarifies that the UI controls Orchestrator commands after this slice.
- Modify `docs/superpowers/plans/2026-07-12-workflow-console-implementation.md`
  - Marks Task 2+ as depending on Orchestrator command surfaces.

---

### Task 1: Workflow Contract Pages And Constants

**Files:**
- Create: `wqb/workflow_contract.py`
- Create: `tests/test_workflow_contract.py`
- Create: `C:\Users\oytl\Desktop\pyproject\brain\knowledge\wiki\60_workflows\long_term_workflow_contract.md`
- Create: `C:\Users\oytl\Desktop\pyproject\brain\knowledge\wiki\60_workflows\workflow_state_machine.md`
- Create: `C:\Users\oytl\Desktop\pyproject\brain\knowledge\wiki\60_workflows\research_record_schema.md`
- Create: `C:\Users\oytl\Desktop\pyproject\brain\knowledge\wiki\60_workflows\candidate_approval_policy.md`

**Interfaces:**
- Produces: `RUN_STATUSES: tuple[str, ...]`
- Produces: `STAGE_NAMES: tuple[str, ...]`
- Produces: `STAGE_STATUSES: tuple[str, ...]`
- Produces: `LEGAL_RUN_TRANSITIONS: dict[str, tuple[str, ...]]`
- Produces: `APPROVAL_REQUIRED_FIELDS: tuple[str, ...]`
- Produces: `RESEARCH_RECORD_SECTIONS: tuple[str, ...]`
- Produces: `render_workflow_contract_pages() -> dict[str, str]`
- Produces: `write_workflow_contract_pages(output_root: str | Path) -> list[Path]`

- [ ] **Step 1: Write failing contract tests**

Create `tests/test_workflow_contract.py`:

```python
import tempfile
import unittest
from pathlib import Path

from wqb.workflow_contract import (
    APPROVAL_REQUIRED_FIELDS,
    LEGAL_RUN_TRANSITIONS,
    RESEARCH_RECORD_SECTIONS,
    RUN_STATUSES,
    STAGE_NAMES,
    STAGE_STATUSES,
    render_workflow_contract_pages,
    write_workflow_contract_pages,
)


class WorkflowContractTests(unittest.TestCase):
    def test_contract_terms_match_approved_orchestrator_design(self):
        self.assertEqual(
            RUN_STATUSES,
            (
                "created",
                "running",
                "waiting_for_user",
                "paused",
                "completed",
                "completed_with_warnings",
                "failed",
                "aborted",
            ),
        )
        self.assertIn("candidate_gate", STAGE_NAMES)
        self.assertIn("research_record_sync", STAGE_NAMES)
        self.assertIn("skipped", STAGE_STATUSES)
        self.assertEqual(LEGAL_RUN_TRANSITIONS["created"], ("running", "aborted"))
        self.assertIn("expression_hash", APPROVAL_REQUIRED_FIELDS)
        self.assertIn("repair", RESEARCH_RECORD_SECTIONS)

    def test_rendered_contract_pages_include_workflow_and_approval_rules(self):
        pages = render_workflow_contract_pages()

        self.assertEqual(
            sorted(pages),
            [
                "candidate_approval_policy.md",
                "long_term_workflow_contract.md",
                "research_record_schema.md",
                "workflow_state_machine.md",
            ],
        )
        self.assertIn("Knowledge Maintenance -> Research Planner", pages["long_term_workflow_contract.md"])
        self.assertIn("Only the Orchestrator may write", pages["workflow_state_machine.md"])
        self.assertIn("candidate_id", pages["candidate_approval_policy.md"])
        self.assertIn("near-miss", pages["research_record_schema.md"])

    def test_write_workflow_contract_pages_writes_markdown_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = write_workflow_contract_pages(Path(tmp))

            names = sorted(path.name for path in paths)
            state_page = Path(tmp) / "workflow_state_machine.md"
            state_exists = state_page.exists()

        self.assertEqual(names, sorted(render_workflow_contract_pages()))
        self.assertTrue(state_exists)
```

- [ ] **Step 2: Run contract tests and verify failure**

Run:

```powershell
Set-Location 'C:\Users\oytl\Desktop\pyproject\brain\skills-and-workflows\BrainWorkflow'
python -m unittest tests.test_workflow_contract -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'wqb.workflow_contract'`.

- [ ] **Step 3: Implement workflow contract module**

Create `wqb/workflow_contract.py`:

```python
from __future__ import annotations

from pathlib import Path


RUN_STATUSES = (
    "created",
    "running",
    "waiting_for_user",
    "paused",
    "completed",
    "completed_with_warnings",
    "failed",
    "aborted",
)

STAGE_NAMES = (
    "objective_selected",
    "schedule",
    "scout_seed",
    "batch_generation",
    "backtest",
    "triage",
    "repair",
    "candidate_gate",
    "user_approval",
    "approved_queue",
    "research_record_sync",
    "complete",
)

STAGE_STATUSES = (
    "not_started",
    "running",
    "completed",
    "paused",
    "failed",
    "skipped",
)

LEGAL_RUN_TRANSITIONS = {
    "created": ("running", "aborted"),
    "running": ("waiting_for_user", "paused", "completed", "completed_with_warnings", "failed", "aborted"),
    "waiting_for_user": ("running", "aborted"),
    "paused": ("running", "failed", "aborted"),
    "failed": ("aborted",),
    "completed": (),
    "completed_with_warnings": (),
    "aborted": (),
}

APPROVAL_REQUIRED_FIELDS = (
    "candidate_id",
    "platform_alpha_id",
    "version",
    "expression_hash",
    "approved_at",
    "approved_by",
    "source_run_id",
)

RESEARCH_RECORD_SECTIONS = (
    "backtest",
    "triage",
    "repair",
    "candidate_gate",
    "user_approval",
    "approved_queue",
    "manual_submission_status",
)


def render_workflow_contract_pages() -> dict[str, str]:
    """Input: none. Output: Markdown pages. Render durable workflow contract text."""
    workflow = "\n".join(
        [
            "# Long Term Workflow Contract",
            "",
            "Research flow: Knowledge Maintenance -> Research Planner -> Option Cards -> User Selects Objective -> Schedule Research -> Scout / Seed -> 30 Alpha Batch -> Multisim / Backtest -> Triage -> Repair Near-Miss -> Candidate Gate -> User Approval -> Approved Candidate Queue -> Research Record.",
            "",
            "Codex chat context is never a source of truth. A new session must recover from run files and the knowledge wiki.",
            "",
        ]
    )
    state = "\n".join(
        [
            "# Workflow State Machine",
            "",
            "Only the Orchestrator may write official run_state.json.",
            "",
            "Run statuses: " + ", ".join(RUN_STATUSES),
            "",
            "Stage names: " + ", ".join(STAGE_NAMES),
            "",
            "Stage statuses: " + ", ".join(STAGE_STATUSES),
            "",
        ]
    )
    record = "\n".join(
        [
            "# Research Record Schema",
            "",
            "The Research Record stores backtest, triage, repair, candidate gate, user approval, approved queue, and manual submission status.",
            "",
            "Obvious failures are compact summaries. Near-miss and repair branches keep original expression, repair hypothesis, version history, checks, and final judgment.",
            "",
        ]
    )
    approval = "\n".join(
        [
            "# Candidate Approval Policy",
            "",
            "Approval binds an exact candidate_id, platform_alpha_id, version, and expression_hash.",
            "",
            "A changed expression hash invalidates the old approval.",
            "",
            "Required fields: " + ", ".join(APPROVAL_REQUIRED_FIELDS),
            "",
        ]
    )
    return {
        "long_term_workflow_contract.md": workflow,
        "workflow_state_machine.md": state,
        "research_record_schema.md": record,
        "candidate_approval_policy.md": approval,
    }


def write_workflow_contract_pages(output_root: str | Path) -> list[Path]:
    """Input: output root. Output: written paths. Write workflow contract Markdown pages."""
    root = Path(output_root)
    root.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for filename, content in render_workflow_contract_pages().items():
        path = root / filename
        path.write_text(content, encoding="utf-8")
        written.append(path)
    return written
```

- [ ] **Step 4: Run focused contract tests**

Run:

```powershell
python -m unittest tests.test_workflow_contract -v
```

Expected: PASS with 3 tests.

- [ ] **Step 5: Write actual root knowledge contract pages**

Run:

```powershell
@'
from pathlib import Path
from wqb.workflow_contract import write_workflow_contract_pages
write_workflow_contract_pages(Path(r"C:\Users\oytl\Desktop\pyproject\brain\knowledge\wiki\60_workflows"))
'@ | python -
```

Expected: command exits 0 and writes the four Markdown files under the root knowledge vault.

- [ ] **Step 6: Commit Task 1**

Run:

```powershell
Set-Location 'C:\Users\oytl\Desktop\pyproject\brain\skills-and-workflows'
git add BrainWorkflow/wqb/workflow_contract.py BrainWorkflow/tests/test_workflow_contract.py
git commit -m "add workflow contract constants"
```

Expected: commit succeeds. Root knowledge Markdown files are outside the git repository and remain local vault artifacts.

---

### Task 2: Workflow State And Event Store

**Files:**
- Create: `wqb/workflow_state.py`
- Create: `wqb/workflow_events.py`
- Create: `tests/test_workflow_state.py`
- Create: `tests/test_workflow_events.py`

**Interfaces:**
- Consumes: constants from `wqb.workflow_contract`
- Produces: `WorkflowStageState`
- Produces: `WorkflowRunState`
- Produces: `WorkflowStateError`
- Produces: `create_initial_state(run_id: str, run_dir: str | Path, objective: str, created_at: str) -> WorkflowRunState`
- Produces: `transition_run_state(state: WorkflowRunState, new_status: str, reason: str = "") -> WorkflowRunState`
- Produces: `write_run_state(path: str | Path, state: WorkflowRunState) -> Path`
- Produces: `load_run_state(path: str | Path) -> WorkflowRunState`
- Produces: `write_active_run(run_root: str | Path, run_id: str, run_dir: str | Path) -> Path`
- Produces: `load_active_run(run_root: str | Path) -> dict[str, str]`
- Produces: `diagnose_state_consistency(run_dir: str | Path) -> list[str]`
- Produces: `WorkflowEvent`
- Produces: `append_workflow_event(run_dir: str | Path, event_type: str, payload: dict[str, object], occurred_at: str) -> Path`
- Produces: `read_workflow_events(run_dir: str | Path) -> list[WorkflowEvent]`

- [ ] **Step 1: Write failing workflow state tests**

Create `tests/test_workflow_state.py`:

```python
import tempfile
import unittest
from pathlib import Path

from wqb.workflow_state import (
    WorkflowStateError,
    create_initial_state,
    diagnose_state_consistency,
    load_active_run,
    load_run_state,
    transition_run_state,
    write_active_run,
    write_run_state,
)


class WorkflowStateTests(unittest.TestCase):
    def test_initial_state_contains_all_stages_and_next_action(self):
        state = create_initial_state("run1", "runs/run1", "Power Pool", "2026-07-12T00:00:00Z")

        self.assertEqual(state.run_id, "run1")
        self.assertEqual(state.status, "created")
        self.assertEqual(state.current_stage, "objective_selected")
        self.assertEqual(state.next_action, "workflow-start")
        self.assertEqual(state.stages["schedule"].status, "not_started")

    def test_transition_rejects_illegal_jump_from_created_to_completed(self):
        state = create_initial_state("run1", "runs/run1", "Power Pool", "2026-07-12T00:00:00Z")

        with self.assertRaisesRegex(WorkflowStateError, "illegal run status transition"):
            transition_run_state(state, "completed")

    def test_state_write_and_load_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "run_state.json"
            state = create_initial_state("run1", Path(tmp), "Power Pool", "2026-07-12T00:00:00Z")
            write_run_state(path, state)
            loaded = load_run_state(path)

        self.assertEqual(loaded.run_id, "run1")
        self.assertEqual(loaded.objective, "Power Pool")

    def test_active_run_pointer_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_active_run(tmp, "run1", Path(tmp) / "run1")
            active = load_active_run(tmp)

        self.assertEqual(active["run_id"], "run1")

    def test_consistency_detects_candidate_queue_without_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "approved_candidates.jsonl").write_text('{"candidate_id":"c1"}\n', encoding="utf-8")
            issues = diagnose_state_consistency(root)

        self.assertIn("candidate_queue_without_approval", issues)
```

- [ ] **Step 2: Write failing workflow event tests**

Create `tests/test_workflow_events.py`:

```python
import tempfile
import unittest
from pathlib import Path

from wqb.workflow_events import append_workflow_event, read_workflow_events


class WorkflowEventsTests(unittest.TestCase):
    def test_append_and_read_events_preserves_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            append_workflow_event(tmp, "workflow_created", {"run_id": "run1"}, "2026-07-12T00:00:00Z")
            append_workflow_event(tmp, "stage_started", {"stage": "schedule"}, "2026-07-12T00:01:00Z")
            events = read_workflow_events(tmp)

        self.assertEqual([event.event_type for event in events], ["workflow_created", "stage_started"])
        self.assertEqual(events[1].payload["stage"], "schedule")

    def test_invalid_event_rows_are_skipped_but_valid_rows_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "workflow_events.jsonl"
            path.write_text("not-json\n" + '{"event_type":"workflow_created","occurred_at":"t","payload":{}}\n', encoding="utf-8")
            events = read_workflow_events(tmp)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, "workflow_created")
```

- [ ] **Step 3: Run state and event tests and verify failure**

Run:

```powershell
python -m unittest tests.test_workflow_state tests.test_workflow_events -v
```

Expected: FAIL with missing `wqb.workflow_state` and `wqb.workflow_events`.

- [ ] **Step 4: Implement workflow events**

Create `wqb/workflow_events.py`:

```python
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any


EVENTS_FILENAME = "workflow_events.jsonl"


@dataclass(frozen=True)
class WorkflowEvent:
    event_type: str
    occurred_at: str
    payload: dict[str, Any]


def append_workflow_event(run_dir: str | Path, event_type: str, payload: dict[str, object], occurred_at: str) -> Path:
    """Input: run dir, event type, payload, timestamp. Output: event path. Append one workflow event."""
    root = Path(run_dir)
    root.mkdir(parents=True, exist_ok=True)
    path = root / EVENTS_FILENAME
    event = WorkflowEvent(event_type=str(event_type), occurred_at=str(occurred_at), payload=dict(payload))
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(asdict(event), ensure_ascii=False, sort_keys=True) + "\n")
    return path


def read_workflow_events(run_dir: str | Path) -> list[WorkflowEvent]:
    """Input: run dir. Output: workflow events. Read valid append-only events in file order."""
    path = Path(run_dir) / EVENTS_FILENAME
    if not path.exists():
        return []
    events: list[WorkflowEvent] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict) and "event_type" in row and "occurred_at" in row:
            events.append(
                WorkflowEvent(
                    event_type=str(row["event_type"]),
                    occurred_at=str(row["occurred_at"]),
                    payload=dict(row.get("payload", {})),
                )
            )
    return events
```

- [ ] **Step 5: Implement workflow state**

Create `wqb/workflow_state.py`:

```python
from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
import json
from pathlib import Path
from typing import Any

from wqb.workflow_contract import LEGAL_RUN_TRANSITIONS, RUN_STATUSES, STAGE_NAMES, STAGE_STATUSES


STATE_FILENAME = "run_state.json"
ACTIVE_RUN_FILENAME = "active_run.json"


class WorkflowStateError(ValueError):
    """Input: invalid state action. Output: exception. Signal illegal workflow state use."""


@dataclass(frozen=True)
class WorkflowStageState:
    name: str
    status: str = "not_started"
    started_at: str = ""
    completed_at: str = ""
    evidence_paths: list[str] = field(default_factory=list)
    blocker: str = ""


@dataclass(frozen=True)
class WorkflowRunState:
    run_id: str
    run_dir: str
    objective: str
    status: str
    current_stage: str
    last_completed_stage: str
    next_action: str
    pause_reason: str
    waiting_for_user: bool
    created_at: str
    updated_at: str
    budget_used: int
    research_record_synced: bool
    stages: dict[str, WorkflowStageState]


def create_initial_state(run_id: str, run_dir: str | Path, objective: str, created_at: str) -> WorkflowRunState:
    """Input: run id, run dir, objective, timestamp. Output: initial state. Create a formal run state."""
    stages = {name: WorkflowStageState(name=name) for name in STAGE_NAMES}
    return WorkflowRunState(
        run_id=str(run_id),
        run_dir=str(run_dir),
        objective=str(objective),
        status="created",
        current_stage="objective_selected",
        last_completed_stage="",
        next_action="workflow-start",
        pause_reason="",
        waiting_for_user=False,
        created_at=str(created_at),
        updated_at=str(created_at),
        budget_used=0,
        research_record_synced=False,
        stages=stages,
    )


def transition_run_state(state: WorkflowRunState, new_status: str, reason: str = "") -> WorkflowRunState:
    """Input: state and target status. Output: new state. Enforce legal run status transitions."""
    if new_status not in RUN_STATUSES:
        raise WorkflowStateError(f"unsupported run status: {new_status}")
    allowed = LEGAL_RUN_TRANSITIONS[state.status]
    if new_status not in allowed:
        raise WorkflowStateError(f"illegal run status transition: {state.status} -> {new_status}")
    return replace(
        state,
        status=new_status,
        pause_reason=reason if new_status in {"paused", "failed", "aborted"} else "",
        waiting_for_user=(new_status == "waiting_for_user"),
        next_action=_next_action_for_status(new_status),
    )


def _next_action_for_status(status: str) -> str:
    """Input: run status. Output: next action name. Map status to safe user command."""
    return {
        "created": "workflow-start",
        "running": "workflow-continue",
        "waiting_for_user": "workflow-approve-candidates",
        "paused": "workflow-resume",
        "failed": "workflow-abort",
        "completed": "",
        "completed_with_warnings": "",
        "aborted": "",
    }[status]


def _state_to_dict(state: WorkflowRunState) -> dict[str, Any]:
    """Input: state. Output: JSON-safe dict. Convert nested dataclasses."""
    row = asdict(state)
    row["stages"] = {name: asdict(stage) for name, stage in state.stages.items()}
    return row


def _state_from_dict(row: dict[str, Any]) -> WorkflowRunState:
    """Input: JSON row. Output: WorkflowRunState. Rebuild nested dataclasses."""
    stages = {
        name: WorkflowStageState(**dict(stage_row))
        for name, stage_row in dict(row.get("stages", {})).items()
        if name in STAGE_NAMES and isinstance(stage_row, dict)
    }
    for name in STAGE_NAMES:
        stages.setdefault(name, WorkflowStageState(name=name))
    return WorkflowRunState(
        run_id=str(row["run_id"]),
        run_dir=str(row["run_dir"]),
        objective=str(row.get("objective", "")),
        status=str(row["status"]),
        current_stage=str(row.get("current_stage", "objective_selected")),
        last_completed_stage=str(row.get("last_completed_stage", "")),
        next_action=str(row.get("next_action", "")),
        pause_reason=str(row.get("pause_reason", "")),
        waiting_for_user=bool(row.get("waiting_for_user", False)),
        created_at=str(row.get("created_at", "")),
        updated_at=str(row.get("updated_at", "")),
        budget_used=int(row.get("budget_used", 0)),
        research_record_synced=bool(row.get("research_record_synced", False)),
        stages=stages,
    )


def write_run_state(path: str | Path, state: WorkflowRunState) -> Path:
    """Input: path and state. Output: written path. Atomically write official run state."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(target.suffix + ".tmp")
    temp.write_text(json.dumps(_state_to_dict(state), ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    temp.replace(target)
    return target


def load_run_state(path: str | Path) -> WorkflowRunState:
    """Input: path. Output: WorkflowRunState. Load official run state from JSON."""
    return _state_from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


def write_active_run(run_root: str | Path, run_id: str, run_dir: str | Path) -> Path:
    """Input: run root, run id, run dir. Output: pointer path. Write active run index."""
    root = Path(run_root)
    root.mkdir(parents=True, exist_ok=True)
    path = root / ACTIVE_RUN_FILENAME
    path.write_text(json.dumps({"run_id": str(run_id), "run_dir": str(run_dir)}, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_active_run(run_root: str | Path) -> dict[str, str]:
    """Input: run root. Output: active run pointer. Load active run index or empty dict."""
    path = Path(run_root) / ACTIVE_RUN_FILENAME
    if not path.exists():
        return {}
    row = json.loads(path.read_text(encoding="utf-8"))
    return {"run_id": str(row.get("run_id", "")), "run_dir": str(row.get("run_dir", ""))}


def diagnose_state_consistency(run_dir: str | Path) -> list[str]:
    """Input: run dir. Output: issue codes. Detect contradictions between state and artifacts."""
    root = Path(run_dir)
    issues: list[str] = []
    if (root / "approved_candidates.jsonl").exists() and not (root / "approval.jsonl").exists():
        issues.append("candidate_queue_without_approval")
    if (root / STATE_FILENAME).exists():
        state = load_run_state(root / STATE_FILENAME)
        if state.status == "completed" and not (root / "research_record.json").exists():
            issues.append("completed_without_research_record")
    return issues
```

- [ ] **Step 6: Run focused state and event tests**

Run:

```powershell
python -m unittest tests.test_workflow_state tests.test_workflow_events -v
```

Expected: PASS with 7 tests.

- [ ] **Step 7: Commit Task 2**

Run:

```powershell
Set-Location 'C:\Users\oytl\Desktop\pyproject\brain\skills-and-workflows'
git add BrainWorkflow/wqb/workflow_state.py BrainWorkflow/wqb/workflow_events.py BrainWorkflow/tests/test_workflow_state.py BrainWorkflow/tests/test_workflow_events.py
git commit -m "add workflow state and events"
```

Expected: commit succeeds.

---

### Task 3: Research Record Store

**Files:**
- Create: `wqb/research_record.py`
- Create: `tests/test_research_record.py`

**Interfaces:**
- Produces: `ResearchRecord`
- Produces: `empty_research_record(run_id: str, objective: str) -> ResearchRecord`
- Produces: `record_alpha_result(record: ResearchRecord, alpha_row: dict[str, object]) -> ResearchRecord`
- Produces: `record_repair_version(record: ResearchRecord, candidate_id: str, version: int, expression_hash: str, hypothesis: str, result: dict[str, object]) -> ResearchRecord`
- Produces: `record_candidate_gate(record: ResearchRecord, candidate: dict[str, object], decision: str, reasons: list[str]) -> ResearchRecord`
- Produces: `write_research_record(path: str | Path, record: ResearchRecord) -> Path`
- Produces: `load_research_record(path: str | Path) -> ResearchRecord`
- Produces: `render_research_record_markdown(record: ResearchRecord) -> str`
- Produces: `sync_research_record_to_raw(record: ResearchRecord, raw_root: str | Path) -> Path`

- [ ] **Step 1: Write failing Research Record tests**

Create `tests/test_research_record.py`:

```python
import tempfile
import unittest
from pathlib import Path

from wqb.research_record import (
    empty_research_record,
    load_research_record,
    record_alpha_result,
    record_candidate_gate,
    record_repair_version,
    render_research_record_markdown,
    sync_research_record_to_raw,
    write_research_record,
)


class ResearchRecordTests(unittest.TestCase):
    def test_failed_alpha_summary_is_compact(self):
        record = empty_research_record("run1", "Power Pool")
        record = record_alpha_result(
            record,
            {
                "alpha_id": "a1",
                "expression_hash": "h1",
                "hard_pass": False,
                "benchmark_label": "weak_discard",
                "metrics": {"sharpe": 0.2},
                "failed": ["LOW_SHARPE"],
            },
        )

        self.assertEqual(record.failures[0]["alpha_id"], "a1")
        self.assertNotIn("expression", record.failures[0])

    def test_repair_version_history_is_idempotent_by_candidate_version_hash(self):
        record = empty_research_record("run1", "Power Pool")
        payload = {"sharpe": 1.3, "failed": []}
        record = record_repair_version(record, "c1", 1, "h1", "reduce turnover", payload)
        record = record_repair_version(record, "c1", 1, "h1", "reduce turnover", payload)

        self.assertEqual(len(record.repairs["c1"]), 1)

    def test_candidate_gate_and_markdown_rendering(self):
        record = empty_research_record("run1", "Power Pool")
        record = record_candidate_gate(record, {"candidate_id": "c1", "platform_alpha_id": "a1", "expression_hash": "h1"}, "ready_for_approval", ["hard checks passed"])
        markdown = render_research_record_markdown(record)

        self.assertIn("# Research Record", markdown)
        self.assertIn("ready_for_approval", markdown)

    def test_write_load_and_sync_to_raw(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            record = empty_research_record("run1", "Power Pool")
            path = write_research_record(root / "research_record.json", record)
            loaded = load_research_record(path)
            raw_path = sync_research_record_to_raw(loaded, root / "raw")

        self.assertEqual(loaded.run_id, "run1")
        self.assertTrue(raw_path.name == "research_record.md")
```

- [ ] **Step 2: Run Research Record tests and verify failure**

Run:

```powershell
python -m unittest tests.test_research_record -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'wqb.research_record'`.

- [ ] **Step 3: Implement Research Record module**

Create `wqb/research_record.py`:

```python
from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
import json
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ResearchRecord:
    run_id: str
    objective: str
    failures: list[dict[str, Any]] = field(default_factory=list)
    alpha_results: list[dict[str, Any]] = field(default_factory=list)
    repairs: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    candidate_gate: list[dict[str, Any]] = field(default_factory=list)
    approvals: list[dict[str, Any]] = field(default_factory=list)
    queue_updates: list[dict[str, Any]] = field(default_factory=list)


def empty_research_record(run_id: str, objective: str) -> ResearchRecord:
    """Input: run id and objective. Output: ResearchRecord. Create an empty research record."""
    return ResearchRecord(run_id=str(run_id), objective=str(objective))


def record_alpha_result(record: ResearchRecord, alpha_row: dict[str, object]) -> ResearchRecord:
    """Input: record and alpha row. Output: updated record. Store alpha result with compact failure summaries."""
    row = dict(alpha_row)
    results = [*record.alpha_results, row]
    failures = list(record.failures)
    if not bool(row.get("hard_pass", False)):
        failures.append(
            {
                "alpha_id": row.get("alpha_id", ""),
                "expression_hash": row.get("expression_hash", ""),
                "benchmark_label": row.get("benchmark_label", ""),
                "metrics": row.get("metrics", {}),
                "failed": row.get("failed", []),
            }
        )
    return replace(record, alpha_results=results, failures=failures)


def record_repair_version(
    record: ResearchRecord,
    candidate_id: str,
    version: int,
    expression_hash: str,
    hypothesis: str,
    result: dict[str, object],
) -> ResearchRecord:
    """Input: record and repair version. Output: updated record. Store one unique repair version."""
    repairs = {key: list(value) for key, value in record.repairs.items()}
    rows = repairs.setdefault(str(candidate_id), [])
    identity = (int(version), str(expression_hash))
    if not any((int(row["version"]), str(row["expression_hash"])) == identity for row in rows):
        rows.append(
            {
                "candidate_id": str(candidate_id),
                "version": int(version),
                "expression_hash": str(expression_hash),
                "hypothesis": str(hypothesis),
                "result": dict(result),
            }
        )
    return replace(record, repairs=repairs)


def record_candidate_gate(record: ResearchRecord, candidate: dict[str, object], decision: str, reasons: list[str]) -> ResearchRecord:
    """Input: record, candidate, decision, reasons. Output: updated record. Store one gate decision."""
    row = dict(candidate)
    row["decision"] = str(decision)
    row["reasons"] = [str(item) for item in reasons]
    return replace(record, candidate_gate=[*record.candidate_gate, row])


def write_research_record(path: str | Path, record: ResearchRecord) -> Path:
    """Input: path and record. Output: written path. Persist machine-readable research record."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(asdict(record), ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return target


def load_research_record(path: str | Path) -> ResearchRecord:
    """Input: path. Output: ResearchRecord. Load a machine-readable research record."""
    row = json.loads(Path(path).read_text(encoding="utf-8"))
    return ResearchRecord(**row)


def render_research_record_markdown(record: ResearchRecord) -> str:
    """Input: record. Output: Markdown. Render research findings for raw knowledge sync."""
    lines = [
        "# Research Record",
        "",
        f"- Run ID: `{record.run_id}`",
        f"- Objective: {record.objective}",
        "",
        "## Failures",
    ]
    for failure in record.failures:
        lines.append(f"- `{failure.get('alpha_id', '')}` `{failure.get('expression_hash', '')}` {failure.get('benchmark_label', '')}")
    lines.extend(["", "## Repair", ""])
    for candidate_id, rows in record.repairs.items():
        lines.append(f"### {candidate_id}")
        for row in rows:
            lines.append(f"- version `{row['version']}` hash `{row['expression_hash']}` hypothesis: {row['hypothesis']}")
    lines.extend(["", "## Candidate Gate", ""])
    for row in record.candidate_gate:
        lines.append(f"- `{row.get('candidate_id', '')}` {row.get('decision', '')}: {', '.join(row.get('reasons', []))}")
    return "\n".join(lines) + "\n"


def sync_research_record_to_raw(record: ResearchRecord, raw_root: str | Path) -> Path:
    """Input: record and raw root. Output: Markdown path. Write raw research record into knowledge raw."""
    path = Path(raw_root) / "research" / "runs" / record.run_id / "research_record.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_research_record_markdown(record), encoding="utf-8")
    return path
```

- [ ] **Step 4: Run focused Research Record tests**

Run:

```powershell
python -m unittest tests.test_research_record -v
```

Expected: PASS with 4 tests.

- [ ] **Step 5: Commit Task 3**

Run:

```powershell
Set-Location 'C:\Users\oytl\Desktop\pyproject\brain\skills-and-workflows'
git add BrainWorkflow/wqb/research_record.py BrainWorkflow/tests/test_research_record.py
git commit -m "add research record store"
```

Expected: commit succeeds.

---

### Task 4: Candidate Approval And Queue

**Files:**
- Create: `wqb/candidate_queue.py`
- Create: `tests/test_candidate_queue.py`

**Interfaces:**
- Consumes: `APPROVAL_REQUIRED_FIELDS` from `wqb.workflow_contract`
- Produces: `approve_candidate(run_dir: str | Path, candidate: dict[str, object], approved_at: str, approved_by: str) -> dict[str, object]`
- Produces: `load_approvals(run_dir: str | Path) -> list[dict[str, object]]`
- Produces: `queue_approved_candidate(run_dir: str | Path, approval: dict[str, object]) -> dict[str, object]`
- Produces: `load_approved_queue(run_root_or_run_dir: str | Path) -> list[dict[str, object]]`
- Produces: `update_candidate_queue_status(run_dir: str | Path, candidate_id: str, version: int, expression_hash: str, status: str, updated_at: str) -> dict[str, object]`
- Produces: `approval_matches_candidate(approval: dict[str, object], candidate: dict[str, object]) -> bool`

- [ ] **Step 1: Write failing candidate queue tests**

Create `tests/test_candidate_queue.py`:

```python
import tempfile
import unittest

from wqb.candidate_queue import (
    approval_matches_candidate,
    approve_candidate,
    load_approved_queue,
    load_approvals,
    queue_approved_candidate,
    update_candidate_queue_status,
)


class CandidateQueueTests(unittest.TestCase):
    def candidate(self):
        return {
            "candidate_id": "c1",
            "platform_alpha_id": "a1",
            "version": 1,
            "expression_hash": "h1",
            "sharpe": 1.4,
        }

    def test_approval_binds_exact_candidate_version_and_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            approval = approve_candidate(tmp, self.candidate(), "2026-07-12T00:00:00Z", "user")
            loaded = load_approvals(tmp)

        self.assertEqual(approval["expression_hash"], "h1")
        self.assertEqual(loaded[0]["candidate_id"], "c1")
        self.assertTrue(approval_matches_candidate(approval, self.candidate()))
        changed = dict(self.candidate(), expression_hash="h2")
        self.assertFalse(approval_matches_candidate(approval, changed))

    def test_queue_deduplicates_same_candidate_version_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            approval = approve_candidate(tmp, self.candidate(), "2026-07-12T00:00:00Z", "user")
            queue_approved_candidate(tmp, approval)
            queue_approved_candidate(tmp, approval)
            rows = load_approved_queue(tmp)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "queued")

    def test_queue_status_update_requires_matching_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            approval = approve_candidate(tmp, self.candidate(), "2026-07-12T00:00:00Z", "user")
            queue_approved_candidate(tmp, approval)
            updated = update_candidate_queue_status(tmp, "c1", 1, "h1", "manually_submitted", "2026-07-12T01:00:00Z")
            rows = load_approved_queue(tmp)

        self.assertEqual(updated["status"], "manually_submitted")
        self.assertEqual(rows[0]["status"], "manually_submitted")
```

- [ ] **Step 2: Run candidate queue tests and verify failure**

Run:

```powershell
python -m unittest tests.test_candidate_queue -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'wqb.candidate_queue'`.

- [ ] **Step 3: Implement candidate queue module**

Create `wqb/candidate_queue.py`:

```python
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


APPROVAL_FILENAME = "approval.jsonl"
QUEUE_FILENAME = "approved_candidates.jsonl"
QUEUE_STATUSES = {"queued", "manually_submitted", "api_submitted", "skipped", "invalidated"}


def _append_jsonl(path: Path, row: dict[str, Any]) -> None:
    """Input: path and row. Output: none. Append one JSONL row."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Input: path. Output: rows. Read valid JSONL rows."""
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def approve_candidate(run_dir: str | Path, candidate: dict[str, object], approved_at: str, approved_by: str) -> dict[str, object]:
    """Input: run dir, candidate, approval metadata. Output: approval row. Persist exact candidate approval."""
    approval = {
        "candidate_id": str(candidate["candidate_id"]),
        "platform_alpha_id": str(candidate["platform_alpha_id"]),
        "version": int(candidate["version"]),
        "expression_hash": str(candidate["expression_hash"]),
        "approved_at": str(approved_at),
        "approved_by": str(approved_by),
        "source_run_id": str(candidate.get("source_run_id", "")),
    }
    _append_jsonl(Path(run_dir) / APPROVAL_FILENAME, approval)
    return approval


def load_approvals(run_dir: str | Path) -> list[dict[str, object]]:
    """Input: run dir. Output: approvals. Load candidate approval rows."""
    return _read_jsonl(Path(run_dir) / APPROVAL_FILENAME)


def approval_matches_candidate(approval: dict[str, object], candidate: dict[str, object]) -> bool:
    """Input: approval and candidate. Output: bool. Check exact version and hash binding."""
    return (
        str(approval.get("candidate_id", "")) == str(candidate.get("candidate_id", ""))
        and int(approval.get("version", -1)) == int(candidate.get("version", -2))
        and str(approval.get("expression_hash", "")) == str(candidate.get("expression_hash", ""))
    )


def _queue_identity(row: dict[str, object]) -> tuple[str, int, str]:
    """Input: queue-like row. Output: identity tuple. Build dedupe key."""
    return (str(row.get("candidate_id", "")), int(row.get("version", 0)), str(row.get("expression_hash", "")))


def queue_approved_candidate(run_dir: str | Path, approval: dict[str, object]) -> dict[str, object]:
    """Input: run dir and approval. Output: queue row. Add one approved candidate if not already queued."""
    path = Path(run_dir) / QUEUE_FILENAME
    rows = _read_jsonl(path)
    identity = _queue_identity(approval)
    for row in rows:
        if _queue_identity(row) == identity:
            return row
    queued = dict(approval)
    queued["status"] = "queued"
    _append_jsonl(path, queued)
    return queued


def load_approved_queue(run_root_or_run_dir: str | Path) -> list[dict[str, object]]:
    """Input: run root or run dir. Output: queue rows. Load approved candidate queue."""
    root = Path(run_root_or_run_dir)
    direct = root / QUEUE_FILENAME
    if direct.exists():
        return _read_jsonl(direct)
    rows: list[dict[str, object]] = []
    for path in root.glob(f"*/{QUEUE_FILENAME}"):
        rows.extend(_read_jsonl(path))
    return rows


def update_candidate_queue_status(
    run_dir: str | Path,
    candidate_id: str,
    version: int,
    expression_hash: str,
    status: str,
    updated_at: str,
) -> dict[str, object]:
    """Input: identity and status. Output: updated row. Rewrite queue with one status update."""
    if status not in QUEUE_STATUSES:
        raise ValueError(f"unsupported queue status: {status}")
    path = Path(run_dir) / QUEUE_FILENAME
    rows = _read_jsonl(path)
    target = (str(candidate_id), int(version), str(expression_hash))
    updated: dict[str, object] | None = None
    for row in rows:
        if _queue_identity(row) == target:
            row["status"] = status
            row["updated_at"] = str(updated_at)
            updated = row
            break
    if updated is None:
        raise ValueError("candidate queue entry not found")
    path.write_text("", encoding="utf-8")
    for row in rows:
        _append_jsonl(path, row)
    return updated
```

- [ ] **Step 4: Run focused candidate queue tests**

Run:

```powershell
python -m unittest tests.test_candidate_queue -v
```

Expected: PASS with 3 tests.

- [ ] **Step 5: Commit Task 4**

Run:

```powershell
Set-Location 'C:\Users\oytl\Desktop\pyproject\brain\skills-and-workflows'
git add BrainWorkflow/wqb/candidate_queue.py BrainWorkflow/tests/test_candidate_queue.py
git commit -m "add candidate approval queue"
```

Expected: commit succeeds.

---

### Task 5: Orchestrator Core Lifecycle

**Files:**
- Create: `wqb/orchestrator.py`
- Create: `tests/test_orchestrator.py`

**Interfaces:**
- Consumes: `create_initial_state`, `write_run_state`, `load_run_state`, `write_active_run`, `append_workflow_event`
- Produces: `OrchestratorPaths`
- Produces: `WorkflowOrchestrator`
- Produces: `WorkflowOrchestrator.start(objective: str, selected_option_id: str, created_at: str) -> dict[str, object]`
- Produces: `WorkflowOrchestrator.status() -> dict[str, object]`
- Produces: `WorkflowOrchestrator.resume(resumed_at: str) -> dict[str, object]`
- Produces: `WorkflowOrchestrator.abort(reason: str, aborted_at: str) -> dict[str, object]`

- [ ] **Step 1: Write failing Orchestrator lifecycle tests**

Create `tests/test_orchestrator.py`:

```python
import tempfile
import unittest
from pathlib import Path

from wqb.orchestrator import OrchestratorPaths, WorkflowOrchestrator
from wqb.workflow_state import load_active_run, load_run_state


class WorkflowOrchestratorTests(unittest.TestCase):
    def paths(self, root: Path) -> OrchestratorPaths:
        return OrchestratorPaths(project_root=root, workflow_root=root / "BrainWorkflow", knowledge_root=root / "knowledge", run_root=root / "runs")

    def test_start_creates_manifest_state_events_and_active_pointer(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orchestrator = WorkflowOrchestrator(self.paths(root))
            result = orchestrator.start("Power Pool", "option-1", "2026-07-12T00:00:00Z")
            state = load_run_state(Path(result["run_dir"]) / "run_state.json")
            active = load_active_run(root / "runs")

        self.assertEqual(result["status"], "created")
        self.assertEqual(state.objective, "Power Pool")
        self.assertEqual(active["run_id"], result["run_id"])

    def test_status_reports_next_action_without_chat_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orchestrator = WorkflowOrchestrator(self.paths(root))
            orchestrator.start("Power Pool", "option-1", "2026-07-12T00:00:00Z")
            status = orchestrator.status()

        self.assertEqual(status["next_action"], "workflow-start")
        self.assertEqual(status["current_stage"], "objective_selected")

    def test_abort_releases_active_run_and_preserves_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orchestrator = WorkflowOrchestrator(self.paths(root))
            started = orchestrator.start("Power Pool", "option-1", "2026-07-12T00:00:00Z")
            result = orchestrator.abort("user changed objective", "2026-07-12T00:05:00Z")
            state = load_run_state(Path(started["run_dir"]) / "run_state.json")
            active = load_active_run(root / "runs")

        self.assertEqual(result["status"], "aborted")
        self.assertEqual(state.status, "aborted")
        self.assertEqual(active, {})
```

- [ ] **Step 2: Run Orchestrator tests and verify failure**

Run:

```powershell
python -m unittest tests.test_orchestrator -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'wqb.orchestrator'`.

- [ ] **Step 3: Implement Orchestrator core**

Create `wqb/orchestrator.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from uuid import uuid4

from wqb.workflow_events import append_workflow_event, read_workflow_events
from wqb.workflow_state import (
    ACTIVE_RUN_FILENAME,
    STATE_FILENAME,
    WorkflowRunState,
    create_initial_state,
    load_active_run,
    load_run_state,
    transition_run_state,
    write_active_run,
    write_run_state,
)


@dataclass(frozen=True)
class OrchestratorPaths:
    project_root: Path
    workflow_root: Path
    knowledge_root: Path
    run_root: Path


class WorkflowOrchestrator:
    def __init__(self, paths: OrchestratorPaths) -> None:
        """Input: OrchestratorPaths. Output: instance. Create a workflow controller over durable files."""
        self.paths = paths

    def start(self, objective: str, selected_option_id: str, created_at: str) -> dict[str, object]:
        """Input: objective, option id, timestamp. Output: start summary. Create a formal workflow run."""
        self.paths.run_root.mkdir(parents=True, exist_ok=True)
        run_id = f"{created_at.replace(':', '').replace('-', '').replace('+', 'plus')}-{uuid4().hex[:8]}"
        run_dir = self.paths.run_root / run_id
        run_dir.mkdir(parents=True, exist_ok=False)
        manifest = {
            "run_id": run_id,
            "objective": str(objective),
            "selected_option_id": str(selected_option_id),
            "created_at": str(created_at),
            "knowledge_root": str(self.paths.knowledge_root),
        }
        (run_dir / "run_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        state = create_initial_state(run_id, run_dir, objective, created_at)
        write_run_state(run_dir / STATE_FILENAME, state)
        append_workflow_event(run_dir, "workflow_created", manifest, created_at)
        write_active_run(self.paths.run_root, run_id, run_dir)
        return self._summary(state)

    def status(self) -> dict[str, object]:
        """Input: none. Output: status summary. Read active run state without chat context."""
        state = self._active_state()
        if state is None:
            return {"active": False, "run_id": "", "status": "none", "next_action": "workflow-start"}
        summary = self._summary(state)
        summary["active"] = True
        summary["event_count"] = len(read_workflow_events(state.run_dir))
        return summary

    def resume(self, resumed_at: str) -> dict[str, object]:
        """Input: timestamp. Output: status summary. Resume a paused run without repeating completed work."""
        state = self._active_state()
        if state is None:
            return {"active": False, "status": "none", "next_action": "workflow-start"}
        if state.status == "paused":
            state = transition_run_state(state, "running", "")
            write_run_state(Path(state.run_dir) / STATE_FILENAME, state)
            append_workflow_event(state.run_dir, "workflow_resumed", {"run_id": state.run_id}, resumed_at)
        return self._summary(state)

    def abort(self, reason: str, aborted_at: str) -> dict[str, object]:
        """Input: reason and timestamp. Output: status summary. Abort active run and release pointer."""
        state = self._active_state()
        if state is None:
            return {"active": False, "status": "none"}
        if state.status != "aborted":
            state = transition_run_state(state, "aborted", reason)
            write_run_state(Path(state.run_dir) / STATE_FILENAME, state)
            append_workflow_event(state.run_dir, "workflow_aborted", {"run_id": state.run_id, "reason": reason}, aborted_at)
        active_path = self.paths.run_root / ACTIVE_RUN_FILENAME
        if active_path.exists():
            active_path.unlink()
        return self._summary(state)

    def _active_state(self) -> WorkflowRunState | None:
        """Input: none. Output: active state or none. Load current active run state."""
        active = load_active_run(self.paths.run_root)
        if not active:
            return None
        return load_run_state(Path(active["run_dir"]) / STATE_FILENAME)

    def _summary(self, state: WorkflowRunState) -> dict[str, object]:
        """Input: state. Output: summary dict. Present stable Orchestrator status."""
        return {
            "run_id": state.run_id,
            "run_dir": state.run_dir,
            "objective": state.objective,
            "status": state.status,
            "current_stage": state.current_stage,
            "next_action": state.next_action,
            "waiting_for_user": state.waiting_for_user,
        }
```

- [ ] **Step 4: Adjust `write_active_run` to support clearing active pointer**

Modify `wqb/workflow_state.py` by adding:

```python
def clear_active_run(run_root: str | Path) -> None:
    """Input: run root. Output: none. Remove active run pointer when a workflow ends."""
    path = Path(run_root) / ACTIVE_RUN_FILENAME
    if path.exists():
        path.unlink()
```

Then update `wqb/orchestrator.py` to import and call `clear_active_run` instead of deleting the pointer inline.

- [ ] **Step 5: Run focused Orchestrator tests**

Run:

```powershell
python -m unittest tests.test_orchestrator -v
```

Expected: PASS with 3 tests.

- [ ] **Step 6: Run state/event/Orchestrator regression tests**

Run:

```powershell
python -m unittest tests.test_workflow_state tests.test_workflow_events tests.test_orchestrator -v
```

Expected: PASS.

- [ ] **Step 7: Commit Task 5**

Run:

```powershell
Set-Location 'C:\Users\oytl\Desktop\pyproject\brain\skills-and-workflows'
git add BrainWorkflow/wqb/orchestrator.py BrainWorkflow/wqb/workflow_state.py BrainWorkflow/tests/test_orchestrator.py BrainWorkflow/tests/test_workflow_state.py
git commit -m "add workflow orchestrator lifecycle"
```

Expected: commit succeeds.

---

### Task 6: Stage Adapters And Plan-Only Orchestration

**Files:**
- Create: `wqb/workflow_stage_adapters.py`
- Create: `tests/test_workflow_stage_adapters.py`
- Modify: `wqb/orchestrator.py`
- Modify: `tests/test_orchestrator.py`

**Interfaces:**
- Consumes: existing `build_research_schedule`, `write_research_schedule`, `run_readiness`, `RunRecorder`
- Produces: `schedule_research_stage(knowledge_root: str | Path, run_dir: str | Path, selected_option_id: str) -> dict[str, object]`
- Produces: `summarize_stage_artifacts(run_dir: str | Path) -> dict[str, object]`
- Produces: `WorkflowOrchestrator.continue_once(now: str) -> dict[str, object]`

- [ ] **Step 1: Write failing stage adapter tests**

Create `tests/test_workflow_stage_adapters.py`:

```python
import json
import tempfile
import unittest
from pathlib import Path

from wqb.workflow_stage_adapters import schedule_research_stage, summarize_stage_artifacts


class WorkflowStageAdaptersTests(unittest.TestCase):
    def test_schedule_research_stage_writes_stage_artifact_from_option_card(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            knowledge = root / "knowledge"
            decisions = knowledge / "wiki" / "70_decisions"
            decisions.mkdir(parents=True)
            (decisions / "research_option_cards.jsonl").write_text(
                json.dumps({"option_id": "option-1", "title": "Power Pool", "scope": "USA D1", "score": {"total": 10}}) + "\n",
                encoding="utf-8",
            )
            run_dir = root / "runs" / "run1"
            summary = schedule_research_stage(knowledge, run_dir, "option-1")

        self.assertEqual(summary["stage"], "schedule")
        self.assertTrue((run_dir / "stages" / "schedule" / "research_schedule.json").exists())

    def test_summarize_stage_artifacts_counts_jsonl_and_candidates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "all_alphas.jsonl").write_text('{"alpha_id":"a1"}\n', encoding="utf-8")
            (root / "candidates.csv").write_text("alpha_id,expression_hash\nA,h\n", encoding="utf-8")
            summary = summarize_stage_artifacts(root)

        self.assertEqual(summary["alpha_result_count"], 1)
        self.assertEqual(summary["candidate_file_exists"], True)
```

- [ ] **Step 2: Run adapter tests and verify failure**

Run:

```powershell
python -m unittest tests.test_workflow_stage_adapters -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'wqb.workflow_stage_adapters'`.

- [ ] **Step 3: Implement stage adapters**

Create `wqb/workflow_stage_adapters.py`:

```python
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Input: JSONL path. Output: rows. Read valid JSONL rows."""
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def schedule_research_stage(knowledge_root: str | Path, run_dir: str | Path, selected_option_id: str) -> dict[str, object]:
    """Input: knowledge root, run dir, option id. Output: schedule summary. Write a plan-only schedule artifact."""
    knowledge = Path(knowledge_root)
    options_path = knowledge / "wiki" / "70_decisions" / "research_option_cards.jsonl"
    options = _read_jsonl(options_path)
    selected = next((row for row in options if str(row.get("option_id", "")) == str(selected_option_id)), None)
    if selected is None and options:
        selected = options[0]
    if selected is None:
        raise ValueError("no research option cards found")
    stage_dir = Path(run_dir) / "stages" / "schedule"
    stage_dir.mkdir(parents=True, exist_ok=True)
    schedule = {
        "stage": "schedule",
        "selected_option_id": str(selected_option_id),
        "title": str(selected.get("title", "")),
        "scope": str(selected.get("scope", "")),
    }
    (stage_dir / "research_schedule.json").write_text(json.dumps(schedule, ensure_ascii=False, indent=2), encoding="utf-8")
    return schedule


def summarize_stage_artifacts(run_dir: str | Path) -> dict[str, object]:
    """Input: run dir. Output: artifact summary. Read existing run artifacts without changing state."""
    root = Path(run_dir)
    alpha_results = _read_jsonl(root / "all_alphas.jsonl")
    return {
        "alpha_result_count": len(alpha_results),
        "candidate_file_exists": (root / "candidates.csv").exists(),
        "simulation_event_count": len(_read_jsonl(root / "simulation_events.jsonl")),
    }
```

- [ ] **Step 4: Add `continue_once` schedule behavior to Orchestrator**

Modify `wqb/orchestrator.py` imports:

```python
from dataclasses import dataclass, replace
from wqb.workflow_stage_adapters import schedule_research_stage
```

Add method to `WorkflowOrchestrator`:

```python
    def continue_once(self, now: str) -> dict[str, object]:
        """Input: timestamp. Output: status summary. Advance exactly one legal workflow stage."""
        state = self._active_state()
        if state is None:
            return {"active": False, "status": "none", "next_action": "workflow-start"}
        run_dir = Path(state.run_dir)
        if state.status == "created" and state.current_stage == "objective_selected":
            state = transition_run_state(state, "running", "")
            state = replace(state, current_stage="schedule", next_action="workflow-continue")
            write_run_state(run_dir / STATE_FILENAME, state)
            append_workflow_event(run_dir, "stage_started", {"stage": "schedule"}, now)
            return self._summary(state)
        if state.status == "running" and state.current_stage == "schedule":
            manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
            result = schedule_research_stage(self.paths.knowledge_root, run_dir, str(manifest.get("selected_option_id", "")))
            state = replace(state, current_stage="scout_seed", last_completed_stage="schedule")
            write_run_state(run_dir / STATE_FILENAME, state)
            append_workflow_event(run_dir, "stage_completed", {"stage": "schedule", "result": result}, now)
            return self._summary(state)
        return self._summary(state)
```

- [ ] **Step 5: Extend Orchestrator tests for plan-only schedule progress**

Append to `tests/test_orchestrator.py`:

```python
    def test_continue_once_advances_created_run_to_schedule_then_scout_seed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            decisions = root / "knowledge" / "wiki" / "70_decisions"
            decisions.mkdir(parents=True)
            (decisions / "research_option_cards.jsonl").write_text(
                '{"option_id":"option-1","title":"Power Pool","scope":"USA D1","score":{"total":10}}\n',
                encoding="utf-8",
            )
            orchestrator = WorkflowOrchestrator(self.paths(root))
            orchestrator.start("Power Pool", "option-1", "2026-07-12T00:00:00Z")
            first = orchestrator.continue_once("2026-07-12T00:01:00Z")
            second = orchestrator.continue_once("2026-07-12T00:02:00Z")

        self.assertEqual(first["current_stage"], "schedule")
        self.assertEqual(second["current_stage"], "scout_seed")
```

- [ ] **Step 6: Run focused adapter and Orchestrator tests**

Run:

```powershell
python -m unittest tests.test_workflow_stage_adapters tests.test_orchestrator -v
```

Expected: PASS.

- [ ] **Step 7: Commit Task 6**

Run:

```powershell
Set-Location 'C:\Users\oytl\Desktop\pyproject\brain\skills-and-workflows'
git add BrainWorkflow/wqb/workflow_stage_adapters.py BrainWorkflow/wqb/orchestrator.py BrainWorkflow/tests/test_workflow_stage_adapters.py BrainWorkflow/tests/test_orchestrator.py
git commit -m "connect orchestrator schedule stage"
```

Expected: commit succeeds.

---

### Task 7: Candidate Gate, Approval, Queue, And Research Record Integration

**Files:**
- Modify: `wqb/orchestrator.py`
- Modify: `tests/test_orchestrator.py`
- Modify: `wqb/research_record.py`
- Modify: `tests/test_research_record.py`

**Interfaces:**
- Consumes: `candidate_queue.approve_candidate`, `candidate_queue.queue_approved_candidate`
- Consumes: `research_record.record_candidate_gate`, `write_research_record`, `sync_research_record_to_raw`
- Produces: `WorkflowOrchestrator.request_candidate_approval(candidates: list[dict[str, object]], now: str) -> dict[str, object]`
- Produces: `WorkflowOrchestrator.approve_candidates(candidate_ids: list[str], approved_at: str, approved_by: str) -> dict[str, object]`
- Produces: `WorkflowOrchestrator.sync_research_record(now: str) -> dict[str, object]`

- [ ] **Step 1: Add failing Orchestrator candidate gate tests**

Append to `tests/test_orchestrator.py`:

```python
    def test_candidate_gate_pauses_for_user_and_approval_queues_exact_candidates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orchestrator = WorkflowOrchestrator(self.paths(root))
            started = orchestrator.start("Power Pool", "option-1", "2026-07-12T00:00:00Z")
            candidate = {
                "candidate_id": "c1",
                "platform_alpha_id": "a1",
                "version": 1,
                "expression_hash": "h1",
                "source_run_id": started["run_id"],
            }
            gate = orchestrator.request_candidate_approval([candidate], "2026-07-12T00:10:00Z")
            approved = orchestrator.approve_candidates(["c1"], "2026-07-12T00:11:00Z", "user")

        self.assertEqual(gate["status"], "waiting_for_user")
        self.assertEqual(approved["queued_count"], 1)
```

- [ ] **Step 2: Add failing Research Record approval test**

Append to `tests/test_research_record.py`:

```python
    def test_research_record_tracks_approvals_and_queue_updates(self):
        from wqb.research_record import record_approval, record_queue_update

        record = empty_research_record("run1", "Power Pool")
        record = record_approval(record, {"candidate_id": "c1", "expression_hash": "h1"})
        record = record_queue_update(record, {"candidate_id": "c1", "status": "queued"})

        self.assertEqual(record.approvals[0]["candidate_id"], "c1")
        self.assertEqual(record.queue_updates[0]["status"], "queued")
```

- [ ] **Step 3: Run tests and verify failure**

Run:

```powershell
python -m unittest tests.test_orchestrator tests.test_research_record -v
```

Expected: FAIL with missing `request_candidate_approval`, `approve_candidates`, `record_approval`, and `record_queue_update`.

- [ ] **Step 4: Implement Research Record approval helpers**

Add to `wqb/research_record.py`:

```python
def record_approval(record: ResearchRecord, approval: dict[str, object]) -> ResearchRecord:
    """Input: record and approval. Output: updated record. Store user approval evidence."""
    return replace(record, approvals=[*record.approvals, dict(approval)])


def record_queue_update(record: ResearchRecord, queue_row: dict[str, object]) -> ResearchRecord:
    """Input: record and queue row. Output: updated record. Store approved queue update."""
    return replace(record, queue_updates=[*record.queue_updates, dict(queue_row)])
```

Extend `render_research_record_markdown` by adding after Candidate Gate rows:

```python
    lines.extend(["", "## User Approval", ""])
    for row in record.approvals:
        lines.append(f"- `{row.get('candidate_id', '')}` hash `{row.get('expression_hash', '')}`")
    lines.extend(["", "## Approved Queue", ""])
    for row in record.queue_updates:
        lines.append(f"- `{row.get('candidate_id', '')}` status `{row.get('status', '')}`")
```

- [ ] **Step 5: Implement Orchestrator candidate gate and approval methods**

Modify `wqb/orchestrator.py` imports:

```python
from wqb.candidate_queue import approve_candidate, queue_approved_candidate
from wqb.research_record import (
    empty_research_record,
    load_research_record,
    record_approval,
    record_candidate_gate,
    record_queue_update,
    write_research_record,
)
```

Add these methods to `WorkflowOrchestrator`:

```python
    def request_candidate_approval(self, candidates: list[dict[str, object]], now: str) -> dict[str, object]:
        """Input: candidates and timestamp. Output: status summary. Pause run for user candidate approval."""
        state = self._active_state()
        if state is None:
            return {"active": False, "status": "none"}
        run_dir = Path(state.run_dir)
        record = self._load_or_create_research_record(state)
        for candidate in candidates:
            record = record_candidate_gate(record, candidate, "ready_for_approval", ["hard checks passed"])
        write_research_record(run_dir / "research_record.json", record)
        (run_dir / "candidate_gate.json").write_text(json.dumps(candidates, ensure_ascii=False, indent=2), encoding="utf-8")
        state = transition_run_state(state, "waiting_for_user", "candidate approval required")
        write_run_state(run_dir / STATE_FILENAME, state)
        append_workflow_event(run_dir, "user_approval_requested", {"candidate_count": len(candidates)}, now)
        return self._summary(state)

    def approve_candidates(self, candidate_ids: list[str], approved_at: str, approved_by: str) -> dict[str, object]:
        """Input: candidate ids and approval metadata. Output: queue summary. Approve and queue exact candidates."""
        state = self._active_state()
        if state is None:
            return {"active": False, "queued_count": 0}
        run_dir = Path(state.run_dir)
        candidates = json.loads((run_dir / "candidate_gate.json").read_text(encoding="utf-8"))
        wanted = {str(item) for item in candidate_ids}
        record = self._load_or_create_research_record(state)
        queued_count = 0
        for candidate in candidates:
            if str(candidate.get("candidate_id", "")) not in wanted:
                continue
            approval = approve_candidate(run_dir, candidate, approved_at, approved_by)
            queue_row = queue_approved_candidate(run_dir, approval)
            record = record_approval(record, approval)
            record = record_queue_update(record, queue_row)
            queued_count += 1
        write_research_record(run_dir / "research_record.json", record)
        append_workflow_event(run_dir, "candidates_approved", {"queued_count": queued_count}, approved_at)
        state = transition_run_state(state, "running", "")
        write_run_state(run_dir / STATE_FILENAME, state)
        return {"run_id": state.run_id, "queued_count": queued_count, "status": state.status}

    def _load_or_create_research_record(self, state: WorkflowRunState):
        """Input: state. Output: ResearchRecord. Load or create the run research record."""
        path = Path(state.run_dir) / "research_record.json"
        if path.exists():
            return load_research_record(path)
        return empty_research_record(state.run_id, state.objective)
```

- [ ] **Step 6: Run focused integration tests**

Run:

```powershell
python -m unittest tests.test_orchestrator tests.test_research_record tests.test_candidate_queue -v
```

Expected: PASS.

- [ ] **Step 7: Commit Task 7**

Run:

```powershell
Set-Location 'C:\Users\oytl\Desktop\pyproject\brain\skills-and-workflows'
git add BrainWorkflow/wqb/orchestrator.py BrainWorkflow/wqb/research_record.py BrainWorkflow/tests/test_orchestrator.py BrainWorkflow/tests/test_research_record.py
git commit -m "integrate candidate approval flow"
```

Expected: commit succeeds.

---

### Task 8: Workflow CLI Commands

**Files:**
- Modify: `wqb/cli.py`
- Modify: `tests/test_cli.py`

**Interfaces:**
- Consumes: `WorkflowOrchestrator`, `OrchestratorPaths`
- Produces CLI commands:
  - `workflow-start`
  - `workflow-status`
  - `workflow-resume`
  - `workflow-abort`
  - `workflow-approve-candidates`
  - `workflow-update-candidate-status`

- [ ] **Step 1: Add failing CLI parser and dispatch tests**

Append to `tests/test_cli.py`:

```python
class WorkflowOrchestratorCliTests(unittest.TestCase):
    def test_parse_args_accepts_workflow_start(self):
        with patch("sys.argv", ["wqb", "workflow-start", "--objective", "Power Pool", "--selected-option-id", "option-1"]):
            from wqb.cli import parse_args
            args = parse_args()

        self.assertEqual(args.command, "workflow-start")
        self.assertEqual(args.objective, "Power Pool")

    def test_workflow_status_dispatches_orchestrator(self):
        from wqb.cli import main

        output = io.StringIO()
        with patch("sys.argv", ["wqb", "workflow-status"]), patch(
            "wqb.cli.WorkflowOrchestrator"
        ) as orchestrator_cls, redirect_stdout(output):
            orchestrator_cls.return_value.status.return_value = {"status": "created"}
            main()

        self.assertEqual(json.loads(output.getvalue())["status"], "created")
```

If `io`, `json`, `patch`, or `redirect_stdout` are already imported in `tests/test_cli.py`, reuse the existing imports. If any are missing, add them at the top:

```python
import io
import json
from contextlib import redirect_stdout
from unittest.mock import patch
```

- [ ] **Step 2: Run CLI tests and verify failure**

Run:

```powershell
python -m unittest tests.test_cli.WorkflowOrchestratorCliTests -v
```

Expected: FAIL because parser does not know the workflow commands.

- [ ] **Step 3: Add Orchestrator path helper in `wqb/cli.py`**

Modify imports:

```python
from wqb.orchestrator import OrchestratorPaths, WorkflowOrchestrator
```

Add helper near other path helpers:

```python
def default_orchestrator_paths(config: dict[str, Any]) -> OrchestratorPaths:
    """Input: run config. Output: OrchestratorPaths. Resolve local workflow state roots."""
    workflow_root = Path(__file__).resolve().parents[1]
    project_root = workflow_root.parents[1]
    knowledge_root = Path(config.get("knowledge_root", default_knowledge_root()))
    run_root = Path(config.get("run_root", "runs"))
    if not run_root.is_absolute():
        run_root = workflow_root / run_root
    return OrchestratorPaths(project_root=project_root, workflow_root=workflow_root, knowledge_root=knowledge_root, run_root=run_root)
```

- [ ] **Step 4: Add parser commands**

In `parse_args()`, add:

```python
    subparsers.add_parser("workflow-status")
    workflow_start = subparsers.add_parser("workflow-start")
    workflow_start.add_argument("--objective", required=True)
    workflow_start.add_argument("--selected-option-id", required=True)
    workflow_resume = subparsers.add_parser("workflow-resume")
    workflow_resume.add_argument("--now", default="")
    workflow_abort = subparsers.add_parser("workflow-abort")
    workflow_abort.add_argument("--reason", required=True)
    workflow_abort.add_argument("--now", default="")
    workflow_approve = subparsers.add_parser("workflow-approve-candidates")
    workflow_approve.add_argument("--candidate-id", action="append", default=[])
    workflow_approve.add_argument("--approved-by", default="user")
    workflow_approve.add_argument("--now", default="")
```

- [ ] **Step 5: Add main dispatch**

In `main()`, before legacy commands that require stage config live execution, add:

```python
    elif args.command == "workflow-start":
        orchestrator = WorkflowOrchestrator(default_orchestrator_paths(config))
        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        result = orchestrator.start(args.objective, args.selected_option_id, now)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.command == "workflow-status":
        orchestrator = WorkflowOrchestrator(default_orchestrator_paths(config))
        print(json.dumps(orchestrator.status(), ensure_ascii=False, indent=2))
    elif args.command == "workflow-resume":
        orchestrator = WorkflowOrchestrator(default_orchestrator_paths(config))
        now = args.now or datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        print(json.dumps(orchestrator.resume(now), ensure_ascii=False, indent=2))
    elif args.command == "workflow-abort":
        orchestrator = WorkflowOrchestrator(default_orchestrator_paths(config))
        now = args.now or datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        print(json.dumps(orchestrator.abort(args.reason, now), ensure_ascii=False, indent=2))
    elif args.command == "workflow-approve-candidates":
        orchestrator = WorkflowOrchestrator(default_orchestrator_paths(config))
        now = args.now or datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        print(json.dumps(orchestrator.approve_candidates(args.candidate_id, now, args.approved_by), ensure_ascii=False, indent=2))
```

- [ ] **Step 6: Run focused CLI workflow tests**

Run:

```powershell
python -m unittest tests.test_cli.WorkflowOrchestratorCliTests -v
```

Expected: PASS.

- [ ] **Step 7: Run broader CLI regression**

Run:

```powershell
python -m unittest tests.test_cli -v
```

Expected: PASS.

- [ ] **Step 8: Commit Task 8**

Run:

```powershell
Set-Location 'C:\Users\oytl\Desktop\pyproject\brain\skills-and-workflows'
git add BrainWorkflow/wqb/cli.py BrainWorkflow/tests/test_cli.py
git commit -m "add workflow orchestrator cli"
```

Expected: commit succeeds.

---

### Task 9: Console State And Documentation Alignment

**Files:**
- Modify: `wqb/console_state.py`
- Modify: `tests/test_console_state.py`
- Modify: `README.md`
- Modify: `docs/superpowers/specs/2026-07-12-workflow-console-design.md`
- Modify: `docs/superpowers/plans/2026-07-12-workflow-console-implementation.md`

**Interfaces:**
- Consumes: `load_active_run`, `load_run_state`, `read_workflow_events`, `load_approved_queue`
- Produces: console state keys:
  - `active_workflow`
  - `workflow_events`
  - `approved_queue`
  - `research_record`

- [ ] **Step 1: Add failing console state test for Orchestrator-backed state**

Append to `tests/test_console_state.py`:

```python
    def test_load_console_state_includes_active_workflow_state_events_and_queue(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            knowledge = root / "knowledge"
            runs = root / "runs"
            run_dir = runs / "run1"
            run_dir.mkdir(parents=True)
            knowledge.mkdir()
            (runs / "active_run.json").write_text(json.dumps({"run_id": "run1", "run_dir": str(run_dir)}), encoding="utf-8")
            from wqb.workflow_state import create_initial_state, write_run_state
            from wqb.workflow_events import append_workflow_event
            write_run_state(run_dir / "run_state.json", create_initial_state("run1", run_dir, "Power Pool", "2026-07-12T00:00:00Z"))
            append_workflow_event(run_dir, "workflow_created", {"run_id": "run1"}, "2026-07-12T00:00:00Z")
            (run_dir / "approved_candidates.jsonl").write_text('{"candidate_id":"c1","status":"queued"}\n', encoding="utf-8")

            state = load_console_state(
                ConsolePaths(root, root / "BrainWorkflow", knowledge, runs, root / "milestone.md", root / "worklog.md", runs / "console_jobs")
            )

        self.assertEqual(state["active_workflow"]["run_id"], "run1")
        self.assertEqual(state["workflow_events"][0]["event_type"], "workflow_created")
        self.assertEqual(state["approved_queue"][0]["candidate_id"], "c1")
```

- [ ] **Step 2: Run console state tests and verify failure**

Run:

```powershell
python -m unittest tests.test_console_state -v
```

Expected: FAIL because `active_workflow`, `workflow_events`, and `approved_queue` keys are absent.

- [ ] **Step 3: Update console state aggregation**

Modify `wqb/console_state.py` imports:

```python
from wqb.candidate_queue import load_approved_queue
from wqb.workflow_events import read_workflow_events
from wqb.workflow_state import load_active_run, load_run_state
```

Add helper:

```python
def _active_workflow_summary(runs_root: Path) -> dict[str, Any]:
    """Input: runs root. Output: active workflow summary. Read Orchestrator-owned state."""
    active = load_active_run(runs_root)
    if not active:
        return {"exists": False}
    run_dir = Path(active["run_dir"])
    state_path = run_dir / "run_state.json"
    if not state_path.exists():
        return {"exists": True, "run_id": active.get("run_id", ""), "state_exists": False}
    state = load_run_state(state_path)
    return {
        "exists": True,
        "state_exists": True,
        "run_id": state.run_id,
        "run_dir": state.run_dir,
        "status": state.status,
        "current_stage": state.current_stage,
        "next_action": state.next_action,
        "waiting_for_user": state.waiting_for_user,
    }
```

Extend `load_console_state()` return dict:

```python
        "active_workflow": _active_workflow_summary(paths.runs_root),
        "workflow_events": [event.__dict__ for event in read_workflow_events(Path(load_active_run(paths.runs_root).get("run_dir", paths.runs_root)))],
        "approved_queue": load_approved_queue(paths.runs_root),
```

- [ ] **Step 4: Update README Orchestrator operation section**

Add to `README.md`:

```markdown
## Orchestrator-First Workflow

Long-term research should start from the Orchestrator commands instead of manually chaining low-level commands.

```powershell
python -m wqb.cli workflow-start --objective "Power Pool" --selected-option-id option-1
python -m wqb.cli workflow-status
python -m wqb.cli workflow-resume
```

The Orchestrator owns `run_state.json`, `workflow_events.jsonl`, Research Record sync, candidate approval, and approved candidate queue records. Legacy commands remain useful for diagnostics and focused recovery, but they are not the source of official workflow state.
```

- [ ] **Step 5: Update console design and console implementation plan dependency**

In `docs/superpowers/specs/2026-07-12-workflow-console-design.md`, add under Architecture:

```markdown
After the Orchestrator slice, the console should call `workflow-*` commands or Orchestrator functions for official research flow. Low-level CLI commands remain visible as diagnostic actions, not the normal control path.
```

In `docs/superpowers/plans/2026-07-12-workflow-console-implementation.md`, add under Global Constraints:

```markdown
- Console Task 2 and later must use Orchestrator-owned state and `workflow-*` commands when controlling official research runs.
```

- [ ] **Step 6: Run focused console state tests**

Run:

```powershell
python -m unittest tests.test_console_state -v
```

Expected: PASS.

- [ ] **Step 7: Run full suite and compile checks**

Run:

```powershell
python -m unittest discover -s tests -v
python -m py_compile wqb/workflow_contract.py wqb/workflow_state.py wqb/workflow_events.py wqb/research_record.py wqb/candidate_queue.py wqb/orchestrator.py wqb/workflow_stage_adapters.py wqb/cli.py wqb/console_state.py
```

Expected: all tests pass and `py_compile` exits 0.

- [ ] **Step 8: Commit Task 9**

Run:

```powershell
Set-Location 'C:\Users\oytl\Desktop\pyproject\brain\skills-and-workflows'
git add BrainWorkflow/wqb/console_state.py BrainWorkflow/tests/test_console_state.py BrainWorkflow/README.md BrainWorkflow/docs/superpowers/specs/2026-07-12-workflow-console-design.md BrainWorkflow/docs/superpowers/plans/2026-07-12-workflow-console-implementation.md
git commit -m "align console with orchestrator state"
```

Expected: commit succeeds.

---

## Final Verification

Run from `C:\Users\oytl\Desktop\pyproject\brain\skills-and-workflows\BrainWorkflow`:

```powershell
python -m unittest discover -s tests -v
python -m py_compile wqb/workflow_contract.py wqb/workflow_state.py wqb/workflow_events.py wqb/research_record.py wqb/candidate_queue.py wqb/orchestrator.py wqb/workflow_stage_adapters.py wqb/cli.py wqb/console_state.py
```

Run from `C:\Users\oytl\Desktop\pyproject\brain\skills-and-workflows`:

```powershell
git diff --check HEAD~9..HEAD
git status --short --branch
```

Expected:

- all `unittest` tests pass;
- `py_compile` exits 0;
- `git diff --check` reports no whitespace errors;
- only known untracked local planning files remain, if any.

## Self-Review Checklist

- Spec coverage: Tasks 1-2 cover knowledge workflow contracts, state names, events, active run, and Resume foundation. Tasks 3-4 cover Research Record, candidate approval, and approved queue. Tasks 5-7 cover Orchestrator lifecycle, schedule stage, candidate gate, and queue integration. Task 8 covers CLI. Task 9 covers UI state alignment and documentation.
- Red-flag scan: run the planning-quality scan from the writing-plans skill and remove every match before committing.
- Type consistency: verify function names in task interfaces match code snippets and tests.
- Scope boundary: this plan does not rewrite core alpha generation, simulation, checker, benchmark, repair, planner, data ledger, template library, or API client.
