// LinkedIn page actions. API notes: docs/platforms/linkedin.md
// The current web app is server-driven UI (React Server Component streams with component trees
// and no entity data), so the classic voyager REST API is called from inside a LinkedIn tab with
// the page's own cookies plus the csrf-token header (the JSESSIONID cookie value), exactly as the
// old web app did. Call strategy; only the endpoints that still answer are wired.

import { PageError } from "../errors";
import { intParam, param, type PageAction, type PageActionContext, type PagePlatform, type Params } from "./types";

const SITE = "https://www.linkedin.com";

function csrfToken(): string {
  const m = /JSESSIONID="?([^";]+)/.exec(document.cookie);
  if (!m) throw new PageError("not_logged_in", "JSESSIONID cookie not found: sign in to linkedin.com first");
  return m[1];
}

async function voyager(ctx: PageActionContext, path: string): Promise<unknown> {
  const res = await ctx.fetch(SITE + path, {
    credentials: "include",
    headers: { "csrf-token": csrfToken(), accept: "application/vnd.linkedin.normalized+json+2.1", "x-restli-protocol-version": "2.0.0", "x-li-lang": "zh_CN" },
  });
  if (res.status === 401 || res.status === 403) throw new PageError("not_logged_in", `linkedin answered ${res.status} (session expired or blocked)`);
  if (res.status === 429) throw new PageError("rate_limited", "linkedin answered 429 (too many requests)");
  if (res.status === 404 || res.status === 410) throw new PageError("not_found", `linkedin answered ${res.status} for ${path.split("?")[0]}`);
  if (!res.ok) throw new PageError("extension_error", `linkedin HTTP ${res.status} for ${path.split("?")[0]}`);
  return res.json();
}

function need(p: Params, key: string): string {
  const v = param(p, key);
  if (!v) throw new PageError("bad_request", `missing param: ${key}`);
  return v;
}

// Home feed, chronological. Later pages carry the paginationToken of the first answer.
const getFeed: PageAction = (p, ctx) => {
  const start = intParam(p, "start", 0);
  const tok = param(p, "token");
  return voyager(ctx, `/voyager/api/feed/updatesV2?count=10&q=chronFeed&start=${start}${tok ? `&paginationToken=${encodeURIComponent(tok)}` : ""}`);
};
// One post by activity id: the update with its highlighted comments and social counts.
const getPost: PageAction = (p, ctx) => voyager(ctx, `/voyager/api/feed/updates/urn:li:activity:${need(p, "id").replace(/^urn:li:activity:/, "")}`);
// Profile by vanity name (the /in/{vanity} segment).
const getUser: PageAction = (p, ctx) => voyager(ctx, `/voyager/api/identity/dash/profiles?q=memberIdentity&memberIdentity=${encodeURIComponent(need(p, "id"))}&decorationId=com.linkedin.voyager.dash.deco.identity.profile.WebTopCardCore-16`);
// People search: the dash search clusters GraphQL query (queryId hash from the public web app; it
// changes with deployments). When it stops answering, the global typeahead is the fallback.
const SEARCH_QUERY_ID = "voyagerSearchDashClusters.b0928897b71bd00a5a7291755dcd64f0";
const searchUsers: PageAction = async (p, ctx) => {
  const kw = need(p, "keyword");
  const start = intParam(p, "start", 0);
  const variables = `(start:${start},origin:GLOBAL_SEARCH_HEADER,query:(keywords:${encodeURIComponent(kw).replace(/[()]/g, (c) => `%${c.charCodeAt(0).toString(16)}`)},flagshipSearchIntent:SEARCH_SRP,queryParameters:List((key:resultType,value:List(PEOPLE))),includeFiltersInResponse:false))`;
  try {
    return await voyager(ctx, `/voyager/api/graphql?variables=${variables}&queryId=${SEARCH_QUERY_ID}`);
  } catch (e) {
    if (!(e instanceof PageError && (e.code === "not_found" || e.code === "extension_error"))) throw e;
    return voyager(ctx, `/voyager/api/voyagerSearchDashTypeahead?q=globalTypeahead&query=${encodeURIComponent(kw)}&start=0&count=10`);
  }
};

// ---- classic (Ember) pages: /in/{vanity}/recent-activity/all/ and /feed/update/{urn}/ still run
// the old voyager-web app, which issues dash GraphQL calls the page script can capture. Navigate
// strategy for member posts, comments and replies; nothing is requested by the extension itself.

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const sinceOf = (p: Params) => (typeof p.since === "number" ? p.since : 0);
const USER_POSTS = "ProfileUpdates"; // substring of the dash GraphQL queryId
const COMMENTS = "SocialDashComments";

async function clickThenWait(ctx: PageActionContext, text: string, pattern: string, waitMs = 20_000): Promise<unknown> {
  const clickAt = Date.now();
  try {
    await ctx.clickText(text, 4_000);
  } catch {
    return { end: true, href: location.href }; // no control left: the list is complete
  }
  try {
    return await ctx.waitCapture(pattern, clickAt, waitMs);
  } catch (e) {
    if (e instanceof PageError && e.code === "timeout") return { end: true, href: location.href };
    throw e;
  }
}

// Member posts: the page fetches feedDashProfileUpdatesByMemberShareFeed on load; "显示更多结果" asks for the next page.
const getUserPosts: PageAction = (p, ctx) => (p.more ? clickThenWait(ctx, "/显示更多结果|Show more results/", USER_POSTS) : ctx.waitCapture(USER_POSTS, sinceOf(p), 25_000));

/** The post page embeds the update with its first comments in a <code id="bpr-guid-…"> block. */
async function postBlock(activity: string, waitMs = 15_000): Promise<string | null> {
  const deadline = Date.now() + waitMs;
  for (;;) {
    for (const el of Array.from(document.querySelectorAll("code"))) {
      const t = el.textContent ?? "";
      if (t.includes("feedDashUpdatesByBackendUrn") && t.includes(activity)) return t;
    }
    if (Date.now() > deadline) return null;
    await sleep(300);
  }
}
const getComments: PageAction = async (p, ctx) => {
  if (p.more) return clickThenWait(ctx, "/加载更多评论|Load more comments/", COMMENTS);
  const text = await postBlock(String(p.post_id ?? p.id ?? ""));
  if (!text) throw new PageError("not_found", "post data not found on this page (removed, or the page moved to the new layout)");
  return { ssr: true, text, href: location.href };
};

type LiComment = { entityUrn?: string; commentary?: { text?: string }; $type?: string };
function commentSnippet(id: string): string | null {
  const texts: string[] = [];
  for (const el of Array.from(document.querySelectorAll("code"))) texts.push(el.textContent ?? "");
  for (const c of ctxCaptures) texts.push(c);
  for (const t of texts) {
    if (!t.includes(`urn:li:fsd_comment:(${id},`)) continue;
    try {
      const inc = (JSON.parse(t) as { included?: LiComment[] }).included ?? [];
      const hit = inc.find((c) => String(c.$type ?? "").endsWith(".Comment") && String(c.entityUrn ?? "").includes(`(${id},`));
      const s = hit?.commentary?.text?.replace(/\s+/g, " ").trim().slice(0, 40);
      if (s) return s;
    } catch {
      /* not json */
    }
  }
  return null;
}
let ctxCaptures: string[] = [];
// Replies: locate the comment by its text, click its "N 条回复" control (later pages: "查看之前的回复").
const getReplies: PageAction = async (p, ctx) => {
  const id = String(p.comment_id ?? "");
  if (!id) throw new PageError("bad_request", "missing param: comment_id");
  ctxCaptures = (ctx.captures(COMMENTS) as { body?: unknown }[]).map((c) => (typeof c.body === "string" ? c.body : JSON.stringify(c.body ?? "")));
  const pattern = `fsd_comment%3A%28${id}%2C`; // the reply query names the parent comment in its variables
  if (!p.more) {
    // replies already shown under the comment come with the page block; only older ones need a click
    const block = await postBlock(String(p.post_id ?? ""), 3_000);
    if (block && block.includes(`urn:li:comment:(activity:${String(p.post_id ?? "")},${id}),urn:li:comment:`)) return { ssr: true, text: block, href: location.href, _comment_id: id };
  }
  const snippet = commentSnippet(id);
  if (!snippet) throw new PageError("not_found", `comment ${id} is not among the comments loaded on this page`);
  let anchor: HTMLElement | null = null;
  for (let i = 0; i < 20 && !anchor; i++) {
    anchor = Array.from(document.querySelectorAll<HTMLElement>("span, div, p")).find((e) => e.children.length === 0 && (e.textContent || "").includes(snippet)) ?? null;
    if (!anchor) await sleep(250);
  }
  if (!anchor) throw new PageError("not_found", `comment ${id} is not rendered on the page`);
  // "N 条回复" only unfolds the replies already on the page; "查看之前的回复" asks the site for older ones.
  const findControl = (re: RegExp): HTMLElement | null => {
    for (let el: HTMLElement | null = anchor!.parentElement, depth = 0; el && depth < 12; el = el.parentElement, depth++) {
      const leaf = Array.from(el.querySelectorAll<HTMLElement>("button, span, a")).find((c) => re.test((c.innerText || c.textContent || "").trim()));
      if (leaf) return leaf.closest<HTMLElement>("button, a, [role='button']") ?? leaf;
    }
    return null;
  };
  const LOAD_RE = /^\s*(查看之前的回复|加载更多回复|Load previous replies|Load more replies)\s*$/;
  const UNFOLD_RE = /^\s*(\d+\s*条回复|View \d+ repl(y|ies))\s*$/;
  let control = findControl(LOAD_RE);
  if (!control) {
    const unfold = findControl(UNFOLD_RE);
    if (unfold) {
      unfold.scrollIntoView({ block: "center" });
      unfold.click();
      await sleep(1_500);
      control = findControl(LOAD_RE);
    }
  }
  if (!control) {
    if (p.more) return { end: true, href: location.href };
    throw new PageError("not_found", `comment ${id} has no replies control`);
  }
  const clickAt = Date.now();
  control.scrollIntoView({ block: "center" });
  control.click();
  try {
    const cap = (await ctx.waitCapture(pattern, clickAt, 20_000)) as Record<string, unknown>;
    return { ...cap, _comment_id: id };
  } catch (e) {
    if (p.more && e instanceof PageError && e.code === "timeout") return { end: true, href: location.href };
    throw e;
  }
};

export const linkedinPage: PagePlatform = {
  id: "linkedin",
  hosts: [".linkedin.com"],
  riskSignals: [/linkedin\.com\/checkpoint\//, /linkedin\.com\/uas\/login/],
  actions: { get_feed: getFeed, get_post: getPost, get_user: getUser, search_users: searchUsers, get_user_posts: getUserPosts, get_comments: getComments, get_replies: getReplies },
};
