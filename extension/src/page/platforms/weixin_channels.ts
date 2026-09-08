// 视频号 page actions. API notes: docs/platforms/weixin_channels.md
// Stage: probing. Only a probe action until the page structure and endpoints are recorded.

import type { PageAction, PagePlatform } from "./types";

const probe: PageAction = async () => {
  const g = window as unknown as Record<string, unknown>;
  return {
    href: location.href,
    title: document.title,
    globals: Object.keys(g).filter((k) => /^(__|_|wx|WX|channels|finder)/.test(k)).slice(0, 60),
    text: (document.body?.innerText ?? "").replace(/\s+/g, " ").slice(0, 400),
  };
};

export const weixinChannelsPage: PagePlatform = {
  id: "weixin_channels",
  hosts: ["channels.weixin.qq.com"],
  riskSignals: [],
  actions: { probe },
};
