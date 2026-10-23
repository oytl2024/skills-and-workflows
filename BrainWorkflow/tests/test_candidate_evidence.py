import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from wqb.checker import fetch_check_summary


def platform_payloads():
    """Input: none. Output: tuple[dict, dict]; synthetic unsubmitted Alpha and full check evidence."""
    baseline = [{"name": "LOW_SHARPE", "result": "PASS"},
                {"name": "LOW_FITNESS", "result": "PASS"}]
    detail = {"id": "alpha1", "status": "UNSUBMITTED", "regular": {"code": "rank(close)"},
              "settings": {"region": "USA", "delay": 1, "decay": 4},
              "is": {"sharpe": 1.8, "fitness": 1.3, "checks": baseline}}
    checks = {"is": {"checks": [
        {"name": "SELF_CORRELATION", "result": "PASS", "value": 0.2},
        {"name": "PROD_CORRELATION", "result": "PASS", "value": 0.3},
        {"name": "MATCHES_THEMES", "result": "WARNING"}]}, "checkTime": "2026-10-11T00:00:00Z"}
    return detail, checks


class CandidateEvidenceTests(unittest.TestCase):
    def test_self_pool_capture_timeout_returns_unreadable_and_cannot_save_after_release(self):
        """Input: real held SELF guard, existing/absent cache fixtures. Output: assertions; timeout never supplies a reusable revision."""
        from concurrent.futures import ThreadPoolExecutor
        from wqb.candidate_evidence import (SELF_POOL_REVISION_FILENAME, capture_evidence_revision,
            invalidate_self_pool, save_candidate_evidence)
        from wqb.lockfile import json_lock_transition_guard
        save_candidate_evidence(self.client, 'alpha1', self.detail, self.checks)
        saved = self.evidence_files()[0].read_bytes()
        guard = self.root / 'machine/candidate_evidence' / SELF_POOL_REVISION_FILENAME
        with patch('wqb.candidate_evidence.EVIDENCE_LOCK_TIMEOUT_SECONDS', 0.02):
            with ThreadPoolExecutor(max_workers=1) as worker:
                with json_lock_transition_guard(guard, 1.0, 0.01, 'fixture SELF guard'):
                    revisions = [worker.submit(capture_evidence_revision, self.client, alpha_id).result(timeout=2)
                                 for alpha_id in ('alpha1', 'absent')]
        self.assertEqual(revisions, ['unreadable', 'unreadable'])
        invalidate_self_pool(self.root, 'manual:timeout-fixture')
        for alpha_id, revision in zip(('alpha1', 'absent'), revisions):
            detail = dict(self.detail, id=alpha_id)
            audit = save_candidate_evidence(self.client, alpha_id, detail, self.checks, revision)
            self.assertEqual(audit['persistence_status'], 'superseded')
        self.assertEqual(len(self.evidence_files()), 1)
        self.assertEqual(self.evidence_files()[0].read_bytes(), saved)

    def test_self_pool_lock_timeout_does_not_abort_fake_check_fetch(self):
        """Input: held real SELF guard and fake platform payloads. Output: assertions; fetch continues without caching unverifiable evidence."""
        from concurrent.futures import ThreadPoolExecutor
        from wqb.candidate_evidence import SELF_POOL_REVISION_FILENAME, load_candidate_evidence
        from wqb.lockfile import json_lock_transition_guard
        guard = self.root / 'machine/candidate_evidence' / SELF_POOL_REVISION_FILENAME
        with patch('wqb.candidate_evidence.EVIDENCE_LOCK_TIMEOUT_SECONDS', 0.02):
            with ThreadPoolExecutor(max_workers=1) as worker:
                with json_lock_transition_guard(guard, 1.0, 0.01, 'fixture SELF guard'):
                    summary = worker.submit(fetch_check_summary, self.client, 'alpha1').result(timeout=2)
        self.assertTrue(summary.hard_pass)
        self.assertEqual(self.client.get_json.call_count, 2)
        self.assertEqual(summary.metrics['candidate_evidence']['persistence_status'], 'failed')
        self.assertIsNone(load_candidate_evidence(self.client, 'alpha1'))
        self.assertEqual(self.evidence_files(), [])

    def test_self_pool_change_invalidates_existing_and_absent_inflight_entries_once(self):
        from wqb.candidate_evidence import (capture_evidence_revision, invalidate_self_pool,
            save_candidate_evidence, load_candidate_evidence)
        save_candidate_evidence(self.client, 'alpha1', self.detail, self.checks)
        saved = self.evidence_files()[0].read_bytes()
        existing_revision = capture_evidence_revision(self.client, 'alpha1')
        absent_revision = capture_evidence_revision(self.client, 'absent')
        invalidate_self_pool(self.root, 'manual:submitted-alpha')
        self.assertIsNone(load_candidate_evidence(self.client, 'alpha1'))
        self.assertEqual(self.evidence_files()[0].read_bytes(), saved)
        self.assertEqual(save_candidate_evidence(self.client, 'alpha1', self.detail, self.checks, existing_revision)['persistence_status'], 'superseded')
        detail = dict(self.detail, id='absent')
        self.assertEqual(save_candidate_evidence(self.client, 'absent', detail, self.checks, absent_revision)['persistence_status'], 'superseded')
        fresh_revision = capture_evidence_revision(self.client, 'alpha1')
        invalidate_self_pool(self.root, 'manual:submitted-alpha')
        self.assertEqual(capture_evidence_revision(self.client, 'alpha1'), fresh_revision)
        self.assertEqual(save_candidate_evidence(self.client, 'alpha1', self.detail, self.checks, fresh_revision)['persistence_status'], 'persisted')
        self.assertIsNotNone(load_candidate_evidence(self.client, 'alpha1'))

    def test_same_timestamp_invalidations_are_distinct_events(self):
        """Input: two invalidations with identical clocks. Output: assertions. A later event still defeats older checks."""
        from wqb.candidate_evidence import capture_evidence_revision, invalidate_candidate_evidence, save_candidate_evidence
        with patch('time.time', return_value=1000):
            invalidate_candidate_evidence(self.client, 'alpha1')
            before = capture_evidence_revision(self.client, 'alpha1')
            invalidate_candidate_evidence(self.client, 'alpha1')
            result = save_candidate_evidence(self.client, 'alpha1', self.detail, self.checks, before)
        self.assertEqual(result['persistence_status'], 'superseded')

    def test_inflight_check_cannot_overwrite_later_invalidation(self):
        """Input: invalidation during a platform check. Output: assertions. Only a later fresh check can restore reuse."""
        from wqb.candidate_evidence import invalidate_candidate_evidence, load_candidate_evidence

        def respond(path):
            """Input: endpoint str. Output: synthetic response dict. Invalidate while the first check is in flight."""
            if path.endswith('/check'):
                invalidate_candidate_evidence(self.client, 'alpha1', 'account_changed')
                return self.checks
            return self.detail

        self.client.get_json.side_effect = respond
        result = fetch_check_summary(self.client, 'alpha1')
        self.assertTrue(result.hard_pass)
        self.assertIsNone(load_candidate_evidence(self.client, 'alpha1'))
        self.assertEqual(result.metrics['candidate_evidence']['persistence_status'], 'superseded')
        self.client.get_json.side_effect = [self.detail, self.checks]
        fetch_check_summary(self.client, 'alpha1')
        self.assertIsNotNone(load_candidate_evidence(self.client, 'alpha1'))

    def setUp(self):
        """Input: none. Output: none; isolate all evidence in a temporary knowledge root."""
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.client = Mock()
        self.client.knowledge_root = self.root
        self.detail, self.checks = platform_payloads()
        self.client.get_json.side_effect = [self.detail, self.checks] * 3

    def evidence_files(self):
        """Input: none. Output: list[Path]; inspect only machine candidate evidence."""
        return list((self.root / "machine" / "candidate_evidence").glob("*.json"))

    def test_repeat_reuses_complete_evidence_before_any_request_and_across_clients(self):
        first = fetch_check_summary(self.client, "alpha1")
        fresh_client = Mock()
        fresh_client.knowledge_root = self.root
        fresh_client.get_json.side_effect = AssertionError("cache hit must make no platform request")
        second = fetch_check_summary(fresh_client, "alpha1")
        self.assertEqual(first.hard_pass, second.hard_pass)
        self.assertEqual(first.warnings, second.warnings)
        self.assertEqual(first.metrics["sharpe"], second.metrics["sharpe"])
        self.assertEqual(first.metrics["candidate_evidence"]["evidence_source"], "fresh")
        self.assertEqual(second.metrics["candidate_evidence"]["evidence_source"], "cached")
        fresh_client.get_json.assert_not_called()
        self.assertEqual(len(self.evidence_files()), 1)
        record = json.loads(self.evidence_files()[0].read_text(encoding="utf-8"))
        self.assertEqual(record["alpha_detail"], self.detail)
        self.assertEqual(record["check_response"], self.checks)
        self.assertEqual(record["identity"]["expression"], "rank(close)")
        self.assertEqual(record["identity"]["settings"], self.detail["settings"])
        self.assertFalse((self.root / "human.md").exists())

    def test_no_explicit_real_root_leaves_existing_clients_uncached(self):
        for root in (None, Mock(), "relative-knowledge"):
            with self.subTest(root=root):
                client = Mock()
                if root is not None:
                    client.knowledge_root = root
                client.get_json.side_effect = [self.detail, self.checks] * 2
                fetch_check_summary(client, "alpha1")
                fetch_check_summary(client, "alpha1")
                self.assertEqual(client.get_json.call_count, 4)
        self.assertEqual(self.evidence_files(), [])

    def test_only_verified_unsubmitted_identity_can_be_persisted(self):
        mutations = [{"id": "other"}, {"id": None}, {"status": "SUBMITTED"}, {"status": None},
                     {"regular": {}}, {"regular": {"code": " "}}, {"settings": {}},
                     {"settings": None}, {"settings": {"delay": float("nan")}}]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                detail = {**self.detail, **mutation}
                self.client.get_json.side_effect = [detail, self.checks]
                fetch_check_summary(self.client, "alpha1")
                self.assertEqual(self.evidence_files(), [])

    def test_pending_failed_or_missing_full_correlation_not_reusable(self):
        for result in ("PENDING", "FAIL", "WARNING", None):
            with self.subTest(result=result):
                checks = copy.deepcopy(self.checks)
                if result is None:
                    checks["is"]["checks"].pop(1)
                else:
                    checks["is"]["checks"][1]["result"] = result
                self.client.get_json.side_effect = [self.detail, checks] * 2
                fetch_check_summary(self.client, "alpha1")
                fetch_check_summary(self.client, "alpha1")
                self.assertEqual(self.evidence_files(), [])

    def test_baseline_failure_never_fetches_or_persists_full_check(self):
        self.detail["is"]["checks"][0]["result"] = "FAIL"
        self.client.get_json.side_effect = [self.detail]
        self.assertFalse(fetch_check_summary(self.client, "alpha1").hard_pass)
        self.assertEqual(self.client.get_json.call_count, 1)
        self.assertEqual(self.evidence_files(), [])

    def test_expired_disabled_or_invalid_validity_forces_fresh_requests(self):
        for validity in (1, 0, -1, True, 8 * 24 * 60 * 60, float("inf"), float("nan"), "invalid"):
            with self.subTest(validity=validity):
                self.client.get_json.reset_mock()
                self.client.candidate_evidence_max_age_seconds = validity
                self.client.get_json.side_effect = [self.detail, self.checks] * 2
                with patch("time.time", return_value=1000):
                    fetch_check_summary(self.client, "alpha1")
                with patch("time.time", return_value=1002):
                    fetch_check_summary(self.client, "alpha1")
                self.assertEqual(self.client.get_json.call_count, 4)

    def test_corruption_and_identity_tampering_fail_closed(self):
        fetch_check_summary(self.client, "alpha1")
        self.assertEqual(len(self.evidence_files()), 1)
        path = self.evidence_files()[0]
        original = path.read_text(encoding="utf-8")
        for replacement in ("{", "[]", "null"):
            path.write_text(replacement, encoding="utf-8")
            calls_before = self.client.get_json.call_count
            self.client.get_json.side_effect = [self.detail, self.checks]
            fetch_check_summary(self.client, "alpha1")
            self.assertEqual(self.client.get_json.call_count, calls_before + 2)
        record = json.loads(original)
        record["identity"]["settings"]["decay"] = 99
        path.write_text(json.dumps(record), encoding="utf-8")
        self.client.get_json.reset_mock()
        self.client.get_json.side_effect = [self.detail, self.checks]
        fetch_check_summary(self.client, "alpha1")
        self.assertEqual(self.client.get_json.call_count, 2)

    def test_explicit_invalidation_requires_new_platform_evidence(self):
        fetch_check_summary(self.client, "alpha1")
        self.assertEqual(len(self.evidence_files()), 1)
        from wqb.candidate_evidence import invalidate_candidate_evidence
        invalidate_candidate_evidence(self.client, "alpha1")
        fetch_check_summary(self.client, "alpha1")
        self.assertEqual(self.client.get_json.call_count, 4)

    def test_invalidation_retains_verified_identity_raw_evidence_and_original_times(self):
        from wqb.candidate_evidence import invalidate_candidate_evidence, load_candidate_evidence
        with patch("time.time", return_value=1000):
            fetch_check_summary(self.client, "alpha1")
        path = self.evidence_files()[0]
        original = json.loads(path.read_text(encoding="utf-8"))
        with patch("time.time", return_value=1001):
            invalidate_candidate_evidence(self.client, "alpha1")
            self.assertIsNone(load_candidate_evidence(self.client, "alpha1"))
        invalidated = json.loads(path.read_text(encoding="utf-8"))
        for key in ("identity", "alpha_detail", "check_response", "checked_at", "expires_at"):
            self.assertIn(key, invalidated)
            self.assertEqual(invalidated[key], original[key])
        self.assertTrue(invalidated["invalidated"])
        self.assertEqual(invalidated["invalidation_reason"], "explicit_invalidation")
        self.assertEqual(invalidated["invalidated_at"], 1001)

    def test_custom_invalidation_reason_is_retained_and_corrupt_evidence_is_not_erased(self):
        from wqb.candidate_evidence import invalidate_candidate_evidence
        fetch_check_summary(self.client, "alpha1")
        path = self.evidence_files()[0]
        invalidate_candidate_evidence(self.client, "alpha1", reason="actual_submit_confirmed")
        record = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(record["invalidation_reason"], "actual_submit_confirmed")
        path.write_text("{corrupt evidence", encoding="utf-8")
        with self.assertRaises(ValueError):
            invalidate_candidate_evidence(self.client, "alpha1")
        self.assertEqual(path.read_text(encoding="utf-8"), "{corrupt evidence")

    def test_invalidation_still_works_while_reuse_is_disabled(self):
        fetch_check_summary(self.client, "alpha1")
        from wqb.candidate_evidence import invalidate_candidate_evidence
        self.client.candidate_evidence_max_age_seconds = 0
        invalidate_candidate_evidence(self.client, "alpha1")
        del self.client.candidate_evidence_max_age_seconds
        fetch_check_summary(self.client, "alpha1")
        self.assertEqual(self.client.get_json.call_count, 4)

    def test_response_cannot_replace_first_detail_identity(self):
        for echoed in ({"id": "other"}, {"regular": {"code": "rank(open)"}},
                       {"settings": {"region": "CHN"}}, {"status": "SUBMITTED"}):
            with self.subTest(echoed=echoed):
                self.client.get_json.side_effect = [self.detail, {**self.checks, **echoed}]
                fetch_check_summary(self.client, "alpha1")
                self.assertEqual(self.evidence_files(), [])

    def test_cache_hits_do_not_extend_original_expiry(self):
        self.client.candidate_evidence_max_age_seconds = 10
        with patch("time.time", return_value=1000):
            first = fetch_check_summary(self.client, "alpha1")
        original = self.evidence_files()[0].read_bytes()
        with patch("time.time", return_value=1009):
            cached = fetch_check_summary(self.client, "alpha1")
            self.assertEqual(cached.hard_pass, first.hard_pass)
            self.assertEqual(cached.metrics["candidate_evidence"]["checked_at"], 1000)
            self.assertEqual(cached.metrics["candidate_evidence"]["expires_at"], 1010)
        self.assertEqual(self.evidence_files()[0].read_bytes(), original)
        with patch("time.time", return_value=1010):
            fetch_check_summary(self.client, "alpha1")
        self.assertEqual(self.client.get_json.call_count, 4)

    def test_future_dated_evidence_is_not_reused(self):
        with patch("time.time", return_value=1000):
            fetch_check_summary(self.client, "alpha1")
        with patch("time.time", return_value=999):
            fetch_check_summary(self.client, "alpha1")
        self.assertEqual(self.client.get_json.call_count, 4)

    def test_corrupt_raw_checks_with_valid_digest_still_fail_semantic_validation(self):
        import hashlib
        fetch_check_summary(self.client, "alpha1")
        path = self.evidence_files()[0]
        record = json.loads(path.read_text(encoding="utf-8"))
        record["check_response"]["is"]["checks"][0]["result"] = "PENDING"
        record.pop("integrity_sha256")
        record["integrity_sha256"] = hashlib.sha256(json.dumps(
            record, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()
        path.write_text(json.dumps(record), encoding="utf-8")
        fetch_check_summary(self.client, "alpha1")
        self.assertEqual(self.client.get_json.call_count, 4)

    def test_settings_identity_preserves_json_types_not_python_coercion(self):
        import hashlib
        fetch_check_summary(self.client, "alpha1")
        path = self.evidence_files()[0]
        record = json.loads(path.read_text(encoding="utf-8"))
        record["identity"]["settings"]["delay"] = True
        record.pop("integrity_sha256")
        record["integrity_sha256"] = hashlib.sha256(json.dumps(
            record, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()
        path.write_text(json.dumps(record), encoding="utf-8")
        fetch_check_summary(self.client, "alpha1")
        self.assertEqual(self.client.get_json.call_count, 4)

    def test_storage_failure_does_not_change_platform_summary(self):
        with patch("wqb.candidate_evidence._write_record", side_effect=OSError("read only")):
            first = fetch_check_summary(self.client, "alpha1")
        self.assertTrue(first.hard_pass)
        self.assertEqual(self.evidence_files(), [])
        audit = first.metrics["candidate_evidence"]
        self.assertEqual(audit["evidence_source"], "fresh")
        self.assertEqual(audit["persistence_status"], "failed")
        self.assertEqual(audit["persistence_error"], "OSError")
        self.assertIsNone(audit["expires_at"])
        second = fetch_check_summary(self.client, "alpha1")
        self.assertEqual(self.client.get_json.call_count, 4)
        self.assertEqual(second.metrics["candidate_evidence"]["evidence_source"], "fresh")
        self.assertEqual(second.metrics["candidate_evidence"]["persistence_status"], "persisted")

    def test_malformed_platform_metrics_still_get_fresh_ineligible_audit(self):
        for metrics in (None, [], 0):
            with self.subTest(metrics=metrics):
                self.client.get_json.side_effect = [{"is": metrics}]
                summary = fetch_check_summary(self.client, "alpha1")
                self.assertFalse(summary.hard_pass)
                self.assertEqual(summary.metrics["candidate_evidence"]["evidence_source"], "fresh")
                self.assertEqual(summary.metrics["candidate_evidence"]["persistence_status"], "ineligible")

    def test_save_returns_explicit_status_and_raw_metrics_stay_unmodified(self):
        from wqb.candidate_evidence import save_candidate_evidence
        with patch("time.time", return_value=1000):
            status = save_candidate_evidence(self.client, "alpha1", self.detail, self.checks)
        self.assertIsInstance(status, dict)
        self.assertEqual(status["persistence_status"], "persisted")
        self.assertEqual(status["checked_at"], 1000)
        self.assertEqual(status["expires_at"], 1000 + 24 * 60 * 60)
        with patch("wqb.candidate_evidence._write_record", side_effect=OSError("read only")):
            status = save_candidate_evidence(self.client, "alpha1", self.detail, self.checks)
        self.assertEqual(status["persistence_status"], "failed")
        self.assertIsNone(status["expires_at"])
        self.assertNotIn("candidate_evidence", self.detail["is"])

    def test_disabled_and_ineligible_fresh_results_never_claim_persistence(self):
        del self.client.knowledge_root
        summary = fetch_check_summary(self.client, "alpha1")
        self.assertTrue(summary.hard_pass)
        self.assertEqual(summary.metrics["candidate_evidence"]["persistence_status"], "disabled")
        self.detail["is"]["checks"][0]["result"] = "FAIL"
        self.client.get_json.side_effect = [self.detail]
        summary = fetch_check_summary(self.client, "alpha1")
        self.assertFalse(summary.hard_pass)
        self.assertEqual(summary.metrics["candidate_evidence"]["evidence_source"], "fresh")
        self.assertEqual(summary.metrics["candidate_evidence"]["persistence_status"], "ineligible")
        self.assertIsNone(summary.metrics["candidate_evidence"]["expires_at"])

    def test_cached_audit_reports_effective_shortened_expiry(self):
        with patch("time.time", return_value=1000):
            fresh = fetch_check_summary(self.client, "alpha1")
        self.client.candidate_evidence_max_age_seconds = 10
        with patch("time.time", return_value=1001):
            cached = fetch_check_summary(self.client, "alpha1")
        self.assertEqual(fresh.metrics["candidate_evidence"]["expires_at"], 1000 + 24 * 60 * 60)
        self.assertEqual(cached.metrics["candidate_evidence"]["expires_at"], 1010)
        self.assertEqual(cached.metrics["candidate_evidence"]["checked_at"], 1000)
        self.assertEqual(cached.metrics["candidate_evidence"]["persistence_status"], "persisted")
        self.assertNotIn("candidate_evidence", self.detail["is"])

    def test_cli_build_client_only_attaches_explicit_absolute_root(self):
        from wqb.cli import build_client
        config = {"request_timeout_seconds": 10, "max_retries": 2, "base_backoff_seconds": 1}
        for root in (None, str(self.root), "relative"):
            with self.subTest(root=root), patch("wqb.cli.WQBClient") as constructor:
                client = constructor.return_value
                client.__dict__.pop("knowledge_root", None)
                configured = dict(config)
                if root is not None:
                    configured["knowledge_root"] = root
                build_client(configured)
                if root == str(self.root):
                    self.assertEqual(client.knowledge_root, self.root)
                else:
                    self.assertNotIn("knowledge_root", vars(client))
