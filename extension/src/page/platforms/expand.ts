// Expanding a comment's replies on navigate-style sites (抖音 / 小红书 / 快手): the reply
// request is signed by the site, so we make the page issue it by clicking the comment's
// "展开 N 条回复" control, then capture the response. The comment is located by its text
// (taken from the already-captured comment list); comments further down the list are
// reached by scrolling the list until they are loaded.

import { PageError } from "../errors";
import type { PageActionContext, Params } from "./types";

export interface ExpandSpec {
  /** Capture pattern of the top-level comment list (to read comment texts and to scroll for more). */
  listPattern: string;
  /** Extract {id, text} from one captured comment-list body. */
  extract: (body: unknown) => { id: string; text: string }[];
  /** Pattern of the reply response for this comment id. */
  replyPattern: (id: string) => string;
  /** Text of the control that expands / loads more replies inside the comment element. */
  expandRe: RegExp;
  scrollSelector?: string;
  /** How later pages of replies load: clicking the control again (default) or scrolling `replyScrollSelector`. */
  moreBy?: "click" | "scroll";
  replyScrollSelector?: string;
}

const MAX_SCROLLS = 6;

function textOf(el: Element): string {
  return (el.textContent || "").replace(/\s+/g, " ").trim();
}

/** Smallest element whose text contains `snippet`. */
function findBySnippet(snippet: string): Element | null {
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  let best: Element | null = null;
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    if ((n.textContent || "").includes(snippet)) {
      const el = n.parentElement;
      if (el && (!best || el.textContent!.length < best.textContent!.length)) best = el;
    }
  }
  return best;
}

/** Walk up from the comment text to the element that also holds an expand control; click it. */
function clickExpand(anchor: Element, expandRe: RegExp): boolean {
  let el: Element | null = anchor;
  for (let depth = 0; el && depth < 10; depth++, el = el.parentElement) {
    // Smallest element whose text matches: a caption may carry an icon child, so leaves alone
    // are not enough; the smallest match is the caption itself rather than a container.
    const controls = Array.from(el.querySelectorAll<HTMLElement>("*")).filter((c) => expandRe.test(textOf(c))).sort((a, b) => (a.textContent || "").length - (b.textContent || "").length);
    if (controls.length) {
      const c = controls[0];
      c.scrollIntoView({ block: "center" });
      c.click();
      return true;
    }
    if (textOf(el).length > 4000) break; // left the comment, now in the list container
  }
  return false;
}

export async function expandReplies(p: Params, ctx: PageActionContext, spec: ExpandSpec): Promise<unknown> {
  const id = String(p.comment_id ?? "");
  if (!id) throw new PageError("bad_request", "missing param: comment_id");
  let snippet = typeof p.snippet === "string" ? p.snippet : "";
  const since = Date.now();

  if (!snippet) {
    // Comment texts come from the captured list pages: first every page already captured in this
    // tab (the first page may not be the oldest capture), then scroll for more.
    await ctx.waitCapture(spec.listPattern, 0, 20_000);
    const find = (bodies: unknown[]) => bodies.flatMap((b) => spec.extract(b)).find((c) => c.id === id);
    let hit = find(ctx.captures(spec.listPattern));
    for (let i = 0; i < MAX_SCROLLS && !hit; i++) {
      try {
        hit = find([await ctx.scrollCapture(spec.listPattern, { scroll_selector: spec.scrollSelector, timeoutMs: 10_000 })]);
      } catch (e) {
        if (e instanceof PageError && e.code === "timeout") break;
        throw e;
      }
    }
    if (hit) snippet = hit.text.slice(0, 24);
    if (!snippet) throw new PageError("not_found", `comment ${id} not found in the first ${MAX_SCROLLS + 1} pages of comments`);
  }

  // Pages of replies are numbered: the cursor carries the index of the next page. Sites often
  // load several pages on their own (a modal that fills up on scroll), so a page already sitting
  // in the ring buffer is returned as is; only when none is left do we click / scroll for more.
  const pageIdx = Number(p.page ?? 0);
  if (p.more) {
    const caps = ctx.captures(spec.replyPattern(id)) as Record<string, unknown>[];
    if (caps.length > pageIdx) return { ...caps[pageIdx], _comment_id: id, _snippet: snippet, _page: pageIdx + 1 };
    if (spec.moreBy === "scroll") {
      try {
        const res = (await ctx.scrollCapture(spec.replyPattern(id), { scroll_selector: spec.replyScrollSelector, timeoutMs: 20_000 })) as Record<string, unknown>;
        return { ...res, _comment_id: id, _snippet: snippet, _page: pageIdx + 1 };
      } catch (e) {
        if (e instanceof PageError && e.code === "timeout") return { end: true, href: location.href, _snippet: snippet };
        throw e;
      }
    }
  }
  // The response is captured before the framework renders it: poll the DOM for a while, and
  // nudge the list once (rendering can wait for a scroll) before giving up.
  let anchor: Element | null = null;
  for (let i = 0; i < 24 && !anchor; i++) {
    anchor = findBySnippet(snippet);
    if (!anchor) {
      if (i === 12) window.scrollBy(0, 400);
      await new Promise((r) => setTimeout(r, 250));
    }
  }
  if (!anchor) throw new PageError("not_found", `comment ${id} is not rendered on the page (snippet: ${snippet})`);
  if (!clickExpand(anchor, spec.expandRe)) {
    if (p.more) return { end: true, href: location.href, _snippet: snippet };
    throw new PageError("not_found", `comment ${id} has no expand control (no replies?)`);
  }
  try {
    const res = (await ctx.waitCapture(spec.replyPattern(id), since, 15_000)) as Record<string, unknown>;
    return { ...res, _comment_id: id, _snippet: snippet, _page: pageIdx + 1 };
  } catch (e) {
    if (p.more && e instanceof PageError && e.code === "timeout") return { end: true, href: location.href, _snippet: snippet };
    throw e;
  }
}
