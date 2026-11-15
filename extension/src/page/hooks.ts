// Response capture: wraps fetch, XMLHttpRequest, Worker and MessageChannel so every response
// the site receives is handed to `record`. Installed once per document and build by index.ts;
// importing this module changes nothing.

import type { Capture } from "../shared/messages";
import { absolute, bodyPreview, bytesToText, headersToObject, parseBody, wantsCapture } from "./bytes";

export function installCaptureHooks(record: (c: Capture) => void): void {
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
}
