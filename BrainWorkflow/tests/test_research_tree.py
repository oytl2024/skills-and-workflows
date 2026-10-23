"""Real offline compiler receipts and run-local IO; no platform/model fixtures."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from tests.test_hypothesis_design import compiler_fixture
from wqb import exploration_eligibility as eligibility
from wqb import research_tree as subject
from wqb.cli import simulation_identity_hash
from wqb.hypothesis_design import validate_hypothesis_design
from wqb.semantic_contracts import SemanticPolicy
from wqb.runtime_control import _write


class ResearchTreeTests(unittest.TestCase):
    def setUp(self):
        """Input: TestCase. Output: None; compile sourced pairs in an isolated owning Start."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.run = self.root / 'lane'
        self.run.mkdir()
        self.vault = self.root / 'knowledge'
        design, self.compiler_resources, self.scope = compiler_fixture(treatment=True)
        self.period = {'start': '2020-01-01', 'end': '2025-12-31'}
        for relative, text in self.compiler_resources['source_texts'].items():
            path = self.vault / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding='utf-8')
        index = self.vault / 'machine/source_index.jsonl'
        index.parent.mkdir(parents=True)
        index.write_text(''.join(json.dumps(row) + '\n' for row in
                                self.compiler_resources['source_index'].values()), encoding='utf-8')
        self.manifest = dict(run_id=self.run.name, knowledge_root=str(self.vault),
            selected_scope=self.scope, start_snapshot=dict(selected_scope=self.scope,
                research_policy=dict(exploration_scout=True, paired_scout=True,
                                     exploration_policy_version=1)))
        _write(self.run / 'run_manifest.json', self.manifest)
        # The real resource-only IO producer must run BEFORE any compiler result.
        cert = eligibility.certify_exploration_resources(
            self.run, self.vault, self.compiler_resources, self.scope)
        self.receipts = {}
        leaf = dict(kind='role', role='pulse')
        features = [dict(kind='level', input=leaf)] + [
            dict(kind='change', input=leaf, horizon=n) for n in (5, 22, 122, 252)]
        for name, a, b, direction in [('root', 0, 1, 'positive'),
                                       ('left', 0, 2, 'positive'),
                                       ('right', 1, 3, 'positive'),
                                       ('fallback', 2, 4, 'positive'),
                                       ('reverse', 0, 1, 'negative')]:
            raw = deepcopy(design)
            raw.pop('design_id')
            raw['prediction_direction'] = direction
            raw['feature_plan'] = deepcopy(features[a])
            raw['experiment_plan']['baseline'] = deepcopy(features[a])
            raw['experiment_plan']['treatments'][0]['feature'] = deepcopy(features[b])
            normalized = validate_hypothesis_design(dict(summary='Offline tree.', designs=[raw]),
                self.compiler_resources['evidence_pack'], SemanticPolicy())['designs'][0]
            self.receipts[name] = eligibility.validate_exploration(
                normalized, self.compiler_resources, self.scope)
        snapshot = eligibility.build_exploration_snapshot(list(self.receipts.values()),
            resource_certificates=[cert] * len(self.receipts))
        snapshot['measurement_period'] = self.period
        snapshot['tree_comparison_policy'] = dict(schema_version=1, edit='feature',
            target_metric='fitness', target_direction='increase', turnover_max=.4)
        self.manifest['start_snapshot'] = snapshot
        _write(self.run / 'run_manifest.json', self.manifest)
        self.resources = dict(compiled_pairs={key: row['compiled'] for key, row in self.receipts.items()},
                              sources=deepcopy(self.compiler_resources['source_index']))
        self.tree = dict(schema_version=1, scope=self.scope, period=self.period,
            source_ids=sorted(self.resources['sources']), roots=['root'], nodes=[])
        for name, parent, arm in [('root', None, None), ('left', 'root', 'baseline'),
                                  ('right', 'root', 'treatment')]:
            self.tree['nodes'].append(dict(node_id=name, parent_id=parent, parent_arm_id=arm,
                pair_ref=name, expected_simulation_identities=self.identities(name),
                targets=dict(baseline=['left'] if name == 'root' else [],
                             treatment=['right'] if name == 'root' else []), fallback=[], reverse={}))
        _write(self.run / 'runtime_control.json', dict(desired_state='running', enable_live_api=False,
            request_revision='offline', max_simulations=150, max_runtime_seconds=3600, max_recoveries=3))
        _write(self.run / 'runtime_status.json', dict(simulation_attempts=0, elapsed_seconds=0))

    def identities(self, name):
        """Input: pair ref str. Output: dict[str,str] of authoritative CLI arm hashes."""
        return {arm['arm_id']: simulation_identity_hash(arm['binding']['bound_expression'], arm['settings'])
                for arm in self.receipts[name]['compiled']['experiment']['arms']}

    def checked(self, name='root', arm='baseline', sharpe=1.0, fitness=.6, **changes):
        """Input: compiled arm ref and metric overrides. Output: existing checked-record dict."""
        compiled = next(row for row in self.receipts[name]['compiled']['experiment']['arms']
                        if row['arm_id'] == arm)
        identity = self.identities(name)[arm]
        row = dict(status='CHECKED', alpha_id=identity[:12], expression_hash=identity,
            expression=compiled['binding']['bound_expression'], settings=deepcopy(compiled['settings']),
            scope=self.scope, measurement_scope='IS', measurement_period=self.period,
            test_period=self.period, metrics=dict(sharpe=sharpe, fitness=fitness, returns=.1, turnover=.2),
            hard_pass=False, failed=[], pending=['SELF_CORRELATION', 'PROD_CORRELATION'])
        return row | changes

    def freeze(self):
        """Input: fixture. Output: immutable adapter attachment dict."""
        return subject.freeze_tree(self.run, self.tree, self.resources)

    def advance(self, rows=None, maximum=30):
        """Input: optional measured rows/list and maximum/int. Output: adapter plan dict."""
        return subject.advance_tree(self.run, rows or [], maximum)

    def test_freeze_authenticates_real_compiler_and_never_rewrites_manifest(self):
        before = (self.run / 'run_manifest.json').read_bytes()
        saved = self.freeze()
        self.assertEqual(saved, self.freeze())
        self.assertEqual(saved['status'], 'frozen')
        self.assertEqual(saved['tree_digest'], json.loads(
            (self.run / 'runtime/experiment_tree.json').read_text(encoding='utf-8'))['tree_digest'])
        self.assertEqual(before, (self.run / 'run_manifest.json').read_bytes())
        self.assertEqual(saved['simulation_count'], 4)
        self.tree['nodes'][0]['targets']['baseline'] = []
        with self.assertRaises(ValueError):
            self.freeze()

    def test_compiler_output_identity_scope_period_and_sources_cannot_be_forged(self):
        original = deepcopy((self.tree, self.resources))
        for mutation in ('expression', 'digest', 'draft', 'identity', 'scope', 'period', 'source'):
            self.tree, self.resources = deepcopy(original)
            if mutation == 'expression':
                self.resources['compiled_pairs']['root']['experiment']['arms'][0]['binding']['bound_expression'] = 'invented'
            elif mutation == 'digest':
                self.resources['compiled_pairs']['root']['compilation_digest'] = 'invented'
            elif mutation == 'draft':
                self.resources['compiled_pairs']['root']['drafts'][0]['semantic_status'] = 'reviewed'
            elif mutation == 'identity':
                self.tree['nodes'][0]['expected_simulation_identities']['baseline'] = 'invented'
            elif mutation == 'scope':
                self.tree['scope'] = dict(self.scope, universe='other')
            elif mutation == 'period':
                self.tree['period'] = dict(self.period, end='2024-12-31')
            else:
                self.resources['sources'][self.tree['source_ids'][0]]['content_hash'] = '0' * 64
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                self.freeze()
        self.assertFalse((self.run / 'runtime/experiment_tree.json').exists())

    def test_missing_certificate_and_changed_raw_fail_even_with_self_consistent_receipts(self):
        raw = self.vault / next(iter(self.compiler_resources['source_texts']))
        before = raw.read_bytes()
        raw.write_bytes(before + b'changed')
        with self.assertRaises(ValueError):
            self.freeze()
        raw.write_bytes(before)
        self.manifest['start_snapshot']['exploration_context'].pop('resource_certificates')
        _write(self.run / 'run_manifest.json', self.manifest)
        with self.assertRaises(ValueError):
            self.freeze()

    def test_stale_raw_gate_projects_blocked_instead_of_leaving_ready_summary(self):
        self.freeze()
        self.advance()
        raw = self.vault / next(iter(self.compiler_resources['source_texts']))
        raw.write_bytes(raw.read_bytes() + b'changed')
        with self.assertRaises(ValueError):
            self.advance()
        summary = json.loads((self.run / 'runtime/tree_execution.json').read_text(encoding='utf-8'))
        self.assertEqual(summary['status'], 'blocked')
        self.assertFalse(summary['accepted_incumbents'])
        self.assertEqual(summary['retained_expression_hashes'], [])

    def test_whole_pair_budget_and_replay_use_existing_generator_schema(self):
        from wqb.generator import generate_hypothesis_candidates, hypothesis_candidate_metadata
        self.freeze()
        limited = self.advance(maximum=1)
        self.assertEqual(limited['candidates'], [])
        self.assertEqual(limited['status'], 'budget_wait')
        plan = self.advance(maximum=2)
        self.assertEqual(len(plan['candidates']), 2)
        self.assertEqual(self.advance(maximum=30)['plan_id'], plan['plan_id'])
        patch = plan['config_patch']
        candidates = generate_hypothesis_candidates(patch['hypothesis_snapshot'], patch['scheduled_hypotheses'], 30)
        self.assertEqual(len(candidates), 2)
        for candidate in plan['candidates']:
            audit = hypothesis_candidate_metadata(patch['hypothesis_snapshot'], candidate, patch['ai_plan_receipt'])
            self.assertTrue(audit['experiment_arms'])

    def test_reduced_quota_waits_without_invalidating_unsubmitted_reservation(self):
        self.freeze()
        plan = self.advance(maximum=2)
        result = self.advance(maximum=1)
        self.assertEqual(result['status'], 'budget_wait')
        self.assertFalse(result['candidates'])
        self.assertEqual(self.advance(maximum=2)['plan_id'], plan['plan_id'])

    def test_both_signals_expand_all_children_and_reuse_measured_parents(self):
        self.freeze()
        self.advance()
        plan = self.advance([self.checked(), self.checked(arm='treatment')])
        self.assertEqual(plan['selected_node_ids'], ['left', 'right'])
        self.assertEqual(len(plan['candidates']), 2)
        actual = {row['bound_expression'] for row in plan['candidates']}
        expected = {self.checked(name, 'treatment')['expression'] for name in ('left', 'right')}
        self.assertEqual(actual, expected)
        self.assertEqual(self.advance()['plan_id'], plan['plan_id'])

    def test_partial_unknown_failed_and_out_of_period_never_take_fallback(self):
        self.add_fallback()
        self.freeze()
        self.advance()
        for changes in ({'status': 'unknown'}, {'status': 'failed'},
                        {'measurement_period': dict(self.period, start='2021-01-01')},
                        {'metrics': dict(sharpe=None, returns=.1)}, {'pending': ['LOW_SHARPE']}):
            rows = [self.checked(sharpe=0), self.checked(arm='treatment', sharpe=0, **changes)]
            result = self.advance(rows)
            self.assertNotIn('fallback', result['selected_node_ids'])
            self.assertFalse(result['candidates'])

    def test_actual_report_period_cannot_be_relabelled_as_the_frozen_period(self):
        self.freeze()
        row = self.checked(arm='treatment')
        row['metrics'].update(startDate='2021-01-01', endDate=self.period['end'])
        result = self.advance([self.checked(), row])
        self.assertFalse(result['routes']['root']['selected_node_ids'])
        self.assertFalse(result['candidates'])

    def add_fallback(self):
        """Input: fixture. Output: None; declare a real-compiled no-signal alternate pair."""
        node = deepcopy(self.tree['nodes'][1])
        node.update(node_id='fallback', pair_ref='fallback', parent_arm_id='fallback',
                    expected_simulation_identities=self.identities('fallback'))
        self.tree['nodes'][0]['fallback'] = ['fallback']
        self.tree['nodes'].append(node)

    def test_no_signal_uses_only_frozen_fallback_with_complete_budget(self):
        self.add_fallback()
        saved = self.freeze()
        self.assertEqual(saved['simulation_count'], 5)
        plan = self.advance([self.checked(sharpe=0), self.checked(arm='treatment', sharpe=0)], maximum=1)
        self.assertEqual(plan['status'], 'budget_wait')
        self.assertFalse(plan['candidates'])
        plan = self.advance(maximum=2)
        self.assertEqual(plan['selected_node_ids'], ['fallback'])
        self.assertEqual(len(plan['candidates']), 2)

    def test_negative_requires_actual_reverse_and_never_inverts_metrics(self):
        root = self.tree['nodes'][0]
        root['reverse'] = {arm: dict(pair_ref='reverse', arm_id=arm,
            simulation_identity=self.identities('reverse')[arm], interpretation='Frozen opposite response.',
            targets=[]) for arm in ('baseline', 'treatment')}
        self.assertEqual(self.freeze()['simulation_count'], 6)
        rows = [self.checked(sharpe=-1), self.checked(arm='treatment', sharpe=-1)]
        for row in rows:
            row['metrics']['returns'] = -.1
        plan = self.advance(rows)
        self.assertEqual(len(plan['candidates']), 2)
        self.assertEqual({row['bound_expression'] for row in plan['candidates']},
                         {self.checked('reverse', arm)['expression'] for arm in ('baseline', 'treatment')})
        final = self.advance([self.checked('reverse'), self.checked('reverse', 'treatment')])
        self.assertEqual(final['routes']['root']['selected_arm_ids'], ['baseline', 'treatment'])
        self.assertFalse(final['candidates'])

    def test_terminal_positive_reverse_is_retained_as_measured_seed_core(self):
        root = self.tree['nodes'][0]
        root['reverse'] = {arm: dict(pair_ref='reverse', arm_id=arm,
            simulation_identity=self.identities('reverse')[arm], interpretation='Frozen opposite response.',
            targets=[]) for arm in ('baseline', 'treatment')}
        self.freeze()
        original = [self.checked(sharpe=-1.5), self.checked(arm='treatment', sharpe=-1.6)]
        for row in original:
            row['metrics']['returns'] = -.1
        self.advance(original)
        result = self.advance([self.checked('reverse', sharpe=1.6, fitness=.8),
                               self.checked('reverse', 'treatment', sharpe=1.8, fitness=.9)])
        self.assertEqual(result['status'], 'finished')
        retained = json.loads((self.run / 'runtime/tree_execution.json').read_text())['retained_expression_hashes']
        self.assertIn(self.identities('reverse')['treatment'], retained)

    def test_stop_boundary_preserves_unsubmitted_plan_and_does_not_call_executor(self):
        self.freeze()
        plan = self.advance()
        control = json.loads((self.run / 'runtime_control.json').read_text(encoding='utf-8'))
        _write(self.run / 'runtime_control.json', control | dict(desired_state='paused'))
        def forbidden(config, metadata):
            """Input: executor dicts. Output: raises if Stop is bypassed."""
            self.fail('executor called after Stop')
        result = subject.execute_tree_round(self.run, forbidden)
        self.assertEqual(result['status'], 'stopped')
        _write(self.run / 'runtime_control.json', control)
        self.assertEqual(self.advance()['plan_id'], plan['plan_id'])

    def test_executor_uncertainty_is_durable_and_cannot_blindly_redispatch(self):
        self.freeze()
        calls = []
        def uncertain(config, metadata):
            """Input: frozen config/metadata dicts. Output: raise after accepting a durable handoff."""
            calls.append(metadata['tree_plan_id'])
            raise TimeoutError('unknown POST outcome')
        with self.assertRaises(TimeoutError):
            subject.execute_tree_round(self.run, uncertain)
        result = subject.execute_tree_round(self.run, uncertain)
        self.assertEqual(result['status'], 'recover')
        self.assertFalse(result['candidates'])
        self.assertEqual(len(calls), 1)

    def test_injected_executor_can_read_existing_generator_metadata_after_handoff(self):
        from wqb.generator import generate_hypothesis_candidates, hypothesis_candidate_metadata
        self.freeze()
        calls = []
        def executor(config, metadata):
            """Input: existing batch config/metadata. Output: offline receipt after real generator verification."""
            candidates = generate_hypothesis_candidates(config['hypothesis_snapshot'], config['scheduled_hypotheses'], 30)
            audits = [hypothesis_candidate_metadata(config['hypothesis_snapshot'], candidate,
                config['ai_plan_receipt']) for candidate in config['scheduled_hypotheses']]
            calls.append(metadata['tree_plan_id'])
            return dict(generated=len(candidates), audited=len(audits))
        result = subject.execute_tree_round(self.run, executor)
        self.assertEqual(result['executor_result'], dict(generated=2, audited=2))
        self.assertEqual(subject.execute_tree_round(self.run, executor)['status'], 'recover')
        self.assertEqual(len(calls), 1)

    def test_incumbent_uses_real_comparison_not_signal_selection(self):
        self.freeze()
        parent, child = self.checked(sharpe=1.5), self.checked(arm='treatment', sharpe=1.6, fitness=.8)
        result = self.advance([parent, child])
        self.assertEqual(result['comparisons']['root']['outcome'], 'accepted')
        self.assertEqual(result['accepted_incumbents']['root']['alpha_id'], child['alpha_id'])
        child['metrics']['fitness'] = .4
        # Conflicting final measurements are not overwritten by a convenient later result.
        result = self.advance([child])
        self.assertNotEqual(result['comparisons']['root']['outcome'], 'accepted')

    def test_execution_summary_is_derived_and_preserves_incumbent_references(self):
        frozen = self.freeze()
        parent = self.checked(sharpe=1.5)
        child = self.checked(arm='treatment', sharpe=1.6, fitness=.8)
        result = self.advance([parent, child])
        path = self.run / 'runtime/tree_execution.json'
        summary = json.loads(path.read_text(encoding='utf-8'))
        self.assertEqual(summary['status'], result['status'])
        self.assertEqual(summary['tree_digest'], frozen['tree_digest'])
        self.assertEqual(summary['accepted_incumbents']['root']['expression_hash'], child['expression_hash'])
        self.assertEqual(summary['retained_expression_hashes'], summary['incumbent_expression_hashes'])
        self.assertEqual(summary['retained_expression_hashes'], [child['expression_hash']])
        self.assertEqual(summary['nodes'][0]['node_id'], 'left')
        self.assertEqual(summary['routes']['root']['selected_arm_ids'], ['baseline', 'treatment'])
        self.assertEqual(summary['comparisons']['root']['outcome'], 'accepted')
        # This file is a disposable projection, not a competing authority.
        path.write_text('{}', encoding='utf-8')
        replay = self.advance()
        self.assertEqual(json.loads(path.read_text(encoding='utf-8'))['accepted_incumbents'], replay['accepted_incumbents'])

    def test_rejected_child_rolls_back_to_checked_parent(self):
        self.freeze()
        parent = self.checked(sharpe=1.5, fitness=.8)
        child = self.checked(arm='treatment', sharpe=1.6, fitness=.6)
        result = self.advance([parent, child])
        self.assertEqual(result['comparisons']['root']['outcome'], 'rejected')
        self.assertEqual(result['accepted_incumbents']['root']['expression_hash'], parent['expression_hash'])

    def test_reverse_reserves_companion_arm_even_when_only_one_confirmation_is_routed(self):
        root = self.tree['nodes'][0]
        root['reverse'] = dict(baseline=dict(pair_ref='reverse', arm_id='baseline',
            simulation_identity=self.identities('reverse')['baseline'],
            interpretation='Frozen opposite response.', targets=[]))
        frozen = self.freeze()
        self.assertEqual(frozen['simulation_count'], 6)
        negative = self.checked(sharpe=-1)
        negative['metrics']['returns'] = -.1
        result = self.advance([negative, self.checked(arm='treatment', sharpe=0)], maximum=1)
        self.assertEqual(result['status'], 'budget_wait')
        self.assertFalse(result['candidates'])
        plan = self.advance(maximum=2)
        self.assertEqual(len(plan['candidates']), 2)

    def test_missing_and_nonfinite_evidence_is_not_signal_or_new_post_authority(self):
        self.freeze()
        self.advance()
        result = self.advance([self.checked()])
        self.assertFalse(result['candidates'])
        self.assertFalse(result['routes']['root']['selected_node_ids'])
        invalid = self.checked(arm='treatment')
        invalid['metrics']['sharpe'] = float('nan')
        result = self.advance([invalid])
        self.assertFalse(result['candidates'])
        self.assertEqual(result['status'], 'recover')

    def test_summary_records_stop_without_overwriting_frozen_or_planned_work(self):
        self.freeze()
        plan = self.advance()
        path = Path(plan['config_patch']['ai_plan_receipt'])
        before = path.read_bytes()
        control = json.loads((self.run / 'runtime_control.json').read_text(encoding='utf-8'))
        _write(self.run / 'runtime_control.json', control | dict(desired_state='paused'))
        self.assertEqual(self.advance()['status'], 'stopped')
        summary = json.loads((self.run / 'runtime/tree_execution.json').read_text(encoding='utf-8'))
        self.assertEqual(summary['status'], 'stopped')
        self.assertEqual(path.read_bytes(), before)

    def test_stop_projection_retains_already_verified_incumbents(self):
        self.freeze()
        self.advance([self.checked(sharpe=1.5), self.checked(arm='treatment', sharpe=1.6, fitness=.8)])
        control = json.loads((self.run / 'runtime_control.json').read_text(encoding='utf-8'))
        _write(self.run / 'runtime_control.json', control | dict(desired_state='paused'))
        result = self.advance()
        self.assertEqual(result['status'], 'stopped')
        self.assertIn('root', result['accepted_incumbents'])

    def test_peer_tree_reservations_block_duplicate_work_without_new_ledger(self):
        self.freeze()
        original = self.advance()
        peer = self.root / 'peer'
        peer.mkdir()
        manifest = deepcopy(self.manifest)
        manifest['run_id'] = peer.name
        # Certificates bind their owning run. Use the real IO producer for peer,
        # not a copied certificate with an edited owner/digest.
        seed = dict(selected_scope=self.scope, research_policy=manifest['start_snapshot']['research_policy'])
        _write(peer / 'run_manifest.json', manifest | dict(start_snapshot=seed))
        certificate = eligibility.certify_exploration_resources(peer, self.vault, self.compiler_resources, self.scope)
        snapshot = eligibility.build_exploration_snapshot(list(self.receipts.values()),
            resource_certificates=[certificate] * len(self.receipts))
        snapshot.update(measurement_period=self.period,
                        tree_comparison_policy=self.manifest['start_snapshot']['tree_comparison_policy'])
        _write(peer / 'run_manifest.json', manifest | dict(start_snapshot=snapshot))
        _write(peer / 'runtime_control.json', json.loads((self.run / 'runtime_control.json').read_text(encoding='utf-8')))
        _write(peer / 'runtime_status.json', dict(simulation_attempts=0, elapsed_seconds=0))
        subject.freeze_tree(peer, self.tree, self.resources)
        result = subject.advance_tree(peer, [], 30)
        self.assertEqual(result['status'], 'recover')
        self.assertFalse(result['candidates'])
        self.assertEqual(self.advance()['plan_id'], original['plan_id'])

    def test_large_tree_round_is_capped_at_thirty_complete_unique_arms(self):
        design = deepcopy(self.receipts['root']['compiler_input']['design'])
        design.pop('design_id')
        receipts = {}
        nodes = []
        for index in range(16):
            raw = deepcopy(design)
            baseline = dict(kind='change', input=dict(kind='role', role='pulse'), horizon=2 * index + 1)
            treatment = dict(kind='change', input=dict(kind='role', role='pulse'), horizon=2 * index + 2)
            raw['feature_plan'] = baseline
            raw['experiment_plan']['baseline'] = baseline
            raw['experiment_plan']['treatments'][0]['feature'] = treatment
            normalized = validate_hypothesis_design(dict(summary='Offline wide tree.', designs=[raw]),
                self.compiler_resources['evidence_pack'], SemanticPolicy())['designs'][0]
            name = 'wide-' + str(index)
            receipts[name] = eligibility.validate_exploration(normalized, self.compiler_resources, self.scope)
            ids = {arm['arm_id']: simulation_identity_hash(arm['binding']['bound_expression'], arm['settings'])
                   for arm in receipts[name]['compiled']['experiment']['arms']}
            nodes.append(dict(node_id=name, parent_id=None, parent_arm_id=None, pair_ref=name,
                expected_simulation_identities=ids, targets=dict(baseline=[], treatment=[]), fallback=[], reverse={}))
        cert = self.manifest['start_snapshot']['exploration_context']['resource_certificates'][0]
        snapshot = eligibility.build_exploration_snapshot(list(receipts.values()),
            resource_certificates=[cert] * len(receipts))
        snapshot['measurement_period'] = self.period
        self.manifest['start_snapshot'] = snapshot
        _write(self.run / 'run_manifest.json', self.manifest)
        self.resources['compiled_pairs'] = {key: row['compiled'] for key, row in receipts.items()}
        self.tree.update(roots=list(receipts), nodes=nodes, limits=dict(max_depth=1, max_width=16))
        self.assertEqual(self.freeze()['simulation_count'], 32)
        result = self.advance(maximum=100)
        self.assertEqual(len(result['candidates']), 30)
        hashes = {simulation_identity_hash(row['bound_expression'], row['settings']) for row in result['candidates']}
        self.assertEqual(len(hashes), 30)
        self.assertEqual(len(json.loads(Path(result['config_patch']['ai_plan_receipt']).read_text(encoding='utf-8'))[
            'selection']['experiments']), 15)

    def test_invalid_scope_period_and_identity_rows_cannot_accept_incumbent(self):
        self.freeze()
        row = self.checked(arm='treatment', sharpe=1.6, fitness=.8)
        row['test_period'] = dict(self.period, start='2019-01-01')
        result = self.advance([self.checked(sharpe=1.5), row])
        self.assertEqual(result['comparisons']['root']['outcome'], 'inconclusive')
        self.assertFalse(result['accepted_incumbents'])

    def test_stored_plan_and_attachment_tampering_fail_closed(self):
        self.freeze()
        plan = self.advance()
        path = Path(plan['config_patch']['ai_plan_receipt'])
        before = path.read_bytes()
        changed = json.loads(before)
        changed['reserved_simulation_identities'] = []
        _write(path, changed)
        with self.assertRaises(ValueError):
            self.advance()
        path.write_bytes(before)
        attachment = self.run / 'runtime/experiment_tree.json'
        changed = json.loads(attachment.read_text(encoding='utf-8'))
        changed['tree_digest'] = '0' * 64
        _write(attachment, changed)
        with self.assertRaises(ValueError):
            self.advance()

    def test_conflicting_parent_evidence_cannot_replay_previously_planned_descendants(self):
        self.freeze()
        self.advance([self.checked(), self.checked(arm='treatment')])
        conflict = self.checked(sharpe=0)
        result = self.advance([conflict])
        self.assertFalse(result['candidates'])
        self.assertFalse(result['routes']['root']['selected_node_ids'])

    def test_real_generator_roundtrip_finishes_and_restart_retains_rollback(self):
        from wqb.generator import generate_hypothesis_candidates
        self.freeze()
        first = self.advance()
        self.assertEqual(len(generate_hypothesis_candidates(first['config_patch']['hypothesis_snapshot'],
            first['candidates'], 30)), 2)
        second = self.advance([self.checked(sharpe=1.5), self.checked(arm='treatment', sharpe=1.6, fitness=.8)])
        self.assertEqual(len(generate_hypothesis_candidates(second['config_patch']['hypothesis_snapshot'],
            second['candidates'], 30)), 2)
        final = self.advance([self.checked('left', 'treatment', sharpe=1.7, fitness=1.),
                              self.checked('right', 'treatment', sharpe=1.7, fitness=.7)])
        self.assertEqual(final['status'], 'finished')
        self.assertFalse(final['candidates'])
        self.assertEqual(final['comparisons']['left']['outcome'], 'accepted')
        self.assertEqual(final['comparisons']['right']['outcome'], 'rejected')
        self.assertEqual(final['accepted_incumbents']['right']['expression_hash'],
                         self.identities('root')['treatment'])
        self.assertEqual(self.advance()['accepted_incumbents'], final['accepted_incumbents'])

    def test_existing_cli_accepts_authenticated_tree_plan_before_and_after_handoff(self):
        from wqb.cli import _hypothesis_source_selection
        self.freeze()
        plan = self.advance()
        self.assertTrue(_hypothesis_source_selection(plan['config_patch']).fields)
        from wqb.research_planning import prepare_source_plan
        prepared = prepare_source_plan(self.run, plan['config_patch'],
                                       {'workflow_stage': 'scout'}, '2026-10-23T00:00:00Z')
        self.assertEqual(prepared, plan['config_patch'])
        calls = []
        def execute(config, metadata):
            """Input: tree config/metadata dicts. Output: offline receipt after real CLI validation."""
            calls.append(_hypothesis_source_selection(config))
            return {'status': 'offline'}
        subject.execute_tree_round(self.run, execute)
        self.assertEqual(len(calls), 1)
        subject.execute_tree_round(self.run, execute)
        self.assertEqual(len(calls), 1)

    def test_attempt_budget_is_read_not_renewed_or_charged_by_planning(self):
        self.freeze()
        _write(self.run / 'runtime_status.json', dict(simulation_attempts=149, elapsed_seconds=0))
        result = self.advance()
        self.assertEqual(result['status'], 'budget_wait')
        self.assertEqual(json.loads((self.run / 'runtime_status.json').read_text(encoding='utf-8'))['simulation_attempts'], 149)

    def test_global_history_unknown_identity_blocks_whole_pair(self):
        self.freeze()
        other = self.root / 'source-batch'
        other.mkdir()
        (other / 'simulation_events.jsonl').write_text(json.dumps(dict(
            expression_hash=self.identities('root')['baseline'], status='unknown')) + '\n', encoding='utf-8')
        result = self.advance()
        self.assertEqual(result['status'], 'recover')
        self.assertFalse(result['candidates'])


if __name__ == '__main__':
    unittest.main()
