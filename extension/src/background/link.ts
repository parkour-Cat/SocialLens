// The link to the backend: config, the WebSocket (connect, reconnect with backoff), sending,
// and log lines mirrored into the backend log. Incoming messages go to the handler index.ts
// registers; "hello" also updates the connection state here.

import { pagePlatformActions } from "../page/platforms/catalog";
import { log, setVerbose } from "../shared/log";
import type { BackendToExt, ExtToBackend } from "../shared/messages";
import { VERSION } from "./env";

export const DEFAULT_BACKEND = "ws://127.0.0.1:17800/ws/extension";
const RECONNECT_MAX_MS = 30_000;

// ---- config -------------------------------------------------------------------

export interface Config {
  backendUrl: string;
  token: string;
  verbose: boolean;
}

export async function loadConfig(): Promise<Config> {
  const s = await chrome.storage.local.get(["backendUrl", "token", "verbose"]);
  const cfg = {
    backendUrl: (s.backendUrl as string) || DEFAULT_BACKEND,
    token: (s.token as string) || "",
    verbose: Boolean(s.verbose),
  };
  setVerbose(cfg.verbose);
  return cfg;
}

// ---- connection state -----------------------------------------------------------

let ws: WebSocket | null = null;
let connected = false;
let backendVersion: string | null = null;
let lastError: string | null = null;
let reconnectDelay = 1000;
let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
let currentConfig: Config | null = null;

let onMessage: (msg: BackendToExt) => void | Promise<void> = () => {};
let onClosed: () => void = () => {};

/** Who handles backend messages (index.ts). */
export function onBackendMessage(handler: (msg: BackendToExt) => void | Promise<void>): void {
  onMessage = handler;
}

/** Called when the socket closes, e.g. to fail tasks waiting on a page (execute.ts). */
export function onBackendClosed(handler: () => void): void {
  onClosed = handler;
}

export function linkState(): { connected: boolean; backendVersion: string | null; lastError: string | null; config: Config | null } {
  return { connected, backendVersion, lastError, config: currentConfig };
}

export function wsSend(msg: ExtToBackend): void {
  if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(msg));
}

export function remoteLog(level: "debug" | "info" | "warning" | "error", msg: string, fields: Record<string, unknown> = {}): void {
  wsSend({ type: "log", level, msg, ...fields });
}

let connecting: Promise<void> | null = null;

/** Idempotent: concurrent callers share one attempt; a live socket is never duplicated. */
export function connect(): Promise<void> {
  if (connecting) return connecting;
  if (ws && (ws.readyState === WebSocket.CONNECTING || ws.readyState === WebSocket.OPEN)) return Promise.resolve();
  connecting = doConnect().finally(() => {
    connecting = null;
  });
  return connecting;
}

async function doConnect(): Promise<void> {
  if (reconnectTimer) {
    clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }
  // No token is needed in the normal case: the backend recognises this extension by the
  // Origin header (chrome-extension://<fixed id>). A token is only a fallback.
  currentConfig = await loadConfig();
  log.info("connecting", currentConfig.backendUrl);
  let socket: WebSocket;
  try {
    socket = new WebSocket(currentConfig.backendUrl);
  } catch (e) {
    lastError = `bad backend url: ${String(e)}`;
    scheduleReconnect();
    return;
  }
  ws = socket;
  socket.onopen = () => {
    if (ws !== socket) return;
    wsSend({ type: "auth", token: currentConfig!.token, extension_version: VERSION, actions: pagePlatformActions() });
  };
  socket.onmessage = (ev) => {
    if (ws !== socket) return; // stale socket
    let msg: BackendToExt;
    try {
      msg = JSON.parse(String(ev.data));
    } catch {
      return;
    }
    if (msg.type === "hello") {
      connected = true;
      backendVersion = msg.backend_version;
      lastError = null;
      reconnectDelay = 1000;
      log.info("connected to backend", msg.backend_version);
    }
    void onMessage(msg);
  };
  socket.onerror = () => {
    if (ws === socket) lastError = "connection error (is the backend running?)";
  };
  socket.onclose = (ev) => {
    if (ws !== socket) return; // a newer socket owns the state; nothing to do
    ws = null;
    const wasConnected = connected;
    connected = false;
    backendVersion = null;
    if (ev.code === 4003) lastError = "backend rejected this extension (unexpected extension id and no valid token)";
    else if (ev.code !== 1000) lastError = ev.reason || `closed (${ev.code})`;
    onClosed();
    if (wasConnected) log.warn("disconnected", ev.code, ev.reason);
    if (ev.code !== 4003) scheduleReconnect();
  };
}

function scheduleReconnect(): void {
  if (reconnectTimer) return;
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    void connect();
  }, reconnectDelay);
  reconnectDelay = Math.min(reconnectDelay * 2, RECONNECT_MAX_MS);
}

/** Drop the current socket and connect again now, with the backoff reset (config change, popup, dev hook). */
export function reconnectNow(reason: string): Promise<void> {
  reconnectDelay = 1000;
  if (ws) ws.close(1000, reason);
  return connect();
}

/** ws://host:port/ws/extension -> http://host:port */
export function httpBase(wsUrl: string): string {
  try {
    const u = new URL(wsUrl);
    return `${u.protocol === "wss:" ? "https" : "http"}://${u.host}`;
  } catch {
    return "http://127.0.0.1:17800";
  }
}
