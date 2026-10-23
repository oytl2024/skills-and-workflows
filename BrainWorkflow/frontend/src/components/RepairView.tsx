import type { ExperimentNode } from '../types';
import { fact, hypothesis, Status } from './NodeDetail';

// Input: server Repair experiments and view-only selection. Output: inspectable full table; own scroll managed by its parent region.
export function RepairView({ nodes, selected, onSelect }: { nodes: ExperimentNode[]; selected?: string; onSelect: (id: string) => void }) {
  if (!nodes.length) return <div className="empty">暂无 Repair 实验</div>;
  return <table className="repair-table"><caption className="sr-only">Repair 实验与比较证据</caption><thead><tr>
    <th>实验 / 状态</th><th>表达式 / 设置</th><th>Alpha ID</th><th>评分</th><th>测量指标 / 信号</th><th>采纳 / 回退原因</th>
  </tr></thead><tbody>{nodes.map(node => <tr key={node.node_id} className={selected === node.node_id ? 'view-selected' : ''}>
    <td><button className="row-link" onClick={() => onSelect(node.node_id)} data-view-focus={`repair-${node.node_id}`}>{hypothesis(node) || node.node_id}</button><Status value={node.state} /><code className="small-id">{node.node_id}</code></td>
    <td><pre>{node.expression || '未提供'}</pre><pre className="muted">{node.settings ? JSON.stringify(node.settings, null, 2) : '未提供'}</pre></td>
    <td className="mono">{node.alpha_id ?? ''}</td><td className="numeric">{fact(node.score)}</td>
    <td><pre>{node.metrics && Object.keys(node.metrics).length ? fact(node.metrics) : '未知'}</pre><span>{fact(node.signal)}</span></td>
    <td className="long-text">{node.reason || '未提供'}{node.comparison !== undefined && <pre>{fact(node.comparison)}</pre>}</td>
  </tr>)}</tbody></table>;
}
