// Entry: icon rail, hash routing between the five pages, keyboard shortcuts, theme / language, polling.
import { $, esc, J, api, toast, on, act, S, store, parseHash, IC } from "./core.js";
import { ZH, setLang, installI18n } from "./i18n.js";
import { show as showSearch, refreshHeader } from "./search.js";
import { showData, showTasks } from "./pages.js";
import { showStatus, loadStatus, alerts } from "./status.js";
import { showApi } from "./apidoc.js";
import { openRoute, leaveRoute, close as closeDrawer, isOpen as drawerOpen } from "./drawer.js";

const PAGES = { search: ["搜索", IC.search], data: ["数据", IC.data], tasks: ["任务", IC.tasks], status: ["状态", IC.status], api: ["接口", IC.api] };
let lastSearch = store.sget("lastSearch", "#/search");

// ---- theme ------------------------------------------------------------------------------------------
const THEMES = ["system", "light", "dark"];
let theme = store.get("theme", "system");
function applyTheme() { if (theme === "system") delete document.documentElement.dataset.theme; else document.documentElement.dataset.theme = theme; }
on("theme", () => { theme = THEMES[(THEMES.indexOf(theme) + 1) % 3]; store.set("theme", theme); applyTheme(); rail(); });
on("lang", () => setLang(ZH ? "en" : "zh"));

// ---- rail ---------------------------------------------------------------------------------------------
let badge = { tasks: 0 };
function rail() {
  const al = S.platforms.length ? alerts() : []; const lvl = al.some((a) => a.level === "bad") ? "bad" : al.length ? "warn" : "ok";
  const st = S.status;
  $("rail").innerHTML = `<a class="brand" href="#/search" title="SocialLens"><i></i></a>
    ${Object.entries(PAGES).map(([id, [n, ic]]) => `<button class="nav${S.page === id ? " on" : ""}" data-act="nav" data-arg='${J(id)}' data-tip="${n}" aria-label="${n}">${ic}${id === "tasks" && badge.tasks ? `<span class="cnt">${badge.tasks}</span>` : ""}${id === "status" && lvl !== "ok" ? `<span class="ndot ${lvl}"></span>` : ""}</button>`).join("")}
    <div class="rfoot">
      <button class="nav" data-act="nav" data-arg='"status"' data-tip="${st ? `后端 v${esc(st.backend_version)} · ${st.extension?.online ? "扩展已连接" : "扩展未连接"}` : "后端不可达"}"><span class="dot ${st?.extension?.online ? "ok" : "bad"}"></span></button>
      <button class="nav" data-act="theme" data-tip="${{ system: "主题：跟随系统", light: "主题：浅色", dark: "主题：深色" }[theme]}">${{ system: IC.auto, light: IC.sun, dark: IC.moon }[theme]}</button>
      <button class="nav" data-act="lang" data-tip="${ZH ? "English" : "中文"}">${IC.globe}</button>
    </div>`;
}
on("nav", (id) => { if (id === "search") { location.hash = lastSearch; return; } location.hash = `#/${id}`; });
on("setPage", (id) => { S.page = id; rail(); });
on("searchHash", (k) => { lastSearch = k; store.sset("lastSearch", k); });
async function badges() {
  try { const ts = (await api("/tasks?limit=100")).data; badge.tasks = ts.filter((t) => (t.status === "running" || t.status === "queued") && t.platform !== "_system" && t.action !== "navigate").length; } catch {}
  rail();
}
on("badges", () => setTimeout(badges, 300));

// ---- routing ------------------------------------------------------------------------------------------
function setPage(page, params) {
  S.page = page; rail(); $("main").scrollTop = 0;
  document.title = `${PAGES[page][0]} · SocialLens`;
  if (page === "search") return showSearch(params);
  if (page === "data") return showData(params);
  if (page === "tasks") return showTasks(params);
  if (page === "status") { showStatus(); loadStatus().then(showStatus).catch(() => showStatus()); return; }
  if (page === "api") return showApi();
}
function route() {
  const r = parseHash();
  if (r.page === "post" || r.page === "user") {
    if (!S.page) setPage("search", new URLSearchParams(lastSearch.split("?")[1] || ""));
    openRoute(r.page === "post" ? "posts" : "users", r.rest[0], r.rest.slice(1).join("/"));
    return;
  }
  leaveRoute();
  const page = PAGES[r.page] ? r.page : "search";
  if (S.page && page !== S.page && drawerOpen()) closeDrawer();
  if (page === "search") { lastSearch = location.hash || "#/search"; store.sset("lastSearch", lastSearch); }
  setPage(page, r.params);
}
let routeQueued = false;
const scheduleRoute = () => { if (routeQueued) return; routeQueued = true; setTimeout(() => { routeQueued = false; route(); }, 0); };
window.addEventListener("hashchange", scheduleRoute);
window.addEventListener("popstate", scheduleRoute);

// ---- keyboard -------------------------------------------------------------------------------------------
let kb = -1;
function navEls() { return [...$("main").querySelectorAll("[data-nav]")].filter((el) => el.offsetParent); }
function mark(i) {
  const els = navEls(); if (!els.length) return null;
  kb = Math.max(0, Math.min(els.length - 1, i));
  els.forEach((el, j) => el.classList.toggle("kb", j === kb));
  els[kb].scrollIntoView({ block: "nearest" });
  return els[kb];
}
document.addEventListener("keydown", (e) => {
  const tag = document.activeElement?.tagName; const typing = /INPUT|TEXTAREA|SELECT/.test(tag) || document.activeElement?.isContentEditable;
  if (e.key === "Escape") {
    if ($("modal").classList.contains("open")) return $("modal").classList.remove("open");
    if (typing) return document.activeElement.blur();
    if (drawerOpen()) return closeDrawer();
    return;
  }
  if (typing || e.metaKey || e.ctrlKey || e.altKey) return;
  if (document.body.classList.contains("dr-open") && $("drawer").classList.contains("full")) return;
  if (e.key === "/") { const f = $("f-keyword") || $("f-id") || $("d-q"); if (f) { e.preventDefault(); f.focus(); f.select(); } return; }
  if (e.key === "j" || e.key === "k") {
    const els = navEls(); const cur = els.findIndex((el) => el.classList.contains("kb"));
    const el = mark((cur < 0 ? (e.key === "j" ? -1 : 1) : cur) + (e.key === "j" ? 1 : -1));
    if (el && drawerOpen() && el.dataset.act === "open") el.click();
    return;
  }
  if (e.key === "o" || e.key === "Enter") { const el = navEls().find((x) => x.classList.contains("kb")); if (el) { e.preventDefault(); el.click(); } return; }
  if (e.key === "t") {
    const offs = [...$("main").querySelectorAll(".seg.sm")].map((seg) => seg.querySelector("button:not(.on)")).filter(Boolean).map((b) => [b.dataset.act, JSON.parse(b.dataset.arg)]);
    offs.forEach(([a, args]) => act(a, ...args));
  }
});

// ---- boot -----------------------------------------------------------------------------------------------
async function poll() {
  try { await loadStatus(); } catch {}
  rail(); refreshHeader(); badges();
}
(async () => {
  applyTheme(); rail(); installI18n();
  try { S.platforms = (await api("/platforms")).data; } catch (e) { toast("无法读取平台列表：" + e.message, true); }
  try { await loadStatus(); } catch {}
  route(); badges();
  setInterval(poll, 15000);
})();
