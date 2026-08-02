import tempfile
import unittest
from pathlib import Path

from wqb.interaction_memory import append_interaction_note, compile_interaction_lessons, load_interaction_notes
from wqb.knowledge_contracts import parse_markdown_front_matter


class InteractionMemoryTests(unittest.TestCase):
    def test_append_interaction_note_writes_raw_jsonl_and_dedupes_repeated_note(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = append_interaction_note(
                tmp,
                summary="When a workflow bug is fixed, the fix must become a rule or test.",
                category="workflow_rule",
                tags=["problem_to_workflow", "maintenance"],
                evidence_paths=["milestone.md"],
                captured_at="2026-07-30T00:00:00+00:00",
                source="codex_chat",
            )
            duplicate_path = append_interaction_note(
                tmp,
                summary="When a workflow bug is fixed, the fix must become a rule or test.",
                category="workflow_rule",
                tags=["maintenance", "problem_to_workflow"],
                evidence_paths=["todo.md"],
                captured_at="2026-07-31T00:00:00+00:00",
            )

            text = path.read_text(encoding="utf-8")
            note_count = len(load_interaction_notes(tmp))

        self.assertTrue(path.as_posix().endswith("raw/community/user_messages/2026-07-30/interaction_notes.jsonl"))
        self.assertTrue(duplicate_path.as_posix().endswith("raw/community/user_messages/2026-07-31/interaction_notes.jsonl"))
        self.assertIn("problem_to_workflow", text)
        self.assertEqual(note_count, 1)

    def test_compile_interaction_lessons_uses_concrete_raw_note_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            append_interaction_note(
                tmp,
                summary="Console must show what is running so the user does not ask Codex for status.",
                category="engineering_lesson",
                tags=["console", "delivery_gate"],
                evidence_paths=["runs/console_jobs/job/summary.md"],
                captured_at="2026-07-30T00:00:00+00:00",
            )

            summary = compile_interaction_lessons(tmp, "2026-07-30T00:00:00+00:00")
            lesson_text = (Path(tmp) / "wiki" / "50_engineering_lessons.md").read_text(encoding="utf-8")
            metadata, _ = parse_markdown_front_matter(lesson_text)

        self.assertEqual(summary["lesson_count"], 1)
        self.assertIn("Console must show what is running", lesson_text)
        self.assertEqual(metadata["compiled_from"], ["raw/community/user_messages/2026-07-30/interaction_notes.jsonl"])


if __name__ == "__main__":
    unittest.main()
