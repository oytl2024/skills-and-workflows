"""Source-backed project hypotheses for deterministic Repair; no live transport."""

from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from tests.test_compiled_repair_policy import fixture


class RepairRulebookTests(unittest.TestCase):
    def test_derived_semantic_tags_do_not_become_required_official_facts(self):
        """Input: sourced field with advisory tags. Output: finite rules, without promoting tags into traits."""
        from wqb.repair_rulebook import build_default_repair_policy
        resources, _ = fixture()
        resources['field_rows'][0]['semantic_tags'] = ['noisy', 'persistent']
        policy = build_default_repair_policy(resources)
        self.assertTrue(policy['rules'])
        self.assertNotIn('noisy', policy['traits'])
        self.assertNotIn('persistent', policy['traits'])

    def test_manual_v2_without_certified_resources_is_rejected_at_start(self):
        """Input: source-free manual v2 policy. Output: rejection before mission creation, not a late Repair stall."""
        from wqb.preplanned_start import _repair_policy
        from wqb.repair_rulebook import build_default_repair_policy
        resources, _ = fixture()
        policy = build_default_repair_policy(resources)
        policy.pop('resources')
        with self.assertRaisesRegex(ValueError, 'supplied v2'):
            _repair_policy(resources, policy)

    def test_rulebook_is_in_maintenance_and_loaded_version_identity(self):
        """Input: temporary code and project catalog. Output: assertions. Prevent unnoticed packaged rule drift."""
        from wqb.runtime_revision import source_code_revision
        from wqb.maintenance_resolution import _code_digest
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'wqb').mkdir()
            (root / 'wqb' / 'module.py').write_text('value = 1\n', encoding='utf-8')
            (root / 'configs').mkdir()
            path = root / 'configs' / 'repair_rulebook.json'
            path.write_text('{"version":1}', encoding='utf-8')
            before = (source_code_revision(root / 'wqb'), _code_digest(root))
            path.write_text('{"version":2}', encoding='utf-8')
            self.assertNotEqual(before[0], source_code_revision(root / 'wqb'))
            self.assertNotEqual(before[1], _code_digest(root))

    def test_desktop_bundle_includes_only_the_named_public_rulebook(self):
        """Input: existing build script. Output: assertions. Bundle required rules without private configs."""
        script = (Path(__file__).resolve().parents[1] / 'scripts/build_desktop.ps1').read_text(encoding='utf-8')
        self.assertIn('configs/repair_rulebook.json', script)
        self.assertIn('Join-Path $Stage "configs"', script)
        self.assertNotIn('Copy-Item -Recurse', script)

    def test_new_start_assembles_default_policy_instead_of_empty_search(self):
        """Input: actual sourced composer resources. Output: assertions. Freeze project rules without raw fabrication."""
        from wqb.preplanned_start import _repair_policy
        resources, _ = fixture()
        policy = _repair_policy(resources)
        self.assertEqual(policy['schema_version'], 2)
        self.assertTrue(policy['rules'])

    def test_source_backed_defaults_are_nonempty_project_hypotheses(self):
        """Input: source-backed MATRIX resource. Output: assertions. Never claim setting effects are official facts."""
        from wqb.repair_rulebook import build_default_repair_policy
        resources, _ = fixture()
        before = deepcopy(resources)
        policy = build_default_repair_policy(resources)
        self.assertEqual(policy['schema_version'], 2)
        self.assertEqual(policy['rulebook_id'], 'metric-directed-defaults-v1')
        self.assertTrue(policy['rules'])
        self.assertTrue(all(rule['basis'] == 'project_hypothesis' for rule in policy['rules']))
        self.assertTrue(all(rule['trigger']['checks'] for rule in policy['rules']))
        self.assertNotIn('noisy', policy['traits'])
        self.assertNotIn('nuisance_exposure', policy['traits'])
        self.assertEqual(resources, before)

    def test_defaults_cover_metric_issues_without_new_fields_or_formulas(self):
        """Input: sourced data. Output: assertions. Freeze finite metric-specific settings rules."""
        from wqb.repair_rulebook import build_default_repair_policy
        resources, _ = fixture()
        rules = build_default_repair_policy(resources)['rules']
        issues = {name for rule in rules for name in rule['trigger']['checks']}
        self.assertTrue({'HIGH_TURNOVER', 'LOW_SHARPE', 'LOW_FITNESS', 'CONCENTRATED_WEIGHT'} <= issues)
        self.assertTrue(all(rule['edit'] in {'decay', 'truncation'} for rule in rules))
        self.assertTrue(all(0 < len(rule['grid']) <= 32 for rule in rules))

    def test_false_field_fact_is_not_converted_into_a_usable_rulebook(self):
        """Input: field/raw type disagreement. Output: assertions. Defaults do not bypass source validation."""
        from wqb.repair_rulebook import build_default_repair_policy
        resources, _ = fixture()
        resources['field_rows'][0]['field_type'] = 'VECTOR'
        with self.assertRaises(ValueError):
            build_default_repair_policy(resources)
