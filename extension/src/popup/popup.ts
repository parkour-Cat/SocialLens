import { PLATFORM_ICONS } from "../shared/icons";
import type { ExtStatus, PopupToBg } from "../shared/messages";

const $ = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;

const LOGOS: Record<string, { bg: string; mark: string }> = {
  bilibili: { bg: "#00A1D6", mark: "B" },
  xiaohongshu: { bg: "#FF2442", mark: "红" },
  douyin: { bg: "#161823", mark: "抖" },
  kuaishou: { bg: "#FF4906", mark: "快" },
  weixin_mp: { bg: "#07C160", mark: "公" },
  weixin_channels: { bg: "#FA9D3B", mark: "视" },
  youtube: { bg: "#FF0000", mark: "▶" },
  x: { bg: "#000000", mark: "X" },
  reddit: { bg: "#FF4500", mark: "r/" },
  zhihu: { bg: "#0066FF", mark: "知" },
  tiktok: { bg: "#010101", mark: "T" },
  instagram: { bg: "#E1306C", mark: "ig" },
  linkedin: { bg: "#0A66C2", mark: "in" },
  toutiao: { bg: "#ED4040", mark: "头" },
};

// ---- i18n: the popup is written in Chinese; English comes from this dictionary. Language follows
// the browser UI language (chrome.i18n), overridable with localStorage sl_lang = "zh" | "en".
const LANG: "zh" | "en" = (() => {
  try {
    const v = localStorage.getItem("sl_lang");
    if (v === "zh" || v === "en") return v;
  } catch {
    /* storage unavailable */
  }
  const ui = (chrome.i18n?.getUILanguage?.() || navigator.language || "").toLowerCase();
  return ui.startsWith("zh") ? "zh" : "en";
})();
const EN: Record<string, string> = {
  "已连接": "connected", "当前页面": "Current page", "页": "tabs", "无法联系 background": "Cannot reach the background script", "登录后后端才能使用这个页面": "Sign in first, then the backend can use this page",
  "连接中…": "Connecting…", "打开控制台": "Open console", "重连": "Reconnect", "高级设置": "Advanced", "后端地址": "Backend address", "留空即可": "leave empty", "保存并连接": "Save and connect",
  "Token（通常不需要，仅当后端提示扩展 ID 不匹配时填 data/token 的内容）": "Token (normally not needed; only when the backend reports an extension id mismatch, paste the content of data/token)",
  "后端未启动": "backend not running", "已登录": "signed in", "未登录": "not signed in", "后端未连接，此页暂时不能用": "Backend not connected; this page cannot be used yet", "后端可以在这个页面里执行请求": "The backend can run requests in this page", "已暂停": "paused", "录制中": "recording", "去登录 ↗": "Sign in ↗", "恢复": "Resume",
  "B 站": "Bilibili", "小红书": "Xiaohongshu", "抖音": "Douyin", "快手": "Kuaishou", "公众号": "WeChat Official Accounts", "视频号": "WeChat Channels", "知乎": "Zhihu", "今日头条": "Toutiao",
  "打开 bilibili.com，右上角登录（扫码或账号密码）": "Open bilibili.com and sign in at the top right (QR code or password)", "打开 douyin.com，右上角登录，用抖音 App 扫码": "Open douyin.com, sign in at the top right by scanning with the Douyin app", "打开 instagram.com 登录（需要能访问 Instagram 的网络）": "Sign in at instagram.com (needs a network that can reach Instagram)", "打开 kuaishou.com，右上角登录，用快手 App 扫码": "Open kuaishou.com, sign in at the top right by scanning with the Kuaishou app", "打开 linkedin.com 登录": "Sign in at linkedin.com", "打开 reddit.com 登录（不登录也能看公开内容，登录后才有个人首页流）": "Sign in at reddit.com (public content works signed out; the home feed needs an account)", "打开 tiktok.com 登录（需要能访问 TikTok 的网络；不登录也能看部分公开内容）": "Sign in at tiktok.com (needs a network that can reach TikTok; some public content works signed out)", "打开 toutiao.com，点右上角登录（不登录也能看公开内容）": "Open toutiao.com and sign in at the top right (public content works signed out)", "打开 channels.weixin.qq.com（视频号网页版），用微信扫码登录": "Open channels.weixin.qq.com and sign in by scanning with WeChat", "打开 mp.weixin.qq.com（公众号后台），用微信扫码登录你自己的公众号；公域搜索和文章列表都走这个后台": "Open mp.weixin.qq.com (the Official Accounts backstage) and sign in to your own account with WeChat; search and article lists go through this backstage", "打开 x.com 登录（几乎所有页面都要求登录）": "Sign in at x.com (nearly every page requires it)", "打开 xiaohongshu.com，用小红书 App 扫码登录": "Open xiaohongshu.com and sign in by scanning with the Xiaohongshu app", "打开 youtube.com，用 Google 账号登录（不登录也能看公开内容）": "Open youtube.com and sign in with a Google account (public content works signed out)", "打开 zhihu.com，扫码或账号登录（几乎所有内容都要求登录）": "Open zhihu.com and sign in by QR code or password (nearly everything requires it)",
};
const t = (s: string): string => (LANG === "en" ? (EN[s] ?? s) : s);
function translateStatic(): void {
  if (LANG !== "en") return;
  document.documentElement.lang = "en";
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    const k = (n.nodeValue ?? "").trim();
    if (k && EN[k]) n.nodeValue = n.nodeValue!.replace(k, EN[k]);
  }
  for (const el of Array.from(document.querySelectorAll<HTMLElement>("[placeholder]"))) {
    const v = el.getAttribute("placeholder") ?? "";
    if (EN[v]) el.setAttribute("placeholder", EN[v]);
  }
}
translateStatic();

function send<T = unknown>(msg: PopupToBg): Promise<T> {
  return chrome.runtime.sendMessage(msg) as Promise<T>;
}

// Icons are inlined data URIs (src/shared/icons.ts): no request, no fade, nothing to flicker.
function logoEl(id: string, small = false): HTMLElement {
  const l = LOGOS[id] ?? { bg: "#666", mark: "?" };
  const el = document.createElement("span");
  el.className = `plogo${small ? " sm" : ""}`;
  el.style.background = l.bg;
  const ico = PLATFORM_ICONS[id];
  if (ico) {
    const img = document.createElement("img");
    img.src = ico;
    img.alt = "";
    img.className = "ok";
    el.appendChild(img);
  } else {
    el.textContent = l.mark;
  }
  return el;
}

let lastRendered = "";

function consoleUrl(backendUrl: string): string {
  try {
    const u = new URL(backendUrl);
    return `${u.protocol === "wss:" ? "https" : "http"}://${u.host}/ui/`;
  } catch {
    return "http://127.0.0.1:17800/ui/";
  }
}

function render(s: ExtStatus): void {
  // Only touch the DOM when something changed: rebuilding the list every poll makes it flicker.
  const key = JSON.stringify(s);
  if (key === lastRendered) return;
  lastRendered = key;
  const conn = $("conn");
  conn.className = `pill ${s.connected ? "ok" : "bad"}`;
  conn.innerHTML = `<span class="dot ${s.connected ? "ok" : "bad"}"></span>${s.connected ? `${t("已连接")} · v${s.backendVersion ?? "?"}` : t("后端未启动")}`;

  // the tab the user is looking at
  const cur = $("current");
  if (s.currentTab) {
    cur.hidden = false;
    const holder = $("cur-logo");
    holder.replaceWith(Object.assign(logoEl(s.currentTab.platform, true), { id: "cur-logo" }));
    $("cur-title").textContent = `${t("当前页面")}：${t(s.currentTab.name)} · ${s.currentTab.logged_in ? t("已登录") : t("未登录")}`;
    $("cur-sub").textContent = !s.connected ? t("后端未连接，此页暂时不能用") : s.currentTab.logged_in || !s.currentTab.login_required ? t("后端可以在这个页面里执行请求") : t("登录后后端才能使用这个页面");
  } else {
    cur.hidden = true;
  }

  // things that need the user: paused queues, lost backend
  const alerts = $("alerts");
  alerts.innerHTML = "";
  if (s.lastError && !s.connected) {
    const a = document.createElement("div");
    a.className = "alert bad";
    a.innerHTML = `<span class="dot bad"></span><span>${s.lastError}</span>`;
    alerts.appendChild(a);
  }
  for (const q of s.alerts ?? []) {
    const a = document.createElement("div");
    a.className = "alert";
    const mins = Math.ceil(q.paused_for_s / 60);
    a.innerHTML = `<span class="dot warn"></span><span>${LANG === "en" ? `${t(q.name)} queue paused, ${mins} min left. Handle the captcha on the page, then resume.` : `${q.name} 队列已暂停，还剩 ${mins} 分钟。先在页面里处理验证码，再恢复。`}</span>`;
    const btn = document.createElement("button");
    btn.className = "small";
    btn.textContent = t("恢复");
    btn.onclick = async () => {
      btn.disabled = true;
      await send({ type: "popup.resume", platform: q.platform });
      setTimeout(refresh, 500);
    };
    a.appendChild(btn);
    alerts.appendChild(a);
  }

  const list = $("platforms");
  list.innerHTML = "";
  for (const [id, p] of Object.entries(s.platforms)) {
    const el = document.createElement("div");
    el.className = "plat";
    const paused = (s.alerts ?? []).some((a) => a.platform === id);
    const dot = document.createElement("span");
    dot.className = `dot ${paused ? "warn" : p.logged_in ? "ok" : "bad"}`;
    const name = document.createElement("span");
    name.textContent = t(p.name || id);
    const tabs = document.createElement("span");
    tabs.className = "tabs";
    tabs.textContent = paused ? t("已暂停") : p.logged_in ? (p.tab_ids.length ? `${p.tab_ids.length} ${t("页")}` : "—") : t("未登录");
    const right = document.createElement("span");
    if (!p.logged_in) {
      const a = document.createElement("a");
      a.href = p.login_url;
      a.target = "_blank";
      a.title = t(p.login_hint);
      a.textContent = t("去登录 ↗");
      right.appendChild(a);
    } else {
      right.className = "tabs";
      right.textContent = p.recording ? t("录制中") : "";
    }
    el.append(dot, logoEl(id, true), name, tabs, right);
    list.appendChild(el);
  }

  $("build").textContent = s.build ? `build ${s.build.slice(0, 7)}` : "";
  const urlInput = $<HTMLInputElement>("backendUrl");
  if (!urlInput.value) urlInput.value = s.backendUrl;
  $("open").onclick = () => chrome.tabs.create({ url: consoleUrl(s.backendUrl) });
}

async function refresh(): Promise<void> {
  try {
    render(await send<ExtStatus>({ type: "popup.status" }));
  } catch (e) {
    $("error").textContent = `${t("无法联系 background")}: ${String(e)}`;
  }
}

$("save").addEventListener("click", async () => {
  const backendUrl = $<HTMLInputElement>("backendUrl").value.trim();
  const token = $<HTMLInputElement>("token").value.trim();
  await send({ type: "popup.save", backendUrl, token });
  $<HTMLInputElement>("token").value = "";
  setTimeout(refresh, 600);
});

$("reconnect").addEventListener("click", async () => {
  await send({ type: "popup.reconnect" });
  setTimeout(refresh, 600);
});

void refresh();
setInterval(refresh, 2000);
