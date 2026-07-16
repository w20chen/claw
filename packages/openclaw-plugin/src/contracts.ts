export type Mode = "observe" | "enforce";
export type ExecutionBackend = "hook-only" | "marker" | "managed-wrapper";
export type ProfilingMode = "off" | "proc" | "perf" | "ksys" | "vtune";

export type PluginConfig = {
  endpoint: string;
  mode: Mode;
  decisionTimeoutMs: number;
  reportTimeoutMs: number;
  failOpen: boolean;
  sendRawParams: boolean;
  authTokenEnv: string;
  logLevel: "error" | "warn" | "info" | "debug";
  executionBackend: ExecutionBackend;
  launcherPath: string;
  collectorSocket: string;
  instrumentHosts: string[];
  instrumentTools: string[];
  enableCgroup: boolean;
  enableAffinity: boolean;
  enableNuma: boolean;
  profilingMode: ProfilingMode;
  securityBoundaryAccepted: boolean;
};

export type CommonEvent = {
  schema_version: "scheduler.v1";
  event_id: string;
  occurred_at: string;
  plugin_version: string;
  run_id: string | null;
  session_id: string | null;
  session_key: string | null;
  agent_id: string | null;
};

export type ResourceScope = {
  pid: number | null;
  process_start_time: number | null;
  container_id: string | null;
  include_children: boolean;
  source: string | null;
  kind?: "pid" | "cgroup-v2";
  execution_id?: string | null;
  root_pid?: number | null;
  root_starttime_ticks?: number | null;
  cgroup_path?: string | null;
  pid_namespace_inode?: number | null;
  attribution_source?: string | null;
};

export type ToolBeforeRequest = CommonEvent & {
  tool_call_id: string | null;
  tool_name: string;
  tool_kind: string | null;
  tool_input_kind: string | null;
  operation_hint: string | null;
  derived_paths: string[];
  params_digest: string;
  param_features: {
    serialized_size_bytes: number;
    string_length: number;
    list_item_count: number;
    path_count: number;
    has_command_like_field: boolean;
  };
  raw_params: unknown | null;
  resource_scope: ResourceScope | null;
};

export type ToolDecision = {
  decision_id: string;
  action: "allow" | "block";
  reason_code: string;
  reason: string;
  policy_name: string;
  policy_version: string;
  lease_id: string | null;
  prediction: {
    duration_p50_ms: number | null;
    duration_p90_ms: number | null;
    resource_class: string;
    confidence: number | null;
  };
  placement_advice: {
    cpu_set: string | null;
    numa_node: number | null;
    llc_cluster: string | null;
    advisory: true;
  };
  placement?: unknown | null;
  profiling?: unknown | null;
};

export type ExecutionRegistrationRequest = {
  execution_id: string;
  tool_call_id: string | null;
  run_id: string | null;
  session_key_hash: string | null;
  command_digest: string;
  command: string;
  workdir: string | null;
  host: string;
  placement: unknown | null;
  profiling: unknown | null;
  backend: "marker" | "managed-wrapper";
};

export type ExecutionRegistrationResponse = {
  execution_id: string;
  one_time_token: string;
  expires_at: string;
};

export type ToolCompletedEvent = CommonEvent & {
  tool_call_id: string | null;
  decision_id: string | null;
  lease_id: string | null;
  execution_id: string | null;
  tool_name: string;
  duration_ms: number;
  succeeded: boolean;
  error_type: string | null;
  error_digest: string | null;
  result_size_bytes: number | null;
  resource_scope: ResourceScope | null;
};
