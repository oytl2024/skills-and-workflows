"""Strict optional semantic contracts; provenance validation never upgrades evidence.

Source indexes are existing SourceIndexRow dictionaries keyed by their ``path``.
Measured references locate indexed raw research artifacts; the compiler must also
inspect those artifacts for expression/settings/results/test evidence before
publishing a measured claim. This module performs no filesystem or platform IO.

Shared JSON fields: semantic_version (1/2), semantic_status (legacy/unreviewed,
unreviewed, reviewed), evidence_refs, hypothesis_card, input_slots,
operator_roles, binding_version (1/2), hypothesis_id, hypothesis_version.
Operators additionally carry conditional_uses, definition and raw_definition.
raw_definition preserves platform API syntax strings without supplying types.
Absent cards and
definitions serialize by omission; legacy identity and skeleton are unchanged.
InputSlot.reduction is None or {operator: str, parameters: {name: scalar}};
parameters are named non-input arguments, not expression fragments. A definition
is {description, input_types, output_type, parameters, evidence_refs}; each
parameter has name/type/required and optional default. input_types matches the
leading input parameters, while parameters preserves the complete signature.
Unknown type/definition metadata is represented by an absent definition, never
inferred from an operator name. Structural parsers alone do not grant provenance.
"""

from dataclasses import asdict, dataclass, field, fields
from datetime import date, datetime
from pathlib import PurePosixPath
import math
import re
from copy import deepcopy


EVIDENCE_KINDS = {"documented", "hypothesis", "measured"}
SEMANTIC_STATUSES = {"legacy/unreviewed", "unreviewed", "reviewed"}
PLATFORM_SOURCE_TYPES = {"platform_learn_material", "platform_data_field_capture", "platform_activity_snapshot"}
CARD_FIELDS = ("data_meaning", "mechanism", "conditions", "alternative", "prediction", "operator_roles", "falsification")
IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
SHA256 = re.compile(r"[a-fA-F0-9]{64}\Z")
VALUE_TYPES = {"MATRIX", "VECTOR", "GROUP", "INTEGER", "FLOAT", "BOOLEAN", "STRING"}
DEFAULT_VALUE_TYPES = {"INTEGER": (int,), "FLOAT": (int, float), "BOOLEAN": (bool,), "STRING": (str,)}
SEMANTIC_FIELDS = {
    "semantic_version", "semantic_status", "binding_version", "hypothesis_id", "hypothesis_version",
    "definition", "definition_basis", "raw_definition", "evidence_refs", "hypothesis_card", "input_slots", "operator_roles", "conditional_uses",
}
MAX_PREMISES = 24
MAX_QUOTE_BYTES = 7000
MAX_VALUE_PATH = 16
MAX_JSON_DEPTH = 32


@dataclass(frozen=True)
class SemanticPolicy:
    max_mechanisms: int = 3
    max_conditions_per_mechanism: int = 2


@dataclass(frozen=True)
class EvidenceRef:
    source_path: str
    sha256: str
    capture_date: str
    kind: str
    experiment_refs: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class HypothesisCard:
    data_meaning: str
    mechanism: str
    conditions: str
    alternative: str
    prediction: str
    operator_roles: str
    falsification: str


@dataclass(frozen=True)
class InputSlot:
    name: str
    role: str
    required_semantics: list[str]
    field_type: str
    required_metadata: list[str] = field(default_factory=list)
    reduction: dict | None = None


@dataclass(frozen=True)
class OperatorRole:
    operator: str
    role: str
    purpose: str


def _text(value: object) -> str:
    """Input: object. Output: str. Require nonblank text without coercion."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("expected nonempty string")
    return value


def _strings(value: object) -> list[str]:
    """Input: object. Output: list[str]. Require a JSON array of nonblank strings."""
    if not isinstance(value, list):
        raise ValueError("expected list of strings")
    return [_text(item) for item in value]


def _path(value: object) -> str:
    """Input: object. Output: str. Require a canonical vault-relative POSIX path."""
    value = _text(value)
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {".", ".."} for part in value.split("/")) or ":" in value or "\\" in value or str(path) != value or any(ord(char) < 32 for char in value):
        raise ValueError("expected canonical local relative path")
    return value


def _shape(row: object, cls: type) -> dict:
    """Input: object and dataclass type. Output: dict. Reject unknown nested fields."""
    if not isinstance(row, dict) or set(row) - {item.name for item in fields(cls)}:
        raise ValueError("expected object with known fields")
    return row


def check_semantic_record_fields(row: dict, cls: type) -> None:
    """Input: dict and record dataclass type. Output: None. Reject versioned unknown fields, preserving legacy loading."""
    if not isinstance(row, dict):
        raise ValueError("expected record object")
    if row.get("semantic_version") == 2 or row.get("binding_version") == 2 or "definition_basis" in row or "timing_contract" in row:
        _shape(row, cls)


def _exact_fields(row: object, names: set[str]) -> dict:
    """Input: object/required keys set[str]. Output: dict. Require an exact wire object."""
    if not isinstance(row, dict) or set(row) != names:
        raise ValueError("unknown or missing contract fields")
    return row


def resource_scope_from_dict(row: dict) -> dict:
    """Input: dict. Output: dict. Validate exact scope without bool/int or text coercion."""
    _exact_fields(row, {"instrument_type", "region", "delay", "universe"})
    for key in ("instrument_type", "region", "universe"):
        _text(row[key])
    if type(row["delay"]) is not int or row["delay"] < 0:
        raise ValueError("scope delay must be a nonnegative integer")
    return dict(row)


def _json_value(value: object, depth: int = 0) -> None:
    """Input: object/int depth. Output: None. Reject non-JSON values and excessive nesting."""
    if depth > MAX_JSON_DEPTH:
        raise ValueError("JSON value nesting exceeds bound")
    if value is None or type(value) in (str, int, bool):
        return
    if type(value) is float and math.isfinite(value):
        return
    if isinstance(value, list):
        for item in value:
            _json_value(item, depth + 1)
        return
    if isinstance(value, dict) and all(type(key) is str for key in value):
        for item in value.values():
            _json_value(item, depth + 1)
        return
    raise ValueError("expected finite JSON value")


def premise_from_dict(row: dict) -> dict:
    """Input: dict. Output: copied dict. Parse bounded locator shape, without evidence authority."""
    _exact_fields(row, {"evidence_ref", "locator"})
    ref = evidence_ref_from_dict(row["evidence_ref"])
    if ref.kind != "documented":
        raise ValueError("source premises require documented evidence")
    locator = row["locator"]
    if not isinstance(locator, dict):
        raise ValueError("expected locator object")
    if locator.get("kind") == "markdown_quote":
        _exact_fields(locator, {"kind", "heading", "quote"})
        _text(locator["heading"])
        quote = _text(locator["quote"])
        if len(quote.encode("utf-8")) > MAX_QUOTE_BYTES:
            raise ValueError("premise quote exceeds bound")
    elif locator.get("kind") == "json_value":
        _exact_fields(locator, {"kind", "row_identity", "value_path", "expected_value"})
        identity = _exact_fields(locator["row_identity"], {"dataset_id", "field_id", "scope"})
        _text(identity["dataset_id"])
        _text(identity["field_id"])
        resource_scope_from_dict(identity["scope"])
        path = _strings(locator["value_path"])
        if len(path) > MAX_VALUE_PATH:
            raise ValueError("value path exceeds bound")
        _json_value(locator["expected_value"])
    else:
        raise ValueError("unsupported premise locator")
    return deepcopy(row)


def _premises(value: object) -> list[dict]:
    """Input: object. Output: list[dict]. Require bounded, nonempty source premises."""
    if not isinstance(value, list) or not 1 <= len(value) <= MAX_PREMISES:
        raise ValueError("premise count outside bound")
    return [premise_from_dict(item) for item in value]


def _rule(row: dict) -> None:
    """Input: contract dict. Output: None. Validate rule identity, not rule support."""
    _text(row["rule_id"])
    if type(row["rule_version"]) is not int or row["rule_version"] < 1:
        raise ValueError("rule version must be a positive integer")


def timing_contract_from_dict(row: dict) -> dict:
    """Input: dict. Output: copied dict. Parse timing shape only; never certify policy or PIT."""
    _exact_fields(row, {"kind", "scope", "cutoff_class", "field_identity", "premises", "rule_id", "rule_version", "historical_pit_verified"})
    if row["kind"] != "platform_execution_policy" or row["historical_pit_verified"] is not False:
        raise ValueError("unsupported timing kind or historical PIT claim")
    resource_scope_from_dict(row["scope"])
    identity = _exact_fields(row["field_identity"], {"dataset_id", "field_id"})
    for value in identity.values():
        _text(value)
    _text(row["cutoff_class"])
    _premises(row["premises"])
    _rule(row)
    return deepcopy(row)


def definition_basis_from_dict(row: dict) -> dict:
    """Input: dict. Output: copied dict. Parse derivation basis, without deriving or trusting types."""
    _exact_fields(row, {"operator", "signature_premise", "type_premises", "rule_id", "rule_version", "definition_digest"})
    if not IDENTIFIER.fullmatch(_text(row["operator"])):
        raise ValueError("invalid basis operator")
    premise_from_dict(row["signature_premise"])
    premises = _premises(row["type_premises"])
    if len(premises) + 1 > MAX_PREMISES:
        raise ValueError("basis premise count exceeds bound")
    _rule(row)
    if not isinstance(row["definition_digest"], str) or not SHA256.fullmatch(row["definition_digest"]):
        raise ValueError("expected definition digest")
    return deepcopy(row)


def evidence_ref_from_dict(row: dict) -> EvidenceRef:
    """Input: dict. Output: EvidenceRef. Parse structure, not factual authority."""
    row = _shape(row, EvidenceRef)
    try:
        ref = EvidenceRef(**row)
    except TypeError as exc:
        raise ValueError("missing evidence fields") from exc
    _path(ref.source_path)
    if not isinstance(ref.sha256, str) or not SHA256.fullmatch(ref.sha256):
        raise ValueError("expected SHA256 digest")
    if not isinstance(ref.capture_date, str) or date.fromisoformat(ref.capture_date).isoformat() != ref.capture_date:
        raise ValueError("expected ISO capture date")
    if not isinstance(ref.kind, str) or ref.kind not in EVIDENCE_KINDS:
        raise ValueError("unknown evidence kind")
    for path in _strings(ref.experiment_refs):
        _path(path)
    if ref.kind == "measured" and not ref.experiment_refs:
        raise ValueError("measured evidence requires experiment references")
    return ref


def hypothesis_card_from_dict(row: dict) -> HypothesisCard:
    """Input: dict. Output: HypothesisCard. Require seven nonempty single sentences."""
    row = _shape(row, HypothesisCard)
    if set(row) != set(CARD_FIELDS):
        raise ValueError("expected seven hypothesis card sections")
    for value in row.values():
        text = _text(value).strip()
        # Sentence separators exclude decimal points and dots inside function names.
        if "\n" in text or "\r" in text or re.search(r"[.!?\u3002\uff01\uff1f]\s+\S|[\u3002\uff01\uff1f]\S", text):
            raise ValueError("each hypothesis card section must be one sentence")
    return HypothesisCard(**row)


def input_slot_from_dict(row: dict) -> InputSlot:
    """Input: dict. Output: InputSlot. Parse a named slot without inventing field metadata."""
    row = _shape(row, InputSlot)
    try:
        slot = InputSlot(**row)
    except TypeError as exc:
        raise ValueError("missing input slot fields") from exc
    if not IDENTIFIER.fullmatch(_text(slot.name)):
        raise ValueError("invalid slot name")
    _text(slot.role)
    _strings(slot.required_semantics)
    _strings(slot.required_metadata)
    if slot.field_type not in ("MATRIX", "VECTOR", "GROUP"):
        raise ValueError("unknown slot field type")
    if slot.reduction is not None:
        reduction = slot.reduction
        if not isinstance(reduction, dict) or set(reduction) != {"operator", "parameters"}:
            raise ValueError("reduction requires operator and parameters")
        if not IDENTIFIER.fullmatch(_text(reduction["operator"])) or not isinstance(reduction["parameters"], dict):
            raise ValueError("invalid reduction operator or parameters")
        for key, value in reduction["parameters"].items():
            if not IDENTIFIER.fullmatch(_text(key)) or type(value) not in (str, int, float, bool):
                raise ValueError("invalid reduction parameter")
            if type(value) is float and not math.isfinite(value):
                raise ValueError("nonfinite reduction parameter")
    return slot


def operator_role_from_dict(row: dict) -> OperatorRole:
    """Input: dict. Output: OperatorRole. Parse an operator's necessary purpose."""
    row = _shape(row, OperatorRole)
    try:
        role = OperatorRole(**row)
    except TypeError as exc:
        raise ValueError("missing operator role fields") from exc
    if not IDENTIFIER.fullmatch(_text(role.operator)):
        raise ValueError("invalid operator name")
    _text(role.role)
    _text(role.purpose)
    return role


def semantic_fields_from_dict(row: dict) -> dict:
    """Input: record dict. Output: parsed optional fields dict. Fail closed for new JSON fields."""
    if not isinstance(row, dict):
        raise ValueError("expected semantic record object")
    result = {}
    if "definition_basis" in row:
        result["definition_basis"] = definition_basis_from_dict(row["definition_basis"])
    if "raw_definition" in row:
        if not isinstance(row["raw_definition"], str):
            raise ValueError("raw_definition: expected platform syntax string")
        result["raw_definition"] = row["raw_definition"]
    if "definition" in row:
        result["definition"] = operator_definition_from_dict(row["definition"])
    for key in ("semantic_version", "binding_version", "hypothesis_version"):
        if key in row:
            value = row[key]
            if type(value) is not int or value < 1 or (key != "hypothesis_version" and value not in (1, 2)):
                raise ValueError(f"{key}: unsupported version")
            result[key] = value
    if "semantic_status" in row:
        if not isinstance(row["semantic_status"], str) or row["semantic_status"] not in SEMANTIC_STATUSES:
            raise ValueError("semantic_status: unknown status")
        result["semantic_status"] = row["semantic_status"]
    if "hypothesis_id" in row:
        result["hypothesis_id"] = _text(row["hypothesis_id"])
    if "hypothesis_card" in row:
        result["hypothesis_card"] = hypothesis_card_from_dict(row["hypothesis_card"])
    for key, parser in (("evidence_refs", evidence_ref_from_dict), ("input_slots", input_slot_from_dict),
                        ("operator_roles", operator_role_from_dict)):
        if key in row:
            if not isinstance(row[key], list):
                raise ValueError(f"{key}: expected list")
            result[key] = [parser(item) for item in row[key]]
    names = [slot.name for slot in result.get("input_slots", [])]
    if len(names) != len(set(names)):
        raise ValueError("input_slots: duplicate names")
    if "conditional_uses" in row:
        if not isinstance(row["conditional_uses"], list):
            raise ValueError("conditional_uses: expected list")
        uses = []
        for use in row["conditional_uses"]:
            if not isinstance(use, dict) or set(use) != {"conditions", "purpose", "failure_risks", "evidence_refs"}:
                raise ValueError("conditional_uses: unknown or missing fields")
            _text(use["conditions"])
            _text(use["purpose"])
            _strings(use["failure_risks"])
            if not isinstance(use["evidence_refs"], list):
                raise ValueError("conditional_uses.evidence_refs: expected list")
            refs = [asdict(evidence_ref_from_dict(ref)) for ref in use["evidence_refs"]]
            uses.append(dict(use, evidence_refs=refs))
        result["conditional_uses"] = uses
    return result


def operator_definition_from_dict(row: dict) -> dict:
    """Input: dict. Output: JSON-safe dict. Parse explicit types/signature; never infer from names."""
    if not isinstance(row, dict) or set(row) != {"description", "input_types", "output_type", "parameters", "evidence_refs"}:
        raise ValueError("definition: unknown or missing fields")
    _text(row["description"])
    inputs = _strings(row["input_types"])
    if not inputs or any(item not in VALUE_TYPES for item in inputs) or row["output_type"] not in VALUE_TYPES:
        raise ValueError("definition: unknown input/output types")
    if not isinstance(row["parameters"], list) or not row["parameters"]:
        raise ValueError("definition: expected parameter signature")
    parameters = []
    for parameter in row["parameters"]:
        if not isinstance(parameter, dict) or not {"name", "type", "required"} <= set(parameter) or set(parameter) - {"name", "type", "required", "default"}:
            raise ValueError("definition: invalid parameter fields")
        if not IDENTIFIER.fullmatch(_text(parameter["name"])) or parameter["type"] not in VALUE_TYPES or type(parameter["required"]) is not bool:
            raise ValueError("definition: invalid parameter signature")
        if "default" in parameter and (parameter["required"] or type(parameter["default"]) not in (str, int, float, bool)):
            raise ValueError("definition: invalid parameter default")
        if type(parameter.get("default")) is float and not math.isfinite(parameter["default"]):
            raise ValueError("definition: nonfinite parameter default")
        if "default" in parameter and type(parameter["default"]) not in DEFAULT_VALUE_TYPES.get(parameter["type"], ()):
            raise ValueError("definition: default does not match declared parameter type")
        parameters.append(dict(parameter))
    if len({item["name"] for item in parameters}) != len(parameters):
        raise ValueError("definition: duplicate parameters")
    if [item["type"] for item in parameters[:len(inputs)]] != inputs:
        raise ValueError("definition: input types disagree with parameter signature")
    if not isinstance(row["evidence_refs"], list):
        raise ValueError("definition: expected evidence references")
    refs = [evidence_ref_from_dict(ref) for ref in row["evidence_refs"]]
    if not refs or any(ref.kind != "documented" for ref in refs):
        raise ValueError("definition: explicit types require documented evidence")
    return dict(row, input_types=inputs, parameters=parameters, evidence_refs=[asdict(ref) for ref in refs])


def semantic_record_to_dict(record: object) -> dict:
    """Input: record dataclass. Output: JSON-safe dict. Omit absent optional objects for strict reloading."""
    row = asdict(record)
    for key in ("definition", "hypothesis_card", "definition_basis"):
        if row.get(key) is None:
            row.pop(key, None)
    if not row.get("hypothesis_id"):
        row.pop("hypothesis_id", None)
    return row


def _indexed_source(path: str, source_index: dict) -> dict:
    """Input: path str, existing index dict. Output: source dict. Verify index identity and metadata."""
    source = source_index.get(path)
    if not isinstance(source, dict) or source.get("path") != path:
        raise ValueError("source missing or path mismatched")
    if not isinstance(source.get("content_hash"), str) or not SHA256.fullmatch(source["content_hash"]):
        raise ValueError("source missing content_hash")
    captured = _text(source.get("captured_at"))
    datetime.fromisoformat(captured.replace("Z", "+00:00"))
    _text(source.get("source_type"))
    _text(source.get("source_family"))
    return source


def validate_semantic_record(row: dict, source_index: dict) -> list[dict]:
    """Input: record dict and path-keyed SourceIndexRow dicts. Output: code/path/message issues list.

    Verify structure and indexed provenance, without IO, grade promotion, or claims
    that research payloads have been inspected. Measured payload review belongs
    to compilation; indexed references alone do not establish successful results.
    """
    issues = []
    try:
        if isinstance(row, dict) and (row.get("semantic_version") == 2 or row.get("binding_version") == 2):
            # Resolve complete-record shapes lazily to avoid import-time cycles.
            if "template_id" in row:
                from wqb.template_library import TemplateRecord
                check_semantic_record_fields(row, TemplateRecord)
            elif "operator" in row:
                from wqb.operator_semantics import OperatorSemanticRecord
                check_semantic_record_fields(row, OperatorSemanticRecord)
            elif set(row) - SEMANTIC_FIELDS:
                raise ValueError("unknown semantic record fields")
        parsed = semantic_fields_from_dict(row)
    except (ValueError, TypeError) as exc:
        return [dict(code="invalid_structure", path="$", message=str(exc))]
    if not isinstance(source_index, dict):
        return [dict(code="invalid_source_index", path="$", message="expected path-keyed source index")]
    references = [(f"evidence_refs[{i}]", ref) for i, ref in enumerate(parsed.get("evidence_refs", []))]
    if "definition" in parsed:
        references.extend((f"definition.evidence_refs[{i}]", evidence_ref_from_dict(ref))
                          for i, ref in enumerate(parsed["definition"]["evidence_refs"]))
    for i, use in enumerate(parsed.get("conditional_uses", [])):
        refs = [evidence_ref_from_dict(ref) for ref in use["evidence_refs"]]
        if not any(ref.kind in {"hypothesis", "measured"} for ref in refs):
            issues.append(dict(code="unsupported_inference", path=f"conditional_uses[{i}]", message="economic uses require their own hypothesis or measured evidence"))
        references.extend((f"conditional_uses[{i}].evidence_refs[{j}]", ref) for j, ref in enumerate(refs))
    if "hypothesis_card" in parsed and not any(ref.kind in {"hypothesis", "measured"} for ref in parsed.get("evidence_refs", [])):
        issues.append(dict(code="unsupported_inference", path="hypothesis_card", message="hypothesis card requires hypothesis or measured evidence"))
    for path, ref in references:
        try:
            source = _indexed_source(ref.source_path, source_index)
            if source["content_hash"].lower() != ref.sha256.lower() or source["captured_at"][:10] != ref.capture_date:
                raise ValueError("source digest or capture date mismatched")
            if ref.kind == "documented" and not (
                ref.source_path.startswith("raw/platform/")
                and source["source_family"].startswith("raw/platform/")
                and ref.source_path.startswith(source["source_family"] + "/")
                and source["source_type"] in PLATFORM_SOURCE_TYPES
            ):
                raise ValueError("documented definitions require platform provenance")
            for experiment in ref.experiment_refs:
                indexed = _indexed_source(experiment, source_index)
                if not experiment.startswith("raw/research/") or not indexed["source_family"].startswith("raw/research/") or not experiment.startswith(indexed["source_family"] + "/") or indexed["source_type"] != "research_record_source":
                    raise ValueError("experiment reference requires indexed research provenance")
        except (ValueError, TypeError) as exc:
            issues.append(dict(code="invalid_evidence", path=path, message=str(exc)))
    return issues
