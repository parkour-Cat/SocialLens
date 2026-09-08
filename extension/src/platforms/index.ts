import { bilibili } from "./bilibili";
import { douyin } from "./douyin";
import { kuaishou } from "./kuaishou";
import { weixinChannels } from "./weixin_channels";
import { weixinMp } from "./weixin_mp";
import { x } from "./x";
import { youtube } from "./youtube";
import { reddit } from "./reddit";
import { zhihu } from "./zhihu";
import { tiktok } from "./tiktok";
import { instagram } from "./instagram";
import { linkedin } from "./linkedin";
import { toutiao } from "./toutiao";
import { xiaohongshu } from "./xiaohongshu";
import { hostMatches, type PlatformDef } from "./types";

export const platforms: PlatformDef[] = [bilibili, xiaohongshu, douyin, weixinMp, kuaishou, weixinChannels, youtube, x, reddit, zhihu, tiktok, instagram, linkedin, toutiao];

export function platformById(id: string): PlatformDef | undefined {
  return platforms.find((p) => p.id === id);
}

export function platformForUrl(url: string | undefined): PlatformDef | undefined {
  if (!url) return undefined;
  let host: string;
  try {
    host = new URL(url).hostname;
  } catch {
    return undefined;
  }
  return platforms.find((p) => hostMatches(p, host));
}

export type { PlatformDef } from "./types";
