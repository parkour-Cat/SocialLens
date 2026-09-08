import type { PlatformDef } from "../types";

export const weixinChannels: PlatformDef = {
  id: "weixin_channels",
  name: "视频号",
  homeUrl: "https://channels.weixin.qq.com/",
  hosts: ["channels.weixin.qq.com"],
  loginCookie: { url: "https://channels.weixin.qq.com/", name: "sessionid" },
  loginUrl: "https://channels.weixin.qq.com/",
  loginHint: "打开 channels.weixin.qq.com（视频号网页版），用微信扫码登录",
  matches: ["https://channels.weixin.qq.com/*"],
};
