export type JsonValue = string | number | boolean | null | JsonValue[] | { [key: string]: JsonValue };
export type Stage = 'scout' | 'seed' | 'repair';
export type Action = 'start' | 'stop';

export interface ExperimentNode {
  node_id: string;
  parent_id?: string | null;
  layer: number | null;
  hypothesis: string | Record<string, JsonValue> | null;
  expression: string | null;
  settings: Record<string, JsonValue> | null;
  alpha_id: string | null;
  signal: JsonValue;
  metrics: Record<string, JsonValue> | null;
  state: string;
  reason: string | null;
  score?: number | null;
  condition?: JsonValue;
  field_characteristics?: JsonValue;
  sources?: JsonValue;
  comparison?: JsonValue;
  raw_signal?: JsonValue;
  directional_signal?: JsonValue;
  arms?: Record<string, ExperimentNode>;
}

export interface Lane {
  lane_id: string;
  name: string;
  status: string;
  stage: string;
  nodes: ExperimentNode[];
  seeds: ExperimentNode[];
  repair: ExperimentNode[];
}

export interface CommandReply {
  command_id: string;
  status: string;
  job_id?: string;
  message?: string;
}

export interface ApplicationSnapshot {
  schema_version: 1;
  server_epoch: string;
  sequence: number;
  evidence_at: string | null;
  request_revision: string | number;
  group: {
    group_id: string;
    status: string;
    desired_state: string;
    daily_budget?: JsonValue;
  };
  lanes: Lane[];
  allowed_actions: { start: boolean; stop: boolean };
  options: { option_id: string; title: string }[];
  blocker: string;
  command_statuses?: CommandReply[] | Record<string, Omit<CommandReply, 'command_id'>>;
}

export interface TrackedCommand extends CommandReply {
  action: Action;
  expected_revision: string | number;
  group_id: string;
}

export type Connection = 'connecting' | 'live' | 'reconnecting' | 'polling' | 'offline' | 'fixture';
export interface ApplicationState {
  snapshot: ApplicationSnapshot | null;
  connection: Connection;
  error: string;
  commands: TrackedCommand[];
}

export interface LaneView {
  stage: Stage;
  selected: Partial<Record<Stage, string>>;
  collapsed: string[];
  scroll: Record<string, number>;
  focus: string | null;
}
