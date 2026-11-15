// What the extension knows about tabs: the pool of tabs it owns, which tabs belong to which
// platform, login state (cookie check) broadcast to the backend, reaching a tab's content
// script, and per-platform record mode.

import { TabPool } from "./tabpool";
import { platformById, platforms, type PlatformDef } from "../platforms";
import { hostMatches } from "../platforms/types";
import { log } from "../shared/log";
import type { BgToContent } from "../shared/messages";
import { BUILD } from "./env";
import { ExtError } from "./errors";
import { wsSend } from "./link";

/** Platforms in record mode: their captures are forwarded to the backend. */
export const recording = new Set<string>();

// ---- tabs -----------------------------------------------------------------------

// Tabs the extension owns (session / helper tabs in the work window), cursor keys, and which
// tab a navigate task may take over: see tabpool.ts (unit-tested, no chrome.* inside).
export const pool = new TabPool({
  getTab: async (id) => {
    const t = await chrome.tabs.get(id).catch(() => null);
    return t?.id != null ? { id: t.id, url: t.url, pendingUrl: t.pendingUrl, index: t.index, windowId: t.windowId } : null;
  },
  removeTab: (id) => chrome.tabs.remove(id).catch(() => {}),
  reachable: (id) => waitContentReady(id, 1_500).then(() => true, () => false),
  log: (msg, ...args) => log.debug(msg, ...args),
});

export async function tabsForPlatform(def: PlatformDef): Promise<chrome.tabs.Tab[]> {
  const all = await chrome.tabs.query({});
  return all.filter((t) => {
    if (!t.url || t.id == null || pool.isClosing(t.id)) return false;
    try {
      return hostMatches(def, new URL(t.url).hostname);
    } catch {
      return false;
    }
  });
}

export async function isLoggedIn(def: PlatformDef): Promise<boolean> {
  if (!def.loginCookie) return true;
  try {
    const c = await chrome.cookies.get({ url: def.loginCookie.url, name: def.loginCookie.name });
    return !!c?.value;
  } catch {
    return false;
  }
}

const lastTabState = new Map<string, string>();
let tabStateTimer: ReturnType<typeof setTimeout> | null = null;

export async function broadcastTabStates(force = false): Promise<void> {
  for (const def of platforms) {
    const tabs = await tabsForPlatform(def);
    const state = { platform: def.id, logged_in: await isLoggedIn(def), tab_ids: tabs.map((t) => t.id!).sort() };
    const key = JSON.stringify(state);
    if (force || lastTabState.get(def.id) !== key) {
      lastTabState.set(def.id, key);
      wsSend({ type: "tab.state", ...state });
    }
  }
}

export function scheduleTabStates(): void {
  if (tabStateTimer) clearTimeout(tabStateTimer);
  tabStateTimer = setTimeout(() => {
    tabStateTimer = null;
    void broadcastTabStates();
  }, 400);
}

chrome.tabs.onUpdated.addListener((_id, info) => {
  if (info.status || info.url) scheduleTabStates();
});
chrome.tabs.onRemoved.addListener(scheduleTabStates);
chrome.tabs.onCreated.addListener(scheduleTabStates);
chrome.cookies.onChanged.addListener((info) => {
  if (platforms.some((p) => p.loginCookie?.name === info.cookie.name)) scheduleTabStates();
});

/** Resolves once a navigation in the tab commits (URL change) or finishes; never rejects. */
export function waitTabNavigated(tabId: number, timeoutMs: number): Promise<void> {
  return new Promise((resolve) => {
    const finish = () => {
      chrome.tabs.onUpdated.removeListener(listener);
      clearTimeout(timer);
      resolve();
    };
    // A bare "complete" can belong to the previous document still finishing; require either a
    // URL change (commit) or a loading -> complete sequence observed after we started waiting.
    let sawLoading = false;
    const listener = (id: number, info: chrome.tabs.TabChangeInfo) => {
      if (id !== tabId) return;
      if (info.status === "loading") sawLoading = true;
      if (info.url || (sawLoading && info.status === "complete")) finish();
    };
    chrome.tabs.onUpdated.addListener(listener);
    const timer = setTimeout(finish, timeoutMs);
  });
}

export async function sendToTab(tabId: number, msg: BgToContent): Promise<{ ok: boolean; doc?: string; page_build?: string | null } | undefined> {
  return chrome.tabs.sendMessage(tabId, msg);
}

/**
 * Resolves with the document id once the tab's content script answers. With `notDoc`, keeps
 * polling until a *different* document answers: Chrome updates a tab's URL when a navigation
 * starts, while the old document (and its content script) may still be alive for a while.
 */
export async function waitContentReady(tabId: number, timeoutMs = 10_000, notDoc?: string): Promise<string> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const res = await sendToTab(tabId, { type: "capture.config", enabled: captureEnabledForTab(tabId) });
      const doc = res?.doc ?? "";
      // A document whose page script is from another build (loaded before an extension reload)
      // would answer with stale action code; treat it as not ready so a fresh tab gets opened.
      const buildOk = res?.page_build === BUILD;
      if (buildOk && (!notDoc || doc !== notDoc)) return doc;
      if (!buildOk) lastBuildMismatch = res?.page_build ?? "none";
    } catch {
      /* not injected yet */
    }
    await new Promise((r) => setTimeout(r, 200));
  }
  throw new ExtError(
    "extension_error",
    notDoc ? "navigated document did not become reachable" : `content script not reachable in tab${lastBuildMismatch ? ` (page build ${lastBuildMismatch}, expected ${BUILD}; reload that page)` : ""}`,
  );
}
let lastBuildMismatch: string | null = null;

export const tabPlatform = new Map<number, string>();

function captureEnabledForTab(tabId: number): boolean {
  const pid = tabPlatform.get(tabId);
  return !!pid && recording.has(pid);
}

export async function pushCaptureConfig(platformId: string): Promise<void> {
  const def = platformById(platformId);
  if (!def) return;
  for (const t of await tabsForPlatform(def)) {
    sendToTab(t.id!, { type: "capture.config", enabled: recording.has(platformId) }).catch(() => {});
  }
}
