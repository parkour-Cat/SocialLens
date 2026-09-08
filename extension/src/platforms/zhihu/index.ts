import type { PlatformDef } from "../types";

export const zhihu: PlatformDef = {
  id: "zhihu",
  name: "知乎",
  homeUrl: "https://www.zhihu.com/",
  hosts: [".zhihu.com"],
  loginCookie: { url: "https://www.zhihu.com/", name: "z_c0" },
  loginUrl: "https://www.zhihu.com/signin",
  loginHint: "打开 zhihu.com，扫码或账号登录（几乎所有内容都要求登录）",
  matches: ["https://*.zhihu.com/*"],
};
