import {definePluginEntry, type HookApi} from "openclaw/plugin-sdk/plugin-entry";
import {randomUUID} from "node:crypto";
import {SidecarClient} from "./client.js";
import {loadConfig, isRecord} from "./config.js";
import {CorrelationMap} from "./correlation.js";
import type {CommonEvent, ResourceScope, ToolBeforeRequest, ToolCompletedEvent} from "./contracts.js";
import {consoleLogger} from "./logging.js";
import {paramFeatures, redact, stableDigest} from "./redaction.js";

const pluginVersion = "0.1.0";

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
      authTokenEnv: {type: "string", default: "OPENCLAW_SCHEDULER_TOKEN"},
      logLevel: {enum: ["error", "warn", "info", "debug"], default: "info"}
    }
  },
  register(api: HookApi): void {
  const config = loadConfig(api.pluginConfig ?? {});
  const logger = api.logger ?? consoleLogger;
  const client = new SidecarClient(config);
  const correlation = new CorrelationMap(300_000, 10_000);

  api.on("before_tool_call", async (event: unknown, context: unknown) => {
    const payload = buildToolBefore(event, config.sendRawParams);
    mergeContext(payload, context);
    payload.resource_scope = buildResourceScope(event, context);
    try {
      const decision = await client.decide(payload);
      correlation.set(payload.tool_call_id, decision.decision_id, decision.lease_id);
      if (config.mode === "enforce" && decision.action === "block") {
        return {
          block: true,
          blockReason: decision.reason
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

  api.on("after_tool_call", async (event: unknown, context: unknown) => {
    const completion = buildCompletion(event, correlation.take(extractString(event, ["tool_call_id", "toolCallId", "id"])));
    mergeContext(completion, context);
    completion.resource_scope = buildResourceScope(event, context);
    try {
      await client.reportCompletion(completion);
    } catch (error) {
      logger.warn("hardware scheduler completion report failed", classifyError(error));
    }
  });

  api.on("model_call_started", async (event: unknown, context: unknown) => {
    await reportModel(client, logger, event, "model_call_started");
  });

  api.on("model_call_ended", async (event: unknown, context: unknown) => {
    await reportModel(client, logger, event, "model_call_ended");
  });
}
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
    raw_params: sendRawParams ? safeParams : null,
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
  const command = params.command ?? params.cmd;
  if (typeof command === "string" && command.length > 0) return command;
  const nested = params.exec;
  if (isRecord(nested)) {
    const nestedCommand = nested.command ?? nested.cmd;
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
    result_size_bytes: extractNumber(event, ["result_size_bytes", "resultSizeBytes"]),
    resource_scope: null
  };
}

function buildResourceScope(event: unknown, context: unknown): ResourceScope | null {
  const pid = extractNumberDeep([event, context], [
    "pid",
    "process_id",
    "processId",
    "tool_pid",
    "toolPid",
    "child_pid",
    "childPid"
  ]);
  const processStartTime = extractFiniteNumberDeep([event, context], [
    "process_start_time",
    "processStartTime",
    "create_time",
    "createTime"
  ]);
  const containerId = extractStringDeep([event, context], ["container_id", "containerId"]);
  if (pid === null && processStartTime === null && containerId === null) return null;
  return {
    pid,
    process_start_time: processStartTime,
    container_id: containerId,
    include_children: true,
    source: "openclaw-hook"
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

function extractNumberDeep(values: unknown[], keys: string[]): number | null {
  const value = extractDeep(values, keys);
  return typeof value === "number" && Number.isFinite(value) && value >= 0 ? Math.floor(value) : null;
}

function extractFiniteNumberDeep(values: unknown[], keys: string[]): number | null {
  const value = extractDeep(values, keys);
  return typeof value === "number" && Number.isFinite(value) && value >= 0 ? value : null;
}

function extractStringDeep(values: unknown[], keys: string[]): string | null {
  const value = extractDeep(values, keys);
  return typeof value === "string" && value.length > 0 ? value : null;
}

function extractDeep(values: unknown[], keys: string[]): unknown {
  for (const value of values) {
    const found = findDeep(value, new Set(keys), 0);
    if (found !== undefined) return found;
  }
  return undefined;
}

function findDeep(value: unknown, keys: Set<string>, depth: number): unknown {
  if (!isRecord(value) || depth > 4) return undefined;
  for (const key of keys) {
    if (Object.prototype.hasOwnProperty.call(value, key)) return value[key];
  }
  for (const item of Object.values(value)) {
    if (isRecord(item)) {
      const found = findDeep(item, keys, depth + 1);
      if (found !== undefined) return found;
    }
  }
  return undefined;
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
