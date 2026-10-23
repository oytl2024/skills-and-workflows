import { useEffect, useLayoutEffect, useRef, useState, useSyncExternalStore, type ReactNode } from 'react';
import { Activity, ArrowUpRight, CircleAlert, FlaskConical, GitBranch, Play, Radio, Sprout, Square, Wrench } from 'lucide-react';
import { ApplicationClient } from './api';
import type { ApplicationState, Lane, LaneView, Stage, TrackedCommand } from './types';
import { WorkflowNavigation } from './components/WorkflowNavigation';
import { ExperimentTree } from './components/ExperimentTree';
import { fact, NodeDetail, Status, stateName } from './components/NodeDetail';
import { SeedView } from './components/SeedView';
import { RepairView } from './components/RepairView';
import './styles.css';

const STAGES = [
  { id: 'scout', name: 'Scout', label: '实验树', icon: GitBranch },
  { id: 'seed', name: 'Seed', label: '保留核心', icon: Sprout },
  { id: 'repair', name: 'Repair', label: '修复实验', icon: Wrench },
] as const;
const CONNECTION_NAMES = { connecting: '正在连接', live: '实时连接', reconnecting: '重连中 · 轮询备用', polling: '轮询更新 · 实时连接待恢复', offline: '离线 · 自动重试', fixture: '离线测试 · 非实时数据' };

// Input: lane (Lane). Output: new local-only LaneView, initialized to an inspectable server stage.
function initialView(lane: Lane): LaneView {
  return { stage: STAGES.some(s => s.id === lane.stage.toLowerCase()) ? lane.stage.toLowerCase() as Stage : 'scout', selected: {}, collapsed: [], scroll: {}, focus: null };
}

// Input: tracked command. Output: human-readable acknowledgment, never implying research/Stop fence completion.
function commandMessage(command: TrackedCommand): string {
  const action = command.action === 'start' ? 'Start' : 'Stop';
  if (command.status === 'pending') return `正在发送 ${action}`;
  if (command.status === 'unknown') return `${action} 回执未确认，正在核对；不会自动重发。`;
  if (['accepted', 'queued', 'running'].includes(command.status)) return `${action} 已受理${command.job_id ? ` · 任务 ${command.job_id}` : ''}${command.action === 'stop' ? ' · 等待持久状态确认' : ''}`;
  return command.message || `${action}：${stateName(command.status)}`;
}

interface ScrollProps {
  name: string;
  view: LaneView;
  onView: (patch: Partial<LaneView>) => void;
  active: boolean;
  children: ReactNode;
  className?: string;
  testId?: string;
}

// Input: local scroll key, LaneView, visibility and children. Output: stable scroll region retaining independent positions.
function ScrollRegion({ name, view, onView, active, children, className = '', testId }: ScrollProps) {
  const ref = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => { if (active && ref.current) ref.current.scrollTop = view.scroll[name] ?? 0; }, [active, name]);
  return <div ref={ref} className={`scroll-region ${className}`} data-testid={testId} onScroll={event => {
    onView({ scroll: { ...view.scroll, [name]: event.currentTarget.scrollTop } });
  }}>{children}</div>;
}

// Input: authoritative lane and local-only browsing state. Output: persistent Scout/Seed/Repair views with independent scroll/focus.
function LaneWorkspace({ lane, active, view, onView }: { lane: Lane; active: boolean; view: LaneView; onView: (patch: Partial<LaneView>) => void }) {
  const ref = useRef<HTMLDivElement>(null);
  const wasActive = useRef(false);
  useLayoutEffect(() => {
    if (active && !wasActive.current && view.focus) {
      Array.from(ref.current?.querySelectorAll<HTMLElement>('[data-view-focus]') ?? []).find(el => el.dataset.viewFocus === view.focus)?.focus({ preventScroll: true });
    }
    wasActive.current = active;
  }, [active, view.focus]);
  const stageNodes = { scout: lane.nodes, seed: lane.seeds, repair: lane.repair };
  return <div ref={ref} hidden={!active} className="lane-workspace" onFocusCapture={event => {
    const id = (event.target as HTMLElement).dataset.viewFocus;
    if (id && id !== view.focus) onView({ focus: id });
  }}>
    <div className="lane-heading"><div><p className="eyebrow">研究流程</p><h1>{lane.name}</h1></div><div className="execution-stage"><Activity size={15} /><span>当前执行阶段</span><strong>{stateName(lane.stage) || '未知'}</strong><Status value={lane.status} /></div></div>
    <div className="stage-tabs" role="tablist" aria-label={`${lane.name} 阶段浏览`} onKeyDown={event => {
      const index = STAGES.findIndex(s => s.id === view.stage);
      const next = event.key === 'ArrowRight' ? (index + 1) % 3 : event.key === 'ArrowLeft' ? (index + 2) % 3 : event.key === 'Home' ? 0 : event.key === 'End' ? 2 : -1;
      if (next !== -1) { event.preventDefault(); onView({ stage: STAGES[next].id }); ref.current?.querySelector<HTMLButtonElement>(`[data-stage="${STAGES[next].id}"]`)?.focus(); }
    }}>
      {STAGES.map(({ id, name, label, icon: Icon }) => <button key={id} role="tab" id={`${lane.lane_id}-${id}-tab`} aria-controls={`${lane.lane_id}-${id}-panel`} aria-selected={view.stage === id} tabIndex={view.stage === id ? 0 : -1} data-stage={id} data-view-focus={`stage-${id}`} onClick={() => onView({ stage: id })}><Icon size={16} />{name}<span className="tab-description">{label}</span><span className="tab-count">{stageNodes[id].length}</span></button>)}
    </div>
    {STAGES.map(({ id }) => {
      const nodes = stageNodes[id];
      const selected = nodes.find(n => n.node_id === view.selected[id]) ?? nodes[0];
      const visible = active && view.stage === id;
      const select = (nodeId: string): void => onView({ selected: { ...view.selected, [id]: nodeId } });
      return <div key={id} hidden={view.stage !== id} role="tabpanel" id={`${lane.lane_id}-${id}-panel`} aria-labelledby={`${lane.lane_id}-${id}-tab`} className={`stage-panel ${id === 'repair' ? 'repair-panel' : ''}`}>
        {id === 'repair' ? <>
          <div className="panel-title"><h2>修复实验</h2><span className="muted">{nodes.length} 条记录</span></div>
          <ScrollRegion name="repair-table" view={view} onView={onView} active={visible} className="repair-scroll" testId="repair-scroll"><RepairView nodes={nodes} selected={selected?.node_id} onSelect={select} /></ScrollRegion>
          <ScrollRegion name={`repair-detail-${selected?.node_id ?? ''}`} view={view} onView={onView} active={visible} className="repair-detail"><NodeDetail node={selected} /></ScrollRegion>
        </> : <div className="split-pane">
          <ScrollRegion name={`${id}-list`} view={view} onView={onView} active={visible} className="list-pane">
            {id === 'scout' ? <><div className="panel-title"><h2>预规划实验树</h2><span className="muted">{nodes.length} 个节点</span></div><ExperimentTree nodes={nodes} selected={selected?.node_id} collapsed={view.collapsed} onSelect={select} onToggle={nodeId => onView({ collapsed: view.collapsed.includes(nodeId) ? view.collapsed.filter(v => v !== nodeId) : [...view.collapsed, nodeId] })} /></> : <SeedView nodes={nodes} selected={selected?.node_id} onSelect={select} />}
          </ScrollRegion>
          <ScrollRegion name={`${id}-detail-${selected?.node_id ?? ''}`} view={view} onView={onView} active={visible} className="detail-pane" testId={id === 'scout' ? 'node-detail-scroll' : 'seed-detail-scroll'}><NodeDetail node={selected} /></ScrollRegion>
        </div>}
      </div>;
    })}
  </div>;
}

// Input: injected ApplicationClient (production API or explicit test fixture). Output: Chinese read-only research workspace and group Start/Stop.
export function App({ client }: { client: ApplicationClient }) {
  const state: ApplicationState = useSyncExternalStore(client.subscribe, client.getState, client.getState);
  const { snapshot, connection, error, commands } = state;
  const [selectedLane, setSelectedLane] = useState<string | null>(null);
  const [selectedOption, setSelectedOption] = useState('');
  const [views, setViews] = useState<Record<string, LaneView>>({});
  useEffect(() => { client.start(); return () => client.dispose(); }, [client]);
  const optionId = snapshot?.options.some(o => o.option_id === selectedOption) ? selectedOption : snapshot?.options[0]?.option_id ?? '';
  const currentLane = snapshot?.lanes.some(l => l.lane_id === selectedLane) ? selectedLane : null;
  const relevantCommands = commands.filter(c => c.group_id === snapshot?.group.group_id);
  const unresolved = relevantCommands.filter(c => ['pending', 'unknown'].includes(c.status));
  const actionBlocked = (action: 'start' | 'stop'): boolean => relevantCommands.some(c =>
    (action === 'start' || c.action === 'stop') && (['pending', 'unknown'].includes(c.status) ||
      (['accepted', 'queued', 'running'].includes(c.status) && c.expected_revision === snapshot?.request_revision)));
  const latest = relevantCommands.at(-1);
  const feedback = [...unresolved, ...(latest && !unresolved.includes(latest) ? [latest] : [])];
  return <div className="application-shell">
    <header className="application-header"><div className="brand"><FlaskConical size={21} /><span>BrainWorkflow</span><span className="brand-divider">/</span><span className="workspace-label">研究工作台</span></div>
      <div className="group-actions"><label className="sr-only" htmlFor="objective">研究目标</label><select id="objective" value={optionId} disabled={!snapshot || !snapshot.allowed_actions.start || actionBlocked('start')} onChange={event => setSelectedOption(event.target.value)}>
        {!snapshot?.options.length && <option value="">暂无可选目标</option>}{snapshot?.options.map(o => <option key={o.option_id} value={o.option_id}>{o.title}</option>)}
      </select><button className="start-button" disabled={!snapshot?.allowed_actions.start || actionBlocked('start') || !['live', 'polling'].includes(connection) || connection === 'fixture'} onClick={() => { void client.command('start', optionId); }}><Play size={15} fill="currentColor" />Start</button>
        <button className="stop-button" disabled={!snapshot?.allowed_actions.stop || actionBlocked('stop') || connection === 'fixture'} onClick={() => { void client.command('stop'); }}><Square size={14} fill="currentColor" />Stop</button></div>
    </header>
    <div className="evidence-bar"><div className="group-state">组状态 {snapshot ? <Status value={snapshot.group.status} /> : <span>未知</span>}{snapshot && <span className="desired-state">期望：{stateName(snapshot.group.desired_state)}</span>}</div>
      {snapshot?.group.daily_budget !== undefined && <span className="budget">共享日预算 <span className="mono">{typeof snapshot.group.daily_budget === 'object' && snapshot.group.daily_budget && !Array.isArray(snapshot.group.daily_budget) && 'used' in snapshot.group.daily_budget && 'limit' in snapshot.group.daily_budget ? `${fact(snapshot.group.daily_budget.used)} / ${fact(snapshot.group.daily_budget.limit)}` : fact(snapshot.group.daily_budget)}</span></span>}
      <span className="connection" data-connection={connection}><Radio size={14} />{CONNECTION_NAMES[connection]}</span>
      <span className="evidence-time">证据 {snapshot?.evidence_at ? <time dateTime={snapshot.evidence_at}>{snapshot.evidence_at}</time> : '未知'}</span>
    </div>
    {(error || snapshot?.blocker || feedback.length > 0) && <div className="feedback-band">
      {error && <div className="notice" role="status"><CircleAlert size={16} />{error}</div>}
      {snapshot?.blocker && <div className="notice blocker" role="alert"><CircleAlert size={16} /><span>{snapshot.blocker}</span></div>}
      {feedback.map(c => <div key={c.command_id} className={`notice command-notice ${['refused', 'rejected', 'failed', 'error', 'conflict'].includes(c.status) ? 'command-error' : ''}`} role={['refused', 'rejected', 'failed', 'error', 'conflict'].includes(c.status) ? 'alert' : 'status'}><span>{commandMessage(c)}</span><span className="command-identity mono" title="命令身份">{c.command_id}</span>{c.message && c.status !== 'unknown' && commandMessage(c) !== c.message && <span>{c.message}</span>}</div>)}
    </div>}
    <WorkflowNavigation lanes={snapshot?.lanes ?? []} selected={currentLane} onSelect={setSelectedLane} />
    <main className="workspace-main">
      {!snapshot ? <div className="initial-state"><FlaskConical size={30} /><h1>研究工作台</h1><p>{connection === 'offline' ? '无法连接本地服务，正在自动重试。' : '正在读取研究状态…'}</p></div> : <>
        <section hidden={currentLane !== null} className="overview"><div className="overview-heading"><p className="eyebrow">研究组</p><h1>流程总览</h1><p className="group-id mono">{snapshot.group.group_id}</p></div>
          {!snapshot.lanes.length ? <div className="empty">暂无研究流程</div> : <div className="overview-table-wrap"><table className="overview-table"><thead><tr><th>研究流程</th><th>状态</th><th>当前阶段</th><th>Scout 节点</th><th>保留核心</th><th>Repair 记录</th><th><span className="sr-only">查看</span></th></tr></thead><tbody>{snapshot.lanes.map(lane => <tr key={lane.lane_id}>
            <td><button className="row-link" aria-label={`查看${lane.name}`} onClick={() => setSelectedLane(lane.lane_id)}>{lane.name}</button><span className="small-id mono">{lane.lane_id}</span></td><td><Status value={lane.status} /></td><td>{lane.stage || '未知'}</td><td className="numeric">{lane.nodes.length}</td><td className="numeric">{lane.seeds.length}</td><td className="numeric">{lane.repair.length}</td><td><button className="icon-button" title={`打开${lane.name}`} aria-label={`打开${lane.name}`} onClick={() => setSelectedLane(lane.lane_id)}><ArrowUpRight size={17} /></button></td>
          </tr>)}</tbody></table></div>}
        </section>
        {snapshot.lanes.map(lane => <LaneWorkspace key={lane.lane_id} lane={lane} active={currentLane === lane.lane_id} view={views[lane.lane_id] ?? initialView(lane)} onView={patch => setViews(previous => ({ ...previous, [lane.lane_id]: { ...(previous[lane.lane_id] ?? initialView(lane)), ...patch } }))} />)}
      </>}
    </main>
    <footer className="application-footer"><span>{snapshot ? `schema v${snapshot.schema_version} · ${snapshot.server_epoch} · #${snapshot.sequence}` : '等待服务快照'}</span><span>最终 Alpha 提交需单独授权</span></footer>
  </div>;
}
