// Reddit page actions. API notes: docs/platforms/reddit.md
// The classic JSON API: any reddit path + ".json" answers with the same data the old site
// rendered. No signature; the page's own cookies carry the login. Call strategy (in-tab fetch).

import { PageError } from "../errors";
import { intParam, param, type PageAction, type PageActionContext, type PagePlatform, type Params } from "./types";

const SITE = "https://www.reddit.com";

async function getJson(ctx: PageActionContext, path: string, query: Record<string, string | number | undefined> = {}): Promise<unknown> {
  const url = new URL(path.startsWith("http") ? path : SITE + path);
  url.searchParams.set("raw_json", "1");
  for (const [k, v] of Object.entries(query)) if (v !== undefined && v !== "") url.searchParams.set(k, String(v));
  const res = await ctx.fetch(url.toString(), { credentials: "include", headers: { accept: "application/json" } });
  if (res.status === 429) throw new PageError("rate_limited", "reddit answered 429 (too many requests)");
  if (res.status === 403) throw new PageError("not_logged_in", "reddit answered 403 (private or login required)");
  if (res.status === 404) throw new PageError("not_found", `reddit answered 404 for ${url.pathname}`);
  if (!res.ok) throw new PageError("extension_error", `reddit HTTP ${res.status} for ${url.pathname}`);
  return res.json();
}

function need(p: Params, key: string): string {
  const v = param(p, key);
  if (!v) throw new PageError("bad_request", `missing param: ${key}`);
  return v;
}

const searchPosts: PageAction = (p, ctx) => getJson(ctx, "/search.json", { q: need(p, "keyword"), type: "link", sort: param(p, "order") ?? "relevance", limit: 25, after: param(p, "after"), include_over_18: "on" });
const searchUsers: PageAction = (p, ctx) => getJson(ctx, "/search.json", { q: need(p, "keyword"), type: "user", limit: 25, after: param(p, "after") });
const getPost: PageAction = (p, ctx) => getJson(ctx, `/comments/${need(p, "id").replace(/^t3_/, "")}.json`, { limit: 1 });
// First page: the post's comment listing. Later pages: the ids the listing's "more" stub named,
// fetched 100 at a time through /api/morechildren (the backend keeps the remaining ids in the cursor).
const getComments: PageAction = (p, ctx) => {
  const post = need(p, "post_id").replace(/^t3_/, "");
  const children = param(p, "children");
  if (children) return getJson(ctx, "/api/morechildren.json", { api_type: "json", link_id: `t3_${post}`, children, sort: param(p, "mode") ?? "confidence", limit_children: "false" });
  return getJson(ctx, `/comments/${post}.json`, { sort: param(p, "mode") ?? "confidence", limit: 100, depth: 1 });
};
// One comment's subtree: /comments/{post}/_/{comment}.json (depth-limited to direct replies).
const getReplies: PageAction = (p, ctx) => getJson(ctx, `/comments/${need(p, "post_id").replace(/^t3_/, "")}/_/${need(p, "comment_id").replace(/^t1_/, "")}.json`, { limit: 100, depth: 2 });
const getUser: PageAction = (p, ctx) => getJson(ctx, `/user/${need(p, "id").replace(/^u\//, "")}/about.json`);
const getUserPosts: PageAction = (p, ctx) => getJson(ctx, `/user/${need(p, "id").replace(/^u\//, "")}/submitted.json`, { sort: param(p, "order") ?? "new", limit: 25, after: param(p, "after") });
// Logged in: the personalised home feed; anonymous: /best falls back to popular.
const getFeed: PageAction = (p, ctx) => getJson(ctx, "/best.json", { limit: 25, after: param(p, "after") });
const getTrending: PageAction = (p, ctx) => getJson(ctx, "/r/popular.json", { limit: intParam(p, "limit", 25), after: param(p, "after"), geo_filter: param(p, "geo") ?? "GLOBAL" });

export const redditPage: PagePlatform = {
  id: "reddit",
  hosts: [".reddit.com"],
  riskSignals: [/reddit\.com\/(?:r\/)?[^/]*\/?.*\/blocked/, /www\.reddit\.com\/challenge/],
  actions: {
    search_posts: searchPosts,
    search_users: searchUsers,
    get_post: getPost,
    get_comments: getComments,
    get_replies: getReplies,
    get_user: getUser,
    get_user_posts: getUserPosts,
    get_feed: getFeed,
    get_trending: getTrending,
  },
};
