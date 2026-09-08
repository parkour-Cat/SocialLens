# 抖音 平台笔记

平台标识：`douyin`
站点：`https://www.douyin.com`，接口同域 `/aweme/v1/web/...`
风险等级：high
默认策略：navigate（站点自己发请求，扩展捕获响应 / 读 SSR 数据 / 滚动翻页）
限速：请求间隔 4 秒，随机延迟 ±2 秒，每分钟上限 10
登录态检测：cookie `sessionid` 存在。不少接口匿名可用，但搜索和评论常弹登录墙。

## 能力清单

| action | 状态 | 策略 | 说明 |
|---|---|---|---|
| search_posts | done | navigate | 搜索视频，滚动翻页 |
| search_users | done | navigate | 搜索用户 |
| get_post | done | navigate | 视频详情，参数 aweme_id |
| get_comments | done | navigate | 视频评论，滚动翻页 |
| get_user | done | navigate | 用户资料，参数 sec_uid，来自流式页面数据 |
| get_user_posts | done | navigate | 用户作品，滚动翻页 |
| get_feed | done | navigate | 首页推荐，滚动翻页 |
| get_my_favorites | planned | navigate | 自己的收藏 / 点赞 |
| download | planned | 后端直下 | 无水印视频地址（`play_addr`），需带 Referer |

## 站点机制（已录制确认）

- 接口在 `www.douyin.com/aweme/v1/web/`（推荐流是 `v2/web/module/feed`），查询参数里带 `a_bogus` 和 `msToken`，由页面混淆脚本生成，不自己拼；所有动作让站点自己请求。
- 响应体大：推荐流 1.5 到 3.6 MB，搜索超过 1 MB，所以拦截层正文上限是 6 MB（后端 WebSocket 允许 16 MB）。
- 页面是流式渲染：数据以 React flight 风格记录推进 `window.__pace_f`；`<script id="RENDER_DATA">` 只含 app 配置；没有 `_ROUTER_DATA`。除用户资料外，内容都靠页面自己的 XHR。
- 风控信号：`security.douyin.com`、`verify.snssdk.com`、`/captcha/verify|get`。

## 接口映射（2026-09-07 全部录制确认）

页面结构：抖音网页版是流式渲染（`window.__pace_f` 里是 React flight 风格的记录 `"<id>:<json>"`），`<script id="RENDER_DATA">` 只含 app 配置，没有 `_ROUTER_DATA`。内容大多靠页面自己的 XHR。

### search_posts

- 入口：`/search/{keyword}?type=video`，页面加载即请求 `GET /aweme/v1/web/search/item/?keyword=&offset=&count=&cursor=`，响应可超过 1 MB。
- 字段：`data[]{type, aweme_info{aweme_id, desc, create_time, author{sec_uid,uid,nickname,avatar_thumb,follower_count}, statistics{digg_count,comment_count,share_count,collect_count}, video{play_addr{url_list,width,height,data_size}, cover, origin_cover, duration(毫秒), play_addr_265}, text_extra[{hashtag_name}], images[]}}`，`has_more`，`cursor`。
- 样本：`search_posts.json`、`search_posts_page2.json`。翻页靠滚动。

### search_users

- 入口：`/search/{keyword}?type=user`，请求 `GET /aweme/v1/web/discover/search/?search_channel=aweme_user_web`。
- 字段：`user_list[]{user_info{uid, sec_uid, nickname, unique_id, signature, avatar_thumb, follower_count, total_favorited, custom_verify}}`，`has_more`，`cursor`。
- 样本：`search_users.json`

### get_post

- 入口：`/video/{aweme_id}`，页面请求 `GET /aweme/v1/web/aweme/detail/?aweme_id=`。
- 字段：`aweme_detail{...}` 与搜索卡片的 `aweme_info` 同构。
- 样本：`get_post.json`。视频无水印地址 `video.play_addr.url_list[0]`，下载带 Referer。

### get_comments

- 入口：同视频页，页面加载即请求 `GET /aweme/v1/web/comment/list/?aweme_id=&cursor=&count=`，每页 5 到 10 条，滚动翻页。
- 字段：`comments[]{cid, text, aweme_id, create_time(秒), digg_count, user{sec_uid,uid,nickname,avatar_thumb}, reply_comment[], reply_comment_total, ip_label, is_hot}`，`has_more`，`cursor`，`total`。
- 样本：`get_comments.json`、`get_comments_page2.json`

### get_user

- 入口：`/user/{sec_uid}`。资料不走 XHR，在 `__pace_f` 流式记录里：找 `{user: {statusCode, user: {secUid, nickname, desc, avatar300Url, followerCount, followingCount, awemeCount, totalFavorited, uniqueId, ipLocation, city, ...}}}`（camelCase）。注意另有 `{user: {info: {...}}}` 是当前登录用户，不能混淆。
- 样本：`get_user.json`

### get_user_posts

- 入口：同用户页，页面请求 `GET /aweme/v1/web/aweme/post/?sec_user_id=&max_cursor=&count=`，`aweme_list[]`，`has_more`，`max_cursor`。滚动翻页。
- 样本：`get_user_posts.json`、`get_user_posts_page2.json`

### get_feed

- 入口：`/?recommend=1`，页面请求 `POST /aweme/v2/web/module/feed/`，`aweme_list[]`，`has_more`。滚动翻页。
- 样本：`get_feed.json`、`get_feed_page2.json`

- 热搜：`/hot` 页面请求 `/aweme/v1/web/hot/search/list/`，`data.word_list[]`（word、hot_value、position、label：1 新 3 热 4 独家 5 首发 8 爆），第一条 position 为空是置顶。回复：`/aweme/v1/web/comment/list/reply/?comment_id=` 带 a_bogus，只能在视频页按评论正文定位后点"展开 N 条回复"再捕获（expand.ts）；捕获到列表响应时 DOM 可能还没渲染，要轮询。 第一次展开站点只请求 3 条（count=3），之后每次"展开更多"10 条；已内联在列表里的单条回复再展开会返回空。实测 226 条回复的评论：首页 3 条，第二页 10 条。

## 变更记录

| 日期 | 变化 |
|---|---|
| 2026-09-07 | 初稿，能力清单 |
| 2026-09-07 | 七个动作实现并用登录态样本确认，parser 测试通过 |
