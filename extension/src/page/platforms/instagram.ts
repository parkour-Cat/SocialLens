// Instagram page actions. API notes: docs/platforms/instagram.md
// Every GraphQL query is POSTed to /graphql/query or /api/graphql, so captures are told apart by
// the field the response carries (`url ## /field/`). Post and comment pages are server-rendered
// into <script type="application/json"> blocks (Relay preloader payloads); the page hands the
// block's text to the backend. Nothing is requested by the extension itself.

import { PageError } from "../errors";
import { firstOrMore, more } from "./navigate";
import type { PageAction, PageActionContext, PagePlatform, Params } from "./types";

const Q = "/\\/graphql\\/query|\\/api\\/graphql/";
const FEED = `${Q} ## /xdt_api__v1__feed__timeline__connection/`;
const USER = `${Q} ## /"biography_with_entities"/`;
const USER_POSTS = `${Q} ## /feed__user_timeline_graphql_connection/`;
const SEARCH_POSTS = `${Q} ## /xdt_fbsearch__top_serp_graphql/`;
const SEARCH_USERS = `${Q} ## /fbsearch__topsearch_connection/`;
const COMMENTS = `${Q} ## /media_id__comments__connection/`;
const REPLIES = `${Q} ## /child_comments__connection/`;
const EXPLORE = "/\\/discover\\/web\\/explore_grid\\//";
const since = (p: Params) => (typeof p.since === "number" ? p.since : 0);
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/** Text of the first server-rendered JSON block containing `needle` (polls while the page hydrates). */
async function ssrBlock(needle: string, waitMs = 12_000): Promise<string | null> {
  const deadline = Date.now() + waitMs;
  for (;;) {
    for (const el of Array.from(document.querySelectorAll('script[type="application/json"]'))) {
      const t = el.textContent ?? "";
      if (t.includes(needle)) return t;
    }
    if (Date.now() > deadline) return null;
    await sleep(300);
  }
}

const getFeed: PageAction = (p, ctx) => firstOrMore(p, ctx, FEED);
const getUser: PageAction = (p, ctx) => ctx.waitCapture(USER, since(p), 20_000);
const getUserPosts: PageAction = (p, ctx) => firstOrMore(p, ctx, USER_POSTS);
// Explore: the first grid is server-rendered (PolarisQueryPreloaderCache block with sectional_items);
// scrolling asks /api/v1/discover/web/explore_grid/ for the next.
const getTrending: PageAction = async (p, ctx) => {
  if (p.more) return more(ctx, EXPLORE);
  const text = await ssrBlock("sectional_items");
  if (!text) throw new PageError("not_found", "explore grid not found on this page (page changed?)");
  return { ssr: true, text, href: location.href };
};
const searchPosts: PageAction = (p, ctx) => firstOrMore(p, ctx, SEARCH_POSTS);

// Accounts come from the search panel: open it from the side nav, type the keyword, capture the
// topsearch answer the site fetches while typing. No paging.
const searchUsers: PageAction = async (p, ctx) => {
  const kw = String(p.keyword ?? "");
  if (!kw) throw new PageError("bad_request", "missing param: keyword");
  await ctx.click("a:has(svg[aria-label='搜索']), a:has(svg[aria-label='Search']), [role='link']:has(svg[aria-label='搜索']), [role='link']:has(svg[aria-label='Search'])", 15_000);
  await sleep(800);
  const typedAt = Date.now();
  await ctx.type("input[aria-label='搜索输入'], input[placeholder='搜索'], input[aria-label='Search input'], input[placeholder='Search'], input[type='text']", kw, { waitMs: 8_000 });
  return ctx.waitCapture(SEARCH_USERS, typedAt, 20_000);
};

const getPost: PageAction = async () => {
  const text = await ssrBlock("xdt_api__v1__media__shortcode__web_info");
  if (!text) throw new PageError("not_found", "post data not found on this page (removed, private, or page changed)");
  return { ssr: true, text, href: location.href };
};

// First page: the server-rendered comments block. Later pages: Instagram loads more when the
// comment column scrolls; if nothing arrives the list has ended (or the site did not paginate).
/** The comment column: the tallest scrollable box inside the post (classes are hashed, so it is
 *  found by layout and tagged with a data attribute the scroll action can select). */
function commentScroller(): string | undefined {
  let best: HTMLElement | null = null;
  for (const el of Array.from(document.querySelectorAll<HTMLElement>("article div, [role='dialog'] div, main div"))) {
    const oy = getComputedStyle(el).overflowY;
    if ((oy === "auto" || oy === "scroll") && el.scrollHeight - el.clientHeight > 50 && el.clientHeight > 100 && (!best || el.scrollHeight > best.scrollHeight)) best = el;
  }
  if (!best) return undefined;
  best.setAttribute("data-sociallens-scroll", "comments");
  return '[data-sociallens-scroll="comments"]';
}
const getComments: PageAction = async (p, ctx) => {
  if (p.more) return more(ctx, COMMENTS, commentScroller());
  const text = await ssrBlock("media_id__comments__connection");
  if (!text) throw new PageError("not_found", "comments block not found on this page (comments disabled, or page changed)");
  return { ssr: true, text, href: location.href };
};

type IgCommentNode = { pk?: unknown; text?: string };
function commentSnippet(text: string, id: string): string | null {
  try {
    const nodes: IgCommentNode[] = [];
    const walk = (o: unknown, d: number) => {
      if (d > 40 || !o || typeof o !== "object") return;
      if (Array.isArray(o)) return o.forEach((v) => walk(v, d + 1));
      const r = o as Record<string, unknown>;
      if (r.pk != null && typeof r.text === "string" && "comment_like_count" in r) nodes.push(r as IgCommentNode);
      for (const v of Object.values(r)) walk(v, d + 1);
    };
    walk(JSON.parse(text), 0);
    const n = nodes.find((c) => String(c.pk) === id);
    return n?.text?.replace(/\s+/g, " ").trim().slice(0, 40) || null;
  } catch {
    return null;
  }
}

const EXPAND_RE = /查看所有\s*\d+\s*条回复|查看回复|View all \d+ replies|View replies|查看更多回复|View more replies/;
/** Replies under one comment: locate the comment by its text, click its "查看所有 N 条回复" control.
 *  The child-comments query names the parent in its variables, so the wait matches on the id. */
const getReplies: PageAction = async (p, ctx) => {
  const id = String(p.comment_id ?? "");
  if (!id) throw new PageError("bad_request", "missing param: comment_id");
  const pattern = `${Q} @@ /${id}/ ## /child_comments__connection/`;
  if (!p.more) {
    const had = ctx.captures(pattern) as Record<string, unknown>[];
    if (had.length) return { ...had[had.length - 1], _comment_id: id }; // expanded earlier in this tab
  }
  const text = await ssrBlock("media_id__comments__connection");
  const snippet = text ? commentSnippet(text, id) : null;
  if (!snippet) throw new PageError("not_found", `comment ${id} is not among the comments rendered on the page`);
  let anchor: HTMLElement | null = null;
  for (let i = 0; i < 20 && !anchor; i++) {
    const els = Array.from(document.querySelectorAll<HTMLElement>("span, div, h1, h2, h3")).filter((e) => e.children.length === 0 && (e.textContent || "").includes(snippet));
    anchor = els[0] ?? null;
    if (!anchor) await sleep(250);
  }
  if (!anchor) throw new PageError("not_found", `comment ${id} is not rendered on the page (snippet: ${snippet})`);
  // Walk up until a container holds an expand control; take the innermost clickable one.
  let control: HTMLElement | null = null;
  for (let el: HTMLElement | null = anchor.parentElement, depth = 0; el && depth < 16 && !control; el = el.parentElement, depth++) {
    const cands = Array.from(el.querySelectorAll<HTMLElement>("*")).filter((c) => c.children.length === 0 && EXPAND_RE.test((c.innerText || c.textContent || "").trim()));
    const leaf = cands[0] ?? null;
    control = leaf ? (leaf.closest<HTMLElement>("[role='button'], button, a, [tabindex]") ?? leaf) : null;
  }
  if (!control) {
    if (p.more) return { end: true, href: location.href };
    throw new PageError("not_found", `comment ${id} has no expand control (no replies?)`);
  }
  const clickAt = Date.now();
  control.scrollIntoView({ block: "center" });
  control.click();
  try {
    const cap = (await ctx.waitCapture(pattern, clickAt, 15_000)) as Record<string, unknown>;
    return { ...cap, _comment_id: id };
  } catch (e) {
    if (p.more && e instanceof PageError && e.code === "timeout") return { end: true, href: location.href };
    if (e instanceof PageError && e.code === "timeout") throw new PageError("timeout", `clicked <${control.tagName.toLowerCase()}> "${(control.innerText || "").trim().slice(0, 40)}" but no child-comments response followed`);
    throw e;
  }
};

export const instagramPage: PagePlatform = {
  id: "instagram",
  hosts: [".instagram.com"],
  riskSignals: [/instagram\.com\/challenge\//, /instagram\.com\/accounts\/suspended/, /instagram\.com\/accounts\/login\/\?next=/],
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
