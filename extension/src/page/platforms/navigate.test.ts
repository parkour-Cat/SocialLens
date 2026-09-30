import { beforeAll, describe, expect, it } from "vitest";

import { PageError } from "../errors";
import type { PageActionContext } from "./types";
import { MORE_TIMEOUT_MS, captureOrGlobal, firstOrMore, more } from "./navigate";

beforeAll(() => {
  (globalThis as { location?: unknown }).location = { href: "https://site.test/page" };
});

/** A page-action context that records what was asked of it. */
function ctx(overrides: Partial<PageActionContext> = {}) {
  const calls: unknown[][] = [];
  const c = {
    waitCapture: async (...a: unknown[]) => (calls.push(["waitCapture", ...a]), { body: "first" }),
    scrollCapture: async (...a: unknown[]) => (calls.push(["scrollCapture", ...a]), { body: "next" }),
    readGlobal: async (...a: unknown[]) => (calls.push(["readGlobal", ...a]), { ssr: 1 }),
    ...overrides,
  } as unknown as PageActionContext;
  return { c, calls };
}

describe("firstOrMore", () => {
  it("waits for the page's own first request from `since`", async () => {
    const { c, calls } = ctx();
    expect(await firstOrMore({ since: 42 }, c, "/x/")).toEqual({ body: "first" });
    expect(calls).toEqual([["waitCapture", "/x/", 42]]);
    await firstOrMore({}, c, "/x/");
    expect(calls[1]).toEqual(["waitCapture", "/x/", 0]); // reused tab: read from the start of the ring
  });

  it("scrolls the same tab for later pages", async () => {
    const { c, calls } = ctx();
    expect(await firstOrMore({ more: true }, c, "/x/", ".list")).toEqual({ body: "next" });
    expect(calls).toEqual([["scrollCapture", "/x/", { scroll_selector: ".list", timeoutMs: MORE_TIMEOUT_MS }]]);
  });
});

describe("more", () => {
  it("reports the end of the list when scrolling triggers nothing", async () => {
    const { c } = ctx({ scrollCapture: async () => { throw new PageError("timeout", "nothing"); } });
    expect(await more(c, "/x/")).toEqual({ end: true, href: "https://site.test/page" });
  });

  it("passes other errors through", async () => {
    const { c } = ctx({ scrollCapture: async () => { throw new PageError("captcha_required", "verify"); } });
    await expect(more(c, "/x/")).rejects.toMatchObject({ code: "captcha_required" });
  });
});

describe("captureOrGlobal", () => {
  it("falls back to the server-rendered global only on a capture timeout", async () => {
    const { c, calls } = ctx({ waitCapture: async () => { throw new PageError("timeout", "no capture"); } });
    expect(await captureOrGlobal({ since: 5 }, c, "/x/", "__INITIAL_STATE__")).toEqual({ ssr: true, path: "__INITIAL_STATE__", value: { ssr: 1 }, href: "https://site.test/page" });
    expect(calls).toEqual([["readGlobal", "__INITIAL_STATE__", 5_000]]);
    const bad = ctx({ waitCapture: async () => { throw new PageError("not_found", "gone"); } });
    await expect(captureOrGlobal({}, bad.c, "/x/", "g")).rejects.toMatchObject({ code: "not_found" });
    expect(bad.calls).toEqual([]);
  });
});
