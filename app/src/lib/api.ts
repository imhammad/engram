import { invoke } from "@tauri-apps/api/core";

// The engine listens on a random loopback port with a per-launch token,
// both chosen by the Rust shell. Every request goes through api() so the
// token is always attached (see docs/decisions/0005).

type EngineConnection = { baseUrl: string; token: string };

let connection: Promise<EngineConnection> | null = null;

function getConnection(): Promise<EngineConnection> {
  if (!connection) {
    connection = invoke<EngineConnection>("engine_connection").catch((err) => {
      connection = null; // retry on the next call
      throw err;
    });
  }
  return connection;
}

export async function api<T = unknown>(
  path: string,
  init: { method?: string; body?: unknown } = {},
): Promise<T> {
  const { baseUrl, token } = await getConnection();
  const headers: Record<string, string> = { "X-Engram-Token": token };
  if (init.body !== undefined) headers["Content-Type"] = "application/json";
  const res = await fetch(`${baseUrl}${path}`, {
    method: init.method ?? "GET",
    headers,
    body: init.body === undefined ? undefined : JSON.stringify(init.body),
  });
  if (!res.ok) {
    throw new Error(`Engine request failed (${res.status})`);
  }
  return (await res.json()) as T;
}

/** POST and read a newline-delimited JSON stream, one callback per event. */
export async function apiStream<E = unknown>(
  path: string,
  body: unknown,
  onEvent: (event: E) => void,
): Promise<void> {
  const { baseUrl, token } = await getConnection();
  const res = await fetch(`${baseUrl}${path}`, {
    method: "POST",
    headers: { "X-Engram-Token": token, "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok || !res.body) {
    throw new Error(`Engine request failed (${res.status})`);
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let newline = buffer.indexOf("\n");
    while (newline >= 0) {
      const line = buffer.slice(0, newline).trim();
      buffer = buffer.slice(newline + 1);
      if (line) onEvent(JSON.parse(line) as E);
      newline = buffer.indexOf("\n");
    }
  }
  if (buffer.trim()) onEvent(JSON.parse(buffer) as E);
}
