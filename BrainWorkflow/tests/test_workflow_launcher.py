import json
import tempfile
import unittest
from pathlib import Path

from wqb.workflow_launcher import (
    WorkflowLaunchConfig,
    create_run_manifest,
    load_workflow_launch_config,
    workflow_run_manifest_to_dict,
    write_run_manifest,
)


class WorkflowLauncherTests(unittest.TestCase):
    def test_load_workflow_launch_config_merges_defaults_local_and_overrides(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            defaults = root / "defaults.json"
            local = root / "local.json"
            defaults.write_text(json.dumps({"knowledge_root": "knowledge", "region": "USA", "delay": 1, "batch_size": 30, "mode": "plan-only"}), encoding="utf-8")
            local.write_text(json.dumps({"region": "EUR", "universe": "TOP2500"}), encoding="utf-8")

            config = load_workflow_launch_config(defaults, local, overrides={"delay": 0, "objective": "Power Pool"})

        self.assertEqual(config.region, "EUR")
        self.assertEqual(config.delay, 0)
        self.assertEqual(config.batch_size, 30)
        self.assertEqual(config.objective, "Power Pool")
        self.assertFalse(config.live_api_enabled)
        self.assertEqual(config.submit_policy, "blocked")

    def test_create_run_manifest_uses_conservative_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            defaults = root / "defaults.json"
            defaults.write_text(json.dumps({"knowledge_root": "knowledge", "run_root": str(root / "runs"), "objective": "Power Pool", "region": "USA", "delay": 1}), encoding="utf-8")
            config = load_workflow_launch_config(defaults)

            manifest = create_run_manifest(config, generated_at="2026-07-10T00:00:00Z")
            payload = workflow_run_manifest_to_dict(manifest)

        self.assertEqual(payload["batch_size"], 30)
        self.assertEqual(payload["mode"], "plan-only")
        self.assertEqual(payload["submit_policy"], "blocked")
        self.assertFalse(payload["live_api_enabled"])
        self.assertIn("data_ledger", payload["knowledge_artifacts"])
        self.assertEqual(
            payload["knowledge_artifacts"]["benchmark_rules"],
            "machine/benchmark_rules.jsonl",
        )
        self.assertEqual(payload["knowledge_artifacts"]["data_ledger"], "machine/data_ledger.jsonl")
        self.assertEqual(payload["knowledge_artifacts"]["template_library"], "machine/template_library.jsonl")
        self.assertEqual(payload["knowledge_artifacts"]["freshness_manifest"], "machine/freshness_manifest.json")

    def test_create_run_manifest_uses_legacy_artifacts_only_when_machine_resources_are_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            knowledge_root = Path(tmp) / "knowledge"
            legacy_paths = {
                "data_ledger": knowledge_root / "wiki" / "20_semantics" / "data_ledger.jsonl",
                "template_library": knowledge_root / "wiki" / "30_templates" / "template_library.jsonl",
                "freshness_manifest": knowledge_root / "wiki" / "80_maintenance" / "freshness_manifest.json",
                "benchmark_rules": knowledge_root / "wiki" / "50_benchmarks" / "benchmark_rules.jsonl",
            }
            for path in legacy_paths.values():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("[]", encoding="utf-8")

            manifest = create_run_manifest(WorkflowLaunchConfig(knowledge_root=str(knowledge_root)))

        self.assertEqual(manifest.knowledge_artifacts, {
            name: path.relative_to(knowledge_root).as_posix()
            for name, path in legacy_paths.items()
        } | {"activity_snapshot": "raw/platform/activities/bootstrap_activity_snapshot.md"})

    def test_create_run_manifest_keeps_same_day_runs_in_separate_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            defaults = root / "defaults.json"
            defaults.write_text(json.dumps({"knowledge_root": "knowledge", "run_root": str(root / "runs"), "objective": "Power Pool"}), encoding="utf-8")
            config = load_workflow_launch_config(defaults)

            first = create_run_manifest(config, generated_at="2026-07-10T09:00:00Z")
            second = create_run_manifest(config, generated_at="2026-07-10T09:00:01Z")

        self.assertNotEqual(first.run_id, second.run_id)
        self.assertNotEqual(first.run_dir, second.run_dir)

    def test_create_run_manifest_rejects_non_boolean_live_api_enabled_from_direct_config(self):
        with self.assertRaisesRegex(ValueError, "live_api_enabled.*boolean"):
            config = WorkflowLaunchConfig(knowledge_root="knowledge", live_api_enabled="false")
            create_run_manifest(config, generated_at="2026-07-10T00:00:00Z")

    def test_create_run_manifest_avoids_collision_for_identical_generated_at(self):
        config = WorkflowLaunchConfig(knowledge_root="knowledge", objective="Power Pool")

        first = create_run_manifest(config, generated_at="2026-07-10T00:00:00Z")
        second = create_run_manifest(config, generated_at="2026-07-10T00:00:00Z")

        self.assertNotEqual(first.run_id, second.run_id)
        self.assertNotEqual(first.run_dir, second.run_dir)

    def test_load_workflow_launch_config_rejects_non_boolean_live_api_enabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            defaults = Path(tmp) / "defaults.json"
            defaults.write_text(json.dumps({"knowledge_root": "knowledge", "live_api_enabled": "false"}), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "live_api_enabled.*boolean"):
                load_workflow_launch_config(defaults)

    def test_write_run_manifest_creates_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            defaults = root / "defaults.json"
            defaults.write_text(json.dumps({"knowledge_root": "knowledge", "run_root": str(root / "runs"), "objective": "Power Pool", "region": "USA", "delay": 1}), encoding="utf-8")
            config = load_workflow_launch_config(defaults)
            manifest = create_run_manifest(config, generated_at="2026-07-10T00:00:00Z")

            path = write_run_manifest(Path(manifest.run_dir) / "run_manifest.json", manifest)
            payload = json.loads(path.read_text(encoding="utf-8"))

            self.assertEqual(payload["objective"], "Power Pool")
            self.assertTrue(path.exists())
