// Page actions: the generic ones every platform tab can run (echo, fetch, wait_capture, ...)
// and dispatch to platform actions registered under ./platforms. Bound to one capture ring.

import type { Capture, TaskSpec } from "../shared/messages";
import { absolute, parseBody } from "./bytes";
import { findClickable, findScrollables, resolvePath, safeClone } from "./dom";
import { PageError } from "./errors";
import { makeMatcher } from "./matcher";
import { currentPagePlatform, platformAction } from "./platforms";
import type { CaptureRing } from "./ring";

type Params = Record<string, unknown>;

export function createActions(store: CaptureRing, plog: (level: string, msg: string, data?: unknown) => void): { execute: (task: TaskSpec) => Promise<unknown> } {
  const ring: Capture[] = store.items;
  const waiters = store.waiters;

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

  return { execute };
}
