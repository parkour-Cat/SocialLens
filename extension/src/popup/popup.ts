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
  conn.innerHTML = `<span class="dot ${s.connected ? "ok" : "bad"}"></span>${s.connected ? `已连接 · v${s.backendVersion ?? "?"}` : "后端未启动"}`;

  // the tab the user is looking at
  const cur = $("current");
  if (s.currentTab) {
    cur.hidden = false;
    const holder = $("cur-logo");
    holder.replaceWith(Object.assign(logoEl(s.currentTab.platform, true), { id: "cur-logo" }));
    $("cur-title").textContent = `当前页面：${s.currentTab.name} · ${s.currentTab.logged_in ? "已登录" : "未登录"}`;
    $("cur-sub").textContent = !s.connected ? "后端未连接，此页暂时不能用" : s.currentTab.logged_in || !s.currentTab.login_required ? "后端可以在这个页面里执行请求" : "登录后后端才能使用这个页面";
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
    a.innerHTML = `<span class="dot warn"></span><span>${q.name} 队列已暂停，还剩 ${Math.ceil(q.paused_for_s / 60)} 分钟。先在页面里处理验证码，再恢复。</span>`;
    const btn = document.createElement("button");
    btn.className = "small";
    btn.textContent = "恢复";
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
    name.textContent = p.name || id;
    const tabs = document.createElement("span");
    tabs.className = "tabs";
    tabs.textContent = paused ? "已暂停" : p.logged_in ? (p.tab_ids.length ? `${p.tab_ids.length} 页` : "—") : "未登录";
    const right = document.createElement("span");
    if (!p.logged_in) {
      const a = document.createElement("a");
      a.href = p.login_url;
      a.target = "_blank";
      a.title = p.login_hint;
      a.textContent = "去登录 ↗";
      right.appendChild(a);
    } else {
      right.className = "tabs";
      right.textContent = p.recording ? "录制中" : "";
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
    $("error").textContent = `无法联系 background: ${String(e)}`;
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
