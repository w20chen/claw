type Entry = {
  decisionId: string | null;
  leaseId: string | null;
  executionId: string | null;
  expiresAt: number;
};

export class CorrelationMap {
  private readonly entries = new Map<string, Entry>();

  constructor(private readonly ttlMs: number, private readonly maxEntries: number) {}

  set(toolCallId: string | null, decisionId: string | null, leaseId: string | null, executionId: string | null = null): void {
    if (!toolCallId) return;
    this.sweep();
    if (this.entries.size >= this.maxEntries) {
      const first = this.entries.keys().next().value;
      if (first) this.entries.delete(first);
    }
    this.entries.set(toolCallId, {decisionId, leaseId, executionId, expiresAt: Date.now() + this.ttlMs});
  }

  take(toolCallId: string | null): Entry | null {
    if (!toolCallId) return null;
    this.sweep();
    const entry = this.entries.get(toolCallId) ?? null;
    this.entries.delete(toolCallId);
    return entry;
  }

  clear(): void {
    this.entries.clear();
  }

  private sweep(): void {
    const now = Date.now();
    for (const [key, entry] of this.entries.entries()) {
      if (entry.expiresAt <= now) this.entries.delete(key);
    }
  }
}
