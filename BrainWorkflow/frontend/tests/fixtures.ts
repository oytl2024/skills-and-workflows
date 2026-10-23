import type { ApplicationSnapshot, Lane } from '../src/types';

// Input: lane count (number). Output: explicitly fictional offline snapshot (ApplicationSnapshot).
export function fixtureSnapshot(count = 2): ApplicationSnapshot {
  return {
    schema_version: 1, server_epoch: 'test-epoch', sequence: 1,
    evidence_at: '2026-10-22T08:00:00Z', request_revision: 'revision-1',
    group: { group_id: 'fixture-group', status: 'paused', desired_state: 'stopped', daily_budget: { used: 12, limit: 4000 } },
    lanes: Array.from({ length: count }, (_, i): Lane => ({
      lane_id: `lane-${i}`, name: `离线测试流程 ${i + 1}`, status: i ? 'waiting' : 'paused', stage: 'scout',
      nodes: [
        { node_id: `root-${i}`, layer: 1, hypothesis: `测试假设 ${i + 1}`, expression: 'rank(test_field)', settings: { region: 'USA', decay: 5 }, alpha_id: null, signal: null, metrics: {}, state: 'planned', reason: '尚未执行' },
        { node_id: `child-${i}`, parent_id: `root-${i}`, layer: 2, hypothesis: '测试处理组', expression: 'rank(ts_mean(test_field, 22))', settings: { decay: 5 }, alpha_id: 'fixture-alpha', signal: 'positive', metrics: { sharpe: 1.4, turnover: 0.2 }, state: 'accepted', reason: '离线比较证据' },
      ],
      seeds: [{ node_id: `seed-${i}`, layer: 2, hypothesis: '测试保留核心', expression: 'rank(test_field)', settings: {}, alpha_id: 'fixture-seed', signal: 'positive', metrics: { sharpe: 1.4 }, state: 'accepted', reason: '离线门槛通过', score: 2.4 }],
      repair: [{ node_id: `repair-${i}`, layer: 3, hypothesis: '测试修复', expression: 'rank(ts_mean(test_field, 5))', settings: { decay: 10 }, alpha_id: null, signal: null, metrics: {}, state: 'planned', reason: '等待离线执行', score: null }],
    })), allowed_actions: { start: true, stop: true },
    options: [{ option_id: 'fixture-option', title: '离线测试目标' }], blocker: '',
  };
}
