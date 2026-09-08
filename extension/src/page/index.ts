// MAIN-world page script. Runs at document_start inside platform sites.
// 1. Hooks fetch/XHR so responses can be captured (ring buffer always; forwarded only when enabled).
// 2. Executes generic actions sent by the background (echo, fetch, wait_capture, read_global)
//    and platform actions registered under src/page/platforms/.

import {
  PAGE_CHANNEL,
  isEnvelope,
  type BgToContent,
  type Capture,
  type ContentToBg,
  type TaskError,
  type TaskSpec,
} from "../shared/messages";
import { PageError } from "./errors";
import { currentPagePlatform, platformAction } from "./platforms";

// Re-injection after an extension reload must not install the same build twice: the whole
// script body lives in installSocialLens(), which runs once per document *per build*. A newer
// build installs alongside an older one (the old hooks cannot be removed); the background only
// routes tasks to documents whose page build matches its own, so the old listener is idle.
declare const __BUILD_ID__: string;
const BUILD = typeof __BUILD_ID__ === "string" ? __BUILD_ID__ : "dev";
const MARK = "__sociallens_page__";

// 抖音 feed / search responses run past 1 MB; the backend WebSocket accepts up to 16 MB.
function installSocialLens(): void {
const MAX_BODY_CHARS = 6_000_000;
const RING_SIZE = 200;
const ORIGIN = location.origin;

function toError(e: unknown): TaskError {
  if (e instanceof PageError) return { code: e.code, message: e.message, details: e.details };
  return { code: "extension_error", message: e instanceof Error ? e.message : String(e) };
}

// ---- state ------------------------------------------------------------------

let captureEnabled = false;
const ring: Capture[] = [];
const waiters: { test: (c: Capture) => boolean; resolve: (c: Capture) => void }[] = [];
const cancelled = new Set<string>();

function post(msg: ContentToBg): void {
  window.postMessage({ [PAGE_CHANNEL]: true, dir: "from-page", msg }, ORIGIN);
}

function plog(level: string, msg: string, data?: unknown): void {
  post({ type: "page.log", level, msg, data });
}

function record(c: Capture): void {
  // status 0 = aborted / network-failed / CORS-blocked request: nothing usable, and it must not
  // satisfy a waiter (sites often cancel a duplicate request right before the real one).
  if (c.status === 0) return;
  ring.push(c);
  if (ring.length > RING_SIZE) ring.shift();
  for (let i = waiters.length - 1; i >= 0; i--) {
    if (waiters[i].test(c)) {
      const w = waiters.splice(i, 1)[0];
      w.resolve(c);
    }
  }
  if (captureEnabled) post({ type: "page.capture", ...c });
}

// ---- capture helpers -----------------------------------------------------------

function wantsCapture(contentType: string | null): boolean {
  if (!contentType) return true;
  const ct = contentType.toLowerCase();
  // text/x-component: React Server Components payloads (LinkedIn flagship-web)
  return ct.includes("json") || ct.includes("text/plain") || ct.includes("xml") || ct.includes("javascript") || ct.includes("x-component");
}

function parseBody(text: string, contentType: string | null): { body: unknown; truncated: boolean } {
  const truncated = text.length > MAX_BODY_CHARS;
  const slice = truncated ? text.slice(0, MAX_BODY_CHARS) : text;
  const looksJson = (contentType ?? "").includes("json") || /^\s*[[{]/.test(slice);
  if (looksJson && !truncated) {
    try {
      return { body: JSON.parse(slice), truncated };
    } catch {
      /* fall through */
    }
  }
  return { body: slice, truncated };
}

function absolute(url: string): string {
  try {
    return new URL(url, location.href).href;
  } catch {
    return url;
  }
}

// ---- fetch hook ----------------------------------------------------------------

const originalFetch = window.fetch.bind(window);

window.fetch = async function hookedFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const res = await originalFetch(input, init);
  try {
    const url = absolute(typeof input === "string" ? input : input instanceof Request ? input.url : String(input));
    const method = (init?.method ?? (input instanceof Request ? input.method : "GET")).toUpperCase();
    const contentType = res.headers.get("content-type");
    const reqHeaders = headersToObject(init?.headers ?? (input instanceof Request ? input.headers : undefined));
    const reqBody = bodyPreview(init?.body);
    if (wantsCapture(contentType)) {
      res
        .clone()
        .text()
        .then((text) => {
          const { body, truncated } = parseBody(text, contentType);
          record({ url, method, status: res.status, content_type: contentType, body, truncated, ts: Date.now(), kind: "fetch", request_headers: reqHeaders, request_body: reqBody });
        })
        .catch(() => {});
    } else if (url.includes("/api/") || url.includes("/flagship-web/")) {
      // LinkedIn flagship-web answers React Server Component streams as application/octet-stream
      // Binary API answers (gzip bytes, octet-stream): decode what can be decoded, else keep the
      // url visible as a capture with an empty body so that waits and probes still see the request.
      res
        .clone()
        .arrayBuffer()
        .then(async (buf) => {
          const text = await bytesToText(buf).catch(() => null);
          const parsed = text ? parseBody(text, "application/json") : { body: null, truncated: false };
          record({ url: text ? url : `${url}#binary`, method, status: res.status, content_type: contentType, ...parsed, ts: Date.now(), kind: "fetch", request_headers: reqHeaders, request_body: reqBody });
        })
        .catch(() => {});
    } else {
      // Not a data response (html, images, streams): keep only the url so probes show what the page asked for.
      record({ url: `${url}#skipped`, method, status: res.status, content_type: contentType, body: null, truncated: false, ts: Date.now(), kind: "fetch", request_headers: reqHeaders, request_body: reqBody });
    }
  } catch {
    /* never break the page */
  }
  return res;
};

// ---- XHR hook ------------------------------------------------------------------

const MAX_REQ_BODY = 4096;

function bodyPreview(b: unknown): string | undefined {
  if (b == null) return undefined;
  if (typeof b === "string") return b.slice(0, MAX_REQ_BODY);
  if (b instanceof URLSearchParams) return b.toString().slice(0, MAX_REQ_BODY);
  if (b instanceof FormData) return [...b.entries()].map(([k, v]) => `${k}=${typeof v === "string" ? v : "[file]"}`).join("&").slice(0, MAX_REQ_BODY);
  return undefined; // binary bodies are not interesting here
}

function headersToObject(h: HeadersInit | undefined): Record<string, string> {
  const out: Record<string, string> = {};
  if (!h) return out;
  if (h instanceof Headers) h.forEach((v, k) => (out[k] = v));
  else if (Array.isArray(h)) h.forEach(([k, v]) => (out[k.toLowerCase()] = v));
  else Object.entries(h).forEach(([k, v]) => (out[k.toLowerCase()] = String(v)));
  return out;
}

const xhrOpen = XMLHttpRequest.prototype.open;
const xhrSend = XMLHttpRequest.prototype.send;
const xhrSetHeader = XMLHttpRequest.prototype.setRequestHeader;
const xhrMeta = new WeakMap<XMLHttpRequest, { method: string; url: string; headers: Record<string, string> }>();

XMLHttpRequest.prototype.open = function (this: XMLHttpRequest, method: string, url: string | URL, ...rest: unknown[]) {
  xhrMeta.set(this, { method: String(method).toUpperCase(), url: absolute(String(url)), headers: {} });
  // @ts-expect-error variadic passthrough
  return xhrOpen.call(this, method, url, ...rest);
};

XMLHttpRequest.prototype.setRequestHeader = function (this: XMLHttpRequest, name: string, value: string) {
  const meta = xhrMeta.get(this);
  if (meta) meta.headers[name.toLowerCase()] = value;
  return xhrSetHeader.call(this, name, value);
};

XMLHttpRequest.prototype.send = function (this: XMLHttpRequest, body?: Document | XMLHttpRequestBodyInit | null) {
  const reqBody = bodyPreview(body);
  this.addEventListener("loadend", () => {
    try {
      const meta = xhrMeta.get(this);
      if (!meta) return;
      const contentType = this.getResponseHeader("content-type");
      let text: string | null = null;
      if (this.responseType === "" || this.responseType === "text") text = wantsCapture(contentType) ? this.responseText : null;
      else if (this.responseType === "json") text = JSON.stringify(this.response);
      else if (this.responseType === "arraybuffer" && this.response instanceof ArrayBuffer) {
        // binary XHR (gzip / encrypted JSON): decode asynchronously, keep the url visible either way
        void bytesToText(this.response).then((t) => {
          const parsed = t ? parseBody(t, "application/json") : { body: null, truncated: false };
          record({ method: meta.method, url: t ? meta.url : `${meta.url}#binary`, request_headers: meta.headers, request_body: reqBody, status: this.status, content_type: contentType, ...parsed, ts: Date.now(), kind: "xhr" });
        }).catch(() => {});
        return;
      } else if (this.responseType === "blob" && this.response instanceof Blob) {
        // LinkedIn's classic app reads voyager JSON through blob XHRs: decode like arraybuffer
        void this.response.arrayBuffer().then(async (buf) => {
          const t = await bytesToText(buf).catch(() => null);
          const parsed = t ? parseBody(t, contentType) : { body: null, truncated: false };
          record({ method: meta.method, url: t ? meta.url : `${meta.url}#binary`, request_headers: meta.headers, request_body: reqBody, status: this.status, content_type: contentType, ...parsed, ts: Date.now(), kind: "xhr" });
        }).catch(() => {});
        return;
      }
      if (text == null) {
        record({ method: meta.method, url: `${meta.url}#skipped`, request_headers: meta.headers, request_body: reqBody, status: this.status, content_type: contentType, body: null, truncated: false, ts: Date.now(), kind: "xhr" });
        return;
      }
      const parsed = parseBody(text, contentType);
      record({ method: meta.method, url: meta.url, request_headers: meta.headers, request_body: reqBody, status: this.status, content_type: contentType, ...parsed, ts: Date.now(), kind: "xhr" });
    } catch {
      /* ignore */
    }
  });
  return xhrSend.call(this, body);
};

// ---- Web Worker messages -------------------------------------------------------------------
// Some sites fetch inside a Worker (TikTok: comments), invisible to the fetch/XHR hooks above.
// Messages the worker posts back to the page are recorded as captures with a "worker://" url,
// so wait_capture / scroll_capture patterns like `worker:// @@ /"comments":/` work on them.
/** Bytes a worker posted back (知乎 hands gzip-compressed JSON to the page this way) -> text. */
async function bytesToText(d: unknown): Promise<string | null> {
  let bytes: Uint8Array | null = null;
  if (d instanceof ArrayBuffer) bytes = new Uint8Array(d);
  else if (ArrayBuffer.isView(d)) bytes = new Uint8Array(d.buffer, d.byteOffset, d.byteLength);
  else if (d && typeof d === "object" && !Array.isArray(d) && "0" in (d as object) && typeof (d as Record<string, unknown>)[0] === "number") {
    const o = d as Record<string, number>;
    const n = Object.keys(o).length;
    bytes = new Uint8Array(n);
    for (let i = 0; i < n; i++) bytes[i] = o[i];
  }
  if (!bytes || bytes.length < 20) return null;
  if (bytes[0] === 0x1f && bytes[1] === 0x8b && typeof DecompressionStream === "function") {
    const stream = new Blob([bytes.slice() as unknown as BlobPart]).stream().pipeThrough(new DecompressionStream("gzip"));
    return await new Response(stream).text();
  }
  // Plain text (JSON, or line-oriented streams such as React Server Components): keep whatever
  // decodes as UTF-8 without control bytes; real binary (media, protobuf) stays out.
  let text: string;
  try {
    text = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
  } catch {
    return null;
  }
  // eslint-disable-next-line no-control-regex
  return /[\x00-\x08\x0e-\x1f]/.test(text.slice(0, 2000)) ? null : text;
}

async function recordWorkerMessage(name: string, d: unknown): Promise<void> {
  try {
    let text: string | null = typeof d === "string" ? d : null;
    let gz = false;
    if (text == null) {
      const decoded = await bytesToText(d);
      if (decoded != null) {
        text = decoded;
        gz = true;
      } else if (d && typeof d === "object") text = JSON.stringify(d);
    }
    // Media pipelines post whole segments as byte objects (LinkedIn's video probes are ~2 MB each):
    // they would evict every real capture from the ring, so anything that large is dropped.
    if (!text || text.length < 100 || text.length > 256_000 || !/^\s*[[{]/.test(text)) return;
    const parsed = parseBody(text, "application/json");
    record({ method: "MESSAGE", url: `worker://${name}${gz ? "#bytes" : ""}`, request_body: text.slice(0, 4000), status: 200, content_type: "application/json", ...parsed, ts: Date.now(), kind: "worker" });
  } catch {
    /* non-serialisable message (transferables, cycles): not data we want */
  }
}

// Data handed over through MessageChannel ports (a worker replying on a transferred port never
// fires the worker's own "message" event): listen on both ports of every channel the page creates.
const NativeMessageChannel = window.MessageChannel;
if (NativeMessageChannel) {
  window.MessageChannel = class SocialLensMessageChannel extends NativeMessageChannel {
    constructor() {
      super();
      for (const port of [this.port1, this.port2]) port.addEventListener("message", (e: MessageEvent) => void recordWorkerMessage("port", e.data));
    }
  } as typeof MessageChannel;
}

const NativeWorker = window.Worker;
if (NativeWorker) {
  window.Worker = class SocialLensWorker extends NativeWorker {
    constructor(scriptURL: string | URL, options?: WorkerOptions) {
      super(scriptURL, options);
      const name = String(scriptURL).split("?")[0].slice(-120);
      this.addEventListener("message", (e: MessageEvent) => {
        void recordWorkerMessage(name, e.data);
      });
    }
  } as typeof Worker;
}

// ---- actions -------------------------------------------------------------------

type Params = Record<string, unknown>;

function str(p: Params, key: string, required = false): string | undefined {
  const v = p[key];
  if (v == null) {
    if (required) throw new PageError("bad_request", `missing param: ${key}`);
    return undefined;
  }
  return String(v);
}

async function actionEcho(p: Params): Promise<unknown> {
  return {
    echo: p.payload ?? null,
    via: "page",
    url: location.href,
    title: document.title,
    ready_state: document.readyState,
    ua: navigator.userAgent,
  };
}

async function actionFetch(p: Params): Promise<unknown> {
  const url = absolute(str(p, "url", true)!);
  const method = (str(p, "method") ?? "GET").toUpperCase();
  const headers = (p.headers as Record<string, string> | undefined) ?? {};
  let body: BodyInit | undefined;
  if (p.body != null) {
    body = typeof p.body === "string" ? p.body : JSON.stringify(p.body);
    if (typeof p.body !== "string" && !Object.keys(headers).some((h) => h.toLowerCase() === "content-type")) {
      headers["content-type"] = "application/json";
    }
  }
  // Goes through the hooked fetch on purpose so the response also lands in the ring buffer
  // and, in record mode, in the raw archive.
  const res = await window.fetch(url, { method, headers, body, credentials: "include" });
  const contentType = res.headers.get("content-type");
  const text = await res.text();
  const want = str(p, "response") ?? "auto";
  const parsed = want === "text" ? { body: text, truncated: false } : parseBody(text, contentType);
  const resHeaders: Record<string, string> = {};
  res.headers.forEach((v, k) => (resHeaders[k] = v));
  return { status: res.status, url: res.url, headers: resHeaders, ...parsed };
}

/** `/regex/flags` is a regular expression; anything else is a plain substring (paths like
 *  `/api/x/y` are substrings, not regexes, because their tail is not a valid flag list). */
function textMatcher(pattern: string): (s: string) => boolean {
  const m = /^\/(.+)\/([gimsuy]*)$/.exec(pattern);
  if (m) {
    try {
      const re = new RegExp(m[1], m[2]);
      return (s) => re.test(s);
    } catch {
      /* fall through to substring */
    }
  }
  return (s) => s.includes(pattern);
}

/** "url-pattern" or "url-pattern @@ request-body-pattern" (GraphQL: match the operationName). */
// Response text, stringified once per capture (Instagram answers every GraphQL query at the same
// URL, so captures are told apart by what the response contains).
const responseText = new WeakMap<Capture, string>();
function textOfCapture(c: Capture): string {
  let t = responseText.get(c);
  if (t == null) {
    t = typeof c.body === "string" ? c.body : c.body == null ? "" : JSON.stringify(c.body);
    responseText.set(c, t);
  }
  return t;
}

/** `url`, `url @@ request-body`, or `url ## response-body`; each part a substring or /regex/. */
function makeMatcher(pattern: string): (c: Capture) => boolean {
  const [urlAndReq, respPart] = pattern.split(" ## ");
  const [urlPart, bodyPart] = urlAndReq.split(" @@ ");
  const urlOk = textMatcher(urlPart.trim());
  const reqOk = bodyPart ? textMatcher(bodyPart.trim()) : null;
  const respOk = respPart ? textMatcher(respPart.trim()) : null;
  return (c) => urlOk(c.url) && (!reqOk || reqOk(c.request_body ?? "")) && (!respOk || respOk(textOfCapture(c)));
}

async function actionWaitCapture(p: Params, taskTimeoutMs: number): Promise<unknown> {
  const pattern = str(p, "pattern", true)!;
  const since = typeof p.since === "number" ? p.since : 0;
  const timeoutMs = typeof p.timeout_ms === "number" ? p.timeout_ms : Math.max(1000, taskTimeoutMs - 1000);
  const match = makeMatcher(pattern);
  const test = (c: Capture) => c.ts >= since && match(c);
  const risk = currentPagePlatform()?.riskSignals ?? [];
  const isRisk = (c: Capture) => c.ts >= since && risk.some((re) => re.test(c.url));
  plog("debug", "wait_capture", { pattern, since, href: location.href, ready: document.readyState, ring: ring.length });

  const risky = ring.find(isRisk);
  if (risky) throw new PageError("captcha_required", `site is showing a risk-control challenge (${risky.url.slice(0, 80)})`, { url: location.href });
  const existing = [...ring].reverse().find(test);
  if (existing) return existing;

  return new Promise((resolve, reject) => {
    const waiter = {
      test: (c: Capture) => test(c) || isRisk(c),
      resolve: (c: Capture) => {
        if (isRisk(c)) reject(new PageError("captcha_required", `site is showing a risk-control challenge (${c.url.slice(0, 80)})`, { url: location.href }));
        else resolve(c);
      },
    };
    waiters.push(waiter);
    setTimeout(() => {
      const i = waiters.indexOf(waiter);
      if (i >= 0) {
        waiters.splice(i, 1);
        reject(new PageError("timeout", `no response matching ${pattern} within ${timeoutMs}ms`));
      }
    }, timeoutMs);
  });
}

function resolvePath(path: string): unknown {
  let cur: unknown = window;
  for (const seg of path.split(".")) {
    if (cur == null || (typeof cur !== "object" && typeof cur !== "function")) return undefined;
    cur = unwrapRef((cur as Record<string, unknown>)[seg]);
  }
  return cur;
}

/** Vue refs expose the real value under `.value`; unwrap so paths read naturally. */
function unwrapRef(v: unknown): unknown {
  if (v && typeof v === "object" && (v as Record<string, unknown>).__v_isRef === true) {
    return (v as { value: unknown }).value;
  }
  return v;
}

/** JSON-safe deep copy: unwraps Vue refs/reactive proxies, drops functions, cuts cycles, bounds depth. */
function safeClone(v: unknown, seen = new WeakSet<object>(), depth = 0): unknown {
  v = unwrapRef(v);
  if (v == null) return v;
  const t = typeof v;
  if (t === "function" || t === "symbol") return undefined;
  if (t === "bigint") return String(v);
  if (t !== "object") return v;
  if (depth > 48) return "[depth]"; // YouTube's ytInitialData nests 20+ levels deep
  const obj = v as object;
  if (seen.has(obj)) return "[cycle]";
  seen.add(obj);
  try {
    if (Array.isArray(obj)) return obj.map((x) => safeClone(x, seen, depth + 1));
    if (obj instanceof Map) return Object.fromEntries([...obj.entries()].map(([k, x]) => [String(k), safeClone(x, seen, depth + 1)]));
    if (obj instanceof Set) return [...obj].map((x) => safeClone(x, seen, depth + 1));
    if (obj instanceof Date) return obj.toISOString();
    const out: Record<string, unknown> = {};
    for (const k of Object.keys(obj)) {
      if (k.startsWith("__v_") || k === "_rawValue" || k === "_value" || k === "dep") continue;
      const c = safeClone((obj as Record<string, unknown>)[k], seen, depth + 1);
      if (c !== undefined) out[k] = c;
    }
    return out;
  } finally {
    seen.delete(obj); // shared (non-cyclic) references are fine; only true cycles are cut
  }
}

async function actionReadGlobal(p: Params): Promise<unknown> {
  const path = str(p, "path", true)!;
  const waitMs = typeof p.wait_ms === "number" ? p.wait_ms : 0;
  const deadline = Date.now() + waitMs;
  let cur = resolvePath(path);
  while (cur === undefined && Date.now() < deadline) {
    await new Promise((r) => setTimeout(r, 200));
    cur = resolvePath(path);
  }
  if (cur === undefined) throw new PageError("not_found", `window.${path} is undefined`);
  return safeClone(cur);
}

/** Elements that actually scroll (overflow auto/scroll with hidden content), tallest first. */
function findScrollables(limit = 8): { el: HTMLElement; selector: string; scrollHeight: number; clientHeight: number }[] {
  const out: { el: HTMLElement; selector: string; scrollHeight: number; clientHeight: number }[] = [];
  const all = document.querySelectorAll<HTMLElement>("body *");
  for (let i = 0; i < all.length && i < 5000; i++) {
    const el = all[i];
    if (el.scrollHeight - el.clientHeight < 50 || el.clientHeight < 100) continue;
    const oy = getComputedStyle(el).overflowY;
    if (oy !== "auto" && oy !== "scroll") continue;
    const sel = el.tagName.toLowerCase() + (el.id ? `#${el.id}` : "") + (el.classList.length ? "." + [...el.classList].slice(0, 2).join(".") : "");
    out.push({ el, selector: sel, scrollHeight: el.scrollHeight, clientHeight: el.clientHeight });
  }
  out.sort((a, b) => b.scrollHeight - b.clientHeight - (a.scrollHeight - a.clientHeight));
  return out.slice(0, limit);
}

/** Read one DOM element: its text / an attribute, optionally decoded as JSON or URI-encoded JSON
 *  (sites embed server-rendered state in <script id="RENDER_DATA"> that way). */
async function actionReadElement(p: Params): Promise<unknown> {
  const selector = str(p, "selector", true)!;
  const waitMs = typeof p.wait_ms === "number" ? p.wait_ms : 0;
  const deadline = Date.now() + waitMs;
  let el = document.querySelector(selector);
  while (!el && Date.now() < deadline) {
    await new Promise((r) => setTimeout(r, 200));
    el = document.querySelector(selector);
  }
  if (!el) throw new PageError("not_found", `no element matches ${selector}`);
  const attr = str(p, "attr") ?? "textContent";
  let value: string | null;
  if (attr === "textContent") value = el.textContent;
  else if (attr === "innerText") value = (el as HTMLElement).innerText;
  else if (attr === "outerHTML") value = el.outerHTML;
  else value = el.getAttribute(attr);
  const decode = str(p, "decode");
  if (value == null) return null;
  try {
    if (decode === "uri-json") return JSON.parse(decodeURIComponent(value));
    if (decode === "json") return JSON.parse(value);
  } catch (e) {
    throw new PageError("parse_error", `cannot decode ${selector} as ${decode}: ${String(e)}`);
  }
  return value;
}

/** Click an element (the site's own handlers run), optionally waiting for it to appear first. */
function findClickable(selector: string | undefined, text: string | undefined): HTMLElement | null {
  if (!text) return selector ? document.querySelector<HTMLElement>(selector) : null;
  // Smallest element whose own visible text equals `text` (a tab label, a button caption).
  const candidates = [...document.querySelectorAll<HTMLElement>(selector || "a,button,span,div,li,p")];
  // "/regex/flags" matches the visible text as a regular expression (e.g. "/^\d+ 条评论$/").
  const rx = text.length > 2 && text.startsWith("/") && /\/[a-z]*$/.test(text) ? new RegExp(text.slice(1, text.lastIndexOf("/")), text.slice(text.lastIndexOf("/") + 1)) : null;
  let best: HTMLElement | null = null;
  for (const el of candidates) {
    const own = (el.innerText || "").replace(/[​-‍﻿]/g, "").trim(); // 知乎 pads captions with zero-width chars
    if (rx ? !rx.test(own) : own !== text) continue;
    if (!best || el.innerHTML.length < best.innerHTML.length) best = el;
  }
  return best;
}

async function actionClick(p: Params): Promise<unknown> {
  const selector = str(p, "selector");
  const text = str(p, "text");
  if (!selector && !text) throw new PageError("bad_request", "click needs selector or text");
  const waitMs = typeof p.wait_ms === "number" ? p.wait_ms : 5000;
  const deadline = Date.now() + waitMs;
  let el = findClickable(selector, text);
  while (!el && Date.now() < deadline) {
    await new Promise((r) => setTimeout(r, 200));
    el = findClickable(selector, text);
  }
  if (!el) throw new PageError("not_found", `no element matches ${selector ?? ""} ${text ? `text=${text}` : ""}`);
  el.scrollIntoView({ block: "center" });
  el.click();
  return { clicked: selector ?? `text=${text}`, text: (el.innerText || "").slice(0, 80) };
}

/** Type into an input/textarea the way a user would (native setter + input event), optionally
 *  pressing Enter afterwards so the site's own search handler runs. */
async function actionType(p: Params): Promise<unknown> {
  const selector = str(p, "selector", true)!;
  const text = str(p, "text") ?? "";
  const waitMs = typeof p.wait_ms === "number" ? p.wait_ms : 5000;
  const deadline = Date.now() + waitMs;
  let el = document.querySelector<HTMLInputElement | HTMLTextAreaElement>(selector);
  while (!el && Date.now() < deadline) {
    await new Promise((r) => setTimeout(r, 200));
    el = document.querySelector<HTMLInputElement | HTMLTextAreaElement>(selector);
  }
  if (!el) throw new PageError("not_found", `no element matches ${selector}`);
  el.focus();
  const proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
  const setter = Object.getOwnPropertyDescriptor(proto, "value")?.set;
  if (setter) setter.call(el, text);
  else el.value = text;
  el.dispatchEvent(new Event("input", { bubbles: true }));
  el.dispatchEvent(new Event("change", { bubbles: true }));
  if (p.submit) {
    for (const type of ["keydown", "keypress", "keyup"]) {
      el.dispatchEvent(new KeyboardEvent(type, { key: "Enter", code: "Enter", keyCode: 13, which: 13, bubbles: true }));
    }
    el.form?.requestSubmit?.();
  }
  return { typed: text, selector, submitted: !!p.submit };
}

/** Server-rendered state: inline <script type="application/json"> / <code> blocks (Instagram, LinkedIn)
 *  whose text contains params.contains; returns their text (head-limited by params.max_chars). */
function actionFindScripts(p: Params): unknown {
  const selector = str(p, "selector") || 'script[type="application/json"], script:not([src]), code';
  const contains = str(p, "contains") || "";
  const maxChars = typeof p.max_chars === "number" ? p.max_chars : 200_000;
  const limit = typeof p.limit === "number" ? p.limit : 20;
  const out: { id: string | null; type: string | null; size: number; index: number; text: string }[] = [];
  const els = Array.from(document.querySelectorAll(selector));
  for (let i = 0; i < els.length && out.length < limit; i++) {
    const el = els[i];
    const text = el.textContent ?? "";
    if (text.length < 20 || (contains && !text.includes(contains))) continue;
    out.push({ id: el.id || null, type: el.getAttribute("type"), size: text.length, index: i, text: text.slice(0, maxChars) });
  }
  return out;
}

/** Dev: every capture in the ring buffer matching params.pattern (default all), oldest first. */
function actionListCaptures(p: Params): unknown {
  const match = makeMatcher(str(p, "pattern") || "/./");
  const since = typeof p.since === "number" ? p.since : 0;
  const bodyChars = typeof p.body_chars === "number" ? p.body_chars : 0;
  const limit = typeof p.limit === "number" ? p.limit : 300;
  return ring
    .filter((c) => c.ts >= since && match(c))
    .slice(-limit)
    .map((c) => {
      const text = typeof c.body === "string" ? c.body : JSON.stringify(c.body ?? null);
      return { url: c.url, ts: c.ts, size: text?.length ?? 0, ...(bodyChars ? { body: (text ?? "").slice(0, bodyChars) } : {}) };
    });
}

/** Dev: what the page looks like from the script's point of view. */
async function actionDomProbe(): Promise<unknown> {
  return {
    href: location.href,
    title: document.title,
    ready_state: document.readyState,
    visibility: document.visibilityState,
    window_scroll: { scrollHeight: document.documentElement.scrollHeight, innerHeight: window.innerHeight },
    scrollables: findScrollables().map(({ selector, scrollHeight, clientHeight }) => ({ selector, scrollHeight, clientHeight })),
    globals: Object.keys(window).filter((k) => k.startsWith("__") || k.startsWith("_")).slice(0, 40),
    ring_urls: ring.slice(-15).map((c) => c.url.slice(0, 100)),
    text: (document.body?.innerText ?? "").replace(/\s+/g, " ").slice(0, 400),
    script_ids: [...document.scripts].map((sc) => sc.id).filter(Boolean).slice(0, 20),
    inputs: [...document.querySelectorAll<HTMLInputElement>("input,textarea")].slice(0, 12).map((i) => ({ tag: i.tagName.toLowerCase(), type: i.getAttribute("type"), placeholder: i.getAttribute("placeholder"), id: i.id || null, class: i.className.toString().slice(0, 60), name: i.getAttribute("name") })),
  };
}

/** Scroll (window or a container) until a new response matching `pattern` is captured. */
async function actionScrollCapture(p: Params, taskTimeoutMs: number): Promise<unknown> {
  const pattern = str(p, "pattern", true)!;
  const selector = str(p, "scroll_selector");
  const timeoutMs = typeof p.timeout_ms === "number" ? p.timeout_ms : Math.max(2000, taskTimeoutMs - 1000);
  const since = Date.now();
  let tick = 0;
  const scrollOnce = () => {
    // Explicit selector, else every scrollable container on the page (side navs included, harmless), plus the window.
    // With an explicit selector only that container moves: scrolling the window as well would push
    // a side column (Instagram's comment list) out of the viewport, and its lazy loader never fires.
    let targets: (HTMLElement | Window)[];
    if (selector) {
      const el = document.querySelector<HTMLElement>(selector);
      targets = el ? [el] : [window];
    } else {
      targets = [...findScrollables(4).map((s) => s.el), window];
    }
    // Step down the page like a reader (lazy sections such as comment lists load when they
    // enter the viewport), jumping to the bottom every few ticks for plain infinite lists.
    tick += 1;
    const step = tick % 4 === 0 ? Number.MAX_SAFE_INTEGER : 700 * tick;
    for (const t of targets) {
      if (t instanceof Window) window.scrollTo({ top: Math.min(step, document.documentElement.scrollHeight), behavior: "auto" });
      else {
        t.scrollTo({ top: Math.min(step, t.scrollHeight), behavior: "auto" });
        t.dispatchEvent(new WheelEvent("wheel", { deltaY: 600, bubbles: true })); // some lists page on wheel, not scroll
      }
      t.dispatchEvent(new Event("scroll"));
    }
  };
  const wait = actionWaitCapture({ pattern, since, timeout_ms: timeoutMs }, taskTimeoutMs);
  let settled = false;
  wait.then(() => (settled = true), () => (settled = true));
  void (async () => {
    while (!settled && Date.now() - since < timeoutMs) {
      scrollOnce();
      await new Promise((r) => setTimeout(r, 700));
    }
  })();
  return wait;
}

async function execute(task: TaskSpec): Promise<unknown> {
  const p = task.params ?? {};
  switch (task.action) {
    case "echo":
      return actionEcho(p);
    case "fetch":
      return actionFetch(p);
    case "wait_capture":
      return actionWaitCapture(p, task.timeout_ms);
    case "read_global":
      return actionReadGlobal(p);
    case "scroll_capture":
      return actionScrollCapture(p, task.timeout_ms);
    case "dom_probe":
      return actionDomProbe();
    case "list_captures":
      return actionListCaptures(p);
    case "find_scripts":
      return actionFindScripts(p);
    case "read_element":
      return actionReadElement(p);
    case "click":
      return actionClick(p);
    case "type":
      return actionType(p);
    default: {
      const handler = platformAction(task.platform, task.action);
      if (!handler) throw new PageError("unsupported", `page cannot execute action "${task.action}" for ${task.platform}`);
      return handler(p, {
        fetch: window.fetch.bind(window),
        captures: (pattern) => ring.filter(makeMatcher(pattern)),
        timeoutMs: task.timeout_ms,
        waitCapture: (pattern, since = 0, timeoutMs) => actionWaitCapture({ pattern, since, ...(timeoutMs ? { timeout_ms: timeoutMs } : {}) }, task.timeout_ms),
        scrollCapture: (pattern, opts) => actionScrollCapture({ pattern, scroll_selector: opts?.scroll_selector, ...(opts?.timeoutMs ? { timeout_ms: opts.timeoutMs } : {}) }, task.timeout_ms),
        readGlobal: (path, waitMs = 0) => actionReadGlobal({ path, wait_ms: waitMs }),
        readElement: (selector, opts) => actionReadElement({ selector, attr: opts?.attr, decode: opts?.decode, wait_ms: opts?.waitMs ?? 0 }),
        click: (selector, waitMs = 5000) => actionClick({ selector, wait_ms: waitMs }),
        clickText: (text, waitMs = 5000) => actionClick({ text, wait_ms: waitMs }),
        type: (selector, text, opts) => actionType({ selector, text, submit: opts?.submit ?? false, wait_ms: opts?.waitMs ?? 5000 }),
      });
    }
  }
}

async function runTask(task: TaskSpec): Promise<void> {
  const timeout = new Promise<never>((_, reject) =>
    setTimeout(() => reject(new PageError("timeout", `page action ${task.action} timed out`)), task.timeout_ms),
  );
  try {
    const payload = await Promise.race([execute(task), timeout]);
    if (cancelled.delete(task.id)) return;
    post({ type: "page.task.result", id: task.id, ok: true, payload, build: BUILD });
  } catch (e) {
    if (cancelled.delete(task.id)) return;
    post({ type: "page.task.result", id: task.id, ok: false, error: toError(e), build: BUILD });
  }
}

// ---- inbound messages -------------------------------------------------------------

window.addEventListener("message", (ev: MessageEvent) => {
  if (ev.source !== window || !isEnvelope(ev.data) || ev.data.dir !== "to-page") return;
  const msg = ev.data.msg as BgToContent;
  switch (msg.type) {
    case "task.execute":
      if ((window as unknown as Record<string, unknown>)[MARK] !== BUILD) break; // a newer build took over
      void runTask(msg.task);
      break;
    case "task.cancel":
      cancelled.add(msg.id);
      break;
    case "capture.config":
      captureEnabled = msg.enabled;
      plog("debug", `capture ${captureEnabled ? "enabled" : "disabled"}`);
      break;
  }
});

plog("debug", "page script installed");
}

if ((window as unknown as Record<string, unknown>)[MARK] !== BUILD) {
  (window as unknown as Record<string, unknown>)[MARK] = BUILD;
  document.documentElement.dataset.sociallensBuild = BUILD;
  installSocialLens();
}
