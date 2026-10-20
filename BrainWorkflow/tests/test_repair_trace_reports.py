import copy
import html
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from wqb import research_record as records
from wqb.knowledge_experience_compile import compile_research_case_reports
from wqb.knowledge_compile import compile_research_records


def attempt_fixture():
    """Input: none. Output: dict. Build a measured Repair attempt without platform calls."""
    baseline = {'alpha_id': 'parent', 'expression_hash': 'parent-hash',
                'expression': 'rank(signal)', 'settings': {'decay': 4},
                'metrics': {'sharpe': 1.0}}
    child = {'alpha_id': 'child', 'expression_hash': 'child-hash',
             'expression': 'rank(signal)', 'settings': {'decay': 8},
             'metrics': {'sharpe': 1.2}}
    decision = {'hypothesis': 'Longer decay reduces noise', 'edit': 'decay', 'value': 8,
                'economic_rationale': 'Slow information diffusion',
                'expected_improvement': 'Higher sharpe', 'risks': 'Signal lag',
                'target_metric': 'sharpe', 'target_direction': 'increase',
                'falsification': 'No sharpe improvement', 'applicability': 'Slow signals'}
    return {'parent_alpha_id': 'parent', 'parent_expression_hash': 'parent-hash',
            'plan': {'evidence_digest': 'evidence-sha', 'receipt_path': 'plans/receipt.json',
                     'decision': decision, 'judgment': {'status': 'completed', 'decision': decision},
                     'variants': [child]}, 'children': [child],
            'experiment_trace': {'schema_version': 1, 'baseline': baseline,
                'measured_child': child, 'decision': decision, 'outcome': 'accept',
                'reason': 'Target improved', 'metric_changes': {
                    'sharpe': {'before': 1.0, 'after': 1.2, 'delta': 0.2}},
                'remaining_checks': ['SELF_CORRELATION'],
                'interpretation': 'Local comparison only', 'submission_qualified': False}}


class RepairTraceReportTests(unittest.TestCase):
    def integrate(self, record, attempts):
        """Input: record/list. Output: record. Assert the public integration API exists."""
        function = getattr(records, 'record_repair_attempts', None)
        self.assertTrue(callable(function), 'record_repair_attempts is missing')
        return function(record, attempts)

    def test_idempotent_resume_preserves_legacy_versions_and_detaches_trace(self):
        attempt = attempt_fixture()
        legacy = records.record_repair_version(records.empty_research_record('run', 'test'),
                    'parent-hash', 7, 'old-hash', 'legacy hypothesis', {'metrics': {}})
        original = copy.deepcopy(legacy)
        result = self.integrate(legacy, [attempt, attempt])
        self.assertEqual(legacy, original)
        rows = result.repair['parent-hash']
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0], legacy.repair['parent-hash'][0])
        self.assertGreater(rows[1]['version'], 7)
        self.assertEqual(rows[1]['expression_hash'], 'child-hash')
        self.assertEqual(rows[1]['experiment_trace'], attempt['experiment_trace'])
        self.assertEqual(rows[1]['plan_provenance'], {
            'evidence_digest': 'evidence-sha', 'receipt_path': 'plans/receipt.json'})
        with tempfile.TemporaryDirectory() as tmp:
            path = records.write_research_record(Path(tmp) / 'record.json', result)
            resumed = self.integrate(records.load_research_record(path), [attempt])
        self.assertEqual(resumed, result)
        attempt['experiment_trace']['decision']['hypothesis'] = 'mutated'
        self.assertEqual(rows[1]['hypothesis'], 'Longer decay reduces noise')
        self.assertNotEqual(rows[1]['experiment_trace']['decision']['hypothesis'], 'mutated')

    def test_distinct_plan_same_child_hash_gets_unique_version(self):
        first = attempt_fixture()
        second = copy.deepcopy(first)
        second['plan']['evidence_digest'] = 'next-evidence'
        result = self.integrate(records.empty_research_record('run', ''), [first, second])
        rows = result.repair['parent-hash']
        self.assertEqual(len(rows), 2)
        self.assertEqual(len({(r['version'], r['expression_hash']) for r in rows}), 2)
        self.assertEqual(self.integrate(result, [second, first]), result)

    def test_stop_decision_without_child_is_retained(self):
        attempt = attempt_fixture()
        attempt['plan']['variants'] = []
        attempt['children'] = []
        attempt['plan']['decision']['hypothesis'] = 'Stop: insufficient evidence'
        attempt.pop('experiment_trace')
        result = self.integrate(records.empty_research_record('run', ''), [attempt])
        row = result.repair['parent-hash'][0]
        self.assertEqual(row['hypothesis'], 'Stop: insufficient evidence')
        self.assertEqual(self.integrate(result, [attempt]), result)
        text = records.render_research_record_markdown(result)
        self.assertIn('Stop decision', text)
        self.assertIn('plans/receipt.json', text)
        self.assertNotIn('Outcome: accept', text)

    def test_raw_and_compiled_reports_show_measured_evidence_not_ledgers(self):
        result = self.integrate(records.empty_research_record('run', 'test'), [attempt_fixture()])
        raw = records.render_research_record_markdown(result)
        with tempfile.TemporaryDirectory() as tmp:
            with patch('wqb.knowledge_experience_compile.compile_research_case_reports',
                       side_effect=AssertionError('record sync must not compile')):
                records.sync_research_record_to_machine(result, tmp, '2026-10-13T00:00:00Z')
            paths = compile_research_case_reports(tmp, '2026-10-13T00:00:00Z', 5)
            compiled = paths[0].read_text(encoding='utf-8')
        for text in (raw, compiled):
            text = html.unescape(text)
            for token in ('Baseline', 'parent-hash', 'Target', 'sharpe', 'increase',
                          'Longer decay reduces noise', 'Single change', 'decay',
                          '1.0', '1.2', '0.2', 'accept', 'SELF_CORRELATION',
                          'Slow signals', 'Signal lag', 'No sharpe improvement',
                          'evidence-sha', 'plans/receipt.json', 'not causal proof',
                          'not submission qualification'):
                self.assertIn(token, text)
            self.assertNotIn('"schema_version"', text)
            self.assertNotIn('"metrics"', text)

    def test_legacy_is_not_labeled_ai_or_measured(self):
        record = records.record_repair_version(records.empty_research_record('run', ''),
                    'parent', 1, 'hash', 'Old hypothesis', {})
        for text in (records.render_research_record_markdown(record),):
            self.assertIn('Trace unavailable', text)
            self.assertIn('Old hypothesis', text)
            self.assertNotIn('Outcome: accept', text)
            self.assertNotIn('AI', text)

    def test_reports_bound_and_escape_untrusted_trace_text(self):
        attempt = attempt_fixture()
        bad = '<script>alert(1)</script> [click](https://bad) `code` |\n# injected '
        attempt['experiment_trace']['decision']['hypothesis'] = bad + 'x' * 10000
        attempt['experiment_trace']['remaining_checks'] = [bad] * 10000
        attempt['experiment_trace']['metric_changes'].update({str(i): {'before': bad} for i in range(1000)})
        result = self.integrate(records.empty_research_record('run', ''), [attempt] * 100)
        raw = records.render_research_record_markdown(result)
        self.assertLess(len(raw), 16000)
        self.assertNotIn('<script>', raw)
        self.assertNotIn('[click](', raw)
        self.assertNotIn('\n# injected', raw)
        self.assertIn('truncated', raw)

    def test_resume_updates_inflight_attempt_without_new_version(self):
        attempt = attempt_fixture()
        inflight = copy.deepcopy(attempt)
        inflight.pop('experiment_trace')
        inflight['children'] = []
        record = self.integrate(records.empty_research_record('run', ''), [inflight])
        result = self.integrate(record, [attempt])
        self.assertEqual(len(result.repair['parent-hash']), 1)
        self.assertEqual(result.repair['parent-hash'][0]['experiment_trace'], attempt['experiment_trace'])
        self.assertEqual(self.integrate(result, [inflight]), result)

    def test_contract_without_edit_fields_shows_measured_single_change(self):
        attempt = attempt_fixture()
        attempt['experiment_trace']['decision'].pop('edit')
        attempt['experiment_trace']['decision'].pop('value')
        result = self.integrate(records.empty_research_record('run', ''), [attempt])
        text = html.unescape(records.render_research_record_markdown(result))
        self.assertIn('decay: 4 -> 8', text)

    def test_report_total_budget_with_many_hostile_attempts(self):
        attempt = attempt_fixture()
        decision = attempt['experiment_trace']['decision']
        for key in decision:
            decision[key] = '<' * 2000
        attempt['experiment_trace']['remaining_checks'] = ['<' * 2000] * 100
        repairs = {'parent': [dict(experiment_trace=attempt['experiment_trace'])] * 100}
        record = records.ResearchRecord('run', '', repair=repairs)
        text = records.render_research_record_markdown(record)
        self.assertLess(len(text), records.REPAIR_REPORT_CHAR_LIMIT + 1000)
        self.assertIn('truncated', text)

    def test_alpha_fallback_and_legacy_attempt_preserve_no_trace(self):
        attempt = {'parent_alpha_id': 'parent', 'children': [{'expression_hash': 'child'}]}
        result = self.integrate(records.empty_research_record('run', ''), [attempt])
        self.assertNotIn('experiment_trace', result.repair['parent'][0])
        self.assertEqual(self.integrate(result, [attempt]), result)

    def test_legacy_compiled_report_marks_missing_trace(self):
        record = records.record_repair_version(records.empty_research_record('run', ''),
                                              'parent', 1, 'hash', 'Old hypothesis', {})
        with tempfile.TemporaryDirectory() as tmp:
            records.sync_research_record_to_machine(record, tmp)
            report = compile_research_case_reports(tmp, '2026-10-13T00:00:00Z', 1)[0]
            text = report.read_text(encoding='utf-8')
        self.assertIn('Trace unavailable', text)
        self.assertNotIn('AI', text)

    def test_compile_research_records_twice_keeps_repair_only_authority(self):
        record = self.integrate(records.empty_research_record('run', 'test'), [attempt_fixture()])
        self.assertEqual(record.backtest, [])
        with tempfile.TemporaryDirectory() as tmp:
            records.sync_research_record_to_machine(record, tmp, '2026-10-10T00:00:00Z')
            records.sync_research_record_to_raw(record, Path(tmp) / 'raw')
            for timestamp in ('2026-10-13T00:00:00Z', '2026-10-14T00:00:00Z'):
                summary = compile_research_records(tmp, timestamp)
                report = Path(summary['case_report_paths'][0]).read_text(encoding='utf-8')
                self.assertIn('Longer decay reduces noise', report)
                self.assertIn('Before-after sharpe', report)
                self.assertIn('plans/receipt.json', report)
                self.assertEqual(len(records.load_research_record_ledger(tmp)), 1)

    def test_reports_show_baseline_failed_checks_scope_and_period(self):
        attempt = attempt_fixture()
        baseline = attempt['experiment_trace']['baseline']
        baseline['failed'] = ['LOW_SHARPE']
        baseline['settings'].update(region='USA', universe='TOP3000', delay=1)
        baseline['test_period'] = 'P2Y'
        record = self.integrate(records.empty_research_record('run', ''), [attempt])
        with tempfile.TemporaryDirectory() as tmp:
            records.sync_research_record_to_machine(record, tmp)
            compiled = compile_research_case_reports(tmp, '2026-10-13T00:00:00Z', 1)[0].read_text(encoding='utf-8')
        for text in (records.render_research_record_markdown(record), compiled):
            text = html.unescape(text)
            for token in ('Baseline failed checks', 'LOW_SHARPE', 'Baseline scope', 'USA', 'TOP3000', 'delay: 1', 'P2Y'):
                self.assertIn(token, text)

    def test_missing_baseline_scope_is_explicit_not_inferred(self):
        record = self.integrate(records.empty_research_record('run', ''), [attempt_fixture()])
        text = records.render_research_record_markdown(record)
        self.assertIn('Baseline scope', text)
        self.assertIn('period: not recorded', text)

    def test_historical_newer_raw_summary_cannot_hide_structured_trace(self):
        record = self.integrate(records.empty_research_record('run', 'test'), [attempt_fixture()])
        with tempfile.TemporaryDirectory() as tmp:
            path = records.sync_research_record_to_machine(record, tmp, '2026-10-10T00:00:00Z')
            lossy = {'run_id': 'run', 'final_state': 'compiled_from_raw',
                     'synced_at': '2026-10-12T00:00:00Z', 'repair': {},
                     'raw_source_path': 'raw/research/runs/run/research_record.md',
                     'case_reason': 'representative_failure'}
            with path.open('a', encoding='utf-8') as handle:
                handle.write(json.dumps(lossy) + '\n')
            records.sync_research_record_to_raw(record, Path(tmp) / 'raw')
            result = compile_research_records(tmp, '2026-10-13T00:00:00Z')
            report = Path(result['case_report_paths'][0]).read_text(encoding='utf-8')
            self.assertIn('Longer decay reduces noise', report)
            self.assertEqual(len(records.load_research_record_ledger(tmp)), 2)

    def test_no_trace_uses_top_level_plan_decision_without_authorship(self):
        attempt = attempt_fixture()
        attempt.pop('experiment_trace')
        attempt['plan']['judgment'] = {'decision': {'hypothesis': 'Must not use wrapper'}}
        record = self.integrate(records.empty_research_record('run', ''), [attempt])
        self.assertEqual(record.repair['parent-hash'][0]['hypothesis'], 'Longer decay reduces noise')
        text = records.render_research_record_markdown(record)
        self.assertIn('Trace unavailable', text)
        self.assertNotIn('Must not use wrapper', text)
        self.assertNotIn('AI', text)

    def test_stop_trace_shows_baseline_checks_scope_without_measured_effect(self):
        attempt = attempt_fixture()
        attempt['plan']['variants'] = []
        attempt['children'] = []
        trace = attempt['experiment_trace']
        trace.pop('measured_child')
        trace['metric_changes'] = {}
        trace['outcome'] = 'inconclusive'
        trace['reason'] = 'Stopped before simulation; no measured effect'
        trace['baseline']['failed'] = ['LOW_SHARPE']
        trace['baseline']['settings'].update(region='USA', universe='TOP3000', delay=1)
        trace['baseline']['test_period'] = '2014-2024'
        record = self.integrate(records.empty_research_record('run', ''), [attempt])
        text = html.unescape(records.render_research_record_markdown(record))
        for token in ('Stop decision', 'Baseline failed checks', 'LOW_SHARPE', 'Baseline scope',
                      'USA', 'TOP3000', '2014-2024', 'inconclusive', 'no measured effect'):
            self.assertIn(token, text)
        self.assertNotIn('Before-after', text)


if __name__ == '__main__':
    unittest.main()
