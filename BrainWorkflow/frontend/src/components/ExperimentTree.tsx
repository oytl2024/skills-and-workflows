import { ChevronDown, ChevronRight, GitBranch } from 'lucide-react';
import type { ExperimentNode } from '../types';
import { hypothesis, Status } from './NodeDetail';

interface TreeProps {
  nodes: ExperimentNode[];
  selected?: string;
  collapsed: string[];
  onSelect: (id: string) => void;
  onToggle: (id: string) => void;
}

// Input: bounded server nodes and view-only tree state. Output: accessible hierarchy; selecting never dispatches work.
export function ExperimentTree({ nodes, selected, collapsed, onSelect, onToggle }: TreeProps) {
  const ids = new Set(nodes.map(n => n.node_id));
  const children = new Map<string, ExperimentNode[]>();
  nodes.forEach(n => { if (n.parent_id && ids.has(n.parent_id)) children.set(n.parent_id, [...(children.get(n.parent_id) ?? []), n]); });
  const rows: { node: ExperimentNode; depth: number; expandable: boolean }[] = [];
  const seen = new Set<string>();
  // Input: node and indentation (number). Output: void; flattens visible hierarchy with cycle protection.
  function visit(node: ExperimentNode, depth: number): void {
    if (seen.has(node.node_id)) return;
    seen.add(node.node_id);
    const descendants = children.get(node.node_id) ?? [];
    rows.push({ node, depth, expandable: descendants.length > 0 });
    if (!collapsed.includes(node.node_id)) descendants.forEach(child => visit(child, depth + 1));
    else {
      const pending = [...descendants];
      while (pending.length) {
        const child = pending.pop()!;
        if (!seen.has(child.node_id)) { seen.add(child.node_id); pending.push(...(children.get(child.node_id) ?? [])); }
      }
    }
  }
  nodes.filter(n => !n.parent_id || !ids.has(n.parent_id)).forEach(n => visit(n, 0));
  nodes.forEach(n => { if (!seen.has(n.node_id)) visit(n, 0); });
  if (!nodes.length) return <div className="empty">暂无 Scout 计划</div>;
  return <div className="experiment-tree" role="tree" aria-label="Scout 实验树" onKeyDown={event => {
    const buttons = Array.from(event.currentTarget.querySelectorAll<HTMLButtonElement>('.tree-select'));
    const index = buttons.indexOf(document.activeElement as HTMLButtonElement);
    if (index < 0) return;
    const row = rows[index];
    if (['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) {
      event.preventDefault();
      const next = event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length - 1 : Math.max(0, Math.min(buttons.length - 1, index + (event.key === 'ArrowDown' ? 1 : -1)));
      buttons[next]?.focus();
    }
    if ((event.key === 'ArrowRight' && collapsed.includes(row.node.node_id)) || (event.key === 'ArrowLeft' && !collapsed.includes(row.node.node_id))) {
      if (row.expandable) { event.preventDefault(); onToggle(row.node.node_id); }
    }
  }}>
    {rows.map(({ node, depth, expandable }) => <div key={node.node_id} className={`tree-row ${node.node_id === selected ? 'view-selected' : ''}`} role="treeitem" aria-level={depth + 1} aria-selected={node.node_id === selected} aria-expanded={expandable ? !collapsed.includes(node.node_id) : undefined}>
      <div className="tree-indent" style={{ width: Math.min(depth, 8) * 16 }} />
      {expandable ? <button className="tree-toggle icon-button" title={collapsed.includes(node.node_id) ? '展开分支' : '折叠分支'} aria-label={`${collapsed.includes(node.node_id) ? '展开' : '折叠'} ${node.node_id}`} onClick={() => onToggle(node.node_id)}>{collapsed.includes(node.node_id) ? <ChevronRight size={15} /> : <ChevronDown size={15} />}</button> : <GitBranch size={14} className="tree-leaf" aria-hidden="true" />}
      <button className="tree-select" onClick={() => onSelect(node.node_id)} data-view-focus={`node-${node.node_id}`}>
        <span className="tree-title">{hypothesis(node) || node.node_id}</span>
        <span className="tree-subline"><span>层 {node.layer ?? '未知'}</span><Status value={node.state} /></span>
      </button>
    </div>)}
  </div>;
}
