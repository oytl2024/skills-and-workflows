import tempfile
import unittest
import json
import hashlib
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

from wqb.research_record import (
    empty_research_record,
    load_research_record_ledger,
    load_research_record,
    record_alpha_result,
    record_candidate_gate,
    record_repair_version,
    render_research_record_markdown,
    sync_research_record_to_machine,
    sync_research_record_to_raw,
    write_research_record,
)
from wqb.knowledge_contracts import parse_markdown_front_matter
from wqb.knowledge_freshness import evaluate_knowledge_contract_health


class ManualSubmissionTests(unittest.TestCase):
    def setUp(self):
        """Input: none. Output: isolated run, indexed report and ledger fixture paths."""
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'knowledge'
        self.run = Path(self.temp.name) / 'runs/run-a'
        self.expression = 'rank(ts_zscore(vec_avg(buzz_trend_metric_10), 120))'
        self.settings = dict(region='USA', delay=1, universe='TOP3000', instrumentType='EQUITY', decay=2)
        self.alpha = dict(alpha_id='alpha1', expression=self.expression, settings=self.settings,
                          expression_hash=hashlib.sha256(json.dumps([self.expression, self.settings], sort_keys=True).encode()).hexdigest(),
                          hard_pass=False, failed=['PROD_CORRELATION'],
                          metrics={'checks': [{'name': 'SELF_CORRELATION', 'result': 'PENDING'}]})
        self.record = record_alpha_result(empty_research_record('run-a', 'fixture'), self.alpha)
        write_research_record(self.run / 'research_record.json', self.record)
        (self.run / 'all_alphas.jsonl').write_text(json.dumps(self.alpha) + '\n', encoding='utf-8')
        self.report = self.make_report('alpha1')
        self.ledger = self.root / 'machine/data_ledger.jsonl'
        self.ledger.write_text(json.dumps(dict(dataset_id='ai_equity_alpha', field_id='buzz_trend_metric_10',
            field_type='VECTOR', region='USA', delay=1, universe='TOP3000', instrument_type='EQUITY',
            submitted_usage_count=3)) + '\n', encoding='utf-8')

    def make_report(self, alpha_id, name=None):
        """Input: Alpha/name str. Output: Path. Register an immutable-shape direct report fixture."""
        from wqb.knowledge_contracts import SourceIndexRow, render_front_matter, upsert_source_index_rows
        path = self.root / 'raw/community/user_messages/2026-10-15' / (name or f'manual-submission-{alpha_id}.md')
        path.parent.mkdir(parents=True, exist_ok=True)
        relative = path.relative_to(self.root).as_posix()
        body = f'# Manual Submission Report: {alpha_id}\n\nThe user reports that Alpha {alpha_id} was manually submitted.\n'
        meta = dict(source_type='user_report', source_family='raw/community/user_messages', source_path=relative,
                    captured_at='2026-10-15T14:39:05+00:00', capture_tool='codex_user_report', content_status='raw_markdown',
                    record_count=1, content_hash=hashlib.sha256(body.encode()).hexdigest(), update_check='user correction', compiled_targets=[])
        path.write_text(render_front_matter(meta) + body, encoding='utf-8')
        upsert_source_index_rows(self.root, [SourceIndexRow(path=relative, contents='report', **{
            key: meta[key] for key in ('source_type', 'source_family', 'captured_at', 'content_status', 'record_count', 'content_hash', 'update_check', 'compiled_targets')})])
        return path

    def reconcile(self, path=None):
        """Input: optional report Path. Output: reconciliation dict from the production entry."""
        from wqb.research_record import reconcile_manual_submission
        return reconcile_manual_submission(self.root, self.run, path or self.report, '2026-10-16T00:00:00+00:00')

    def test_replay_preserves_checks_unknown_time_and_absent_queue(self):
        first = self.reconcile()
        self.assertEqual(first['status'], 'reconciled', first)
        before = (self.run / 'research_record.json').read_bytes()
        second = self.reconcile()
        self.assertEqual(second['status'], 'reconciled', second)
        self.assertEqual((self.run / 'research_record.json').read_bytes(), before)
        record = load_research_record(self.run / 'research_record.json')
        self.assertEqual(record.backtest, self.record.backtest)
        self.assertEqual(record.triage, self.record.triage)
        self.assertEqual(len(record.manual_submission_status), 1)
        self.assertIsNone(record.manual_submission_status[0]['submitted_at'])
        self.assertEqual(record.user_approval, [])
        self.assertFalse((self.run / 'approved_candidates.jsonl').exists())
        usage = json.loads(self.ledger.read_text())
        self.assertEqual(usage['submitted_usage_count'], 4)
        self.assertEqual(usage['submitted_legacy_usage_count'], 3)
        self.assertEqual(usage['submitted_alpha_ids'], ['alpha1'])
        self.assertEqual(len(load_research_record_ledger(self.root)), 1)
        self.assertIn('alpha1', (self.root / 'raw/research/runs/run-a/research_record.md').read_text())

    def test_distinct_reports_same_alpha_and_distinct_alphas(self):
        self.reconcile()
        self.reconcile(self.make_report('alpha1', 'repeat.md'))
        row = dict(self.alpha, alpha_id='alpha2')
        write_research_record(self.run / 'research_record.json', record_alpha_result(load_research_record(self.run / 'research_record.json'), row))
        with (self.run / 'all_alphas.jsonl').open('a', encoding='utf-8') as handle:
            handle.write(json.dumps(row) + '\n')
        self.assertEqual(self.reconcile(self.make_report('alpha2'))['status'], 'reconciled')
        self.assertEqual(json.loads(self.ledger.read_text())['submitted_usage_count'], 5)
        self.assertEqual(len(load_research_record(self.run / 'research_record.json').manual_submission_status), 2)

    def test_unmatched_or_conflicting_identity_writes_no_usage(self):
        for rows in ([dict(self.alpha, alpha_id='other')], [self.alpha, dict(self.alpha, settings={**self.settings, 'decay': 7})]):
            with self.subTest(rows=rows):
                (self.run / 'all_alphas.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in rows), encoding='utf-8')
                before = self.ledger.read_bytes()
                self.assertEqual(self.reconcile()['status'], 'blocked')
                self.assertEqual(self.ledger.read_bytes(), before)
                self.assertEqual(load_research_record(self.run / 'research_record.json').manual_submission_status, [])

    def test_unindexed_or_changed_report_rejected(self):
        self.report.write_text(self.report.read_text() + 'changed', encoding='utf-8')
        self.assertEqual(self.reconcile()['status'], 'blocked')
        self.assertEqual(json.loads(self.ledger.read_text())['submitted_usage_count'], 3)

    def test_partial_projection_retry_is_idempotent(self):
        with patch('wqb.research_record.sync_research_record_to_raw', side_effect=OSError('fixture projection failure')):
            self.assertEqual(self.reconcile()['status'], 'partial')
        self.assertEqual(self.reconcile()['status'], 'reconciled')
        self.assertEqual(len(load_research_record(self.run / 'research_record.json').manual_submission_status), 1)
        self.assertEqual(json.loads(self.ledger.read_text())['submitted_usage_count'], 4)

    def test_replay_does_not_renew_raw_capture_date(self):
        from datetime import datetime, timezone
        with patch('wqb.research_record.datetime', wraps=datetime) as clock:
            clock.now.return_value = datetime(2026, 10, 16, tzinfo=timezone.utc)
            self.assertEqual(self.reconcile()['status'], 'reconciled')
            path = self.root / 'raw/research/runs/run-a/research_record.md'
            before = path.read_bytes()
            clock.now.return_value = datetime(2026, 10, 17, tzinfo=timezone.utc)
            self.assertEqual(self.reconcile()['status'], 'reconciled')
            self.assertEqual(path.read_bytes(), before)

    def test_report_changed_during_lock_acquisition_is_not_consumed(self):
        from wqb.source_run_lock import acquire_source_run_lock
        def acquire(*args, **kwargs):
            """Input: lock arguments. Output: real lock receipt; simulate report mutation before commit."""
            self.report.write_text(self.report.read_text() + 'changed', encoding='utf-8')
            return acquire_source_run_lock(*args, **kwargs)
        with patch('wqb.source_run_lock.acquire_source_run_lock', side_effect=acquire):
            self.assertEqual(self.reconcile()['status'], 'blocked')
        self.assertEqual(load_research_record(self.run / 'research_record.json').manual_submission_status, [])

    def test_missing_data_ledger_is_visible_without_fabricated_rows(self):
        self.ledger.unlink()
        result = self.reconcile()
        self.assertEqual(result['status'], 'reconciled', result)
        self.assertTrue(any('usage unresolved' in item for item in result['diagnostics']))
        self.assertFalse(self.ledger.exists())

    def test_replay_does_not_invalidate_newly_checked_cache(self):
        from wqb.candidate_evidence import capture_evidence_revision, load_candidate_evidence, save_candidate_evidence
        from tests.test_candidate_evidence import platform_payloads
        from types import SimpleNamespace
        self.assertEqual(self.reconcile()['status'], 'reconciled')
        client = SimpleNamespace(knowledge_root=self.root)
        detail, checks = platform_payloads()
        revision = capture_evidence_revision(client, 'alpha1')
        save_candidate_evidence(client, 'alpha1', detail, checks, revision)
        before = capture_evidence_revision(client, 'alpha1')
        self.assertEqual(self.reconcile()['status'], 'reconciled')
        self.assertEqual(capture_evidence_revision(client, 'alpha1'), before)
        self.assertIsNotNone(load_candidate_evidence(client, 'alpha1'))

    def test_failed_durable_write_stays_invalidated_and_retry_is_safe(self):
        from wqb.candidate_evidence import capture_evidence_revision
        from types import SimpleNamespace
        client = SimpleNamespace(knowledge_root=self.root)
        old = capture_evidence_revision(client, 'alpha1')
        with patch('wqb.research_record.write_research_record', side_effect=OSError('fixture interruption')):
            self.assertEqual(self.reconcile()['status'], 'blocked')
        new = capture_evidence_revision(client, 'alpha1')
        self.assertNotEqual(new, old)
        self.assertEqual(self.reconcile()['status'], 'reconciled')
        self.assertEqual(capture_evidence_revision(client, 'alpha1'), new)

    def test_unindexed_report_and_active_source_lock_are_blocking(self):
        index = self.root / 'machine/source_index.jsonl'
        original = index.read_text()
        index.write_text('', encoding='utf-8')
        self.assertEqual(self.reconcile()['status'], 'blocked')
        index.write_text(original, encoding='utf-8')
        from wqb.source_run_lock import acquire_source_run_lock, release_source_run_lock
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        lock = acquire_source_run_lock(self.run, 'fixture', now)
        try:
            self.assertEqual(self.reconcile()['status'], 'blocked')
        finally:
            release_source_run_lock(self.run, 'fixture', now, owner_id=lock['owner_id'])
        self.assertEqual(load_research_record(self.run / 'research_record.json').manual_submission_status, [])

    def test_matching_queue_updated_without_approval_or_identity_rewrite(self):
        from wqb.candidate_queue import approve_candidate, queue_approved_candidate, load_approved_queue
        candidate = dict(candidate_id='candidate1', platform_alpha_id='alpha1', version=1,
                         expression_hash=self.alpha['expression_hash'], source_run_id='run-a')
        approval = approve_candidate(self.run, candidate, '2026-10-14T00:00:00Z', 'fixture')
        queue_approved_candidate(self.run, approval)
        self.assertEqual(self.reconcile()['status'], 'reconciled')
        row = load_approved_queue(self.run)[0]
        self.assertEqual(row['status'], 'manually_submitted')
        for key, value in approval.items():
            self.assertEqual(row[key], value)

    def test_malformed_local_row_is_blocked_without_usage_or_event(self):
        (self.run / 'all_alphas.jsonl').write_text('[1, 2]\n', encoding='utf-8')
        self.assertEqual(self.reconcile()['status'], 'blocked')
        self.assertEqual(json.loads(self.ledger.read_text())['submitted_usage_count'], 3)
        self.assertEqual(load_research_record(self.run / 'research_record.json').manual_submission_status, [])

    def test_projection_failure_after_usage_does_not_double_count_on_retry(self):
        with patch('wqb.research_record._project_manual_queue', side_effect=OSError('queue projection failure')):
            self.assertEqual(self.reconcile()['status'], 'partial')
        self.assertEqual(json.loads(self.ledger.read_text())['submitted_usage_count'], 4)
        self.assertEqual(self.reconcile()['status'], 'reconciled')
        self.assertEqual(json.loads(self.ledger.read_text())['submitted_usage_count'], 4)
        self.assertEqual(len(load_research_record_ledger(self.root)), 1)

    def test_mismatched_queue_identity_is_preserved(self):
        from wqb.candidate_queue import approve_candidate, queue_approved_candidate
        candidate = dict(candidate_id='candidate1', platform_alpha_id='alpha1', version=1,
                         expression_hash='wrong-hash', source_run_id='run-a')
        queue_approved_candidate(self.run, approve_candidate(self.run, candidate, '2026-10-14T00:00:00Z', 'fixture'))
        path = self.run / 'approved_candidates.jsonl'
        before = path.read_bytes()
        result = self.reconcile()
        self.assertEqual(result['status'], 'reconciled')
        self.assertTrue(any('identity mismatch' in text for text in result['diagnostics']))
        self.assertEqual(path.read_bytes(), before)


class ResearchRecordTests(unittest.TestCase):
    def test_sync_research_record_to_machine_appends_latest_run_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            record = empty_research_record("run-a", "Power Pool breadth-first scout")
            record = record_alpha_result(record, {
                "alpha_id": "alpha-a",
                "expression_hash": "hash-a",
                "hard_pass": False,
                "benchmark_label": "near_miss",
                "metrics": {"sharpe": 1.3},
                "failed": ["prod_correlation"],
            })

            path = sync_research_record_to_machine(record, tmp, "2026-07-30T00:00:00+00:00")
            rows = load_research_record_ledger(tmp)

        self.assertEqual(path, Path(tmp) / "machine" / "research_records.jsonl")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["run_id"], "run-a")
        self.assertEqual(rows[0]["final_state"], "in_progress")

    def test_json_roundtrip_and_markdown_include_all_contract_sections(self):
        from wqb.research_record import ResearchRecord
        from wqb.workflow_contract import RESEARCH_RECORD_SECTIONS

        sections = {
            "backtest": [{"alpha_id": "a1"}],
            "triage": [{"alpha_id": "a1", "decision": "hard_pass"}],
            "repair": {"c1": [{"version": 1}]},
            "candidate_gate": [{"candidate_id": "c1"}],
            "user_approval": [{"candidate_id": "c1"}],
            "approved_queue": [{"candidate_id": "c1", "status": "queued"}],
            "manual_submission_status": [{"candidate_id": "c1", "status": "manually_submitted"}],
        }
        record = ResearchRecord(run_id="run1", objective="Power Pool", **sections)

        with tempfile.TemporaryDirectory() as tmp:
            path = write_research_record(Path(tmp) / "research_record.json", record)
            loaded = load_research_record(path)
            payload = json.loads(path.read_text(encoding="utf-8"))
        markdown = render_research_record_markdown(loaded)

        self.assertEqual(asdict(loaded), asdict(record))
        self.assertTrue(set(RESEARCH_RECORD_SECTIONS).issubset(payload))
        for heading in (
            "## Backtest", "## Triage", "## Repair", "## Candidate Gate",
            "## User Approval", "## Approved Queue", "## Manual Submission Status",
        ):
            self.assertIn(heading, markdown)

    def test_load_old_record_uses_backward_compatible_section_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "research_record.json"
            path.write_text(json.dumps({"run_id": "run1", "objective": "old", "failures": []}), encoding="utf-8")
            loaded = load_research_record(path)

        self.assertEqual(loaded.backtest, [])
        self.assertEqual(loaded.manual_submission_status, [])
    def test_failed_alpha_summary_is_compact(self):
        record = empty_research_record("run1", "Power Pool")
        record = record_alpha_result(
            record,
            {
                "alpha_id": "a1",
                "expression_hash": "h1",
                "hard_pass": False,
                "benchmark_label": "weak_discard",
                "metrics": {"sharpe": 0.2},
                "failed": ["LOW_SHARPE"],
            },
        )

        self.assertEqual(record.failures[0]["alpha_id"], "a1")
        self.assertNotIn("expression", record.failures[0])

    def test_repair_version_history_is_idempotent_by_candidate_version_hash(self):
        record = empty_research_record("run1", "Power Pool")
        payload = {"sharpe": 1.3, "failed": []}
        record = record_repair_version(record, "c1", 1, "h1", "reduce turnover", payload)
        record = record_repair_version(record, "c1", 1, "h1", "reduce turnover", payload)

        self.assertEqual(len(record.repairs["c1"]), 1)

    def test_candidate_gate_and_markdown_rendering(self):
        record = empty_research_record("run1", "Power Pool")
        record = record_candidate_gate(record, {"candidate_id": "c1", "platform_alpha_id": "a1", "expression_hash": "h1"}, "ready_for_approval", ["hard checks passed"])
        markdown = render_research_record_markdown(record)

        self.assertIn("# Research Record", markdown)
        self.assertIn("ready_for_approval", markdown)

    def test_candidate_gate_is_idempotent_by_full_identity_and_decision(self):
        record = empty_research_record("run1", "Power Pool")
        candidate = {
            "candidate_id": "c1",
            "platform_alpha_id": "a1",
            "version": 1,
            "expression_hash": "h1",
            "source_run_id": "run1",
        }

        record = record_candidate_gate(
            record, candidate, "ready_for_approval", ["first reason"]
        )
        record = record_candidate_gate(
            record, candidate, "ready_for_approval", ["retry reason"]
        )

        self.assertEqual(len(record.candidate_gate), 1)
        self.assertEqual(record.candidate_gate[0]["reasons"], ["first reason"])

    def test_write_load_and_sync_to_raw(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            record = empty_research_record("run1", "Power Pool")
            path = write_research_record(root / "research_record.json", record)
            loaded = load_research_record(path)
            raw_path = sync_research_record_to_raw(loaded, root / "raw")

        self.assertEqual(loaded.run_id, "run1")
        self.assertTrue(raw_path.name == "research_record.md")

    def test_raw_sync_writes_canonical_metadata_and_updates_source_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "knowledge"
            for name in ("raw", "machine", "wiki"):
                (root / name).mkdir(parents=True)
            record = empty_research_record("run1", "Power Pool")

            raw_path = sync_research_record_to_raw(record, root / "raw")
            metadata, _ = parse_markdown_front_matter(raw_path.read_text(encoding="utf-8"))
            health = evaluate_knowledge_contract_health(root)
            self.assertEqual(metadata["source_family"], "raw/research/runs")
            self.assertEqual(metadata["record_count"], 1)
            self.assertTrue((root / "machine" / "source_index.jsonl").exists())
            self.assertFalse(
                any(issue["path"] == str(raw_path) for issue in health["issues"]),
                health["issues"],
            )

    def test_interrupted_research_record_replace_preserves_previous_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "research_record.json"
            write_research_record(path, empty_research_record("run1", "old objective"))

            with patch.object(Path, "replace", side_effect=OSError("interrupted replace")):
                with self.assertRaisesRegex(OSError, "interrupted replace"):
                    write_research_record(path, empty_research_record("run1", "new objective"))

            loaded = load_research_record(path)

        self.assertEqual(loaded.objective, "old objective")

    def test_research_record_tracks_approvals_and_queue_updates(self):
        from wqb.research_record import (
            record_approval,
            record_manual_submission_status,
            record_queue_update,
        )

        record = empty_research_record("run1", "Power Pool")
        approval = {
            "candidate_id": "c1", "platform_alpha_id": "a1", "version": 1,
            "expression_hash": "h1", "source_run_id": "run1", "approved_at": "t", "approved_by": "user",
        }
        queue_row = dict(approval, status="queued")
        manual_row = dict(approval, status="manually_submitted")
        record = record_approval(record, approval)
        record = record_approval(record, approval)
        record = record_queue_update(record, queue_row)
        record = record_queue_update(record, queue_row)
        record = record_manual_submission_status(record, manual_row)
        record = record_manual_submission_status(record, manual_row)

        self.assertEqual(record.approvals[0]["candidate_id"], "c1")
        self.assertEqual(record.queue_updates[0]["status"], "queued")
        self.assertEqual(len(record.user_approval), 1)
        self.assertEqual(len(record.approved_queue), 1)
        self.assertEqual(len(record.manual_submission_status), 1)

    def test_status_history_dedupes_only_immediate_retries(self):
        from wqb.research_record import record_manual_submission_status, record_queue_update

        record = empty_research_record("run1", "Power Pool")
        base = {
            "candidate_id": "c1", "platform_alpha_id": "a1", "version": 1,
            "expression_hash": "h1", "source_run_id": "run1",
        }
        for status in ("queued", "manually_submitted", "queued"):
            row = dict(base, status=status)
            record = record_queue_update(record, row)
            record = record_manual_submission_status(record, row)

        self.assertEqual(
            [row["status"] for row in record.approved_queue],
            ["queued", "manually_submitted", "queued"],
        )
        self.assertEqual(
            [row["status"] for row in record.manual_submission_status],
            ["queued", "manually_submitted", "queued"],
        )


class MechanismRecordBridgeTests(unittest.TestCase):
    def test_official_planner_generator_record_ingestion_preserves_verified_pair(self):
        """Input: real offline producers. Output: persisted paired lineage and tamper rejection."""
        from tests.test_hypothesis_selection import paired_selection_fixture
        from wqb.research_planning import prepare_source_plan
        from wqb.generator import hypothesis_candidate_metadata
        from wqb.cli import simulation_identity_hash
        from wqb.research_record import empty_research_record, record_alpha_result, research_record_to_dict
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshot, experiments = paired_selection_fixture(root)
            run = root / 'run'
            run.mkdir()
            (run / 'run_manifest.json').write_text(json.dumps(dict(start_snapshot=snapshot)))
            settings = experiments[0]['arms'][0]['settings']
            config = dict(settings, instrument_type=settings['instrumentType'], unit_handling=settings['unitHandling'],
                          nan_handling=settings['nanHandling'], max_alphas_per_round=3)
            plan = prepare_source_plan(run, config, {}, 'now')
            binding = plan['scheduled_hypotheses'][0]
            row = dict(hypothesis_candidate_metadata(snapshot, binding, plan['ai_plan_receipt']),
                       alpha_id='a', expression=binding['bound_expression'], settings=settings,
                       expression_hash=simulation_identity_hash(binding['bound_expression'], settings),
                       metrics=dict(returns=0.1), failed=[], pending=[], hard_pass=True)
            record = record_alpha_result(empty_research_record('run', 'test'), row)
            result = research_record_to_dict(record)['backtest'][0]
            self.assertEqual(result.get('mechanism_experiments'), experiments)
            self.assertIn('mechanism_source', result)
            self.assertEqual(result['scope'], binding['scope'])
            self.assertNotIn('measurement_period', result)
            from wqb.research_record import sync_research_record_to_machine
            from wqb.knowledge_compile import compile_research_records
            from wqb.mechanism_evidence import select_mechanism_context
            second = plan['scheduled_hypotheses'][1]
            second_row = dict(hypothesis_candidate_metadata(snapshot, second, plan['ai_plan_receipt']),
                alpha_id='b', expression=second['bound_expression'], settings=settings,
                expression_hash=simulation_identity_hash(second['bound_expression'], settings),
                metrics=dict(returns=0.2), status='CHECKED', failed=[], pending=[], hard_pass=True)
            record = record_alpha_result(record, second_row)
            vault = root / 'derived'
            sync_research_record_to_machine(record, vault, 'now')
            compiled = compile_research_records(vault, 'now')
            view = json.loads(Path(compiled['mechanism_evidence_path']).read_text(encoding='utf-8'))
            self.assertEqual(len(view['groups']), 1)
            self.assertEqual(view['groups'][0]['unique_simulations'], 2)
            self.assertEqual(view['groups'][0]['label'], 'inconclusive')
            self.assertIn('known_period_absent', view['groups'][0]['limitations'])
            self.assertEqual(len(select_mechanism_context(view, {'design_id': experiments[0]['design_id']})['items']), 1)
            Path(plan['experiment_sidecar_path']).write_text('{}')
            with self.assertRaises(ValueError):
                record_alpha_result(record, row)
