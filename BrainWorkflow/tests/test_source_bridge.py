import csv
import json
import tempfile
import unittest
from pathlib import Path

from wqb.source_bridge import (
    active_run_needs_scout_seed_candidates,
    inspect_scout_seed_source_bridge,
)


def write_candidates(path: Path) -> None:
    """Input: candidate CSV path. Output: none. Write one valid source candidate row."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=["alpha_id", "expression_hash"])
        writer.writeheader()
        writer.writerow({"alpha_id": "a1", "expression_hash": "h1"})


class SourceBridgeTests(unittest.TestCase):
    def test_active_run_needs_candidates_only_for_scout_seed_pause(self):
        summary = {
            "active": True,
            "status": "paused",
            "current_stage": "scout_seed",
            "pause_reason": "missing candidates.csv",
        }

        self.assertTrue(active_run_needs_scout_seed_candidates(summary))
        self.assertFalse(
            active_run_needs_scout_seed_candidates({**summary, "current_stage": "repair"})
        )

    def test_bridge_imports_existing_valid_source_candidate_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            runs = Path(tmp)
            active = runs / "active"
            source = runs / "source1"
            active.mkdir()
            write_candidates(source / "candidates.csv")

            decision = inspect_scout_seed_source_bridge(
                runs, active, "2026-08-12T00:00:00+00:00"
            )

        self.assertEqual(decision.action, "import_existing")
        self.assertEqual(decision.source_run_id, "source1")

    def test_bridge_waits_when_cooldown_active(self):
        with tempfile.TemporaryDirectory() as tmp:
            runs = Path(tmp)
            active = runs / "active"
            source = runs / "source1"
            active.mkdir()
            source.mkdir()
            (source / "rate_limit_state.json").write_text(
                json.dumps(
                    {"status": "cooldown", "retry_at": "2099-01-01T00:00:00+00:00"}
                ),
                encoding="utf-8",
            )

            decision = inspect_scout_seed_source_bridge(
                runs, active, "2026-08-12T00:00:00+00:00"
            )

        self.assertEqual(decision.action, "rate_limit_wait")
        self.assertEqual(decision.source_run_id, "source1")

    def test_bridge_detects_pending_submission_after_checked_submission(self):
        with tempfile.TemporaryDirectory() as tmp:
            runs = Path(tmp)
            active = runs / "active"
            source = runs / "source1"
            active.mkdir()
            source.mkdir()
            (source / "simulation_events.jsonl").write_text(
                "\n".join(
                    json.dumps(row)
                    for row in (
                        {
                            "event": "SUBMITTED",
                            "expression_hash": "checked-hash",
                            "progress_url": "https://progress/checked",
                        },
                        {"event": "CHECKED", "expression_hash": "checked-hash"},
                        {
                            "event": "SUBMITTED",
                            "expression_hash": "pending-hash",
                            "progress_url": "https://progress/pending",
                        },
                    )
                )
                + "\n",
                encoding="utf-8",
            )

            decision = inspect_scout_seed_source_bridge(
                runs, active, "2026-08-12T00:00:00+00:00"
            )

        self.assertEqual(decision.action, "complete_in_flight")
        self.assertEqual(decision.source_run_id, "source1")

    def test_bridge_rejects_candidates_with_malformed_headers(self):
        with tempfile.TemporaryDirectory() as tmp:
            runs = Path(tmp)
            active = runs / "active"
            source = runs / "source1"
            active.mkdir()
            source.mkdir()
            (source / "candidates.csv").write_text(
                "alpha_id,not_expression_hash\na1,h1\n", encoding="utf-8"
            )

            decision = inspect_scout_seed_source_bridge(
                runs, active, "2026-08-12T00:00:00+00:00"
            )

        self.assertNotEqual(decision.action, "import_existing")
        self.assertEqual(decision.action, "maintenance_blocker")

    def test_bridge_rejects_candidates_with_empty_identities(self):
        with tempfile.TemporaryDirectory() as tmp:
            runs = Path(tmp)
            active = runs / "active"
            source = runs / "source1"
            active.mkdir()
            source.mkdir()
            (source / "candidates.csv").write_text(
                "alpha_id,expression_hash\n,\n", encoding="utf-8"
            )

            decision = inspect_scout_seed_source_bridge(
                runs, active, "2026-08-12T00:00:00+00:00"
            )

        self.assertNotEqual(decision.action, "import_existing")
        self.assertEqual(decision.action, "maintenance_blocker")

    def test_bridge_retries_planned_source_candidates(self):
        with tempfile.TemporaryDirectory() as tmp:
            runs = Path(tmp)
            active = runs / "active"
            source = runs / "source1"
            active.mkdir()
            source.mkdir()
            (source / "planned_candidates.jsonl").write_text("{}\n", encoding="utf-8")

            decision = inspect_scout_seed_source_bridge(
                runs, active, "2026-08-12T00:00:00+00:00"
            )

        self.assertEqual(decision.action, "retry_planned")
        self.assertEqual(decision.source_run_id, "source1")

    def test_bridge_reports_maintenance_blocker_without_schedule_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            runs = Path(tmp)
            active = runs / "active"
            active.mkdir()

            decision = inspect_scout_seed_source_bridge(
                runs, active, "2026-08-12T00:00:00+00:00"
            )

        self.assertEqual(decision.action, "maintenance_blocker")

    def test_bridge_builds_source_batch_metadata_from_schedule(self):
        with tempfile.TemporaryDirectory() as tmp:
            runs = Path(tmp)
            active = runs / "active"
            schedule = active / "stages" / "schedule" / "research_schedule.json"
            schedule.parent.mkdir(parents=True)
            schedule.write_text(
                json.dumps(
                    {
                        "template_matches": [
                            {
                                "field_id": "buzz_intensity_score_15",
                                "dataset_id": "analyst_buzz",
                                "template_id": "vector_event_count_surprise",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            decision = inspect_scout_seed_source_bridge(
                runs, active, "2026-08-12T00:00:00+00:00"
            )

        self.assertEqual(decision.action, "start_source_batch")
        self.assertEqual(decision.metadata["field_search"], "buzz_intensity_score_15")
        self.assertEqual(decision.metadata["exact_field_id"], "buzz_intensity_score_15")
        self.assertEqual(decision.metadata["dataset_id"], "analyst_buzz")
        self.assertEqual(decision.metadata["workflow_stage"], "scout")
        self.assertEqual(decision.metadata["max_alphas_per_round"], 30)
