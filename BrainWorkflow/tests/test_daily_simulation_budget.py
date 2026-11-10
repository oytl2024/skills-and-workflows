import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


NOW = '2026-10-21T15:59:59+00:00'
NEXT = '2026-10-21T16:00:00+00:00'


def race_charge(path, result):
    """Input: owning run path str and multiprocessing Queue. Output: None. Race a complete daily reservation."""
    from wqb.daily_simulation_budget import charge_daily_budget, DailyBudgetUnavailable
    try:
        charge_daily_budget(Path(path), 4000, Path(path).name, NOW)
        result.put('charged')
    except DailyBudgetUnavailable:
        result.put('refused')


class DailySimulationBudgetTests(unittest.TestCase):
    def setUp(self):
        """Input: none. Output: None. Create an isolated two-run budget store."""
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'runs'
        self.a = self.root / 'a'
        self.b = self.root / 'b'
        self.a.mkdir(parents=True)
        self.b.mkdir()

    def api(self):
        """Input: none. Output: module. Require the shared ledger implementation."""
        from wqb import daily_simulation_budget
        return daily_simulation_budget

    def test_3999_plus_one_and_overflow(self):
        api = self.api()
        api.ensure_daily_policy(self.root)
        api.charge_daily_budget(self.a, 3999, 'one', NOW)
        api.charge_daily_budget(self.a, 1, 'two', NOW)
        with self.assertRaises(api.DailyBudgetUnavailable):
            api.charge_daily_budget(self.a, 1, 'three', NOW)
        row = api.read_daily_budget(self.a, NOW)
        self.assertEqual((row['used'], row['remaining'], row['lifetime_attempts']), (4000, 0, 4000))

    def test_two_runs_share_balance_and_multichild_replay(self):
        api = self.api()
        api.ensure_daily_policy(self.root)
        api.charge_daily_budget(self.a, 5, 'first', NOW)
        api.charge_daily_budget(self.b, 3, 'second', NOW)
        api.charge_daily_budget(self.a, 5, 'first', NOW)
        self.assertEqual(api.read_daily_budget(self.b, NOW)['used'], 8)
        self.assertEqual(api.read_daily_budget(self.a, NOW)['lifetime_attempts'], 5)
        with self.assertRaises(ValueError):
            api.charge_daily_budget(self.b, 5, 'first', NOW)

    def test_invalid_counts_and_conflicting_replay(self):
        api = self.api()
        api.ensure_daily_policy(self.root)
        for value in (-1, 0, True, 1.5, '1'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                api.charge_daily_budget(self.a, value, 'bad', NOW)
        api.charge_daily_budget(self.a, 2, 'ok', NOW)
        with self.assertRaises(ValueError):
            api.charge_daily_budget(self.a, 3, 'ok', NOW)
        self.assertEqual(api.read_daily_budget(self.a, NOW)['used'], 2)

    def test_midnight_retains_lifetime_and_passive_read_does_not_write(self):
        api = self.api()
        api.ensure_daily_policy(self.root)
        api.charge_daily_budget(self.a, 4000, 'old', NOW)
        ledger = self.root / 'daily_simulation_budget/ledger.json'
        before = ledger.read_bytes()
        row = api.read_daily_budget(self.a, NEXT)
        self.assertEqual((row['budget_date'], row['used'], row['remaining']), ('2026-10-22', 0, 4000))
        self.assertEqual(row['lifetime_attempts'], 4000)
        self.assertEqual(before, ledger.read_bytes())
        api.charge_daily_budget(self.a, 2, 'new', NEXT)
        self.assertEqual(api.read_daily_budget(self.a, NEXT)['lifetime_attempts'], 4002)
        self.assertTrue((self.root / 'daily_simulation_budget/archive/2026-10-21.json').exists())
        with self.assertRaises(ValueError):
            api.read_daily_budget(self.a, NOW)

    def test_corrupt_or_missing_established_store_blocks(self):
        api = self.api()
        api.ensure_daily_policy(self.root)
        ledger = self.root / 'daily_simulation_budget/ledger.json'
        ledger.write_text('{}', encoding='utf-8')
        with self.assertRaises(ValueError):
            api.read_daily_budget(self.a, NOW)
        ledger.unlink()
        with self.assertRaises(ValueError):
            api.ensure_daily_policy(self.root)

    def test_deleted_whole_store_cannot_reset_established_allowance(self):
        import shutil
        api = self.api()
        api.ensure_daily_policy(self.root)
        api.charge_daily_budget(self.a, 4000, 'spent', NOW)
        shutil.rmtree(self.root / 'daily_simulation_budget')
        self.assertTrue(api.has_shared_policy(self.a))
        with self.assertRaises(ValueError):
            api.ensure_daily_policy(self.root)

    def test_opaque_colon_identity_replays_after_midnight(self):
        api = self.api()
        api.ensure_daily_policy(self.root)
        api.charge_daily_budget(self.a, 4, 'attempt:one', NOW)
        api.charge_daily_budget(self.b, 1, 'next', NEXT)
        self.assertEqual(api.charge_daily_budget(self.a, 4, 'attempt:one', NEXT)['lifetime_attempts'], 4)

    def test_missing_archive_blocks_new_reservations(self):
        api = self.api()
        api.ensure_daily_policy(self.root)
        api.charge_daily_budget(self.a, 4, 'first', NOW)
        api.charge_daily_budget(self.b, 1, 'next', NEXT)
        (self.root / 'daily_simulation_budget/archive/2026-10-21.json').unlink()
        with self.assertRaises(ValueError):
            api.charge_daily_budget(self.b, 1, 'new', NEXT)

    def test_unprojected_legacy_charge_still_enforces_lifetime_ceiling(self):
        from wqb.runtime_control import RuntimePaused
        api = self.api()
        self.prepare_activation(179)
        api.ensure_daily_policy(self.root)
        api.charge_daily_budget(self.a, 1, 'last', NOW)
        with self.assertRaises(RuntimePaused):
            api.charge_daily_budget(self.a, 1, 'over', NOW)

    def test_activation_waits_for_legacy_accounting_and_carries_it(self):
        import os
        from threading import Event, Thread
        from wqb.runtime_control import CONTROL_ENV, check_submission_allowed, request_runtime_state
        api = self.api()
        self.prepare_activation(150)
        control = request_runtime_state(self.a, 'running')
        entered, release = Event(), Event()
        errors = []
        original = api.has_shared_policy
        def delayed_policy(run):
            """Input: run Path. Output: bool. Freeze the legacy accounting decision during concurrent migration."""
            result = original(run)
            entered.set()
            if not release.wait(3):
                raise AssertionError('test accounting release timed out')
            return result
        def submit():
            """Input: closed-over local fixture. Output: None. Reserve without making a request."""
            try:
                check_submission_allowed(1)
            except Exception as error:
                errors.append(error)
        def activate():
            """Input: closed-over fixture. Output: None. Race only local activation against accounting."""
            try:
                api.activate_daily_policy(self.a, control['request_revision'], 'concurrent test', NOW)
            except Exception as error:
                errors.append(error)
        with patch.dict(os.environ, {CONTROL_ENV: str(self.a)}), patch.object(api, 'has_shared_policy', delayed_policy):
            worker = Thread(target=submit)
            migration = Thread(target=activate)
            worker.start()
            try:
                self.assertTrue(entered.wait(3))
                migration.start()
            finally:
                release.set()
                worker.join(4)
                if migration.ident is not None:
                    migration.join(4)
            self.assertFalse(worker.is_alive())
            self.assertFalse(migration.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(api.read_daily_budget(self.a, NOW)['used'], 151)

    def test_cross_run_policy_establishment_waits_for_legacy_route(self):
        import os
        from threading import Event, Thread
        from wqb.runtime_control import CONTROL_ENV, check_submission_allowed, request_runtime_state
        api = self.api()
        request_runtime_state(self.b, 'running', enable_live_api=True)
        entered, release = Event(), Event()
        errors = []
        original = api.has_shared_policy
        def delayed_policy(run):
            """Input: run Path. Output: bool. Hold another run between routing and legacy accounting."""
            result = original(run)
            entered.set()
            if not release.wait(3):
                raise AssertionError('test route timed out')
            return result
        def reserve():
            """Input: local fixture. Output: None. Reserve a unit without any POST client."""
            try:
                check_submission_allowed(1)
            except Exception as error:
                errors.append(error)
        with patch.dict(os.environ, {CONTROL_ENV: str(self.b)}), patch.object(api, 'has_shared_policy', delayed_policy), patch.object(api, 'BUDGET_LOCK_SECONDS', .05):
            worker = Thread(target=reserve)
            worker.start()
            try:
                self.assertTrue(entered.wait(2))
                with self.assertRaisesRegex(ValueError, 'transition busy'):
                    api.ensure_daily_policy(self.root)
            finally:
                release.set()
                worker.join(4)
        self.assertEqual(errors, [])
        self.assertFalse(worker.is_alive())
        api.ensure_daily_policy(self.root)
        with patch.dict(os.environ, {CONTROL_ENV: str(self.b)}):
            check_submission_allowed(1)
        self.assertEqual(api.read_daily_budget(self.b)['used'], 1)
        self.assertEqual(api.read_daily_budget(self.b)['lifetime_attempts'], 2)

    def test_projection_crash_and_rollover_replay_do_not_refund(self):
        api = self.api()
        api.ensure_daily_policy(self.root)
        api.charge_daily_budget(self.a, 5, 'first', NOW)
        with patch('wqb.runtime_control.update_runtime_status', side_effect=OSError('projection crash')):
            with self.assertRaises(OSError):
                api.reconcile_lifetime_attempts(self.a)
        self.assertEqual(api.read_daily_budget(self.a, NOW)['used'], 5)
        self.assertEqual(api.reconcile_lifetime_attempts(self.a), 5)
        original = api._write
        def fail_rollover(path, row):
            """Input: Path/dict. Output: None. Fail only the first active-day replacement."""
            if path.name == 'ledger.json' and row.get('budget_date') == '2026-10-22':
                raise OSError('rollover crash')
            return original(path, row)
        with patch.object(api, '_write', side_effect=fail_rollover):
            with self.assertRaises(OSError):
                api.charge_daily_budget(self.a, 1, 'next', NEXT)
        api.charge_daily_budget(self.a, 1, 'next', NEXT)
        self.assertEqual(api.read_daily_budget(self.a, NEXT)['lifetime_attempts'], 6)

    def test_concurrent_processes_cannot_overbook(self):
        import multiprocessing
        api = self.api()
        api.ensure_daily_policy(self.root)
        context = multiprocessing.get_context('spawn')
        queue = context.Queue()
        workers = [context.Process(target=race_charge, args=(str(run), queue)) for run in (self.a, self.b)]
        try:
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join(15)
                self.assertEqual(worker.exitcode, 0)
            self.assertEqual(sorted([queue.get(timeout=2), queue.get(timeout=2)]), ['charged', 'refused'])
            self.assertEqual(api.read_daily_budget(self.a, NOW)['used'], 4000)
        finally:
            for worker in workers:
                if worker.is_alive():
                    worker.terminate()
                    worker.join(5)
            queue.close()
            queue.join_thread()

    def test_dated_charge_replay_after_midnight_does_not_charge_again(self):
        api = self.api()
        api.ensure_daily_policy(self.root)
        api.charge_daily_budget(self.a, 4, '2026-10-21:first', NOW)
        api.charge_daily_budget(self.a, 2, '2026-10-22:second', NEXT)
        api.charge_daily_budget(self.a, 4, '2026-10-21:first', NEXT)
        self.assertEqual(api.read_daily_budget(self.a, NEXT)['used'], 2)
        self.assertEqual(api.read_daily_budget(self.a, NEXT)['lifetime_attempts'], 6)

    def prepare_activation(self, used=150):
        """Input: historical attempts int. Output: current intent dict. Prepare a local legacy mission without live work."""
        from wqb.runtime_control import request_runtime_state, update_runtime_status
        (self.a / 'run_manifest.json').write_text(json.dumps({'run_id': self.a.name}), encoding='utf-8')
        control = request_runtime_state(self.a, 'paused', enable_live_api=True, max_simulations=180,
                                        max_runtime_seconds=64800, max_recoveries=3)
        update_runtime_status(self.a, simulation_attempts=used)
        return control

    def test_daily_planner_uses_today_not_historical_run_ceiling(self):
        from wqb.research_planning import hypothesis_authorized_maximum
        from wqb.runtime_control import request_runtime_state
        api = self.api()
        control = self.prepare_activation(5000)
        api.activate_daily_policy(self.a, control['request_revision'], 'test daily planning', NOW)
        request_runtime_state(self.a, 'running')
        original_clock = api._clock
        with patch.object(api, '_clock', side_effect=lambda value: original_clock(value or NEXT)):
            self.assertEqual(hypothesis_authorized_maximum(self.a, 30), 30)
            api.charge_daily_budget(self.a, 3997, 'daily-used', NEXT)
            self.assertEqual(hypothesis_authorized_maximum(self.a, 30), 3)

    def test_daily_round_ceiling_only_preserves_explicit_limit(self):
        from wqb.research_rounds import research_round_limit
        control = {'simulation_budget_mode': 'daily', 'max_simulations': 180}
        self.assertIsNone(research_round_limit(control))
        self.assertEqual(research_round_limit({**control, 'max_rounds': 4}), 4)
        self.assertEqual(research_round_limit({'max_simulations': 180}), 6)

    def test_scout_plan_reservation_survives_midnight_unchanged(self):
        from tests.test_hypothesis_pipeline import pipeline_fixture
        from wqb.research_planning import prepare_hypothesis_plan
        from wqb.runtime_control import request_runtime_state, update_runtime_status
        api = self.api()
        (self.root / 'fixture').mkdir()
        _, config, run = pipeline_fixture(self.root / 'fixture')
        path = run / 'run_manifest.json'
        path.write_text(json.dumps({**json.loads(path.read_text()), 'run_id': run.name}))
        control = request_runtime_state(run, 'paused', enable_live_api=False)
        update_runtime_status(run, simulation_attempts=0)
        api.activate_daily_policy(run, control['request_revision'], 'test plan migration', NOW)
        api.charge_daily_budget(run, 3997, 'used', NOW)
        request_runtime_state(run, 'running')
        clock = [NOW]
        original = api._clock
        with patch.object(api, '_clock', side_effect=lambda value: original(value or clock[0])):
            import os
            from wqb.runtime_control import DAILY_RECONCILE_ENV, DailyBudgetExhausted
            with patch.dict(os.environ, {DAILY_RECONCILE_ENV: '1'}), patch('wqb.research_planning.run_ai_checkpoint') as model:
                with self.assertRaises(DailyBudgetExhausted):
                    prepare_hypothesis_plan(run, {**config, 'max_alphas_per_round': 30},
                                            {'scheduled_batch_maximum': 30}, NOW)
                model.assert_not_called()
            first = prepare_hypothesis_plan(run, {**config, 'max_alphas_per_round': 30},
                                            {'scheduled_batch_maximum': 30}, NOW)
            clock[0] = NEXT
            second = prepare_hypothesis_plan(run, {**config, 'max_alphas_per_round': 30},
                                             {'scheduled_batch_maximum': 30}, NEXT)
        self.assertEqual(first, second)
        self.assertEqual(first['max_alphas_per_round'], 3)

    def test_reconciliation_mode_prohibits_posts_even_with_available_quota(self):
        import os
        from wqb.runtime_control import CONTROL_ENV, DAILY_RECONCILE_ENV, DailyBudgetExhausted, check_submission_allowed, request_runtime_state
        api = self.api()
        control = self.prepare_activation(0)
        api.activate_daily_policy(self.a, control['request_revision'], 'read-only reconciliation', NOW)
        request_runtime_state(self.a, 'running')
        with patch.dict(os.environ, {CONTROL_ENV: str(self.a), DAILY_RECONCILE_ENV: '1'}):
            check_submission_allowed()
            with self.assertRaises(DailyBudgetExhausted):
                check_submission_allowed(1)
        self.assertEqual(api.read_daily_budget(self.a)['used'], 0)

    def test_complete_pair_waits_instead_of_discarding_direction_at_one_remaining(self):
        from tests.test_hypothesis_selection import paired_selection_fixture
        from wqb.research_planning import prepare_source_plan
        from wqb.runtime_control import DailyBudgetExhausted, request_runtime_state
        api = self.api()
        control = self.prepare_activation(0)
        snapshot, experiments = paired_selection_fixture(self.root)
        (self.a / 'run_manifest.json').write_text(json.dumps({'run_id': self.a.name, 'start_snapshot': snapshot}))
        api.activate_daily_policy(self.a, control['request_revision'], 'paired test', NOW)
        api.charge_daily_budget(self.a, 3999, 'used', NOW)
        request_runtime_state(self.a, 'running')
        settings = experiments[0]['arms'][0]['settings']
        config = dict(settings, instrument_type=settings['instrumentType'], unit_handling=settings['unitHandling'],
                      nan_handling=settings['nanHandling'], max_alphas_per_round=30)
        original = api._clock
        with patch.object(api, '_clock', side_effect=lambda value: original(value or NOW)):
            with self.assertRaises(DailyBudgetExhausted) as wait:
                prepare_source_plan(self.a, config, {}, NOW)
        self.assertEqual(wait.exception.budget['required_count'], 2)
        self.assertEqual(list((self.a / 'runtime/research_plans').glob('*.experiments.json')), [])
        api.charge_daily_budget(self.a, 3998, 'next-day-used', NEXT)
        with patch.object(api, '_clock', side_effect=lambda value: original(value or NEXT)):
            first = prepare_source_plan(self.a, config, {'scheduled_batch_maximum': 30}, NEXT)
            replay = prepare_source_plan(self.a, {**config, 'max_alphas_per_round': first['max_alphas_per_round']},
                                         {'scheduled_batch_maximum': 30}, NEXT)
        self.assertEqual(first, replay)

    def test_activation_refuses_unknown_historical_usage(self):
        api = self.api()
        control = self.prepare_activation()
        (self.a / 'runtime_status.json').unlink()
        with self.assertRaises(ValueError):
            api.activate_daily_policy(self.a, control['request_revision'], 'unknown history test', NOW)

    def test_activation_replay_finishes_receipt_after_intent_publication_crash(self):
        api = self.api()
        control = self.prepare_activation()
        original = api._write
        def fail_receipt(path, row):
            """Input: Path/dict. Output: None. Fail only the final receipt after intent is durable."""
            if path.name == 'daily_budget_activation.json' and row.get('status') == 'applied':
                raise OSError('receipt interruption')
            return original(path, row)
        with patch.object(api, '_write', side_effect=fail_receipt):
            with self.assertRaises(OSError):
                api.activate_daily_policy(self.a, control['request_revision'], 'crash test', NOW)
        api.activate_daily_policy(self.a, control['request_revision'], 'crash test', NOW)
        receipt = json.loads((self.a / 'runtime/daily_budget_activation.json').read_text())
        self.assertEqual(receipt['status'], 'applied')
        self.assertEqual(api.read_daily_budget(self.a, NOW)['used'], 150)

    def test_activation_preserves_stop_limits_and_carries_history_once(self):
        api = self.api()
        control = self.prepare_activation()
        api.activate_daily_policy(self.a, control['request_revision'], 'human approved test', NOW)
        from wqb.runtime_control import read_runtime_control
        current = read_runtime_control(self.a)
        self.assertEqual(current['desired_state'], 'paused')
        self.assertEqual((current['max_simulations'], current['max_runtime_seconds'], current['max_recoveries']), (180, 64800, 3))
        row = api.read_daily_budget(self.a, NOW)
        self.assertEqual((row['used'], row['lifetime_attempts'], row['remaining']), (150, 150, 3850))
        api.activate_daily_policy(self.a, control['request_revision'], 'human approved test', NOW)
        self.assertEqual(api.read_daily_budget(self.a, NOW)['used'], 150)

    def test_activation_rejects_newer_stop_and_protected_original_scope(self):
        api = self.api()
        control = self.prepare_activation()
        from wqb.runtime_control import request_runtime_state, _read, _write
        request_runtime_state(self.a, 'paused')
        with self.assertRaises(ValueError):
            api.activate_daily_policy(self.a, control['request_revision'], 'test', NOW)
        path = self.a / 'runtime_control.json'
        current = _read(path)
        current['original_batch_scope_id'] = 'protected'
        _write(path, current)
        with self.assertRaises(ValueError):
            api.activate_daily_policy(self.a, current['request_revision'], 'test', NOW)

    def test_runtime_gate_charges_shared_day_but_not_gets_or_lifetime_cap(self):
        import os
        from wqb.runtime_control import request_runtime_state, check_submission_allowed, CONTROL_ENV
        api = self.api()
        control = self.prepare_activation(5000)
        api.activate_daily_policy(self.a, control['request_revision'], 'test', NOW)
        current = api.read_daily_budget(self.a, NOW)
        self.assertEqual(current['remaining'], 0)
        # A fresh day ignores the preserved 180 legacy ceiling but keeps lifetime history.
        from wqb.runtime_control import read_runtime_control
        request_runtime_state(self.a, 'running', expected_revision=read_runtime_control(self.a)['request_revision'])
        original = api._clock
        with patch.dict(os.environ, {CONTROL_ENV: str(self.a)}), patch.object(api, '_clock', side_effect=lambda now: original(now or NEXT)):
            check_submission_allowed()
            check_submission_allowed(5)
            check_submission_allowed()
            row = api.read_daily_budget(self.a, NEXT)
            self.assertEqual((row['used'], row['lifetime_attempts']), (5, 5005))

    def test_authority_audit_reports_daily_remaining_not_legacy_ceiling(self):
        from wqb.run_authority import inspect_run_authority
        api = self.api()
        control = self.prepare_activation()
        api.activate_daily_policy(self.a, control['request_revision'], 'test', NOW)
        original = api._clock
        with patch.object(api, '_clock', side_effect=lambda now: original(now or NOW)):
            audit = inspect_run_authority(self.a)
        self.assertEqual(audit['remaining_simulations'], 3850)
        self.assertEqual(audit['recorded_attempts'], 150)

    def test_full_daily_allowance_refuses_multisimulation_before_client_call(self):
        import os
        from unittest.mock import Mock
        from wqb.runtime_control import request_runtime_state, read_runtime_control, DailyBudgetExhausted, CONTROL_ENV
        from wqb.simulator import submit_multisimulation
        api = self.api()
        control = self.prepare_activation()
        api.activate_daily_policy(self.a, control['request_revision'], 'test', NOW)
        api.charge_daily_budget(self.a, 3850, 'fill', NOW)
        request_runtime_state(self.a, 'running', expected_revision=read_runtime_control(self.a)['request_revision'])
        client = Mock()
        original = api._clock
        with patch.dict(os.environ, {CONTROL_ENV: str(self.a)}), patch.object(api, '_clock', side_effect=lambda now: original(now or NOW)):
            with self.assertRaises(DailyBudgetExhausted):
                submit_multisimulation(client, [{'regular': 'rank(close)'}, {'regular': 'rank(open)'}])
        client.post_json.assert_not_called()


if __name__ == '__main__':
    unittest.main()
