// 状态 page: alerts first (paused queues, broken probes, Chrome stuck, extension offline), then one tile per
// platform (login, page-load budget, probe), then the risk-control log.
import { $, esc, J, fmtT, api, toast, on, act, S, pname, logo, pcolor, actionName } from "./core.js";

export async function loadStatus() {
  try { S.status = (await api("/status")).data; } catch (e) { S.status = null; throw e; }
  try { S.health = (await api("/health/platforms")).data; } catch {}
  return S.status;
}
/** Alerts shared by the status page and the rail's status dot. */
export function alerts() {
  const st = S.status, out = []; if (!st) return [{ level: "bad", html: "后端不可达" }];
  const hp = S.health?.platforms || {};
  if (!st.extension?.online) out.push({ level: "bad", html: `扩展没有连上后端：在 chrome://extensions 加载 extension/dist，或点扩展图标里的"重连"。` });
  const stuck = st.diagnosis?.chrome_stuck;
  if (stuck) out.push({ level: "bad", html: `<b>Chrome 可能卡住了</b>：<span>自 ${esc(fmtT(stuck.since))} 起 ${stuck.tasks} 个页面任务的标签页始终没有加载（${stuck.platforms.map(pname).map(esc).join("、")}），扩展后台却在线。</span> <span>完全退出 Chrome（包括托盘）再重开。</span>` });
  for (const p of S.platforms) {
    const q = st.queues?.[p.id] || {};
    if (q.paused_for_s > 0) out.push({ level: "warn", html: `${logo(p.id)} <span>${esc(p.name)} 队列已暂停，还剩 ${Math.ceil(q.paused_for_s / 60)} 分钟。多半是风控或验证码，先在浏览器里处理，再点恢复。</span>`, btn: `<button class="btn sm" data-act="resume" data-arg='${J(p.id)}'>恢复</button>` });
    const h = hp[p.id];
    if (h?.state === "broken") out.push({ level: "bad", html: `${logo(p.id)} ${esc(p.name)} <span>探测失败</span>：<span class="mono">${esc(h.action || "")} · ${esc(h.code || "")}${h.message ? ": " + esc(h.message.slice(0, 120)) : ""}</span>${h.broken_since ? `（<span>从 ${esc(fmtT(h.broken_since))} 起</span>）` : ""}` });
  }
  return out;
}
on("resume", async (pid) => { try { await api(`/${pid}/resume`, { method: "POST" }); toast("已恢复队列"); await loadStatus(); showStatus(); act("badges"); } catch (e) { toast(e.message, true); } });
on("healthRun", async () => { try { await api("/health/check", { method: "POST", body: JSON.stringify({ wait: false }) }); } catch (e) { toast(e.message, true); } setTimeout(refresh, 800); });
on("platformSearch", (pid) => act("quick", pid, "search_posts", {}));

let timer;
async function refresh() { if (S.page !== "status") return; try { await loadStatus(); } catch {} showStatus(); }
export function showStatus() {
  clearTimeout(timer); if (S.page !== "status") return;
  const st = S.status, hp = S.health?.platforms || {}, h = S.health;
  const al = alerts();
  const rows = h ? Object.values(h.platforms || {}).filter(Boolean) : [];
  const n = (s) => rows.filter((r) => r.state === s).length;
  const last = rows.length ? rows.map((r) => r.checked_at).sort().pop() : null;
  const tiles = S.platforms.map((p) => {
    const s = st?.platforms?.[p.id] || {}, q = st?.queues?.[p.id] || {}, budget = p.rate_limit?.page_loads || 0, used = q.page_loads_in_window || 0, ratio = budget ? used / budget : 0, hh = hp[p.id];
    const pill = s.logged_in === false ? `<span class="pill bad">未登录</span>` : hh?.state === "broken" ? `<span class="pill bad">异常</span>` : q.paused_for_s > 0 ? `<span class="pill warn">已暂停 ${Math.ceil(q.paused_for_s / 60)}m</span>` : q.budget_wait_s > 0 ? `<span class="pill warn">配额等待</span>` : q.running ? `<span class="pill ok">执行中</span>` : p.id === "weixin_channels" ? `<span class="pill">仅后台</span>` : `<span class="pill">空闲</span>`;
    const foot = s.logged_in === false ? `<a href="${esc(p.login_url || p.home_url)}" target="_blank" rel="noreferrer" title="${esc(p.login_hint || "")}">去登录 ↗</a>` : hh?.checked_at ? `<span class="${hh.state === "broken" ? "err" : ""}" title="${esc(hh.message || hh.action || "")}">探测${hh.state === "ok" ? "正常" : hh.state === "broken" ? "异常" : "受阻"} ${esc(fmtT(hh.checked_at).slice(6))}</span>` : `<span>${(s.tabs || []).length ? (s.tabs || []).length + " 个标签页" : ""}</span>`;
    return `<div class="tile" style="--pc:${pcolor(p.id)}"><div class="tn">${logo(p.id, "md")}<b>${esc(p.name)}</b>${pill}</div><div class="progress ${ratio >= 0.9 ? "bad" : ratio >= 0.6 ? "warn" : ""}"><i style="width:${Math.min(100, ratio * 100)}%"></i></div><div class="tm faint"><span class="num">页面 ${used}/${budget || "∞"} · ${Math.round((p.rate_limit?.window_s || 600) / 60)} 分钟</span>${foot}</div><button class="tgo" data-act="platformSearch" data-arg='${J(p.id)}' title="去搜索">→</button></div>`;
  }).join("");
  $("main").innerHTML = `<div class="wrap"><div class="ph"><div><div class="eyebrow">STATUS</div><h1>状态</h1></div><div class="stats"><span class="live"><span class="dot ${st?.extension?.online ? "ok" : "bad"}"></span>${st ? `后端 v${esc(st.backend_version)} · ${st.extension?.online ? "扩展已连接" : "扩展未连接"}` : "后端不可达"}</span></div></div>
    ${al.length ? `<div class="alerts">${al.map((a) => `<div class="alert ${a.level}"><span class="dot ${a.level}"></span><span class="at">${a.html}</span>${a.btn || ""}</div>`).join("")}</div>` : `<div class="alert ok"><span class="dot ok"></span>一切正常：扩展已连接，没有暂停的队列，没有异常的探测。</div>`}
    <div class="healthbar"><span title="每个平台各跑一次最便宜的读取（热榜或首页流），每个平台算一次页面加载。">平台探测</span><span class="faint">·</span><span>${last ? `上次 ${esc(fmtT(last))}` : "还没检查过"}</span>${rows.length ? `<span class="faint">·</span><span>${n("ok")} 正常</span><span class="faint">·</span><span class="${n("broken") ? "err" : ""}">${n("broken")} 异常</span><span class="faint">·</span><span>${n("blocked")} 受阻</span>` : ""}${h?.interval_min ? `<span class="faint">·</span><span>每 ${Math.round(h.interval_min / 60 * 10) / 10} 小时</span>` : ""}<span class="sp"></span><button class="btn sm" data-act="healthRun" ${h?.running ? "disabled" : ""}>${h?.running ? `<span class="spin"></span>检查中…` : "现在检查"}</button></div>
    <div class="tiles">${tiles}</div>
    <section class="panel"><div class="pth">风控事件 <span id="risk-sub" title="每次遇到验证码或限流时记录之前 10 / 60 分钟的页面加载、任务和调用来源，只记录不干预，用来摸各站的真实阈值。">只记录，不干预</span></div><div id="risk" class="rows"><div class="empty">加载中…</div></div></section></div>`;
  loadRisk();
  timer = setTimeout(refresh, h?.running ? 3000 : 15000);
}
async function loadRisk() {
  try {
    const evs = (await api("/risk/events?limit=10")).data.events || [];
    const ctxName = { multi_search: "多平台搜索中", health: "健康检查中", collect: "连续拉取中" };
    if ($("risk-sub")) $("risk-sub").textContent = evs.length ? `最近 ${evs.length} 次` : "只记录，不干预";
    if ($("risk")) $("risk").innerHTML = evs.length ? evs.map((e) => `<div class="lrow"><span class="mono faint">${esc(fmtT(e.at))}</span>${logo(e.platform)}<span class="strong">${esc(pname(e.platform))}</span><span class="mono">${esc(e.code)}</span><span class="mute">${esc(actionName(e.action))}</span><span class="faint ell"><span>页面 ${e.page_loads_10m}/10min,${e.page_loads_60m}/60min · 任务 ${e.tasks_10m}/10min,${e.tasks_60m}/60min</span>${e.min_gap_s_10m != null ? ` · <span>最小间隔 ${e.min_gap_s_10m} 秒</span>` : ""}${(e.contexts_10m || []).length ? ` · ${e.contexts_10m.map((c) => `<span>${esc(ctxName[c] || c)}</span>`).join(" ")}` : ""}${e.since_last_hit_s != null ? ` · <span>上次命中 ${Math.round(e.since_last_hit_s / 60)} 分钟前</span>` : ""}</span><span class="sp"></span><span class="pill bad" title="${esc(e.message || "")}">${esc(e.code === "captcha_required" ? "验证码" : "限流")}</span></div>`).join("") : `<div class="empty">还没有风控事件</div>`;
  } catch {}
}
