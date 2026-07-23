/**
 * Trace v5 reader / normalizer.
 *
 * Reads v5 single-line-complete-action records and normalizes them into
 * the v6 span_start / span_end model for backward compatibility.
 */

import type {
  SpanStartRecord,
  SpanEndRecord,
  SpanIdentity,
  SpanKind,
  StatusCode,
  AttributionStatus,
  MonitorQuality,
  ExecutionMode,
} from "./schema.js";

export interface V5ActionRecord {
  type: string;
  action_type: string;
  action_id: string;
  run_id: string | null;
  session_id: string | null;
  session_key?: string | null;
  agent_id: string | null;
  ts_start: number;
  ts_end: number;
  data: V5ActionData;
}

export interface V5ActionData {
  tool_name?: string;
  tool_args?: unknown;
  tool_result?: unknown;
  duration_ms?: number;
  success?: boolean;
  error?: string | null;
  resource_usage?: V5ResourceUsage;
  provider?: string;
  model?: string;
  messages_in?: unknown;
  content?: unknown;
  llm_latency_ms?: number;
  outcome?: string;
  context_token_budget?: number;
  raw_request?: unknown;
  raw_response?: unknown;
}

export interface V5ResourceUsage {
  attribution_status?: string;
  monitor_source?: string;
  sampling_interval_ms?: number;
  sampling_point_count?: number;
  sampling_quality?: string;
  cpu_time_delta_s?: number;
  cpu_utilization_avg_cores?: number | null;
  cpu_utilization_avg_pct?: number | null;
  memory_rss_bytes_before?: number | null;
  memory_rss_bytes_after?: number | null;
  memory_rss_bytes_peak?: number | null;
  memory_footprint_bytes?: number | null;
  disk_read_bytes_delta?: number | null;
  disk_write_bytes_delta?: number | null;
  net_rx_bytes_delta?: number | null;
  net_tx_bytes_delta?: number | null;
  target_pid?: number | null;
}

/**
 * Try to detect if a JSON line is a v5 record.
 */
export function isV5Record(record: unknown): record is V5ActionRecord {
  if (typeof record !== "object" || record === null) return false;
  const r = record as Record<string, unknown>;
  return r.type === "action" && typeof r.action_type === "string";
}

/**
 * Normalize a v5 action record into a pair of v6 span_start + span_end records.
 * Returns [spanStart, spanEnd] or null if the record can't be normalized.
 */
export function normalizeV5ToV6(record: V5ActionRecord): [SpanStartRecord, SpanEndRecord] | null {
  const kind: SpanKind = record.action_type === "llm_call" ? "llm" : "tool";
  const name = kind === "llm"
    ? (record.data.model ?? "unknown-model")
    : (record.data.tool_name ?? "unknown-tool");

  // v5 timestamps are wall-clock seconds — convert to ns
  const wallStartNs = BigInt(Math.floor(record.ts_start * 1_000_000_000));
  const wallEndNs = BigInt(Math.floor(record.ts_end * 1_000_000_000));
  // We don't have monotonic times from v5, so use wall-clock as fallback
  // and mark quality as derived
  const durationMs = record.data.duration_ms ?? 0;
  const durationNs = BigInt(Math.floor((durationMs > 0 ? durationMs : Math.max(0, (record.ts_end - record.ts_start) * 1000))) * 1_000_000);

  const identity: Omit<SpanIdentity, "record_type" | "wall_time_ns" | "monotonic_time_ns"> = {
    schema_version: 6,
    trace_id: record.run_id ?? record.action_id,
    span_id: record.action_id,
    parent_span_id: null, // v5 doesn't have explicit parent info
    session_id: record.session_id,
    run_id: record.run_id,
    agent_id: record.agent_id,
    sequence_no: 0, // unknown from v5
    kind,
    name,
  };

  // Determine status
  let statusCode: StatusCode = "unknown";
  if (kind === "tool") {
    if (record.data.success === true) statusCode = "ok";
    else if (record.data.error) statusCode = "error";
    else statusCode = "unknown";
  } else {
    if (record.data.outcome === "completed") statusCode = "ok";
    else if (record.data.outcome === "error") statusCode = "error";
    else statusCode = "unknown";
  }

  // Execution mode
  const mode: ExecutionMode = "in_process_or_runtime_managed";
  const resourceUsage = record.data.resource_usage;

  const spanStart: SpanStartRecord = {
    ...identity,
    record_type: "span_start",
    wall_time_ns: wallStartNs.toString(),
    monotonic_time_ns: wallStartNs.toString(), // fallback — derived from wall clock
    input: {
      requested_args: kind === "tool" ? (record.data.tool_args as Record<string, unknown> | null) ?? null : null,
      messages: kind === "llm" ? (record.data.messages_in as unknown[] | null) : null,
    },
    execution: {
      mode,
      execution_id: null,
    },
  };

  const spanEnd: SpanEndRecord = {
    ...identity,
    record_type: "span_end",
    wall_time_ns: wallEndNs.toString(),
    monotonic_time_ns: wallEndNs.toString(), // fallback — derived from wall clock
    duration_ns: durationNs.toString(),
    status: {
      code: statusCode,
      message: record.data.error ?? null,
    },
    output: {
      result: kind === "tool" ? record.data.tool_result : undefined,
      content: kind === "llm" ? record.data.content : undefined,
      exit_code: kind === "tool" && record.data.success === true ? 0 : undefined,
    },
    execution: {
      mode,
      execution_id: null,
      payload_pid: resourceUsage?.target_pid ?? null,
    },
    resources: {
      attribution_status: normalizeAttribution(resourceUsage?.attribution_status),
      scope: resourceUsage?.target_pid ? "process_tree" : "none",
      quality: "unknown", // v5 didn't track monitor windows
      monitor_start_wall_time_ns: null,
      monitor_end_wall_time_ns: null,
      monitor_start_monotonic_ns: null,
      monitor_end_monotonic_ns: null,
      coverage_duration_ns: null,
      action_duration_ns: durationNs.toString(),
      coverage_ratio: null,
      coverage_reason: "clock_data_missing",
      cpu_time_s: resourceUsage?.cpu_time_delta_s ?? null,
      rss_peak_bytes: resourceUsage?.memory_rss_bytes_peak ?? resourceUsage?.memory_footprint_bytes ?? null,
    },
  };

  return [spanStart, spanEnd];
}

function normalizeAttribution(raw: string | undefined): AttributionStatus {
  switch (raw) {
    case "pid": return "attributed";
    case "cgroup-v2": return "attributed";
    case "unattributed": return "unattributed";
    case "pid-unavailable": return "failed";
    default: return "unknown";
  }
}
