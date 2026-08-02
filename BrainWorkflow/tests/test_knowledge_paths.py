from pathlib import Path
import tempfile
import unittest

from wqb.knowledge_paths import (
    ENGINEERING_LESSONS_WIKI_PATH,
    MACHINE_RESOURCE_FILES,
    RAW_INTERACTION_ROOT,
    active_top_level_names,
    engineering_lessons_wiki_path,
    ensure_knowledge_dirs,
    existing_machine_resource_path,
    interaction_note_file_path,
    knowledge_paths,
    machine_resource_path,
    relative_to_knowledge_root,
)


class KnowledgePathsTests(unittest.TestCase):
    def test_interaction_memory_paths_use_centralized_contracts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            self.assertEqual(RAW_INTERACTION_ROOT, Path("raw") / "community" / "user_messages")
            self.assertEqual(ENGINEERING_LESSONS_WIKI_PATH, Path("wiki") / "50_engineering_lessons.md")
            self.assertEqual(
                interaction_note_file_path(root, "2026-07-30T00:00:00+00:00"),
                root / "raw" / "community" / "user_messages" / "2026-07-30" / "interaction_notes.jsonl",
            )
            self.assertEqual(engineering_lessons_wiki_path(root), root / "wiki" / "50_engineering_lessons.md")

    def test_ensure_knowledge_dirs_creates_three_active_layers(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = ensure_knowledge_dirs(tmp)

            self.assertTrue(paths.raw.is_dir())
            self.assertTrue(paths.machine.is_dir())
            self.assertTrue(paths.wiki.is_dir())
            self.assertEqual(active_top_level_names(tmp), {"raw", "machine", "wiki"})

    def test_active_top_level_names_includes_unexpected_directories_for_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            ensure_knowledge_dirs(tmp)
            Path(tmp, "legacy").mkdir()

            self.assertEqual(active_top_level_names(tmp), {"raw", "machine", "wiki", "legacy"})

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
