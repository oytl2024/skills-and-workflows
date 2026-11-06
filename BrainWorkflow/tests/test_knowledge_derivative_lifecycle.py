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
