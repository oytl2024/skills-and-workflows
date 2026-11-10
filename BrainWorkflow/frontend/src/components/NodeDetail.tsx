import type { ExperimentNode, JsonValue } from '../types';

const STATE_NAMES: Record<string, string> = {
  planned: '待执行', unselected: '未选中', waiting: '等待中', queued: '已排队', running: '执行中',
  recovering: '恢复中', accepted: '已采纳', rejected: '未采纳', inconclusive: '证据不足',
  completed: '已完成', failed: '失败', paused: '已暂停', stopped: '已停止', blocked: '受阻',
  positive: '正向信号', negative: '反向信号', no_signal: '无明确信号', unknown: '未知',
  pending: '等待中', missing: '尚无记录', checked: '已检查', CHECKED: '已检查',
  qualified: '已通过检查', recover: '待恢复', conflict: '证据冲突', branched: '已分支', finished: '已结束',
};

// Input: server state (string). Output: readable Chinese label, preserving unrecognized server states.
export function stateName(state: string): string { return STATE_NAMES[state] ?? state; }

// Input: optional server JSON. Output: lossless readable string, with explicit unknown for missing values.
export function fact(value: JsonValue | undefined): string {
  if (value === null || value === undefined) return '未知';
  if (typeof value === 'object') return JSON.stringify(value, null, 2);
  return typeof value === 'number' && !Number.isFinite(value) ? '未知' : String(value);
}

// Input: ExperimentNode. Output: hypothesis label from text or structured server evidence, no invented summary.
export function hypothesis(node: ExperimentNode): string {
  return node.hypothesis === null ? '' : typeof node.hypothesis === 'string' ? node.hypothesis : fact(node.hypothesis);
}

// Input: server status (string). Output: labeled inline status element; color is supplemental.
export function Status({ value }: { value: string }) {
  return <span className="status" data-state={value}><span className="status-dot" aria-hidden="true" />{stateName(value)}</span>;
}

// Input: one optional experiment node. Output: complete read-only evidence; absent IDs remain literally blank.
export function NodeDetail({ node, armLabel }: { node?: ExperimentNode; armLabel?: string }) {
  if (!node) return <div className="empty">暂无实验记录</div>;
  const metrics = node.metrics ?? {};
  const primaryMetrics = ['sharpe', 'fitness', 'returns', 'turnover'];
  const metricKeys = [...primaryMetrics, ...Object.keys(metrics).filter(key => !primaryMetrics.includes(key))];
  const metricNames: Record<string, string> = { sharpe: 'Sharpe', fitness: 'Fitness', returns: 'Returns', turnover: 'Turnover' };
  return <article className="node-detail">
    <div className="section-heading"><h2>{armLabel || '实验详情'}</h2><Status value={node.state} /></div>
    <dl className="identity">
      {!armLabel && <><dt>节点</dt><dd className="mono">{node.node_id}</dd>
      <dt>层级</dt><dd>{fact(node.layer)}</dd></>}
      {!node.arms && <><dt>Alpha ID</dt><dd className="mono blank-id" data-testid="alpha-id" aria-label={node.alpha_id ? 'Alpha ID' : 'Alpha ID 尚未提供'}>{node.alpha_id ?? ''}</dd></>}
    </dl>
    {!armLabel && <section><h3>经济假设</h3><p className="long-text">{hypothesis(node) || '未提供'}</p></section>}
    {node.arms ? Object.entries(node.arms).map(([arm, evidence]) => <section className="pair-arm" key={arm}>
      <NodeDetail node={evidence} armLabel={arm === 'baseline' ? '基线组' : arm === 'treatment' ? '处理组' : arm} />
    </section>) : <>
      <section><h3>表达式</h3><pre className="expression" tabIndex={0} data-view-focus={armLabel ? `expression-${node.node_id}` : 'expression'}>{node.expression || '未提供'}</pre></section>
      <section><h3>设置</h3><pre className="settings">{node.settings ? JSON.stringify(node.settings, null, 2) : '未提供'}</pre></section>
      <section><h3>测量指标</h3><dl className="metrics">{metricKeys.map(key => <div key={key}><dt>{metricNames[key] ?? key}</dt><dd>{fact(metrics[key])}</dd></div>)}</dl></section>
    </>}
    {!armLabel && <section><h3>信号</h3><p className="long-text">{typeof node.signal === 'string' ? stateName(node.signal) : fact(node.signal)}</p>
      {node.raw_signal !== undefined && <p>原始：{fact(node.raw_signal)}</p>}
      {node.directional_signal !== undefined && <p>方向：{fact(node.directional_signal)}</p>}
    </section>}
    {node.score !== undefined && (!armLabel || node.score !== null) && <section><h3>评分</h3><p className="mono">{fact(node.score)}</p></section>}
    {(!armLabel || node.reason) && <section><h3>路由 / 采纳 / 回退原因</h3><p className="long-text">{node.reason || '未提供'}</p></section>}
    {([
      ['condition', '适用条件'], ['field_characteristics', '字段特征'],
      ['comparison', '比较证据'], ['sources', '来源引用'],
    ] as const).map(([key, label]) => node[key] !== undefined && <section key={key}><h3>{label}</h3><pre className="long-text">{fact(node[key])}</pre></section>)}
  </article>;
}
