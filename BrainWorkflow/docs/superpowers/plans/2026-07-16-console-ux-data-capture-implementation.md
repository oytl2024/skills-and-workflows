# Console UX And Data Field Capture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a usable local BrainWorkflow console with selectable research decisions and a formal all-scope platform data-field raw capture -> data ledger compile maintenance path.

**Architecture:** Keep the existing Python standard-library console and Orchestrator model. Add a focused raw capture module, a separate data ledger compiler module, CLI commands, console job mappings, and a clearer HTML console that drives workflow actions from durable option cards and compiled knowledge state.

**Tech Stack:** Python standard library, `unittest`, existing `wqb.client.WQBClient`, existing `wqb.data_catalog` API helpers, existing Obsidian `knowledge/raw` and `knowledge/wiki` layout, existing local `http.server` console.

## Global Constraints

- Preserve the existing Scout -> Seed -> Discovery -> Repair -> Submit research workflow and Orchestrator ownership model.
- Do not add React, npm, or a frontend build pipeline in this slice.
- Do not run live simulations, alpha submission, or candidate repair behavior changes.
- Do not trigger full platform data recapture during daily research startup.
- `capture-platform-data-fields` is a live API action and requires explicit `--enable-live-api`.
- `compile-data-ledger` is local-only and reads raw data-field snapshots.
- Normal console research start must not ask the user to type `option-1`, objective strings, region, delay, or universe.
- Raw platform data-field materials are stored under `knowledge/raw/platform/data_fields/YYYY-MM-DD/`.
- Failed ledger compile must not delete or overwrite the last valid ledger.
- Use `python -c "import sys, runpy; sys.platform='linux'; runpy.run_module('unittest', run_name='__main__')"` for test discovery on this Windows Codex setup when direct unittest startup imports `_overlapped`.

---

## File Structure

Create:

- `BrainWorkflow/wqb/data_field_capture.py`: scope matrix expansion, raw capture loop, raw JSONL/Markdown writers, recoverable API error recording.
- `BrainWorkflow/wqb/data_ledger_compile.py`: compile raw `data_fields.jsonl` snapshots into `wiki/20_semantics/data_ledger.jsonl`, `data_ledger.md`, and freshness manifest updates.
- `BrainWorkflow/tests/test_data_field_capture.py`: tests for scope matrix, raw file output, pagination-style fake responses, recoverable invalid scope recording.
- `BrainWorkflow/tests/test_data_ledger_compile.py`: tests for raw-to-ledger aggregation, source path preservation, partial status, no-overwrite validation.

Modify:

- `BrainWorkflow/wqb/cli.py`: add `capture-platform-data-fields` and `compile-data-ledger` commands, args, dispatch functions, live gate.
- `BrainWorkflow/wqb/console_jobs.py`: map new console actions to CLI commands.
- `BrainWorkflow/wqb/console_server.py`: redesign dashboard HTML, validate selected option cards, gate data capture, build workflow start from selected cards.
- `BrainWorkflow/wqb/console_state.py`: add data coverage summary from raw capture manifests and expose it to the dashboard.
- `BrainWorkflow/tests/test_cli.py`: CLI parse and dispatch coverage for the new commands.
- `BrainWorkflow/tests/test_console_jobs.py`: action mapping tests.
- `BrainWorkflow/tests/test_console_server.py`: UI and action gate tests.
- `BrainWorkflow/tests/test_console_state.py`: data coverage read model tests.
- `BrainWorkflow/docs/operations/operating_guide.md`: operator instructions.
- `BrainWorkflow/docs/operations/maintainer_handoff.md`: maintainer context and recovery guidance.
- `BrainWorkflow/README.md`: link to updated console and data maintenance docs.
- Root `todo.md` and root `milestone.md`: progress and recovery notes outside the repo.

---

### Task 1: Platform Data Field Raw Capture Module

**Files:**
- Create: `BrainWorkflow/wqb/data_field_capture.py`
- Test: `BrainWorkflow/tests/test_data_field_capture.py`

**Interfaces:**
- Consumes: `wqb.data_catalog.fetch_operators`, `wqb.data_catalog.fetch_data_sets`, `wqb.data_catalog.fetch_data_fields`.
- Produces:
  - `CaptureScope(instrument_type: str, region: str, delay: int, universe: str)`
  - `build_capture_scopes(...) -> list[CaptureScope]`
  - `capture_platform_data_fields(client: Any, knowledge_root: str | Path, generated_at: str | None = None, instrument_types: list[str] | None = None, regions: list[str] | None = None, delays: list[int] | None = None, universes: list[str] | None = None, max_scopes: int = 0, max_datasets_per_scope: int = 0, max_fields_per_dataset: int = 0, resume_capture: bool = False) -> dict[str, Any]`

- [ ] **Step 1: Write failing tests for scope expansion and raw capture files**

Add this test file:

```python
import json
import tempfile
import unittest
from pathlib import Path

from wqb.data_field_capture import build_capture_scopes, capture_platform_data_fields


class FakeCaptureClient:
    def __init__(self):
        self.paths = []

    def get_json(self, path):
        self.paths.append(path)
        if path == "/operators":
            return {"results": [{"name": "rank"}, {"name": "ts_delta"}]}
        if path.startswith("/data-sets?"):
            if "region=EUR" in path:
                raise RuntimeError("scope rejected")
            return {
                "results": [
                    {"id": "fundamental3", "name": "Fundamentals", "category": "fundamental"},
                    {"id": "news7", "name": "News", "category": "news"},
                ]
            }
        if path.startswith("/data-fields?") and "dataset.id=fundamental3" in path:
            return {
                "results": [
                    {
                        "id": "fnd3_q_cash_fast_d1",
                        "type": "MATRIX",
                        "coverage": 0.84,
                        "alphaCount": 1,
                        "userCount": 1,
                        "dataset": {"id": "fundamental3", "name": "Fundamentals", "category": "fundamental"},
                        "description": "Quarterly cash",
                    }
                ]
            }
        if path.startswith("/data-fields?") and "dataset.id=news7" in path:
            return {"results": []}
        return {"results": []}


class DataFieldCaptureTests(unittest.TestCase):
    def test_build_capture_scopes_expands_matrix_and_applies_limit(self):
        scopes = build_capture_scopes(
            instrument_types=["EQUITY"],
            regions=["USA", "EUR"],
            delays=[0, 1],
            universes=["TOP3000", "TOP500"],
            max_scopes=3,
        )

        self.assertEqual(len(scopes), 3)
        self.assertEqual(scopes[0].region, "USA")
        self.assertEqual(scopes[0].delay, 0)
        self.assertEqual(scopes[0].universe, "TOP3000")

    def test_capture_platform_data_fields_writes_raw_snapshot_and_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "knowledge"
            summary = capture_platform_data_fields(
                FakeCaptureClient(),
                root,
                generated_at="2026-07-16T08:30:00+00:00",
                instrument_types=["EQUITY"],
                regions=["USA", "EUR"],
                delays=[1],
                universes=["TOP3000"],
                max_fields_per_dataset=10,
            )
            capture_dir = Path(summary["capture_dir"])

            self.assertTrue((capture_dir / "index.md").exists())
            self.assertTrue((capture_dir / "manifest.json").exists())
            self.assertTrue((capture_dir / "operators.json").exists())
            self.assertTrue((capture_dir / "scopes.jsonl").exists())
            self.assertTrue((capture_dir / "data_sets.jsonl").exists())
            self.assertTrue((capture_dir / "data_fields.jsonl").exists())
            self.assertTrue((capture_dir / "errors.jsonl").exists())

            fields = [json.loads(line) for line in (capture_dir / "data_fields.jsonl").read_text(encoding="utf-8").splitlines()]
            errors = [json.loads(line) for line in (capture_dir / "errors.jsonl").read_text(encoding="utf-8").splitlines()]

        self.assertEqual(summary["field_count"], 1)
        self.assertEqual(summary["error_count"], 1)
        self.assertEqual(fields[0]["field"]["id"], "fnd3_q_cash_fast_d1")
        self.assertEqual(fields[0]["scope"]["region"], "USA")
        self.assertIn("scope rejected", errors[0]["message"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests and confirm RED**

Run:

```powershell
Set-Location 'C:\Users\oytl\Desktop\pyproject\brain\skills-and-workflows\BrainWorkflow'
python -c "import sys, runpy; sys.platform='linux'; runpy.run_module('unittest', run_name='__main__')" tests.test_data_field_capture -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'wqb.data_field_capture'`.

- [ ] **Step 3: Implement raw capture module**

Create `BrainWorkflow/wqb/data_field_capture.py` with:

```python
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from wqb.data_catalog import fetch_data_fields, fetch_data_sets, fetch_operators


DEFAULT_CAPTURE_INSTRUMENT_TYPES = ("EQUITY",)
DEFAULT_CAPTURE_REGIONS = ("USA", "EUR", "ASI", "GLB")
DEFAULT_CAPTURE_DELAYS = (0, 1)
DEFAULT_CAPTURE_UNIVERSES = ("TOP3000", "TOP2000", "TOP1000", "TOP500", "TOP200")
RAW_CAPTURE_ROOT = Path("raw") / "platform" / "data_fields"
SAFE_PAGE_LIMIT = 50


@dataclass(frozen=True)
class CaptureScope:
    instrument_type: str
    region: str
    delay: int
    universe: str


def _now() -> str:
    """Input: none. Output: str. Return a UTC timestamp for data capture records."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _capture_day(generated_at: str) -> str:
    """Input: timestamp. Output: yyyy-mm-dd str. Choose the raw capture directory date."""
    return generated_at[:10]


def build_capture_scopes(
    instrument_types: list[str] | None = None,
    regions: list[str] | None = None,
    delays: list[int] | None = None,
    universes: list[str] | None = None,
    max_scopes: int = 0,
) -> list[CaptureScope]:
    """Input: optional scope lists. Output: CaptureScope list. Expand the platform data-field capture matrix."""
    selected_instruments = instrument_types or list(DEFAULT_CAPTURE_INSTRUMENT_TYPES)
    selected_regions = regions or list(DEFAULT_CAPTURE_REGIONS)
    selected_delays = delays or list(DEFAULT_CAPTURE_DELAYS)
    selected_universes = universes or list(DEFAULT_CAPTURE_UNIVERSES)
    scopes = [
        CaptureScope(str(instrument), str(region), int(delay), str(universe))
        for instrument in selected_instruments
        for region in selected_regions
        for delay in selected_delays
        for universe in selected_universes
    ]
    if max_scopes > 0:
        return scopes[: int(max_scopes)]
    return scopes


def _write_json(path: Path, payload: Any) -> None:
    """Input: path and payload. Output: none. Write stable JSON for raw capture artifacts."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _append_jsonl(path: Path, row: dict[str, Any]) -> None:
    """Input: path and row. Output: none. Append one JSONL row for resumable raw capture."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _clear_outputs(capture_dir: Path) -> None:
    """Input: capture directory. Output: none. Start a clean raw capture when resume is disabled."""
    for name in ("scopes.jsonl", "data_sets.jsonl", "data_fields.jsonl", "errors.jsonl"):
        path = capture_dir / name
        if path.exists():
            path.unlink()


def _scope_dict(scope: CaptureScope) -> dict[str, Any]:
    """Input: CaptureScope. Output: dict. Convert scope to a JSON-safe row."""
    return asdict(scope)


def _error_row(scope: CaptureScope | None, endpoint: str, error: Exception, generated_at: str) -> dict[str, Any]:
    """Input: scope, endpoint, error, timestamp. Output: JSON row. Preserve recoverable capture failures."""
    return {
        "generated_at": generated_at,
        "scope": _scope_dict(scope) if scope is not None else {},
        "endpoint": endpoint,
        "message": str(error),
        "error_type": type(error).__name__,
    }


def _write_index(capture_dir: Path, summary: dict[str, Any]) -> None:
    """Input: capture dir and summary. Output: none. Write the human-readable raw capture index."""
    lines = [
        "# Platform Data Field Capture",
        "",
        f"Generated at: `{summary['generated_at']}`",
        "",
        f"- Scope Count: `{summary['scope_count']}`",
        f"- Dataset Count: `{summary['data_set_count']}`",
        f"- Field Count: `{summary['field_count']}`",
        f"- Error Count: `{summary['error_count']}`",
        f"- Capture Status: `{summary['status']}`",
        "",
        "Next command:",
        "",
        "```powershell",
        "python -m wqb.cli compile-data-ledger --knowledge-root <knowledge-root>",
        "```",
    ]
    (capture_dir / "index.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def capture_platform_data_fields(
    client: Any,
    knowledge_root: str | Path,
    generated_at: str | None = None,
    instrument_types: list[str] | None = None,
    regions: list[str] | None = None,
    delays: list[int] | None = None,
    universes: list[str] | None = None,
    max_scopes: int = 0,
    max_datasets_per_scope: int = 0,
    max_fields_per_dataset: int = 0,
    resume_capture: bool = False,
) -> dict[str, Any]:
    """Input: client, vault root, scope filters, limits. Output: summary dict. Capture platform data fields into raw."""
    generated = generated_at or _now()
    root = Path(knowledge_root)
    capture_dir = root / RAW_CAPTURE_ROOT / _capture_day(generated)
    capture_dir.mkdir(parents=True, exist_ok=True)
    if not resume_capture:
        _clear_outputs(capture_dir)

    operators: list[dict[str, Any]] = []
    error_count = 0
    try:
        operators = fetch_operators(client)
        _write_json(capture_dir / "operators.json", {"generated_at": generated, "operators": operators})
    except Exception as error:
        error_count += 1
        _append_jsonl(capture_dir / "errors.jsonl", _error_row(None, "/operators", error, generated))
        _write_json(capture_dir / "operators.json", {"generated_at": generated, "operators": []})

    scopes = build_capture_scopes(instrument_types, regions, delays, universes, max_scopes=max_scopes)
    data_set_count = 0
    field_count = 0

    for scope in scopes:
        scope_row = {"generated_at": generated, "scope": _scope_dict(scope), "status": "started"}
        try:
            data_sets = fetch_data_sets(
                client,
                scope.instrument_type,
                scope.region,
                int(scope.delay),
                scope.universe,
                limit=SAFE_PAGE_LIMIT,
            )
            if max_datasets_per_scope > 0:
                data_sets = data_sets[: int(max_datasets_per_scope)]
            scope_row.update({"status": "completed", "data_set_count": len(data_sets)})
            _append_jsonl(capture_dir / "scopes.jsonl", scope_row)
        except Exception as error:
            error_count += 1
            scope_row.update({"status": "failed", "data_set_count": 0, "message": str(error)})
            _append_jsonl(capture_dir / "scopes.jsonl", scope_row)
            _append_jsonl(capture_dir / "errors.jsonl", _error_row(scope, "/data-sets", error, generated))
            continue

        for data_set in data_sets:
            data_set_count += 1
            dataset_id = str(data_set.get("id", ""))
            _append_jsonl(
                capture_dir / "data_sets.jsonl",
                {"generated_at": generated, "scope": _scope_dict(scope), "data_set": data_set},
            )
            if not dataset_id:
                continue
            try:
                fields = fetch_data_fields(
                    client,
                    scope.instrument_type,
                    scope.region,
                    int(scope.delay),
                    scope.universe,
                    dataset_id=dataset_id,
                    limit=SAFE_PAGE_LIMIT,
                    max_records=max_fields_per_dataset if max_fields_per_dataset > 0 else 1000000,
                )
            except Exception as error:
                error_count += 1
                _append_jsonl(capture_dir / "errors.jsonl", _error_row(scope, f"/data-fields?dataset.id={dataset_id}", error, generated))
                continue
            for field in fields:
                field_count += 1
                _append_jsonl(
                    capture_dir / "data_fields.jsonl",
                    {
                        "generated_at": generated,
                        "scope": _scope_dict(scope),
                        "data_set": data_set,
                        "field": field,
                        "endpoint": "/data-fields",
                    },
                )

    summary = {
        "generated_at": generated,
        "capture_dir": str(capture_dir),
        "scope_count": len(scopes),
        "operator_count": len(operators),
        "data_set_count": data_set_count,
        "field_count": field_count,
        "error_count": error_count,
        "status": "completed" if error_count == 0 else "completed_with_warnings",
    }
    _write_json(capture_dir / "manifest.json", summary)
    errors_path = capture_dir / "errors.jsonl"
    if not errors_path.exists():
        errors_path.write_text("", encoding="utf-8")
    _write_index(capture_dir, summary)
    return summary
```

- [ ] **Step 4: Run tests and confirm GREEN**

Run:

```powershell
python -c "import sys, runpy; sys.platform='linux'; runpy.run_module('unittest', run_name='__main__')" tests.test_data_field_capture -v
```

Expected: PASS.

- [ ] **Step 5: Commit Task 1**

```powershell
git add BrainWorkflow/wqb/data_field_capture.py BrainWorkflow/tests/test_data_field_capture.py
git commit -m "add platform data field raw capture"
```

---

### Task 2: Compile Data Ledger From Raw Captures

**Files:**
- Create: `BrainWorkflow/wqb/data_ledger_compile.py`
- Test: `BrainWorkflow/tests/test_data_ledger_compile.py`

**Interfaces:**
- Consumes:
  - raw files from `knowledge/raw/platform/data_fields/YYYY-MM-DD/`
  - `wqb.semantics.field_semantic_embedding`
  - `wqb.data_ledger.DataLedgerRecord`, `write_data_ledger_markdown`, `load_data_ledger`
- Produces:
  - `compile_data_ledger_from_raw(knowledge_root: str | Path, capture_dir: str | Path | None = None, generated_at: str | None = None) -> dict[str, Any]`
  - `latest_capture_dir(knowledge_root: str | Path) -> Path`

- [ ] **Step 1: Write failing tests for raw aggregation and no-overwrite validation**

Add:

```python
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from wqb.data_ledger import load_data_ledger
from wqb.data_ledger_compile import compile_data_ledger_from_raw, latest_capture_dir


def write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


class DataLedgerCompileTests(unittest.TestCase):
    def test_latest_capture_dir_selects_newest_data_field_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "knowledge"
            old = root / "raw" / "platform" / "data_fields" / "2026-07-15"
            new = root / "raw" / "platform" / "data_fields" / "2026-07-16"
            old.mkdir(parents=True)
            new.mkdir(parents=True)

            self.assertEqual(latest_capture_dir(root), new)

    def test_compile_data_ledger_from_raw_aggregates_scope_and_source_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "knowledge"
            capture = root / "raw" / "platform" / "data_fields" / "2026-07-16"
            rows = [
                {
                    "generated_at": "2026-07-16T08:00:00+00:00",
                    "scope": {"instrument_type": "EQUITY", "region": "USA", "delay": 1, "universe": "TOP3000"},
                    "data_set": {"id": "fundamental3", "name": "Fundamentals", "category": "fundamental"},
                    "field": {"id": "fnd3_q_cash_fast_d1", "type": "MATRIX", "coverage": 0.84, "alphaCount": 1, "userCount": 1, "description": "Quarterly cash"},
                },
                {
                    "generated_at": "2026-07-16T08:00:00+00:00",
                    "scope": {"instrument_type": "EQUITY", "region": "EUR", "delay": 0, "universe": "TOP500"},
                    "data_set": {"id": "fundamental3", "name": "Fundamentals", "category": "fundamental"},
                    "field": {"id": "fnd3_q_cash_fast_d1", "type": "MATRIX", "coverage": 0.72, "alphaCount": 3, "userCount": 2, "description": "Quarterly cash"},
                },
            ]
            write_jsonl(capture / "data_fields.jsonl", rows)
            (capture / "manifest.json").write_text(json.dumps({"status": "completed", "field_count": 2}), encoding="utf-8")

            summary = compile_data_ledger_from_raw(root, capture_dir=capture, generated_at="2026-07-16T09:00:00+00:00")
            ledger_path = root / "wiki" / "20_semantics" / "data_ledger.jsonl"
            records = load_data_ledger(ledger_path)
            raw_row = json.loads(ledger_path.read_text(encoding="utf-8").splitlines()[0])

        self.assertEqual(summary["record_count"], 1)
        self.assertEqual(records[0].field_id, "fnd3_q_cash_fast_d1")
        self.assertEqual(records[0].available_regions, ["EUR", "USA"])
        self.assertEqual(records[0].available_delays, [0, 1])
        self.assertEqual(records[0].available_universes, ["TOP3000", "TOP500"])
        self.assertIn("cash", records[0].semantic_tags)
        self.assertIn("raw/platform/data_fields/2026-07-16/data_fields.jsonl", raw_row["source_paths"][0])
        self.assertEqual(raw_row["source_quality"], "platform_raw_capture")
        self.assertEqual(raw_row["coverage_status"], "measured_raw")

    def test_compile_failure_keeps_existing_ledger(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "knowledge"
            capture = root / "raw" / "platform" / "data_fields" / "2026-07-16"
            capture.mkdir(parents=True)
            ledger = root / "wiki" / "20_semantics" / "data_ledger.jsonl"
            ledger.parent.mkdir(parents=True)
            ledger.write_text('{"field_id": "last_good"}\n', encoding="utf-8")
            write_jsonl(
                capture / "data_fields.jsonl",
                [
                    {
                        "scope": {"instrument_type": "EQUITY", "region": "USA", "delay": 1, "universe": "TOP3000"},
                        "data_set": {"id": "bad"},
                        "field": {"id": "bad_field", "type": "MATRIX"},
                    }
                ],
            )

            with patch("wqb.data_ledger_compile.load_data_ledger", side_effect=ValueError("validation failed")):
                with self.assertRaisesRegex(ValueError, "validation failed"):
                    compile_data_ledger_from_raw(root, capture_dir=capture, generated_at="2026-07-16T09:00:00+00:00")

            self.assertIn("last_good", ledger.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests and confirm RED**

Run:

```powershell
python -c "import sys, runpy; sys.platform='linux'; runpy.run_module('unittest', run_name='__main__')" tests.test_data_ledger_compile -v
```

Expected: FAIL with missing module or missing functions.

- [ ] **Step 3: Implement compiler**

Create `BrainWorkflow/wqb/data_ledger_compile.py`:

```python
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from wqb.data_ledger import DataLedgerRecord, data_ledger_record_to_dict, load_data_ledger, write_data_ledger_markdown
from wqb.semantics import field_semantic_embedding


RAW_CAPTURE_ROOT = Path("raw") / "platform" / "data_fields"
DATA_LEDGER_JSONL = Path("wiki") / "20_semantics" / "data_ledger.jsonl"
DATA_LEDGER_MD = Path("wiki") / "20_semantics" / "data_ledger.md"
FRESHNESS_MANIFEST = Path("wiki") / "80_maintenance" / "freshness_manifest.json"


def _now() -> str:
    """Input: none. Output: str. Return UTC timestamp for compile records."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def latest_capture_dir(knowledge_root: str | Path) -> Path:
    """Input: knowledge root. Output: Path. Return newest raw platform data-field capture directory."""
    root = Path(knowledge_root) / RAW_CAPTURE_ROOT
    candidates = [path for path in root.glob("*") if path.is_dir()]
    if not candidates:
        raise FileNotFoundError(f"no platform data-field captures found under {root}")
    return sorted(candidates)[-1]


def _read_json(path: Path) -> dict[str, Any]:
    """Input: JSON path. Output: dict. Read optional JSON capture metadata."""
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Input: JSONL path. Output: row list. Load raw capture rows."""
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            if isinstance(row, dict):
                rows.append(row)
    return rows


def _relative_source(root: Path, path: Path) -> str:
    """Input: root and path. Output: portable source path string."""
    try:
        return str(path.relative_to(root)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def _risk_from_counts(alpha_count: int, user_count: int) -> str:
    """Input: alpha and user counts. Output: low/medium/high risk label."""
    crowded = max(alpha_count, user_count)
    if crowded >= 50:
        return "high"
    if crowded >= 10:
        return "medium"
    return "low"


def _template_ids(field_type: str, tags: list[str]) -> list[str]:
    """Input: field type and tags. Output: compatible template id hints."""
    tag_set = set(tags)
    if field_type.upper() == "VECTOR":
        return ["vector_event_count_surprise", "vector_event_value_surprise"]
    if tag_set & {"cash", "cashflow", "asset_strength", "profitability", "growth"}:
        return ["matrix_fast_delta_rank", "matrix_ts_zscore_rank"]
    return ["matrix_ts_zscore_rank"]


def _update_manifest(root: Path, generated_at: str) -> None:
    """Input: knowledge root and timestamp. Output: none. Mark data ledger freshness after compile."""
    manifest_path = root / FRESHNESS_MANIFEST
    rows: list[dict[str, Any]] = []
    if manifest_path.exists():
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        if isinstance(payload, list):
            rows = [row for row in payload if isinstance(row, dict)]
    by_name = {str(row.get("name", "")): row for row in rows}
    by_name["data_ledger"] = {
        "name": "data_ledger",
        "path": str(DATA_LEDGER_JSONL).replace("\\", "/"),
        "updated_at": generated_at[:10],
        "max_age_days": 1,
        "status": "refreshed",
        "source_note": "Compiled from raw platform data-field captures.",
    }
    ordered = [by_name[name] for name in sorted(by_name)]
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(ordered, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    """Input: output path and rows. Output: none. Write JSONL deterministically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _record_from_group(root: Path, capture_path: Path, rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Input: root, raw source path, grouped rows. Output: data ledger JSON row."""
    first = rows[0]
    field = first.get("field", {}) if isinstance(first.get("field"), dict) else {}
    data_set = first.get("data_set", {}) if isinstance(first.get("data_set"), dict) else {}
    scopes = [row.get("scope", {}) for row in rows if isinstance(row.get("scope"), dict)]
    embedding = field_semantic_embedding({**field, "dataset": data_set})
    field_id = str(field.get("id", ""))
    field_type = str(field.get("type", ""))
    alpha_count = max(int(row.get("field", {}).get("alphaCount", 0) or 0) for row in rows)
    user_count = max(int(row.get("field", {}).get("userCount", row.get("field", {}).get("user_count", 0)) or 0) for row in rows)
    tags = sorted(set(embedding["tags"]) | {str(data_set.get("category", "")).lower()} - {""})
    regions = sorted({str(scope.get("region", "")) for scope in scopes if scope.get("region")})
    delays = sorted({int(scope.get("delay", 0)) for scope in scopes})
    universes = sorted({str(scope.get("universe", "")) for scope in scopes if scope.get("universe")})
    primary_scope = scopes[0] if scopes else {}
    coverage_values = [float(row.get("field", {}).get("coverage", 0.0) or 0.0) for row in rows]
    coverage = max(coverage_values) if coverage_values else 0.0
    correlation_risk = _risk_from_counts(alpha_count, user_count)
    return data_ledger_record_to_dict(
        DataLedgerRecord(
            dataset_id=str(data_set.get("id", embedding.get("dataset_id", ""))),
            dataset_name=str(data_set.get("name", "")),
            field_id=field_id,
            field_type=field_type,
            region=str(primary_scope.get("region", "")),
            delay=int(primary_scope.get("delay", 0)),
            universe=str(primary_scope.get("universe", "")),
            semantic_tags=tags,
            coverage=coverage,
            alpha_count=alpha_count,
            user_count=user_count,
            simulation_usage_count=0,
            submitted_usage_count=0,
            last_used_at="",
            best_result_label="unexplored_raw_candidate",
            correlation_risk=correlation_risk,
            source_paths=[_relative_source(root, capture_path)],
            available_regions=regions,
            available_delays=delays,
            available_universes=universes,
            activity_tags=[],
            compatible_template_ids=_template_ids(field_type, tags),
            gate_requirements=["verify_platform_availability_before_live_run"],
            experiment_paths=[],
            instrument_type=str(primary_scope.get("instrument_type", "")),
            date_coverage=str(field.get("dateCoverage", field.get("date_coverage", ""))),
            data_category=str(data_set.get("category", "")),
            crowding_risk=correlation_risk,
            known_operators=["rank", "ts_delta", "ts_zscore"],
            repair_usage_count=0,
        )
    ) | {"source_quality": "platform_raw_capture", "coverage_status": "measured_raw"}


def compile_data_ledger_from_raw(
    knowledge_root: str | Path,
    capture_dir: str | Path | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Input: vault root and optional capture dir. Output: summary dict. Compile data ledger from raw captures."""
    generated = generated_at or _now()
    root = Path(knowledge_root)
    selected_capture = Path(capture_dir) if capture_dir is not None else latest_capture_dir(root)
    fields_path = selected_capture / "data_fields.jsonl"
    manifest = _read_json(selected_capture / "manifest.json")
    rows = _read_jsonl(fields_path)
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        field = row.get("field", {}) if isinstance(row.get("field"), dict) else {}
        data_set = row.get("data_set", {}) if isinstance(row.get("data_set"), dict) else {}
        field_id = str(field.get("id", ""))
        dataset_id = str(data_set.get("id", ""))
        if field_id:
            grouped[(dataset_id, field_id)].append(row)

    output_rows = [
        _record_from_group(root, fields_path, grouped[key])
        for key in sorted(grouped, key=lambda item: (item[0], item[1]))
    ]
    ledger_path = root / DATA_LEDGER_JSONL
    markdown_path = root / DATA_LEDGER_MD
    tmp_path = ledger_path.with_suffix(".jsonl.tmp")
    _write_jsonl(tmp_path, output_rows)
    records = load_data_ledger(tmp_path)
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path.replace(ledger_path)
    write_data_ledger_markdown(markdown_path, records, generated)
    _update_manifest(root, generated)
    partial = str(manifest.get("status", "")) != "completed"
    return {
        "generated_at": generated,
        "capture_dir": str(selected_capture),
        "ledger_path": str(ledger_path),
        "markdown_path": str(markdown_path),
        "record_count": len(records),
        "source_status": "partial" if partial else "complete",
    }
```

- [ ] **Step 4: Run tests and confirm GREEN**

Run:

```powershell
python -c "import sys, runpy; sys.platform='linux'; runpy.run_module('unittest', run_name='__main__')" tests.test_data_ledger_compile -v
```

Expected: PASS.

- [ ] **Step 5: Commit Task 2**

```powershell
git add BrainWorkflow/wqb/data_ledger_compile.py BrainWorkflow/tests/test_data_ledger_compile.py
git commit -m "compile data ledger from raw fields"
```

---

### Task 3: CLI Commands For Capture And Compile

**Files:**
- Modify: `BrainWorkflow/wqb/cli.py`
- Test: `BrainWorkflow/tests/test_cli.py`

**Interfaces:**
- Consumes:
  - `capture_platform_data_fields`
  - `compile_data_ledger_from_raw`
  - existing `build_client(config)`
- Produces:
  - CLI command `capture-platform-data-fields`
  - CLI command `compile-data-ledger`
  - Python wrappers `capture_platform_data_fields_command(...) -> dict[str, Any]` and `compile_data_ledger_command(...) -> dict[str, Any]`

- [ ] **Step 1: Add failing CLI tests**

Append to `BrainWorkflow/tests/test_cli.py`:

```python
    def test_capture_platform_data_fields_requires_live_api_flag(self):
        with patch("sys.argv", ["wqb", "capture-platform-data-fields"]):
            with self.assertRaises(SystemExit) as ctx:
                main()

        self.assertIn("--enable-live-api", str(ctx.exception))

    def test_capture_platform_data_fields_dispatches_with_scope_limits(self):
        output = io.StringIO()
        with patch("sys.argv", ["wqb", "capture-platform-data-fields", "--enable-live-api", "--capture-region", "USA,EUR", "--capture-delay", "1", "--capture-universe", "TOP3000", "--max-scopes", "2"]):
            with patch("wqb.cli.capture_platform_data_fields_command", return_value={"field_count": 7}) as command:
                with redirect_stdout(output):
                    main()

        kwargs = command.call_args.kwargs
        self.assertEqual(kwargs["regions"], ["USA", "EUR"])
        self.assertEqual(kwargs["delays"], [1])
        self.assertEqual(kwargs["universes"], ["TOP3000"])
        self.assertEqual(kwargs["max_scopes"], 2)
        self.assertEqual(json.loads(output.getvalue())["field_count"], 7)

    def test_compile_data_ledger_dispatches_without_live_api(self):
        output = io.StringIO()
        with patch("sys.argv", ["wqb", "compile-data-ledger", "--knowledge-root", "knowledge"]):
            with patch("wqb.cli.compile_data_ledger_command", return_value={"record_count": 3}) as command:
                with redirect_stdout(output):
                    main()

        self.assertEqual(command.call_args.args[0], "knowledge")
        self.assertEqual(json.loads(output.getvalue())["record_count"], 3)
```

If `test_cli.py` does not import `io`, `redirect_stdout`, `patch`, or `main` in the local section where these tests are added, reuse the existing imports at the top of the file and add only the missing imports.

- [ ] **Step 2: Run focused CLI tests and confirm RED**

Run:

```powershell
python -c "import sys, runpy; sys.platform='linux'; runpy.run_module('unittest', run_name='__main__')" tests.test_cli.WorkflowCliTests -v
```

If the class name differs, run:

```powershell
python -c "import sys, runpy; sys.platform='linux'; runpy.run_module('unittest', run_name='__main__')" tests.test_cli -v
```

Expected: FAIL because the commands are not in parser choices or wrapper functions are absent.

- [ ] **Step 3: Modify imports and add wrappers**

In `BrainWorkflow/wqb/cli.py`, add imports near the existing knowledge/data imports:

```python
from wqb.data_field_capture import capture_platform_data_fields
from wqb.data_ledger_compile import compile_data_ledger_from_raw
```

Add functions near `compile_research_records_command`:

```python
def capture_platform_data_fields_command(
    config: dict[str, Any],
    knowledge_root: str | Path,
    instrument_types: list[str] | None = None,
    regions: list[str] | None = None,
    delays: list[int] | None = None,
    universes: list[str] | None = None,
    max_scopes: int = 0,
    max_datasets_per_scope: int = 0,
    max_fields_per_dataset: int = 0,
    resume_capture: bool = False,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Input: config, vault root, filters, limits. Output: capture summary. Fetch platform data fields into raw."""
    client = build_client(config)
    client.authenticate()
    return capture_platform_data_fields(
        client,
        knowledge_root,
        generated_at=generated_at,
        instrument_types=instrument_types,
        regions=regions,
        delays=delays,
        universes=universes,
        max_scopes=max_scopes,
        max_datasets_per_scope=max_datasets_per_scope,
        max_fields_per_dataset=max_fields_per_dataset,
        resume_capture=resume_capture,
    )


def compile_data_ledger_command(knowledge_root: str | Path, capture_dir: str | Path | None = None) -> dict[str, Any]:
    """Input: vault root and optional capture dir. Output: compile summary. Build the data ledger from raw fields."""
    return compile_data_ledger_from_raw(knowledge_root, capture_dir=capture_dir)
```

- [ ] **Step 4: Extend parser**

Add these command choices:

```python
"capture-platform-data-fields",
"compile-data-ledger",
```

Add parser args after the existing knowledge args:

```python
    parser.add_argument("--data-capture-date", default="")
    parser.add_argument("--capture-region", default="")
    parser.add_argument("--capture-delay", default="")
    parser.add_argument("--capture-universe", default="")
    parser.add_argument("--max-scopes", type=int, default=0)
    parser.add_argument("--max-datasets-per-scope", type=int, default=0)
    parser.add_argument("--max-fields-per-dataset", type=int, default=0)
    parser.add_argument("--resume-capture", action="store_true", default=False)
    parser.add_argument("--capture-dir", default="")
```

Add helper parsing functions near `parse_csv_arg`:

```python
def parse_optional_csv(value: str) -> list[str] | None:
    """Input: comma-separated string. Output: list or None. Parse optional CLI filters."""
    items = parse_csv_arg(value)
    return items or None


def parse_optional_int_csv(value: str) -> list[int] | None:
    """Input: comma-separated integers. Output: int list or None. Parse optional numeric filters."""
    items = parse_csv_arg(value)
    if not items:
        return None
    try:
        return [int(item) for item in items]
    except ValueError as err:
        raise SystemExit(f"integer list expected: {value}") from err
```

- [ ] **Step 5: Add dispatch**

In `main()`, before `plan-research-options` or near knowledge commands:

```python
    elif args.command == "capture-platform-data-fields":
        if not args.enable_live_api:
            raise SystemExit("--enable-live-api is required for capture-platform-data-fields")
        generated_at = args.data_capture_date or None
        if generated_at and len(generated_at) == 10:
            generated_at = f"{generated_at}T00:00:00+00:00"
        result = capture_platform_data_fields_command(
            config,
            args.knowledge_root,
            instrument_types=None,
            regions=parse_optional_csv(args.capture_region),
            delays=parse_optional_int_csv(args.capture_delay),
            universes=parse_optional_csv(args.capture_universe),
            max_scopes=args.max_scopes,
            max_datasets_per_scope=args.max_datasets_per_scope,
            max_fields_per_dataset=args.max_fields_per_dataset,
            resume_capture=args.resume_capture,
            generated_at=generated_at,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.command == "compile-data-ledger":
        result = compile_data_ledger_command(args.knowledge_root, capture_dir=args.capture_dir or None)
        print(json.dumps(result, ensure_ascii=False, indent=2))
```

- [ ] **Step 6: Run CLI tests**

Run:

```powershell
python -c "import sys, runpy; sys.platform='linux'; runpy.run_module('unittest', run_name='__main__')" tests.test_cli -v
```

Expected: PASS.

- [ ] **Step 7: Commit Task 3**

```powershell
git add BrainWorkflow/wqb/cli.py BrainWorkflow/tests/test_cli.py
git commit -m "add data field maintenance cli"
```

---

### Task 4: Console Job Actions And Data Coverage State

**Files:**
- Modify: `BrainWorkflow/wqb/console_jobs.py`
- Modify: `BrainWorkflow/wqb/console_state.py`
- Test: `BrainWorkflow/tests/test_console_jobs.py`
- Test: `BrainWorkflow/tests/test_console_state.py`

**Interfaces:**
- Consumes:
  - CLI commands from Task 3.
  - raw capture manifests under `knowledge/raw/platform/data_fields/*/manifest.json`.
- Produces:
  - console actions `capture-platform-data-fields` and `compile-data-ledger`
  - `state["data_coverage"]` summary dict for rendering

- [ ] **Step 1: Add failing console job tests**

In `BrainWorkflow/tests/test_console_jobs.py`, extend `test_build_cli_command_has_separate_knowledge_maintenance_actions` or add:

```python
    def test_build_cli_command_maps_data_capture_and_compile(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = make_paths(Path(tmp))

            capture = build_cli_command("capture-platform-data-fields", paths, {"enable_live_api": True, "max_scopes": "4"})
            compile_cmd = build_cli_command("compile-data-ledger", paths, {})

        self.assertIn("capture-platform-data-fields", capture)
        self.assertIn("--enable-live-api", capture)
        self.assertIn("--max-scopes", capture)
        self.assertIn("4", capture)
        self.assertIn("compile-data-ledger", compile_cmd)
        self.assertNotIn("--enable-live-api", compile_cmd)
```

In `BrainWorkflow/tests/test_console_state.py`, add:

```python
    def test_console_state_reports_latest_data_coverage_capture(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = make_paths(root)
            capture = paths.knowledge_root / "raw" / "platform" / "data_fields" / "2026-07-16"
            capture.mkdir(parents=True)
            (capture / "manifest.json").write_text(
                json.dumps(
                    {
                        "generated_at": "2026-07-16T08:00:00+00:00",
                        "capture_dir": str(capture),
                        "scope_count": 4,
                        "data_set_count": 8,
                        "field_count": 120,
                        "error_count": 1,
                        "status": "completed_with_warnings",
                    }
                ),
                encoding="utf-8",
            )

            state = load_console_state(paths)

        self.assertTrue(state["data_coverage"]["exists"])
        self.assertEqual(state["data_coverage"]["field_count"], 120)
        self.assertEqual(state["data_coverage"]["error_count"], 1)
```

- [ ] **Step 2: Run tests and confirm RED**

Run:

```powershell
python -c "import sys, runpy; sys.platform='linux'; runpy.run_module('unittest', run_name='__main__')" tests.test_console_jobs tests.test_console_state -v
```

Expected: FAIL for missing action mapping and missing `data_coverage`.

- [ ] **Step 3: Add job mappings**

In `BrainWorkflow/wqb/console_jobs.py`, extend `build_cli_command`:

```python
    if action == "capture-platform-data-fields":
        command = [
            *base,
            "capture-platform-data-fields",
            "--knowledge-root",
            knowledge_root,
        ]
        if data.get("enable_live_api"):
            command.append("--enable-live-api")
        if data.get("max_scopes"):
            command.extend(["--max-scopes", str(data.get("max_scopes"))])
        if data.get("max_datasets_per_scope"):
            command.extend(["--max-datasets-per-scope", str(data.get("max_datasets_per_scope"))])
        if data.get("max_fields_per_dataset"):
            command.extend(["--max-fields-per-dataset", str(data.get("max_fields_per_dataset"))])
        if data.get("resume_capture"):
            command.append("--resume-capture")
        return command
    if action == "compile-data-ledger":
        return [*base, "compile-data-ledger", "--knowledge-root", knowledge_root]
```

- [ ] **Step 4: Add data coverage read model**

In `BrainWorkflow/wqb/console_state.py`, add:

```python
def _data_coverage_summary(knowledge_root: Path) -> dict[str, Any]:
    """Input: knowledge root. Output: data coverage summary. Read latest raw data-field capture manifest."""
    root = knowledge_root / "raw" / "platform" / "data_fields"
    captures = sorted([path for path in root.glob("*") if path.is_dir()])
    if not captures:
        return {"exists": False, "latest_capture_dir": "", "field_count": 0, "scope_count": 0, "data_set_count": 0, "error_count": 0, "status": ""}
    latest = captures[-1]
    manifest = _read_json(latest / "manifest.json")
    return {
        "exists": bool(manifest),
        "latest_capture_dir": str(latest),
        "generated_at": str(manifest.get("generated_at", "")),
        "field_count": int(manifest.get("field_count", 0)),
        "scope_count": int(manifest.get("scope_count", 0)),
        "data_set_count": int(manifest.get("data_set_count", 0)),
        "error_count": int(manifest.get("error_count", 0)),
        "status": str(manifest.get("status", "")),
    }
```

Add to the dict returned by `load_console_state`:

```python
        "data_coverage": _data_coverage_summary(paths.knowledge_root),
```

- [ ] **Step 5: Run tests and commit**

Run:

```powershell
python -c "import sys, runpy; sys.platform='linux'; runpy.run_module('unittest', run_name='__main__')" tests.test_console_jobs tests.test_console_state -v
```

Expected: PASS.

Commit:

```powershell
git add BrainWorkflow/wqb/console_jobs.py BrainWorkflow/wqb/console_state.py BrainWorkflow/tests/test_console_jobs.py BrainWorkflow/tests/test_console_state.py
git commit -m "surface data coverage in console"
```

---

### Task 5: Selectable Option Cards And Console Action Gates

**Files:**
- Modify: `BrainWorkflow/wqb/console_server.py`
- Test: `BrainWorkflow/tests/test_console_server.py`

**Interfaces:**
- Consumes:
  - `state["option_cards"]`
  - `state["freshness"]`
  - `state["data_coverage"]`
  - `build_raw_cli_command`
- Produces:
  - selectable option-card HTML
  - `workflow-start-from-option` console action
  - live-gated data capture action

- [ ] **Step 1: Add failing console server tests**

In `BrainWorkflow/tests/test_console_server.py`, add:

```python
    def test_render_dashboard_uses_selectable_option_cards_without_manual_option_id_input(self):
        state = {
            "readiness": {"exists": True, "passed": True, "blocked": False},
            "freshness": {"exists": True, "valid": True, "record_count": 6, "stale_count": 0, "missing_count": 0},
            "data_coverage": {"exists": True, "field_count": 120, "scope_count": 4, "data_set_count": 8, "error_count": 0, "status": "completed"},
            "option_cards": [{"title": "Power Pool", "primary_incentive": "power_pool", "candidate_scope": "USA D1 TOP3000", "score": {"total": 9.0}}],
            "schedule": {"preview": "# Schedule"},
            "jobs": [],
            "proposal_counts": {},
            "active_workflow": {"exists": False},
            "approved_queue": [],
            "queue_diagnostics": [],
            "workflow_events": [],
        }

        html = render_dashboard(state)

        self.assertIn('type="radio"', html)
        self.assertIn('name="selected_option_id"', html)
        self.assertIn('value="option-1"', html)
        self.assertIn('value="workflow-start-from-option"', html)
        self.assertNotIn('<input name="objective"', html)
        self.assertNotIn('type="text" name="selected_option_id"', html)

    def test_build_action_command_starts_workflow_from_selected_card(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = make_paths(root)
            artifact = paths.knowledge_root / "wiki" / "20_semantics" / "data_ledger.jsonl"
            artifact.parent.mkdir(parents=True)
            artifact.write_text("{}\n", encoding="utf-8")
            maintenance = paths.knowledge_root / "wiki" / "80_maintenance"
            maintenance.mkdir(parents=True)
            (maintenance / "freshness_manifest.json").write_text(
                json.dumps(
                    [
                        {"name": "data_ledger", "path": "wiki/20_semantics/data_ledger.jsonl", "updated_at": "2026-07-16", "max_age_days": 7},
                        {"name": "template_library", "path": "wiki/20_semantics/data_ledger.jsonl", "updated_at": "2026-07-16", "max_age_days": 7},
                        {"name": "benchmark_rules", "path": "wiki/20_semantics/data_ledger.jsonl", "updated_at": "2026-07-16", "max_age_days": 7},
                        {"name": "activity_snapshot", "path": "wiki/20_semantics/data_ledger.jsonl", "updated_at": "2026-07-16", "max_age_days": 7},
                        {"name": "operator_catalog", "path": "wiki/20_semantics/data_ledger.jsonl", "updated_at": "2026-07-16", "max_age_days": 7},
                        {"name": "research_option_cards", "path": "wiki/20_semantics/data_ledger.jsonl", "updated_at": "2026-07-16", "max_age_days": 7},
                    ]
                ),
                encoding="utf-8",
            )
            decisions = paths.knowledge_root / "wiki" / "70_decisions"
            decisions.mkdir(parents=True)
            (decisions / "research_option_cards.jsonl").write_text(
                json.dumps({"title": "Power Pool", "primary_incentive": "power_pool"}) + "\n",
                encoding="utf-8",
            )

            command = build_action_command("workflow-start-from-option", paths, {"selected_option_id": "option-1"})

        self.assertIn("workflow-start", command)
        self.assertIn("--selected-option-id", command)
        self.assertIn("option-1", command)
        self.assertIn("--objective", command)
        self.assertIn("Power Pool", command)

    def test_build_action_command_refuses_data_capture_without_live_api(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = make_paths(Path(tmp))

            with self.assertRaisesRegex(ValueError, "enable_live_api"):
                build_action_command("capture-platform-data-fields", paths, {})
```

- [ ] **Step 2: Run tests and confirm RED**

Run:

```powershell
python -c "import sys, runpy; sys.platform='linux'; runpy.run_module('unittest', run_name='__main__')" tests.test_console_server -v
```

Expected: FAIL because selectable cards and the new action are absent.

- [ ] **Step 3: Add option-card normalization helpers**

In `BrainWorkflow/wqb/console_server.py`, add:

```python
def _option_rows(paths: ConsolePaths) -> list[dict[str, Any]]:
    """Input: console paths. Output: normalized option rows. Load durable research options."""
    path = paths.knowledge_root / "wiki" / "70_decisions" / "research_option_cards.jsonl"
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for index, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            normalized = dict(row)
            normalized.setdefault("option_id", f"option-{index}")
            rows.append(normalized)
    return rows


def _selected_option(paths: ConsolePaths, selected_option_id: str) -> dict[str, Any]:
    """Input: paths and selected option id. Output: option row. Validate console research selection."""
    selected = str(selected_option_id).strip()
    if not selected:
        raise ValueError("select a research option card before starting workflow")
    for row in _option_rows(paths):
        if str(row.get("option_id", "")) == selected:
            return row
    raise ValueError(f"selected research option is not available: {selected}")


def _option_objective(row: dict[str, Any]) -> str:
    """Input: option row. Output: objective string. Derive workflow objective from the selected card."""
    return str(row.get("title") or row.get("primary_incentive") or "Research option").strip()
```

- [ ] **Step 4: Extend action command builder**

In `build_action_command`:

```python
    if action == "capture-platform-data-fields" and not _truthy(data.get("enable_live_api")):
        raise ValueError("enable_live_api is required before capturing platform data fields")
    if action == "workflow-start-from-option":
        if not _freshness_clean(paths):
            raise ValueError("knowledge maintenance is required before starting research workflow")
        option = _selected_option(paths, str(data.get("selected_option_id", "")))
        normalized = {
            "objective": _option_objective(option),
            "selected_option_id": str(option.get("option_id")),
        }
        return build_raw_cli_command("workflow-start", paths, normalized)
```

Keep the existing `workflow-start` branch for CLI compatibility, but the dashboard should no longer render manual fields for it.

- [ ] **Step 5: Replace dashboard HTML with clearer sections**

Refactor `render_dashboard` by adding small render helpers:

```python
def _badge(label: str, value: Any, state: str = "neutral") -> str:
    """Input: label, value, state. Output: HTML badge. Render one compact status marker."""
    return f"<span class='badge badge-{escape(state)}'><strong>{escape(label)}</strong> {escape(str(value))}</span>"


def _render_option_controls(cards: list[dict[str, Any]]) -> str:
    """Input: option card rows. Output: HTML. Render selectable research option cards."""
    if not cards:
        return "<div class='empty'>No research options. Refresh option cards with live API authorization.</div>"
    rows = []
    for index, card in enumerate(cards, start=1):
        option_id = str(card.get("option_id") or f"option-{index}")
        title = str(card.get("title", "Research option"))
        incentive = str(card.get("primary_incentive", ""))
        scope = str(card.get("candidate_scope", ""))
        score = card.get("score", {})
        total = score.get("total", "") if isinstance(score, dict) else ""
        rows.append(
            "<label class='option-card'>"
            f"<input type='radio' name='selected_option_id' value='{escape(option_id)}' {'checked' if index == 1 else ''}>"
            f"<span class='option-title'>{escape(title)}</span>"
            f"<span class='option-meta'>{escape(incentive)} | {escape(scope)} | score {escape(str(total))}</span>"
            "</label>"
        )
    return "".join(rows)
```

Update `_html_page` CSS to use the spec palette and dense layout:

```python
        "body{font-family:Segoe UI,Arial,sans-serif;margin:0;background:#F6F7F9;color:#18202A}"
        "header{background:#18202A;color:white;padding:14px 24px;display:flex;justify-content:space-between;align-items:center}"
        "main{display:grid;grid-template-columns:220px minmax(0,1fr);gap:0;min-height:calc(100vh - 56px)}"
        "nav{border-right:1px solid #D9E0E8;background:#fff;padding:16px}"
        ".workspace{padding:18px 22px;display:grid;gap:14px}"
        "section{background:white;border:1px solid #D9E0E8;border-radius:8px;padding:14px}"
        ".ledger-strip{display:flex;gap:8px;flex-wrap:wrap}"
        ".badge{border:1px solid #D9E0E8;border-radius:999px;padding:4px 8px;font-size:12px;background:#fff}"
        ".badge-ready{border-color:#167C80;color:#167C80}.badge-warn{border-color:#B7791F;color:#B7791F}.badge-blocked{border-color:#B42318;color:#B42318}"
        ".option-card{display:block;border:1px solid #D9E0E8;border-radius:8px;padding:10px;margin:8px 0;cursor:pointer}"
        ".option-card:has(input:checked){border-color:#167C80;box-shadow:inset 3px 0 0 #167C80}"
        ".option-title{display:block;font-weight:600}.option-meta{display:block;font-size:12px;color:#4B5563;margin-top:3px}"
        "button,input,select,textarea{font:inherit;margin:4px 0;padding:7px 9px}button{cursor:pointer}"
        "code,pre{font-family:Consolas,monospace}.wide{grid-column:1/-1}.empty{color:#6B7280}"
```

Render five visible areas:

```python
    body = f"""
<nav>
<strong>Operations</strong>
<a href="/">Research start</a>
<a href="/proposals">Proposals</a>
</nav>
<div class="workspace">
<section class="wide"><h2>Ledger Strip</h2><div class="ledger-strip">{ledger_strip}</div></section>
<section><h2>Research Start</h2>{research_start_form}</section>
<section><h2>Workflow Progress</h2>{workflow_progress}</section>
<section><h2>Knowledge Maintenance</h2>{knowledge_forms}</section>
<section><h2>Data Coverage</h2>{data_coverage_panel}</section>
<section class="wide"><h2>Recent Jobs</h2><ul>{job_items}</ul></section>
</div>
"""
```

- [ ] **Step 6: Run tests and commit**

Run:

```powershell
python -c "import sys, runpy; sys.platform='linux'; runpy.run_module('unittest', run_name='__main__')" tests.test_console_server -v
```

Expected: PASS.

Commit:

```powershell
git add BrainWorkflow/wqb/console_server.py BrainWorkflow/tests/test_console_server.py
git commit -m "make console research options selectable"
```

---

### Task 6: Data Coverage Controls And Structured Proposal Inputs

**Files:**
- Modify: `BrainWorkflow/wqb/console_server.py`
- Test: `BrainWorkflow/tests/test_console_server.py`

**Interfaces:**
- Consumes: action gates and state from Tasks 4 and 5.
- Produces: visible controls for data capture, data ledger compile, research-record compile, health check, and structured proposal select fields.

- [ ] **Step 1: Add failing UI tests for controls**

In `BrainWorkflow/tests/test_console_server.py`, add:

```python
    def test_render_dashboard_exposes_data_capture_and_compile_controls(self):
        state = {
            "readiness": {"exists": True, "passed": False, "blocked": True},
            "freshness": {"exists": True, "valid": True, "record_count": 6, "stale_count": 1, "missing_count": 0},
            "data_coverage": {"exists": True, "field_count": 120, "scope_count": 4, "data_set_count": 8, "error_count": 0, "status": "completed"},
            "option_cards": [],
            "schedule": {"preview": ""},
            "jobs": [],
            "proposal_counts": {},
            "active_workflow": {"exists": False},
            "approved_queue": [],
            "queue_diagnostics": [],
            "workflow_events": [],
        }

        html = render_dashboard(state)

        self.assertIn('value="capture-platform-data-fields"', html)
        self.assertIn('value="compile-data-ledger"', html)
        self.assertIn('name="enable_live_api"', html)
        self.assertIn("120", html)

    def test_render_proposals_uses_select_controls_for_structured_fields(self):
        html = render_proposals([])

        self.assertIn("<select name=\"issue_type\"", html)
        self.assertIn("<select name=\"affected_modules\"", html)
        self.assertIn("template_innovation", html)
        self.assertIn("data_coverage", html)
```

- [ ] **Step 2: Run tests and confirm RED**

Run:

```powershell
python -c "import sys, runpy; sys.platform='linux'; runpy.run_module('unittest', run_name='__main__')" tests.test_console_server -v
```

Expected: FAIL for missing structured controls.

- [ ] **Step 3: Add data coverage forms**

In the `Data Coverage` section of `render_dashboard`, include:

```html
<form method="post" action="/actions/run">
  <input type="hidden" name="action" value="capture-platform-data-fields">
  <label><input type="checkbox" name="enable_live_api"> enable_live_api</label>
  <select name="max_scopes">
    <option value="0">All configured scopes</option>
    <option value="4">First 4 scopes</option>
    <option value="10">First 10 scopes</option>
  </select>
  <button>Capture platform data fields</button>
</form>
<form method="post" action="/actions/run">
  <input type="hidden" name="action" value="compile-data-ledger">
  <button>Compile data ledger from raw</button>
</form>
```

Render current counts from `state["data_coverage"]` in the same section.

- [ ] **Step 4: Replace proposal free-form routing fields with selects**

In `render_proposals`, replace text inputs for structured fields:

```html
<select name="issue_type">
  <option value="template_innovation">template_innovation</option>
  <option value="data_coverage">data_coverage</option>
  <option value="benchmark_rule">benchmark_rule</option>
  <option value="workflow_gate">workflow_gate</option>
</select>
<select name="affected_modules">
  <option value="template_library">template_library</option>
  <option value="data_coverage">data_coverage</option>
  <option value="console">console</option>
  <option value="orchestrator">orchestrator</option>
  <option value="knowledge_compile">knowledge_compile</option>
</select>
```

Keep `summary` and `evidence_paths` as text fields because the user needs to write actual evidence and notes there.

- [ ] **Step 5: Run tests and commit**

Run:

```powershell
python -c "import sys, runpy; sys.platform='linux'; runpy.run_module('unittest', run_name='__main__')" tests.test_console_server -v
```

Expected: PASS.

Commit:

```powershell
git add BrainWorkflow/wqb/console_server.py BrainWorkflow/tests/test_console_server.py
git commit -m "add console data maintenance controls"
```

---

### Task 7: Operating Docs And Recovery Notes

**Files:**
- Modify: `BrainWorkflow/docs/operations/operating_guide.md`
- Modify: `BrainWorkflow/docs/operations/maintainer_handoff.md`
- Modify: `BrainWorkflow/README.md`
- Modify: root `todo.md`
- Modify: root `milestone.md`

**Interfaces:**
- Consumes: CLI and console behavior from Tasks 1-6.
- Produces: durable operator guidance for using the console and maintaining the knowledge base.

- [ ] **Step 1: Add documentation sections**

In `BrainWorkflow/docs/operations/operating_guide.md`, add exact command examples:

````markdown
## Platform Data Field Maintenance

Use this when the user asks to refresh platform data coverage before research.

Capture raw platform data fields:

```powershell
python -m wqb.cli capture-platform-data-fields --knowledge-root 'C:\Users\oytl\Desktop\pyproject\brain\knowledge' --enable-live-api
```

Compile the data ledger from raw:

```powershell
python -m wqb.cli compile-data-ledger --knowledge-root 'C:\Users\oytl\Desktop\pyproject\brain\knowledge'
```

Then check knowledge health:

```powershell
python -m wqb.cli knowledge-health-check --knowledge-root 'C:\Users\oytl\Desktop\pyproject\brain\knowledge'
```

`cache-metadata` remains a targeted exploration command. It is not the authoritative data scheduling ledger.
````

Add a console workflow section:

```markdown
## Console Research Selection

The normal UI path is:

1. Refresh option cards with live API authorization.
2. Select one research option card in the console.
3. Start workflow from the selected card.
4. Continue the Orchestrator one legal step at a time.

Do not type option IDs manually in normal operation. The console maps the selected card to `workflow-start`.
```

- [ ] **Step 2: Update maintainer handoff**

Add a section to `BrainWorkflow/docs/operations/maintainer_handoff.md`:

````markdown
## Data Field Coverage Contract

Authoritative data scheduling coverage comes from `knowledge/raw/platform/data_fields/YYYY-MM-DD/` snapshots compiled by `compile-data-ledger`.

The previous `cache-metadata` path is useful for small targeted experiments, but it does not represent all accessible data fields and must not be treated as full coverage.

If a future Codex resumes this work and sees a partial ledger, run or schedule:

```powershell
python -m wqb.cli capture-platform-data-fields --knowledge-root 'C:\Users\oytl\Desktop\pyproject\brain\knowledge' --enable-live-api
python -m wqb.cli compile-data-ledger --knowledge-root 'C:\Users\oytl\Desktop\pyproject\brain\knowledge'
```
````

- [ ] **Step 3: Update README link**

In `BrainWorkflow/README.md`, add one bullet under the existing docs section:

```markdown
- Platform data-field maintenance and selectable console operation are documented in `docs/operations/operating_guide.md`.
```

- [ ] **Step 4: Update root recovery files**

Append root `todo.md` with:

```markdown
### Result
- Implemented selectable console research decisions.
- Added platform data-field raw capture and data ledger compile maintenance path.
- Updated operations documentation.
```

Append root `milestone.md` with:

```markdown
## 2026-07-16 Console UX And Data Field Capture Implementation

- Current loop: implementation complete pending final verification.
- Exact next command: run full non-live test suite and compileall from `skills-and-workflows/BrainWorkflow`.
```

- [ ] **Step 5: Run documentation scans and commit**

Run:

```powershell
rg -n "cache-metadata|capture-platform-data-fields|compile-data-ledger|option card" BrainWorkflow/docs/operations BrainWorkflow/README.md
```

Expected: output includes the new command descriptions and console selection guidance.

Commit:

```powershell
git add BrainWorkflow/docs/operations/operating_guide.md BrainWorkflow/docs/operations/maintainer_handoff.md BrainWorkflow/README.md
git commit -m "document console data maintenance workflow"
```

Root `todo.md` and root `milestone.md` stay local recovery files unless the user asks to commit them in a different repository.

---

### Task 8: Full Verification, Review Package, And Push

**Files:**
- Modify: no production files unless verification reveals a defect.
- Test: full non-live suite.

**Interfaces:**
- Consumes: all earlier task commits.
- Produces: final verification evidence and pushed branch.

- [ ] **Step 1: Run focused suites**

Run:

```powershell
Set-Location 'C:\Users\oytl\Desktop\pyproject\brain\skills-and-workflows\BrainWorkflow'
python -c "import sys, runpy; sys.platform='linux'; runpy.run_module('unittest', run_name='__main__')" tests.test_data_field_capture tests.test_data_ledger_compile tests.test_console_jobs tests.test_console_state tests.test_console_server tests.test_cli -v
```

Expected: PASS.

- [ ] **Step 2: Run full non-live suite**

Run:

```powershell
python -c "import sys, runpy; sys.platform='linux'; runpy.run_module('unittest', run_name='__main__')" discover -s tests -q
```

Expected: PASS.

- [ ] **Step 3: Run compile and diff checks**

Run:

```powershell
python -m compileall -q wqb tests
git diff --check
git status --short --branch
```

Expected:

- compileall exits 0;
- diff check exits 0;
- status shows only intended source/doc changes before final commit, plus protected local progress files if they are present.

- [ ] **Step 4: Request code review**

Use `superpowers:requesting-code-review` for the final implementation branch review. Provide reviewers with:

```text
Review range: f8714c4..HEAD
Focus: data capture raw persistence, ledger compile no-overwrite behavior, console option selection safety, live API gates, and docs accuracy.
Do not review live simulation or submit behavior because this slice does not change it.
```

Fix any Critical or Important findings with tests.

- [ ] **Step 5: Commit final fixes if review requires them**

If review fixes are needed:

```powershell
git add BrainWorkflow/wqb BrainWorkflow/tests BrainWorkflow/docs BrainWorkflow/README.md
git commit -m "fix console data capture review findings"
```

Run the full verification commands again.

- [ ] **Step 6: Push branch**

Direct shell git may fail with Windows socket provider error in this Codex environment. Prefer normal `git push`; if it fails, use the existing Node REPL proxy pattern.

Normal command:

```powershell
git push
```

Fallback command through Node REPL:

```javascript
var cp = await import('node:child_process');
var command = 'set HTTP_PROXY=http://127.0.0.1:7897&& set HTTPS_PROXY=http://127.0.0.1:7897&& set http_proxy=http://127.0.0.1:7897&& set https_proxy=http://127.0.0.1:7897&& git -C C:\\Users\\oytl\\Desktop\\pyproject\\brain\\skills-and-workflows -c http.proxy=http://127.0.0.1:7897 -c https.proxy=http://127.0.0.1:7897 push';
var result = cp.spawnSync('cmd.exe', ['/d', '/s', '/c', command], { cwd: 'C:\\Users\\oytl\\Desktop\\pyproject\\brain', encoding: 'utf8', timeout: 120000 });
nodeRepl.write(JSON.stringify({status: result.status, stdout: result.stdout, stderr: result.stderr}, null, 2));
```

Expected: branch `agent/brainworkflow-phase2` updates on `origin`.

---

## Plan Self-Review

Spec coverage:

- UI redesign: Tasks 5 and 6.
- Selectable option cards: Task 5.
- Non-free-text normal workflow routing: Task 5 and Task 6.
- Raw platform data-field capture: Task 1 and Task 3.
- Ledger compile from raw: Task 2 and Task 3.
- Console actions: Task 4, Task 5, and Task 6.
- Readiness and freshness visibility: Task 4 and Task 5.
- Documentation: Task 7.
- Verification and review: Task 8.

Type consistency:

- `capture_platform_data_fields(...) -> dict[str, Any]` is defined in Task 1 and consumed by Task 3.
- `compile_data_ledger_from_raw(...) -> dict[str, Any]` is defined in Task 2 and consumed by Task 3.
- `state["data_coverage"]` is defined in Task 4 and consumed by Tasks 5 and 6.
- `workflow-start-from-option` is defined in Task 5 and rendered by Task 5.

Completion-marker scan:

- This plan contains no unresolved marker terms from the project planning rules.

Execution recommendation:

- Use Subagent-Driven execution. Task boundaries are independent enough for fresh workers: capture module, compile module, CLI, console state/jobs, UI rendering, docs, and final review.
