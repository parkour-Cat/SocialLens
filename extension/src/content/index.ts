// ISOLATED-world bridge: relays messages between the page script (window.postMessage)
// and the background service worker (chrome.runtime). No logic lives here.

import { PAGE_CHANNEL, isEnvelope, type BgToContent, type ContentToBg } from "../shared/messages";

const ORIGIN = location.origin;
// Identifies this document instance. The background uses it to tell a freshly navigated
// document apart from the one that is about to be unloaded.
const DOC_ID = crypto.randomUUID();

function toPage(msg: BgToContent): void {
  window.postMessage({ [PAGE_CHANNEL]: true, dir: "to-page", msg }, ORIGIN);
}

const onPageMessage = (ev: MessageEvent) => {
  if (ev.source !== window || !isEnvelope(ev.data) || ev.data.dir !== "from-page") return;
  try {
    chrome.runtime.sendMessage(ev.data.msg as ContentToBg).catch(() => {
      /* background asleep; nothing to do */
    });
  } catch {
    // "Extension context invalidated": this copy of the bridge belongs to a reloaded/removed
    // extension. It can never talk to the background again, so stop listening.
    window.removeEventListener("message", onPageMessage);
  }
};
window.addEventListener("message", onPageMessage);

chrome.runtime.onMessage.addListener((msg: BgToContent, sender, sendResponse) => {
  if (sender.id !== chrome.runtime.id || sender.tab) return false;
  toPage(msg);
  sendResponse({ ok: true, doc: DOC_ID, page_build: document.documentElement.dataset.sociallensBuild ?? null });
  return false;
});

chrome.runtime
  .sendMessage({ type: "content.ready", url: location.href } satisfies ContentToBg)
  .then((cfg: { captureEnabled?: boolean } | undefined) => {
    if (cfg?.captureEnabled) toPage({ type: "capture.config", enabled: true });
  })
  .catch(() => {});
