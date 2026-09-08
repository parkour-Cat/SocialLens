import type { PlatformDef } from "../types";

export const x: PlatformDef = {
  id: "x",
  name: "X",
  homeUrl: "https://x.com/home",
  hosts: [".x.com", "x.com"],
  loginCookie: { url: "https://x.com/", name: "auth_token" },
  loginUrl: "https://x.com/login",
  loginHint: "打开 x.com 登录（几乎所有页面都要求登录）",
  matches: ["https://*.x.com/*", "https://x.com/*"],
};
