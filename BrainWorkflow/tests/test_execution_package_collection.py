"""Terminal collection transactions against real temporary research completion."""
import importlib
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from tests import test_execution_package_retirement as fixtures
from wqb.runtime_control import _write


class ExecutionPackageCollectionTests(unittest.TestCase):
    def setUp(self):
        """Input: TestCase. Output: completed, recorded isolated tree with no live effects."""
        self.fixture = fixtures.ExecutionRetirementTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.run = self.fixture.run

    def test_terminal_collection_preserves_authority_results_and_console_view(self):
        lifecycle = importlib.import_module('wqb.execution_package_lifecycle')
        from wqb.console_api import _lane
        from wqb.execution_package import load_execution_package
        from wqb.research_retirement import retirement_boundary
        before = _lane(self.run)
        protected = {name: (self.run / name).read_bytes() for name in
                     ('run_manifest.json', 'runtime_control.json', 'all_alphas.jsonl', 'research_record.json')}
        result = lifecycle.retire_execution_package(self.run, fixtures.NOW)
        self.assertEqual(result['status'], 'retired')
        self.assertGreater(result['removed_count'], 0)
        self.assertFalse((self.run / 'runtime/experiment_tree.json').exists())
        self.assertEqual(_lane(self.run), before)
        for name, raw in protected.items():
            self.assertEqual((self.run / name).read_bytes(), raw)
        with self.assertRaises(ValueError):
            load_execution_package(self.run)
        self.assertEqual(retirement_boundary(self.run)['status'], 'retired')
        self.assertEqual(lifecycle.retire_execution_package(self.run, fixtures.NOW)['removed_count'], 0)
        self.assertEqual(lifecycle.load_retired_summary(self.run)['console_projection'], before)

    def test_stop_prevents_commit_and_collection(self):
        lifecycle = importlib.import_module('wqb.execution_package_lifecycle')
        control = self.fixture.read('runtime_control.json')
        _write(self.run / 'runtime_control.json', dict(control, desired_state='paused'))
        with self.assertRaises(ValueError):
            lifecycle.retire_execution_package(self.run, fixtures.NOW)
        self.assertTrue((self.run / 'runtime/experiment_tree.json').exists())
        self.assertFalse((self.run / lifecycle.RETIRED_RECEIPT).exists())

    def test_stop_race_defers_cleanup_without_requesting_code_maintenance(self):
        from wqb.workflow_driver import _retire_completed_package
        control = self.fixture.read('runtime_control.json')
        _write(self.run / 'runtime_control.json', dict(control, desired_state='paused'))
        with patch('wqb.workflow_driver.dispatch_notification') as notice:
            result = _retire_completed_package(self.run, 'unused-worker', fixtures.NOW)
        self.assertEqual(result['status'], 'deferred')
        self.assertEqual(result['reason'], 'user_paused')
        notice.assert_not_called()

    def test_stop_during_archival_preparation_wins_before_commit(self):
        lifecycle = importlib.import_module('wqb.execution_package_lifecycle')
        from wqb.runtime_control import request_runtime_state
        original = lifecycle.prepare_package_archive

        def stop_after_archive(run):
            """Input: owner Path. Output: verified archive, after a real durable Stop interleaves."""
            result = original(run)
            control = self.fixture.read('runtime_control.json')
            request_runtime_state(run, 'paused', expected_revision=control['request_revision'])
            return result

        with patch.object(lifecycle, 'prepare_package_archive', side_effect=stop_after_archive):
            with self.assertRaises(ValueError):
                lifecycle.retire_execution_package(self.run, fixtures.NOW)
        self.assertEqual(self.fixture.read('runtime_control.json')['desired_state'], 'paused')
        self.assertFalse((self.run / lifecycle.RETIRED_RECEIPT).exists())
        self.assertTrue((self.run / 'runtime/experiment_tree.json').exists())

    def test_committed_crash_recovers_without_recreating_inputs(self):
        lifecycle = importlib.import_module('wqb.execution_package_lifecycle')
        with patch.object(lifecycle, '_collect_entry', side_effect=RuntimeError('interrupted collection')):
            with self.assertRaises(RuntimeError):
                lifecycle.retire_execution_package(self.run, fixtures.NOW)
        self.assertTrue((self.run / lifecycle.RETIRED_RECEIPT).exists())
        self.assertTrue(lifecycle.load_retired_summary(self.run))
        self.assertEqual(lifecycle.retire_execution_package(self.run, fixtures.NOW)['status'], 'retired')

    def test_committed_collection_retry_respects_a_new_durable_stop(self):
        lifecycle = importlib.import_module('wqb.execution_package_lifecycle')
        with patch.object(lifecycle, '_collect_entry', side_effect=RuntimeError('interrupted')):
            with self.assertRaises(RuntimeError):
                lifecycle.retire_execution_package(self.run, fixtures.NOW)
        from wqb.runtime_control import request_runtime_state
        request_runtime_state(self.run, 'paused')
        with self.assertRaises(ValueError):
            lifecycle.retire_execution_package(self.run, fixtures.NOW)
        self.assertTrue((self.run / 'runtime/experiment_tree.json').exists())

    def test_committed_retry_rejects_structurally_incomplete_authority(self):
        lifecycle = importlib.import_module('wqb.execution_package_lifecycle')
        with patch.object(lifecycle, '_collect_entry', side_effect=RuntimeError('interrupted')):
            with self.assertRaises(RuntimeError):
                lifecycle.retire_execution_package(self.run, fixtures.NOW)
        _write(self.run / 'runtime_control.json', dict(desired_state='running'))
        with self.assertRaises(ValueError):
            lifecycle.retire_execution_package(self.run, fixtures.NOW)
        self.assertTrue((self.run / 'runtime/experiment_tree.json').exists())

    def test_canonical_group_digest_is_used_by_terminal_proof(self):
        from wqb import research_group as group
        from wqb.execution_retirement import terminal_retirement_proof
        created = group.create_group(self.run.parent,
            [dict(run_id='temporary-member', plan_digest=group._digest(self.fixture.fixture.compiler_resources))],
            dict(enable_live_api=True, max_runtime_seconds=3600, max_recoveries=3))
        directory = self.run.parent / 'research_groups' / created['group_id']
        manifest = json.loads((directory / 'group_manifest.json').read_bytes())
        manifest['lanes'][0]['run_id'] = self.run.name
        digest = group._digest(manifest)
        _write(directory / 'group_manifest.json', manifest)
        intent = json.loads((directory / 'group_intent.json').read_bytes())
        _write(directory / 'group_intent.json', dict(intent, manifest_sha256=digest, desired_state='running'))
        _write(self.run / 'research_group_binding.json', dict(group_id=created['group_id'],
            manifest_sha256=digest, **manifest['lanes'][0]))
        self.assertEqual(group.read_group(directory)['lanes'][0]['run_id'], self.run.name)
        self.assertTrue(terminal_retirement_proof(self.run)['eligible'])

    def test_precommit_crash_can_retry_after_legitimate_candidate_invalidation(self):
        lifecycle = importlib.import_module('wqb.execution_package_lifecycle')
        from wqb.candidate_evidence import invalidate_candidate_evidence
        other = self.fixture.repair_fixture(qualified=True)
        original = lifecycle._store_immutable

        def before_commit(run, path, value):
            """Input: immutable writer arguments. Output: persisted preparation except simulated commit interruption."""
            if path == lifecycle.RETIRED_RECEIPT:
                raise RuntimeError('crash before commit')
            return original(run, path, value)

        with patch.object(lifecycle, '_store_immutable', side_effect=before_commit):
            with self.assertRaises(RuntimeError):
                lifecycle.retire_execution_package(other.run, fixtures.NOW)
        invalidate_candidate_evidence(other.client, 'child', 'legitimate later account evidence')
        self.assertTrue(other.proof()['eligible'])
        self.assertEqual(lifecycle.retire_execution_package(other.run, fixtures.NOW)['status'], 'retired')

    def test_partial_collection_retry_keeps_already_removed_inputs_absent(self):
        lifecycle = importlib.import_module('wqb.execution_package_lifecycle')
        original = lifecycle._collect_entry
        removed = []

        def interrupt(run, row):
            """Input: exact collector arguments. Output: first deletion, then simulated interruption."""
            if removed:
                raise RuntimeError('crash after first removal')
            result = original(run, row)
            removed.append(run / row['path'])
            return result

        with patch.object(lifecycle, '_collect_entry', side_effect=interrupt):
            with self.assertRaises(RuntimeError):
                lifecycle.retire_execution_package(self.run, fixtures.NOW)
        self.assertFalse(removed[0].exists())
        result = lifecycle.retire_execution_package(self.run, fixtures.NOW)
        self.assertEqual(result['status'], 'retired')
        self.assertFalse(removed[0].exists())

    def test_tampered_summary_never_authorizes_collection(self):
        lifecycle = importlib.import_module('wqb.execution_package_lifecycle')
        with patch.object(lifecycle, '_collect_entry', side_effect=RuntimeError('interrupted collection')):
            with self.assertRaises(RuntimeError):
                lifecycle.retire_execution_package(self.run, fixtures.NOW)
        path = self.run / self.fixture.read(lifecycle.RETIRED_RECEIPT)['summary_path']
        summary = json.loads(path.read_text())
        summary['run_id'] = 'another-owner'
        _write(path, summary)
        with self.assertRaises(ValueError):
            lifecycle.retire_execution_package(self.run, fixtures.NOW)
        self.assertTrue((self.run / 'runtime/experiment_tree.json').exists())

    def test_peer_dedup_keeps_retired_plan_reservations(self):
        lifecycle = importlib.import_module('wqb.execution_package_lifecycle')
        from wqb.research_tree import _global_excluded
        plans = list((self.run / 'runtime/research_plans').glob('tree-plan-*.json'))
        reserved = {identity for path in plans if not path.name.endswith('.experiments.json')
                    for identity in json.loads(path.read_text())['reserved_simulation_identities']}
        self.assertTrue(reserved)
        lifecycle.retire_execution_package(self.run, fixtures.NOW)
        peer = self.run.parent / 'another-active-lane'
        peer.mkdir()
        excluded = _global_excluded(peer, dict(source_run_root=str(self.run.parent)))
        self.assertTrue(reserved <= excluded)

    def test_driver_automatically_retires_after_successful_recording(self):
        from wqb.workflow_driver import run_workflow_driver
        status = dict(active=True, run_dir=str(self.run), status='running', current_stage='research_record_sync')
        result = run_workflow_driver(SimpleNamespace(), dict(runtime_max_steps=2),
            step=lambda: dict(status, status='completed', current_stage='complete'),
            status_reader=lambda: status, now_func=lambda: fixtures.NOW)
        self.assertEqual(result['runtime_status'], 'completed', result)
        self.assertEqual(result['execution_package_retirement']['status'], 'retired')
        self.assertFalse((self.run / 'runtime/experiment_tree.json').exists())

    def test_cleanup_programming_fault_is_event_routed_without_rewriting_research(self):
        from wqb.workflow_driver import _retire_completed_package
        before = (self.run / 'run_state.json').read_bytes()
        with patch('wqb.execution_package_lifecycle.retire_execution_package',
                   side_effect=KeyError('unexpected cleanup shape')), patch(
                'wqb.workflow_driver.dispatch_notification', side_effect=lambda run, case, now: case) as notice:
            result = _retire_completed_package(self.run, 'fixture-owner', fixtures.NOW)
        self.assertEqual(result['status'], 'deferred')
        self.assertTrue(result['case_id'])
        self.assertTrue((self.run / 'runtime/execution_package/retirement_fault.json').exists())
        self.assertEqual((self.run / 'run_state.json').read_bytes(), before)
        self.assertTrue((self.run / 'runtime/experiment_tree.json').exists())
        notice.assert_called_once()

    def test_notification_exception_does_not_turn_recorded_success_into_failure(self):
        from wqb.workflow_driver import _retire_completed_package
        with patch('wqb.execution_package_lifecycle.retire_execution_package', side_effect=ValueError('defer')), patch(
                'wqb.workflow_driver.dispatch_notification', side_effect=RuntimeError('uncertain notification')):
            result = _retire_completed_package(self.run, 'fixture-owner', fixtures.NOW)
        self.assertEqual(result['status'], 'deferred')
        self.assertEqual(result['notification_delivery'], 'unknown')
        self.assertEqual(self.fixture.read('run_state.json')['status'], 'completed')

    def test_group_can_verify_retired_member_without_reopening_its_active_inputs(self):
        lifecycle = importlib.import_module('wqb.execution_package_lifecycle')
        from wqb import research_group_driver as group
        snapshot = self.fixture.read('run_manifest.json')['start_snapshot']
        state = self.fixture.read('run_state.json')
        lifecycle.retire_execution_package(self.run, fixtures.NOW)
        self.fixture.vault.rename(self.fixture.fixture.root / 'removed-vault')
        group._validate_prepared_resource_context(self.run, self.fixture.vault, snapshot, state)
        changed = dict(snapshot, measurement_period=dict(start='2000-01-01', end='2001-01-01'))
        with self.assertRaises(ValueError):
            group._validate_prepared_resource_context(self.run, self.fixture.vault, changed, state)

    def test_real_completed_repair_retirement_preserves_qualified_raw_cache(self):
        lifecycle = importlib.import_module('wqb.execution_package_lifecycle')
        other = self.fixture.repair_fixture(qualified=True)
        caches = {path: path.read_bytes() for path in (other.vault / 'machine/candidate_evidence').glob('*.json')}
        self.assertTrue(caches)
        calls = other.client.get_json.call_count
        result = lifecycle.retire_execution_package(other.run, fixtures.NOW)
        self.assertEqual(result['status'], 'retired')
        summary = lifecycle.load_retired_summary(other.run)
        self.assertTrue(summary['candidate_evidence'])
        self.assertTrue(summary['repair']['attempts'][0]['children'])
        self.assertEqual(other.client.get_json.call_count, calls)
        for path, raw in caches.items():
            self.assertEqual(path.read_bytes(), raw)

    def test_actual_repair_after_freeze_never_recertifies_raw_or_loads_global_benchmark(self):
        from wqb import research_tree
        original = research_tree.freeze_tree

        def freeze(*args, **kwargs):
            """Input: real fixture producer arguments. Output: sealed tree, then disable scientific global readers."""
            result = original(*args, **kwargs)
            self.enterContext(patch('wqb.exploration_eligibility._resource_certificate',
                side_effect=AssertionError('global raw reopened after freeze')))
            self.enterContext(patch('wqb.benchmark_rules.load_benchmark_rules',
                side_effect=AssertionError('global benchmark reopened after freeze')))
            return result

        with patch.object(research_tree, 'freeze_tree', side_effect=freeze):
            other = self.fixture.repair_fixture(qualified=True)
        self.assertEqual(other.read('run_state.json')['status'], 'completed')
        self.assertTrue(other.proof()['eligible'])


if __name__ == '__main__':
    unittest.main()
