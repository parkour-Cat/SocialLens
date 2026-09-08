import type { PlatformDef } from "../types";

export const kuaishou: PlatformDef = {
  id: "kuaishou",
  name: "快手",
  homeUrl: "https://www.kuaishou.com/?isHome=1",
  hosts: [".kuaishou.com"],
  loginCookie: { url: "https://www.kuaishou.com/", name: "userId" }, // session cookie names rotate (kuaishou.server.webday7_st); userId is set only when logged in
  loginUrl: "https://www.kuaishou.com/",
  loginHint: "打开 kuaishou.com，右上角登录，用快手 App 扫码",
  matches: ["https://*.kuaishou.com/*"],
};
