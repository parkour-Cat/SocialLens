# LinkedIn 平台笔记

平台标识：`linkedin`
站点：https://www.linkedin.com
风险等级：low / medium / high
默认策略：navigate / call
限速：请求间隔 N 秒，随机延迟 ±M 秒，每分钟上限 K
登录态检测：cookie `li_at`（linkedin.com）

## 能力清单

编码前先填这张表。状态：planned、recording、done、unsupported。

| action | 状态 | 策略 | 说明 |
|---|---|---|---|
| search_posts | unsupported | | 老的 /search/blended 已下线（404）；新版搜索页是 SDUI，内容结果只在 RSC 组件树里 |
| search_users | done | call | /voyager/api/graphql voyagerSearchDashClusters（PEOPLE）；queryId 哈希取自公开网页版，会随部署改；失败时退到全局联想 |
| get_post | done | call | /voyager/api/feed/updates/urn:li:activity:{id}，附带精选评论（raw.comments） |
| get_comments | done | navigate | 老版帖子页 /feed/update/{urn}/：首页评论内嵌在 `code#bpr-guid-…`，续页点「加载更多评论」捕获 socialDashCommentsBySocialDetail |
| get_replies | done | navigate | 同一页面：评论下已展示的回复在内嵌块里，更早的点「查看之前的回复」捕获 socialDashCommentsByRepliesByCursor |
| get_user | done | call | /voyager/api/identity/dash/profiles?q=memberIdentity（WebTopCardCore）；无粉丝数。非隐身模式访问会留下「谁看过我」记录 |
| get_user_posts | done | navigate | 老版动态页 /in/{vanity}/recent-activity/all/ 加载时的 feedDashProfileUpdatesByMemberShareFeed（20 条）；「显示更多结果」对非联系人返回空 |
| get_feed | done | call | /voyager/api/feed/updatesV2?q=chronFeed，按 paginationToken 翻页 |
| get_trending | unsupported | | /feed/storylines 已下线 |
| download | planned | | 图片直链；视频 progressiveStreams 直链（parser 已取）。本账号首页流里没有带媒体的帖子，未验证 |

原则：所有动作都只打开站点页面、捕获站点自己发出的请求，后端和扩展都不主动构造接口调用（不模拟签名、不自己拼 API），这样站点看到的流量和用户手动浏览一致。翻页靠滚动页面触发站点自己的下一页请求。 LinkedIn 对搜索量和批量看主页最敏感，整页配额压到 10 分钟 8 次，连续拉取默认页数不宜超过 3。

## 接口映射

### 为什么是 call 而不是 navigate

2026-09-08 录制：linkedin.com 的网页已经全部换成 React Server Components + 服务端驱动 UI（`/flagship-web/rsc-action/actions/{pagination,server-request,component}`，响应是 `application/octet-stream` 的 RSC 流）。流里只有组件树（`proto.sdui.*`），没有 activity urn、没有作者 id，DOM 里也没有任何数据属性；首页流、搜索页、个人主页都是这样。所以"只捕获站点自己的请求"在 LinkedIn 上拿不到结构化数据。

老的 voyager REST 接口对登录账号仍部分可用：在 LinkedIn 标签页里用页面 cookie 请求，带 `csrf-token: {JSESSIONID cookie 值}`、`accept: application/vnd.linkedin.normalized+json+2.1`、`x-restli-protocol-version: 2.0.0`。这和老版网页自己的请求一致，但毕竟是主动调接口，限速压到 6 秒 ±3 秒、10 分钟 8 次整页配额。

响应是 normalized JSON：`{data, included[]}`，`*字段` 是指向 included 里实体的 urn 引用。parser 用 `_Store` 按 entityUrn / urn 索引。

### get_feed

- 平台接口：`GET /voyager/api/feed/updatesV2?count=10&q=chronFeed&start=0`；续页 `&start=10&paginationToken=…`（第一页 `data.metadata.paginationToken`）。
- 样本文件：`get_feed.json`
- 字段映射：included 里的 UpdateV2：`updateMetadata.urn` → id（activity 数字）；`commentary.text.text` → content；`actor{name.text, image, navigationUrl, subDescription}` → author（公司 actor 用 MiniCompany）；`content{ImageComponent|LinkedInVideoComponent|ArticleComponent}` → media / type；`*socialDetail → *totalSocialActivityCounts{numLikes,numComments,numShares}` → metrics。没有发布时间戳（只有"3天前"文字，留在 raw.posted）。
- 已知坑：`chronFeed` 是关注对象的时间线，本账号只有 7 条；`paging.total` 可信。

### get_post

- 平台接口：`GET /voyager/api/feed/updates/urn:li:activity:{id}`；`data` 是薄的 Update，真正的 UpdateV2 在 included 里，评论实体（Comment）也在 included 里。
- 样本文件：`get_post.json`
- 字段映射：同上；Comment：`urn` `urn:li:comment:(activity:{aid},{cid})` → id；`commentV2.text`；`commenter.*miniProfile` → 作者；`createdTime`（毫秒）；`*socialDetail → counts.numLikes`。写进 post.raw.comments。

### get_user

- 平台接口：`GET /voyager/api/identity/dash/profiles?q=memberIdentity&memberIdentity={vanity}&decorationId=com.linkedin.voyager.dash.deco.identity.profile.WebTopCardCore-16`
- 样本文件：`get_user.json`
- 字段映射：included 里 publicIdentifier 等于请求 vanity 的 Profile（响应里还会带登录者自己的 Profile）：firstName + lastName → name；headline → bio；`profilePicture.displayImageReference.vectorImage{rootUrl, artifacts[]}` → avatar；`geoLocation.*geo` → raw.location。老的 `/identity/profiles/{vanity}/profileView` 返回 410。

### search_users

- 平台接口：`GET /voyager/api/graphql?variables=(start:0,origin:GLOBAL_SEARCH_HEADER,query:(keywords:{kw},flagshipSearchIntent:SEARCH_SRP,queryParameters:List((key:resultType,value:List(PEOPLE))),includeFiltersInResponse:false))&queryId=voyagerSearchDashClusters.b0928897b71bd00a5a7291755dcd64f0`
- 样本文件：`search_users.json`（联想：`search_users_typeahead.json`）
- 字段映射：included 里的 EntityResultViewModel：`title.text`、`primarySubtitle.text`（headline）、`secondarySubtitle.text`（地点）、`navigationUrl`（/in/{vanity}）。网络外的人显示为"领英会员"、navigationUrl 指向 headless 页面，parser 丢弃。`data.data.searchDashClustersByAll.metadata.totalResultCount` → total；每页 10。
- 已知坑：queryId 哈希会随部署改，改了就 404，页面动作会退到 `voyagerSearchDashTypeahead`（只有联想词，人很少）。CONTENT 结果用同一个 queryId 只返回 FeedbackCard，所以没有 search_posts。

### get_user_posts（navigate）

- 触发方式：打开 `https://www.linkedin.com/in/{vanity}/recent-activity/all/`。这个路由还是老的 Ember 应用（voyager-web），加载时自己请求。
- 平台接口：`GET /voyager/api/graphql?variables=(count:20,start:0,profileUrn:urn:li:fsd_profile:…)&queryId=voyagerFeedDashProfileUpdates.…` → `data.data.feedDashProfileUpdatesByMemberShareFeed{*elements, paging, metadata.paginationToken}`，实体在 included（dash `Update`：`entityUrn` 里带 activity urn，`actor{name.text,description,navigationUrl,image}`，`commentary.text.text`，`content{imageComponent|linkedInVideoComponent|articleComponent}`，`*socialDetail → *totalSocialActivityCounts{numLikes,numComments,numShares}`）。
- 续页：点「显示更多结果」，站点带 paginationToken 请求 `start:20`；对非联系人返回空数组（本账号看 Jensen Huang 只给 20 条）。
- 样本文件：`get_user_posts.json`
- 已知坑：老应用的 XHR 用 responseType=blob 读 JSON，页面钩子对 blob 也要解码（已改）。

### get_comments（navigate）

- 触发方式：打开 `https://www.linkedin.com/feed/update/urn:li:activity:{id}/`（老版页面）。首页评论内嵌在 `<code id="bpr-guid-…">`（含 `feedDashUpdatesByBackendUrn`），帖子的 SocialDetail.comments.*elements 是顶层评论引用（首屏 8 条，paging.total 是总数）。
- 续页：点「加载更多评论」→ `GET /voyager/api/graphql?variables=(count:10,numReplies:1,paginationToken:…,socialDetailUrn:…,sortOrder:RELEVANCE,start:10)&queryId=voyagerSocialDashComments.…` → `data.data.socialDashCommentsBySocialDetail{*elements,paging{start,count,total},metadata.paginationToken}`。
- 样本文件：`get_post_page.json`（内嵌块）、`get_comments_page2.json`
- 字段映射：dash `Comment`：`entityUrn` `urn:li:fsd_comment:(cid,urn:li:activity:aid)` → id；`commentary.text`；`commenter{title.text,subtitle.text,navigationUrl,image}` → author；`createdAt`（毫秒）；`*socialDetail → counts{numComments, reactionTypeCounts}` → raw.reply_count / likes。回复和顶层评论实体形状相同，只能靠列表引用区分。

### get_replies（navigate）

- 触发方式：同一帖子页。评论下已展示的回复来自内嵌块里该评论的 SocialDetail.comments（paging.total 是回复总数）；更早的回复点「查看之前的回复」（「N 条回复」只是展开已加载的，不发请求）。
- 平台接口：`GET /voyager/api/graphql?variables=(commentUrn:urn:li:fsd_comment:(cid,urn:li:activity:aid),count:10,cursor:…)&queryId=voyagerSocialDashComments.…` → `data.data.socialDashCommentsByRepliesByCursor{*elements, metadata{replyNextCursor, replyPreviousCursor}}`。
- 样本文件：`get_replies.json`
- 已验证：5 条回复分两页拿全。

## 下载

- 媒体地址从哪个字段取。
- 必需请求头。
- 是否加密、是否音视频分离。

## 变更记录

| 日期 | 变化 |
|---|---|
| 2026-09-08 | 新版网页全 SDUI，改走 voyager call；四个动作可用，评论列表 / 作者动态 / 内容搜索 / 热榜不可用 |
| 2026-09-08 | 发现 /in/{vanity}/recent-activity/all/ 和 /feed/update/{urn}/ 仍是老版 Ember 页面，可捕获 dash GraphQL：补上作者动态、评论、回复三个动作（navigate） |
