// Shared building blocks for navigate-style platforms (小红书, 抖音, ...): the site issues its
// own signed requests; the first page is captured as the page loads, later pages are
// triggered by scrolling the same tab (`more: true`, routed via the `_tab` cursor).

import { PageError } from "../errors";
import type { PageActionContext, Params } from "./types";

export const MORE_TIMEOUT_MS = 15_000;

/** Scroll for the next page; if nothing arrives the list has ended (the site stops requesting). */
export async function more(ctx: PageActionContext, pattern: string, scrollSelector?: string): Promise<unknown> {
  try {
    return await ctx.scrollCapture(pattern, { scroll_selector: scrollSelector, timeoutMs: MORE_TIMEOUT_MS });
  } catch (e) {
    if (e instanceof PageError && e.code === "timeout") return { end: true, href: location.href };
    throw e;
  }
}

/** First page: wait for the response the page fetches on load. Later pages: scroll. */
export function firstOrMore(p: Params, ctx: PageActionContext, pattern: string, scrollSelector?: string): Promise<unknown> {
  if (p.more) return more(ctx, pattern, scrollSelector);
  return ctx.waitCapture(pattern, typeof p.since === "number" ? p.since : 0);
}

/** First page from a captured response, falling back to a server-rendered global. */
export async function captureOrGlobal(p: Params, ctx: PageActionContext, pattern: string, globalPath: string, captureTimeoutMs = 12_000): Promise<unknown> {
  const since = typeof p.since === "number" ? p.since : 0;
  try {
    return await ctx.waitCapture(pattern, since, captureTimeoutMs);
  } catch (e) {
    if (!(e instanceof PageError && e.code === "timeout")) throw e;
  }
  const value = await ctx.readGlobal(globalPath, 5_000);
  return { ssr: true, path: globalPath, value, href: location.href };
}
