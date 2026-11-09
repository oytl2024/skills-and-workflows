"""Offline frozen scientific consumers; transports never reach a platform."""
from copy import deepcopy
import json
import unittest
from unittest.mock import Mock, patch

from tests import test_execution_package as packages
from tests.test_repair_search import search_fixture
from wqb import cli, research_tree
from wqb.benchmark_rules import (benchmark_rule_to_dict, benchmark_rulebook_digest,
                                 default_benchmark_rules, START_SNAPSHOT_VERSION)
from wqb.models import CheckSummary
from wqb.repair_policy import benchmark_resource_run, verify_consumed_plan
from wqb.repair_runtime import RepairRuntimeExecutor
from wqb.runtime_control import _write


class ExecutionConsumerResourcesTests(unittest.TestCase):
    def setUp(self):
        """Input: TestCase. Output: temporary sealed owner with sourced finite Repair and benchmark rules."""
        self.package = packages.ExecutionPackageTests()
        self.package.setUp()
        self.addCleanup(self.package.doCleanups)
        self.fixture = self.package.fixture
        self.run = self.fixture.run
        snapshot = self.fixture.manifest['start_snapshot']
        snapshot['research_policy']['deterministic_repair'] = True
        self.package.enable()
        rules = default_benchmark_rules()
        snapshot.update(artifact_binding_version=START_SNAPSHOT_VERSION, benchmark_rulebook=dict(
            path='machine/benchmark_rules.jsonl', sha256=benchmark_rulebook_digest(rules),
            rules=[benchmark_rule_to_dict(rule) for rule in rules]))
        self.parent, policy = search_fixture()
        path, source = next(iter(self.fixture.compiler_resources['source_index'].items()))
        ref = dict(source_path=path, sha256=source['content_hash'],
                   capture_date=source['captured_at'][:10], kind='documented')
        for rule in policy['rules']:
            rule['evidence_refs'] = [deepcopy(ref)]
        for trait in policy['traits'].values():
            trait['evidence_refs'] = [deepcopy(ref)]
        snapshot['repair_search_policy'] = policy
        from wqb.initial_research_planning import _annotation_context, DATA_CHARACTERISTICS_PATH
        artifact_path = self.run / DATA_CHARACTERISTICS_PATH
        artifact = json.loads(artifact_path.read_text(encoding='utf-8'))
        context = _annotation_context(self.fixture.compiler_resources, self.fixture.manifest)
        artifact['repair_search_policy_sha256'] = context['repair_search_policy_sha256']
        _write(artifact_path, artifact)
        _write(self.run / 'run_manifest.json', self.fixture.manifest)
        self.fixture.freeze()
        self.executor = RepairRuntimeExecutor(dict(knowledge_root=str(self.fixture.vault),
            active_workflow_run_dir=str(self.run)), enable_live_api=True)

    def hide_vault(self):
        """Input: fixture. Output: None; rename only this test's temporary global sources."""
        self.fixture.vault.rename(self.fixture.root / 'unavailable-global-vault')

    def execute(self, plan):
        """Input: deterministic receipt dict. Output: checked children using fake transport and real benchmark."""
        summary = CheckSummary('child', False, [], [], [],
                               dict(sharpe=1.1, fitness=.6, returns=.1, turnover=.2))
        with patch('wqb.cli._live_gate_kwargs', return_value={}), \
             patch('wqb.cli.require_readiness_gate'), \
             patch('wqb.cli.build_client', return_value=Mock()), \
             patch('wqb.cli.submit_simulation', return_value='progress/offline'), \
             patch('wqb.cli.poll_simulation', return_value=dict(alpha='child')), \
             patch('wqb.cli.fetch_check_summary', return_value=summary):
            return self.executor(self.run, self.parent, [dict(repair_plan=plan)], 1)

    def test_repair_child_triage_uses_owner_rules_without_global_vault(self):
        plan = self.executor.prepare(self.run, self.parent, [], 1)
        self.assertEqual(len(plan['variants']), 1)
        self.hide_vault()
        with patch('wqb.benchmark.load_active_benchmark_rules',
                   side_effect=AssertionError('Repair triage reopened mutable global rules')):
            rows = self.execute(plan)
        expected = cli.benchmark_fields_for_record(rows[0], run_dir=self.run, consumer='triage')
        self.assertEqual({key: rows[0][key] for key in expected}, expected)
        self.assertTrue((self.run / 'stages/repair/parents').is_dir())
        self.assertFalse((self.run / 'all_alphas.jsonl').exists())

    def test_finite_search_and_receipt_replay_use_same_frozen_sources(self):
        before = self.executor.prepare(self.run, self.parent, [], 1)
        self.hide_vault()
        with patch('wqb.exploration_eligibility._resource_certificate',
                   side_effect=AssertionError('Repair reopened global source certificates')):
            self.assertEqual(self.executor.prepare(self.run, self.parent, [], 1), before)
            self.assertEqual(verify_consumed_plan(self.run, before), before)
        tampered = deepcopy(before)
        tampered['variants'][0]['settings']['decay'] = 31
        with self.assertRaises(ValueError):
            verify_consumed_plan(self.run, tampered)

    def test_tree_and_hypothesis_selection_replay_without_global_sources(self):
        from wqb.hypothesis_selection import select_experiment_batch
        before = self.fixture.advance(maximum=2)
        snapshot = before['config_patch']['hypothesis_snapshot']
        from wqb.hypothesis_selection import validate_operational_resource_context
        context = validate_operational_resource_context(snapshot)
        selection = select_experiment_batch(snapshot, context['experiments'], 2)
        self.hide_vault()
        self.assertEqual(self.fixture.advance(maximum=2), before)
        self.assertEqual(select_experiment_batch(snapshot, context['experiments'], 2), selection)
        self.assertEqual(research_tree._load(self.run)[1], self.fixture.manifest['start_snapshot'])

    def test_seed_ranking_uses_frozen_owner_rules_without_global_sources(self):
        from tests.test_seed_policy import measured
        from wqb.research_seed_stage import prepare_seed_selection
        row = measured()
        row['expression_hash'] = row['simulation_identity']
        _write(self.run / 'runtime/tree_execution.json', dict(status='finished',
            retained_expression_hashes=[row['expression_hash']]))
        before = prepare_seed_selection(self.run, [row])
        self.assertEqual(len(before['seed_rows']), 1)
        self.hide_vault()
        self.assertEqual(prepare_seed_selection(self.run, [row]), before)
        self.assertFalse(before['submission_qualified'])

    def test_benchmark_adapter_rejects_missing_or_corrupt_seal_before_classification(self):
        from wqb.execution_package import SEAL_PATH
        subrun = self.run / 'stages/repair/parents/child'
        self.assertEqual(benchmark_resource_run(self.run, subrun), self.run)
        seal_path = self.run / SEAL_PATH
        before = seal_path.read_bytes()
        seal_path.write_bytes(before + b'corrupt')
        with self.assertRaises(ValueError):
            benchmark_resource_run(self.run, subrun)
        seal_path.unlink()
        with self.assertRaises(ValueError):
            benchmark_resource_run(self.run, subrun)

    def test_benchmark_adapter_preserves_absent_marker_legacy_subrun(self):
        legacy = self.fixture.root / 'legacy'
        subrun = legacy / 'stages/repair/parents/child'
        legacy.mkdir()
        self.assertEqual(benchmark_resource_run(legacy, subrun), subrun)
        _write(legacy / 'run_manifest.json', dict(start_snapshot=dict(research_policy={})))
        _write(legacy / 'runtime/execution_package/seal.json', dict(schema_version=1))
        self.assertEqual(benchmark_resource_run(legacy, subrun), subrun)

    def test_new_history_still_deduplicates_after_vault_disappears(self):
        before = self.executor.prepare(self.run, self.parent, [], 1)
        self.hide_vault()
        history = [dict(expression_hash=before['variants'][0]['expression_hash'])]
        after = self.executor.prepare(self.run, self.parent, history, 1)
        self.assertEqual(len(after['variants']), 1)
        self.assertNotEqual(after['variants'][0]['expression_hash'],
                            before['variants'][0]['expression_hash'])

