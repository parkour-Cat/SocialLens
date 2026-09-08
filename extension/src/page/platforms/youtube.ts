// YouTube page actions. API notes: docs/platforms/youtube.md
// First screens are server-rendered into window.ytInitialData / ytInitialPlayerResponse;
// further pages are the site's own POST /youtubei/v1/{search,browse,next} calls, triggered by scrolling.

import { PageError } from "../errors";
import { more } from "./navigate";
import type { PageAction, PagePlatform } from "./types";

const initial = async (ctx: Parameters<PageAction>[1], name: string) => ctx.readGlobal(name, 15_000);

const searchPosts: PageAction = async (p, ctx) => {
  if (p.more) return more(ctx, "/youtubei/v1/search");
  return { ssr: true, data: await initial(ctx, "ytInitialData"), href: location.href };
};
const searchUsers = searchPosts;

const getPost: PageAction = async (p, ctx) => {
  const player = await initial(ctx, "ytInitialPlayerResponse").catch(() => null);
  const data = await initial(ctx, "ytInitialData").catch(() => null);
  if (!player && !data) throw new PageError("not_found", "video page state not found");
  return { ssr: true, player, data, href: location.href };
};

function findContinuation(obj: unknown, depth = 0): string | null {
  // The watch page embeds the comments continuation token in ytInitialData
  // (itemSectionRenderer sectionIdentifier "comment-item-section" -> continuationCommand.token).
  if (depth > 60 || obj == null || typeof obj !== "object") return null;
  if (!Array.isArray(obj)) {
    const o = obj as Record<string, unknown>;
    if (o.sectionIdentifier === "comment-item-section") {
      const cmd = findKey(o, "continuationCommand") as { token?: string } | null;
      if (cmd?.token) return cmd.token;
    }
  }
  for (const v of Array.isArray(obj) ? obj : Object.values(obj as object)) {
    const r = findContinuation(v, depth + 1);
    if (r) return r;
  }
  return null;
}

function findKey(obj: unknown, key: string, depth = 0): unknown {
  if (depth > 60 || obj == null || typeof obj !== "object") return null;
  if (!Array.isArray(obj) && key in (obj as object)) return (obj as Record<string, unknown>)[key];
  for (const v of Array.isArray(obj) ? obj : Object.values(obj as object)) {
    const r = findKey(v, key, depth + 1);
    if (r) return r;
  }
  return null;
}

async function innertubeNext(ctx: Parameters<PageAction>[1], token: string): Promise<Record<string, unknown>> {
  const cfg = ((window as unknown as { ytcfg?: { data_?: Record<string, unknown> } }).ytcfg?.data_ ?? {}) as Record<string, unknown>;
  const key = String(cfg.INNERTUBE_API_KEY ?? "");
  const context = cfg.INNERTUBE_CONTEXT ?? { client: { clientName: "WEB", clientVersion: String(cfg.INNERTUBE_CLIENT_VERSION ?? "2.20250101.00.00") } };
  const res = await ctx.fetch(`https://www.youtube.com/youtubei/v1/next?key=${encodeURIComponent(key)}&prettyPrint=false`, {
    method: "POST",
    credentials: "include",
    headers: { "content-type": "application/json", "x-youtube-client-name": "1", "x-youtube-client-version": String(cfg.INNERTUBE_CLIENT_VERSION ?? "") },
    body: JSON.stringify({ context, continuation: token }),
  });
  if (!res.ok) throw new PageError(res.status === 429 ? "rate_limited" : "extension_error", `youtubei next HTTP ${res.status}`);
  return { body: await res.json(), url: res.url, status: res.status, method: "POST", kind: "fetch", ts: Date.now(), truncated: false, content_type: "application/json" };
}

/** Walk any JSON for comment threads: [commentId, replies continuation token | null]. */
function threadTokens(obj: unknown, out: Map<string, string | null>, depth = 0): void {
  if (depth > 60 || obj == null || typeof obj !== "object") return;
  if (!Array.isArray(obj)) {
    const o = obj as Record<string, unknown>;
    const th = o.commentThreadRenderer as Record<string, unknown> | undefined;
    if (th) {
      const vm = (th.commentViewModel as Record<string, unknown> | undefined) ?? {};
      const inner = (vm.commentViewModel as Record<string, unknown> | undefined) ?? vm;
      const cid = String(inner.commentId ?? ((th.comment as Record<string, unknown> | undefined)?.commentRenderer as Record<string, unknown> | undefined)?.commentId ?? "");
      if (cid) out.set(cid, (findKey(th.replies, "continuationCommand") as { token?: string } | null)?.token ?? null);
    }
  }
  for (const v of Array.isArray(obj) ? obj : Object.values(obj as object)) threadTokens(v, out, depth + 1);
}

/** Token of the "load more comments" continuation in a next() response (top-level continuation items only). */
function nextPageToken(body: unknown): string | null {
  const eps = ((body as Record<string, unknown>)?.onResponseReceivedEndpoints as Record<string, unknown>[] | undefined) ?? [];
  let token: string | null = null;
  for (const ep of eps) {
    for (const key of ["reloadContinuationItemsCommand", "appendContinuationItemsAction"]) {
      const items = ((ep[key] as Record<string, unknown> | undefined)?.continuationItems as Record<string, unknown>[] | undefined) ?? [];
      for (const it of items) if (it.continuationItemRenderer) token = (findKey(it.continuationItemRenderer, "continuationCommand") as { token?: string } | null)?.token ?? token;
    }
  }
  return token;
}

const getReplies: PageAction = async (p, ctx) => {
  // Replies live behind a per-thread continuation token. With `token` (from a cursor or the
  // comment's raw.replies_token) call next() directly; otherwise page through the comment list
  // until the thread with comment_id shows up and take its token.
  const cid = String(p.comment_id ?? "");
  let token = typeof p.token === "string" && p.token ? p.token : null;
  if (!token) {
    if (!cid) throw new PageError("bad_request", "missing param: comment_id");
    let cont = findContinuation(await initial(ctx, "ytInitialData"));
    for (let page = 0; page < 8 && cont; page++) {
      const res = await innertubeNext(ctx, cont);
      const map = new Map<string, string | null>();
      threadTokens(res.body, map);
      if (map.has(cid)) {
        token = map.get(cid) ?? null;
        if (!token) return { body: { onResponseReceivedEndpoints: [] }, _comment_id: cid, _no_replies: true };
        break;
      }
      cont = nextPageToken(res.body);
    }
    if (!token) throw new PageError("not_found", `comment ${cid} not found in the first pages of comments`);
  }
  return { ...(await innertubeNext(ctx, token)), _comment_id: cid };
};

const getTrending: PageAction = async (p, ctx) => {
  if (p.more) return more(ctx, "/youtubei/v1/browse");
  return { ssr: true, data: await initial(ctx, "ytInitialData"), href: location.href };
};

const getComments: PageAction = async (p, ctx) => {
  // The comments section only loads on a real, interactive scroll, which does not happen in our
  // tab. Instead call the same innertube endpoint the page would: POST /youtubei/v1/next with
  // the continuation token from ytInitialData (page 1) or from the previous response (later pages).
  let token = typeof p.token === "string" && p.token ? p.token : null;
  if (!token) {
    const data = await initial(ctx, "ytInitialData");
    token = findContinuation(data);
  }
  if (!token) throw new PageError("not_found", "no comments continuation on this watch page (comments turned off?)");
  return innertubeNext(ctx, token);
};

const getStreams: PageAction = async (p, ctx) => {
  // streamingData of the watch page: progressive formats carry a plain url (360p/720p); adaptive
  // ones are cipher/SABR protected and left to yt-dlp on the backend side.
  const player = (await initial(ctx, "ytInitialPlayerResponse")) as { videoId?: string; streamingData?: unknown; videoDetails?: { videoId?: string } } | null;
  if (!player?.streamingData) throw new PageError("not_found", "no streamingData on this watch page (login-only, age-restricted or removed video?)");
  return { videoId: player.videoDetails?.videoId, streamingData: player.streamingData };
};

const getUser: PageAction = async (p, ctx) => ({ ssr: true, data: await initial(ctx, "ytInitialData"), href: location.href });

const getUserPosts: PageAction = async (p, ctx) => {
  if (p.more) return more(ctx, "/youtubei/v1/browse");
  return { ssr: true, data: await initial(ctx, "ytInitialData"), href: location.href };
};

const getFeed: PageAction = async (p, ctx) => {
  if (p.more) return more(ctx, "/youtubei/v1/browse");
  return { ssr: true, data: await initial(ctx, "ytInitialData"), href: location.href };
};

export const youtubePage: PagePlatform = {
  id: "youtube",
  hosts: [".youtube.com"],
  riskSignals: [/\/sorry\/index/, /google\.com\/recaptcha/],
  actions: { search_posts: searchPosts, search_users: searchUsers, get_post: getPost, get_comments: getComments, get_user: getUser, get_user_posts: getUserPosts, get_feed: getFeed, get_streams: getStreams, get_replies: getReplies, get_trending: getTrending },
};
