import { describe, expect, it } from "vitest";

import type { Capture } from "../shared/messages";
import { makeMatcher, textMatcher, textOfCapture } from "./matcher";

const cap = (url: string, extra: Partial<Capture> = {}): Capture => ({ url, method: "GET", status: 200, ts: 0, kind: "fetch", body: null, truncated: false, ...extra }) as Capture;

describe("textMatcher", () => {
  it("treats /.../ as a regex and everything else as a substring", () => {
    expect(textMatcher("/\\/comment\\/list\\//")("https://a.com/aweme/v1/web/comment/list/?x")).toBe(true);
    expect(textMatcher("/comment/list/")("https://a.com/aweme/v1/web/comment/list/?x")).toBe(true); // a path, not a regex: its tail is not a flag list
    expect(textMatcher("/api/x/list")("https://a.com/api/x/list")).toBe(true);
    expect(textMatcher("/api/x/y")("https://a.com/api/x/y")).toBe(false); // "y" is a valid flag: this one IS parsed as a sticky regex, so end patterns with a slash
    expect(textMatcher("/API/i")("https://a.com/api/")).toBe(true); // flags work
    expect(textMatcher("/(unclosed/")("/(unclosed/")).toBe(true); // invalid regex falls back to substring
    expect(textMatcher("nope")("https://a.com/")).toBe(false);
  });
});

describe("makeMatcher", () => {
  it("matches on the url alone", () => {
    const m = makeMatcher("/\\/(general\\/search\\/single|search\\/item)\\//");
    expect(m(cap("https://www.douyin.com/aweme/v1/web/search/item/?keyword=x"))).toBe(true);
    expect(m(cap("https://www.douyin.com/aweme/v1/web/general/search/single/?keyword=x"))).toBe(true);
    expect(m(cap("https://www.douyin.com/aweme/v1/web/hot/search/list/"))).toBe(false);
  });

  it("@@ matches the request body (GraphQL operation names)", () => {
    const m = makeMatcher("/graphql @@ /UserTweets|UserOriginalsTimeline/");
    expect(m(cap("https://x.com/i/api/graphql/abc/UserTweets", { request_body: '{"operationName":"UserTweets"}' }))).toBe(true);
    expect(m(cap("https://x.com/i/api/graphql/abc/Other", { request_body: '{"operationName":"Other"}' }))).toBe(false);
    expect(m(cap("https://x.com/i/api/graphql/abc/UserTweets"))).toBe(false); // no body recorded
  });

  it("## matches the response body, stringified once for object bodies", () => {
    const m = makeMatcher("/\\/graphql\\/query|\\/api\\/graphql/ ## /xdt_api__v1__feed__timeline__connection/");
    const feed = cap("https://www.instagram.com/graphql/query", { body: { data: { xdt_api__v1__feed__timeline__connection: { edges: [] } } } });
    const other = cap("https://www.instagram.com/graphql/query", { body: { data: { get_slide_mailbox: {} } } });
    expect(m(feed)).toBe(true);
    expect(m(other)).toBe(false);
    expect(m(cap("https://www.instagram.com/api/graphql", { body: '{"xdt_api__v1__feed__timeline__connection":1}' }))).toBe(true);
    expect(textOfCapture(feed)).toBe(textOfCapture(feed)); // cached per capture
    expect(textOfCapture(cap("u"))).toBe("");
  });

  it("worker:// captures work with a body regex", () => {
    const m = makeMatcher('worker:// @@ /"comments":/');
    expect(m(cap("worker://msg#1", { request_body: '{"comments":[]}' }))).toBe(true);
    expect(m(cap("https://site/api", { request_body: '{"comments":[]}' }))).toBe(false);
  });
});
