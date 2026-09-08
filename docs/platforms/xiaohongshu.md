# 小红书 平台笔记

平台标识：`xiaohongshu`
站点：`https://www.xiaohongshu.com`，接口域 `https://edith.xiaohongshu.com`
风险等级：high
默认策略：navigate（站点自己发请求，扩展读 SSR 状态 / 捕获响应 / 滚动翻页）
限速：请求间隔 4 秒，随机延迟 ±2 秒，每分钟上限 10
登录态检测：cookie `web_session` 存在。小红书网页版几乎所有接口都要求登录，匿名只能看少量推荐。

## 能力清单

| action | 状态 | 策略 | 说明 |
|---|---|---|---|
| search_posts | done | navigate | 搜索笔记；翻页靠滚动，REST 已验证三页无重复 |
| search_users | done | navigate + 点击 | 搜索页忽略 `type=user`，页面动作点"用户"标签后捕获 `search/usersearch`；`data.users[]`、`has_more`，每页 15，滚动翻页 |
| get_post | done | navigate | 笔记详情（图文 / 视频），需要 `xsec_token` |
| get_comments | done | navigate | 笔记评论，翻页靠滚动 |
| get_user | done | navigate | 用户资料，需要 `xsec_token` |
| get_user_posts | done | navigate | 用户笔记，REST 已验证四页无重复，列表到底返回空 |
| get_feed | done | navigate | 首页推荐，翻页靠滚动 |
| get_my_favorites | planned | call | 自己的收藏 / 点赞 |
| download | planned | 后端直下 | 图片原图、视频无水印地址 |

## 站点机制（已录制确认）

- 接口分布在 `edith.xiaohongshu.com`（大部分）和 `so.xiaohongshu.com`（搜索），页面通过 CORS 带 cookie 调用。
- 每个请求带 `X-s`、`X-t`、`X-s-common` 三个签名头。`X-s` / `X-t` 由页面全局函数 `window._webmsxyw(path, body)` 生成；`X-s-common` 由页面拦截器生成，已是不可解码的私有格式（首字节 0xd9 等，非 base64 JSON），所以不自己拼请求。
- 笔记详情和用户主页都要带 `xsec_token`，来自搜索结果 / 列表项，单独拿 id 打不开。
- 风控信号：`search.state == "error"`、`redcaptcha/v2/verify|check`、`website-login/captcha`、以及整站 HTML 空正文（按出口 IP 计）。

## 策略结论（2026-09-07 实测）

- `X-s-common` 已是不可解码的私有格式（不是 base64 JSON），不自己拼请求。所有动作走 navigate：后台开临时标签页，读 SSR 状态或等站点自己的响应，翻页在同一标签页里滚动（cursor 带 `_tab`）。
- 后台标签页（`active:false`）会照常发出页面加载时的请求（搜索页在后台照常发 `search/notes`），但"滚动加载更多"依赖 IntersectionObserver，隐藏文档里不触发。所以扩展把临时标签页放在一个独立的工作窗口里，并在滚动前把它切成该窗口的活动标签页。
- 页面窗口本身不滚动（`scrollHeight == innerHeight`），列表在内部容器里；`scroll_capture` 自动找最高的可滚动元素。
- `redcaptcha/v2/getconfig` 每次页面加载都会请求，不是风控信号；只把 `redcaptcha/v2/verify|check` 和 `website-login/captcha` 当挑战。

## 翻页约定

- 列表类第一页返回 cursor `{"tab": <tabId>}`；带 cursor 再调时在该标签页滚动，最多等 15 秒。没有新响应就视为列表结束，返回空 items、cursor 为空，不报错。
- 会话标签页闲置 10 分钟自动关闭，之后再用旧 cursor 会得到 `cursor_expired`（HTTP 410），重新不带 cursor 调用即可。

## 接口映射

### search_posts

- 入口：`/search_result?keyword=&source=web_explore_feed`，结果不在 SSR 里（`search.feeds` 为空），页面挂载后自己请求。
- 平台接口：`POST so.xiaohongshu.com/api/sns/web/v2/search/notes`（注意 v2，域名 so）。页面加载后会连发两页。
- 样本：`search_posts.json`
- 字段：`data.items[]{id, xsec_token, model_type, note_card{display_title, type, user{user_id,nickname,avatar,xsec_token}, interact_info{liked_count,comment_count,shared_count,collected_count}, cover{url_default,url_pre,width,height}, image_list[], corner_tag_info}}`，`data.has_more`。计数是字符串。
- 分页：cursor `{"tab": <tabId>}`，下一页靠滚动同一标签页。
- 页面级软封锁实测（2026-09-07 下午）：`/explore` 等页面 HTML 返回 200 但正文为空（`text/plain`，0 字节），用户自己的标签页里也一样，所有 navigate 动作以 `not_found`（读不到 `__INITIAL_STATE__`）失败。当时用户切换了网络节点后立即恢复，说明封锁按出口 IP 计，与账号 / cookie 无关。日常使用仍要控制频率。
- 风控实测：同一关键词一小时内搜了约六次后，搜索接口开始以网络错误失败（浏览器看到的是 status 0，站点状态 `search.state` 变成 `error`），其它接口不受影响。页面侧检测到 `search.state == "error"` 会立即报 rate_limited，队列暂停 5 分钟。对策只有等。

### get_feed

- 入口：`/explore`，第一批在 SSR：`__INITIAL_STATE__.feed.feeds[]{id, xsecToken, modelType, noteCard{displayTitle, type, user{userId,nickname,avatar,xsecToken}, interactInfo{likedCount}, cover{urlDefault,urlPre,width,height}}, ignore}`（camelCase）。
- 更多：滚动触发 `POST edith/api/sns/web/v1/homefeed`，字段同搜索卡片（snake_case）。
- 样本：`get_feed.json`

### get_post

- 入口：`/explore/{note_id}?xsec_token=&xsec_source=pc_search`。没有 xsec_token 打不开。
- 数据在 SSR：`__INITIAL_STATE__.note.noteDetailMap[note_id].note{noteId, type(normal|video), title, desc, time(毫秒), ipLocation, user{userId,nickname,avatar,xsecToken}, interactInfo{likedCount,commentCount,shareCount,collectedCount}, imageList[{urlDefault,urlPre,width,height}], video{media{stream{h264[],h265[],av1[]}}}, tagList[{name}]}`。
- 样本：`get_post.json`
- 视频取 `stream` 里宽度最大的 `masterUrl`，下载需带 Referer。

### get_comments

- 入口：同笔记页，页面加载后自己请求 `GET edith/api/sns/web/v2/comment/page?note_id=&cursor=&xsec_token=`。
- 样本：`get_comments.json`
- 字段：`data.comments[]{id, content, like_count, create_time(毫秒), ip_location, user_info{user_id,nickname,image,xsec_token}, sub_comments[], sub_comment_count, sub_comment_has_more}`，`data.has_more`，`data.cursor`。
- 分页：滚动 `div.note-scroller`。评论列表的加载更多依赖 IntersectionObserver，隐藏标签页里不触发，所以临时标签页必须放在可见的工作窗口里。

### get_user

- 入口：`/user/profile/{user_id}?xsec_token=&xsec_source=pc_note`。
- 数据在 SSR：`__INITIAL_STATE__.user.userPageData{basicInfo{nickname, desc, imageb, images, redId, gender, ipLocation}, interactions[{type: follows|fans|interaction, count}], tags[{name}]}`。user_id 从页面 URL 取。
- 样本：`get_user.json`

### get_user_posts

- 入口：同用户页。第一批在 SSR：`__INITIAL_STATE__.user.notes` 是"页数组的数组"，每项 `{id, xsecToken, noteCard{...}}`；`user.noteQueries[]{cursor, hasMore, page}`。
- 更多：滚动触发 `GET edith/api/sns/web/v1/user_posted?num=30&cursor=&user_id=&xsec_token=`，`data.notes[]{note_id, xsec_token, display_title, type, user, interact_info, cover, time}`，`data.has_more`，`data.cursor`。
- 样本：`get_user_posts.json`（SSR）、`get_user_posts_page2.json`（接口）

### search_users

站点忽略 URL 里的 `type=user`，只有在页面上点"用户"标签才会请求 `search/usersearch`。页面动作先等 3 秒看有没有现成响应，没有就 `clickText("用户")` 再等；字段：`id`、`name`、`image`、`fans`（字符串，可能带万）、`note_count`、`sub_title`、`xsec_token`（拼进主页链接）、`red_id`。2026-09-07 录样本两页各 15 条。

- 回复：`/api/sns/web/v2/comment/sub/page?note_id=&root_comment_id=` 带 x-s，只能在笔记页点"展开 N 条回复"再捕获（expand.ts，滚动容器 `.note-scroller`）。热榜：网页版没有公开热榜，点搜索框只发 `search/trending/query`（个性化"猜你想搜"），`get_trending` 返回的就是它。

## 变更记录

| 日期 | 变化 |
|---|---|
| 2026-09-07 | 初稿，能力清单 |
| 2026-09-07 | 六个动作实现并用登录态样本确认；REST 含翻页经真浏览器验证；记录搜索风控与出口 IP 软封锁 |
