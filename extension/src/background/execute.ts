// Running a task from the backend: in-tab calls go to one of the extension's own tabs (helper or
// session tabs in the work window), navigate tasks open or reuse a work tab and wait for the
// site's own response or run a page action there. Results go back over the link.

import { runUntilSettled } from "./settle";
import { platformById, type PlatformDef } from "../platforms";
import { log } from "../shared/log";
import type { TaskSpec } from "../shared/messages";
import { BUILD, VERSION } from "./env";
import { ExtError, toError } from "./errors";
import { remoteLog, wsSend } from "./link";
import { isLoggedIn, pool, sendToTab, tabsForPlatform, waitContentReady, waitTabNavigated } from "./tabs";
import { createInWorkWindow, getWorkWindowId, openWorkTab } from "./workwindow";

const pendingPage = new Map<string, { resolve: (v: unknown) => void; reject: (e: unknown) => void; tabId: number }>();
const cancelledTasks = new Set<string>();

/** Tasks waiting for their page to answer. */
export function pendingCount(): number {
  return pendingPage.size;
}

/** A page's answer (page.task.result) for a task waiting on it. */
export function settlePageResult(id: string, ok: boolean, payload: unknown, error?: { code?: string; message?: string; details?: Record<string, unknown> }): void {
  const p = pendingPage.get(id);
  if (p) {
    pendingPage.delete(id);
    ok ? p.resolve(payload) : p.reject(new ExtError(error?.code ?? "extension_error", error?.message ?? "page error", error?.details));
  }
}

/** The backend cancelled a task: stop waiting on its page and tell the page. */
export function cancelTask(id: string): void {
  cancelledTasks.add(id);
  const p = pendingPage.get(id);
  if (p) {
    pendingPage.delete(id);
    sendToTab(p.tabId, { type: "task.cancel", id }).catch(() => {});
    p.reject(new ExtError("cancelled", "cancelled by backend"));
  }
}

/** The backend went away: every task waiting on a page fails. */
export function rejectAllPending(): void {
  for (const [id, p] of pendingPage) {
    p.reject(new ExtError("extension_offline", "backend disconnected"));
    pendingPage.delete(id);
  }
}

async function findOrOpenTab(def: PlatformDef): Promise<number> {
  const tabs = await tabsForPlatform(def);
  // Only our own helper / session tabs; the user's tabs are never used (see TabPool.callCandidates).
  const ready = pool.callCandidates(tabs);
  // Tabs opened before the extension was (re)loaded have no live content script; skip them.
  for (const t of ready.slice(0, 4)) {
    const reachable = await waitContentReady(t.id!, 1_500).then(() => true, () => false);
    remoteLog("info", "tab probe", { platform: def.id, tab: t.id, url: (t.url ?? "").slice(0, 60), reachable });
    if (reachable) {
      pool.touch(t.id!);
      return t.id!;
    }
  }
  // No usable tab: open one helper tab per platform in the work window (never in the user's
  // window), reuse it for later in-tab calls, and let the idle sweep close it.
  for (const [tabId, h] of [...pool.helperTabs]) {
    if (h.platform === def.id) await pool.closeTab(tabId); // unreachable (stale build / discarded): replace it
  }
  log.info("opening tab for", def.id);
  remoteLog("info", "opening helper tab", { platform: def.id, ready_tabs: ready.length, all_tabs: tabs.length });
  const tab = await createInWorkWindow(def.homeUrl, false);
  pool.addHelper(tab.id!, def.id);
  const t0 = Date.now();
  try {
    await waitContentReady(tab.id!, 30_000);
    remoteLog("info", "new tab ready", { platform: def.id, tab: tab.id, ms: Date.now() - t0 });
  } catch (e) {
    const info = await chrome.tabs.get(tab.id!).catch(() => null);
    remoteLog("warning", "new tab never reachable", { platform: def.id, tab: tab.id, status: info?.status, url: (info?.url ?? "").slice(0, 80), discarded: info?.discarded });
    throw e;
  }
  // Let the site's own scripts run briefly (device cookies, SSR state) but never block on a
  // page that streams forever.
  await Promise.race([waitTabNavigated(tab.id!, 5_000), new Promise((r) => setTimeout(r, 5_000))]);
  return tab.id!;
}

function executeInTab(tabId: number, task: TaskSpec): Promise<unknown> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      if (pendingPage.delete(task.id)) {
        remoteLog("warning", "page did not answer", { task_id: task.id, tab: tabId, action: task.action });
        reject(new ExtError("timeout", `page did not answer within ${task.timeout_ms}ms`));
      }
    }, task.timeout_ms + 1000);
    pendingPage.set(task.id, {
      tabId,
      resolve: (v) => {
        clearTimeout(timer);
        resolve(v);
      },
      reject: (e) => {
        clearTimeout(timer);
        reject(e);
      },
    });
    sendToTab(tabId, { type: "task.execute", task })
      .then((res) => remoteLog("info", "task sent to page", { task_id: task.id, tab: tabId, action: task.action, doc: String(res?.doc ?? "").slice(0, 8) }))
      .catch((e) => {
        if (pendingPage.delete(task.id)) reject(new ExtError("extension_error", `cannot reach tab ${tabId}: ${String(e)}`));
      });
  });
}

async function executeTask(task: TaskSpec): Promise<unknown> {
  if (task.platform === "_system") {
    if (task.action === "cookies") {
      // Dev: which cookies exist for a site (names + domains, never values) to pick a login marker.
      const url = String(task.params.url ?? "");
      const all = await chrome.cookies.getAll(url ? { url } : {});
      return { url, cookies: all.map((c) => ({ name: c.name, domain: c.domain, http_only: c.httpOnly, expires: c.expirationDate ? new Date(c.expirationDate * 1000).toISOString() : null })) };
    }
    if (task.action !== "echo") throw new ExtError("unsupported", `unknown system action ${task.action}`);
    const tabs = await chrome.tabs.query({});
    return { echo: task.params.payload ?? null, via: "background", extension_version: VERSION, build: BUILD, open_tabs: tabs.length, work_window: getWorkWindowId() };
  }
  const def = platformById(task.platform);
  if (!def) throw new ExtError("unknown_platform", `extension has no adapter for ${task.platform}`);
  if (def.loginRequired !== false && !task.params.allow_anonymous && !(await isLoggedIn(def))) {
    throw new ExtError("not_logged_in", `未登录${def.name}：${def.loginHint}`, { login_url: def.loginUrl, platform: def.id });
  }
  // Continue in a tab kept open by an earlier navigate (pagination by scrolling).
  if (typeof task.params._tab === "number") {
    const key = pool.resolveCursor(task.params._tab);
    const alive = key && (await chrome.tabs.get(key.tabId).then(() => true, () => false));
    if (!key || !alive) throw new ExtError("cursor_expired", "the tab behind this cursor is gone; start again without a cursor");
    if (pool.busy.has(key.tabId)) throw new ExtError("extension_error", "the tab behind this cursor is loading another page; retry shortly");
    pool.touch(key.tabId);
    await chrome.tabs.update(key.tabId, { active: true }).catch(() => {}); // must be visible to load more
    const curDoc = await waitContentReady(key.tabId, 5_000);
    if (curDoc !== key.doc) {
      throw new ExtError("cursor_expired", "the page behind this cursor was replaced by a later task in the same tab; start again without a cursor");
    }
    const value = await executeInTab(key.tabId, task);
    return pool.withTab(value, task.params._tab);
  }

  if (cancelledTasks.delete(task.id)) throw new ExtError("cancelled", "cancelled");

  if (task.strategy === "navigate" && typeof task.params.url === "string") {
    // Tabs the extension owns in the work window: nothing the user is looking at gets navigated
    // away, and pages with unload handlers cannot block us. Login is a cookie check, so no
    // helper tab is needed before navigating.
    let since = Date.now();
    const deadline = since + task.timeout_ms - 1000;
    const keepTab = !!task.params.keep_tab;
    const shortUrl = String(task.params.url).slice(0, 80);
    // A session tab already sitting on this URL (comments -> replies -> replies of one post) is
    // reused instead of loading the page again: fewer page loads is what keeps risk control quiet.
    // Its ring buffer still holds the earlier responses, so the action waits from time 0.
    const reused = await pool.findSessionTab(def.id, task.params.url);
    const reusable = reused == null ? await pool.findReusableTab(def.id, task.action, keepTab) : null;
    let navTabId: number;
    let ownTab = false;
    if (reused != null) {
      navTabId = reused;
      since = 0;
      pool.touch(navTabId);
      await chrome.tabs.update(navTabId, { active: true }).catch(() => {});
      remoteLog("info", "navigate: reusing session tab", { task_id: task.id, tab: navTabId, url: shortUrl });
    } else {
      // Replace an owned tab (the platform's home / previous search page) in place rather than
      // piling up tabs: the user wants one page per platform. Chrome would not commit a
      // tabs.update({url}) navigation of these tabs from this code path (the navigation stayed
      // pending with the old document alive, in headless and headed Chromium alike, while the
      // same call from the service worker console worked), so the tab is closed and a new one
      // opened at its index. Cursors bound to the old tab expire with it.
      let index: number | undefined;
      if (reusable != null) {
        const old = await chrome.tabs.get(reusable).catch(() => null);
        index = old?.index;
        await pool.closeTab(reusable);
        remoteLog("info", "navigate: replacing owned tab", { task_id: task.id, tab: reusable, url: shortUrl });
      } else {
        remoteLog("info", "navigate: opening work tab", { task_id: task.id, url: shortUrl });
      }
      const navTab = await openWorkTab(task.params.url, index);
      navTabId = navTab.id!;
      ownTab = true;
      remoteLog("info", "navigate: work tab created", { task_id: task.id, tab: navTabId, window: navTab.windowId, replaced: reusable ?? undefined });
    }
    pool.busy.add(navTabId);
    try {
      const doc = await waitContentReady(navTabId, Math.min(20_000, task.timeout_ms));
      log.debug("navigate: document", doc.slice(0, 8), "reachable after", Date.now() - since, "ms in tab", navTabId);
      if (keepTab && ownTab) {
        pool.addSession(navTabId, def.id, task.action);
        await pool.trimSessionTabs(def.id);
      }
      const pattern = task.params.capture_pattern;
      const pageAction = typeof task.params.page_action === "string" ? task.params.page_action : undefined;
      if (pageAction) {
        // Run a page action in the navigated document instead of waiting for a capture.
        // The action decides how long to wait (e.g. read_global with wait_ms). Sites with an
        // interstitial ("Please wait..." bot checks, login bounces) replace the document after
        // load, which would strand the action: re-issue it in the new document when that happens.
        const pageParams = { ...((task.params.page_params as Record<string, unknown>) ?? {}), since };
        const runId = (d: string, attempt: number) => (attempt === 0 ? task.id : `${task.id}:${d.slice(0, 8)}`);
        const outcome = await runUntilSettled(doc, {
          deadline,
          run: (d, attempt) => executeInTab(navTabId, { ...task, id: runId(d, attempt), action: pageAction, params: pageParams }),
          // The replacement watch times out at the deadline: that is the action timing out, not a navigation problem.
          watchReplaced: (d, remaining) => waitContentReady(navTabId, remaining, d),
          cancel: (d, attempt) => {
            pendingPage.delete(runId(d, attempt));
            sendToTab(navTabId, { type: "task.cancel", id: runId(d, attempt) }).catch(() => {});
          },
          onReplaced: (d, attempt) => remoteLog("info", "navigate: document replaced, re-running page action", { task_id: task.id, tab: navTabId, doc: d.slice(0, 8), attempt }),
        });
        if ("value" in outcome) return pool.withTab(outcome.value, keepTab ? pool.cursorKeyFor(navTabId, outcome.doc) : undefined);
        throw new ExtError("timeout", `page action ${pageAction} did not finish before the navigation settled`);
      }
      if (typeof pattern !== "string") {
        return pool.withTab({ navigated: task.params.url }, keepTab ? pool.cursorKeyFor(navTabId, doc) : undefined);
      }
      // A site may chain documents (redirects, interstitials). Wait in the current document, but
      // if it gets replaced before a match arrives, re-issue the wait in the new one.
      const waitId = (d: string) => `${task.id}:${d.slice(0, 8)}`;
      const outcome = await runUntilSettled(doc, {
        deadline,
        run: (d) => executeInTab(navTabId, { ...task, id: waitId(d), action: "wait_capture", params: { pattern, since, timeout_ms: deadline - Date.now() } }),
        watchReplaced: (d, remaining) => waitContentReady(navTabId, remaining, d),
        cancel: (d) => {
          pendingPage.delete(waitId(d));
          sendToTab(navTabId, { type: "task.cancel", id: waitId(d) }).catch(() => {});
        },
        onReplaced: (d) => log.debug("navigate: document replaced, re-waiting in", d.slice(0, 8)),
      });
      if ("value" in outcome) return pool.withTab(outcome.value, keepTab ? pool.cursorKeyFor(navTabId, outcome.doc) : undefined);
      throw new ExtError("timeout", `no captured response matching ${pattern} before the navigation settled`);
    } finally {
      pool.busy.delete(navTabId);
      if (!keepTab && ownTab) await pool.closeTab(navTabId);
    }
  }
  const tabId = await findOrOpenTab(def);
  log.debug("task", task.id, "using tab", tabId);
  if (cancelledTasks.delete(task.id)) throw new ExtError("cancelled", "cancelled");
  return executeInTab(tabId, task);
}

export async function runTask(task: TaskSpec): Promise<void> {
  const started = Date.now();
  log.debug("task", task.id, task.platform, task.action);
  try {
    const payload = await executeTask(task);
    if (cancelledTasks.delete(task.id)) return;
    wsSend({ type: "task.result", id: task.id, ok: true, payload });
  } catch (e) {
    cancelledTasks.delete(task.id);
    const err = toError(e);
    log.warn("task failed", task.id, err.code, err.message);
    wsSend({ type: "task.result", id: task.id, ok: false, error: err });
  } finally {
    remoteLog("debug", "task finished in extension", { task_id: task.id, elapsed_ms: Date.now() - started });
  }
}
