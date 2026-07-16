import type {PluginConfig, ToolBeforeRequest, ToolCompletedEvent, ToolDecision} from "./contracts.js";

export class SidecarClient {
  constructor(private readonly config: PluginConfig) {}

  async decide(payload: ToolBeforeRequest): Promise<ToolDecision> {
    return this.post<ToolDecision>("/v1/decisions/tool", payload, this.config.decisionTimeoutMs);
  }

  async reportCompletion(payload: ToolCompletedEvent): Promise<void> {
    await this.post<unknown>("/v1/events/tool-completed", payload, this.config.reportTimeoutMs);
  }

  async reportModel(payload: unknown): Promise<void> {
    await this.post<unknown>("/v1/events/model", payload, this.config.reportTimeoutMs);
  }

  private async post<T>(path: string, payload: unknown, timeoutMs: number): Promise<T> {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const headers: Record<string, string> = {"content-type": "application/json"};
      const token = process.env[this.config.authTokenEnv];
      if (token) headers.authorization = `Bearer ${token}`;
      const response = await fetch(`${this.config.endpoint}${path}`, {
        method: "POST",
        headers,
        body: JSON.stringify(payload),
        signal: controller.signal
      });
      if (!response.ok) {
        throw new Error(`sidecar_http_${response.status}`);
      }
      return (await response.json()) as T;
    } finally {
      clearTimeout(timeout);
    }
  }
}
