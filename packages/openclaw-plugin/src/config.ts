import type {PluginConfig} from "./contracts.js";

const defaults: PluginConfig = {
  endpoint: "http://127.0.0.1:8765",
  mode: "observe",
  decisionTimeoutMs: 800,
  reportTimeoutMs: 800,
  failOpen: true,
  sendRawParams: false,
  authTokenEnv: "OPENCLAW_SCHEDULER_TOKEN",
  logLevel: "info",
  executionBackend: "hook-only",
  launcherPath: "/opt/claw/bin/claw-launch",
  collectorSocket: "/run/claw/collector.sock",
  instrumentHosts: ["gateway"],
  instrumentTools: ["exec"],
  enableCgroup: true,
  enableAffinity: true,
  enableNuma: true,
  profilingMode: "off",
  securityBoundaryAccepted: false
};

export function loadConfig(input: unknown): PluginConfig {
  const raw = isRecord(input) ? input : {};
  const config = {...defaults, ...raw};
  if (config.mode !== "observe" && config.mode !== "enforce") {
    throw new Error(`invalid mode: ${String(config.mode)}`);
  }
  if (!Number.isInteger(config.decisionTimeoutMs) || config.decisionTimeoutMs <= 0) {
    throw new Error("decisionTimeoutMs must be a positive integer");
  }
  if (!Number.isInteger(config.reportTimeoutMs) || config.reportTimeoutMs <= 0) {
    throw new Error("reportTimeoutMs must be a positive integer");
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
  if (typeof config.collectorSocket !== "string" || config.collectorSocket.length === 0) {
    throw new Error("collectorSocket must be a non-empty string");
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
