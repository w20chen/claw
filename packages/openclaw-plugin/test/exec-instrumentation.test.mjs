import test from "node:test";
import assert from "node:assert/strict";
import {instrumentExecParams} from "../dist/exec-instrumentation.js";

const baseConfig = {
  endpoint: "http://127.0.0.1:8765",
  mode: "observe",
  decisionTimeoutMs: 800,
  reportTimeoutMs: 800,
  failOpen: true,
  sendRawParams: false,
  authTokenEnv: "OPENCLAW_SCHEDULER_TOKEN",
  logLevel: "info",
  executionBackend: "marker",
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

const payload = {
  schema_version: "scheduler.v1",
  event_id: "evt-1",
  occurred_at: "2026-07-16T00:00:00Z",
  plugin_version: "0.1.0",
  run_id: "run-1",
  session_id: null,
  session_key: "session-secret",
  agent_id: null,
  tool_call_id: "call-1",
  tool_name: "exec",
  tool_kind: null,
  tool_input_kind: null,
  operation_hint: null,
  derived_paths: [],
  params_digest: "sha256:" + "a".repeat(64),
  param_features: {
    serialized_size_bytes: 0,
    string_length: 0,
    list_item_count: 0,
    path_count: 0,
    has_command_like_field: true
  },
  raw_params: null,
  resource_scope: null
};

const decision = {
  decision_id: "decision-1",
  action: "allow",
  reason_code: "observe_only",
  reason: "ok",
  policy_name: "observe-only",
  policy_version: "1",
  lease_id: null,
  prediction: {
    duration_p50_ms: null,
    duration_p90_ms: null,
    resource_class: "unknown",
    confidence: null
  },
  placement_advice: {
    cpu_set: null,
    numa_node: null,
    llc_cluster: null,
    advisory: true
  }
};

test("marker backend injects env without changing command", async () => {
  const seen = [];
  const client = {
    async registerExecution(request) {
      seen.push(request);
      return {one_time_token: "token-1"};
    }
  };
  const event = {toolName: "exec", toolCallId: "call-1", params: {command: "pytest tests -q", env: {KEEP: "1"}}};

  const result = await instrumentExecParams(event, {}, payload, decision, client, baseConfig);

  assert.equal(result.executionId, "call-1");
  assert.equal(result.params.command, "pytest tests -q");
  assert.equal(result.params.env.KEEP, "1");
  assert.equal(result.params.env.CLAW_EXECUTION_ID, "call-1");
  assert.equal(result.params.env.CLAW_TOOL_CALL_ID, "call-1");
  assert.equal(result.params.env.CLAW_RUN_ID, "run-1");
  assert.match(result.params.env.CLAW_COMMAND_DIGEST, /^sha256:[a-f0-9]{64}$/);
  assert.match(result.params.env.CLAW_SESSION_KEY_HASH, /^sha256:[a-f0-9]{64}$/);
  assert.equal(seen[0].command, "pytest tests -q");
});

test("managed-wrapper rewrites command to launcher token only", async () => {
  const client = {
    async registerExecution() {
      return {one_time_token: "-token-1"};
    }
  };
  const event = {toolName: "exec", toolCallId: "call-1", params: {command: "echo raw-command"}};

  const result = await instrumentExecParams(
    event,
    {},
    payload,
    decision,
    client,
    {...baseConfig, executionBackend: "managed-wrapper", securityBoundaryAccepted: true}
  );

  assert.equal(result.params.command, "'/opt/claw/bin/claw-launch' run --execution-id='call-1' --token='-token-1'");
  assert.equal(result.params.command.includes("raw-command"), false);
  assert.equal(result.params.env.CLAW_EXECUTION_ID, "call-1");
});
