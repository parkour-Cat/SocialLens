// Shared plumbing: API client, formatting, platform metadata, the click-action registry and the hash router.
import { ZH } from "./i18n.js";

export const API = "/api/v1";
export const $ = (id) => document.getElementById(id);
export const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
/** JSON for an HTML attribute (data-arg). */
export const J = (v) => esc(JSON.stringify(v ?? null));
export const fmtN = (n) => n == null ? "–" : ZH ? (n >= 1e8 ? (n / 1e8).toFixed(1) + "亿" : n >= 1e4 ? (n / 1e4).toFixed(1).replace(/\.0$/, "") + "万" : String(n)) : (n >= 1e6 ? (n / 1e6).toFixed(1) + "M" : n >= 1e3 ? (n / 1e3).toFixed(1) + "K" : String(n));
// Times come from the backend in UTC ISO; show them in local time (unparseable platform times fall back to raw text).
export const fmtT = (t) => { if (!t) return "–"; const d = new Date(String(t)); if (Number.isNaN(d.getTime())) return String(t).replace("T", " ").slice(5, 16); const p = (n) => String(n).padStart(2, "0"); return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`; };
export const fmtB = (b) => b == null ? "–" : b >= 1 << 30 ? (b / (1 << 30)).toFixed(2) + " GB" : b >= 1 << 20 ? (b / (1 << 20)).toFixed(1) + " MB" : b >= 1024 ? (b / 1024).toFixed(0) + " KB" : b + " B";
export const fmtDur = (s) => { if (!s) return ""; s = Math.round(s); const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), x = s % 60; const p = (n) => String(n).padStart(2, "0"); return h ? `${h}:${p(m)}:${p(x)}` : `${m}:${p(x)}`; };

export const store = {
  get(k, d) { try { const v = localStorage.getItem("sl_" + k); return v == null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem("sl_" + k, JSON.stringify(v)); } catch {} },
  sget(k, d) { try { const v = sessionStorage.getItem("sl_" + k); return v == null ? d : JSON.parse(v); } catch { return d; } },
  sset(k, v) { try { sessionStorage.setItem("sl_" + k, JSON.stringify(v)); } catch {} },
};

let toastTimer;
export function toast(text, bad) {
  const m = $("toast"); m.textContent = text; m.classList.toggle("bad", !!bad); m.classList.add("show");
  clearTimeout(toastTimer); toastTimer = setTimeout(() => m.classList.remove("show"), bad ? 6000 : 2500);
}

export async function api(path, opts) {
  const res = await fetch(API + path, { headers: { "content-type": "application/json" }, ...opts });
  let body; try { body = await res.json(); } catch { body = { error: { code: "http_" + res.status, message: await res.text() } }; }
  if (!res.ok || body.success === false) { const e = body.error || {}; const err = new Error(`${e.code || res.status}: ${e.message || ""}`); err.code = e.code; throw err; }
  return body;
}

// ---- global state shared by pages -------------------------------------------------------------
export const S = { platforms: [], status: null, health: null, page: null };

// ---- platforms ------------------------------------------------------------------------------------
export const LOGOS = {
  bilibili: { bg: "#00A1D6", mark: "B" }, xiaohongshu: { bg: "#FF2442", mark: "红" }, douyin: { bg: "#161823", mark: "抖" }, kuaishou: { bg: "#FF4906", mark: "快" },
  weixin_mp: { bg: "#07C160", mark: "公" }, weixin_channels: { bg: "#FA9D3B", mark: "视" }, youtube: { bg: "#FF0000", mark: "▶" }, x: { bg: "#71717A", mark: "X" },
  reddit: { bg: "#FF4500", mark: "r/" }, zhihu: { bg: "#0066FF", mark: "知" }, tiktok: { bg: "#25F4EE", mark: "T" },
  instagram: { bg: "#E1306C", mark: "ig" }, linkedin: { bg: "#0A66C2", mark: "in" }, toutiao: { bg: "#ED4040", mark: "头" },
};
export const pcolor = (id) => (LOGOS[id] || { bg: "#888" }).bg;
const ICONS = window.PLATFORM_ICONS || {};
export const plat = (id) => S.platforms.find((p) => p.id === id);
export const pname = (id) => id === "_system" ? "系统" : (plat(id)?.name || id);
export function logo(id, size = "sm") {
  const l = LOGOS[id] || { bg: "#666", mark: "?" }; const ico = ICONS[id];
  return `<span class="plogo ${size}" style="--pc:${l.bg}" title="${esc(pname(id))}">${ico ? `<img src="${ico}" alt="">` : esc(l.mark)}</span>`;
}
export const capsOf = (pid) => new Set((plat(pid)?.capabilities || []).map((c) => c.action));
/** "call" (cheap request inside an open tab) or "navigate" (opens a page, spends the page-load budget). */
export const strategy = (pid, action) => (plat(pid)?.capabilities || []).find((c) => c.action === action)?.strategy || "call";
export const loggedOut = (pid) => S.status?.platforms?.[pid]?.logged_in === false;

export const ACTIONS = [
  ["search_posts", "搜索内容"], ["search_users", "搜索用户"], ["get_post", "帖子详情"], ["get_comments", "评论"], ["get_replies", "评论的回复"],
  ["get_user", "用户资料"], ["get_user_posts", "用户的帖子"], ["get_feed", "推荐流"], ["get_trending", "热榜"],
];
export const LIST_ACTIONS = new Set(["search_posts", "search_users", "get_comments", "get_replies", "get_user_posts", "get_feed", "get_trending"]);
export const ORDERS = { bilibili: { search_posts: [["totalrank", "综合"], ["click", "播放"], ["pubdate", "最新"]], get_user_posts: [["pubdate", "最新"], ["click", "播放"]], get_comments: [["3", "热门"], ["2", "时间"]] }, x: { search_posts: [["live", "最新"], ["top", "热门"]] }, reddit: { search_posts: [["relevance", "相关"], ["hot", "热门"], ["top", "最高"], ["new", "最新"]], get_user_posts: [["new", "最新"], ["hot", "热门"], ["top", "最高"]], get_comments: [["confidence", "最佳"], ["top", "最高"], ["new", "最新"]] }, zhihu: { get_user_posts: [["answers", "回答"], ["articles", "文章"]] } };
export const DEBUG_ACTIONS = new Set(["echo", "fetch", "wait_capture", "read_global", "scroll_capture", "dom_probe", "list_captures", "find_scripts", "read_element", "click", "type"]);
export const isDebugTask = (t) => DEBUG_ACTIONS.has(t.action) || (t.action === "navigate" && DEBUG_ACTIONS.has(t.params?.page_action));
export function actionName(a) { return ({ download: "下载", collect: "连续拉取", navigate: "打开页面", echo: "echo" }[a]) || (ACTIONS.find((x) => x[0] === a)?.[1]) || a; }
export function itemKind(it) { if (!it) return "posts"; if (it.type === "topic") return "topics"; if ("post_id" in it && "likes" in it) return "comments"; if (it.metrics && "followers" in it.metrics && !("type" in it)) return "users"; return "posts"; }
export const xs = (it) => it?.raw?.xsec_token || "";
export function taskSummary(t) {
  const p = t.params || {}, r = t.result || {};
  if (t.action === "collect") return `${actionName(p.action)} ${p.params?.keyword || p.params?.post_id || p.params?.id || ""} · ${r.count || 0} 条 ${r.pages || 0} 页`;
  if (t.action === "download") return `${r.title || p.post_id || ""}`;
  const pp = p.page_params || {};
  const key = [p.keyword ?? pp.keyword, p.post_id ?? pp.post_id ?? p.id ?? pp.id, p.comment_id ?? pp.comment_id].filter(Boolean).join(" ").slice(0, 60);
  return p.more ? (key ? `${key} · 续页` : "续页") : key;
}
export function statusPill(t) { const m = { done: ["neutral", "完成"], failed: ["bad", t.error?.code || "失败"], running: ["ok", "执行中"], queued: ["accent", "排队"], cancelled: ["neutral", "已取消"] }[t.status] || ["neutral", t.status]; return `<span class="pill ${m[0]}">${esc(m[1])}</span>`; }
export const isActive = (t) => t.status === "running" || t.status === "queued";

// ---- click actions ----------------------------------------------------------------------------------
// Markup says <button data-act="name" data-arg='[...]'>; modules register handlers with on(). The innermost
// [data-act] wins, so a button inside a clickable row never also opens the row.
const ACTS = {};
let CTX = {};
/** The element / event behind the current data-act click (handlers get only their data-arg values). */
export const actCtx = () => CTX;
export const on = (name, fn) => { ACTS[name] = fn; };
export const act = (name, ...args) => ACTS[name]?.(...args);
document.addEventListener("click", (e) => {
  const el = e.target.closest("[data-act]"); if (!el) return;
  const a = e.target.closest("a[href]"); if (a && a !== el && el.contains(a)) return; // plain links inside rows
  const fn = ACTS[el.dataset.act]; if (!fn) return;
  if (el.tagName === "A") e.preventDefault();
  let args = []; try { args = el.dataset.arg ? JSON.parse(el.dataset.arg) : []; } catch {}
  CTX = { el, event: e }; try { fn(...(Array.isArray(args) ? args : [args])); } finally { CTX = {}; }
});

// ---- hash router ------------------------------------------------------------------------------------
// #/search?p=bilibili,x&a=search_posts&q=… · #/data?k=… · #/tasks?tab=… · #/status · #/api?p=… · #/post/<p>/<id> · #/user/<p>/<id>
export function parseHash(h = location.hash) {
  const raw = h.replace(/^#\/?/, ""); const [path, qs] = raw.split("?");
  const parts = (path || "").split("/").map(decodeURIComponent);
  return { page: parts[0] || "search", rest: parts.slice(1), params: new URLSearchParams(qs || "") };
}
export function hashFor(page, params, rest = []) {
  const q = params instanceof URLSearchParams ? params : new URLSearchParams(Object.entries(params || {}).filter(([, v]) => v != null && v !== ""));
  const s = q.toString();
  return `#/${[page, ...rest.map(encodeURIComponent)].join("/")}${s ? "?" + s : ""}`;
}
export function go(page, params, { replace = false, rest = [] } = {}) {
  const h = hashFor(page, params, rest);
  if (h === location.hash) { window.dispatchEvent(new HashChangeEvent("hashchange")); return; }
  if (replace) { history.replaceState(null, "", h); window.dispatchEvent(new HashChangeEvent("hashchange")); } else location.hash = h;
}

export function saveBlob(name, text, type) { const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([text], { type })); a.download = name; a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 1000); }
export function exportJSON(items, name) { if (!items?.length) return toast("没有数据可导出", true); saveBlob(`${name}-${Date.now()}.json`, JSON.stringify(items, null, 2), "application/json"); }
function flat(it) {
  const k = itemKind(it);
  if (k === "topics") return { rank: it.rank, platform: it.platform, title: it.title, heat: it.heat, category: it.category, description: it.description, url: it.url };
  if (k === "users") return { id: it.id, platform: it.platform, name: it.name, url: it.url, followers: it.metrics?.followers, following: it.metrics?.following, posts: it.metrics?.posts, bio: it.bio, avatar_url: it.avatar_url, xsec_token: it.raw?.xsec_token };
  if (k === "comments") return { id: it.id, platform: it.platform, post_id: it.post_id, parent_id: it.parent_id, author_id: it.author?.id, author_name: it.author?.name, content: it.content, likes: it.likes, publish_time: it.publish_time };
  return { id: it.id, platform: it.platform, type: it.type, title: it.title, content: it.content, author_id: it.author?.id, author_name: it.author?.name, url: it.url, likes: it.metrics?.likes, comments: it.metrics?.comments, shares: it.metrics?.shares, collects: it.metrics?.collects, views: it.metrics?.views, publish_time: it.publish_time, cover_url: it.cover_url, media_urls: (it.media || []).map((m) => m.url).join(" | "), tags: (it.tags || []).join(" | "), xsec_token: it.raw?.xsec_token };
}
export function exportCSV(items, name) {
  if (!items?.length) return toast("没有数据可导出", true);
  const rows = items.map(flat); const cols = Object.keys(rows[0]);
  const cell = (v) => { const s = v == null ? "" : String(v); return /[",\n\r]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s; };
  saveBlob(`${name}-${Date.now()}.csv`, "﻿" + [cols.join(","), ...rows.map((r) => cols.map((c) => cell(r[c])).join(","))].join("\r\n"), "text/csv;charset=utf-8");
}
export function copyText(t) { navigator.clipboard.writeText(t).then(() => toast("已复制"), () => toast("复制失败", true)); }
on("copy", (t) => copyText(t));

export const IC = {
  search: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>',
  data: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v14c0 1.7 3.6 3 8 3s8-1.3 8-3V5"/><path d="M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3"/></svg>',
  tasks: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M9 6h11M9 12h11M9 18h11"/><path d="m3 6 1 1 2-2M3 12l1 1 2-2M3 18l1 1 2-2"/></svg>',
  status: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12h4l3-8 4 16 3-8h4"/></svg>',
  api: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m8 7-5 5 5 5M16 7l5 5-5 5"/></svg>',
  globe: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c3 3.5 3 14.5 0 18M12 3c-3 3.5-3 14.5 0 18"/></svg>',
  sun: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>',
  moon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg>',
  auto: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9"/><path d="M12 3v18a9 9 0 0 0 0-18z" fill="currentColor"/></svg>',
  expand: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7"/></svg>',
  shrink: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M4 14h6v6M20 10h-6V4M14 10l7-7M3 21l7-7"/></svg>',
  ext: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/></svg>',
  x: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M6 6l12 12M18 6 6 18"/></svg>',
  back: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M15 18l-6-6 6-6"/></svg>',
  table: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M4 6h16M4 12h16M4 18h16"/></svg>',
  grid: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="4" y="4" width="7" height="7" rx="1.5"/><rect x="13" y="4" width="7" height="7" rx="1.5"/><rect x="4" y="13" width="7" height="7" rx="1.5"/><rect x="13" y="13" width="7" height="7" rx="1.5"/></svg>',
  play: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>',
  dl: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M12 4v11M7 10l5 5 5-5M5 20h14"/></svg>',
};
