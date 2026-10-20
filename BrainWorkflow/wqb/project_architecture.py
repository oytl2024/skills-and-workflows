"""Parse and validate the canonical project architecture in milestone.md."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import re

from wqb.workflow_contract import STAGE_NAMES


MODULE_COLUMNS = ("id", "name", "responsibility", "status", "code", "tests", "evidence")
EDGE_COLUMNS = ("from", "to", "relation", "explanation")
VALID_STATUSES = {"implemented", "partial", "planned", "blocked"}
MODULE_ID = re.compile(r"^[a-z][a-z0-9-]*$")
WORKFLOW_COLUMNS = ("id", "name", "purpose", "status", "group", "runtime_stages", "owner_modules", "evidence")
WORKFLOW_EDGE_COLUMNS = ("from", "to", "kind", "explanation")
WORKFLOW_STATUSES = VALID_STATUSES | {"manual"}
WORKFLOW_GROUPS = {"research", "knowledge", "submission"}
WORKFLOW_EDGE_KINDS = {"next", "conditional", "loop", "prerequisite", "manual"}


class ArchitectureError(ValueError):
    """Invalid or unsafe project architecture input."""


def _cells(line: str, number: int, path: Path) -> list[str]:
    """Input: Markdown table row and location. Output: cell strings or ArchitectureError."""
    if not line.startswith("|") or not line.endswith("|"):
        raise ArchitectureError(f"{path}:{number}: table row must start and end with |")
    inner = line[1:-1]
    parts = re.split(r"(?<!\\)\|", inner)
    return [part.strip().replace(r"\|", "|") for part in parts]


def _table(lines: list[str], marker: str, columns: tuple[str, ...], path: Path) -> list[tuple[int, dict[str, str]]]:
    """Input: document lines and table contract. Output: located rows after strict header checks."""
    start = f"<!-- project-{marker}:start -->"
    end = f"<!-- project-{marker}:end -->"
    if lines.count(start) != 1 or lines.count(end) != 1:
        raise ArchitectureError(f"{path}: expected one {start} and {end}")
    first = lines.index(start)
    last = lines.index(end)
    if last <= first or last - first < 3:
        raise ArchitectureError(f"{path}:{first + 1}: empty or reversed {marker} table")
    content = [(first + index + 2, line.strip()) for index, line in enumerate(lines[first + 1:last]) if line.strip()]
    if len(content) < 2 or tuple(_cells(content[0][1], content[0][0], path)) != columns:
        raise ArchitectureError(f"{path}:{first + 2}: expected columns {', '.join(columns)}")
    divider = _cells(content[1][1], content[1][0], path)
    if len(divider) != len(columns) or any(not re.fullmatch(r":?-{3,}:?", cell) for cell in divider):
        raise ArchitectureError(f"{path}:{content[1][0]}: invalid table separator")
    rows = []
    for number, line in content[2:]:
        cells = _cells(line, number, path)
        if len(cells) != len(columns):
            raise ArchitectureError(f"{path}:{number}: expected {len(columns)} columns, got {len(cells)}")
        rows.append((number, dict(zip(columns, cells))))
    return rows


def _references(raw: str, status: str, root: Path, source: Path, number: int) -> list[dict[str, object]]:
    """Input: comma-separated workspace paths. Output: safe resolved link records."""
    result: list[dict[str, object]] = []
    for item in raw.split(","):
        relative = item.strip()
        if not relative:
            continue
        candidate = (root / relative).resolve()
        if not candidate.is_relative_to(root):
            raise ArchitectureError(f"{source}:{number}: outside workspace: {relative}")
        exists = candidate.exists()
        if exists and not candidate.is_file():
            raise ArchitectureError(f"{source}:{number}: not a file: {relative}")
        if status != "planned" and not exists:
            raise ArchitectureError(f"{source}:{number}: missing path: {relative}")
        result.append({"path": relative.replace("\\", "/"), "exists": exists})
    return result


def _details(lines: list[str], module_id: str, source: Path) -> str:
    """Input: document lines and module ID. Output: bounded Markdown detail text."""
    heading = f"### {module_id}"
    if lines.count(heading) != 1:
        raise ArchitectureError(f"{source}: missing or duplicate detail section: {heading}")
    first = lines.index(heading) + 1
    last = next((i for i in range(first, len(lines)) if lines[i].startswith("### ") or lines[i].startswith("## ")), len(lines))
    detail = "\n".join(lines[first:last]).strip()
    if not detail:
        raise ArchitectureError(f"{source}:{first}: empty detail section: {module_id}")
    return detail


def load_architecture(path: Path, workspace_root: Path) -> dict[str, object]:
    """Input: milestone Markdown and workspace root Paths. Output: validated graph dict."""
    source = path.resolve()
    root = workspace_root.resolve()
    lines = source.read_text(encoding="utf-8").splitlines()
    module_rows = _table(lines, "modules", MODULE_COLUMNS, source)
    edge_rows = _table(lines, "dependencies", EDGE_COLUMNS, source)
    modules: list[dict[str, object]] = []
    ids: set[str] = set()
    for number, row in module_rows:
        module_id = row["id"]
        if not MODULE_ID.fullmatch(module_id):
            raise ArchitectureError(f"{source}:{number}: invalid module ID: {module_id}")
        if module_id in ids:
            raise ArchitectureError(f"{source}:{number}: duplicate module: {module_id}")
        if row["status"] not in VALID_STATUSES:
            raise ArchitectureError(f"{source}:{number}: invalid status: {row['status']}")
        if row["status"] != "planned" and any(not row[key].strip() for key in ("code", "tests", "evidence")):
            raise ArchitectureError(f"{source}:{number}: nonplanned module requires code, tests and evidence")
        ids.add(module_id)
        modules.append({
            "id": module_id,
            "name": row["name"],
            "responsibility": row["responsibility"],
            "status": row["status"],
            "code": _references(row["code"], row["status"], root, source, number),
            "tests": _references(row["tests"], row["status"], root, source, number),
            "evidence": _references(row["evidence"], row["status"], root, source, number),
            "detail": _details(lines, module_id, source),
        })
    if not modules:
        raise ArchitectureError(f"{source}: architecture has no modules")
    edges: list[dict[str, str]] = []
    for number, row in edge_rows:
        if row["from"] not in ids or row["to"] not in ids:
            raise ArchitectureError(f"{source}:{number}: dependency references unknown module")
        edges.append(row)
    workflow_steps: list[dict[str, object]] = []
    workflow_edges: list[dict[str, str]] = []
    step_marker = "<!-- project-workflow-steps:start -->"
    edge_marker = "<!-- project-workflow-edges:start -->"
    if step_marker in lines or edge_marker in lines:
        step_rows = _table(lines, "workflow-steps", WORKFLOW_COLUMNS, source)
        transition_rows = _table(lines, "workflow-edges", WORKFLOW_EDGE_COLUMNS, source)
        step_ids: set[str] = set()
        for number, row in step_rows:
            step_id = row["id"]
            if not MODULE_ID.fullmatch(step_id):
                raise ArchitectureError(f"{source}:{number}: invalid workflow step ID: {step_id}")
            if step_id in step_ids:
                raise ArchitectureError(f"{source}:{number}: duplicate workflow step: {step_id}")
            if row["status"] not in WORKFLOW_STATUSES:
                raise ArchitectureError(f"{source}:{number}: invalid workflow status: {row['status']}")
            if row["group"] not in WORKFLOW_GROUPS:
                raise ArchitectureError(f"{source}:{number}: invalid workflow group: {row['group']}")
            stages = [value.strip() for value in row["runtime_stages"].split(",") if value.strip()]
            for stage in stages:
                if stage not in STAGE_NAMES:
                    raise ArchitectureError(f"{source}:{number}: unknown runtime stage: {stage}")
            if row["group"] == "research" and row["status"] != "planned" and not stages:
                raise ArchitectureError(f"{source}:{number}: research step requires runtime stage")
            owners = [value.strip() for value in row["owner_modules"].split(",") if value.strip()]
            if not owners:
                raise ArchitectureError(f"{source}:{number}: workflow step requires owner module")
            for owner in owners:
                if owner not in ids:
                    raise ArchitectureError(f"{source}:{number}: unknown owner module: {owner}")
            if row["status"] != "planned" and not row["evidence"].strip():
                raise ArchitectureError(f"{source}:{number}: nonplanned workflow step requires evidence")
            step_ids.add(step_id)
            workflow_steps.append({
                "id": step_id,
                "name": row["name"],
                "purpose": row["purpose"],
                "status": row["status"],
                "group": row["group"],
                "runtime_stages": stages,
                "owner_modules": owners,
                "evidence": _references(row["evidence"], row["status"], root, source, number),
                "detail": _details(lines, f"step:{step_id}", source),
            })
        if not workflow_steps:
            raise ArchitectureError(f"{source}: architecture has no workflow steps")
        for number, row in transition_rows:
            if row["from"] not in step_ids or row["to"] not in step_ids:
                raise ArchitectureError(f"{source}:{number}: workflow edge references unknown workflow step")
            if row["kind"] not in WORKFLOW_EDGE_KINDS:
                raise ArchitectureError(f"{source}:{number}: invalid workflow edge kind: {row['kind']}")
            if row["from"] == row["to"] and row["kind"] != "loop":
                raise ArchitectureError(f"{source}:{number}: self workflow edge requires loop kind")
            workflow_edges.append(row)
    updated_at = datetime.fromtimestamp(source.stat().st_mtime, tz=timezone.utc).isoformat()
    return {"modules": modules, "edges": edges, "workflow_steps": workflow_steps, "workflow_edges": workflow_edges, "updated_at": updated_at}
