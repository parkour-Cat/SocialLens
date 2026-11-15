import { describe, expect, it } from "vitest";

import type { Capture } from "../shared/messages";
import { CaptureRing } from "./ring";

const cap = (url: string, status = 200): Capture => ({ url, method: "GET", status, content_type: "application/json", body: {}, truncated: false, ts: Date.now(), kind: "fetch" });

describe("CaptureRing", () => {
  it("keeps the last `size` captures and ignores aborted requests", () => {
    const r = new CaptureRing(() => {}, 3);
    for (const u of ["a", "b", "c", "d"]) r.record(cap(u));
    r.record(cap("aborted", 0));
    expect(r.items.map((c) => c.url)).toEqual(["b", "c", "d"]);
  });

  it("resolves and removes matching waiters only", () => {
    const r = new CaptureRing(() => {});
    const got: string[] = [];
    r.waiters.push({ test: (c) => c.url.includes("comments"), resolve: (c) => got.push(c.url) });
    r.waiters.push({ test: (c) => c.url.includes("feed"), resolve: (c) => got.push(c.url) });
    r.record(cap("/api/comments?page=1"));
    r.record(cap("/api/comments?page=2")); // that waiter is gone already
    expect(got).toEqual(["/api/comments?page=1"]);
    expect(r.waiters).toHaveLength(1);
  });

  it("an aborted request never satisfies a waiter", () => {
    const r = new CaptureRing(() => {});
    let hit = false;
    r.waiters.push({ test: () => true, resolve: () => (hit = true) });
    r.record(cap("/api/x", 0));
    expect(hit).toBe(false);
  });

  it("forwards to the background only while capture is enabled", () => {
    const sent: string[] = [];
    const r = new CaptureRing((c) => sent.push(c.url));
    r.record(cap("one"));
    r.captureEnabled = true;
    r.record(cap("two"));
    expect(sent).toEqual(["two"]);
  });
});
