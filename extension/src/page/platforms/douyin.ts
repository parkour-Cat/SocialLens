// 抖音 page actions. API notes: docs/platforms/douyin.md
// Query signatures (a_bogus / msToken) come from obfuscated page code, so the site does all
// requests itself; we capture responses and scroll for more. Endpoint paths are matched on
// their tail so version prefixes can change.
//
// Some page data is streamed into `window.__pace_f` as React-flight style records
// (`push([1, "<id>:<json>"])`); the visited user's profile lives there.

import { PageError } from "../errors";
import { expandReplies } from "./expand";
import { firstOrMore, more } from "./navigate";
import type { PageAction, PageActionContext, PagePlatform } from "./types";

/** Parsed JSON records from the page's streamed flight data. */
async function flightRecords(ctx: PageActionContext, waitMs = 8_000): Promise<unknown[]> {
  const chunks = (await ctx.readGlobal("__pace_f", waitMs)) as unknown[];
  const out: unknown[] = [];
  for (const ch of Array.isArray(chunks) ? chunks : []) {
    if (!Array.isArray(ch) || typeof ch[1] !== "string") continue;
    for (const rec of (ch[1] as string).split(/\n(?=[0-9a-f]+:)/)) {
      const m = /^[0-9a-f]+:([\[{].*)$/s.exec(rec);
      if (!m) continue;
      try {
        out.push(JSON.parse(m[1]));
      } catch {
        /* partial / non-JSON record */
      }
    }
  }
  return out;
}

function findObject(obj: unknown, pred: (o: Record<string, unknown>) => boolean, depth = 0): Record<string, unknown> | null {
  if (depth > 16 || obj == null || typeof obj !== "object") return null;
  if (!Array.isArray(obj) && pred(obj as Record<string, unknown>)) return obj as Record<string, unknown>;
  for (const v of Array.isArray(obj) ? obj : Object.values(obj as object)) {
    const r = findObject(v, pred, depth + 1);
    if (r) return r;
  }
  return null;
}

const searchPosts: PageAction = async (p, ctx) => firstOrMore(p, ctx, "/\\/(general\\/search\\/single|search\\/item)\\//");
const searchUsers: PageAction = async (p, ctx) => firstOrMore(p, ctx, "/\\/(discover\\/search|search\\/user)\\//");
const getPost: PageAction = async (p, ctx) => ctx.waitCapture("/aweme/detail/", typeof p.since === "number" ? p.since : 0);
const getComments: PageAction = async (p, ctx) => firstOrMore(p, ctx, "/comment/list/");
const getReplies: PageAction = (p, ctx) =>
  expandReplies(p, ctx, {
    listPattern: "/\\/comment\\/list\\/\\?/",
    extract: (body) => ((body as { body?: { comments?: { cid?: string; text?: string }[] } })?.body?.comments ?? []).map((c) => ({ id: String(c.cid ?? ""), text: String(c.text ?? "") })),
    replyPattern: (id) => `/comment\\/list\\/reply\\/\\?[^ ]*comment_id=${id}/`,
    expandRe: /^展开/,
  });
const getTrending: PageAction = async (p, ctx) => ctx.waitCapture("/hot/search/list/", typeof p.since === "number" ? p.since : 0);
const getUserPosts: PageAction = async (p, ctx) => {
  if (p.more) return more(ctx, "/aweme/post/");
  const since = typeof p.since === "number" ? p.since : 0;
  // Some profiles open on another tab (合集 / 直播回放) and only request the works list once
  // the 作品 tab is selected; click it when nothing arrives on its own.
  try {
    return await ctx.waitCapture("/aweme/post/", since, 8_000);
  } catch (e) {
    if (!(e instanceof PageError && e.code === "timeout")) throw e;
  }
  await ctx.clickText("作品", 3_000).catch(() => null);
  return ctx.waitCapture("/aweme/post/", since);
};
const getFeed: PageAction = async (p, ctx) => firstOrMore(p, ctx, "/\\/(tab|module)\\/feed\\//");

const getUser: PageAction = async (p, ctx) => {
  // The visited profile is streamed as {user: {statusCode, user: {...}}}; the logged-in user
  // appears elsewhere as {user: {info: {...}}} and must not be confused with it.
  const deadline = Date.now() + 15_000;
  for (;;) {
    const records = await flightRecords(ctx, 3_000).catch(() => []);
    for (const rec of records) {
      const hit = findObject(rec, (o) => typeof o.user === "object" && !!o.user && typeof (o.user as Record<string, unknown>).user === "object" && !!(o.user as Record<string, unknown>).user);
      if (hit) return { ssr: true, user: hit.user, href: location.href };
    }
    if (Date.now() > deadline) throw new PageError("not_found", "user profile not found in page data (private, banned, or page layout changed)");
    await new Promise((r) => setTimeout(r, 500));
  }
};

export const douyinPage: PagePlatform = {
  id: "douyin",
  hosts: [".douyin.com"],
  riskSignals: [/security\.douyin\.com/, /verify\.snssdk\.com/, /\/captcha\/(verify|get)/],
  actions: {
    search_posts: searchPosts,
    search_users: searchUsers,
    get_post: getPost,
    get_comments: getComments,
    get_user: getUser,
    get_user_posts: getUserPosts,
    get_feed: getFeed,
    get_replies: getReplies, get_trending: getTrending,
  },
};
