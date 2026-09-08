// Service worker: keeps the WebSocket to the backend, routes tasks to platform tabs,
// tracks per-platform tab/login state, forwards captures when a platform is recording.

import { pagePlatformActions } from "../page/platforms/catalog";
import { platformById, platformForUrl, platforms, type PlatformDef } from "../platforms";
import { hostMatches } from "../platforms/types";
import { log, setVerbose } from "../shared/log";
import type {
  BackendToExt,
  BgToContent,
  ContentToBg,
  ExtStatus,
  ExtToBackend,
  PopupToBg,
  TaskError,
  TaskSpec,
} from "../shared/messages";

declare const __BUILD_ID__: string;
const VERSION = chrome.runtime.getManifest().version;
const BUILD = typeof __BUILD_ID__ === "string" ? __BUILD_ID__ : "dev";
const DEFAULT_BACKEND = "ws://127.0.0.1:17800/ws/extension";
const RECONNECT_MAX_MS = 30_000;
const ALARM = "sociallens-keepalive";

class ExtError extends Error {
  constructor(
    public code: string,
    message: string,
    public details?: Record<string, unknown>,
  ) {
    super(message);
  }
}

function toError(e: unknown): TaskError {
  if (e instanceof ExtError) return { code: e.code, message: e.message, details: e.details };
  return { code: "extension_error", message: e instanceof Error ? e.message : String(e) };
}

// ---- config -------------------------------------------------------------------

interface Config {
  backendUrl: string;
  token: string;
  verbose: boolean;
}

async function loadConfig(): Promise<Config> {
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

const recording = new Set<string>();
const pendingPage = new Map<string, { resolve: (v: unknown) => void; reject: (e: unknown) => void; tabId: number }>();
const cancelledTasks = new Set<string>();

function wsSend(msg: ExtToBackend): void {
  if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(msg));
}

function remoteLog(level: "debug" | "info" | "warning" | "error", msg: string, fields: Record<string, unknown> = {}): void {
  wsSend({ type: "log", level, msg, ...fields });
}

let connecting: Promise<void> | null = null;

/** Idempotent: concurrent callers share one attempt; a live socket is never duplicated. */
function connect(): Promise<void> {
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
    void handleBackend(msg);
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
    for (const [id, p] of pendingPage) {
      p.reject(new ExtError("extension_offline", "backend disconnected"));
      pendingPage.delete(id);
    }
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

async function handleBackend(msg: BackendToExt): Promise<void> {
  switch (msg.type) {
    case "hello":
      connected = true;
      backendVersion = msg.backend_version;
      lastError = null;
      reconnectDelay = 1000;
      log.info("connected to backend", msg.backend_version);
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
      cancelledTasks.add(msg.id);
      {
        const p = pendingPage.get(msg.id);
        if (p) {
          pendingPage.delete(msg.id);
          sendToTab(p.tabId, { type: "task.cancel", id: msg.id }).catch(() => {});
          p.reject(new ExtError("cancelled", "cancelled by backend"));
        }
      }
      break;
    case "record.set":
      if (msg.enabled) recording.add(msg.platform);
      else recording.delete(msg.platform);
      await pushCaptureConfig(msg.platform);
      break;
  }
}

// ---- tabs -----------------------------------------------------------------------

async function tabsForPlatform(def: PlatformDef): Promise<chrome.tabs.Tab[]> {
  const all = await chrome.tabs.query({});
  return all.filter((t) => {
    if (!t.url || t.id == null) return false;
    try {
      return hostMatches(def, new URL(t.url).hostname);
    } catch {
      return false;
    }
  });
}

async function isLoggedIn(def: PlatformDef): Promise<boolean> {
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

async function broadcastTabStates(force = false): Promise<void> {
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

function scheduleTabStates(): void {
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
function waitTabNavigated(tabId: number, timeoutMs: number): Promise<void> {
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

async function sendToTab(tabId: number, msg: BgToContent): Promise<{ ok: boolean; doc?: string; page_build?: string | null } | undefined> {
  return chrome.tabs.sendMessage(tabId, msg);
}

/**
 * Resolves with the document id once the tab's content script answers. With `notDoc`, keeps
 * polling until a *different* document answers: Chrome updates a tab's URL when a navigation
 * starts, while the old document (and its content script) may still be alive for a while.
 */
async function waitContentReady(tabId: number, timeoutMs = 10_000, notDoc?: string): Promise<string> {
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

const tabPlatform = new Map<number, string>();

function captureEnabledForTab(tabId: number): boolean {
  const pid = tabPlatform.get(tabId);
  return !!pid && recording.has(pid);
}

async function pushCaptureConfig(platformId: string): Promise<void> {
  const def = platformById(platformId);
  if (!def) return;
  for (const t of await tabsForPlatform(def)) {
    sendToTab(t.id!, { type: "capture.config", enabled: recording.has(platformId) }).catch(() => {});
  }
}

async function findOrOpenTab(def: PlatformDef): Promise<number> {
  const tabs = await tabsForPlatform(def);
  const ready = tabs.filter((t) => t.status === "complete" && !t.discarded);
  const ours = (id: number) => helperTabs.has(id) || sessionTabs.has(id);
  // Our own helper / session tabs first (keeps the user's tabs untouched), then the user's, most recent first.
  ready.sort((a, b) => Number(ours(b.id!)) - Number(ours(a.id!)) || Number(b.active) - Number(a.active) || (b.lastAccessed ?? 0) - (a.lastAccessed ?? 0));
  // Tabs opened before the extension was (re)loaded have no live content script; skip them.
  for (const t of ready.slice(0, 4)) {
    const reachable = await waitContentReady(t.id!, 1_500).then(() => true, () => false);
    remoteLog("info", "tab probe", { platform: def.id, tab: t.id, url: (t.url ?? "").slice(0, 60), reachable });
    if (reachable) {
      const h = helperTabs.get(t.id!);
      if (h) h.lastUsed = Date.now();
      return t.id!;
    }
  }
  // No usable tab: open one helper tab per platform in the work window (never in the user's
  // window), reuse it for later in-tab calls, and let the idle sweep close it.
  for (const [tabId, h] of helperTabs) {
    if (h.platform === def.id) {
      helperTabs.delete(tabId);
      await chrome.tabs.remove(tabId).catch(() => {}); // unreachable (stale build / discarded): replace it
    }
  }
  log.info("opening tab for", def.id);
  remoteLog("info", "opening helper tab", { platform: def.id, ready_tabs: ready.length, all_tabs: tabs.length });
  const tab = await createInWorkWindow(def.homeUrl, false);
  helperTabs.set(tab.id!, { platform: def.id, lastUsed: Date.now() });
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

// ---- work window ------------------------------------------------------------------------
// Temporary tabs live in their own window so (1) the user's window is never touched and
// (2) the active tab there is a *visible* document: IntersectionObserver-driven infinite
// scroll and requestAnimationFrame do not run in hidden tabs. The window is created unfocused
// and off to the side; Chrome may clamp the position onto the screen.

let workWindowId: number | null = null;

async function workWindowAlive(): Promise<number | null> {
  if (workWindowId == null) return null;
  const ok = await chrome.windows.get(workWindowId).then(() => true, () => false);
  if (!ok) workWindowId = null;
  return workWindowId;
}

/** Open `url` in the work window; the window is created around the first tab (no placeholder). */
async function createInWorkWindow(url: string, active: boolean): Promise<chrome.tabs.Tab> {
  const windowId = await workWindowAlive();
  if (windowId != null) return chrome.tabs.create({ windowId, url, active });
  // Explicit bounds can be rejected ("must be at least 50% within visible screen space") on
  // small or scaled displays; let Chrome pick defaults and only then try to shrink it.
  const w = await chrome.windows.create({ url, focused: false, state: "normal" });
  workWindowId = w.id!;
  chrome.windows.update(workWindowId, { width: 1000, height: 1000, left: 0, top: 0 }).catch(() => {});
  log.info("work window created", workWindowId);
  const tab = w.tabs?.[0] ?? (await chrome.tabs.query({ windowId: workWindowId }))[0];
  return tab;
}

chrome.windows.onRemoved.addListener((id) => {
  if (id === workWindowId) workWindowId = null;
});

async function openWorkTab(url: string): Promise<chrome.tabs.Tab> {
  return createInWorkWindow(url, true);
}

// ---- session tabs (kept open by navigate + keep_tab, reused for scroll pagination) ------

// Tabs the extension owns. Session tabs: kept by navigate + keep_tab for cursor pagination.
// Helper tabs: one per platform for in-tab calls when no usable tab exists. Both live in the
// work window and are closed after SESSION_IDLE_MS unused; the user's own tabs are never closed.
const sessionTabs = new Map<number, { platform: string; lastUsed: number }>();
const helperTabs = new Map<number, { platform: string; lastUsed: number }>();
const SESSION_IDLE_MS = 5 * 60_000;
const SESSION_MAX_PER_PLATFORM = 3; // beyond this the least recently used session tab is closed
const SESSION_MAX_TOTAL = 8; // across all platforms

function withTab(value: unknown, tabId: number | undefined): unknown {
  if (tabId == null) return value;
  return value && typeof value === "object" && !Array.isArray(value) ? { ...(value as object), _tab: tabId } : { value, _tab: tabId };
}

/** Keep only the most recently used session tabs of a platform; old cursors then expire. */
async function trimSessionTabs(platform: string): Promise<void> {
  const mine = [...sessionTabs].filter(([, s]) => s.platform === platform).sort((a, b) => b[1].lastUsed - a[1].lastUsed);
  for (const [tabId] of mine.slice(SESSION_MAX_PER_PLATFORM)) {
    sessionTabs.delete(tabId);
    await chrome.tabs.remove(tabId).catch(() => {});
    log.debug("closed surplus session tab", tabId, platform);
  }
  const all = [...sessionTabs].sort((a, b) => b[1].lastUsed - a[1].lastUsed);
  for (const [tabId, s] of all.slice(SESSION_MAX_TOTAL)) {
    sessionTabs.delete(tabId);
    await chrome.tabs.remove(tabId).catch(() => {});
    log.debug("closed surplus session tab (total cap)", tabId, s.platform);
  }
}

async function gcSessionTabs(): Promise<void> {
  const now = Date.now();
  for (const map of [sessionTabs, helperTabs]) {
    for (const [tabId, s] of map) {
      if (now - s.lastUsed > SESSION_IDLE_MS) {
        map.delete(tabId);
        await chrome.tabs.remove(tabId).catch(() => {});
        log.debug("closed idle tab", tabId, s.platform);
      }
    }
  }
  // Nothing of ours left in the work window (only the placeholder, or tabs we no longer track
  // and no task is running): close the window so it does not linger on the user's desktop.
  if (workWindowId != null && pendingPage.size === 0) {
    const tabs = await chrome.tabs.query({ windowId: workWindowId }).catch(() => []);
    if (tabs.every((t) => !sessionTabs.has(t.id!) && !helperTabs.has(t.id!))) {
      const id = workWindowId;
      workWindowId = null;
      chrome.windows.remove(id).catch(() => {});
      log.debug("closed empty work window", id);
    }
  }
}
chrome.tabs.onRemoved.addListener((id) => {
  sessionTabs.delete(id);
  helperTabs.delete(id);
});

function sameUrl(a: string, b: string): boolean {
  try {
    const ua = new URL(a);
    const ub = new URL(b);
    ua.hash = ub.hash = "";
    ua.searchParams.sort();
    ub.searchParams.sort();
    return ua.href.replace(/\/$/, "") === ub.href.replace(/\/$/, "");
  } catch {
    return a === b;
  }
}

/** A live session tab of this platform whose document is still on `url` (no in-page navigation since). */
async function findSessionTab(platform: string, url: string): Promise<number | null> {
  for (const [tabId, s] of [...sessionTabs].sort((a, b) => b[1].lastUsed - a[1].lastUsed)) {
    if (s.platform !== platform) continue;
    const tab = await chrome.tabs.get(tabId).catch(() => null);
    // tab.url is the committed document; a still-"loading" status only means late resources.
    if (!(tab?.url && !tab.pendingUrl && sameUrl(tab.url, url))) continue;
    // A tab whose content script is gone (extension reloaded meanwhile) cannot be reused.
    const reachable = await waitContentReady(tabId, 1_500).then(() => true, () => false);
    if (reachable) return tabId;
    sessionTabs.delete(tabId);
    chrome.tabs.remove(tabId).catch(() => {});
  }
  return null;
}

// ---- task execution ----------------------------------------------------------------

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
    return { echo: task.params.payload ?? null, via: "background", extension_version: VERSION, build: BUILD, open_tabs: tabs.length, work_window: workWindowId };
  }
  const def = platformById(task.platform);
  if (!def) throw new ExtError("unknown_platform", `extension has no adapter for ${task.platform}`);
  if (def.loginRequired !== false && !task.params.allow_anonymous && !(await isLoggedIn(def))) {
    throw new ExtError("not_logged_in", `未登录${def.name}：${def.loginHint}`, { login_url: def.loginUrl, platform: def.id });
  }
  // Continue in a tab kept open by an earlier navigate (pagination by scrolling).
  if (typeof task.params._tab === "number") {
    const session = sessionTabs.get(task.params._tab);
    const alive = session && (await chrome.tabs.get(task.params._tab).then(() => true, () => false));
    if (!alive) throw new ExtError("cursor_expired", "the tab behind this cursor is gone; start again without a cursor");
    session!.lastUsed = Date.now();
    await chrome.tabs.update(task.params._tab, { active: true }).catch(() => {}); // must be visible to load more
    await waitContentReady(task.params._tab, 5_000);
    const value = await executeInTab(task.params._tab, task);
    return withTab(value, task.params._tab);
  }

  const tabId = await findOrOpenTab(def);
  log.debug("task", task.id, "using tab", tabId);
  if (cancelledTasks.delete(task.id)) throw new ExtError("cancelled", "cancelled");

  if (task.strategy === "navigate" && typeof task.params.url === "string") {
    // Dedicated tab in the work window: a fresh, visible document every time, nothing the
    // user is looking at gets navigated away, and pages with unload handlers cannot block us.
    let since = Date.now();
    const deadline = since + task.timeout_ms - 1000;
    // A session tab already sitting on this URL (comments -> replies -> replies of one post) is
    // reused instead of loading the page again: fewer page loads is what keeps risk control quiet.
    // Its ring buffer still holds the earlier responses, so the action waits from time 0.
    const reused = await findSessionTab(def.id, task.params.url);
    let navTabId: number;
    let ownTab = false;
    if (reused != null) {
      navTabId = reused;
      since = 0;
      sessionTabs.get(navTabId)!.lastUsed = Date.now();
      await chrome.tabs.update(navTabId, { active: true }).catch(() => {});
      remoteLog("info", "navigate: reusing session tab", { task_id: task.id, tab: navTabId, url: String(task.params.url).slice(0, 80) });
    } else {
      remoteLog("info", "navigate: opening work tab", { task_id: task.id, url: String(task.params.url).slice(0, 80) });
      const navTab = await openWorkTab(task.params.url);
      navTabId = navTab.id!;
      ownTab = true;
      remoteLog("info", "navigate: work tab created", { task_id: task.id, tab: navTabId, window: navTab.windowId });
    }
    try {
      let doc = await waitContentReady(navTabId, Math.min(20_000, task.timeout_ms));
      log.debug("navigate: document", doc.slice(0, 8), "reachable after", Date.now() - since, "ms in tab", navTabId);
      if (task.params.keep_tab && ownTab) {
        sessionTabs.set(navTabId, { platform: def.id, lastUsed: Date.now() });
        await trimSessionTabs(def.id);
      }
      const pattern = task.params.capture_pattern;
      const pageAction = typeof task.params.page_action === "string" ? task.params.page_action : undefined;
      if (pageAction) {
        // Run a page action in the navigated document instead of waiting for a capture.
        // The action decides how long to wait (e.g. read_global with wait_ms). Sites with an
        // interstitial ("Please wait..." bot checks, login bounces) replace the document after
        // load, which would strand the action: re-issue it in the new document when that happens.
        const pageParams = { ...((task.params.page_params as Record<string, unknown>) ?? {}), since };
        let attempt = 0;
        while (Date.now() < deadline) {
          const runId = attempt === 0 ? task.id : `${task.id}:${doc.slice(0, 8)}`;
          const running = executeInTab(navTabId, { ...task, id: runId, action: pageAction, params: pageParams });
          const replaced = waitContentReady(navTabId, deadline - Date.now(), doc).then((d) => ({ replacedBy: d }));
          const outcome = await Promise.race([running.then((v) => ({ value: v })), replaced]);
          if ("value" in outcome) return withTab(outcome.value, task.params.keep_tab ? navTabId : undefined);
          pendingPage.delete(runId);
          sendToTab(navTabId, { type: "task.cancel", id: runId }).catch(() => {});
          doc = outcome.replacedBy;
          attempt++;
          remoteLog("info", "navigate: document replaced, re-running page action", { task_id: task.id, tab: navTabId, doc: doc.slice(0, 8), attempt });
        }
        throw new ExtError("timeout", `page action ${pageAction} did not finish before the navigation settled`);
      }
      if (typeof pattern !== "string") {
        return withTab({ navigated: task.params.url }, task.params.keep_tab ? navTabId : undefined);
      }
      // A site may chain documents (redirects, interstitials). Wait in the current document, but
      // if it gets replaced before a match arrives, re-issue the wait in the new one.
      while (Date.now() < deadline) {
        const remaining = deadline - Date.now();
        const waitId = `${task.id}:${doc.slice(0, 8)}`;
        const waiting = executeInTab(navTabId, { ...task, id: waitId, action: "wait_capture", params: { pattern, since, timeout_ms: remaining } });
        const replaced = waitContentReady(navTabId, remaining, doc).then((d) => ({ replacedBy: d }));
        const outcome = await Promise.race([waiting.then((v) => ({ value: v })), replaced]);
        if ("value" in outcome) return withTab(outcome.value, task.params.keep_tab ? navTabId : undefined);
        pendingPage.delete(waitId);
        sendToTab(navTabId, { type: "task.cancel", id: waitId }).catch(() => {});
        doc = outcome.replacedBy;
        log.debug("navigate: document replaced, re-waiting in", doc.slice(0, 8));
      }
      throw new ExtError("timeout", `no captured response matching ${pattern} before the navigation settled`);
    } finally {
      if (!task.params.keep_tab && ownTab) chrome.tabs.remove(navTabId).catch(() => {});
    }
  }
  return executeInTab(tabId, task);
}

async function runTask(task: TaskSpec): Promise<void> {
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
      const p = pendingPage.get(msg.id);
      if (p) {
        pendingPage.delete(msg.id);
        msg.ok ? p.resolve(msg.payload) : p.reject(new ExtError(msg.error?.code ?? "extension_error", msg.error?.message ?? "page error", msg.error?.details));
      }
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
        .then(() => {
          if (ws) ws.close(1000, "config changed");
          reconnectDelay = 1000;
          return connect();
        })
        .then(() => sendResponse({ ok: true }));
      return true;
    case "popup.reconnect":
      reconnectDelay = 1000;
      if (ws) ws.close(1000, "manual reconnect");
      void connect().then(() => sendResponse({ ok: true }));
      return true;
    case "popup.resume": {
      const cfg = currentConfig;
      const base = httpBase(cfg?.backendUrl ?? DEFAULT_BACKEND);
      void fetch(`${base}/api/v1/${msg.platform}/resume`, { method: "POST" })
        .then((r) => sendResponse({ ok: r.ok }))
        .catch((e) => sendResponse({ ok: false, error: String(e) }));
      return true;
    }
  }
  return false;
});

chrome.tabs.onRemoved.addListener((id) => tabPlatform.delete(id));

async function buildStatus(): Promise<ExtStatus> {
  const cfg = currentConfig ?? (await loadConfig());
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
  if (connected) {
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
    connected,
    backendUrl: cfg.backendUrl,
    hasToken: !!cfg.token,
    backendVersion,
    lastError,
    platforms: platformStates,
    pendingTasks: pendingPage.size,
    currentTab,
    alerts,
    build: BUILD,
  };
}

/** ws://host:port/ws/extension -> http://host:port */
function httpBase(wsUrl: string): string {
  try {
    const u = new URL(wsUrl);
    return `${u.protocol === "wss:" ? "https" : "http"}://${u.host}`;
  } catch {
    return "http://127.0.0.1:17800";
  }
}

// ---- lifecycle -----------------------------------------------------------------------

// Dev hook used by scripts/e2e_chrome.py after seeding chrome.storage; harmless otherwise.
(self as unknown as { __sociallens: unknown }).__sociallens = {
  reconnect: () => {
    reconnectDelay = 1000;
    if (ws) ws.close(1000, "dev reconnect");
    return connect();
  },
  status: buildStatus,
};

chrome.alarms.create(ALARM, { periodInMinutes: 0.5 });
chrome.alarms.onAlarm.addListener((a) => {
  if (a.name !== ALARM) return;
  if (!connected) void connect();
  void gcSessionTabs();
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
