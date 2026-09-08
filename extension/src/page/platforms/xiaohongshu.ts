// 小红书 page actions. API notes: docs/platforms/xiaohongshu.md
//
// The site signs every API call with a private, undecodable X-s-common header, so we never
// build requests ourselves. Each action runs inside a tab the background opened on the right
// URL (navigate strategy): the first page comes from the SSR state (window.__INITIAL_STATE__)
// or from the response the page fetches on load; further pages are triggered by scrolling
// the same tab (`more: true`, routed via the `_tab` cursor). The site does all the talking.
// Endpoint versions change (v1 -> v2 for search/notes); match on the path tail only.

import { PageError } from "../errors";
import { expandReplies } from "./expand";
import { firstOrMore, more } from "./navigate";
import type { PageAction, PagePlatform } from "./types";

const STATE = "__INITIAL_STATE__";

const searchPosts: PageAction = async (p, ctx) => {
  if (p.more) return more(ctx, "/search/notes");
  const since = typeof p.since === "number" ? p.since : 0;
  // Race the capture against the page's own search store: when the site's request fails
  // (risk control answers without CORS headers, so the browser sees a network error) the
  // store flips to "error" and nothing will ever be captured.
  const capture = ctx.waitCapture("/search/notes", since);
  const errored = (async () => {
    for (;;) {
      await new Promise((r) => setTimeout(r, 1000));
      const state = await ctx.readGlobal(`${STATE}.search.state`).catch(() => null);
      if (state === "error") throw new PageError("rate_limited", "小红书 search request failed in the page (state=error): likely risk control on search; wait and retry later");
    }
  })();
  return Promise.race([capture, errored]);
};
const searchUsers: PageAction = async (p, ctx) => {
  // The search page ignores `type=user` in the URL and always opens on 笔记; the user search
  // request (search/usersearch) is only made once the 用户 tab is clicked.
  if (p.more) return more(ctx, "/search/usersearch");
  const since = typeof p.since === "number" ? p.since : 0;
  try {
    return await ctx.waitCapture("/search/usersearch", since, 3_000);
  } catch (e) {
    if (!(e instanceof PageError && e.code === "timeout")) throw e;
  }
  const clickAt = Date.now();
  await ctx.clickText("用户", 8_000);
  return ctx.waitCapture("/search/usersearch", clickAt, 15_000);
};

const getPost: PageAction = async (p, ctx) => {
  // Note detail is server-rendered into the state; the map is keyed by note id.
  const id = String(p.id ?? "");
  const map = (await ctx.readGlobal(`${STATE}.note.noteDetailMap`, 15_000)) as Record<string, unknown> | null;
  const entry = map && (map[id] ?? Object.values(map)[0]);
  if (!entry) throw new PageError("not_found", `note ${id} not in page state (deleted, private, or xsec_token invalid)`);
  return { note_id: id, detail: entry, href: location.href };
};

const getComments: PageAction = async (p, ctx) => firstOrMore(p, ctx, "/comment/page");
const getReplies: PageAction = (p, ctx) =>
  expandReplies(p, ctx, {
    listPattern: "/comment/page",
    extract: (body) => ((body as { body?: { data?: { comments?: { id?: string; content?: string }[] } } })?.body?.data?.comments ?? []).map((c) => ({ id: String(c.id ?? ""), text: String(c.content ?? "") })),
    replyPattern: (id) => `/comment\\/sub\\/page\\?[^ ]*root_comment_id=${id}/`,
    expandRe: /^展开/,
    scrollSelector: ".note-scroller",
  });
const getTrending: PageAction = async (p, ctx) => {
  // The search box shows trending words once focused; the request is search/querytrending (or hot_list).
  const since = Date.now();
  await ctx.click("#search-input", 5_000).catch(() => null);
  return ctx.waitCapture("/\\/search\\/(querytrending|hot_list|trending)/", since, 15_000);
};

const getUser: PageAction = async (p, ctx) => {
  const user = await ctx.readGlobal(`${STATE}.user.userPageData`, 15_000);
  return { user, href: location.href };
};

const getUserPosts: PageAction = async (p, ctx) => {
  if (p.more) return more(ctx, "/user_posted");
  // First batch is server-rendered; the page only calls user_posted when scrolling.
  const notes = await ctx.readGlobal(`${STATE}.user.notes`, 15_000);
  const queries = await ctx.readGlobal(`${STATE}.user.noteQueries`, 2_000).catch(() => null);
  return { ssr: true, notes, queries, href: location.href };
};

const getFeed: PageAction = async (p, ctx) => {
  if (p.more) return more(ctx, "/homefeed");
  const feeds = await ctx.readGlobal(`${STATE}.feed.feeds`, 15_000);
  return { ssr: true, feeds, href: location.href };
};

export const xiaohongshuPage: PagePlatform = {
  id: "xiaohongshu",
  hosts: [".xiaohongshu.com"],
  // redcaptcha/v2/getconfig is fetched on every page load and is NOT a challenge; only the
  // verification endpoints and the login/captcha page mean the user is being challenged.
  riskSignals: [/xiaohongshu\.com\/website-login\/captcha/, /\/api\/redcaptcha\/v2\/(verify|check)/],
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
