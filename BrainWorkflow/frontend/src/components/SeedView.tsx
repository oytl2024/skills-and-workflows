import { Sprout } from 'lucide-react';
import type { ExperimentNode } from '../types';
import { fact, hypothesis, Status } from './NodeDetail';

// Input: retained server cores and local node selection. Output: read-only Seed list with unchanged eligibility evidence.
export function SeedView({ nodes, selected, onSelect }: { nodes: ExperimentNode[]; selected?: string; onSelect: (id: string) => void }) {
  return <div className="seed-view">
    <div className="section-heading"><h2><Sprout size={17} />保留核心</h2><span className="muted">{nodes.length}</span></div>
    {!nodes.length ? <div className="empty">暂无保留核心</div> : nodes.map(node => <button key={node.node_id} className={`seed-row ${selected === node.node_id ? 'view-selected' : ''}`} onClick={() => onSelect(node.node_id)} data-view-focus={`seed-${node.node_id}`}>
      <span className="seed-title">{hypothesis(node) || node.node_id}</span><Status value={node.state} />
      <code>{node.expression || '未提供'}</code>
      <span className="seed-facts">评分 {fact(node.score)} · Sharpe {fact(node.metrics?.sharpe)}</span>
      <span className="seed-reason">{node.reason || '未提供保留依据'}</span>
    </button>)}
  </div>;
}
