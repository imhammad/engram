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
