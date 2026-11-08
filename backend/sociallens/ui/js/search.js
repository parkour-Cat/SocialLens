// 搜索 page: one command bar for single-platform actions (every capability) and multi-platform search
// (cmd/ctrl+click a second chip). Every run pushes a #/search?… entry; results are cached per entry
// (memory + sessionStorage) so back / forward / reload restore them without hitting the site again.
import { actCtx, $, esc, J, fmtN, fmtT, api, toast, on, act, S, store, plat, pname, logo, pcolor, capsOf, loggedOut, ACTIONS, LIST_ACTIONS, ORDERS, actionName, itemKind, hashFor, exportJSON, exportCSV, IC } from "./core.js";
import { renderList, viewOf, viewSeg, setView, skeleton } from "./results.js";
import { openItem, close as closeDrawer } from "./drawer.js";

const F = store.get("form", { sel: [], action: "search_posts", keyword: "", id: "", cid: "", xsec: "", order: "", mode: "page", limit: 200, mtype: "post" });
F.sel = (F.sel || []).slice(0, 14);
let R = null;              // current result: { single } | { multi }
let loading = null;        // { t0, text }
let showAll = store.get("chipsAll", false);
const CACHE = new Map(Object.entries(store.sget("results", {})));
const saveForm = () => store.set("form", F);
function cachePut(k, v) {
  CACHE.set(k, v); while (CACHE.size > 12) CACHE.delete(CACHE.keys().next().value);
  try { store.sset("results", Object.fromEntries(CACHE)); } catch { /* quota: memory cache still works */ }
}
const multi = () => F.sel.length > 1;
const one = () => F.sel[0];

// ---- form <-> hash ------------------------------------------------------------------------------
function formParams() {
  const p = { p: F.sel.join(",") };
  if (multi()) { p.t = F.mtype; p.q = F.keyword; return p; }
  p.a = F.action;
  if (F.action.startsWith("search_")) p.q = F.keyword;
  if (["get_post", "get_comments", "get_replies", "get_user", "get_user_posts"].includes(F.action)) p.id = F.id;
  if (F.action === "get_replies") p.cid = F.cid;
  if (F.xsec && needsXsec()) p.x = F.xsec;
  if (F.order && orders()) p.o = F.order;
  if (F.mode === "collect" && LIST_ACTIONS.has(F.action)) { p.m = "collect"; p.n = F.limit; }
  return p;
}
function formFromParams(q) {
  const ps = (q.get("p") || "").split(",").filter((id) => plat(id)); if (!ps.length) return false;
  F.sel = ps; F.keyword = q.get("q") || ""; F.mtype = q.get("t") || F.mtype;
  if (ps.length === 1) { F.action = q.get("a") || "search_posts"; F.id = q.get("id") || ""; F.cid = q.get("cid") || ""; F.xsec = q.get("x") || ""; F.order = q.get("o") || ""; F.mode = q.get("m") === "collect" ? "collect" : "page"; F.limit = Number(q.get("n")) || F.limit; }
  return true;
}
const keyOf = () => hashFor("search", formParams());
const orders = () => ORDERS[one()]?.[F.action] || null;
const needsXsec = () => one() === "xiaohongshu" && ["get_post", "get_comments", "get_replies", "get_user", "get_user_posts"].includes(F.action);
const availActions = () => { const caps = capsOf(one()); return ACTIONS.filter(([a]) => caps.has(a)); };

/** Router entry: #/search?… */
export function show(q) {
  if (!S.platforms.length) return;
  if (!F.sel.length || !F.sel.every((id) => plat(id))) F.sel = [S.platforms[0].id];
  if (q && q.get("p")) {
    formFromParams(q);
    const k = location.hash; R = CACHE.get(k) || null;
  }
  fixAction(); saveForm(); render();
}
function fixAction() {
  if (multi()) return;
  const acts = availActions().map(([a]) => a);
  if (!acts.includes(F.action)) F.action = acts[0] || "search_posts";
  if (!LIST_ACTIONS.has(F.action)) F.mode = "page";
  const os = orders(); if (os && !os.some(([v]) => v === F.order)) F.order = os[0][0]; if (!os) F.order = "";
}

// ---- rendering ------------------------------------------------------------------------------------
function usageOrder() { const u = store.get("pusage", {}); return S.platforms.map((p, i) => [p, (u[p.id] || 0) * 100 - i]).sort((a, b) => b[1] - a[1]).map(([p]) => p); }
function chips() {
  const ordered = usageOrder(); const pinned = new Set(ordered.slice(0, 7).map((p) => p.id));
  const list = showAll ? S.platforms : S.platforms.filter((p) => pinned.has(p.id) || F.sel.includes(p.id));
  const rest = S.platforms.length - list.length;
  const usable = (p) => !multi() || capsOf(p.id).has(F.mtype === "user" ? "search_users" : "search_posts");
  return `<div class="chips">${list.map((p) => `<button class="chip${F.sel.includes(p.id) ? " on" : ""}${loggedOut(p.id) ? " off" : ""}${usable(p) ? "" : " dim"}" style="--pc:${pcolor(p.id)}" data-act="chip" data-arg='${J(p.id)}' title="${loggedOut(p.id) ? "未登录" : ""}">${logo(p.id)}<span>${esc(p.name)}</span></button>`).join("")}${rest > 0 ? `<button class="chip more" data-act="chipsAll" data-arg="true">+${rest}</button>` : showAll ? `<button class="chip more" data-act="chipsAll" data-arg="false">收起</button>` : ""}<span class="hint"><kbd>⌘</kbd> + 点击 多选平台</span></div>`;
}
function cmdBar() {
  const m = multi();
  const fields = [];
  if (m) {
    fields.push(`<div class="seg"><button class="${F.mtype === "post" ? "on" : ""}" data-act="mtype" data-arg='"post"'>帖子</button><button class="${F.mtype === "user" ? "on" : ""}" data-act="mtype" data-arg='"user"'>用户</button></div>`);
    fields.push(`<div class="kw">${IC.search}<input id="f-keyword" class="field" value="${esc(F.keyword)}" placeholder="关键词" autocomplete="off"><kbd>/</kbd></div>`);
    fields.push(`<div class="seg dis" title="多平台只拉一页"><button class="on">一页</button><button>连续到 N 条</button></div>`);
  } else {
    fields.push(`<select id="f-action" class="field">${availActions().map(([a, n]) => `<option value="${a}" ${a === F.action ? "selected" : ""}>${n}</option>`).join("")}</select>`);
    if (F.action.startsWith("search_")) fields.push(`<div class="kw">${IC.search}<input id="f-keyword" class="field" value="${esc(F.keyword)}" placeholder="关键词，或粘贴帖子 / 用户链接" autocomplete="off"><kbd>/</kbd></div>`);
    if (["get_post", "get_comments", "get_replies", "get_user", "get_user_posts"].includes(F.action)) fields.push(`<div class="kw">${IC.search}<input id="f-id" class="field" value="${esc(F.id)}" placeholder="${F.action.startsWith("get_user") ? "用户 id / @handle / 用户名，或粘贴链接" : "帖子 id（BV 号、笔记 id、视频 id、推文 id），或粘贴链接"}" autocomplete="off"><kbd>/</kbd></div>`);
    if (F.action === "get_replies") fields.push(`<input id="f-cid" class="field w160" value="${esc(F.cid)}" placeholder="评论 id">`);
    if (needsXsec()) fields.push(`<input id="f-xsec" class="field w160" value="${esc(F.xsec)}" placeholder="xsec_token">`);
    if (["get_feed", "get_trending"].includes(F.action)) fields.push(`<div class="kw ghost">${esc(actionName(F.action))} · ${esc(pname(one()))}</div>`);
    const os = orders(); if (os) fields.push(`<div class="seg">${os.map(([v, n]) => `<button class="${F.order === v ? "on" : ""}" data-act="order" data-arg='${J(v)}'>${n}</button>`).join("")}</div>`);
    if (LIST_ACTIONS.has(F.action)) fields.push(`<div class="seg"><button class="${F.mode === "page" ? "on" : ""}" data-act="mode" data-arg='"page"'>一页</button><button class="${F.mode === "collect" ? "on" : ""}" data-act="mode" data-arg='"collect"'><span>连续到</span><input id="f-limit" type="number" min="1" max="1000" value="${esc(F.limit)}"><span>条</span></button></div>`);
  }
  const busy = !!loading;
  fields.push(`<button class="btn primary" data-act="run" ${busy ? "disabled" : ""}>${busy ? `<span class="spin"></span>` : ""}${m ? `同时搜索 ${F.sel.length} 个平台` : F.mode === "collect" && LIST_ACTIONS.has(F.action) ? "连续拉取" : "查询"}</button>`);
  const note = m ? `<div class="cnote warn">多平台只拉一页，避免同时撞上多个平台的风控。要翻页或连续拉取，点分组右上角的「在单平台下翻页」。</div>`
    : F.mode === "collect" && LIST_ACTIONS.has(F.action) ? `<div class="cnote">将创建连续拉取任务，在后台翻页直到够数；进度也能在「任务」页看到。</div>` : "";
  return `<div class="cmd" id="cmd">${chips()}<div class="frow">${fields.join("")}</div>${note}</div>`;
}
function resultHead(s) {
  const ctx = `${logo(s.pid)}<b>${esc(pname(s.pid))}</b><span class="faint">·</span><span>${esc(actionName(s.action))}</span>${s.key ? `<span class="faint">·</span><span class="mono strong ell">${esc(s.key)}</span>` : ""}`;
  const count = `${s.items.length} 条${s.total ? "，共约 " + fmtN(s.total) : ""}${s.collect ? "" : s.cursor ? "，可翻页" : "，没有更多"}`;
  const meta = [count, s.secs ? `${s.secs} 秒` : "", s.source || "", s.at ? `查询于 ${fmtT(new Date(s.at).toISOString())}` : ""].filter(Boolean).map((x) => `<span>${esc(x)}</span>`).join(`<span class="faint">·</span>`);
  return `<div class="rh">${ctx}<span class="rmeta faint">${meta}</span><span class="sp"></span>${viewSeg(s.pid, s.kind)}<button class="btn ghost sm" data-act="export" data-arg='"json"'>导出 JSON</button><button class="btn ghost sm" data-act="export" data-arg='"csv"'>导出 CSV</button>${s.cursor ? `<button class="btn sm" data-act="next" ${loading ? "disabled" : ""}>下一页</button>` : ""}</div>`;
}
function results() {
  if (loading && !R?.single?.items?.length && !loading.multi) return `<section class="res"><div class="rh"><span class="spin"></span><span>${esc(loading.text)}</span></div>${skeleton()}</section>`;
  if (loading?.multi) return loading.multi.map((pid) => `<section class="res grp" style="--pc:${pcolor(pid)}"><div class="rh">${logo(pid)}<b>${esc(pname(pid))}</b><span class="spin"></span><span class="faint">搜索中…</span></div>${skeleton(3)}</section>`).join("");
  if (!R) return `<section class="res"><div class="hero"><div class="hico">${IC.search}</div><div class="ht">选平台、填关键词，回车查询</div><div class="faint">也可以直接粘贴帖子或用户链接。<kbd>⌘</kbd> + 点击平台可以同时搜索多个平台。</div></div></section>`;
  if (R.multi) {
    const kind = R.multi.type === "user" ? "users" : "posts";
    return R.multi.results.map((e) => {
      const q = e.quota || {};
      const stat = e.error ? `<span class="err ell" title="${esc(e.error.message)}">${esc(e.error.code)}: ${esc(e.error.message)}</span>` : `<span>${e.items.length} 条${e.total ? "，共约 " + fmtN(e.total) : ""}${e.cursor ? "，可翻页" : "，没有更多"}</span>`;
      const quota = q.page_loads ? `<span class="faint">页面 ${q.page_loads_used}/${q.page_loads} · ${Math.round(q.window_s / 60)} 分钟</span>` : "";
      return `<section class="res grp" style="--pc:${pcolor(e.platform)}"><div class="rh">${logo(e.platform)}<b>${esc(pname(e.platform))}</b>${stat}${quota}<span class="sp"></span>${e.items.length ? viewSeg(e.platform, kind) + `<button class="btn ghost sm" data-act="handoff" data-arg='${J(e.platform)}'>在单平台下翻页 →</button>` : ""}</div>${e.items.length ? renderList(e.items, kind, e.platform, viewOf(e.platform, kind)) : e.error ? "" : `<div class="empty">没有结果</div>`}</section>`;
    }).join("");
  }
  const s = R.single;
  const prog = loading?.collect ? `<div class="progress"><i style="width:${Math.min(100, (loading.collect.count || 0) / (loading.collect.limit || 1) * 100)}%"></i></div>` : "";
  return `<section class="res">${resultHead(s)}${prog}${loading && !loading.collect ? `<div class="rbusy"><span class="spin"></span>${esc(loading.text)}</div>` : ""}${s.error ? `<div class="banner bad">${esc(s.error)}</div>` : ""}${renderList(s.items, s.kind, s.pid, viewOf(s.pid, s.kind))}</section>`;
}
function header() {
  const st = S.status; const n = S.platforms.length; const inn = n ? S.platforms.filter((p) => !loggedOut(p.id)).length : 0;
  const ext = st?.extension?.online;
  const running = st ? Object.values(st.queues || {}).reduce((a, q) => a + (q.running ? 1 : 0) + (q.queued || 0), 0) : 0;
  return `<div class="ph"><div><div class="eyebrow">SEARCH</div><h1>搜索</h1></div><div class="stats"><span class="live"><span class="dot ${ext ? "ok" : st ? "bad" : ""}"></span>${ext ? "扩展已连接" : st ? "扩展未连接" : "连接中…"}</span><span><b class="num">${inn}</b>/${n} 平台已登录</span><span>队列 <b>${running ? running + " 个进行中" : "空闲"}</b></span></div></div>`;
}
export function render() {
  if (S.page !== "search") return;
  const ae = document.activeElement; const focusId = ae?.id; const sel = focusId && ae.selectionStart != null ? [ae.selectionStart, ae.selectionEnd] : null;
  $("main").innerHTML = `<div class="wrap">${header()}${cmdBar()}<div id="results">${results()}</div><div class="hints"><span><kbd>/</kbd> 关键词</span><span><kbd>j</kbd> <kbd>k</kbd> 上下</span><span><kbd>o</kbd> 打开详情</span><span><kbd>Esc</kbd> 关闭</span><span><kbd>t</kbd> 表格 / 卡片</span></div></div>`;
  if (focusId && $(focusId)) { $(focusId).focus(); if (sel) try { $(focusId).setSelectionRange(...sel); } catch {} }
}
const renderResults = () => { if (S.page === "search" && $("results")) $("results").innerHTML = results(); };

// ---- form events ----------------------------------------------------------------------------------
document.addEventListener("input", (e) => {
  const id = e.target.id; if (!id?.startsWith("f-")) return;
  const k = { "f-keyword": "keyword", "f-id": "id", "f-cid": "cid", "f-xsec": "xsec", "f-limit": "limit" }[id]; if (k) { F[k] = k === "limit" ? Number(e.target.value) || 1 : e.target.value; saveForm(); }
});
document.addEventListener("change", (e) => { if (e.target.id === "f-action") { F.action = e.target.value; fixAction(); saveForm(); render(); } });
document.addEventListener("keydown", (e) => { if (e.key === "Enter" && e.target.id?.startsWith("f-") && e.target.tagName === "INPUT") { e.preventDefault(); run(); } });
document.addEventListener("click", (e) => { if (e.target.id === "f-limit") e.stopPropagation(); }, true);
on("chip", (id) => {
  const { event } = actCtx();
  if (event.metaKey || event.ctrlKey) { F.sel = F.sel.includes(id) ? (F.sel.length > 1 ? F.sel.filter((x) => x !== id) : F.sel) : [...F.sel, id]; }
  else F.sel = [id];
  const u = store.get("pusage", {}); u[id] = (u[id] || 0) + 1; store.set("pusage", u);
  fixAction(); saveForm();
  // switching back to a platform shows its last result again instead of stale rows from another one
  const k = keyOf(); const hit = CACHE.get(k) || (!multi() && [...CACHE.entries()].reverse().find(([, v]) => v.single?.pid === id)?.[1]);
  R = hit || (R?.single?.pid === id && !multi() ? R : null);
  render();
});
on("chipsAll", (v) => { showAll = v; store.set("chipsAll", v); render(); });
on("mtype", (t) => { F.mtype = t; saveForm(); render(); });
on("order", (v) => { F.order = v; saveForm(); render(); });
on("mode", (m) => { if (actCtx().event?.target.id === "f-limit") return; F.mode = m; saveForm(); render(); if (m === "collect") $("f-limit")?.select(); });
on("view", (pid, kind, v) => { setView(pid, kind, v); renderResults(); });
on("export", (fmt) => { const items = R?.single?.items || R?.multi?.results.flatMap((e) => e.items) || []; (fmt === "csv" ? exportCSV : exportJSON)(items, "sociallens"); });
on("run", () => run());
on("next", () => runQuery(true));

// ---- running ------------------------------------------------------------------------------------
const looksLikeLink = (s) => /^https?:\/\//i.test(s) || /^[\w-]+(\.[\w-]+)+\/\S+/.test(s);
async function run() {
  const raw = (F.action.startsWith("search_") || multi() ? F.keyword : F.id).trim();
  if (looksLikeLink(raw)) {
    try {
      const r = (await api("/resolve?q=" + encodeURIComponent(raw))).data;
      if (r.kind === "post" && r.platform) return quick(r.platform, "get_post", { id: r.id, xsec: r.xsec_token });
      if (r.kind === "user" && r.platform) return quick(r.platform, "get_user", { id: r.id, xsec: r.xsec_token });
      if (r.kind === "short_link") return toast(`${pname(r.platform)} 的短链接暂时不能直接解析，请打开后复制完整地址`, true);
      if (r.kind === "keyword" && r.id) { F.keyword = r.id; if (r.platform) F.sel = [r.platform]; }
    } catch (e) { return toast(e.message, true); }
  }
  if (multi()) return runMulti();
  if (F.action.startsWith("search_") && !F.keyword.trim()) return toast("至少填一个关键词", true);
  if (["get_post", "get_comments", "get_replies", "get_user", "get_user_posts"].includes(F.action) && !F.id.trim()) return toast("请填写 id", true);
  if (F.mode === "collect" && LIST_ACTIONS.has(F.action)) return runCollect();
  return runQuery(false);
}
function push() { const k = keyOf(); if (location.hash !== k) history.pushState(null, "", k); act("searchHash", k); return k; }
function params() {
  const a = F.action, p = {};
  if (a.startsWith("search_")) p.keyword = F.keyword.trim();
  if (["get_comments", "get_replies"].includes(a)) p.post_id = F.id.trim();
  if (["get_post", "get_user", "get_user_posts"].includes(a)) p.id = F.id.trim();
  if (a === "get_replies") p.comment_id = F.cid.trim();
  if (needsXsec() && F.xsec.trim()) p.xsec_token = F.xsec.trim();
  if (orders() && F.order) p[a === "get_comments" ? "mode" : "order"] = F.order;
  return p;
}
function pathFor(more, cursor) {
  const pid = one(), a = F.action, prm = params(), q = new URLSearchParams();
  if (more && cursor) q.set("cursor", cursor);
  for (const k of ["xsec_token", "order", "mode"]) if (prm[k]) q.set(k, prm[k]);
  const id = encodeURIComponent(prm.id || prm.post_id || ""); let path;
  if (a === "search_posts" || a === "search_users") { q.set("keyword", prm.keyword); q.set("type", a === "search_users" ? "user" : "post"); path = `/${pid}/search`; }
  else if (a === "get_post") path = `/${pid}/posts/${id}`;
  else if (a === "get_comments") path = `/${pid}/posts/${id}/comments`;
  else if (a === "get_replies") path = `/${pid}/posts/${id}/comments/${encodeURIComponent(prm.comment_id)}/replies`;
  else if (a === "get_user") path = `/${pid}/users/${id}`;
  else if (a === "get_user_posts") path = `/${pid}/users/${id}/posts`;
  else if (a === "get_feed") path = `/${pid}/feed`;
  else path = `/${pid}/trending`;
  const s = q.toString(); return path + (s ? "?" + s : "");
}
const ctxKey = (a, p) => a.startsWith("search_") ? p.keyword : a === "get_replies" ? `${p.post_id} / ${p.comment_id}` : (p.id || p.post_id || "");
async function runQuery(more) {
  const s0 = more ? R?.single : null; if (more && !s0?.cursor) return;
  const k = more ? location.hash : push();
  loading = { t0: Date.now(), text: "请求中，页面级动作要开标签页，可能要十几秒…" }; if (!more) R = null; render();
  try {
    const r = await api(pathFor(more, s0?.cursor));
    const single = !Array.isArray(r.data?.items) && !Array.isArray(r.data) && r.data?.id;
    const items = Array.isArray(r.data?.items) ? r.data.items : Array.isArray(r.data) ? r.data : [r.data];
    const prm = params();
    const s = more ? { ...s0, items: s0.items.concat(items), cursor: r.cursor || null } : { pid: one(), action: F.action, kind: r.data?.kind === "topics" ? "topics" : itemKind(items[0]), items, cursor: r.cursor || null, total: r.data?.total, key: ctxKey(F.action, prm), at: Date.now(), postId: prm.post_id, xsec: prm.xsec_token };
    s.secs = ((Date.now() - loading.t0) / 1000).toFixed(1); s.task = r.task_id;
    R = { single: s }; cachePut(k, R); loading = null; render();
    if (single && !more) openItem(items[0]);
  } catch (e) { loading = null; R = more ? R : { single: { pid: one(), action: F.action, kind: "posts", items: [], key: ctxKey(F.action, params()), error: e.message } }; render(); toast(e.message, true); }
}
async function runCollect() {
  const k = push(); const a = F.action, pid = one(), prm = params(); const limit = Number(F.limit) || 100;
  loading = { t0: Date.now(), text: "连续拉取中…", collect: { count: 0, limit } }; R = { single: { pid, action: a, kind: "posts", items: [], key: ctxKey(a, prm), source: "连续拉取", collect: true } }; render();
  try {
    const r = await api(`/${pid}/collect`, { method: "POST", body: JSON.stringify({ action: a, params: prm, limit }) });
    const id = r.data.id; let t; act("badges");
    for (;;) {
      t = (await api(`/tasks/${id}`)).data; const res = t.result || {};
      loading.collect = { count: res.count || 0, limit }; R.single.source = `连续拉取 ${id} · ${res.count || 0} 条 ${res.pages || 0} 页`;
      if (S.page === "search") { const rh = document.querySelector("#results .res"); if (rh) renderResults(); }
      if (["done", "failed", "cancelled"].includes(t.status)) break;
      await new Promise((ok) => setTimeout(ok, 1500));
    }
    const res = t.result || {}; const items = res.items || [];
    const why = { limit: "达到条数上限", no_more: "已到列表末尾", max_pages: "达到页数上限", error: "中途出错，保留已拿到的", cancelled: "已取消" }[res.stopped_by] || res.stopped_by || "";
    R = { single: { pid, action: a, kind: res.kind === "topics" ? "topics" : itemKind(items[0]), items, cursor: null, total: res.total, key: ctxKey(a, prm), source: `连续拉取 · ${res.pages || 0} 页 · ${why}`, at: Date.now(), secs: ((Date.now() - loading.t0) / 1000).toFixed(0), collect: true, error: res.error ? `${res.error.code}: ${res.error.message}` : null } };
    cachePut(k, R);
  } catch (e) { toast(e.message, true); if (R?.single) R.single.error = e.message; }
  loading = null; render(); act("badges");
}
async function runMulti() {
  if (!F.keyword.trim()) return toast("至少填一个关键词", true);
  const a = F.mtype === "user" ? "search_users" : "search_posts";
  const ids = F.sel.filter((id) => capsOf(id).has(a)); if (!ids.length) return toast("选中的平台都不支持这种搜索", true);
  const k = push(); loading = { t0: Date.now(), text: "同时搜索中…", multi: ids }; R = null; render();
  try {
    const r = await api(`/search?keyword=${encodeURIComponent(F.keyword.trim())}&platforms=${ids.join(",")}&type=${F.mtype}`);
    R = { multi: { keyword: F.keyword.trim(), type: F.mtype, results: r.data.results, secs: ((Date.now() - loading.t0) / 1000).toFixed(1) } }; cachePut(k, R);
  } catch (e) { toast(e.message, true); }
  loading = null; render();
}
on("handoff", (pid) => {
  const m = R?.multi; const e = m?.results.find((x) => x.platform === pid); if (!e) return;
  F.sel = [pid]; F.action = m.type === "user" ? "search_users" : "search_posts"; F.keyword = m.keyword; F.mode = "page"; fixAction(); saveForm();
  R = { single: { pid, action: F.action, kind: m.type === "user" ? "users" : "posts", items: e.items, cursor: e.cursor, total: e.total, key: m.keyword, source: "多平台搜索", at: Date.now() } };
  cachePut(push(), R); render();
});

/** Fill the form and run: used by links inside results, the drawer, @mentions and #topics. */
export function quick(platform, action, o = {}) {
  closeDrawer();
  F.sel = [platform || one()]; F.action = action; F.mode = "page";
  if (o.keyword != null) F.keyword = o.keyword; if (o.id != null) F.id = o.id; if (o.cid != null) F.cid = o.cid; F.xsec = o.xsec || "";
  fixAction(); saveForm();
  if (S.page !== "search") { S.page = "search"; act("setPage", "search"); }
  run();
}
on("quick", (platform, action, o) => quick(platform, action, o));
/** Show a stored result set (query history, a finished collect task) as if it had just been queried. */
export function showResult({ pid, action, params: p = {}, items, kind, source, at }) {
  F.sel = [pid]; F.action = action || "search_posts"; F.keyword = p.keyword || ""; F.id = p.post_id || p.id || p.user_id || ""; F.cid = p.comment_id || ""; F.xsec = p.xsec_token || ""; F.mode = "page"; fixAction(); saveForm();
  R = { single: { pid, action: F.action, kind: kind === "topics" ? "topics" : kind || itemKind(items[0]), items, cursor: null, key: ctxKey(F.action, { keyword: F.keyword, id: F.id, post_id: F.id, comment_id: F.cid }), source, at } };
  S.page = "search"; act("setPage", "search"); cachePut(push(), R); render();
}
on("showResult", (r) => showResult(r));
export const refreshHeader = () => { if (S.page === "search" && !loading && document.querySelector("#main .ph")) document.querySelector("#main .ph").outerHTML = header(); };
