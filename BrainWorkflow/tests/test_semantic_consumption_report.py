"""Reports measure existing frozen consumers without starting research or inventing gates."""

from copy import deepcopy
import json
import unittest
from unittest.mock import patch

from wqb.knowledge_compile import prepare_full_semantic_compile, build_full_semantic_report


class SemanticConsumptionReportTests(unittest.TestCase):
    def setUp(self):
        """Input: none. Output: actual frozen temporary Start lane, fake initial model only."""
        from tests.test_preplanned_start import PreplannedStartTests
        from wqb.research_tree import _load
        self.fixture = PreplannedStartTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        result = self.fixture.prepare()
        self.assertEqual(result['status'], 'completed', result)
        self.root = self.fixture.paths.knowledge_root
        self.run = self.fixture.paths.run_root / result['group']['lanes'][0]['run_id']
        _, self.snapshot = _load(self.run)
        self.plan = prepare_full_semantic_compile(self.root, dict(model_call_budget=0))
        self.request = dict(resources=self.fixture.resources[0], templates=self.snapshot['template_rows'])

    def test_real_binder_and_frozen_start_are_measured_not_inferred(self):
        """Input: existing source-bound operations/lane. Output: measured layers without model/platform/Start calls."""
        calls = self.fixture.runner.call_count
        before = {str(p): p.read_bytes() for p in self.fixture.paths.run_root.rglob('*') if p.is_file()}
        report = build_full_semantic_report(self.root, self.plan,
            binding_requests=[self.request], consumer_run_dirs=[self.run])
        self.assertEqual(report['compiler_binder']['status'], 'measured')
        self.assertEqual(report['compiler_binder']['denominator'], len(self.snapshot['template_rows']))
        self.assertGreater(report['compiler_binder']['numerator'], 0)
        self.assertEqual(report['start_consumption']['numerator'], 1)
        self.assertEqual(report['start_consumption']['denominator'], 1)
        self.assertFalse(report['research_ready'])
        self.assertEqual(self.fixture.runner.call_count, calls)
        self.assertEqual(before, {str(p): p.read_bytes() for p in self.fixture.paths.run_root.rglob('*') if p.is_file()})

    def test_failed_binding_and_corrupt_lane_remain_in_denominators(self):
        """Input: invalid operation and mutated frozen attachment. Output: zero verified consumers, attempted counts retained."""
        request = deepcopy(self.request)
        request['templates'] = [dict(request['templates'][0], skeleton='undefined_operator({signal})')]
        attachment = self.run / 'runtime/experiment_tree.json'
        value = json.loads(attachment.read_text())
        value['tree_digest'] = '0' * 64
        attachment.write_text(json.dumps(value), encoding='utf-8')
        report = build_full_semantic_report(self.root, self.plan,
            binding_requests=[request], consumer_run_dirs=[self.run])
        self.assertEqual(report['compiler_binder']['numerator'], 0)
        self.assertEqual(report['compiler_binder']['denominator'], 1)
        self.assertEqual(report['start_consumption']['numerator'], 0)
        self.assertEqual(report['start_consumption']['denominator'], 1)
        self.assertTrue(report['start_consumption']['reasons'])

    def test_duplicate_consumers_do_not_pad_coverage(self):
        """Input: repeated same operation and lane. Output: exact distinct denominators."""
        report = build_full_semantic_report(self.root, self.plan,
            binding_requests=[self.request, self.request], consumer_run_dirs=[self.run, self.run])
        self.assertEqual(report['compiler_binder']['denominator'], len(self.snapshot['template_rows']))
        self.assertEqual(report['start_consumption']['denominator'], 1)

    def test_ignored_envelope_metadata_does_not_duplicate_bindings(self):
        """Input: same consumed resources with an unused display note. Output: one set of operation measurements."""
        alias = deepcopy(self.request)
        alias['resources']['review_note'] = 'Same operation, different display metadata'
        report = build_full_semantic_report(self.root, self.plan, binding_requests=[self.request, alias])
        self.assertEqual(report['compiler_binder']['denominator'], len(self.snapshot['template_rows']))

    def test_inventory_mutation_during_consumer_validation_refuses_report(self):
        """Input: inventory changed during consumer checks. Output: refuse publishing inconsistent measurement."""
        from wqb import full_semantic_coverage
        original = full_semantic_coverage._consumer_measurements
        inventory = self.root / self.plan['inventory_ref']['path']

        def mutate(*args):
            result = original(*args)
            with inventory.open('ab') as stream:
                stream.write(b'\n')
            return result

        with patch.object(full_semantic_coverage, '_consumer_measurements', side_effect=mutate):
            with self.assertRaisesRegex(ValueError, 'inventory changed'):
                build_full_semantic_report(self.root, self.plan,
                    binding_requests=[self.request], consumer_run_dirs=[self.run])

    def test_foreign_vault_is_rejected_before_loading_run(self):
        """Input: local lane declaring another vault. Output: counted rejection without reading foreign knowledge."""
        from wqb import research_tree
        manifest_path = self.run / 'run_manifest.json'
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        manifest['knowledge_root'] = str(self.root.parent / 'unrelated-vault')
        manifest_path.write_text(json.dumps(manifest), encoding='utf-8')
        with patch.object(research_tree, '_load', side_effect=AssertionError('Must not load foreign vault')):
            report = build_full_semantic_report(self.root, self.plan, consumer_run_dirs=[self.run])
        self.assertEqual(report['start_consumption']['numerator'], 0)
        self.assertEqual(report['start_consumption']['denominator'], 1)

    def test_oversize_manifest_is_rejected_before_reading(self):
        """Input: manifest larger than the bounded-reader limit. Output: explicit counted failure, no manifest load."""
        from pathlib import Path
        manifest_path = self.run / 'run_manifest.json'
        original = Path.read_bytes

        def guarded_read(path):
            if path == manifest_path:
                self.fail('Oversize manifest must be rejected before read_bytes')
            return original(path)

        with patch('wqb.full_semantic_coverage.MAX_CONSUMER_MANIFEST_BYTES', 1), patch.object(
                Path, 'read_bytes', guarded_read):
            report = build_full_semantic_report(self.root, self.plan, consumer_run_dirs=[self.run])
        self.assertEqual(report['start_consumption']['numerator'], 0)
        self.assertIn('safe read bound', report['start_consumption']['reasons'][0]['reason'])

    def test_alias_run_paths_count_once(self):
        """Input: same frozen lane through dot-dot alias. Output: one genuine consumer denominator."""
        alias = self.run / '..' / self.run.name
        report = build_full_semantic_report(self.root, self.plan, consumer_run_dirs=[self.run, alias])
        self.assertEqual(report['start_consumption']['numerator'], 1)
        self.assertEqual(report['start_consumption']['denominator'], 1)


class SharedFieldReportVerificationTests(unittest.TestCase):
    def test_multiple_jobs_scan_shared_original_only_once_then_finalize(self):
        """Input: three jobs sharing one bounded extract. Output: one original scan plus final mutation check."""
        from pathlib import Path
        from tests.test_field_source_projection import FieldSourceProjectionTests
        fixture = FieldSourceProjectionTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        capture = fixture.fixture
        row = deepcopy(capture.rows[0])
        row['field']['id'] = 'f001'
        capture.rows.insert(1, row)
        row = deepcopy(row)
        row['field']['id'] = 'f002'
        capture.rows.insert(2, row)
        capture.save()
        # Existing excerpts bind the previous original, so use a fresh isolated fixture directory.
        capture.relative = capture.relative.replace('2026-10-23', '2026-10-24')
        capture.source = capture.root / capture.relative
        capture.source.parent.mkdir(parents=True)
        for item in capture.rows:
            item['generated_at'] = '2026-10-24T00:00:00Z'
        capture.save()
        capture.produce(max_batches=1, max_fields=3)
        plan = prepare_full_semantic_compile(capture.root, dict(model_call_budget=0, max_targets_per_job=1))
        reads, original = [], Path.open

        def counted(path, *args, **kwargs):
            if path == capture.source and args and 'r' in args[0]:
                reads.append(path)
            return original(path, *args, **kwargs)

        with patch.object(Path, 'open', counted):
            report = build_full_semantic_report(capture.root, plan)
        self.assertGreaterEqual(report['inventory']['numerator'], 3)
        self.assertLessEqual(len(reads), 2)
        from wqb import full_semantic_coverage
        measured = full_semantic_coverage._consumer_measurements
        saved_report = capture.root / report['report_paths']['json']
        before = saved_report.read_bytes()

        def mutate_original(*args):
            """Input: consumer arguments. Output: prior result after changing the verified original."""
            result = measured(*args)
            with capture.source.open('ab') as stream:
                stream.write(b'\n')
            return result

        with patch.object(full_semantic_coverage, '_consumer_measurements', side_effect=mutate_original):
            with self.assertRaisesRegex(ValueError, 'field extraction evidence changed'):
                build_full_semantic_report(capture.root, plan)
        self.assertEqual(saved_report.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
