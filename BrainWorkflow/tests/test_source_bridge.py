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


def write_active_metadata(
    active: Path,
    field_id: str = "cash_field",
    dataset_id: str = "fundamental3",
    region: str = "USA",
    delay: int = 1,
    universe: str = "TOP3000",
) -> None:
    """Input: active run and expected source values. Output: none. Write workflow schedule and selected scope."""
    active.mkdir(parents=True, exist_ok=True)
    (active / "run_manifest.json").write_text(
        json.dumps(
            {
                "run_id": active.name,
                "selected_scope": {
                    "instrument_type": "EQUITY",
                    "region": region,
                    "delay": delay,
                    "universe": universe,
                },
            }
        ),
        encoding="utf-8",
    )
    schedule = active / "stages" / "schedule" / "research_schedule.json"
    schedule.parent.mkdir(parents=True, exist_ok=True)
    schedule.write_text(
        json.dumps(
            {
                "template_matches": [
                    {
                        "field_id": field_id,
                        "dataset_id": dataset_id,
                        "template_id": "matrix_ts_zscore_rank",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )


def write_source_metadata(
    source: Path,
    field_id: str = "cash_field",
    dataset_id: str = "fundamental3",
    region: str = "USA",
    delay: int = 1,
    universe: str = "TOP3000",
) -> None:
    """Input: source run and provenance values. Output: none. Write source metadata used for compatibility checks."""
    source.mkdir(parents=True, exist_ok=True)
    meta = {
        "data_fields_path": (
            f"/data-fields?instrumentType=EQUITY&region={region}&delay={delay}"
            f"&universe={universe}&dataset.id={dataset_id}&search={field_id}"
        ),
        "field_search": field_id,
        "exact_field_id": field_id,
        "dataset_id": dataset_id,
        "workflow_stage": "scout",
    }
    (source / "run_meta.jsonl").write_text(json.dumps(meta) + "\n", encoding="utf-8")


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
            write_active_metadata(active)
            write_source_metadata(source)
            write_candidates(source / "candidates.csv")

            decision = inspect_scout_seed_source_bridge(
                runs, active, "2026-08-12T00:00:00+00:00"
            )

        self.assertEqual(decision.action, "import_existing")
        self.assertEqual(decision.source_run_id, "source1")

    def test_bridge_uses_field_search_when_source_exact_field_is_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            runs = Path(tmp)
            active = runs / "active"
            source = runs / "source1"
            write_active_metadata(active)
            write_source_metadata(source)
            write_candidates(source / "candidates.csv")
            metadata_path = source / "run_meta.jsonl"
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            metadata["exact_field_id"] = ""
            metadata_path.write_text(json.dumps(metadata) + "\n", encoding="utf-8")

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
            write_active_metadata(active)
            write_source_metadata(source)
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
            write_active_metadata(active)
            write_source_metadata(source)
            (source / "simulation_events.jsonl").write_text(
                "\n".join(
                    json.dumps(row)
                    for row in (
                        {
                            "event": "SUBMITTED",
                            "expression_hash": "checked-hash",
                            "progress_url": "https://progress/checked",
                        },
                        {
                            "event": "CHECKED",
                            "expression_hash": "checked-hash",
                            "progress_url": "https://progress/checked",
                        },
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

    def test_bridge_keeps_later_same_expression_submission_pending(self):
        with tempfile.TemporaryDirectory() as tmp:
            runs = Path(tmp)
            active = runs / "active"
            source = runs / "source1"
            write_active_metadata(active)
            write_source_metadata(source)
            (source / "simulation_events.jsonl").write_text(
                "\n".join(
                    json.dumps(row)
                    for row in (
                        {
                            "event": "SUBMITTED",
                            "expression_hash": "same-hash",
                            "progress_url": "https://progress/p1",
                        },
                        {
                            "event": "SUBMITTED",
                            "expression_hash": "same-hash",
                            "progress_url": "https://progress/p2",
                        },
                        {
                            "event": "CHECKED",
                            "expression_hash": "same-hash",
                            "progress_url": "https://progress/p1",
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
            write_active_metadata(active)
            write_source_metadata(source)
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
            write_active_metadata(active)
            write_source_metadata(source)
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
            write_active_metadata(active)
            write_source_metadata(source)
            (source / "planned_candidates.jsonl").write_text(
                json.dumps({"expression_hash": "h1", "expression": "rank(cash_field)"}) + "\n",
                encoding="utf-8",
            )

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

    def test_bridge_excludes_wrong_field_and_wrong_scope_source_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            runs = Path(tmp)
            active = runs / "active"
            write_active_metadata(active)
            wrong_field = runs / "wrong-field"
            wrong_scope = runs / "wrong-scope"
            write_source_metadata(wrong_field, field_id="other_field")
            write_candidates(wrong_field / "candidates.csv")
            write_source_metadata(wrong_scope, region="EUR", universe="TOP2500")
            write_candidates(wrong_scope / "candidates.csv")

            decision = inspect_scout_seed_source_bridge(
                runs, active, "2026-08-12T00:00:00+00:00"
            )

        self.assertEqual(decision.action, "start_source_batch")
        self.assertEqual(decision.source_run_id, "")

    def test_bridge_persists_first_source_binding_and_does_not_switch(self):
        with tempfile.TemporaryDirectory() as tmp:
            runs = Path(tmp)
            active = runs / "active"
            first = runs / "source1"
            newer = runs / "source2"
            write_active_metadata(active)
            write_source_metadata(first)
            write_candidates(first / "candidates.csv")

            selected = inspect_scout_seed_source_bridge(
                runs, active, "2026-08-12T00:00:00+00:00"
            )
            write_source_metadata(newer)
            write_candidates(newer / "candidates.csv")
            stable = inspect_scout_seed_source_bridge(
                runs, active, "2026-08-12T00:01:00+00:00"
            )
            binding = json.loads(
                (active / "stages" / "scout_seed" / "source_bridge_binding.json").read_text(
                    encoding="utf-8"
                )
            )
            events = (active / "workflow_events.jsonl").read_text(encoding="utf-8")

        self.assertEqual(selected.source_run_id, "source1")
        self.assertEqual(stable.source_run_id, "source1")
        self.assertEqual(binding["source_run_id"], "source1")
        self.assertIn("source_run_bound", events)

    def test_bridge_classifies_exhausted_planned_queue_as_maintenance_blocker(self):
        with tempfile.TemporaryDirectory() as tmp:
            runs = Path(tmp)
            active = runs / "active"
            source = runs / "source1"
            write_active_metadata(active)
            write_source_metadata(source)
            planned = {"expression_hash": "h1", "expression": "rank(cash_field)"}
            (source / "planned_candidates.jsonl").write_text(
                json.dumps(planned) + "\n", encoding="utf-8"
            )
            (source / "simulation_events.jsonl").write_text(
                "\n".join(
                    (
                        json.dumps({"event": "SUBMITTED", **planned, "progress_url": "/simulations/1"}),
                        json.dumps({"event": "ERROR", **planned, "progress_url": "/simulations/1"}),
                    )
                )
                + "\n",
                encoding="utf-8",
            )

            decision = inspect_scout_seed_source_bridge(
                runs, active, "2026-08-12T00:00:00+00:00"
            )

        self.assertEqual(decision.action, "maintenance_blocker")
        self.assertEqual(decision.source_run_id, "source1")
        self.assertIn("exhausted", decision.reason)

    def test_bridge_prefers_recoverable_source_over_exhausted_sibling(self):
        with tempfile.TemporaryDirectory() as tmp:
            runs = Path(tmp)
            active = runs / "active"
            recoverable = runs / "recoverable"
            exhausted = runs / "exhausted"
            write_active_metadata(active)
            write_source_metadata(recoverable)
            recoverable_planned = {
                "expression_hash": "recoverable-hash",
                "expression": "rank(cash_field)",
            }
            (recoverable / "planned_candidates.jsonl").write_text(
                json.dumps(recoverable_planned) + "\n", encoding="utf-8"
            )
            write_source_metadata(exhausted)
            exhausted_planned = {
                "expression_hash": "exhausted-hash",
                "expression": "rank(cash_field + 1)",
            }
            (exhausted / "planned_candidates.jsonl").write_text(
                json.dumps(exhausted_planned) + "\n", encoding="utf-8"
            )
            (exhausted / "simulation_events.jsonl").write_text(
                json.dumps({"event": "ERROR", **exhausted_planned}) + "\n",
                encoding="utf-8",
            )

            decision = inspect_scout_seed_source_bridge(
                runs, active, "2026-08-12T00:00:00+00:00"
            )

        self.assertEqual(decision.action, "retry_planned")
        self.assertEqual(decision.source_run_id, "recoverable")

    def test_bridge_blocks_recovery_at_consecutive_rate_limit_threshold(self):
        with tempfile.TemporaryDirectory() as tmp:
            runs = Path(tmp)
            active = runs / "active"
            source = runs / "source1"
            write_active_metadata(active)
            write_source_metadata(source)
            (source / "rate_limit_state.json").write_text(
                json.dumps(
                    {
                        "status": "cooldown",
                        "retry_at": "2099-01-01T00:00:00+00:00",
                        "consecutive_429_count": 3,
                    }
                ),
                encoding="utf-8",
            )

            decision = inspect_scout_seed_source_bridge(
                runs, active, "2026-08-12T00:00:00+00:00"
            )

        self.assertEqual(decision.action, "maintenance_blocker")
        self.assertEqual(decision.source_run_id, "source1")
        self.assertIn("rate limit", decision.reason)

    def test_bridge_builds_source_batch_metadata_from_schedule(self):
        with tempfile.TemporaryDirectory() as tmp:
            runs = Path(tmp)
            active = runs / "active"
            write_active_metadata(
                active,
                field_id="buzz_intensity_score_15",
                dataset_id="analyst_buzz",
            )

            decision = inspect_scout_seed_source_bridge(
                runs, active, "2026-08-12T00:00:00+00:00"
            )

        self.assertEqual(decision.action, "start_source_batch")
        self.assertEqual(decision.metadata["field_search"], "buzz_intensity_score_15")
        self.assertEqual(decision.metadata["exact_field_id"], "buzz_intensity_score_15")
        self.assertEqual(decision.metadata["dataset_id"], "analyst_buzz")
        self.assertEqual(decision.metadata["region"], "USA")
        self.assertEqual(decision.metadata["delay"], 1)
        self.assertEqual(decision.metadata["universe"], "TOP3000")
        self.assertEqual(decision.metadata["workflow_stage"], "scout")
        self.assertEqual(decision.metadata["max_alphas_per_round"], 30)
