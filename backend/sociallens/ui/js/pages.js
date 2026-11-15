// 数据 (query history + local cache) and 任务 (collects, downloads, page tasks) pages.
import { $, esc, J, fmtN, fmtT, fmtB, api, toast, on, act, S, store, plat, pname, logo, actionName, statusPill, taskSummary, isDebugTask, isActive, go, hashFor, exportJSON, exportCSV, IC } from "./core.js";
import { renderList, viewOf, viewSeg, setView } from "./results.js";
import { Z } from "./i18n.js";

const platOptions = (v, all = "全部平台") => `<option value="">${all}</option>` + S.platforms.map((p) => `<option value="${p.id}" ${p.id === v ? "selected" : ""}>${esc(p.name)}</option>`).join("");
const head = (eyebrow, title, stats = "") => `<div class="ph"><div><div class="eyebrow">${eyebrow}</div><h1>${title}</h1></div><div class="stats">${stats}</div></div>`;

// ---- 数据 ---------------------------------------------------------------------------------------------
const DK = { k: "queries", p: "", q: "", n: 200, s: "" }; let dItems = [];
const SOURCE_NAME = { api: "接口调用", multi_search: "多平台搜索", collect: "连续拉取" };
export function showData(q) {
  if (q) { DK.k = q.get("k") || DK.k; DK.p = q.get("p") ?? DK.p; DK.q = q.get("q") ?? DK.q; DK.n = Number(q.get("n")) || DK.n; DK.s = q.get("s") ?? ""; }
  $("main").innerHTML = `<div class="wrap">${head("DATA", "数据", `<span>查过的查询、帖子、用户、评论都存在本地 SQLite</span>`)}
    <div class="cmd"><div class="frow"><div class="seg">${[["queries", "查询记录"], ["posts", "帖子"], ["users", "用户"], ["comments", "评论"], ["storage", Z("存储", "Storage")]].map(([k, n]) => `<button class="${DK.k === k ? "on" : ""}" data-act="dKind" data-arg='${J(k)}'>${n}</button>`).join("")}</div>
    ${DK.k === "storage" ? `<span class="sp"></span>` : `<select id="d-platform" class="field w160">${platOptions(DK.p)}</select>`}
    ${DK.k === "storage" ? "" : DK.k === "queries" ? `<div class="kw">${IC.search}<input id="d-q" class="field" value="${esc(DK.q)}" placeholder="关键词 / id" autocomplete="off"><kbd>/</kbd></div>` : `<select id="d-src" class="field" style="min-width:220px;max-width:420px" title="只看某次查询抓到的"><option value="">来源：全部缓存</option></select><label class="inl faint" ${DK.s ? "hidden" : ""}>最多<input id="d-n" class="field w80" type="number" min="1" max="1000" value="${DK.n}">条</label><span class="sp"></span>`}
    <button class="btn" data-act="dLoad">刷新</button></div></div>
    <div id="d-out"><section class="res"><div class="rbusy"><span class="spin"></span>加载中…</div></section></div></div>`;
  loadData();
}
const dHash = () => history.replaceState(null, "", hashFor("data", { k: DK.k, p: DK.p, q: DK.k === "queries" ? DK.q : "", n: DK.k === "queries" || DK.s ? "" : DK.n, s: DK.k === "queries" ? "" : DK.s }));
on("dKind", (k) => { DK.k = k; DK.s = ""; dHash(); showData(); });
on("dLoad", () => { dHash(); loadData(); });
document.addEventListener("change", (e) => { if (e.target.id === "d-platform") { DK.p = e.target.value; DK.s = ""; dHash(); showData(); }
  if (e.target.id === "d-src") { DK.s = e.target.value; dHash(); showData(); } if (e.target.id === "d-n") { DK.n = Number(e.target.value) || 200; dHash(); loadData(); } });
document.addEventListener("input", (e) => { if (e.target.id === "d-q") DK.q = e.target.value; });
document.addEventListener("keydown", (e) => { if (e.key === "Enter" && e.target.id === "d-q") { dHash(); loadData(); } });
async function loadData() {
  const out = $("d-out"); if (!out) return;
  try {
    if (DK.k === "storage") return await loadStorage(out);
    if (DK.k === "queries") {
      const q = new URLSearchParams({ limit: "200" }); if (DK.p) q.set("platform", DK.p); if (DK.q.trim()) q.set("q", DK.q.trim());
      const rows = (await api("/queries?" + q)).data;
      out.innerHTML = `<section class="res"><div class="rh"><b>查询记录</b><span class="faint">${rows.length} 条 · 每次列表查询都记下返回了哪些条目；指标每次变化存一份快照</span></div>${rows.length ? `<div class="rows">${rows.map((r) => `<div class="lrow" data-act="dOpen" data-arg="${r.id}" data-nav><span class="mono faint">${esc(fmtT(r.at))}</span>${logo(r.platform)}<span class="strong">${esc(pname(r.platform))}</span><span class="mute">${esc(actionName(r.action))}</span>${r.key ? `<span class="mono ell">${esc(r.key)}</span>` : ""}<span class="sp"></span><span class="pill">${esc(SOURCE_NAME[r.source] || r.source)}</span><span class="num faint">${r.count} 条</span><span class="go">打开结果 →</span></div>`).join("")}</div>` : `<div class="empty">还没有查询记录</div>`}</section>`;
    } else {
      // "来源" lists the queries that returned this kind, so one feed / search can be looked at on its own
      const ql = new URLSearchParams({ limit: "100" }); if (DK.p) ql.set("platform", DK.p);
      const srcs = (await api("/queries?" + ql).catch(() => ({ data: [] }))).data.filter((r) => r.kind === DK.k);
      if ($("d-src")) $("d-src").innerHTML = `<option value="">来源：全部缓存</option>` + srcs.map((r) => `<option value="${r.id}" ${String(r.id) === String(DK.s) ? "selected" : ""}>${esc(fmtT(r.at))} · ${esc(DK.p ? "" : pname(r.platform) + " · ")}${esc(actionName(r.action))}${r.key ? " · " + esc(r.key) : ""} · ${r.count} 条</option>`).join("");
      let src = null;
      if (DK.s) { src = (await api(`/queries/${DK.s}`)).data; dItems = src.items || []; }
      else { const q = new URLSearchParams({ kind: DK.k, limit: String(DK.n) }); if (DK.p) q.set("platform", DK.p); dItems = (await api("/items?" + q)).data; }
      const pid = DK.p || src?.platform || null;
      const what = src ? `${dItems.length} 条 · 来自 ${fmtT(src.at)} 的${actionName(src.action)}${src.key ? "「" + src.key + "」" : ""}，按当时的顺序` : `${dItems.length} 条 · 按最近更新排序`;
      out.innerHTML = `<section class="res"><div class="rh"><b>${{ posts: "帖子", users: "用户", comments: "评论" }[DK.k]}</b><span class="faint">${esc(what)}</span><span class="sp"></span>${viewSeg(pid, DK.k, "dView")}<button class="btn ghost sm" data-act="dExport" data-arg='"json"'>导出 JSON</button><button class="btn ghost sm" data-act="dExport" data-arg='"csv"'>导出 CSV</button></div>${renderList(dItems, DK.k, pid, viewOf(pid, DK.k), { showPlatform: !pid })}</section>`;
    }
  } catch (e) { out.innerHTML = `<section class="res"><div class="banner bad">${esc(e.message)}</div></section>`; }
}
on("dView", (pid, kind, v) => { setView(pid, kind, v); loadData(); });
on("dExport", (f) => (f === "csv" ? exportCSV : exportJSON)(dItems, "cache"));
on("dOpen", async (id) => {
  try { const q = (await api(`/queries/${id}`)).data; act("showResult", { pid: q.platform, action: q.action, params: q.params || {}, items: q.items, kind: q.kind, source: `历史 #${q.id}`, at: Date.parse(q.at) }); }
  catch (e) { toast(e.message, true); }
});

// ---- 数据 › 存储 ----------------------------------------------------------------------------------------
const STORE_ROWS = [
  ["tasks", Z("已结束的任务", "Finished tasks"), Z("每条都带完整结果，结果里的条目已另存进缓存", "each keeps its full result; its items are in the cache too")],
  ["health", Z("平台探测记录", "Platform probes"), ""],
  ["risk_events", Z("风控事件", "Risk-control hits"), ""],
  ["queries", Z("查询记录", "Query history"), ""],
  ["snapshots", Z("指标快照", "Metric snapshots"), Z("指标每次变化存一份", "one per metric change")],
  ["items", Z("缓存的帖子、用户、评论", "Cached posts, users, comments"), ""],
  ["raw", Z("录制样本", "Recorded captures"), Z("录制模式存下的原始响应", "raw responses saved by record mode")],
  ["uploads", Z("下载临时分片", "Download chunks"), Z("中断的下载留下的", "left by interrupted downloads")],
];
const STORE_NAME = Object.fromEntries(STORE_ROWS.map(([k, n]) => [k, n]));
const keepText = (d) => (d > 0 ? Z(`保留 ${d} 天`, `keep ${d} days`) : Z("一直保留", "kept"));
const pruneSummary = (r) => {
  const rows = Object.entries(r.removed).filter(([k]) => k !== "raw" && k !== "uploads").reduce((a, [, n]) => a + n, 0);
  const files = (r.removed.raw || 0) + (r.removed.uploads || 0);
  return Z(`删除 ${fmtN(rows)} 条记录、${fmtN(files)} 个文件；数据库 ${fmtB(r.db_bytes_before)} → ${fmtB(r.db_bytes_after)}`, `removed ${fmtN(rows)} rows and ${fmtN(files)} files; database ${fmtB(r.db_bytes_before)} → ${fmtB(r.db_bytes_after)}`);
};
async function loadStorage(out) {
  const u = (await api("/storage")).data;
  const cell = (k) => {
    const t = u.tables[k], d = u.dirs[k];
    return t ? { n: t.rows, count: Z(`${fmtN(t.rows)} 条`, `${fmtN(t.rows)} rows`), size: "≈ " + fmtB(t.bytes), oldest: t.oldest ? fmtT(t.oldest) : "–" }
      : { n: d.files, count: Z(`${fmtN(d.files)} 个文件`, `${fmtN(d.files)} files`), size: fmtB(d.bytes), oldest: "–" };
  };
  const row = ([k, name, note]) => { const c = cell(k); return `<tr><td><div class="strong">${esc(name)}</div>${note ? `<div class="faint">${esc(note)}</div>` : ""}</td><td class="r num">${c.count}</td><td class="r num">${c.size}</td><td class="r mono faint">${esc(c.oldest)}</td><td><span class="pill ${u.policy[k] > 0 ? "accent" : ""}">${keepText(u.policy[k])}</span></td><td class="r"><button class="btn ghost sm" data-act="sClear" data-arg='${J(k)}' ${c.n ? "" : "disabled"}>${Z("清空", "Clear")}</button></td></tr>`; };
  const fixed = [[Z("下载的媒体", "Downloaded media"), u.dirs.downloads, Z("不会自动清理，需要的话自己删文件", "never pruned; delete files yourself if needed")], [Z("日志", "Logs"), u.dirs.logs, Z("按大小自动轮转", "rotated by size")]]
    .map(([name, d, note]) => `<tr><td><div class="strong">${esc(name)}</div><div class="faint">${esc(note)}</div></td><td class="r num">${Z(`${fmtN(d.files)} 个文件`, `${fmtN(d.files)} files`)}</td><td class="r num">${fmtB(d.bytes)}</td><td class="r faint">–</td><td></td><td></td></tr>`).join("");
  const last = u.last_prune ? Z(`上次清理：${fmtT(u.last_prune.at)}，${pruneSummary(u.last_prune)}`, `Last prune: ${fmtT(u.last_prune.at)}, ${pruneSummary(u.last_prune)}`) : Z("本次启动后还没清理过", "Not pruned since the backend started");
  const sched = u.prune_interval_h > 0 ? Z(`每 ${u.prune_interval_h} 小时按保留策略自动清理一次`, `pruned by the policy every ${u.prune_interval_h} h`) : Z("定时清理已关闭", "scheduled pruning is off");
  out.innerHTML = `<section class="res"><div class="rh"><b>${Z("存储", "Storage")}</b><span class="faint mono">${esc(u.data_dir)}</span><span class="faint">${Z("数据库", "database")} ${fmtB(u.db.bytes)}</span><span class="sp"></span><button class="btn sm" data-act="sPrune">${Z("按保留策略清理", "Prune by policy")}</button></div>
    <div class="tablewrap"><table class="tbl"><thead><tr><th></th><th class="r">${Z("数量", "Count")}</th><th class="r">${Z("大小", "Size")}</th><th class="r">${Z("最早", "Oldest")}</th><th>${Z("保留策略", "Retention")}</th><th></th></tr></thead><tbody>${STORE_ROWS.map(row).join("")}${fixed}</tbody></table></div>
    <div class="note faint" style="padding:10px 16px">${esc(sched)} · ${esc(last)}。${Z("保留天数用环境变量 SOCIALLENS_RETAIN_*_DAYS 设置，0 表示一直保留。", "Set retention with SOCIALLENS_RETAIN_*_DAYS environment variables; 0 keeps forever.")}</div></section>`;
}
on("sPrune", async () => {
  try { const r = (await api("/storage/prune", { method: "POST", body: "{}" })).data; toast(pruneSummary(r)); loadData(); } catch (e) { toast(e.message, true); }
});
on("sClear", async (k) => {
  const what = k === "tasks" ? Z("全部已结束的任务（进行中的不受影响）", "all finished tasks (running ones are kept)") : Z(`全部「${STORE_NAME[k]}」`, `all ${STORE_NAME[k]}`);
  if (!confirm(Z(`删除${what}？删除后无法恢复。`, `Delete ${what}? This cannot be undone.`))) return;
  try { const r = (await api("/storage/prune", { method: "POST", body: JSON.stringify({ older_than_days: { [k]: 0 } }) })).data; toast(pruneSummary(r)); loadData(); } catch (e) { toast(e.message, true); }
});

// ---- 任务 ---------------------------------------------------------------------------------------------
const TK = { tab: "active", p: "", type: "", debug: false }; let tTimer; let tLimit = 200;
export function showTasks(q) {
  if (q) { TK.tab = q.get("tab") || TK.tab; TK.p = q.get("p") ?? TK.p; TK.type = q.get("type") ?? TK.type; }
  $("main").innerHTML = `<div class="wrap">${head("TASKS", "任务", `<span id="t-dir" class="mono faint"></span>`)}
    <div class="cmd"><div class="frow"><div class="seg" id="t-tabs"></div>
    <select id="t-platform" class="field w160">${platOptions(TK.p)}</select>
    <select id="t-type" class="field w160"><option value="">全部类型</option>${[["collect", "连续拉取"], ["download", "下载"], ["query", "查询"]].map(([v, n]) => `<option value="${v}" ${TK.type === v ? "selected" : ""}>${n}</option>`).join("")}</select>
    <label class="chk"><input type="checkbox" id="t-debug" ${TK.debug ? "checked" : ""}> 显示调试动作</label><span class="sp"></span>
    <button class="btn primary" data-act="newDl">${IC.dl}新建下载</button></div></div>
    <div id="t-out"><section class="res"><div class="rbusy"><span class="spin"></span>加载中…</div></section></div></div>`;
  loadTasks();
}
const tHash = () => history.replaceState(null, "", hashFor("tasks", { tab: TK.tab, p: TK.p, type: TK.type }));
on("tTab", (t) => { TK.tab = t; tHash(); loadTasks(); });
on("tMore", () => { tLimit += 200; loadTasks(); });
document.addEventListener("change", (e) => {
  if (e.target.id === "t-platform") { TK.p = e.target.value; tHash(); loadTasks(); }
  if (e.target.id === "t-type") { TK.type = e.target.value; tHash(); loadTasks(); }
  if (e.target.id === "t-debug") { TK.debug = e.target.checked; loadTasks(); }
});
const typeOf = (t) => t.action === "collect" ? "collect" : t.action === "download" ? "download" : "query";
const TYPE_ICON = { collect: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M20 11a8 8 0 0 0-14.9-4M4 13a8 8 0 0 0 14.9 4"/><path d="M4 4v4h4M20 20v-4h-4"/></svg>', download: IC.dl, query: IC.search };
function progress(t) {
  const r = t.result || {};
  if (t.action === "collect") { const pct = r.limit ? Math.min(100, Math.round((r.count || 0) / r.limit * 100)) : t.status === "done" ? 100 : 0; return [pct, `${r.count || 0} / ${r.limit || "?"} 条 · ${r.pages || 0} 页${r.stopped_by ? " · " + ({ limit: "够数", no_more: "到底", max_pages: "页数上限", error: "出错", cancelled: "取消" }[r.stopped_by] || r.stopped_by) : ""}`]; }
  if (t.action === "download") { const files = r.files || []; const done = files.filter((f) => f.status === "done").length; const b = files.reduce((a, f) => a + (f.bytes_done || 0), 0), tot = files.reduce((a, f) => a + (f.bytes_total || 0), 0); return [tot ? Math.round(b / tot * 100) : t.status === "done" ? 100 : 0, files.length ? `${done}/${files.length} 个文件 · ${fmtB(b)}${tot ? " / " + fmtB(tot) : ""}` : (r.stage || "")]; }
  return [null, ""];
}
function taskRow(t) {
  const ty = typeOf(t); const [pct, ptext] = progress(t); const r = t.result || {};
  const file = t.action === "download" && r.files?.[0]?.path ? r.files[0].path.split(/[\\/]/).slice(-2).join("/") : "";
  const btns = [isActive(t) ? `<button class="btn ghost sm" data-act="cancel" data-arg='${J(t.id)}'>取消</button>` : "", t.action === "collect" && t.status === "done" ? `<button class="btn ghost sm" data-act="showCollect" data-arg='${J(t.id)}'>查看结果 →</button>` : ""].join("");
  return `<div class="trow ${t.status}"><span class="tico ${ty}" title="${esc(actionName(t.action))}">${TYPE_ICON[ty]}</span>${logo(t.platform)}<div class="tmain"><div class="tt"><span class="strong">${esc(pname(t.platform))} · ${esc(actionName(t.action === "collect" ? t.params?.action : t.action))}</span><span class="mute ell">${esc(taskSummary(t))}</span></div>${pct != null ? `<div class="progress ${t.status === "failed" ? "bad" : ""}"><i style="width:${pct}%"></i></div>` : ""}<div class="ts faint"><span class="mono">${esc(t.id)}</span><span>${esc(fmtT(t.created_at))}</span>${ptext ? `<span class="num">${esc(ptext)}</span>` : ""}${file ? `<span class="mono ell">${esc(file)}</span>` : ""}${t.error ? `<span class="err ell" title="${esc(t.error.message)}">${esc(t.error.code)}: ${esc(t.error.message)}</span>` : ""}</div></div>${statusPill(t)}<div class="tacts">${btns}</div></div>`;
}
async function loadTasks() {
  clearTimeout(tTimer); const out = $("t-out"); if (!out || S.page !== "tasks") return;
  try {
    const q = new URLSearchParams({ limit: String(tLimit) }); if (TK.p) q.set("platform", TK.p);
    const all = (await api("/tasks?" + q)).data.filter((t) => t.platform !== "_system" && (TK.debug || !isDebugTask(t)) && (!TK.type || typeOf(t) === TK.type));
    const groups = { active: all.filter(isActive), done: all.filter((t) => t.status === "done" || t.status === "cancelled"), failed: all.filter((t) => t.status === "failed") };
    $("t-tabs").innerHTML = [["active", "进行中"], ["done", "已完成"], ["failed", "失败"]].map(([k, n]) => `<button class="${TK.tab === k ? "on" : ""}" data-act="tTab" data-arg='${J(k)}'>${n}<span class="cnt">${groups[k].length}</span></button>`).join("");
    const list = groups[TK.tab] || [];
    const dir = all.find((t) => t.result?.dir)?.result.dir; if (dir && $("t-dir")) $("t-dir").textContent = "下载目录 " + dir.replace(/([\\/][^\\/]+){2}$/, "");
    out.innerHTML = `<section class="res">${list.length ? `<div class="rows">${list.map(taskRow).join("")}</div>` : `<div class="empty">${TK.tab === "active" ? "没有进行中的任务。在「搜索」里把条数切到「连续到 N 条」，或在结果、详情里点「下载」。" : "没有任务"}</div>`}${all.length >= tLimit ? `<div class="more"><button class="btn sm" data-act="tMore">加载更多</button></div>` : ""}</section>`;
    if (groups.active.length) tTimer = setTimeout(loadTasks, 2000);
  } catch (e) { out.innerHTML = `<section class="res"><div class="banner bad">${esc(e.message)}</div></section>`; }
}
on("cancel", async (id) => { try { await api(`/tasks/${id}/cancel`, { method: "POST" }); toast("已取消"); loadTasks(); act("badges"); } catch (e) { toast(e.message, true); } });
on("showCollect", async (id) => {
  try { const t = (await api(`/tasks/${id}`)).data; const res = t.result || {}; const p = t.params || {}; act("showResult", { pid: t.platform, action: p.action, params: p.params || {}, items: res.items || [], kind: res.kind, source: `连续拉取 ${id} · ${res.pages || 0} 页`, at: Date.parse(t.created_at) }); }
  catch (e) { toast(e.message, true); }
});

// ---- 新建下载 modal ------------------------------------------------------------------------------------
on("newDl", () => {
  $("modal").innerHTML = `<div class="mbox"><div class="mh"><b>新建下载</b><span class="sp"></span><button class="iconbtn" data-act="mClose">${IC.x}</button></div>
    <label>平台<select id="m-platform" class="field">${S.platforms.map((p) => `<option value="${p.id}">${esc(p.name)}</option>`).join("")}</select></label>
    <label>帖子 id 或链接<input id="m-id" class="field" placeholder="粘贴链接会自动识别平台"></label>
    <label>xsec_token <span class="faint">（小红书需要，链接里自带的会自动带上）</span><input id="m-xsec" class="field"></label>
    <div class="mf"><button class="btn" data-act="mClose">取消</button><button class="btn primary" data-act="mDl">${IC.dl}下载</button></div></div>`;
  $("modal").classList.add("open"); $("m-id").focus();
});
on("mClose", () => $("modal").classList.remove("open"));
on("mDl", async () => {
  let id = $("m-id").value.trim(), platform = $("m-platform").value, xsec = $("m-xsec").value.trim();
  if (/^https?:\/\//.test(id) || /\.[a-z]{2,}\//.test(id)) {
    try { const r = (await api("/resolve?q=" + encodeURIComponent(id))).data; if (r.kind !== "post") return toast("这个链接不是帖子", true); platform = r.platform; id = r.id; xsec = r.xsec_token || xsec; }
    catch (e) { return toast(e.message, true); }
  }
  await act("download", platform, id, xsec); $("modal").classList.remove("open"); if (S.page === "tasks") { TK.tab = "active"; loadTasks(); }
});
