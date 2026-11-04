"""Offline K5 coverage reports never publish or turn prose into eligibility."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from wqb.full_semantic_compile import prepare_full_semantic_compile
from wqb.full_semantic_execution import run_full_semantic_compile
from wqb.full_semantic_coverage import build_full_semantic_report


class FullSemanticCoverageTests(unittest.TestCase):
    def test_default_report_is_compact_and_shares_unchanged_target_details(self):
        """Input: repeated same-source coverage. Output: compact reports sharing one immutable target object."""
        plan = self.plan()
        first = build_full_semantic_report(self.root, plan)
        self.assertNotIn('targets', first)
        ref = first['targets_ref']
        payload = (self.root / ref['path']).read_bytes()
        self.assertEqual(hashlib.sha256(payload).hexdigest(), ref['sha256'])
        self.assertEqual(len(payload.splitlines()), first['inventory']['denominator'])
        before = (self.root / ref['path']).stat().st_mtime_ns
        second = build_full_semantic_report(self.root, plan, detailed=True)
        self.assertEqual(second['targets_ref'], ref)
        self.assertEqual(len(second['targets']), 2)
        self.assertEqual((self.root / ref['path']).stat().st_mtime_ns, before)
        stored = json.loads((self.root / second['report_paths']['json']).read_bytes())
        self.assertNotIn('targets', stored)
        self.assertEqual(stored['targets_ref'], ref)

    def test_changed_target_details_have_distinct_content_reference(self):
        """Input: source mutation after coverage. Output: new details reference without overwriting old evidence."""
        plan = self.plan()
        first = build_full_semantic_report(self.root, plan)
        old = (self.root / first['targets_ref']['path']).read_bytes()
        self.write(self.source_path, '### rank\nChanged source.\n')
        second = build_full_semantic_report(self.root, plan)
        self.assertNotEqual(first['targets_ref'], second['targets_ref'])
        self.assertEqual((self.root / first['targets_ref']['path']).read_bytes(), old)

    def test_corrupt_shared_target_object_is_not_replaced_silently(self):
        """Input: corrupted shared details. Output: explicit rejection, not a fresh-looking overwrite."""
        plan = self.plan()
        first = build_full_semantic_report(self.root, plan)
        self.write(first['targets_ref']['path'], 'corrupt')
        with self.assertRaisesRegex(ValueError, 'immutable'):
            build_full_semantic_report(self.root, plan)

    def test_legacy_plan_local_inventory_remains_readable_without_storage_migration(self):
        """Input: fixture plan with original plan-local reference. Output: same denominator and no execution authority."""
        from wqb.full_semantic_compile import _digest, _bytes
        current = self.plan()
        legacy = deepcopy(current)
        legacy['identity'].pop('inventory_format_version')
        legacy['content_key'] = _digest(legacy['identity'])
        base = 'machine/semantic_jobs/' + legacy['content_key']
        legacy['plan_path'] = base + '/plan.json'
        legacy['inventory_ref']['path'] = base + '/inventory.jsonl'
        payload = (self.root / current['inventory_ref']['path']).read_text(encoding='utf-8')
        self.write(legacy['inventory_ref']['path'], payload)
        self.write(legacy['plan_path'], _bytes(legacy).decode('utf-8'))
        report = build_full_semantic_report(self.root, legacy)
        self.assertEqual(report['inventory']['denominator'], 2)
        self.assertEqual(report['explanations']['processed'], 0)

    def setUp(self):
        """Input: TestCase. Output: temporary vault with two current indexed operators."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source_path = 'raw/platform/learn/day/operators.md'
        text = '### rank\n- Description: Cross-sectional rank.\n### delta\n- Description: Change.\n'
        self.write(self.source_path, text)
        self.source = dict(path=self.source_path, content_hash=hashlib.sha256(text.encode()).hexdigest(),
            captured_at=(datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
            source_type='platform_learn_material', source_family='raw/platform/learn')
        self.write('machine/source_index.jsonl', self.source)

    def write(self, relative, value):
        """Input: relative str and JSON value/text. Output: fixture Path with serialized contents."""
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value if isinstance(value, str) else json.dumps(value), encoding='utf-8', newline='\n')
        return path

    def plan(self, budget=0, **kwargs):
        """Input: finite budget int/config. Output: actual K4 prepared plan dict."""
        return prepare_full_semantic_compile(self.root, dict(model_call_budget=budget, **kwargs))

    def answer(self, *, job, output_schema, deadline):
        """Input: actual fixture executor contract. Output: strict literal-only explanation dict."""
        ref = dict(source_path=self.source_path, sha256=self.source['content_hash'],
                   capture_date=self.source['captured_at'][:10], kind='documented', experiment_refs=[])
        return dict(summary='Literal facts only', targets=[dict(target_id=t['target_id'], identity=t['identity'],
            literal_fact_summary='Cross-sectional rank.' if t['identity']['operator'] == 'rank' else 'Change.',
            typed_facts={}, hypothesis_cards=[], conditional_uses=[], missing_facts=['No typed definition'],
            conflicting_facts=[], evidence_refs=[ref]) for t in job['input']['targets']])

    def execute(self, plan, executor=None):
        """Input: plan dict/optional fixture callback. Output: real execution receipt, zero external calls."""
        result = run_full_semantic_compile(self.root, plan, executor=executor or self.answer)
        self.assertTrue(result['targets'])
        return result

    def snapshot(self):
        """Input: fixture vault. Output: mapping of all nonreport paths to bytes."""
        return {p.relative_to(self.root).as_posix(): p.read_bytes() for p in self.root.rglob('*')
                if p.is_file() and not p.is_relative_to(self.root / 'machine/reports')}

    def test_unattempted_and_partial_inventory_keep_denominators(self):
        self.write('machine/operator_ledger.jsonl', dict(operator='unsupported'))
        plan = self.plan()
        report = build_full_semantic_report(self.root, plan, detailed=True)
        self.assertEqual(report['inventory']['denominator'], 3)
        self.assertEqual(report['explanations']['denominator'], 3)
        self.assertEqual(report['explanations']['processed'], 0)
        self.assertEqual(report['explanations']['numerator'], 0)
        self.assertEqual(len(report['targets']), 3)
        self.assertEqual(sum(t['processing_status'] == 'unattempted' for t in report['targets']), 2)
        self.assertEqual(report['compiler_binder']['denominator_unit'], 'candidate_operation_bindings')
        self.assertEqual(report['start_consumption']['denominator_unit'], 'frozen_start_lanes')

    def test_current_validated_literals_are_not_executable_or_consumed(self):
        plan = self.plan(1)
        self.assertEqual(self.execute(plan)['status'], 'completed')
        report = build_full_semantic_report(self.root, plan)
        self.assertEqual(report['explanations']['processed'], 2)
        self.assertEqual(report['explanations']['numerator'], 2)
        self.assertEqual(report['explanations']['documented_targets'], 2)
        for layer in ('compiler_binder', 'start_consumption'):
            self.assertEqual(report[layer]['status'], 'not_evaluated')
            self.assertEqual(report[layer]['numerator'], 0)
            self.assertIsNone(report[layer]['denominator'])
            self.assertTrue(report[layer]['reasons'])
        self.assertFalse(report['research_ready'])

    def test_processing_is_not_semantics(self):
        def unresolved(**kwargs):
            """Input: executor kwargs. Output: valid but unresolved target answers."""
            answer = self.answer(**kwargs)
            for target in answer['targets']:
                target.update(literal_fact_summary=None, evidence_refs=[])
            return answer

        plan = self.plan(1)
        self.execute(plan, unresolved)
        report = build_full_semantic_report(self.root, plan)
        self.assertEqual(report['explanations']['processed'], 2)
        self.assertEqual(report['explanations']['numerator'], 0)

    def test_partial_attempts_remain_in_semantic_denominator(self):
        plan = self.plan(1, max_targets_per_job=1)
        self.execute(plan)
        report = build_full_semantic_report(self.root, plan)
        self.assertEqual(report['explanations']['denominator'], 2)
        self.assertEqual(report['explanations']['numerator'], 1)
        self.assertEqual(report['explanations']['unattempted'], 1)

    def test_source_mutation_invalidates_previous_success(self):
        plan = self.plan(1)
        self.execute(plan)
        self.write(self.source_path, '### rank\nAltered.\n')
        report = build_full_semantic_report(self.root, plan)
        self.assertEqual(report['inventory']['numerator'], 0)
        self.assertEqual(report['explanations']['numerator'], 0)
        self.assertTrue(report['diagnostics'])

    def test_stale_sources_have_bytes_but_no_current_semantic_coverage(self):
        self.source['captured_at'] = '2000-01-01T00:00:00Z'
        self.write('machine/source_index.jsonl', self.source)
        plan = self.plan(1)
        self.execute(plan)
        report = build_full_semantic_report(self.root, plan, detailed=True)
        self.assertEqual(report['inventory']['numerator'], 2)
        self.assertEqual(report['explanations']['numerator'], 0)
        self.assertTrue(all(t['freshness_status'] == 'stale' for t in report['targets']))

    def test_tampered_result_and_forged_execution_summary_are_not_coverage(self):
        plan = self.plan(1)
        result = self.execute(plan)
        ref = result['jobs'][0]['result_ref']
        self.write(ref['path'], dict(status='validated', targets=[], research_eligible=True))
        self.write(str(Path(plan['plan_path']).parent / 'execution_result.json').replace('\\', '/'),
                   dict(full_coverage=True, coverage=dict(eligible_targets=999), targets=[]))
        report = build_full_semantic_report(self.root, plan)
        self.assertEqual(report['explanations']['numerator'], 0)
        self.assertEqual(report['compiler_binder']['numerator'], 0)

    def test_invented_state_has_no_reservation_authority(self):
        plan = self.plan()
        base = Path(plan['jobs'][0]['path']).parent.as_posix()
        self.write(base + '/execution_state.json', dict(status='completed', job_id=plan['jobs'][0]['job_id']))
        report = build_full_semantic_report(self.root, plan)
        self.assertEqual(report['explanations']['processed'], 0)
        self.assertTrue(report['diagnostics'])

    def test_report_only_writes_bounded_reports_and_no_authority(self):
        plan = self.plan(1)
        self.execute(plan)
        before = self.snapshot()
        report = build_full_semantic_report(self.root, plan)
        self.assertEqual(before, self.snapshot())
        self.assertEqual(report['model_calls'], 0)
        self.assertEqual(report['platform_calls'], 0)
        self.assertFalse(report['publication_authorized'])
        self.assertFalse(report['research_authorized'])
        self.assertEqual(json.loads((self.root / report['report_paths']['json']).read_bytes()), report)
        markdown = (self.root / report['report_paths']['markdown']).read_text(encoding='utf-8')
        self.assertLess(len(markdown), 6000)
        self.assertNotIn(plan['jobs'][0]['target_ids'][0], markdown)
        self.assertIn('not_evaluated', markdown)

    def test_plan_tampering_fails_closed_without_reports(self):
        plan = deepcopy(self.plan())
        plan['coverage']['target_count'] = 10000
        with self.assertRaises(ValueError):
            build_full_semantic_report(self.root, plan)
        self.assertFalse((self.root / 'machine/reports').exists())

    def test_field_literals_keep_scope_denominator_without_invented_eligibility(self):
        scope = dict(instrument_type='EQUITY', region='USA', delay=1, universe='TOP3000')
        rows = [dict(data_set=dict(id='prices'), scope=scope,
                     field=dict(id=name, type=kind, description=description))
                for name, kind, description in [('level', 'MATRIX', 'Closing price'),
                                                 ('vector', 'VECTOR', 'Vector price')]]
        path = 'raw/platform/data_fields/day/data_fields.jsonl'
        text = ''.join(json.dumps(row) + '\n' for row in rows)
        self.write(path, text)
        source = dict(self.source, path=path, source_type='platform_data_field_capture',
                      source_family='raw/platform/data_fields', content_hash=hashlib.sha256(text.encode()).hexdigest())
        self.write('machine/source_index.jsonl', json.dumps(self.source) + '\n' + json.dumps(source))

        def literal(**kwargs):
            """Input: fake executor kwargs. Output: field/operator literals, no derived metadata."""
            job = kwargs['job']
            if job['input']['targets'][0]['kind'] == 'operator':
                return self.answer(**kwargs)
            ref = dict(source_path=path, sha256=source['content_hash'], capture_date=source['captured_at'][:10],
                       kind='documented', experiment_refs=[])
            descriptions = {row['field']['id']: row['field']['description'] for row in rows}
            return dict(summary='Original descriptions only', targets=[dict(target_id=t['target_id'], identity=t['identity'],
                literal_fact_summary=descriptions[t['identity']['field_id']], typed_facts={}, hypothesis_cards=[],
                conditional_uses=[], missing_facts=['Grain and polarity unknown'], conflicting_facts=[], evidence_refs=[ref])
                for t in job['input']['targets']])

        plan = self.plan(10)
        self.assertEqual(self.execute(plan, literal)['status'], 'completed')
        before = self.snapshot()
        report = build_full_semantic_report(self.root, plan)
        self.assertEqual(report['explanations']['numerator'], 4)
        self.assertEqual(report['inventory']['scope_rows']['denominator'], 2)
        self.assertEqual(before, self.snapshot())
        self.assertEqual(report['compiler_binder']['status'], 'not_evaluated')

    def test_hypothesis_only_output_never_becomes_documented(self):
        def hypothesis(**kwargs):
            """Input: fake executor kwargs. Output: sourced conditional research uses, not official facts."""
            answer = self.answer(**kwargs)
            for target in answer['targets']:
                ref = dict(target['evidence_refs'][0], kind='hypothesis')
                target.update(literal_fact_summary=None, evidence_refs=[], conditional_uses=[dict(
                    conditions='When tested on the frozen scope', purpose='Possible relative price mechanism',
                    failure_risks=['Polarity remains unknown'], evidence_refs=[ref])])
            return answer

        plan = self.plan(1)
        self.assertEqual(self.execute(plan, hypothesis)['status'], 'completed')
        report = build_full_semantic_report(self.root, plan)
        self.assertEqual(report['explanations']['numerator'], 2)
        self.assertEqual(report['explanations']['hypothesis_targets'], 2)
        self.assertEqual(report['explanations']['documented_targets'], 0)

    def test_mutation_during_validation_does_not_leave_successful_coverage(self):
        from unittest.mock import patch
        import wqb.full_semantic_coverage as coverage

        plan = self.plan(1)
        self.execute(plan)
        validate = coverage._validate_explanation

        def mutate(*args, **kwargs):
            """Input: validator args. Output: actual validation then deliberately corrupted fixture source."""
            checked = validate(*args, **kwargs)
            self.write(self.source_path, '### rank\nChanged after checking.\n')
            return checked

        with patch.object(coverage, '_validate_explanation', mutate):
            report = build_full_semantic_report(self.root, plan)
        self.assertEqual(report['explanations']['numerator'], 0)
        self.assertEqual(report['inventory']['numerator'], 0)

    def test_malformed_state_is_diagnostic_not_uncaught_exception(self):
        plan = self.plan()
        base = Path(plan['jobs'][0]['path']).parent.as_posix()
        self.write(base + '/execution_state.json', [])
        report = build_full_semantic_report(self.root, plan)
        self.assertEqual(report['explanations']['numerator'], 0)
        self.assertTrue(report['diagnostics'])

    def test_rehashed_invented_output_is_revalidated_not_trusted(self):
        from wqb.full_semantic_compile import _bytes

        plan = self.plan(1)
        result = self.execute(plan)
        ref = result['jobs'][0]['result_ref']
        value = json.loads((self.root / ref['path']).read_bytes())
        value['targets'][0]['literal_fact_summary'] = 'Invented official polarity'
        value['target_validation'] = {tid: dict(status='supported', research_eligible=True)
                                      for tid in plan['jobs'][0]['target_ids']}
        raw = _bytes(value)
        (self.root / ref['path']).write_bytes(raw)
        state_path = (self.root / plan['jobs'][0]['path']).parent / 'execution_state.json'
        state = json.loads(state_path.read_bytes())
        state['result_ref']['sha256'] = hashlib.sha256(raw).hexdigest()
        self.write(state_path.relative_to(self.root).as_posix(), state)
        report = build_full_semantic_report(self.root, plan)
        self.assertEqual(report['explanations']['numerator'], 0)
        self.assertEqual(report['compiler_binder']['numerator'], 0)

    def test_rehashed_proof_flags_must_match_canonical_reconstruction(self):
        from wqb.full_semantic_compile import _bytes

        plan = self.plan(1)
        execution = self.execute(plan)
        ref = execution['jobs'][0]['result_ref']
        value = json.loads((self.root / ref['path']).read_bytes())
        for proof in value['target_validation'].values():
            proof['research_eligible'] = True
        raw = _bytes(value)
        (self.root / ref['path']).write_bytes(raw)
        state_path = (self.root / plan['jobs'][0]['path']).parent / 'execution_state.json'
        state = json.loads(state_path.read_bytes())
        state['result_ref']['sha256'] = hashlib.sha256(raw).hexdigest()
        self.write(state_path.relative_to(self.root).as_posix(), state)
        report = build_full_semantic_report(self.root, plan)
        self.assertEqual(report['explanations']['numerator'], 0)

    def test_real_k3_facts_are_readonly_and_missing_artifact_is_not_recreated(self):
        from tests.test_field_semantic_enrichment import FieldSemanticEnrichmentTests

        fixture = FieldSemanticEnrichmentTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)

        def answer(*, job, **kwargs):
            """Input: real bound field job dict. Output: documented units from the certified fixture."""
            return dict(summary='Documented units only', targets=[dict(target_id=t['target_id'], identity=t['identity'],
                literal_fact_summary='Cash balance', typed_facts=dict(units=fixture.fact('units', 'USD')),
                hypothesis_cards=[], conditional_uses=[], missing_facts=['polarity'], conflicting_facts=[],
                evidence_refs=[fixture.evidence]) for t in job['input']['targets']])

        plan = prepare_full_semantic_compile(fixture.root, dict(model_call_budget=1))
        execution = run_full_semantic_compile(fixture.root, plan, executor=answer)
        self.assertEqual(execution['status'], 'completed', execution['blockers'])
        before = {p: p.read_bytes() for p in fixture.root.rglob('*') if p.is_file()}
        report = build_full_semantic_report(fixture.root, plan)
        self.assertEqual(report['explanations']['documented_targets'], 1)
        self.assertTrue(all(p.read_bytes() == raw for p, raw in before.items()))
        cached = json.loads((fixture.root / execution['jobs'][0]['result_ref']['path']).read_bytes())
        artifact = fixture.root / next(iter(cached['field_result_refs'].values()))['path']
        artifact.unlink()
        report = build_full_semantic_report(fixture.root, plan)
        self.assertEqual(report['explanations']['numerator'], 0)
        self.assertFalse(artifact.exists())

    def test_age_policy_keeps_the_entire_last_allowed_calendar_day(self):
        from wqb.knowledge_age_policy import KNOWLEDGE_MAX_AGE_DAYS

        self.source['captured_at'] = (datetime.now(timezone.utc) - timedelta(
            days=KNOWLEDGE_MAX_AGE_DAYS)).replace(hour=0, minute=0, second=0).isoformat()
        self.write('machine/source_index.jsonl', self.source)
        plan = self.plan(1)
        self.assertEqual(self.execute(plan)['status'], 'completed')
        report = build_full_semantic_report(self.root, plan)
        self.assertEqual(report['explanations']['numerator'], 2)

    def test_unvalidated_start_claims_do_not_define_measured_lanes(self):
        plan = self.plan()
        self.write('machine/reports/start_consumption.json', dict(status='validated',
            source_bound=True, consumed_targets=plan['jobs'][0]['target_ids'], lane_count=999))
        report = build_full_semantic_report(self.root, plan)
        self.assertEqual(report['start_consumption']['numerator'], 0)
        self.assertIsNone(report['start_consumption']['denominator'])

    def test_inventory_is_streamed_not_read_as_one_full_copy(self):
        from unittest.mock import patch

        plan = self.plan()
        inventory_path = self.root / plan['inventory_ref']['path']
        original = Path.read_bytes

        def bounded(path):
            """Input: Path. Output: normal bytes, but deny whole-file inventory copies."""
            if path == inventory_path:
                raise AssertionError('inventory must be streamed')
            return original(path)

        with patch.object(Path, 'read_bytes', bounded):
            report = build_full_semantic_report(self.root, plan, detailed=True)
        self.assertEqual(report['inventory']['denominator'], 2)
        self.assertEqual(report['inventory_ref'], plan['inventory_ref'])
        self.assertNotIn('occurrences', report['targets'][0])

    def test_completed_reservation_audit_does_not_reload_full_inventory(self):
        from unittest.mock import patch

        plan = self.plan(1)
        self.execute(plan)
        path = self.root / plan['inventory_ref']['path']
        original = Path.read_bytes

        def bounded(current):
            """Input: Path. Output: normal bytes except forbidden whole-inventory reads."""
            if current == path:
                raise AssertionError('reservation audit must reuse authenticated plan')
            return original(current)

        with patch.object(Path, 'read_bytes', bounded):
            report = build_full_semantic_report(self.root, plan)
        self.assertEqual(report['explanations']['numerator'], 2)

    def test_report_reuses_canonical_reservation_authority_validator(self):
        """Input: completed result. Output: canonical reservation check, not a second trust implementation."""
        from unittest.mock import patch
        import wqb.full_semantic_coverage as coverage
        import wqb.full_semantic_execution as execution
        plan = self.plan(1)
        self.execute(plan)
        with patch.object(coverage, '_verify_state', wraps=execution._verify_state, create=True) as verify:
            report = build_full_semantic_report(self.root, plan)
        self.assertEqual(report['explanations']['numerator'], 2)
        self.assertEqual(verify.call_count, len(plan['jobs']))

    def test_inventory_mutation_after_validation_prevents_report_publication(self):
        """Input: inventory changes after cache authentication. Output: failure before any report is written."""
        from unittest.mock import patch
        import wqb.full_semantic_coverage as coverage
        plan = self.plan(1)
        self.execute(plan)
        validate = coverage._validate_explanation
        def mutate(*args, **kwargs):
            """Input: validation args. Output: real validation followed by a simulated concurrent inventory write."""
            result = validate(*args, **kwargs)
            with (self.root / plan['inventory_ref']['path']).open('ab') as stream:
                stream.write(b'\n')
            return result
        with patch.object(coverage, '_validate_explanation', mutate), self.assertRaisesRegex(ValueError, 'inventory changed'):
            build_full_semantic_report(self.root, plan)
        self.assertFalse((self.root / 'machine/reports').exists())

    def test_inventory_tamper_is_rejected_before_any_report_write(self):
        plan = self.plan()
        with (self.root / plan['inventory_ref']['path']).open('ab') as stream:
            stream.write(b'\n')
        with self.assertRaises(ValueError):
            build_full_semantic_report(self.root, plan)
        self.assertFalse((self.root / 'machine/reports').exists())

    def test_stale_execution_contracts_remain_diagnostics_not_call_authority(self):
        from unittest.mock import patch
        import wqb.full_semantic_execution as execution

        plan = self.plan()
        before = self.snapshot()
        with patch.object(execution, '_contracts', return_value=dict(stale_contract=True)):
            report = build_full_semantic_report(self.root, plan)
        self.assertEqual(report['explanations']['numerator'], 0)
        self.assertEqual(report['explanations']['denominator'], 2)
        self.assertEqual(report['model_calls'], 0)
        self.assertFalse(report['research_authorized'])
        self.assertTrue(any('contracts differ' in d.get('reason', '') for d in report['diagnostics']))
        self.assertEqual(before, self.snapshot())


if __name__ == '__main__':
    unittest.main()
