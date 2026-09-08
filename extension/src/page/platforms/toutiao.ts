// 今日头条 page actions. API notes: docs/platforms/toutiao.md
// Every list endpoint carries a _signature the site computes itself, so nothing is called directly:
// pages are opened and the site's own responses captured (navigate strategy). Detail and profile
// pages are server-rendered into <script id="RENDER_DATA"> (URI-encoded JSON, decoded in the backend).

import { PageError } from "../errors";
import { expandReplies } from "./expand";
import { more } from "./navigate";
import type { PageAction, PageActionContext, PagePlatform, Params } from "./types";

const FEED = "/\\/api\\/pc\\/list\\/feed\\?/";
const USER_FEED = "/\\/api\\/pc\\/list\\/user\\/feed\\?/";
const COMMENTS = "/\\/article\\/v4\\/tab_comments\\//";
const HOT = "/hot-event/hot-board/";
const SEARCH_MORE = "/so\\.toutiao\\.com\\/search\\/\\?/"; // JSON pages loaded on scroll; page 1 is server-rendered
const DRAWER = '[class*="comment-drawer"]';
const since = (p: Params) => (typeof p.since === "number" ? p.since : 0);

const renderData = async (ctx: PageActionContext) => {
  const text = await ctx.readElement("#RENDER_DATA", { waitMs: 15_000 }).catch(() => null);
  if (!text) throw new PageError("not_found", "RENDER_DATA not found on this page (removed, or page changed)");
  return { ssr: true, text, href: location.href };
};

/** First page: the response the page fetches on load; if it was server-rendered instead, one scroll asks for the next. */
async function captureOrScroll(ctx: PageActionContext, pattern: string, from: number): Promise<unknown> {
  try {
    return await ctx.waitCapture(pattern, from, 5_000);
  } catch (e) {
    if (!(e instanceof PageError && e.code === "timeout")) throw e;
  }
  return more(ctx, pattern);
}

const getFeed: PageAction = (p, ctx) => (p.more ? more(ctx, FEED) : captureOrScroll(ctx, FEED, since(p)));
const getUserPosts: PageAction = (p, ctx) => (p.more ? more(ctx, USER_FEED) : captureOrScroll(ctx, USER_FEED, since(p)));
const getTrending: PageAction = (p, ctx) => ctx.waitCapture(HOT, since(p), 20_000);
const getPost: PageAction = (_p, ctx) => renderData(ctx);
const getUser: PageAction = (_p, ctx) => renderData(ctx);

// The article page renders the first 20 comments and a "查看全部 N 条评论" button that opens a side
// drawer; the drawer's "查看更多评论" button requests the next tab_comments page (offset+20).
async function openDrawer(ctx: PageActionContext): Promise<boolean> {
  if (document.querySelector(DRAWER)) return true;
  await ctx.click("button.side-drawer-btn", 5_000).catch(() => null);
  await new Promise((r) => setTimeout(r, 1_500));
  return !!document.querySelector(DRAWER);
}
const getComments: PageAction = async (p, ctx) => {
  if (!p.more) return ctx.waitCapture(COMMENTS, since(p), 20_000);
  if (!(await openDrawer(ctx))) return { end: true, href: location.href };
  const clickAt = Date.now();
  try {
    await ctx.click(`${DRAWER} .load-more-btn`, 3_000);
  } catch {
    return { end: true, href: location.href }; // no button left: every comment is loaded
  }
  try {
    return await ctx.waitCapture(COMMENTS, clickAt, 15_000);
  } catch (e) {
    if (e instanceof PageError && e.code === "timeout") return { end: true, href: location.href };
    throw e;
  }
};

type TtComment = { comment?: { id_str?: string; id?: unknown; text?: string } };
const getReplies: PageAction = async (p, ctx) =>
  expandReplies(p, ctx, {
    listPattern: COMMENTS,
    extract: (cap) => ((cap as { body?: { data?: TtComment[] } })?.body?.data ?? []).map((c) => ({ id: String(c.comment?.id_str ?? c.comment?.id ?? ""), text: String(c.comment?.text ?? "") })),
    // /2/comment/v4/reply_list/?id={comment}&offset=0&count=5 ; "查看更多回复" asks for the next offset
    replyPattern: (id) => `/reply_list\\/\\?.*[?&]id=${id}(&|$)/`,
    expandRe: /查看全部\s*\d+\s*条回复|\d+\s*条回复|查看更多回复|展开更多回复/,
  });

// Search (so.toutiao.com, pd=information): the first page is server-rendered as .result-content
// cards; scrolling fetches JSON pages whose `dom` holds the same card markup. Both go to the backend.
const searchPosts: PageAction = async (p, ctx) => {
  if (p.more) return more(ctx, SEARCH_MORE);
  let cards: Element[] = [];
  for (let i = 0; i < 40 && !cards.length; i++) {
    cards = Array.from(document.querySelectorAll(".result-content"));
    if (!cards.length) await new Promise((r) => setTimeout(r, 250));
  }
  if (!cards.length) throw new PageError("not_found", "no search result cards on the page (captcha, or layout changed)");
  return { html: cards.map((c) => c.outerHTML), href: location.href, keyword: p.keyword };
};

export const toutiaoPage: PagePlatform = {
  id: "toutiao",
  hosts: [".toutiao.com"],
  riskSignals: [/\/captcha\//, /verify\.snssdk\.com/, /verifycenter\.snssdk\.com\/captcha/],
  actions: {
    search_posts: searchPosts,
    get_post: getPost,
    get_comments: getComments,
    get_replies: getReplies,
    get_user: getUser,
    get_user_posts: getUserPosts,
    get_feed: getFeed,
    get_trending: getTrending,
  },
};
