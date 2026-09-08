# 视频号 平台笔记

平台标识：`weixin_channels`
站点：`https://channels.weixin.qq.com`（网页版，微信扫码登录）
风险等级：high
默认策略：navigate（分享链接播放页）+ call（创作者后台接口）
限速：请求间隔 5 秒，随机延迟 ±2 秒，每分钟上限 8
登录态检测：cookie `sessionid`（域 channels.weixin.qq.com）。登录地址 `https://channels.weixin.qq.com`，微信扫码。

## 能力清单

视频号网页端只有两个入口：创作者后台（只看自己的账号）和分享链接的播放页。没有搜索、推荐流、他人主页。

| action | 状态 | 策略 | 说明 |
|---|---|---|---|
| get_post | planned | navigate | 只接受分享链接（`channels.weixin.qq.com/web/pages/feed?...` 一类带 token 的 URL），抓标题、作者、封面、可见互动数 |
| download | planned | 扩展侧解密 | 播放页视频分片加密，页面里拿 decode key 解密后分块传回后端 |
| get_my_posts | planned | call | 自己账号的作品列表（创作者后台接口） |
| get_my_comments | planned | call | 自己作品的评论（创作者后台接口） |
| search_posts / search_users / get_feed / get_user / get_user_posts / get_comments | unsupported | | 网页端没有公域入口 |

## 探测记录（2026-09-07）

- 扫码登录后落在 `https://channels.weixin.qq.com/platform`，标题"视频号助手"：这是创作者后台，导航是 首页 / 内容管理 / 互动管理 / 直播 / 收入与服务 / 带货中心 / 数据中心 / 设置，全部是自己账号的数据。
- 登录 cookie：`sessionid`、`wxuin`（域 channels.weixin.qq.com，均非 HttpOnly）。
- 接口前缀 `/cgi-bin/mmfinderassistant-bin/...`（auth、notification、statistic、helper 等），都是后台自用。
- 访问 `/`、`/platform/discover`、`/platform/home` 都回到后台首页；`/web/pages/feed` 无参数时页面不可达（分享链接的播放页需要 `video_id` 等参数）。
- 用户确认：网页端只能播放分享链接里的视频，没有搜索页。结论：公域不可达，能力限于分享链接抓取 / 下载和自己账号的数据。

## 变更记录

| 日期 | 变化 |
|---|---|
| 2026-09-07 | 初稿，能力清单 |
