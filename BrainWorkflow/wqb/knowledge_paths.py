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
    """Input: knowledge root. Output: all current top-level directory names for active-structure validation."""
    root = Path(knowledge_root)
    if not root.exists():
        return set()
    return {path.name for path in root.iterdir() if path.is_dir()}
