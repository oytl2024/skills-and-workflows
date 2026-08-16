import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import capture_learn_material as capture
from wqb.knowledge_contracts import parse_markdown_front_matter


def _sample_capture() -> dict[str, object]:
    """Input: none. Output: dict. Build a small non-live Learn capture fixture."""
    return {
        "generated_at": "2026-08-09T00:00:00+00:00",
        "excluded": ["courses"],
        "operators": [
            {
                "name": "rank",
                "category": "Cross Sectional",
                "definition": "rank(x)",
                "description": "Rank a signal.",
            }
        ],
        "documentation_pages": [
            {
                "id": "consultant-submission-tests",
                "title": "Consultant Submission Tests",
                "category": "Documentation",
                "content": "Sharpe, fitness, self correlation, and production correlation checks.",
            }
        ],
        "documentation_errors": [],
        "search_results": {"operators": {"tutorialPage": {"results": []}}},
        "faqs": [{"question": "What are checks?", "answer": "Submission gates."}],
        "videos": [{"title": "Operators"}],
        "recommended_readings": [{"title": "Research workflow"}],
    }


def _sample_manifest(capture_payload: dict[str, object]) -> dict[str, object]:
    """Input: capture payload. Output: manifest dict. Build counts for raw Learn writers."""
    return {
        "generated_at": capture_payload["generated_at"],
        "excluded": capture_payload["excluded"],
        "counts": {
            key: len(value)
            for key, value in capture_payload.items()
            if isinstance(value, list)
        },
        "search_query_count": 1,
    }


class CaptureLearnMaterialTests(unittest.TestCase):
    def _patched_roots(self, root: Path):
        """Input: temp root. Output: patch context manager. Route capture outputs to temp vault."""
        original_root = capture.KNOWLEDGE_ROOT
        learn_relative = capture.WIKI_LEARN_PAGE.relative_to(original_root)
        operator_relative = capture.WIKI_OPERATOR_PAGE.relative_to(original_root)
        return (
            patch.object(capture, "KNOWLEDGE_ROOT", root),
            patch.object(capture, "RAW_LEARN_ROOT", root / "raw" / "platform" / "learn"),
            patch.object(capture, "JSON_CACHE_ROOT", root / "machine" / "cache" / "learn"),
            patch.object(capture, "WIKI_LEARN_PAGE", root / learn_relative),
            patch.object(capture, "WIKI_OPERATOR_PAGE", root / operator_relative),
        )

    def test_learn_capture_preview_paths_avoid_legacy_wiki_directories(self):
        root = capture.KNOWLEDGE_ROOT

        self.assertEqual(
            capture.WIKI_LEARN_PAGE.relative_to(root).as_posix(),
            "machine/previews/learn_material_index.md",
        )
        self.assertEqual(
            capture.WIKI_OPERATOR_PAGE.relative_to(root).as_posix(),
            "machine/previews/operator_catalog_official.md",
        )

    def test_raw_learn_markdown_has_contract_metadata_and_source_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "knowledge"
            capture_payload = _sample_capture()
            manifest = _sample_manifest(capture_payload)
            contexts = self._patched_roots(root)
            with contexts[0], contexts[1], contexts[2], contexts[3], contexts[4]:
                paths = capture.write_raw_learn_markdown(capture_payload, manifest)

            index_path = root / "raw" / "source_index.md"
            machine_index = root / "machine" / "source_index.jsonl"
            first_metadata, _ = parse_markdown_front_matter(paths[0].read_text(encoding="utf-8"))
            indexed_rows = [
                json.loads(line)
                for line in machine_index.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            combined_text = "\n".join(path.read_text(encoding="utf-8") for path in paths)
            index_exists = index_path.exists()

        self.assertEqual(first_metadata["source_family"], "raw/platform/learn")
        self.assertEqual(first_metadata["source_path"], "raw/platform/learn/2026-08-09/index.md")
        self.assertEqual(first_metadata["record_count"], 1)
        self.assertTrue(first_metadata["update_check"])
        self.assertTrue(index_exists)
        self.assertEqual({row["path"] for row in indexed_rows}, {path.relative_to(root).as_posix() for path in paths})
        self.assertNotIn("wiki/10_foundations", combined_text)
        self.assertNotIn("wiki/20_semantics", combined_text)
        self.assertNotIn("wiki/30_templates", combined_text)

    def test_learn_capture_preview_writers_do_not_create_obsolete_wiki_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "knowledge"
            capture_payload = _sample_capture()
            contexts = self._patched_roots(root)
            with contexts[0], contexts[1], contexts[2], contexts[3], contexts[4]:
                capture.write_learn_wiki(capture_payload)
                capture.write_operator_wiki(capture_payload["operators"], "2026-08-09T00:00:00+00:00")

            learn_preview = root / "machine" / "previews" / "learn_material_index.md"
            operator_preview = root / "machine" / "previews" / "operator_catalog_official.md"
            learn_preview_exists = learn_preview.exists()
            operator_preview_exists = operator_preview.exists()
            old_learn_exists = (root / "wiki" / "10_foundations").exists()
            old_operator_exists = (root / "wiki" / "20_semantics").exists()

        self.assertTrue(learn_preview_exists)
        self.assertTrue(operator_preview_exists)
        self.assertFalse(old_learn_exists)
        self.assertFalse(old_operator_exists)


if __name__ == "__main__":
    unittest.main()
