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
import type { PageAction, PagePlatform } from "./types";

const platforms: PagePlatform[] = [bilibiliPage, xiaohongshuPage, douyinPage, weixinMpPage, kuaishouPage, weixinChannelsPage, youtubePage, xPage, redditPage, zhihuPage, tiktokPage, instagramPage, linkedinPage, toutiaoPage];

export function currentPagePlatform(hostname = location.hostname): PagePlatform | undefined {
  return platforms.find((p) => p.hosts.some((h) => (h.startsWith(".") ? hostname === h.slice(1) || hostname.endsWith(h) : hostname === h)));
}

export function platformAction(platformId: string, action: string): PageAction | undefined {
  return platforms.find((p) => p.id === platformId)?.actions[action];
}

export { pagePlatformActions } from "./catalog";
export type { PageAction, PageActionContext, PagePlatform } from "./types";
