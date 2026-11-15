// 接口 page: capability matrix, REST endpoints derived from /openapi.json, MCP tools, conventions.
// The per-route Chinese names / descriptions and platform notes moved here verbatim from the old console.
import { $, esc, J, api, toast, on, S, plat, pname, logo, IC } from "./core.js";
import { Z, ZH } from "./i18n.js";

const STATUS_NAME = { open: ["bad", "未解决"], unverified: ["warn", "待验证"], limit: ["neutral", "站点限制"], by_design: ["neutral", "有意为之"] };
async function loadIssues() {
  if (!S.platforms.length) { setTimeout(loadIssues, 300); return; }
  try {
    const list = (await api("/known-issues")).data;
    $("issues-list").innerHTML = list.map((i) => { const st = STATUS_NAME[i.status] || ["neutral", i.status]; const who = i.platform === "extension" ? "扩展" : i.platform === "general" ? "通用" : pname(i.platform); return `<div class="row" style="align-items:flex-start"><span class="t">${esc(i.since)}</span><span>${i.platform === "extension" || i.platform === "general" ? `<b>${esc(who)}</b>` : `${logo(i.platform)} ${esc(who)}`} · <b>${esc(ZH ? i.title : i.title_en)}</b><br><span class="sub">${esc(ZH ? i.detail : i.detail_en)}</span></span><span class="pill ${st[0]}">${esc(st[1])}</span></div>`; }).join("");
  } catch (e) { $("issues-list").innerHTML = `<div class="empty">${esc(e.message)}</div>`; }
}
let apiDoc = null, mcpDoc = null;
const CAP_COLS = [["search_posts", Z("搜索内容", "Search posts")], ["search_users", Z("搜索用户", "Search users")], ["get_post", Z("帖子详情", "Post detail")], ["get_comments", Z("评论", "Comments")], ["get_replies", Z("评论回复", "Replies")], ["get_user", Z("用户资料", "Profile")], ["get_user_posts", Z("用户帖子", "User posts")], ["get_feed", Z("推荐流", "Feed")], ["get_trending", Z("热榜", "Trending")], ["download", Z("下载", "Download")]];
const UNVERIFIED = { weixin_mp: { get_user_posts: Z("账号被 freq control 冻结，等解冻录样本", "the account is frozen by freq control; samples wait for the thaw") } };
const NO_DOWNLOAD = new Set(["weixin_channels"]);
const PLATFORM_NOTES = {
  weixin_channels: Z("视频号网页版只有创作者后台和分享链接播放页，没有公域搜索、详情、评论入口，这些接口都不可用；后台数据接口留到以后做。", "The WeChat Channels website only has the creator backstage and share-link players: no public search, detail or comment entry, so none of these endpoints work. Backstage data endpoints are left for later."),
  weixin_mp: Z("公众号没有推荐流和热榜；搜索只能搜公众号（账号），文章列表靠 appmsg 接口，账号解冻后才能验证。", "Official Accounts have no feed or trending; search only finds accounts, and the article list relies on the appmsg endpoint, which can only be verified once the account thaws."),
  xiaohongshu: Z("小红书的笔记和用户 id 要配合链接里的 xsec_token；热榜实际是搜索框的\"猜你想搜\"，个性化。", "Xiaohongshu note and user ids need the xsec_token from the link; \"trending\" is really the search box's personalised suggestions."),
  kuaishou: Z("快手网页版的评论列表不带子评论信息，没有评论回复；也没找到公开热榜。", "Kuaishou's web comment list carries no reply information, so there are no replies; no public trending list was found either."),
  youtube: Z("YouTube 不登录也能用公开内容；下载走 yt-dlp 并沿用系统代理。", "YouTube works without signing in for public content; downloads go through yt-dlp using the system proxy."),
  linkedin: Z("LinkedIn 新版首页和搜索是服务端驱动 UI，没有可捕获的实体数据，首页流、帖子详情、个人资料、人员搜索在标签页里调用老的 voyager 接口（带 csrf 头）；作者动态页和帖子详情页还是老版页面，作者动态、评论、评论回复靠捕获它自己的请求。没有内容搜索和热榜。作者动态对非联系人只给 20 条；人员搜索的 queryId 会随站点部署变化。", "LinkedIn's new home and search are server-driven UI with no capturable entity data, so feed, post detail, profile and people search call the classic voyager API inside the tab (with the csrf header); the activity and post-detail pages are still the classic app, so member posts, comments and replies are captured from its own requests. No content search or trending. Member posts stop at 20 for non-connections; the people-search queryId changes with deployments."),
  instagram: Z("Instagram 只捕获站点自己发的 GraphQL 请求，扩展不主动调接口。帖子详情和评论第一页是页面内嵌数据；用户搜索通过在搜索框里输入触发，没有翻页（网页版本身不提供更多账号结果）。风控最严的平台，整页加载配额 10 分钟 10 次。", "Instagram only captures the site's own GraphQL requests; the extension never calls the API itself. Post detail and the first comment page are embedded in the page; user search is triggered by typing into the search box and has no paging (the website offers no more). The strictest platform: 10 page loads per 10 minutes."),
  toutiao: Z("头条所有接口都带站点自己算的签名，扩展只打开页面、捕获站点自己发的请求。搜索走 so.toutiao.com 的资讯标签；评论第二页起要打开评论抽屉，抽屉在未登录时可能不可用。", "Every Toutiao endpoint carries a site-computed signature, so the extension only opens pages and captures the site's own requests. Search uses the news tab on so.toutiao.com; comment pages after the first need the comment drawer, which may require signing in."),
  reddit: Z("Reddit 走公开的 .json 接口，不需要签名；不登录也能用，登录后首页流才是个性化的。评论一次最多 100 条顶层，更多的要 morechildren 接口，暂不做。", "Reddit uses the public .json endpoints, no signature needed; works signed out, the home feed is personalised only when signed in. Comments come 100 top-level at a time; the rest go through morechildren."),
  zhihu: Z("知乎几乎所有内容都要登录。帖子 id 形如 answer:123、article:123、question:123；评论会内联带上每条的前几条回复。", "Nearly everything on Zhihu requires signing in. Post ids look like answer:123, article:123, question:123; comments inline the first few replies of each."),
  tiktok: Z("TikTok 需要能访问的网络（浏览器走系统代理即可）。视频只给 id 时，后端先通过公开的 oembed 接口换成作者名再打开页面。评论要先在页面里点开评论面板才会请求，扩展会自动点。", "TikTok needs a network that can reach it (the browser's system proxy is enough). Given only a video id, the backend first resolves the author through the public oembed endpoint. Comments load only after the comment panel is opened; the extension clicks it."),
};
const NOUN = { bilibili: Z("视频", "videos"), xiaohongshu: Z("笔记", "notes"), douyin: Z("视频", "videos"), kuaishou: Z("视频", "videos"), weixin_mp: Z("文章", "articles"), youtube: Z("视频", "videos"), x: Z("推文", "tweets"), weixin_channels: Z("视频", "videos"), reddit: Z("帖子", "posts"), zhihu: Z("回答 / 文章 / 问题", "answers / articles / questions"), tiktok: Z("视频", "videos"), toutiao: Z("文章", "articles"), instagram: Z("帖子", "posts"), linkedin: Z("动态", "posts") };
const USER_ID = { reddit: Z("用户名（不带 u/）", "username (without u/)"), zhihu: Z("url_token（主页链接 /people/ 后面那段）", "url_token (the part after /people/ in the profile link)"), tiktok: Z("@uniqueId（不带 @ 也行）", "@uniqueId (the @ is optional)"), bilibili: Z("mid（数字）", "mid (a number)"), xiaohongshu: Z("用户 id，配合链接里的 xsec_token", "user id plus the xsec_token from the link"), douyin: Z("sec_uid（主页链接 /user/ 后面那串）", "sec_uid (the part after /user/ in the profile link)"), kuaishou: Z("用户 id（主页链接 /profile/ 后面那段）", "user id (the part after /profile/)"), weixin_mp: Z("公众号的 fakeid（搜索公众号结果里的 id）", "the account's fakeid (the id in account search results)"), youtube: Z("@handle 或 UC 开头的频道 id", "@handle or a UC… channel id"), x: Z("用户名（不带 @）", "username (without @)"), toutiao: Z("作者主页 token（/c/user/token/ 后面那串 MS4w… ）", "profile token (the MS4w… part after /c/user/token/)"), instagram: Z("用户名（不带 @）", "username (without @)"), linkedin: Z("个人主页 vanity（/in/ 后面那段）", "profile vanity name (the part after /in/)") };
const ORDERS_DESC = { bilibili: Z("order 可选 totalrank 综合、click 播放、pubdate 最新", "order: totalrank (relevance), click (views), pubdate (newest)"), x: Z("order 可选 live 最新、top 热门", "order: live (latest), top"), reddit: Z("order 可选 relevance 相关、hot、top、new、comments", "order: relevance, hot, top, new, comments") };
const DL_DESC = { reddit: Z("i.redd.it 图片直链；v.redd.it 视频是分离的 DASH，取视频和音轨用 ffmpeg 合并，无声视频只留视频。", "i.redd.it images are direct; v.redd.it videos are split DASH, video and audio are merged with ffmpeg, silent videos keep the video track only."), tiktok: Z("视频地址绑定浏览器 cookie，后端直连 403，交给 yt-dlp 并沿用系统代理。", "Video urls are bound to browser cookies and answer 403 from the backend, so yt-dlp handles them through the system proxy."), bilibili: Z("有 ffmpeg 时取 DASH 最高画质并合并音视频，没有时取单文件 mp4；mode 可强制 dash 或 mp4。", "With ffmpeg the best DASH quality is merged; without it a single mp4 is taken; mode forces dash or mp4."), youtube: Z("交给 yt-dlp（已装进后端环境），最高画质并合并，沿用系统代理。", "Handled by yt-dlp (installed with the backend), best quality merged, through the system proxy."), weixin_mp: Z("下载文章里的图片（直链）。", "Downloads the article's images (direct links)."), xiaohongshu: Z("视频取最高清晰度的直链，图片取原图；要带 xsec_token。", "Best-quality video link and original images; needs xsec_token."), douyin: Z("视频直链，无水印版本以站点给的为准；图文帖下载全部图片。", "Direct video link as the site provides it; image posts download every image."), kuaishou: Z("视频直链。", "Direct video link."), x: Z("视频取最高码率的 mp4，图片取原图。", "Highest-bitrate mp4 for videos, original images.") };
const ROUTE_INFO = {
  "GET /api/v1/{platform}/search": { name: Z("搜索", "Search"), cap: "search", desc: (pid, caps) => {
    const noun = NOUN[pid] || Z("内容", "content");
    const kinds = [caps.has("search_posts") ? Z(`搜${noun}（type=post）`, `${noun} (type=post)`) : null, caps.has("search_users") ? Z("搜账号（type=user）", "accounts (type=user)") : null].filter(Boolean);
    if (!caps.has("search_posts")) return Z(`只能搜账号（type=user），${pid === "weixin_mp" ? "也就是按名称搜公众号" : "不能搜内容"}。带 cursor 翻页。`, `Accounts only (type=user)${pid === "weixin_mp" ? ", i.e. official accounts by name" : "; no content search"}. Pages with cursor.`);
    return Z(`${kinds.join("，")}，type 默认 post。${ORDERS_DESC[pid] ? ORDERS_DESC[pid] + "。" : ""}带 cursor 翻页。${pid === "xiaohongshu" ? "搜索接口容易触发风控，别连续大量调用。" : ""}`, `Searches ${kinds.join(" or ")}; type defaults to post. ${ORDERS_DESC[pid] ? ORDERS_DESC[pid] + ". " : ""}Pages with cursor.${pid === "xiaohongshu" ? " Search trips risk control easily; avoid bursts." : ""}`);
  } },
  "GET /api/v1/{platform}/posts/{post_id}": { name: Z("帖子详情", "Post detail"), cap: "get_post", desc: (pid) => Z(`一条${NOUN[pid] || "帖子"}：标题、正文、作者、指标、媒体地址。${pid === "xiaohongshu" ? "post_id 是笔记 id，必须带列表项里的 xsec_token。" : pid === "bilibili" ? "post_id 用 BV 号或 av 号。" : pid === "weixin_mp" ? "post_id 是文章链接 /s/ 后面那段。" : pid === "youtube" ? "post_id 是视频 id（watch?v= 后面 11 位）。" : pid === "x" ? "post_id 是推文 id（status/ 后面的数字）。" : ""}`, `One of the platform's ${NOUN[pid] || "posts"}: title, text, author, metrics, media urls.${pid === "xiaohongshu" ? " post_id is the note id and needs the xsec_token from the list item." : pid === "bilibili" ? " post_id is a BV or av id." : pid === "weixin_mp" ? " post_id is the part after /s/ in the article link." : pid === "youtube" ? " post_id is the 11-character video id (after watch?v=)." : pid === "x" ? " post_id is the tweet id (the number after status/)." : ""}`) },
  "GET /api/v1/{platform}/posts/{post_id}/comments": { name: Z("评论", "Comments"), cap: "get_comments", desc: (pid) => Z(`一级评论列表，带 cursor 翻页。${pid === "bilibili" ? "mode 选排序：3 热门（默认）、2 时间。" : pid === "xiaohongshu" ? "要带 xsec_token。" : pid === "reddit" ? "mode 选排序：confidence（默认）、top、new、controversial、old、qa；每页最多 100 条顶层，cursor 翻页走 morechildren；回复以\"有更多回复\"标记。" : pid === "zhihu" ? "每条评论内联带前几条回复（parent_id 已挂好）。" : ""}`, `Top-level comments, pages with cursor.${pid === "bilibili" ? " mode picks the order: 3 hot (default), 2 by time." : pid === "xiaohongshu" ? " Needs xsec_token." : pid === "reddit" ? " mode picks the order: confidence (default), top, new, controversial, old, qa; up to 100 top-level per page, later pages go through morechildren." : pid === "zhihu" ? " Each comment inlines its first replies (parent_id set)." : ""}`) },
  "GET /api/v1/{platform}/posts/{post_id}/comments/{comment_id}/replies": { name: Z("评论的回复", "Replies"), cap: "get_replies", desc: (pid) => Z(`一条评论下的回复（楼中楼），parent_id 是该评论，带 cursor 翻页。${["douyin", "xiaohongshu"].includes(pid) ? "接口带签名，扩展会在页面里找到那条评论点\"展开回复\"再捕获，每次十几秒。" : pid === "youtube" ? "用评论自带的 continuation，很快。" : pid === "x" ? "就是那条回复自己的详情页。" : ""}`, `Replies under one comment; parent_id is that comment; pages with cursor.${["douyin", "xiaohongshu"].includes(pid) ? " The endpoint is signed, so the extension locates the comment on the page and clicks its expand control before capturing; ten seconds or so each time." : pid === "youtube" ? " Uses the comment's own continuation token; fast." : pid === "x" ? " This is the reply's own detail page." : ""}`) },
  "GET /api/v1/{platform}/users/{user_id}": { name: Z("用户资料", "Profile"), cap: "get_user", desc: (pid) => Z(`资料和粉丝、关注、作品数。user_id 用 ${USER_ID[pid] || "平台的用户 id"}。`, `Profile with follower, following and post counts. user_id is the ${USER_ID[pid] || "platform's user id"}.`) },
  "GET /api/v1/{platform}/users/{user_id}/posts": { name: Z("用户的帖子", "User posts"), cap: "get_user_posts", desc: (pid) => Z(`某个账号发布的${NOUN[pid] || "内容"}，最新在前，带 cursor 翻页。${pid === "bilibili" ? "order 可选 pubdate 最新、click 播放。" : ""}${pid === "weixin_mp" ? "走公众号后台的 appmsg 接口，每页 5 篇，账号有频率限制。" : ""}`, `The ${NOUN[pid] || "posts"} an account published, newest first, pages with cursor.${pid === "bilibili" ? " order: pubdate (newest) or click (views)." : ""}${pid === "weixin_mp" ? " Uses the backstage appmsg endpoint, 5 per page, rate limited per account." : ""}`) },
  "GET /api/v1/{platform}/feed": { name: Z("推荐流", "Feed"), cap: "get_feed", desc: (pid) => Z(`登录账号自己的${pid === "youtube" ? "首页" : "推荐"}信息流，带 cursor 翻页。`, `The signed-in account's ${pid === "youtube" ? "home" : "recommendation"} feed, pages with cursor.`) },
  "GET /api/v1/{platform}/trending": { name: Z("热榜", "Trending"), cap: "get_trending", desc: (pid) => ({ bilibili: Z("综合热门视频，data.kind=posts，带 cursor 翻页。", "Popular videos, data.kind=posts, pages with cursor."), youtube: Z("Trending 页的视频，data.kind=posts，带 cursor 翻页。", "Videos from the Trending page, data.kind=posts, pages with cursor."), douyin: Z("抖音热搜话题，data.kind=topics，每条有 rank、title、heat（热度值）、url 和\"新 / 热 / 爆\"标签。", "Hot search topics, data.kind=topics, each with rank, title, heat, url and a label."), x: Z("趋势话题，data.kind=topics，heat 从\"12.3K posts\"这类描述解析。", "Trends, data.kind=topics; heat is parsed from descriptions like \"12.3K posts\"."), xiaohongshu: Z("网页版没有公开热榜，这里给的是搜索框的\"猜你想搜\"，个性化推荐，data.kind=topics。", "The website has no public trending list; this is the search box's personalised suggestions, data.kind=topics.") }[pid] || Z("热门列表。", "Trending list.")) },
  "POST /api/v1/{platform}/posts/{post_id}/download": { name: Z("下载媒体", "Download media"), cap: "download", desc: (pid) => Z(`把这条${NOUN[pid] || "帖子"}的媒体下到 data/downloads/${pid}/{作者}/。${DL_DESC[pid] || ""}默认立即返回任务，wait: true 阻塞到完成；media_index 只下某一个媒体。`, `Downloads the post's media into data/downloads/${pid}/{author}/. ${DL_DESC[pid] ? DL_DESC[pid] + " " : ""}Returns the task at once; wait: true blocks until done; media_index downloads a single item.`) },
  "POST /api/v1/{platform}/collect": { name: Z("连续拉取", "Collect"), cap: "list", desc: (pid, caps) => { const acts = [...LIST_CAPS].filter((c) => caps.has(c) && !UNVERIFIED[pid]?.[c]).map((c) => `${c}${Z("（", " (")}${CAP_COLS.find((x) => x[0] === c)?.[1]}${Z("）", ")")}`).join(Z("、", ", ")); return Z(`后台连续翻页，直到 limit 条、站点没有更多或 max_pages。${pid} 可用的列表动作：${acts}。params 是该动作的参数，结果里有 items、pages、complete、stopped_by。`, `Pages in the background until limit items, the end of the list or max_pages. List actions for ${pid}: ${acts}. params are that action's parameters; the result carries items, pages, complete and stopped_by.`); } },
  "POST /api/v1/{platform}/resume": { name: Z("恢复队列", "Resume queue"), cap: null, desc: Z("队列因验证码或限流暂停后，在浏览器里处理完，调这个恢复。", "After a captcha or rate limit paused the queue, handle it in the browser and call this to resume.") },
  "GET /api/v1/{platform}/capabilities": { name: Z("平台能力", "Capabilities"), cap: null, desc: Z("这个平台支持的动作、执行方式（call 在已开页面里发接口，navigate 新开页面）和超时。", "The platform's actions, how each runs (call = request inside an open tab, navigate = open a page) and timeouts.") },
  "GET /api/v1/tasks": { name: Z("任务列表", "Task list"), desc: Z("最近的任务，可按 platform、status、action（collect、download 等）筛选。结果里不带 items 和 raw（条数在 result.item_count），要完整结果加 full=true，或用 GET /tasks/{id} 取单个任务。", "Recent tasks; filter by platform, status or action (collect, download …). Results come without items and raw (their count is in result.item_count); add full=true for everything, or GET /tasks/{id} for one task.") },
  "GET /api/v1/tasks/{task_id}": { name: Z("任务详情", "Task detail"), desc: Z("任务状态、参数、结果和错误。下载和连续拉取的进度也在 result 里。", "Status, params, result and error of a task. Download and collect progress live in result.") },
  "POST /api/v1/tasks/{task_id}/cancel": { name: Z("取消任务", "Cancel task"), desc: Z("取消排队或执行中的任务，下载和连续拉取都可以。", "Cancels a queued or running task, downloads and collects included.") },
  "GET /api/v1/downloads": { name: Z("下载任务列表", "Download tasks"), desc: Z("最近的下载任务，每个文件的进度、路径和错误。", "Recent download tasks with per-file progress, path and error.") },
  "GET /api/v1/collects": { name: Z("连续拉取任务列表", "Collect tasks"), desc: Z("最近的连续拉取任务：条数、页数、结束原因。拉到的条目不在列表里，要的话加 full=true 或用 GET /tasks/{id}。", "Recent collect tasks: item count, pages, why they stopped. The collected items are left out; add full=true or use GET /tasks/{id}.") },
  "GET /health": { name: Z("健康检查", "Health"), desc: Z("后端活着就返回 ok 和版本号。", "Returns ok and the version while the backend is alive.") },
  "GET /api/v1/status": { name: Z("整体状态", "Status"), desc: Z("后端版本、扩展连接、各平台登录状态和标签页、每个队列的排队、暂停、页面加载配额用量。", "Backend version, extension connection, per-platform login state and tabs, each queue's backlog, pauses and page-load budget.") },
  "GET /api/v1/platforms": { name: Z("平台列表", "Platforms"), desc: Z("所有平台：id、名称、登录地址和提示、域名、风险等级、限速、能力。", "Every platform: id, name, login url and hint, domains, risk level, rate limit, capabilities.") },
  "GET /api/v1/resolve": { name: Z("识别链接", "Resolve link"), desc: Z("把粘进来的链接或 id 变成 platform、kind（post / user / keyword / short_link）和 id，小红书链接会带出 xsec_token。控制台顶部的输入框就是它。", "Turns a pasted link or id into platform, kind (post / user / keyword / short_link) and id; Xiaohongshu links also yield xsec_token. The console's top input uses it.") },
  "GET /api/v1/storage": { name: Z("存储占用", "Storage usage"), desc: Z("数据库大小、各表的条数和大约字节数、最早一条的时间，下载 / 录制 / 临时分片 / 日志目录的大小，以及保留策略（天，0 表示一直保留）。", "Database size; rows, approximate bytes and oldest entry per table; size of the downloads, raw, uploads and logs directories; and the retention policy in days (0 keeps forever).") },
  "POST /api/v1/export/xlsx": { name: Z("导出 Excel", "Export Excel"), desc: Z("把 rows（每行一个对象，键作表头）生成 .xlsx。字符串（包括 id）存成文本、数字存成数字，十几位的数字 id 在 Excel 里不会被改成科学计数法。", "Turns rows (one object per row, keys as the header) into an .xlsx. Strings, ids included, stay text and numbers stay numbers, so long numeric ids keep every digit in Excel.") },
  "POST /api/v1/storage/prune": { name: Z("清理旧数据", "Prune old data"), desc: Z("不带参数按保留策略清理；older_than_days 指定 {目标: 天数}，0 表示该目标全部删除。目标：tasks（只删已结束的）、health、risk_events、queries、snapshots、items、raw、uploads。下载的媒体永远不会被删。", "With no body, prunes by the retention policy; older_than_days sets {target: days}, where 0 deletes everything in that target. Targets: tasks (finished only), health, risk_events, queries, snapshots, items, raw, uploads. Downloaded media is never deleted.") },
  "GET /api/v1/items": { name: Z("本地缓存", "Local cache"), desc: Z("查询过的帖子、用户、评论（kind）都存在本地 SQLite，按最近更新排序，可按平台筛选。", "Every queried post, user and comment (kind) is stored in local SQLite; sorted by last update, filterable by platform.") },
  "GET /api/v1/items/{kind}/{platform}/{item_id}": { name: Z("缓存里的一条", "One cached item"), desc: Z("按类型、平台、id 取缓存里的一条记录。", "One cached record by kind, platform and id.") },
  "GET /api/v1/mcp/tools": { name: Z("MCP 工具列表", "MCP tools"), desc: Z("MCP server 暴露的 tool 和 resource，本页 MCP 部分的数据来源。", "The tools and resources the MCP server exposes; the source of this page's MCP section.") },
  "GET /api/v1/tasks/cookies": { name: Z("站点 cookie 名", "Site cookie names"), dev: true, desc: Z("浏览器为某个站点持有的 cookie 名和域（不含值），用来挑登录标记。", "Cookie names and domains the browser holds for a site (no values), for picking a login marker.") },
  "POST /api/v1/tasks/echo": { name: Z("扩展回声", "Extension echo"), dev: true, desc: Z("经扩展的 background 走一圈，验证后端和扩展的链路。", "Round trip through the extension's background; verifies the backend–extension link.") },
  "POST /api/v1/{platform}/echo": { name: Z("页面回声", "Page echo"), dev: true, cap: null, desc: Z("在该平台的一个标签页里执行 echo，验证页面级路由。", "Runs echo inside one of the platform's tabs; verifies page-level routing.") },
  "POST /api/v1/{platform}/record": { name: Z("录制模式", "Recording mode"), dev: true, cap: null, desc: Z("打开后，该平台标签页里的接口响应都会存到 data/raw/，用来采样和排查。", "While on, API responses in the platform's tabs are saved to data/raw/ for sampling and debugging.") },
  "GET /api/v1/{platform}/raw": { name: Z("原始响应", "Raw responses"), dev: true, cap: null, desc: Z("录制模式存下的原始响应清单，按日期。", "Raw responses saved by recording mode, by date.") },
  "POST /api/v1/{platform}/run": { name: Z("执行任意动作", "Run any action"), dev: true, cap: null, desc: Z("直接跑该平台声明的能力或通用页面动作（fetch、wait_capture、read_global、navigate 等），raw: true 返回原始响应。采样脚本用的就是它。", "Runs any declared capability or generic page action (fetch, wait_capture, read_global, navigate …); raw: true returns the raw response. The sampling scripts use it.") },
};
const MCP_ZH = ZH ? { status: "整体状态", list_platforms: "平台列表和登录状态，先调它", get_capabilities: "某平台的能力", resume: "恢复暂停的队列", get_task: "查任务", search: "搜索内容或用户", get_post: "帖子详情", get_comments: "评论", get_replies: "评论的回复", get_user: "用户资料", get_user_posts: "用户的帖子", get_feed: "推荐流", get_trending: "热榜", collect: "连续拉取多页", download: "下载媒体", list_downloads: "下载任务列表" } : { status: "Overall status", list_platforms: "Platforms and login state; call first", get_capabilities: "A platform's capabilities", resume: "Resume a paused queue", get_task: "Look up a task", search: "Search posts or users", get_post: "Post detail", get_comments: "Comments", get_replies: "Replies", get_user: "Profile", get_user_posts: "User posts", get_feed: "Feed", get_trending: "Trending", collect: "Collect several pages", download: "Download media", list_downloads: "Download tasks" };
const LIST_CAPS = new Set(["search_posts", "search_users", "get_comments", "get_replies", "get_user_posts", "get_feed", "get_trending"]);

function apiPlatform() { return $("api-platform").value || S.platforms[0]?.id || "bilibili"; }
function capsOf(pid) { return new Set((plat(pid)?.capabilities || []).map((c) => c.action)); }
function supports(pid, cap) {
  if (cap == null) return true;
  const caps = capsOf(pid);
  if (cap === "download") return caps.has("get_post") && !NO_DOWNLOAD.has(pid);
  if (cap === "list") return [...LIST_CAPS].some((c) => caps.has(c) && !UNVERIFIED[pid]?.[c]);
  if (cap === "search") return caps.has("search_posts") || caps.has("search_users");  // one route serves both
  return caps.has(cap);
}
async function apiExamples(platform) {
  const ex = { platform, post_id: "<post_id>", comment_id: "<comment_id>", user_id: "<user_id>", task_id: "<task_id>", item_id: "<id>", kind: "posts", keyword: Z("露营", "camping"), q: "https://www.bilibili.com/video/BV1cXNW6XEeC" };
  try {
    const posts = (await api(`/items?kind=posts&platform=${platform}&limit=1`)).data;
    if (posts[0]) { ex.post_id = posts[0].id; if (posts[0].author?.id) ex.user_id = posts[0].author.id; if (posts[0].raw?.xsec_token) ex.xsec_token = posts[0].raw.xsec_token; }
    const cs = (await api(`/items?kind=comments&platform=${platform}&limit=1`)).data;
    if (cs[0]) { ex.comment_id = cs[0].id; if (cs[0].post_id) ex.post_id = cs[0].post_id; }
    const ts = (await api("/tasks?limit=1")).data; if (ts[0]) ex.task_id = ts[0].id;
  } catch {}
  return ex;
}
function schemaType(sc) { if (!sc) return ""; if (sc.type) return sc.type + (sc.enum ? ` (${sc.enum.join("|")})` : ""); if (sc.anyOf) return sc.anyOf.map(schemaType).filter((x) => x && x !== "null").join(" | "); if (sc.$ref) return sc.$ref.split("/").pop(); return ""; }
function resolveRef(ref) { return ref?.split("/").slice(1).reduce((o, k) => o?.[k], apiDoc); }
function bodySchema(op) { const sc = op.requestBody?.content?.["application/json"]?.schema; if (!sc) return null; return sc.$ref ? resolveRef(sc.$ref) : sc.anyOf ? resolveRef(sc.anyOf.find((x) => x.$ref)?.$ref) : sc; }
function exampleBody(bs) {
  const body = {};
  for (const [k, v] of Object.entries(bs.properties || {})) {
    if (k === "action") body[k] = "search_posts"; else if (k === "params") body[k] = { keyword: Z("露营", "camping") }; else if (k === "limit") body[k] = 100; else if (k === "wait") body[k] = true; else if (k === "payload") body[k] = {}; else if (k === "enabled") body[k] = true; else if (k === "xsec_token") continue;
    else if ((bs.required || []).includes(k)) body[k] = v.type === "integer" ? 1 : v.type === "boolean" ? true : `<${k}>`;
  }
  return body;
}
function curlFor(method, path, op, ex) {
  const p = path.replace(/\{(\w+)\}/g, (_, k) => ex[k] ?? `<${k}>`);
  const qs = (op.parameters || []).filter((x) => x.in === "query" && (x.required || x.name === "keyword" || (x.name === "xsec_token" && ex.xsec_token))).map((x) => `${x.name}=${encodeURIComponent(ex[x.name] ?? `<${x.name}>`)}`).join("&");
  const url = `${location.origin}${p}${qs ? "?" + qs : ""}`;
  let cmd = `curl ${method !== "get" ? "-X " + method.toUpperCase() + " " : ""}"${url}"`;
  const bs = bodySchema(op);
  if (bs) cmd += ` -H "content-type: application/json" -d '${JSON.stringify(exampleBody(bs))}'`;
  return { cmd, url };
}
function paramRows(op) {
  const rows = (op.parameters || []).filter((x) => x.name !== "platform").map((x) => [x.name, `${x.in === "path" ? "路径" : "查询"}${x.required ? "，必填" : ""} · ${schemaType(x.schema)}`]);
  const bs = bodySchema(op);
  if (bs?.properties) for (const [k, v] of Object.entries(bs.properties)) rows.push([k, `body${(bs.required || []).includes(k) ? "，必填" : ""} · ${schemaType(v)}${v.default != null ? "，默认 " + JSON.stringify(v.default) : ""}`]);
  return rows;
}
function endpointHtml(method, path, op, info, ex, pid, i) {
  const shown = esc(path).replace("{platform}", `<b>${esc(pid)}</b>`);
  const rows = paramRows(op); const { cmd, url } = curlFor(method, path, op, ex); const id = `ep-${method}-${i}`;
  const tryable = method === "get" && !url.includes("%3C") && !url.includes("<");
  const todo = typeof info.cap === "string" && UNVERIFIED[pid]?.[info.cap];
  const desc = typeof info.desc === "function" ? info.desc(pid, capsOf(pid)) : info.desc;
  return `<details class="ep" id="${id}"><summary><span class="method ${method}">${method.toUpperCase()}</span><span class="name">${esc(info.name)}</span><span class="path">${shown}</span><span class="desc">${todo ? `<span class="pill warn">待验证</span> ` : ""}${esc(desc)}</span></summary><div class="body"><div>${esc(desc)}${todo ? `<div class="sub" style="color:var(--warn)">待验证：${esc(todo)}</div>` : ""}</div>${rows.length ? `<div class="params">${rows.map(([k, t]) => `<span class="k">${esc(k)}</span><span class="ty">${esc(t)}</span><span></span>`).join("")}</div>` : ""}<div class="snippet">${esc(cmd)}<button class="btn ghost sm" data-act="copy" data-arg='${J(cmd)}'>复制</button></div>${tryable ? `<div><button class="btn sm" data-act="tryGet" data-arg='${J([id, url])}'>试一下</button></div><pre id="${id}-out" hidden></pre>` : ""}${op.description ? `<div class="en">${esc(op.description)}</div>` : ""}</div></details>`;
}
function renderMatrix() {
  const head = `<tr><th>平台</th>${CAP_COLS.map(([, n]) => `<th>${n}</th>`).join("")}</tr>`;
  const rows = S.platforms.map((p) => `<tr><td><span class="pcell${PLATFORM_NOTES[p.id] ? " has-tip" : ""}" tabindex="0">${logo(p.id)} ${esc(p.name)}${PLATFORM_NOTES[p.id] ? `<span class="tip">${esc(PLATFORM_NOTES[p.id])}</span>` : ""}</span></td>${CAP_COLS.map(([cap]) => { const todo = UNVERIFIED[p.id]?.[cap]; const ok = supports(p.id, cap); return `<td>${todo ? `<span class="todo" title="${esc(todo)}">待验证</span>` : ok ? `<span class="yes">✓</span>` : `<span class="no">–</span>`}</td>`; }).join("")}</tr>`);
  $("api-matrix").innerHTML = `<thead>${head}</thead><tbody>${rows.join("")}</tbody>`;
}
async function loadApi() {
  void loadIssues();
  try {
    if (!apiDoc) apiDoc = await (await fetch("/openapi.json")).json();
    if (!mcpDoc) mcpDoc = (await api("/mcp/tools")).data;
    $("api-base").textContent = location.origin + "/api/v1";
    const sel = $("api-platform");
    if (!sel.options.length) { sel.innerHTML = S.platforms.map((p) => `<option value="${p.id}">${esc(p.name)}</option>`).join(""); sel.value = null || S.platforms[0]?.id; sel.addEventListener("change", loadApi); }
    const pid = apiPlatform();
    renderMatrix();
    const ex = await apiExamples(pid);
    const buckets = { data: [], tasks: [], system: [], dev: [] };
    let i = 0;
    for (const [path, ops] of Object.entries(apiDoc.paths)) for (const [method, op] of Object.entries(ops)) {
      if (path.startsWith("/api/v1/internal") || path === "/") continue;
      const key = `${method.toUpperCase()} ${path}`; const info = ROUTE_INFO[key] || { name: op.summary || path, desc: op.description || "", cap: null };
      const perPlatform = path.includes("{platform}");
      if (perPlatform && !supports(pid, info.cap)) continue;
      const html = endpointHtml(method, path, op, info, ex, pid, i++);
      if (info.dev) buckets.dev.push(html);
      else if (perPlatform && info.cap != null) buckets.data.push(html);
      else if (path.includes("/tasks") || path.includes("/downloads") || path.includes("/collects")) buckets.tasks.push(html);
      else buckets.system.push(html);  // incl. per-platform housekeeping: capabilities, resume
    }
    const usable = CAP_COLS.filter(([c]) => supports(pid, c) && !UNVERIFIED[pid]?.[c]).map(([, n]) => n);
    $("api-data-note").innerHTML = PLATFORM_NOTES[pid] ? `<p>${esc(PLATFORM_NOTES[pid])}</p>` : "";
    $("api-data").innerHTML = buckets.data.length ? buckets.data.join("") : `<div class="empty">${esc(pname(pid))} 没有可用的数据接口。</div>`;
    if (usable.length) $("api-data-note").innerHTML += `<p>${esc(pname(pid))} 可用：${usable.join("、")}。路径里的 ${esc("{platform}")} 已替换成 <b>${esc(pid)}</b>，示例 id 取自该平台的缓存，能直接复制运行。</p>`;
    $("api-tasks").innerHTML = buckets.tasks.join("");
    $("api-system").innerHTML = buckets.system.join("");
    $("api-dev").innerHTML = buckets.dev.join("");
    const claudeCmd = "claude mcp add sociallens -- uv run --project <repo>/backend sociallens-mcp";
    $("mcp-cmd").innerHTML = esc(`# Claude Code 一条命令接入\n${claudeCmd}\n# 手动启动（需要后端已在跑，SOCIALLENS_URL 可改后端地址）\n${mcpDoc.command}`) + `<button class="btn ghost sm" data-act="copy" data-arg='${J(claudeCmd)}'>复制</button>`;
    const tools = mcpDoc.tools.map((t) => {
      const props = t.input_schema?.properties || {}; const req = new Set(t.input_schema?.required || []);
      const rows = Object.entries(props).map(([k, v]) => `<span class="k">${esc(k)}</span><span class="ty">${esc(schemaType(v))}${req.has(k) ? "，必填" : v.default != null ? "，默认 " + esc(JSON.stringify(v.default)) : ""}</span><span></span>`).join("");
      return `<details class="ep"><summary><span class="method">tool</span><span class="name">${esc(MCP_ZH[t.name] || t.name)}</span><span class="path">${esc(t.name)}</span><span class="desc">${esc(t.description)}</span></summary><div class="body">${rows ? `<div class="params">${rows}</div>` : `<div class="sub">无参数</div>`}<div class="en">${esc(t.description)}</div></div></details>`;
    });
    const res = [...mcpDoc.resources.map((r) => ({ u: r.uri, d: r.description })), ...mcpDoc.resource_templates.map((r) => ({ u: r.uri_template, d: r.description }))].map((r) => `<details class="ep"><summary><span class="method">resource</span><span class="name">资源</span><span class="path">${esc(r.u)}</span><span class="desc">${esc(r.d || "")}</span></summary><div class="body"><div class="en">${esc(r.d || "")}</div></div></details>`);
    $("api-mcp").innerHTML = tools.join("") + res.join("");
  } catch (e) { toast(e.message, true); }
}
on("tryGet", async (id, url) => {
  const out = $(id + "-out"); out.hidden = false; out.textContent = "请求中…";
  try { const res = await fetch(url); const body = await res.json(); out.textContent = JSON.stringify(body, null, 2).slice(0, 20000); } catch (e) { out.textContent = String(e); }
});

export function showApi() {
  $("main").innerHTML = `<div class="wrap"><div class="ph"><div><div class="eyebrow">API</div><h1>接口</h1></div><div class="stats"><a href="/docs" target="_blank">Swagger ↗</a><a href="/openapi.json" target="_blank">openapi.json ↗</a></div></div>
    <section class="panel"><div class="pth">已知问题 <span>已知不能用的和为什么；调试一个平台前先看这里</span></div><div id="issues-list" class="rows"></div></section>
    <section class="panel"><div class="pth">各平台能用什么 <span>打勾的是有真实样本和测试、在真浏览器里验证过的；"待验证"是代码已完成但还没跑通；空的是平台没有。鼠标放在平台图标上看该平台的说明</span></div><div class="tablewrap" style="overflow:visible"><table class="tbl matrix" id="api-matrix"></table></div></section>
    <section class="panel"><div class="pth">数据接口 <span class="list-tools"><span>平台</span><select id="api-platform" class="field w160"></select></span></div><div class="note" id="api-data-note"></div><div id="api-data"></div></section>
    <section class="panel"><div class="pth">任务与下载 <span>长任务立即返回 task_id，之后轮询</span></div><div id="api-tasks"></div></section>
    <section class="panel"><div class="pth">系统与工具 <span>状态、平台列表、链接识别、本地缓存</span></div><div id="api-system"></div></section>
    <section class="panel"><div class="pth">MCP <span>给 Claude Code 之类的模型客户端用，独立进程，纯 REST 薄壳</span></div><div class="note"><div class="snippet" id="mcp-cmd"></div><div class="faint" style="margin-top:8px">其他客户端的配置：<code class="mono">{"command": "uv", "args": ["run", "--project", "&lt;repo&gt;/backend", "sociallens-mcp"], "env": {"SOCIALLENS_URL": "http://127.0.0.1:17800"}}</code></div></div><div id="api-mcp"></div></section>
    <details class="panel devpanel"><summary class="pth">开发调试 <span>录制模式、原始响应、直接执行任意动作，平时用不到</span></summary><div id="api-dev"></div></details>
    <section class="panel"><div class="pth">约定</div><div class="note">
      <p>后端只监听本机 <code id="api-base" class="mono"></code>，没有鉴权，程序直接调。</p>
      <p>成功响应是 <code class="mono">{success: true, data, cursor?, task_id?}</code>，失败是 <code class="mono">{success: false, error: {code, message}}</code>。列表类的 <code class="mono">data</code> 是 <code class="mono">{items, total, kind?}</code>，翻页把顶层 <code class="mono">cursor</code> 原样传回去；cursor 绑定一个浏览器标签页，闲置几分钟后过期（cursor_expired），从第一页重来即可。</p>
      <p>错误码：<code class="mono">not_logged_in</code> 未登录，<code class="mono">extension_offline</code> 扩展没连上，<code class="mono">captcha_required</code> 站点要求验证，队列暂停，<code class="mono">rate_limited</code> 被限流，<code class="mono">cursor_expired</code> 游标过期，<code class="mono">timeout</code> 页面没在时限内给出数据，<code class="mono">unsupported</code> 该平台没有这个动作，<code class="mono">not_found</code> 对象不存在。</p>
    </div></section></div>`;
  loadApi();
}
