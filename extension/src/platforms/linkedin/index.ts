import type { PlatformDef } from "../types";

export const linkedin: PlatformDef = {
  id: "linkedin",
  name: "LinkedIn",
  homeUrl: "https://www.linkedin.com/feed/",
  hosts: [".linkedin.com"],
  loginCookie: { url: "https://www.linkedin.com/", name: "li_at" },
  loginUrl: "https://www.linkedin.com/login",
  loginHint: "打开 linkedin.com 登录",
  loginRequired: true,
  matches: ["https://*.linkedin.com/*"],
};
