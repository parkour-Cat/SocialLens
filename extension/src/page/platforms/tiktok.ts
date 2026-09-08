// TikTok page actions. API notes: docs/platforms/tiktok.md
// Same signing scheme as 抖音 (X-Bogus / msToken): navigate and capture. Video and profile
// pages are server-rendered into <script id="__UNIVERSAL_DATA_FOR_REHYDRATION__">.
// URL patterns are expectations until confirmed by recording (see the notes file).

import { PageError } from "../errors";
import { expandReplies } from "./expand";
import { firstOrMore, more } from "./navigate";
import type { PageAction, PageActionContext, PagePlatform } from "./types";

// The state script is ~250 KB; decoding it in the page and cloning it through postMessage takes
// tens of seconds, so the raw text goes to the backend, which parses it.
const rehydration = async (ctx: Parameters<PageAction>[1]) => ctx.readElement("#__UNIVERSAL_DATA_FOR_REHYDRATION__", { waitMs: 15_000 });

const searchPosts: PageAction = (p, ctx) => firstOrMore(p, ctx, "/api/search/item/full/"); // the video tab; /search/general/full/ is the top tab
const searchUsers: PageAction = (p, ctx) => firstOrMore(p, ctx, "/api/search/user/full/");
const getPost: PageAction = async (p, ctx) => {
  const text = await rehydration(ctx).catch(() => null);
  if (!text) throw new PageError("not_found", "rehydration state not found on this page (removed, private, or page changed)");
  return { ssr: true, text, href: location.href };
};
// Comments load only once the comment panel is open: click the action-bar comment icon
// (data-e2e="comment-icon"), then the page requests /api/comment/list/ like any other XHR.
const COMMENT_LIST = "/\\/api\\/comment\\/list\\/\\?/"; // not .../list/reply/
// The side panel has two tabs (评论 / 创作者视频); the comment list container only exists while
// the 评论 tab is active. Open the panel with the action-bar icon, then switch tabs if needed.
const PANEL = '[class*="DivCommentMain"]';
async function openCommentPanel(ctx: PageActionContext): Promise<void> {
  const open = () => !!document.querySelector(PANEL);
  // After the "Please wait..." interstitial the app hydrates slowly: give the icon time to appear,
  // and retry the icon / tab clicks until the list container shows up.
  for (let attempt = 0; attempt < 3 && !open(); attempt++) {
    await ctx.click('[data-e2e="comment-icon"]', attempt === 0 ? 20_000 : 5_000).catch(() => null);
    await new Promise((r) => setTimeout(r, 800));
    if (!open()) await ctx.clickText("评论", 3_000).catch(() => ctx.clickText("Comments", 3_000)).catch(() => null);
    await new Promise((r) => setTimeout(r, 800));
  }
  if (!open()) throw new PageError("not_found", "comment panel did not open (comment icon not found; page not hydrated or layout changed)");
}
const getComments: PageAction = async (p, ctx) => {
  if (p.more) {
    await openCommentPanel(ctx);
    return more(ctx, COMMENT_LIST, PANEL); // scrolling the panel's own container loads the next page
  }
  const since = typeof p.since === "number" ? p.since : 0;
  try {
    return await ctx.waitCapture(COMMENT_LIST, since, 5_000);
  } catch (e) {
    if (!(e instanceof PageError && e.code === "timeout")) throw e;
  }
  const clickAt = Date.now();
  await openCommentPanel(ctx);
  return ctx.waitCapture(COMMENT_LIST, clickAt, 25_000);
};
const getReplies: PageAction = async (p, ctx) => {
  // Make sure the panel is open (a list captured earlier in this tab counts: since 0), without
  // toggling it closed by clicking the icon a second time.
  if (!p.more) await getComments({ ...p, more: undefined, since: 0 }, ctx); // surfaces why the panel could not open
  return expandReplies(p, ctx, {
    listPattern: COMMENT_LIST,
    extract: (body) => ((body as { body?: { comments?: { cid?: unknown; text?: string }[] } })?.body?.comments ?? []).map((c) => ({ id: String(c.cid ?? ""), text: String(c.text ?? "") })),
    replyPattern: (id) => `/comment\\/list\\/reply\\/\\?[^ ]*comment_id=${id}/`,
    expandRe: /查看\s*\d+\s*条回复|查看其它\s*\d+\s*条评论|查看更多|View \d+ replies|View more replies|View \d+ more/, // first expand: "查看 58 条回复"; later pages: "查看其它 54 条评论"
    scrollSelector: PANEL,
  });
};

const getUser: PageAction = async (p, ctx) => ({ ssr: true, text: await rehydration(ctx), href: location.href });
const getUserPosts: PageAction = (p, ctx) => (p.more ? more(ctx, "/api/post/item_list/") : firstOrMore(p, ctx, "/api/post/item_list/"));
const getFeed: PageAction = (p, ctx) => firstOrMore(p, ctx, "/api/recommend/item_list/");
const getTrending: PageAction = (p, ctx) => firstOrMore(p, ctx, "/api/explore/item_list/");

export const tiktokPage: PagePlatform = {
  id: "tiktok",
  hosts: [".tiktok.com"],
  riskSignals: [/tiktok\.com\/captcha/, /verify\.tiktok\.com/, /\/captcha\/(verify|get)/],
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
