# Long-Term Workflow Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the foundation layer for the long-term BrainWorkflow system: Data Ledger, Template Library, knowledge freshness checks, incentive-aware research scheduling, and workflow-change proposals.

**Architecture:** Add small, focused Python modules under `wqb/` that load Markdown/JSONL knowledge artifacts, expose typed dataclass contracts, and feed the existing principle-led planner without changing simulation, repair, or submission logic. Research commands consume compiled knowledge; maintenance commands write health and proposal artifacts but do not run heavy website recapture in this plan.

**Tech Stack:** Python standard library, `dataclasses`, `json`, `pathlib`, `unittest`, existing `wqb.cli`, existing `wqb.principle_model.OptionCard`, Markdown and JSONL files in the shared knowledge vault.

## Global Constraints

- Do not hardcode WorldQuant BRAIN credentials.
- Do not modify the core simulation, repair, or submit execution path in this plan.
- Research commands must consume existing knowledge artifacts and must not run heavy raw-source capture or full wiki compile.
- Workflow optimization must write rule-change proposals only; the user decides whether to apply them.
- Use `BRAIN_KNOWLEDGE_ROOT` when set, otherwise use the existing shared-vault default.
- Put new module constants directly below imports.
- Every new function must include a short comment or docstring describing input, output, and purpose.
- Each task must be independently testable and committed separately.

---

## File Structure

- Create `wqb/data_ledger.py`
  - Owns Data Ledger row contracts, JSONL parsing, Markdown rendering, and scoring helpers.
- Create `tests/test_data_ledger.py`
  - Verifies row loading, usage-aware scoring, and Markdown output.
- Create `wqb/template_library.py`
  - Owns template contracts, JSONL parsing, compatibility scoring, and Markdown rendering.
- Create `tests/test_template_library.py`
  - Verifies template loading and data-template matching.
- Create `wqb/knowledge_freshness.py`
  - Owns freshness manifest contracts and stale/fresh status checks.
- Create `tests/test_knowledge_freshness.py`
  - Verifies age checks and status labels.
- Create `wqb/research_scheduler.py`
  - Turns a selected `OptionCard` plus Data Ledger and Template Library records into a concrete schedule.
- Create `tests/test_research_scheduler.py`
  - Verifies schedules prefer underused data and compatible low-correlation templates.
- Create `wqb/workflow_proposals.py`
  - Owns workflow-change proposal contracts and writers.
- Create `tests/test_workflow_proposals.py`
  - Verifies proposal generation and persistence.
- Modify `wqb/cli.py`
  - Add read/write helper commands for the new foundation layer.
- Extend `tests/test_cli.py`
  - Verify new CLI helper functions do not trigger simulations.
- Modify `README.md`
  - Link this implementation plan.
- Modify `todo.md`
  - Record plan completion and later task execution progress.

---

### Task 1: Data Ledger Contracts And Scoring

**Files:**
- Create: `wqb/data_ledger.py`
- Test: `tests/test_data_ledger.py`

**Interfaces:**
- Consumes: JSONL rows from `knowledge/wiki/20_semantics/data_ledger.jsonl`.
- Produces:
  - `DataLedgerRecord`
  - `data_ledger_record_to_dict(record: DataLedgerRecord) -> dict[str, Any]`
  - `load_data_ledger(path: Path) -> list[DataLedgerRecord]`
  - `score_data_for_research(record: DataLedgerRecord, incentive: str, region: str, delay: int) -> float`
  - `select_data_for_research(records: list[DataLedgerRecord], incentive: str, region: str, delay: int, limit: int) -> list[DataLedgerRecord]`
  - `write_data_ledger_markdown(path: Path, records: list[DataLedgerRecord], generated_at: str) -> Path`

- [ ] **Step 1: Write the failing test**

Create `tests/test_data_ledger.py`:

```python
import json
import tempfile
import unittest
from pathlib import Path

from wqb.data_ledger import (
    DataLedgerRecord,
    data_ledger_record_to_dict,
    load_data_ledger,
    score_data_for_research,
    select_data_for_research,
    write_data_ledger_markdown,
)


class DataLedgerTest(unittest.TestCase):
    def test_load_data_ledger_round_trips_jsonl(self):
        row = {
            "dataset_id": "news12",
            "dataset_name": "News Events",
            "field_id": "news12_sentiment_fast_d1",
            "field_type": "MATRIX",
            "region": "USA",
            "delay": 1,
            "universe": "TOP3000",
            "semantic_tags": ["event", "sentiment", "fast_d1"],
            "coverage": 0.82,
            "alpha_count": 12,
            "user_count": 4,
            "simulation_usage_count": 1,
            "submitted_usage_count": 0,
            "last_used_at": "2026-07-09",
            "best_result_label": "repairable_signal",
            "correlation_risk": "medium",
            "source_paths": ["knowledge/raw/platform/learn/2026-07-09/documentation_pages.md"],
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "data_ledger.jsonl"
            path.write_text(json.dumps(row, sort_keys=True) + "\n", encoding="utf-8")

            records = load_data_ledger(path)

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].field_id, "news12_sentiment_fast_d1")
        self.assertEqual(data_ledger_record_to_dict(records[0])["dataset_id"], "news12")

    def test_score_data_prefers_underused_matching_incentive_data(self):
        preferred = DataLedgerRecord(
            dataset_id="news12",
            dataset_name="News Events",
            field_id="news12_sentiment_fast_d1",
            field_type="MATRIX",
            region="USA",
            delay=1,
            universe="TOP3000",
            semantic_tags=["event", "sentiment", "fast_d1", "power_pool"],
            coverage=0.82,
            alpha_count=12,
            user_count=4,
            simulation_usage_count=1,
            submitted_usage_count=0,
            last_used_at="2026-07-09",
            best_result_label="repairable_signal",
            correlation_risk="medium",
            source_paths=["raw"],
        )
        crowded = DataLedgerRecord(
            dataset_id="pv1",
            dataset_name="Price Volume",
            field_id="volume",
            field_type="MATRIX",
            region="USA",
            delay=1,
            universe="TOP3000",
            semantic_tags=["liquidity"],
            coverage=0.99,
            alpha_count=900,
            user_count=300,
            simulation_usage_count=30,
            submitted_usage_count=5,
            last_used_at="2026-07-09",
            best_result_label="prod_correlation_fail",
            correlation_risk="high",
            source_paths=["raw"],
        )

        selected = select_data_for_research([crowded, preferred], "power_pool", "USA", 1, limit=1)

        self.assertEqual(selected[0].field_id, "news12_sentiment_fast_d1")
        self.assertGreater(score_data_for_research(preferred, "power_pool", "USA", 1), score_data_for_research(crowded, "power_pool", "USA", 1))

    def test_write_data_ledger_markdown_creates_reviewable_table(self):
        record = DataLedgerRecord(
            dataset_id="analyst9",
            dataset_name="Analyst Revisions",
            field_id="analyst9_eps_revision",
            field_type="MATRIX",
            region="USA",
            delay=1,
            universe="TOP3000",
            semantic_tags=["analyst_revision", "growth"],
            coverage=0.76,
            alpha_count=40,
            user_count=11,
            simulation_usage_count=0,
            submitted_usage_count=0,
            last_used_at="",
            best_result_label="unexplored",
            correlation_risk="low",
            source_paths=["knowledge/raw/platform/learn/2026-07-09/documentation_pages.md"],
        )
        with tempfile.TemporaryDirectory() as tmp:
            output = write_data_ledger_markdown(Path(tmp) / "data_ledger.md", [record], "2026-07-10T00:00:00Z")
            text = output.read_text(encoding="utf-8")

        self.assertIn("analyst9_eps_revision", text)
        self.assertIn("analyst_revision, growth", text)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify failure**

Run:

```powershell
python -m unittest tests.test_data_ledger -v
```

Expected: fail with `ModuleNotFoundError: No module named 'wqb.data_ledger'`.

- [ ] **Step 3: Implement `wqb/data_ledger.py`**

Create `wqb/data_ledger.py`:

```python
from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any


LOW_RISK_BONUS = 1.5
MEDIUM_RISK_BONUS = 0.3
HIGH_RISK_PENALTY = 2.5
MATCHING_SCOPE_BONUS = 2.0
INCENTIVE_TAG_BONUS = 2.0
UNDERUSED_BONUS = 2.0
SUBMITTED_USAGE_PENALTY = 1.5
SIM_USAGE_PENALTY = 0.08
REPAIRABLE_SIGNAL_BONUS = 1.0
PROD_CORR_PENALTY = 2.0


@dataclass(frozen=True)
class DataLedgerRecord:
    dataset_id: str
    dataset_name: str
    field_id: str
    field_type: str
    region: str
    delay: int
    universe: str
    semantic_tags: list[str]
    coverage: float
    alpha_count: int
    user_count: int
    simulation_usage_count: int
    submitted_usage_count: int
    last_used_at: str
    best_result_label: str
    correlation_risk: str
    source_paths: list[str]


def data_ledger_record_to_dict(record: DataLedgerRecord) -> dict[str, Any]:
    """Input: DataLedgerRecord. Output: dict[str, Any]. Convert ledger record to JSON-safe data."""
    return asdict(record)


def _record_from_dict(row: dict[str, Any]) -> DataLedgerRecord:
    """Input: dict row. Output: DataLedgerRecord. Normalize one JSONL row from the data ledger."""
    return DataLedgerRecord(
        dataset_id=str(row.get("dataset_id", "")),
        dataset_name=str(row.get("dataset_name", "")),
        field_id=str(row.get("field_id", "")),
        field_type=str(row.get("field_type", "")),
        region=str(row.get("region", "")),
        delay=int(row.get("delay", 0)),
        universe=str(row.get("universe", "")),
        semantic_tags=[str(item) for item in row.get("semantic_tags", []) if str(item)],
        coverage=float(row.get("coverage", 0.0)),
        alpha_count=int(row.get("alpha_count", 0)),
        user_count=int(row.get("user_count", 0)),
        simulation_usage_count=int(row.get("simulation_usage_count", 0)),
        submitted_usage_count=int(row.get("submitted_usage_count", 0)),
        last_used_at=str(row.get("last_used_at", "")),
        best_result_label=str(row.get("best_result_label", "")),
        correlation_risk=str(row.get("correlation_risk", "unknown")),
        source_paths=[str(item) for item in row.get("source_paths", []) if str(item)],
    )


def load_data_ledger(path: Path) -> list[DataLedgerRecord]:
    """Input: JSONL path. Output: DataLedgerRecord list. Load data scheduling memory from disk."""
    if not path.exists():
        return []
    records: list[DataLedgerRecord] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            records.append(_record_from_dict(json.loads(line)))
    return records


def score_data_for_research(record: DataLedgerRecord, incentive: str, region: str, delay: int) -> float:
    """Input: data record, incentive, region, delay. Output: float score. Rank fields for research scheduling."""
    score = float(record.coverage) * 2.0
    if record.region.upper() == region.upper() and int(record.delay) == int(delay):
        score += MATCHING_SCOPE_BONUS
    tags = {tag.lower() for tag in record.semantic_tags}
    if incentive.lower() in tags:
        score += INCENTIVE_TAG_BONUS
    if record.simulation_usage_count == 0 and record.submitted_usage_count == 0:
        score += UNDERUSED_BONUS
    score -= record.submitted_usage_count * SUBMITTED_USAGE_PENALTY
    score -= record.simulation_usage_count * SIM_USAGE_PENALTY
    risk = record.correlation_risk.lower()
    if risk == "low":
        score += LOW_RISK_BONUS
    elif risk == "medium":
        score += MEDIUM_RISK_BONUS
    elif risk == "high":
        score -= HIGH_RISK_PENALTY
    if record.best_result_label == "repairable_signal":
        score += REPAIRABLE_SIGNAL_BONUS
    if record.best_result_label == "prod_correlation_fail":
        score -= PROD_CORR_PENALTY
    return round(score, 4)


def select_data_for_research(
    records: list[DataLedgerRecord],
    incentive: str,
    region: str,
    delay: int,
    limit: int,
) -> list[DataLedgerRecord]:
    """Input: records and scheduling filters. Output: ranked records. Select data candidates for a run."""
    scored = sorted(
        records,
        key=lambda item: (score_data_for_research(item, incentive, region, delay), item.field_id),
        reverse=True,
    )
    return scored[: max(int(limit), 0)]


def write_data_ledger_markdown(path: Path, records: list[DataLedgerRecord], generated_at: str) -> Path:
    """Input: output path, records, timestamp. Output: path. Write reviewable Markdown data ledger."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Data Ledger",
        "",
        f"Generated at: `{generated_at}`",
        "",
        "| Dataset | Field | Scope | Tags | Usage | Best Result | Risk |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for record in records:
        scope = f"{record.region} D{record.delay} {record.universe}"
        tags = ", ".join(record.semantic_tags)
        usage = f"sim={record.simulation_usage_count}; submitted={record.submitted_usage_count}"
        lines.append(
            f"| {record.dataset_id} | `{record.field_id}` | {scope} | {tags} | {usage} | {record.best_result_label} | {record.correlation_risk} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
```

- [ ] **Step 4: Run the tests to verify pass**

Run:

```powershell
python -m unittest tests.test_data_ledger -v
```

Expected: 3 tests pass.

- [ ] **Step 5: Commit**

Run:

```powershell
git add BrainWorkflow/wqb/data_ledger.py BrainWorkflow/tests/test_data_ledger.py
git commit -m "add data ledger foundation"
```

Expected: commit succeeds.

---

### Task 2: Template Library Contracts And Matching

**Files:**
- Create: `wqb/template_library.py`
- Test: `tests/test_template_library.py`

**Interfaces:**
- Consumes:
  - JSONL rows from `knowledge/wiki/30_templates/template_library.jsonl`
  - `DataLedgerRecord` from `wqb.data_ledger`
- Produces:
  - `TemplateRecord`
  - `template_record_to_dict(record: TemplateRecord) -> dict[str, Any]`
  - `load_template_library(path: Path) -> list[TemplateRecord]`
  - `score_template_for_data(template: TemplateRecord, data_record: DataLedgerRecord, incentive: str) -> float`
  - `select_templates_for_data(templates: list[TemplateRecord], data_record: DataLedgerRecord, incentive: str, limit: int) -> list[TemplateRecord]`
  - `write_template_library_markdown(path: Path, templates: list[TemplateRecord], generated_at: str) -> Path`

- [ ] **Step 1: Write the failing test**

Create `tests/test_template_library.py`:

```python
import json
import tempfile
import unittest
from pathlib import Path

from wqb.data_ledger import DataLedgerRecord
from wqb.template_library import (
    TemplateRecord,
    load_template_library,
    score_template_for_data,
    select_templates_for_data,
    template_record_to_dict,
    write_template_library_markdown,
)


def sample_data() -> DataLedgerRecord:
    return DataLedgerRecord(
        dataset_id="news12",
        dataset_name="News Events",
        field_id="news12_sentiment_fast_d1",
        field_type="MATRIX",
        region="USA",
        delay=1,
        universe="TOP3000",
        semantic_tags=["event", "sentiment", "fast_d1", "power_pool"],
        coverage=0.82,
        alpha_count=12,
        user_count=4,
        simulation_usage_count=1,
        submitted_usage_count=0,
        last_used_at="2026-07-09",
        best_result_label="repairable_signal",
        correlation_risk="medium",
        source_paths=["raw"],
    )


class TemplateLibraryTest(unittest.TestCase):
    def test_load_template_library_round_trips_jsonl(self):
        row = {
            "template_id": "event_fast_delta_rank",
            "hypothesis": "Fast event sentiment changes are incorporated gradually.",
            "skeleton": "rank(ts_delta({field}, 1))",
            "required_field_types": ["MATRIX"],
            "compatible_semantic_tags": ["event", "sentiment", "fast_d1"],
            "operator_tags": ["time_series_surprise", "cross_sectional_normalizer"],
            "status": "seed",
            "correlation_risk": "low",
            "repair_levers": ["group_neutralize", "window_5"],
            "source_paths": ["knowledge/wiki/30_templates/template_families.md"],
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "template_library.jsonl"
            path.write_text(json.dumps(row, sort_keys=True) + "\n", encoding="utf-8")

            templates = load_template_library(path)

        self.assertEqual(len(templates), 1)
        self.assertEqual(templates[0].template_id, "event_fast_delta_rank")
        self.assertEqual(template_record_to_dict(templates[0])["status"], "seed")

    def test_select_templates_prefers_compatible_low_risk_template(self):
        compatible = TemplateRecord(
            template_id="event_fast_delta_rank",
            hypothesis="Fast event sentiment changes are incorporated gradually.",
            skeleton="rank(ts_delta({field}, 1))",
            required_field_types=["MATRIX"],
            compatible_semantic_tags=["event", "sentiment", "fast_d1", "power_pool"],
            operator_tags=["time_series_surprise", "cross_sectional_normalizer"],
            status="seed",
            correlation_risk="low",
            repair_levers=["group_neutralize"],
            source_paths=["wiki"],
        )
        incompatible = TemplateRecord(
            template_id="vector_attention_avg",
            hypothesis="Vector attention breadth predicts return pressure.",
            skeleton="rank(vec_avg({field}))",
            required_field_types=["VECTOR"],
            compatible_semantic_tags=["attention"],
            operator_tags=["vector_reducer"],
            status="seed",
            correlation_risk="medium",
            repair_levers=["vec_sum"],
            source_paths=["wiki"],
        )

        selected = select_templates_for_data([incompatible, compatible], sample_data(), "power_pool", limit=1)

        self.assertEqual(selected[0].template_id, "event_fast_delta_rank")
        self.assertGreater(score_template_for_data(compatible, sample_data(), "power_pool"), score_template_for_data(incompatible, sample_data(), "power_pool"))

    def test_write_template_library_markdown_creates_reviewable_table(self):
        template = TemplateRecord(
            template_id="quality_spread",
            hypothesis="Cashflow quality minus leverage pressure reprices gradually.",
            skeleton="rank({positive}) - rank({negative})",
            required_field_types=["MATRIX"],
            compatible_semantic_tags=["cashflow", "leverage_pressure"],
            operator_tags=["cross_sectional_normalizer"],
            status="discovery_ready",
            correlation_risk="medium",
            repair_levers=["subindustry_neutralize"],
            source_paths=["knowledge/wiki/30_templates/template_families.md"],
        )
        with tempfile.TemporaryDirectory() as tmp:
            output = write_template_library_markdown(Path(tmp) / "template_library.md", [template], "2026-07-10T00:00:00Z")
            text = output.read_text(encoding="utf-8")

        self.assertIn("quality_spread", text)
        self.assertIn("Cashflow quality", text)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify failure**

Run:

```powershell
python -m unittest tests.test_template_library -v
```

Expected: fail with `ModuleNotFoundError: No module named 'wqb.template_library'`.

- [ ] **Step 3: Implement `wqb/template_library.py`**

Create `wqb/template_library.py`:

```python
from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any

from wqb.data_ledger import DataLedgerRecord


FIELD_TYPE_MATCH_BONUS = 3.0
TAG_MATCH_BONUS = 0.8
INCENTIVE_TAG_BONUS = 1.5
LOW_RISK_BONUS = 1.5
MEDIUM_RISK_BONUS = 0.3
HIGH_RISK_PENALTY = 2.0
STATUS_SCORES = {
    "submit_proven": 2.0,
    "discovery_ready": 1.5,
    "seed": 1.0,
    "scout_only": 0.2,
    "repair_only": -0.5,
    "deprecated": -4.0,
}


@dataclass(frozen=True)
class TemplateRecord:
    template_id: str
    hypothesis: str
    skeleton: str
    required_field_types: list[str]
    compatible_semantic_tags: list[str]
    operator_tags: list[str]
    status: str
    correlation_risk: str
    repair_levers: list[str]
    source_paths: list[str]


def template_record_to_dict(record: TemplateRecord) -> dict[str, Any]:
    """Input: TemplateRecord. Output: dict[str, Any]. Convert template record to JSON-safe data."""
    return asdict(record)


def _template_from_dict(row: dict[str, Any]) -> TemplateRecord:
    """Input: dict row. Output: TemplateRecord. Normalize one JSONL row from the template library."""
    return TemplateRecord(
        template_id=str(row.get("template_id", "")),
        hypothesis=str(row.get("hypothesis", "")),
        skeleton=str(row.get("skeleton", "")),
        required_field_types=[str(item).upper() for item in row.get("required_field_types", []) if str(item)],
        compatible_semantic_tags=[str(item) for item in row.get("compatible_semantic_tags", []) if str(item)],
        operator_tags=[str(item) for item in row.get("operator_tags", []) if str(item)],
        status=str(row.get("status", "scout_only")),
        correlation_risk=str(row.get("correlation_risk", "unknown")),
        repair_levers=[str(item) for item in row.get("repair_levers", []) if str(item)],
        source_paths=[str(item) for item in row.get("source_paths", []) if str(item)],
    )


def load_template_library(path: Path) -> list[TemplateRecord]:
    """Input: JSONL path. Output: TemplateRecord list. Load strategy template memory from disk."""
    if not path.exists():
        return []
    records: list[TemplateRecord] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            records.append(_template_from_dict(json.loads(line)))
    return records


def score_template_for_data(template: TemplateRecord, data_record: DataLedgerRecord, incentive: str) -> float:
    """Input: template, data record, incentive. Output: float score. Rank template fit for a field."""
    score = STATUS_SCORES.get(template.status, 0.0)
    if data_record.field_type.upper() in {item.upper() for item in template.required_field_types}:
        score += FIELD_TYPE_MATCH_BONUS
    else:
        score -= FIELD_TYPE_MATCH_BONUS
    data_tags = {tag.lower() for tag in data_record.semantic_tags}
    template_tags = {tag.lower() for tag in template.compatible_semantic_tags}
    score += len(data_tags & template_tags) * TAG_MATCH_BONUS
    if incentive.lower() in template_tags or incentive.lower() in data_tags:
        score += INCENTIVE_TAG_BONUS
    risk = template.correlation_risk.lower()
    if risk == "low":
        score += LOW_RISK_BONUS
    elif risk == "medium":
        score += MEDIUM_RISK_BONUS
    elif risk == "high":
        score -= HIGH_RISK_PENALTY
    return round(score, 4)


def select_templates_for_data(
    templates: list[TemplateRecord],
    data_record: DataLedgerRecord,
    incentive: str,
    limit: int,
) -> list[TemplateRecord]:
    """Input: templates, data record, incentive, limit. Output: ranked templates. Select template candidates."""
    scored = sorted(
        templates,
        key=lambda item: (score_template_for_data(item, data_record, incentive), item.template_id),
        reverse=True,
    )
    return scored[: max(int(limit), 0)]


def write_template_library_markdown(path: Path, templates: list[TemplateRecord], generated_at: str) -> Path:
    """Input: output path, templates, timestamp. Output: path. Write reviewable Markdown template library."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Template Library",
        "",
        f"Generated at: `{generated_at}`",
        "",
        "| Template | Status | Hypothesis | Field Types | Tags | Risk |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for template in templates:
        field_types = ", ".join(template.required_field_types)
        tags = ", ".join(template.compatible_semantic_tags)
        lines.append(
            f"| `{template.template_id}` | {template.status} | {template.hypothesis} | {field_types} | {tags} | {template.correlation_risk} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
```

- [ ] **Step 4: Run the tests to verify pass**

Run:

```powershell
python -m unittest tests.test_template_library tests.test_data_ledger -v
```

Expected: 6 tests pass.

- [ ] **Step 5: Commit**

Run:

```powershell
git add BrainWorkflow/wqb/template_library.py BrainWorkflow/tests/test_template_library.py
git commit -m "add template library foundation"
```

Expected: commit succeeds.

---

### Task 3: Knowledge Freshness Checks

**Files:**
- Create: `wqb/knowledge_freshness.py`
- Test: `tests/test_knowledge_freshness.py`

**Interfaces:**
- Consumes: JSON manifest rows with `name`, `path`, `updated_at`, and `max_age_days`.
- Produces:
  - `KnowledgeFreshnessRecord`
  - `KnowledgeFreshnessStatus`
  - `load_freshness_manifest(path: Path) -> list[KnowledgeFreshnessRecord]`
  - `evaluate_freshness(records: list[KnowledgeFreshnessRecord], today: date) -> list[KnowledgeFreshnessStatus]`
  - `write_freshness_report(path: Path, statuses: list[KnowledgeFreshnessStatus], generated_at: str) -> Path`

- [ ] **Step 1: Write the failing test**

Create `tests/test_knowledge_freshness.py`:

```python
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from wqb.knowledge_freshness import (
    KnowledgeFreshnessRecord,
    evaluate_freshness,
    load_freshness_manifest,
    write_freshness_report,
)


class KnowledgeFreshnessTest(unittest.TestCase):
    def test_load_freshness_manifest(self):
        row = {
            "name": "data_ledger",
            "path": "knowledge/wiki/20_semantics/data_ledger.jsonl",
            "updated_at": "2026-07-08",
            "max_age_days": 1,
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "freshness.json"
            path.write_text(json.dumps([row], sort_keys=True), encoding="utf-8")

            records = load_freshness_manifest(path)

        self.assertEqual(records[0].name, "data_ledger")
        self.assertEqual(records[0].max_age_days, 1)

    def test_evaluate_freshness_marks_stale_records(self):
        records = [
            KnowledgeFreshnessRecord("data_ledger", "knowledge/wiki/20_semantics/data_ledger.jsonl", "2026-07-08", 1),
            KnowledgeFreshnessRecord("template_library", "knowledge/wiki/30_templates/template_library.jsonl", "2026-07-10", 7),
        ]

        statuses = evaluate_freshness(records, today=date(2026, 7, 10))

        by_name = {status.name: status for status in statuses}
        self.assertTrue(by_name["data_ledger"].stale)
        self.assertFalse(by_name["template_library"].stale)
        self.assertEqual(by_name["data_ledger"].age_days, 2)

    def test_write_freshness_report(self):
        statuses = evaluate_freshness(
            [KnowledgeFreshnessRecord("benchmarks", "knowledge/wiki/50_benchmarks", "2026-07-06", 3)],
            today=date(2026, 7, 10),
        )
        with tempfile.TemporaryDirectory() as tmp:
            output = write_freshness_report(Path(tmp) / "freshness_report.md", statuses, "2026-07-10T00:00:00Z")
            text = output.read_text(encoding="utf-8")

        self.assertIn("benchmarks", text)
        self.assertIn("stale", text)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify failure**

Run:

```powershell
python -m unittest tests.test_knowledge_freshness -v
```

Expected: fail with `ModuleNotFoundError: No module named 'wqb.knowledge_freshness'`.

- [ ] **Step 3: Implement `wqb/knowledge_freshness.py`**

Create `wqb/knowledge_freshness.py`:

```python
from dataclasses import dataclass
from datetime import date
import json
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class KnowledgeFreshnessRecord:
    name: str
    path: str
    updated_at: str
    max_age_days: int


@dataclass(frozen=True)
class KnowledgeFreshnessStatus:
    name: str
    path: str
    updated_at: str
    max_age_days: int
    age_days: int
    stale: bool


def _record_from_dict(row: dict[str, Any]) -> KnowledgeFreshnessRecord:
    """Input: dict row. Output: KnowledgeFreshnessRecord. Normalize one manifest entry."""
    return KnowledgeFreshnessRecord(
        name=str(row.get("name", "")),
        path=str(row.get("path", "")),
        updated_at=str(row.get("updated_at", "")),
        max_age_days=int(row.get("max_age_days", 0)),
    )


def load_freshness_manifest(path: Path) -> list[KnowledgeFreshnessRecord]:
    """Input: manifest path. Output: freshness records. Load knowledge freshness settings."""
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        return []
    return [_record_from_dict(row) for row in payload if isinstance(row, dict)]


def evaluate_freshness(records: list[KnowledgeFreshnessRecord], today: date) -> list[KnowledgeFreshnessStatus]:
    """Input: records and current date. Output: statuses. Mark stale knowledge artifacts."""
    statuses: list[KnowledgeFreshnessStatus] = []
    for record in records:
        updated = date.fromisoformat(record.updated_at)
        age_days = (today - updated).days
        statuses.append(
            KnowledgeFreshnessStatus(
                name=record.name,
                path=record.path,
                updated_at=record.updated_at,
                max_age_days=record.max_age_days,
                age_days=age_days,
                stale=age_days > record.max_age_days,
            )
        )
    return statuses


def write_freshness_report(path: Path, statuses: list[KnowledgeFreshnessStatus], generated_at: str) -> Path:
    """Input: output path, statuses, timestamp. Output: path. Write a Markdown knowledge freshness report."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Knowledge Freshness Report",
        "",
        f"Generated at: `{generated_at}`",
        "",
        "| Name | Status | Age Days | Max Age Days | Path |",
        "| --- | --- | ---: | ---: | --- |",
    ]
    for status in statuses:
        label = "stale" if status.stale else "fresh"
        lines.append(f"| {status.name} | {label} | {status.age_days} | {status.max_age_days} | `{status.path}` |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
```

- [ ] **Step 4: Run the tests to verify pass**

Run:

```powershell
python -m unittest tests.test_knowledge_freshness -v
```

Expected: 3 tests pass.

- [ ] **Step 5: Commit**

Run:

```powershell
git add BrainWorkflow/wqb/knowledge_freshness.py BrainWorkflow/tests/test_knowledge_freshness.py
git commit -m "add knowledge freshness checks"
```

Expected: commit succeeds.

---

### Task 4: Incentive-Aware Research Scheduler

**Files:**
- Create: `wqb/research_scheduler.py`
- Test: `tests/test_research_scheduler.py`

**Interfaces:**
- Consumes:
  - `OptionCard` from `wqb.principle_model`
  - `DataLedgerRecord` and `select_data_for_research` from `wqb.data_ledger`
  - `TemplateRecord` and `select_templates_for_data` from `wqb.template_library`
- Produces:
  - `ResearchSchedule`
  - `research_schedule_to_dict(schedule: ResearchSchedule) -> dict[str, Any]`
  - `build_research_schedule(option: OptionCard, data_records: list[DataLedgerRecord], templates: list[TemplateRecord], region: str, delay: int, max_data: int = 5, templates_per_data: int = 2, batch_size: int = 30) -> ResearchSchedule`
  - `write_research_schedule(path: Path, schedule: ResearchSchedule, generated_at: str) -> Path`

- [ ] **Step 1: Write the failing test**

Create `tests/test_research_scheduler.py`:

```python
import tempfile
import unittest
from pathlib import Path

from wqb.data_ledger import DataLedgerRecord
from wqb.principle_model import OptionCard, ScoreBreakdown, SourceEvidence
from wqb.research_scheduler import build_research_schedule, research_schedule_to_dict, write_research_schedule
from wqb.template_library import TemplateRecord


def option_card() -> OptionCard:
    return OptionCard(
        title="Explore current Power Pool boards",
        primary_incentive="power_pool",
        secondary_incentives=["genius"],
        why_now="Visible Power Pool boards include USA D1.",
        candidate_scope="USA D1 underused event data.",
        expected_asset_value="Simple alpha assets with lower criteria.",
        correlation_risk="Medium-high unless new data and distinct templates are used.",
        resource_cost="One 30-alpha scout batch.",
        evidence=[SourceEvidence("api", "/consultant/boards/power-pool", "Power Pool boards", "2026-07-10T00:00:00Z")],
        failure_modes=["Power Pool correlation failure."],
        decision_needed="Choose this option.",
        score=ScoreBreakdown(total=8.0, components={"power_pool": 8.0}, penalties={}, reasons=["Visible board."]),
    )


def data_records() -> list[DataLedgerRecord]:
    return [
        DataLedgerRecord(
            dataset_id="pv1",
            dataset_name="Price Volume",
            field_id="volume",
            field_type="MATRIX",
            region="USA",
            delay=1,
            universe="TOP3000",
            semantic_tags=["liquidity"],
            coverage=0.99,
            alpha_count=900,
            user_count=300,
            simulation_usage_count=30,
            submitted_usage_count=5,
            last_used_at="2026-07-09",
            best_result_label="prod_correlation_fail",
            correlation_risk="high",
            source_paths=["raw"],
        ),
        DataLedgerRecord(
            dataset_id="news12",
            dataset_name="News Events",
            field_id="news12_sentiment_fast_d1",
            field_type="MATRIX",
            region="USA",
            delay=1,
            universe="TOP3000",
            semantic_tags=["event", "sentiment", "fast_d1", "power_pool"],
            coverage=0.82,
            alpha_count=12,
            user_count=4,
            simulation_usage_count=1,
            submitted_usage_count=0,
            last_used_at="2026-07-09",
            best_result_label="repairable_signal",
            correlation_risk="medium",
            source_paths=["raw"],
        ),
    ]


def templates() -> list[TemplateRecord]:
    return [
        TemplateRecord(
            template_id="event_fast_delta_rank",
            hypothesis="Fast event sentiment changes are incorporated gradually.",
            skeleton="rank(ts_delta({field}, 1))",
            required_field_types=["MATRIX"],
            compatible_semantic_tags=["event", "sentiment", "fast_d1", "power_pool"],
            operator_tags=["time_series_surprise", "cross_sectional_normalizer"],
            status="seed",
            correlation_risk="low",
            repair_levers=["group_neutralize"],
            source_paths=["wiki"],
        )
    ]


class ResearchSchedulerTest(unittest.TestCase):
    def test_build_schedule_prefers_underused_data_and_matching_template(self):
        schedule = build_research_schedule(option_card(), data_records(), templates(), region="USA", delay=1)

        self.assertEqual(schedule.primary_incentive, "power_pool")
        self.assertEqual(schedule.selected_data[0].field_id, "news12_sentiment_fast_d1")
        self.assertEqual(schedule.template_matches[0]["template_id"], "event_fast_delta_rank")
        self.assertEqual(schedule.batch_size, 30)
        self.assertIn("local_novelty_gate", schedule.local_gates)

    def test_research_schedule_to_dict_is_json_safe(self):
        schedule = build_research_schedule(option_card(), data_records(), templates(), region="USA", delay=1)
        row = research_schedule_to_dict(schedule)

        self.assertEqual(row["option_title"], "Explore current Power Pool boards")
        self.assertEqual(row["selected_data"][0]["field_id"], "news12_sentiment_fast_d1")

    def test_write_research_schedule_creates_markdown(self):
        schedule = build_research_schedule(option_card(), data_records(), templates(), region="USA", delay=1)
        with tempfile.TemporaryDirectory() as tmp:
            output = write_research_schedule(Path(tmp) / "schedule.md", schedule, "2026-07-10T00:00:00Z")
            text = output.read_text(encoding="utf-8")

        self.assertIn("Explore current Power Pool boards", text)
        self.assertIn("news12_sentiment_fast_d1", text)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify failure**

Run:

```powershell
python -m unittest tests.test_research_scheduler -v
```

Expected: fail with `ModuleNotFoundError: No module named 'wqb.research_scheduler'`.

- [ ] **Step 3: Implement `wqb/research_scheduler.py`**

Create `wqb/research_scheduler.py`:

```python
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from wqb.data_ledger import DataLedgerRecord, data_ledger_record_to_dict, select_data_for_research
from wqb.principle_model import OptionCard
from wqb.template_library import TemplateRecord, select_templates_for_data


DEFAULT_LOCAL_GATES = [
    "syntax_gate",
    "field_availability_gate",
    "field_type_gate",
    "template_complexity_gate",
    "local_novelty_gate",
    "self_correlation_proxy_gate",
    "production_correlation_risk_gate",
]


@dataclass(frozen=True)
class ResearchSchedule:
    option_title: str
    primary_incentive: str
    region: str
    delay: int
    batch_size: int
    selected_data: list[DataLedgerRecord]
    template_matches: list[dict[str, Any]]
    local_gates: list[str]
    stop_rules: list[str]


def research_schedule_to_dict(schedule: ResearchSchedule) -> dict[str, Any]:
    """Input: ResearchSchedule. Output: dict[str, Any]. Convert schedule to JSON-safe data."""
    row = asdict(schedule)
    row["selected_data"] = [data_ledger_record_to_dict(record) for record in schedule.selected_data]
    return row


def build_research_schedule(
    option: OptionCard,
    data_records: list[DataLedgerRecord],
    templates: list[TemplateRecord],
    region: str,
    delay: int,
    max_data: int = 5,
    templates_per_data: int = 2,
    batch_size: int = 30,
) -> ResearchSchedule:
    """Input: option, ledger, templates, scope. Output: ResearchSchedule. Create a concrete research schedule."""
    selected_data = select_data_for_research(data_records, option.primary_incentive, region, delay, max_data)
    template_matches: list[dict[str, Any]] = []
    for record in selected_data:
        matched = select_templates_for_data(templates, record, option.primary_incentive, templates_per_data)
        for template in matched:
            template_matches.append(
                {
                    "field_id": record.field_id,
                    "dataset_id": record.dataset_id,
                    "template_id": template.template_id,
                    "skeleton": template.skeleton,
                    "hypothesis": template.hypothesis,
                    "correlation_risk": template.correlation_risk,
                }
            )
    return ResearchSchedule(
        option_title=option.title,
        primary_incentive=option.primary_incentive,
        region=region,
        delay=int(delay),
        batch_size=int(batch_size),
        selected_data=selected_data,
        template_matches=template_matches,
        local_gates=list(DEFAULT_LOCAL_GATES),
        stop_rules=[
            "stop_after_one_30_alpha_scout_batch_without_signal",
            "stop_repair_after_8_variants_without_metric_or_check_improvement",
            "promote_only_latest_hard_check_passes",
        ],
    )


def write_research_schedule(path: Path, schedule: ResearchSchedule, generated_at: str) -> Path:
    """Input: output path, schedule, timestamp. Output: path. Write Markdown research schedule."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Research Schedule",
        "",
        f"Generated at: `{generated_at}`",
        "",
        f"- Option: {schedule.option_title}",
        f"- Primary Incentive: `{schedule.primary_incentive}`",
        f"- Scope: {schedule.region} D{schedule.delay}",
        f"- Batch Size: {schedule.batch_size}",
        "",
        "## Selected Data",
    ]
    for record in schedule.selected_data:
        lines.append(f"- `{record.field_id}` from `{record.dataset_id}`; tags: {', '.join(record.semantic_tags)}; risk: {record.correlation_risk}")
    lines.extend(["", "## Template Matches"])
    for match in schedule.template_matches:
        lines.append(f"- `{match['template_id']}` on `{match['field_id']}`: {match['hypothesis']}")
    lines.extend(["", "## Local Gates"])
    for gate in schedule.local_gates:
        lines.append(f"- {gate}")
    lines.extend(["", "## Stop Rules"])
    for rule in schedule.stop_rules:
        lines.append(f"- {rule}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
```

- [ ] **Step 4: Run the tests to verify pass**

Run:

```powershell
python -m unittest tests.test_research_scheduler tests.test_template_library tests.test_data_ledger -v
```

Expected: 9 tests pass.

- [ ] **Step 5: Commit**

Run:

```powershell
git add BrainWorkflow/wqb/research_scheduler.py BrainWorkflow/tests/test_research_scheduler.py
git commit -m "add incentive aware research scheduler"
```

Expected: commit succeeds.

---

### Task 5: Workflow Change Proposals

**Files:**
- Create: `wqb/workflow_proposals.py`
- Test: `tests/test_workflow_proposals.py`

**Interfaces:**
- Consumes: issue/event dicts from research logs or benchmark summaries.
- Produces:
  - `WorkflowChangeProposal`
  - `workflow_change_proposal_to_dict(proposal: WorkflowChangeProposal) -> dict[str, Any]`
  - `proposal_from_issue(issue: dict[str, Any], generated_at: str) -> WorkflowChangeProposal`
  - `write_workflow_proposals(output_dir: Path, proposals: list[WorkflowChangeProposal]) -> tuple[Path, Path]`

- [ ] **Step 1: Write the failing test**

Create `tests/test_workflow_proposals.py`:

```python
import json
import tempfile
import unittest
from pathlib import Path

from wqb.workflow_proposals import (
    proposal_from_issue,
    workflow_change_proposal_to_dict,
    write_workflow_proposals,
)


class WorkflowProposalsTest(unittest.TestCase):
    def test_proposal_from_correlation_issue(self):
        issue = {
            "issue_type": "prod_correlation_cluster",
            "summary": "Three event templates failed production correlation.",
            "evidence_paths": ["runs/20260710_scout/all_alphas.jsonl"],
            "affected_modules": ["template_library", "benchmark"],
        }

        proposal = proposal_from_issue(issue, "2026-07-10T00:00:00Z")

        self.assertEqual(proposal.status, "proposed")
        self.assertIn("production correlation", proposal.proposed_rule_change.lower())
        self.assertIn("template_library", proposal.affected_modules)

    def test_write_workflow_proposals_creates_jsonl_and_markdown(self):
        proposal = proposal_from_issue(
            {
                "issue_type": "pnl_signal_misclassified",
                "summary": "Stable PnL was discarded because fitness was below threshold.",
                "evidence_paths": ["runs/20260710_repair/summary.json"],
                "affected_modules": ["benchmark"],
            },
            "2026-07-10T00:00:00Z",
        )
        with tempfile.TemporaryDirectory() as tmp:
            jsonl_path, markdown_path = write_workflow_proposals(Path(tmp), [proposal])
            rows = [json.loads(line) for line in jsonl_path.read_text(encoding="utf-8").splitlines()]
            markdown = markdown_path.read_text(encoding="utf-8")

        self.assertEqual(rows[0]["status"], "proposed")
        self.assertIn("Stable PnL", markdown)
        self.assertIn("User Decision Options", markdown)
        self.assertEqual(workflow_change_proposal_to_dict(proposal)["issue_type"], "pnl_signal_misclassified")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify failure**

Run:

```powershell
python -m unittest tests.test_workflow_proposals -v
```

Expected: fail with `ModuleNotFoundError: No module named 'wqb.workflow_proposals'`.

- [ ] **Step 3: Implement `wqb/workflow_proposals.py`**

Create `wqb/workflow_proposals.py`:

```python
from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any


PROPOSAL_JSONL = "workflow_change_proposals.jsonl"
PROPOSAL_MARKDOWN = "workflow_change_proposals.md"


@dataclass(frozen=True)
class WorkflowChangeProposal:
    proposal_id: str
    generated_at: str
    issue_type: str
    title: str
    trigger: str
    evidence_paths: list[str]
    affected_modules: list[str]
    proposed_rule_change: str
    expected_benefit: str
    risk: str
    required_code_changes: list[str]
    required_knowledge_updates: list[str]
    user_decision_options: list[str]
    status: str


def workflow_change_proposal_to_dict(proposal: WorkflowChangeProposal) -> dict[str, Any]:
    """Input: WorkflowChangeProposal. Output: dict[str, Any]. Convert proposal to JSON-safe data."""
    return asdict(proposal)


def _rule_text(issue_type: str, summary: str) -> tuple[str, str, str]:
    """Input: issue type and summary. Output: rule, benefit, risk. Map repeated issue to proposal text."""
    normalized = issue_type.lower()
    if "prod_correlation" in normalized:
        return (
            "Down-rank data-template pairs that repeatedly fail production correlation, and require a distinct data source, operator skeleton, or economic hypothesis before reusing them.",
            "Reduces wasted production-correlation checks and pushes novelty upstream.",
            "May suppress a repairable family if the evidence window is too small.",
        )
    if "self_correlation" in normalized:
        return (
            "Require local self-correlation proxy review before scheduling data or templates overlapping with submitted alpha families.",
            "Reduces candidate loss from avoidable self-correlation failures.",
            "May over-penalize fields that can pass with a materially better Sharpe.",
        )
    if "pnl_signal" in normalized:
        return (
            "Increase repair priority when stable PnL evidence exists even if a single metric is below threshold.",
            "Prevents discarding signal-bearing near-miss alphas.",
            "May spend repair budget on visually appealing but fragile in-sample signals.",
        )
    return (
        f"Review this issue and add a workflow rule if it repeats: {summary}",
        "Captures new workflow knowledge before the same issue recurs.",
        "Manual review is needed because the issue class is not yet mapped.",
    )


def proposal_from_issue(issue: dict[str, Any], generated_at: str) -> WorkflowChangeProposal:
    """Input: issue dict and timestamp. Output: proposal. Convert one research issue into a reviewable rule proposal."""
    issue_type = str(issue.get("issue_type", "manual_review"))
    summary = str(issue.get("summary", "Unclassified workflow issue."))
    evidence_paths = [str(item) for item in issue.get("evidence_paths", []) if str(item)]
    affected_modules = [str(item) for item in issue.get("affected_modules", []) if str(item)]
    proposed_rule_change, expected_benefit, risk = _rule_text(issue_type, summary)
    proposal_id = f"{generated_at[:10]}-{issue_type.replace('_', '-')}"
    return WorkflowChangeProposal(
        proposal_id=proposal_id,
        generated_at=generated_at,
        issue_type=issue_type,
        title=summary,
        trigger=summary,
        evidence_paths=evidence_paths,
        affected_modules=affected_modules,
        proposed_rule_change=proposed_rule_change,
        expected_benefit=expected_benefit,
        risk=risk,
        required_code_changes=affected_modules,
        required_knowledge_updates=["knowledge/wiki/50_benchmarks", "knowledge/wiki/60_workflows"],
        user_decision_options=["accept", "reject", "revise", "defer"],
        status="proposed",
    )


def _proposal_markdown(proposal: WorkflowChangeProposal) -> str:
    """Input: proposal. Output: Markdown string. Render one workflow-change proposal for review."""
    evidence = "\n".join(f"- `{path}`" for path in proposal.evidence_paths) or "- none recorded"
    modules = ", ".join(proposal.affected_modules) or "manual_review"
    options = ", ".join(proposal.user_decision_options)
    return (
        f"## {proposal.title}\n\n"
        f"- Proposal ID: `{proposal.proposal_id}`\n"
        f"- Status: `{proposal.status}`\n"
        f"- Issue Type: `{proposal.issue_type}`\n"
        f"- Affected Modules: {modules}\n\n"
        f"### Trigger\n{proposal.trigger}\n\n"
        f"### Evidence\n{evidence}\n\n"
        f"### Proposed Rule Change\n{proposal.proposed_rule_change}\n\n"
        f"### Expected Benefit\n{proposal.expected_benefit}\n\n"
        f"### Risk\n{proposal.risk}\n\n"
        f"### User Decision Options\n{options}\n"
    )


def write_workflow_proposals(output_dir: Path, proposals: list[WorkflowChangeProposal]) -> tuple[Path, Path]:
    """Input: output dir and proposals. Output: JSONL and Markdown paths. Persist workflow proposal artifacts."""
    output_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = output_dir / PROPOSAL_JSONL
    markdown_path = output_dir / PROPOSAL_MARKDOWN
    with jsonl_path.open("w", encoding="utf-8") as handle:
        for proposal in proposals:
            handle.write(json.dumps(workflow_change_proposal_to_dict(proposal), ensure_ascii=False, sort_keys=True) + "\n")
    markdown = ["# Workflow Change Proposals", ""]
    for proposal in proposals:
        markdown.append(_proposal_markdown(proposal))
    markdown_path.write_text("\n\n".join(markdown), encoding="utf-8")
    return jsonl_path, markdown_path
```

- [ ] **Step 4: Run the tests to verify pass**

Run:

```powershell
python -m unittest tests.test_workflow_proposals -v
```

Expected: 2 tests pass.

- [ ] **Step 5: Commit**

Run:

```powershell
git add BrainWorkflow/wqb/workflow_proposals.py BrainWorkflow/tests/test_workflow_proposals.py
git commit -m "add workflow change proposals"
```

Expected: commit succeeds.

---

### Task 6: CLI Foundation Commands

**Files:**
- Modify: `wqb/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes:
  - `default_knowledge_root() -> Path` from `wqb.cli`
  - `load_data_ledger(path: Path) -> list[DataLedgerRecord]`
  - `load_template_library(path: Path) -> list[TemplateRecord]`
  - `load_freshness_manifest(path: Path) -> list[KnowledgeFreshnessRecord]`
  - `evaluate_freshness(records: list[KnowledgeFreshnessRecord], today: date) -> list[KnowledgeFreshnessStatus]`
  - `write_freshness_report(path: Path, statuses: list[KnowledgeFreshnessStatus], generated_at: str) -> Path`
  - `build_research_schedule(...) -> ResearchSchedule`
  - `write_research_schedule(path: Path, schedule: ResearchSchedule, generated_at: str) -> Path`
  - `write_workflow_proposals(output_dir: Path, proposals: list[WorkflowChangeProposal]) -> tuple[Path, Path]`
- Produces:
  - `knowledge_health_check(knowledge_root: str | Path, manifest_path: str | Path, output_path: str | Path, today_value: str | None = None) -> dict[str, Any]`
  - `schedule_research_from_option(option_json: str | Path, knowledge_root: str | Path, output_path: str | Path, region: str, delay: int) -> dict[str, Any]`
  - argparse commands `knowledge-health-check` and `schedule-research`

- [ ] **Step 1: Add failing CLI tests**

Append these tests to `tests/test_cli.py` inside the existing test class:

```python
    def test_knowledge_health_check_writes_report_without_simulation(self):
        from wqb.cli import knowledge_health_check

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "freshness.json"
            report = root / "knowledge" / "wiki" / "80_maintenance" / "freshness_report.md"
            manifest.write_text(
                json.dumps(
                    [
                        {
                            "name": "data_ledger",
                            "path": "knowledge/wiki/20_semantics/data_ledger.jsonl",
                            "updated_at": "2026-07-08",
                            "max_age_days": 1,
                        }
                    ]
                ),
                encoding="utf-8",
            )

            result = knowledge_health_check(root, manifest, report, today_value="2026-07-10")

        self.assertEqual(result["stale_count"], 1)
        self.assertTrue(Path(result["report_path"]).exists())

    def test_schedule_research_from_option_uses_ledger_and_templates(self):
        from wqb.cli import schedule_research_from_option
        from wqb.principle_model import option_card_to_dict

        option = OptionCard(
            title="Explore current Power Pool boards",
            primary_incentive="power_pool",
            secondary_incentives=["genius"],
            why_now="Visible Power Pool boards include USA D1.",
            candidate_scope="USA D1 underused event data.",
            expected_asset_value="Simple alpha assets with lower criteria.",
            correlation_risk="Medium-high unless new data and distinct templates are used.",
            resource_cost="One 30-alpha scout batch.",
            evidence=[SourceEvidence("api", "/consultant/boards/power-pool", "Power Pool boards", "2026-07-10T00:00:00Z")],
            failure_modes=["Power Pool correlation failure."],
            decision_needed="Choose this option.",
            score=ScoreBreakdown(total=8.0, components={"power_pool": 8.0}, penalties={}, reasons=["Visible board."]),
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            option_path = root / "option.json"
            option_path.write_text(json.dumps(option_card_to_dict(option)), encoding="utf-8")
            ledger_dir = root / "wiki" / "20_semantics"
            template_dir = root / "wiki" / "30_templates"
            ledger_dir.mkdir(parents=True)
            template_dir.mkdir(parents=True)
            (ledger_dir / "data_ledger.jsonl").write_text(
                json.dumps(
                    {
                        "dataset_id": "news12",
                        "dataset_name": "News Events",
                        "field_id": "news12_sentiment_fast_d1",
                        "field_type": "MATRIX",
                        "region": "USA",
                        "delay": 1,
                        "universe": "TOP3000",
                        "semantic_tags": ["event", "sentiment", "fast_d1", "power_pool"],
                        "coverage": 0.82,
                        "alpha_count": 12,
                        "user_count": 4,
                        "simulation_usage_count": 1,
                        "submitted_usage_count": 0,
                        "last_used_at": "2026-07-09",
                        "best_result_label": "repairable_signal",
                        "correlation_risk": "medium",
                        "source_paths": ["raw"],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            (template_dir / "template_library.jsonl").write_text(
                json.dumps(
                    {
                        "template_id": "event_fast_delta_rank",
                        "hypothesis": "Fast event sentiment changes are incorporated gradually.",
                        "skeleton": "rank(ts_delta({field}, 1))",
                        "required_field_types": ["MATRIX"],
                        "compatible_semantic_tags": ["event", "sentiment", "fast_d1", "power_pool"],
                        "operator_tags": ["time_series_surprise"],
                        "status": "seed",
                        "correlation_risk": "low",
                        "repair_levers": ["group_neutralize"],
                        "source_paths": ["wiki"],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            output_path = root / "wiki" / "70_decisions" / "research_schedule.md"

            result = schedule_research_from_option(option_path, root, output_path, "USA", 1)

        self.assertEqual(result["selected_data_count"], 1)
        self.assertEqual(result["template_match_count"], 1)
        self.assertTrue(Path(result["schedule_path"]).exists())
```

Also ensure `tests/test_cli.py` imports these names if missing:

```python
import json
from pathlib import Path

from wqb.principle_model import OptionCard, ScoreBreakdown, SourceEvidence
```

- [ ] **Step 2: Run the focused CLI tests to verify failure**

Run:

```powershell
python -m unittest tests.test_cli -v
```

Expected: fail because `knowledge_health_check` and `schedule_research_from_option` are not defined.

- [ ] **Step 3: Modify `wqb/cli.py` imports**

Add or merge these imports near existing imports:

```python
from dataclasses import fields as dataclass_fields
from datetime import date

from wqb.data_ledger import load_data_ledger
from wqb.knowledge_freshness import evaluate_freshness, load_freshness_manifest, write_freshness_report
from wqb.research_scheduler import build_research_schedule, research_schedule_to_dict, write_research_schedule
from wqb.template_library import load_template_library
```

- [ ] **Step 4: Add helper functions to `wqb/cli.py`**

Add near `plan_research_options`:

```python
def _option_card_from_dict(row: dict[str, Any]) -> OptionCard:
    """Input: dict row. Output: OptionCard. Rebuild an option card from JSON for scheduling."""
    evidence = [SourceEvidence(**item) for item in row.get("evidence", [])]
    score = ScoreBreakdown(**row["score"])
    allowed = {field.name for field in dataclass_fields(OptionCard)}
    data = {key: value for key, value in row.items() if key in allowed}
    data["evidence"] = evidence
    data["score"] = score
    return OptionCard(**data)


def knowledge_health_check(
    knowledge_root: str | Path,
    manifest_path: str | Path,
    output_path: str | Path,
    today_value: str | None = None,
) -> dict[str, Any]:
    """Input: knowledge root, manifest path, output path, date string. Output: summary dict. Check compiled knowledge freshness."""
    root = Path(knowledge_root)
    manifest = Path(manifest_path)
    if not manifest.is_absolute():
        manifest = root / manifest
    output = Path(output_path)
    if not output.is_absolute():
        output = root / output
    current = date.fromisoformat(today_value) if today_value else date.today()
    records = load_freshness_manifest(manifest)
    statuses = evaluate_freshness(records, current)
    report = write_freshness_report(output, statuses, datetime.now(timezone.utc).replace(microsecond=0).isoformat())
    return {
        "record_count": len(statuses),
        "stale_count": len([status for status in statuses if status.stale]),
        "report_path": str(report),
    }


def schedule_research_from_option(
    option_json: str | Path,
    knowledge_root: str | Path,
    output_path: str | Path,
    region: str,
    delay: int,
) -> dict[str, Any]:
    """Input: option path, knowledge root, output path, region, delay. Output: summary dict. Build schedule from compiled knowledge."""
    root = Path(knowledge_root)
    option = _option_card_from_dict(json.loads(Path(option_json).read_text(encoding="utf-8")))
    ledger = load_data_ledger(root / "wiki" / "20_semantics" / "data_ledger.jsonl")
    templates = load_template_library(root / "wiki" / "30_templates" / "template_library.jsonl")
    schedule = build_research_schedule(option, ledger, templates, region=region, delay=delay)
    output = Path(output_path)
    if not output.is_absolute():
        output = root / output
    schedule_path = write_research_schedule(output, schedule, datetime.now(timezone.utc).replace(microsecond=0).isoformat())
    row = research_schedule_to_dict(schedule)
    return {
        "schedule_path": str(schedule_path),
        "selected_data_count": len(row["selected_data"]),
        "template_match_count": len(row["template_matches"]),
        "local_gates": row["local_gates"],
    }
```

If `OptionCard`, `ScoreBreakdown`, `SourceEvidence`, `datetime`, `timezone`, `json`, `Path`, or `Any` are already imported in `wqb/cli.py`, merge the imports rather than duplicating them.

- [ ] **Step 5: Extend argparse in `wqb/cli.py`**

Add command names where the parser defines `choices`:

```python
"knowledge-health-check",
"schedule-research",
```

Add parser arguments:

```python
    parser.add_argument("--freshness-manifest", default="wiki/80_maintenance/freshness_manifest.json")
    parser.add_argument("--freshness-report", default="wiki/80_maintenance/freshness_report.md")
    parser.add_argument("--today", default="")
    parser.add_argument("--option-json", default="")
    parser.add_argument("--schedule-output", default="wiki/70_decisions/research_schedule.md")
    parser.add_argument("--schedule-region", default="USA")
    parser.add_argument("--schedule-delay", type=int, default=1)
```

Add dispatcher branches in `main()`:

```python
    elif args.command == "knowledge-health-check":
        result = knowledge_health_check(
            default_knowledge_root(),
            args.freshness_manifest,
            args.freshness_report,
            today_value=args.today or None,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.command == "schedule-research":
        if not args.option_json:
            raise SystemExit("--option-json is required for schedule-research")
        result = schedule_research_from_option(
            args.option_json,
            default_knowledge_root(),
            args.schedule_output,
            args.schedule_region,
            args.schedule_delay,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
```

- [ ] **Step 6: Run tests to verify pass**

Run:

```powershell
python -m unittest tests.test_cli tests.test_research_scheduler tests.test_knowledge_freshness tests.test_template_library tests.test_data_ledger -v
```

Expected: all focused tests pass.

- [ ] **Step 7: Commit**

Run:

```powershell
git add BrainWorkflow/wqb/cli.py BrainWorkflow/tests/test_cli.py
git commit -m "add long term workflow cli helpers"
```

Expected: commit succeeds.

---

### Task 7: Knowledge Seed Files And Documentation

**Files:**
- Create: `docs/knowledge/freshness_manifest.example.json`
- Create: `docs/knowledge/data_ledger.example.jsonl`
- Create: `docs/knowledge/template_library.example.jsonl`
- Modify: `README.md`
- Modify: `knowledge/wiki/60_workflows/workflow_optimization_backlog.md` only if this shared vault file is in scope for the execution session.

**Interfaces:**
- Consumes: modules from Tasks 1-6.
- Produces: example files that make the foundation layer understandable and testable without live platform access.

- [ ] **Step 1: Create example freshness manifest**

Create `docs/knowledge/freshness_manifest.example.json`:

```json
[
  {
    "name": "data_ledger",
    "path": "knowledge/wiki/20_semantics/data_ledger.jsonl",
    "updated_at": "2026-07-10",
    "max_age_days": 1
  },
  {
    "name": "template_library",
    "path": "knowledge/wiki/30_templates/template_library.jsonl",
    "updated_at": "2026-07-10",
    "max_age_days": 7
  },
  {
    "name": "benchmark_rules",
    "path": "knowledge/wiki/50_benchmarks",
    "updated_at": "2026-07-10",
    "max_age_days": 3
  }
]
```

- [ ] **Step 2: Create example Data Ledger JSONL**

Create `docs/knowledge/data_ledger.example.jsonl` with this single line:

```json
{"alpha_count":12,"best_result_label":"repairable_signal","correlation_risk":"medium","coverage":0.82,"dataset_id":"news12","dataset_name":"News Events","delay":1,"field_id":"news12_sentiment_fast_d1","field_type":"MATRIX","last_used_at":"2026-07-09","region":"USA","semantic_tags":["event","sentiment","fast_d1","power_pool"],"simulation_usage_count":1,"source_paths":["knowledge/raw/platform/learn/2026-07-09/documentation_pages.md"],"submitted_usage_count":0,"universe":"TOP3000","user_count":4}
```

- [ ] **Step 3: Create example Template Library JSONL**

Create `docs/knowledge/template_library.example.jsonl` with this single line:

```json
{"compatible_semantic_tags":["event","sentiment","fast_d1","power_pool"],"correlation_risk":"low","hypothesis":"Fast event sentiment changes are incorporated gradually.","operator_tags":["time_series_surprise","cross_sectional_normalizer"],"repair_levers":["group_neutralize","window_5"],"required_field_types":["MATRIX"],"skeleton":"rank(ts_delta({field}, 1))","source_paths":["knowledge/wiki/30_templates/template_families.md"],"status":"seed","template_id":"event_fast_delta_rank"}
```

- [ ] **Step 4: Update README**

Append this section to `README.md`:

```markdown
## Long-Term Workflow Foundation

The long-term workflow separates research runs from knowledge maintenance.

Research commands consume compiled knowledge artifacts such as Data Ledger, Template Library, benchmark rules, and principle pages. They should not trigger full Learn/forum/operator recapture or full wiki compilation.

Maintenance commands refresh raw sources, update compiled ledgers, run freshness checks, and generate workflow-change proposals for user review.

Example foundation files live under `docs/knowledge/`:

- `freshness_manifest.example.json`
- `data_ledger.example.jsonl`
- `template_library.example.jsonl`
```

- [ ] **Step 5: Run documentation verification**

Run:

```powershell
Test-Path docs\knowledge\freshness_manifest.example.json
Test-Path docs\knowledge\data_ledger.example.jsonl
Test-Path docs\knowledge\template_library.example.jsonl
python -m json.tool docs\knowledge\freshness_manifest.example.json > $null
python -c "import json, pathlib; [json.loads(line) for line in pathlib.Path('docs/knowledge/data_ledger.example.jsonl').read_text().splitlines() if line.strip()]; [json.loads(line) for line in pathlib.Path('docs/knowledge/template_library.example.jsonl').read_text().splitlines() if line.strip()]"
```

Expected: three `True` lines and no Python errors.

- [ ] **Step 6: Commit**

Run:

```powershell
git add BrainWorkflow/README.md BrainWorkflow/docs/knowledge/freshness_manifest.example.json BrainWorkflow/docs/knowledge/data_ledger.example.jsonl BrainWorkflow/docs/knowledge/template_library.example.jsonl
git commit -m "document long term workflow foundation artifacts"
```

Expected: commit succeeds.

---

### Task 8: Full Verification And Publish

**Files:**
- Verify every file changed by Tasks 1-7.

**Interfaces:**
- Consumes: all previous task outputs.
- Produces: pushed branch or a clear network/authentication blocker.

- [ ] **Step 1: Run full unit tests**

Run:

```powershell
python -m unittest discover -s tests -q
```

Expected: all tests pass.

- [ ] **Step 2: Run static syntax checks for new modules**

Run:

```powershell
python -m py_compile wqb\data_ledger.py wqb\template_library.py wqb\knowledge_freshness.py wqb\research_scheduler.py wqb\workflow_proposals.py wqb\cli.py
```

Expected: exit code 0 and no syntax errors.

- [ ] **Step 3: Run Git whitespace check**

Run from `C:\Users\oytl\Desktop\pyproject\brain\skills-and-workflows`:

```powershell
git diff --check
```

Expected: no whitespace errors. Windows CRLF conversion warnings are acceptable if there are no reported file-and-line errors.

- [ ] **Step 4: Check worktree state**

Run:

```powershell
git status --short --branch
```

Expected: current branch is `agent/brainworkflow-phase2` and the worktree is clean after commits.

- [ ] **Step 5: Push branch**

Run:

```powershell
git -c http.proxy=http://127.0.0.1:7890 -c https.proxy=http://127.0.0.1:7890 push -u origin agent/brainworkflow-phase2
```

Expected: branch push succeeds. If the network resets, retry `git ls-remote` once through the same proxy before reporting a blocker.

- [ ] **Step 6: Verify remote pointer**

Run:

```powershell
git -c http.proxy=http://127.0.0.1:7890 -c https.proxy=http://127.0.0.1:7890 ls-remote --heads origin agent/brainworkflow-phase2
```

Expected: output contains a commit hash and `refs/heads/agent/brainworkflow-phase2`.

---

## Self-Review Checklist

- Spec coverage:
  - Data Ledger is covered by Task 1.
  - Template Library and operator/data matching are covered by Task 2.
  - Runtime freshness checks without full compile are covered by Task 3 and Task 6.
  - Research scheduling from selected option is covered by Task 4 and Task 6.
  - Workflow-change proposals for user review are covered by Task 5.
  - Research commands and maintenance helper commands are covered by Task 6.
  - Example knowledge artifacts and operator handoff documentation are covered by Task 7.
  - Heavy raw-source recapture and full wiki compile automation are intentionally excluded from this foundation plan and should receive a later plan.
- Type consistency:
  - `DataLedgerRecord` is defined in Task 1 and consumed by Tasks 2 and 4.
  - `TemplateRecord` is defined in Task 2 and consumed by Task 4.
  - `ResearchSchedule` is defined in Task 4 and written by Task 6.
  - `WorkflowChangeProposal` is defined and persisted in Task 5.
  - CLI helper signatures in Task 6 consume the exact loader and writer names defined in earlier tasks.
