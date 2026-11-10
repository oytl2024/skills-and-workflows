"""Script-owned local execution inputs, independent of mutable global catalogs."""
from copy import deepcopy
import importlib
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tests import test_research_tree as fixtures
from wqb import exploration_eligibility as eligibility
from wqb import research_tree
from wqb.runtime_control import _write


class ExecutionPackageTests(unittest.TestCase):
    def setUp(self):
        """Input: TestCase. Output: isolated source-certified tree fixture; no network/model."""
        self.fixture = fixtures.ResearchTreeTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.run = self.fixture.run

    def enable(self, version=1):
        """Input: explicit package version. Output: refreshed pre-model certificate/snapshot in temporary fixture only."""
        fixture = self.fixture
        snapshot = fixture.manifest['start_snapshot']
        policy = snapshot['research_policy']
        policy.update(preplanned_tree_version=1, execution_package_version=version)
        snapshot['repair_search_policy'] = dict(schema_version=1, rules=[], traits={})
        _write(self.run / 'run_manifest.json', fixture.manifest)
        certificate = eligibility.certify_exploration_resources(
            self.run, fixture.vault, fixture.compiler_resources, fixture.scope)
        replacement = eligibility.build_exploration_snapshot(list(fixture.receipts.values()),
            resource_certificates=[certificate] * len(fixture.receipts))
        snapshot.update(replacement)
        _write(self.run / 'run_manifest.json', fixture.manifest)
        from wqb import initial_research_planning as planning
        context = planning._annotation_context(fixture.compiler_resources, fixture.manifest)
        fields = context['fields']
        annotations = [dict(dataset_id=row['dataset_id'], field_id=row['field_id'],
            known_trait_keys=[], unknown_trait_keys=row['unknown_trait_keys'],
            hypotheses=[], suggested_repair_rule_ids=[]) for row in fields]
        used = {(row['dataset_id'], row['field_id']) for row in fields}
        artifact = dict(schema_version=1, input_sha256='a' * 64,
            resource_certificate_sha256=certificate['content_sha256'],
            repair_search_policy_sha256=context['repair_search_policy_sha256'],
            purpose='documentation_only', fields=planning._annotation_fields(
                dict(data_characteristics=annotations), dict(annotation_context=context), used))
        _write(self.run / planning.DATA_CHARACTERISTICS_PATH, artifact)

    def test_annotation_is_required_at_freeze_and_bound_by_exact_bytes(self):
        from wqb.initial_research_planning import DATA_CHARACTERISTICS_PATH
        self.enable()
        path = self.run / DATA_CHARACTERISTICS_PATH
        before = path.read_bytes()
        path.unlink()
        with self.assertRaises(ValueError):
            self.fixture.freeze()
        path.write_bytes(before)
        self.fixture.freeze()
        module = importlib.import_module('wqb.execution_package')
        seal = module.load_execution_package(self.run)['seal']
        self.assertEqual(seal['data_characteristics']['path'], DATA_CHARACTERISTICS_PATH)
        path.write_bytes(before + b' ')
        with self.assertRaises(ValueError):
            module.load_execution_package(self.run)

    def test_freeze_creates_script_owned_local_context_and_does_not_rewrite_manifest(self):
        self.enable()
        before = (self.run / 'run_manifest.json').read_bytes()
        frozen = self.fixture.freeze()
        module = importlib.import_module('wqb.execution_package')
        seal = json.loads((self.run / module.SEAL_PATH).read_text(encoding='utf-8'))
        self.assertEqual(seal['run_id'], self.run.name)
        self.assertEqual(seal['schema_version'], 1)
        self.assertEqual(module.load_execution_context(self.run),
                         eligibility.validate_exploration_snapshot(self.fixture.manifest['start_snapshot']))
        self.assertEqual(research_tree._load(self.run)[0], frozen)
        self.assertEqual((self.run / 'run_manifest.json').read_bytes(), before)

    def test_sealed_tree_loads_after_global_sources_disappear_without_global_reads(self):
        self.enable()
        expected = self.fixture.freeze()
        self.fixture.vault.rename(self.fixture.root / 'unavailable-global-vault')
        with patch('wqb.exploration_eligibility._resource_certificate',
                   side_effect=AssertionError('runtime must not reopen global knowledge')):
            actual, snapshot = research_tree._load(self.run)
            self.assertEqual(actual, expected)
            self.assertEqual(snapshot, self.fixture.manifest['start_snapshot'])
            context = eligibility.validate_operational_exploration(self.run, self.fixture.vault, snapshot)
            self.assertTrue(context['experiments'])

    def test_identical_freeze_reuses_seal_without_reopening_global_sources(self):
        self.enable()
        expected = self.fixture.freeze()
        self.fixture.vault.rename(self.fixture.root / 'unavailable-global-vault')
        self.assertEqual(self.fixture.freeze(), expected)
        changed = deepcopy(self.fixture.tree)
        changed['roots'] = []
        with self.assertRaises(ValueError):
            research_tree.freeze_tree(self.run, changed, self.fixture.resources)

    def test_new_package_execution_never_schedules_a_late_model_checkpoint(self):
        from wqb.ai_checkpoints import schedule_run_checkpoint
        self.enable()
        self.fixture.freeze()
        _write(self.run / 'stages/schedule/research_schedule.json', {})
        _write(self.run / 'candidate_gate.json', {})
        _write(self.run / 'research_record.json', {})
        with patch('wqb.ai_checkpoints.run_ai_checkpoint', return_value={'unexpected': True}) as model:
            for stage, status in [('scout_seed', 'paused'), ('user_approval', 'waiting_for_user'),
                                  ('complete', 'completed')]:
                self.assertIsNone(schedule_run_checkpoint(self.run,
                    dict(current_stage=stage, status=status), '2026-11-09T00:00:00Z', ['no-model']))
        model.assert_not_called()
        self.assertFalse((self.run / 'stages/ai/ai_checkpoints.jsonl').exists())

    def test_missing_seal_cannot_silently_recertify_during_execution(self):
        self.enable()
        self.fixture.freeze()
        module = importlib.import_module('wqb.execution_package')
        (self.run / module.SEAL_PATH).unlink()
        with self.assertRaises(ValueError):
            research_tree._load(self.run)
        with self.assertRaises(ValueError):
            eligibility.validate_operational_exploration(self.run, self.fixture.vault,
                                                       self.fixture.manifest['start_snapshot'])

    def test_legacy_tree_still_uses_its_original_source_contract(self):
        self.fixture.freeze()
        self.fixture.vault.rename(self.fixture.root / 'unavailable-global-vault')
        with self.assertRaises((ValueError, OSError)):
            research_tree._load(self.run)

    def test_bad_version_cannot_opt_into_local_only_execution(self):
        module = importlib.import_module('wqb.execution_package')
        for value in (True, 0, 2, '1', None):
            policy = dict(preplanned_tree_version=1, execution_package_version=value)
            with self.subTest(version=value), self.assertRaises(ValueError):
                module.package_enabled(dict(research_policy=policy))
        self.assertFalse(module.package_enabled(self.fixture.manifest['start_snapshot']))

    def test_console_configuration_preserves_validated_script_package_opt_in(self):
        from wqb.console_start import load_start_config
        paths = SimpleNamespace(configuration_root=self.fixture.root)
        file = self.fixture.root / 'configs/workflow_local.json'
        policy = dict(paired_scout=True, preplanned_tree_version=1, execution_package_version=1)
        _write(file, dict(research_policy=policy))
        self.assertEqual(load_start_config(paths)['research_policy'], policy)
        for version in (True, 0, 2):
            policy['execution_package_version'] = version
            _write(file, dict(research_policy=policy))
            with self.subTest(version=version), self.assertRaises(ValueError):
                load_start_config(paths)

    def test_seal_owner_and_local_input_tampering_reject(self):
        self.enable()
        self.fixture.freeze()
        module = importlib.import_module('wqb.execution_package')
        seal = json.loads((self.run / module.SEAL_PATH).read_text(encoding='utf-8'))
        paths = [self.run / 'run_manifest.json', self.run / research_tree.ATTACHMENT,
                 self.run / seal['certificate_refs'][0]['path'], self.run / module.SEAL_PATH]
        for path in paths:
            before = path.read_bytes()
            if path == self.run / module.SEAL_PATH:
                altered = json.loads(before)
                altered['run_id'] = 'other'
                _write(path, altered)
            else:
                path.write_bytes(before + b' ')
            try:
                with self.subTest(path=path.name), self.assertRaises(ValueError):
                    module.load_execution_context(self.run)
            finally:
                path.write_bytes(before)
        other = self.fixture.root / 'other-owner'
        other.mkdir()
        _write(other / 'run_manifest.json', self.fixture.manifest)
        with self.assertRaises(ValueError):
            module.load_execution_context(other)

    def test_producer_rejects_tree_body_that_differs_from_validated_proposal(self):
        self.enable()
        module = importlib.import_module('wqb.execution_package')
        with patch.object(module, 'seal_execution_context', return_value={}):
            self.fixture.freeze()
        path = self.run / research_tree.ATTACHMENT
        attachment = json.loads(path.read_text(encoding='utf-8'))
        root = next(node for node in attachment['tree']['nodes'] if node['node_id'] == 'root')
        self.assertTrue(root['targets']['baseline'])
        root['targets']['baseline'] = []
        _write(path, attachment)
        with self.assertRaises(ValueError):
            module.seal_execution_context(self.run)

    def test_runtime_readiness_uses_owned_package_and_preserves_live_permission(self):
        from wqb.run_readiness import evaluate_run_readiness
        self.enable()
        self.fixture.freeze()
        self.fixture.vault.rename(self.fixture.root / 'unavailable-global-vault')
        kwargs = dict(knowledge_root=self.fixture.vault, mode='research', batch_size=4,
            region=self.fixture.scope['region'], universe=self.fixture.scope['universe'],
            delay=self.fixture.scope['delay'], start_snapshot=self.fixture.manifest['start_snapshot'],
            execution_run_dir=self.run)
        with patch('wqb.run_readiness.load_freshness_manifest',
                   side_effect=AssertionError('global scientific gate must not run')):
            report = evaluate_run_readiness(**kwargs, live_api_enabled=True)
            self.assertFalse(report.blocked, report.issues)
            report = evaluate_run_readiness(**kwargs, live_api_enabled=False)
            self.assertTrue(report.blocked)
            self.assertIn('live_api_disabled', [issue.code for issue in report.issues])
        changed = deepcopy(kwargs)
        changed['universe'] = 'DIFFERENT'
        report = evaluate_run_readiness(**changed, live_api_enabled=True)
        self.assertTrue(report.blocked)
        changed = deepcopy(kwargs)
        changed['delay'] = True
        self.assertTrue(evaluate_run_readiness(**changed, live_api_enabled=True).blocked)

    def test_runtime_adapter_binds_owner_and_cannot_authorize_submission(self):
        from wqb.cli import _live_gate_kwargs, require_readiness_gate, ReadinessGateError
        self.fixture.manifest['selected_option_id'] = 'fixture-option'
        self.enable()
        self.fixture.freeze()
        config = dict(self.fixture.scope, knowledge_root=str(self.fixture.vault),
                      active_workflow_run_dir=str(self.run))
        with patch('wqb.workflow_stage_adapters._snapshot_schedule_inputs') as inputs:
            kwargs = _live_gate_kwargs(config, self.run / 'readiness')
        inputs.assert_called_once()
        self.assertEqual(kwargs['execution_run_dir'], self.run)
        self.fixture.vault.rename(self.fixture.root / 'unavailable-global-vault')
        with patch('wqb.run_readiness.load_freshness_manifest',
                   side_effect=AssertionError('must read sealed context')):
            require_readiness_gate(**kwargs)
            kwargs['mode'] = 'submit-candidate'
            kwargs['submit_confirmed'] = True
            with self.assertRaises(ReadinessGateError):
                require_readiness_gate(**kwargs)

    def test_local_readiness_rejects_unversioned_owner_and_changed_expected_context(self):
        from wqb.run_readiness import evaluate_run_readiness
        self.fixture.freeze()
        kwargs = dict(knowledge_root=self.fixture.vault, mode='research', batch_size=4,
            live_api_enabled=True, execution_run_dir=self.run,
            start_snapshot=self.fixture.manifest['start_snapshot'], **self.fixture.scope)
        # Only the public scope arguments belong to readiness.
        kwargs.pop('instrument_type', None)
        kwargs.pop('as_of', None)
        report = evaluate_run_readiness(**kwargs)
        self.assertTrue(report.blocked)
        self.assertEqual(report.issues[0].code, 'invalid_execution_package')

    def test_two_real_prepared_lanes_keep_separate_owned_inputs_without_global_catalog(self):
        from tests import test_preplanned_start as start_fixtures
        from tests.test_initial_research_planning import FakeRunner
        from wqb.execution_package import load_execution_package
        fixture = start_fixtures.PreplannedStartTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.add_lane(1)
        fixture.config.update(parallel_workflows=2, research_policy=dict(
            paired_scout=True, preplanned_tree_version=1, execution_package_version=1))

        def answer(brief):
            """Input: certified fixture brief dict. Output: initial tree plus reference-only annotations."""
            result = fixture.answer_for_brief(brief)
            result['data_characteristics'] = [dict(dataset_id=row['dataset_id'], field_id=row['field_id'],
                known_trait_keys=[], unknown_trait_keys=row['unknown_trait_keys'], hypotheses=[],
                suggested_repair_rule_ids=[]) for row in brief['annotation_context']['fields']]
            return result

        fixture.runner = FakeRunner(side_effect=answer)
        result = fixture.prepare()
        self.assertEqual(result['status'], 'completed', result)
        self.assertEqual(fixture.runner.call_count, 2)
        self.assertEqual(result['group']['desired_state'], 'paused')
        fixture.paths.knowledge_root.rename(fixture.root / 'removed-global-vault')
        lanes = [fixture.paths.run_root / lane['run_id'] for lane in result['group']['lanes']]
        packages = [load_execution_package(run) for run in lanes]
        identities = [{(row['dataset_id'], row['field_id']) for row in package['snapshot']['data_ledger_rows']}
                      for package in packages]
        self.assertTrue(identities[0].isdisjoint(identities[1]))
        changed = lanes[0] / packages[0]['seal']['certificate_refs'][0]['path']
        changed.write_bytes(changed.read_bytes() + b' ')
        with self.assertRaises(ValueError):
            load_execution_package(lanes[0])
        self.assertEqual(load_execution_package(lanes[1]), packages[1])


if __name__ == '__main__':
    unittest.main()
