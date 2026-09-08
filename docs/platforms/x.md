# X 平台笔记

平台标识：`x`
站点：`https://x.com`，接口 `GET/POST /i/api/graphql/{queryId}/{OperationName}`
风险等级：medium
默认策略：navigate（站点自己发 GraphQL 请求，扩展按 URL 里的 OperationName 捕获；queryId 随部署变化，不自己拼）
限速：请求间隔 3 秒，随机延迟 ±1.5 秒，每分钟上限 12
登录态检测：cookie `auth_token`（域 .x.com）。几乎所有页面都要登录。登录地址 `https://x.com/login`。

## 能力清单

| action | 状态 | 策略 | 说明 |
|---|---|---|---|
| search_posts | done | navigate | `/search?q=&src=typed_query&f=live`（`order=top` 用 f=top），捕获 `SearchTimeline`，滚动翻页 |
| search_users | done | navigate | `/search?q=&f=user`，捕获 `SearchTimeline`（用户结果） |
| get_post | done | navigate | `/i/status/{id}`，捕获 `TweetDetail`，按 focalTweetId 取主推文 |
| get_comments | done | navigate | 同推文页 `TweetDetail` 里主推文以外的推文即回复 |
| get_user | done | navigate | `/{screen_name}`，捕获 `UserByScreenName` |
| get_user_posts | done | navigate | 同主页，捕获 `UserOriginalsTimeline`（旧名 `UserTweets` 也认），滚动翻页 |
| get_feed | done | navigate | `/home`，捕获 `HomeTimeline`，滚动翻页 |
| download | planned | 后端直下 | 图片 `media_url_https`，视频 `video_info.variants` 最高码率 |

## 实测机制（2026-09-07）

- 响应是 timeline instructions，parser 直接递归找 `{__typename: "Tweet", legacy}`。推文字段在 `legacy`（full_text、created_at、favorite_count、retweet_count、reply_count、quote_count、bookmark_count、entities/extended_entities.media），浏览量在 `views.count`，长文在 `note_tweet`。
- 用户对象（2026 版）没有 `legacy`：名字在 `core{name, screen_name, created_at}`，头像 `avatar.image_url`，粉丝 `relationship_counts{followers, following}`，推文数 `tweet_counts{tweets, media_tweets}`，简介 `profile_bio.description`，位置 `location.location`。
- 翻页：响应里 `cursorType: Bottom` 的条目存在即有下一页；实际翻页靠滚动同一标签页。
- 风控信号：`/i/flow/login` 跳转、429、`account/access` 挑战页。

- 回复的回复：就是那条回复自己的 TweetDetail（`/i/status/{comment_id}`），parser 把 `parent_id` 设为它、`post_id` 用 conversation_id。趋势：`/explore/tabs/trending` 的 GraphQL（ExplorePage / GenericTimelineById），项是 `itemType: TimelineTrend`，`trend_metadata.meta_description` 里有 "12.3K posts" 类热度。

## 变更记录

| 日期 | 变化 |
|---|---|
| 2026-09-07 | 初稿 |
| 2026-09-07 | 七个动作全部有登录态样本和 parser 测试，REST 含翻页经真浏览器验证 |
