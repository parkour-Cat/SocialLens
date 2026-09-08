import type { PlatformDef } from "../types";

export const douyin: PlatformDef = {
  id: "douyin",
  name: "抖音",
  homeUrl: "https://www.douyin.com/?recommend=1",
  hosts: [".douyin.com"],
  loginCookie: { url: "https://www.douyin.com/", name: "sessionid" },
  loginUrl: "https://www.douyin.com/",
  loginHint: "打开 douyin.com，右上角登录，用抖音 App 扫码",
  matches: ["https://*.douyin.com/*"],
};
