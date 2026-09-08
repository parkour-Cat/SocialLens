import type { PlatformDef } from "../types";

export const weixinMp: PlatformDef = {
  id: "weixin_mp",
  name: "公众号",
  homeUrl: "https://mp.weixin.qq.com/",
  hosts: ["mp.weixin.qq.com"],
  loginCookie: { url: "https://mp.weixin.qq.com/", name: "slave_sid" },
  loginUrl: "https://mp.weixin.qq.com/",
  loginHint: "打开 mp.weixin.qq.com（公众号后台），用微信扫码登录你自己的公众号；公域搜索和文章列表都走这个后台",
  matches: ["https://mp.weixin.qq.com/*"],
};
