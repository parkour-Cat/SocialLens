import type { PlatformDef } from "../types";

export const youtube: PlatformDef = {
  id: "youtube",
  name: "YouTube",
  homeUrl: "https://www.youtube.com/",
  hosts: [".youtube.com"],
  loginCookie: { url: "https://www.youtube.com/", name: "SAPISID" },
  loginUrl: "https://www.youtube.com/",
  loginHint: "打开 youtube.com，用 Google 账号登录（不登录也能看公开内容）",
  loginRequired: false,
  matches: ["https://*.youtube.com/*"],
};
