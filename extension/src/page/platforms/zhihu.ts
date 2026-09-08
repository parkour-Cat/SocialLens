// 知乎 page actions. API notes: docs/platforms/zhihu.md
// Requests carry the x-zse-96 signature, so the site issues them: navigate to the page and
// capture. Detail / profile / hot pages are server-rendered into <script id="js-initialData">.
// Findings (2026-09-07): the content search page renders its first 20 results server-side and
// only calls search_v3 on scroll, so search_posts opens the people tab (which does fetch) and
// clicks 综合 to make the site request the first page; comments only load after clicking the
// "N 条评论" button; the hot list is server-rendered (topstory.hotList), no request at all.

import { PageError } from "../errors";
import { expandReplies } from "./expand";
import { more } from "./navigate";
import type { PageAction, PageActionContext, PagePlatform } from "./types";

// #js-initialData can exceed the message size when decoded/cloned in the page; hand over the
// raw text and let the backend parse it.
const initialData = async (ctx: PageActionContext) => ctx.readElement("#js-initialData", { waitMs: 15_000 });
const SEARCH = "/api/v4/search_v3";
const ROOT_COMMENTS = "/\\/api\\/v4\\/comment_v5\\/(answers|articles|questions)\\/\\d+\\/root_comment/";

const searchPosts: PageAction = async (p, ctx) => {
  if (p.more) return more(ctx, `/search_v3\\?.*t=general/`);
  const since = typeof p.since === "number" ? p.since : 0;
  try {
    return await ctx.waitCapture(`/search_v3\\?.*t=general/`, since, 3_000);
  } catch (e) {
    if (!(e instanceof PageError && e.code === "timeout")) throw e;
  }
  const clickAt = Date.now();
  await ctx.clickText("综合", 10_000);
  return ctx.waitCapture(`/search_v3\\?.*t=general/`, clickAt, 20_000);
};
const searchUsers: PageAction = async (p, ctx) => (p.more ? more(ctx, `/search_v3\\?.*t=people/`) : ctx.waitCapture(`/search_v3\\?.*t=people/`, typeof p.since === "number" ? p.since : 0));

const getPost: PageAction = async (p, ctx) => {
  const text = await initialData(ctx).catch(() => null);
  if (!text) throw new PageError("not_found", "js-initialData not found on this page (deleted, or page changed)");
  return { ssr: true, text, href: location.href };
};

const getComments: PageAction = async (p, ctx) => {
  if (p.more) return more(ctx, ROOT_COMMENTS);
  const since = typeof p.since === "number" ? p.since : 0;
  try {
    return await ctx.waitCapture(ROOT_COMMENTS, since, 3_000);
  } catch (e) {
    if (!(e instanceof PageError && e.code === "timeout")) throw e;
  }
  const clickAt = Date.now();
  await ctx.clickText("/^\\d+ 条评论$/", 10_000); // the answer's own action bar button
  return ctx.waitCapture(ROOT_COMMENTS, clickAt, 20_000);
};

const stripTags = (s: string) => s.replace(/<[^>]+>/g, "").replace(/&nbsp;/g, " ").trim();
type ZhihuComment = { id?: unknown; content?: string; child_comment_count?: number; child_comments?: unknown[] };
const getReplies: PageAction = async (p, ctx) => {
  // The comment panel must be open first (same as getComments) so the root comment is rendered.
  if (!p.more) {
    const list = (await getComments({ ...p, more: undefined }, ctx).catch(() => null)) as { body?: { data?: ZhihuComment[] } } | null;
    const root = list?.body?.data?.find((c) => String(c.id) === String(p.comment_id));
    // root_comment already embeds the first child comments; when that is all of them there is
    // nothing to expand on the page.
    if (root && Array.isArray(root.child_comments) && root.child_comments.length >= (root.child_comment_count ?? 0)) {
      return { body: { data: root.child_comments, paging: { is_end: true } }, url: "inline://zhihu/child_comments", status: 200, method: "GET", kind: "fetch", ts: Date.now(), truncated: false, content_type: "application/json", _comment_id: String(p.comment_id) };
    }
  }
  return expandReplies(p, ctx, {
    listPattern: ROOT_COMMENTS,
    extract: (body) => ((body as { body?: { data?: { id?: unknown; content?: string }[] } })?.body?.data ?? []).map((c) => ({ id: String(c.id ?? ""), text: stripTags(String(c.content ?? "")) })),
    // every page is a plain fetch of child_comment (offset cursor); later pages load when the
    // modal's own scroll container (a hashed css-* class, so no fixed selector: scroll whatever
    // scrolls) reaches the bottom
    replyPattern: (id) => `/comment_v5\/comment\/${id}\/child_comment/`,
    expandRe: /查看全部|条回复|展开/,
    moreBy: "scroll",
  });
};

const getUser: PageAction = async (p, ctx) => ({ ssr: true, text: await initialData(ctx), href: location.href });
const USER_POSTS = "/\\/api\\/v4\\/members\\/[^/]+\\/(answers|articles)/";
const getUserPosts: PageAction = (p, ctx) => (p.more ? more(ctx, USER_POSTS) : ctx.waitCapture(USER_POSTS, typeof p.since === "number" ? p.since : 0));
const getFeed: PageAction = (p, ctx) => (p.more ? more(ctx, "/api/v3/feed/topstory/recommend") : ctx.waitCapture("/api/v3/feed/topstory/recommend", typeof p.since === "number" ? p.since : 0));
const getTrending: PageAction = async (p, ctx) => ({ ssr: true, text: await initialData(ctx), href: location.href });

export const zhihuPage: PagePlatform = {
  id: "zhihu",
  hosts: [".zhihu.com"],
  riskSignals: [/zhihu\.com\/account\/unhuman/, /\/api\/v4\/captcha/, /zhihu\.com\/signin/],
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
