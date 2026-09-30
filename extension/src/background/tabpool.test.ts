import { describe, expect, it } from "vitest";

import { SESSION_IDLE_MS, SESSION_MAX_PER_PLATFORM, SESSION_MAX_TOTAL, TabPool, sameUrl, tabGroup, type PoolTab } from "./tabpool";

/** A fake Chrome: tabs by id, which of them answer, and what got removed. */
function fake(opts: { tabs?: Record<number, Partial<PoolTab>>; unreachable?: number[] } = {}) {
  const removed: number[] = [];
  let clock = 1_000_000;
  const tabs: Record<number, Partial<PoolTab>> = { ...(opts.tabs ?? {}) };
  const unreachable = new Set(opts.unreachable ?? []);
  const pool = new TabPool({
    getTab: async (id) => (id in tabs ? ({ id, ...tabs[id] } as PoolTab) : null),
    removeTab: async (id) => {
      removed.push(id);
    },
    reachable: async (id) => !unreachable.has(id),
    now: () => clock,
  });
  return { pool, removed, tabs, unreachable, tick: (ms: number) => (clock += ms) };
}

describe("sameUrl / tabGroup", () => {
  it("ignores hash, query order and trailing slash", () => {
    expect(sameUrl("https://x.com/a?b=1&a=2#top", "https://x.com/a?a=2&b=1")).toBe(true);
    expect(sameUrl("https://x.com/a/", "https://x.com/a")).toBe(true);
    expect(sameUrl("https://x.com/a?b=1", "https://x.com/a?b=2")).toBe(false);
    expect(sameUrl("not a url", "not a url")).toBe(true);
  });
  it("puts every search action in one group", () => {
    expect(tabGroup("search_posts")).toBe(tabGroup("search_users"));
    expect(tabGroup("get_comments")).not.toBe(tabGroup("search_posts"));
  });
});

describe("findReusableTab", () => {
  it("prefers a session tab of the same action group over the helper", async () => {
    const { pool } = fake();
    pool.addHelper(1, "douyin");
    pool.addSession(2, "douyin", "search_posts");
    expect(await pool.findReusableTab("douyin", "search_users", true)).toBe(2);
    expect(await pool.findReusableTab("douyin", "get_comments", true)).toBe(1);
  });

  it("never hands a session tab to a task that will not keep it", async () => {
    const { pool } = fake();
    pool.addSession(2, "douyin", "search_posts");
    expect(await pool.findReusableTab("douyin", "get_post", false)).toBeNull();
    pool.addHelper(1, "douyin");
    expect(await pool.findReusableTab("douyin", "get_post", false)).toBe(1);
  });

  it("stays inside the platform", async () => {
    const { pool } = fake();
    pool.addHelper(1, "tiktok");
    pool.addSession(2, "tiktok", "search_posts");
    expect(await pool.findReusableTab("douyin", "search_posts", true)).toBeNull();
  });

  it("takes the least recently used session tab once the platform is at its cap", async () => {
    const { pool, tick } = fake();
    for (let i = 1; i <= SESSION_MAX_PER_PLATFORM; i++) {
      pool.addSession(i, "x", "get_comments");
      tick(1000);
    }
    expect(await pool.findReusableTab("x", "get_user_posts", true)).toBe(1);
    pool.addSession(9, "x", "get_comments"); // fourth of another kind: the cap says take the oldest
    expect(await pool.findReusableTab("x", "get_feed", true)).toBe(1);
  });

  it("skips busy tabs and closes unreachable ones", async () => {
    const { pool, removed, unreachable } = fake({ unreachable: [2] });
    pool.addSession(2, "x", "search_posts"); // content script gone
    pool.addSession(3, "x", "search_posts");
    pool.busy.add(3);
    expect(await pool.findReusableTab("x", "search_posts", true)).toBeNull();
    expect(removed).toEqual([2]);
    expect(pool.sessionTabs.has(2)).toBe(false);
    unreachable.clear();
    pool.busy.delete(3);
    expect(await pool.findReusableTab("x", "search_posts", true)).toBe(3);
  });
});

describe("findSessionTab", () => {
  it("returns the session tab whose committed document is on the url", async () => {
    const { pool, tabs } = fake({ tabs: { 5: { url: "https://x.com/explore?a=1" }, 6: { url: "https://x.com/explore", pendingUrl: "https://x.com/other" } } });
    pool.addSession(5, "x", "get_trending");
    pool.addSession(6, "x", "get_trending");
    expect(await pool.findSessionTab("x", "https://x.com/explore?a=1#h")).toBe(5);
    expect(await pool.findSessionTab("x", "https://x.com/explore")).toBeNull(); // 6 is mid-navigation
    tabs[6] = { url: "https://x.com/explore" };
    expect(await pool.findSessionTab("x", "https://x.com/explore")).toBe(6);
  });
});

describe("closing tabs", () => {
  it("excludes a tab being closed until Chrome confirms the removal", async () => {
    const { pool } = fake();
    pool.addHelper(1, "bilibili");
    await pool.closeTab(1);
    expect(pool.isClosing(1)).toBe(true);
    expect(pool.owns(1)).toBe(false);
    expect(await pool.findReusableTab("bilibili", "get_post", false)).toBeNull();
    pool.forget(1);
    expect(pool.isClosing(1)).toBe(false);
  });
});

describe("housekeeping", () => {
  it("trims surplus session tabs per platform and in total", async () => {
    const { pool, removed, tick } = fake();
    for (let i = 1; i <= SESSION_MAX_PER_PLATFORM + 2; i++) {
      pool.addSession(i, "x", "search_posts");
      tick(1);
    }
    await pool.trimSessionTabs("x");
    expect([...removed].sort()).toEqual([1, 2]); // the two oldest
    expect(pool.sessionTabs.size).toBe(SESSION_MAX_PER_PLATFORM);
    removed.length = 0;
    let id = 100;
    for (const p of ["a", "b", "c", "d"]) for (let i = 0; i < 2; i++) pool.addSession(id++, p, "get_feed");
    await pool.trimSessionTabs("d");
    expect(pool.sessionTabs.size).toBe(SESSION_MAX_TOTAL);
  });

  it("closes idle tabs but not busy ones", async () => {
    const { pool, removed, tick } = fake();
    pool.addSession(1, "x", "search_posts");
    pool.addHelper(2, "x");
    pool.addSession(3, "x", "get_feed");
    pool.busy.add(3);
    tick(SESSION_IDLE_MS + 1);
    await pool.gcSessionTabs();
    expect(removed.sort()).toEqual([1, 2]);
    expect(pool.sessionTabs.has(3)).toBe(true);
  });

  it("touch keeps a tab alive", async () => {
    const { pool, removed, tick } = fake();
    pool.addSession(1, "x", "search_posts");
    tick(SESSION_IDLE_MS - 10);
    pool.touch(1);
    tick(20);
    await pool.gcSessionTabs();
    expect(removed).toEqual([]);
  });
});

describe("cursor keys", () => {
  it("binds a cursor to the tab and the document it showed", () => {
    const { pool } = fake();
    pool.addSession(7, "x", "search_posts");
    const key = pool.cursorKeyFor(7, "doc-a");
    expect(pool.cursorKeyFor(7, "doc-a")).toBe(key); // same page, same key
    expect(pool.cursorKeyFor(7, "doc-b")).not.toBe(key); // replaced document, new key
    expect(pool.resolveCursor(key)).toEqual({ tabId: 7, doc: "doc-a" });
    expect(pool.withTab({ items: [] }, key)).toEqual({ items: [], _tab: key });
    expect(pool.withTab([1, 2], key)).toEqual({ value: [1, 2], _tab: key });
    expect(pool.withTab({ a: 1 }, undefined)).toEqual({ a: 1 });
  });

  it("expires once the tab is closed or no longer a session tab", async () => {
    const { pool } = fake();
    pool.addSession(7, "x", "search_posts");
    const key = pool.cursorKeyFor(7, "doc-a");
    await pool.closeTab(7);
    expect(pool.resolveCursor(key)).toBeNull();
    pool.forget(7);
    expect(pool.resolveCursor(key)).toBeNull();
    expect(pool.resolveCursor(12345)).toBeNull();
  });

  it("a replaced tab keeps the old key resolvable to the old document, so the caller can tell", () => {
    const { pool } = fake();
    pool.addSession(7, "x", "search_posts");
    const old = pool.cursorKeyFor(7, "doc-a");
    pool.addSession(7, "x", "search_users"); // same tab id taken over by another page
    expect(pool.resolveCursor(old)?.doc).toBe("doc-a"); // != the tab's current document -> cursor_expired
  });
});
