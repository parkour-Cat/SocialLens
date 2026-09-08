import type { PlatformDef } from "../types";

export const bilibili: PlatformDef = {
  id: "bilibili",
  name: "B 站",
  homeUrl: "https://www.bilibili.com/",
  hosts: [".bilibili.com"],
  loginCookie: { url: "https://www.bilibili.com/", name: "SESSDATA" },
  loginUrl: "https://www.bilibili.com/",
  loginHint: "打开 bilibili.com，右上角登录（扫码或账号密码）",
  matches: ["https://*.bilibili.com/*"],
};
