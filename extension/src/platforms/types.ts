// Extension half of a platform adapter. Keep it thin: where the site lives, how to tell
// the user is logged in, and how each action is executed. Parsing lives in the backend.

export interface LoginCookie {
  url: string; // cookie scope url passed to chrome.cookies.get
  name: string;
}

export interface PlatformDef {
  id: string;
  name: string;
  homeUrl: string;
  /** hostnames (exact or `.suffix`) that belong to this platform */
  hosts: string[];
  loginCookie?: LoginCookie;
  /** Where the user signs in, and a one-line hint shown in the popup / in not_logged_in errors. */
  loginUrl: string;
  loginHint: string;
  /** false = tasks run without a login (the platform serves public data anonymously) */
  loginRequired?: boolean;
  /** URL patterns for content_scripts; must mirror manifest.json */
  matches: string[];
}

export function hostMatches(def: PlatformDef, hostname: string): boolean {
  return def.hosts.some((h) => (h.startsWith(".") ? hostname === h.slice(1) || hostname.endsWith(h) : hostname === h));
}
