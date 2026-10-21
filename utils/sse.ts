export interface SseEvent {
  event?: string;
  text?: string;
  answer?: string;
  detail?: string;
  sources?: unknown[];
  cached?: boolean;
  query_plan?: Record<string, unknown>;
  images?: unknown[];
  structured?: unknown[];
  context?: string;
  flow?: Record<string, Record<string, unknown>>;
  llm_skipped?: boolean;
  request_id?: string;
}

export function consumeSseFrames(buffer: string): { events: SseEvent[]; rest: string } {
  const events: SseEvent[] = [];
  let rest = buffer;
  while (rest.length > 0) {
    const splitAt = rest.indexOf("\n\n");
    if (splitAt === -1) break;
    const frame = rest.slice(0, splitAt);
    rest = rest.slice(splitAt + 2);
    const payload = frame
      .split("\n")
      .filter((line) => line.startsWith("data:"))
      .map((line) => line.slice(5).replace(/^ /, ""))
      .join("\n");
    if (!payload) continue;
    try {
      events.push(JSON.parse(payload) as SseEvent);
    } catch {
      // Drop a malformed frame and keep reading.
    }
  }
  return { events, rest };
}

export function flushSseBuffer(buffer: string): SseEvent[] {
  if (!buffer.trim()) return [];
  return consumeSseFrames(`${buffer}\n\n`).events;
}
