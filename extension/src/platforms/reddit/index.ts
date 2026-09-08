import type { PlatformDef } from "../types";

export const reddit: PlatformDef = {
  id: "reddit",
  name: "Reddit",
  homeUrl: "https://www.reddit.com/",
  hosts: [".reddit.com"],
  loginCookie: { url: "https://www.reddit.com/", name: "reddit_session" },
  loginUrl: "https://www.reddit.com/login/",
  loginHint: "打开 reddit.com 登录（不登录也能看公开内容，登录后才有个人首页流）",
  loginRequired: false,
  matches: ["https://*.reddit.com/*"],
};
