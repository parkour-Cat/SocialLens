import type { PlatformDef } from "../types";

export const tiktok: PlatformDef = {
  id: "tiktok",
  name: "TikTok",
  homeUrl: "https://www.tiktok.com/foryou",
  hosts: [".tiktok.com"],
  loginCookie: { url: "https://www.tiktok.com/", name: "sessionid" },
  loginUrl: "https://www.tiktok.com/login",
  loginHint: "打开 tiktok.com 登录（需要能访问 TikTok 的网络；不登录也能看部分公开内容）",
  loginRequired: false,
  matches: ["https://*.tiktok.com/*"],
};
