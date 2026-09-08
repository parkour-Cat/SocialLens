# B 站 平台笔记

平台标识：`bilibili`
站点：`https://www.bilibili.com`、`https://search.bilibili.com`、`https://space.bilibili.com`，接口域 `https://api.bilibili.com`
风险等级：low
默认策略：call（页面上下文里 fetch，wbi 签名由扩展在页面内计算）
限速：请求间隔 2 秒，随机延迟 ±1 秒，每分钟上限 20
登录态检测：cookie `SESSDATA` 存在

B 站是 MVP 平台，作用是最快证明架构成立。

## 能力清单

| action | 状态 | 策略 | 说明 |
|---|---|---|---|
| search_posts | done | call | 搜索视频，`order`: totalrank / click / pubdate / dm / stow |
| search_users | done | call | 搜索用户 |
| get_post | done | call | 视频详情，参数 BV 号或 aid |
| get_comments | done | call | 视频一级评论及其前几条子评论，`mode`: 3 热门 / 2 时间 |
| get_user | done | call | UP 主资料 + 关注/粉丝数 |
| get_user_posts | done | call | UP 主投稿，`order`: pubdate / click / stow |
| get_feed | planned | navigate | 首页推荐 |
| get_trending | planned | call | 热门 / 排行榜 |
| get_my_favorites | planned | call | 自己的收藏夹 |
| download | planned | 后端直下 | DASH 音视频分离，需 ffmpeg 合并 |

## 实现位置

- 页面侧：`extension/src/page/platforms/bilibili.ts`，含 wbi 签名（`getMixinKey` / `signWbi`）、错误码映射、动作实现。
- 后端：`backend/sociallens/platforms/bilibili/`，`parsers.py` 纯函数，`cursor.py` 分页游标。
- 样本：`backend/tests/fixtures/bilibili/{action}.json`，由 `scripts/sample_bilibili.py` 录制。
- 测试：`backend/tests/test_bilibili_parsers.py`。

## wbi 签名

参数按 key 排序、去掉值里的 `!'()*`、拼成 query，追加 `wts`（秒级时间戳），`w_rid = md5(query + mixinKey)`。mixinKey 来自 `/x/web-interface/nav` 返回的 `wbi_img.img_url` 和 `sub_url` 两个文件名拼接后按固定置换表重排取前 32 位。扩展内缓存 6 小时。这和站点自身 JS 做的事情相同。

## 错误码映射

| 平台返回 | SocialLens 错误码 | 说明 |
|---|---|---|
| HTTP 412 | rate_limited | 请求被拦截。新配置文件在站点 JS 设置设备 cookie（buvid3）之前发请求就会触发，页面侧已加等待 |
| 页面跳到 `security.bilibili.com/412` 并请求 `/th/captcha/` | captcha_required | navigate 策略打开视频页时匿名配置文件常见。页面侧把这些 URL 当风控信号，`wait_capture` 立即失败而不是等超时 |
| -352 风控校验失败 | rate_limited | 匿名访问 space 类接口必现；登录后正常 |
| code 0 且 data 只有 `v_voucher` | captcha_required | 风控要求验证码，需要人在浏览器里过一次，然后 `POST /api/v1/bilibili/resume` |
| -101 / -403 | not_logged_in | |
| -404 / 62002 / 62004 | not_found | 视频不存在、被隐藏、审核中 |
| -412 | rate_limited | |

rate_limited 和 captcha_required 会让平台队列暂停 5 分钟，`POST /api/v1/bilibili/resume` 可立即恢复。

## 接口映射

### search_posts

- 平台接口：`GET /x/web-interface/wbi/search/type?search_type=video&keyword=&page=&order=&page_size=42`（wbi）
- 样本：`search_posts.json`（匿名可采）
- 字段映射：`bvid` → id；`title` 去掉 `<em class="keyword">` 标签 → title；`description` → content；`mid` / `author` / `upic` → author；`pic`（`//` 开头需补 https）→ cover_url；`play` → views，`like` → likes，`review` → comments，`favorites` → collects；`pubdate` → publish_time；`tag` 逗号分隔 → tags。`duration` 是 `mm:ss` 字符串，保留在 raw。
- 分页：`page` / `numPages`，cursor 编码 `{"page": n}`。`numResults` 固定上限 1000。
- 已知坑：匿名新配置文件偶尔返回 `v_voucher`，见错误码。

### search_users

- 平台接口：同上，`search_type=bili_user`
- 字段映射：`mid` → id，`uname` → name，`upic` → avatar_url，`usign` → bio，`fans` → followers，`videos` → posts。
- 分页：同 search_posts，每页 20。

### get_post

- 平台接口：`GET /x/web-interface/wbi/view?bvid=`（或 `aid=`）。非 wbi 版本 `/x/web-interface/view` 对匿名新配置文件返回 412，所以用 wbi 版。
- 样本：`get_post.json`（匿名可采）
- 字段映射：`bvid` → id；`title`、`desc`；`owner.{mid,name,face}` → author；`pic` → cover_url；`stat.{view,like,reply,share,favorite}` → metrics；`pubdate`；`tname` → tags；`pages[]` → media，每 P 一条 MediaItem，`extra.cid` 供下载取 playurl。`aid`、`cid`、`coin`、`danmaku` 保留在 raw。
- 已知坑：多 P 视频 `pages` 多条；`pic` 可能是 http。

### get_comments

- 平台接口：`GET /x/v2/reply/wbi/main?type=1&oid={aid}&mode=3&pagination_str={"offset":""}&plat=1&web_location=1315875`（wbi）
- oid 必须是 aid；传 BV 号时页面侧先调 view 换 aid，缓存在页内。
- 页面侧在响应里附加 `_post_id`（调用方传入的 id），parser 用它填 post_id。
- 样本：`get_comments.json`（匿名可采，但匿名只给少量评论）
- 字段映射：`rpid` → id，`parent`（0 表示一级）→ parent_id，`member.{mid,uname,avatar}` → author，`content.message` → content，`like` → likes，`ctime` → publish_time，`rcount` 保留在 raw。一级评论自带的前几条 `replies` 也展平进 items。
- 分页：`cursor.pagination_reply.next_offset`，cursor 编码 `{"offset": ...}`；`cursor.is_end` 为真则无下一页。`cursor.all_count` → total。

### get_user

- 平台接口：`GET /x/space/wbi/acc/info?mid=`（wbi）+ `GET /x/relation/stat?vmid=`，页面侧并行请求后返回 `{info, stat}`。
- 样本：`get_user.json`（登录态采样；匿名必返回 -352）
- 字段映射：`info.data.{mid,name,face,sign}`；`stat.data.{follower,following}` → metrics；`level`、`sex`、`official`、`vip.status` 保留在 raw。

### get_user_posts

- 平台接口：`GET /x/space/wbi/arc/search?mid=&pn=&ps=30&order=pubdate&platform=web&web_location=1550101`（wbi）
- 样本：`get_user_posts.json`（登录态采样；匿名返回 412 或 -352）
- 字段映射：`list.vlist[].{bvid,title,description,pic,play,comment,created,author,mid}`；`page.{pn,ps,count}` 分页，cursor 编码 `{"page": n}`。

## 下载（未实现）

- 媒体地址：`GET /x/player/wbi/playurl?bvid=&cid=&fnval=4048`，返回 DASH，`dash.video[]` 和 `dash.audio[]` 分离，选最高清晰度。 页面动作 `get_play_url(id, cid, mode)`：`dash` 用 `fnval=4048&fourk=1`；`mp4` 用 `fnval=1&platform=html5&high_quality=1&qn=80` 得单文件 durl。CDN 地址只要 Referer，不要 cookie。
- 必需请求头：`Referer: https://www.bilibili.com`，`User-Agent` 与浏览器一致。
- 不加密。音视频分离，后端下载两路后用 ffmpeg 合并。清晰度受账号等级限制。

- 回复（楼中楼）：`GET /x/v2/reply/reply?type=1&oid=&root=&pn=&ps=20`，不需要 wbi；`data.page.{num,size,count}` 翻页。热门：`GET /x/web-interface/popular?pn=&ps=20`，`data.list[]` 是 view 同构记录，`data.no_more` 结束。

## 变更记录

| 日期 | 变化 |
|---|---|
| 2026-09-06 | 初稿，接口来自公开资料 |
| 2026-09-07 | 六个动作实现并全部用真实样本确认；view 改用 wbi 版；记录 412 / -352 / v_voucher 行为；扩展重载后自动向已打开标签页重新注入脚本 |
