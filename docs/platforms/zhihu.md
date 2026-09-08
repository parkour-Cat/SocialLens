# 知乎 平台笔记

平台标识：`zhihu`
站点：https://www.zhihu.com ，专栏文章在 https://zhuanlan.zhihu.com
风险等级：high（接口带 x-zse-96 签名；未登录几乎不可用；频繁访问会跳"异常流量"验证）
默认策略：navigate（让站点自己发签名请求，扩展捕获）
限速：请求间隔 4 秒，随机延迟 ±2 秒，10 分钟内最多 12 次整页加载
登录态检测：cookie `z_c0`

## 能力清单

| action | 状态 | 策略 | 说明 |
|---|---|---|---|
| search_posts | done | navigate | `/search?type=content&q=` → 捕获 `/api/v4/search_v3`，`data[].object` 是 answer / article / question |
| search_users | done | navigate | `/search?type=people&q=` → 同一接口，`object.type=people` |
| get_post | done | navigate | 回答 `/answer/{id}`（或 `/question/{qid}/answer/{aid}`）、文章 `zhuanlan.zhihu.com/p/{id}`、问题 `/question/{id}`；SSR `<script id="js-initialData">` 的 `initialState.entities` |
| get_comments | done | navigate | 详情页 → 捕获 `/api/v4/comment_v5/(answers|articles|questions)/{id}/root_comment` |
| get_replies | 部分 | navigate | 评论接口已内联返回每条评论的前几条回复；溢出时点"查看全部 N 条回复"打开模态框，捕获 `/api/v4/comment_v5/comment/{id}/child_comment`（首页 20 条，已录样本 get_replies_overflow）。模态框内更多回复靠滚动加载，试了 `div.css-34podr` 等所有可滚动元素都没触发第二次请求，第二页待解 |
| get_user | done | navigate | `/people/{url_token}` 的 initialData `entities.users` |
| get_user_posts | done | navigate | `/people/{token}/answers` → `/api/v4/members/{token}/answers`；order=articles 走 `/posts` |
| get_feed | done | navigate | 首页 → `/api/v3/feed/topstory/recommend` |
| get_trending | done | navigate | `/hot` → `/api/v3/feed/topstory/hot-lists/total`，返回话题（kind=topics） |
| download | unsupported | | 只有回答里的图片，暂不做 |

## 统一模型

- 帖子 id 形如 `answer:123`、`article:123`、`question:123`，三种对象都映射成 SocialPost（`raw.kind` 区分），正文是去掉 HTML 标签的纯文本，图片取正文里的 `<img>`。
- 用户 id 用 `url_token`。

## 变更记录

| 日期 | 变化 |
|---|---|
| 2026-09-07 | 骨架 |
| 2026-09-07 | 录样本、parser 测试、REST 验证：8 个动作通过（搜索走"用户"标签点"综合"；详情/资料/热榜读 #js-initialData 原文由后端解析）；评论内联返回回复，get_replies 溢出翻页待补样本 |
| 2026-09-08 | 溢出回复：展开控件带图标不是纯文字节点，展开助手改为取文字匹配的最小元素后首页 20 条通了；模态框滚动翻页未触发，待解 |
| 2026-09-08 | 溢出回复第二页仍待解：模态框一打开就渲染了全部 51 条，但只观察到一次 limit=20 的 child_comment 请求；fetch/XHR（含二进制响应）、Worker 消息（含 gzip 字节）、MessageChannel 端口都加了钩子，均未见其余 31 条的来源。可能是 Service Worker 或 iframe。已放弃深挖 |
| 2026-09-08 | 溢出回复翻页已解：弹窗的滚动容器是哈希类名（当时是 div.css-34podr），之前的选择器选错了元素；改成滚动页面上所有可滚动容器，滚到底就发 child_comment offset 翻页请求。捕获模式只匹配 child_comment（之前混入的 worker 备选被噪声秒中）。51 条回复三页 20+20+11 验证通过 |
