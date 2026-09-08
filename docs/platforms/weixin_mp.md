# 公众号 平台笔记

平台标识：`weixin_mp`
站点：`https://mp.weixin.qq.com`（公众号后台，需要扫码登录自己的公众号）；文章页 `https://mp.weixin.qq.com/s/...`（公开）
风险等级：high
默认策略：call（后台接口在登录态下直接可调，无签名；参数 `token` 从后台页面 URL 取）
限速：请求间隔 6 秒，随机延迟 ±3 秒，每分钟上限 6。后台接口一天查几十个账号、一小时几百次请求就会临时冻结。
登录态检测：cookie `slave_sid`（域 `mp.weixin.qq.com`）。登录地址 `https://mp.weixin.qq.com`，微信扫码。

## 能做什么、不能做什么

公众号没有公开的网页版内容流。能拿到公域数据的入口是自己后台的"图文编辑器 → 插入超链接 → 选择其他公众号"功能背后的两个接口：按名称搜任意公众号、列出任意公众号的已发布文章。单篇文章正文页公开，不登录可抓。

拿不到的：按关键词全网搜正文（只有微信 App 搜一搜有）、阅读数、在看数、点赞、评论（只有微信客户端有）。这些标 unsupported。

## 能力清单

| action | 状态 | 策略 | 说明 |
|---|---|---|---|
| search_users | done | call | 按名称搜任意公众号（`searchbiz`），id 即 fakeid，每页 5，cursor `{begin}` |
| get_user_posts | 代码完成，待解冻验证 | call | 任意公众号的已发布文章列表（`appmsg`，按 fakeid），每页 5。实测账号处于 freq control 冻结，报 rate_limited |
| get_post | done | navigate | 单篇文章：标题、公众号名、作者、正文文本与 HTML、图片、发布时间、封面。参数为文章 URL 或 `/s/` 后的 id |
| get_user | done | call | 公众号资料（名称、头像、简介、微信号），按名称或微信号精确搜索取第一条 |
| search_posts | unsupported | | 网页端没有关键词全文搜索 |
| get_comments | unsupported | | 评论只在微信客户端 |
| get_feed | unsupported | | 没有推荐流 |
| download | planned | 后端直下 | 文章内图片 |

## 站点机制

- 后台页面 URL 形如 `https://mp.weixin.qq.com/cgi-bin/home?t=home/index&lang=zh_CN&token=123456`，`token` 是会话参数，接口都要带。
- 搜公众号：`GET /cgi-bin/searchbiz?action=search_biz&token=&lang=zh_CN&f=json&ajax=1&query=&begin=0&count=5`，返回 `list[]{fakeid, nickname, alias, round_head_img, service_type}`。
- 文章列表：`GET /cgi-bin/appmsg?action=list_ex&token=&lang=zh_CN&f=json&ajax=1&fakeid=&query=&begin=0&count=5&type=9`，返回 `app_msg_list[]{aid, title, link, digest, cover, create_time, update_time}`，`app_msg_cnt`。
- 冻结信号：`base_resp.ret` 为 200013（操作频繁），`ret` 非 0 一律视为失败。
- 文章正文页：服务端渲染，细节见下面实测。

## 实测（2026-09-07）

- 后台首页 URL 里有 `token`，页面全局 `wx.data.t` 也有，扩展从 URL 或 `wx.data.t` 取。
- `searchbiz` 确认可用：`GET /cgi-bin/searchbiz?action=search_biz&token=&lang=zh_CN&f=json&ajax=1&query=&begin=0&count=5`，返回 `list[]{fakeid, nickname, alias, round_head_img, service_type, signature, verify_status}`。样本 `search_users.json`。分页 cursor `{"begin": n}`，每页 5。
- `appmsg` 第一次调用就返回 `base_resp.ret=200013 "freq control"`：这个账号的文章列表接口当时已处于冻结状态（新号或当天已被限制）。冻结通常持续数小时到一天，映射为 rate_limited，队列暂停 5 分钟。样本待冻结解除后录制。
- 单篇文章页：navigate 打开 `https://mp.weixin.qq.com/s/{id}`，页面侧读 `#activity-name`（标题）、`#js_name`（公众号名）、`#js_author_name`（作者）、`#js_content`（正文用 textContent，innerText 为空因为容器初始隐藏；图片取 `data-src`）、`#publish_time`（"2026年8月23日 14:56"，parser 按东八区转 ISO）、`og:image`（封面）、URL 里的 `__biz`。样本 `get_post.json`。

## 接口映射

按上面的实测；`get_user` 复用 `searchbiz` 取第一条匹配。

## 变更记录

| 日期 | 变化 |
|---|---|
| 2026-09-07 | 初稿，能力清单与机制预期 |
| 2026-09-07 | searchbiz / 单篇文章确认并录样本；appmsg 因账号冻结待验证 |

- 图片下载已验证（2026-09-08）：文章内图片直链带 Referer 直下，2 张成功。文章列表 appmsg 仍被 freq control 冻结（429）。
