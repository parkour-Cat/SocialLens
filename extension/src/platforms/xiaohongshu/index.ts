import type { PlatformDef } from "../types";

export const xiaohongshu: PlatformDef = {
  id: "xiaohongshu",
  name: "小红书",
  homeUrl: "https://www.xiaohongshu.com/explore",
  hosts: [".xiaohongshu.com"],
  loginCookie: { url: "https://www.xiaohongshu.com/", name: "web_session" },
  loginUrl: "https://www.xiaohongshu.com/explore",
  loginHint: "打开 xiaohongshu.com，用小红书 App 扫码登录",
  matches: ["https://*.xiaohongshu.com/*"],
};
