export type SandboxPathEnv = {
  hostWorkspace?: string;
  containerWorkspace?: string;
  execWorkdir?: string;
};

export function normalizeSandboxToolParams(
  params: Record<string, unknown> | null,
  toolName: string,
  env: SandboxPathEnv = {
    hostWorkspace: process.env.CLAW_SANDBOX_HOST_WORKSPACE,
    containerWorkspace: process.env.CLAW_SANDBOX_CONTAINER_WORKSPACE,
    execWorkdir: process.env.CLAW_EXEC_WORKDIR,
  }
): {params: Record<string, unknown> | null; changed: boolean} {
  if (params === null) return {params: null, changed: false};
  const hostWorkspace = normalizePathEnv(env.hostWorkspace);
  const containerWorkspace = normalizePathEnv(env.containerWorkspace)
    ?? normalizePathEnv(env.execWorkdir)
    ?? "/workspace";
  if (hostWorkspace === null) return {params, changed: false};
  const targetWorkspace = usesContainerWorkspace(toolName) ? containerWorkspace : null;

  let changed = false;
  const normalized = rewritePathFields(params, hostWorkspace, targetWorkspace, (didChange) => {
    changed = changed || didChange;
  });

  if (toolName === "exec") {
    if (normalized.host === "gateway") {
      delete normalized.host;
      changed = true;
    }
    if (normalized.elevated === true) {
      delete normalized.elevated;
      changed = true;
    }
    if (typeof normalized.workdir === "string") {
      const mapped = mapHostWorkspacePath(normalized.workdir, hostWorkspace, containerWorkspace);
      if (mapped !== normalized.workdir) {
        normalized.workdir = mapped;
        changed = true;
      }
    }
  }

  return {params: normalized, changed};
}

function rewritePathFields(
  value: Record<string, unknown>,
  hostWorkspace: string,
  targetWorkspace: string | null,
  markChanged: (changed: boolean) => void
): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [key, item] of Object.entries(value)) {
    if (typeof item === "string" && isPathLikeKey(key)) {
      const mapped = mapHostWorkspacePath(item, hostWorkspace, targetWorkspace);
      out[key] = mapped;
      markChanged(mapped !== item);
      continue;
    }
    if (isPlainRecord(item)) {
      out[key] = rewritePathFields(item as Record<string, unknown>, hostWorkspace, targetWorkspace, markChanged);
      continue;
    }
    if (Array.isArray(item)) {
      out[key] = item.map((entry) => {
        if (isPlainRecord(entry)) {
          return rewritePathFields(entry as Record<string, unknown>, hostWorkspace, targetWorkspace, markChanged);
        }
        return entry;
      });
      continue;
    }
    out[key] = item;
  }
  return out;
}

function isPathLikeKey(key: string): boolean {
  const normalized = key.toLowerCase();
  return [
    "path",
    "file",
    "filename",
    "filepath",
    "target",
    "source",
    "destination",
    "dest",
    "cwd",
    "workdir",
    "workingdirectory",
  ].includes(normalized);
}

function mapHostWorkspacePath(value: string, hostWorkspace: string, targetWorkspace: string | null): string {
  const normalized = normalizePathString(value);
  if (normalized === hostWorkspace) return targetWorkspace ?? ".";
  if (normalized.startsWith(`${hostWorkspace}/`)) {
    const suffix = normalized.slice(hostWorkspace.length + 1);
    return targetWorkspace === null ? suffix : `${targetWorkspace}/${suffix}`;
  }
  return value;
}

function usesContainerWorkspace(toolName: string): boolean {
  return toolName === "exec" || toolName === "process";
}

function normalizePathEnv(value: string | undefined): string | null {
  if (typeof value !== "string" || value.length === 0) return null;
  return normalizePathString(value).replace(/\/+$/g, "") || "/";
}

function normalizePathString(value: string): string {
  return value.replace(/\\/g, "/").replace(/\/+/g, "/").replace(/\/+$/g, "") || "/";
}

function isPlainRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
