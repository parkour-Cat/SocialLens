import { describe, expect, it } from "vitest";

import { MAX_BODY_CHARS, bodyPreview, bytesToText, headersToObject, parseBody, wantsCapture } from "./bytes";
import { safeClone } from "./dom";

describe("parseBody / wantsCapture", () => {
  it("parses JSON by content type or by shape, keeps other text as is", () => {
    expect(parseBody('{"a":1}', "application/json")).toEqual({ body: { a: 1 }, truncated: false });
    expect(parseBody(' [1,2]', null)).toEqual({ body: [1, 2], truncated: false });
    expect(parseBody("<html>", "text/html")).toEqual({ body: "<html>", truncated: false });
    expect(parseBody("{broken", "application/json")).toEqual({ body: "{broken", truncated: false });
  });

  it("truncates huge bodies and then leaves them as text", () => {
    const big = "[" + "1,".repeat(MAX_BODY_CHARS) + "1]";
    const out = parseBody(big, "application/json");
    expect(out.truncated).toBe(true);
    expect(typeof out.body).toBe("string");
    expect((out.body as string).length).toBe(MAX_BODY_CHARS);
  });

  it("captures data responses, skips html and media", () => {
    expect(wantsCapture("application/json; charset=utf-8")).toBe(true);
    expect(wantsCapture("text/x-component")).toBe(true);
    expect(wantsCapture(null)).toBe(true);
    expect(wantsCapture("text/html")).toBe(false);
    expect(wantsCapture("image/webp")).toBe(false);
  });
});

describe("request previews", () => {
  it("summarises request bodies and headers", () => {
    expect(bodyPreview("x".repeat(5000))).toHaveLength(4096);
    expect(bodyPreview(new URLSearchParams({ a: "1", b: "2" }))).toBe("a=1&b=2");
    const fd = new FormData();
    fd.append("q", "露营");
    fd.append("f", new Blob(["x"]));
    expect(bodyPreview(fd)).toBe("q=露营&f=[file]");
    expect(bodyPreview(new Uint8Array([1]))).toBeUndefined();
    expect(headersToObject(new Headers({ "X-A": "1" }))).toEqual({ "x-a": "1" });
    expect(headersToObject([["X-B", "2"]])).toEqual({ "x-b": "2" });
    expect(headersToObject({ "X-C": "3" })).toEqual({ "x-c": "3" });
  });
});

async function gzip(text: string): Promise<ArrayBuffer> {
  const stream = new Blob([text]).stream().pipeThrough(new CompressionStream("gzip"));
  return new Response(stream).arrayBuffer();
}

describe("bytesToText", () => {
  const json = JSON.stringify({ comments: Array.from({ length: 5 }, (_, i) => ({ id: i, text: "评论" })) });

  it("gunzips gzip bytes and decodes plain UTF-8, in any byte container", async () => {
    expect(await bytesToText(await gzip(json))).toBe(json);
    const utf8 = new TextEncoder().encode(json);
    expect(await bytesToText(utf8)).toBe(json);
    expect(await bytesToText(Object.fromEntries([...utf8].map((b, i) => [String(i), b])))).toBe(json); // worker-posted byte objects
  });

  it("refuses binary and tiny payloads", async () => {
    expect(await bytesToText(new Uint8Array(64).fill(1))).toBeNull();
    expect(await bytesToText(new Uint8Array([0xff, 0xfe, 0xfd, ...new Uint8Array(40)]))).toBeNull();
    expect(await bytesToText(new TextEncoder().encode("short"))).toBeNull();
    expect(await bytesToText("not bytes")).toBeNull();
  });
});

describe("safeClone", () => {
  it("unwraps Vue refs, converts Map/Set/Date, drops functions, cuts only real cycles", () => {
    const shared = { n: 1 };
    const o: Record<string, unknown> = { ref: { __v_isRef: true, value: 5 }, m: new Map([["k", 1]]), s: new Set([1]), d: new Date(0), f: () => 1, a: shared, b: shared, big: 10n };
    o.self = o;
    expect(safeClone(o)).toEqual({ ref: 5, m: { k: 1 }, s: [1], d: "1970-01-01T00:00:00.000Z", a: { n: 1 }, b: { n: 1 }, big: "10", self: "[cycle]" });
  });
});
