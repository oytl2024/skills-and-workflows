"""Repair termination describes rule search, never economic disproof."""

import unittest


class RepairStopTraceTests(unittest.TestCase):
    def test_pending_or_inconclusive_children_are_not_measured_rejection(self):
        """Input: incomplete child comparison. Output: explicit inconclusive finite exhaustion, not failed search."""
        from wqb.repair_scheduler import _exhaustion_trace
        attempts = [dict(children=[dict(alpha_id='pending')], experiment_trace=dict(outcome='inconclusive'))]
        trace = _exhaustion_trace({}, dict(stop_reason='no_novel_candidates'), attempts)
        self.assertEqual(trace['stop_reason'], 'inconclusive_search_exhaustion')
        self.assertEqual(trace['tested_candidates'], 0)

    def test_unmeasured_exhaustion_preserves_specific_reason_and_skips(self):
        """Input: untested plan dict. Output: assertions. Retain actionable missing-premise detail."""
        from wqb.repair_scheduler import _exhaustion_trace
        plan = dict(stop_reason='missing_prerequisites', skipped=[dict(reason='unknown_frequency')])
        trace = _exhaustion_trace({}, plan, [])
        self.assertEqual(trace['stop_reason'], 'missing_prerequisites')
        self.assertEqual(trace['skipped'], plan['skipped'])
        self.assertEqual(trace['tested_candidates'], 0)
        self.assertFalse(trace['submission_qualified'])

    def test_tested_search_without_improvement_is_not_mechanism_rejection(self):
        """Input: exhausted plan/measured rejection. Output: assertions. Classify only finite search evidence."""
        from wqb.repair_scheduler import _exhaustion_trace
        attempts = [dict(children=[dict(alpha_id='measured')],
                         experiment_trace=dict(outcome='rejected'))]
        trace = _exhaustion_trace({}, dict(stop_reason='no_novel_candidates'), attempts)
        self.assertEqual(trace['stop_reason'], 'tested_without_improvement')
        self.assertEqual(trace['planner_stop_reason'], 'no_novel_candidates')
        self.assertEqual(trace['tested_candidates'], 1)
        self.assertNotIn('disproven', trace['reason'])

    def test_previous_improvement_is_retained_when_space_is_exhausted(self):
        """Input: accepted incumbent history. Output: assertions. Do not label accepted improvement a failure."""
        from wqb.repair_scheduler import _exhaustion_trace
        attempts = [dict(children=[dict(alpha_id='better')], experiment_trace=dict(outcome='accepted'))]
        trace = _exhaustion_trace({}, dict(stop_reason='no_novel_candidates'), attempts)
        self.assertEqual(trace['stop_reason'], 'search_space_exhausted_after_improvement')
