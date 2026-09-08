// Page-side platform actions: run in the site's MAIN world with the user's cookies.
// Keep them thin — fetch the platform's own API and return the raw JSON. Parsing is the backend's job.

export type Params = Record<string, unknown>;

export interface PageActionContext {
  /** The page's fetch (hooked, so responses also land in the capture ring buffer). */
  fetch: typeof window.fetch;
  timeoutMs: number;
  /** Wait for a captured response whose URL matches (substring or /regex/) since `since`. */
  waitCapture: (pattern: string, since?: number, timeoutMs?: number) => Promise<unknown>;
  /** Every capture already in the ring buffer that matches `pattern`, oldest first. */
  captures: (pattern: string) => unknown[];
  /** Scroll (window or `scroll_selector`) until a new matching response is captured. */
  scrollCapture: (pattern: string, opts?: { scroll_selector?: string; timeoutMs?: number }) => Promise<unknown>;
  /** Read window.<path> (Vue refs unwrapped, cycles cut), polling up to waitMs for it to appear. */
  readGlobal: (path: string, waitMs?: number) => Promise<unknown>;
  /** Read a DOM element's text/attribute, optionally decoded ("json" | "uri-json"). */
  readElement: (selector: string, opts?: { attr?: string; decode?: "json" | "uri-json"; waitMs?: number }) => Promise<unknown>;
  /** Click an element (site handlers run). */
  click: (selector: string, waitMs?: number) => Promise<unknown>;
  /** Click the smallest element whose visible text equals `text` (tab labels, buttons). */
  clickText: (text: string, waitMs?: number) => Promise<unknown>;
  /** Type into an input like a user (native setter + input event); submit presses Enter. */
  type: (selector: string, text: string, opts?: { submit?: boolean; waitMs?: number }) => Promise<unknown>;
}

export type PageAction = (params: Params, ctx: PageActionContext) => Promise<unknown>;

export interface PagePlatform {
  id: string;
  /** hostnames (exact or `.suffix`) */
  hosts: string[];
  actions: Record<string, PageAction>;
  /** Captured request URLs that mean the site is showing a risk-control / captcha challenge.
   *  Generic waits fail fast with captcha_required instead of timing out. */
  riskSignals?: RegExp[];
}

export function param(p: Params, key: string): string | undefined {
  const v = p[key];
  return v == null ? undefined : String(v);
}

export function intParam(p: Params, key: string, fallback: number): number {
  const v = Number(p[key]);
  return Number.isFinite(v) && v > 0 ? Math.floor(v) : fallback;
}
