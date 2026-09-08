# YouTube 平台笔记

平台标识：`youtube`
站点：`https://www.youtube.com`，接口 `POST /youtubei/v1/{search|browse|next|player}`
风险等级：low
默认策略：navigate（首屏读页面全局 `ytInitialData` / `ytInitialPlayerResponse`，翻页靠滚动触发 `youtubei/v1/*`）
限速：请求间隔 2 秒，随机延迟 ±1 秒，每分钟上限 20
登录态检测：cookie `SAPISID`（域 .youtube.com）。匿名可用（`loginRequired: false`），登录后能看会员内容和个性化推荐。登录地址 `https://www.youtube.com`，Google 账号。

## 能力清单

| action | 状态 | 策略 | 说明 |
|---|---|---|---|
| search_posts | done | navigate | `/results?search_query=&sp=EgIQAQ%3D%3D`（视频过滤），首屏 `ytInitialData`，更多 `youtubei/v1/search` |
| search_users | done | navigate | `/results?search_query=&sp=EgIQAg%3D%3D`（频道过滤），`channelRenderer` |
| get_post | done | navigate | `/watch?v=`，`ytInitialPlayerResponse.videoDetails` + `microformat`，点赞数取 `ytInitialData` 里标签为「赞」的 `factoidRenderer`（备选：赞按钮 accessibilityText）；评论总数首屏没有（延迟加载），`metrics.comments` 为空，总数走 get_comments 的 `total` |
| get_comments | done | call in tab | 页面内 POST `youtubei/v1/next`，continuation 取自 `ytInitialData` 的 comment-item-section；下一页的 token 编进 cursor。滚动方式在我们的标签页里不触发评论加载，所以改为直接调接口 |
| get_streams | done | navigate | `/watch?v=` 的 `ytInitialPlayerResponse.streamingData`。`formats[]`（渐进式）虽带明文 `url`，但 2026-09 实测后端直连和页面内 fetch 都 403（缺 PO token），`adaptiveFormats[]` 只有 SABR，没有地址。下载因此走 yt-dlp（需系统代理），此动作只在 `mode=progressive` 时用 |
| get_user | done | navigate | `/@handle` 或 `/channel/UC...`，`metadata.channelMetadataRenderer` + 页头文本里的订阅数、视频数 |
| get_user_posts | done | navigate | `/@handle/videos`，首屏 `lockupViewModel` 网格，更多 `youtubei/v1/browse` |
| get_feed | done | navigate | 首页 `lockupViewModel` / `shortsLockupViewModel`，更多 `youtubei/v1/browse` |
| download | planned | 后端直下 | `streamingData` 的地址带签名且有时效，需在页面侧解出，后期再做 |

## 实测机制（2026-09-07）

- `ytInitialData` 是 renderer 树，嵌套超过 20 层（页面状态序列化的深度上限因此从 14 放到 48）。搜索结果是 `videoRenderer` / `channelRenderer`；频道视频页和首页已改用 `lockupViewModel`（`contentId`、`metadata.lockupMetadataViewModel.title.content`、`metadataRows` 里的观看数和发布时间、`contentImage.thumbnailViewModel`），短视频是 `shortsLockupViewModel`。parser 三种都认。
- 计数是本地化文本（"64,347,035次观看"、"269万位订阅者"、"1.2M views"），parser 统一转整数；发布时间只有相对文本（"1年前"），转成近似时间戳。
- 评论：`commentThreadRenderer` 或新版 `commentEntityPayload`（`commentId` 在 `properties` 下；`properties.content.content`、`author.displayName`、`toolbar.likeCountNotliked`）。`commentViewModel` 也带 `commentId` 但没有正文，要跳过。总数取 `commentsHeaderRenderer.countText`。下一页 token 只取 `continuationItems` 顶层的 `continuationItemRenderer`，回复串的 continuation 在更深层，不能混用。关闭评论的视频（comment-item-section 里只有帮助链接）返回 404 not_found。
- `youtubei/v1/*` 请求体是 JSON，带 `context` 和 `continuation`；响应里 `onResponseReceivedActions[].appendContinuationItemsAction.continuationItems[]`。

- 回复：评论线程 `commentThreadRenderer.replies.commentRepliesRenderer` 里的 continuation token（parser 放在 `raw.replies_token`），页面动作 `get_replies` 没有 token 时会翻评论列表找到该线程再取。热榜：`/feed/trending` 的 ytInitialData，与搜索页同一套 videoRenderer / lockupViewModel。

## 变更记录

| 日期 | 变化 |
|---|---|
| 2026-09-07 | 初稿 |
| 2026-09-07 | 七个动作实现并有真实样本；评论改为页面内直接调 innertube |
