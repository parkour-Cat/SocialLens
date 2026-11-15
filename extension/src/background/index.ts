// Service worker entry: wires the backend link (link.ts) to task execution (execute.ts), answers
// content scripts and the popup, reports status, and keeps the connection alive.
//
//   link.ts        WebSocket to the backend, config, reconnect
//   tabs.ts        owned-tab pool, platform tabs, login state, content-script reachability
//   workwindow.ts  the separate window the extension's tabs live in
//   execute.ts     running a task in a tab (in-tab calls, navigate + capture / page action)

import { platformForUrl, platforms } from "../platforms";
import { log } from "../shared/log";
import type { BackendToExt, ContentToBg, ExtStatus, PopupToBg } from "../shared/messages";
import { BUILD } from "./env";
import { cancelTask, pendingCount, rejectAllPending, runTask, settlePageResult } from "./execute";
import { DEFAULT_BACKEND, connect, httpBase, linkState, loadConfig, onBackendClosed, onBackendMessage, reconnectNow, remoteLog, wsSend } from "./link";
import { broadcastTabStates, isLoggedIn, pool, pushCaptureConfig, recording, scheduleTabStates, tabPlatform, tabsForPlatform } from "./tabs";

const ALARM = "sociallens-keepalive";

// ---- messages from the backend ---------------------------------------------------------

async function handleBackend(msg: BackendToExt): Promise<void> {
  switch (msg.type) {
    case "hello":
      await broadcastTabStates(true);
      break;
    case "ping":
      wsSend({ type: "pong", ts: msg.ts });
      break;
    case "task.dispatch": {
      const { type: _t, ...task } = msg;
      void runTask(task);
      break;
    }
    case "task.cancel":
      cancelTask(msg.id);
      break;
    case "record.set":
      if (msg.enabled) recording.add(msg.platform);
      else recording.delete(msg.platform);
      await pushCaptureConfig(msg.platform);
      break;
  }
}

onBackendMessage(handleBackend);
onBackendClosed(rejectAllPending);

// ---- messages from content scripts and popup -----------------------------------------

chrome.runtime.onMessage.addListener((msg: ContentToBg | PopupToBg, sender, sendResponse) => {
  const tabId = sender.tab?.id;
  switch (msg.type) {
    case "content.ready": {
      const def = platformForUrl(msg.url);
      if (tabId != null && def) tabPlatform.set(tabId, def.id);
      scheduleTabStates();
      sendResponse({ captureEnabled: !!def && recording.has(def.id) });
      return false;
    }
    case "page.task.result": {
      // After an extension reload an older page script may still live in the same document
      // and answer with stale code (e.g. "unsupported" for new actions); only trust this build.
      if (msg.build !== BUILD) {
        remoteLog("info", "ignored result from another page build", { task_id: msg.id, build: msg.build ?? "none", expected: BUILD });
        return false;
      }
      settlePageResult(msg.id, msg.ok, msg.payload, msg.error);
      return false;
    }
    case "page.capture": {
      const def = platformForUrl(sender.tab?.url);
      if (def && recording.has(def.id)) {
        const { type: _t, ...capture } = msg;
        wsSend({ type: "capture", platform: def.id, ...capture });
      }
      return false;
    }
    case "page.log":
      log.debug("[page]", msg.msg, msg.data ?? "");
      return false;
    case "popup.status":
      void buildStatus().then(sendResponse);
      return true;
    case "popup.save":
      void chrome.storage.local
        .set({ backendUrl: msg.backendUrl || DEFAULT_BACKEND, token: msg.token })
        .then(() => reconnectNow("config changed"))
        .then(() => sendResponse({ ok: true }));
      return true;
    case "popup.reconnect":
      void reconnectNow("manual reconnect").then(() => sendResponse({ ok: true }));
      return true;
    case "popup.resume": {
      const base = httpBase(linkState().config?.backendUrl ?? DEFAULT_BACKEND);
      void fetch(`${base}/api/v1/${msg.platform}/resume`, { method: "POST" })
        .then((r) => sendResponse({ ok: r.ok }))
        .catch((e) => sendResponse({ ok: false, error: String(e) }));
      return true;
    }
  }
  return false;
});

chrome.tabs.onRemoved.addListener((id) => {
  tabPlatform.delete(id);
  pool.forget(id);
});

// ---- status (popup, dev hook) -------------------------------------------------------------

async function buildStatus(): Promise<ExtStatus> {
  const link = linkState();
  const cfg = link.config ?? (await loadConfig());
  const platformStates: ExtStatus["platforms"] = {};
  for (const def of platforms) {
    const tabs = await tabsForPlatform(def);
    platformStates[def.id] = { name: def.name, logged_in: await isLoggedIn(def), tab_ids: tabs.map((t) => t.id!), recording: recording.has(def.id), login_url: def.loginUrl, login_hint: def.loginHint };
  }
  // The tab the user is looking at (popups open on the active tab of the focused window).
  let currentTab: ExtStatus["currentTab"] = null;
  try {
    const [active] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
    const def = active?.url ? platformForUrl(active.url) : undefined;
    if (def) currentTab = { platform: def.id, name: def.name, logged_in: platformStates[def.id]?.logged_in ?? false, login_required: def.loginRequired !== false };
  } catch {
    currentTab = null;
  }
  // Paused queues come from the backend's status route (the extension only sees its own tasks).
  let alerts: ExtStatus["alerts"] = [];
  if (link.connected) {
    try {
      const res = await fetch(httpBase(cfg.backendUrl) + "/api/v1/status");
      const body = (await res.json()) as { data?: { queues?: Record<string, { paused_for_s?: number }> } };
      for (const [pid, q] of Object.entries(body.data?.queues ?? {})) {
        if ((q.paused_for_s ?? 0) > 0 && platformStates[pid]) alerts.push({ platform: pid, name: platformStates[pid].name, paused_for_s: q.paused_for_s! });
      }
    } catch {
      alerts = [];
    }
  }
  return {
    connected: link.connected,
    backendUrl: cfg.backendUrl,
    hasToken: !!cfg.token,
    backendVersion: link.backendVersion,
    lastError: link.lastError,
    platforms: platformStates,
    pendingTasks: pendingCount(),
    currentTab,
    alerts,
    build: BUILD,
  };
}

// ---- lifecycle -----------------------------------------------------------------------

// Dev hook used by scripts/e2e_chrome.py after seeding chrome.storage; harmless otherwise.
(self as unknown as { __sociallens: unknown }).__sociallens = {
  reconnect: () => reconnectNow("dev reconnect"),
  status: buildStatus,
};

chrome.alarms.create(ALARM, { periodInMinutes: 0.5 });
chrome.alarms.onAlarm.addListener((a) => {
  if (a.name !== ALARM) return;
  if (!linkState().connected) void connect();
  void pool.gcSessionTabs();
});
chrome.runtime.onStartup.addListener(() => void connect());
chrome.runtime.onInstalled.addListener(() => {
  void connect();
  void reinjectOpenTabs();
});

/** After an install/reload, existing platform tabs have orphaned scripts. Inject fresh ones. */
async function reinjectOpenTabs(): Promise<void> {
  for (const def of platforms) {
    for (const t of await tabsForPlatform(def)) {
      if (t.id == null || t.discarded) continue;
      try {
        // The MAIN-world page script survives an extension reload (it lives in the page, not in
        // the extension context); only inject it where it is missing. The bridge always needs
        // a fresh copy because the old one lost its runtime connection.
        // page.js is build-idempotent: it installs only if this build is not already there.
        await chrome.scripting.executeScript({ target: { tabId: t.id }, files: ["page.js"], world: "MAIN", injectImmediately: true });
        await chrome.scripting.executeScript({ target: { tabId: t.id }, files: ["content.js"], injectImmediately: true });
        remoteLog("info", "re-injected scripts", { tab: t.id, platform: def.id, build: BUILD });
      } catch (e) {
        remoteLog("warning", "re-inject failed", { tab: t.id, platform: def.id, error: String(e).slice(0, 120) });
      }
    }
  }
}
void connect();
