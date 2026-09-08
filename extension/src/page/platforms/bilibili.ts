// B 站 page actions. API notes: docs/platforms/bilibili.md
// Most read APIs need the "wbi" signature: params sorted, joined with a mixin key derived
// from two image URLs in /x/web-interface/nav, then md5. Same algorithm the site runs.

import { PageError } from "../errors";
import { md5 } from "../md5";
import { intParam, param, type PageAction, type PageActionContext, type PagePlatform, type Params } from "./types";

const API = "https://api.bilibili.com";

// ---- wbi signing -------------------------------------------------------------

const MIXIN_TAB = [
  46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13, 37,
  48, 7, 16, 24, 55, 40, 61, 26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11, 36, 20, 34, 44, 52,
];

let wbiKeys: { mixin: string; fetchedAt: number } | null = null;

async function getMixinKey(ctx: PageActionContext): Promise<string> {
  if (wbiKeys && Date.now() - wbiKeys.fetchedAt < 6 * 3600_000) return wbiKeys.mixin;
  const nav = await getJson(ctx, `${API}/x/web-interface/nav`, { allowCodes: [-101] });
  const img = String(nav?.data?.wbi_img?.img_url ?? "");
  const sub = String(nav?.data?.wbi_img?.sub_url ?? "");
  const strip = (u: string) => u.slice(u.lastIndexOf("/") + 1).split(".")[0];
  const orig = strip(img) + strip(sub);
  if (orig.length < 64) throw new PageError("extension_error", "cannot read wbi keys from nav api");
  const mixin = MIXIN_TAB.map((i) => orig[i]).join("").slice(0, 32);
  wbiKeys = { mixin, fetchedAt: Date.now() };
  return mixin;
}

async function signWbi(ctx: PageActionContext, params: Record<string, string | number>): Promise<string> {
  const mixin = await getMixinKey(ctx);
  const withTs: Record<string, string> = { ...Object.fromEntries(Object.entries(params).map(([k, v]) => [k, String(v)])), wts: String(Math.floor(Date.now() / 1000)) };
  const query = Object.keys(withTs)
    .sort()
    .map((k) => `${encodeURIComponent(k)}=${encodeURIComponent(withTs[k].replace(/[!'()*]/g, ""))}`)
    .join("&");
  return `${query}&w_rid=${md5(query + mixin)}`;
}

// ---- http helpers -------------------------------------------------------------

interface BiliResponse {
  code: number;
  message?: string;
  data?: any;
  [k: string]: unknown;
}

const CODE_MAP: Record<number, string> = {
  [-101]: "not_logged_in",
  [-352]: "rate_limited", // risk control on anonymous / high-frequency access
  [-412]: "rate_limited", // request blocked
  [-403]: "not_logged_in",
  [-404]: "not_found",
  [-400]: "bad_request",
  62002: "not_found", // video hidden
  62004: "not_found", // video under review
};

/** A fresh profile has no device cookies until the site's own JS has run; API calls made
 *  before that get HTTP 412. Wait (bounded) for buvid3 to appear. */
async function ensureReady(): Promise<void> {
  const deadline = Date.now() + 10_000;
  while (Date.now() < deadline) {
    if (/(^|;\s*)buvid3=/.test(document.cookie) && document.readyState !== "loading") return;
    await new Promise((r) => setTimeout(r, 250));
  }
}

async function getJson(ctx: PageActionContext, url: string, opts: { allowCodes?: number[] } = {}): Promise<BiliResponse> {
  await ensureReady();
  const res = await ctx.fetch(url, { credentials: "include" });
  if (res.status === 412) throw new PageError("rate_limited", "bilibili returned HTTP 412 (request blocked)");
  let body: BiliResponse;
  try {
    body = (await res.json()) as BiliResponse;
  } catch {
    throw new PageError("parse_error", `non-JSON response (${res.status}) from ${url}`);
  }
  if (body.code === 0 && body.data && typeof body.data === "object" && "v_voucher" in body.data && Object.keys(body.data).length === 1) {
    // Risk control: the site would now show a captcha. We never solve it; report and let the queue pause.
    throw new PageError("captcha_required", "bilibili risk control (v_voucher): open the site in the browser, pass the check, then resume", { url });
  }
  if (body.code !== 0 && !(opts.allowCodes ?? []).includes(body.code)) {
    throw new PageError(CODE_MAP[body.code] ?? "extension_error", `bilibili api code ${body.code}: ${body.message ?? ""}`, { code: body.code, url });
  }
  return body;
}

async function wbiGet(ctx: PageActionContext, path: string, params: Record<string, string | number>): Promise<BiliResponse> {
  return getJson(ctx, `${API}${path}?${await signWbi(ctx, params)}`);
}

async function plainGet(ctx: PageActionContext, path: string, params: Record<string, string | number>): Promise<BiliResponse> {
  const q = new URLSearchParams(Object.fromEntries(Object.entries(params).map(([k, v]) => [k, String(v)])));
  return getJson(ctx, `${API}${path}?${q}`);
}

// ---- id helpers --------------------------------------------------------------------

const aidCache = new Map<string, number>();

async function resolveAid(ctx: PageActionContext, id: string): Promise<number> {
  if (/^\d+$/.test(id)) return Number(id);
  const cached = aidCache.get(id);
  if (cached) return cached;
  const view = await wbiGet(ctx, "/x/web-interface/wbi/view", { bvid: id });
  const aid = Number(view.data?.aid);
  if (!aid) throw new PageError("not_found", `cannot resolve aid for ${id}`);
  aidCache.set(id, aid);
  return aid;
}

function requireId(p: Params, key = "id"): string {
  const v = param(p, key);
  if (!v) throw new PageError("bad_request", `missing param: ${key}`);
  return v;
}

// ---- actions ----------------------------------------------------------------------

const searchPosts: PageAction = async (p, ctx) => {
  const keyword = requireId(p, "keyword");
  const page = intParam(p, "page", 1);
  const order = param(p, "order") ?? "totalrank"; // totalrank | click | pubdate | dm | stow
  return wbiGet(ctx, "/x/web-interface/wbi/search/type", { search_type: "video", keyword, page, order, page_size: 42 });
};

const searchUsers: PageAction = async (p, ctx) => {
  const keyword = requireId(p, "keyword");
  const page = intParam(p, "page", 1);
  return wbiGet(ctx, "/x/web-interface/wbi/search/type", { search_type: "bili_user", keyword, page });
};

const getPost: PageAction = async (p, ctx) => {
  const id = requireId(p);
  const key: Record<string, string | number> = /^\d+$/.test(id) ? { aid: id } : { bvid: id };
  return wbiGet(ctx, "/x/web-interface/wbi/view", key);
};

const getPlayUrl: PageAction = async (p, ctx) => {
  // Stream URLs for one page (cid) of a video. dash: separate video/audio (fnval 4048, up to 4K
  // for logged-in accounts, merged by the backend with ffmpeg); mp4: single-file durl via the
  // html5 platform (up to 1080p). CDN URLs then only need the Referer, no cookies.
  const id = requireId(p);
  const cid = requireId(p, "cid");
  const key: Record<string, string | number> = /^\d+$/.test(id) ? { avid: id } : { bvid: id };
  const mode = param(p, "mode") ?? "dash";
  const params: Record<string, string | number> =
    mode === "mp4" ? { ...key, cid, fnval: 1, fnver: 0, fourk: 1, platform: "html5", high_quality: 1, qn: 80 } : { ...key, cid, fnval: 4048, fnver: 0, fourk: 1 };
  return wbiGet(ctx, "/x/player/wbi/playurl", params);
};

const getUser: PageAction = async (p, ctx) => {
  const mid = requireId(p);
  const [info, stat] = await Promise.all([
    wbiGet(ctx, "/x/space/wbi/acc/info", { mid }),
    plainGet(ctx, "/x/relation/stat", { vmid: mid }),
  ]);
  return { info, stat };
};

const getComments: PageAction = async (p, ctx) => {
  const postId = requireId(p, "post_id");
  const oid = await resolveAid(ctx, postId);
  const offset = param(p, "offset") ?? "";
  const mode = intParam(p, "mode", 3); // 3 = hot, 2 = time
  const body = await wbiGet(ctx, "/x/v2/reply/wbi/main", {
    type: 1,
    oid,
    mode,
    pagination_str: JSON.stringify({ offset }),
    plat: 1,
    web_location: 1315875,
  });
  return { ...body, _post_id: postId }; // the parser needs the id the caller used (BV or aid)
};

const getReplies: PageAction = async (p, ctx) => {
  // /x/v2/reply/reply: replies under root rpid, plain paging (no wbi needed).
  const postId = requireId(p, "post_id");
  const root = requireId(p, "comment_id");
  const oid = await resolveAid(ctx, postId);
  const page = intParam(p, "page", 1);
  const body = await plainGet(ctx, "/x/v2/reply/reply", { type: 1, oid, root, pn: page, ps: 20, web_location: 333.788 });
  return { ...body, _post_id: postId, _comment_id: root };
};

const getTrending: PageAction = async (p, ctx) => {
  // 综合热门: /x/web-interface/popular, paged with pn/ps, data.no_more at the end.
  const page = intParam(p, "page", 1);
  const body = await plainGet(ctx, "/x/web-interface/popular", { pn: page, ps: 20 });
  return { ...body, _page: page };
};

const getUserPosts: PageAction = async (p, ctx) => {
  const mid = requireId(p);
  const page = intParam(p, "page", 1);
  const order = param(p, "order") ?? "pubdate";
  return wbiGet(ctx, "/x/space/wbi/arc/search", { mid, pn: page, ps: 30, order, platform: "web", web_location: 1550101 });
};

export const bilibiliPage: PagePlatform = {
  id: "bilibili",
  hosts: [".bilibili.com"],
  // security.bilibili.com/412 and its captcha endpoints appear when a page load is challenged.
  riskSignals: [/security\.bilibili\.com\/(412|th\/captcha)/],
  actions: {
    search_posts: searchPosts,
    search_users: searchUsers,
    get_post: getPost,
    get_user: getUser,
    get_comments: getComments,
    get_user_posts: getUserPosts, get_play_url: getPlayUrl,
    get_replies: getReplies, get_trending: getTrending,
  },
};
