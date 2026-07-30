# Simplified Knowledge Structure Delivery Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a fixed, testable knowledge maintenance and delivery-gate path that leaves `knowledge/` clean, keeps machine ledgers out of Obsidian wiki pages, supports stratified platform data capture, and preserves useful workflow lessons without relying on Codex chat context.

**Architecture:** Add a canonical knowledge path layer first, then migrate readers and writers to `knowledge/machine/` while keeping legacy read fallbacks during transition. Build a clean compile pipeline that generates compact human wiki pages, machine resources, cleanup logs, and delivery-gate reports, then expose the state through the existing CLI and Console without rewriting the Orchestrator research workflow.

**Tech Stack:** Python standard library, dataclasses, JSON, JSONL, Markdown files, `unittest`, existing BrainWorkflow CLI and Console modules, PowerShell verification commands.

## Global Constraints

- Preserve the existing Orchestrator, Console job model, readiness gates, candidate queue, and Scout -> Seed -> Discovery -> Repair -> Submit research workflow.
- The active knowledge tree is exactly `knowledge/raw`, `knowledge/machine`, and `knowledge/wiki`; root `todo.md`, root `milestone.md`, `runs/`, and project source files remain outside this contract.
- Machine resources live under `knowledge/machine`: `scope_matrix.jsonl`, `data_ledger.jsonl`, `operator_ledger.jsonl`, `template_library.jsonl`, `benchmark_rules.jsonl`, `research_records.jsonl`, `source_index.jsonl`, and `freshness_manifest.json`.
- Human wiki pages stay compact and experience-oriented: no full JSONL ledgers, no raw API dumps, and no chronological run dumps.
- Clean compile removes ordinary obsolete active mixed paths only after verification and refuses automatic deletion for `.env`, credential, secret, token, password, key, and ambiguous private files.
- Platform data capture broadens before depth: discover a scope matrix, sample bounded field counts across many scopes, and record partial coverage explicitly.
- Research workflows must continue to obey readiness gates. If only partial or stale platform knowledge exists, the system records a blocker rather than inventing coverage.
- Useful user corrections, repeated blockers, missed-signal examples, and workflow bugs become durable raw interaction notes, machine rules, tests, wiki lessons, or proposals.
- Execution must update root `todo.md` and `milestone.md` at task boundaries and before any interruption while the larger project remains incomplete.
- No live simulation or alpha submission is part of this implementation plan.
- Keep a schema-first extension point by centralizing path and resource contracts in one module; this implementation does not add a database, RAG service, or external dependency.

---

## File Structure

### New Files

- `BrainWorkflow/wqb/knowledge_paths.py`
  - Single source of truth for `raw/`, `machine/`, `wiki/`, managed resource names, legacy fallbacks, and safe relative path handling.
- `BrainWorkflow/tests/test_knowledge_paths.py`
  - Tests for canonical path resolution, legacy fallback, and top-level active-tree checks.
- `BrainWorkflow/wqb/knowledge_clean_compile.py`
  - Clean structure health checks, obsolete-path planning, sensitive-file refusal, cleanup log writing, and active-tree verification.
- `BrainWorkflow/tests/test_knowledge_clean_compile.py`
  - Tests for clean structure pass/fail, safe cleanup, refused sensitive cleanup, large wiki-machine-resource detection, and cleanup log content.
- `BrainWorkflow/wqb/knowledge_experience_compile.py`
  - Human-facing wiki compiler for compact learning pages and selected research case reports.
- `BrainWorkflow/tests/test_knowledge_experience_compile.py`
  - Tests for wiki page generation, compactness checks, promoted lessons, and case report selection.
- `BrainWorkflow/wqb/interaction_memory.py`
  - Raw conversation/workflow correction capture and compilation into lessons or proposal rows.
- `BrainWorkflow/tests/test_interaction_memory.py`
  - Tests for interaction note persistence, dedupe, classification, and generated lesson/proposal records.
- `BrainWorkflow/wqb/data_capture_plan.py`
  - Scope matrix discovery model, stratified capture plan builder, per-scope field-budget allocation, and plan persistence.
- `BrainWorkflow/tests/test_data_capture_plan.py`
  - Tests for scope matrix rows, balanced scope sampling, bounded per-scope field counts, and partial coverage metadata.
- `BrainWorkflow/wqb/knowledge_maintenance.py`
  - One callable pipeline for compile -> human wiki -> cleanup -> health report.
- `BrainWorkflow/tests/test_knowledge_maintenance.py`
  - Tests for successful clean compile and explicit failed/paused compile reports.
- `BrainWorkflow/wqb/delivery_gate.py`
  - Fixed handoff gate that verifies knowledge structure, machine resources, compact wiki, workflow start/continue boundary, Console endpoints, and local tests by report.
- `BrainWorkflow/tests/test_delivery_gate.py`
  - Tests for pass, fail, and accepted durable pause reports.

### Modified Files

- `BrainWorkflow/wqb/data_ledger_compile.py`
  - Write data ledger JSONL to `machine/data_ledger.jsonl`; write only compact Markdown summary to `wiki/20_data_semantics.md` through the human wiki compiler; update `machine/freshness_manifest.json`.
- `BrainWorkflow/wqb/data_ledger.py`
  - Add knowledge-root-aware ledger loader and writer helper while preserving direct path loading.
- `BrainWorkflow/wqb/template_library.py`
  - Add knowledge-root-aware template loader using `machine/template_library.jsonl` with legacy read fallback.
- `BrainWorkflow/wqb/benchmark_rules.py`
  - Move active rulebook authority to `machine/benchmark_rules.jsonl`; keep run snapshot validation deterministic.
- `BrainWorkflow/wqb/operator_semantics.py`
  - Write operator ledger to `machine/operator_ledger.jsonl`.
- `BrainWorkflow/wqb/knowledge_freshness.py`
  - Read freshness manifest from `machine/freshness_manifest.json`; report clean-structure issues from `knowledge_clean_compile`.
- `BrainWorkflow/wqb/knowledge_contracts.py`
  - Simplify canonical prefixes to the new `raw/`, `machine/`, `wiki/` contract and write machine `source_index.jsonl` plus compact raw `source_index.md`.
- `BrainWorkflow/wqb/run_readiness.py`
  - Read machine resources from `knowledge_paths.py` and keep legacy fallback during transition.
- `BrainWorkflow/wqb/research_planner.py`
  - Read machine data/template/rule resources through `knowledge_paths.py`.
- `BrainWorkflow/wqb/workflow_stage_adapters.py`
  - Read resource paths through `knowledge_paths.py` and preserve existing stage behavior.
- `BrainWorkflow/wqb/research_record.py`
  - Append authoritative run summaries to `machine/research_records.jsonl` and keep raw Markdown sync for source material.
- `BrainWorkflow/wqb/orchestrator.py`
  - Call the new research-record machine sync from the existing `_sync_research_record_unlocked` path.
- `BrainWorkflow/wqb/data_field_capture.py`
  - Accept capture plans and per-scope field budgets; write `machine/scope_matrix.jsonl` and raw plan evidence.
- `BrainWorkflow/wqb/cli.py`
  - Add or extend commands: `compile-knowledge`, `knowledge-clean-check`, `capture-interaction-note`, `discover-data-scope-matrix`, `plan-stratified-data-capture`, `delivery-gate`; update existing capture and compile commands.
- `BrainWorkflow/wqb/console_state.py`
  - Show clean compile status, delivery gate status, machine resource freshness, scope matrix coverage, and human wiki compactness.
- `BrainWorkflow/wqb/console_jobs.py`
  - Add durable job commands for compile knowledge, stratified capture planning, and delivery gate.
- `BrainWorkflow/wqb/console_server.py`
  - Add one-page Console actions and status panels for knowledge compile, stratified data capture, delivery gate, and interaction-note proposal capture.
- `BrainWorkflow/wqb/console_timeline.py`
  - Add timeline rows for clean compile and delivery gate.
- Existing tests under `BrainWorkflow/tests/`
  - Update path expectations from old `wiki/20_semantics/*.jsonl`, `wiki/30_templates/*.jsonl`, and `wiki/80_maintenance/freshness_manifest.json` to canonical `machine/*`.
- `BrainWorkflow/docs/operations/operating_guide.md`
  - Explain the cleaned knowledge tree, normal Console operation, compile paths, and delivery gate.
- Root `todo.md` and root `milestone.md`
  - Record progress, verification evidence, blocked state, and exact resume command.

---

### Task 1: Canonical Knowledge Paths

**Files:**
- Create: `BrainWorkflow/wqb/knowledge_paths.py`
- Create: `BrainWorkflow/tests/test_knowledge_paths.py`
- Modify: none

**Interfaces:**
- Consumes: `pathlib.Path`
- Produces:
  - `MACHINE_RESOURCE_FILES: dict[str, str]`
  - `LEGACY_MACHINE_RESOURCE_PATHS: dict[str, tuple[Path, ...]]`
  - `KnowledgePaths` dataclass with `root: Path`, `raw: Path`, `machine: Path`, `wiki: Path`
  - `knowledge_paths(knowledge_root: str | Path) -> KnowledgePaths`
  - `ensure_knowledge_dirs(knowledge_root: str | Path) -> KnowledgePaths`
  - `machine_resource_path(knowledge_root: str | Path, resource_name: str) -> Path`
  - `existing_machine_resource_path(knowledge_root: str | Path, resource_name: str) -> Path`
  - `relative_to_knowledge_root(path: str | Path, knowledge_root: str | Path) -> str`
  - `active_top_level_names(knowledge_root: str | Path) -> set[str]`

- [ ] **Step 1: Write the failing tests**

Add this test file:

```python
from pathlib import Path
import tempfile
import unittest

from wqb.knowledge_paths import (
    MACHINE_RESOURCE_FILES,
    active_top_level_names,
    ensure_knowledge_dirs,
    existing_machine_resource_path,
    knowledge_paths,
    machine_resource_path,
    relative_to_knowledge_root,
)


class KnowledgePathsTests(unittest.TestCase):
    def test_ensure_knowledge_dirs_creates_three_active_layers(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = ensure_knowledge_dirs(tmp)

            self.assertTrue(paths.raw.is_dir())
            self.assertTrue(paths.machine.is_dir())
            self.assertTrue(paths.wiki.is_dir())
            self.assertEqual(active_top_level_names(tmp), {"raw", "machine", "wiki"})

    def test_machine_resource_path_uses_canonical_machine_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = machine_resource_path(tmp, "data_ledger")

            self.assertEqual(path, Path(tmp) / "machine" / "data_ledger.jsonl")
            self.assertEqual(MACHINE_RESOURCE_FILES["freshness_manifest"], "freshness_manifest.json")

    def test_existing_machine_resource_path_prefers_machine_then_legacy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy = root / "wiki" / "20_semantics" / "data_ledger.jsonl"
            legacy.parent.mkdir(parents=True)
            legacy.write_text('{"field_id":"legacy"}\n', encoding="utf-8")

            self.assertEqual(existing_machine_resource_path(root, "data_ledger"), legacy)

            canonical = root / "machine" / "data_ledger.jsonl"
            canonical.parent.mkdir(parents=True)
            canonical.write_text('{"field_id":"canonical"}\n', encoding="utf-8")

            self.assertEqual(existing_machine_resource_path(root, "data_ledger"), canonical)

    def test_unsupported_machine_resource_name_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                machine_resource_path(tmp, "not_a_resource")

    def test_relative_to_knowledge_root_is_posix(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "raw" / "platform" / "learn" / "doc.md"
            path.parent.mkdir(parents=True)
            path.write_text("# doc\n", encoding="utf-8")

            self.assertEqual(relative_to_knowledge_root(path, root), "raw/platform/learn/doc.md")
```

- [ ] **Step 2: Run the tests and confirm RED**

Run:

```powershell
Set-Location 'C:\Users\oytl\Desktop\pyproject\brain\skills-and-workflows\BrainWorkflow'
python -m unittest tests.test_knowledge_paths -v
```

Expected: fail with `ModuleNotFoundError` for `wqb.knowledge_paths`.

- [ ] **Step 3: Implement `knowledge_paths.py`**

Create:

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


MACHINE_RESOURCE_FILES: dict[str, str] = {
    "scope_matrix": "scope_matrix.jsonl",
    "data_ledger": "data_ledger.jsonl",
    "operator_ledger": "operator_ledger.jsonl",
    "template_library": "template_library.jsonl",
    "benchmark_rules": "benchmark_rules.jsonl",
    "research_records": "research_records.jsonl",
    "source_index": "source_index.jsonl",
    "freshness_manifest": "freshness_manifest.json",
}

LEGACY_MACHINE_RESOURCE_PATHS: dict[str, tuple[Path, ...]] = {
    "data_ledger": (Path("wiki") / "20_semantics" / "data_ledger.jsonl",),
    "operator_ledger": (Path("wiki") / "20_semantics" / "operator_semantics.jsonl",),
    "template_library": (Path("wiki") / "30_templates" / "template_library.jsonl",),
    "benchmark_rules": (Path("wiki") / "50_benchmarks" / "benchmark_rules.jsonl",),
    "research_records": (Path("wiki") / "40_experiments" / "research_record_compile.json",),
    "freshness_manifest": (Path("wiki") / "80_maintenance" / "freshness_manifest.json",),
}

ACTIVE_TOP_LEVELS = {"raw", "machine", "wiki"}


@dataclass(frozen=True)
class KnowledgePaths:
    root: Path
    raw: Path
    machine: Path
    wiki: Path


def knowledge_paths(knowledge_root: str | Path) -> KnowledgePaths:
    """Input: knowledge root path. Output: KnowledgePaths. Build canonical vault paths without creating them."""
    root = Path(knowledge_root)
    return KnowledgePaths(root=root, raw=root / "raw", machine=root / "machine", wiki=root / "wiki")


def ensure_knowledge_dirs(knowledge_root: str | Path) -> KnowledgePaths:
    """Input: knowledge root path. Output: KnowledgePaths. Create the three active knowledge layers."""
    paths = knowledge_paths(knowledge_root)
    paths.raw.mkdir(parents=True, exist_ok=True)
    paths.machine.mkdir(parents=True, exist_ok=True)
    paths.wiki.mkdir(parents=True, exist_ok=True)
    return paths


def _require_resource_name(resource_name: str) -> str:
    """Input: resource name. Output: normalized name. Reject unsupported machine resource names."""
    name = str(resource_name).strip()
    if name not in MACHINE_RESOURCE_FILES:
        raise ValueError(f"unsupported machine resource: {resource_name}")
    return name


def machine_resource_path(knowledge_root: str | Path, resource_name: str) -> Path:
    """Input: knowledge root and resource name. Output: canonical machine resource path."""
    name = _require_resource_name(resource_name)
    return Path(knowledge_root) / "machine" / MACHINE_RESOURCE_FILES[name]


def existing_machine_resource_path(knowledge_root: str | Path, resource_name: str) -> Path:
    """Input: knowledge root and resource name. Output: existing canonical path or legacy fallback path."""
    name = _require_resource_name(resource_name)
    canonical = machine_resource_path(knowledge_root, name)
    if canonical.exists():
        return canonical
    for legacy in LEGACY_MACHINE_RESOURCE_PATHS.get(name, ()):
        candidate = Path(knowledge_root) / legacy
        if candidate.exists():
            return candidate
    return canonical


def relative_to_knowledge_root(path: str | Path, knowledge_root: str | Path) -> str:
    """Input: path and knowledge root. Output: POSIX relative path rooted at the knowledge vault."""
    root = Path(knowledge_root).resolve()
    candidate = Path(path).resolve()
    try:
        return candidate.relative_to(root).as_posix()
    except ValueError:
        return Path(path).as_posix()


def active_top_level_names(knowledge_root: str | Path) -> set[str]:
    """Input: knowledge root. Output: set of top-level directory names in the active vault."""
    root = Path(knowledge_root)
    if not root.exists():
        return set()
    return {path.name for path in root.iterdir() if path.is_dir()}
```

- [ ] **Step 4: Run the tests and confirm GREEN**

Run:

```powershell
Set-Location 'C:\Users\oytl\Desktop\pyproject\brain\skills-and-workflows\BrainWorkflow'
python -m unittest tests.test_knowledge_paths -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

Run:

```powershell
Set-Location 'C:\Users\oytl\Desktop\pyproject\brain\skills-and-workflows'
git add BrainWorkflow/wqb/knowledge_paths.py BrainWorkflow/tests/test_knowledge_paths.py
git commit -m "add canonical knowledge paths"
```

---

### Task 2: Move Machine Resource Authority Out Of Wiki

**Files:**
- Modify: `BrainWorkflow/wqb/data_ledger_compile.py`
- Modify: `BrainWorkflow/wqb/data_ledger.py`
- Modify: `BrainWorkflow/wqb/template_library.py`
- Modify: `BrainWorkflow/wqb/benchmark_rules.py`
- Modify: `BrainWorkflow/wqb/operator_semantics.py`
- Modify: `BrainWorkflow/wqb/knowledge_freshness.py`
- Modify: `BrainWorkflow/wqb/run_readiness.py`
- Modify: `BrainWorkflow/wqb/research_planner.py`
- Modify: `BrainWorkflow/wqb/workflow_stage_adapters.py`
- Modify: `BrainWorkflow/tests/test_data_ledger_compile.py`
- Modify: `BrainWorkflow/tests/test_data_ledger.py`
- Modify: `BrainWorkflow/tests/test_template_library.py`
- Modify: `BrainWorkflow/tests/test_benchmark_rules.py`
- Modify: `BrainWorkflow/tests/test_knowledge_freshness.py`
- Modify: `BrainWorkflow/tests/test_run_readiness.py`
- Modify: `BrainWorkflow/tests/test_research_planner.py`
- Modify: `BrainWorkflow/tests/test_workflow_stage_adapters.py`

**Interfaces:**
- Consumes from Task 1:
  - `machine_resource_path(knowledge_root, resource_name) -> Path`
  - `existing_machine_resource_path(knowledge_root, resource_name) -> Path`
- Produces:
  - `load_data_ledger_from_knowledge(knowledge_root: str | Path) -> list[DataLedgerRecord]`
  - `data_ledger_path_for_knowledge(knowledge_root: str | Path) -> Path`
  - `load_template_library_from_knowledge(knowledge_root: str | Path) -> list[TemplateRecord]`
  - `template_library_path_for_knowledge(knowledge_root: str | Path) -> Path`
  - `benchmark_rules_path_for_knowledge(knowledge_root: str | Path) -> Path`

- [ ] **Step 1: Write failing path-migration tests**

Add or extend tests with these assertions:

```python
def test_compile_data_ledger_writes_jsonl_to_machine_and_markdown_out_of_machine(self):
    summary = compile_data_ledger_from_raw(root, capture_dir=capture_dir, generated_at="2026-07-30T00:00:00+00:00")

    self.assertEqual(Path(summary["ledger_path"]), root / "machine" / "data_ledger.jsonl")
    self.assertTrue((root / "machine" / "data_ledger.jsonl").exists())
    self.assertFalse((root / "wiki" / "20_semantics" / "data_ledger.jsonl").exists())


def test_readiness_prefers_machine_resource_over_legacy_resource(self):
    (root / "machine").mkdir()
    (root / "wiki" / "20_semantics").mkdir(parents=True)
    (root / "machine" / "data_ledger.jsonl").write_text(machine_row, encoding="utf-8")
    (root / "wiki" / "20_semantics" / "data_ledger.jsonl").write_text(legacy_row, encoding="utf-8")

    records = load_data_ledger_from_knowledge(root)

    self.assertEqual(records[0].field_id, "machine_field")


def test_readiness_reads_legacy_resource_when_machine_resource_has_not_been_compiled(self):
    (root / "wiki" / "20_semantics").mkdir(parents=True)
    (root / "wiki" / "20_semantics" / "data_ledger.jsonl").write_text(legacy_row, encoding="utf-8")

    records = load_data_ledger_from_knowledge(root)

    self.assertEqual(records[0].field_id, "legacy_field")
```

- [ ] **Step 2: Run focused tests and confirm RED**

Run:

```powershell
Set-Location 'C:\Users\oytl\Desktop\pyproject\brain\skills-and-workflows\BrainWorkflow'
python -m unittest tests.test_data_ledger_compile tests.test_data_ledger tests.test_run_readiness -v
```

Expected: fail because current constants still point to `wiki/20_semantics` and `wiki/80_maintenance`.

- [ ] **Step 3: Move write paths to `machine/`**

Update these constants and helpers:

```python
# data_ledger_compile.py
from wqb.knowledge_paths import machine_resource_path, existing_machine_resource_path

DATA_LEDGER_RESOURCE = "data_ledger"
FRESHNESS_MANIFEST_RESOURCE = "freshness_manifest"
DATA_LEDGER_MD = Path("wiki") / "20_data_semantics.md"

# inside compile_data_ledger_from_raw()
ledger_path = machine_resource_path(root, DATA_LEDGER_RESOURCE)
markdown_path = root / DATA_LEDGER_MD
manifest_path = machine_resource_path(root, FRESHNESS_MANIFEST_RESOURCE)
prior_rows = _read_jsonl(existing_machine_resource_path(root, DATA_LEDGER_RESOURCE))
for record in load_data_ledger(existing_machine_resource_path(root, DATA_LEDGER_RESOURCE)):
    ...
```

Add knowledge-root-aware loaders:

```python
# data_ledger.py
from wqb.knowledge_paths import existing_machine_resource_path, machine_resource_path


def data_ledger_path_for_knowledge(knowledge_root: str | Path) -> Path:
    """Input: knowledge root. Output: Path. Return the current data-ledger authority path."""
    return existing_machine_resource_path(knowledge_root, "data_ledger")


def load_data_ledger_from_knowledge(knowledge_root: str | Path) -> list[DataLedgerRecord]:
    """Input: knowledge root. Output: DataLedgerRecord list. Load canonical machine ledger with legacy fallback."""
    return load_data_ledger(data_ledger_path_for_knowledge(knowledge_root))
```

```python
# template_library.py
from wqb.knowledge_paths import existing_machine_resource_path


def template_library_path_for_knowledge(knowledge_root: str | Path) -> Path:
    """Input: knowledge root. Output: Path. Return the current template-library authority path."""
    return existing_machine_resource_path(knowledge_root, "template_library")


def load_template_library_from_knowledge(knowledge_root: str | Path) -> list[TemplateRecord]:
    """Input: knowledge root. Output: TemplateRecord list. Load canonical template records with legacy fallback."""
    return load_template_library(template_library_path_for_knowledge(knowledge_root))
```

```python
# benchmark_rules.py
from wqb.knowledge_paths import existing_machine_resource_path, machine_resource_path

BENCHMARK_RULES_PATH = Path("machine") / "benchmark_rules.jsonl"


def benchmark_rules_path_for_knowledge(knowledge_root: str | Path) -> Path:
    """Input: knowledge root. Output: Path. Return the current benchmark-rule authority path."""
    return existing_machine_resource_path(knowledge_root, "benchmark_rules")


def load_active_benchmark_rules(knowledge_root: str | Path, fallback_to_defaults: bool = True) -> list[BenchmarkRule]:
    """Input: vault root and fallback flag. Output: active rules. Prefer the persisted machine rulebook."""
    path = benchmark_rules_path_for_knowledge(knowledge_root)
    if path.exists():
        return load_benchmark_rules(path)
    if fallback_to_defaults:
        return default_benchmark_rules()
    return []
```

- [ ] **Step 4: Update consumers**

Replace direct `root / "wiki" / ...` resource reads with knowledge-root-aware helpers:

```python
# run_readiness.py
from wqb.data_ledger import data_ledger_path_for_knowledge, load_data_ledger_from_knowledge
from wqb.template_library import load_template_library_from_knowledge, template_library_path_for_knowledge
from wqb.knowledge_paths import existing_machine_resource_path

FRESHNESS_MANIFEST_RESOURCE = "freshness_manifest"

manifest = existing_machine_resource_path(root, FRESHNESS_MANIFEST_RESOURCE)
ledger_path = data_ledger_path_for_knowledge(root)
template_path = template_library_path_for_knowledge(root)
ledger_records = load_data_ledger_from_knowledge(root)
template_records = load_template_library_from_knowledge(root)
```

Use the same pattern in `research_planner.py` and `workflow_stage_adapters.py`. Preserve direct path readers for tests and run snapshots.

- [ ] **Step 5: Run focused tests and confirm GREEN**

Run:

```powershell
Set-Location 'C:\Users\oytl\Desktop\pyproject\brain\skills-and-workflows\BrainWorkflow'
python -m unittest tests.test_data_ledger_compile tests.test_data_ledger tests.test_template_library tests.test_benchmark_rules tests.test_knowledge_freshness tests.test_run_readiness tests.test_research_planner tests.test_workflow_stage_adapters -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

Run:

```powershell
Set-Location 'C:\Users\oytl\Desktop\pyproject\brain\skills-and-workflows'
git add BrainWorkflow/wqb/data_ledger_compile.py BrainWorkflow/wqb/data_ledger.py BrainWorkflow/wqb/template_library.py BrainWorkflow/wqb/benchmark_rules.py BrainWorkflow/wqb/operator_semantics.py BrainWorkflow/wqb/knowledge_freshness.py BrainWorkflow/wqb/run_readiness.py BrainWorkflow/wqb/research_planner.py BrainWorkflow/wqb/workflow_stage_adapters.py BrainWorkflow/tests/test_data_ledger_compile.py BrainWorkflow/tests/test_data_ledger.py BrainWorkflow/tests/test_template_library.py BrainWorkflow/tests/test_benchmark_rules.py BrainWorkflow/tests/test_knowledge_freshness.py BrainWorkflow/tests/test_run_readiness.py BrainWorkflow/tests/test_research_planner.py BrainWorkflow/tests/test_workflow_stage_adapters.py
git commit -m "move machine resources out of wiki"
```

---

### Task 3: Clean Knowledge Structure Health And Cleanup Log

**Files:**
- Create: `BrainWorkflow/wqb/knowledge_clean_compile.py`
- Create: `BrainWorkflow/tests/test_knowledge_clean_compile.py`
- Modify: `BrainWorkflow/wqb/knowledge_freshness.py`
- Modify: `BrainWorkflow/tests/test_knowledge_freshness.py`

**Interfaces:**
- Consumes from Task 1:
  - `knowledge_paths(knowledge_root) -> KnowledgePaths`
  - `machine_resource_path(knowledge_root, resource_name) -> Path`
  - `active_top_level_names(knowledge_root) -> set[str]`
- Produces:
  - `KnowledgeCleanIssue` dataclass
  - `CleanupCandidate` dataclass
  - `evaluate_clean_knowledge_structure(knowledge_root: str | Path) -> dict[str, Any]`
  - `plan_obsolete_active_cleanup(knowledge_root: str | Path) -> list[CleanupCandidate]`
  - `apply_obsolete_active_cleanup(knowledge_root: str | Path, generated_at: str, dry_run: bool = True) -> dict[str, Any]`
  - `write_cleanup_log(knowledge_root: str | Path, rows: list[dict[str, Any]], generated_at: str) -> Path`

- [ ] **Step 1: Write failing clean-structure tests**

Create tests:

```python
import tempfile
import unittest
from pathlib import Path

from wqb.knowledge_clean_compile import (
    apply_obsolete_active_cleanup,
    evaluate_clean_knowledge_structure,
    plan_obsolete_active_cleanup,
)


class KnowledgeCleanCompileTests(unittest.TestCase):
    def test_clean_structure_accepts_only_raw_machine_wiki(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ("raw", "machine", "wiki"):
                (root / name).mkdir()

            report = evaluate_clean_knowledge_structure(root)

            self.assertEqual(report["issue_count"], 0)
            self.assertTrue(report["clean"])

    def test_clean_structure_reports_legacy_active_paths_and_wiki_jsonl(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "raw" / "learn").mkdir(parents=True)
            (root / "raw" / "learn" / "glossary.md").write_text("# old\n", encoding="utf-8")
            (root / "wiki" / "20_semantics").mkdir(parents=True)
            (root / "wiki" / "20_semantics" / "data_ledger.jsonl").write_text("{}\n", encoding="utf-8")

            report = evaluate_clean_knowledge_structure(root)
            codes = {issue["code"] for issue in report["issues"]}

            self.assertIn("legacy_active_path", codes)
            self.assertIn("machine_resource_inside_wiki", codes)
            self.assertFalse(report["clean"])

    def test_cleanup_refuses_sensitive_files_and_removes_ordinary_legacy_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ordinary = root / "wiki" / "20_semantics" / "old.md"
            ordinary.parent.mkdir(parents=True)
            ordinary.write_text("# old\n", encoding="utf-8")
            sensitive = root / "raw" / "learn" / ".env"
            sensitive.parent.mkdir(parents=True)
            sensitive.write_text("SECRET=1\n", encoding="utf-8")

            planned = plan_obsolete_active_cleanup(root)
            by_name = {Path(item.path).name: item.action for item in planned}

            self.assertEqual(by_name["old.md"], "remove")
            self.assertEqual(by_name[".env"], "refuse")

            summary = apply_obsolete_active_cleanup(root, "2026-07-30T00:00:00+00:00", dry_run=False)

            self.assertFalse(ordinary.exists())
            self.assertTrue(sensitive.exists())
            self.assertEqual(summary["removed_count"], 1)
            self.assertEqual(summary["refused_count"], 1)
            self.assertTrue((root / "raw" / "maintenance" / "cleanup_logs").exists())
```

- [ ] **Step 2: Run tests and confirm RED**

Run:

```powershell
Set-Location 'C:\Users\oytl\Desktop\pyproject\brain\skills-and-workflows\BrainWorkflow'
python -m unittest tests.test_knowledge_clean_compile -v
```

Expected: fail because `wqb.knowledge_clean_compile` does not exist.

- [ ] **Step 3: Implement clean compile module**

Create:

```python
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

from wqb.knowledge_paths import ACTIVE_TOP_LEVELS, active_top_level_names, relative_to_knowledge_root


SENSITIVE_NAME_FRAGMENTS = (".env", "credential", "secret", "token", "password", "api_key", "apikey", "private_key")
OBSOLETE_ACTIVE_PREFIXES = (
    Path("raw") / "learn",
    Path("wiki") / "20_semantics",
    Path("wiki") / "30_templates",
    Path("wiki") / "40_experiments",
    Path("wiki") / "50_benchmarks",
    Path("wiki") / "70_decisions",
    Path("wiki") / "80_maintenance",
)
WIKI_MACHINE_EXTENSIONS = {".json", ".jsonl", ".csv"}


@dataclass(frozen=True)
class KnowledgeCleanIssue:
    code: str
    path: str
    message: str
    action: str


@dataclass(frozen=True)
class CleanupCandidate:
    path: str
    reason: str
    action: str
    sha256: str


def _now() -> str:
    """Input: none. Output: timestamp string. Return UTC time for clean compile logs."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _sha256(path: Path) -> str:
    """Input: file path. Output: SHA-256 hex digest. Hash cleanup candidates before removal."""
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else ""


def _is_sensitive(path: Path) -> bool:
    """Input: path. Output: bool. Identify files that must not be auto-deleted."""
    lowered = path.name.lower()
    return any(fragment in lowered for fragment in SENSITIVE_NAME_FRAGMENTS)


def _is_under_prefix(path: Path, root: Path, prefix: Path) -> bool:
    """Input: path, root, prefix. Output: bool. Check if path lives under a managed obsolete prefix."""
    try:
        relative = path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return relative == prefix or relative.is_relative_to(prefix)


def evaluate_clean_knowledge_structure(knowledge_root: str | Path) -> dict[str, Any]:
    """Input: knowledge root. Output: dict. Check the simplified active knowledge contract."""
    root = Path(knowledge_root)
    issues: list[KnowledgeCleanIssue] = []
    top_levels = active_top_level_names(root)
    extra = sorted(top_levels - ACTIVE_TOP_LEVELS)
    for name in extra:
        issues.append(KnowledgeCleanIssue("extra_active_layer", str(root / name), "Top-level active knowledge layer is not allowed.", "Move compiled content under raw, machine, or wiki."))
    for prefix in OBSOLETE_ACTIVE_PREFIXES:
        path = root / prefix
        if path.exists():
            issues.append(KnowledgeCleanIssue("legacy_active_path", str(path), "Legacy mixed active path remains after compile.", "Run clean compile cleanup after successful compile verification."))
    wiki_root = root / "wiki"
    if wiki_root.exists():
        for path in sorted(wiki_root.rglob("*")):
            if path.is_file() and path.suffix.lower() in WIKI_MACHINE_EXTENSIONS:
                issues.append(KnowledgeCleanIssue("machine_resource_inside_wiki", str(path), "Machine-readable artifact is inside the human wiki.", "Move machine artifacts under knowledge/machine."))
    return {
        "clean": not issues,
        "issue_count": len(issues),
        "top_levels": sorted(top_levels),
        "issues": [asdict(issue) for issue in issues],
    }


def plan_obsolete_active_cleanup(knowledge_root: str | Path) -> list[CleanupCandidate]:
    """Input: knowledge root. Output: cleanup candidates. Plan ordinary removals and sensitive refusals."""
    root = Path(knowledge_root)
    rows: list[CleanupCandidate] = []
    for prefix in OBSOLETE_ACTIVE_PREFIXES:
        base = root / prefix
        if not base.exists():
            continue
        for path in sorted(base.rglob("*")):
            if path.is_file():
                action = "refuse" if _is_sensitive(path) else "remove"
                rows.append(CleanupCandidate(str(path), f"obsolete active prefix {prefix.as_posix()}", action, _sha256(path)))
    return rows


def write_cleanup_log(knowledge_root: str | Path, rows: list[dict[str, Any]], generated_at: str) -> Path:
    """Input: knowledge root, cleanup rows, timestamp. Output: log path. Persist cleanup evidence."""
    root = Path(knowledge_root)
    day = generated_at[:10]
    path = root / "raw" / "maintenance" / "cleanup_logs" / f"{day}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    return path


def apply_obsolete_active_cleanup(knowledge_root: str | Path, generated_at: str | None = None, dry_run: bool = True) -> dict[str, Any]:
    """Input: knowledge root, timestamp, dry-run flag. Output: cleanup summary. Remove ordinary obsolete files after verification."""
    generated = generated_at or _now()
    root = Path(knowledge_root)
    candidates = plan_obsolete_active_cleanup(root)
    rows: list[dict[str, Any]] = []
    for candidate in candidates:
        path = Path(candidate.path)
        row = asdict(candidate) | {"generated_at": generated, "dry_run": dry_run}
        if candidate.action == "remove" and not dry_run:
            path.unlink(missing_ok=True)
            row["applied"] = True
        else:
            row["applied"] = False
        rows.append(row)
    log_path = write_cleanup_log(root, rows, generated) if rows else root / "raw" / "maintenance" / "cleanup_logs" / f"{generated[:10]}.jsonl"
    return {
        "generated_at": generated,
        "dry_run": dry_run,
        "removed_count": sum(1 for row in rows if row.get("applied")),
        "refused_count": sum(1 for row in rows if row.get("action") == "refuse"),
        "candidate_count": len(rows),
        "cleanup_log_path": str(log_path),
    }
```

- [ ] **Step 4: Integrate health report**

Update `evaluate_knowledge_contract_health()` to merge `evaluate_clean_knowledge_structure()`:

```python
from wqb.knowledge_clean_compile import evaluate_clean_knowledge_structure

clean_report = evaluate_clean_knowledge_structure(root)
for issue in clean_report["issues"]:
    issues.append(
        KnowledgeHealthIssue(
            code=str(issue["code"]),
            path=str(issue["path"]),
            message=str(issue["message"]),
            action=str(issue["action"]),
        )
    )
```

Set returned fields:

```python
"clean_structure": clean_report["clean"],
"clean_structure_issue_count": clean_report["issue_count"],
```

- [ ] **Step 5: Run focused tests**

Run:

```powershell
Set-Location 'C:\Users\oytl\Desktop\pyproject\brain\skills-and-workflows\BrainWorkflow'
python -m unittest tests.test_knowledge_clean_compile tests.test_knowledge_freshness -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

Run:

```powershell
Set-Location 'C:\Users\oytl\Desktop\pyproject\brain\skills-and-workflows'
git add BrainWorkflow/wqb/knowledge_clean_compile.py BrainWorkflow/tests/test_knowledge_clean_compile.py BrainWorkflow/wqb/knowledge_freshness.py BrainWorkflow/tests/test_knowledge_freshness.py
git commit -m "add clean knowledge compile checks"
```

---

### Task 4: Human Experience Wiki Compiler

**Files:**
- Create: `BrainWorkflow/wqb/knowledge_experience_compile.py`
- Create: `BrainWorkflow/tests/test_knowledge_experience_compile.py`
- Modify: `BrainWorkflow/wqb/knowledge_contracts.py`
- Modify: `BrainWorkflow/tests/test_knowledge_contracts.py`

**Interfaces:**
- Consumes:
  - `machine_resource_path(knowledge_root, resource_name) -> Path`
  - `existing_machine_resource_path(knowledge_root, resource_name) -> Path`
  - `relative_to_knowledge_root(path, knowledge_root) -> str`
- Produces:
  - `HUMAN_WIKI_FILES: dict[str, Path]`
  - `compile_human_experience_wiki(knowledge_root: str | Path, generated_at: str | None = None, max_case_reports: int = 20) -> dict[str, Any]`
  - `write_machine_source_index(knowledge_root: str | Path, rows: list[SourceIndexRow]) -> Path`
  - `update_source_index(knowledge_root, rows) -> Path` still writes compact raw Markdown index and also writes `machine/source_index.jsonl`

- [ ] **Step 1: Write failing wiki compiler tests**

Create tests:

```python
import json
from pathlib import Path
import tempfile
import unittest

from wqb.knowledge_experience_compile import compile_human_experience_wiki


class KnowledgeExperienceCompileTests(unittest.TestCase):
    def test_compile_writes_only_target_human_pages(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            machine = root / "machine"
            machine.mkdir(parents=True)
            (machine / "data_ledger.jsonl").write_text(json.dumps({
                "dataset_id": "analyst_ds",
                "field_id": "analyst_revision",
                "field_type": "MATRIX",
                "semantic_tags": ["analyst", "revision"],
                "correlation_risk": "low",
                "coverage": 0.91,
                "source_paths": ["raw/platform/data_fields/2026-07-30/data_fields.jsonl"]
            }) + "\n", encoding="utf-8")
            (machine / "template_library.jsonl").write_text(json.dumps({
                "template_id": "analyst_revision_delay_rank",
                "template_family": "event_revision",
                "hypothesis": "Analyst revisions can proxy improving expectations.",
                "required_field_types": ["MATRIX"],
                "compatible_semantic_tags": ["analyst", "revision"],
                "operator_tags": ["rank", "ts_delta"],
                "status": "seed",
                "correlation_risk": "low",
                "repair_levers": ["neutralization", "decay"],
                "source_paths": ["raw/community/forum/example.md"]
            }) + "\n", encoding="utf-8")
            (machine / "benchmark_rules.jsonl").write_text(json.dumps({
                "rule_id": "near_miss_stable_pnl_promotion",
                "issue_types": ["near_miss"],
                "description": "Stable PnL deserves repair review.",
                "promotion_condition": "PNL shape is straight enough.",
                "action": "Create a repair candidate.",
                "evidence_paths": ["raw/community/user_messages/example.md"],
                "consumed_by": ["triage"],
                "risk": "repair budget can be wasted"
            }) + "\n", encoding="utf-8")

            summary = compile_human_experience_wiki(root, "2026-07-30T00:00:00+00:00")

            self.assertEqual(summary["page_count"], 6)
            self.assertTrue((root / "wiki" / "00_start_here.md").exists())
            self.assertTrue((root / "wiki" / "20_data_semantics.md").exists())
            self.assertFalse((root / "wiki" / "20_semantics" / "data_ledger.jsonl").exists())

    def test_human_pages_are_compact_and_do_not_dump_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "machine").mkdir()
            (root / "machine" / "data_ledger.jsonl").write_text("", encoding="utf-8")
            summary = compile_human_experience_wiki(root, "2026-07-30T00:00:00+00:00")

            for path_text in summary["page_paths"]:
                text = Path(path_text).read_text(encoding="utf-8")
                self.assertLess(len(text), 12000)
                self.assertNotIn('{"', text)
                self.assertTrue(text.startswith("---\n"))
```

- [ ] **Step 2: Run tests and confirm RED**

Run:

```powershell
Set-Location 'C:\Users\oytl\Desktop\pyproject\brain\skills-and-workflows\BrainWorkflow'
python -m unittest tests.test_knowledge_experience_compile -v
```

Expected: fail because `wqb.knowledge_experience_compile` does not exist.

- [ ] **Step 3: Implement compact human wiki compiler**

Create a compiler with these page targets:

```python
HUMAN_WIKI_FILES = {
    "start_here": Path("wiki") / "00_start_here.md",
    "factor_principles": Path("wiki") / "10_factor_principles.md",
    "data_semantics": Path("wiki") / "20_data_semantics.md",
    "template_operator_patterns": Path("wiki") / "30_template_and_operator_patterns.md",
    "benchmark_repair_rules": Path("wiki") / "40_benchmark_and_repair_rules.md",
    "engineering_lessons": Path("wiki") / "50_engineering_lessons.md",
}
```

Write deterministic pages with front matter:

```python
def _front_matter(generated_at: str, compiled_from: list[str], consumed_by: list[str]) -> str:
    """Input: timestamp, sources, consumers. Output: Markdown front matter."""
    return render_front_matter({
        "compiled_at": generated_at,
        "compiled_from": compiled_from,
        "consumed_by": consumed_by,
        "stale_after_days": 14,
        "trust_level": "compiled_experience",
        "update_trigger": "compile-knowledge",
    })
```

Use resource readers that load only the first bounded set needed for summary:

```python
def _read_jsonl_rows(path: Path, limit: int = 200) -> list[dict[str, Any]]:
    """Input: JSONL path and limit. Output: row dictionaries. Read bounded machine rows for wiki summaries."""
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
            if len(rows) >= limit:
                break
    return rows
```

`compile_human_experience_wiki()` writes:

```python
return {
    "generated_at": generated,
    "page_count": len(page_paths),
    "page_paths": [str(path) for path in page_paths],
    "case_report_count": case_report_count,
}
```

Page content rules:

- `00_start_here.md`: current workflow purpose, normal Console operation, current highest-signal principles.
- `10_factor_principles.md`: simple economic logic, novelty against self/prod correlation, repair promotion for stable PnL, batch size 30.
- `20_data_semantics.md`: grouped semantic tags from `machine/data_ledger.jsonl`, field type mix, underexplored data categories.
- `30_template_and_operator_patterns.md`: template families, operator compositions, repair levers, crowding notes.
- `40_benchmark_and_repair_rules.md`: rulebook actions by issue type.
- `50_engineering_lessons.md`: context recovery, milestone rule, problem-to-workflow principle, data capture breadth-first rule.

- [ ] **Step 4: Update source index writer**

Modify `update_source_index()` so it writes:

```python
machine_jsonl = root / "machine" / "source_index.jsonl"
raw_markdown = root / "raw" / "source_index.md"
```

The JSONL row uses `source_index_row_to_dict(row)`. The Markdown remains compact and excludes payload dumps.

- [ ] **Step 5: Run focused tests**

Run:

```powershell
Set-Location 'C:\Users\oytl\Desktop\pyproject\brain\skills-and-workflows\BrainWorkflow'
python -m unittest tests.test_knowledge_experience_compile tests.test_knowledge_contracts -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

Run:

```powershell
Set-Location 'C:\Users\oytl\Desktop\pyproject\brain\skills-and-workflows'
git add BrainWorkflow/wqb/knowledge_experience_compile.py BrainWorkflow/tests/test_knowledge_experience_compile.py BrainWorkflow/wqb/knowledge_contracts.py BrainWorkflow/tests/test_knowledge_contracts.py
git commit -m "compile compact human knowledge wiki"
```

---

### Task 5: Research Record Machine Ledger And Selected Case Reports

**Files:**
- Modify: `BrainWorkflow/wqb/research_record.py`
- Modify: `BrainWorkflow/wqb/orchestrator.py`
- Modify: `BrainWorkflow/wqb/knowledge_compile.py`
- Modify: `BrainWorkflow/wqb/knowledge_experience_compile.py`
- Modify: `BrainWorkflow/tests/test_research_record.py`
- Modify: `BrainWorkflow/tests/test_orchestrator.py`
- Modify: `BrainWorkflow/tests/test_knowledge_compile.py`
- Modify: `BrainWorkflow/tests/test_knowledge_experience_compile.py`

**Interfaces:**
- Consumes:
  - `machine_resource_path(knowledge_root, "research_records") -> Path`
  - Existing `ResearchRecord`
- Produces:
  - `research_record_to_dict(record: ResearchRecord) -> dict[str, Any]`
  - `append_research_record_jsonl(knowledge_root: str | Path, record: ResearchRecord, synced_at: str) -> Path`
  - `load_research_record_ledger(knowledge_root: str | Path) -> list[dict[str, Any]]`
  - `sync_research_record_to_machine(record: ResearchRecord, knowledge_root: str | Path, synced_at: str) -> Path`
  - `select_research_case_records(rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]`
  - `compile_research_case_reports(knowledge_root: str | Path, generated_at: str, limit: int) -> list[Path]`

- [ ] **Step 1: Write failing research ledger tests**

Extend `tests/test_research_record.py`:

```python
def test_sync_research_record_to_machine_appends_latest_run_row(self):
    with tempfile.TemporaryDirectory() as tmp:
        record = empty_research_record("run-a", "Power Pool breadth-first scout")
        record = record_alpha_result(record, {
            "alpha_id": "alpha-a",
            "expression_hash": "hash-a",
            "hard_pass": False,
            "benchmark_label": "near_miss",
            "metrics": {"sharpe": 1.3},
            "failed": ["prod_correlation"],
        })

        path = sync_research_record_to_machine(record, tmp, "2026-07-30T00:00:00+00:00")
        rows = load_research_record_ledger(tmp)

        self.assertEqual(path, Path(tmp) / "machine" / "research_records.jsonl")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["run_id"], "run-a")
        self.assertEqual(rows[0]["final_state"], "in_progress")
```

Extend `tests/test_knowledge_experience_compile.py`:

```python
def test_selected_near_miss_research_record_gets_case_report(self):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "machine").mkdir()
        row = {
            "run_id": "run-near-miss",
            "objective": "Explore new analyst data",
            "final_state": "paused",
            "case_reason": "near_miss",
            "backtest": [{"alpha_id": "a1", "metrics": {"sharpe": 1.2}}],
            "triage": [{"failed": ["prod_correlation"], "benchmark_label": "near_miss"}],
            "repair": {},
            "candidate_gate": [],
            "synced_at": "2026-07-30T00:00:00+00:00",
        }
        (root / "machine" / "research_records.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")

        reports = compile_research_case_reports(root, "2026-07-30T00:00:00+00:00", limit=5)

        self.assertEqual(len(reports), 1)
        text = reports[0].read_text(encoding="utf-8")
        self.assertIn("run-near-miss", text)
        self.assertIn("Reusable Lesson", text)
```

- [ ] **Step 2: Run tests and confirm RED**

Run:

```powershell
Set-Location 'C:\Users\oytl\Desktop\pyproject\brain\skills-and-workflows\BrainWorkflow'
python -m unittest tests.test_research_record tests.test_knowledge_experience_compile -v
```

Expected: fail because the machine JSONL sync and case report functions are not present.

- [ ] **Step 3: Add machine ledger functions**

Add to `research_record.py`:

```python
from datetime import datetime, timezone

from wqb.knowledge_paths import machine_resource_path


def research_record_to_dict(record: ResearchRecord) -> dict[str, Any]:
    """Input: ResearchRecord. Output: dict. Convert a run record into a machine-ledger row."""
    return asdict(record)


def _research_record_final_state(record: ResearchRecord) -> str:
    """Input: ResearchRecord. Output: state label. Derive a compact run outcome for ledger filtering."""
    if record.manual_submission_status:
        return str(record.manual_submission_status[-1].get("status", "submitted"))
    if record.approved_queue:
        return str(record.approved_queue[-1].get("status", "approved_queue"))
    if record.candidate_gate:
        return "candidate_gate"
    if record.repair:
        return "repair"
    if record.backtest:
        return "in_progress"
    return "created"


def _case_reason(record: ResearchRecord) -> str:
    """Input: ResearchRecord. Output: case reason. Mark learning-worthy records for human case compilation."""
    if record.manual_submission_status or record.approved_queue:
        return "submitted_or_approved"
    if any(row.get("benchmark_label") == "near_miss" for row in record.triage):
        return "near_miss"
    if record.repair:
        return "repair_loop"
    if record.triage:
        return "representative_failure"
    return ""


def append_research_record_jsonl(knowledge_root: str | Path, record: ResearchRecord, synced_at: str) -> Path:
    """Input: knowledge root, record, timestamp. Output: machine JSONL path. Append a compact authoritative run row."""
    path = machine_resource_path(knowledge_root, "research_records")
    path.parent.mkdir(parents=True, exist_ok=True)
    row = research_record_to_dict(record) | {
        "synced_at": synced_at,
        "final_state": _research_record_final_state(record),
        "case_reason": _case_reason(record),
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    return path


def load_research_record_ledger(knowledge_root: str | Path) -> list[dict[str, Any]]:
    """Input: knowledge root. Output: research record rows. Load the machine research-record ledger."""
    path = machine_resource_path(knowledge_root, "research_records")
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def sync_research_record_to_machine(record: ResearchRecord, knowledge_root: str | Path, synced_at: str | None = None) -> Path:
    """Input: record, knowledge root, timestamp. Output: machine path. Sync one research record into the machine ledger."""
    generated = synced_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    return append_research_record_jsonl(knowledge_root, record, generated)
```

- [ ] **Step 4: Wire Orchestrator sync**

In `orchestrator._sync_research_record_unlocked`, after the existing per-run raw sync succeeds, call:

```python
sync_research_record_to_machine(record, self.knowledge_root, now)
```

If the existing method lacks `self.knowledge_root`, use the existing Orchestrator constructor field that points at the knowledge vault; do not add a second knowledge-root field.

- [ ] **Step 5: Add selected case report compiler**

Add to `knowledge_experience_compile.py`:

```python
CASE_REPORT_DIR = Path("wiki") / "60_research_cases"


def select_research_case_records(rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    """Input: research ledger rows and limit. Output: selected rows. Pick learning-worthy research cases."""
    ranked = [
        row for row in rows
        if str(row.get("case_reason", "")) in {"submitted_or_approved", "near_miss", "repair_loop", "representative_failure"}
    ]
    return ranked[: max(int(limit), 0)]


def _case_report_text(row: dict[str, Any], generated_at: str) -> str:
    """Input: research row and timestamp. Output: compact Markdown case report."""
    run_id = str(row.get("run_id", ""))
    objective = str(row.get("objective", ""))
    reason = str(row.get("case_reason", ""))
    failed = sorted({
        str(item)
        for triage in row.get("triage", [])
        if isinstance(triage, dict)
        for item in triage.get("failed", [])
    })
    front = _front_matter(generated_at, ["machine/research_records.jsonl"], ["human_learning", "workflow_review"])
    return "\n".join([
        front.rstrip(),
        f"# Research Case {run_id}",
        "",
        f"- Objective: {objective}",
        f"- Case Reason: {reason}",
        f"- Failed Checks: {', '.join(failed) if failed else 'none recorded'}",
        f"- Run ID: `{run_id}`",
        "",
        "## Reusable Lesson",
        "",
        _lesson_from_case_reason(reason, failed),
        "",
    ]) + "\n"


def compile_research_case_reports(knowledge_root: str | Path, generated_at: str, limit: int) -> list[Path]:
    """Input: knowledge root, timestamp, limit. Output: report paths. Compile selected research cases for humans."""
    root = Path(knowledge_root)
    rows = load_research_record_ledger(root)
    reports: list[Path] = []
    for row in select_research_case_records(rows, limit):
        run_id = str(row.get("run_id", "")).replace("/", "_").replace("\\", "_")
        path = root / CASE_REPORT_DIR / f"{run_id}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_case_report_text(row, generated_at), encoding="utf-8")
        reports.append(path)
    return reports
```

- [ ] **Step 6: Run focused tests**

Run:

```powershell
Set-Location 'C:\Users\oytl\Desktop\pyproject\brain\skills-and-workflows\BrainWorkflow'
python -m unittest tests.test_research_record tests.test_orchestrator tests.test_knowledge_compile tests.test_knowledge_experience_compile -v
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

Run:

```powershell
Set-Location 'C:\Users\oytl\Desktop\pyproject\brain\skills-and-workflows'
git add BrainWorkflow/wqb/research_record.py BrainWorkflow/wqb/orchestrator.py BrainWorkflow/wqb/knowledge_compile.py BrainWorkflow/wqb/knowledge_experience_compile.py BrainWorkflow/tests/test_research_record.py BrainWorkflow/tests/test_orchestrator.py BrainWorkflow/tests/test_knowledge_compile.py BrainWorkflow/tests/test_knowledge_experience_compile.py
git commit -m "sync research records into machine knowledge"
```

---

### Task 6: Interaction Memory And Problem-To-Workflow Capture

**Files:**
- Create: `BrainWorkflow/wqb/interaction_memory.py`
- Create: `BrainWorkflow/tests/test_interaction_memory.py`
- Modify: `BrainWorkflow/wqb/cli.py`
- Modify: `BrainWorkflow/wqb/console_server.py`
- Modify: `BrainWorkflow/wqb/console_jobs.py`
- Modify: `BrainWorkflow/tests/test_cli.py`
- Modify: `BrainWorkflow/tests/test_console_server.py`
- Modify: `BrainWorkflow/tests/test_console_jobs.py`

**Interfaces:**
- Consumes:
  - `relative_to_knowledge_root(path, knowledge_root) -> str`
  - `render_front_matter(metadata) -> str`
- Produces:
  - `InteractionNote` dataclass
  - `append_interaction_note(knowledge_root: str | Path, summary: str, category: str, tags: list[str], evidence_paths: list[str], captured_at: str | None = None, source: str = "codex_chat") -> Path`
  - `load_interaction_notes(knowledge_root: str | Path) -> list[dict[str, Any]]`
  - `compile_interaction_lessons(knowledge_root: str | Path, generated_at: str) -> dict[str, Any]`
  - CLI command `capture-interaction-note`

- [ ] **Step 1: Write failing interaction-memory tests**

Create:

```python
import tempfile
import unittest
from pathlib import Path

from wqb.interaction_memory import append_interaction_note, compile_interaction_lessons, load_interaction_notes


class InteractionMemoryTests(unittest.TestCase):
    def test_append_interaction_note_writes_raw_markdown_with_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = append_interaction_note(
                tmp,
                summary="When a workflow bug is fixed, the fix must become a rule or test.",
                category="workflow_rule",
                tags=["problem_to_workflow", "maintenance"],
                evidence_paths=["milestone.md"],
                captured_at="2026-07-30T00:00:00+00:00",
                source="codex_chat",
            )

            text = path.read_text(encoding="utf-8")
            self.assertTrue(path.as_posix().endswith("raw/community/user_messages/2026-07-30/interaction_notes.jsonl"))
            self.assertIn("problem_to_workflow", text)
            self.assertEqual(len(load_interaction_notes(tmp)), 1)

    def test_compile_interaction_lessons_writes_human_engineering_lesson(self):
        with tempfile.TemporaryDirectory() as tmp:
            append_interaction_note(
                tmp,
                summary="Console must show what is running so the user does not ask Codex for status.",
                category="engineering_lesson",
                tags=["console", "delivery_gate"],
                evidence_paths=["runs/console_jobs/job/summary.md"],
                captured_at="2026-07-30T00:00:00+00:00",
            )

            summary = compile_interaction_lessons(tmp, "2026-07-30T00:00:00+00:00")

            self.assertEqual(summary["lesson_count"], 1)
            lesson_text = (Path(tmp) / "wiki" / "50_engineering_lessons.md").read_text(encoding="utf-8")
            self.assertIn("Console must show what is running", lesson_text)
```

- [ ] **Step 2: Run tests and confirm RED**

Run:

```powershell
Set-Location 'C:\Users\oytl\Desktop\pyproject\brain\skills-and-workflows\BrainWorkflow'
python -m unittest tests.test_interaction_memory -v
```

Expected: fail because `wqb.interaction_memory` does not exist.

- [ ] **Step 3: Implement interaction memory**

Create:

```python
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any


RAW_INTERACTION_ROOT = Path("raw") / "community" / "user_messages"


@dataclass(frozen=True)
class InteractionNote:
    captured_at: str
    source: str
    category: str
    summary: str
    tags: list[str]
    evidence_paths: list[str]
    note_hash: str


def _now() -> str:
    """Input: none. Output: timestamp string. Return UTC time for interaction memory."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _hash_note(summary: str, category: str, tags: list[str]) -> str:
    """Input: note fields. Output: SHA-256 digest. Dedupe repeated user corrections."""
    payload = json.dumps({"summary": summary, "category": category, "tags": sorted(tags)}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def append_interaction_note(
    knowledge_root: str | Path,
    summary: str,
    category: str,
    tags: list[str],
    evidence_paths: list[str],
    captured_at: str | None = None,
    source: str = "codex_chat",
) -> Path:
    """Input: knowledge root and note fields. Output: raw JSONL path. Persist one reusable interaction note."""
    generated = captured_at or _now()
    clean_tags = [str(tag) for tag in tags if str(tag).strip()]
    note = InteractionNote(
        captured_at=generated,
        source=str(source),
        category=str(category),
        summary=str(summary),
        tags=clean_tags,
        evidence_paths=[str(path) for path in evidence_paths],
        note_hash=_hash_note(str(summary), str(category), clean_tags),
    )
    path = Path(knowledge_root) / RAW_INTERACTION_ROOT / generated[:10] / "interaction_notes.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    existing_hashes = {row.get("note_hash") for row in load_interaction_notes(knowledge_root)}
    if note.note_hash not in existing_hashes:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(note), ensure_ascii=False, sort_keys=True) + "\n")
    return path


def load_interaction_notes(knowledge_root: str | Path) -> list[dict[str, Any]]:
    """Input: knowledge root. Output: interaction rows. Load raw interaction memory rows."""
    root = Path(knowledge_root) / RAW_INTERACTION_ROOT
    rows: list[dict[str, Any]] = []
    if not root.exists():
        return rows
    for path in sorted(root.rglob("interaction_notes.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
    return rows


def compile_interaction_lessons(knowledge_root: str | Path, generated_at: str) -> dict[str, Any]:
    """Input: knowledge root and timestamp. Output: summary. Append interaction-derived lessons to the human wiki."""
    root = Path(knowledge_root)
    notes = load_interaction_notes(root)
    lesson_rows = [row for row in notes if str(row.get("category", "")) in {"workflow_rule", "engineering_lesson", "factor_lesson"}]
    path = root / "wiki" / "50_engineering_lessons.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "---",
        "compiled_at: " + generated_at,
        "compiled_from:",
        "  - raw/community/user_messages",
        "consumed_by:",
        "  - human_learning",
        "  - workflow_maintenance",
        "stale_after_days: 14",
        "trust_level: compiled_experience",
        "update_trigger: compile-knowledge",
        "---",
        "# Engineering Lessons",
        "",
    ]
    for row in lesson_rows:
        lines.append(f"- {row.get('summary', '')}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"generated_at": generated_at, "lesson_count": len(lesson_rows), "path": str(path)}
```

- [ ] **Step 4: Add CLI and Console actions**

Add parser fields:

```python
capture_note = subparsers.add_parser("capture-interaction-note")
capture_note.add_argument("--knowledge-root", required=True)
capture_note.add_argument("--summary", required=True)
capture_note.add_argument("--category", required=True)
capture_note.add_argument("--tag", action="append", default=[])
capture_note.add_argument("--evidence-path", action="append", default=[])
```

Add command dispatch:

```python
elif args.command == "capture-interaction-note":
    path = append_interaction_note(
        args.knowledge_root,
        args.summary,
        args.category,
        list(args.tag),
        list(args.evidence_path),
    )
    print(json.dumps({"path": str(path)}, ensure_ascii=False, indent=2))
```

Console form posts to `capture-interaction-note`; the form uses category select values `workflow_rule`, `engineering_lesson`, `factor_lesson`, and `proposal_seed`.

- [ ] **Step 5: Run focused tests**

Run:

```powershell
Set-Location 'C:\Users\oytl\Desktop\pyproject\brain\skills-and-workflows\BrainWorkflow'
python -m unittest tests.test_interaction_memory tests.test_cli tests.test_console_server tests.test_console_jobs -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

Run:

```powershell
Set-Location 'C:\Users\oytl\Desktop\pyproject\brain\skills-and-workflows'
git add BrainWorkflow/wqb/interaction_memory.py BrainWorkflow/tests/test_interaction_memory.py BrainWorkflow/wqb/cli.py BrainWorkflow/wqb/console_server.py BrainWorkflow/wqb/console_jobs.py BrainWorkflow/tests/test_cli.py BrainWorkflow/tests/test_console_server.py BrainWorkflow/tests/test_console_jobs.py
git commit -m "capture interaction memory for workflow learning"
```

---

### Task 7: Stratified Platform Data Capture Planner

**Files:**
- Create: `BrainWorkflow/wqb/data_capture_plan.py`
- Create: `BrainWorkflow/tests/test_data_capture_plan.py`
- Modify: `BrainWorkflow/wqb/data_field_capture.py`
- Modify: `BrainWorkflow/wqb/data_ledger_compile.py`
- Modify: `BrainWorkflow/wqb/cli.py`
- Modify: `BrainWorkflow/wqb/console_jobs.py`
- Modify: `BrainWorkflow/wqb/console_server.py`
- Modify: `BrainWorkflow/wqb/console_progress.py`
- Modify: `BrainWorkflow/tests/test_data_field_capture.py`
- Modify: `BrainWorkflow/tests/test_data_ledger_compile.py`
- Modify: `BrainWorkflow/tests/test_cli.py`
- Modify: `BrainWorkflow/tests/test_console_jobs.py`
- Modify: `BrainWorkflow/tests/test_console_server.py`
- Modify: `BrainWorkflow/tests/test_console_progress.py`

**Interfaces:**
- Consumes:
  - Existing `fetch_data_sets_with_metadata(client, instrument_type, region, delay, universe, limit, max_records) -> tuple[list[dict[str, Any]], bool]`
  - Existing `fetch_data_fields_with_metadata(...)`
  - Existing `CaptureScope`
- Produces:
  - `ScopeMatrixRow` dataclass
  - `StratifiedCaptureScope` dataclass
  - `discover_scope_matrix(client: Any, knowledge_root: str | Path, generated_at: str | None = None, instrument_types: list[str] | None = None, regions: list[str] | None = None, delays: list[int] | None = None, universes: list[str] | None = None, max_scopes: int = 0) -> dict[str, Any]`
  - `build_stratified_capture_plan(scope_rows: list[dict[str, Any]], fields_per_scope: int = 100, max_scopes: int = 0) -> list[dict[str, Any]]`
  - `write_capture_plan(knowledge_root: str | Path, rows: list[dict[str, Any]], generated_at: str) -> Path`
  - `load_capture_plan(path: str | Path) -> list[dict[str, Any]]`

- [ ] **Step 1: Write failing scope-matrix and stratified-plan tests**

Create:

```python
import tempfile
import unittest
from pathlib import Path

from wqb.data_capture_plan import build_stratified_capture_plan, discover_scope_matrix, load_capture_plan, write_capture_plan


class FakeClient:
    def get_json(self, path):
        if path.startswith("/data-sets?"):
            return {"count": 2, "results": [{"id": "ds_a", "category": "analyst"}, {"id": "ds_b", "category": "news"}]}
        raise AssertionError(path)


class DataCapturePlanTests(unittest.TestCase):
    def test_discover_scope_matrix_writes_machine_scope_matrix(self):
        with tempfile.TemporaryDirectory() as tmp:
            summary = discover_scope_matrix(
                FakeClient(),
                tmp,
                generated_at="2026-07-30T00:00:00+00:00",
                regions=["USA", "EUR"],
                delays=[0, 1],
                universes=["TOP3000"],
            )

            self.assertEqual(summary["scope_count"], 4)
            self.assertEqual(summary["available_scope_count"], 4)
            self.assertTrue((Path(tmp) / "machine" / "scope_matrix.jsonl").exists())

    def test_stratified_plan_balances_scopes_and_caps_fields_per_scope(self):
        rows = [
            {"instrument_type": "EQUITY", "region": "USA", "delay": 1, "universe": "TOP3000", "status": "available", "dataset_count": 10},
            {"instrument_type": "EQUITY", "region": "EUR", "delay": 1, "universe": "TOP1200", "status": "available", "dataset_count": 8},
            {"instrument_type": "EQUITY", "region": "ASI", "delay": 1, "universe": "MINVOL1M", "status": "failed", "dataset_count": 0},
        ]

        plan = build_stratified_capture_plan(rows, fields_per_scope=50, max_scopes=2)

        self.assertEqual(len(plan), 2)
        self.assertEqual({row["field_budget"] for row in plan}, {50})
        self.assertEqual({row["status"] for row in plan}, {"planned"})

    def test_write_and_load_capture_plan_round_trips_jsonl(self):
        with tempfile.TemporaryDirectory() as tmp:
            rows = [{"instrument_type": "EQUITY", "region": "USA", "delay": 1, "universe": "TOP3000", "field_budget": 50, "status": "planned"}]

            path = write_capture_plan(tmp, rows, "2026-07-30T00:00:00+00:00")

            self.assertTrue(path.as_posix().endswith("raw/platform/data_fields/capture_plans/2026-07-30.jsonl"))
            self.assertEqual(load_capture_plan(path), rows)
```

- [ ] **Step 2: Run tests and confirm RED**

Run:

```powershell
Set-Location 'C:\Users\oytl\Desktop\pyproject\brain\skills-and-workflows\BrainWorkflow'
python -m unittest tests.test_data_capture_plan -v
```

Expected: fail because `wqb.data_capture_plan` does not exist.

- [ ] **Step 3: Implement data capture planner**

Create:

```python
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from wqb.data_catalog import fetch_data_sets_with_metadata
from wqb.data_field_capture import build_capture_scopes
from wqb.knowledge_paths import machine_resource_path


CAPTURE_PLAN_ROOT = Path("raw") / "platform" / "data_fields" / "capture_plans"


@dataclass(frozen=True)
class ScopeMatrixRow:
    generated_at: str
    instrument_type: str
    region: str
    delay: int
    universe: str
    status: str
    dataset_count: int
    truncated: bool
    message: str = ""


def _now() -> str:
    """Input: none. Output: timestamp string. Return UTC time for capture planning."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _append_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    """Input: path and rows. Output: none. Write deterministic JSONL."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def discover_scope_matrix(
    client: Any,
    knowledge_root: str | Path,
    generated_at: str | None = None,
    instrument_types: list[str] | None = None,
    regions: list[str] | None = None,
    delays: list[int] | None = None,
    universes: list[str] | None = None,
    max_scopes: int = 0,
) -> dict[str, Any]:
    """Input: API client, knowledge root, scope filters. Output: summary. Probe broad platform data availability."""
    generated = generated_at or _now()
    scopes = build_capture_scopes(instrument_types, regions, delays, universes, max_scopes=max_scopes)
    rows: list[dict[str, Any]] = []
    for scope in scopes:
        try:
            data_sets, truncated = fetch_data_sets_with_metadata(
                client, scope.instrument_type, scope.region, int(scope.delay), scope.universe, limit=1, max_records=1
            )
            row = ScopeMatrixRow(
                generated,
                scope.instrument_type,
                scope.region,
                int(scope.delay),
                scope.universe,
                "available" if data_sets else "empty",
                len(data_sets),
                bool(truncated),
                "",
            )
        except Exception as error:
            row = ScopeMatrixRow(generated, scope.instrument_type, scope.region, int(scope.delay), scope.universe, "failed", 0, False, str(error))
        rows.append(asdict(row))
    path = machine_resource_path(knowledge_root, "scope_matrix")
    _append_jsonl(path, rows)
    return {
        "generated_at": generated,
        "scope_matrix_path": str(path),
        "scope_count": len(rows),
        "available_scope_count": sum(1 for row in rows if row["status"] == "available"),
    }


def build_stratified_capture_plan(scope_rows: list[dict[str, Any]], fields_per_scope: int = 100, max_scopes: int = 0) -> list[dict[str, Any]]:
    """Input: scope matrix rows and limits. Output: planned capture rows. Select diverse scopes before deepening one scope."""
    available = [
        row for row in scope_rows
        if str(row.get("status", "")) == "available"
    ]
    ordered = sorted(
        available,
        key=lambda row: (str(row.get("region", "")), int(row.get("delay", 0)), str(row.get("universe", ""))),
    )
    if max_scopes > 0:
        ordered = ordered[: int(max_scopes)]
    return [
        {
            "instrument_type": str(row.get("instrument_type", "EQUITY")),
            "region": str(row.get("region", "")),
            "delay": int(row.get("delay", 0)),
            "universe": str(row.get("universe", "")),
            "field_budget": int(fields_per_scope),
            "status": "planned",
        }
        for row in ordered
    ]


def write_capture_plan(knowledge_root: str | Path, rows: list[dict[str, Any]], generated_at: str) -> Path:
    """Input: knowledge root, planned rows, timestamp. Output: capture plan path."""
    path = Path(knowledge_root) / CAPTURE_PLAN_ROOT / f"{generated_at[:10]}.jsonl"
    _append_jsonl(path, rows)
    return path


def load_capture_plan(path: str | Path) -> list[dict[str, Any]]:
    """Input: capture plan path. Output: capture plan rows."""
    source = Path(path)
    if not source.exists():
        return []
    return [json.loads(line) for line in source.read_text(encoding="utf-8").splitlines() if line.strip()]
```

- [ ] **Step 4: Make `capture_platform_data_fields()` execute a plan**

Modify signature:

```python
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
    capture_plan_path: str | Path | None = None,
    fields_per_scope: int = 0,
) -> dict[str, Any]:
```

If `capture_plan_path` is set, load plan rows and build scopes from it. If `fields_per_scope > 0`, allocate a per-scope budget across selected datasets:

```python
remaining_scope_budget = int(plan_row.get("field_budget", fields_per_scope)) if fields_per_scope > 0 else 0
for data_set in data_sets:
    if remaining_scope_budget == 0 and fields_per_scope > 0:
        break
    request_limit = max_fields_per_dataset
    if fields_per_scope > 0:
        request_limit = min(max(remaining_scope_budget, 1), SAFE_PAGE_LIMIT)
    fields, fields_truncated = fetch_data_fields_with_metadata(..., limit=SAFE_PAGE_LIMIT, max_records=request_limit or SAFE_PAGE_LIMIT)
    remaining_scope_budget = max(0, remaining_scope_budget - len(fields))
```

Each scope row writes:

```python
"sampling_mode": "stratified" if fields_per_scope > 0 or capture_plan_path else "full_scope",
"field_budget": field_budget,
"certification_status": "partial" if fields_per_scope > 0 else existing_certification_value,
```

- [ ] **Step 5: Add CLI and Console controls**

Add CLI commands:

```powershell
python -m wqb.cli discover-data-scope-matrix --knowledge-root <root> --enable-live-api --max-scopes 40
python -m wqb.cli plan-stratified-data-capture --knowledge-root <root> --fields-per-scope 100 --max-scopes 40
python -m wqb.cli capture-platform-data-fields --knowledge-root <root> --enable-live-api --capture-plan-path <path> --fields-per-scope 100
```

Console `capture-platform-data-fields` form gains:

```html
<input name="fields_per_scope" type="number" min="0" value="100">
<input name="max_scopes" type="number" min="0" value="40">
```

The Console command builder passes `--fields-per-scope` and `--capture-plan-path` when those form fields exist.

- [ ] **Step 6: Run focused tests**

Run:

```powershell
Set-Location 'C:\Users\oytl\Desktop\pyproject\brain\skills-and-workflows\BrainWorkflow'
python -m unittest tests.test_data_capture_plan tests.test_data_field_capture tests.test_data_ledger_compile tests.test_cli tests.test_console_jobs tests.test_console_server tests.test_console_progress -v
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

Run:

```powershell
Set-Location 'C:\Users\oytl\Desktop\pyproject\brain\skills-and-workflows'
git add BrainWorkflow/wqb/data_capture_plan.py BrainWorkflow/tests/test_data_capture_plan.py BrainWorkflow/wqb/data_field_capture.py BrainWorkflow/wqb/data_ledger_compile.py BrainWorkflow/wqb/cli.py BrainWorkflow/wqb/console_jobs.py BrainWorkflow/wqb/console_server.py BrainWorkflow/wqb/console_progress.py BrainWorkflow/tests/test_data_field_capture.py BrainWorkflow/tests/test_data_ledger_compile.py BrainWorkflow/tests/test_cli.py BrainWorkflow/tests/test_console_jobs.py BrainWorkflow/tests/test_console_server.py BrainWorkflow/tests/test_console_progress.py
git commit -m "add stratified platform data capture planning"
```

---

### Task 8: Knowledge Maintenance Pipeline And CLI

**Files:**
- Create: `BrainWorkflow/wqb/knowledge_maintenance.py`
- Create: `BrainWorkflow/tests/test_knowledge_maintenance.py`
- Modify: `BrainWorkflow/wqb/cli.py`
- Modify: `BrainWorkflow/wqb/console_jobs.py`
- Modify: `BrainWorkflow/wqb/console_server.py`
- Modify: `BrainWorkflow/wqb/console_state.py`
- Modify: `BrainWorkflow/wqb/console_timeline.py`
- Modify: `BrainWorkflow/tests/test_cli.py`
- Modify: `BrainWorkflow/tests/test_console_jobs.py`
- Modify: `BrainWorkflow/tests/test_console_server.py`
- Modify: `BrainWorkflow/tests/test_console_state.py`
- Modify: `BrainWorkflow/tests/test_console_timeline.py`

**Interfaces:**
- Consumes:
  - `compile_human_experience_wiki(knowledge_root, generated_at, max_case_reports) -> dict[str, Any]`
  - `compile_interaction_lessons(knowledge_root, generated_at) -> dict[str, Any]`
  - `apply_obsolete_active_cleanup(knowledge_root, generated_at, dry_run) -> dict[str, Any]`
  - `evaluate_knowledge_contract_health(knowledge_root) -> dict[str, Any]`
- Produces:
  - `KnowledgeMaintenanceReport` dataclass
  - `run_knowledge_maintenance(knowledge_root: str | Path, generated_at: str | None = None, apply_cleanup: bool = False, max_case_reports: int = 20) -> dict[str, Any]`
  - CLI command `compile-knowledge`

- [ ] **Step 1: Write failing maintenance pipeline tests**

Create:

```python
import json
from pathlib import Path
import tempfile
import unittest

from wqb.knowledge_maintenance import run_knowledge_maintenance


class KnowledgeMaintenanceTests(unittest.TestCase):
    def test_compile_knowledge_creates_clean_machine_and_wiki_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "machine").mkdir()
            (root / "machine" / "data_ledger.jsonl").write_text("", encoding="utf-8")
            (root / "machine" / "template_library.jsonl").write_text("", encoding="utf-8")
            (root / "machine" / "benchmark_rules.jsonl").write_text("", encoding="utf-8")
            (root / "machine" / "research_records.jsonl").write_text("", encoding="utf-8")
            (root / "machine" / "operator_ledger.jsonl").write_text("", encoding="utf-8")
            (root / "machine" / "scope_matrix.jsonl").write_text("", encoding="utf-8")
            (root / "machine" / "freshness_manifest.json").write_text("[]", encoding="utf-8")

            report = run_knowledge_maintenance(root, "2026-07-30T00:00:00+00:00", apply_cleanup=True)

            self.assertEqual(report["status"], "completed")
            self.assertTrue((root / "wiki" / "00_start_here.md").exists())
            self.assertTrue((root / "raw" / "maintenance" / "compile_reports" / "2026-07-30.json").exists())

    def test_compile_knowledge_records_blocker_when_structure_is_not_clean_after_cleanup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "raw" / "learn").mkdir(parents=True)
            (root / "raw" / "learn" / ".env").write_text("SECRET=1\n", encoding="utf-8")

            report = run_knowledge_maintenance(root, "2026-07-30T00:00:00+00:00", apply_cleanup=True)

            self.assertEqual(report["status"], "blocked")
            self.assertGreater(report["health"]["issue_count"], 0)
            self.assertTrue((root / "raw" / "learn" / ".env").exists())
```

- [ ] **Step 2: Run tests and confirm RED**

Run:

```powershell
Set-Location 'C:\Users\oytl\Desktop\pyproject\brain\skills-and-workflows\BrainWorkflow'
python -m unittest tests.test_knowledge_maintenance -v
```

Expected: fail because `wqb.knowledge_maintenance` does not exist.

- [ ] **Step 3: Implement maintenance pipeline**

Create:

```python
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from wqb.interaction_memory import compile_interaction_lessons
from wqb.knowledge_clean_compile import apply_obsolete_active_cleanup
from wqb.knowledge_experience_compile import compile_human_experience_wiki
from wqb.knowledge_freshness import evaluate_knowledge_contract_health
from wqb.knowledge_paths import ensure_knowledge_dirs


@dataclass(frozen=True)
class KnowledgeMaintenanceReport:
    generated_at: str
    status: str
    wiki: dict[str, Any]
    interaction_lessons: dict[str, Any]
    cleanup: dict[str, Any]
    health: dict[str, Any]


def _now() -> str:
    """Input: none. Output: timestamp string. Return UTC time for knowledge maintenance."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _write_report(knowledge_root: str | Path, report: dict[str, Any]) -> Path:
    """Input: knowledge root and report. Output: report path. Persist maintenance evidence."""
    day = str(report["generated_at"])[:10]
    path = Path(knowledge_root) / "raw" / "maintenance" / "compile_reports" / f"{day}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return path


def run_knowledge_maintenance(
    knowledge_root: str | Path,
    generated_at: str | None = None,
    apply_cleanup: bool = False,
    max_case_reports: int = 20,
) -> dict[str, Any]:
    """Input: knowledge root and compile settings. Output: maintenance report. Run compile, cleanup, and health verification."""
    generated = generated_at or _now()
    ensure_knowledge_dirs(knowledge_root)
    wiki = compile_human_experience_wiki(knowledge_root, generated, max_case_reports=max_case_reports)
    interaction = compile_interaction_lessons(knowledge_root, generated)
    cleanup = apply_obsolete_active_cleanup(knowledge_root, generated, dry_run=not apply_cleanup)
    health = evaluate_knowledge_contract_health(knowledge_root)
    status = "completed" if health.get("issue_count", 0) == 0 else "blocked"
    report = asdict(KnowledgeMaintenanceReport(generated, status, wiki, interaction, cleanup, health))
    report["report_path"] = str(_write_report(knowledge_root, report))
    return report
```

- [ ] **Step 4: Add CLI command**

Add parser:

```python
compile_knowledge = subparsers.add_parser("compile-knowledge")
compile_knowledge.add_argument("--knowledge-root", required=True)
compile_knowledge.add_argument("--apply-cleanup", action="store_true")
compile_knowledge.add_argument("--max-case-reports", type=int, default=20)
```

Add dispatch:

```python
elif args.command == "compile-knowledge":
    report = run_knowledge_maintenance(args.knowledge_root, apply_cleanup=bool(args.apply_cleanup), max_case_reports=int(args.max_case_reports))
    print(json.dumps(report, ensure_ascii=False, indent=2))
```

- [ ] **Step 5: Wire Console and timeline**

`console_jobs.build_cli_command()` maps action `compile-knowledge` to:

```python
return [*base, "compile-knowledge", "--knowledge-root", knowledge_root, "--apply-cleanup"]
```

`console_state.build_console_state()` includes:

```python
"knowledge_maintenance": _latest_knowledge_maintenance(paths.knowledge_root),
```

`console_timeline.build_timeline_rows()` adds a row:

```python
_row("knowledge_compile", "completed" if state.get("knowledge_maintenance", {}).get("status") == "completed" else "waiting", "knowledge maintenance", "Compile raw facts into machine resources and compact human wiki.")
```

- [ ] **Step 6: Run focused tests**

Run:

```powershell
Set-Location 'C:\Users\oytl\Desktop\pyproject\brain\skills-and-workflows\BrainWorkflow'
python -m unittest tests.test_knowledge_maintenance tests.test_cli tests.test_console_jobs tests.test_console_server tests.test_console_state tests.test_console_timeline -v
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

Run:

```powershell
Set-Location 'C:\Users\oytl\Desktop\pyproject\brain\skills-and-workflows'
git add BrainWorkflow/wqb/knowledge_maintenance.py BrainWorkflow/tests/test_knowledge_maintenance.py BrainWorkflow/wqb/cli.py BrainWorkflow/wqb/console_jobs.py BrainWorkflow/wqb/console_server.py BrainWorkflow/wqb/console_state.py BrainWorkflow/wqb/console_timeline.py BrainWorkflow/tests/test_cli.py BrainWorkflow/tests/test_console_jobs.py BrainWorkflow/tests/test_console_server.py BrainWorkflow/tests/test_console_state.py BrainWorkflow/tests/test_console_timeline.py
git commit -m "add knowledge maintenance pipeline"
```

---

### Task 9: Delivery Gate And Operational Handoff Report

**Files:**
- Create: `BrainWorkflow/wqb/delivery_gate.py`
- Create: `BrainWorkflow/tests/test_delivery_gate.py`
- Modify: `BrainWorkflow/wqb/cli.py`
- Modify: `BrainWorkflow/wqb/console_state.py`
- Modify: `BrainWorkflow/wqb/console_jobs.py`
- Modify: `BrainWorkflow/wqb/console_server.py`
- Modify: `BrainWorkflow/wqb/console_timeline.py`
- Modify: `BrainWorkflow/tests/test_cli.py`
- Modify: `BrainWorkflow/tests/test_console_state.py`
- Modify: `BrainWorkflow/tests/test_console_jobs.py`
- Modify: `BrainWorkflow/tests/test_console_server.py`
- Modify: `BrainWorkflow/tests/test_console_timeline.py`

**Interfaces:**
- Consumes:
  - `evaluate_clean_knowledge_structure(knowledge_root) -> dict[str, Any]`
  - `evaluate_run_readiness(...) -> ReadinessReport`
  - existing workflow state files under `runs/`
  - existing Console state builder
- Produces:
  - `DeliveryGateCheck` dataclass
  - `run_delivery_gate(knowledge_root: str | Path, runs_root: str | Path, generated_at: str | None = None, console_base_url: str = "") -> dict[str, Any]`
  - CLI command `delivery-gate`

- [ ] **Step 1: Write failing delivery-gate tests**

Create:

```python
import json
from pathlib import Path
import tempfile
import unittest

from wqb.delivery_gate import run_delivery_gate


class DeliveryGateTests(unittest.TestCase):
    def _write_minimal_clean_knowledge(self, root: Path) -> None:
        for name in ("raw", "machine", "wiki"):
            (root / name).mkdir(parents=True, exist_ok=True)
        for name in ("scope_matrix.jsonl", "data_ledger.jsonl", "operator_ledger.jsonl", "template_library.jsonl", "benchmark_rules.jsonl", "research_records.jsonl", "source_index.jsonl"):
            (root / "machine" / name).write_text("{}\n", encoding="utf-8")
        (root / "machine" / "freshness_manifest.json").write_text("[]", encoding="utf-8")
        for page in ("00_start_here.md", "10_factor_principles.md", "20_data_semantics.md", "30_template_and_operator_patterns.md", "40_benchmark_and_repair_rules.md", "50_engineering_lessons.md"):
            (root / "wiki" / page).write_text("---\ncompiled_from:\n  - raw/platform/learn/doc.md\ncompiled_at: 2026-07-30T00:00:00+00:00\ntrust_level: compiled_experience\nstale_after_days: 14\nupdate_trigger: compile-knowledge\nconsumed_by:\n  - human_learning\n---\n# Page\n", encoding="utf-8")

    def test_delivery_gate_accepts_expected_durable_pause(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            knowledge = base / "knowledge"
            runs = base / "runs"
            self._write_minimal_clean_knowledge(knowledge)
            run_dir = runs / "20260730T000000-paused"
            run_dir.mkdir(parents=True)
            (run_dir / "run_state.json").write_text(json.dumps({
                "run_id": "20260730T000000-paused",
                "status": "paused",
                "stage": "scout_seed",
                "pause_reason": "missing candidates.csv",
                "evidence_paths": ["stages/scout_seed/scout_seed_handoff.json"]
            }), encoding="utf-8")
            handoff = run_dir / "stages" / "scout_seed" / "scout_seed_handoff.json"
            handoff.parent.mkdir(parents=True)
            handoff.write_text("{}", encoding="utf-8")

            report = run_delivery_gate(knowledge, runs, "2026-07-30T00:00:00+00:00")

            self.assertEqual(report["status"], "passed")
            self.assertIn("expected_pause", {check["code"] for check in report["checks"]})

    def test_delivery_gate_fails_when_machine_ledger_is_inside_wiki(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            knowledge = base / "knowledge"
            runs = base / "runs"
            (knowledge / "wiki" / "20_semantics").mkdir(parents=True)
            (knowledge / "wiki" / "20_semantics" / "data_ledger.jsonl").write_text("{}\n", encoding="utf-8")

            report = run_delivery_gate(knowledge, runs, "2026-07-30T00:00:00+00:00")

            self.assertEqual(report["status"], "failed")
            self.assertIn("clean_knowledge_structure", {check["code"] for check in report["checks"] if check["status"] == "failed"})
```

- [ ] **Step 2: Run tests and confirm RED**

Run:

```powershell
Set-Location 'C:\Users\oytl\Desktop\pyproject\brain\skills-and-workflows\BrainWorkflow'
python -m unittest tests.test_delivery_gate -v
```

Expected: fail because `wqb.delivery_gate` does not exist.

- [ ] **Step 3: Implement delivery gate**

Create:

```python
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from wqb.knowledge_clean_compile import evaluate_clean_knowledge_structure
from wqb.knowledge_paths import MACHINE_RESOURCE_FILES, machine_resource_path


REQUIRED_HUMAN_WIKI_FILES = (
    "00_start_here.md",
    "10_factor_principles.md",
    "20_data_semantics.md",
    "30_template_and_operator_patterns.md",
    "40_benchmark_and_repair_rules.md",
    "50_engineering_lessons.md",
)


@dataclass(frozen=True)
class DeliveryGateCheck:
    code: str
    status: str
    message: str
    evidence_path: str = ""


def _now() -> str:
    """Input: none. Output: timestamp string. Return UTC time for delivery gate reports."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _latest_run_state(runs_root: Path) -> dict[str, Any]:
    """Input: runs root. Output: latest run state row. Load newest durable Orchestrator state."""
    states = sorted(runs_root.glob("*/run_state.json"))
    if not states:
        return {}
    return json.loads(states[-1].read_text(encoding="utf-8"))


def _check(status: bool, code: str, message: str, evidence_path: str = "") -> DeliveryGateCheck:
    """Input: pass flag and details. Output: DeliveryGateCheck."""
    return DeliveryGateCheck(code, "passed" if status else "failed", message, evidence_path)


def run_delivery_gate(
    knowledge_root: str | Path,
    runs_root: str | Path,
    generated_at: str | None = None,
    console_base_url: str = "",
) -> dict[str, Any]:
    """Input: knowledge root, runs root, timestamp, Console URL. Output: delivery gate report."""
    generated = generated_at or _now()
    knowledge = Path(knowledge_root)
    runs = Path(runs_root)
    checks: list[DeliveryGateCheck] = []
    clean = evaluate_clean_knowledge_structure(knowledge)
    checks.append(_check(bool(clean.get("clean")), "clean_knowledge_structure", "Knowledge active tree follows raw/machine/wiki.", str(knowledge)))
    for resource_name in MACHINE_RESOURCE_FILES:
        path = machine_resource_path(knowledge, resource_name)
        checks.append(_check(path.exists(), f"machine_resource_{resource_name}", f"Machine resource exists: {resource_name}.", str(path)))
    for page_name in REQUIRED_HUMAN_WIKI_FILES:
        path = knowledge / "wiki" / page_name
        compact = path.exists() and path.stat().st_size <= 12000
        checks.append(_check(compact, f"human_wiki_{page_name}", f"Compact human wiki page exists: {page_name}.", str(path)))
    state = _latest_run_state(runs)
    expected_pause = state.get("status") == "paused" and state.get("stage") == "scout_seed" and "candidates.csv" in str(state.get("pause_reason", ""))
    checks.append(_check(bool(state), "workflow_state_exists", "Latest workflow state is durable.", str(runs)))
    checks.append(_check(expected_pause or state.get("status") in {"completed", "waiting_for_approval"}, "expected_pause", "Workflow reached a durable accepted boundary.", str(runs)))
    report = {
        "generated_at": generated,
        "status": "passed" if all(check.status == "passed" for check in checks) else "failed",
        "checks": [asdict(check) for check in checks],
    }
    report_path = knowledge / "raw" / "maintenance" / "delivery_gates" / f"{generated[:10]}.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    report["report_path"] = str(report_path)
    return report
```

- [ ] **Step 4: Add CLI command**

Add parser:

```python
delivery_gate = subparsers.add_parser("delivery-gate")
delivery_gate.add_argument("--knowledge-root", required=True)
delivery_gate.add_argument("--runs-root", required=True)
delivery_gate.add_argument("--console-base-url", default="")
```

Add dispatch:

```python
elif args.command == "delivery-gate":
    report = run_delivery_gate(args.knowledge_root, args.runs_root, console_base_url=str(args.console_base_url))
    print(json.dumps(report, ensure_ascii=False, indent=2))
```

- [ ] **Step 5: Wire Console state and timeline**

`console_state` reads the newest report under `raw/maintenance/delivery_gates/*.json`:

```python
"delivery_gate": _latest_delivery_gate(paths.knowledge_root),
```

`console_jobs.build_cli_command()` maps action `delivery-gate` to:

```python
return [*base, "delivery-gate", "--knowledge-root", knowledge_root, "--runs-root", str(paths.runs_root)]
```

`console_timeline` adds a delivery row after workflow boundary:

```python
_row("delivery_gate", state.get("delivery_gate", {}).get("status", "waiting"), "delivery gate", "Verify fixed automation before handoff.")
```

- [ ] **Step 6: Run focused tests**

Run:

```powershell
Set-Location 'C:\Users\oytl\Desktop\pyproject\brain\skills-and-workflows\BrainWorkflow'
python -m unittest tests.test_delivery_gate tests.test_cli tests.test_console_state tests.test_console_jobs tests.test_console_server tests.test_console_timeline -v
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

Run:

```powershell
Set-Location 'C:\Users\oytl\Desktop\pyproject\brain\skills-and-workflows'
git add BrainWorkflow/wqb/delivery_gate.py BrainWorkflow/tests/test_delivery_gate.py BrainWorkflow/wqb/cli.py BrainWorkflow/wqb/console_state.py BrainWorkflow/wqb/console_jobs.py BrainWorkflow/wqb/console_server.py BrainWorkflow/wqb/console_timeline.py BrainWorkflow/tests/test_cli.py BrainWorkflow/tests/test_console_state.py BrainWorkflow/tests/test_console_jobs.py BrainWorkflow/tests/test_console_server.py BrainWorkflow/tests/test_console_timeline.py
git commit -m "add workflow delivery gate"
```

---

### Task 10: Documentation, Console Operating Guide, And Final Verification

**Files:**
- Modify: `BrainWorkflow/docs/operations/operating_guide.md`
- Modify: `BrainWorkflow/docs/superpowers/specs/2026-07-30-simplified-knowledge-structure-delivery-contract-design.md`
- Modify: `BrainWorkflow/todo.md`
- Modify: root `todo.md`
- Modify: root `milestone.md`

**Interfaces:**
- Consumes:
  - CLI commands from Tasks 6-9
  - Delivery report from `run_delivery_gate(...)`
- Produces:
  - Updated operating guide explaining how the user runs the workflow and knowledge maintenance without chat debugging.
  - Updated milestone recovery anchor with current loop, verification evidence, blocker state, and exact next command.

- [ ] **Step 1: Update operating guide**

Add a section:

```markdown
## Knowledge Maintenance

The active vault has three layers:

- `knowledge/raw`: facts, platform snapshots, forum/advisor material, interaction notes, raw research records, and maintenance evidence.
- `knowledge/machine`: JSON/JSONL resources consumed by the workflow code.
- `knowledge/wiki`: compact human lessons and selected case reports.

Normal maintenance command:

```powershell
python -m wqb.cli compile-knowledge --knowledge-root 'C:\Users\oytl\Desktop\pyproject\brain\knowledge' --apply-cleanup
```

After a platform data refresh, run `compile-knowledge` before research scheduling.
```

Add a section:

```markdown
## Stratified Platform Data Capture

Use breadth-first capture before deep capture:

```powershell
python -m wqb.cli discover-data-scope-matrix --knowledge-root 'C:\Users\oytl\Desktop\pyproject\brain\knowledge' --enable-live-api --max-scopes 40
python -m wqb.cli plan-stratified-data-capture --knowledge-root 'C:\Users\oytl\Desktop\pyproject\brain\knowledge' --fields-per-scope 100 --max-scopes 40
python -m wqb.cli capture-platform-data-fields --knowledge-root 'C:\Users\oytl\Desktop\pyproject\brain\knowledge' --enable-live-api --capture-plan-path '<plan-path>' --fields-per-scope 100
python -m wqb.cli compile-data-ledger --knowledge-root 'C:\Users\oytl\Desktop\pyproject\brain\knowledge'
python -m wqb.cli compile-knowledge --knowledge-root 'C:\Users\oytl\Desktop\pyproject\brain\knowledge' --apply-cleanup
```
```

Add a section:

```markdown
## Delivery Gate

Run this before considering the fixed workflow ready for routine operation:

```powershell
python -m wqb.cli delivery-gate --knowledge-root 'C:\Users\oytl\Desktop\pyproject\brain\knowledge' --runs-root 'C:\Users\oytl\Desktop\pyproject\brain\runs'
```

A planned pause is acceptable only when the report states the pause, stage, reason, and evidence path.
```

- [ ] **Step 2: Update implementation status in spec**

Change the spec status line to:

```markdown
Status: implemented, pending live platform refresh and routine operation hardening
```

Add an implementation notes section with commit range and final verification commands.

- [ ] **Step 3: Run full non-live verification**

Run:

```powershell
Set-Location 'C:\Users\oytl\Desktop\pyproject\brain\skills-and-workflows\BrainWorkflow'
$env:SystemRoot='C:\Windows'; $env:windir='C:\Windows'
python -c "import sys, runpy; sys.platform='linux'; runpy.run_module('unittest', run_name='__main__')" discover -s tests -q
python -m compileall -q wqb tests
```

Expected:

- unittest discovery passes.
- compileall exits with code 0.

- [ ] **Step 4: Run delivery gate against the local project state**

Run:

```powershell
Set-Location 'C:\Users\oytl\Desktop\pyproject\brain\skills-and-workflows\BrainWorkflow'
python -m wqb.cli compile-knowledge --knowledge-root 'C:\Users\oytl\Desktop\pyproject\brain\knowledge' --apply-cleanup
python -m wqb.cli delivery-gate --knowledge-root 'C:\Users\oytl\Desktop\pyproject\brain\knowledge' --runs-root 'C:\Users\oytl\Desktop\pyproject\brain\runs'
```

Expected:

- `compile-knowledge` writes `raw/maintenance/compile_reports/<date>.json`.
- `delivery-gate` writes `raw/maintenance/delivery_gates/<date>.json`.
- Delivery gate status is `passed`, or `failed` only with an explicit sensitive-file refusal or live-platform-refresh blocker recorded in root `milestone.md`.

- [ ] **Step 5: Run diff checks**

Run:

```powershell
Set-Location 'C:\Users\oytl\Desktop\pyproject\brain\skills-and-workflows'
git diff --check
```

Expected: passes, allowing only already-existing LF/CRLF warnings.

- [ ] **Step 6: Update root progress files**

Append to root `todo.md`:

```markdown
### Result
- Implemented simplified knowledge structure delivery contract.
- Non-live tests passed.
- Delivery gate report: `<delivery-gate-report-path>`.
- Remaining live prerequisite: refresh platform metadata with valid WorldQuant BRAIN authentication before spending simulation budget.
```

Update root `milestone.md` with:

```markdown
## 2026-07-30 Simplified Knowledge Contract Complete

- Current loop: simplified knowledge structure delivery contract, complete.
- Last successful command: `<last verification command>`.
- Current blocker/uncertainty: `<none or live platform auth/data refresh blocker>`.
- Exact next command: `python -m wqb.cli delivery-gate --knowledge-root 'C:\Users\oytl\Desktop\pyproject\brain\knowledge' --runs-root 'C:\Users\oytl\Desktop\pyproject\brain\runs'`.
- Files changed but not committed: `<status summary>`.
```

- [ ] **Step 7: Commit docs and final progress**

Run:

```powershell
Set-Location 'C:\Users\oytl\Desktop\pyproject\brain\skills-and-workflows'
git add BrainWorkflow/docs/operations/operating_guide.md BrainWorkflow/docs/superpowers/specs/2026-07-30-simplified-knowledge-structure-delivery-contract-design.md BrainWorkflow/todo.md
git commit -m "document simplified knowledge workflow operation"
```

Root `todo.md` and root `milestone.md` are outside the active git repository; do not attempt to commit them from `skills-and-workflows`.

---

## Final Verification Commands

Run after Task 10:

```powershell
Set-Location 'C:\Users\oytl\Desktop\pyproject\brain\skills-and-workflows\BrainWorkflow'
$env:SystemRoot='C:\Windows'; $env:windir='C:\Windows'
python -c "import sys, runpy; sys.platform='linux'; runpy.run_module('unittest', run_name='__main__')" discover -s tests -q
python -m compileall -q wqb tests
python -m wqb.cli compile-knowledge --knowledge-root 'C:\Users\oytl\Desktop\pyproject\brain\knowledge' --apply-cleanup
python -m wqb.cli delivery-gate --knowledge-root 'C:\Users\oytl\Desktop\pyproject\brain\knowledge' --runs-root 'C:\Users\oytl\Desktop\pyproject\brain\runs'
Set-Location 'C:\Users\oytl\Desktop\pyproject\brain\skills-and-workflows'
git diff --check
git status --short --branch
```

Expected final state:

- Tests pass.
- `compileall` passes.
- `knowledge/raw`, `knowledge/machine`, and `knowledge/wiki` are the only active knowledge layers.
- Machine resources are under `knowledge/machine`.
- Human wiki pages are compact Markdown pages.
- Delivery gate produces a durable pass/fail report without needing Codex chat context.
- Root `milestone.md` contains the next command and current blocker state.
