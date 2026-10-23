import { ArrowLeft, ArrowRight, LayoutDashboard } from 'lucide-react';
import type { Lane } from '../types';
import { Status } from './NodeDetail';

// Input: cached lanes, viewed ID and selection callback. Output: read-only bounded workflow navigation.
export function WorkflowNavigation({ lanes, selected, onSelect }: { lanes: Lane[]; selected: string | null; onSelect: (id: string | null) => void }) {
  const index = lanes.findIndex(lane => lane.lane_id === selected);
  const lane = lanes[index];
  return <nav className="workflow-navigation" aria-label="流程浏览">
    <button className={`overview-button ${!lane ? 'selected' : ''}`} onClick={() => onSelect(null)} aria-current={!lane ? 'page' : undefined}><LayoutDashboard size={17} />总览</button>
    <span className="nav-divider" aria-hidden="true" />
    <div className="arrows">
      <button className="icon-button" title="上一个流程" aria-label="上一个流程" disabled={index <= 0} onClick={() => onSelect(lanes[index - 1].lane_id)}><ArrowLeft size={18} /></button>
      <span className="page-count" aria-live="polite">{lane ? `${index + 1} / ${lanes.length}` : `— / ${lanes.length}`}</span>
      <button className="icon-button" title="下一个流程" aria-label="下一个流程" disabled={!lanes.length || index >= lanes.length - 1} onClick={() => onSelect(lanes[index + 1].lane_id)}><ArrowRight size={18} /></button>
    </div>
    {lane && <div className="current-lane"><span>{lane.name}</span><Status value={lane.status} /></div>}
  </nav>;
}
