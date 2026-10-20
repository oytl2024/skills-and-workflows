import copy
from dataclasses import asdict
import importlib
import unittest


def evidence(kind="hypothesis"):
    """Input: kind str. Output: dict. Build an evidence reference without external IO."""
    return dict(source_path="raw/platform/learn/operators.md", sha256="a" * 64,
                capture_date="2026-10-13", kind=kind, experiment_refs=[])


def card():
    """Input: none. Output: dict[str, str]. Build seven one-sentence sections."""
    return dict(data_meaning="The field measures sentiment.", mechanism="Prices may adjust slowly.",
                conditions="The signal is available before trading.", alternative="Attention may explain the change.",
                prediction="Returns may increase above 0.5 after rank(x).",
                operator_roles="rank(x) removes scale dependence.", falsification="No later return difference weakens this idea.")


def semantic_fields():
    """Input: none. Output: dict. Build the optional shared serialization contract."""
    return dict(semantic_version=2, semantic_status="reviewed", evidence_refs=[evidence()],
                hypothesis_card=card(), operator_roles=[dict(operator="rank", role="normalization", purpose="Remove scale")],
                input_slots=[dict(name="signal", role="signal", required_semantics=["sentiment"], field_type="MATRIX",
                                  required_metadata=["units", "available_at"], reduction=None)])


class SemanticContractsTests(unittest.TestCase):
    def test_resource_contract_shapes_do_not_validate_source_authority(self):
        """Input: shape-only fixtures. Output: None. Strict parse neither reads sources nor certifies facts."""
        from tests.test_resource_evidence import timing_contract, definition_basis
        from wqb.semantic_contracts import timing_contract_from_dict, definition_basis_from_dict
        for parse, row in ((timing_contract_from_dict, timing_contract()), (definition_basis_from_dict, definition_basis())):
            self.assertEqual(parse(row), row)
            for missing in row:
                with self.subTest(missing=missing), self.assertRaises(ValueError):
                    parse({key: value for key, value in row.items() if key != missing})
            parsed = parse(row)
            parsed["rule_id"] = "changed"
            self.assertNotEqual(parsed, row)

    def setUp(self):
        """Input: none. Output: None. Require the new contract through an assertion for RED."""
        self.assertIsNotNone(importlib.util.find_spec("wqb.semantic_contracts"), "semantic contracts are not implemented")
        self.api = importlib.import_module("wqb.semantic_contracts")
        self.index = {"raw/platform/learn/operators.md": dict(path="raw/platform/learn/operators.md", content_hash="a" * 64,
                      captured_at="2026-10-13T09:00:00+08:00", source_type="platform_learn_material", source_family="raw/platform/learn")}

    def test_policy_and_dataclass_roundtrip(self):
        """Input: TestCase. Output: None. Verify defaults and public dataclass serialization."""
        self.assertEqual(asdict(self.api.SemanticPolicy()), dict(max_mechanisms=3, max_conditions_per_mechanism=2))
        self.assertEqual(asdict(self.api.evidence_ref_from_dict(evidence())), evidence())
        self.assertEqual(asdict(self.api.hypothesis_card_from_dict(card())), card())
        self.assertEqual(self.api.validate_semantic_record(semantic_fields(), self.index), [])

    def test_definition_requires_explicit_types_and_documented_provenance(self):
        """Input: TestCase. Output: None. Reject undocumented or malformed math/type contracts."""
        definition = dict(description="Average vector values", input_types=["VECTOR"], output_type="MATRIX",
            parameters=[dict(name="x", type="VECTOR", required=True)], evidence_refs=[evidence("documented")])
        self.assertEqual(self.api.validate_semantic_record(dict(definition=definition), self.index), [])
        for patch in [dict(output_type="UNKNOWN"), dict(parameters="x"), dict(evidence_refs=[evidence()]), dict(typo=1)]:
            with self.subTest(patch=patch):
                self.assertTrue(self.api.validate_semantic_record(dict(definition=dict(definition, **patch)), self.index))

    def test_definition_defaults_match_declared_parameter_types(self):
        """Input: TestCase. Output: None. Check typed defaults without Python bool/int coercion."""
        definition = dict(description="Transform values", input_types=["MATRIX"], output_type="MATRIX",
            parameters=[dict(name="x", type="MATRIX", required=True)], evidence_refs=[evidence("documented")])
        invalid = [("INTEGER", "not-an-integer"), ("INTEGER", True), ("INTEGER", 1.5),
            ("FLOAT", True), ("FLOAT", "0.5"), ("FLOAT", float("nan")), ("FLOAT", float("inf")),
            ("BOOLEAN", 1), ("STRING", 1), ("MATRIX", 0), ("VECTOR", "x"), ("GROUP", "sector")]
        for value_type, value in invalid:
            row = dict(definition, parameters=definition["parameters"] +
                [dict(name="option", type=value_type, required=False, default=value)])
            with self.subTest(value_type=value_type, value=value), self.assertRaises(ValueError):
                self.api.operator_definition_from_dict(row)
        for value_type, value in [("INTEGER", 1), ("FLOAT", 1), ("FLOAT", 0.5), ("BOOLEAN", False), ("STRING", "mean")]:
            row = dict(definition, parameters=definition["parameters"] +
                [dict(name="option", type=value_type, required=False, default=value)])
            with self.subTest(value_type=value_type, value=value):
                self.assertEqual(self.api.operator_definition_from_dict(row), row)

    def test_serialized_versions_reject_unknown_fields_but_legacy_extensions_survive(self):
        """Input: TestCase. Output: None. Verify strict versioned and compatible legacy loading."""
        from wqb.operator_semantics import operator_semantic_record_from_dict
        from wqb.template_library import template_record_from_dict
        for loader in (operator_semantic_record_from_dict, template_record_from_dict):
            with self.subTest(loader=loader.__name__), self.assertRaises(ValueError):
                loader(dict(semantic_version=2, evidence_refz=[]))
            loader(dict(historical_extra="preserved legacy behavior"))
        self.assertTrue(self.api.validate_semantic_record(dict(semantic_version=2, evidence_refz=[]), self.index))

    def test_reduction_rejects_nonfinite_parameters(self):
        """Input: TestCase. Output: None. Reject non-JSON numeric reduction parameters."""
        slot = semantic_fields()["input_slots"][0]
        for value in (float("nan"), float("inf")):
            row = dict(input_slots=[dict(slot, reduction=dict(operator="reduce", parameters=dict(limit=value)))])
            self.assertTrue(self.api.validate_semantic_record(row, self.index))

    def test_cards_require_exactly_seven_single_sentence_sections(self):
        """Input: TestCase. Output: None. Verify sentence boundaries and exact card shape."""
        for key, value in [("mechanism", ""), ("prediction", "First sentence. Second sentence."),
                           ("conditions", "First\nSecond"), ("alternative", 12)]:
            row = card()
            row[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.api.hypothesis_card_from_dict(row)
        for row in [dict(card(), extra="no"), {k: v for k, v in card().items() if k != "mechanism"}]:
            with self.assertRaises(ValueError):
                self.api.hypothesis_card_from_dict(row)

    def test_malformed_new_fields_fail_closed(self):
        """Input: TestCase. Output: None. Verify optional new fields reject malformed values."""
        for key, value in [("semantic_version", True), ("semantic_status", "ready"), ("evidence_refs", "oops"),
                           ("operator_roles", [{}]), ("input_slots", [dict(name="x", role="signal", field_type="MAGIC")]),
                           ("conditional_uses", [dict(conditions="x", purpose="y", failure_risks=[], evidence_refs=[], typo=1)]),
                           ("hypothesis_card", None), ("binding_version", 9), ("hypothesis_version", 0)]:
            row = dict(semantic_fields(), **{key: value})
            with self.subTest(key=key):
                issues = self.api.validate_semantic_record(row, self.index)
                self.assertTrue(issues)
                self.assertTrue(all(set(item) == {"code", "path", "message"} for item in issues))
        for patch in [dict(kind="verified"), dict(sha256="bad"), dict(source_path="../secret"),
                      dict(capture_date="2026-02-30"), dict(experiment_refs="x"), dict(extra=1)]:
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                self.api.evidence_ref_from_dict(dict(evidence(), **patch))

    def test_documented_requires_matching_platform_source(self):
        """Input: TestCase. Output: None. Verify existing source-index keys and platform origin."""
        row = dict(evidence_refs=[evidence("documented")])
        self.assertEqual(self.api.validate_semantic_record(row, self.index), [])
        for patch in [dict(content_hash="b" * 64), dict(captured_at="2026-10-12T09:00:00Z"),
                      dict(source_type="user_provided_reference", source_family="community"),
                      dict(source_type="unknown"), dict(source_family="raw/platform/activities"),
                      dict(path="raw/platform/other.md")]:
            index = copy.deepcopy(self.index)
            index["raw/platform/learn/operators.md"].update(patch)
            with self.subTest(patch=patch):
                self.assertTrue(self.api.validate_semantic_record(row, index))
        self.assertTrue(self.api.validate_semantic_record(row, {}))

    def test_source_paths_reject_control_characters(self):
        """Input: TestCase. Output: None. Reject control characters in local evidence paths."""
        with self.assertRaises(ValueError):
            self.api.evidence_ref_from_dict(dict(evidence(), source_path="raw/platform/learn/bad\npath.md"))

    def test_hypothesis_remains_hypothesis_and_measured_requires_verified_experiments(self):
        """Input: TestCase. Output: None. Verify grade separation and indexed experiment references."""
        ref = evidence("measured")
        row = dict(evidence_refs=[ref])
        self.assertTrue(self.api.validate_semantic_record(row, self.index))
        ref["experiment_refs"] = ["raw/research/runs/experiment.json"]
        self.assertTrue(self.api.validate_semantic_record(row, self.index))
        index = copy.deepcopy(self.index)
        index[ref["experiment_refs"][0]] = dict(path=ref["experiment_refs"][0], content_hash="b" * 64,
            captured_at="2026-10-13T00:00:00Z", source_type="research_record_source", source_family="raw/research/runs")
        self.assertEqual(self.api.validate_semantic_record(row, index), [])
        for key in ["path", "content_hash", "captured_at", "source_type", "source_family"]:
            broken = copy.deepcopy(index)
            del broken[ref["experiment_refs"][0]][key]
            self.assertTrue(self.api.validate_semantic_record(row, broken))
        hypothesis = dict(evidence_refs=[evidence()])
        self.assertEqual(self.api.validate_semantic_record(hypothesis, self.index), [])
        self.assertEqual(hypothesis["evidence_refs"][0]["kind"], "hypothesis")

    def test_economic_claims_cannot_borrow_documented_definition_grade(self):
        """Input: TestCase. Output: None. Require separate evidence for conditional inferences."""
        row = dict(conditional_uses=[dict(conditions="Comparable scale", purpose="May reveal underreaction",
                   failure_risks=["Noise"], evidence_refs=[evidence("documented")])])
        self.assertTrue(self.api.validate_semantic_record(row, self.index))
        row["conditional_uses"][0]["evidence_refs"].append(evidence())
        self.assertEqual(self.api.validate_semantic_record(row, self.index), [])
