import type { PlatformDef } from "../types";

export const toutiao: PlatformDef = {
  id: "toutiao",
  name: "今日头条",
  homeUrl: "https://www.toutiao.com/",
  hosts: [".toutiao.com"],
  loginCookie: { url: "https://www.toutiao.com/", name: "sid_guard" }, // passport login cookie; `sessionid` was not visible to chrome.cookies here
  loginUrl: "https://www.toutiao.com/",
  loginHint: "打开 toutiao.com，点右上角登录（不登录也能看公开内容）",
  loginRequired: false,
  matches: ["https://*.toutiao.com/*"],
};
