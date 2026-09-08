# {平台名} 平台笔记

平台标识：`{platform}`
站点：
风险等级：low / medium / high
默认策略：navigate / call
限速：请求间隔 N 秒，随机延迟 ±M 秒，每分钟上限 K
登录态检测：

## 能力清单

编码前先填这张表。状态：planned、recording、done、unsupported。

| action | 状态 | 策略 | 说明 |
|---|---|---|---|
| search_posts | planned | | |
| search_users | planned | | |
| get_post | planned | | |
| get_comments | planned | | |
| get_user | planned | | |
| get_user_posts | planned | | |
| get_feed | planned | | |
| get_trending | planned | | |
| get_my_favorites | planned | | |
| download | planned | | |

## 接口映射

录制样本后再填。每个 action 一节。

### {action}

- 触发方式：跳转到哪个 URL，或在页面里调用什么。
- 平台接口：URL 模式，方法。
- 样本文件：`backend/tests/fixtures/{platform}/{action}_*.json`
- 字段映射：平台字段 → 统一模型字段。
- 分页：cursor 编码什么。
- 已知坑：

## 下载

- 媒体地址从哪个字段取。
- 必需请求头。
- 是否加密、是否音视频分离。

## 变更记录

| 日期 | 变化 |
|---|---|
