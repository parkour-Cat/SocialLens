// Bookkeeping of the tabs the extension owns, kept free of chrome.* so it can be unit-tested:
// which tab a navigate task may take over, when idle or surplus tabs get closed, and the cursor
// keys that bind a pagination cursor to one tab *and* the document it showed.
//
// Session tabs: kept open by navigate + keep_tab so cursor pagination can scroll them.
// Helper tabs: one per platform for in-tab calls when no usable tab exists.
// Both live in the work window; the user's own tabs are never touched.

export const SESSION_IDLE_MS = 5 * 60_000;
export const SESSION_MAX_PER_PLATFORM = 3; // beyond this the least recently used session tab is closed
export const SESSION_MAX_TOTAL = 8; // across all platforms
const CURSOR_KEYS_MAX = 500;

export interface PoolTab {
  id: number;
  url?: string;
  pendingUrl?: string;
  index?: number;
  windowId?: number;
}

export interface PoolDeps {
  getTab(tabId: number): Promise<PoolTab | null>;
  removeTab(tabId: number): Promise<void>;
  /** Does the tab's content script (of this build) answer? */
  reachable(tabId: number): Promise<boolean>;
  now?: () => number;
  log?: (msg: string, ...args: unknown[]) => void;
}

export interface SessionTab {
  platform: string;
  lastUsed: number;
  action?: string;
}

export interface HelperTab {
  platform: string;
  lastUsed: number;
}

/** Actions that share one tab: any search replaces the previous search page. */
export const tabGroup = (action: string): string => (action.startsWith("search_") ? "search" : action);

export function sameUrl(a: string, b: string): boolean {
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

export class TabPool {
  readonly sessionTabs = new Map<number, SessionTab>();
  readonly helperTabs = new Map<number, HelperTab>();
  /** Tabs with a navigate task in flight: never taken over or handed a cursor continuation. */
  readonly busy = new Set<number>();
  // Tabs we asked Chrome to close; tabs.query still lists them for a moment, and a task sent
  // there dies with "Receiving end does not exist".
  private readonly closing = new Set<number>();
  // What goes out as `_tab` (and comes back inside a cursor) is a key naming a tab *and* the
  // document it showed at the time. Owned tabs get replaced when a later task takes them over,
  // so a bare tab id would let an old cursor scroll a page that shows something else.
  private cursorSeq = 0;
  private readonly cursorKeys = new Map<number, { tabId: number; doc: string }>();
  private readonly now: () => number;
  private readonly log: (msg: string, ...args: unknown[]) => void;

  constructor(private readonly deps: PoolDeps) {
    this.now = deps.now ?? (() => Date.now());
    this.log = deps.log ?? (() => {});
  }

  // ---- membership --------------------------------------------------------

  addSession(tabId: number, platform: string, action?: string): void {
    this.helperTabs.delete(tabId);
    this.sessionTabs.set(tabId, { platform, lastUsed: this.now(), action });
  }

  addHelper(tabId: number, platform: string): void {
    this.helperTabs.set(tabId, { platform, lastUsed: this.now() });
  }

  touch(tabId: number): void {
    const s = this.sessionTabs.get(tabId) ?? this.helperTabs.get(tabId);
    if (s) s.lastUsed = this.now();
  }

  owns(tabId: number): boolean {
    return this.sessionTabs.has(tabId) || this.helperTabs.has(tabId);
  }

  isClosing(tabId: number): boolean {
    return this.closing.has(tabId);
  }

  /** Close a tab we own (or borrowed); it stays excluded from lookups until Chrome confirms. */
  closeTab(tabId: number): Promise<void> {
    this.closing.add(tabId);
    this.sessionTabs.delete(tabId);
    this.helperTabs.delete(tabId);
    return this.deps.removeTab(tabId);
  }

  /** chrome.tabs.onRemoved: drop every record of the tab, including cursors into it. */
  forget(tabId: number): void {
    this.closing.delete(tabId);
    this.sessionTabs.delete(tabId);
    this.helperTabs.delete(tabId);
    this.busy.delete(tabId);
    for (const [key, c] of this.cursorKeys) if (c.tabId === tabId) this.cursorKeys.delete(key);
  }

  // ---- cursors -----------------------------------------------------------

  cursorKeyFor(tabId: number, doc: string): number {
    for (const [key, c] of this.cursorKeys) if (c.tabId === tabId && c.doc === doc) return key;
    if (this.cursorKeys.size >= CURSOR_KEYS_MAX) this.cursorKeys.delete(this.cursorKeys.keys().next().value!); // oldest first
    this.cursorKeys.set(++this.cursorSeq, { tabId, doc });
    return this.cursorSeq;
  }

  /** The tab and document a cursor key points at; null once the tab is gone or was never a session tab. */
  resolveCursor(key: number): { tabId: number; doc: string } | null {
    const c = this.cursorKeys.get(key);
    return c && this.sessionTabs.has(c.tabId) ? c : null;
  }

  withTab(value: unknown, key: number | undefined): unknown {
    if (key == null) return value;
    return value && typeof value === "object" && !Array.isArray(value) ? { ...(value as object), _tab: key } : { value, _tab: key };
  }

  // ---- housekeeping ------------------------------------------------------

  private sessionsOf(platform: string): [number, SessionTab][] {
    return [...this.sessionTabs].filter(([, s]) => s.platform === platform).sort((a, b) => b[1].lastUsed - a[1].lastUsed);
  }

  /** Keep only the most recently used session tabs of a platform; old cursors then expire. */
  async trimSessionTabs(platform: string): Promise<void> {
    for (const [tabId] of this.sessionsOf(platform).slice(SESSION_MAX_PER_PLATFORM)) {
      await this.closeTab(tabId);
      this.log("closed surplus session tab", tabId, platform);
    }
    const all = [...this.sessionTabs].sort((a, b) => b[1].lastUsed - a[1].lastUsed);
    for (const [tabId, s] of all.slice(SESSION_MAX_TOTAL)) {
      await this.closeTab(tabId);
      this.log("closed surplus session tab (total cap)", tabId, s.platform);
    }
  }

  /** Close session and helper tabs unused for SESSION_IDLE_MS. The work window itself stays open. */
  async gcSessionTabs(): Promise<void> {
    const now = this.now();
    for (const map of [this.sessionTabs, this.helperTabs] as Map<number, { platform: string; lastUsed: number }>[]) {
      for (const [tabId, s] of [...map]) {
        if (now - s.lastUsed > SESSION_IDLE_MS && !this.busy.has(tabId)) {
          await this.closeTab(tabId);
          this.log("closed idle tab", tabId, s.platform);
        }
      }
    }
  }

  // ---- lookups -----------------------------------------------------------

  /** Reachable and not busy; an unreachable tab (extension reloaded meanwhile) is closed. */
  private async usable(tabId: number): Promise<boolean> {
    if (this.busy.has(tabId) || this.closing.has(tabId)) return false;
    const ok = await this.deps.reachable(tabId);
    if (!ok) void this.closeTab(tabId);
    return ok;
  }

  /** A live session tab of this platform whose document is still on `url` (no in-page navigation since). */
  async findSessionTab(platform: string, url: string): Promise<number | null> {
    for (const [tabId] of this.sessionsOf(platform)) {
      const tab = await this.deps.getTab(tabId);
      // tab.url is the committed document; a still-"loading" status only means late resources.
      if (!(tab?.url && !tab.pendingUrl && sameUrl(tab.url, url))) continue;
      if (await this.usable(tabId)) return tabId;
    }
    return null;
  }

  /**
   * An owned tab of this platform that a navigate task may take over (replace in place) instead
   * of opening another tab; the user wants one page per platform, not a new tab per search: a
   * session tab loaded by the same kind of action (a new search replaces the previous search
   * page; its cursor then expires), then the platform's helper tab, then, at the per-platform
   * cap, the least recently used session tab. Tasks without `keepTab` (get_post / get_user) only
   * take the helper tab so they never invalidate a pagination cursor. Null: open a fresh tab.
   */
  async findReusableTab(platform: string, action: string, keepTab: boolean): Promise<number | null> {
    const mine = this.sessionsOf(platform);
    if (keepTab) {
      for (const [tabId, s] of mine) if (s.action && tabGroup(s.action) === tabGroup(action) && (await this.usable(tabId))) return tabId;
    }
    for (const [tabId, h] of [...this.helperTabs]) if (h.platform === platform && (await this.usable(tabId))) return tabId;
    if (keepTab && mine.length >= SESSION_MAX_PER_PLATFORM) {
      for (const [tabId] of [...mine].reverse()) if (await this.usable(tabId)) return tabId;
    }
    return null;
  }
}
