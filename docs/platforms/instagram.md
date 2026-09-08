# Instagram 平台笔记

平台标识：`instagram`
站点：https://www.instagram.com
风险等级：low / medium / high
默认策略：navigate / call
限速：请求间隔 N 秒，随机延迟 ±M 秒，每分钟上限 K
登录态检测：cookie `sessionid`（instagram.com）

## 能力清单

编码前先填这张表。状态：planned、recording、done、unsupported。

| action | 状态 | 策略 | 说明 |
|---|---|---|---|
| search_posts | done | navigate | 关键词搜索页 /explore/search/keyword/?q= 的结果网格 |
| search_users | done | navigate | 站内搜索框（topsearch）的账号结果 |
| get_post | done | navigate | 帖子页 /p/{shortcode}/ 或 /reel/{shortcode}/ |
| get_comments | done | navigate | 帖子页的评论列表，滚动翻页 |
| get_replies | done | navigate | 评论下的子评论，页面里点「查看回复」 |
| get_user | done | navigate | 主页 /{username}/ |
| get_user_posts | done | navigate | 主页帖子网格，滚动翻页 |
| get_feed | done | navigate | 首页时间线 |
| get_trending | done | navigate | /explore/ 推荐网格 |
| download | done | | 图片 / 视频直链（CDN 地址带签名，有时效；视频 10.9MB 验证通过，通用下载流程） |

原则：所有动作都只打开站点页面、捕获站点自己发出的请求，后端和扩展都不主动构造接口调用（不模拟签名、不自己拼 API），这样站点看到的流量和用户手动浏览一致。翻页靠滚动页面触发站点自己的下一页请求。 Instagram 对高频翻页和搜索最敏感，整页配额压到 10 分钟 10 次，连续拉取默认页数不宜超过 5。

## 接口映射

原则：全部 navigate，扩展只打开页面并捕获站点自己发的 GraphQL 请求。所有查询都 POST 到 `/graphql/query` 或 `/api/graphql`，URL 无法区分，页面动作用 `url ## /响应字段/` 按响应内容匹配（`fb_api_req_friendly_name` 会改名，不用）。翻页 cursor 里带 `_tab`，续页在同一标签页里滚动。

### get_feed

- 触发方式：打开 `https://www.instagram.com/`，首页时间线由站点请求；滚动续页。
- 平台接口：`POST /graphql/query`（PolarisFeedTimelineRootV2Query）→ `data.xdt_api__v1__feed__timeline__connection{edges[{node{media}}],page_info}`。一页里混着推荐单元，帖子可能只有几条。
- 样本文件：`get_feed.json`

### get_user / get_user_posts

- 触发方式：打开 `https://www.instagram.com/{username}/`。
- 平台接口：资料 `POST /api/graphql` → `data.user{pk,username,full_name,biography,biography_with_entities,follower_count,following_count,media_count,profile_pic_url,hd_profile_pic_url_info,is_verified,is_private,category,external_url,bio_links}`（按 `biography_with_entities` 字段匹配）；帖子 `POST /graphql/query` → `data.xdt_api__v1__feed__user_timeline_graphql_connection{edges[{node(media)}],page_info{end_cursor,has_next_page}}`，滚动续页。
- 样本文件：`get_user.json`、`get_user_posts.json`

### get_post

- 触发方式：打开 `https://www.instagram.com/p/{code}/`（或 /reel/）。
- 平台接口：页面内嵌 `<script type="application/json">`（Relay preloader，`adp_PolarisPostRootQueryRelayPreloader_…`）→ 深处 `result.data.xdt_api__v1__media__shortcode__web_info.items[0]`。页面动作把整块文本交给后端，后端按字段名递归查找。
- 样本文件：`get_post.json`（{ssr, text, href}）
- 字段映射（media）：pk → id；code → raw.code 与 url；caption.text → content；user → author；taken_at → publish_time；like_count / comment_count / play_count；image_versions2.candidates[0].url → cover；video_versions[0].url → 视频；carousel_media[] → 多图；media_type 2 或 product_type clips → video。

### get_comments

- 触发方式：帖子页内嵌块 `adp_PolarisPostCommentsContainerQueryRelayPreloader_…` → `data.xdt_api__v1__media__media_id__comments__connection{edges[{node{pk,text,created_at,comment_like_count,user,child_comment_count,parent_comment_id}}],page_info{end_cursor,has_next_page}}`，首页 15 条。
- 续页：滚动评论栏（帖子里最高的可滚动容器，类名是哈希，页面动作按布局找并打上 data-sociallens-scroll 标记）触发站点请求同字段的下一页；每页 15 条，验证到第三页。注意只能滚评论栏，同时滚窗口会把评论栏推出视口，懒加载就不触发（scroll_capture 已改为指定容器时不滚窗口）。
- 样本文件：`get_comments.json`

### get_replies

- 触发方式：在评论正文旁点"查看所有 N 条回复"，站点请求子评论。页面动作用内嵌块里的评论正文定位控件。
- 平台接口：`POST /api/graphql` → `data.xdt_api__v1__media__media_id__comments__parent_comment_id__child_comments__connection{edges[{node}],page_info}`。
- 样本文件：`get_replies.json`

### search_posts

- 触发方式：打开 `https://www.instagram.com/explore/search/keyword/?q={kw}`。
- 平台接口：`POST /api/graphql` → `data.xdt_fbsearch__top_serp_graphql{edges[{node{__typename:XDTTopSerpMediaGridUnit,items[media]}}],page_info{end_cursor,has_next_page}}`，滚动续页。
- 样本文件：`search_posts.json`

### search_users

- 触发方式：首页点侧栏"搜索"打开搜索面板，在输入框里输入关键词，站点边输边查。没有翻页：网页版的关键词搜索页只有帖子网格，没有"账户"标签，账号结果只有面板这一批（站点本身就不提供更多）。
- 平台接口：`POST /api/graphql` → `data.xdt_api__v1__fbsearch__topsearch_connection{users[{user{pk,username,full_name,profile_pic_url,is_verified,search_social_context}}],hashtags[],places[]}`。
- 样本文件：`search_users.json`

### get_trending

- 触发方式：打开 `https://www.instagram.com/explore/`。
- 平台接口：`GET /api/v1/discover/web/explore_grid/?…` → `{sectional_items[…{media}], next_max_id, more_available}`，约 1MB 一页；parser 递归收集带 code 的 media。
- 样本文件：`get_trending.json`

## 下载

- 媒体地址从哪个字段取。
- 必需请求头。
- 是否加密、是否音视频分离。

## 变更记录

| 日期 | 变化 |
|---|---|
| 2026-09-08 | 九个动作实现并验证，评论翻页到第三页 |
