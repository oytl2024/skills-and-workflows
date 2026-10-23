"""Offline whole-path acceptance through source recovery, Repair and approval."""

import json
import tempfile
import unittest
from pathlib import Path

from tests import test_orchestrator
from tests.test_source_bridge import write_source_metadata
from tests.test_workflow_stage_outcomes import checked_alpha
from wqb.orchestrator import WorkflowOrchestrator
from wqb.workflow_auto_continue import auto_continue_workflow


NOW = "2026-10-09T00:00:00+00:00"


def append_jsonl(path: Path, rows: list[dict]) -> None:
    """Input: path and JSON rows. Output: none. Append durable fake-platform evidence."""
    with path.open("a", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row) + "\n")


class WholeWorkflowAcceptanceTests(unittest.TestCase):
    def test_weak_round_rotates_then_discovery_repair_and_restart_reach_approval(self):
        """Input: offline two-round mission. Output: assertions. Exercise the controller, real stage adapters and durable lineage."""
        from tests.test_research_rounds import round_fixture, write_json
        from tests.test_workflow_stage_outcomes import write_rows
        with tempfile.TemporaryDirectory() as tmp:
            engine, active = round_fixture(Path(tmp))
            engine.continue_once(NOW)
            self.assertTrue((active / 'rounds/round-0001/all_alphas.jsonl').exists())
            schedule = json.loads((active / 'stages/schedule/research_schedule.json').read_text())
            selected = schedule['template_matches'][0]
            source = engine.paths.run_root / 'round-two-source'
            write_source_metadata(source, field_id=selected['field_id'], dataset_id=selected['dataset_id'])
            meta_path = source / 'run_meta.jsonl'
            meta = json.loads(meta_path.read_text())
            meta.update(research_round_id='round-0002', template_provenance=selected)
            meta_path.write_text(json.dumps(meta) + '\n')
            scout = [checked_alpha('repairable' if i == 0 else 'weak',
                     alpha_id=f'scout-{i}', expression_hash=f'scout-hash-{i}') for i in range(30)]
            write_rows(source, scout)
            append_jsonl(source / 'planned_candidates.jsonl', [
                {'expression_hash': row['expression_hash'], 'expression': row['expression']} for row in scout])
            append_jsonl(source / 'simulation_events.jsonl', [
                {'event': 'CHECKED', 'expression_hash': row['expression_hash']} for row in scout])
            write_json(active / 'runtime_status.json', {'simulation_attempts': 60})
            calls = []
            def discovery(run, parent):
                """Input: measured seed. Output:30 checked children. No platform calls."""
                calls.append('discovery')
                return [{**checked_alpha('repairable' if i == 0 else 'weak',
                    alpha_id=f'discovery-{i}', expression_hash=f'discovery-hash-{i}'),
                    'parent_alpha_id': parent['alpha_id'], 'parent_expression_hash': parent['expression_hash']}
                    for i in range(30)]
            def repair(run, parent, actions, maximum):
                """Input: bounded Repair context. Output: one fully checked child. No submission authorization."""
                calls.append('repair')
                self.assertLessEqual(maximum, 8)
                return [checked_alpha('qualified', alpha_id='passed-' + parent['alpha_id'],
                    expression_hash='passed-' + parent['expression_hash'], parent_alpha_id=parent['alpha_id'])]
            result = {}
            for _ in range(25):
                result = auto_continue_workflow(engine.paths, {}, NOW, enable_live_api=True,
                    discovery_executor=discovery, repair_executor=repair)
                if result.get('status') in {'waiting_for_user', 'failed'}:
                    break
            self.assertEqual(result.get('status'), 'waiting_for_user', result)
            self.assertEqual(calls.count('discovery'), 1)
            self.assertIn('repair', calls)
            before = list(calls)
            replay = auto_continue_workflow(engine.paths, {}, NOW, enable_live_api=True,
                discovery_executor=discovery, repair_executor=repair)
            self.assertEqual(replay['status'], 'waiting_for_user')
            self.assertEqual(calls, before)
            self.assertFalse((active / 'submission_receipt.json').exists())

    def test_30_scout_plans_cooldown_restart_repair_and_human_boundary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = test_orchestrator.WorkflowOrchestratorTests()
            paths = fixture.paths(root)
            engine = WorkflowOrchestrator(paths)
            started = engine.start("Power Pool", "option-1", NOW)
            active = Path(started["run_dir"])
            for _ in range(3):
                engine.continue_once(NOW)
            self.assertEqual(engine.status()["current_stage"], "scout_seed")
            self.assertEqual(engine.status()["status"], "paused")

            source = paths.run_root / "fake-source"
            write_source_metadata(source)
            planned = [
                {"expression_hash": f"h{i}", "expression": f"rank(cash_field)+{i}"}
                for i in range(30)
            ]
            append_jsonl(source / "planned_candidates.jsonl", planned)
            events = []
            for i in range(4):
                events.append({"event": "SUBMITTED", "expression_hash": f"h{i}", "progress_url": f"/simulations/{i}"})
                if i < 3:
                    events.append({"event": "CHECKED", "expression_hash": f"h{i}", "progress_url": f"/simulations/{i}"})
            append_jsonl(source / "simulation_events.jsonl", events)
            append_jsonl(source / "all_alphas.jsonl", [
                checked_alpha("repairable", alpha_id=f"a{i}", expression_hash=f"h{i}")
                for i in range(3)
            ])
            (source / "rate_limit_state.json").write_text(json.dumps({
                "status": "cooldown", "retry_at": "2026-10-09T00:00:10+00:00", "consecutive_429_count": 1,
            }), encoding="utf-8")

            calls = []
            blocked = auto_continue_workflow(paths, {}, NOW, enable_live_api=True,
                                             complete_in_flight_runner=lambda *_: calls.append("polled"))
            self.assertEqual(blocked["next_action"], "rate-limit-wait")
            self.assertEqual(calls, [])
            self.assertEqual(len((source / "planned_candidates.jsonl").read_text().splitlines()), 30)

            def finish_in_flight(run_dir: str) -> dict:
                """Input: source run dir. Output: fake recovery receipt. Finish only recorded progress URL."""
                self.assertEqual(Path(run_dir), source)
                calls.append("polled")
                append_jsonl(source / "simulation_events.jsonl", [
                    {"event": "CHECKED", "expression_hash": "h3", "progress_url": "/simulations/3"}
                ])
                append_jsonl(source / "all_alphas.jsonl", [
                    checked_alpha("repairable", alpha_id="a3", expression_hash="h3")
                ])
                return {"status": "completed", "recovered": 1}

            recovered = auto_continue_workflow(paths, {}, "2026-10-09T00:00:11+00:00", enable_live_api=True,
                                               complete_in_flight_runner=finish_in_flight)
            self.assertEqual(recovered["source_bridge"]["action"], "complete_in_flight")
            self.assertEqual(calls, ["polled"])
            imported = auto_continue_workflow(paths, {}, "2026-10-09T00:00:12+00:00")
            self.assertEqual(imported["source_bridge"]["action"], "import_research_outcome")
            self.assertTrue((active / "stages" / "scout_seed" / "scout_seed_import.json").is_file())

            def repair(run_dir: Path, parent: dict, actions: list[dict], maximum: int) -> list[dict]:
                """Input: repair context. Output: one checked hard pass. Fake platform repair only."""
                calls.append("repair")
                self.assertEqual(run_dir, active)
                self.assertLessEqual(maximum, 8)
                return [checked_alpha("qualified", alpha_id=f"repaired-{parent['alpha_id']}",
                                      expression_hash=f"h-repaired-{parent['alpha_id']}",
                                      parent_alpha_id=parent["alpha_id"])]

            result = imported
            for _ in range(20):
                result = auto_continue_workflow(paths, {}, NOW, enable_live_api=True, repair_executor=repair)
                if result.get("status") in {"waiting_for_user", "failed"}:
                    break
            self.assertEqual(result["status"], "waiting_for_user", result)
            self.assertIn("repair", calls)
            restarted = WorkflowOrchestrator(paths)
            self.assertEqual(restarted.status()["status"], "waiting_for_user")
            calls_before_restart = list(calls)
            replay = auto_continue_workflow(paths, {}, NOW, enable_live_api=True,
                                            complete_in_flight_runner=finish_in_flight,
                                            repair_executor=repair)
            self.assertEqual(replay["status"], "waiting_for_user")
            self.assertEqual(calls, calls_before_restart)
            self.assertFalse((active / "approved_candidates.jsonl").exists())
            self.assertFalse((active / "submission_receipt.json").exists())
