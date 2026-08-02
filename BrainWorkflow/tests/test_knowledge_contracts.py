import json
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

    def test_parse_markdown_front_matter_preserves_body_without_trailing_newline(self):
        text = "---\nsource_type: platform_api\n---\n# Body"

        _, body = parse_markdown_front_matter(text)

        self.assertEqual(body, "# Body")

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
        self.assertIn("missing stale_after_days", issues)

    def test_canonical_source_family_identifies_legacy_and_canonical_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "knowledge"

            canonical = canonical_source_family(root / "raw" / "platform" / "learn" / "2026-07-22" / "index.md", root)
            legacy = canonical_source_family(root / "raw" / "learn" / "old.md", root)
            wiki = canonical_source_family(root / "wiki" / "20_semantics" / "operators.md", root)
            machine = canonical_source_family(root / "machine" / "data_ledger.jsonl", root)
            unknown_machine = canonical_source_family(root / "machine" / "untrusted.jsonl", root)

        self.assertEqual(canonical, "raw/platform/learn")
        self.assertEqual(legacy, "legacy")
        self.assertEqual(wiki, "wiki/20_semantics")
        self.assertEqual(machine, "machine/data_ledger.jsonl")
        self.assertEqual(unknown_machine, "external")

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
            machine_rows = [
                json.loads(line)
                for line in (root / "machine" / "source_index.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]

        self.assertIn("raw/platform/data_fields/2026-07-22/index.md", text)
        self.assertIn("compare field ids and exact scopes", text)
        self.assertIn("wiki/20_semantics/data_ledger.md", text)
        self.assertEqual(machine_rows, [
            {
                "path": "raw/platform/data_fields/2026-07-22/index.md",
                "source_family": "data_fields",
                "source_type": "platform_api",
                "contents": "platform data-field capture manifest",
                "update_check": "compare field ids and exact scopes",
                "compiled_targets": ["wiki/20_semantics/data_ledger.md"],
            }
        ])


if __name__ == "__main__":
    unittest.main()
