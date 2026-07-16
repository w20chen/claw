import {definePluginEntry, type HookApi} from "@openclaw/plugin-sdk";
import {randomUUID} from "node:crypto";
import {SidecarClient} from "./client.js";
import {loadConfig, isRecord} from "./config.js";
import {CorrelationMap} from "./correlation.js";
import type {CommonEvent, ToolBeforeRequest, ToolCompletedEvent} from "./contracts.js";
import {consoleLogger} from "./logging.js";
import {paramFeatures, redact, stableDigest} from "./redaction.js";

const pluginVersion = "0.1.0";

export default definePluginEntry((api: HookApi) => {
  const config = loadConfig(api.getConfig ? api.getConfig() : {});
  const logger = api.logger ?? consoleLogger;
  const client = new SidecarClient(config);
  const correlation = new CorrelationMap(300_000, 10_000);

  api.on("before_tool_call", async (event: unknown) => {
    const payload = buildToolBefore(event, config.sendRawParams);
    try {
      const decision = await client.decide(payload);
      correlation.set(payload.tool_call_id, decision.decision_id, decision.lease_id);
      if (config.mode === "enforce" && decision.action === "block") {
        return {
          action: "block",
          blockReason: decision.reason,
          reasonCode: decision.reason_code
        };
      }
      return undefined;
    } catch (error) {
      logger.warn("hardware scheduler decision failed", classifyError(error));
      if (config.mode === "observe" || config.failOpen) return undefined;
      return {
        action: "block",
        blockReason: "Hardware scheduler sidecar unavailable and failOpen=false.",
        reasonCode: "sidecar_unavailable"
      };
    }
  });

  api.on("after_tool_call", async (event: unknown) => {
    const completion = buildCompletion(event, correlation.take(extractString(event, ["tool_call_id", "toolCallId", "id"])));
    try {
      await client.reportCompletion(completion);
    } catch (error) {
      logger.warn("hardware scheduler completion report failed", classifyError(error));
    }
  });

  api.on("model_call_started", async (event: unknown) => {
    await reportModel(client, logger, event, "model_call_started");
  });

  api.on("model_call_ended", async (event: unknown) => {
    await reportModel(client, logger, event, "model_call_ended");
  });
});

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

function buildToolBefore(event: unknown, sendRawParams: boolean): ToolBeforeRequest {
  const params = isRecord(event) ? event.params ?? event.arguments ?? event.input ?? null : null;
  const safeParams = redact(params);
  return {
    ...common(event),
    tool_call_id: extractString(event, ["tool_call_id", "toolCallId", "id"]),
    tool_name: extractString(event, ["tool_name", "toolName", "name"]) ?? "unknown",
    tool_kind: extractString(event, ["tool_kind", "toolKind", "kind"]),
    tool_input_kind: extractString(event, ["tool_input_kind", "toolInputKind", "inputKind"]),
    derived_paths: [],
    params_digest: stableDigest(safeParams),
    param_features: paramFeatures(safeParams),
    raw_params: sendRawParams ? safeParams : null
  };
}

function buildCompletion(
  event: unknown,
  prior: {decisionId: string | null; leaseId: string | null} | null
): ToolCompletedEvent {
  const errorType = extractString(event, ["error_type", "errorType"]);
  return {
    ...common(event),
    tool_call_id: extractString(event, ["tool_call_id", "toolCallId", "id"]),
    decision_id: prior?.decisionId ?? null,
    lease_id: prior?.leaseId ?? null,
    tool_name: extractString(event, ["tool_name", "toolName", "name"]) ?? "unknown",
    duration_ms: extractNumber(event, ["duration_ms", "durationMs"]) ?? 0,
    succeeded: extractBoolean(event, ["succeeded", "success"]) ?? errorType === null,
    error_type: errorType,
    error_digest: null,
    result_size_bytes: extractNumber(event, ["result_size_bytes", "resultSizeBytes"])
  };
}

async function reportModel(client: SidecarClient, logger: {warn(message: string, data?: unknown): void}, event: unknown, eventType: string): Promise<void> {
  try {
    await client.reportModel({
      ...common(event),
      event_type: eventType,
      call_id: extractString(event, ["call_id", "callId", "id"]),
      provider: extractString(event, ["provider"]),
      model: extractString(event, ["model"]),
      duration_ms: extractNumber(event, ["duration_ms", "durationMs"]),
      outcome: extractString(event, ["outcome", "status"]),
      context_token_budget: extractNumber(event, ["context_token_budget", "contextTokenBudget"])
    });
  } catch (error) {
    logger.warn("hardware scheduler model report failed", classifyError(error));
  }
}

function extractString(value: unknown, keys: string[]): string | null {
  if (!isRecord(value)) return null;
  for (const key of keys) {
    const item = value[key];
    if (typeof item === "string" && item.length > 0) return item;
  }
  return null;
}

function extractNumber(value: unknown, keys: string[]): number | null {
  if (!isRecord(value)) return null;
  for (const key of keys) {
    const item = value[key];
    if (typeof item === "number" && Number.isFinite(item) && item >= 0) return Math.floor(item);
  }
  return null;
}

function extractBoolean(value: unknown, keys: string[]): boolean | null {
  if (!isRecord(value)) return null;
  for (const key of keys) {
    const item = value[key];
    if (typeof item === "boolean") return item;
  }
  return null;
}

function classifyError(error: unknown): {type: string; message: string} {
  if (error instanceof Error) return {type: error.name, message: error.message};
  return {type: "unknown", message: String(error)};
}
