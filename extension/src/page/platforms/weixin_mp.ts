// 公众号 page actions. API notes: docs/platforms/weixin_mp.md
//
// Public data comes through the user's own 公众号 backend (mp.weixin.qq.com): the "insert
// link -> other account's article" feature is backed by two plain JSON endpoints that only
// need the session `token` (in the page URL / wx.data.t). Article bodies are public pages.

import { PageError } from "../errors";
import type { PageAction, PageActionContext, PagePlatform } from "./types";

const SITE = "https://mp.weixin.qq.com";

function sessionToken(): string {
  const fromUrl = new URLSearchParams(location.search).get("token");
  if (fromUrl) return fromUrl;
  const wx = (window as unknown as { wx?: { data?: { t?: string } } }).wx;
  if (wx?.data?.t) return String(wx.data.t);
  throw new PageError("not_logged_in", "公众号后台会话 token 不可用：请在 mp.weixin.qq.com 扫码登录后台并保持标签页打开");
}

async function cgi(ctx: PageActionContext, path: string, params: Record<string, string | number>): Promise<Record<string, unknown>> {
  const q = new URLSearchParams({ token: sessionToken(), lang: "zh_CN", f: "json", ajax: "1", ...Object.fromEntries(Object.entries(params).map(([k, v]) => [k, String(v)])) });
  const res = await ctx.fetch(`${SITE}/cgi-bin/${path}?${q}`, { credentials: "include", headers: { "x-requested-with": "XMLHttpRequest" } });
  let body: Record<string, unknown>;
  try {
    body = (await res.json()) as Record<string, unknown>;
  } catch {
    throw new PageError("parse_error", `non-JSON response (${res.status}) from ${path}`);
  }
  const base = (body.base_resp as { ret?: number; err_msg?: string } | undefined) ?? {};
  const ret = Number(base.ret ?? 0);
  if (ret !== 0) {
    if (ret === 200013) throw new PageError("rate_limited", "公众号后台：操作频繁，接口已被临时冻结（通常持续数小时）", { ret });
    if (ret === 200003 || ret === -6) throw new PageError("not_logged_in", `公众号后台会话失效（ret ${ret}），请重新扫码登录`, { ret });
    throw new PageError("extension_error", `公众号后台接口错误 ret=${ret} ${base.err_msg ?? ""}`, { ret });
  }
  return body;
}

const searchUsers: PageAction = async (p, ctx) => {
  const keyword = String(p.keyword ?? "");
  if (!keyword) throw new PageError("bad_request", "missing param: keyword");
  const begin = typeof p.begin === "number" ? p.begin : 0;
  const body = await cgi(ctx, "searchbiz", { action: "search_biz", query: keyword, begin, count: 5 });
  return { ...body, _begin: begin }; // the parser needs the offset to build the next cursor
};

const getUserPosts: PageAction = async (p, ctx) => {
  const fakeid = String(p.id ?? "");
  if (!fakeid) throw new PageError("bad_request", "missing param: id (fakeid from search_users)");
  const begin = typeof p.begin === "number" ? p.begin : 0;
  const body = await cgi(ctx, "appmsg", { action: "list_ex", fakeid, query: String(p.query ?? ""), begin, count: 5, type: 9 });
  return { ...body, _begin: begin };
};

const getUser: PageAction = async (p, ctx) => {
  // No dedicated profile endpoint; searching the exact name or alias returns the card.
  const keyword = String(p.keyword ?? p.id ?? "");
  if (!keyword) throw new PageError("bad_request", "missing param: id or keyword");
  return cgi(ctx, "searchbiz", { action: "search_biz", query: keyword, begin: 0, count: 5 });
};

const getPost: PageAction = async (p, ctx) => {
  // Public article page (mp.weixin.qq.com/s/...): everything is server-rendered.
  await ctx.readElement("#js_content", { waitMs: 15_000 });
  const text = (sel: string) => (document.querySelector(sel) as HTMLElement | null)?.innerText?.trim() ?? null;
  const content = document.querySelector("#js_content") as HTMLElement | null;
  const images = [...(content?.querySelectorAll("img") ?? [])].map((im) => im.getAttribute("data-src") || im.getAttribute("src") || "").filter((u) => u.startsWith("http"));
  const g = window as unknown as Record<string, unknown>;
  const num = (k: string) => (typeof g[k] === "string" || typeof g[k] === "number" ? Number(g[k]) : NaN);
  const ct = num("ct");
  const publishTime = Number.isFinite(ct) && ct > 0 ? new Date(ct * 1000).toISOString() : (text("#publish_time") ? null : null);
  const status = text("#js_content") === null ? (document.body?.innerText ?? "").slice(0, 120) : null;
  if (!content) throw new PageError("not_found", `article body not found: ${status ?? ""}`);
  return {
    id: String(p.id ?? location.pathname.split("/").pop()),
    url: location.href.split("#")[0],
    title: text("#activity-name") ?? document.title,
    author: text("#js_author_name") ?? text("#meta_content .rich_media_meta_text"),
    account_name: text("#js_name") ?? (typeof g.nickname === "string" ? (g.nickname as string) : null),
    biz: typeof g.biz === "string" ? g.biz : new URLSearchParams(location.search).get("__biz"),
    publish_time: publishTime,
    publish_time_text: text("#publish_time"),
    ip_wording: text("#js_ip_wording"),
    cover: (typeof g.msg_cdn_url === "string" ? (g.msg_cdn_url as string) : null) ?? document.querySelector('meta[property="og:image"]')?.getAttribute("content") ?? null,
    // #js_content stays visibility:hidden until the page's own JS reveals it, and innerText of a
    // hidden element is empty; textContent is what we want anyway.
    text: (content.textContent ?? "").replace(/\s+\n/g, "\n"),
    html: content.innerHTML.slice(0, 400_000),
    images,
  };
};

export const weixinMpPage: PagePlatform = {
  id: "weixin_mp",
  hosts: ["mp.weixin.qq.com"],
  riskSignals: [],
  actions: {
    search_users: searchUsers,
    get_user_posts: getUserPosts,
    get_user: getUser,
    get_post: getPost,
  },
};
