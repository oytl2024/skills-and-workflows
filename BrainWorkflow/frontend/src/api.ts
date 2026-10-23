import type { Action, ApplicationSnapshot, ApplicationState, CommandReply, ExperimentNode, TrackedCommand } from './types';

const SNAPSHOT_URL = '/api/application/snapshot';
const EVENTS_URL = '/api/application/events';
const COMMAND_URL = '/api/application/commands';
const POLL_MS = 3000;
const RECONNECT_MS = 5000;
const WATCHDOG_MS = 15000;
const REQUEST_TIMEOUT_MS = 10000;
const STORAGE_KEY = 'brainworkflow.unresolved-commands.v1';

type Fetcher = typeof fetch;
interface ClientOptions {
  fetcher?: Fetcher;
  eventSource?: ((url: string) => EventSource) | null;
  storage?: Storage | null;
}

// Input: unknown node JSON and depth. Output: bool; unknown layer is null, never a fabricated zero.
function validNode(value: unknown, depth = 0): value is ExperimentNode {
  const n = value as ExperimentNode | null;
  const objectOrNull = (v: unknown) => v === null || (typeof v === 'object' && v !== null && !Array.isArray(v));
  return !!n && depth < 4 && typeof n.node_id === 'string' && !!n.node_id && typeof n.state === 'string' &&
    (n.layer === null || (Number.isSafeInteger(n.layer) && n.layer! >= 0)) &&
    (n.parent_id === undefined || n.parent_id === null || typeof n.parent_id === 'string') &&
    (n.hypothesis === null || typeof n.hypothesis === 'string' || objectOrNull(n.hypothesis)) &&
    (n.expression === null || typeof n.expression === 'string') && objectOrNull(n.settings) && objectOrNull(n.metrics) &&
    (n.alpha_id === null || typeof n.alpha_id === 'string') && (n.reason === null || typeof n.reason === 'string') &&
    (n.score === undefined || n.score === null || (typeof n.score === 'number' && Number.isFinite(n.score))) &&
    (n.arms === undefined || (objectOrNull(n.arms) && n.arms !== null && Object.values(n.arms).every(arm => validNode(arm, depth + 1))));
}

// Input: unknown JSON. Output: validated v1 snapshot or Error; never supplies missing research facts.
export function parseSnapshot(value: unknown): ApplicationSnapshot {
  const s = value as ApplicationSnapshot | null;
  if (!s || s.schema_version !== 1 || typeof s.server_epoch !== 'string' || !s.server_epoch ||
    !Number.isSafeInteger(s.sequence) || s.sequence < 0 || !['string', 'number'].includes(typeof s.request_revision) ||
    !(s.evidence_at === null || typeof s.evidence_at === 'string') ||
    !s.group || typeof s.group.group_id !== 'string' || typeof s.group.status !== 'string' || typeof s.group.desired_state !== 'string' ||
    typeof s.allowed_actions?.start !== 'boolean' || typeof s.allowed_actions.stop !== 'boolean' ||
    !Array.isArray(s.options) || !s.options.every(o => o && typeof o.option_id === 'string' && typeof o.title === 'string') ||
    typeof s.blocker !== 'string' || !Array.isArray(s.lanes) || !s.lanes.every(l =>
      l && typeof l.lane_id === 'string' && typeof l.name === 'string' && typeof l.status === 'string' && typeof l.stage === 'string' &&
      [l.nodes, l.seeds, l.repair].every(items => Array.isArray(items) && items.every(n => validNode(n))))) {
    throw new Error('应用快照格式不兼容，等待重新连接。');
  }
  if (new Set(s.lanes.map(l => l.lane_id)).size !== s.lanes.length || s.lanes.some(l =>
    [l.nodes, l.seeds, l.repair].some(items => new Set(items.map(n => n.node_id)).size !== items.length))) {
    throw new Error('应用快照含重复身份，等待重新连接。');
  }
  return s;
}

// Input: unknown JSON reply and command identity (string). Output: matching receipt or Error.
function parseReply(value: unknown, id: string): CommandReply {
  const reply = value as CommandReply | null;
  if (!reply || reply.command_id !== id || typeof reply.status !== 'string') throw new Error('命令回执无法核实');
  return reply;
}

// Input: optional browser Storage. Output: unresolved typed commands; invalid storage is ignored safely.
function restoreCommands(storage: Storage | null): TrackedCommand[] {
  try {
    const items: unknown = JSON.parse(storage?.getItem(STORAGE_KEY) || '[]');
    return Array.isArray(items) ? items.filter(c => c && typeof c.command_id === 'string' &&
      ['start', 'stop'].includes(c.action) && typeof c.group_id === 'string' &&
      ['string', 'number'].includes(typeof c.expected_revision) && ['pending', 'unknown'].includes(c.status))
      .map(c => ({ ...c, status: 'unknown' })) : [];
  } catch { return []; }
}

export class ApplicationClient {
  private state: ApplicationState;
  private listeners = new Set<() => void>();
  private fetcher: Fetcher;
  private eventsFactory: ClientOptions['eventSource'];
  private storage: Storage | null;
  private stream: EventSource | null = null;
  private pollTimer?: ReturnType<typeof setInterval>;
  private reconnectTimer?: ReturnType<typeof setTimeout>;
  private watchdog?: ReturnType<typeof setInterval>;
  private lastEvent = 0;
  private running = false;
  private retiredEpochs = new Set<string>();
  private refreshPromise: Promise<void> | null = null;
  private controller: AbortController | null = null;
  private fixtureMode = false;

  // Input: local transport/storage adapters (ClientOptions). Output: inert client; start() activates reads only.
  constructor(options: ClientOptions = {}) {
    this.fetcher = options.fetcher ?? globalThis.fetch.bind(globalThis);
    this.eventsFactory = options.eventSource === undefined ? (typeof EventSource === 'undefined' ? null : url => new EventSource(url)) : options.eventSource;
    this.storage = options.storage === undefined ? (() => { try { return globalThis.sessionStorage ?? null; } catch { return null; } })() : options.storage;
    this.state = { snapshot: null, connection: 'connecting', error: '', commands: restoreCommands(this.storage) };
  }

  // Input: explicit offline snapshot. Output: fixture-only client with commands disabled; never selected by production bootstrap.
  static fixture(snapshot: ApplicationSnapshot): ApplicationClient {
    const client = new ApplicationClient({ storage: null, eventSource: null });
    client.fixtureMode = true;
    client.state = { snapshot: parseSnapshot(snapshot), connection: 'fixture', error: '', commands: [] };
    return client;
  }

  // Input: explicit fixture snapshot. Output: void; updates test clients only.
  setFixture(snapshot: ApplicationSnapshot): void {
    if (!this.fixtureMode) throw new Error('Fixture updates are test-only');
    this.accept(parseSnapshot(snapshot));
  }

  // Input: none. Output: stable ApplicationState for React subscription.
  getState = (): ApplicationState => this.state;

  // Input: state listener (() => void). Output: unsubscribe callback.
  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => { this.listeners.delete(listener); };
  };

  // Input: partial ApplicationState. Output: void; publishes immutable state and saves only unresolved identities.
  private update(patch: Partial<ApplicationState>): void {
    this.state = { ...this.state, ...patch };
    try { this.storage?.setItem(STORAGE_KEY, JSON.stringify(this.state.commands.filter(c => ['pending', 'unknown'].includes(c.status)))); } catch { /* The in-memory identity remains authoritative for this view. */ }
    this.listeners.forEach(listener => listener());
  }

  // Input: validated full snapshot. Output: void; rejects stale/retired versions, reconciles receipts without POST replay.
  private accept(snapshot: ApplicationSnapshot): void {
    const previous = this.state.snapshot;
    if (this.retiredEpochs.has(snapshot.server_epoch)) return;
    if (previous?.server_epoch === snapshot.server_epoch && snapshot.sequence <= previous.sequence) return;
    if (previous && previous.server_epoch !== snapshot.server_epoch) this.retiredEpochs.add(previous.server_epoch);
    const receipts = Array.isArray(snapshot.command_statuses) ? snapshot.command_statuses :
      Object.entries(snapshot.command_statuses ?? {}).map(([command_id, reply]) => ({ ...reply, command_id }));
    const commands = this.state.commands.map(c => {
      const receipt = receipts.find(r => r.command_id === c.command_id);
      return receipt ? { ...c, ...receipt } : c;
    });
    this.update({ snapshot, commands, error: '' });
  }

  // Input: none. Output: void; opens read-only transport and bounded liveness watchdog.
  start(): void {
    if (this.running || this.fixtureMode) return;
    this.running = true;
    void this.refresh();
    this.connect();
    this.watchdog = setInterval(() => {
      if (this.stream && Date.now() - this.lastEvent >= WATCHDOG_MS) this.fallback('实时更新超时，正在重连。');
    }, 1000);
  }

  // Input: none. Output: void; closes only UI transports, never workflow workers or authority.
  dispose(): void {
    this.running = false;
    this.stream?.close();
    this.stream = null;
    this.controller?.abort();
    clearInterval(this.pollTimer);
    clearInterval(this.watchdog);
    clearTimeout(this.reconnectTimer);
    this.pollTimer = undefined;
    this.refreshPromise = null;
  }

  // Input: none. Output: Promise<void>; fetches one bounded full snapshot, guarding in-flight stale HTTP replies.
  async refresh(): Promise<void> {
    if (this.fixtureMode || !this.running) return;
    if (this.refreshPromise) return this.refreshPromise;
    const startedAt = this.state.snapshot;
    const controller = new AbortController();
    this.controller = controller;
    const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
    this.refreshPromise = (async () => {
      try {
        const response = await this.fetcher(SNAPSHOT_URL, { signal: controller.signal, cache: 'no-store', credentials: 'same-origin' });
        if (!response.ok) throw new Error('状态读取失败');
        const snapshot = parseSnapshot(await response.json());
        if (!this.running || controller.signal.aborted) return;
        if (this.state.snapshot !== startedAt && this.state.snapshot?.server_epoch !== snapshot.server_epoch) return;
        this.accept(snapshot);
        if (this.state.connection !== 'live') this.update({ connection: 'polling', error: '' });
      } catch (error) {
        if (this.running) {
          this.update({ connection: 'offline', error: error instanceof Error ? error.message : '无法读取最新状态，正在自动重试；上次证据已保留。' });
          this.ensurePolling();
        }
      } finally {
        clearTimeout(timeout);
        if (this.controller === controller) this.controller = null;
        this.refreshPromise = null;
      }
    })();
    return this.refreshPromise;
  }

  // Input: none. Output: void; connects SSE, validates complete snapshots, resnapshots on epoch or sequence gaps.
  private connect(): void {
    if (!this.running || !this.eventsFactory) { this.ensurePolling(); return; }
    try {
      const stream = this.eventsFactory(EVENTS_URL);
      this.stream = stream;
      this.lastEvent = Date.now();
      const receive = (event: Event): void => {
        if (!this.running || this.stream !== stream) return;
        try {
          const snapshot = parseSnapshot(JSON.parse((event as MessageEvent<string>).data));
          const current = this.state.snapshot;
          this.lastEvent = Date.now();
          if (this.retiredEpochs.has(snapshot.server_epoch)) return;
          if (current && snapshot.server_epoch !== current.server_epoch) {
            this.fallback('服务已重启，正在核对最新状态。');
            // A gap resnapshot may already be in flight from the previous epoch.
            if (this.refreshPromise) void this.refreshPromise.then(() => this.refresh());
            else void this.refresh();
            return;
          }
          if (current && snapshot.sequence > current.sequence + 1) void this.refresh();
          this.accept(snapshot);
          this.update({ connection: 'live', error: '' });
          clearInterval(this.pollTimer);
          this.pollTimer = undefined;
        } catch (error) { this.fallback(error instanceof Error ? error.message : '实时状态无法解析，正在重连。'); }
      };
      stream.addEventListener('snapshot', receive);
      stream.addEventListener('message', receive);
      stream.addEventListener('heartbeat', () => { if (this.stream === stream) this.lastEvent = Date.now(); });
      stream.addEventListener('runtime-error', () => { if (this.stream === stream) this.fallback('实时状态生成失败，正在重连。'); });
      stream.onerror = () => { if (this.stream === stream) this.fallback('实时连接中断，正在重连。'); };
    } catch { this.fallback('无法建立实时连接，正在重连。'); }
  }

  // Input: none. Output: void; enables single bounded fallback poll interval, no command side effects.
  private ensurePolling(): void {
    if (this.running && !this.pollTimer) this.pollTimer = setInterval(() => { void this.refresh(); }, POLL_MS);
  }

  // Input: human-readable error (string). Output: void; replaces broken SSE with polling and delayed reconnect.
  private fallback(error: string): void {
    this.stream?.close();
    this.stream = null;
    this.update({ connection: 'reconnecting', error });
    this.ensurePolling();
    clearTimeout(this.reconnectTimer);
    this.reconnectTimer = setTimeout(() => this.connect(), RECONNECT_MS);
  }

  // Input: authorized action and optional option ID (strings). Output: Promise<void>; sends exactly once, tracks uncertain delivery.
  async command(action: Action, optionId?: string): Promise<void> {
    const snapshot = this.state.snapshot;
    if (!snapshot || this.fixtureMode || !snapshot.allowed_actions[action]) return;
    const blocked = this.state.commands.some(c => c.group_id === snapshot.group.group_id &&
      (action === 'start' || c.action === 'stop') && (['pending', 'unknown'].includes(c.status) ||
        (['accepted', 'queued', 'running'].includes(c.status) && c.expected_revision === snapshot.request_revision)));
    if (blocked || (action === 'start' && !['live', 'polling'].includes(this.state.connection))) return;
    const command_id = crypto.randomUUID();
    const tracked: TrackedCommand = { command_id, action, status: 'pending', expected_revision: snapshot.request_revision, group_id: snapshot.group.group_id };
    this.update({ commands: [...this.state.commands.slice(-19), tracked] });
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
    try {
      const response = await this.fetcher(COMMAND_URL, {
        method: 'POST', signal: controller.signal, credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ command_id, action, expected_revision: snapshot.request_revision, ...(action === 'start' && optionId ? { selected_option_id: optionId } : {}) }),
      });
      const reply = parseReply(await response.json(), command_id);
      this.update({ commands: this.state.commands.map(c => c.command_id === command_id && c.status === 'pending' ? { ...c, ...reply } : c) });
      void this.refresh();
    } catch {
      this.update({ commands: this.state.commands.map(c => c.command_id === command_id && c.status === 'pending' ?
        { ...c, status: 'unknown', message: '回执未确认，正在核对命令；不会自动重发。' } : c) });
      void this.refresh();
    } finally { clearTimeout(timeout); }
  }
}
