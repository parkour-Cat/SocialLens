// Result lists: posts / users as table or cards, trending topics, comment threads. Rows carry
// data-act="open" with a list id + index; the drawer resolves them through getList().
import { esc, J, fmtN, fmtT, fmtDur, logo, store, api, toast, on, act, actCtx, xs, IC } from "./core.js";

const LISTS = new Map(); let seq = 0;
export function listId(items) { const id = "l" + (++seq); LISTS.set(id, items); if (LISTS.size > 80) LISTS.delete(LISTS.keys().next().value); return id; }
export const getList = (id) => LISTS.get(id);

const PORTRAIT = new Set(["xiaohongshu", "douyin", "kuaishou", "instagram", "tiktok"]);
export function viewOf(pid, kind) {
  if (kind === "comments" || kind === "topics") return "table";
  const v = store.get("views", {})[`${pid || "_"}:${kind}`];
  return v || (kind === "posts" && PORTRAIT.has(pid) ? "card" : "table");
}
export function setView(pid, kind, v) { const all = store.get("views", {}); all[`${pid || "_"}:${kind}`] = v; store.set("views", all); }
export function viewSeg(pid, kind, act = "view") {
  if (kind === "comments" || kind === "topics") return "";
  const v = viewOf(pid, kind);
  return `<div class="seg sm" title="表格 / 卡片（t）"><button class="${v === "table" ? "on" : ""}" data-act="${act}" data-arg='${J([pid, kind, "table"])}'>${IC.table}<span>表格</span></button><button class="${v === "card" ? "on" : ""}" data-act="${act}" data-arg='${J([pid, kind, "card"])}'>${IC.grid}<span>卡片</span></button></div>`;
}

const img = (src, cls, alt = "") => src ? `<img class="${cls}" src="${esc(src)}" alt="${esc(alt)}" loading="lazy" referrerpolicy="no-referrer" onerror="this.classList.add('broken')">` : `<span class="${cls} broken"></span>`;
export const avatar = (u, cls = "av") => u?.avatar_url ? img(u.avatar_url, cls) : `<span class="${cls} ph">${esc((u?.name || "?").slice(0, 1))}</span>`;
export const titleOf = (p) => { const s = (p.content || "").replace(/&(amp|lt|gt|quot|#39);/g, (m) => ({ "&amp;": "&", "&lt;": "<", "&gt;": ">", "&quot;": '"', "&#39;": "'" })[m]).replace(/\s+/g, " ").trim(); return p.title || (s.length > 90 ? s.slice(0, 90) + "…" : s) || "（无标题）"; };
const videoDur = (p) => (p.media || []).find((m) => m.type === "video" && m.duration)?.duration;
/** X (and other threaded sites) store the parent post id on replies; a reply is a post of its own there. */
export const isReply = (p) => !!(p?.raw?.in_reply_to);
const replyTag = (p) => isReply(p) ? `<span class="pill reply">↩ 回复</span>` : "";
const imgCount = (p) => (p.media || []).filter((m) => m.type === "image").length;

/** opts: { showPlatform } — show a platform logo per row (cache / mixed lists). */
export function renderList(items, kind, pid, view, opts = {}) {
  if (!items?.length) return `<div class="empty">没有数据</div>`;
  const lid = listId(items); const sp = !!opts.showPlatform;
  const open = (i) => `data-act="open" data-arg='${J([lid, i])}' data-nav`;
  if (kind === "comments") return renderThread(items, pid, lid, opts);
  if (kind === "topics") {
    return `<table class="tbl"><thead><tr><th class="r">#</th><th>话题</th><th class="r">热度</th><th>分类</th><th>说明</th><th></th></tr></thead><tbody>${items.map((t, i) => `<tr data-act="topic" data-arg='${J([t.platform || pid, t.title])}' data-nav><td class="r num faint">${esc(t.rank)}</td><td class="strong">${esc(t.title)}</td><td class="r num">${fmtN(t.heat)}</td><td class="mute">${esc(t.category || "")}</td><td class="mute"><div class="clamp1">${esc(t.description || "")}</div></td><td class="acts">${t.url ? `<a class="btn ghost sm" href="${esc(t.url)}" target="_blank" rel="noreferrer">打开 ↗</a>` : ""}<button class="btn ghost sm" data-act="topic" data-arg='${J([t.platform || pid, t.title])}'>搜索</button></td></tr>`).join("")}</tbody></table>`;
  }
  if (kind === "users") {
    if (view === "card") return `<div class="cards users">${items.map((u, i) => `<div class="ucard" ${open(i)}>${avatar(u, "uav")}<div class="un">${sp ? logo(u.platform) : ""}${esc(u.name)}</div><div class="mono faint">${esc(u.id)}</div><div class="ustats"><span><b class="num">${fmtN(u.metrics?.followers)}</b> 粉丝</span><span><b class="num">${fmtN(u.metrics?.posts)}</b> 作品</span></div><div class="clamp2 mute">${esc(u.bio || "")}</div></div>`).join("")}</div>`;
    return `<table class="tbl"><thead><tr><th></th><th>名称</th><th class="r">粉丝</th><th class="r">关注</th><th class="r">作品</th><th>简介</th><th></th></tr></thead><tbody>${items.map((u, i) => `<tr ${open(i)}><td style="width:40px">${avatar(u)}</td><td><div class="strong">${sp ? logo(u.platform) + " " : ""}${esc(u.name)}</div><div class="mono faint">${esc(u.id)}</div></td><td class="r num">${fmtN(u.metrics?.followers)}</td><td class="r num">${fmtN(u.metrics?.following)}</td><td class="r num">${fmtN(u.metrics?.posts)}</td><td class="mute"><div class="clamp2">${esc(u.bio || "")}</div></td><td class="acts">${u.url ? `<a class="btn ghost sm" href="${esc(u.url)}" target="_blank" rel="noreferrer">主页 ↗</a>` : ""}<button class="btn ghost sm" data-act="quick" data-arg='${J([u.platform || pid, "get_user_posts", { id: u.id, xsec: xs(u) }])}'>帖子</button></td></tr>`).join("")}</tbody></table>`;
  }
  if (view === "card") {
    const portrait = PORTRAIT.has(pid);
    return `<div class="cards">${items.map((p, i) => { const d = videoDur(p), n = imgCount(p); return `<div class="pcard ${portrait || PORTRAIT.has(p.platform) ? "portrait" : ""}" ${open(i)}><div class="cv">${p.cover_url ? img(p.cover_url, "cvimg") : `<div class="cvtext">${esc((p.content || "").slice(0, 160))}</div>`}${d ? `<span class="badge">${fmtDur(d)}</span>` : n > 1 ? `<span class="badge">1/${n}</span>` : ""}${sp ? `<span class="pbadge">${logo(p.platform)}</span>` : ""}</div><div class="cb"><div class="clamp2 strong">${replyTag(p)}${esc(titleOf(p))}</div><div class="cm"><span class="who">${avatar(p.author, "av xs")}<span class="ell">${esc(p.author?.name || "")}</span></span><span class="num faint">♥ ${fmtN(p.metrics?.likes)}</span></div></div></div>`; }).join("")}</div>`;
  }
  return `<table class="tbl"><thead><tr><th></th><th>标题 / 内容</th><th>作者</th><th class="r">赞</th><th class="r">评论</th><th class="r">播放</th><th>时间</th><th></th></tr></thead><tbody>${items.map((p, i) => {
    const snip = (p.content || "").replace(/\s+/g, " ").trim(); const d = videoDur(p);
    return `<tr ${open(i)}><td class="tc"><div class="thumbw">${img(p.cover_url, "thumb")}${d ? `<span class="tdur">${fmtDur(d)}</span>` : ""}</div></td><td class="tmain"><div class="clamp2 strong">${sp ? logo(p.platform) + " " : ""}${replyTag(p)}${esc(titleOf(p))}</div>${p.title && snip ? `<div class="clamp1 mute">${esc(snip)}</div>` : ""}<div class="mono faint">${esc(p.id)}</div></td><td class="nowrap"><span class="who">${avatar(p.author, "av xs")}<span class="ell">${esc(p.author?.name || "")}</span></span></td><td class="r num">${fmtN(p.metrics?.likes)}</td><td class="r num">${fmtN(p.metrics?.comments)}</td><td class="r num">${fmtN(p.metrics?.views)}</td><td class="nowrap faint num">${fmtT(p.publish_time)}</td><td class="acts">${p.url ? `<a class="btn ghost sm" href="${esc(p.url)}" target="_blank" rel="noreferrer">打开 ↗</a>` : ""}<button class="btn ghost sm" data-act="openTab" data-arg='${J([lid, i, "comments"])}'>评论</button><button class="btn ghost sm" data-act="download" data-arg='${J([p.platform || pid, p.id, xs(p)])}'>下载</button></td></tr>`;
  }).join("")}</tbody></table>`;
}

// ---- comment threads ------------------------------------------------------------------------------
export const replyCount = (c) => c.raw?.reply_count ?? c.raw?.replies ?? c.raw?.reply_total ?? c.raw?.sub_comment_count ?? c.raw?.rcount;
function canReply(c) { const n = replyCount(c); return n > 0 || c.raw?.replies_token || c.raw?.sub_comment_has_more || c.raw?.has_more_replies; }
export function commentHtml(c, lid, i, pid, reply, opts = {}) {
  const n = replyCount(c); const postId = c.post_id || opts.postId || "";
  const fmt = opts.rich ? opts.rich(c.content || "", c.platform || pid) : esc(c.content);
  return `<div class="cmt${reply ? " reply" : ""}" data-cid="${esc(c.id)}" ${lid ? `data-act="open" data-arg='${J([lid, i])}' data-nav` : ""}>${avatar(c.author, "av")}<div class="cbody"><div class="ch"><b>${esc(c.author?.name || "匿名")}</b>${c.raw?.is_creator || c.raw?.is_submitter ? `<span class="pill accent">作者</span>` : ""}<span class="faint">${fmtT(c.publish_time)}</span></div><div class="ctext">${fmt}</div><div class="cmeta"><span>♥ <b class="num">${fmtN(c.likes)}</b></span>${n != null && !reply ? `<span>回复 <b class="num">${fmtN(n)}</b></span>` : ""}${!reply && canReply(c) ? `<button class="linkbtn" data-act="replies" data-arg='${J([c.platform || pid, postId, c.id, null, opts.xsec || ""])}'>展开回复</button>` : ""}</div></div></div>`;
}
export function renderThread(items, pid, lid, opts = {}) {
  const byParent = {}; for (const c of items) if (c.parent_id) (byParent[c.parent_id] ||= []).push(c);
  const roots = items.filter((c) => !c.parent_id); const rootIds = new Set(roots.map((r) => r.id));
  const html = roots.map((c) => commentHtml(c, lid, items.indexOf(c), pid, false, opts) + (byParent[c.id] || []).map((r) => commentHtml(r, lid, items.indexOf(r), pid, true, opts)).join("")).join("");
  const orphans = items.filter((c) => c.parent_id && !rootIds.has(c.parent_id));
  return `<div class="thread">${html}${orphans.map((r) => commentHtml(r, lid, items.indexOf(r), pid, true, opts)).join("")}</div>`;
}
on("replies", async (platform, postId, cid, cursor, xsec) => {
  const { el } = actCtx();
  const host = el.closest(".cmt") || el.closest(".replies-more")?.previousElementSibling; const thread = el.closest(".thread");
  el.disabled = true; el.textContent = "加载中…";
  try {
    const q = new URLSearchParams(); if (cursor) q.set("cursor", cursor); if (xsec) q.set("xsec_token", xsec);
    const r = await api(`/${platform}/posts/${encodeURIComponent(postId)}/comments/${encodeURIComponent(cid)}/replies${q.toString() ? "?" + q : ""}`);
    const shown = new Set([...thread.querySelectorAll(".cmt.reply")].map((d) => d.dataset.cid));
    const replies = (r.data?.items || []).filter((c) => !shown.has(String(c.id)));
    const lid = listId(replies);
    let anchor = el.closest(".replies-more") || host; while (anchor.nextElementSibling?.classList.contains("reply")) anchor = anchor.nextElementSibling;
    anchor.insertAdjacentHTML("afterend", replies.map((c, k) => commentHtml(c, lid, k, platform, true, { xsec })).join("") + (r.cursor ? `<div class="replies-more"><button class="linkbtn" data-act="replies" data-arg='${J([platform, postId, cid, r.cursor, xsec])}'>更多回复</button></div>` : ""));
    if (el.closest(".replies-more")) el.closest(".replies-more").remove(); else el.textContent = replies.length ? `已展开 ${replies.length} 条` : "没有回复";
  } catch (e) { el.disabled = false; el.textContent = "展开回复"; toast(e.message, true); }
});
on("topic", (pid, title) => act("quick", pid, "search_posts", { keyword: title }));

export function skeleton(n = 6) {
  return `<div class="skel">${Array.from({ length: n }, () => `<div class="skrow"><div class="sk" style="width:96px;height:54px"></div><div class="skcol"><div class="sk" style="height:14px;width:68%"></div><div class="sk" style="height:12px;width:38%"></div></div></div>`).join("")}</div>`;
}
