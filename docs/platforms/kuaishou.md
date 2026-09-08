# 快手 平台笔记

平台标识：`kuaishou`
站点：`https://www.kuaishou.com`。旧 UI 页面用 `POST /graphql`（靠请求体 `operationName` 区分），新 UI 页面用 `POST /rest/v/...`，详见实测
风险等级：medium
默认策略：navigate（站点自己发请求，扩展捕获响应或读服务端渲染状态，滚动翻页）
限速：请求间隔 4 秒，随机延迟 ±2 秒，每分钟上限 10
登录态检测：cookie `userId`（会话 cookie 名会轮换，`userId` 只在登录后出现）。登录地址 `https://www.kuaishou.com`，快手 App 扫码。

## 能力清单

| action | 状态 | 策略 | 说明 |
|---|---|---|---|
| search_posts | done | navigate | 搜索视频 `/search/video?searchKey=`，捕获 `/rest/v/search/feed`，滚动翻页 |
| search_users | done | navigate | 搜索用户：没有独立路由（`/search/author` 会被当成关键词），用视频搜索页顺带发出的 `/rest/v/search/user` |
| get_post | done | navigate | 视频详情 `/short-video/{photoId}`，读 `__APOLLO_STATE__` |
| get_comments | done | navigate | 评论 GraphQL `commentListQuery`（新字段 `rootCommentsV2` / `pcursorV2`），滚动翻页 |
| get_user | done | navigate | 用户资料 `/profile/{userId}`，读 `INIT_STATE` |
| get_user_posts | done | navigate | 用户作品，捕获 `/rest/v/profile/feed`，滚动翻页 |
| get_feed | done | navigate | 首页精彩流 GraphQL `brilliantDataQuery`，滚动翻页 |
| download | planned | 后端直下 | `photoUrl` / `mainMvUrls`，需带 Referer |

## 实测（2026-09-07）

快手网页版有新旧两套 UI 并存：

- 旧 UI（首页 `/?isHome=1`、视频页 `/short-video/{id}`）：接口是 `POST /graphql`，靠请求体 `operationName` 区分；页面服务端渲染到 `window.__APOLLO_STATE__`。
- 新 UI（搜索 `/search/video?searchKey=`、主页 `/profile/{id}`）：接口是 `POST /rest/v/...`，页面服务端渲染到 `window.INIT_STATE`（键名是经过位移混淆的请求路径，按值里的字段找）。
- 登录态：cookie `userId` 存在即已登录（会话 cookie 名会轮换，如 `kuaishou.server.webday7_st`）。搜索、主页、视频页匿名也能看，评论需登录。

| action | 数据来源 | 备注 |
|---|---|---|
| search_posts | `POST /rest/v/search/feed` `{keyword, page:"search", pcursor}` → `feeds[]{photo, author, tags}`，`pcursor` | 页面加载即请求，滚动翻页 |
| search_users | `POST /rest/v/search/user` `{keyword, pcursor}` → `users[]{user_id, user_name, headurl, user_text, verified}` | 搜索视频页也会顺带请求 |
| get_post | `window.__APOLLO_STATE__.defaultClient` 里 `VisionVideoDetailPhoto:{id}`、`VisionVideoDetailAuthor:{uid}`、`...tags.N` | 无 XHR |
| get_comments | GraphQL `commentListQuery` → `visionCommentList{rootComments[], pcursor, commentCount}` | 视频页加载即请求；样本含 14 条评论，REST 含翻页已验证 |
| get_user | `window.INIT_STATE` 里含 `userProfile{profile{user_id,user_name,headurl,user_text}, ownerCount{fan,follow,like,photo_public}, userDefineId, gender}` 的条目 | 无 XHR |
| get_user_posts | `POST /rest/v/profile/feed` `{user_id, pcursor, page:"profile"}` → `feeds[]` | 滚动翻页 |
| get_feed | GraphQL `brilliantDataQuery` → `brilliantData{feeds[], pcursor}` | 首页"精彩"流；`likeCount` 是 "46.4万" 这种字符串，用 `realLikeCount` |

`photo` 字段：`id, caption, timestamp(毫秒), duration(毫秒), likeCount/realLikeCount, viewCount, commentCount, collectCount, coverUrl, photoUrl` 或 `photoUrls[{url}]`（新 UI），`width/height`。视频地址直链 mp4，下载带 Referer。

## 通用能力变更

为快手加了两项通用能力，其它平台也能用：

- 拦截层记录请求体前 4 KB（`request_body`）。
- `wait_capture` / `scroll_capture` 的 pattern 支持 `"url模式 @@ 请求体模式"`，两边各自可用子串或 `/正则/`。


- 子评论：`commentListQuery` 返回的 rootComments 没有任何 subComment 字段，网页版看不到楼中楼，`get_replies` 不提供。热榜：没找到公开入口。

## 变更记录

| 日期 | 变化 |
|---|---|
| 2026-09-07 | 初稿，能力清单 |
| 2026-09-07 | 七个动作全部有真实样本和 parser 测试，REST 路由含翻页经真浏览器验证；发现新旧 UI 并存（REST + INIT_STATE / GraphQL + __APOLLO_STATE__） |
