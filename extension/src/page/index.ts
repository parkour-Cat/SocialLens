// MAIN-world page script. Runs at document_start inside platform sites.
// 1. Hooks fetch/XHR/workers so responses can be captured (hooks.ts; ring buffer in ring.ts,
//    forwarded only when record mode is on).
// 2. Executes generic actions sent by the background and platform actions registered under
//    src/page/platforms/ (actions.ts).

import {
  PAGE_CHANNEL,
  isEnvelope,
  type BgToContent,
  type ContentToBg,
  type TaskError,
  type TaskSpec,
} from "../shared/messages";
import { createActions } from "./actions";
import { PageError } from "./errors";
import { installCaptureHooks } from "./hooks";
import { CaptureRing } from "./ring";

// Re-injection after an extension reload must not install the same build twice: the whole
// script body lives in installSocialLens(), which runs once per document *per build*. A newer
// build installs alongside an older one (the old hooks cannot be removed); the background only
// routes tasks to documents whose page build matches its own, so the old listener is idle.
declare const __BUILD_ID__: string;
const BUILD = typeof __BUILD_ID__ === "string" ? __BUILD_ID__ : "dev";
const MARK = "__sociallens_page__";

function installSocialLens(): void {
  const ORIGIN = location.origin;

  function toError(e: unknown): TaskError {
    if (e instanceof PageError) return { code: e.code, message: e.message, details: e.details };
    return { code: "extension_error", message: e instanceof Error ? e.message : String(e) };
  }

  const cancelled = new Set<string>();

  function post(msg: ContentToBg): void {
    window.postMessage({ [PAGE_CHANNEL]: true, dir: "from-page", msg }, ORIGIN);
  }

  function plog(level: string, msg: string, data?: unknown): void {
    post({ type: "page.log", level, msg, data });
  }

  const store = new CaptureRing((c) => post({ type: "page.capture", ...c }));
  installCaptureHooks((c) => store.record(c));
  const { execute } = createActions(store, plog);

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
        store.captureEnabled = msg.enabled;
        plog("debug", `capture ${store.captureEnabled ? "enabled" : "disabled"}`);
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
