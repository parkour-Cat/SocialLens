import { log } from "../shared/log";

// The work window: the separate window every tab the extension opens lives in.
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

// The window stays open between tasks: every fresh window Chrome creates lands on top of whatever
// the user is doing, so it is created once, holds a pinned placeholder page (work.html) so closing
// our last tab does not close it, and later tasks only add tabs, which does not raise the window.
// Its bounds are remembered, so once moved aside (or to another screen) it stays there.
const WORK_PAGE = chrome.runtime.getURL("work.html");
type Bounds = { left: number; top: number; width: number; height: number };
let boundsTimer: ReturnType<typeof setTimeout> | null = null;

async function savedBounds(): Promise<Bounds | null> {
  const s = await chrome.storage.local.get("workWindowBounds");
  const b = s.workWindowBounds as Bounds | undefined;
  return b && Number.isFinite(b.width) && b.width >= 400 ? b : null;
}

/** Open `url` in the work window, creating the window (unfocused, with the placeholder) when needed. */
export async function createInWorkWindow(url: string, active: boolean, index?: number): Promise<chrome.tabs.Tab> {
  const windowId = await workWindowAlive();
  if (windowId != null) {
    await restoreWorkWindow();
    return chrome.tabs.create({ windowId, url, active, ...(index != null ? { index } : {}) });
  }
  const bounds = await savedBounds();
  // Explicit bounds can be rejected ("must be at least 50% within visible screen space") on
  // small or scaled displays: fall back to Chrome's defaults, then try to resize.
  const w = await chrome.windows.create({ url, focused: false, state: "normal", ...(bounds ?? {}) }).catch(() => chrome.windows.create({ url, focused: false, state: "normal" }));
  workWindowId = w.id!;
  if (!bounds) chrome.windows.update(workWindowId, { width: 1000, height: 800, left: 0, top: 0 }).catch(() => {});
  const tab = w.tabs?.[0] ?? (await chrome.tabs.query({ windowId: workWindowId }))[0];
  chrome.tabs.create({ windowId: workWindowId, url: WORK_PAGE, active: false, index: 0, pinned: true }).catch(() => {});
  log.info("work window created", workWindowId);
  return tab;
}

chrome.windows.onRemoved.addListener((id) => {
  if (id === workWindowId) workWindowId = null;
});
chrome.windows.onBoundsChanged.addListener((w) => {
  if (w.id !== workWindowId || w.state !== "normal" || !w.width || !w.height) return;
  if (boundsTimer) clearTimeout(boundsTimer);
  boundsTimer = setTimeout(() => {
    void chrome.storage.local.set({ workWindowBounds: { left: w.left ?? 0, top: w.top ?? 0, width: w.width!, height: w.height! } });
  }, 500);
});

export async function openWorkTab(url: string, index?: number): Promise<chrome.tabs.Tab> {
  return createInWorkWindow(url, true, index);
}



/** Bring the work window back when it was minimized: hidden tabs stop loading more. */
async function restoreWorkWindow(): Promise<void> {
  const windowId = await workWindowAlive();
  if (windowId == null) return;
  const w = await chrome.windows.get(windowId).catch(() => null);
  if (w?.state === "minimized") await chrome.windows.update(windowId, { state: "normal", focused: false }).catch(() => {});
}

export function getWorkWindowId(): number | null {
  return workWindowId;
}
