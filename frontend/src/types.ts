export type Booking = {
  id: string;
  profile_id: string;
  step_key: string;
  status: string;
  slot: string;
  service_id: string;
  external_ref: string | null;
  status_reason: string | null;
  reconciled_route_id: string | null;
};
export type Prerequisite = {
  key: string;
  title: string;
  description: string;
  kind: "lab";
  service_key: string;
  gate: "before_booking" | "before_execution";
  readiness?: "pending" | "ready" | "rejected" | "expired";
  valid_until?: string | null;
  booking?: Booking | null;
};
export type Step = {
  key: string;
  title: string;
  description: string;
  action_type: "consultation" | "followup" | "diagnostic_imaging" | "procedure";
  depends_on: string[];
  unlock_on: ("followup_needed" | "resolved")[];
  prerequisites?: Prerequisite[];
  booking_gate_open?: boolean;
  execution_gate_open?: boolean;
  availability?: string;
  booking?: Booking | null;
  choice?: {
    status: "declined" | "resumed";
    reason_code: string | null;
    updated_at: string;
  } | null;
};
export type Trace = {
  rule_id: string;
  matched: boolean;
  checks: {
    field: string;
    actual: unknown;
    op: string;
    expected: unknown;
    passed: boolean;
    source_pointer: string;
  }[];
};
export type Route = {
  id: string;
  version: number;
  status: string;
  parent_route_id?: string | null;
  trigger_result_id?: string | null;
  steps: Step[];
  warnings?: string[];
  trace?: Trace[];
  ruleset_version?: string;
  results?: Record<string, string>;
};
export type CaseSummary = {
  id: string;
  profile_id: string;
  clinic_id: string;
  modality: string;
  created_at: string;
  status: string;
  pending_review: boolean;
  conclusion: string;
};
export type IntegrationProfile = {
  label: string;
  clinic_id: string;
  input: "json" | "dicom";
  booking_mode: "local_simulator" | "deferred_simulator";
  services: Record<string, string>;
  fields: Record<string, Record<string, unknown>>;
  version: string;
  demo_scenarios: boolean;
};
export type CaseDetail = CaseSummary & {
  patient_token: string;
  source_kind: string;
  source_profile_id: string;
  report: {
    study_uid: string;
    encounter_ref: string;
    source_version: number;
    conclusion: string;
    exam_purpose: string;
    facts: {
      code: string;
      value: unknown;
      source_pointer: string;
      unit?: string;
    }[];
  };
  proposal: Route;
  published_route: Route | null;
  previous_bookings: (Booking & {
    route_version: number;
    original_route_version: number;
    title: string;
  })[];
  history: { id: string; version: number; status: string; profile_id: string }[];
  events: {
    id: string;
    kind: string;
    created_at: string;
    payload: Record<string, unknown>;
  }[];
  decisions: { action: string; reason: string; reason_code: string }[];
};
export type Patient = {
  case_id: string;
  pending_review: boolean;
  route: Route | null;
  previous_bookings: (Booking & {
    route_version: number;
    original_route_version: number;
    title: string;
  })[];
};
export type LatencySummary = {
  count: number;
  p50_ms: number | null;
  p95_ms: number | null;
  p99_ms: number | null;
};
export type Metrics = {
  counts: Record<string, number>;
  routing_latency: LatencySummary & {
    unit: "ms";
    boundary: "field_parsing_to_route_proposal_before_commit";
    by_modality: Record<string, LatencySummary>;
    by_format: Record<string, LatencySummary>;
  };
  workflow_latency: {
    unit: "ms";
    boundary: "persisted_event_timestamps";
    proposal_to_decision: LatencySummary;
    approval_to_publication: LatencySummary;
  };
  booking_conversion: number | null;
  conversion_details: {
    unit: "shown_route_versions";
    attribution_window_days: number;
    shown_route_versions: number;
    converted_route_versions: number;
    provisional_route_versions: number;
    shown_from: string | null;
    shown_before: string | null;
    booking_conversion: number | null;
  };
  patient_choices: {
    unit: "shown_route_versions";
    attribution_window_days: number;
    shown_route_versions: number;
    route_versions_with_decline: number;
    route_versions_with_resume: number;
    resume_rate_after_decline: number | null;
    by_step: {
      step_key: string;
      declined_route_steps: number;
      resumed_route_steps: number;
      first_decline_reasons: Record<string, number>;
    }[];
  };
  uplift: number | null;
  uplift_status: "no_control_group";
  synthetic: boolean;
};
export type QualityReview = {
  synthetic: boolean;
  unit: "route_decisions";
  aggregation_only: boolean;
  total_decisions: number;
  groups: {
    profile_id: string;
    modality: string;
    exam_purpose: "screening" | "diagnostic" | "unknown";
    ruleset_version: string;
    rule_id: string;
    proposal_mode: "manual" | "rule";
    decisions: number;
    approved: number;
    edited: number;
    rejected: number;
    edit_types: Record<string, number>;
    reason_codes: Record<string, number>;
  }[];
};
