"""Read-only lifecycle tests; all fixtures live in temporary directories."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from wqb.full_semantic_compile import _bytes, _digest, _hash
from wqb.knowledge_derivative_lifecycle import (
    audit_semantic_derivative, apply_semantic_retirement, check_semantic_retirement,
)


class DerivativeLifecycleTests(unittest.TestCase):
    def setUp(self):
        """Input: test instance. Output: isolated vault and two immutable legacy plans."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.old = self.plan('old')
        self.new = self.plan('new')

    def plan(self, generation, budget=0, shared=False, rows=(), jobs=(), config_budget=None):
        """Input: generation str/budget int/shared bool. Output: saved minimal plan path str."""
        raw = b''.join(_bytes({key: value for key, value in row.items() if not shared or key != 'job_id'}) + b'\n'
                       for row in rows)
        jobs = list(jobs)
        identity = dict(root=str(self.root), jobs=jobs, sources=[], generation=generation,
                        inventory_sha256=_hash(raw), config=dict(model_call_budget=budget if config_budget is None else config_budget, max_runtime_seconds=1))
        if shared:
            identity['inventory_format_version'] = 3
        key = _digest(identity)
        base = 'machine/semantic_jobs/' + key
        inventory = ('machine/semantic_inventories/' + _hash(raw) if shared else base) + '/inventory.jsonl'
        plan = dict(kind='full_semantic_compile_plan', schema_version=1, root=str(self.root),
                    content_key=key, plan_path=base + '/plan.json', identity=identity, jobs=jobs,
                    estimates={}, coverage=dict(target_count=len(rows), prepared_targets=sum(r['status'] == 'prepared' for r in rows),
                        blocked_targets=sum(r['status'] == 'blocked' for r in rows), source_validated_targets=sum(r['source_validated'] for r in rows)), inventory_ref=dict(path=inventory, sha256=_hash(raw)),
                    budget=dict(model_call_budget=budget, execution_authorized=False), model_calls=0)
        for path, data in ((inventory, raw), (plan['plan_path'], _bytes(plan))):
            target = self.root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        return plan['plan_path']

    def snapshot(self):
        """Input: fixture. Output: relative file/byte map for mutation detection."""
        return {str(p.relative_to(self.root)): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}

    def test_valid_audit_is_protected_and_read_only(self):
        before = self.snapshot()
        result = audit_semantic_derivative(self.root, self.old, replacement_plan_path=self.new)
        self.assertTrue(result['validated'])
        self.assertFalse(result['eligible'])
        self.assertIn('replacement_order_unproven', result['reasons'])
        self.assertIn('external_references_not_verified', result['reasons'])
        self.assertEqual(result['inventory']['sha256'], _hash(b''))
        self.assertEqual(before, self.snapshot())

    def test_missing_or_same_replacement_protects(self):
        for replacement in (None, self.old):
            result = audit_semantic_derivative(self.root, self.old, replacement_plan_path=replacement)
            self.assertFalse(result['eligible'])
            self.assertIn('replacement_required', result['reasons'])

    def test_shared_inventory_is_never_candidate(self):
        path = self.plan('shared', shared=True)
        result = audit_semantic_derivative(self.root, path, replacement_plan_path=self.new)
        self.assertIn('shared_inventory_protected', result['reasons'])

    def test_budget_execution_and_tamper_protect(self):
        for generation, budget in (('funded', 1), ('boolean', False)):
            result = audit_semantic_derivative(self.root, self.plan(generation, budget), replacement_plan_path=self.new)
            self.assertFalse(result['validated'])
        target = self.root / self.old
        plan = json.loads(target.read_bytes())
        plan['identity']['generation'] = 'tampered'
        target.write_bytes(_bytes(plan))
        self.assertFalse(audit_semantic_derivative(self.root, self.old)['validated'])

    def test_inventory_tamper_and_owner_evidence(self):
        inventory = (self.root / self.old).parent / 'inventory.jsonl'
        inventory.write_bytes(b'{}\n')
        self.assertFalse(audit_semantic_derivative(self.root, self.old)['validated'])
        inventory.write_bytes(b'')
        ((self.root / self.old).parent / 'execution_authority.json').write_text('{}')
        self.assertIn('owner_has_additional_artifacts', audit_semantic_derivative(self.root, self.old)['reasons'])

    def test_apply_always_refuses_without_mutation(self):
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, 'approval'):
            apply_semantic_retirement(self.root, self.old, replacement_plan_path=self.new)
        self.assertEqual(before, self.snapshot())

    def test_marker_check_fails_closed(self):
        self.assertFalse(check_semantic_retirement(self.root, self.old)['blocked'])
        marker = (self.root / self.old).parent / 'retirement.json'
        marker.write_bytes(b'not valid json')
        self.assertTrue(check_semantic_retirement(self.root, self.old)['blocked'])
        self.assertTrue(check_semantic_retirement(self.root, '../plan.json')['blocked'])

    def test_links_are_protected(self):
        path = (self.root / self.old).parent / 'retirement.json'
        try:
            path.symlink_to(self.root / self.new)
        except OSError:
            self.skipTest('symlink creation unavailable')
        self.assertTrue(check_semantic_retirement(self.root, self.old)['blocked'])

    def test_bounded_and_invalid_paths(self):
        for path in ('../plan.json', str(self.root / self.old), self.old.replace('plan.json', 'inventory.jsonl')):
            self.assertFalse(audit_semantic_derivative(self.root, path)['validated'])
        with patch('wqb.knowledge_derivative_lifecycle.MAX_AUDIT_BYTES', 1):
            self.assertFalse(audit_semantic_derivative(self.root, self.old)['validated'])

    def row(self, name):
        """Input: name str. Output: valid blocked operator inventory row dict."""
        identity = dict(operator=name)
        return dict(target_id='operator:' + _digest(identity), kind='operator', identity=identity,
                    status='blocked', job_id=None, scopes=[], source_validated_scopes=[],
                    source_validated=False, gaps=[], padding='x' * 4096)

    def test_streams_inventory_larger_than_plan_limit_without_bulk_reads(self):
        rows = [self.row(str(i)) for i in range(5000)]
        path = self.plan('large', rows=rows)
        inventory = (self.root / path).parent / 'inventory.jsonl'
        self.assertGreater(inventory.stat().st_size, 16 * 1024 * 1024)
        original = Path.read_bytes
        def read_bytes(target):
            """Input: Path. Output: bytes; reject bulk inventory reads."""
            self.assertNotEqual(target, inventory)
            return original(target)
        with patch.object(Path, 'read_bytes', read_bytes):
            result = audit_semantic_derivative(self.root, path)
        self.assertTrue(result['validated'], result)
        self.assertEqual(result['target_count'], len(rows))
        self.assertEqual(result['inventory_counts']['blocked_targets'], len(rows))

    def test_config_budget_mismatch_rejected(self):
        path = self.plan('mismatch', config_budget=5)
        self.assertFalse(audit_semantic_derivative(self.root, path)['validated'])

    def test_duplicate_ids_schema_and_row_bound_rejected(self):
        row = self.row('x')
        for rows in ([row, row], [dict(row, status='unknown')], [dict(row, target_id='wrong')],
                     [dict(row, source_validated=1)]):
            path = self.plan(str(rows)[:60], rows=rows)
            self.assertFalse(audit_semantic_derivative(self.root, path)['validated'])
        path = self.plan('line_bound', rows=[row])
        with patch('wqb.knowledge_derivative_lifecycle.MAX_INVENTORY_LINE_BYTES', 128):
            self.assertFalse(audit_semantic_derivative(self.root, path)['validated'])

    def test_count_mismatch_rejected(self):
        path = self.plan('count', rows=[self.row('x')])
        target = self.root / path
        plan = json.loads(target.read_bytes())
        plan['coverage']['target_count'] = 2
        target.write_bytes(_bytes(plan))
        self.assertFalse(audit_semantic_derivative(self.root, path)['validated'])

    def test_invalid_job_identity_rejected(self):
        path = self.plan('job', jobs=[dict(job_id='../escape', target_ids=[])])
        self.assertFalse(audit_semantic_derivative(self.root, path)['validated'])

    def job_plan(self):
        """Input: fixture. Output: real-format isolated plan with two explanation jobs' targets."""
        from tests.test_full_semantic_execution import FullSemanticExecutionTests
        fixture = FullSemanticExecutionTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        plan = fixture.plan(0)
        return fixture.root, plan

    def test_exact_job_refs_inspected_without_source_reads(self):
        root, plan = self.job_plan()
        before = {str(p): p.read_bytes() for p in root.rglob('*') if p.is_file()}
        result = audit_semantic_derivative(root, plan['plan_path'])
        self.assertTrue(result['validated'], result)
        self.assertEqual(result['job_evidence']['checked_jobs'], len(plan['jobs']))
        self.assertEqual(result['job_evidence']['status'], 'protected')
        self.assertIn('job_content_validation_not_requested', result['reasons'])
        self.assertNotIn('referred_job_evidence_not_verified', result['reasons'])
        self.assertEqual(before, {str(p): p.read_bytes() for p in root.rglob('*') if p.is_file()})

    def test_job_execution_artifacts_protect_inventory_validation(self):
        for name in ('execution_state.json', 'attempt_reservation.json', 'explanation_result.json', 'unknown.bin'):
            with self.subTest(name=name):
                root, plan = self.job_plan()
                ((root / plan['jobs'][0]['path']).parent / name).write_bytes(b'{}')
                result = audit_semantic_derivative(root, plan['plan_path'])
                self.assertTrue(result['validated'], result)
                self.assertIn('job_execution_or_unknown_artifact_present', result['reasons'])

    def test_job_ref_tamper_and_limits_protect(self):
        root, plan = self.job_plan()
        with patch('wqb.knowledge_derivative_lifecycle.MAX_JOB_CHECKS', 0):
            result = audit_semantic_derivative(root, plan['plan_path'])
        self.assertTrue(result['validated'], result)
        self.assertEqual(result['job_evidence']['status'], 'protected')
        self.assertIn('job_evidence_check_bound', result['reasons'])
        (root / plan['jobs'][0]['path']).write_bytes(b'{}')
        result = audit_semantic_derivative(root, plan['plan_path'])
        self.assertTrue(result['validated'], result)
        self.assertIn('job_content_validation_not_requested', result['reasons'])
        self.assertEqual(result['job_evidence']['status'], 'protected')

    def test_inventory_mutation_during_stream_protects(self):
        from wqb import knowledge_derivative_lifecycle as lifecycle
        path = self.plan('race', rows=[self.row('x')])
        inventory = (self.root / path).parent / 'inventory.jsonl'
        original = lifecycle._json
        def parse(text):
            """Input: JSON str. Output: parsed value, injecting concurrent inventory replacement."""
            value = original(text)
            if isinstance(value, dict) and 'target_id' in value:
                inventory.write_bytes(b'changed')
            return value
        with patch.object(lifecycle, '_json', parse):
            self.assertFalse(audit_semantic_derivative(self.root, path)['validated'])

    def test_same_size_hash_tamper_and_duplicate_json_rejected(self):
        path = self.plan('hash', rows=[self.row('x')])
        inventory = (self.root / path).parent / 'inventory.jsonl'
        raw = inventory.read_bytes()
        inventory.write_bytes(raw.replace(b'xxxx', b'yyyy', 1))
        self.assertFalse(audit_semantic_derivative(self.root, path)['validated'])
        inventory.write_bytes(b'{"target_id":"a","target_id":"b"}\n')
        self.assertFalse(audit_semantic_derivative(self.root, path)['validated'])


class RetirementTransactionTests(unittest.TestCase):
    def setUp(self):
        """Input: TestCase. Output: isolated legacy/current inventories; no real vault operations."""
        self.fixture = DerivativeLifecycleTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        rows = [self.fixture.row('alpha'), self.fixture.row('beta')]
        self.old = self.fixture.plan('old transaction', rows=rows)
        self.new = self.fixture.plan('replacement', rows=rows, shared=True)
        self.inventory = (self.root / self.old).parent / 'inventory.jsonl'
        self.original = self.inventory.read_bytes()

    def prepare(self):
        """Input: fixture state. Output: prepared, nonexecuting retirement transaction."""
        from wqb.knowledge_derivative_lifecycle import prepare_semantic_retirement
        return prepare_semantic_retirement(self.root, self.old, replacement_plan_path=self.new)

    def collect(self):
        """Input: explicit fixture-only approval. Output: idempotent collection result."""
        return apply_semantic_retirement(self.root, self.old,
            approved_inventory_paths=[self.inventory.relative_to(self.root).as_posix()],
            approval_reference='isolated fixture approval')

    def test_prepare_retains_original_and_preserves_exact_historical_bytes(self):
        import gzip
        from wqb.knowledge_derivative_lifecycle import read_retired_semantic_plan
        result = self.prepare()
        self.assertEqual(result['status'], 'prepared')
        self.assertEqual(self.inventory.read_bytes(), self.original)
        self.assertEqual(gzip.decompress((self.root / result['archive_ref']['path']).read_bytes()), self.original)
        history = read_retired_semantic_plan(self.root, self.old)
        self.assertTrue(history['read_only'])
        self.assertFalse(history['research_ready'])
        self.assertEqual(history['inventory_counts']['target_count'], 2)

    def test_collection_is_approved_exact_lossless_and_idempotent(self):
        self.prepare()
        first = self.collect()
        self.assertEqual(first['removed_count'], 1)
        self.assertFalse(self.inventory.exists())
        second = self.collect()
        self.assertEqual(second['removed_count'], 0)
        self.assertEqual(second['status'], 'collected')
        self.assertTrue((self.root / self.old).exists())

    def test_foreign_approval_cannot_delete_even_after_preparation(self):
        self.prepare()
        with self.assertRaisesRegex(ValueError, 'approval'):
            apply_semantic_retirement(self.root, self.old, approved_inventory_paths=[self.new], approval_reference='fixture')
        self.assertEqual(self.inventory.read_bytes(), self.original)

    def test_missing_identity_or_scope_protects_original(self):
        from wqb.knowledge_derivative_lifecycle import prepare_semantic_retirement
        incomplete = self.fixture.plan('incomplete', rows=[self.fixture.row('alpha')], shared=True)
        with self.assertRaisesRegex(ValueError, 'replacement'):
            prepare_semantic_retirement(self.root, self.old, replacement_plan_path=incomplete)
        self.assertFalse(self.inventory.with_name('retirement.json').exists())

    def test_execution_and_run_references_prevent_retirement(self):
        owner = self.root / 'runs/mission/run_manifest.json'
        owner.parent.mkdir(parents=True)
        owner.write_text(json.dumps({'evidence_path': str(self.inventory)}), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'reference'):
            self.prepare()
        self.assertTrue(self.inventory.exists())
        owner.unlink()
        self.inventory.with_name('execution_authority.json').write_text('{}', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'execution|artifact'):
            self.prepare()

    def test_interruption_after_intent_keeps_history_and_recovers(self):
        from wqb import knowledge_derivative_lifecycle as lifecycle
        self.prepare()
        with patch.object(lifecycle, '_remove_expanded_inventory', side_effect=OSError('fixture crash')):
            with self.assertRaises(OSError):
                self.collect()
        self.assertTrue(self.inventory.exists())
        self.assertTrue(lifecycle.check_semantic_retirement(self.root, self.old)['blocked'])
        self.assertEqual(self.collect()['status'], 'collected')

    def test_interruption_after_unlink_recovers_without_resurrection(self):
        from wqb import knowledge_derivative_lifecycle as lifecycle
        self.prepare()
        with patch.object(lifecycle, '_complete_retirement', side_effect=OSError('fixture crash')):
            with self.assertRaises(OSError):
                self.collect()
        self.assertFalse(self.inventory.exists())
        self.assertEqual(lifecycle.read_retired_semantic_plan(self.root, self.old)['status'], 'retired')
        self.assertEqual(self.collect()['status'], 'collected')

    def test_changed_payload_or_corrupt_archive_never_collected(self):
        result = self.prepare()
        archive = self.root / result['archive_ref']['path']
        archive.write_bytes(b'corrupt')
        with self.assertRaises(ValueError):
            self.collect()
        self.assertEqual(self.inventory.read_bytes(), self.original)

    def test_completed_payload_reappearance_is_a_visible_fault(self):
        self.prepare()
        self.collect()
        self.inventory.write_bytes(self.original)
        with self.assertRaisesRegex(ValueError, 'reappeared'):
            self.collect()

    def test_retired_plan_rejected_before_any_execution_authority(self):
        from wqb.full_semantic_execution import run_full_semantic_compile
        plan = json.loads((self.root / self.old).read_bytes())
        self.prepare()
        result = run_full_semantic_compile(self.root, plan, executor=lambda **_: self.fail('model not allowed'))
        self.assertEqual(result['status'], 'blocked')
        self.assertFalse(self.inventory.with_name('execution_authority.json').exists())

    def test_history_report_stays_read_only_after_collection(self):
        from wqb.full_semantic_coverage import build_full_semantic_report
        plan = json.loads((self.root / self.old).read_bytes())
        self.prepare()
        self.collect()
        report = build_full_semantic_report(self.root, plan)
        self.assertEqual(report['status'], 'retired')
        self.assertTrue(report['read_only'])
        self.assertFalse(report['research_ready'])
        self.assertFalse((self.root / 'machine/reports').exists())

    def test_reference_created_after_intent_prevents_collection(self):
        self.prepare()
        owner = self.root / 'runs/new/job.json'
        owner.parent.mkdir(parents=True)
        owner.write_text(json.dumps({'path': str(self.inventory)}), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'reference'):
            self.collect()
        self.assertEqual(self.inventory.read_bytes(), self.original)

    def test_same_vault_but_different_exact_scope_is_not_covered(self):
        from wqb.knowledge_derivative_lifecycle import prepare_semantic_retirement
        row = self.fixture.row('scoped')
        usa = dict(region='USA', delay=1, universe='TOP3000', instrument_type='EQUITY')
        old = self.fixture.plan('old scope', rows=[dict(row, scopes=[usa])])
        new = self.fixture.plan('new scope', rows=[dict(row, scopes=[dict(usa, universe='TOP1000')])], shared=True)
        with self.assertRaisesRegex(ValueError, 'scope'):
            prepare_semantic_retirement(self.root, old, replacement_plan_path=new)

    def test_model_runner_cannot_enter_while_retirement_holds_plan_guard(self):
        from wqb import full_semantic_execution as execution
        from wqb.knowledge_derivative_lifecycle import plan_guard
        plan = json.loads((self.root / self.old).read_bytes())
        with plan_guard(self.root, self.old), patch.object(execution, 'LOCK_TIMEOUT_SECONDS', .03):
            result = execution.run_full_semantic_compile(self.root, plan, executor=lambda **_: self.fail('model not allowed'))
        self.assertEqual(result['status'], 'blocked')
        self.assertFalse(self.inventory.with_name('execution_authority.json').exists())

    def test_preparer_cannot_recreate_payload_for_a_marked_plan(self):
        fixture_root, plan = self.fixture.job_plan()
        from wqb.full_semantic_compile import prepare_full_semantic_compile
        inventory = fixture_root / plan['inventory_ref']['path']
        inventory.unlink()
        (fixture_root / plan['plan_path']).with_name('retirement.json').write_bytes(b'unknown marker')
        with self.assertRaisesRegex(ValueError, 'retired'):
            prepare_full_semantic_compile(fixture_root, plan['identity']['config'])
        self.assertFalse(inventory.exists())


class ArchivalOnlyRetirementTests(RetirementTransactionTests):
    def legacy_job_plan(self):
        """Input: fixture. Output: temporary legacy-format plan bound to genuine prepared job bytes."""
        root, current = self.fixture.job_plan()
        assigned = {tid: job['job_id'] for job in current['jobs'] for tid in job['target_ids']}
        rows = [json.loads(line) for line in (root / current['inventory_ref']['path']).read_bytes().splitlines()]
        rows = [dict(row, job_id=assigned.get(row['target_id'])) for row in rows]
        builder = DerivativeLifecycleTests()
        builder.root = root
        path = builder.plan('legacy prepared jobs', rows=rows, jobs=current['jobs'])
        return root, json.loads((root / path).read_bytes())

    def prepare(self):
        """Input: fixture. Output: archive-only intent without any semantic replacement."""
        from wqb import knowledge_derivative_lifecycle as lifecycle
        self.assertTrue(callable(getattr(lifecycle, 'prepare_semantic_archive_retirement', None)),
                        'explicit archive-only preparation API is missing')
        return lifecycle.prepare_semantic_archive_retirement(self.root, self.old)

    def test_archive_contract_has_no_replacement_or_completeness_claim(self):
        from wqb import knowledge_derivative_lifecycle as lifecycle
        before = (self.root / self.old).read_bytes()
        self.prepare()
        intent = json.loads(self.inventory.with_name('retirement.json').read_bytes())
        self.assertEqual(intent['retention_contract'], 'lossless_inventory_archive_v1')
        self.assertNotIn('replacement_ref', intent)
        self.assertNotIn('coverage_proof', intent)
        self.collect()
        (self.root / self.new).unlink()
        with lifecycle.open_retired_semantic_inventory(self.root, self.old) as reader:
            self.assertEqual(reader.read(), self.original)
        self.assertEqual((self.root / self.old).read_bytes(), before)

    def test_archive_audit_is_readonly_and_default_audit_stays_protected(self):
        from wqb import knowledge_derivative_lifecycle as lifecycle
        self.assertTrue(callable(getattr(lifecycle, 'audit_semantic_archive_retirement', None)))
        before = self.fixture.snapshot()
        audit = lifecycle.audit_semantic_archive_retirement(self.root, self.old)
        self.assertEqual(audit['disposition'], 'archive_candidate', audit)
        self.assertEqual(before, self.fixture.snapshot())
        self.assertIn('replacement_required', audit_semantic_derivative(self.root, self.old)['reasons'])

    def test_arbitrary_history_label_cannot_exempt_an_active_reference(self):
        owner = self.root / 'runs/mission/run_manifest.json'
        owner.parent.mkdir(parents=True)
        owner.write_bytes(_bytes(dict(status='retired', role='documentary',
            inventory_ref=dict(path=self.inventory.relative_to(self.root).as_posix(), sha256=_hash(self.original)))))
        with self.assertRaisesRegex(ValueError, 'reference'):
            self.prepare()
        self.assertFalse(self.inventory.with_name('retirement.json').exists())

    def test_archive_audit_propagates_reference_scan_diagnostics_without_writes(self):
        """Input: fixture scan with a byte refusal. Output: protected audit with compact owner diagnostics."""
        from wqb import knowledge_derivative_lifecycle as lifecycle
        before = self.fixture.snapshot()
        with patch.object(lifecycle, 'RETIREMENT_SCAN_BYTES', 1):
            audit = lifecycle.audit_semantic_archive_retirement(self.root, self.old)
        self.assertEqual(audit['disposition'], 'protected')
        self.assertFalse(audit['validated'])
        self.assertIn('evidence reference scan limit', audit['reasons'][0])
        self.assertEqual(audit['scan_diagnostics']['limiting_bound'], 'file_bytes')
        self.assertTrue(audit['scan_diagnostics']['current_owner'].endswith('plan.json'))
        self.assertEqual(before, self.fixture.snapshot())

    def test_coverage_reference_requires_exact_documentary_contract(self):
        plan = json.loads((self.root / self.old).read_bytes())
        report = self.root / ('machine/reports/full_semantic_coverage_' + plan['content_key'] + '.json')
        report.parent.mkdir(parents=True)
        report.write_bytes(_bytes(dict(kind='run_manifest', inventory_ref=plan['inventory_ref'])))
        with self.assertRaisesRegex(ValueError, 'documentary|reference'):
            self.prepare()

    def test_archive_only_cannot_accept_replacement_on_collection(self):
        self.prepare()
        with self.assertRaisesRegex(ValueError, 'replacement'):
            apply_semantic_retirement(self.root, self.old, replacement_plan_path=self.new,
                approved_inventory_paths=[self.inventory.relative_to(self.root).as_posix()],
                approval_reference='fixture')
        self.assertTrue(self.inventory.exists())

    def test_archive_contract_and_original_plan_tampering_fail_closed(self):
        from wqb import knowledge_derivative_lifecycle as lifecycle
        self.prepare()
        marker = self.inventory.with_name('retirement.json')
        original = marker.read_bytes()
        intent = json.loads(original)
        intent['retention_contract'] = 'replacement_not_needed'
        marker.write_bytes(_bytes(intent))
        with self.assertRaises(ValueError):
            self.collect()
        marker.write_bytes(original)
        plan = json.loads((self.root / self.old).read_bytes())
        plan['coverage']['target_count'] += 1
        (self.root / self.old).write_bytes(_bytes(plan))
        with self.assertRaises(ValueError):
            lifecycle.open_retired_semantic_inventory(self.root, self.old)
        self.assertTrue(self.inventory.exists())

    def test_plan_guard_blocks_concurrent_retirement(self):
        from wqb import knowledge_derivative_lifecycle as lifecycle
        with lifecycle.plan_guard(self.root, self.old), patch.object(lifecycle, 'LIFECYCLE_LOCK_SECONDS', .03):
            with self.assertRaises((ValueError, TimeoutError)):
                self.prepare()
        self.assertFalse(self.inventory.with_name('retirement.json').exists())

    def test_changed_expanded_bytes_cannot_be_archived(self):
        self.inventory.write_bytes(self.original.replace(b'xxxx', b'yyyy', 1))
        with self.assertRaises(ValueError):
            self.prepare()
        self.assertFalse(self.inventory.with_name('retirement.json').exists())

    def test_hardlinked_inventory_cannot_be_archived(self):
        import os
        os.link(self.inventory, self.inventory.with_name('other-copy'))
        with self.assertRaises(ValueError):
            self.prepare()

    def test_job_preparation_bytes_are_verified_before_and_after_retirement(self):
        from wqb import knowledge_derivative_lifecycle as lifecycle
        root, plan = self.legacy_job_plan()
        lifecycle.prepare_semantic_archive_retirement(root, plan['plan_path'])
        job = root / plan['jobs'][0]['path']
        before = job.read_bytes()
        job.write_bytes(b'{}')
        with self.assertRaisesRegex(ValueError, 'job'):
            lifecycle.read_retired_semantic_plan(root, plan['plan_path'])
        job.write_bytes(before)
        (job.parent / 'attempt_reservation.json').write_bytes(b'{}')
        with self.assertRaisesRegex(ValueError, 'job|execution'):
            lifecycle.apply_semantic_retirement(root, plan['plan_path'],
                approved_inventory_paths=[plan['inventory_ref']['path']], approval_reference='fixture')

    def test_real_coverage_report_is_documentary_and_kept_byte_identical(self):
        from wqb.full_semantic_coverage import build_full_semantic_report
        from wqb import knowledge_derivative_lifecycle as lifecycle
        root, plan = self.legacy_job_plan()
        evidence = {p: p.read_bytes() for p in root.rglob('*') if p.is_file() and p.name != 'inventory.jsonl'}
        report = build_full_semantic_report(root, plan)
        path = root / report['report_paths']['json']
        original = path.read_bytes()
        lifecycle.prepare_semantic_archive_retirement(root, plan['plan_path'])
        lifecycle.apply_semantic_retirement(root, plan['plan_path'],
            approved_inventory_paths=[plan['inventory_ref']['path']], approval_reference='fixture')
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual({p: p.read_bytes() for p in evidence}, evidence)
        self.assertEqual(build_full_semantic_report(root, plan)['status'], 'retired')

    def test_documentary_report_cannot_hide_an_additional_dependency(self):
        from wqb.full_semantic_coverage import build_full_semantic_report
        from wqb import knowledge_derivative_lifecycle as lifecycle
        root, plan = self.legacy_job_plan()
        report = build_full_semantic_report(root, plan)
        report['diagnostics'].append(dict(path=plan['inventory_ref']['path']))
        (root / report['report_paths']['json']).write_bytes(_bytes(report))
        with self.assertRaisesRegex(ValueError, 'reference'):
            lifecycle.prepare_semantic_archive_retirement(root, plan['plan_path'])

    def test_active_job_lock_blocks_archival_without_issuing_authority(self):
        from wqb import knowledge_derivative_lifecycle as lifecycle
        from wqb.lockfile import json_lock_transition_guard
        root, plan = self.legacy_job_plan()
        job = (root / plan['jobs'][0]['path']).parent
        with json_lock_transition_guard(job / 'execution_guard', 1, .01, 'fixture busy'):
            with patch.object(lifecycle, 'LIFECYCLE_LOCK_SECONDS', .03):
                with self.assertRaises((ValueError, TimeoutError)):
                    lifecycle.prepare_semantic_archive_retirement(root, plan['plan_path'])
        self.assertFalse((root / plan['plan_path']).with_name('retirement.json').exists())
        self.assertFalse((job / 'execution_authority.json').exists())

    def test_interruption_before_intent_is_retryable_and_does_not_hide_inventory(self):
        with patch('wqb.knowledge_contracts._write_immutable_source', side_effect=OSError('fixture crash')):
            with self.assertRaises(OSError):
                self.prepare()
        self.assertEqual(self.inventory.read_bytes(), self.original)
        self.assertFalse(check_semantic_retirement(self.root, self.old)['blocked'])
        self.prepare()
        self.assertEqual(self.collect()['removed_count'], 1)

    def test_original_plan_changed_during_collection_is_not_deleted(self):
        from wqb import knowledge_derivative_lifecycle as lifecycle
        self.prepare()
        original = lifecycle._check_snapshots
        def change(root, snapshots):
            """Input: paths/digests. Output: None; inject an uncooperative immutable-plan alteration."""
            original(root, snapshots)
            path = root / self.old
            value = json.loads(path.read_bytes())
            value['model_calls'] = 1
            path.write_bytes(_bytes(value))
        with patch.object(lifecycle, '_check_snapshots', change), self.assertRaises(ValueError):
            self.collect()
        self.assertTrue(self.inventory.exists())

    def test_archive_changed_during_collection_is_not_deleted(self):
        from wqb import knowledge_derivative_lifecycle as lifecycle
        result = self.prepare()
        original = lifecycle._check_snapshots
        def change(root, snapshots):
            """Input: paths/digests. Output: None; inject an archive alteration before collection."""
            original(root, snapshots)
            (root / result['archive_ref']['path']).write_bytes(b'changed')
        with patch.object(lifecycle, '_check_snapshots', change), self.assertRaises(ValueError):
            self.collect()
        self.assertTrue(self.inventory.exists())

    def test_job_input_and_brief_alterations_block_preparation(self):
        from wqb import knowledge_derivative_lifecycle as lifecycle
        for name in ('input.json', 'brief.txt'):
            with self.subTest(name=name):
                root, plan = self.legacy_job_plan()
                job = root / plan['jobs'][0]['path']
                job.with_name(name).write_bytes(b'changed')
                with self.assertRaisesRegex(ValueError, 'job'):
                    lifecycle.prepare_semantic_archive_retirement(root, plan['plan_path'])

    def test_concurrent_preparation_and_collection_are_idempotent(self):
        from concurrent.futures import ThreadPoolExecutor
        from wqb import knowledge_derivative_lifecycle as lifecycle
        with patch.object(lifecycle, 'LIFECYCLE_LOCK_SECONDS', 15), ThreadPoolExecutor(max_workers=2) as pool:
            prepared = list(pool.map(lambda _: self.prepare(), range(2)))
            collected = list(pool.map(lambda _: self.collect(), range(2)))
        self.assertEqual(prepared[0]['archive_ref'], prepared[1]['archive_ref'])
        self.assertEqual(sorted(row['removed_count'] for row in collected), [0, 1])

    def test_retirement_intent_changed_during_collection_is_not_deleted(self):
        from wqb import knowledge_derivative_lifecycle as lifecycle
        self.prepare()
        original = lifecycle._check_snapshots
        def change(root, snapshots):
            """Input: paths/digests. Output: None; inject an intent alteration before collection."""
            original(root, snapshots)
            marker = self.inventory.with_name('retirement.json')
            intent = json.loads(marker.read_bytes())
            intent['inventory_counts']['target_count'] += 1
            marker.write_bytes(_bytes(intent))
        with patch.object(lifecycle, '_check_snapshots', change), self.assertRaises(ValueError):
            self.collect()
        self.assertTrue(self.inventory.exists())

    def test_archive_object_hardlink_is_rejected_by_retired_reader(self):
        import os
        from wqb import knowledge_derivative_lifecycle as lifecycle
        prepared = self.prepare()
        archive = self.root / prepared['archive_ref']['path']
        os.link(archive, archive.with_name('alias'))
        with self.assertRaises(ValueError):
            lifecycle.open_retired_semantic_inventory(self.root, self.old)
        self.assertTrue(self.inventory.exists())

    def test_junction_owner_cannot_redirect_archival(self):
        import os
        import subprocess
        if os.name != 'nt':
            self.skipTest('Windows junction contract')
        base = self.inventory.parent
        redirected = self.root / 'redirected-fixture-owner'
        base.rename(redirected)
        result = subprocess.run(['cmd.exe', '/d', '/c', 'mklink', '/J', str(base), str(redirected)],
                                capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        try:
            with self.assertRaises(ValueError):
                self.prepare()
            self.assertFalse((redirected / 'retirement.json').exists())
            self.assertEqual((redirected / 'inventory.jsonl').read_bytes(), self.original)
        finally:
            base.rmdir()

    def test_legacy_embedded_target_report_has_independent_bounded_documentary_read(self):
        from wqb.full_semantic_coverage import build_full_semantic_report
        from wqb import knowledge_derivative_lifecycle as lifecycle
        root, plan = self.legacy_job_plan()
        report = build_full_semantic_report(root, plan, detailed=True)
        report.pop('targets_ref')
        report['schema_version'] = 1
        relative = report['report_paths']['json']
        path = root / relative
        path.write_bytes(_bytes(report))
        with patch.object(lifecycle, 'MAX_AUDIT_BYTES', 1):
            self.assertEqual(lifecycle._documentary_report(root, plan, relative), _hash(path.read_bytes()))
        before = path.read_bytes()
        lifecycle.prepare_semantic_archive_retirement(root, plan['plan_path'])
        lifecycle.apply_semantic_retirement(root, plan['plan_path'],
            approved_inventory_paths=[plan['inventory_ref']['path']], approval_reference='fixture')
        self.assertEqual(path.read_bytes(), before)

    def test_documentary_reader_uses_bounded_handle_reads_and_enforces_limit(self):
        from wqb.full_semantic_coverage import build_full_semantic_report
        from wqb import knowledge_derivative_lifecycle as lifecycle
        root, plan = self.legacy_job_plan()
        report = build_full_semantic_report(root, plan)
        relative = report['report_paths']['json']
        path = root / relative
        expected = _hash(path.read_bytes())
        with patch.object(Path, 'read_bytes', side_effect=AssertionError('unbounded pathname read')):
            self.assertEqual(lifecycle._documentary_report(root, plan, relative), expected)
        with patch.object(lifecycle, 'MAX_HISTORICAL_REPORT_BYTES', 1), self.assertRaisesRegex(ValueError, 'bound'):
            lifecycle._documentary_report(root, plan, relative)
