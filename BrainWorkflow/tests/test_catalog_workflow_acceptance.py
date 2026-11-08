"""Offline catalog intake through the real frozen tree, Seed and Repair driver."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from tests import test_preplanned_driver_acceptance as driver_tests


POLICY = 'knowledge_catalog_v1'
OPTIONAL_FIELD_METADATA = ('units', 'available_at', 'timing', 'grain', 'vector_grain')
REPAIR_DECAYS = (8, 16)
MAX_VIRTUAL_WAIT_SECONDS = 60


def catalog_driver_fixture():
    """Input: none. Output: TestCase instance; reuse fixtures without discovering inherited tests."""
    class CatalogDriverFixture(driver_tests.PreplannedDriverAcceptanceTests):
        def certify_resources(self):
            """Input: fixture resources. Output: None; retain raw truth, omit optional canonical facts."""
            super().certify_resources()
            fixture = self.case.fixture
            fixture.config['resource_admission_policy'] = POLICY
            settings = fixture.resources[0]['settings']
            fixture.config.update(instrument_type=settings['instrumentType'], decay=settings['decay'],
                neutralization=settings['neutralization'], truncation=settings['truncation'],
                pasteurization=settings['pasteurization'], unit_handling=settings['unitHandling'],
                nan_handling=settings['nanHandling'], language=settings['language'])
            self.raw_sources = {}
            self.canonical_fields = []
            for resource in fixture.resources:
                self.raw_sources.update(deepcopy(resource['source_index']))
                for row in resource['field_rows']:
                    for key in OPTIONAL_FIELD_METADATA:
                        row.pop(key, None)
                    self.canonical_fields.append(deepcopy(row))
                for operator in resource['operator_rows']:
                    operator['definition']['description'] = 'Economic interpretation unknown.'
            ledger = fixture.paths.knowledge_root / 'machine/data_ledger.jsonl'
            ledger.write_text(''.join(json.dumps(row) + '\n' for row in self.canonical_fields),
                              encoding='utf-8')

        def write_readiness_inputs(self):
            """Input: ready group. Output: None; remove only the temporary global template library."""
            super().write_readiness_inputs()
            template = self.case.fixture.paths.knowledge_root / 'machine/template_library.jsonl'
            self.assertTrue(template.is_file())
            template.unlink()

        def drive(self, run):
            """Input: owning run Path. Output: real driver result with bounded virtual polling, no transport backoff."""
            from wqb.workflow_driver import run_workflow_driver
            waited = 0

            def now():
                """Input: none. Output: UTC str; advance only driver scheduling waits, not resource authority."""
                return (datetime.now(timezone.utc) + timedelta(seconds=waited)).isoformat()

            def virtual_wait(seconds):
                """Input: driver delay float. Output: None; bounded local scheduling clock advance without sleeping."""
                nonlocal waited
                self.assertGreaterEqual(seconds, 0)
                waited += seconds
                self.assertLessEqual(waited, MAX_VIRTUAL_WAIT_SECONDS, 'Offline driver wait did not converge')

            def unexpected_wait(seconds):
                """Input: requested delay float. Output: assertion failure; immediate fake HTTP never needs polling."""
                self.fail('Unexpected offline polling/backoff: ' + str(seconds))

            def bounded_driver(*args, **kwargs):
                """Input: unchanged production driver arguments. Output: real driver result with no polling sleeps."""
                return run_workflow_driver(*args, **kwargs, now_func=now, sleep_func=virtual_wait)

            with patch('wqb.workflow_driver.run_workflow_driver', side_effect=bounded_driver), \
                    patch('wqb.research_group_driver.utc_now', side_effect=now), \
                    patch('wqb.client.cooperative_sleep', side_effect=unexpected_wait), \
                    patch('wqb.simulator.cooperative_sleep', side_effect=unexpected_wait), \
                    patch('wqb.cli.cooperative_sleep', side_effect=unexpected_wait):
                return super().drive(run)

    return CatalogDriverFixture()


class CatalogWorkflowAcceptanceTests(unittest.TestCase):
    def assert_catalog_context(self, fixture):
        """Input: initialized fixture TestCase. Output: frozen trees; assert real owning readiness."""
        from wqb.cli import _live_gate_kwargs, require_readiness_gate
        from wqb.hypothesis_selection import validate_operational_resource_context
        from wqb.research_tree import _load

        knowledge = fixture.case.fixture.paths.knowledge_root
        self.assertFalse((knowledge / 'machine/template_library.jsonl').exists())
        rows = [json.loads(line) for line in
                (knowledge / 'machine/data_ledger.jsonl').read_text(encoding='utf-8').splitlines()]
        self.assertEqual(rows, fixture.canonical_fields)
        for row in rows:
            self.assertGreater(row['coverage'], 0)
            self.assertEqual(row['coverage_status'], 'measured_raw')
            self.assertTrue(row['field_description'])
            for key in OPTIONAL_FIELD_METADATA:
                self.assertNotIn(key, row)
        for path, source in fixture.raw_sources.items():
            self.assertEqual(hashlib.sha256((knowledge / path).read_bytes()).hexdigest(),
                             source['content_hash'])

        trees = {}
        for run in fixture.case.runs:
            manifest = json.loads((run / 'run_manifest.json').read_text(encoding='utf-8'))
            snapshot = manifest['start_snapshot']
            self.assertEqual(snapshot['resource_admission_policy'], POLICY)
            for row in snapshot['data_ledger_rows']:
                self.assertIn(row, fixture.canonical_fields)
            context = validate_operational_resource_context(snapshot)
            self.assertEqual(context['resource_admission_policy'], POLICY)
            scope = manifest['selected_scope']
            kwargs = _live_gate_kwargs(dict(knowledge_root=str(knowledge),
                active_workflow_run_dir=str(run), **{key: scope[key]
                for key in ('region', 'delay', 'universe')}), run)
            self.assertEqual(kwargs['start_snapshot'], snapshot)
            require_readiness_gate(**kwargs)
            report = json.loads((run / 'readiness_report.json').read_text(encoding='utf-8'))
            self.assertFalse(any(issue['level'] == 'block' for issue in report['issues']), report)
            tree, _ = _load(run)
            trees[run] = deepcopy(tree)
        self.assertEqual(fixture.case.fixture.runner.call_count, 2)
        return trees

    def assert_transport_truth(self, fixture):
        """Input: driven fixture TestCase. Output: None; preserve exact identities and HTTP allowlist."""
        from wqb.cli import simulation_identity_hash
        self.assertFalse(fixture.transport_errors, fixture.transport_errors)
        self.assertTrue(fixture.transport.posted)
        self.assertEqual(len(fixture.transport.posted), len(set(fixture.transport.posted)))
        for alpha_id, detail in fixture.transport.details.items():
            identity = simulation_identity_hash(detail['regular']['code'], detail['settings'])
            self.assertIn(identity, fixture.transport.posted)
            self.assertEqual(alpha_id, 'a' + identity[:20])
            self.assertEqual(detail['is']['startDate'], '2020-01-01')
            self.assertEqual(detail['is']['endDate'], '2025-01-01')
        for method, path in fixture.transport.calls:
            self.assertTrue(
                (method == 'POST' and path in ('/authentication', '/simulations'))
                or (method == 'GET' and path in fixture.transport.progress)
                or (method == 'GET' and path.startswith('/alphas/')
                    and path.split('/')[2] in fixture.transport.details
                    and len(path.split('/')) == (4 if path.endswith('/check') else 3)),
                (method, path))

    def test_catalog_intake_frozen_readiness_tree_seed_repair_and_stop(self):
        """Input: two offline scenarios. Output: complete catalog driver and durable Stop/restart evidence."""
        from wqb.repair_scheduler import _verified_prefix
        from wqb.research_group import read_group
        from wqb.research_tree import _load, advance_tree

        for scenario in ('complete', 'stop_during_repair'):
            with self.subTest(scenario=scenario), \
                    patch('socket.socket.connect', side_effect=AssertionError('No network allowed')):
                fixture = catalog_driver_fixture()
                try:
                    fixture.setUp()
                    trees = self.assert_catalog_context(fixture)
                    group_path = Path(fixture.case.group['group_dir'])
                    authority = deepcopy(read_group(group_path)['authority'])
                    if scenario == 'complete':
                        fixture.test_n2_real_driver_reaches_real_repair_without_internal_gate_or_late_model()
                        for run in fixture.case.runs:
                            # Repair has appended measurements; Scout's publication hash is stage-local.
                            result = advance_tree(run, [], 0)
                            self.assertEqual(result['status'], 'finished')
                            self.assertEqual(result['routes']['both']['selected_node_ids'], ['left', 'right'])
                            self.assertEqual(result['routes']['weak']['selected_node_ids'], ['fallback'])
                            self.assertEqual(result['routes']['opposite']['selected_node_ids'], ['reverse_child'])
                            self.assertEqual(result['comparisons']['left']['outcome'], 'rejected')
                            receipt = json.loads((run / 'stages/repair/repair_execution.json').read_text())
                            self.assertTrue(_verified_prefix(run / 'all_alphas.jsonl', receipt, run))
                            self.assertTrue(receipt['attempts'])
                            self.assertTrue(any(attempt.get('children') for attempt in receipt['attempts']))
                            self.assertLessEqual(sum(len(attempt.get('children', []))
                                                     for attempt in receipt['attempts']),
                                                 len(receipt['parent_keys']) * len(REPAIR_DECAYS))
                            for attempt in receipt['attempts']:
                                plan = attempt['plan']
                                self.assertEqual(plan['planner_kind'], 'deterministic')
                                self.assertLessEqual(len(plan['variants']), 1)
                                for variant in plan['variants']:
                                    self.assertEqual(variant['decision']['edit'], 'decay')
                                    self.assertIn(variant['settings']['decay'], REPAIR_DECAYS)
                            repairs = [detail for detail in fixture.transport.details.values()
                                       if detail['settings']['decay'] in REPAIR_DECAYS]
                            self.assertTrue(repairs)
                            for detail in repairs:
                                baseline = dict(detail['settings'], decay=4)
                                self.assertTrue(any(item['regular'] == detail['regular']
                                                    and item['settings'] == baseline
                                                    for item in fixture.transport.details.values()))
                    else:
                        fixture.test_stop_inside_real_repair_post_survives_production_driver_restart()
                        self.assertTrue(any(detail['settings']['decay'] in REPAIR_DECAYS
                                            for detail in fixture.transport.details.values()))
                    self.assertEqual(read_group(group_path)['authority'], authority)
                    for run, tree in trees.items():
                        current, _ = _load(run)
                        self.assertEqual(current['tree'], tree['tree'])
                        self.assertEqual(current['resources'], tree['resources'])
                    self.assert_transport_truth(fixture)
                finally:
                    fixture.doCleanups()


if __name__ == '__main__':
    unittest.main()
