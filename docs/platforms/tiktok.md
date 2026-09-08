# TikTok 平台笔记

平台标识：`tiktok`
站点：https://www.tiktok.com （需要能访问 TikTok 的网络；浏览器走系统代理即可）
风险等级：high（签名与抖音同源：X-Bogus / msToken；验证码在 verify.tiktok.com）
默认策略：navigate
限速：请求间隔 4 秒，随机延迟 ±2 秒，10 分钟内最多 12 次整页加载
登录态检测：cookie `sessionid`（匿名可看部分公开内容，`loginRequired: false`）

## 能力清单

| action | 状态 | 策略 | 说明 |
|---|---|---|---|
| search_posts | done | navigate | `/search/video?q=` → 捕获 `/api/search/item/full/`，`item_list[]`（general/full 是顶部综合标签） |
| search_users | done | navigate | `/search/user?q=` → `/api/search/user/full/`，`user_list[].user_info` |
| get_post | done | navigate | 裸 id 先由后端调公开 oembed 换作者名，拼 `/@{author}/video/{id}`；冷开会先遇到 "Please wait..." 检查页，文档替换后页面动作自动重发（实测 7 秒）；SSR `<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__">` 的 `__DEFAULT_SCOPE__["webapp.video-detail"].itemInfo.itemStruct` |
| get_comments | done | navigate | 视频页点 `[data-e2e="comment-icon"]` 打开面板，面板可能停在"创作者视频"标签，要再点"评论"；列表容器 `[class*="DivCommentMain"]` 出现后才请求 `/api/comment/list/?aweme_id=`（普通 XHR）；翻页滚动该容器。实测首页 20，第二页 25 | 评论由 Web Worker 请求，页面层 fetch/XHR 钩子看不到。现实现：从页面任一带 msToken 的接口 URL 取公共参数，拼 `/api/comment/list/?aweme_id=&cursor=&count=20`，用 `window.byted_acrawler.frontierSign` 签名后 fetch。实测返回空体：签名器只给 X-Bogus，接口现在还要 X-Gnarly / X-Dynosaur。下一步：在 MAIN world 包一层 `Worker` 拦截 worker→页面的消息，直接拿评论数据 |
| get_replies | done | navigate | 面板里按评论正文定位，点"查看 N 条回复"捕获 `/api/comment/list/reply/?comment_id=`，首次 3 条；再翻页点"查看其它 N 条评论"（站点把回复的更多按钮写成"评论"） |
| get_user | done | navigate | `/@{uniqueId}` 的 `webapp.user-detail.userInfo.{user,stats}` |
| get_user_posts | done | navigate | 用户页 → `/api/post/item_list/`，`itemList[]` |
| get_feed | done | navigate | `/foryou` → `/api/recommend/item_list/` |
| get_trending | done | navigate | `/explore` → `/api/explore/item_list/`，返回视频（kind=posts） |
| download | done | yt-dlp | 视频地址绑定浏览器 cookie，后端直连 403；交给 yt-dlp（需要 curl-cffi 做浏览器伪装，已在 `download` 依赖组里），沿用系统代理。实测 1080p mp4 579 KB；偶尔撞上站点检查页会报 "Unable to extract universal data"，重试即可 |

## 变更记录

| 日期 | 变化 |
|---|---|
| 2026-09-07 | 骨架 |
| 2026-09-07 | 录样本、parser 测试、REST 验证：搜索/用户/详情/资料/用户作品/推荐流/探索 7 个通过；详情页状态 JSON(~230KB) 由页面传原文、后端解析；裸视频 id 经公开 oembed 换作者名再拼 @user 路径；冷开标签页较慢，详情类动作复用暖标签页。评论网页端不请求接口，待确认 |
| 2026-09-07 | 冷开检查页问题解决（页面动作在文档替换后重发）；评论改为页内自签名调用，被拒，待用 Worker 消息拦截 |
| 2026-09-07 | 评论三条路都试过：页面 fetch/XHR 钩子看不到（请求经 sw.js Service Worker）；页内 `frontierSign` 自签名调用返回空体（缺 X-Gnarly）；包一层 `Worker` 记录 worker 消息也没有捕获，且工作窗口里的视频页只渲染空壳（正文 398 字符，无评论面板）。能力暂时下线，页面动作和 parser 保留；下一步方向：在用户当前可见的标签页里执行，或 DOM 抓评论 |
| 2026-09-07 | 更正：视频页确实渲染，评论只是要先点开面板；之前的 Service Worker / Worker 结论是在没打开面板的标签页上得出的错误判断。评论改为点图标后捕获，待验证 |
| 2026-09-08 | 评论、回复走通：图标 + 标签两步打开面板；水合慢时等 20 秒并重试；展开助手改为遍历已捕获的所有评论页再滚动 |
| 2026-09-08 | 下载验证：yt-dlp 需 curl-cffi 伪装（否则 "Unexpected response from webpage request"），首次可能撞检查页，重试成功 |
