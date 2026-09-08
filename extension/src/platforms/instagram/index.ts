import type { PlatformDef } from "../types";

export const instagram: PlatformDef = {
  id: "instagram",
  name: "Instagram",
  homeUrl: "https://www.instagram.com/",
  hosts: [".instagram.com"],
  loginCookie: { url: "https://www.instagram.com/", name: "sessionid" },
  loginUrl: "https://www.instagram.com/accounts/login/",
  loginHint: "打开 instagram.com 登录（需要能访问 Instagram 的网络）",
  loginRequired: true,
  matches: ["https://*.instagram.com/*"],
};
