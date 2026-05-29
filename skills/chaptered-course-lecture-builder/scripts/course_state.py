from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any


SUPPORTED_SUFFIXES = {".pdf", ".ppt", ".pptx", ".doc", ".docx", ".md", ".txt"}
IGNORE_DIR_NAMES = {"skill_builds", ".git", "__pycache__", ".venv", "venv"}
IGNORE_EXACT = {
    "AGENTS.md",
    "todo.md",
    "history.md",
    ".course_lecture_skill_state.json",
}
GENERATED_NAME_PATTERNS = [
    re.compile(r"^第\d{2}章知识点与考点\.md$"),
    re.compile(r".*知识逻辑地图\.md$"),
    re.compile(r".*题目-知识点反查表\.md$"),
]
CHAPTER_PATTERN = re.compile(r"第\s*0*(\d{1,2})\s*章")


def file_sha256(path: Path) -> str:
    # input: path(Path); output: str; function: return a stable sha256 digest for one file.
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def is_generated_output(name: str) -> bool:
    # input: name(str); output: bool; function: decide whether a filename is one of this skill's generated outputs.
    if name in IGNORE_EXACT:
        return True
    return any(pattern.match(name) for pattern in GENERATED_NAME_PATTERNS)


def infer_chapter(name: str) -> str | None:
    # input: name(str); output: str|None; function: infer a zero-padded chapter number from a filename when present.
    match = CHAPTER_PATTERN.search(name)
    if not match:
        return None
    return f"{int(match.group(1)):02d}"


def collect_materials(root: Path) -> list[dict[str, Any]]:
    # input: root(Path); output: list[dict[str, Any]]; function: scan a course folder and collect source materials only.
    materials: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if any(part in IGNORE_DIR_NAMES for part in path.parts):
            continue
        if path.suffix.lower() not in SUPPORTED_SUFFIXES:
            continue
        if is_generated_output(path.name):
            continue
        relative = path.relative_to(root).as_posix()
        materials.append(
            {
                "path": relative,
                "name": path.name,
                "suffix": path.suffix.lower(),
                "chapter": infer_chapter(path.name),
                "sha256": file_sha256(path),
                "size": path.stat().st_size,
            }
        )
    return materials


def build_snapshot(root: Path) -> dict[str, Any]:
    # input: root(Path); output: dict[str, Any]; function: build a normalized snapshot for one course folder.
    materials = collect_materials(root)
    files = {item["path"]: item for item in materials}
    chapter_inventory: dict[str, list[str]] = {}
    global_files: list[str] = []

    for item in materials:
        chapter = item["chapter"]
        if chapter is None:
            global_files.append(item["path"])
            continue
        chapter_inventory.setdefault(chapter, []).append(item["path"])

    for chapter in chapter_inventory:
        chapter_inventory[chapter].sort()
    global_files.sort()

    return {
        "course_name": root.name,
        "files": files,
        "chapter_inventory": chapter_inventory,
        "global_files": global_files,
    }


def diff_snapshots(previous: dict[str, Any] | None, current: dict[str, Any]) -> dict[str, Any]:
    # input: previous(dict|None), current(dict); output: dict[str, Any]; function: compute file-level changes between two snapshots.
    previous_files = {} if previous is None else previous.get("files", {})
    current_files = current.get("files", {})

    added_files = sorted(path for path in current_files if path not in previous_files)
    removed_files = sorted(path for path in previous_files if path not in current_files)
    changed_files = sorted(
        path
        for path in current_files
        if path in previous_files and current_files[path]["sha256"] != previous_files[path]["sha256"]
    )

    affected_chapters: set[str] = set()
    unmapped_changed_files: list[str] = []

    for path in added_files + removed_files + changed_files:
        source = current_files.get(path) or previous_files.get(path)
        chapter = source.get("chapter")
        if chapter is None:
            unmapped_changed_files.append(path)
        else:
            affected_chapters.add(chapter)

    mode = "initial" if previous is None else "update"

    return {
        "mode": mode,
        "added_files": added_files,
        "removed_files": removed_files,
        "changed_files": changed_files,
        "affected_chapters": sorted(affected_chapters),
        "unmapped_changed_files": sorted(unmapped_changed_files),
    }


def load_snapshot(state_path: Path) -> dict[str, Any] | None:
    # input: state_path(Path); output: dict|None; function: load a prior snapshot if it exists and is valid json.
    if not state_path.exists():
        return None
    return json.loads(state_path.read_text(encoding="utf-8"))


def write_snapshot(state_path: Path, snapshot: dict[str, Any]) -> None:
    # input: state_path(Path), snapshot(dict); output: None; function: persist the latest snapshot to the course folder.
    state_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")


def run_scan(root: Path, state_path: Path) -> dict[str, Any]:
    # input: root(Path), state_path(Path); output: dict[str, Any]; function: build current state, diff it with the previous state, and persist the new snapshot.
    previous = load_snapshot(state_path)
    current = build_snapshot(root)
    diff = diff_snapshots(previous, current)
    current["meta"] = diff
    write_snapshot(state_path, current)
    return {
        "course_name": current["course_name"],
        "mode": diff["mode"],
        "added_files": diff["added_files"],
        "removed_files": diff["removed_files"],
        "changed_files": diff["changed_files"],
        "affected_chapters": diff["affected_chapters"],
        "unmapped_changed_files": diff["unmapped_changed_files"],
        "chapter_inventory": current["chapter_inventory"],
        "global_files": current["global_files"],
        "state_path": state_path.as_posix(),
    }


def parse_args() -> argparse.Namespace:
    # input: None; output: argparse.Namespace; function: parse command line arguments for the scan command.
    parser = argparse.ArgumentParser(description="Track course materials and detect affected chapters.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan_parser = subparsers.add_parser("scan", help="Scan a course folder and write/update its state file.")
    scan_parser.add_argument("--root", required=True, help="Path to the course root directory.")
    scan_parser.add_argument(
        "--state",
        required=True,
        help="Path to the state json file to read and overwrite.",
    )
    return parser.parse_args()


def main() -> None:
    # input: None; output: None; function: dispatch the CLI command and print the resulting state summary as json.
    args = parse_args()
    if args.command != "scan":
        raise ValueError(f"Unsupported command: {args.command}")

    root = Path(args.root).resolve()
    state_path = Path(args.state).resolve()
    result = run_scan(root, state_path)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
