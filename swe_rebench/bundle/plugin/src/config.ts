import type {PluginConfig} from "./contracts.js";

const defaults: PluginConfig = {
  endpoint: "http://127.0.0.1:8765",
  mode: "observe",
  decisionTimeoutMs: 800,
  reportTimeoutMs: 800,
  failOpen: true,
  authTokenEnv: "OPENCLAW_SCHEDULER_TOKEN",
  logLevel: "info",
  executionBackend: "hook-only",
  launcherPath: "/opt/claw/bin/claw-launch",
  instrumentHosts: ["gateway"],
  instrumentTools: ["exec"],
  enableCgroup: true,
  profilingMode: "off",
  securityBoundaryAccepted: false,
  trace: {
    schema_version: 6,
    include_raw_events: false,
    include_llm_messages: true,
    include_tool_outputs: true,
    redact_sensitive_data: true,
    flush_span_start: true,
    max_string_bytes: 16384,
    max_messages_bytes: 131072,
    max_tool_output_bytes: 65536,
    trace_dir: "",  // disabled by default; scheduler is the primary writer
  },
};

export function loadConfig(input: unknown): PluginConfig {
  const raw = isRecord(input) ? input : {};
  const config = {...defaults, ...raw, ...envOverrides()};
  if (config.mode !== "observe" && config.mode !== "enforce") {
    throw new Error(`invalid mode: ${String(config.mode)}`);
  }
  if (!Number.isInteger(config.decisionTimeoutMs) || config.decisionTimeoutMs <= 0) {
    throw new Error("decisionTimeoutMs must be a positive integer");
  }
  if (!Number.isInteger(config.reportTimeoutMs) || config.reportTimeoutMs <= 0) {
    throw new Error("reportTimeoutMs must be a positive integer");
  }
  if (typeof config.failOpen !== "boolean") {
    throw new Error("failOpen must be a boolean");
  }
  if (!["hook-only", "marker", "managed-wrapper"].includes(String(config.executionBackend))) {
    throw new Error(`invalid executionBackend: ${String(config.executionBackend)}`);
  }
  if (!["off", "proc", "perf", "ksys", "vtune"].includes(String(config.profilingMode))) {
    throw new Error(`invalid profilingMode: ${String(config.profilingMode)}`);
  }
  if (typeof config.launcherPath !== "string" || config.launcherPath.length === 0) {
    throw new Error("launcherPath must be a non-empty string");
  }
  if (!Array.isArray(config.instrumentHosts) || !config.instrumentHosts.every((item) => typeof item === "string")) {
    throw new Error("instrumentHosts must be an array of strings");
  }
  if (!Array.isArray(config.instrumentTools) || !config.instrumentTools.every((item) => typeof item === "string")) {
    throw new Error("instrumentTools must be an array of strings");
  }
  if (config.executionBackend === "managed-wrapper" && config.securityBoundaryAccepted !== true) {
    throw new Error("managed-wrapper requires securityBoundaryAccepted=true");
  }
  return config as PluginConfig;
}

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function envOverrides(): Partial<PluginConfig> {
  const output: Partial<PluginConfig> = {};
  setString(output, "endpoint", process.env.OPENCLAW_HARDWARE_SCHEDULER_ENDPOINT);
  setString(output, "mode", process.env.OPENCLAW_HARDWARE_SCHEDULER_MODE);
  setString(output, "launcherPath", process.env.OPENCLAW_HARDWARE_SCHEDULER_LAUNCHER_PATH);
  setString(output, "executionBackend", process.env.OPENCLAW_HARDWARE_SCHEDULER_EXECUTION_BACKEND);
  setBoolean(output, "failOpen", process.env.OPENCLAW_HARDWARE_SCHEDULER_FAIL_OPEN);
  setBoolean(
    output,
    "securityBoundaryAccepted",
    process.env.OPENCLAW_HARDWARE_SCHEDULER_SECURITY_BOUNDARY_ACCEPTED
  );
  return output;
}

function setString<K extends keyof PluginConfig>(
  output: Partial<PluginConfig>,
  key: K,
  value: string | undefined
): void {
  if (value !== undefined && value.length > 0) {
    (output as Record<string, unknown>)[key] = value;
  }
}

function setBoolean<K extends keyof PluginConfig>(
  output: Partial<PluginConfig>,
  key: K,
  value: string | undefined
): void {
  if (value === undefined || value.length === 0) return;
  const normalized = value.toLowerCase();
  (output as Record<string, unknown>)[key] = ["1", "true", "yes", "on"].includes(normalized);
}
