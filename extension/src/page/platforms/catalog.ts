// Which page actions this build supports, per platform. Sent to the backend on auth so it can
// route a task to an extension instance that actually implements the action.
import { bilibiliPage } from "./bilibili";
import { douyinPage } from "./douyin";
import { kuaishouPage } from "./kuaishou";
import { weixinChannelsPage } from "./weixin_channels";
import { weixinMpPage } from "./weixin_mp";
import { xPage } from "./x";
import { youtubePage } from "./youtube";
import { redditPage } from "./reddit";
import { zhihuPage } from "./zhihu";
import { tiktokPage } from "./tiktok";
import { instagramPage } from "./instagram";
import { linkedinPage } from "./linkedin";
import { toutiaoPage } from "./toutiao";
import { xiaohongshuPage } from "./xiaohongshu";
import type { PagePlatform } from "./types";

const platforms: PagePlatform[] = [bilibiliPage, xiaohongshuPage, douyinPage, weixinMpPage, kuaishouPage, weixinChannelsPage, youtubePage, xPage, redditPage, zhihuPage, tiktokPage, instagramPage, linkedinPage, toutiaoPage];

export function pagePlatformActions(): Record<string, string[]> {
  return Object.fromEntries(platforms.map((p) => [p.id, Object.keys(p.actions)]));
}
