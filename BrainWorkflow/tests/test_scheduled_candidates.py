import unittest

from wqb import generator


class ScheduledCandidateTests(unittest.TestCase):
    def test_v2_rejects_settings_that_contradict_binding_scope(self):
        from tests.test_template_binding import binding_fixture
        for settings in [dict(region='EUR', delay=0, universe='OTHER'), dict(region='EUR'),
                         dict(delay=0), dict(universe='OTHER'), dict(delay=True)]:
            with self.subTest(settings=settings):
                template, fields, operators, scope = binding_fixture()
                with self.assertRaisesRegex(ValueError, 'settings.*scope'):
                    generator.generate_scheduled_candidates(fields, settings, template, 30,
                                                           operator_rows=operators, scope=scope)

    def test_v2_matching_settings_scope_is_preserved_in_all_variants(self):
        from tests.test_template_binding import binding_fixture
        template, fields, operators, scope = binding_fixture()
        settings = {key: scope[key] for key in ('region', 'delay', 'universe')}
        rows = generator.generate_scheduled_candidates(fields, settings, template, 30,
                                                       operator_rows=operators, scope=scope)
        self.assertTrue(rows)
        self.assertTrue(all(all(row.settings[key] == value for key, value in settings.items()) for row in rows))

    def test_v2_consumes_frozen_bindings_and_deduplicates_payload_identity(self):
        from tests.test_template_binding import binding_fixture
        from wqb.cli import simulation_identity_hash
        template, fields, operators, scope = binding_fixture()
        rows = generator.generate_scheduled_candidates(fields, {}, template, 30,
                                                       operator_rows=operators, scope=scope)
        self.assertTrue(rows)
        self.assertTrue(all(row.expression == 'rank(cash / debt)' for row in rows))
        hashes = [simulation_identity_hash(row.expression, row.settings) for row in rows]
        self.assertEqual(len(hashes), len(set(hashes)))
        other = dict(template, template_id='other-story', hypothesis='Another narrative.')
        repeated = generator.generate_scheduled_candidates(fields, {}, other, 30,
                                                           operator_rows=operators, scope=scope)
        self.assertEqual(hashes, [simulation_identity_hash(row.expression, row.settings)
                                  for row in repeated])

    def test_horizon_variation_preserves_weights_and_thresholds(self):
        template = dict(template_id='fixed', hypothesis='Cash resilience',
                        skeleton='rank(ts_mean({field}, 5) * 5 + 5)')
        rows = generator.generate_scheduled_candidates([dict(id='cash', type='MATRIX')], {}, template, 30)
        self.assertTrue(any('ts_mean(cash, 10)' in row.expression for row in rows))
        self.assertTrue(all('* 5 + 5' in row.expression for row in rows))
        template['skeleton'] = 'rank(vec_percentage({field}, percentage=5))'
        rows = generator.generate_scheduled_candidates([dict(id='buzz', type='VECTOR')], {}, template, 30)
        self.assertTrue(all('percentage=5' in row.expression for row in rows))

    def test_unknown_numeric_position_is_not_horizon_and_legacy_order_preserved(self):
        template = dict(template_id='fixed', hypothesis='Cash resilience', skeleton='rank(add(ts_mean({field}, 5), 5))')
        rows = generator.generate_scheduled_candidates([dict(id='cash', type='MATRIX')], {}, template, 30)
        self.assertTrue(all(row.expression.endswith(', 5))') for row in rows))
        template['skeleton'] = 'rank(ts_mean({field}, 20))'
        rows = generator.generate_scheduled_candidates([dict(id='cash', type='MATRIX')], {}, template, 30)
        self.assertEqual(rows[0].expression, 'rank(ts_mean(cash, 5))')

    def test_v2_only_explicit_window_positions_vary(self):
        from tests.test_template_binding import binding_fixture
        template, fields, operators, scope = binding_fixture()
        template['skeleton'] = 'rank(ts_mean({flow}, {window}) / {liability})'
        rows = generator.generate_scheduled_candidates(fields, {}, template, 30, operator_rows=operators, scope=scope)
        self.assertTrue(any('ts_mean(cash, 10)' in row.expression for row in rows))
        self.assertTrue(all(' / debt)' in row.expression for row in rows))
        template['skeleton'] = 'rank(ts_mean({flow}, 5) / {liability})'
        rows = generator.generate_scheduled_candidates(fields, {}, template, 30, operator_rows=operators, scope=scope)
        self.assertEqual({row.expression for row in rows}, {'rank(ts_mean(cash, 5) / debt)'})

    def test_v2_numeric_limit_and_single_line_precheck_preserved(self):
        from tests.test_template_binding import binding_fixture
        template, fields, operators, scope = binding_fixture()
        for skeleton, reason in [('rank(ts_mean({flow}, 5) / {liability} + 2 + 3)', 'numeric_param_count'),
                                  ('rank({flow} /\n{liability})', 'multiline')]:
            template['skeleton'] = skeleton
            with self.assertRaisesRegex(ValueError, reason):
                generator.generate_scheduled_candidates(fields, {}, template, 30, operator_rows=operators, scope=scope)

    def test_boolean_decay_is_not_an_integer_decay(self):
        template = dict(template_id='fixed', hypothesis='Cash resilience', skeleton='rank({field})', preferred_decay=False)
        with self.assertRaisesRegex(ValueError, 'decay'):
            generator.generate_scheduled_candidates([dict(id='cash', type='MATRIX')], {}, template, 30)

    def test_v2_precheck_uses_existing_scout_limits(self):
        from tests.test_template_binding import binding_fixture
        from wqb.research_workflow import precheck_expression
        template, fields, operators, scope = binding_fixture()
        template['skeleton'] = 'rank(ts_mean({flow}, 5) / {liability})'
        rows = generator.generate_scheduled_candidates(fields, {}, template, 30,
                                                       operator_rows=operators, scope=scope)
        self.assertTrue(rows)
        self.assertTrue(all(precheck_expression(row.expression, 'scout').ok for row in rows))
        template['skeleton'] = 'rank(rank(rank(rank({flow} / {liability}))))'
        with self.assertRaisesRegex(ValueError, 'nesting_depth'):
            generator.generate_scheduled_candidates(fields, {}, template, 30, operator_rows=operators, scope=scope)

    def test_vector_template_reducer_consumes_raw_field_exactly_once(self):
        """Input: VECTOR field and explicit reducer kernels. Output: assertions. Do not reduce a vector twice or count an average."""
        from wqb.research_workflow import precheck_expression
        for reducer in ('vec_avg', 'vec_count'):
            with self.subTest(reducer=reducer):
                rows = generator.generate_scheduled_candidates([{'id': 'buzz', 'type': 'VECTOR'}], {}, {
                    'template_id': reducer, 'skeleton': f'rank(ts_zscore({reducer}({{field}}), 20))',
                    'hypothesis': 'Attention surprise'}, 30)
                self.assertTrue(rows)
                self.assertTrue(all(f'{reducer}(buzz)' in row.expression for row in rows))
                self.assertTrue(all(precheck_expression(row.expression, 'scout').ok for row in rows))
        percentage = generator.generate_scheduled_candidates([{'id': 'buzz', 'type': 'VECTOR'}], {}, {
            'template_id': 'percentile', 'skeleton': 'rank(vec_percentage({field}, percentage=0.5))',
            'hypothesis': 'Event distribution tail'}, 1)
        self.assertEqual(percentage[0].expression, 'rank(vec_percentage(buzz, percentage=0.5))')

    def test_partial_scheduled_batch_is_published_before_multisimulation(self):
        """Input: four valid novel candidates under cap30. Output: assertions. Submit actual size, never pad."""
        import tempfile
        from pathlib import Path
        from unittest.mock import Mock, patch
        from wqb.cli import run_field_batch, load_config
        from wqb.knowledge_source_resolver import SourceSelection
        from wqb.recorder import RunRecorder
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = load_config('configs/stage1_usa_d1.yaml', overrides={
                'run_root': str(root), 'max_alphas_per_round': 30})
            template = {'template_id': 'cash', 'skeleton': 'rank({field})', 'hypothesis': 'Cash resilience'}
            config['scheduled_template'] = template
            candidates = generator.generate_scheduled_candidates(
                [{'id': 'cash', 'type': 'MATRIX'}], generator.build_settings(config), template, 4)
            selection = SourceSelection([{'id': 'cash', 'type': 'MATRIX'}], 'knowledge',
                                        'knowledge', 'knowledge', [], [])
            recorder = RunRecorder(root / 'source')
            def submit_batch(client, payloads, **kwargs):
                """Input: fake client, payload list. Output: progress str. Require plan publication before POST."""
                self.assertEqual(len(recorder.read_jsonl('planned_candidates.jsonl')), 4)
                self.assertEqual(len(payloads), 4)
                return 'progress/1'
            with patch('wqb.cli.resolve_source_inputs', return_value=selection), \
                 patch('wqb.generator.generate_scheduled_candidates', return_value=candidates), \
                 patch('wqb.cli.expression_operator_provenance', return_value=[{'source': 'knowledge_operator_ledger'}]), \
                 patch('wqb.cli.submit_multisimulation', side_effect=submit_batch) as submit:
                run_field_batch(Mock(), recorder, config, workflow_stage='scout', submit_mode='multi',
                                defer_poll=True, multi_chunk_sleep_seconds=0)
            self.assertEqual(submit.call_count, 1)

    def test_recovery_payload_uses_each_persisted_candidate_settings(self):
        """Input: distinct durable variant settings. Output: assertions. Recovery must preserve simulation identity."""
        import tempfile
        from unittest.mock import Mock, patch
        from wqb.cli import load_config, retry_planned_candidates
        from wqb.recorder import RunRecorder
        with tempfile.TemporaryDirectory() as tmp:
            recorder = RunRecorder(tmp)
            config = load_config('configs/stage1_usa_d1.yaml')
            rows = [{'expression_hash': f'h{i}', 'expression': 'rank(cash)',
                     'settings': {**generator.build_settings(config), 'decay': value}}
                    for i, value in enumerate([4, 12])]
            for row in rows:
                recorder.append_jsonl('planned_candidates.jsonl', row)
            with patch('wqb.cli.submit_candidate_payloads', return_value=[]) as submit:
                retry_planned_candidates(Mock(), recorder, config, submit_mode='multi')
            self.assertEqual([payload['settings']['decay'] for payload in submit.call_args.args[2]], [4, 12])

    def test_five_day_seed_has_thirty_unseen_discovery_variants(self):
        """Input: Scout30 and a measured5-day kernel. Output: assertions. Discovery must survive Scout deduplication."""
        settings = {'decay': 0}
        template = {'template_id': 'cash', 'skeleton': 'rank(ts_zscore({field}, 20))', 'hypothesis': 'Cash resilience'}
        fields = [{'id': 'cash', 'type': 'MATRIX'}]
        scout = generator.generate_scheduled_candidates(fields, settings, template, 30)
        seen = {(row.expression, tuple(sorted(row.settings.items()))) for row in scout}
        seed = {**template, 'skeleton': 'rank(ts_zscore({field}, 5))'}
        discovery = generator.generate_scheduled_candidates(fields, settings, seed, 90)
        unseen = [row for row in discovery if (row.expression, tuple(sorted(row.settings.items()))) not in seen]
        self.assertGreaterEqual(len(unseen), 30)

    def test_batch_runner_submits_thirty_scheduled_candidates_in_six_requests(self):
        """Input: local knowledge fixtures and mocked platform. Output: assertions. Exercise actual batch path and provenance."""
        import json
        from pathlib import Path
        import tempfile
        from unittest.mock import Mock, patch
        from wqb.cli import run_field_batch, load_config
        from wqb.knowledge_source_resolver import SourceSelection
        from wqb.recorder import RunRecorder
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = load_config('configs/stage1_usa_d1.yaml', overrides={'run_root': str(root),
                'max_alphas_per_round': 30})
            config['scheduled_template'] = {'template_id': 'cash', 'skeleton': 'rank(ts_zscore({field}, 20))',
                                            'hypothesis': 'Cash resilience', 'preferred_decay': 12}
            selection = SourceSelection([{'id': 'cash', 'type': 'MATRIX'}], 'knowledge',
                                        'knowledge', 'knowledge', [], [])
            recorder = RunRecorder(root / 'source')
            with patch('wqb.cli.resolve_source_inputs', return_value=selection), \
                 patch('wqb.cli.expression_operator_provenance', return_value=[{'source': 'knowledge_operator_ledger'}]), \
                 patch('wqb.cli.submit_multisimulation', return_value='progress/1') as submit:
                run_field_batch(Mock(), recorder, config, exact_field_id='cash', workflow_stage='scout',
                                submit_mode='multi', defer_poll=True, multi_chunk_sleep_seconds=0)
            rows = recorder.read_jsonl('planned_candidates.jsonl')
            self.assertEqual(len(rows), 30)
            self.assertEqual(submit.call_count, 6)
            self.assertEqual(len({row['expression_hash'] for row in rows}), 30)
            self.assertTrue(all('ts_zscore(cash,' in row['expression'] for row in rows))
            self.assertEqual(rows[0]['settings']['decay'], 12)
            self.assertEqual(rows[0]['template_provenance']['template_id'], 'cash')

    def test_scheduled_skeleton_is_consumed_and_thirty_settings_are_distinct(self):
        """Input: measured field and scheduled template. Output: assertions. Preserve economic kernel in all variants."""
        build = getattr(generator, 'generate_scheduled_candidates', None)
        self.assertIsNotNone(build, 'scheduled template executor missing')
        rows = build([{'id': 'cash', 'type': 'MATRIX'}], {'decay': 4},
                     {'template_id': 'cash-standardized', 'skeleton': 'rank(ts_zscore({field}, 20))',
                      'hypothesis': 'Relative cash improvement signals financial resilience.'}, 30)
        self.assertEqual(len(rows), 30)
        self.assertTrue(all('ts_zscore(cash,' in row.expression for row in rows))
        self.assertEqual(len({(row.expression, tuple(sorted(row.settings.items()))) for row in rows}), 30)
        self.assertTrue(all('cash-standardized' in row.tags for row in rows))

    def test_unknown_placeholder_rejected_not_replaced_with_generic_templates(self):
        """Input: unsupported skeleton. Output: assertions. Never silently substitute a different hypothesis."""
        build = getattr(generator, 'generate_scheduled_candidates', None)
        self.assertIsNotNone(build)
        with self.assertRaises(ValueError):
            build([{'id': 'cash', 'type': 'MATRIX'}], {},
                  {'template_id': 'bad', 'skeleton': 'rank({unknown})', 'hypothesis': 'Cash resilience'}, 30)
