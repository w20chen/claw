import {definePluginEntry, type HookApi} from "openclaw/plugin-sdk/plugin-entry";
import {randomUUID} from "node:crypto";
import {SidecarClient} from "./client.js";
import {loadConfig, isRecord} from "./config.js";
import {CorrelationMap} from "./correlation.js";
import type {CommonEvent, ModelEvent, PluginConfig, ToolBeforeRequest, ToolCompletedEvent} from "./contracts.js";
import {buildTrustedResourceScope, instrumentExecParams} from "./exec-instrumentation.js";
import type {InstrumentResult} from "./exec-instrumentation.js";
import {consoleLogger} from "./logging.js";
import {jsonSafe, paramFeatures, redact, stableDigest} from "./redaction.js";
import {
  SpanRegistry,
} from "./trace/registry.js";
import {
  TraceWriter,
} from "./trace/writer.js";
import {
  monotonicNowNs,
  wallClockNowNs,
  durationNs,
  CLOCK_SOURCE_DESCRIPTION,
  CLOCK_PRECISION,
} from "./trace/clock.js";
import {
  sanitizeTraceData,
} from "./trace/sanitizer.js";
import type {
  SpanStartRecord,
  SpanEndRecord,
  TraceMetadataRecord,
  SpanKind,
  StatusCode,
  ExecutionMode,
  AttributionStatus,
  MonitorQuality,
  CoverageReason,
  SpanEndExecution,
  SpanEndResources,
} from "./trace/schema.js";
import { TRACE_SCHEMA_VERSION } from "./trace/schema.js";

const pluginVersion = "0.1.0";

// ── Plugin-wide state ──────────────────────────────────────────────────
let writer: TraceWriter | null = null;
let registry: SpanRegistry | null = null;

export default definePluginEntry({
  id: "hardware-scheduler",
  name: "Hardware Scheduler",
  description: "Hardware-aware tool scheduling bridge for OpenClaw.",
  configSchema: {
    type: "object",
    additionalProperties: false,
    properties: {
      endpoint: {type: "string", default: "http://127.0.0.1:8765"},
      mode: {enum: ["observe", "enforce"], default: "observe"},
      decisionTimeoutMs: {type: "integer", default: 800, minimum: 1},
      reportTimeoutMs: {type: "integer", default: 800, minimum: 1},
      failOpen: {type: "boolean", default: true},
      sendRawParams: {type: "boolean", default: false},
      recordRawTrace: {type: "boolean", default: true},
      authTokenEnv: {type: "string", default: "OPENCLAW_SCHEDULER_TOKEN"},
      logLevel: {enum: ["error", "warn", "info", "debug"], default: "info"},
      executionBackend: {enum: ["hook-only", "marker", "managed-wrapper"], default: "hook-only"},
      launcherPath: {type: "string", default: "/opt/claw/bin/claw-launch"},
      collectorSocket: {type: "string", default: "/run/claw/collector.sock"},
      instrumentHosts: {type: "array", items: {type: "string"}, default: ["gateway"]},
      instrumentTools: {type: "array", items: {type: "string"}, default: ["exec"]},
      enableCgroup: {type: "boolean", default: true},
      enableAffinity: {type: "boolean", default: true},
      enableNuma: {type: "boolean", default: true},
      profilingMode: {enum: ["off", "proc", "perf", "ksys", "vtune"], default: "off"},
      securityBoundaryAccepted: {type: "boolean", default: false},
      trace: {
        type: "object",
        additionalProperties: false,
        properties: {
          schema_version: {type: "integer", default: 6},
          include_raw_events: {type: "boolean", default: false},
          include_llm_messages: {type: "boolean", default: true},
          include_tool_outputs: {type: "boolean", default: true},
          redact_sensitive_data: {type: "boolean", default: true},
          flush_span_start: {type: "boolean", default: true},
          max_string_bytes: {type: "integer", default: 16384},
          max_messages_bytes: {type: "integer", default: 131072},
          max_tool_output_bytes: {type: "integer", default: 65536},
          trace_file_path: {type: "string", default: ""},
        },
      },
    }
  },
  register(api: HookApi): void {
  const config = loadConfig(api.pluginConfig ?? {});
  const logger = api.logger ?? consoleLogger;
  const client = new SidecarClient(config);
  const correlation = new CorrelationMap(300_000, 10_000);

  // Initialize trace v6 if trace_file_path is configured
  registry = new SpanRegistry();
  const traceCfg = config.trace;
  if (traceCfg.trace_file_path && traceCfg.trace_file_path.length > 0) {
    writer = new TraceWriter(traceCfg.trace_file_path, traceCfg.flush_span_start, logger);
    writer.open().then(() => {
      const metadata: TraceMetadataRecord = {
        schema_version: TRACE_SCHEMA_VERSION,
        record_type: "trace_metadata",
        trace_format_version: TRACE_SCHEMA_VERSION,
        scaffold: "openclaw",
        mode: "collect",
        created_at: new Date().toISOString().replace("+00:00", "Z"),
        clock_source: CLOCK_SOURCE_DESCRIPTION,
        clock_precision: CLOCK_PRECISION,
      };
      writer!.writeRecord(metadata);
    }).catch(() => {
      // best-effort
    });
  }

  // ── before_tool_call ──────────────────────────────────────────────

  api.on("before_tool_call", async (event: unknown, context: unknown) => {
    const toolName = extractString(event, ["tool_name", "toolName", "name"]) ?? "unknown";
    const toolCallId = extractString(event, ["tool_call_id", "toolCallId", "id"]);
    const runId = extractString(event, ["run_id", "runId"]) ?? extractString(context, ["runId", "run_id"]);
    const sessionId = extractString(event, ["session_id", "sessionId"]) ?? extractString(context, ["sessionId", "session_id"]);
    const agentId = extractString(event, ["agent_id", "agentId"]) ?? extractString(context, ["agentId", "agent_id"]);
    const traceId = runId ?? "unknown-run";

    // Resolve parent span
    let parentSpanId: string | null = null;
    let correlationStatus: "resolved" | "unresolved" = "unresolved";
    let correlationReason: string | null = null;
    if (toolCallId && registry) {
      parentSpanId = registry.getToolCallParent(toolCallId);
      if (parentSpanId) {
        correlationStatus = "resolved";
      } else {
        correlationReason = "tool_call_id_not_found";
      }
    } else {
      correlationReason = "no_tool_call_id";
    }

    // Generate span ID
    const spanId = toolCallId ?? `${traceId}:tool:${registry ? String(registry.listActiveSpans().length) : "0"}`;

    // Build span_start
    const startWall = wallClockNowNs();
    const startMono = monotonicNowNs();

    if (registry) {
      registry.beginSpan({
        traceId,
        spanId,
        parentSpanId,
        sessionId,
        runId,
        agentId,
        kind: "tool",
        name: toolName,
        startWallTimeNs: startWall,
        startMonotonicTimeNs: startMono,
      });
    }

    // Build input args from before hook (the true source of truth)
    const hookParams = isRecord(event) ? (event as Record<string, unknown>).params ?? (event as Record<string, unknown>).arguments ?? (event as Record<string, unknown>).input ?? null : null;

    // Write span_start immediately (before any sidecar calls)
    if (writer) {
      const spanStart: SpanStartRecord = {
        schema_version: TRACE_SCHEMA_VERSION,
        record_type: "span_start",
        trace_id: traceId,
        span_id: spanId,
        parent_span_id: parentSpanId,
        session_id: sessionId,
        run_id: runId,
        agent_id: agentId,
        sequence_no: registry?.getSpan(traceId, spanId)?.sequenceNo ?? 0,
        kind: "tool",
        name: toolName,
        wall_time_ns: startWall.toString(),
        monotonic_time_ns: startMono.toString(),
        input: {
          requested_args: traceCfg.redact_sensitive_data
            ? (sanitizeTraceData(hookParams) as Record<string, unknown> | null)
            : (jsonSafe(hookParams) as Record<string, unknown> | null),
        },
        execution: {
          mode: null, // Will be filled by instrumentExecParams
          execution_id: null,
        },
        correlation: correlationStatus === "unresolved" ? {
          status: correlationStatus,
          reason: correlationReason,
        } : undefined,
      };
      writer.writeRecord(spanStart);
      if (registry) registry.markStartWritten(traceId, spanId);
    }

    // Original sidecar logic
    const payload = buildToolBefore(event, config);
    mergeContext(payload, context);
    payload.resource_scope = buildTrustedResourceScope(event, context);
    try {
      const decision = await client.decide(payload);
      if (config.mode === "enforce" && decision.action === "block") {
        return {
          block: true,
          blockReason: decision.reason
        };
      }
      const instrumentation = await instrumentExecParams(event, context, payload, decision, client, config);
      correlation.set(payload.tool_call_id, decision.decision_id, decision.lease_id, instrumentation.executionId);

      // Store command variants for span_end
      if (registry) {
        const span = registry.getSpan(traceId, spanId);
        if (span) {
          span.metadata = {
            requestedCommand: instrumentation.requestedCommand,
            effectiveCommand: instrumentation.effectiveCommand,
            payloadCommand: instrumentation.payloadCommand,
            executionId: instrumentation.executionId,
          };
        }
      }

      return instrumentation.params === null ? undefined : {params: instrumentation.params};
    } catch (error) {
      logger.warn("hardware scheduler decision failed", classifyError(error));
      if (config.mode === "observe" || config.failOpen) return undefined;
      return {
        block: true,
        blockReason: "Hardware scheduler sidecar unavailable and failOpen=false."
      };
    }
  });

  // ── after_tool_call ───────────────────────────────────────────────

  api.on("after_tool_call", async (event: unknown, context: unknown) => {
    const toolName = extractString(event, ["tool_name", "toolName", "name"]) ?? "unknown";
    const toolCallId = extractString(event, ["tool_call_id", "toolCallId", "id"]);
    const runId = extractString(event, ["run_id", "runId"]) ?? extractString(context, ["runId", "run_id"]);
    const traceId = runId ?? "unknown-run";
    const spanId = toolCallId ?? traceId;

    const endWall = wallClockNowNs();
    const endMono = monotonicNowNs();

    // Look up the active span for start times
    const activeSpan = registry?.endSpan(traceId, spanId) ?? null;

    // Clean up parent mapping
    if (toolCallId && registry) {
      registry.clearToolCallParent(toolCallId);
    }

    const startMono = activeSpan?.startMonotonicTimeNs ?? endMono;
    const startWall = activeSpan?.startWallTimeNs ?? endWall;
    const parentSpanId = activeSpan?.parentSpanId ?? null;
    const durNs = durationNs(startMono, endMono);

    // Original sidecar logic
    const completion = buildCompletion(
      event,
      correlation.take(extractString(event, ["tool_call_id", "toolCallId", "id"])),
      config
    );
    mergeContext(completion, context);
    completion.resource_scope = buildTrustedResourceScope(event, context);
    if (completion.resource_scope === null && completion.execution_id !== null) {
      try {
        completion.resource_scope = await client.getExecutionScope(completion.execution_id);
      } catch (error) {
        logger.warn("hardware scheduler execution scope lookup failed", classifyError(error));
      }
    }
    try {
      await client.reportCompletion(completion);
    } catch (error) {
      logger.warn("hardware scheduler completion report failed", classifyError(error));
    }

    // Determine status code
    let statusCode: StatusCode = "unknown";
    if (completion.succeeded) {
      statusCode = "ok";
    } else if (completion.error_type === "timeout") {
      statusCode = "timeout";
    } else if (completion.error_type === "cancelled") {
      statusCode = "cancelled";
    } else if (completion.error_type) {
      statusCode = "error";
    }

    // Build execution info
    const execMode: ExecutionMode = completion.execution_id
      ? (config.executionBackend === "managed-wrapper" ? "launcher" : "marker")
      : "in_process_or_runtime_managed";

    const scope = completion.resource_scope;
    const meta = activeSpan?.metadata;
    const execInfo: SpanEndExecution = {
      mode: execMode,
      execution_id: completion.execution_id,
      requested_command: (meta?.requestedCommand as string | null) ?? null,
      effective_command: (meta?.effectiveCommand as string | null) ?? null,
      payload_command: (meta?.payloadCommand as string | null) ?? null,
      payload_pid: scope?.root_pid ?? scope?.pid ?? null,
      payload_pid_start_time_ticks: scope?.root_starttime_ticks ?? null,
      cgroup_path: scope?.cgroup_path ?? null,
      cgroup_id: null,
      pid_role: scope?.root_pid ? "payload_root" : (scope?.pid ? "payload_root" : null),
    };

    // Sanitize command fields for trace
    if (traceCfg.redact_sensitive_data) {
      if (execInfo.effective_command) {
        execInfo.effective_command = sanitizeTraceData(execInfo.effective_command) as string;
      }
    }

    // Build resource info
    const resourceScope = completion.resource_scope;
    const hasPid = (resourceScope?.pid ?? resourceScope?.root_pid) !== null;
    const hasCgroup = resourceScope?.cgroup_path !== null;

    let attrStatus: AttributionStatus;
    let resQuality: MonitorQuality = "unknown";
    let coverageReason: CoverageReason | string = "pid_unavailable";

    if (!hasPid && !hasCgroup) {
      attrStatus = "unattributed";
      coverageReason = "pid_unavailable";
    } else if (hasCgroup) {
      attrStatus = "attributed";
      coverageReason = "full_window";
      resQuality = "partial"; // We don't know the exact monitor window without launcher data
    } else {
      attrStatus = "partially_attributed";
      coverageReason = "pid_registered_late";
      resQuality = "partial";
    }

    // For native tools with no PID, mark appropriately
    if (!completion.execution_id && !hasPid) {
      attrStatus = "unattributed";
      resQuality = "unknown";
      coverageReason = "pid_unavailable";
    }

    const resources: SpanEndResources = {
      attribution_status: attrStatus,
      scope: hasCgroup ? "cgroup" : (hasPid ? "process_tree" : "none"),
      quality: resQuality,
      monitor_start_wall_time_ns: null,
      monitor_end_wall_time_ns: null,
      monitor_start_monotonic_ns: null,
      monitor_end_monotonic_ns: null,
      coverage_duration_ns: null,
      action_duration_ns: durNs.toString(),
      coverage_ratio: null,
      coverage_reason: coverageReason,
      cpu_time_s: null,
      rss_peak_bytes: null,
    };

    // Write span_end
    if (writer) {
      const seqNo = activeSpan?.sequenceNo ?? 0;
      const spanEnd: SpanEndRecord = {
        schema_version: TRACE_SCHEMA_VERSION,
        record_type: "span_end",
        trace_id: traceId,
        span_id: spanId,
        parent_span_id: parentSpanId,
        session_id: activeSpan?.sessionId ?? completion.session_id,
        run_id: runId,
        agent_id: activeSpan?.agentId ?? completion.agent_id,
        sequence_no: seqNo,
        kind: "tool",
        name: toolName,
        wall_time_ns: endWall.toString(),
        monotonic_time_ns: endMono.toString(),
        duration_ns: durNs.toString(),
        status: {
          code: statusCode,
          message: completion.error_type ?? null,
        },
        output: {
          exit_code: completion.succeeded ? 0 : null,
          result: traceCfg.include_tool_outputs
            ? (traceCfg.redact_sensitive_data
                ? sanitizeTraceData(completion.raw_result)
                : completion.raw_result)
            : null,
        },
        execution: execInfo,
        resources,
        correlation: activeSpan === null ? {
          status: "unresolved",
          reason: "span_start_not_found",
        } : undefined,
      };
      writer.writeRecord(spanEnd);
    }
  });

  // ── model_call_started ────────────────────────────────────────────

  let llmSeqCounter = 0;

  api.on("model_call_started", async (event: unknown, context: unknown) => {
    const callId = extractString(event, ["call_id", "callId", "id"]);
    const runId = extractString(event, ["run_id", "runId"]) ?? extractString(context, ["runId", "run_id"]);
    const sessionId = extractString(event, ["session_id", "sessionId"]) ?? extractString(context, ["sessionId", "session_id"]);
    const agentId = extractString(event, ["agent_id", "agentId"]) ?? extractString(context, ["agentId", "agent_id"]);
    const model = extractString(event, ["model"]) ?? "unknown-model";
    const provider = extractString(event, ["provider"]);
    const traceId = runId ?? "unknown-run";

    llmSeqCounter++;
    const spanId = callId ?? `${traceId}:model:${llmSeqCounter}`;

    const startWall = wallClockNowNs();
    const startMono = monotonicNowNs();

    if (registry) {
      registry.beginSpan({
        traceId,
        spanId,
        parentSpanId: null, // Top-level LLM calls have no parent
        sessionId,
        runId,
        agentId,
        kind: "llm",
        name: model,
        startWallTimeNs: startWall,
        startMonotonicTimeNs: startMono,
      });
    }

    // Write span_start
    if (writer) {
      const hookInput = extractModelInput(event);
      const spanStart: SpanStartRecord = {
        schema_version: TRACE_SCHEMA_VERSION,
        record_type: "span_start",
        trace_id: traceId,
        span_id: spanId,
        parent_span_id: null,
        session_id: sessionId,
        run_id: runId,
        agent_id: agentId,
        sequence_no: registry?.getSpan(traceId, spanId)?.sequenceNo ?? 0,
        kind: "llm",
        name: model,
        wall_time_ns: startWall.toString(),
        monotonic_time_ns: startMono.toString(),
        input: {
          requested_args: null,
          messages: traceCfg.include_llm_messages
            ? (traceCfg.redact_sensitive_data
                ? (sanitizeTraceData(hookInput) as unknown[] | null)
                : (jsonSafe(hookInput) as unknown[] | null))
            : null,
        },
        execution: {
          mode: null,
          execution_id: null,
        },
      };
      writer.writeRecord(spanStart);
      if (registry) registry.markStartWritten(traceId, spanId);
    }

    // Original sidecar logic
    await reportModel(client, logger, event, "model_call_started", config);

    // Store call_id -> span_id mapping for model_call_ended
    if (callId && registry) {
      // Store in a side map (we can use tool_call_parent with a special prefix)
      registry.setToolCallParent(`__llm_call__${callId}`, spanId);
    }
  });

  // ── model_call_ended ──────────────────────────────────────────────

  api.on("model_call_ended", async (event: unknown, context: unknown) => {
    const callId = extractString(event, ["call_id", "callId", "id"]);
    const runId = extractString(event, ["run_id", "runId"]) ?? extractString(context, ["runId", "run_id"]);
    const traceId = runId ?? "unknown-run";

    // Look up the span_id from the started event
    let spanId = callId ?? "";
    if (callId && registry) {
      const mappedSpanId = registry.getToolCallParent(`__llm_call__${callId}`);
      if (mappedSpanId) {
        spanId = mappedSpanId;
        registry.clearToolCallParent(`__llm_call__${callId}`);
      }
    }
    if (!spanId) {
      llmSeqCounter++;
      spanId = `${traceId}:model:${llmSeqCounter}`;
    }

    const endWall = wallClockNowNs();
    const endMono = monotonicNowNs();

    const activeSpan = registry?.endSpan(traceId, spanId) ?? null;
    const startMono = activeSpan?.startMonotonicTimeNs ?? endMono;
    const durNs = durationNs(startMono, endMono);

    const model = extractString(event, ["model"]) ?? activeSpan?.name ?? "unknown-model";
    const outcome = extractString(event, ["outcome", "status"]);
    const durationMs = extractNumber(event, ["duration_ms", "durationMs"]);

    // Extract tool calls from the response to set up parent mapping
    if (registry) {
      const toolCalls = extractToolCallsFromResponse(event);
      for (const tcId of toolCalls) {
        registry.setToolCallParent(tcId, spanId);
      }
    }

    // Determine status
    let statusCode: StatusCode = "unknown";
    if (outcome === "completed" || outcome === "ok" || outcome === "success") {
      statusCode = "ok";
    } else if (outcome === "error" || outcome === "failed") {
      statusCode = "error";
    } else if (outcome === "timeout") {
      statusCode = "timeout";
    } else if (outcome === "cancelled") {
      statusCode = "cancelled";
    }

    // Write span_end
    if (writer) {
      const hookOutput = extractModelOutput(event);
      const spanEnd: SpanEndRecord = {
        schema_version: TRACE_SCHEMA_VERSION,
        record_type: "span_end",
        trace_id: traceId,
        span_id: spanId,
        parent_span_id: null,
        session_id: activeSpan?.sessionId ?? null,
        run_id: runId,
        agent_id: activeSpan?.agentId ?? null,
        sequence_no: activeSpan?.sequenceNo ?? 0,
        kind: "llm",
        name: model,
        wall_time_ns: endWall.toString(),
        monotonic_time_ns: endMono.toString(),
        duration_ns: durNs.toString(),
        status: {
          code: statusCode,
          message: null,
        },
        output: {
          content: traceCfg.include_tool_outputs
            ? (traceCfg.redact_sensitive_data
                ? sanitizeTraceData(hookOutput)
                : jsonSafe(hookOutput))
            : null,
        },
        execution: {
          mode: null,
          execution_id: null,
        },
        resources: {
          attribution_status: "not_applicable",
          scope: "none",
          quality: "unknown",
          monitor_start_wall_time_ns: null,
          monitor_end_wall_time_ns: null,
          monitor_start_monotonic_ns: null,
          monitor_end_monotonic_ns: null,
          coverage_duration_ns: null,
          action_duration_ns: durNs.toString(),
          coverage_ratio: null,
          coverage_reason: "pid_unavailable",
        },
        correlation: activeSpan === null ? {
          status: "unresolved",
          reason: "span_start_not_found",
        } : undefined,
      };
      writer.writeRecord(spanEnd);
    }

    // Original sidecar logic
    await reportModel(client, logger, event, "model_call_ended", config);
  });

  // ── Shutdown handling ────────────────────────────────────────────────
  // Write interrupted spans when plugin is being unloaded
  process.on("beforeExit", () => {
    if (registry && writer) {
      const activeSpans = registry.listActiveSpans();
      const endWall = wallClockNowNs();
      const endMono = monotonicNowNs();

      for (const span of activeSpans) {
        const durNs = durationNs(span.startMonotonicTimeNs, endMono);
        const spanEnd: SpanEndRecord = {
          schema_version: TRACE_SCHEMA_VERSION,
          record_type: "span_end",
          trace_id: span.traceId,
          span_id: span.spanId,
          parent_span_id: span.parentSpanId,
          session_id: span.sessionId,
          run_id: span.runId,
          agent_id: span.agentId,
          sequence_no: span.sequenceNo,
          kind: span.kind,
          name: span.name,
          wall_time_ns: endWall.toString(),
          monotonic_time_ns: endMono.toString(),
          duration_ns: durNs.toString(),
          status: {
            code: "interrupted",
            message: "plugin shutdown before span completion",
          },
          output: {},
          execution: {
            mode: null,
            execution_id: null,
          },
          resources: {
            attribution_status: "not_applicable",
            scope: "none",
            quality: "unknown",
            monitor_start_wall_time_ns: null,
            monitor_end_wall_time_ns: null,
            monitor_start_monotonic_ns: null,
            monitor_end_monotonic_ns: null,
            coverage_duration_ns: null,
            action_duration_ns: durNs.toString(),
            coverage_ratio: null,
            coverage_reason: "pid_unavailable",
          },
        };
        writer.writeRecord(spanEnd);
      }
    }
  });
}
});

// ── Helper functions ───────────────────────────────────────────────────

function common(event: unknown): CommonEvent {
  return {
    schema_version: "scheduler.v1",
    event_id: randomUUID(),
    occurred_at: new Date().toISOString(),
    plugin_version: pluginVersion,
    run_id: extractString(event, ["run_id", "runId"]),
    session_id: extractString(event, ["session_id", "sessionId"]),
    session_key: extractString(event, ["session_key", "sessionKey"]),
    agent_id: extractString(event, ["agent_id", "agentId"])
  };
}

function buildToolBefore(event: unknown, config: PluginConfig): ToolBeforeRequest {
  const params = isRecord(event) ? (event as Record<string, unknown>).params ?? (event as Record<string, unknown>).arguments ?? (event as Record<string, unknown>).input ?? null : null;
  const safeParams = redact(params);
  const rawParams = config.recordRawTrace ? jsonSafe(params) : config.sendRawParams ? safeParams : null;
  const toolName = extractString(event, ["tool_name", "toolName", "name"]) ?? "unknown";
  return {
    ...common(event),
    tool_call_id: extractString(event, ["tool_call_id", "toolCallId", "id"]),
    tool_name: toolName,
    tool_kind: extractString(event, ["tool_kind", "toolKind", "kind"]),
    tool_input_kind: extractString(event, ["tool_input_kind", "toolInputKind", "inputKind"]),
    operation_hint: operationHint(toolName, safeParams),
    derived_paths: [],
    params_digest: stableDigest(safeParams),
    param_features: paramFeatures(safeParams),
    raw_params: rawParams,
    raw_event: config.recordRawTrace ? jsonSafe(event) : null,
    resource_scope: null
  };
}

function operationHint(toolName: string, params: unknown): string | null {
  if (toolName.startsWith("exec-")) return toolName.slice("exec-".length) || null;
  if (toolName !== "exec") return null;
  const command = extractCommand(params);
  if (command === null) return null;
  const base = classifyCommand(command);
  return base === "exec" ? null : base;
}

function extractCommand(params: unknown): string | null {
  if (!isRecord(params)) return null;
  const p = params as Record<string, unknown>;
  const command = p.command ?? p.cmd;
  if (typeof command === "string" && command.length > 0) return command;
  const nested = p.exec;
  if (isRecord(nested)) {
    const nd = nested as Record<string, unknown>;
    const nestedCommand = nd.command ?? nd.cmd;
    if (typeof nestedCommand === "string" && nestedCommand.length > 0) return nestedCommand;
  }
  return null;
}

function classifyCommand(command: string): string {
  const commandMap: Record<string, string> = {
    grep: "grep", egrep: "grep", fgrep: "grep", rg: "grep",
    find: "find", fd: "find", python: "python", python3: "python",
    pytest: "pytest", django: "pytest", pip: "pip", pip3: "pip",
    git: "git", curl: "curl", wget: "curl", npm: "npm", npx: "npm",
    make: "make", gcc: "gcc", clang: "gcc", docker: "docker", podman: "docker",
    cat: "cat", sed: "sed", awk: "awk", ls: "ls", cd: "cd",
    rm: "rm", cp: "cp", mv: "mv"
  };
  const priority: Record<string, number> = {
    pytest: 4, pip: 4, pip3: 4,
    python: 3, python3: 3, git: 3, npm: 3, npx: 3, make: 3,
    gcc: 3, clang: 3, docker: 3, podman: 3, curl: 3, wget: 3,
    grep: 2, rg: 2, find: 2, fd: 2, cat: 2, sed: 2, awk: 2,
    rm: 2, cp: 2, mv: 2
  };
  let best = "exec";
  let bestPriority = -1;
  for (const segment of splitCommandSegments(command)) {
    const token = tokenizeCommandSegment(segment);
    if (token === null) continue;
    const category = commandMap[token] ?? safeUnknownCommand(token);
    if (category === null) continue;
    const score = priority[token] ?? 1;
    if (score >= bestPriority) {
      best = category;
      bestPriority = score;
    }
  }
  return best;
}

function splitCommandSegments(command: string): string[] {
  const segments: string[] = [];
  let current = "";
  let single = false;
  let double = false;
  for (let index = 0; index < command.length; index += 1) {
    const char = command[index];
    if (char === "'" && !double) single = !single;
    if (char === '"' && !single && command[index - 1] !== "\\") double = !double;
    if (!single && !double) {
      if (char === "|" || char === ";") {
        segments.push(current);
        current = "";
        continue;
      }
      if (char === "&" && command[index + 1] === "&") {
        segments.push(current);
        current = "";
        index += 1;
        continue;
      }
    }
    current += char;
  }
  segments.push(current);
  return segments;
}

function tokenizeCommandSegment(segment: string): string | null {
  const parts = segment.match(/"([^"\\]|\\.)*"|'[^']*'|\S+/g)?.map((part) => part.replace(/^['"]|['"]$/g, "")) ?? [];
  let index = 0;
  while (index < parts.length && /^[A-Za-z_][A-Za-z0-9_]*=.*$/s.test(parts[index])) index += 1;
  while (index < parts.length && ["sudo", "nice", "nohup", "timeout"].includes(baseName(parts[index]))) {
    const wrapper = baseName(parts[index]);
    index += 1;
    while (index < parts.length && parts[index].startsWith("-")) index += 1;
    if (wrapper === "timeout" && index < parts.length && /^\d+(\.\d+)?$/.test(parts[index])) index += 1;
  }
  if (index >= parts.length) return null;
  let token = baseName(parts[index]).toLowerCase();
  if ((token === "python" || token === "python3") && parts[index + 1] === "-m" && parts[index + 2]) {
    token = baseName(parts[index + 2]).toLowerCase();
  }
  return token;
}

function baseName(token: string): string {
  return token.split("/").pop() ?? token;
}

function safeUnknownCommand(token: string): string | null {
  const lowered = token.toLowerCase();
  return /^[a-z0-9][a-z0-9._+-]{0,63}$/.test(lowered) ? lowered : null;
}

function mergeContext(payload: CommonEvent, context: unknown): void {
  payload.run_id = payload.run_id ?? extractString(context, ["runId", "run_id"]);
  payload.session_id = payload.session_id ?? extractString(context, ["sessionId", "session_id"]);
  payload.session_key = payload.session_key ?? extractString(context, ["sessionKey", "session_key"]);
  payload.agent_id = payload.agent_id ?? extractString(context, ["agentId", "agent_id"]);
}

function buildCompletion(
  event: unknown,
  prior: {decisionId: string | null; leaseId: string | null; executionId: string | null} | null,
  config: PluginConfig
): ToolCompletedEvent {
  const errorType = extractString(event, ["error_type", "errorType"]);
  const rawResult = config.recordRawTrace ? jsonSafe(extractToolResult(event)) : null;
  const rawEvent = config.recordRawTrace ? jsonSafe(sanitizeCompletionRawEvent(event, config)) : null;
  return {
    ...common(event),
    tool_call_id: extractString(event, ["tool_call_id", "toolCallId", "id"]),
    decision_id: prior?.decisionId ?? null,
    lease_id: prior?.leaseId ?? null,
    execution_id: prior?.executionId ?? null,
    tool_name: extractString(event, ["tool_name", "toolName", "name"]) ?? "unknown",
    duration_ms: extractNumber(event, ["duration_ms", "durationMs"]) ?? 0,
    succeeded: extractBoolean(event, ["succeeded", "success"]) ?? errorType === null,
    error_type: errorType,
    error_digest: null,
    result_size_bytes: extractNumber(event, ["result_size_bytes", "resultSizeBytes"]),
    raw_result: rawResult,
    raw_event: rawEvent,
    resource_scope: null
  };
}

function sanitizeCompletionRawEvent(event: unknown, config: PluginConfig): unknown {
  const safe = jsonSafe(event);
  if (!isRecord(safe)) return safe;
  const params = (safe as Record<string, unknown>).params;
  if (!isRecord(params)) return safe;
  if (!isManagedWrapperCommand((params as Record<string, unknown>).command, config)) return safe;
  return {
    ...safe,
    params: {
      ...params,
      command: "<managed execution wrapper redacted>",
      env: redactManagedWrapperEnv((params as Record<string, unknown>).env)
    }
  };
}

function isManagedWrapperCommand(value: unknown, config: PluginConfig): boolean {
  if (typeof value !== "string") return false;
  return value.includes("claw-launch") || value.includes(config.launcherPath);
}

function redactManagedWrapperEnv(value: unknown): unknown {
  if (!isRecord(value)) return value;
  const output: Record<string, unknown> = {};
  for (const [key, item] of Object.entries(value as Record<string, unknown>)) {
    output[key] = key.startsWith("CLAW_") ? "<redacted>" : item;
  }
  return output;
}

async function reportModel(
  client: SidecarClient,
  logger: {warn(message: string, data?: unknown): void},
  event: unknown,
  eventType: "model_call_started" | "model_call_ended",
  config: PluginConfig
): Promise<void> {
  try {
    const payload: ModelEvent = {
      ...common(event),
      event_type: eventType,
      call_id: extractString(event, ["call_id", "callId", "id"]),
      provider: extractString(event, ["provider"]),
      model: extractString(event, ["model"]),
      duration_ms: extractNumber(event, ["duration_ms", "durationMs"]),
      outcome: extractString(event, ["outcome", "status"]),
      context_token_budget: extractNumber(event, ["context_token_budget", "contextTokenBudget"]),
      raw_input: config.recordRawTrace ? jsonSafe(extractModelInput(event)) : null,
      raw_output: config.recordRawTrace ? jsonSafe(extractModelOutput(event)) : null,
      raw_event: config.recordRawTrace ? jsonSafe(event) : null
    };
    await client.reportModel(payload);
  } catch (error) {
    logger.warn("hardware scheduler model report failed", classifyError(error));
  }
}

/**
 * Extract tool call IDs from a model_call_ended event's response.
 * Handles various shapes: choices[].message.tool_calls, tool_calls, etc.
 */
function extractToolCallsFromResponse(event: unknown): string[] {
  if (!isRecord(event)) return [];
  const evt = event as Record<string, unknown>;

  // Try various paths to find tool calls
  const output = evt.output ?? evt.response ?? evt.content ?? evt.message ?? evt.choices ?? evt;

  if (!isRecord(output)) return [];

  // Direct tool_calls array
  const directCalls = (output as Record<string, unknown>).tool_calls;
  if (Array.isArray(directCalls)) {
    return directCalls.map((tc: unknown) => {
      if (isRecord(tc)) return (tc as Record<string, unknown>).id ?? (tc as Record<string, unknown>).tool_call_id;
      return null;
    }).filter((id: unknown): id is string => typeof id === "string");
  }

  // choices[0].message.tool_calls (OpenAI-style)
  const choices = (output as Record<string, unknown>).choices;
  if (Array.isArray(choices) && choices.length > 0 && isRecord(choices[0])) {
    const message = (choices[0] as Record<string, unknown>).message ?? (choices[0] as Record<string, unknown>).delta;
    if (isRecord(message)) {
      const toolCalls = (message as Record<string, unknown>).tool_calls;
      if (Array.isArray(toolCalls)) {
        return toolCalls.map((tc: unknown) => {
          if (isRecord(tc)) return (tc as Record<string, unknown>).id ?? (tc as Record<string, unknown>).tool_call_id;
          return null;
        }).filter((id: unknown): id is string => typeof id === "string");
      }
    }
  }

  return [];
}

function extractToolResult(event: unknown): unknown {
  if (!isRecord(event)) return null;
  const evt = event as Record<string, unknown>;
  return evt.result ?? evt.output ?? evt.response ?? evt.content ?? evt.data ?? evt.toolResult ?? null;
}

function extractModelInput(event: unknown): unknown {
  if (!isRecord(event)) return null;
  const evt = event as Record<string, unknown>;
  return evt.messages ?? evt.input ?? evt.prompt ?? evt.request ?? evt.body ?? null;
}

function extractModelOutput(event: unknown): unknown {
  if (!isRecord(event)) return null;
  const evt = event as Record<string, unknown>;
  return evt.output ?? evt.response ?? evt.content ?? evt.message ?? evt.choices ?? evt.body ?? null;
}

function extractString(value: unknown, keys: string[]): string | null {
  if (!isRecord(value)) return null;
  const rec = value as Record<string, unknown>;
  for (const key of keys) {
    const item = rec[key];
    if (typeof item === "string" && item.length > 0) return item;
  }
  return null;
}

function extractNumber(value: unknown, keys: string[]): number | null {
  if (!isRecord(value)) return null;
  const rec = value as Record<string, unknown>;
  for (const key of keys) {
    const item = rec[key];
    if (typeof item === "number" && Number.isFinite(item) && item >= 0) return Math.floor(item);
  }
  return null;
}

function extractBoolean(value: unknown, keys: string[]): boolean | null {
  if (!isRecord(value)) return null;
  const rec = value as Record<string, unknown>;
  for (const key of keys) {
    const item = rec[key];
    if (typeof item === "boolean") return item;
  }
  return null;
}

function classifyError(error: unknown): {type: string; message: string} {
  if (error instanceof Error) return {type: error.name, message: error.message};
  return {type: "unknown", message: String(error)};
}