import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApplicationClient, parseSnapshot } from '../src/api';
import { fixtureSnapshot, multiplierSnapshot } from './fixtures';

class FakeEvents {
  listeners = new Map<string, (event: MessageEvent) => void>();
  onerror: (() => void) | null = null;
  close = vi.fn();
  addEventListener(name: string, callback: EventListener) { this.listeners.set(name, callback as (event: MessageEvent) => void); }
  emit(name: string, value: unknown) { this.listeners.get(name)?.({ data: JSON.stringify(value) } as MessageEvent); }
}

afterEach(() => vi.useRealTimers());

describe('application transport', () => {
  it('validates optional manual catalog and preparation strictly while preserving old snapshots', () => {
    const snapshot = multiplierSnapshot();
    expect(parseSnapshot(snapshot)).toBe(snapshot);
    const catalog = snapshot.options[0].scope_selection;
    for (const patch of [{ choices: null }, { choices: [{ region: 'USA', delay: '1', universe: 'TOP3000' }] }, { configured_scope: { region: 'USA', delay: 1.5, universe: 'TOP3000' } }, { captured_at: 10 }, { stale: 'false' }]) {
      expect(() => parseSnapshot({ ...snapshot, options: [{ ...snapshot.options[0], scope_selection: { ...catalog, ...patch } }] })).toThrow();
    }
    expect(() => parseSnapshot({ ...snapshot, options: [{ ...snapshot.options[0], selection_mode: 'automatic' }] })).toThrow();
    expect(() => parseSnapshot({ ...snapshot, options: [{ ...snapshot.options[0], scope_selection: null }] })).toThrow();
    const preparation = { stage: 'capture', status: 'running', requests_used: 1, request_limit: 24 };
    expect(parseSnapshot({ ...snapshot, preparation }).preparation).toEqual(preparation);
    for (const invalid of [null, { ...preparation, requests_used: -1 }, { ...preparation, request_limit: '24' }, { ...preparation, field_count: 1.2 }, { ...preparation, reason: false }, { ...preparation, scope: { region: 'USA', delay: false, universe: 'TOP3000' } }]) {
      expect(() => parseSnapshot({ ...snapshot, preparation: invalid })).toThrow();
    }
  });

  it.each(['manual', 'ordinary', 'resume', 'stop'])('sends selected_scope only for manual Start (%s)', async mode => {
    const snapshot = mode === 'ordinary' ? { ...fixtureSnapshot(), start_mode: 'new' as const } : { ...multiplierSnapshot(), start_mode: mode === 'resume' ? 'resume' as const : 'new' as const };
    const fetcher = vi.fn().mockImplementation((_url, init) => Promise.resolve({ ok: true, json: async () => init?.method === 'POST' ? { command_id: JSON.parse(init.body).command_id, status: 'accepted' } : snapshot }));
    const client = new ApplicationClient({ fetcher, eventSource: null, storage: null });
    client.start();
    await vi.waitFor(() => expect(client.getState().snapshot).not.toBeNull());
    const scope = { region: 'USA', delay: 1, universe: 'TOP3000', extra: 'never serialize' };
    await client.command(mode === 'stop' ? 'stop' : 'start', snapshot.options[0].option_id, scope);
    const body = JSON.parse(fetcher.mock.calls.find(([, init]) => init?.method === 'POST')![1].body);
    if (mode === 'manual') expect(body.selected_scope).toEqual({ region: 'USA', delay: 1, universe: 'TOP3000' });
    else expect(body).not.toHaveProperty('selected_scope');
    if (['resume', 'stop'].includes(mode)) expect(body).not.toHaveProperty('selected_option_id');
    client.dispose();
  });
  it('rejects malformed snapshots instead of synthesizing facts', () => {
    expect(() => parseSnapshot({ schema_version: 1 })).toThrow();
    expect(() => parseSnapshot({ ...fixtureSnapshot(), sequence: NaN })).toThrow();
    expect(parseSnapshot(fixtureSnapshot()).lanes[0].nodes[0].alpha_id).toBeNull();
  });

  it('ignores stale snapshots and retired server epochs', async () => {
    const first = fixtureSnapshot();
    const fetcher = vi.fn().mockResolvedValue({ ok: true, json: async () => first });
    const stream = new FakeEvents();
    const client = new ApplicationClient({ fetcher, eventSource: () => stream as unknown as EventSource, storage: null });
    client.start();
    await vi.waitFor(() => expect(client.getState().snapshot?.sequence).toBe(1));
    stream.emit('snapshot', { ...first, sequence: 5 });
    stream.emit('snapshot', { ...first, sequence: 3 });
    expect(client.getState().snapshot?.sequence).toBe(5);
    fetcher.mockResolvedValue({ ok: true, json: async () => ({ ...first, server_epoch: 'new', sequence: 0 }) });
    stream.emit('snapshot', { ...first, server_epoch: 'new', sequence: 0 });
    await vi.waitFor(() => expect(client.getState().snapshot?.server_epoch).toBe('new'));
    stream.emit('snapshot', { ...first, sequence: 100 });
    expect(client.getState().snapshot?.server_epoch).toBe('new');
    client.dispose();
  });

  it('runtime-error and heartbeat timeout enter visible fallback polling', async () => {
    vi.useFakeTimers();
    const streams: FakeEvents[] = [];
    const fetcher = vi.fn().mockResolvedValue({ ok: true, json: async () => fixtureSnapshot() });
    const client = new ApplicationClient({ fetcher, eventSource: () => { const s = new FakeEvents(); streams.push(s); return s as unknown as EventSource; }, storage: null });
    client.start();
    await vi.advanceTimersByTimeAsync(1);
    streams[0].emit('snapshot', fixtureSnapshot());
    expect(client.getState().connection).toBe('live');
    streams[0].emit('runtime-error', { message: 'projection failed' });
    expect(client.getState().connection).toBe('reconnecting');
    await vi.advanceTimersByTimeAsync(3001);
    expect(fetcher.mock.calls.length).toBeGreaterThan(1);
    expect(client.getState().connection).toBe('polling');
    await vi.advanceTimersByTimeAsync(20000);
    expect(client.getState().connection).not.toBe('live');
    client.dispose();
  });

  it('never replays unknown commands and reconciles a durable command receipt', async () => {
    const snapshot = fixtureSnapshot();
    const stream = new FakeEvents();
    const fetcher = vi.fn().mockImplementation((_url, init) => init?.method === 'POST' ? Promise.reject(new TypeError('lost reply')) : Promise.resolve({ ok: true, json: async () => snapshot }));
    const client = new ApplicationClient({ fetcher, eventSource: () => stream as unknown as EventSource, storage: null });
    client.start();
    await vi.waitFor(() => expect(client.getState().snapshot).not.toBeNull());
    await client.command('start', 'fixture-option');
    const pending = client.getState().commands[0];
    expect(pending.status).toBe('unknown');
    await client.command('start', 'fixture-option');
    expect(fetcher.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(1);
    stream.emit('snapshot', { ...snapshot, sequence: 2, command_statuses: [{ command_id: pending.command_id, status: 'accepted', job_id: 'fixture-job' }] });
    expect(client.getState().commands[0].status).toBe('accepted');
    client.dispose();
  });
});
