# Knowledge Workflow Operating System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the approved Knowledge And Workflow Operating System contracts so BrainWorkflow can distinguish canonical raw facts, compiled wiki rules, authoritative platform data ledgers, semantic template/operator knowledge, benchmark rules, and proposal-driven workflow changes.

**Architecture:** Add focused contract, ledger, and rule modules around the existing Orchestrator and CLI rather than rewriting the research flow. The vault remains Markdown-first, while `data_ledger.jsonl`, `operator_semantics.jsonl`, `template_library.jsonl`, `benchmark_rules.jsonl`, `workflow_rules.jsonl`, and `research_option_cards.jsonl` provide stable schema-first planner inputs.

**Tech Stack:** Python standard library, dataclasses, JSON/JSONL, Markdown with YAML-style front matter blocks, `unittest`, existing `wqb` modules, local Obsidian vault at `C:\Users\oytl\Desktop\pyproject\brain\knowledge`.

## Global Constraints

- Preserve the existing Scout -> Seed -> Discovery -> Repair -> Submit workflow.
- Do not rewrite the Orchestrator, readiness gate, console job model, candidate queue, generator, simulator, checker, or API client.
- Do not build a human learning curriculum; the target is source-clean operating knowledge.
- Do not force all knowledge into databases now; Markdown remains durable and high-value planner inputs use JSONL.
- Do not implement the Windows double-click launcher in this plan.
- Do not run live simulations or submissions in this plan.
- Do not run live platform data capture unless a specific task says `--enable-live-api` and the user has authorized that execution separately.
- Do not let `bootstrap-knowledge` silently replace authoritative measured data ledgers with schema-seeded or cache-only rows.
- Keep root `todo.md` and `milestone.md` current before interruption or handoff.
- On this Windows Codex setup, use `python -c "import sys, runpy; sys.platform='linux'; runpy.run_module('unittest', run_name='__main__')"` for full discovery when direct unittest imports fail.

---

## File Structure

- Create `wqb/knowledge_contracts.py`
  - Owns raw metadata, wiki metadata, front matter parsing/rendering, canonical path checks, source index rows, and contract validation.
- Create `tests/test_knowledge_contracts.py`
  - Verifies metadata parsing, rendering, source index update behavior, and canonical path classification.
- Modify `wqb/knowledge_freshness.py`
  - Adds contract-aware vault health checks without changing existing freshness manifest behavior.
- Modify `tests/test_knowledge_freshness.py`
  - Adds stale/missing/backlink/legacy-path diagnostics.
- Modify `wqb/cli.py`
  - Adds contract validation and semantic compile commands.
- Modify `tests/test_cli.py`
  - Adds parse and dispatch coverage for new commands.
- Modify `wqb/run_readiness.py`
  - Distinguishes seed/cache ledgers from authoritative measured ledgers for research and submit-candidate modes.
- Modify `tests/test_run_readiness.py`
  - Adds cache-only and authoritative measured ledger readiness cases.
- Modify `wqb/data_ledger.py`
  - Adds data authority helpers and Markdown source-status rendering.
- Modify `tests/test_data_ledger.py`
  - Verifies authority classification and exact-scope source freshness.
- Create `wqb/operator_semantics.py`
  - Owns operator semantic records, seed compilation from official operator Markdown, JSONL/Markdown writers, and operator fit scoring.
- Create `tests/test_operator_semantics.py`
  - Verifies operator semantic schema, compatibility scoring, and Markdown rendering.
- Modify `wqb/template_library.py`
  - Extends template records into the approved Template Matrix while preserving backward compatibility.
- Modify `tests/test_template_library.py`
  - Verifies matrix fields, backward-compatible loading, scoring, and Markdown rendering.
- Create `wqb/benchmark_rules.py`
  - Owns active benchmark rule records, near-miss promotion rules, and rule lookup by issue type.
- Create `tests/test_benchmark_rules.py`
  - Verifies benchmark rule schema, near-miss examples, and Markdown output.
- Modify `wqb/research_planner.py`
  - Uses authoritative data status, operator semantics, template matrix, benchmark rules, and current incentives when producing option cards.
- Modify `tests/test_research_planner.py`
  - Adds planner option evidence, degraded-data blockers, and incentive-driven scoring tests.
- Modify `wqb/workflow_proposals.py`
  - Upgrades proposal records to the Spec B lifecycle and user-decision fields.
- Modify `tests/test_workflow_proposals.py`
  - Adds accepted-for-wiki, accepted-for-implementation, accepted-as-experiment, supersedes, and applied transitions.
- Modify `wqb/console_state.py`
  - Exposes data ledger authority, semantic ledger status, benchmark rule status, and proposal lifecycle counts.
- Modify `wqb/console_server.py`
  - Labels maintenance actions and proposal decisions according to Spec B contracts.
- Modify `tests/test_console_state.py` and `tests/test_console_server.py`
  - Verifies dashboard text, authority flags, and proposal UI controls.
- Update vault docs under `C:\Users\oytl\Desktop\pyproject\brain\knowledge\wiki\80_maintenance\` and `wiki\60_workflows\`
  - Writes canonical contract, migration inventory, and cleanup guidance.
- Update `BrainWorkflow/docs/operations/operating_guide.md` and `BrainWorkflow/docs/operations/maintainer_handoff.md`
  - Explains the new contract commands and readiness implications.

---

### Task 1: Knowledge Contract Parser And Source Index

**Files:**
- Create: `BrainWorkflow/wqb/knowledge_contracts.py`
- Create: `BrainWorkflow/tests/test_knowledge_contracts.py`
- Modify: `BrainWorkflow/wqb/cli.py`
- Modify: `BrainWorkflow/tests/test_cli.py`

**Interfaces:**
- Produces: `RAW_CANONICAL_PREFIXES: tuple[str, ...]`
- Produces: `WIKI_CANONICAL_PREFIXES: tuple[str, ...]`
- Produces: `RawSourceMetadata`
- Produces: `WikiPageMetadata`
- Produces: `SourceIndexRow`
- Produces: `parse_markdown_front_matter(text: str) -> tuple[dict[str, Any], str]`
- Produces: `render_front_matter(metadata: dict[str, Any]) -> str`
- Produces: `canonical_source_family(path: str | Path, knowledge_root: str | Path) -> str`
- Produces: `validate_raw_metadata(path: Path) -> list[str]`
- Produces: `validate_wiki_metadata(path: Path) -> list[str]`
- Produces: `update_source_index(knowledge_root: str | Path, rows: list[SourceIndexRow]) -> Path`
- Produces CLI command: `knowledge-contract-check`

- [ ] **Step 1: Write failing tests for front matter and source index**

Create `BrainWorkflow/tests/test_knowledge_contracts.py`:

```python
import tempfile
import unittest
from pathlib import Path

from wqb.knowledge_contracts import (
    RawSourceMetadata,
    SourceIndexRow,
    canonical_source_family,
    parse_markdown_front_matter,
    render_front_matter,
    update_source_index,
    validate_raw_metadata,
    validate_wiki_metadata,
)


class KnowledgeContractTests(unittest.TestCase):
    def test_parse_and_render_front_matter_preserves_body(self):
        text = "---\nsource_type: platform_api\nsource_family: data_fields\nrecord_count: 3\ncompiled_targets:\n  - wiki/20_semantics/data_ledger.md\n---\n# Body\n"

        metadata, body = parse_markdown_front_matter(text)
        rendered = render_front_matter(metadata) + body

        self.assertEqual(metadata["source_type"], "platform_api")
        self.assertEqual(metadata["source_family"], "data_fields")
        self.assertEqual(metadata["record_count"], 3)
        self.assertEqual(metadata["compiled_targets"], ["wiki/20_semantics/data_ledger.md"])
        self.assertIn("# Body", rendered)

    def test_validate_raw_metadata_reports_missing_required_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "knowledge" / "raw" / "platform" / "learn" / "2026-07-22" / "operators.md"
            path.parent.mkdir(parents=True)
            path.write_text("---\nsource_type: platform_api\n---\n# Operators\n", encoding="utf-8")

            issues = validate_raw_metadata(path)

        self.assertIn("missing source_family", issues)
        self.assertIn("missing captured_at", issues)
        self.assertIn("missing compiled_targets", issues)

    def test_validate_wiki_metadata_requires_source_and_consumers(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "knowledge" / "wiki" / "50_benchmarks" / "correlation_and_novelty.md"
            path.parent.mkdir(parents=True)
            path.write_text("---\ncompiled_at: 2026-07-22\n---\n# Rule\n", encoding="utf-8")

            issues = validate_wiki_metadata(path)

        self.assertIn("missing compiled_from", issues)
        self.assertIn("missing consumed_by", issues)
        self.assertIn("missing update_trigger", issues)

    def test_canonical_source_family_identifies_legacy_and_canonical_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "knowledge"

            canonical = canonical_source_family(root / "raw" / "platform" / "learn" / "2026-07-22" / "index.md", root)
            legacy = canonical_source_family(root / "raw" / "learn" / "old.md", root)
            wiki = canonical_source_family(root / "wiki" / "20_semantics" / "operators.md", root)

        self.assertEqual(canonical, "raw/platform/learn")
        self.assertEqual(legacy, "legacy")
        self.assertEqual(wiki, "wiki/20_semantics")

    def test_update_source_index_writes_stable_markdown_inventory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "knowledge"
            row = SourceIndexRow(
                path="raw/platform/data_fields/2026-07-22/index.md",
                source_family="data_fields",
                source_type="platform_api",
                contents="platform data-field capture manifest",
                update_check="compare field ids and exact scopes",
                compiled_targets=["wiki/20_semantics/data_ledger.md"],
            )

            output = update_source_index(root, [row])
            text = output.read_text(encoding="utf-8")

        self.assertIn("raw/platform/data_fields/2026-07-22/index.md", text)
        self.assertIn("compare field ids and exact scopes", text)
        self.assertIn("wiki/20_semantics/data_ledger.md", text)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests and confirm RED**

Run:

```powershell
Set-Location 'C:\Users\oytl\Desktop\pyproject\brain\skills-and-workflows\BrainWorkflow'
python -c "import sys, runpy; sys.platform='linux'; runpy.run_module('unittest', run_name='__main__')" tests.test_knowledge_contracts -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'wqb.knowledge_contracts'`.

- [ ] **Step 3: Implement `knowledge_contracts.py`**

Create `BrainWorkflow/wqb/knowledge_contracts.py`:

```python
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any


RAW_CANONICAL_PREFIXES = (
    "raw/platform/learn",
    "raw/platform/data_fields",
    "raw/platform/activities",
    "raw/platform/account_rules",
    "raw/community/forum",
    "raw/community/advisor_notes",
    "raw/community/user_messages",
    "raw/research/daily",
    "raw/research/batches",
    "raw/research/near_misses",
    "raw/research/repairs",
    "raw/research/submissions",
)

WIKI_CANONICAL_PREFIXES = (
    "wiki/00_principles",
    "wiki/10_foundations",
    "wiki/20_semantics",
    "wiki/30_templates",
    "wiki/40_experiments",
    "wiki/50_benchmarks",
    "wiki/60_workflows",
    "wiki/70_decisions",
    "wiki/80_maintenance",
    "wiki/90_index",
)

RAW_REQUIRED_FIELDS = (
    "source_type",
    "source_family",
    "source_path",
    "captured_at",
    "capture_tool",
    "record_count",
    "content_hash",
    "update_check",
    "compiled_targets",
)

WIKI_REQUIRED_FIELDS = (
    "compiled_from",
    "compiled_at",
    "trust_level",
    "update_trigger",
    "consumed_by",
)


@dataclass(frozen=True)
class RawSourceMetadata:
    source_type: str
    source_family: str
    source_path: str
    captured_at: str
    capture_tool: str
    record_count: int
    content_hash: str
    update_check: str
    compiled_targets: list[str]
    scope: str = ""
    content_status: str = "raw_markdown"


@dataclass(frozen=True)
class WikiPageMetadata:
    compiled_from: list[str]
    compiled_at: str
    trust_level: str
    update_trigger: str
    consumed_by: list[str]


@dataclass(frozen=True)
class SourceIndexRow:
    path: str
    source_family: str
    source_type: str
    contents: str
    update_check: str
    compiled_targets: list[str]


def _coerce_scalar(value: str) -> Any:
    """Input: front matter value. Output: Python scalar. Convert simple YAML-style scalars."""
    stripped = value.strip()
    if stripped.isdigit():
        return int(stripped)
    if stripped.lower() in {"true", "false"}:
        return stripped.lower() == "true"
    return stripped.strip('"').strip("'")


def parse_markdown_front_matter(text: str) -> tuple[dict[str, Any], str]:
    """Input: Markdown text. Output: metadata and body. Parse a small YAML-style front matter block."""
    if not text.startswith("---\n"):
        return {}, text
    lines = text.splitlines()
    end_index = None
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end_index = index
            break
    if end_index is None:
        return {}, text
    metadata: dict[str, Any] = {}
    current_key = ""
    for line in lines[1:end_index]:
        if line.startswith("  - ") and current_key:
            metadata.setdefault(current_key, []).append(_coerce_scalar(line[4:]))
            continue
        if ":" in line:
            key, value = line.split(":", 1)
            current_key = key.strip()
            if value.strip():
                metadata[current_key] = _coerce_scalar(value)
            else:
                metadata[current_key] = []
    body = "\n".join(lines[end_index + 1 :])
    if body:
        body += "\n"
    return metadata, body


def render_front_matter(metadata: dict[str, Any]) -> str:
    """Input: metadata dict. Output: Markdown front matter. Render deterministic YAML-style metadata."""
    lines = ["---"]
    for key in sorted(metadata):
        value = metadata[key]
        if isinstance(value, list):
            lines.append(f"{key}:")
            for item in value:
                lines.append(f"  - {item}")
        else:
            lines.append(f"{key}: {value}")
    lines.append("---")
    return "\n".join(lines) + "\n"


def _relative_posix(path: Path, root: Path) -> str:
    """Input: path and root. Output: posix string. Convert a vault path to relative form."""
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def canonical_source_family(path: str | Path, knowledge_root: str | Path) -> str:
    """Input: path and vault root. Output: source family label. Classify canonical and legacy vault paths."""
    root = Path(knowledge_root)
    relative = _relative_posix(Path(path), root)
    for prefix in RAW_CANONICAL_PREFIXES:
        if relative == prefix or relative.startswith(prefix + "/"):
            return prefix
    for prefix in WIKI_CANONICAL_PREFIXES:
        if relative == prefix or relative.startswith(prefix + "/"):
            return prefix
    if relative.startswith("raw/") or relative.startswith("wiki/"):
        return "legacy"
    return "external"


def _missing_fields(metadata: dict[str, Any], required: tuple[str, ...]) -> list[str]:
    """Input: metadata and required fields. Output: issue strings. Find missing metadata keys."""
    issues: list[str] = []
    for field_name in required:
        value = metadata.get(field_name)
        if value in (None, "", []):
            issues.append(f"missing {field_name}")
    return issues


def validate_raw_metadata(path: Path) -> list[str]:
    """Input: raw Markdown path. Output: issue strings. Validate raw source metadata."""
    metadata, _ = parse_markdown_front_matter(path.read_text(encoding="utf-8"))
    issues = _missing_fields(metadata, RAW_REQUIRED_FIELDS)
    targets = metadata.get("compiled_targets", [])
    if targets and not isinstance(targets, list):
        issues.append("compiled_targets must be a list")
    return issues


def validate_wiki_metadata(path: Path) -> list[str]:
    """Input: wiki Markdown path. Output: issue strings. Validate compiled wiki metadata."""
    metadata, _ = parse_markdown_front_matter(path.read_text(encoding="utf-8"))
    issues = _missing_fields(metadata, WIKI_REQUIRED_FIELDS)
    for list_field in ("compiled_from", "consumed_by"):
        value = metadata.get(list_field, [])
        if value and not isinstance(value, list):
            issues.append(f"{list_field} must be a list")
    return issues


def source_index_row_to_dict(row: SourceIndexRow) -> dict[str, Any]:
    """Input: SourceIndexRow. Output: dict. Convert one source index row."""
    return asdict(row)


def update_source_index(knowledge_root: str | Path, rows: list[SourceIndexRow]) -> Path:
    """Input: vault root and rows. Output: source index path. Write the raw source inventory."""
    root = Path(knowledge_root)
    output = root / "raw" / "source_index.md"
    output.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Raw Source Index",
        "",
        "This file is generated from canonical raw source metadata and migration records.",
        "",
    ]
    for row in sorted(rows, key=lambda item: item.path):
        lines.extend(
            [
                f"## `{row.path}`",
                "",
                f"- Source Family: `{row.source_family}`",
                f"- Source Type: `{row.source_type}`",
                f"- Contents: {row.contents}",
                f"- Update Check: {row.update_check}",
                "- Compiled Targets:",
                *[f"  - `{target}`" for target in row.compiled_targets],
                "",
            ]
        )
    output.write_text("\n".join(lines), encoding="utf-8")
    return output
```

- [ ] **Step 4: Add CLI command parse and dispatch**

In `BrainWorkflow/wqb/cli.py`, add `knowledge-contract-check` to the `choices=[...]` list and dispatch it near existing knowledge commands:

```python
elif args.command == "knowledge-contract-check":
    from wqb.knowledge_contracts import validate_raw_metadata, validate_wiki_metadata

    root = Path(args.knowledge_root)
    issues = []
    for path in sorted((root / "raw").rglob("*.md")):
        for issue in validate_raw_metadata(path):
            issues.append({"path": str(path), "issue": issue})
    for path in sorted((root / "wiki").rglob("*.md")):
        for issue in validate_wiki_metadata(path):
            issues.append({"path": str(path), "issue": issue})
    print(json.dumps({"issue_count": len(issues), "issues": issues}, ensure_ascii=False, indent=2))
    if issues and args.readiness_mode in {"research", "submit-candidate"}:
        raise SystemExit(1)
```

Also import `Path` and `json` only if they are not already imported at the top of `cli.py`.

- [ ] **Step 5: Run focused tests and commit**

Run:

```powershell
python -c "import sys, runpy; sys.platform='linux'; runpy.run_module('unittest', run_name='__main__')" tests.test_knowledge_contracts tests.test_cli -v
```

Expected: PASS.

Commit:

```powershell
git add BrainWorkflow/wqb/knowledge_contracts.py BrainWorkflow/tests/test_knowledge_contracts.py BrainWorkflow/wqb/cli.py BrainWorkflow/tests/test_cli.py
git commit -m "add knowledge source contracts"
```

---

### Task 2: Contract-Aware Knowledge Health Check

**Files:**
- Modify: `BrainWorkflow/wqb/knowledge_freshness.py`
- Modify: `BrainWorkflow/tests/test_knowledge_freshness.py`
- Modify: `BrainWorkflow/wqb/console_state.py`
- Modify: `BrainWorkflow/tests/test_console_state.py`

**Interfaces:**
- Consumes from Task 1: `canonical_source_family`, `validate_raw_metadata`, `validate_wiki_metadata`
- Produces: `KnowledgeHealthIssue`
- Produces: `evaluate_knowledge_contract_health(knowledge_root: str | Path) -> dict[str, Any]`
- Produces console state key: `state["knowledge_contracts"]`

- [ ] **Step 1: Write failing tests for contract health**

Add to `BrainWorkflow/tests/test_knowledge_freshness.py`:

```python
import tempfile
import unittest
from pathlib import Path

from wqb.knowledge_freshness import evaluate_knowledge_contract_health


class KnowledgeContractHealthTests(unittest.TestCase):
    def test_contract_health_reports_legacy_paths_and_missing_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "knowledge"
            legacy = root / "raw" / "learn" / "old.md"
            legacy.parent.mkdir(parents=True)
            legacy.write_text("# Old raw source\n", encoding="utf-8")
            canonical = root / "raw" / "platform" / "learn" / "2026-07-22" / "operators.md"
            canonical.parent.mkdir(parents=True)
            canonical.write_text("---\nsource_type: platform_api\n---\n# Operators\n", encoding="utf-8")
            wiki = root / "wiki" / "20_semantics" / "operators.md"
            wiki.parent.mkdir(parents=True)
            wiki.write_text("---\ncompiled_at: 2026-07-22\n---\n# Operators\n", encoding="utf-8")

            report = evaluate_knowledge_contract_health(root)

        codes = [issue["code"] for issue in report["issues"]]
        self.assertIn("legacy_path", codes)
        self.assertIn("raw_metadata_missing", codes)
        self.assertIn("wiki_metadata_missing", codes)
        self.assertEqual(report["legacy_count"], 1)
        self.assertGreaterEqual(report["issue_count"], 3)
```

Add to `BrainWorkflow/tests/test_console_state.py`:

```python
    def test_console_state_includes_knowledge_contract_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = make_paths(root)
            legacy = paths.knowledge_root / "raw" / "learn" / "old.md"
            legacy.parent.mkdir(parents=True)
            legacy.write_text("# Old\n", encoding="utf-8")

            state = load_console_state(paths)

        self.assertIn("knowledge_contracts", state)
        self.assertEqual(state["knowledge_contracts"]["legacy_count"], 1)
```

- [ ] **Step 2: Run tests and confirm RED**

Run:

```powershell
python -c "import sys, runpy; sys.platform='linux'; runpy.run_module('unittest', run_name='__main__')" tests.test_knowledge_freshness tests.test_console_state -v
```

Expected: FAIL because `evaluate_knowledge_contract_health` and console state key are absent.

- [ ] **Step 3: Implement contract health evaluation**

In `BrainWorkflow/wqb/knowledge_freshness.py`, add:

```python
from dataclasses import asdict, dataclass

from wqb.knowledge_contracts import (
    canonical_source_family,
    validate_raw_metadata,
    validate_wiki_metadata,
)


@dataclass(frozen=True)
class KnowledgeHealthIssue:
    code: str
    path: str
    message: str
    action: str


def evaluate_knowledge_contract_health(knowledge_root: str | Path) -> dict[str, Any]:
    """Input: vault root. Output: health dict. Validate canonical raw/wiki contracts."""
    root = Path(knowledge_root)
    issues: list[KnowledgeHealthIssue] = []
    legacy_count = 0
    raw_root = root / "raw"
    wiki_root = root / "wiki"
    for path in sorted(raw_root.rglob("*.md")) if raw_root.exists() else []:
        family = canonical_source_family(path, root)
        if family == "legacy":
            legacy_count += 1
            issues.append(
                KnowledgeHealthIssue(
                    code="legacy_path",
                    path=str(path),
                    message="Raw source is outside the canonical raw tree.",
                    action="Migrate the file into raw/platform, raw/community, or raw/research before using it as an active source.",
                )
            )
        for issue in validate_raw_metadata(path):
            issues.append(
                KnowledgeHealthIssue(
                    code="raw_metadata_missing",
                    path=str(path),
                    message=issue,
                    action="Add raw source metadata or mark the source as migration-only.",
                )
            )
    for path in sorted(wiki_root.rglob("*.md")) if wiki_root.exists() else []:
        for issue in validate_wiki_metadata(path):
            issues.append(
                KnowledgeHealthIssue(
                    code="wiki_metadata_missing",
                    path=str(path),
                    message=issue,
                    action="Add compiled_from, trust, update trigger, and consumed_by metadata.",
                )
            )
    return {
        "issue_count": len(issues),
        "legacy_count": legacy_count,
        "issues": [asdict(issue) for issue in issues],
    }
```

- [ ] **Step 4: Surface health summary in console state**

In `BrainWorkflow/wqb/console_state.py`, import and call the function:

```python
from wqb.knowledge_freshness import evaluate_knowledge_contract_health
```

Add to the returned state dict from `load_console_state(...)`:

```python
"knowledge_contracts": evaluate_knowledge_contract_health(paths.knowledge_root),
```

If `load_console_state` already builds the dict through a local variable, add the key near existing freshness/readiness keys.

- [ ] **Step 5: Run focused tests and commit**

Run:

```powershell
python -c "import sys, runpy; sys.platform='linux'; runpy.run_module('unittest', run_name='__main__')" tests.test_knowledge_freshness tests.test_console_state -v
```

Expected: PASS.

Commit:

```powershell
git add BrainWorkflow/wqb/knowledge_freshness.py BrainWorkflow/tests/test_knowledge_freshness.py BrainWorkflow/wqb/console_state.py BrainWorkflow/tests/test_console_state.py
git commit -m "add knowledge contract health checks"
```

---

### Task 3: Authoritative Data Ledger Contract And Readiness

**Files:**
- Modify: `BrainWorkflow/wqb/data_ledger.py`
- Modify: `BrainWorkflow/tests/test_data_ledger.py`
- Modify: `BrainWorkflow/wqb/run_readiness.py`
- Modify: `BrainWorkflow/tests/test_run_readiness.py`
- Modify: `BrainWorkflow/wqb/console_state.py`
- Modify: `BrainWorkflow/tests/test_console_state.py`

**Interfaces:**
- Produces: `data_record_authority(record: DataLedgerRecord) -> str`
- Produces: `is_authoritative_data_record(record: DataLedgerRecord) -> bool`
- Produces: `summarize_data_ledger_authority(records: list[DataLedgerRecord]) -> dict[str, Any]`
- Produces readiness issue code: `cache_only_data_ledger`
- Produces console state key: `state["data_authority"]`

- [ ] **Step 1: Write failing data authority tests**

Add to `BrainWorkflow/tests/test_data_ledger.py`:

```python
    def test_data_record_authority_distinguishes_cache_and_measured_platform_rows(self):
        cache = DataLedgerRecord(
            dataset_id="fundamental3",
            dataset_name="Fundamentals",
            field_id="fnd3_q_cash_fast_d1",
            field_type="MATRIX",
            region="USA",
            delay=1,
            universe="TOP3000",
            semantic_tags=["cash"],
            coverage=0.8,
            alpha_count=1,
            user_count=1,
            simulation_usage_count=0,
            submitted_usage_count=0,
            last_used_at="",
            best_result_label="unexplored_cache_candidate",
            correlation_risk="low",
            source_paths=["docs/knowledge/cache/platform_metadata.json"],
            source_quality="platform_metadata_cache",
            coverage_status="measured_cache",
        )
        measured = data_ledger_record_from_dict(data_ledger_record_to_dict(cache) | {
            "source_quality": "platform_raw_capture",
            "coverage_status": "measured_raw",
            "source_updated_at": "2026-07-22",
            "source_paths": ["raw/platform/data_fields/2026-07-22/data_fields.jsonl"],
        })

        self.assertEqual(data_record_authority(cache), "seed_cache")
        self.assertEqual(data_record_authority(measured), "authoritative_measured")
        self.assertFalse(is_authoritative_data_record(cache))
        self.assertTrue(is_authoritative_data_record(measured))
        self.assertEqual(
            summarize_data_ledger_authority([cache, measured])["authoritative_measured_count"],
            1,
        )
```

Add imports:

```python
from wqb.data_ledger import (
    DataLedgerRecord,
    data_ledger_record_from_dict,
    data_ledger_record_to_dict,
    data_record_authority,
    is_authoritative_data_record,
    summarize_data_ledger_authority,
)
```

- [ ] **Step 2: Write failing readiness test for cache-only ledger**

Add to `BrainWorkflow/tests/test_run_readiness.py`:

```python
    def test_research_readiness_blocks_cache_only_data_ledger_for_selected_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "knowledge"
            write_freshness_manifest(root, data_updated_at="2026-07-22")
            write_template_library(root)
            write_data_ledger(
                root,
                [
                    {
                        "dataset_id": "fundamental3",
                        "dataset_name": "Fundamentals",
                        "field_id": "fnd3_q_cash_fast_d1",
                        "field_type": "MATRIX",
                        "region": "USA",
                        "delay": 1,
                        "universe": "TOP3000",
                        "semantic_tags": ["cash", "power_pool"],
                        "coverage": 0.8,
                        "alpha_count": 1,
                        "user_count": 1,
                        "simulation_usage_count": 0,
                        "submitted_usage_count": 0,
                        "last_used_at": "",
                        "best_result_label": "unexplored_cache_candidate",
                        "correlation_risk": "low",
                        "source_paths": ["docs/knowledge/cache/platform_metadata.json"],
                        "source_quality": "platform_metadata_cache",
                        "coverage_status": "measured_cache",
                    }
                ],
            )

            report = evaluate_run_readiness(
                root,
                mode="research",
                batch_size=30,
                live_api_enabled=True,
                region="USA",
                delay=1,
                universe="TOP3000",
                today_value="2026-07-22",
            )

        self.assertTrue(report.blocked)
        self.assertIn("cache_only_data_ledger", [issue.code for issue in report.issues])
```

- [ ] **Step 3: Run tests and confirm RED**

Run:

```powershell
python -c "import sys, runpy; sys.platform='linux'; runpy.run_module('unittest', run_name='__main__')" tests.test_data_ledger tests.test_run_readiness -v
```

Expected: FAIL because authority helpers and issue code are absent.

- [ ] **Step 4: Implement authority helpers**

In `BrainWorkflow/wqb/data_ledger.py`, add after record conversion helpers:

```python
def data_record_authority(record: DataLedgerRecord) -> str:
    """Input: data ledger record. Output: authority label. Classify seed/cache versus measured platform rows."""
    if (
        record.source_quality == "platform_raw_capture"
        and record.coverage_status == "measured_raw"
        and bool(record.source_updated_at)
    ):
        return "authoritative_measured"
    if record.source_quality in {"platform_metadata_cache", "schema_seed", "bootstrap_seed"}:
        return "seed_cache"
    if record.coverage_status in {"measured_cache", "schema_seeded", "partial"}:
        return "seed_cache"
    return "unclassified"


def is_authoritative_data_record(record: DataLedgerRecord) -> bool:
    """Input: data ledger record. Output: bool. Test whether the row is measured platform evidence."""
    return data_record_authority(record) == "authoritative_measured"


def summarize_data_ledger_authority(records: list[DataLedgerRecord]) -> dict[str, Any]:
    """Input: data ledger records. Output: summary dict. Count authority classes for UI and readiness."""
    counts = {"authoritative_measured": 0, "seed_cache": 0, "unclassified": 0}
    for record in records:
        counts[data_record_authority(record)] = counts.get(data_record_authority(record), 0) + 1
    return {
        "record_count": len(records),
        "authoritative_measured_count": counts.get("authoritative_measured", 0),
        "seed_cache_count": counts.get("seed_cache", 0),
        "unclassified_count": counts.get("unclassified", 0),
        "authoritative_ready": bool(records) and counts.get("authoritative_measured", 0) == len(records),
    }
```

Update `write_data_ledger_markdown(...)` table to include `Authority`:

```python
"| Dataset | Field | Scope | Authority | Tags | Usage | Best Result | Risk |",
"| --- | --- | --- | --- | --- | --- | --- | --- |",
```

and each row:

```python
authority = data_record_authority(record)
...
f"| {record.dataset_id} | `{record.field_id}` | {scope} | {authority} | {tags} | {usage} | {record.best_result_label} | {record.correlation_risk} |"
```

- [ ] **Step 5: Add cache-only readiness issue**

In `BrainWorkflow/wqb/run_readiness.py`, import:

```python
from wqb.data_ledger import is_authoritative_data_record, summarize_data_ledger_authority
```

Inside `_validate_scope_artifacts(...)`, replace the strict `uncertified` block with:

```python
uncertified = [record for record in selected_data if not is_authoritative_data_record(record)]
if uncertified:
    authority = summarize_data_ledger_authority(selected_data)
    issues.append(
        _issue(
            level,
            "cache_only_data_ledger",
            f"Selected scope {region} D{int(delay)} {universe} has {authority['seed_cache_count']} seed/cache records and {authority['authoritative_measured_count']} authoritative measured records.",
            ledger_path,
            "Run capture-platform-data-fields and compile-data-ledger before research scheduling.",
        )
    )
    return
```

- [ ] **Step 6: Surface authority in console state**

In `BrainWorkflow/wqb/console_state.py`, import:

```python
from wqb.data_ledger import load_data_ledger, summarize_data_ledger_authority
```

Add a helper:

```python
def _data_authority_summary(knowledge_root: Path) -> dict[str, Any]:
    """Input: knowledge root. Output: data authority summary. Summarize ledger provenance for dashboard."""
    ledger_path = knowledge_root / "wiki" / "20_semantics" / "data_ledger.jsonl"
    try:
        return summarize_data_ledger_authority(load_data_ledger(ledger_path))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return {"record_count": 0, "authoritative_measured_count": 0, "seed_cache_count": 0, "unclassified_count": 0, "authoritative_ready": False}
```

Add to state:

```python
"data_authority": _data_authority_summary(paths.knowledge_root),
```

- [ ] **Step 7: Run focused tests and commit**

Run:

```powershell
python -c "import sys, runpy; sys.platform='linux'; runpy.run_module('unittest', run_name='__main__')" tests.test_data_ledger tests.test_run_readiness tests.test_console_state -v
```

Expected: PASS.

Commit:

```powershell
git add BrainWorkflow/wqb/data_ledger.py BrainWorkflow/tests/test_data_ledger.py BrainWorkflow/wqb/run_readiness.py BrainWorkflow/tests/test_run_readiness.py BrainWorkflow/wqb/console_state.py BrainWorkflow/tests/test_console_state.py
git commit -m "enforce authoritative data ledger readiness"
```

---

### Task 4: Operator Semantic Ledger

**Files:**
- Create: `BrainWorkflow/wqb/operator_semantics.py`
- Create: `BrainWorkflow/tests/test_operator_semantics.py`
- Modify: `BrainWorkflow/wqb/cli.py`
- Modify: `BrainWorkflow/tests/test_cli.py`

**Interfaces:**
- Produces: `OperatorSemanticRecord`
- Produces: `operator_semantic_record_from_dict(row: dict[str, Any]) -> OperatorSemanticRecord`
- Produces: `operator_semantic_record_to_dict(record: OperatorSemanticRecord) -> dict[str, Any]`
- Produces: `load_operator_semantics(path: Path) -> list[OperatorSemanticRecord]`
- Produces: `write_operator_semantics_jsonl(path: Path, records: list[OperatorSemanticRecord]) -> Path`
- Produces: `write_operator_semantics_markdown(path: Path, records: list[OperatorSemanticRecord], generated_at: str) -> Path`
- Produces: `score_operator_for_template(record: OperatorSemanticRecord, field_type: str, template_tags: list[str]) -> float`
- Produces CLI command: `compile-operator-semantics`

- [ ] **Step 1: Write failing operator semantic tests**

Create `BrainWorkflow/tests/test_operator_semantics.py`:

```python
import tempfile
import unittest
from pathlib import Path

from wqb.operator_semantics import (
    OperatorSemanticRecord,
    load_operator_semantics,
    operator_semantic_record_from_dict,
    score_operator_for_template,
    write_operator_semantics_jsonl,
    write_operator_semantics_markdown,
)


class OperatorSemanticsTests(unittest.TestCase):
    def test_operator_semantic_record_loads_workflow_use_and_risk(self):
        record = operator_semantic_record_from_dict(
            {
                "operator": "group_neutralize",
                "family": "neutralization",
                "workflow_uses": ["reduce_correlation", "remove_group_bias"],
                "compatible_field_types": ["MATRIX"],
                "template_tags": ["cross_sectional_normalizer", "repair"],
                "risk_tags": ["over_neutralization"],
                "repair_levers": ["neutralization_industry", "neutralization_subindustry"],
                "source_paths": ["wiki/20_semantics/operator_catalog_official.md"],
            }
        )

        self.assertEqual(record.operator, "group_neutralize")
        self.assertIn("reduce_correlation", record.workflow_uses)
        self.assertGreater(score_operator_for_template(record, "MATRIX", ["repair"]), 0.0)
        self.assertLess(score_operator_for_template(record, "VECTOR", ["repair"]), score_operator_for_template(record, "MATRIX", ["repair"]))

    def test_write_and_load_operator_semantics_jsonl_and_markdown(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            jsonl = root / "operator_semantics.jsonl"
            md = root / "operator_semantics.md"
            record = OperatorSemanticRecord(
                operator="vec_avg",
                family="vector_to_matrix",
                workflow_uses=["summarize_vector_values"],
                compatible_field_types=["VECTOR"],
                template_tags=["event_value"],
                risk_tags=["invalid_raw_vector_use"],
                repair_levers=["replace_vec_count_with_vec_avg"],
                source_paths=["wiki/20_semantics/operators.md"],
            )

            write_operator_semantics_jsonl(jsonl, [record])
            write_operator_semantics_markdown(md, [record], "2026-07-22T00:00:00+00:00")
            loaded = load_operator_semantics(jsonl)
            markdown = md.read_text(encoding="utf-8")

        self.assertEqual(loaded[0].operator, "vec_avg")
        self.assertIn("vector_to_matrix", markdown)
        self.assertIn("summarize_vector_values", markdown)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests and confirm RED**

Run:

```powershell
python -c "import sys, runpy; sys.platform='linux'; runpy.run_module('unittest', run_name='__main__')" tests.test_operator_semantics -v
```

Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `operator_semantics.py`**

Create `BrainWorkflow/wqb/operator_semantics.py`:

```python
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any


FIELD_TYPE_BONUS = 3.0
TAG_MATCH_BONUS = 0.8
RISK_PENALTY = 0.4


@dataclass(frozen=True)
class OperatorSemanticRecord:
    operator: str
    family: str
    workflow_uses: list[str]
    compatible_field_types: list[str]
    template_tags: list[str]
    risk_tags: list[str]
    repair_levers: list[str]
    source_paths: list[str]


def operator_semantic_record_from_dict(row: dict[str, Any]) -> OperatorSemanticRecord:
    """Input: dict row. Output: OperatorSemanticRecord. Normalize one operator semantic row."""
    return OperatorSemanticRecord(
        operator=str(row.get("operator", "")),
        family=str(row.get("family", "")),
        workflow_uses=[str(item) for item in row.get("workflow_uses", []) if str(item)],
        compatible_field_types=[str(item).upper() for item in row.get("compatible_field_types", []) if str(item)],
        template_tags=[str(item) for item in row.get("template_tags", []) if str(item)],
        risk_tags=[str(item) for item in row.get("risk_tags", []) if str(item)],
        repair_levers=[str(item) for item in row.get("repair_levers", []) if str(item)],
        source_paths=[str(item) for item in row.get("source_paths", []) if str(item)],
    )


def operator_semantic_record_to_dict(record: OperatorSemanticRecord) -> dict[str, Any]:
    """Input: OperatorSemanticRecord. Output: dict. Convert a record to JSON-safe data."""
    return asdict(record)


def load_operator_semantics(path: Path) -> list[OperatorSemanticRecord]:
    """Input: JSONL path. Output: operator semantic records. Load operator workflow meanings."""
    if not path.exists():
        return []
    records: list[OperatorSemanticRecord] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            records.append(operator_semantic_record_from_dict(json.loads(line)))
    return records


def write_operator_semantics_jsonl(path: Path, records: list[OperatorSemanticRecord]) -> Path:
    """Input: path and records. Output: path. Write operator semantics as deterministic JSONL."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in sorted(records, key=lambda item: item.operator):
            handle.write(json.dumps(operator_semantic_record_to_dict(record), ensure_ascii=False, sort_keys=True) + "\n")
    return path


def write_operator_semantics_markdown(path: Path, records: list[OperatorSemanticRecord], generated_at: str) -> Path:
    """Input: path, records, timestamp. Output: path. Write human-readable operator semantics."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Operator Semantics",
        "",
        f"Generated at: `{generated_at}`",
        "",
        "| Operator | Family | Workflow Uses | Field Types | Template Tags | Risks | Repair Levers |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for record in sorted(records, key=lambda item: item.operator):
        lines.append(
            "| {} | {} | {} | {} | {} | {} | {} |".format(
                record.operator,
                record.family,
                ", ".join(record.workflow_uses),
                ", ".join(record.compatible_field_types),
                ", ".join(record.template_tags),
                ", ".join(record.risk_tags),
                ", ".join(record.repair_levers),
            )
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def score_operator_for_template(record: OperatorSemanticRecord, field_type: str, template_tags: list[str]) -> float:
    """Input: operator record, field type, template tags. Output: score. Rank operator fit for template work."""
    score = 0.0
    if field_type.upper() in {item.upper() for item in record.compatible_field_types}:
        score += FIELD_TYPE_BONUS
    else:
        score -= FIELD_TYPE_BONUS
    shared = {item.lower() for item in template_tags} & {item.lower() for item in record.template_tags}
    score += len(shared) * TAG_MATCH_BONUS
    score -= len(record.risk_tags) * RISK_PENALTY
    return round(score, 4)
```

- [ ] **Step 4: Add CLI command**

In `BrainWorkflow/wqb/cli.py`, add `compile-operator-semantics` to command choices. Dispatch:

```python
elif args.command == "compile-operator-semantics":
    from datetime import datetime, timezone
    from wqb.operator_semantics import OperatorSemanticRecord, write_operator_semantics_jsonl, write_operator_semantics_markdown

    generated = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    root = Path(args.knowledge_root)
    records = [
        OperatorSemanticRecord(
            operator="rank",
            family="cross_sectional_normalizer",
            workflow_uses=["normalize_cross_section", "reduce_scale_dependency"],
            compatible_field_types=["MATRIX"],
            template_tags=["cross_sectional_normalizer"],
            risk_tags=["crowded_when_used_on_price_volume_only"],
            repair_levers=["group_rank", "group_neutralize"],
            source_paths=["wiki/20_semantics/operator_catalog_official.md"],
        ),
        OperatorSemanticRecord(
            operator="ts_delta",
            family="time_series_change",
            workflow_uses=["capture_recent_change", "event_surprise"],
            compatible_field_types=["MATRIX"],
            template_tags=["time_series_surprise", "event"],
            risk_tags=["turnover_inflation"],
            repair_levers=["increase_window", "add_decay"],
            source_paths=["wiki/20_semantics/operator_catalog_official.md"],
        ),
        OperatorSemanticRecord(
            operator="vec_avg",
            family="vector_to_matrix",
            workflow_uses=["summarize_vector_values"],
            compatible_field_types=["VECTOR"],
            template_tags=["event_value", "vector_to_matrix"],
            risk_tags=["invalid_raw_vector_use"],
            repair_levers=["replace_vec_count_with_vec_avg"],
            source_paths=["wiki/20_semantics/operators.md"],
        ),
    ]
    jsonl_path = root / "wiki" / "20_semantics" / "operator_semantics.jsonl"
    md_path = root / "wiki" / "20_semantics" / "operator_semantics.md"
    write_operator_semantics_jsonl(jsonl_path, records)
    write_operator_semantics_markdown(md_path, records, generated)
    print(json.dumps({"record_count": len(records), "jsonl_path": str(jsonl_path), "markdown_path": str(md_path)}, ensure_ascii=False, indent=2))
```

- [ ] **Step 5: Run focused tests and commit**

Run:

```powershell
python -c "import sys, runpy; sys.platform='linux'; runpy.run_module('unittest', run_name='__main__')" tests.test_operator_semantics tests.test_cli -v
```

Expected: PASS.

Commit:

```powershell
git add BrainWorkflow/wqb/operator_semantics.py BrainWorkflow/tests/test_operator_semantics.py BrainWorkflow/wqb/cli.py BrainWorkflow/tests/test_cli.py
git commit -m "add operator semantic ledger"
```

---

### Task 5: Template Matrix Upgrade

**Files:**
- Modify: `BrainWorkflow/wqb/template_library.py`
- Modify: `BrainWorkflow/tests/test_template_library.py`
- Modify: `BrainWorkflow/wqb/research_scheduler.py`
- Modify: `BrainWorkflow/tests/test_research_scheduler.py`

**Interfaces:**
- Extends: `TemplateRecord`
- Adds fields: `data_semantics`, `economic_hypothesis`, `operator_composition`, `abandon_conditions`, `benchmark_rule_ids`, `template_family`
- Produces: `template_matrix_ready(template: TemplateRecord) -> bool`
- Produces: `template_matrix_summary(templates: list[TemplateRecord]) -> dict[str, Any]`

- [ ] **Step 1: Write failing template matrix tests**

Add to `BrainWorkflow/tests/test_template_library.py`:

```python
    def test_template_record_loads_matrix_fields_with_backward_compatibility(self):
        legacy = template_record_from_dict(
            {
                "template_id": "matrix_fast_delta_rank",
                "hypothesis": "Fresh changes capture underreaction.",
                "skeleton": "rank(ts_delta({field}, 1))",
                "required_field_types": ["MATRIX"],
                "compatible_semantic_tags": ["event"],
                "operator_tags": ["time_series_surprise"],
                "status": "seed",
                "correlation_risk": "low",
                "repair_levers": ["window_3"],
                "source_paths": ["wiki/30_templates/template_families.md"],
            }
        )
        matrix = template_record_from_dict(
            template_record_to_dict(legacy)
            | {
                "data_semantics": ["fast_d1", "event"],
                "economic_hypothesis": "Fresh event data is incorporated gradually.",
                "operator_composition": ["ts_delta", "rank"],
                "abandon_conditions": ["three_batches_no_signal"],
                "benchmark_rule_ids": ["near_miss_stable_pnl"],
                "template_family": "event_surprise",
            }
        )

        self.assertFalse(template_matrix_ready(legacy))
        self.assertTrue(template_matrix_ready(matrix))
        self.assertEqual(template_matrix_summary([legacy, matrix])["matrix_ready_count"], 1)
```

- [ ] **Step 2: Run tests and confirm RED**

Run:

```powershell
python -c "import sys, runpy; sys.platform='linux'; runpy.run_module('unittest', run_name='__main__')" tests.test_template_library -v
```

Expected: FAIL because matrix fields and helpers are absent.

- [ ] **Step 3: Extend `TemplateRecord`**

In `BrainWorkflow/wqb/template_library.py`, add fields to the dataclass with default factories:

```python
    data_semantics: list[str] = field(default_factory=list)
    economic_hypothesis: str = ""
    operator_composition: list[str] = field(default_factory=list)
    abandon_conditions: list[str] = field(default_factory=list)
    benchmark_rule_ids: list[str] = field(default_factory=list)
    template_family: str = ""
```

In `template_record_from_dict(...)`, add:

```python
        data_semantics=[str(item) for item in row.get("data_semantics", []) if str(item)],
        economic_hypothesis=str(row.get("economic_hypothesis", row.get("hypothesis", ""))),
        operator_composition=[str(item) for item in row.get("operator_composition", []) if str(item)],
        abandon_conditions=[str(item) for item in row.get("abandon_conditions", []) if str(item)],
        benchmark_rule_ids=[str(item) for item in row.get("benchmark_rule_ids", []) if str(item)],
        template_family=str(row.get("template_family", "")),
```

Add helpers:

```python
def template_matrix_ready(template: TemplateRecord) -> bool:
    """Input: template record. Output: bool. Check whether template has the full matrix fields."""
    return all(
        [
            bool(template.data_semantics),
            bool(template.economic_hypothesis),
            bool(template.operator_composition),
            bool(template.repair_levers),
            bool(template.abandon_conditions),
            bool(template.template_family),
        ]
    )


def template_matrix_summary(templates: list[TemplateRecord]) -> dict[str, Any]:
    """Input: templates. Output: summary dict. Count matrix readiness."""
    ready = [template for template in templates if template_matrix_ready(template)]
    return {
        "template_count": len(templates),
        "matrix_ready_count": len(ready),
        "seed_only_count": len(templates) - len(ready),
    }
```

Update Markdown rendering to include `Family` and `Matrix Ready` columns:

```python
"| Template | Family | Status | Matrix Ready | Hypothesis | Field Types | Tags | Risk |",
"| --- | --- | --- | --- | --- | --- | --- | --- |",
```

and each row:

```python
ready = "yes" if template_matrix_ready(template) else "no"
lines.append(
    f"| `{template.template_id}` | {template.template_family} | {template.status} | {ready} | {template.hypothesis} | {field_types} | {tags} | {template.correlation_risk} |"
)
```

- [ ] **Step 4: Update scheduler to prefer matrix-ready templates**

In `BrainWorkflow/wqb/template_library.py`, adjust `score_template_for_data(...)`:

```python
    if template_matrix_ready(template):
        score += 1.0
```

This keeps the selection API stable while making complete templates rank higher.

- [ ] **Step 5: Run focused tests and commit**

Run:

```powershell
python -c "import sys, runpy; sys.platform='linux'; runpy.run_module('unittest', run_name='__main__')" tests.test_template_library tests.test_research_scheduler -v
```

Expected: PASS.

Commit:

```powershell
git add BrainWorkflow/wqb/template_library.py BrainWorkflow/tests/test_template_library.py BrainWorkflow/wqb/research_scheduler.py BrainWorkflow/tests/test_research_scheduler.py
git commit -m "upgrade template library to matrix records"
```

---

### Task 6: Benchmark Rulebook

**Files:**
- Create: `BrainWorkflow/wqb/benchmark_rules.py`
- Create: `BrainWorkflow/tests/test_benchmark_rules.py`
- Modify: `BrainWorkflow/wqb/workflow_proposals.py`
- Modify: `BrainWorkflow/tests/test_workflow_proposals.py`

**Interfaces:**
- Produces: `BenchmarkRule`
- Produces: `benchmark_rule_from_dict(row: dict[str, Any]) -> BenchmarkRule`
- Produces: `benchmark_rule_to_dict(rule: BenchmarkRule) -> dict[str, Any]`
- Produces: `load_benchmark_rules(path: Path) -> list[BenchmarkRule]`
- Produces: `write_benchmark_rules_jsonl(path: Path, rules: list[BenchmarkRule]) -> Path`
- Produces: `write_benchmark_rules_markdown(path: Path, rules: list[BenchmarkRule], generated_at: str) -> Path`
- Produces: `default_benchmark_rules() -> list[BenchmarkRule]`
- Produces: `rules_for_issue_type(rules: list[BenchmarkRule], issue_type: str) -> list[BenchmarkRule]`

- [ ] **Step 1: Write failing benchmark rule tests**

Create `BrainWorkflow/tests/test_benchmark_rules.py`:

```python
import tempfile
import unittest
from pathlib import Path

from wqb.benchmark_rules import (
    default_benchmark_rules,
    load_benchmark_rules,
    rules_for_issue_type,
    write_benchmark_rules_jsonl,
    write_benchmark_rules_markdown,
)


class BenchmarkRulesTests(unittest.TestCase):
    def test_default_rules_include_near_miss_and_correlation_cases(self):
        rules = default_benchmark_rules()
        ids = {rule.rule_id for rule in rules}

        self.assertIn("near_miss_stable_pnl_promotion", ids)
        self.assertIn("prod_correlation_novelty_required", ids)
        self.assertTrue(rules_for_issue_type(rules, "pnl_signal"))
        self.assertTrue(rules_for_issue_type(rules, "prod_correlation"))

    def test_write_and_load_benchmark_rules(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            jsonl = root / "benchmark_rules.jsonl"
            md = root / "benchmark_rules.md"
            rules = default_benchmark_rules()

            write_benchmark_rules_jsonl(jsonl, rules)
            write_benchmark_rules_markdown(md, rules, "2026-07-22T00:00:00+00:00")
            loaded = load_benchmark_rules(jsonl)
            markdown = md.read_text(encoding="utf-8")

        self.assertEqual(len(loaded), len(rules))
        self.assertIn("near_miss_stable_pnl_promotion", markdown)
        self.assertIn("3q7OQaog", markdown)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests and confirm RED**

Run:

```powershell
python -c "import sys, runpy; sys.platform='linux'; runpy.run_module('unittest', run_name='__main__')" tests.test_benchmark_rules -v
```

Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement benchmark rules module**

Create `BrainWorkflow/wqb/benchmark_rules.py`:

```python
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any


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


def default_benchmark_rules() -> list[BenchmarkRule]:
    """Input: none. Output: default benchmark rules. Seed active rules from Stage 1 lessons."""
    return [
        BenchmarkRule(
            rule_id="near_miss_stable_pnl_promotion",
            issue_types=["pnl_signal", "near_miss"],
            description="Stable PnL shape should promote an alpha into repair review even when one metric misses threshold.",
            promotion_condition="PnL is visually stable or monotonic enough to resemble the 3q7OQaog signal-recognition case.",
            action="Create a repair candidate and test one lever at a time before abandoning.",
            evidence_paths=["knowledge/wiki/50_benchmarks/signal_quality_and_repairability.md"],
            consumed_by=["triage", "repair_loop", "workflow_proposals"],
            risk="May spend repair budget on fragile in-sample signals.",
        ),
        BenchmarkRule(
            rule_id="prod_correlation_novelty_required",
            issue_types=["prod_correlation", "correlation"],
            description="Repeated production-correlation failures require a distinct data source, operator skeleton, or economic hypothesis.",
            promotion_condition="Candidate or family fails production correlation after otherwise acceptable metrics.",
            action="Down-rank the data-template pair and request template or data novelty before another batch.",
            evidence_paths=["knowledge/wiki/50_benchmarks/correlation_and_novelty.md"],
            consumed_by=["research_planner", "candidate_gate", "repair_loop"],
            risk="May suppress a family that could pass with a large quality improvement.",
        ),
    ]


def load_benchmark_rules(path: Path) -> list[BenchmarkRule]:
    """Input: JSONL path. Output: benchmark rules. Load active rulebook."""
    if not path.exists():
        return []
    return [benchmark_rule_from_dict(json.loads(line)) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


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
```

- [ ] **Step 4: Connect proposals to benchmark rules**

In `BrainWorkflow/wqb/workflow_proposals.py`, import:

```python
from wqb.benchmark_rules import default_benchmark_rules, rules_for_issue_type
```

At the start of `_rule_text(issue_type: str, summary: str)`, add:

```python
    matched_rules = rules_for_issue_type(default_benchmark_rules(), issue_type)
    if matched_rules:
        rule = matched_rules[0]
        return (
            rule.action,
            f"Applies active benchmark rule `{rule.rule_id}` before the issue recurs.",
            rule.risk,
        )
```

- [ ] **Step 5: Run focused tests and commit**

Run:

```powershell
python -c "import sys, runpy; sys.platform='linux'; runpy.run_module('unittest', run_name='__main__')" tests.test_benchmark_rules tests.test_workflow_proposals -v
```

Expected: PASS.

Commit:

```powershell
git add BrainWorkflow/wqb/benchmark_rules.py BrainWorkflow/tests/test_benchmark_rules.py BrainWorkflow/wqb/workflow_proposals.py BrainWorkflow/tests/test_workflow_proposals.py
git commit -m "add active benchmark rulebook"
```

---

### Task 7: Proposal Lifecycle Upgrade

**Files:**
- Modify: `BrainWorkflow/wqb/workflow_proposals.py`
- Modify: `BrainWorkflow/tests/test_workflow_proposals.py`
- Modify: `BrainWorkflow/wqb/console_proposals.py`
- Modify: `BrainWorkflow/tests/test_console_proposals.py`
- Modify: `BrainWorkflow/wqb/console_server.py`
- Modify: `BrainWorkflow/tests/test_console_server.py`

**Interfaces:**
- Extends: `WorkflowChangeProposal`
- Adds fields: `current_behavior`, `expected_impact`, `applied_at`, `supersedes`
- Produces: `PROPOSAL_STATUSES = ("proposed", "rejected", "accepted_for_wiki", "accepted_for_implementation", "accepted_as_experiment", "applied", "deferred")`
- Produces: `normalize_proposal_status(status: str) -> str`

- [ ] **Step 1: Write failing lifecycle tests**

Add to `BrainWorkflow/tests/test_workflow_proposals.py`:

```python
    def test_update_workflow_proposal_decision_accepts_spec_b_lifecycle_statuses(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            proposal = WorkflowChangeProposal(
                proposal_id="p1",
                generated_at="2026-07-22T00:00:00+00:00",
                issue_type="data_coverage",
                title="Cache-only ledger blocked research",
                trigger="Research readiness saw only cache rows.",
                evidence_paths=["knowledge/wiki/20_semantics/data_ledger.jsonl"],
                affected_modules=["run_readiness", "research_planner"],
                proposed_rule_change="Require authoritative measured data before research.",
                expected_benefit="Prevents false readiness.",
                risk="May block research until capture completes.",
                required_code_changes=["run_readiness"],
                required_knowledge_updates=["knowledge/wiki/20_semantics/data_ledger.md"],
                user_decision_options=["accepted_for_wiki", "accepted_for_implementation", "rejected", "deferred"],
                status="proposed",
                current_behavior="Cache rows can appear in planner inputs.",
                expected_impact="Planner waits for measured data.",
                applied_at="",
                supersedes=[],
            )
            write_workflow_proposals(output_dir, [proposal])

            update_workflow_proposal_decision(output_dir, "p1", "accepted_for_implementation", "Implement readiness guard.")
            rows = load_workflow_proposals(output_dir)

        self.assertEqual(rows[0]["status"], "accepted_for_implementation")
        self.assertEqual(rows[0]["user_decision"], "Implement readiness guard.")
        self.assertEqual(rows[0]["current_behavior"], "Cache rows can appear in planner inputs.")
```

- [ ] **Step 2: Run tests and confirm RED**

Run:

```powershell
python -c "import sys, runpy; sys.platform='linux'; runpy.run_module('unittest', run_name='__main__')" tests.test_workflow_proposals -v
```

Expected: FAIL because fields and status are absent.

- [ ] **Step 3: Extend proposal dataclass and status validation**

In `BrainWorkflow/wqb/workflow_proposals.py`, add:

```python
PROPOSAL_STATUSES = (
    "proposed",
    "rejected",
    "accepted_for_wiki",
    "accepted_for_implementation",
    "accepted_as_experiment",
    "applied",
    "deferred",
)


def normalize_proposal_status(status: str) -> str:
    """Input: status string. Output: normalized status. Validate proposal lifecycle status."""
    normalized = str(status).strip().lower()
    if normalized == "accepted":
        normalized = "accepted_for_implementation"
    if normalized not in PROPOSAL_STATUSES:
        raise ValueError(f"unsupported proposal status: {status}")
    return normalized
```

Extend `WorkflowChangeProposal`:

```python
    current_behavior: str = ""
    expected_impact: str = ""
    applied_at: str = ""
    supersedes: list[str] | None = None
```

Update `proposal_from_issue(...)`:

```python
        user_decision_options=["accepted_for_wiki", "accepted_for_implementation", "accepted_as_experiment", "rejected", "deferred"],
        current_behavior=summary,
        expected_impact=expected_benefit,
        applied_at="",
        supersedes=[],
```

Update `_proposal_from_dict(...)` with defaults for the new fields.

Update `update_workflow_proposal_decision(...)`:

```python
    normalized_status = normalize_proposal_status(status)
...
            row["status"] = normalized_status
```

- [ ] **Step 4: Update console proposal select controls**

In `BrainWorkflow/wqb/console_server.py`, proposal decision controls should use select options:

```html
<select name="status">
  <option value="accepted_for_wiki">accepted_for_wiki</option>
  <option value="accepted_for_implementation">accepted_for_implementation</option>
  <option value="accepted_as_experiment">accepted_as_experiment</option>
  <option value="rejected">rejected</option>
  <option value="deferred">deferred</option>
</select>
```

Add test assertion in `tests/test_console_server.py`:

```python
self.assertIn("accepted_for_implementation", html)
self.assertIn("accepted_as_experiment", html)
```

- [ ] **Step 5: Run focused tests and commit**

Run:

```powershell
python -c "import sys, runpy; sys.platform='linux'; runpy.run_module('unittest', run_name='__main__')" tests.test_workflow_proposals tests.test_console_proposals tests.test_console_server -v
```

Expected: PASS.

Commit:

```powershell
git add BrainWorkflow/wqb/workflow_proposals.py BrainWorkflow/tests/test_workflow_proposals.py BrainWorkflow/wqb/console_proposals.py BrainWorkflow/tests/test_console_proposals.py BrainWorkflow/wqb/console_server.py BrainWorkflow/tests/test_console_server.py
git commit -m "upgrade workflow proposal lifecycle"
```

---

### Task 8: Research Planner Contract Inputs

**Files:**
- Modify: `BrainWorkflow/wqb/research_planner.py`
- Modify: `BrainWorkflow/tests/test_research_planner.py`
- Modify: `BrainWorkflow/wqb/option_cards.py`
- Modify: `BrainWorkflow/tests/test_orchestrator.py`

**Interfaces:**
- Consumes from Task 3: `summarize_data_ledger_authority`
- Consumes from Task 4: `load_operator_semantics`
- Consumes from Task 5: `template_matrix_summary`
- Consumes from Task 6: `load_benchmark_rules`
- Produces option card fields:
  - `data_authority`
  - `operator_semantic_count`
  - `template_matrix_ready_count`
  - `benchmark_rule_count`
  - `maintenance_blockers`

- [ ] **Step 1: Write failing planner input test**

Add to `BrainWorkflow/tests/test_research_planner.py`:

```python
    def test_plan_research_options_records_semantic_inputs_and_cache_blocker(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "knowledge"
            write_seed_knowledge(root)

            result = plan_research_options(
                knowledge_root=root,
                generated_at="2026-07-22T00:00:00+00:00",
                max_options=2,
                live_api_enabled=False,
            )

        option = result["options"][0]
        self.assertIn("data_authority", option)
        self.assertIn("template_matrix_ready_count", option)
        self.assertIn("benchmark_rule_count", option)
        self.assertIn("maintenance_blockers", option)
        self.assertIn("authoritative data ledger", " ".join(option["maintenance_blockers"]).lower())
```

If existing `plan_research_options` uses a different signature, keep its current signature and add only the new fields to its returned option rows.

- [ ] **Step 2: Run tests and confirm RED**

Run:

```powershell
python -c "import sys, runpy; sys.platform='linux'; runpy.run_module('unittest', run_name='__main__')" tests.test_research_planner -v
```

Expected: FAIL because new option card fields are absent.

- [ ] **Step 3: Add planner input summaries**

In `BrainWorkflow/wqb/research_planner.py`, load optional ledgers from the knowledge root:

```python
from wqb.benchmark_rules import load_benchmark_rules
from wqb.data_ledger import load_data_ledger, summarize_data_ledger_authority
from wqb.operator_semantics import load_operator_semantics
from wqb.template_library import load_template_library, template_matrix_summary
```

Add helper:

```python
def _planner_contract_inputs(knowledge_root: Path) -> dict[str, Any]:
    """Input: knowledge root. Output: planner input summary. Summarize semantic ledgers for option cards."""
    data_records = load_data_ledger(knowledge_root / "wiki" / "20_semantics" / "data_ledger.jsonl")
    template_records = load_template_library(knowledge_root / "wiki" / "30_templates" / "template_library.jsonl")
    operators = load_operator_semantics(knowledge_root / "wiki" / "20_semantics" / "operator_semantics.jsonl")
    benchmark_rules = load_benchmark_rules(knowledge_root / "wiki" / "50_benchmarks" / "benchmark_rules.jsonl")
    data_authority = summarize_data_ledger_authority(data_records)
    blockers = []
    if not data_authority.get("authoritative_measured_count"):
        blockers.append("Authoritative data ledger is missing or has no measured platform rows.")
    return {
        "data_authority": data_authority,
        "operator_semantic_count": len(operators),
        "template_matrix_ready_count": template_matrix_summary(template_records)["matrix_ready_count"],
        "benchmark_rule_count": len(benchmark_rules),
        "maintenance_blockers": blockers,
    }
```

When building each option card, merge this dict:

```python
option.update(_planner_contract_inputs(Path(knowledge_root)))
```

If the module currently returns dataclasses, add these fields to the dataclass and output conversion instead.

- [ ] **Step 4: Preserve Orchestrator start snapshot compatibility**

In `BrainWorkflow/wqb/option_cards.py`, ensure normalization keeps the new fields as pass-through keys:

```python
PASSTHROUGH_OPTION_FIELDS = {
    "data_authority",
    "operator_semantic_count",
    "template_matrix_ready_count",
    "benchmark_rule_count",
    "maintenance_blockers",
}
```

If option normalization currently copies extra keys, add a regression test to confirm the new keys are retained.

- [ ] **Step 5: Run focused tests and commit**

Run:

```powershell
python -c "import sys, runpy; sys.platform='linux'; runpy.run_module('unittest', run_name='__main__')" tests.test_research_planner tests.test_orchestrator -v
```

Expected: PASS.

Commit:

```powershell
git add BrainWorkflow/wqb/research_planner.py BrainWorkflow/tests/test_research_planner.py BrainWorkflow/wqb/option_cards.py BrainWorkflow/tests/test_orchestrator.py
git commit -m "add planner semantic input summaries"
```

---

### Task 9: Console Contract Visibility

**Files:**
- Modify: `BrainWorkflow/wqb/console_state.py`
- Modify: `BrainWorkflow/tests/test_console_state.py`
- Modify: `BrainWorkflow/wqb/console_server.py`
- Modify: `BrainWorkflow/tests/test_console_server.py`
- Modify: `BrainWorkflow/docs/operations/operating_guide.md`

**Interfaces:**
- Consumes state keys:
  - `knowledge_contracts`
  - `data_authority`
  - `option_cards[*].maintenance_blockers`
- Produces dashboard panels:
  - Knowledge Contracts
  - Data Authority
  - Semantic Ledgers
  - Proposal Lifecycle

- [ ] **Step 1: Write failing console rendering tests**

Add to `BrainWorkflow/tests/test_console_server.py`:

```python
    def test_render_dashboard_labels_cache_data_as_not_authoritative(self):
        state = {
            "readiness": {"exists": True, "passed": False},
            "freshness": {"valid": True, "stale_count": 0, "missing_count": 0},
            "data_coverage": {"field_count": 14, "scope_count": 1, "data_set_count": 4, "error_count": 0, "status": "completed"},
            "data_authority": {"record_count": 14, "authoritative_measured_count": 0, "seed_cache_count": 14, "unclassified_count": 0, "authoritative_ready": False},
            "knowledge_contracts": {"issue_count": 2, "legacy_count": 1, "issues": []},
            "option_cards": [{"option_id": "option-1", "title": "Power Pool", "maintenance_blockers": ["Authoritative data ledger is missing."]}],
            "startable_scopes": [],
            "jobs": [],
            "active_workflow": {"exists": False},
            "approved_queue": [],
            "queue_diagnostics": [],
            "workflow_events": [],
            "proposal_counts": {"accepted_for_implementation": 1},
            "schedule": {"preview": ""},
        }

        html = render_dashboard(state)

        self.assertIn("Data Authority", html)
        self.assertIn("seed/cache", html)
        self.assertIn("authoritative measured", html)
        self.assertIn("Knowledge Contracts", html)
        self.assertIn("Authoritative data ledger is missing", html)
```

- [ ] **Step 2: Run tests and confirm RED**

Run:

```powershell
python -c "import sys, runpy; sys.platform='linux'; runpy.run_module('unittest', run_name='__main__')" tests.test_console_server -v
```

Expected: FAIL because panels are not rendered.

- [ ] **Step 3: Render contract panels**

In `BrainWorkflow/wqb/console_server.py`, add helpers:

```python
def _render_data_authority(authority: dict[str, Any]) -> str:
    """Input: authority summary. Output: HTML. Render data ledger provenance."""
    ready = "yes" if authority.get("authoritative_ready") else "no"
    return (
        "<div class='ledger-strip'>"
        + _badge("authoritative measured", authority.get("authoritative_measured_count", 0), "ready" if ready == "yes" else "warn")
        + _badge("seed/cache", authority.get("seed_cache_count", 0), "warn")
        + _badge("unclassified", authority.get("unclassified_count", 0), "warn")
        + _badge("ready", ready, "ready" if ready == "yes" else "blocked")
        + "</div>"
    )


def _render_knowledge_contracts(contracts: dict[str, Any]) -> str:
    """Input: contract health summary. Output: HTML. Render vault contract health."""
    return (
        "<div class='ledger-strip'>"
        + _badge("issues", contracts.get("issue_count", 0), "warn" if contracts.get("issue_count") else "ready")
        + _badge("legacy paths", contracts.get("legacy_count", 0), "warn" if contracts.get("legacy_count") else "ready")
        + "</div>"
    )


def _option_blockers(cards: list[dict[str, Any]]) -> str:
    """Input: option cards. Output: HTML. Render maintenance blockers attached to options."""
    blockers = []
    for card in cards:
        blockers.extend(str(item) for item in card.get("maintenance_blockers", []) if str(item))
    if not blockers:
        return "<div class='empty'>No option maintenance blockers.</div>"
    return "<ul>" + "".join(f"<li>{escape(item)}</li>" for item in blockers[:6]) + "</ul>"
```

Add sections to `render_dashboard(...)`:

```python
<section><h2>Data Authority</h2>{_render_data_authority(state.get("data_authority", {}))}</section>
<section><h2>Knowledge Contracts</h2>{_render_knowledge_contracts(state.get("knowledge_contracts", {}))}</section>
<section><h2>Option Blockers</h2>{_option_blockers(cards)}</section>
```

- [ ] **Step 4: Update operating guide**

In `BrainWorkflow/docs/operations/operating_guide.md`, add:

```markdown
## Contract Status In The Console

The console distinguishes `seed/cache` data from `authoritative measured` data. Research starts should use authoritative measured data for the selected exact scope. If the console shows only seed/cache rows, run platform data-field maintenance before research.

The Knowledge Contracts panel reports legacy raw paths and missing raw/wiki metadata. These are maintenance issues, not alpha simulation failures.
```

- [ ] **Step 5: Run focused tests and commit**

Run:

```powershell
python -c "import sys, runpy; sys.platform='linux'; runpy.run_module('unittest', run_name='__main__')" tests.test_console_state tests.test_console_server -v
```

Expected: PASS.

Commit:

```powershell
git add BrainWorkflow/wqb/console_state.py BrainWorkflow/tests/test_console_state.py BrainWorkflow/wqb/console_server.py BrainWorkflow/tests/test_console_server.py BrainWorkflow/docs/operations/operating_guide.md
git commit -m "show knowledge contracts in console"
```

---

### Task 10: Canonical Vault Docs And Migration Inventory

**Files:**
- Modify: `C:\Users\oytl\Desktop\pyproject\brain\knowledge\README.md`
- Modify: `C:\Users\oytl\Desktop\pyproject\brain\knowledge\raw\source_index.md`
- Create: `C:\Users\oytl\Desktop\pyproject\brain\knowledge\wiki\80_maintenance\migration_inventory.md`
- Modify: `C:\Users\oytl\Desktop\pyproject\brain\knowledge\wiki\80_maintenance\raw_to_wiki_compile_rules.md`
- Modify: `C:\Users\oytl\Desktop\pyproject\brain\knowledge\wiki\80_maintenance\health_check_protocol.md`
- Modify: `BrainWorkflow/docs/operations/maintainer_handoff.md`
- Modify: `BrainWorkflow/README.md`

**Interfaces:**
- Consumes contract outputs from Tasks 1-9.
- Produces documented migration decisions for legacy raw paths and cache-only ledgers.

- [ ] **Step 1: Write a documentation validation command**

Run this before editing docs to capture current gaps:

```powershell
Set-Location 'C:\Users\oytl\Desktop\pyproject\brain'
rg -n "raw/learn|platform_metadata_cache|authoritative measured|operator_semantics|benchmark_rules|migration inventory" knowledge skills-and-workflows\BrainWorkflow\docs\operations skills-and-workflows\BrainWorkflow\README.md
```

Expected: output mentions old raw/cache paths and few or no authoritative measured contract references.

- [ ] **Step 2: Update knowledge README**

Edit `C:\Users\oytl\Desktop\pyproject\brain\knowledge\README.md` so the layout section states:

```markdown
## Canonical Contract

`raw/` stores source-faithful facts with front matter metadata. `wiki/` stores compiled interpretation and workflow rules with source backlinks. Machine JSONL ledgers under `wiki/` are planner interfaces, not replacements for Markdown source notes.

Cache or bootstrap rows are development seeds. Authoritative data scheduling requires measured platform data from `raw/platform/data_fields/YYYY-MM-DD/` compiled into `wiki/20_semantics/data_ledger.jsonl`.
```

- [ ] **Step 3: Write migration inventory**

Create `knowledge/wiki/80_maintenance/migration_inventory.md`:

```markdown
# Migration Inventory

## Current Legacy Or Mixed Sources

| Path | Status | Required Action | Reason |
| --- | --- | --- | --- |
| `knowledge/raw/learn/` | legacy_candidate | migrate_or_archive | Canonical platform Learn captures live under `raw/platform/learn/`. |
| `docs/knowledge/cache/platform_metadata_20260702_014429.json` | cache_seed_source | retain_ignored_cache | Current data ledger rows point here, but this is not authoritative measured data. |
| `docs/knowledge/cache/platform_metadata_20260703_022956.json` | cache_seed_source | retain_ignored_cache | Current data ledger rows point here, but this is not authoritative measured data. |

## Required Follow-Up

1. Run platform data-field capture into `raw/platform/data_fields/YYYY-MM-DD/` with live authorization.
2. Compile the authoritative data ledger from raw captures.
3. Re-run readiness in research mode for the selected exact scope.
4. Archive legacy raw paths only after their reusable facts are represented in canonical raw or wiki pages.
```

- [ ] **Step 4: Update maintenance docs**

In `raw_to_wiki_compile_rules.md`, add sections:

```markdown
## Authoritative Data Ledger Compile

The official data scheduling ledger is compiled from `raw/platform/data_fields/YYYY-MM-DD/`. A cache-derived ledger can document prior exploration, but it cannot certify platform-wide availability or exact scope freshness.
```

In `health_check_protocol.md`, add:

```markdown
## Contract Health Checks

Health checks must report legacy raw paths, raw files missing source metadata, wiki pages missing source backlinks, cache-only data ledgers, missing operator semantics, missing benchmark rules, and template records that are not matrix-ready.
```

- [ ] **Step 5: Update project operations docs**

In `BrainWorkflow/docs/operations/maintainer_handoff.md`, add:

```markdown
## Spec B Knowledge Contract

Before changing research scheduling, check whether planner inputs are authoritative or seed/cache. The approved Spec B design is `docs/superpowers/specs/2026-07-21-knowledge-workflow-operating-system-design.md`; implementation plan tasks live in `docs/superpowers/plans/2026-07-22-knowledge-workflow-operating-system-implementation.md`.
```

In `BrainWorkflow/README.md`, add a bullet under Operational docs:

```markdown
- `docs/superpowers/specs/2026-07-21-knowledge-workflow-operating-system-design.md`: canonical knowledge and workflow operating system contract.
```

- [ ] **Step 6: Run docs scan and commit code-repo docs only**

Run:

```powershell
Set-Location 'C:\Users\oytl\Desktop\pyproject\brain'
rg -n "authoritative measured|migration inventory|operator_semantics|benchmark_rules|Spec B Knowledge Contract" knowledge skills-and-workflows\BrainWorkflow\README.md skills-and-workflows\BrainWorkflow\docs\operations
```

Expected: output includes the new docs.

Commit only repository docs:

```powershell
Set-Location 'C:\Users\oytl\Desktop\pyproject\brain\skills-and-workflows'
git add BrainWorkflow/README.md BrainWorkflow/docs/operations/maintainer_handoff.md
git commit -m "document knowledge operating system contracts"
```

Root vault changes remain local knowledge-base updates unless the user asks to put the vault in a separate repository.

---

### Task 11: Full Verification And Final Review

**Files:**
- Modify: no production files unless verification or review finds a defect.
- Read: `BrainWorkflow/docs/superpowers/specs/2026-07-21-knowledge-workflow-operating-system-design.md`
- Read: `BrainWorkflow/docs/superpowers/plans/2026-07-22-knowledge-workflow-operating-system-implementation.md`

**Interfaces:**
- Consumes all prior task commits.
- Produces final verification evidence and review package.

- [ ] **Step 1: Run focused knowledge workflow suite**

Run:

```powershell
Set-Location 'C:\Users\oytl\Desktop\pyproject\brain\skills-and-workflows\BrainWorkflow'
python -c "import sys, runpy; sys.platform='linux'; runpy.run_module('unittest', run_name='__main__')" tests.test_knowledge_contracts tests.test_knowledge_freshness tests.test_data_ledger tests.test_run_readiness tests.test_operator_semantics tests.test_template_library tests.test_benchmark_rules tests.test_research_planner tests.test_workflow_proposals tests.test_console_state tests.test_console_server tests.test_cli -v
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
Set-Location 'C:\Users\oytl\Desktop\pyproject\brain\skills-and-workflows'
git diff --check
git status --short --branch
```

Expected:

- `compileall` exits 0;
- `git diff --check` exits 0 except known protected progress-file line-ending warnings if present;
- status shows only protected local progress files outside the intended implementation commits.

- [ ] **Step 4: Generate final review package**

Run:

```powershell
Set-Location 'C:\Users\oytl\Desktop\pyproject\brain\skills-and-workflows'
git diff --stat 2af5fc2..HEAD
git diff 2af5fc2..HEAD -- BrainWorkflow > .superpowers\sdd\final-review-knowledge-os-2af5fc2..HEAD.diff
```

Expected: diff file exists and covers only the Spec B implementation.

- [ ] **Step 5: Request code review**

Use `superpowers:requesting-code-review` with this brief:

```text
Review range: 2af5fc2..HEAD
Focus:
- knowledge raw/wiki contract parsing and health checks;
- data ledger authority classification and readiness blocking;
- operator semantic ledger;
- template matrix backward compatibility;
- benchmark rulebook and proposal lifecycle;
- planner input summaries and console visibility.

Do not review live WorldQuant BRAIN simulations or alpha submission behavior because this plan does not change those paths.
```

Fix any Critical or Important findings with tests.

- [ ] **Step 6: Update recovery docs and push when clean**

Update root `todo.md` and `milestone.md` with final verification evidence.

Push branch:

```powershell
git push origin agent/brainworkflow-phase2
```

If direct push fails with WinSock `10106`, use the Node REPL proxy fallback recorded in root `milestone.md`.

Expected: branch `agent/brainworkflow-phase2` is synced to GitHub.

---

## Plan Self-Review

Spec coverage:

- Canonical Knowledge Vault: Tasks 1, 2, 10.
- Raw Source Contract: Tasks 1, 2, 10.
- Wiki Compile Contract: Tasks 1, 2, 10.
- Data Semantic Ledger: Task 3.
- Operator Semantic Ledger: Task 4.
- Template Matrix: Task 5.
- Benchmark Rulebook: Task 6.
- Research Planner Inputs: Task 8.
- Workflow Intervention Policy: Tasks 7, 8, 10.
- Migration/Cleanup Contract: Task 10.
- Proposal-Based Rule Evolution: Task 7.
- Future Schema-First Interface: Tasks 3, 4, 5, 6, 7, 8, 10.

Type consistency:

- `DataLedgerRecord` remains backward compatible; new authority helpers use existing `source_quality`, `coverage_status`, and `source_updated_at` fields.
- `TemplateRecord` adds defaulted fields only, so old JSONL rows continue to load.
- `WorkflowChangeProposal` adds defaulted fields and normalizes the old `accepted` status to `accepted_for_implementation`.
- New semantic ledgers use JSONL load/write patterns already used by `data_ledger.py` and `template_library.py`.

Completion-marker scan:

- This plan contains no unresolved planning red-flag markers.

Execution recommendation:

- Use Subagent-Driven execution. Task boundaries are independent enough for fresh workers: contract parser, health checks, data authority, operator semantics, template matrix, benchmark rules, proposal lifecycle, planner inputs, console visibility, docs, and final review.
