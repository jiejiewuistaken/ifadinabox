export type EventType =
  | "log"
  | "graph_update"
  | "round_update"
  | "draft_created"
  | "review_result"
  | "run_status";

export type RunEvent = {
  event_id: string;
  run_id: string;
  ts: string;
  type: EventType;
  payload: any;
};

export type CheckboxStatus = {
  id: string;
  label: string;
  status: "true" | "false" | "partial";
  rationale: string;
  evidence?: any[];
};

export type ReviewComment = {
  severity: "blocker" | "major" | "minor";
  section: string;
  comment: string;
  suggestion?: string | null;
};

