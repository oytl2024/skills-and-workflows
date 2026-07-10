import json
import tempfile
import unittest
from pathlib import Path

from wqb.workflow_launcher import (
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
