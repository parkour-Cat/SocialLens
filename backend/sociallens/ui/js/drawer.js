// Detail drawer: posts render in a layout per type (video / image / article / short text), users show
// their profile plus their posts, comments show the comment. Call-strategy platforms fetch the full detail
// automatically (debounced, memoised); navigate-strategy ones wait for a click because it costs a page load.
import { actCtx, $, esc, J, fmtN, fmtT, fmtDur, api, toast, on, act, go, logo, pname, pcolor, capsOf, strategy, itemKind, xs, IC, parseHash, hashFor } from "./core.js";
import { getList, listId, renderList, renderThread, avatar, titleOf, viewOf, viewSeg, setView } from "./results.js";

const D = { stack: [], cur: null, full: false, pushed: false, timer: null };
const DETAIL = new Map();   // "pid:id" -> merged full post
const key = (it) => `${it.platform}:${it.id}`;

function frame(it, extra = {}) {
  const kind = extra.kind || itemKind(it);
  const memo = kind === "posts" ? DETAIL.get(key(it)) : null;
  return { it: memo || it, kind, pid: it.platform, tab: extra.tab || "content", img: 0, detail: memo ? "done" : "idle", comments: null, uposts: null, hist: null, scroll: 0 };
}
export const isOpen = () => !!D.cur;

export function openItem(it, { tab, push = false, full } = {}) {
  if (!it) return;
  if (itemKind(it) === "topics") return act("topic", it.platform, it.title);
  if (push && D.cur) { D.cur.scroll = $("dr-scroll")?.scrollTop || 0; D.stack.push(D.cur); } else D.stack = [];
  D.cur = frame(it, { tab });
  if (full != null) D.full = full;
  render(); kick();
}
on("open", (lid, i) => openItem(getList(lid)?.[i], { push: !!actCtx().el?.closest("#drawer") }));
on("openTab", (lid, i, tab) => openItem(getList(lid)?.[i], { tab }));
on("openUser", (u) => openItem(u, { push: !!actCtx().el?.closest("#drawer") }));

export function close() {
  clearTimeout(D.timer);
  if (D.full && D.pushed) { D.pushed = false; D.full = false; D.cur = null; D.stack = []; history.back(); render(); return; }
  if (D.full) { D.full = false; const r = parseHash(); if (r.page === "post" || r.page === "user") go("search", {}, { replace: true }); }
  D.cur = null; D.stack = []; render();
}
on("drClose", close);
on("drBack", () => { const prev = D.stack.pop(); if (!prev) return; D.cur = prev; render(); requestAnimationFrame(() => { const s = $("dr-scroll"); if (s) s.scrollTop = prev.scroll; }); });
on("drFull", () => {
  const c = D.cur; if (!c) return;
  if (!D.full) { D.full = true; D.pushed = true; history.pushState(null, "", hashFor(c.kind === "users" ? "user" : "post", {}, [c.pid, c.it.id])); render(); }
  else if (D.pushed) { D.pushed = false; D.full = false; history.back(); render(); }
  else { D.full = false; go("search", {}, { replace: true }); render(); }
});
/** Router hook: called for #/post/<p>/<id> and #/user/<p>/<id> (bookmarks, reloads, back/forward). */
export async function openRoute(kind, pid, id) {
  if (D.cur && D.cur.pid === pid && String(D.cur.it.id) === String(id)) { D.full = true; render(); return; }
  D.full = true; D.pushed = false; D.stack = [];
  D.cur = { ...frame({ id, platform: pid }, { kind }), loading: true }; render();
  let it = null;
  try { it = (await api(`/items/${kind}/${encodeURIComponent(pid)}/${encodeURIComponent(id)}`)).data; } catch {}
  if (!it && kind === "posts" && capsOf(pid).has("get_post") && strategy(pid, "get_post") === "call") { try { it = (await api(`/${pid}/posts/${encodeURIComponent(id)}`)).data; } catch (e) { toast(e.message, true); } }
  if (!it && kind === "users" && capsOf(pid).has("get_user") && strategy(pid, "get_user") === "call") { try { it = (await api(`/${pid}/users/${encodeURIComponent(id)}`)).data; } catch (e) { toast(e.message, true); } }
  if (!D.cur || D.cur.pid !== pid || String(D.cur.it.id) !== String(id)) return;
  if (!it) { D.cur.loading = false; D.cur.missing = true; render(); return; }
  D.cur = frame({ ...it, platform: it.platform || pid }, { kind }); render(); kick();
}
/** Router hook: leaving a full-page route returns the drawer to a side panel. */
export function leaveRoute() { if (D.full) { D.full = false; D.pushed = false; render(); } }

// ---- data loading ---------------------------------------------------------------------------------
function kick() {
  clearTimeout(D.timer); const c = D.cur; if (!c) return;
  if (c.kind === "posts" && c.detail === "idle" && capsOf(c.pid).has("get_post") && strategy(c.pid, "get_post") === "call") D.timer = setTimeout(() => loadDetail(c), 450);
  if (c.kind === "users" && !c.uposts && capsOf(c.pid).has("get_user_posts") && strategy(c.pid, "get_user_posts") === "call") D.timer = setTimeout(() => loadUserPosts(c), 450);
  if (c.tab === "comments" && !c.comments) loadComments(c);
  if ((c.kind === "posts" || c.kind === "users") && !c.hist) loadHist(c);
}
async function loadDetail(c) {
  if (c.detail === "loading" || c.detail === "done") return;
  c.detail = "loading"; c.t0 = Date.now(); if (c === D.cur) render();
  try {
    const q = xs(c.it) ? `?xsec_token=${encodeURIComponent(xs(c.it))}` : "";
    const d = (await api(`/${c.pid}/posts/${encodeURIComponent(c.it.id)}${q}`)).data;
    const merged = { ...c.it }; for (const [k, v] of Object.entries(d || {})) if (v != null && !(Array.isArray(v) && !v.length) && v !== "") merged[k] = v;
    merged.raw = { ...(c.it.raw || {}), ...(d?.raw || {}) }; merged.metrics = { ...(c.it.metrics || {}), ...(d?.metrics || {}) };
    c.it = merged; c.detail = "done"; c.secs = ((Date.now() - c.t0) / 1000).toFixed(1); DETAIL.set(key(merged), merged);
  } catch (e) { c.detail = "error"; c.err = e.message; }
  if (c === D.cur) render();
}
async function loadComments(c, more) {
  if (c.comments?.loading) return;
  c.comments = { items: more ? c.comments.items : [], cursor: more ? c.comments.cursor : null, loading: true };
  if (c === D.cur) render();
  try {
    const q = new URLSearchParams(); if (more && c.comments.cursor) q.set("cursor", c.comments.cursor); if (xs(c.it)) q.set("xsec_token", xs(c.it));
    const r = await api(`/${c.pid}/posts/${encodeURIComponent(c.it.id)}/comments${q.toString() ? "?" + q : ""}`);
    c.comments = { items: c.comments.items.concat(r.data?.items || []), cursor: r.cursor || null, total: r.data?.total, loading: false };
  } catch (e) { c.comments = { ...c.comments, loading: false, err: e.message }; }
  if (c === D.cur) render();
}
on("drMoreComments", () => D.cur && loadComments(D.cur, true));
async function loadUserPosts(c, more) {
  if (c.uposts?.loading) return;
  c.uposts = { items: more ? c.uposts.items : [], cursor: more ? c.uposts.cursor : null, loading: true };
  if (c === D.cur) render();
  try {
    const q = new URLSearchParams(); if (more && c.uposts.cursor) q.set("cursor", c.uposts.cursor); if (xs(c.it)) q.set("xsec_token", xs(c.it));
    const r = await api(`/${c.pid}/users/${encodeURIComponent(c.it.id)}/posts${q.toString() ? "?" + q : ""}`);
    c.uposts = { items: c.uposts.items.concat(r.data?.items || []), cursor: r.cursor || null, loading: false };
  } catch (e) { c.uposts = { ...c.uposts, loading: false, err: e.message }; }
  if (c === D.cur) render();
}
on("drUserPosts", (more) => D.cur && loadUserPosts(D.cur, !!more));
async function loadHist(c) {
  c.hist = { snapshots: [] };
  try { c.hist = (await api(`/items/${c.kind}/${encodeURIComponent(c.pid)}/${encodeURIComponent(c.it.id)}/history`)).data; } catch {}
  if (c === D.cur && c.hist.snapshots?.length > 1) render();
}
on("drTab", (t) => { const c = D.cur; if (!c) return; c.tab = t; render(); kick(); });
on("drImg", (k) => { const c = D.cur; if (!c) return; c.img = k; c.gal = true; render(); });
on("drView", (pid, kind, v) => { setView(pid, kind, v); render(); });
on("download", async (platform, id, xsec, mediaIndex) => {
  if (!id) return toast("请填写帖子 id", true);
  try {
    const body = {}; if (xsec) body.xsec_token = xsec; if (mediaIndex != null) body.media_index = mediaIndex;
    const r = await api(`/${platform}/posts/${encodeURIComponent(id)}/download`, { method: "POST", body: JSON.stringify(body) });
    toast(`下载任务 ${r.task_id} 已开始`); act("badges");
  } catch (e) { toast(e.message, true); }
});

// ---- rich text: links, @mentions and #topics become clickable --------------------------------------
const TOKEN = /(https?:\/\/[^\s<>"'，。）)】\]]+)|#([^#\s]{1,40})#|#([\p{L}\p{N}_]{1,40})|@([\p{L}\p{N}_.\-]{1,30})/gu;
const ENT = { "&amp;": "&", "&lt;": "<", "&gt;": ">", "&quot;": '"', "&#39;": "'" };
/** Some sites (X) return text with HTML entities already applied; undo those before escaping once. */
export const unent = (s) => String(s ?? "").replace(/&(amp|lt|gt|quot|#39);/g, (m) => ENT[m]);
export function rich(text, pid, links = []) {
  text = unent(text);
  const tco = (links || []).filter((l) => l?.url); const short = [...text.matchAll(/https?:\/\/t\.co\/\w+/g)];
  const expand = tco.length && tco.length === short.length; let si = 0;
  let out = "", last = 0;
  for (const m of text.matchAll(TOKEN)) {
    out += esc(text.slice(last, m.index)); last = m.index + m[0].length;
    if (m[1]) {
      let url = m[1]; if (expand && /^https?:\/\/t\.co\//.test(url)) url = tco[si++].url;
      const shown = url.replace(/^https?:\/\/(www\.)?/, ""); out += `<a href="${esc(url)}" target="_blank" rel="noreferrer" title="${esc(url)}">${esc(shown.length > 46 ? shown.slice(0, 45) + "…" : shown)}<span class="ext">↗</span></a>`;
    } else if (m[2] || m[3]) {
      const t = m[2] || m[3]; out += `<span class="lk" data-act="quick" data-arg='${J([pid, "search_posts", { keyword: t }])}' title="在${esc(pname(pid))}搜索 #${esc(t)}">${esc(m[0])}</span>`;
    } else {
      const n = m[4]; out += `<span class="lk" data-act="quick" data-arg='${J([pid, "search_users", { keyword: n }])}' title="在${esc(pname(pid))}查找用户 ${esc(n)}">@${esc(n)}</span>`;
    }
  }
  return out + esc(text.slice(last));
}

// ---- rendering ------------------------------------------------------------------------------------
const TYPE_NAME = { video: "视频", image: "图文", article: "文章", text: "动态" };
const metricRow = (pairs) => { const xs2 = pairs.filter((x) => x[1] != null); return xs2.length ? `<div class="metrics">${xs2.map(([n, v]) => `<div><b class="num">${fmtN(v)}</b><span>${n}</span></div>`).join("")}</div>` : ""; };
const postMetrics = (m = {}) => metricRow([["赞", m.likes], ["评论", m.comments], ["收藏", m.collects], ["分享", m.shares], ["播放", m.views]]);
function authorRow(it) {
  const a = it.author; if (!a) return "";
  const u = { ...a, platform: a.platform || it.platform };
  return `<div class="author">${avatar(a, "aav")}<div class="ai"><div class="an">${esc(a.name || a.id)}</div><div class="as"><span class="mono">${esc(a.id || "")}</span>${a.metrics?.followers != null ? ` · <span>${fmtN(a.metrics.followers)} 粉丝</span>` : ""}${it.publish_time ? ` · <span>${esc(fmtT(it.publish_time))}</span>` : ""}</div></div>${a.id ? `<button class="btn sm" data-act="openUser" data-arg='${J([u])}'>TA 的主页</button>` : ""}</div>`;
}
const imgTag = (src, cls = "") => `<img class="${cls}" src="${esc(src)}" referrerpolicy="no-referrer" loading="lazy" onerror="this.classList.add('broken')" alt="">`;
function linkCard(c) { if (!c) return ""; return `<a class="lcard" href="${esc(c.url || "#")}" target="_blank" rel="noreferrer">${c.image ? imgTag(c.image) : ""}<div><span class="faint">${esc(c.domain || (c.url || "").replace(/^https?:\/\//, "").split("/")[0])}</span>${c.title ? `<b>${esc(c.title)}</b>` : ""}${c.description || c.preview ? `<span class="mute clamp2">${esc(c.description || c.preview)}</span>` : ""}</div></a>`; }
function quoteHtml(q, pid) { return `<div class="quote"><div class="who">${q.avatar_url ? imgTag(q.avatar_url, "av xs") : ""}<b>${esc(q.author || "")}</b>${q.author_id ? `<span class="mono faint">@${esc(q.author_id)}</span>` : ""}<span class="faint">${fmtT(q.publish_time)}</span></div>${q.text ? `<div class="body">${rich(q.text, pid)}</div>` : ""}${q.cover_url ? imgTag(q.cover_url, "qimg") : ""}${linkCard(q.article || q.card)}${q.url ? `<a class="faint" href="${esc(q.url)}" target="_blank" rel="noreferrer">查看被引用的帖子 ↗</a>` : ""}</div>`; }

function detailBanner(c) {
  if (!capsOf(c.pid).has("get_post")) return "";
  const nav = strategy(c.pid, "get_post") === "navigate";
  if (c.detail === "done") return `<div class="banner ok"><span class="dot ok"></span>已补全详情${c.secs ? ` · ${c.secs} 秒` : " · 本次会话已缓存"}</div>`;
  if (c.detail === "loading") return `<div class="banner ok"><span class="spin"></span>${nav ? "正在打开页面补全详情…" : "正在补全详情…"}</div>`;
  if (c.detail === "error") return `<div class="banner bad">补全失败：${esc(c.err)}<button class="btn sm" data-act="drDetail">重试</button></div>`;
  if (nav) return `<div class="banner warn">列表里的内容可能不完整。${esc(pname(c.pid))}补全要新开一个页面，占页面配额。<button class="btn sm" data-act="drDetail">加载完整内容</button></div>`;
  return "";
}
function gallery(c, imgs) {
  const k = Math.min(c.img, imgs.length - 1);
  return `<div class="gal"><div class="gmain">${imgTag(imgs[k])}${imgs.length > 1 ? `<button class="gnav prev" data-act="drImg" data-arg="${(k - 1 + imgs.length) % imgs.length}">‹</button><button class="gnav next" data-act="drImg" data-arg="${(k + 1) % imgs.length}">›</button><span class="gidx">${k + 1} / ${imgs.length}</span>` : ""}</div>${imgs.length > 1 ? `<div class="strip">${imgs.map((u, i) => `<button class="${i === k ? "on" : ""}" data-act="drImg" data-arg="${i}">${imgTag(u)}</button>`).join("")}</div>` : ""}</div>`;
}
function mediaFold(it) {
  const media = it.media || []; if (!media.length) return "";
  return `<details class="fold"><summary>媒体与下载 <span class="faint">${media.length}</span></summary><div class="fin">${media.map((m, i) => `<div class="mrow"><span class="pill">${esc(m.type)}</span><span class="mono ell mute">${esc(m.url)}</span>${m.width ? `<span class="faint num">${m.width}×${m.height}</span>` : ""}${m.duration ? `<span class="faint num">${fmtDur(m.duration)}</span>` : ""}<button class="btn ghost sm" data-act="download" data-arg='${J([it.platform, it.id, xs(it), i])}'>下载</button></div>`).join("")}<div class="mrow last"><button class="btn sm primary" data-act="download" data-arg='${J([it.platform, it.id, xs(it)])}'>${IC.dl}下载全部媒体</button></div></div></details>`;
}
const METRIC_NAMES = { likes: "赞", comments: "评论", shares: "分享", collects: "收藏", views: "播放", followers: "粉丝", following: "关注", posts: "作品" };
function histFold(c) {
  const h = c.hist?.snapshots || []; if (h.length < 2) return "";
  const keys = Object.keys(METRIC_NAMES).filter((k) => h.some((s) => s.metrics?.[k] != null));
  return `<details class="fold"><summary>指标变化 <span class="faint">${h.length}</span></summary><div class="fin"><table class="tbl mini"><thead><tr><th>时间</th>${keys.map((k) => `<th class="r">${METRIC_NAMES[k]}</th>`).join("")}</tr></thead><tbody>${h.slice(-12).map((s) => `<tr><td class="faint num">${esc(fmtT(s.at))}</td>${keys.map((k) => `<td class="r num">${fmtN(s.metrics?.[k])}</td>`).join("")}</tr>`).join("")}</tbody></table></div></details>`;
}
const rawFold = (it) => `<details class="fold"><summary>原始 JSON</summary><div class="fin"><pre>${esc(JSON.stringify(it, null, 2))}</pre></div></details>`;

function postContent(c) {
  const it = c.it, pid = c.pid, raw = it.raw || {}, parts = [detailBanner(c)];
  const images = (it.media || []).filter((m) => m.type === "image").map((m) => m.url);
  const video = (it.media || []).find((m) => m.type === "video");
  const type = it.type || (video ? "video" : images.length ? "image" : "text");
  const body = it.content ? `<div class="body">${rich(it.content, pid, raw.links)}</div>` : "";
  const tags = it.tags?.length ? `<div class="tags">${it.tags.map((t) => `<span class="tag" data-act="quick" data-arg='${J([pid, "search_posts", { keyword: t }])}'>#${esc(t)}</span>`).join("")}</div>` : "";
  const delta = it.metrics_then ? Object.keys(METRIC_NAMES).filter((k) => it.metrics_then[k] != null && it.metrics?.[k] != null && it.metrics_then[k] !== it.metrics[k]).map((k) => `${METRIC_NAMES[k]} ${fmtN(it.metrics_then[k])} → ${fmtN(it.metrics[k])}`).join(" · ") : "";
  if (type === "video") {
    parts.push(`<a class="video" href="${esc(it.url || "#")}" target="_blank" rel="noreferrer" title="在原平台播放">${it.cover_url ? imgTag(it.cover_url) : `<span class="vph"></span>`}<span class="play">${IC.play}</span>${video?.duration ? `<span class="dur">${fmtDur(video.duration)}</span>` : ""}<span class="vhint">在${esc(pname(pid))}播放 ↗</span></a>`);
    parts.push(`<h2 class="dtitle">${esc(titleOf(it))}</h2>`, postMetrics(it.metrics), authorRow(it), body, tags);
  } else if (type === "image") {
    const imgs = images.length ? images : it.cover_url ? [it.cover_url] : [];
    if (imgs.length) parts.push(gallery(c, imgs));
    if (it.title) parts.push(`<h2 class="dtitle">${esc(it.title)}</h2>`);
    parts.push(authorRow(it), body, tags, postMetrics(it.metrics));
  } else if (type === "article") {
    if (it.cover_url) parts.push(imgTag(it.cover_url, "acover"));
    parts.push(`<h2 class="dtitle big">${esc(titleOf(it))}</h2>`, authorRow(it), postMetrics(it.metrics));
    if (it.content) parts.push(`<div class="article">${it.content.split(/\n{2,}/).map((p) => `<p>${rich(p, pid, raw.links)}</p>`).join("")}</div>`);
    parts.push(tags);
  } else {
    const grid = images.length ? `<div class="igrid n${Math.min(images.length, 4)}">${images.slice(0, 4).map((u, i) => `<button data-act="drImg" data-arg="${i}">${imgTag(u)}</button>`).join("")}</div>` : it.cover_url ? imgTag(it.cover_url, "acover") : "";
    parts.push(`<div class="tweet">${authorRow(it)}${it.title ? `<h2 class="dtitle">${esc(it.title)}</h2>` : ""}${body}${c.gal && images.length ? gallery(c, images) : grid}${linkCard(raw.article || raw.card)}${raw.quoted ? quoteHtml(raw.quoted, pid) : ""}<div class="tm">${postMetrics(it.metrics)}</div></div>`, tags);
  }
  if (Array.isArray(raw.links) && raw.links.length) parts.push(`<div class="links"><span class="faint">正文链接</span>${raw.links.map((l) => `<a href="${esc(l.url)}" target="_blank" rel="noreferrer" title="${esc(l.url)}">${esc(l.url.replace(/^https?:\/\/(www\.)?/, ""))} ↗</a>`).join("")}</div>`);
  if (delta) parts.push(`<div class="banner ok"><span>当时</span> → <span>现在</span>：${esc(delta)}</div>`);
  parts.push(mediaFold(it), histFold(c), rawFold(it));
  return parts.join("");
}
function commentsTab(c) {
  const s = c.comments;
  if (!s || (s.loading && !s.items.length)) return `<div class="skel">${Array.from({ length: 4 }, () => `<div class="skrow"><div class="sk" style="width:30px;height:30px;border-radius:50%"></div><div class="skcol"><div class="sk" style="height:12px;width:30%"></div><div class="sk" style="height:14px;width:85%"></div></div></div>`).join("")}</div>`;
  if (s.err && !s.items.length) return `<div class="banner bad">${esc(s.err)}<button class="btn sm" data-act="drMoreComments">重试</button></div>`;
  if (!s.items.length) return `<div class="empty">没有评论</div>`;
  return `<div class="chead"><b>${fmtN(c.it.metrics?.comments ?? s.total ?? s.items.length)} 条评论</b><span class="faint">· 已加载 ${s.items.length}</span></div>${renderThread(s.items, c.pid, null, { postId: c.it.id, xsec: xs(c.it), rich })}${s.cursor ? `<div class="more"><button class="btn sm" data-act="drMoreComments" ${s.loading ? "disabled" : ""}>${s.loading ? "加载中…" : "加载更多评论"}</button></div>` : ""}`;
}
function userContent(c) {
  const u = c.it, m = u.metrics || {}, parts = [];
  parts.push(`<div class="uhead">${avatar(u, "uav big")}<div><h2 class="dtitle">${esc(u.name || u.id)}</h2><div class="mono faint">${esc(u.id)}</div></div>${u.url ? `<a class="btn sm" href="${esc(u.url)}" target="_blank" rel="noreferrer">主页 ↗</a>` : ""}</div>`);
  if (u.bio) parts.push(`<div class="body">${rich(u.bio, c.pid)}</div>`);
  parts.push(metricRow([["粉丝", m.followers], ["关注", m.following], ["作品", m.posts], ["获赞", m.likes]]));
  if (capsOf(c.pid).has("get_user_posts")) {
    const s = c.uposts; const nav = strategy(c.pid, "get_user_posts") === "navigate";
    const head = `<div class="sechead"><b>TA 的帖子</b>${s?.items?.length ? `<span class="faint">${s.items.length}</span>` : ""}<span class="sp"></span>${s?.items?.length ? viewSeg(c.pid, "posts", "drView") : ""}</div>`;
    if (!s) parts.push(head + `<div class="banner ${nav ? "warn" : "ok"}">${nav ? `${esc(pname(c.pid))}要新开页面加载，占页面配额。` : "准备加载…"}<button class="btn sm" data-act="drUserPosts">加载 TA 的帖子</button></div>`);
    else if (s.loading && !s.items.length) parts.push(head + `<div class="skel">${Array.from({ length: 3 }, () => `<div class="skrow"><div class="sk" style="width:96px;height:54px"></div><div class="skcol"><div class="sk" style="height:14px;width:70%"></div></div></div>`).join("")}</div>`);
    else if (s.err && !s.items.length) parts.push(head + `<div class="banner bad">${esc(s.err)}<button class="btn sm" data-act="drUserPosts">重试</button></div>`);
    else parts.push(head + `<div class="ulist">${renderList(s.items, "posts", c.pid, viewOf(c.pid, "posts"))}</div>${s.cursor ? `<div class="more"><button class="btn sm" data-act="drUserPosts" data-arg="[true]" ${s.loading ? "disabled" : ""}>${s.loading ? "加载中…" : "加载更多"}</button></div>` : ""}`);
  }
  parts.push(histFold(c), rawFold(u));
  return parts.join("");
}
function commentContent(c) {
  const x = c.it;
  return [authorRow({ ...x, author: x.author }), `<div class="body">${rich(x.content || "", c.pid)}</div>`, metricRow([["赞", x.likes]]), `<div class="faint mono">post ${esc(x.post_id || "")}${x.parent_id ? ` · parent ${esc(x.parent_id)}` : ""}</div>`, rawFold(x)].join("");
}

export function render() {
  const el = $("drawer"), c = D.cur;
  document.body.classList.toggle("dr-open", !!c); el.classList.toggle("open", !!c); el.classList.toggle("full", !!c && D.full); $("scrim").classList.toggle("open", !!c && !D.full);
  if (!c) return;
  const keep = $("dr-scroll")?.dataset.key === key(c.it) ? $("dr-scroll").scrollTop : 0;
  const it = c.it, typeName = c.kind === "users" ? "用户" : c.kind === "comments" ? "评论" : TYPE_NAME[it.type] || "帖子";
  const tabs = c.kind === "posts" && capsOf(c.pid).has("get_comments")
    ? `<div class="tabs"><button class="${c.tab === "content" ? "on" : ""}" data-act="drTab" data-arg='"content"'>内容</button><button class="${c.tab === "comments" ? "on" : ""}" data-act="drTab" data-arg='"comments"'>评论 <span class="faint num">${it.metrics?.comments != null ? fmtN(it.metrics.comments) : ""}</span></button></div>` : "";
  const body = c.loading ? `<div class="skel"><div class="sk" style="height:220px"></div><div class="sk" style="height:18px;width:70%"></div><div class="sk" style="height:14px;width:40%"></div></div>`
    : c.missing ? `<div class="empty">本地缓存里没有这一条。<br>${c.kind === "posts" && capsOf(c.pid).has("get_post") ? `<button class="btn sm" data-act="drDetail" style="margin-top:10px">从${esc(pname(c.pid))}加载</button>` : ""}</div>`
    : c.kind === "users" ? userContent(c) : c.kind === "comments" ? commentContent(c) : c.tab === "comments" ? commentsTab(c) : postContent(c);
  el.innerHTML = `<div class="dh">${D.stack.length ? `<button class="iconbtn" data-act="drBack" title="返回">${IC.back}</button>` : ""}${logo(c.pid)}<span class="dhp">${esc(pname(c.pid))}</span><span class="pill">${typeName}</span><span class="mono faint ell">${esc(it.id)}</span><span class="sp"></span>${it.url ? `<a class="iconbtn" href="${esc(it.url)}" target="_blank" rel="noreferrer" title="在原平台打开">${IC.ext}</a>` : ""}<button class="iconbtn" data-act="drFull" title="${D.full ? "收起为侧栏" : "展开为全宽详情页"}">${D.full ? IC.shrink : IC.expand}</button><button class="iconbtn" data-act="drClose" title="关闭（Esc）">${IC.x}</button></div>${tabs}<div class="db" id="dr-scroll" data-key="${esc(key(it))}"><div class="dbi" style="--pc:${pcolor(c.pid)}">${body}</div></div>`;
  if (keep) $("dr-scroll").scrollTop = keep;
}
// drDetail also covers route items missing from the cache: fetch get_post by id
on("drDetail", () => { const c = D.cur; if (!c) return; if (c.missing) { c.missing = false; c.kind = "posts"; c.detail = "idle"; c.it = { id: c.it.id, platform: c.pid }; } loadDetail(c); });
$("scrim").addEventListener("click", close);
