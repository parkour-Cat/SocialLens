// Message contracts for the three hops: backend <-> background, background <-> content, content <-> page.

export type Strategy = "call" | "navigate";

export interface TaskSpec {
  id: string;
  platform: string;
  action: string;
  params: Record<string, unknown>;
  strategy: Strategy;
  timeout_ms: number;
}

export interface TaskError {
  code: string;
  message: string;
  details?: Record<string, unknown>;
}

// ---- backend <-> background (WebSocket) ----------------------------------

export type BackendToExt =
  | { type: "hello"; heartbeat_s: number; backend_version: string }
  | ({ type: "task.dispatch" } & TaskSpec)
  | { type: "task.cancel"; id: string }
  | { type: "record.set"; platform: string; enabled: boolean }
  | { type: "ping"; ts: number };

export type ExtToBackend =
  | { type: "auth"; token: string; extension_version: string; actions: Record<string, string[]> } // token may be "" when the Origin check applies; actions = page actions per platform this build supports
  | { type: "task.result"; id: string; ok: true; payload: unknown }
  | { type: "task.result"; id: string; ok: false; error: TaskError }
  | ({ type: "capture"; platform: string; task_id?: string } & Capture)
  | { type: "tab.state"; platform: string; logged_in: boolean; tab_ids: number[] }
  | { type: "pong"; ts: number }
  | { type: "log"; level: "debug" | "info" | "warning" | "error"; msg: string; [k: string]: unknown };

// ---- captured responses ---------------------------------------------------

export interface Capture {
  url: string;
  method: string;
  status: number;
  content_type: string | null;
  body: unknown; // parsed JSON when possible, else text
  truncated: boolean;
  request_headers?: Record<string, string>; // headers the page set on its own request (fetch init / XHR setRequestHeader)
  request_body?: string; // first 4 KB of the request body (GraphQL operationName lives here)
  ts: number;
  kind: "fetch" | "xhr" | "global" | "worker"; // worker = a message a Web Worker posted to the page (TikTok loads comments that way)
}

// ---- background <-> content (chrome.runtime messages) --------------------

export type BgToContent =
  | { type: "task.execute"; task: TaskSpec }
  | { type: "task.cancel"; id: string }
  | { type: "capture.config"; enabled: boolean };

export type ContentToBg =
  | { type: "content.ready"; url: string }
  | { type: "page.task.result"; id: string; ok: boolean; payload?: unknown; error?: TaskError; build?: string } // build: page script build that answered
  | ({ type: "page.capture" } & Capture)
  | { type: "page.log"; level: string; msg: string; data?: unknown };

// ---- popup <-> background ------------------------------------------------

export interface ExtStatus {
  connected: boolean;
  backendUrl: string;
  hasToken: boolean;
  backendVersion: string | null;
  lastError: string | null;
  platforms: Record<string, { name: string; logged_in: boolean; tab_ids: number[]; recording: boolean; login_url: string; login_hint: string }>;
  pendingTasks: number;
  /** The platform of the tab the user is looking at, if it is one we support. */
  currentTab: { platform: string; name: string; logged_in: boolean; login_required: boolean } | null;
  /** Platform queues the backend paused (captcha / rate limit) that need the user. */
  alerts: { platform: string; name: string; paused_for_s: number }[];
  build: string;
}

export type PopupToBg =
  | { type: "popup.status" }
  | { type: "popup.save"; backendUrl: string; token: string }
  | { type: "popup.reconnect" }
  | { type: "popup.resume"; platform: string };

// ---- content <-> page (window.postMessage) --------------------------------

export const PAGE_CHANNEL = "__sociallens__";

export interface PageEnvelope {
  [PAGE_CHANNEL]: true;
  dir: "to-page" | "from-page";
  msg: BgToContent | ContentToBg;
}

export function isEnvelope(v: unknown): v is PageEnvelope {
  return !!v && typeof v === "object" && (v as Record<string, unknown>)[PAGE_CHANNEL] === true;
}
