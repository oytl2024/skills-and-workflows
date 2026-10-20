import unittest
import json
import tempfile
from pathlib import Path

from wqb.config import load_config


class ResearchPolicyConfigTests(unittest.TestCase):
    def test_policy_defaults_off_and_explicit_bool_is_required(self):
        from wqb.config import read_research_policy
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'defaults.json'
            self.assertIsNone(read_research_policy(path))
            for value, expected in ((False, None), (True, {'paired_scout': True})):
                path.write_text(json.dumps(dict(research_policy=dict(paired_scout=value))), encoding='utf-8')
                self.assertEqual(read_research_policy(path), expected)
            path.write_text(json.dumps(dict(research_policy=dict(paired_scout='true'))), encoding='utf-8')
            with self.assertRaises(ValueError):
                read_research_policy(path)

    def test_local_and_explicit_config_precedence(self):
        from wqb.config import read_research_policy
        with tempfile.TemporaryDirectory() as tmp:
            path, local = Path(tmp) / 'defaults.json', Path(tmp) / 'local.json'
            path.write_text(json.dumps(dict(research_policy=dict(paired_scout=False))), encoding='utf-8')
            local.write_text(json.dumps(dict(research_policy=dict(paired_scout=True))), encoding='utf-8')
            self.assertEqual(read_research_policy(path, local), dict(paired_scout=True))
            self.assertIsNone(read_research_policy(path, local, override=dict(paired_scout=False)))


class LoadConfigTest(unittest.TestCase):
    def test_load_config_reads_yaml_and_applies_defaults(self):
        config_path = Path(__file__).with_name("_tmp_config.yaml")
        try:
            config_path.write_text(
                "\n".join(
                    [
                        "region: USA",
                        "universe: TOP3000",
                        "delay: 1",
                        "max_alphas_per_round: 7",
                    ]
                ),
                encoding="utf-8",
            )

            config = load_config(config_path)
        finally:
            config_path.unlink(missing_ok=True)

        self.assertEqual(config["region"], "USA")
        self.assertEqual(config["universe"], "TOP3000")
        self.assertEqual(config["delay"], 1)
        self.assertEqual(config["max_alphas_per_round"], 7)
        self.assertEqual(config["instrument_type"], "EQUITY")
        self.assertEqual(config["language"], "FASTEXPR")

    def test_load_config_rejects_missing_required_keys(self):
        config_path = Path(__file__).with_name("_tmp_config.yaml")
        try:
            config_path.write_text("region: USA\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "missing required config keys"):
                load_config(config_path)
        finally:
            config_path.unlink(missing_ok=True)

    def test_stage1_config_keeps_on_off_as_strings(self):
        config = load_config("configs/stage1_usa_d1.yaml")

        self.assertEqual(config["pasteurization"], "ON")
        self.assertEqual(config["nan_handling"], "OFF")


if __name__ == "__main__":
    unittest.main()
