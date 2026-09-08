# 今日头条 平台笔记

平台标识：`toutiao`
站点：https://www.toutiao.com（搜索在 so.toutiao.com）
风险等级：low / medium / high
默认策略：navigate / call
限速：请求间隔 N 秒，随机延迟 ±M 秒，每分钟上限 K
登录态检测：cookie `sid_guard`（passport 登录 cookie；`sessionid` 在 chrome.cookies 里读不到）；匿名可看公开内容

## 能力清单

编码前先填这张表。状态：planned、recording、done、unsupported。

| action | 状态 | 策略 | 说明 |
|---|---|---|---|
| search_posts | done | navigate | so.toutiao.com 搜索页（综合 / 资讯 / 视频标签，看录制结果） |
| search_users | unsupported | | 搜索页没有稳定的用户标签 |
| get_post | done | navigate | 文章 /article/{id}/、视频 /video/{id}/（裸 id 走 /article/ 会被站点跳到视频页）；微头条 /w/{id}/ 未录 |
| get_comments | done | navigate | 文章页评论，滚动翻页 |
| get_replies | done | navigate | 评论下的回复 |
| get_user | done | navigate | 主页 /c/user/token/{token}/ |
| get_user_posts | done | navigate | 主页动态列表，滚动翻页 |
| get_feed | done | navigate | 首页推荐流 |
| get_trending | done | navigate | 热榜 |
| download | done | | 文章图片直链（15 张验证通过）；视频取 video_list 里最高画质的 main_url（720p 22MB 验证通过），地址带 url_expire 时效 |

原则：所有动作都只打开站点页面、捕获站点自己发出的请求，后端和扩展都不主动构造接口调用（不模拟签名、不自己拼 API），这样站点看到的流量和用户手动浏览一致。翻页靠滚动页面触发站点自己的下一页请求。 头条的验证码主要出现在搜索和匿名高频访问，遇到验证码只报错并暂停队列。

## 接口映射

录制样本后再填。每个 action 一节。

原则：全部 navigate，扩展只打开页面并捕获站点自己发的请求；`_signature` / `msToken` 由站点自己带。翻页 cursor 里带 `_tab`，续页在同一标签页里滚动或点击。

### get_feed

- 触发方式：打开 `https://www.toutiao.com/`；首页首屏是 SSR（RENDER_DATA.initialFeed），滚动后站点请求下一页。页面动作先等 5 秒捕获，没有就滚动一次。
- 平台接口：`GET /api/pc/list/feed?channel_id=0&max_behot_time=…&category=pc_profile_recommend&aid=24&app_name=toutiao_web&msToken=…&_signature=…`
- 样本文件：`get_feed.json`、`get_feed_page2.json`
- 字段映射：group_id → id；title；Abstract → content；user_info{user_id,name,avatar_url} → author；digg_count/like_count → likes；comment_count；read_count → views；share_count；publish_time（秒）；middle_image / large_image_list[0] → cover；has_video / video_duration → type video。没有 group_id 的卡片（广告、合集）跳过。
- 分页：has_more；滚动窗口触发。
- 已知坑：滚动会一次触发多页，环形缓冲会被 25 万字节一页的响应挤满。

### get_user / get_user_posts

- 触发方式：打开 `https://www.toutiao.com/c/user/token/{token}/`。
- 平台接口：资料在 `<script id="RENDER_DATA">`（URI 编码 JSON）`data.profileUserInfo{userId,name,avatarUrl,description,userAuthInfo,userVerified,ipLocation,mediaId}`，没有粉丝数；作品列表 `GET /api/pc/list/user/feed?category=profile_all&token=…&max_behot_time=…`，页面加载时自动请求第一页，滚动续页。
- 样本文件：`get_user.json`（RENDER_DATA 解码后）、`get_user_posts.json`
- 已知坑：视频作品是 cell_type 49，计数在 `action{digg_count,comment_count,play_count}` 里，没有 user_info。

### get_post

- 触发方式：打开 `https://www.toutiao.com/article/{group_id}/`。
- 平台接口：`RENDER_DATA.data{title,abstract,content(html),publishTime,groupId,itemId,mediaInfo{userId,name,avatarUrl,description},likeData.count,imageList[],cover,seoTDK{publishTimestamp,keywords}}`。
- 样本文件：`get_post.json`
- 视频页：`RENDER_DATA.data.initialVideo{title,coverUrl,publishTime,userInfo,playCount,diggCount,commentCount,repinCount,duration,videoPlayInfo.video_list[{main_url,backup_url,video_meta{definition,vwidth,vheight,size}}]}`，parser 按宽度排序把最高画质放在 media[0]，下载只取它。样本 `get_post_video.json`。裸 id 打开 /article/{id}/ 会被站点跳到 /video/。

### get_comments

- 触发方式：文章页加载时站点自动请求第一页；第二页起：点 `button.side-drawer-btn`（"查看全部 N 条评论"）打开抽屉，再点抽屉里的 `.load-more-btn`（"查看更多评论"），每次 20 条。
- 平台接口：`GET /article/v4/tab_comments/?aid=24&app_name=toutiao_web&offset=…&count=20&group_id=…&item_id=…&_signature=…` → `{data[{comment{id_str,text,create_time,digg_count,reply_count,user_id,user_name,user_profile_image_url,user_auth_info,is_pgc_author,reply_list}}],has_more,offset,total_number}`。
- 样本文件：`get_comments.json`、`get_comments_page2.json`
- 分页：offset；窗口滚动不会触发，必须点按钮。

### get_replies

- 触发方式：在评论里点"查看全部 N 条回复"（expand.ts 按评论正文定位），更多回复点"查看更多回复"。
- 平台接口：`GET /2/comment/v4/reply_list/?aid=24&app_name=toutiao_web&id={comment_id}&offset=0&count=5&repost=0&_signature=…` → `{data{data[],has_more,offset,total_count}}`。
- 样本文件：`get_replies.json`

### get_trending

- 触发方式：打开首页，站点自动请求。
- 平台接口：`GET /hot-event/hot-board/?origin=toutiao_pc&_signature=…` → `{data[{ClusterId,ClusterIdStr,Title,HotValue,Url,Image{url},Label,LabelDesc}]}`。
- 样本文件：`get_trending.json`；parser 返回 kind=topics。

### search_posts

- 触发方式：打开 `https://so.toutiao.com/search?keyword={kw}&pd=information&source=input`（资讯标签；综合标签是各种垂类卡片的混排，不用）。第一页是 SSR 的 `.result-content` 卡片，页面动作把卡片 outerHTML 数组交给后端；滚动后站点请求 JSON 页。
- 平台接口：`GET https://so.toutiao.com/search/?keyword=…&pd=information&…&_signature=…` → `{dom(html),count,has_more,has_next,…}`。
- 样本文件：`search_posts_page2.json`
- 字段映射：卡片 `cr-params`{gid,title}、`data-log-extra`{group_id,result_type}；正文文字里最长一段当摘要，时间文字（"昨天15:34"、"3小时前"）留在 raw.time_text；跳转链接 `/search/jump?…&url=` 里的目标地址留在 raw.target_url。
- 已知坑：搜索是头条出验证码最快的入口；卡片是 HTML，结构变了 parser 就要跟着改。search_users 未做（搜索页没有稳定的用户标签）。

## 下载

- 媒体地址从哪个字段取。
- 必需请求头。
- 是否加密、是否音视频分离。

## 变更记录

| 日期 | 变化 |
|---|---|
| 2026-09-08 | 八个动作实现，样本经真浏览器录制 |
