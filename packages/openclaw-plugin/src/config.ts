import type {PluginConfig} from "./contracts.js";

const defaults: PluginConfig = {
  endpoint: "http://127.0.0.1:8765",
  mode: "observe",
  decisionTimeoutMs: 800,
  reportTimeoutMs: 800,
  failOpen: true,
  sendRawParams: false,
  authTokenEnv: "OPENCLAW_SCHEDULER_TOKEN",
  logLevel: "info"
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
  return config as PluginConfig;
}

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
