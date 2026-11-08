// i18n: the console is written in Chinese; English is a translation layer over the rendered DOM
// (moved verbatim from the single-file console; new strings are appended in EN_EXTRA below).
export const LANG = (() => { try { const v = localStorage.getItem("sl_lang"); if (v === "zh" || v === "en") return v; } catch {} return /^zh/i.test(navigator.language || "") ? "zh" : "en"; })();
export const ZH = LANG === "zh";
export const Z = (zh, en) => (ZH ? zh : en);
export function setLang(l) { try { localStorage.setItem("sl_lang", l); } catch {} location.reload(); }
export const EN = {
  "SocialLens 控制台": "SocialLens Console", "概览": "Overview", "查询": "Query", "多平台搜索": "Multi-search", "类型": "Type", "全选": "All", "清空": "None", "同时搜索": "Search all", "同时搜索中…": "Searching…",
  "各平台各自限速和页面配额，一次搜索每个平台只算一次页面加载；某个平台出错不影响其他。": "Each platform keeps its own rate limit and page budget; one search costs each platform one page load, and one platform failing does not affect the others.",
  "选几个平台，输入关键词，同时搜。": "Pick a few platforms, type a keyword, search them all at once.", "在查询页翻页 →": "Page on in Query →", "多平台搜索": "Multi-search", "先选至少一个平台": "Pick at least one platform first", "至少填一个关键词": "Type a keyword first", "连续拉取": "Collect", "下载": "Download", "任务": "Tasks", "缓存": "Cache", "接口": "API", "连接中…": "Connecting…",
  "关键词、帖子或用户链接、id，回车直达": "Keyword, post / user link or id — Enter to go", "最近任务": "Recent tasks", "最近 20 条，15 秒刷新": "Last 20, refreshed every 15 s",
  "平台": "Platform", "动作": "Action", "关键词": "Keyword", "帖子 id / 用户 id": "Post id / user id", "评论 id": "Comment id", "小红书链接里的 xsec_token": "xsec_token from the Xiaohongshu link", "排序": "Order", "条数": "Count", "一页": "One page", "连续到": "Up to", "条": "items", "下一页": "Next page", "← 返回": "← Back", "还没有结果": "No results yet", "导出 JSON": "Export JSON", "导出 CSV": "Export CSV",
  "选平台和动作，或直接在上面粘一条链接。": "Pick a platform and an action, or paste a link above.", "连续拉取任务": "Collect tasks", "每 2 秒刷新进行中的": "running ones refresh every 2 s", "刷新": "Refresh", "帖子 id 或链接": "Post id or link", "全部平台": "All platforms", "全部状态": "All statuses", "显示调试动作": "Show debug actions", "加载中…": "Loading…", "加载更多": "Load more",
  "各平台能用什么": "What each platform supports", "打勾的是有真实样本和测试、在真浏览器里验证过的；": "A check means recorded samples, tests and a real-browser run; ", "待验证": "unverified", "是代码已完成但还没跑通；空的是平台没有。鼠标放在平台图标上看该平台的说明": " means the code exists but has not run through yet; a dash means the platform has no such thing. Hover a platform icon for its notes",
  "任务与下载": "Tasks and downloads", "长任务立即返回 task_id，之后轮询": "long tasks return a task_id at once; poll it afterwards", "系统与工具": "System and tools", "状态、平台列表、链接识别、本地缓存": "status, platforms, link resolution, local cache", "数据接口": "Data endpoints", "开发调试": "Debugging", "录制模式、原始响应、直接执行任意动作，平时用不到": "recording mode, raw responses, running any action directly; not needed day to day", "给 Claude Code 之类的模型客户端用，独立进程，纯 REST 薄壳": "for model clients such as Claude Code; a separate process, a thin shell over REST", "其他客户端的配置：": "Config for other clients:",
  "约定": "Conventions", "后端只监听本机": "The backend listens on localhost only", "，没有鉴权，程序直接调。": "; there is no auth, call it directly.", "成功响应是": "A success response is", "，失败是": ", a failure is", "。列表类的": ". For lists,", "是": "is", "，翻页把顶层": "; to page, send the top-level", "原样传回去；cursor 绑定一个浏览器标签页，闲置几分钟后过期（cursor_expired），从第一页重来即可。": "back as is; a cursor is bound to a browser tab and expires after a few idle minutes (cursor_expired) — start again from page one.",
  "错误码：": "Error codes:", "未登录，": "not signed in, ", "扩展没连上，": "extension not connected, ", "站点要求验证，队列暂停，": "the site wants a captcha and the queue is paused, ", "被限流，": "rate limited, ", "游标过期，": "cursor expired, ", "页面没在时限内给出数据，": "the page gave no data in time, ", "该平台没有这个动作，": "the platform has no such action, ", "对象不存在。": "not found.",
  "帖子": "Posts", "用户": "Users", "评论": "Comments", "查询过的帖子、用户、评论都会存在本地 SQLite，这里按最近更新排序。": "Everything queried is kept in local SQLite; sorted by last update.", "关闭": "Close",
  "搜索内容": "Search posts", "搜索用户": "Search users", "帖子详情": "Post detail", "评论的回复": "Replies", "评论回复": "Replies", "用户资料": "User profile", "用户的帖子": "User posts", "用户帖子": "User posts", "推荐流": "Feed", "热榜": "Trending",
  "综合": "Relevance", "播放": "Views", "最新": "Newest", "热门": "Hot", "时间": "Time", "相关": "Relevant", "最高": "Top", "最佳": "Best", "回答": "Answers", "文章": "Articles",
  "系统": "System", "的短链接暂时不能直接解析，请打开后复制完整地址": " short links cannot be resolved here yet; open it and copy the full address",
  "扩展已连接": "extension connected", "扩展未连接": "extension not connected", "后端不可达": "backend unreachable", "扩展没有连上后端：在 chrome://extensions 加载 extension/dist，或点扩展图标里的": "The extension is not connected: load extension/dist at chrome://extensions, or use", "重连": "Reconnect", "恢复": "Resume",
  "风控事件": "Risk-control hits", "只记录，不干预": "recorded, nothing adapts", "每次遇到验证码或限流时记录之前 10 / 60 分钟的页面加载、任务和调用来源，只记录不干预，用来摸各站的真实阈值。": "Each captcha or rate limit is logged with the page loads, tasks and callers of the previous 10 / 60 minutes; nothing adapts to it. That is how the real thresholds of each site get learned.", "还没有风控事件": "No risk-control hits yet", "健康检查": "health check", "多平台搜索中": "multi-search", "连续拉取中": "collecting", "健康检查中": "health check", "上次命中": "previous hit",
  "历史": "History", "查询历史": "Query history", "每次列表查询都记下返回了哪些条目；指标每次变化存一份快照": "every list query records the items it returned; metrics are snapshotted on each change", "关键词 / id": "keyword / id", "还没有查询记录": "No queries yet", "打开结果": "Open results", "当时": "then", "现在": "now", "指标变化": "Metric history", "只看过一次，还没有变化记录": "Seen once; no changes recorded yet",
  "已知问题": "Known issues", "已知不能用的和为什么；调试一个平台前先看这里": "what is known not to work and why; read before debugging a platform", "未解决": "open", "待验证": "unverified", "站点限制": "site limit", "有意为之": "by design", "扩展": "extension", "通用": "general", "自": "since",
  "Chrome 可能卡住了": "Chrome looks stuck", "完全退出 Chrome（包括托盘）再重开。": "Quit Chrome completely (tray too) and reopen it.", "多平台搜索": "multi-search", "连续拉取": "collect", "接口调用": "API call",
  "平台探测": "Probes", "现在检查": "Check now", "检查中…": "Checking…", "还没检查过": "never run", "异常": "Broken", "受阻": "Blocked", "探测失败": "Probe failed", "探测正常": "probe ok", "探测异常": "probe failed", "探测受阻": "probe blocked", "探测": "probe", "每个平台各跑一次最便宜的读取（热榜或首页流），每个平台算一次页面加载。": "Runs each platform's cheapest read (trending or home feed); one page load per platform.",
  "未登录": "Not signed in", "配额等待": "Waiting for budget", "执行中": "Running", "仅后台": "Backstage only", "空闲": "Idle", "去登录 ↗": "Sign in ↗", "分钟": "min", "还没有任务": "No tasks yet", "还没有下载": "No downloads yet", "已恢复队列": "Queue resumed", "打开页面": "Open page", "页": "pages", "续页": "next page", "完成": "Done", "失败": "Failed", "排队": "Queued", "已取消": "Cancelled",
  "用户 id / @handle / 用户名": "User id / @handle / username", "帖子 id（BV 号、笔记 id、视频 id、推文 id）": "Post id (BV id, note id, video id, tweet id)", "请求中，页面级动作要开标签页，可能要十几秒…": "Working… page actions open a tab and can take ten seconds or more",
  "，可翻页": ", more pages", "，没有更多": ", no more", "达到条数上限": "reached the item limit", "已到列表末尾": "end of list", "达到页数上限": "reached the page limit", "中途出错，保留已拿到的": "stopped on an error; pages fetched so far are kept",
  "没有数据": "No data", "话题": "Topic", "热度": "Heat", "分类": "Category", "说明": "Note", "打开 ↗": "Open ↗", "搜索": "Search", "名称": "Name", "粉丝": "Followers", "关注": "Following", "作品": "Posts", "简介": "Bio", "标题 / 内容": "Title / content", "作者": "Author", "赞": "Likes", "（无标题）": "(untitled)", "匿名": "anonymous", "回复": "Replies", "展开回复": "Show replies", "更多回复": "More replies", "没有回复": "No replies", "分享": "Shares", "收藏": "Saves", "链接": "Link", "标签": "Tags", "查看被引用的帖子 ↗": "Open the quoted post ↗", "链接：": "Links: ", "下载全部媒体": "Download all media", "作者的帖子": "Author's posts", "TA 的帖子": "Their posts", "原始 JSON": "Raw JSON", "没有数据可导出": "Nothing to export",
  "够数": "enough", "到底": "end of list", "页数上限": "page limit", "出错": "error", "取消": "Cancel", "查看结果": "View results", "还没有连续拉取任务。在「查询」里把条数切到": "No collect tasks yet. On the Query page switch the count to", "连续到 N 条": "up to N items",
  "请填写帖子 id": "Enter a post id", "已开始": "started", "这个链接不是帖子": "This link is not a post", "还没有下载任务。在查询结果或详情里点「下载」，或在上面填帖子 id、粘链接。": "No downloads yet. Click Download on a result or in the detail drawer, or enter a post id / paste a link above.",
  "状态": "Status", "参数 / 错误": "Params / error", "没有任务": "No tasks",
  "路径": "path", "查询参数": "query", "，必填": ", required", "，默认": ", default", "复制": "Copy", "试一下": "Try it", "没有可用的数据接口。": "No data endpoints available.", "无参数": "No parameters", "资源": "Resources", "已复制": "Copied", "复制失败": "Copy failed", "请求中…": "Requesting…",
  "B 站": "Bilibili", "小红书": "Xiaohongshu", "抖音": "Douyin", "快手": "Kuaishou", "公众号": "WeChat Official Accounts", "视频号": "WeChat Channels", "知乎": "Zhihu", "今日头条": "Toutiao",
  "视频": "video", "笔记": "note", "推文": "tweet", "回答 / 文章 / 问题": "answer / article / question", "动态": "post", "内容": "content",
  "打勾的是有真实样本和测试、在真浏览器里验证过的；\"待验证\"是代码已完成但还没跑通；空的是平台没有。鼠标放在平台图标上看该平台的说明": "A check means recorded samples, tests and a real-browser run; \"unverified\" means the code exists but has not run through yet; a dash means the website has no such thing. Hover a platform icon for its notes",
  "还没有连续拉取任务。在「查询」里把条数切到\"连续到 N 条\"。": "No collect tasks yet. On the Query page switch the count to \"up to N items\".",
  "打开 bilibili.com，右上角登录（扫码或账号密码）": "open bilibili.com and sign in at the top right (QR code or password)", "打开 douyin.com，右上角登录，用抖音 App 扫码": "open douyin.com, sign in at the top right by scanning with the Douyin app", "打开 instagram.com 登录（需要能访问 Instagram 的网络）": "sign in at instagram.com (needs a network that can reach Instagram)", "打开 kuaishou.com，右上角登录，用快手 App 扫码": "open kuaishou.com, sign in at the top right by scanning with the Kuaishou app", "打开 linkedin.com 登录": "sign in at linkedin.com", "打开 reddit.com 登录（不登录也能看公开内容，登录后才有个人首页流）": "sign in at reddit.com (public content works signed out; the home feed needs an account)", "打开 tiktok.com 登录（需要能访问 TikTok 的网络；不登录也能看部分公开内容）": "sign in at tiktok.com (needs a network that can reach TikTok; some public content works signed out)", "打开 toutiao.com，点右上角登录（不登录也能看公开内容）": "open toutiao.com and sign in at the top right (public content works signed out)", "打开 channels.weixin.qq.com（视频号网页版），用微信扫码登录": "open channels.weixin.qq.com and sign in by scanning with WeChat", "打开 mp.weixin.qq.com（公众号后台），用微信扫码登录你自己的公众号；公域搜索和文章列表都走这个后台": "open mp.weixin.qq.com (the Official Accounts backstage) and sign in to your own account with WeChat; search and article lists go through this backstage", "打开 x.com 登录（几乎所有页面都要求登录）": "sign in at x.com (nearly every page requires it)", "打开 xiaohongshu.com，用小红书 App 扫码登录": "open xiaohongshu.com and sign in by scanning with the Xiaohongshu app", "打开 youtube.com，用 Google 账号登录（不登录也能看公开内容）": "open youtube.com and sign in with a Google account (public content works signed out)", "打开 zhihu.com，扫码或账号登录（几乎所有内容都要求登录）": "open zhihu.com and sign in by QR code or password (nearly everything requires it)",
};
const trWord = (s) => (EN[s.trim()] != null ? s.replace(s.trim(), EN[s.trim()]) : s);
const EN_RX = [
  [/^后端 v(.+)$/, "Backend v$1"],
  [/^后端不可达：([\s\S]*)$/, "Backend unreachable: $1"],
  [/^(.+?) 队列已暂停，还剩 (\d+) 分钟。多半是风控或验证码，先在浏览器里处理，再点恢复。$/, (_, p, m) => `${trWord(p)} queue paused, ${m} min left. Usually risk control or a captcha: handle it in the browser, then resume.`],
  [/^已暂停 (\d+)m$/, "Paused $1m"],
  [/^页面 (\S+)\/(\S+) · (\d+) 分钟$/, "Pages $1/$2 · $3 min"],
  [/^(\d+) 个标签页$/, "$1 tabs"],
  [/^最近 (\d+) 个$/, "Last $1"],
  [/^(\d+) 个进行中$/, "$1 running"],
  [/^(.*?) · (\d+) 条 (\d+) 页$/, (_, a, n, p) => `${trWord(a)} · ${n} items, ${p} pages`],
  [/^(\S+) · (\d+) 个文件$/, "$1 · $2 files"],
  [/^(.*) · 续页$/, "$1 · next page"],
  [/^(\d+)\/(\d+) 个文件 · (.+)$/, "$1/$2 files · $3"],
  [/^([\d.]+) 秒 · 任务 (\w+)$/, "$1 s · task $2"],
  [/^([\d.]+) 秒$/, "$1 s"],
  [/^上次 (.+)$/, "last $1"],
  [/^自 (.+) 起 (\d+) 个页面任务的标签页始终没有加载（(.+)），扩展后台却在线。$/, (_, t, n, p) => `Since ${t}, ${n} page tasks timed out without their tab ever answering (${p}) while the extension stayed online.`],
  [/^(\d+) 条 · 第一页$/, "$1 items · first page"],
  [/^历史 #(\d+)$/, "history #$1"],
  [/^页面 (\S+) · 任务 (\S+)$/, "pages $1 · tasks $2"],
  [/^最小间隔 ([\d.]+) 秒$/, "min gap $1 s"],
  [/^上次命中 (\d+) 分钟前$/, "previous hit $1 min ago"],
  [/^最近 (\d+) 次$/, "last $1"],
  [/^(\d+) 正常$/, "$1 ok"],
  [/^(\d+) 异常$/, "$1 broken"],
  [/^(\d+) 受阻$/, "$1 blocked"],
  [/^每 ([\d.]+) 小时$/, "every $1 h"],
  [/^从 (.+) 起$/, "since $1"],
  [/^探测(正常|异常|受阻) (.+)$/, (_, st, t) => `probe ${st === "正常" ? "ok" : st === "异常" ? "failed" : "blocked"} ${t}`],
  [/^(\d+) 条(?:，共约 ([^，]+))?(，可翻页|，没有更多)?$/, (_, n, t, more) => `${n} items${t ? ` of ~${t}` : ""}${more === "，可翻页" ? ", more pages" : more === "，没有更多" ? ", no more" : ""}`],
  [/^连续拉取中：(\d+) 条，(\d+) 页，([\d.]+) 秒$/, "Collecting: $1 items, $2 pages, $3 s"],
  [/^(\d+) 条 \/ (\d+) 页 · ([\d.]+) 秒$/, "$1 items / $2 pages · $3 s"],
  [/^(\d+) 条 \/ (\d+) 页$/, "$1 items / $2 pages"],
  [/^(\d+) 条，站点总数约 (\S+)$/, "$1 items, site total ~$2"],
  [/^连续拉取 (\w+)$/, "collect $1"],
  [/^· 查询于 (.+)$/, "· queried at $1"],
  [/^已展开 (\d+) 条$/, "$1 replies shown"],
  [/^媒体 (\d+) 个$/, "$1 media"],
  [/^(\S+) \/ (\S+) 条 · (\d+) 页(?: · (.+))?$/, (_, a, b, p, r) => `${a} / ${b} items · ${p} pages${r ? ` · ${trWord(r)}` : ""}`],
  [/^下载任务 (\w+) 已开始$/, "Download task $1 started"],
  [/^待验证：([\s\S]+)$/, (_, r) => `Unverified: ${trWord(r)}`],
  [/^可用：(.+?)。路径里的 (.+?) 已替换成 (.+?)，示例 id 取自该平台的缓存，能直接复制运行。$/, (_, l, a, b) => `Available: ${l.split("、").map(trWord).join(", ")}. In paths ${a} is replaced with ${b}; example ids come from this platform's cache, so the commands run as they are.`],
  [/^无法读取平台列表：([\s\S]*)$/, "Cannot load platforms: $1"],
  [/^(路径|查询)(，必填)? · (.*)$/, (_, w, req, t) => `${w === "路径" ? "path" : "query"}${req ? ", required" : ""} · ${t}`],
  [/^body(，必填)? · (.*?)(?:，默认 (.*))?$/, (_, req, t, d) => `body${req ? ", required" : ""} · ${t}${d ? `, default ${d}` : ""}`],
  [/# Claude Code 一条命令接入/, "# Claude Code: one command"],
  [/# 手动启动（需要后端已在跑，SOCIALLENS_URL 可改后端地址）/, "# Manual start (the backend must be running; SOCIALLENS_URL overrides its address)"],
  [/^(\d+) 页$/, "$1 pages"],
  [/^(\d+) 个文件$/, "$1 files"],
  [/^(\d+) 个$/, "$1"],
  [/^(\w+)，必填$/, "$1, required"],
  [/^(\w+)，默认 (.+)$/, "$1, default $2"],
  [/^(not_logged_in: )?未登录(.+?)：(.+)$/, (_, pre, plat, hint) => `${pre || ""}Not signed in to ${trWord(plat)}: ${trWord(hint)}`],
];
const HAS_ZH = /[一-鿿]/;
function trText(text) {
  if (!HAS_ZH.test(text)) return null;
  const k = text.trim();
  if (EN[k] != null) return text.replace(k, EN[k]);
  for (const [re, rep] of EN_RX) if (re.test(k)) { const out = k.replace(re, rep); if (out !== k) return text.replace(k, out); }
  if (k.includes("·")) {
    const out = k.split(/\s*·\s*/).map((piece) => { const r = piece ? trText(piece) : null; return r == null ? piece : r; }).join(" · ");
    if (out !== k) return text.replace(k, out);
  }
  const lead = /^(\S+) (.+)$/.exec(k); // "搜索内容 露营": a known word followed by data
  if (lead && EN[lead[1]] != null) return text.replace(k, `${EN[lead[1]]} ${lead[2]}`);
  return null;
}
function translateDom(root) {
  if (ZH || !root) return;
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT);
  const texts = [];
  for (let n = walker.currentNode; n; n = walker.nextNode()) {
    if (n.nodeType === Node.TEXT_NODE) { if (n.parentElement && !["SCRIPT", "STYLE"].includes(n.parentElement.tagName)) texts.push(n); }
    else for (const a of ["placeholder", "title", "data-tip"]) { const v = n.getAttribute?.(a); if (v && HAS_ZH.test(v)) { const r = trText(v); if (r != null && r !== v) n.setAttribute(a, r); } }
  }
  for (const n of texts) { const r = trText(n.nodeValue); if (r != null && r !== n.nodeValue) n.nodeValue = r; }
}

// ---- strings added by the redesigned console -----------------------------------------------------
Object.assign(EN, {
  "数据": "Data", "收起": "Collapse", "+ 点击 多选平台": "+ click to pick several platforms", "多平台只拉一页": "Multi-platform search fetches one page",
  "关键词，或粘贴帖子 / 用户链接": "Keyword, or paste a post / user link", "用户 id / @handle / 用户名，或粘贴链接": "User id / @handle / username, or paste a link", "帖子 id（BV 号、笔记 id、视频 id、推文 id），或粘贴链接": "Post id (BV id, note id, video id, tweet id), or paste a link",
  "多平台只拉一页，避免同时撞上多个平台的风控。要翻页或连续拉取，点分组右上角的「在单平台下翻页」。": "Multi-platform search fetches one page so several sites never hit risk control at once. To page on or collect, use \"Page on this platform\" on a group.",
  "将创建连续拉取任务，在后台翻页直到够数；进度也能在「任务」页看到。": "Creates a collect task that pages in the background until it has enough; progress also shows on the Tasks page.",
  "表格": "Table", "卡片": "Cards", "表格 / 卡片（t）": "Table / cards (t)", "搜索中…": "Searching…", "连续拉取中…": "Collecting…", "选平台、填关键词，回车查询": "Pick a platform, type a keyword, press Enter",
  "也可以直接粘贴帖子或用户链接。": "You can also paste a post or user link.", "+ 点击平台可以同时搜索多个平台。": "+ click platforms to search several at once.", "在单平台下翻页 →": "Page on this platform →", "没有结果": "No results",
  "上下": "Up / down", "打开详情": "Open detail", "表格 / 卡片": "Table / cards", "主页 ↗": "Profile ↗", "图文": "Image post", "在原平台打开": "Open on the site", "展开为全宽详情页": "Expand to a full page", "收起为侧栏": "Back to the side panel", "关闭（Esc）": "Close (Esc)", "返回": "Back",
  "已补全详情": "Full detail loaded", "本次会话已缓存": "cached this session", "正在打开页面补全详情…": "Opening a page to load the full detail…", "正在补全详情…": "Loading the full detail…", "重试": "Retry", "加载完整内容": "Load full content", "TA 的主页": "Profile",
  "正文链接": "Links in the text", "媒体与下载": "Media and downloads", "没有评论": "No comments", "加载更多评论": "More comments", "获赞": "Likes received", "准备加载…": "Getting ready…", "加载 TA 的帖子": "Load their posts", "本地缓存里没有这一条。": "This one is not in the local cache.",
  "请填写 id": "Enter an id", "选中的平台都不支持这种搜索": "None of the selected platforms supports this search", "查过的查询、帖子、用户、评论都存在本地 SQLite": "Every query, post, user and comment is kept in local SQLite", "查询记录": "Queries", "最多": "Up to", "按最近更新排序": "sorted by last update", "打开结果 →": "Open results →",
  "进行中": "Running", "已完成": "Finished", "全部类型": "All types", "新建下载": "New download", "查看结果 →": "View results →", "粘贴链接会自动识别平台": "A pasted link picks the platform", "（小红书需要，链接里自带的会自动带上）": "(Xiaohongshu needs it; a pasted link carries it)",
  "没有进行中的任务。在「搜索」里把条数切到「连续到 N 条」，或在结果、详情里点「下载」。": "Nothing running. Switch the count to \"up to N items\" on Search, or click Download on a result.",
  "一切正常：扩展已连接，没有暂停的队列，没有异常的探测。": "All good: extension connected, no paused queues, no failing probes.", "去搜索": "Search here", "主题：跟随系统": "Theme: system", "主题：浅色": "Theme: light", "主题：深色": "Theme: dark", "队列": "Queue", "↩ 回复": "↩ Reply", "来源：全部缓存": "Source: whole cache", "只看某次查询抓到的": "Only what one query returned", "内容": "Content", "视频": "Video", "动态": "Post",
});
EN_RX.push(
  [/^\/(\d+) 平台已登录$/, "/$1 platforms signed in"],
  [/^同时搜索 (\d+) 个平台$/, "Search $1 platforms"],
  [/^(\d+) 条 (\d+) 页$/, "$1 items, $2 pages"],
  [/^查询于 (.+)$/, "queried at $1"],
  [/^补全失败：([\s\S]*)$/, "Could not load the detail: $1"],
  [/^列表里的内容可能不完整。(.+)补全要新开一个页面，占页面配额。$/, (_, p) => `The list item may be incomplete. Loading the full detail on ${trWord(p)} opens a page and spends the page-load budget.`],
  [/^(.+)要新开页面加载，占页面配额。$/, (_, p) => `${trWord(p)} opens a page for this and spends the page-load budget.`],
  [/^在(.+)播放 ↗$/, (_, p) => `Play on ${trWord(p)} ↗`],
  [/^从(.+)加载$/, (_, p) => `Load from ${trWord(p)}`],
  [/^在(.+)搜索 #(.+)$/, (_, p, t) => `Search ${trWord(p)} for #${t}`],
  [/^在(.+)查找用户 (.+)$/, (_, p, n) => `Find user ${n} on ${trWord(p)}`],
  [/^(\S+) 粉丝$/, "$1 followers"],
  [/^(\S+) 条评论$/, "$1 comments"],
  [/^已加载 (\d+)$/, "$1 loaded"],
  [/^下载目录 (.+)$/, "Download folder $1"],
  [/^来自 (\S+ \S+) 的(.+?)(?:「(.+)」)?，按当时的顺序$/, (_, t, act, k) => `from the ${trWord(act)}${k ? ` "${k}"` : ""} at ${t}, in its original order`],
);
export function installI18n() {
  if (ZH) return;
  document.documentElement.lang = "en";
  translateDom(document.body);
  const fix = (n) => translateDom(n.nodeType === Node.TEXT_NODE ? n.parentElement : n);
  const mo = new MutationObserver((muts) => { for (const m of muts) { if (m.type === "characterData") { const r = trText(m.target.nodeValue); if (r != null && r !== m.target.nodeValue) m.target.nodeValue = r; } else if (m.type === "attributes") translateDom(m.target); else m.addedNodes.forEach(fix); } });
  mo.observe(document.body, { childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ["placeholder", "title", "data-tip"] });
  const t = new MutationObserver(() => { const r = trText(document.title); if (r && r !== document.title) document.title = r; });
  t.observe(document.querySelector("title"), { childList: true });
}
