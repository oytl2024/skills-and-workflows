"""Recovery-copy history tests; never operate on real runs or platform clients."""

import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from wqb import knowledge_recovery


class RecoveryCopyRetirementTests(unittest.TestCase):
    def test_external_jsonl_scan_buffers_the_pinned_raw_stream(self):
        """Input: real pinned raw handles. Output: JSONL parsing never uses byte-wise raw readline."""
        retirement = self.module()
        original = retirement._open
        target = self.workspace / 'knowledge/machine/data_ledger.jsonl'
        self.write(target, b'{"field":"ordinary"}\n' * 32)

        class PinnedRaw(io.RawIOBase):
            def __init__(self, raw):
                """Input: pinned binary raw handle. Output: spying raw interface with the same descriptor."""
                self.raw = raw

            def readable(self):
                """Input: none. Output: bool; support bounded buffered reads."""
                return True

            def fileno(self):
                """Input: none. Output: original OS descriptor for identity verification."""
                return self.raw.fileno()

            def readinto(self, buffer):
                """Input: writable buffer. Output: byte count from the pinned file."""
                return self.raw.readinto(buffer)

            def readline(self, size=-1):
                """Input: optional bound. Output: failure if the scanner uses unbuffered line IO."""
                raise AssertionError('unbuffered raw readline')

            def close(self):
                """Input: none. Output: None; close the fixture-owned file descriptor."""
                self.raw.close()
                super().close()

        with patch.object(retirement, '_open', side_effect=lambda root, path: PinnedRaw(original(root, path))):
            self.assertEqual(retirement.audit_recovery_copy_retirement(self.run, self.copy_path)[
                'disposition'], 'archive_candidate')

    def test_released_owned_worker_identity_is_not_a_directory_reference(self):
        """Input: released owning lease run_id and a real additional reference. Output: only the actual reference protects."""
        retirement = self.module()
        path = self.run / 'runtime/source_run_lock.json'
        value = dict(status='released', run_id='runtime', action='workflow-driver')
        self.record(path, value)
        self.assertEqual(retirement.audit_recovery_copy_retirement(self.run, self.copy_path)[
            'disposition'], 'archive_candidate')
        self.record(path, dict(value, evidence_path=str(self.copy)))
        self.assertEqual(retirement.audit_recovery_copy_retirement(self.run, self.copy_path)[
            'disposition'], 'protected')

    def test_matching_state_checkpoint_is_owned_history_but_drift_is_protected(self):
        """Input: canonical matching state checkpoint, then mismatched status. Output: authenticate before treating run_dir as metadata."""
        retirement = self.module()
        state = json.loads((self.run / 'run_state.json').read_bytes())
        path = self.run / 'run_state_checkpoint.json'
        self.record(path, state)
        self.assertEqual(retirement.audit_recovery_copy_retirement(self.run, self.copy_path)[
            'disposition'], 'archive_candidate')
        self.record(path, dict(state, status='running'))
        self.assertEqual(retirement.audit_recovery_copy_retirement(self.run, self.copy_path)[
            'disposition'], 'protected')

    def test_old_checked_identity_cannot_hide_a_newer_post_or_pending_checks(self):
        """Input: terminal identity followed by later unfinished activity. Output: protected, not a new archive marker."""
        retirement = self.module()
        path = self.source / 'simulation_events.jsonl'
        before = path.read_bytes()
        for suffix in (
            [dict(event='SUBMISSION_STARTED', attempt_id='second', expression_hash='candidate'),
             dict(event='SUBMITTED', attempt_id='second', expression_hash='candidate')],
            [dict(event='CHECK_PENDING', expression_hash='candidate')]):
            self.write(path, before + b''.join(json.dumps(row).encode() + b'\n' for row in suffix))
            self.assertEqual(retirement.audit_recovery_copy_retirement(self.run, self.copy_path)[
                'disposition'], 'protected')
        self.write(path, before)
        self.record(self.source / 'pending_checks/child.json', dict(status='pending', expression_hash='candidate'))
        self.assertEqual(retirement.audit_recovery_copy_retirement(self.run, self.copy_path)[
            'disposition'], 'protected')

    def test_sibling_archive_owner_metadata_does_not_block_the_other_copy(self):
        """Input: two exact jobs in one closed run. Output: verified first marker does not falsely pin second."""
        retirement = self.module()
        second_path = 'runtime/knowledge_recovery/' + 'b' * 20 + '/knowledge'
        second = self.run / second_path
        self.write(second / 'raw/other.md', b'other captured facts')
        self.record(second.parent / 'sources/facts.json', dict(original='evidence'))
        receipt = dict(self.receipt, knowledge_root=str(second), effective_root=str(second),
            receipt_path=str(second.parent / 'receipt.json'),
            evidence=dict(sources=[str(second.parent / 'sources/facts.json')]))
        self.record(second.parent / 'receipt.json', receipt)
        retirement.prepare_recovery_copy_retirement(self.run, self.copy_path)
        self.assertEqual(retirement.audit_recovery_copy_retirement(self.run, second_path)[
            'disposition'], 'archive_candidate')
        self.assertTrue(retirement.prepare_recovery_copy_retirement(self.run, second_path)['read_only'])

    def test_legacy_pending_check_receipt_prevents_archival(self):
        """Input: legacy pending check receipt. Output: refusal until resolved, then bind its exact bytes."""
        retirement = self.module()
        path = self.source / 'pending_checks.json'
        self.record(path, dict(phase='pending', checks=['SELF_CORRELATION']))
        self.assertEqual(retirement.audit_recovery_copy_retirement(self.run, self.copy_path)[
            'disposition'], 'protected')
        self.record(path, dict(status='resolved', checks=[]))
        marker = retirement.prepare_recovery_copy_retirement(self.run, self.copy_path)
        self.assertIn(path.relative_to(self.workspace).as_posix(), marker['evidence_refs'])

    def test_completed_console_job_routing_root_is_not_an_input_dependency(self):
        """Input: completed canonical CLI job routing root. Output: permit routing metadata, preserve explicit-copy/active references."""
        import sys
        from wqb.console_jobs import create_job, finish_job
        retirement = self.module()
        command = [sys.executable, '-m', 'wqb.cli', 'workflow-continue', '--run-dir', str(self.workspace / 'runs')]
        job = create_job(self.workspace / 'runs/console_jobs', 'workflow-continue', command,
                         self.workspace, metadata={})
        finish_job(job, 'completed')
        self.assertEqual(retirement.audit_recovery_copy_retirement(self.run, self.copy_path)[
            'disposition'], 'archive_candidate')
        path = Path(job.job_dir) / 'job.json'
        value = json.loads(path.read_bytes())
        self.record(path, dict(value, metadata=dict(run_dir=str(self.run))))
        self.assertEqual(retirement.audit_recovery_copy_retirement(self.run, self.copy_path)[
            'disposition'], 'archive_candidate')
        self.record(path, dict(value, metadata=dict(run_dir=str(self.run), input_path=str(self.copy))))
        self.assertEqual(retirement.audit_recovery_copy_retirement(self.run, self.copy_path)[
            'disposition'], 'protected')
        self.record(path, dict(value, action='workflow-start-from-option',
                              command=command[:3] + ['workflow-start'] + command[4:]))
        self.assertEqual(retirement.audit_recovery_copy_retirement(self.run, self.copy_path)[
            'disposition'], 'archive_candidate')
        self.record(path, dict(value, action='workflow-start-from-option',
                              command=command[:2] + ['wqb.console_start', 'workflow-start'] + command[4:]))
        self.assertEqual(retirement.audit_recovery_copy_retirement(self.run, self.copy_path)[
            'disposition'], 'archive_candidate')
        self.record(path, dict(value, status='failed', exit_code=1))
        self.assertEqual(retirement.audit_recovery_copy_retirement(self.run, self.copy_path)[
            'disposition'], 'archive_candidate')
        for action, cli, status in (
                ('workflow-auto-continue', 'workflow-run', 'blocked'),
                ('workflow-auto-continue', 'workflow-run', 'paused'),
                ('workflow-stop', 'workflow-pause', 'completed'),
                ('workflow-acknowledge-source-rate-limit', 'workflow-acknowledge-source-rate-limit', 'completed')):
            self.record(path, dict(value, action=action, status=status,
                                  command=command[:3] + [cli] + command[4:]))
            self.assertEqual(retirement.audit_recovery_copy_retirement(self.run, self.copy_path)[
                'disposition'], 'archive_candidate')
        self.record(path, dict(value, command=command[:-1] + [str(self.copy)]))
        self.assertEqual(retirement.audit_recovery_copy_retirement(self.run, self.copy_path)[
            'disposition'], 'protected')
        self.record(path, dict(value, status='running'))
        self.assertEqual(retirement.audit_recovery_copy_retirement(self.run, self.copy_path)[
            'disposition'], 'protected')

    def test_cancelled_start_intent_is_owner_identity_not_a_copy_input(self):
        """Input: canonical cancelled Start receipt. Output: ignore only closed-owner CAS identity, not input references."""
        retirement = self.module()
        path = self.workspace / 'runs/console_start/request.json'
        value = dict(request_id='c' * 32, status='cancelled', updated_at='2026-11-09T00:00:00+00:00',
                     source_intent=dict(run_dir=str(self.run), request_revision='original'))
        self.record(path, value)
        self.assertEqual(retirement.audit_recovery_copy_retirement(self.run, self.copy_path)[
            'disposition'], 'archive_candidate')
        self.record(path, dict(value, input_path=str(self.copy)))
        self.assertEqual(retirement.audit_recovery_copy_retirement(self.run, self.copy_path)[
            'disposition'], 'protected')
        self.record(path, dict(value, status='preparing'))
        self.assertEqual(retirement.audit_recovery_copy_retirement(self.run, self.copy_path)[
            'disposition'], 'protected')

    def test_authenticated_budget_store_root_is_not_a_scientific_input(self):
        """Input: valid shared policy, then altered policy. Output: route metadata accepted only after owner validation."""
        from wqb.daily_simulation_budget import ensure_daily_policy
        retirement = self.module()
        policy = ensure_daily_policy(self.workspace / 'runs')
        self.assertEqual(retirement.audit_recovery_copy_retirement(self.run, self.copy_path)[
            'disposition'], 'archive_candidate')
        self.record(self.workspace / 'runs/daily_simulation_budget/policy.json', dict(policy, limit=1))
        self.assertEqual(retirement.audit_recovery_copy_retirement(self.run, self.copy_path)[
            'disposition'], 'protected')

    def setUp(self):
        """Input: test instance. Output: isolated closed original-batch run and one knowledge copy."""
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.workspace = Path(self.tmp.name).resolve()
        self.run = self.workspace / 'runs/old'
        self.source = self.workspace / 'runs/source'
        self.copy_path = 'runtime/knowledge_recovery/' + 'a' * 20 + '/knowledge'
        self.copy = self.run / self.copy_path
        self.job = self.copy.parent
        self.write(self.copy / 'raw/facts.md', b'captured_at: 2026-07-30\r\nexact source bytes\r\n')
        self.write(self.copy / 'machine/scope.json', b'{"region":"USA","delay":1,"universe":"TOP3000"}')
        os.utime(self.copy / 'raw/facts.md', ns=(1234567890000000000, 1234567890123456789))
        self.record(self.job / 'sources/day/facts.md', {'source': 'original evidence'})
        self.receipt = dict(status='completed', phase='finished', generated_at='2026-10-11T12:00:00+00:00',
            scope=dict(region='USA', delay=1, universe='TOP3000'), knowledge_root=str(self.copy),
            effective_root=str(self.copy), receipt_path=str(self.job / 'receipt.json'),
            evidence=dict(sources=[str(self.job / 'sources/day/facts.md')]), errors=[])
        self.record(self.job / 'receipt.json', self.receipt)
        self.record(self.run / 'run_state.json', dict(status='aborted', run_dir=str(self.run),
            pause_reason='not used as proof'))
        self.record(self.run / 'runtime_status.json', dict(status='completed', simulation_attempts=1,
            elapsed_seconds=10, recovery_attempts=0, knowledge_recovery=self.receipt,
            last_result=dict(status='completed', next_action='original-batch-complete')))
        self.record(self.run / 'runtime_control.json', dict(desired_state='running', enable_live_api=True,
            request_revision='original', original_batch_scope_id='scope', max_simulations=4,
            max_recoveries=3, max_runtime_seconds=100))
        plan = b'{"expression":"rank(foo)","expression_hash":"candidate"}\n'
        self.write(self.source / 'planned_candidates.jsonl', plan)
        self.write(self.source / 'simulation_events.jsonl',
            b'{"event":"SUBMISSION_STARTED","attempt_id":"one","expression_hash":"candidate"}\n'
            b'{"event":"SUBMITTED","attempt_id":"one","expression_hash":"candidate"}\n'
            b'{"event":"CHECKED","expression_hash":"candidate"}\n')
        self.write(self.source / 'all_alphas.jsonl', b'')
        self.record(self.run / 'runtime/original_batch_scope.json', dict(scope_id='scope', settings=self.receipt['scope'],
            source_run_dir=str(self.source), plan_digest=hashlib.sha256(plan).hexdigest(),
            allowed_expressions=['rank(foo)'], max_recoveries=3, max_runtime_seconds=100,
            original_count=1, new_research_allowed=False))
        self.record(self.run / 'stages/scout_seed/source_bridge_binding.json', dict(source_run_dir=str(self.source)))
        for folder in (self.source, self.run / 'runtime'):
            self.record(folder / 'source_run_lock.json', dict(status='released'))

    def write(self, path, data):
        """Input: fixture Path/bytes. Output: None; create only temporary test files."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def record(self, path, value):
        """Input: fixture Path/JSON value. Output: None; write exact fixture evidence."""
        self.write(path, json.dumps(value, sort_keys=True).encode())

    def module(self):
        """Input: None. Output: retirement module, or assertion identifying the missing API."""
        from wqb import knowledge_recovery_retirement as retirement
        return retirement

    def snapshot(self):
        """Input: fixture tree. Output: file bytes map for original evidence mutation checks."""
        return {p.relative_to(self.workspace).as_posix(): p.read_bytes()
                for p in self.workspace.rglob('*') if p.is_file()}

    def test_audit_is_exact_path_readonly_and_not_execution_readiness(self):
        retirement = self.module()
        before = self.snapshot()
        result = retirement.audit_recovery_copy_retirement(self.run, self.copy_path)
        self.assertEqual(result['disposition'], 'archive_candidate', result)
        self.assertEqual(result['candidate_path'], str(self.copy))
        self.assertEqual(result['file_count'], 2)
        self.assertFalse(result['execution_authorized'])
        self.assertFalse(result['source_certified'])
        self.assertEqual(before, self.snapshot())
        for candidate in ('runtime/knowledge_recovery', self.copy_path + '/..', '../knowledge', str(self.copy)):
            self.assertEqual(retirement.audit_recovery_copy_retirement(self.run, candidate)['disposition'], 'protected')

    def test_active_paused_ambiguous_and_unknown_posts_stay_protected(self):
        retirement = self.module()
        state_path = self.run / 'run_state.json'
        for status in ('running', 'paused', 'blocked', 'unknown'):
            self.record(state_path, dict(status=status, pause_reason='finished original-only scope superseded'))
            self.assertEqual(retirement.audit_recovery_copy_retirement(self.run, self.copy_path)['disposition'], 'protected')
        self.record(state_path, dict(status='aborted'))
        self.write(self.source / 'simulation_events.jsonl',
            b'{"event":"SUBMISSION_STARTED","attempt_id":"unknown","expression_hash":"candidate"}\n')
        result = retirement.audit_recovery_copy_retirement(self.run, self.copy_path)
        self.assertEqual(result['disposition'], 'protected')
        self.assertIn('uncertain', str(result['reasons']))

    def test_incomplete_original_plan_active_lock_and_incomplete_receipt_refuse(self):
        retirement = self.module()
        events = self.source / 'simulation_events.jsonl'
        original = events.read_bytes()
        self.write(events, b'')
        self.assertEqual(retirement.audit_recovery_copy_retirement(self.run, self.copy_path)['disposition'], 'protected')
        self.write(events, original)
        self.record(self.source / 'source_run_lock.json', dict(status='acquired'))
        self.assertEqual(retirement.audit_recovery_copy_retirement(self.run, self.copy_path)['disposition'], 'protected')
        self.record(self.source / 'source_run_lock.json', dict(status='released'))
        self.record(self.job / 'receipt.json', dict(self.receipt, phase='captured'))
        self.assertEqual(retirement.audit_recovery_copy_retirement(self.run, self.copy_path)['disposition'], 'protected')

    def test_external_consumers_descendant_and_ancestor_paths_protect(self):
        retirement = self.module()
        owner = self.workspace / 'runs/paused/run_manifest.json'
        for target in (self.copy, self.copy / 'raw/facts.md', self.job):
            self.record(owner, dict(status='paused', knowledge_root=str(target)))
            result = retirement.audit_recovery_copy_retirement(self.run, self.copy_path)
            self.assertEqual(result['disposition'], 'protected')
            self.assertIn(str(owner), ' '.join(result['reasons']))

    def test_another_run_cannot_disguise_ancestor_dependency_as_routing(self):
        retirement = self.module()
        owner = self.workspace / 'runs/paused/run_manifest.json'
        for key in ('run_dir', 'source_run_dir', 'root'):
            self.record(owner, {key: str(self.run)})
            result = retirement.audit_recovery_copy_retirement(self.run, self.copy_path)
            self.assertEqual(result['disposition'], 'protected', key)

    def test_malformed_original_events_and_receipt_are_protected_not_uncaught(self):
        retirement = self.module()
        events = self.source / 'simulation_events.jsonl'
        before = events.read_bytes()
        for data in (b'[]\n', b'{"event":"CHECKED","event":"ERROR"}\n'):
            self.write(events, data)
            self.assertEqual(retirement.audit_recovery_copy_retirement(self.run, self.copy_path)['disposition'], 'protected')
        self.write(events, before)
        self.record(self.job / 'receipt.json', dict(self.receipt, evidence=[]))
        self.assertEqual(retirement.audit_recovery_copy_retirement(self.run, self.copy_path)['disposition'], 'protected')

    def test_marker_cannot_drop_original_evidence_bindings(self):
        retirement = self.module()
        retirement.prepare_recovery_copy_retirement(self.run, self.copy_path)
        path = self.job / retirement.RETIRED_MARKER
        marker = json.loads(path.read_bytes())
        marker['evidence_refs'] = {}
        self.record(path, marker)
        with self.assertRaises(ValueError):
            retirement.read_retired_recovery_file(self.run, self.copy_path, 'raw/facts.md')

    def test_prepare_read_and_controlled_restore_preserve_history_and_times(self):
        retirement = self.module()
        before = self.snapshot()
        original_mtime = (self.copy / 'raw/facts.md').stat().st_mtime_ns
        result = retirement.prepare_recovery_copy_retirement(self.run, self.copy_path)
        self.assertTrue(self.copy.is_dir())
        self.assertTrue(result['read_only'])
        self.assertEqual(retirement.read_retired_recovery_file(
            self.run, self.copy_path, 'raw/facts.md'), (self.copy / 'raw/facts.md').read_bytes())
        self.assertEqual(result, retirement.prepare_recovery_copy_retirement(self.run, self.copy_path))
        with self.assertRaises(ValueError):
            retirement.restore_retired_recovery_copy(self.run, self.copy_path, approval_reference='')
        restored = retirement.restore_retired_recovery_copy(self.run, self.copy_path, approval_reference='fixture only')
        destination = Path(restored['restored_path'])
        self.assertNotEqual(destination, self.copy)
        self.assertEqual((destination / 'raw/facts.md').stat().st_mtime_ns, original_mtime)
        self.assertEqual((destination / 'raw/facts.md').read_bytes(), (self.copy / 'raw/facts.md').read_bytes())
        for path, data in before.items():
            self.assertEqual((self.workspace / path).read_bytes(), data)

    def test_retired_missing_copy_cannot_refetch_even_after_revision_changes(self):
        retirement = self.module()
        retirement.prepare_recovery_copy_retirement(self.run, self.copy_path)
        # Simulate approved collection using a temporary-fixture rename, never deletion.
        self.copy.rename(self.job / 'fixture_saved_copy')
        before = self.snapshot()
        with patch.object(knowledge_recovery, '_copy_vault', side_effect=AssertionError('no copy')), \
                patch.object(knowledge_recovery, 'WQBClient', side_effect=AssertionError('no client')), \
                patch.object(knowledge_recovery, '_readiness', side_effect=AssertionError('no readiness')):
            result = knowledge_recovery.recover_knowledge(self.workspace / 'knowledge',
                self.receipt['scope'], '2026-11-09T12:00:00+00:00', self.run)
        self.assertEqual(result['status'], 'blocked')
        self.assertTrue(result['archival_history'])
        self.assertEqual(before, self.snapshot())

    def test_corrupt_marker_archive_and_original_evidence_never_grant_capture(self):
        retirement = self.module()
        result = retirement.prepare_recovery_copy_retirement(self.run, self.copy_path)
        archive = self.run / result['archive_ref']['path']
        original = archive.read_bytes()
        archive.write_bytes(b'corrupt')
        with self.assertRaises(ValueError):
            retirement.read_retired_recovery_file(self.run, self.copy_path, 'raw/facts.md')
        self.assertEqual(knowledge_recovery.recover_knowledge(self.workspace / 'knowledge',
            self.receipt['scope'], '2026-11-09T12:00:00+00:00', self.run)['status'], 'blocked')
        archive.write_bytes(original)
        self.record(self.job / 'receipt.json', dict(self.receipt, scope={'region': 'changed'}))
        with self.assertRaises(ValueError):
            retirement.read_retired_recovery_file(self.run, self.copy_path, 'raw/facts.md')

    def test_copy_links_bounds_and_archive_member_paths_refuse(self):
        retirement = self.module()
        alias = self.copy / 'raw/alias.md'
        os.link(self.copy / 'raw/facts.md', alias)
        self.assertEqual(retirement.audit_recovery_copy_retirement(self.run, self.copy_path)['disposition'], 'protected')
        alias.unlink()
        with patch.object(retirement, 'MAX_COPY_BYTES', 1):
            self.assertEqual(retirement.audit_recovery_copy_retirement(self.run, self.copy_path)['disposition'], 'protected')
        retirement.prepare_recovery_copy_retirement(self.run, self.copy_path)
        for name in ('../receipt.json', '/absolute', 'raw/../../receipt.json', 'C:/outside', 'raw\\facts.md'):
            with self.assertRaises(ValueError):
                retirement.read_retired_recovery_file(self.run, self.copy_path, name)

    def test_prepare_crash_does_not_publish_marker_and_retries_existing_archive(self):
        retirement = self.module()
        with patch.object(retirement, '_publish_marker', side_effect=OSError('fixture crash')):
            with self.assertRaises(OSError):
                retirement.prepare_recovery_copy_retirement(self.run, self.copy_path)
        self.assertFalse((self.job / retirement.RETIRED_MARKER).exists())
        result = retirement.prepare_recovery_copy_retirement(self.run, self.copy_path)
        self.assertTrue(result['read_only'])

    def test_recovery_root_overlap_does_not_create_guard_or_other_files(self):
        before = self.snapshot()
        result = knowledge_recovery.recover_knowledge(self.run, self.receipt['scope'],
            '2026-11-09T12:00:00+00:00', self.run)
        self.assertEqual(result['status'], 'blocked')
        self.assertEqual(before, self.snapshot())

    def test_unidentified_or_extra_pending_post_protects_closed_run(self):
        retirement = self.module()
        path = self.source / 'simulation_events.jsonl'
        before = path.read_bytes()
        for row in (dict(event='SUBMISSION_STARTED', expression_hash='candidate'),
                    dict(event='SUBMITTED', expression_hash='other')):
            self.write(path, before + json.dumps(row).encode() + b'\n')
            self.assertEqual(retirement.audit_recovery_copy_retirement(self.run, self.copy_path)['disposition'], 'protected')

    def test_prepare_and_restore_share_recovery_writer_guard(self):
        retirement = self.module()
        with patch.object(retirement, 'LOCK_SECONDS', .02), retirement.recovery_history_guard(self.run):
            with self.assertRaises(ValueError):
                retirement.prepare_recovery_copy_retirement(self.run, self.copy_path)
        self.assertFalse((self.job / retirement.RETIRED_MARKER).exists())

    def test_changed_evidence_before_marker_prevents_retirement(self):
        retirement = self.module()
        verify = retirement._verify_archive

        def change_after_archive(*args):
            """Input: archive verification arguments. Output: None; inject a fixture authority change."""
            verify(*args)
            self.record(self.run / 'runtime_control.json', dict(desired_state='paused'))

        with patch.object(retirement, '_verify_archive', side_effect=change_after_archive):
            with self.assertRaises(ValueError):
                retirement.prepare_recovery_copy_retirement(self.run, self.copy_path)
        self.assertFalse((self.job / retirement.RETIRED_MARKER).exists())
        self.assertTrue(self.copy.is_dir())

    def test_interrupted_restore_stays_isolated_and_can_retry(self):
        retirement = self.module()
        retirement.prepare_recovery_copy_retirement(self.run, self.copy_path)
        original = retirement._publish_no_replace

        def interrupt(source, target):
            """Input: stage/destination Paths. Output: None; fail only historical directory publication."""
            if source.is_dir():
                raise OSError('fixture interrupted restore')
            return original(source, target)

        with patch.object(retirement, '_publish_no_replace', side_effect=interrupt):
            with self.assertRaises(OSError):
                retirement.restore_retired_recovery_copy(self.run, self.copy_path, approval_reference='fixture')
        self.assertTrue(self.copy.is_dir())
        result = retirement.restore_retired_recovery_copy(self.run, self.copy_path, approval_reference='fixture')
        self.assertTrue(Path(result['restored_path']).is_dir())

    def test_invalid_marker_shapes_and_read_bounds_are_refused(self):
        retirement = self.module()
        marker = retirement.prepare_recovery_copy_retirement(self.run, self.copy_path)
        path = self.job / retirement.RETIRED_MARKER
        for values in (dict(archive_ref=[]), dict(manifest={}), dict(schema_version=True)):
            self.record(path, dict(marker, **values))
            with self.assertRaises(ValueError):
                retirement.read_retired_recovery_file(self.run, self.copy_path, 'raw/facts.md')
        self.record(path, marker)
        with self.assertRaises(ValueError):
            retirement.read_retired_recovery_file(self.run, self.copy_path, 'raw/facts.md', max_bytes=1)

    def test_unexpected_zip_members_refuse_even_with_changed_container_hash(self):
        """Input: fixture ZIP with an injected traversal name. Output: refusal, no extraction or outside writes."""
        retirement = self.module()
        marker = retirement.prepare_recovery_copy_retirement(self.run, self.copy_path)
        path = self.run / marker['archive_ref']['path']
        with zipfile.ZipFile(path, 'a') as archive:
            archive.writestr('../outside', b'not allowed')
        marker['archive_ref']['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
        self.record(self.job / retirement.RETIRED_MARKER, marker)
        with self.assertRaises(ValueError):
            retirement.read_retired_recovery_file(self.run, self.copy_path, 'raw/facts.md')
        self.assertFalse((self.job / 'outside').exists())

    def test_run_relative_consumer_in_deep_manifest_is_protected(self):
        """Input: deep run manifest with a run-relative copy selector. Output: explicit consumer protection."""
        retirement = self.module()
        self.record(self.run / 'stages/other/context.json', dict(knowledge_root=self.copy_path))
        self.assertEqual(retirement.audit_recovery_copy_retirement(self.run, self.copy_path)['disposition'], 'protected')

    def test_new_consumer_created_while_archiving_prevents_marker(self):
        """Input: consumer appearing after initial scan. Output: no retirement marker or removal."""
        retirement = self.module()
        verify = retirement._verify_archive

        def add_consumer(*args):
            """Input: verifier arguments. Output: None; add a temporary consumer after archive verification."""
            verify(*args)
            self.record(self.workspace / 'runs/paused/context.json', dict(knowledge_root=str(self.copy)))

        with patch.object(retirement, '_verify_archive', side_effect=add_consumer):
            with self.assertRaises(ValueError):
                retirement.prepare_recovery_copy_retirement(self.run, self.copy_path)
        self.assertFalse((self.job / retirement.RETIRED_MARKER).exists())

    def test_post_prepare_audit_authenticates_history_without_writes(self):
        """Input: prepared historical copy. Output: re-auditable history, not live authority or deletion."""
        retirement = self.module()
        retirement.prepare_recovery_copy_retirement(self.run, self.copy_path)
        before = self.snapshot()
        result = retirement.audit_recovery_copy_retirement(self.run, self.copy_path)
        self.assertEqual(result['disposition'], 'archived_history', result)
        self.assertTrue(result['expanded_copy_present'])
        self.assertEqual(before, self.snapshot())

    def test_reference_context_caches_negatives_without_hiding_routing_evidence(self):
        """Input: repeated ordinary paths plus differently declared root references. Output: cached negatives, same protections."""
        retirement = self.module()
        owner = self.run / 'runtime_status.json'
        context = retirement._reference_context(self.workspace, owner, self.copy)
        deadline = retirement.time.monotonic() + 10
        original = retirement.os.path.abspath
        with patch.object(retirement.os.path, 'abspath', wraps=original) as normalize:
            for index in range(20):
                self.assertFalse(retirement._refers(dict(path='raw/platform/facts.md'),
                    self.workspace, owner, self.copy, deadline, context=context))
            self.assertLessEqual(normalize.call_count, len(context[0]))
        self.assertFalse(retirement._refers(dict(root=str(self.workspace)),
            self.workspace, owner, self.copy, deadline, context=context))
        self.assertTrue(retirement._refers(dict(evidence_path=str(self.workspace)),
            self.workspace, owner, self.copy, deadline, context=context))

    def test_plain_relative_ancestor_names_still_protect(self):
        """Input: plain relative ancestor selector. Output: protection, not semantic-label fast rejection."""
        retirement = self.module()
        self.record(self.workspace / 'runs/paused/context.json', dict(evidence_path='runs'))
        self.assertEqual(retirement.audit_recovery_copy_retirement(self.run, self.copy_path)['disposition'], 'protected')

    def test_unrelated_terminal_reject_retains_dotted_and_descendant_references(self):
        """Input: impossible paths and possible normalized references. Output: no path work for impossibilities only."""
        retirement = self.module()
        owner = self.run / 'stages/other/context.json'
        context = retirement._reference_context(self.workspace, owner, self.copy)
        deadline = retirement.time.monotonic() + 10
        with patch.object(retirement.os.path, 'abspath', side_effect=AssertionError('unrelated normalization')):
            for name in ('raw/platform/source.md', '2026-07-30T01:00:00+00:00', 'return / float'):
                self.assertFalse(retirement._refers(dict(path=name), self.workspace, owner,
                    self.copy, deadline, context=context))
        for name in (str(self.copy / 'raw/facts.md'), self.copy_path + '/raw/facts.md',
                     self.copy_path + '/raw/../raw/facts.md', str(self.copy / '..'), 'runs/old/runtime/..'):
            self.assertTrue(retirement._refers(dict(path=name), self.workspace, owner,
                self.copy, deadline, context=context), name)
