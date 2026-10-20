from __future__ import annotations

from dataclasses import dataclass, field, fields, replace
import json
from pathlib import Path
import re
from typing import Any

from wqb.knowledge_paths import existing_machine_resource_path, machine_resource_path
from wqb.semantic_contracts import (
    EvidenceRef, HypothesisCard, InputSlot, OperatorRole,
    check_semantic_record_fields, semantic_fields_from_dict, semantic_record_to_dict,
)


FIELD_TYPE_BONUS = 3.0
TAG_MATCH_BONUS = 0.8
RISK_PENALTY = 0.4
DEFAULT_OPERATOR_SOURCE_PATH = "docs/knowledge/operator_data_semantics.md"
LEGACY_OPERATOR_SOURCE_PREFIXES = (
    (Path("wiki") / "20_semantics").as_posix(),
    (Path("wiki") / "30_templates").as_posix(),
)
OPERATOR_CALL_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(")
PLATFORM_OPERATOR_FIELDS = {"name", "id", "category", "description", "type", "scope", "level", "documentation"}


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
    semantic_version: int = 1
    semantic_status: str = "legacy/unreviewed"
    evidence_refs: list[EvidenceRef] = field(default_factory=list)
    conditional_uses: list[dict] = field(default_factory=list)
    definition: dict | None = None
    raw_definition: str = ""
    raw_description: str = ""
    hypothesis_card: HypothesisCard | None = None
    input_slots: list[InputSlot] = field(default_factory=list)
    operator_roles: list[OperatorRole] = field(default_factory=list)
    binding_version: int = 1
    hypothesis_id: str = ""
    hypothesis_version: int = 1
    definition_basis: dict | None = None


def default_operator_semantics() -> list[OperatorSemanticRecord]:
    """Input: none. Output: default records. Seed missing workflow semantics without replacing reviewed rows."""
    return [
        OperatorSemanticRecord(
            operator="rank",
            family="cross_sectional_normalizer",
            workflow_uses=["normalize_cross_section", "reduce_scale_dependency"],
            compatible_field_types=["MATRIX"],
            template_tags=["cross_sectional_normalizer"],
            risk_tags=["crowded_when_used_on_price_volume_only"],
            repair_levers=["group_rank", "group_neutralize"],
            source_paths=[DEFAULT_OPERATOR_SOURCE_PATH],
        ),
        OperatorSemanticRecord(
            operator="ts_delta",
            family="time_series_change",
            workflow_uses=["capture_recent_change", "event_surprise"],
            compatible_field_types=["MATRIX"],
            template_tags=["time_series_surprise", "event"],
            risk_tags=["turnover_inflation"],
            repair_levers=["increase_window", "add_decay"],
            source_paths=[DEFAULT_OPERATOR_SOURCE_PATH],
        ),
        OperatorSemanticRecord(
            operator="vec_avg",
            family="vector_to_matrix",
            workflow_uses=["summarize_vector_values"],
            compatible_field_types=["VECTOR"],
            template_tags=["event_value", "vector_to_matrix"],
            risk_tags=["invalid_raw_vector_use"],
            repair_levers=["replace_vec_count_with_vec_avg"],
            source_paths=[DEFAULT_OPERATOR_SOURCE_PATH],
        ),
    ]


def normalize_string_list(value: Any, *, uppercase: bool = False) -> list[str]:
    """Input: None, string, or list value. Output: normalized string list. Preserve scalar strings as one item."""
    if value is None:
        return []
    values = [value] if isinstance(value, str) else value
    if not isinstance(values, list):
        raise ValueError("operator semantic list fields must be lists, strings, or None")
    normalized = [str(item) for item in values if str(item)]
    return [item.upper() for item in normalized] if uppercase else normalized


def operator_semantic_record_from_dict(row: dict[str, Any]) -> OperatorSemanticRecord:
    """Input: dict row. Output: OperatorSemanticRecord. Normalize one operator semantic row."""
    check_semantic_record_fields(row, OperatorSemanticRecord)
    return OperatorSemanticRecord(
        operator=str(row.get("operator", "")),
        family=str(row.get("family", "")),
        workflow_uses=normalize_string_list(row.get("workflow_uses")),
        compatible_field_types=normalize_string_list(row.get("compatible_field_types"), uppercase=True),
        template_tags=normalize_string_list(row.get("template_tags")),
        risk_tags=normalize_string_list(row.get("risk_tags")),
        repair_levers=normalize_string_list(row.get("repair_levers")),
        source_paths=normalize_string_list(row.get("source_paths")),
        raw_description=_raw_operator_description(row),
        **semantic_fields_from_dict(row),
    )


def operator_semantic_record_to_dict(record: OperatorSemanticRecord) -> dict[str, Any]:
    """Input: OperatorSemanticRecord. Output: dict. Convert a record to JSON-safe data."""
    return semantic_record_to_dict(record)


def load_operator_semantics(path: Path) -> list[OperatorSemanticRecord]:
    """Input: JSONL path. Output: operator semantic records. Load operator workflow meanings."""
    if not path.exists():
        return []
    records: list[OperatorSemanticRecord] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            records.append(operator_semantic_record_from_dict(json.loads(line)))
    return records


def extract_expression_operators(expression: str) -> list[str]:
    """Input: expression string. Output: operator names. Extract function-call operators in first-use order."""
    operators: list[str] = []
    seen: set[str] = set()
    for match in OPERATOR_CALL_RE.finditer(expression):
        operator = match.group(1)
        if operator not in seen:
            seen.add(operator)
            operators.append(operator)
    return operators


def expression_operator_provenance(expression: str, knowledge_root: str | Path) -> list[dict[str, Any]]:
    """Input: expression and vault root. Output: operator provenance rows. Link generated code operators to the ledger."""
    ledger_path = existing_machine_resource_path(Path(knowledge_root), "operator_ledger")
    records = {record.operator: record for record in load_operator_semantics(ledger_path)}
    provenance: list[dict[str, Any]] = []
    for operator in extract_expression_operators(expression):
        record = records.get(operator)
        if record is None:
            provenance.append(
                {
                    "operator": operator,
                    "source": "missing_operator_ledger",
                    "family": "",
                    "workflow_uses": [],
                    "risk_tags": [],
                    "repair_levers": [],
                    "source_paths": [],
                }
            )
            continue
        provenance.append(
            {
                "operator": operator,
                "source": "knowledge_operator_ledger",
                "family": record.family,
                "workflow_uses": list(record.workflow_uses),
                "risk_tags": list(record.risk_tags),
                "repair_levers": list(record.repair_levers),
                "source_paths": list(record.source_paths),
            }
        )
    return provenance


def write_operator_semantics_jsonl(path: Path, records: list[OperatorSemanticRecord]) -> Path:
    """Input: path and records. Output: path. Write operator semantics as deterministic JSONL."""
    if any(parent.name == 'semantic_releases' for parent in path.parents):
        raise ValueError('immutable semantic release cannot be written directly')
    if path.parent.name == 'machine' and (path.parent / 'semantic_release.json').exists():
        raise ValueError('active semantic release forbids canonical direct writes')
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
        "| Operator | Family | Workflow Uses | Field Types | Template Tags | Risks | Repair Levers | Sources |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for record in sorted(records, key=lambda item: item.operator):
        lines.append(
            "| {} | {} | {} | {} | {} | {} | {} | {} |".format(
                record.operator,
                record.family,
                ", ".join(record.workflow_uses),
                ", ".join(record.compatible_field_types),
                ", ".join(record.template_tags),
                ", ".join(record.risk_tags),
                ", ".join(record.repair_levers),
                ", ".join(record.source_paths),
            )
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def normalize_operator_source_paths(source_paths: list[str]) -> list[str]:
    """Input: source path list. Output: canonicalized source list. Replace obsolete wiki provenance."""
    normalized: list[str] = []
    saw_legacy = False
    for value in source_paths:
        path = str(value).replace("\\", "/").strip()
        if not path:
            continue
        relative = path.removeprefix("knowledge/")
        absolute_or_vault_rooted = path.startswith("/") or (len(path) > 2 and path[1:3] == ":/") or path.startswith("knowledge/")
        if any(
            relative == prefix
            or relative.startswith(prefix + "/")
            or (absolute_or_vault_rooted and f"/{prefix}/" in relative)
            for prefix in LEGACY_OPERATOR_SOURCE_PREFIXES
        ):
            saw_legacy = True
            continue
        if path not in normalized:
            normalized.append(path)
    if saw_legacy and DEFAULT_OPERATOR_SOURCE_PATH not in normalized:
        normalized.append(DEFAULT_OPERATOR_SOURCE_PATH)
    return normalized or [DEFAULT_OPERATOR_SOURCE_PATH]


def normalize_operator_record_sources(record: OperatorSemanticRecord) -> OperatorSemanticRecord:
    """Input: operator record. Output: record with canonical source paths. Preserve reviewed semantic fields."""
    return replace(
        record,
        source_paths=normalize_operator_source_paths(record.source_paths),
    )


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


def _canonical_operator_rows(knowledge_root: Path) -> list[tuple[dict[str, Any], str]]:
    """Input: vault root. Output: operator rows and source paths. Read canonical structured operator captures."""
    capture_root = knowledge_root / "raw" / "platform" / "data_fields"
    rows: list[tuple[dict[str, Any], str]] = []
    for path in sorted(capture_root.glob("*/operators.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        operators = payload.get("operators", []) if isinstance(payload, dict) else []
        if not isinstance(operators, list):
            continue
        source_path = path.relative_to(knowledge_root).as_posix()
        rows.extend((row, source_path) for row in operators if isinstance(row, dict))
    rows.extend(_indexed_markdown_operator_rows(knowledge_root))
    return rows


def _raw_operator_description(row: dict) -> str:
    """Input: operator dict. Output: str. Keep literal source description separate from typed/economic facts."""
    value = row.get('raw_description', row.get('description', ''))
    if not isinstance(value, str):
        raise ValueError('raw_description: expected source text')
    return value


def _indexed_markdown_operator_rows(root: Path) -> list[tuple[dict, str]]:
    """Input: vault Path. Output: (row dict, path str) list. Verify indexed Markdown before preserving labelled facts."""
    from wqb.knowledge_contracts import parse_markdown_front_matter
    from wqb.semantic_compilation import _material
    index_path = existing_machine_resource_path(root, 'source_index')
    if not index_path.exists():
        return []
    rows, seen = [], {}
    for line in index_path.read_text(encoding='utf-8').splitlines():
        if not line.strip():
            continue
        indexed = json.loads(line)
        relative = indexed.get('path', '')
        if not (isinstance(relative, str) and relative.startswith('raw/platform/')
                and 'operator' in relative.lower() and relative.endswith('.md')):
            continue
        if relative in seen and seen[relative] != indexed:
            raise ValueError('conflicting operator source index rows: ' + relative)
        seen[relative] = indexed
        _, text = _material(root, indexed)
        _, body = parse_markdown_front_matter(text.replace('\r\n', '\n'))
        headings = list(re.finditer(r'^###\s+`?([A-Za-z_][A-Za-z0-9_]*)`?\s*$', body, re.MULTILINE))
        names = set()
        for number, heading in enumerate(headings):
            name = heading[1]
            if name in names:
                raise ValueError('conflicting duplicate operator heading: ' + name)
            names.add(name)
            end = headings[number + 1].start() if number + 1 < len(headings) else len(body)
            section = body[heading.end():end]
            category = re.search(r'^##\s+', section, re.MULTILINE)
            if category:
                section = section[:category.start()]
            labels = {}
            for label in ('Source id', 'Definition', 'Description'):
                values = re.findall(r'^- ' + re.escape(label) + r':[ \t]*(.*)$', section, re.MULTILINE)
                if len(values) > 1:
                    raise ValueError('conflicting operator source label: ' + name + '/' + label)
                if values:
                    value = values[0].strip()
                    labels[label] = value[1:-1] if value.startswith('`') and value.endswith('`') else value
            if labels.get('Source id') != name:
                raise ValueError('operator source identity missing or conflicting: ' + name)
            rows.append((dict(name=name, raw_definition=labels.get('Definition', ''),
                              raw_description=labels.get('Description', '')), relative))
    return rows


def _record_from_canonical_operator(row: dict[str, Any], source_path: str) -> OperatorSemanticRecord | None:
    """Input: canonical operator row and path. Output: semantic record or none. Compile conservative source semantics."""
    row = _normalize_canonical_operator_row(row)
    operator = str(row.get("name", row.get("operator", row.get("id", "")))).strip()
    if not operator:
        return None
    return OperatorSemanticRecord(
        operator=operator,
        family=str(row.get("category", row.get("family", "unclassified"))) or "unclassified",
        workflow_uses=normalize_string_list(row.get("workflow_uses")),
        compatible_field_types=normalize_string_list(row.get("compatible_field_types"), uppercase=True),
        template_tags=normalize_string_list(row.get("template_tags")),
        risk_tags=normalize_string_list(row.get("risk_tags")),
        repair_levers=normalize_string_list(row.get("repair_levers")),
        source_paths=[source_path],
        raw_description=_raw_operator_description(row),
        **semantic_fields_from_dict(row),
    )


def _normalize_canonical_operator_row(row: dict[str, Any]) -> dict[str, Any]:
    """Input: canonical dict. Output: dict. Validate v2 shape and separate raw syntax from typed definitions."""
    if row.get("semantic_version") == 2 or row.get("binding_version") == 2:
        allowed = {item.name for item in fields(OperatorSemanticRecord)} | PLATFORM_OPERATOR_FIELDS
        if set(row) - allowed:
            raise ValueError("canonical operator: unknown v2 fields")
    normalized = dict(row)
    if isinstance(normalized.get("definition"), str):
        syntax = normalized.pop("definition")
        if "raw_definition" in normalized and normalized["raw_definition"] != syntax:
            raise ValueError("canonical operator: conflicting raw definition strings")
        normalized["raw_definition"] = syntax
    return normalized


def compile_operator_semantics(
    knowledge_root: str | Path, generated_at: str
) -> dict[str, Any]:
    """Input: vault root and timestamp. Output: compile summary. Merge canonical operators, seeds, and reviewed records."""
    from wqb.semantic_publication import read_semantic_release
    if read_semantic_release(Path(knowledge_root))['release_id'] is not None:
        raise ValueError('active semantic release: direct operator compile refused; use compile-semantic-knowledge')
    root = Path(knowledge_root)
    jsonl_path = machine_resource_path(root, "operator_ledger")
    markdown_path = root / "machine" / "previews" / "operator_semantics.md"
    by_operator = {record.operator: record for record in default_operator_semantics()}
    captured_facts = {}
    for row, source_path in _canonical_operator_rows(root):
        record = _record_from_canonical_operator(row, source_path)
        if record is not None:
            previous = captured_facts.get(record.operator)
            if previous is not None:
                for key in ('raw_definition', 'raw_description', 'definition'):
                    old, new = getattr(previous, key), getattr(record, key)
                    if old and new and old != new:
                        raise ValueError('conflicting captured operator facts: ' + record.operator + '/' + key)
                record = replace(record, raw_definition=record.raw_definition or previous.raw_definition,
                                 raw_description=record.raw_description or previous.raw_description,
                                 definition=record.definition or previous.definition,
                                 source_paths=sorted(set(previous.source_paths + record.source_paths)))
            captured_facts[record.operator] = record
        if record is not None and record.operator not in by_operator:
            by_operator[record.operator] = record
        elif record is not None:
            by_operator[record.operator] = replace(
                by_operator[record.operator],
                **semantic_fields_from_dict(operator_semantic_record_to_dict(record)),
                raw_description=record.raw_description, source_paths=record.source_paths,
            )
    reviewed_path = existing_machine_resource_path(root, "operator_ledger")
    reviewed_rows = [json.loads(line) for line in reviewed_path.read_text(encoding="utf-8").splitlines() if line.strip()] if reviewed_path.exists() else []
    reviewed = [operator_semantic_record_from_dict(row) for row in reviewed_rows]
    for row, record in zip(reviewed_rows, reviewed):
        captured = by_operator.get(record.operator)
        if captured is not None:
            captured_fields = semantic_fields_from_dict(operator_semantic_record_to_dict(captured))
            missing = {key: value for key, value in captured_fields.items() if key not in row}
            if not record.raw_definition and captured.raw_definition:
                missing["raw_definition"] = captured.raw_definition
            if not record.raw_description and captured.raw_description:
                missing['raw_description'] = captured.raw_description
            if missing.get('raw_definition') or missing.get('raw_description'):
                missing['source_paths'] = sorted(set(record.source_paths + captured.source_paths))
            if any(value for key, value in missing.items() if key not in {"semantic_version", "binding_version", "semantic_status", "hypothesis_version"}):
                missing["semantic_version"] = max(record.semantic_version, captured.semantic_version)
            record = replace(record, **missing)
        by_operator[record.operator] = record
    records = [normalize_operator_record_sources(record) for record in by_operator.values()]
    write_operator_semantics_jsonl(jsonl_path, records)
    write_operator_semantics_markdown(markdown_path, records, generated_at)
    return {
        "record_count": len(records),
        "reviewed_record_count": len(reviewed),
        "jsonl_path": str(jsonl_path),
        "markdown_path": str(markdown_path),
    }
