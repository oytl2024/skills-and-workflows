import tempfile
import unittest
import json
import hashlib
from pathlib import Path

from wqb.operator_semantics import (
    OperatorSemanticRecord,
    compile_operator_semantics,
    expression_operator_provenance,
    extract_expression_operators,
    load_operator_semantics,
    operator_semantic_record_from_dict,
    score_operator_for_template,
    write_operator_semantics_jsonl,
    write_operator_semantics_markdown,
)


class OperatorSemanticsTests(unittest.TestCase):
    def test_legacy_provenance_uses_verified_capture_not_in_new_release(self):
        """Input: partial published ledger and indexed raw. Output: None. Recover only explicit legacy source facts."""
        from wqb.semantic_publication import stage_semantic_release, publish_semantic_release
        body = ('### `rank`\n- Source id: `rank`\n- Definition: `rank(x)`\n'
                '### `vec_count`\n- Source id: `vec_count`\n- Definition: `vec_count(x)`\n- Description: Number of elements.\n')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'wiki').mkdir()
            relative = self.markdown_capture(root, body)
            ledger = root / 'machine/operator_ledger.jsonl'
            ledger.write_text('', encoding='utf-8')
            staged = stage_semantic_release(root, dict(validated_operators=[{'operator': 'ts_delta'}],
                validated_templates=[{'template_id': 'new'}], source_refs=[dict(path=relative,
                sha256=hashlib.sha256((root / relative).read_bytes()).hexdigest())],
                wiki_materials={}), '2026-10-15T00:00:00Z')
            publish_semantic_release(root, staged)
            self.assertEqual(expression_operator_provenance('vec_count(x)', root)[0]['source'], 'missing_operator_ledger')
            rows = expression_operator_provenance('rank(ts_delta(vec_count(x),1))', root, legacy_capture=True)
            self.assertEqual([r['operator'] for r in rows], ['rank', 'ts_delta', 'vec_count'])
            self.assertEqual(rows[1]['source'], 'knowledge_operator_ledger')
            row = rows[2]
            self.assertEqual(row['source'], 'knowledge_indexed_operator_capture')
            self.assertEqual(row['source_paths'], [relative])
            self.assertEqual(row['raw_definition'], 'vec_count(x)')
            self.assertEqual(len(row['source_sha256']), 64)
            self.assertEqual(row['captured_at'], '2026-10-11T00:00:00Z')
            self.assertEqual(expression_operator_provenance('vec_count(x)', root)[0]['source'], 'missing_operator_ledger')

    def test_legacy_provenance_rejects_conflicting_index_before_latest_selection(self):
        """Input: reordered conflicting dated rows. Output: None. Never downgrade to an older source through dict overwrite."""
        from wqb.knowledge_contracts import render_front_matter
        body = '### `vec_count`\n- Source id: `vec_count`\n- Definition: `vec_count(x)`\n'
        for reverse in (False, True):
            with self.subTest(reverse=reverse), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                self.markdown_capture(root, body)
                index = root / 'machine/source_index.jsonl'
                latest = json.loads(index.read_text(encoding='utf-8'))
                older = dict(latest, path='raw/platform/operators/2026-10-01/operators.md', captured_at='2026-10-01T00:00:00Z')
                path = root / older['path']
                path.parent.mkdir(parents=True)
                path.write_text(render_front_matter(older) + body, encoding='utf-8')
                conflict = dict(latest, captured_at='2026-09-01T00:00:00Z')
                rows = [latest, older, conflict]
                index.write_text('\n'.join(json.dumps(row) for row in (rows[::-1] if reverse else rows)), encoding='utf-8')
                with self.assertRaisesRegex(ValueError, 'conflicting operator source index'):
                    expression_operator_provenance('vec_count(x)', root, legacy_capture=True)

    def test_legacy_provenance_never_falls_back_from_bad_newest_capture(self):
        """Input: missing or corrupt newest raw plus valid older raw. Output: None. Fail closed rather than downgrade evidence."""
        from wqb.knowledge_contracts import render_front_matter
        body = '### `vec_count`\n- Source id: `vec_count`\n- Definition: `vec_count(x)`\n'
        for missing in (False, True):
            with self.subTest(missing=missing), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                relative = self.markdown_capture(root, body)
                index = root / 'machine/source_index.jsonl'
                latest = json.loads(index.read_text(encoding='utf-8'))
                older = dict(latest, path='raw/platform/operators/2026-10-01/operators.md', captured_at='2026-10-01T00:00:00Z')
                path = root / older['path']
                path.parent.mkdir(parents=True)
                path.write_text(render_front_matter(older) + body, encoding='utf-8')
                index.write_text(json.dumps(latest) + '\n' + json.dumps(older), encoding='utf-8')
                if missing:
                    (root / relative).unlink()
                else:
                    (root / relative).write_text('changed', encoding='utf-8')
                with self.assertRaises((ValueError, OSError)):
                    expression_operator_provenance('vec_count(x)', root, legacy_capture=True)

    def test_legacy_capture_age_boundary_and_invalid_get_receipt(self):
        """Input: controlled dates and forged receipt. Output: None. Preserve 90-day policy and audit validation."""
        from datetime import datetime, timezone
        from unittest.mock import patch
        body = '### `vec_count`\n- Source id: `vec_count`\n- Definition: `vec_count(x)`\n'
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            relative = self.markdown_capture(root, body)
            for today, allowed in (('2027-01-09', True), ('2027-01-10', False), ('2026-10-10', False)):
                with self.subTest(today=today), patch('wqb.operator_semantics.datetime', wraps=datetime) as clock:
                    clock.now.return_value = datetime.fromisoformat(today).replace(tzinfo=timezone.utc)
                    if allowed:
                        self.assertEqual(expression_operator_provenance('vec_count(x)', root,
                            legacy_capture=True)[0]['source'], 'knowledge_indexed_operator_capture')
                    else:
                        with self.assertRaisesRegex(ValueError, 'knowledge age policy'):
                            expression_operator_provenance('vec_count(x)', root, legacy_capture=True)
            self.markdown_capture_existing(root, relative, body + '\n## Raw GET Receipt\n\n```json\n{}\n```\n')
            with self.assertRaisesRegex(ValueError, 'GET receipt'):
                expression_operator_provenance('vec_count(x)', root, legacy_capture=True)

    def test_legacy_provenance_rejects_untrusted_or_tampered_capture(self):
        """Input: untrusted, incomplete or corrupt captures. Output: None. Never promote unsupported operators."""
        body = '### `vec_count`\n- Source id: `vec_count`\n- Definition: `vec_count(x)`\n'
        for kind in ('user_provided_reference', 'tampered', 'wrong_signature', 'missing_index'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                relative = self.markdown_capture(root, body, source_type=kind if kind == 'user_provided_reference' else 'platform_api')
                (root / 'machine/operator_ledger.jsonl').write_text('', encoding='utf-8')
                if kind == 'tampered':
                    (root / relative).write_text('changed', encoding='utf-8')
                elif kind == 'wrong_signature':
                    # Keep a valid digest while removing the claimed operator signature.
                    text = body.replace('vec_count(x)', 'rank(x)')
                    self.markdown_capture_existing(root, relative, text)
                elif kind == 'missing_index':
                    (root / 'machine/source_index.jsonl').unlink()
                if kind == 'tampered':
                    with self.assertRaises(ValueError):
                        expression_operator_provenance('vec_count(x)', root, legacy_capture=True)
                else:
                    row = expression_operator_provenance('vec_count(x)', root, legacy_capture=True)[0]
                    self.assertEqual(row['source'], 'missing_operator_ledger')

    def markdown_capture_existing(self, root, relative, body):
        """Input: root Path, relative path and body str. Output: None. Replace an isolated fixture with consistent hashes."""
        from wqb.knowledge_contracts import render_front_matter
        path = root / 'machine/source_index.jsonl'
        row = json.loads(path.read_text(encoding='utf-8'))
        row['content_hash'] = hashlib.sha256(body.encode()).hexdigest()
        (root / relative).write_text(render_front_matter(row) + body, encoding='utf-8')
        path.write_text(json.dumps(row) + '\n', encoding='utf-8')

    def test_legacy_dictionary_and_definition_basis_jsonl_roundtrip(self):
        """Input: legacy and optional basis rows. Output: None. Keep exact legacy shape and lossless JSONL."""
        from tests.test_resource_evidence import definition_basis
        from wqb.operator_semantics import operator_semantic_record_to_dict
        expected = dict(operator="", family="", workflow_uses=[], compatible_field_types=[],
                        template_tags=[], risk_tags=[], repair_levers=[], source_paths=[],
                        semantic_version=1, semantic_status="legacy/unreviewed", evidence_refs=[],
                        conditional_uses=[], raw_definition="", raw_description="", input_slots=[],
                        operator_roles=[], binding_version=1, hypothesis_version=1)
        self.assertEqual(operator_semantic_record_to_dict(operator_semantic_record_from_dict({})), expected)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "operators.jsonl"
            row = dict(expected, operator="ts_delta", definition_basis=definition_basis())
            write_operator_semantics_jsonl(path, [operator_semantic_record_from_dict(row)])
            self.assertEqual(operator_semantic_record_to_dict(load_operator_semantics(path)[0]), row)

    def markdown_capture(self, root, body, source_type='platform_api'):
        """Input: Path/body str/source type str. Output: path str. Write isolated indexed capture with real body hash."""
        from wqb.knowledge_contracts import render_front_matter
        relative = 'raw/platform/operators/2026-10-11/operators.md'
        index = dict(path=relative, content_hash=hashlib.sha256(body.encode()).hexdigest(),
                     captured_at='2026-10-11T00:00:00Z', source_type=source_type,
                     source_family='raw/platform/operators')
        path = root / relative
        path.parent.mkdir(parents=True)
        path.write_text(render_front_matter(index) + body, encoding='utf-8')
        (root / 'machine').mkdir(exist_ok=True)
        (root / 'machine/source_index.jsonl').write_text(json.dumps(index)+'\n', encoding='utf-8')
        return relative

    def test_indexed_markdown_preserves_syntax_description_and_actual_source(self):
        """Input: API Markdown capture. Output: None. Preserve source facts without typed/economic promotion."""
        body = '### `rank`\n\n- Source id: `rank`\n- Definition: `rank(x)`\n- Description: Orders values.\n'
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            relative = self.markdown_capture(root, body)
            compile_operator_semantics(root, '2026-10-14T00:00:00Z')
            record = next(r for r in load_operator_semantics(root/'machine/operator_ledger.jsonl') if r.operator == 'rank')
            self.assertEqual(record.raw_definition, 'rank(x)')
            self.assertEqual(getattr(record, 'raw_description', ''), 'Orders values.')
            self.assertIn(relative, record.source_paths)
            self.assertIsNone(record.definition)
            index = json.loads((root/'machine/source_index.jsonl').read_text())
            self.assertEqual(index['source_type'], 'platform_api')

    def test_markdown_conflicting_hash_or_missing_path_rejects_before_writes(self):
        """Input: tampered indexed sources. Output: None. Fail closed before publishing a ledger."""
        for missing in (False, True):
            with self.subTest(missing=missing), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                relative = self.markdown_capture(root, '### `add`\n- Source id: `add`\n- Definition: `add(x, y)`\n')
                if missing:
                    (root/relative).unlink()
                else:
                    with (root/relative).open('a', encoding='utf-8') as handle:
                        handle.write('changed\n')
                with self.assertRaises((ValueError, OSError)):
                    compile_operator_semantics(root, '2026-10-14T00:00:00Z')
                self.assertFalse((root/'machine/operator_ledger.jsonl').exists())

    def test_json_and_markdown_conflicting_syntax_is_rejected(self):
        """Input: conflicting captures. Output: None. Never silently select one assertion for the same operator."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.markdown_capture(root, '### `add`\n- Source id: `add`\n- Definition: `add(x, y)`\n')
            path = root/'raw/platform/data_fields/2026-07-29/operators.json'
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps(dict(operators=[dict(name='add', definition='add(x)')])), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'conflict'):
                compile_operator_semantics(root, '2026-10-14T00:00:00Z')

    def test_matching_json_and_markdown_keep_both_sources_and_descriptions(self):
        """Input: matching captured facts. Output: None. Preserve both provenance paths without granting types."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            relative = self.markdown_capture(root, '### `add`\n- Source id: `add`\n- Definition: `add(x, y)`\n- Description: Add values.\n')
            path = root/'raw/platform/data_fields/2026-07-29/operators.json'
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps(dict(operators=[dict(name='add', definition='add(x, y)', description='Add values.')])), encoding='utf-8')
            compile_operator_semantics(root, '2026-10-14T00:00:00Z')
            record = next(r for r in load_operator_semantics(root/'machine/operator_ledger.jsonl') if r.operator == 'add')
            self.assertEqual(record.raw_description, 'Add values.')
            self.assertEqual(set(record.source_paths), {relative, path.relative_to(root).as_posix()})
            self.assertIsNone(record.definition)

    def test_empty_markdown_definition_does_not_consume_next_label(self):
        """Input: blank source syntax line. Output: None. Keep missing syntax unknown instead of swallowing description."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.markdown_capture(root, '### `add`\n- Source id: `add`\n- Definition:\n- Description: Add values.\n')
            compile_operator_semantics(root, '2026-10-14T00:00:00Z')
            record = next(r for r in load_operator_semantics(root/'machine/operator_ledger.jsonl') if r.operator == 'add')
            self.assertEqual(record.raw_definition, '')
            self.assertEqual(record.raw_description, 'Add values.')



    def test_compile_preserves_raw_api_definition_string_without_inventing_types(self):
        """Input: TestCase. Output: None. Preserve actual API syntax separately from typed definitions."""
        syntax = "add(x, y, filter = false), x + y"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            capture = root / "raw" / "platform" / "data_fields" / "2026-07-29" / "operators.json"
            capture.parent.mkdir(parents=True)
            for version in (None, 2):
                row = dict(name="add", category="Arithmetic", description="Add values", definition=syntax,
                           scope=["REGULAR"], level="ALL")
                if version is not None:
                    row["semantic_version"] = version
                capture.write_text(json.dumps(dict(generated_at="2026-07-29T00:00:00Z", operators=[row])), encoding="utf-8")
                try:
                    compile_operator_semantics(root, "2026-10-13T00:00:00Z")
                except ValueError as exc:
                    self.fail(f"raw API definition strings must remain compatible: {exc}")
                record = next(r for r in load_operator_semantics(root / "machine" / "operator_ledger.jsonl") if r.operator == "add")
                self.assertEqual(getattr(record, "raw_definition", None), syntax)
                self.assertIsNone(record.definition)
                self.assertEqual(record.compatible_field_types, [])

    def test_compile_backfills_legacy_ledger_without_replacing_reviewed_content(self):
        """Input: TestCase. Output: None. Merge captured v2 fields into a real legacy ledger."""
        from tests.test_semantic_contracts import evidence
        definition = dict(description="Normalize cross-sectional values", input_types=["MATRIX"], output_type="MATRIX",
            parameters=[dict(name="x", type="MATRIX", required=True)], evidence_refs=[evidence("documented")])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "machine" / "operator_ledger.jsonl"
            output.parent.mkdir()
            legacy = dict(operator="rank", family="curated", workflow_uses=["reviewed use"],
                source_paths=["raw/community/advisor_notes/rank.md"], semantic_version=1,
                semantic_status="legacy/unreviewed")
            output.write_text(json.dumps(legacy) + "\n", encoding="utf-8")
            capture = root / "raw" / "platform" / "data_fields" / "2026-10-13" / "operators.json"
            capture.parent.mkdir(parents=True)
            capture.write_text(json.dumps(dict(operators=[dict(name="rank", semantic_version=2, definition=definition)])), encoding="utf-8")
            for _ in range(2):
                compile_operator_semantics(root, "2026-10-13T00:00:00Z")
                row = next(json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()
                           if json.loads(line)["operator"] == "rank")
                self.assertEqual(row.get("definition"), definition)
                self.assertEqual(row["semantic_version"], 2)
                for key in legacy:
                    if key != "semantic_version":
                        self.assertEqual(row[key], legacy[key])
            row["definition"] = dict(definition, description="Reviewed definition takes precedence")
            output.write_text(json.dumps(row) + "\n", encoding="utf-8")
            compile_operator_semantics(root, "2026-10-13T00:00:00Z")
            record = next(r for r in load_operator_semantics(output) if r.operator == "rank")
            self.assertEqual(record.definition["description"], "Reviewed definition takes precedence")

    def test_compile_rejects_unknown_v2_canonical_fields_but_accepts_platform_shape(self):
        """Input: TestCase. Output: None. Validate canonical v2 before lossy conversion."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            capture = root / "raw" / "platform" / "data_fields" / "2026-10-13" / "operators.json"
            capture.parent.mkdir(parents=True)
            row = dict(name="rank", category="Cross Sectional", description="Rank values",
                type="REGULAR", scope=["REGULAR", "SELECTION"], level="ALL", documentation="/operators/rank",
                semantic_version=2, evidence_refz=[])
            capture.write_text(json.dumps(dict(operators=[row])), encoding="utf-8")
            with self.assertRaises(ValueError):
                compile_operator_semantics(root, "2026-10-13T00:00:00Z")
            del row["evidence_refz"]
            capture.write_text(json.dumps(dict(operators=[row])), encoding="utf-8")
            compile_operator_semantics(root, "2026-10-13T00:00:00Z")
            row["future_platform_metadata"] = {"opaque": True}
            del row["semantic_version"]
            capture.write_text(json.dumps(dict(operators=[row])), encoding="utf-8")
            compile_operator_semantics(root, "2026-10-13T00:00:00Z")

    def test_explicit_definition_survives_canonical_compile_and_reviewed_merge(self):
        """Input: TestCase. Output: None. Verify explicit type contracts survive actual repeated compilation."""
        from tests.test_semantic_contracts import evidence
        from wqb.operator_semantics import operator_semantic_record_to_dict
        definition = dict(description="Reduce a vector to a scalar per asset", input_types=["VECTOR"],
            output_type="MATRIX", parameters=[dict(name="x", type="VECTOR", required=True),
                dict(name="limit", type="INTEGER", required=False, default=3)], evidence_refs=[evidence("documented")])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            capture = root / "raw" / "platform" / "data_fields" / "2026-10-13" / "operators.json"
            capture.parent.mkdir(parents=True)
            capture.write_text(json.dumps(dict(operators=[dict(name="custom_reduce", definition=definition),
                dict(name="rank", definition=definition)])), encoding="utf-8")
            compile_operator_semantics(root, "2026-10-13T00:00:00Z")
            output = root / "machine" / "operator_ledger.jsonl"
            record = next(r for r in load_operator_semantics(output) if r.operator == "custom_reduce")
            self.assertEqual(operator_semantic_record_to_dict(record).get("definition"), definition)
            seeded = next(r for r in load_operator_semantics(output) if r.operator == "rank")
            self.assertEqual(operator_semantic_record_to_dict(seeded).get("definition"), definition)
            compile_operator_semantics(root, "2026-10-13T01:00:00Z")
            record = next(r for r in load_operator_semantics(output) if r.operator == "custom_reduce")
            self.assertEqual(operator_semantic_record_to_dict(record).get("definition"), definition)

    def test_compile_roundtrips_new_semantics_without_seed_replacement(self):
        """Input: TestCase. Output: None. Preserve all reviewed semantics through the compile merge."""
        from tests.test_semantic_contracts import evidence, semantic_fields
        from wqb.operator_semantics import operator_semantic_record_to_dict
        row = dict(operator="rank", family="reviewed", source_paths=["raw/platform/operators.md"],
                   **semantic_fields())
        row["conditional_uses"] = [dict(conditions="Comparable values", purpose="Normalize scale",
            failure_risks=["Direction lost"], evidence_refs=[evidence()])]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "machine" / "operator_ledger.jsonl"
            path.parent.mkdir()
            path.write_text(json.dumps(row) + "\n", encoding="utf-8")
            for _ in range(2):
                compile_operator_semantics(root, "2026-10-13T00:00:00Z")
                record = next(r for r in load_operator_semantics(path) if r.operator == "rank")
                actual = operator_semantic_record_to_dict(record)
                for key in semantic_fields() | {"conditional_uses": []}:
                    self.assertEqual(actual.get(key), row[key], key)
                self.assertEqual(record.family, "reviewed")

    def test_new_operator_fields_reject_malformed_json(self):
        """Input: TestCase. Output: None. Reject malformed optional operator evidence."""
        with self.assertRaises(ValueError):
            operator_semantic_record_from_dict(dict(operator="rank", evidence_refs="not-a-list"))

    def test_compile_preserves_curated_records_and_adds_missing_canonical_operators(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "knowledge"
            output = root / "machine" / "operator_ledger.jsonl"
            output.parent.mkdir(parents=True)
            curated = OperatorSemanticRecord(
                operator="rank",
                family="reviewed_family",
                workflow_uses=["reviewed_use"],
                compatible_field_types=["MATRIX"],
                template_tags=["reviewed"],
                risk_tags=[],
                repair_levers=[],
                source_paths=["raw/community/advisor_notes/rank.md"],
            )
            write_operator_semantics_jsonl(output, [curated])
            capture = root / "raw" / "platform" / "data_fields" / "2026-07-22"
            capture.mkdir(parents=True)
            (capture / "operators.json").write_text(
                '{"generated_at":"2026-07-22T00:00:00Z","operators":[{"name":"rank"},{"name":"group_rank"}]}',
                encoding="utf-8",
            )

            summary = compile_operator_semantics(root, generated_at="2026-07-22T01:00:00Z")
            records = {record.operator: record for record in load_operator_semantics(output)}

        self.assertEqual(summary["record_count"], len(records))
        self.assertEqual(records["rank"].family, "reviewed_family")
        self.assertIn("group_rank", records)

    def test_compile_default_operator_sources_do_not_publish_legacy_wiki_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "knowledge"

            summary = compile_operator_semantics(root, generated_at="2026-07-22T01:00:00Z")
            rows = [
                json.loads(line)
                for line in (root / "machine" / "operator_ledger.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            preview = Path(summary["markdown_path"]).read_text(encoding="utf-8")

        for row in rows:
            self.assertTrue(row["source_paths"])
            self.assertFalse(
                any(str(path).startswith("wiki/20_semantics") for path in row["source_paths"]),
                row,
            )
        self.assertNotIn("wiki/20_semantics", preview)

    def test_compile_normalizes_reviewed_legacy_operator_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "knowledge"
            output = root / "machine" / "operator_ledger.jsonl"
            legacy_reviewed = OperatorSemanticRecord(
                operator="group_neutralize",
                family="reviewed_neutralization",
                workflow_uses=["reviewed_bias_control"],
                compatible_field_types=["MATRIX"],
                template_tags=["reviewed"],
                risk_tags=["over_neutralization"],
                repair_levers=["neutralization_subindustry"],
                source_paths=["wiki/20_semantics/operator_catalog_official.md"],
            )
            write_operator_semantics_jsonl(output, [legacy_reviewed])

            summary = compile_operator_semantics(root, generated_at="2026-07-22T01:00:00Z")
            records = {record.operator: record for record in load_operator_semantics(output)}
            preview = Path(summary["markdown_path"]).read_text(encoding="utf-8")

        self.assertEqual(records["group_neutralize"].family, "reviewed_neutralization")
        self.assertEqual(records["group_neutralize"].workflow_uses, ["reviewed_bias_control"])
        self.assertEqual(records["group_neutralize"].source_paths, ["docs/knowledge/operator_data_semantics.md"])
        self.assertNotIn("wiki/20_semantics", preview)

    def test_compile_normalizes_absolute_reviewed_legacy_operator_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "knowledge"
            output = root / "machine" / "operator_ledger.jsonl"
            legacy_path = root / "wiki" / "20_semantics" / "operator_catalog_official.md"
            legacy_reviewed = OperatorSemanticRecord(
                operator="winsorize",
                family="reviewed_outlier_control",
                workflow_uses=["cap_outliers"],
                compatible_field_types=["MATRIX"],
                template_tags=["reviewed"],
                risk_tags=[],
                repair_levers=["adjust_std"],
                source_paths=[str(legacy_path)],
            )
            write_operator_semantics_jsonl(output, [legacy_reviewed])

            compile_operator_semantics(root, generated_at="2026-07-22T01:00:00Z")
            records = {record.operator: record for record in load_operator_semantics(output)}

        self.assertEqual(records["winsorize"].family, "reviewed_outlier_control")
        self.assertEqual(records["winsorize"].source_paths, ["docs/knowledge/operator_data_semantics.md"])

    def test_compile_preserves_non_legacy_archive_source_when_normalizing_mixed_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "knowledge"
            output = root / "machine" / "operator_ledger.jsonl"
            legacy_path = root / "wiki" / "20_semantics" / "operator_catalog_official.md"
            archive_path = "docs/archive/wiki/20_semantics/operator_notes.md"
            mixed_reviewed = OperatorSemanticRecord(
                operator="zscore",
                family="reviewed_standardizer",
                workflow_uses=["standardize_signal"],
                compatible_field_types=["MATRIX"],
                template_tags=["reviewed"],
                risk_tags=[],
                repair_levers=["winsorize_first"],
                source_paths=[str(legacy_path), archive_path],
            )
            write_operator_semantics_jsonl(output, [mixed_reviewed])

            compile_operator_semantics(root, generated_at="2026-07-22T01:00:00Z")
            records = {record.operator: record for record in load_operator_semantics(output)}

        self.assertEqual(
            records["zscore"].source_paths,
            [archive_path, "docs/knowledge/operator_data_semantics.md"],
        )

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
                "source_paths": ["docs/knowledge/operator_data_semantics.md"],
            }
        )

        self.assertEqual(record.operator, "group_neutralize")
        self.assertIn("reduce_correlation", record.workflow_uses)
        self.assertGreater(score_operator_for_template(record, "MATRIX", ["repair"]), 0.0)
        self.assertLess(
            score_operator_for_template(record, "VECTOR", ["repair"]),
            score_operator_for_template(record, "MATRIX", ["repair"]),
        )

    def test_operator_semantic_record_normalizes_none_and_scalar_list_fields(self):
        record = operator_semantic_record_from_dict(
            {
                "operator": "rank",
                "family": "cross_sectional_normalizer",
                "workflow_uses": None,
                "compatible_field_types": "matrix",
                "template_tags": "cross_sectional",
                "risk_tags": None,
                "repair_levers": "group_rank",
                "source_paths": "docs/knowledge/operator_data_semantics.md",
            }
        )

        self.assertEqual(record.workflow_uses, [])
        self.assertEqual(record.compatible_field_types, ["MATRIX"])
        self.assertEqual(record.template_tags, ["cross_sectional"])
        self.assertEqual(record.risk_tags, [])
        self.assertEqual(record.repair_levers, ["group_rank"])
        self.assertEqual(record.source_paths, ["docs/knowledge/operator_data_semantics.md"])

    def test_expression_operator_provenance_reads_operator_ledger(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "knowledge"
            write_operator_semantics_jsonl(
                root / "machine" / "operator_ledger.jsonl",
                [
                    OperatorSemanticRecord(
                        operator="rank",
                        family="cross_sectional_normalizer",
                        workflow_uses=["normalize_cross_section"],
                        compatible_field_types=["MATRIX"],
                        template_tags=["cross_sectional_normalizer"],
                        risk_tags=["crowded_when_common"],
                        repair_levers=["group_rank"],
                        source_paths=["raw/platform/learn/operators.md"],
                    ),
                    OperatorSemanticRecord(
                        operator="ts_delta",
                        family="time_series_change",
                        workflow_uses=["capture_recent_change"],
                        compatible_field_types=["MATRIX"],
                        template_tags=["time_series_surprise"],
                        risk_tags=["turnover_inflation"],
                        repair_levers=["increase_window"],
                        source_paths=["raw/platform/learn/operators.md"],
                    ),
                    OperatorSemanticRecord(
                        operator="vec_avg",
                        family="vector_to_matrix",
                        workflow_uses=["summarize_vector_values"],
                        compatible_field_types=["VECTOR"],
                        template_tags=["vector_to_matrix"],
                        risk_tags=["invalid_raw_vector_use"],
                        repair_levers=["replace_vec_count_with_vec_avg"],
                        source_paths=["raw/platform/learn/operators.md"],
                    ),
                ],
            )

            operators = extract_expression_operators("rank(ts_delta(vec_avg(buzz_trend_metric_11), 5))")
            provenance = expression_operator_provenance(
                "rank(ts_delta(vec_avg(buzz_trend_metric_11), 5))",
                root,
            )

        self.assertEqual(operators, ["rank", "ts_delta", "vec_avg"])
        self.assertEqual([row["operator"] for row in provenance], ["rank", "ts_delta", "vec_avg"])
        self.assertEqual(provenance[0]["source"], "knowledge_operator_ledger")
        self.assertEqual(provenance[1]["family"], "time_series_change")
        self.assertIn("raw/platform/learn/operators.md", provenance[2]["source_paths"])

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
                source_paths=["docs/knowledge/operator_data_semantics.md"],
            )

            write_operator_semantics_jsonl(jsonl, [record])
            write_operator_semantics_markdown(md, [record], "2026-07-22T00:00:00+00:00")
            loaded = load_operator_semantics(jsonl)
            markdown = md.read_text(encoding="utf-8")

        self.assertEqual(loaded[0].operator, "vec_avg")
        self.assertIn("vector_to_matrix", markdown)
        self.assertIn("summarize_vector_values", markdown)
        self.assertIn("Sources", markdown)
        self.assertIn("docs/knowledge/operator_data_semantics.md", markdown)


if __name__ == "__main__":
    unittest.main()
