"""K4 execution tests: temporary vaults and fake synchronous executors only."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from wqb.full_semantic_compile import prepare_full_semantic_compile
from wqb.full_semantic_execution import (
    run_full_semantic_compile, load_bound_explanation_job,
    full_semantic_output_schema, validate_full_semantic_output,
)


class FullSemanticExecutionTests(unittest.TestCase):
    def setUp(self):
        """Input: TestCase. Output: isolated two-target raw/index fixture with cleanup."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.path = 'raw/platform/learn/day/operators.md'
        self.text = '### rank\n- Description: Cross-sectional rank.\n### delta\n- Description: Change.\n'
        self.write(self.path, self.text)
        self.source = dict(path=self.path, content_hash=hashlib.sha256(self.text.encode()).hexdigest(),
            captured_at='2026-10-23T00:00:00Z', source_type='platform_learn_material',
            source_family='raw/platform/learn')
        self.write('machine/source_index.jsonl', self.source)

    def write(self, relative, value):
        """Input: relative path str/object. Output: Path; write temporary fixture bytes."""
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value if isinstance(value, str) else json.dumps(value), encoding='utf-8', newline='\n')
        return path

    def plan(self, budget=1, **config):
        """Input: budget int/config kwargs. Output: immutable prepared plan dict."""
        return prepare_full_semantic_compile(self.root, dict(model_call_budget=budget, **config))

    def loaded(self, plan):
        """Input: prepared plan dict. Output: authenticated first explanation job dict."""
        return load_bound_explanation_job((self.root / plan['jobs'][0]['path']).parent)

    def answer(self, job):
        """Input: authenticated job dict. Output: strict unresolved answer with no invented facts."""
        return dict(summary='Explicit semantic gaps retained', targets=[dict(target_id=t['target_id'],
            identity=t['identity'], literal_fact_summary=None, typed_facts={}, hypothesis_cards=[],
            conditional_uses=[], missing_facts=['Typed meaning not established'], conflicting_facts=[],
            evidence_refs=[]) for t in job['input']['targets']])

    def fake(self, *, job, output_schema, deadline):
        """Input: authenticated job/schema/deadline. Output: full fake answer; no real calls."""
        self.assertEqual(output_schema['additionalProperties'], False)
        self.assertGreater(deadline, 0)
        state = json.loads((Path(job['job_dir']) / 'execution_state.json').read_bytes())
        self.assertEqual(state['status'], 'running')
        self.assertTrue(state['reservation_id'])
        return self.answer(job)

    def test_user_evidence_is_hypothesis_only_not_documented_authority(self):
        """Input: original-bound user note. Output: accepted hypothesis, rejected factual relabeling."""
        from wqb.full_semantic_execution import _evidence
        path, text = 'raw/user/idea.txt', 'A falsifiable economic mechanism.'
        source = dict(path=path, source_type='user_note', source_family='raw/user',
                      captured_at='2026-10-23T00:00:00Z',
                      content_hash=hashlib.sha256(text.encode()).hexdigest())
        ref = dict(source_path=path, sha256=source['content_hash'],
                   capture_date='2026-10-23', kind='hypothesis', experiment_refs=[])
        job = dict(source_index={path: source}, source_texts={path: text})
        _evidence([ref], job, hypothesis=True)
        with self.assertRaises(ValueError):
            _evidence([dict(ref, kind='documented')], job)
        with self.assertRaises(ValueError):
            _evidence([ref], dict(job, source_texts={path: 'Altered'}), hypothesis=True)

    def test_zero_budget_never_dispatches_or_confuses_preparation_with_completion(self):
        plan = self.plan(0)
        result = run_full_semantic_compile(self.root, plan, executor=lambda **kw: self.fail('callback'))
        self.assertEqual(result['model_calls'], 0)
        self.assertEqual(result['calls_reserved'], 0)
        self.assertEqual(result['budget_remaining'], 0)
        self.assertEqual(len(result['targets']), 2)
        self.assertTrue(all(t['status'] == 'budget_blocked' for t in result['targets']))

    def test_field_batch_reads_canonical_ledger_once_not_once_per_target(self):
        """Input: two field targets in one job. Output: one ledger scan and both validated gaps."""
        from tests.test_full_semantic_inventory import FullSemanticInventoryTests
        from wqb import full_semantic_execution as module
        fixture = FullSemanticInventoryTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.source('raw/platform/data_fields/day/data_fields.jsonl',
                       ''.join(json.dumps(fixture.field(name=name)) + '\n' for name in ('x', 'y')))
        plan = prepare_full_semantic_compile(fixture.root, {})
        job = load_bound_explanation_job((fixture.root / plan['jobs'][0]['path']).parent)
        calls, original = [], module._rows
        def rows(path, diagnostics):
            """Input: canonical source Path/diagnostics. Output: original rows with read-count evidence."""
            if path.name == 'data_ledger.jsonl':
                calls.append(path)
            yield from original(path, diagnostics)
        with patch.object(module, '_rows', rows):
            result = validate_full_semantic_output(fixture.root, job, self.answer(job))
        self.assertEqual(len(result['target_validation']), 2)
        self.assertEqual(len(calls), 1)

    def test_finite_reservation_full_result_and_completed_reuse_at_zero_budget(self):
        plan = self.plan()
        result = run_full_semantic_compile(self.root, plan, executor=self.fake)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['model_calls'], 1)
        self.assertEqual(result['calls_reserved'], 1)
        self.assertEqual(result['budget_remaining'], 0)
        self.assertEqual(len(result['targets']), 2)
        self.assertTrue(all('missing_facts' in t['result'] for t in result['targets']))
        self.assertTrue(result['full_processing_coverage'])
        self.assertFalse(result['full_coverage'])
        self.assertEqual(result['coverage']['target_count'], 2)
        self.assertEqual(result['coverage']['processed_targets'], 2)
        self.assertEqual(result['coverage']['explained_targets'], 0)
        self.assertEqual(result['coverage']['verified_targets'], 0)
        self.assertEqual(result['coverage']['eligible_targets'], 0)
        cached = run_full_semantic_compile(self.root, self.plan(0), executor=lambda **kw: self.fail('replay'))
        self.assertEqual(cached['status'], 'completed')
        self.assertEqual(cached['model_calls'], 0)
        self.assertTrue(all(t['status'] == 'cached' for t in cached['targets']))

    def test_forged_budget_root_and_job_reference_fail_before_callback(self):
        plan = self.plan(0)
        cases = []
        budget = deepcopy(plan)
        budget['budget']['model_call_budget'] = 20
        cases.append(budget)
        root = deepcopy(plan)
        root['root'] = str(self.root.parent)
        cases.append(root)
        job = deepcopy(plan)
        job['jobs'][0]['target_ids'].append('forged')
        cases.append(job)
        for forged in cases:
            with self.subTest(forged=forged):
                result = run_full_semantic_compile(self.root, forged, executor=lambda **kw: self.fail('callback'))
                self.assertEqual(result['status'], 'blocked')
                self.assertEqual(result['model_calls'], 0)

    def test_loader_detects_input_brief_manifest_and_current_source_tampering(self):
        plan = self.plan()
        job_dir = (self.root / plan['jobs'][0]['path']).parent
        for name in ['input.json', 'brief.txt', 'run_manifest.json']:
            path = job_dir / name
            original = path.read_bytes()
            path.write_bytes(original + b' ')
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.loaded(plan)
            path.write_bytes(original)
        self.write(self.path, self.text + 'Changed\n')
        with self.assertRaises(ValueError):
            self.loaded(plan)
        self.write(self.path, self.text)
        self.write('machine/source_index.jsonl', dict(self.source, captured_at='2000-01-01T00:00:00Z'))
        with self.assertRaises(ValueError):
            self.loaded(plan)

    def test_exact_output_keys_and_target_accounting_are_strict(self):
        job = self.loaded(self.plan())
        answer = self.answer(job)
        mutations = []
        duplicate = deepcopy(answer)
        duplicate['targets'].append(deepcopy(duplicate['targets'][0]))
        mutations.append(duplicate)
        missing = deepcopy(answer)
        missing['targets'].pop()
        mutations.append(missing)
        extra = deepcopy(answer)
        extra['targets'][0]['target_id'] = 'extra'
        mutations.append(extra)
        unknown = deepcopy(answer)
        unknown['trusted'] = True
        mutations.append(unknown)
        unknown = deepcopy(answer)
        unknown['targets'][0]['formula'] = 'rank(x)'
        mutations.append(unknown)
        for bad in mutations:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                validate_full_semantic_output(self.root, job, bad)
        validated = validate_full_semantic_output(self.root, job, answer)
        self.assertEqual(validated['targets'], answer['targets'])

    def test_null_literal_requires_reason_and_invented_types_polarity_formulas_reject(self):
        job = self.loaded(self.plan())
        for mutation in ['missing_reason', 'literal', 'type', 'polarity', 'formula']:
            answer = self.answer(job)
            target = answer['targets'][0]
            if mutation == 'missing_reason':
                target['missing_facts'] = []
            elif mutation == 'literal':
                target['literal_fact_summary'] = 'Guaranteed future returns'
            elif mutation == 'formula':
                target['missing_facts'] = ['Try fabricated_operator(x)']
            else:
                target['typed_facts'][mutation] = {'value': 'positive', 'premises': []}
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                validate_full_semantic_output(self.root, job, answer)

    def test_measured_hypothesis_claims_reject_but_classified_cards_survive(self):
        from wqb.semantic_contracts import CARD_FIELDS
        job = self.loaded(self.plan())
        answer = self.answer(job)
        ref = dict(source_path=self.path, sha256=self.source['content_hash'], capture_date='2026-10-23',
                   kind='hypothesis', experiment_refs=[])
        card = dict(hypothesis_card={key: 'A test hypothesis' for key in CARD_FIELDS}, evidence_refs=[ref])
        answer['targets'][0]['hypothesis_cards'] = [card]
        self.assertEqual(validate_full_semantic_output(self.root, job, answer)['targets'], answer['targets'])
        ref.update(kind='measured', experiment_refs=['raw/research/run/report.md'])
        with self.assertRaisesRegex(ValueError, 'measured'):
            validate_full_semantic_output(self.root, job, answer)

    def test_unknown_running_and_failed_jobs_never_replay_under_a_new_plan(self):
        plan = self.plan()
        def unknown(**kwargs):
            """Input: fake kwargs. Output: exception representing uncertain transport outcome."""
            raise RuntimeError('outcome uncertain')
        first = run_full_semantic_compile(self.root, plan, executor=unknown)
        self.assertEqual(first['calls_reserved'], 1)
        self.assertTrue(all(t['status'] == 'outcome_unknown' for t in first['targets']))
        second = run_full_semantic_compile(self.root, self.plan(3), executor=lambda **kw: self.fail('replayed'))
        self.assertEqual(second['model_calls'], 0)
        self.assertTrue(second['blockers'])

    def test_invalid_output_terminal_without_refund(self):
        result = run_full_semantic_compile(self.root, self.plan(), executor=lambda **kw: {'summary': 'only'})
        self.assertEqual(result['calls_reserved'], 1)
        self.assertTrue(all(t['status'] == 'rejected' for t in result['targets']))
        repeated = run_full_semantic_compile(self.root, self.plan(2), executor=lambda **kw: self.fail('retry'))
        self.assertEqual(repeated['model_calls'], 0)

    def test_finite_budget_stops_between_jobs(self):
        plan = self.plan(1, max_targets_per_job=1)
        result = run_full_semantic_compile(self.root, plan, executor=self.fake)
        self.assertEqual(result['model_calls'], 1)
        self.assertEqual(result['budget_remaining'], 0)
        self.assertEqual({t['status'] for t in result['targets']}, {'completed', 'budget_blocked'})

    def test_original_deadline_survives_restart_and_cancel_is_durable(self):
        plan = self.plan(2, max_targets_per_job=1, max_runtime_seconds=10)
        clock = [1000.0]
        def slow(**kwargs):
            """Input: fake callback kwargs. Output: answer after deterministic deadline advancement."""
            clock[0] += 11
            return self.answer(kwargs['job'])
        with patch('wqb.full_semantic_execution.time.time', side_effect=lambda: clock[0]):
            first = run_full_semantic_compile(self.root, plan, executor=slow)
            second = run_full_semantic_compile(self.root, plan, executor=lambda **kw: self.fail('deadline reset'))
        self.assertEqual(first['deadline'], 1010.0)
        self.assertEqual(second['deadline'], 1010.0)
        self.assertEqual(second['model_calls'], 0)
        plan = self.plan(2, rules_version='cancel')
        control = (self.root / plan['plan_path']).parent / 'control.json'
        control.write_text('{"cancelled":true}', encoding='utf-8')
        cancelled = run_full_semantic_compile(self.root, plan, executor=lambda **kw: self.fail('cancelled'))
        control.write_text('{"cancelled":false}', encoding='utf-8')
        repeated = run_full_semantic_compile(self.root, plan, executor=lambda **kw: self.fail('uncancelled'))
        self.assertEqual(cancelled['status'], 'cancelled')
        self.assertEqual(repeated['status'], 'cancelled')

    def test_canonical_manifest_authority_fields_cannot_be_forged(self):
        from wqb.full_semantic_compile import _bytes
        plan = self.plan()
        path = self.root / plan['jobs'][0]['path']
        original = path.read_bytes()
        for key, value in [('model_calls', 12), ('gaps', ['forged']), ('trusted', True)]:
            altered = json.loads(original)
            altered[key] = value
            path.write_bytes(_bytes(altered))
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.loaded(plan)
            path.write_bytes(original)

    def test_execution_state_cannot_claim_unreserved_completion(self):
        plan = self.plan(0)
        job_dir = (self.root / plan['jobs'][0]['path']).parent
        self.write((job_dir / 'execution_state.json').relative_to(self.root).as_posix(),
                   dict(status='completed', job_id=plan['jobs'][0]['job_id'],
                        input_sha256=plan['jobs'][0]['input_sha256'], owner_plan='forged'))
        result = run_full_semantic_compile(self.root, plan, executor=lambda **kw: self.fail('callback'))
        self.assertTrue(any('reservation' in str(b) for b in result['blockers']))

    def test_source_changes_during_executor_reject_and_do_not_refund(self):
        plan = self.plan()
        def changed(**kwargs):
            """Input: fake callback kwargs. Output: answer after changing the bound source."""
            answer = self.answer(kwargs['job'])
            self.write(self.path, self.text + '\nChanged')
            return answer
        result = run_full_semantic_compile(self.root, plan, executor=changed)
        self.assertEqual(result['calls_reserved'], 1)
        self.assertEqual(result['budget_remaining'], 0)
        self.assertTrue(all(t['status'] == 'rejected' for t in result['targets']))

    def test_interrupted_running_state_is_not_replayed_on_restart(self):
        plan = self.plan()
        def interrupted(**kwargs):
            """Input: fake kwargs. Output: process-style interruption after durable reservation."""
            raise SystemExit('interruption')
        with self.assertRaises(SystemExit):
            run_full_semantic_compile(self.root, plan, executor=interrupted)
        restarted = run_full_semantic_compile(self.root, self.plan(2), executor=lambda **kw: self.fail('replay'))
        self.assertTrue(all(t['status'] == 'outcome_unknown' for t in restarted['targets']))

    def test_field_fact_uses_real_k3_resolver_and_never_updates_canonical_selector(self):
        from tests.test_field_semantic_enrichment import FieldSemanticEnrichmentTests
        from wqb.knowledge_compile import resolve_field_semantics
        fixture = FieldSemanticEnrichmentTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        root = fixture.root
        before = fixture.ledger.read_bytes()
        plan = prepare_full_semantic_compile(root, dict(model_call_budget=1))
        job = load_bound_explanation_job((root / plan['jobs'][0]['path']).parent)
        answer = self.answer(job)
        target = answer['targets'][0]
        target.update(literal_fact_summary='Cash balance', typed_facts=dict(units=fixture.fact('units', 'USD')),
                      evidence_refs=[fixture.evidence])
        validated = validate_full_semantic_output(root, job, answer)
        target_id = target['target_id']
        self.assertEqual(validated['target_validation'][target_id]['status'], 'supported')
        ref = validated['field_result_refs'][target_id]
        selected = dict(fixture.row, field_semantics_ref=dict(schema_version=1, **ref, dataset_id='d', field_id='f'))
        self.assertEqual(resolve_field_semantics(root, selected)['facts']['units'], 'USD')
        self.assertEqual(fixture.ledger.read_bytes(), before)
        target['typed_facts']['units']['value'] = 'invented'
        with self.assertRaisesRegex(ValueError, 'K3'):
            validate_full_semantic_output(root, job, answer)

    def test_readonly_validation_reconstructs_same_field_envelope_without_writes(self):
        """Input: persisted field result. Output: identical readonly envelope with unchanged files/directories."""
        from tests.test_field_semantic_enrichment import FieldSemanticEnrichmentTests
        fixture = FieldSemanticEnrichmentTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        plan = prepare_full_semantic_compile(fixture.root, dict(model_call_budget=1))
        job = load_bound_explanation_job((fixture.root / plan['jobs'][0]['path']).parent)
        answer = self.answer(job)
        answer['targets'][0].update(literal_fact_summary='Cash balance',
            typed_facts=dict(units=fixture.fact('units', 'USD')), evidence_refs=[fixture.evidence])
        expected = validate_full_semantic_output(fixture.root, job, answer)
        paths = set(fixture.root.rglob('*'))
        before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in paths if p.is_file()}
        actual = validate_full_semantic_output(fixture.root, job, answer, persist_field_results=False)
        self.assertEqual(actual, expected)
        self.assertEqual(paths, set(fixture.root.rglob('*')))
        self.assertEqual(before, {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in before})

    def test_readonly_validation_rejects_missing_or_changed_field_artifact_without_creation(self):
        """Input: no matching field artifact or altered bytes. Output: failure with no filesystem writes."""
        from tests.test_field_semantic_enrichment import FieldSemanticEnrichmentTests
        fixture = FieldSemanticEnrichmentTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        plan = prepare_full_semantic_compile(fixture.root, {})
        job = load_bound_explanation_job((fixture.root / plan['jobs'][0]['path']).parent)
        answer = self.answer(job)
        answer['targets'][0].update(literal_fact_summary='Cash balance',
            typed_facts=dict(units=fixture.fact('units', 'USD')), evidence_refs=[fixture.evidence])
        paths = set(fixture.root.rglob('*'))
        before = {p: p.read_bytes() for p in paths if p.is_file()}
        with self.assertRaisesRegex(ValueError, 'field.*artifact'):
            validate_full_semantic_output(fixture.root, job, answer, persist_field_results=False)
        self.assertEqual(paths, set(fixture.root.rglob('*')))
        self.assertEqual(before, {p: p.read_bytes() for p in before})
        validated = validate_full_semantic_output(fixture.root, job, answer)
        ref = next(iter(validated['field_result_refs'].values()))
        artifact = fixture.root / ref['path']
        artifact.write_bytes(artifact.read_bytes() + b' ')
        with self.assertRaisesRegex(ValueError, 'field.*artifact'):
            validate_full_semantic_output(fixture.root, job, answer, persist_field_results=False)

    def test_incomplete_inventory_can_process_subset_without_claiming_full_or_ready(self):
        self.write('raw/platform/data_fields/day/data_fields.jsonl', 'not json\n')
        plan = self.plan()
        result = run_full_semantic_compile(self.root, plan, executor=self.fake)
        self.assertEqual(result['model_calls'], 1)
        self.assertFalse(result['inventory_complete'])
        self.assertFalse(result['full_coverage'])
        self.assertFalse(result['research_ready'])

    def test_unknown_nonterminal_state_cannot_grant_retry(self):
        plan = self.plan()
        run_full_semantic_compile(self.root, plan, executor=self.fake)
        state_path = (self.root / plan['jobs'][0]['path']).parent / 'execution_state.json'
        state = json.loads(state_path.read_bytes())
        state['status'] = 'please_retry'
        state_path.write_text(json.dumps(state), encoding='utf-8')
        result = run_full_semantic_compile(self.root, plan, executor=lambda **kw: self.fail('callback'))
        self.assertTrue(all(t['status'] == 'blocked' for t in result['targets']))

    def test_operator_typed_definition_requires_existing_source_validator(self):
        self.text = ('### rank\n- Source id: `rank`\n- Description: Cross-sectional rank.\n'
                     '- Input types: `MATRIX`\n- Output type: `MATRIX`\n- Parameters:\n'
                     '  - `x`: type=`MATRIX`, required=`true`\n')
        self.write(self.path, self.text)
        self.source['content_hash'] = hashlib.sha256(self.text.encode()).hexdigest()
        self.write('machine/source_index.jsonl', self.source)
        job = self.loaded(self.plan())
        answer = self.answer(job)
        ref = dict(source_path=self.path, sha256=self.source['content_hash'], capture_date='2026-10-23',
                   kind='documented', experiment_refs=[])
        definition = dict(description='Cross-sectional rank.', input_types=['MATRIX'], output_type='MATRIX',
                          parameters=[dict(name='x', type='MATRIX', required=True)], evidence_refs=[ref])
        target = answer['targets'][0]
        target.update(literal_fact_summary='Cross-sectional rank.', evidence_refs=[ref],
                      typed_facts=dict(definition=definition))
        result = validate_full_semantic_output(self.root, job, answer)
        self.assertEqual(result['target_validation'][target['target_id']]['status'], 'supported')
        definition['output_type'] = 'VECTOR'
        with self.assertRaises(ValueError):
            validate_full_semantic_output(self.root, job, answer)

    def test_crash_between_job_intent_and_plan_accounting_never_replays_in_new_plan(self):
        from wqb.full_semantic_compile import _bytes
        plan = self.plan()
        job = plan['jobs'][0]
        base = 'machine/semantic_jobs/' + job['job_id']
        self.write(base + '/attempt_reservation.json', _bytes(dict(job_id=job['job_id'],
            input_sha256=job['input_sha256'], owner_plan=plan['content_key'], deadline=1234)).decode())
        result = run_full_semantic_compile(self.root, self.plan(3), executor=lambda **kw: self.fail('replay'))
        self.assertEqual(result['model_calls'], 0)
        self.assertTrue(all(t['status'] == 'outcome_unknown' for t in result['targets']))

    def test_reservation_gate_rejects_direct_prepared_job_and_accepts_only_running_callback(self):
        from wqb.full_semantic_execution import require_full_semantic_reservation
        for budget in (0, 1):
            plan = self.plan(budget)
            job = self.loaded(plan)
            with self.subTest(budget=budget), self.assertRaises(ValueError):
                require_full_semantic_reservation(job)
        def reserved(**kwargs):
            """Input: running fake callback kwargs. Output: answer after checking charged authority."""
            authority = require_full_semantic_reservation(kwargs['job'])
            self.assertEqual(authority['owner_plan'], plan['content_key'])
            self.assertEqual(authority['deadline'], kwargs['deadline'])
            self.assertEqual(authority['model_call_budget'], 1)
            self.assertEqual(authority['calls_reserved'], 1)
            self.assertEqual(authority['job_id'], job['manifest']['content_key'])
            return self.answer(kwargs['job'])
        result = run_full_semantic_compile(self.root, plan, executor=reserved)
        self.assertEqual(result['status'], 'completed')
        with self.assertRaises(ValueError):
            require_full_semantic_reservation(job)

    def test_reservation_gate_rejects_forged_original_allowance_without_writing_files(self):
        from wqb.full_semantic_execution import require_full_semantic_reservation
        from wqb.full_semantic_compile import _bytes
        plan = self.plan()
        checked = []
        def guarded(**kwargs):
            """Input: running callback kwargs. Output: answer after read-only gate and forged-budget rejection."""
            before = {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file() and p.suffix != '.guard'}
            require_full_semantic_reservation(kwargs['job'])
            self.assertEqual(before, {p: p.read_bytes() for p in before})
            path = self.root / plan['plan_path']
            original = path.read_bytes()
            forged = json.loads(original)
            forged['budget']['model_call_budget'] += 1
            path.write_bytes(_bytes(forged))
            with self.assertRaises(ValueError):
                require_full_semantic_reservation(kwargs['job'])
            path.write_bytes(original)
            checked.append(True)
            return self.answer(kwargs['job'])
        result = run_full_semantic_compile(self.root, plan, executor=guarded)
        self.assertEqual(checked, [True])
        self.assertEqual(result['status'], 'completed')

    def test_reservation_gate_rejects_controls_expiry_uncharge_and_nonrunning_state(self):
        from wqb.full_semantic_execution import require_full_semantic_reservation
        for mutation in ['job_cancel', 'plan_cancel', 'durable_cancel', 'expired', 'uncharge', 'reserved']:
            plan = self.plan(rules_version=mutation)
            checked = []
            def guarded(**kwargs):
                """Input: running fake callback kwargs. Output: valid answer after proving gate rejection."""
                job = kwargs['job']
                job_dir = Path(job['job_dir'])
                plan_dir = (self.root / plan['plan_path']).parent
                if mutation == 'expired':
                    with patch('wqb.full_semantic_execution.time.time', return_value=kwargs['deadline']):
                        with self.assertRaises(ValueError):
                            require_full_semantic_reservation(job)
                else:
                    if mutation == 'job_cancel':
                        self.write((job_dir / 'control.json').relative_to(self.root).as_posix(), dict(cancelled=True))
                    elif mutation == 'plan_cancel':
                        self.write((plan_dir / 'control.json').relative_to(self.root).as_posix(), dict(cancelled=True))
                    elif mutation == 'durable_cancel':
                        self.write((plan_dir / 'execution_state.json').relative_to(self.root).as_posix(), dict(status='cancelled'))
                    elif mutation == 'uncharge':
                        state = json.loads((job_dir / 'execution_state.json').read_bytes())
                        # Temporarily remove only this synthetic reservation file.
                        path = self.root / state['reservation_ref']['path']
                        raw = path.read_bytes()
                        path.unlink()
                    else:
                        path = job_dir / 'execution_state.json'
                        state = json.loads(path.read_bytes())
                        state['status'] = 'reserved'
                        self.write(path.relative_to(self.root).as_posix(), state)
                    with self.assertRaises(ValueError):
                        require_full_semantic_reservation(job)
                    if mutation == 'uncharge':
                        path.write_bytes(raw)
                checked.append(mutation)
                return self.answer(job)
            run_full_semantic_compile(self.root, plan, executor=guarded)
            self.assertEqual(checked, [mutation])


if __name__ == '__main__':
    unittest.main()
