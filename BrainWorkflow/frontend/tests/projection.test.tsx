// @vitest-environment jsdom
import { execFileSync } from 'node:child_process';
import { resolve } from 'node:path';
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { parseSnapshot } from '../src/api';
import { NodeDetail } from '../src/components/NodeDetail';
import { RepairView } from '../src/components/RepairView';

// Input: none. Output: actual Python adapter JSON over isolated temporary artifacts, never active runtime.
function projectedSnapshot(legacy = false) {
  return JSON.parse(execFileSync('python', ['-c',
    `import json; from tests.test_console_api import projection_fixture; print(json.dumps(projection_fixture(${legacy ? 'True' : 'False'})))`], {
    cwd: resolve(process.cwd(), '..'), encoding: 'utf8',
    env: { ...process.env, SystemRoot: process.env.SystemRoot || 'C:/Windows', windir: process.env.windir || 'C:/Windows' },
  }));
}

afterEach(cleanup);
describe('actual Python projection/browser contract', () => {
  it('parses actual legacy progress, legacy Seed and current Repair without fabricated layers', () => {
    const lane = parseSnapshot(projectedSnapshot(true)).lanes[0];
    expect(lane.nodes[0].layer).toBeNull();
    expect(lane.nodes[0].state).toBe('checked');
    expect(lane.seeds[0].expression).toBe('rank(fixture_x)');
    expect(lane.repair[0].score).toBe(.81);
  });
  it('parses null layers and all three actual projected collections', () => {
    const snapshot = parseSnapshot(projectedSnapshot());
    const lane = snapshot.lanes[0];
    expect(lane.nodes[0].layer).toBeNull();
    expect(lane.seeds[0].score).toBe(.75);
    expect(lane.repair[0].alpha_id).toBe('fixture-repair');
    expect(lane.repair[1].alpha_id).toBeNull();
    render(<NodeDetail node={lane.nodes[0]} />);
    expect(screen.getByRole('heading', { name: '基线组' })).toBeTruthy();
    expect(screen.getByRole('heading', { name: '处理组' })).toBeTruthy();
    expect(screen.getByText('rank(fixture_x)')).toBeTruthy();
    expect(screen.getByText('rank(ts_mean(fixture_x, 22))')).toBeTruthy();
    expect(screen.getByText('fixture-baseline')).toBeTruthy();
    expect(screen.getAllByText('未知').length).toBeGreaterThan(0);
  });
  it('renders current Repair expression without substituting the Alpha ID', () => {
    const snapshot = parseSnapshot(projectedSnapshot());
    render(<RepairView nodes={snapshot.lanes[0].repair} onSelect={() => {}} />);
    expect(screen.getByText('rank(ts_delta(fixture_x, 5))')).toBeTruthy();
    expect(screen.getByText('fixture-repair')).toBeTruthy();
    expect(screen.getByText('0.81')).toBeTruthy();
    expect(screen.getByText('rank(ts_delta(fixture_x, 10))')).toBeTruthy();
  });
  it('rejects omitted or malformed layer rather than silently turning it into zero', () => {
    const snapshot = projectedSnapshot();
    delete snapshot.lanes[0].nodes[0].layer;
    expect(() => parseSnapshot(snapshot)).toThrow(/格式不兼容/);
  });
});
