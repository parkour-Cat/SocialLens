# Reddit 平台笔记

平台标识：`reddit`
站点：https://www.reddit.com （需要能访问 Reddit 的网络）
风险等级：medium（未登录约每分钟 10 次就 429；登录后宽松）
默认策略：call（在已开的 reddit 标签页里 fetch `.json` 接口，cookie 自带登录态）
限速：请求间隔 2 秒，随机延迟 ±1 秒
登录态检测：cookie `reddit_session`（匿名可用公开内容，`loginRequired: false`）

## 能力清单

| action | 状态 | 策略 | 说明 |
|---|---|---|---|
| search_posts | done | call | `GET /search.json?q=&type=link&sort=relevance|hot|top|new|comments&after=` |
| search_users | done | call | `GET /search.json?q=&type=user` |
| get_post | done | call | `GET /comments/{id}.json?limit=1`，取第一个 listing 的 t3 |
| get_comments | done | call | `GET /comments/{id}.json?sort=&depth=1&limit=100`，第二个 listing 的 t1；末尾 `kind: more` 占位里的 id 编进 cursor，翻页走 `GET /api/morechildren.json?api_type=json&link_id=t3_&children=`（每次 100 个 id），`json.data.things[]`，`parent_id` 为 t1_ 的是回复 |
| get_replies | done | call | `GET /comments/{post}/_/{comment}.json?depth=2`，焦点评论的 `replies` |
| get_user | done | call | `GET /user/{name}/about.json` |
| get_user_posts | done | call | `GET /user/{name}/submitted.json?sort=new&after=` |
| get_feed | done | call | `GET /best.json`（登录后个性化，匿名等同 popular） |
| get_trending | done | call | `GET /r/popular.json?geo_filter=GLOBAL`，返回帖子（kind=posts） |
| download | done | 后端直下 | i.redd.it 图片直链；v.redd.it 是 DASH，视频 `DASH_xxx.mp4` + 音频 `DASH_AUDIO_128.mp4`（备选 `DASH_AUDIO_64.mp4`、`DASH_audio.mp4`）用 ffmpeg 合并；无声视频（gif 类）音轨 403，跳过只留视频 |

所有请求带 `raw_json=1`，避免 HTML 实体转义。

## 接口映射

- 分页：listing 的 `data.after`（形如 `t3_xxx`）编进 cursor `{"after"}`；评论列表没有 after。
- 帖子 t3：`id`、`title`、`selftext`、`author`、`subreddit`、`score`、`num_comments`、`created_utc`、`permalink`、`url`、`post_hint`、`preview.images[0].source`、`media.reddit_video`、`gallery_data` + `media_metadata`。
- 用户 t2（about.json 的 `data`）：`name`、`icon_img`、`subreddit.public_description`、`subreddit.subscribers`、`total_karma`、`link_karma`、`comment_karma`、`created_utc`。
- 评论 t1：`id`、`body`、`author`、`score`、`created_utc`、`depth`、`replies`（嵌套 listing 或空串）、`kind: more` 的占位表示还有更多。
- 错误：429 → rate_limited；403 → not_logged_in（私有 subreddit 或需登录）；404 → not_found。

## 下载

待 download_sources 验证。视频 fallback_url 形如 `https://v.redd.it/{id}/DASH_720.mp4`，同目录下 `DASH_AUDIO_128.mp4` 是音轨（老视频可能是 `DASH_audio.mp4`，合并失败时退回无声视频）。

## 实测说明

- 评论请求用 `depth=1`，二级回复以 `kind: more` 占位出现，parser 里 `raw.has_more_replies` 为 true，`reply_count` 未知；get_replies 用 `/comments/{post}/_/{comment}.json` 取焦点评论的子树。顶层评论翻页（2026-09-08）：484 条评论的帖子三页拿到 97 + 83 + 73 条，其余是更深层回复。
- 搜索用户返回的 t2 没有 `total_karma`，用 link_karma + comment_karma 之和。
- 外链帖（post_hint=link）映射为 `type: article`，目标链接在 `raw.link_url`。
- 登录账号实测：搜索两页各 25、评论 97 条、回复 6 条、feed 两页、popular 25 条；视频下载 9.9 MB 合并成功（h264 + aac）。

## 变更记录

| 日期 | 变化 |
|---|---|
| 2026-09-07 | 骨架按 `.json` API 写出，同日录样本、parser 测试、REST 含翻页与下载验证 |
