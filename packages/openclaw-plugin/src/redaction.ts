import {createHash} from "node:crypto";
import {isRecord} from "./config.js";

const sensitive = [
  "token",
  "api_key",
  "apikey",
  "secret",
  "password",
  "passwd",
  "authorization",
  "cookie",
  "credential",
  "private_key",
  "access_key"
];

export function redact(value: unknown): unknown {
  if (Array.isArray(value)) {
    return value.map((item) => redact(item));
  }
  if (!isRecord(value)) {
    return value;
  }
  const output: Record<string, unknown> = {};
  for (const [key, child] of Object.entries(value)) {
    const lower = key.toLowerCase();
    output[key] = sensitive.some((needle) => lower.includes(needle)) ? "[REDACTED]" : redact(child);
  }
  return output;
}

export function stableDigest(value: unknown): string {
  return `sha256:${createHash("sha256").update(stableStringify(value)).digest("hex")}`;
}

export function paramFeatures(value: unknown): {
  serialized_size_bytes: number;
  string_length: number;
  list_item_count: number;
  path_count: number;
  has_command_like_field: boolean;
} {
  const text = stableStringify(value);
  let stringLength = 0;
  let listItems = 0;
  let pathCount = 0;
  let commandLike = false;
  walk(value, (key, item) => {
    if (typeof item === "string") {
      stringLength += item.length;
      if (/[A-Za-z]:\\|\/[A-Za-z0-9_.-]/.test(item)) pathCount += 1;
    }
    if (Array.isArray(item)) listItems += item.length;
    if (key && ["cmd", "command", "script", "shell"].includes(key.toLowerCase())) commandLike = true;
  });
  return {
    serialized_size_bytes: Buffer.byteLength(text),
    string_length: stringLength,
    list_item_count: listItems,
    path_count: pathCount,
    has_command_like_field: commandLike
  };
}

function stableStringify(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map((item) => stableStringify(item)).join(",")}]`;
  if (isRecord(value)) {
    return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${stableStringify(value[key])}`).join(",")}}`;
  }
  return JSON.stringify(value);
}

function walk(value: unknown, fn: (key: string | null, value: unknown) => void, key: string | null = null): void {
  fn(key, value);
  if (Array.isArray(value)) {
    for (const item of value) walk(item, fn, null);
  } else if (isRecord(value)) {
    for (const [childKey, child] of Object.entries(value)) walk(child, fn, childKey);
  }
}
