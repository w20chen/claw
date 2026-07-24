import test from "node:test";
import assert from "node:assert/strict";
import {loadConfig} from "../dist/config.js";

test("loadConfig deep-merges partial trace config", () => {
  const config = loadConfig({
    trace: {
      trace_dir: "/tmp/openclaw-traces",
    },
  });

  assert.equal(config.trace.trace_dir, "/tmp/openclaw-traces");
  assert.equal(config.trace.schema_version, 6);
  assert.equal(config.trace.include_llm_messages, true);
  assert.equal(config.trace.include_tool_outputs, true);
});

test("loadConfig maps legacy recordRawTrace to trace capture switches", () => {
  const config = loadConfig({
    recordRawTrace: true,
  });

  assert.equal(config.recordRawTrace, true);
  assert.equal(config.trace.include_raw_events, true);
  assert.equal(config.trace.include_llm_messages, true);
  assert.equal(config.trace.include_tool_outputs, true);
});

test("loadConfig keeps execution placement toggles configurable", () => {
  const config = loadConfig({
    enableCgroup: false,
    enableAffinity: false,
    enableNuma: false,
  });

  assert.equal(config.enableCgroup, false);
  assert.equal(config.enableAffinity, false);
  assert.equal(config.enableNuma, false);
});
