// Capture patterns used by wait_capture / scroll_capture / list_captures and the platform
// actions: `url`, `url @@ request-body`, or `url ## response-body`; each part is a plain
// substring or a `/regex/flags`. Kept free of page globals so it can be unit-tested.

import type { Capture } from "../shared/messages";

/** `/regex/flags` is a regular expression; anything else is a plain substring (paths like
 *  `/api/x/y` are substrings, not regexes, because their tail is not a valid flag list). */
export function textMatcher(pattern: string): (s: string) => boolean {
  const m = /^\/(.+)\/([gimsuy]*)$/.exec(pattern);
  if (m) {
    try {
      const re = new RegExp(m[1], m[2]);
      return (s) => re.test(s);
    } catch {
      /* fall through to substring */
    }
  }
  return (s) => s.includes(pattern);
}

// Response text, stringified once per capture (Instagram answers every GraphQL query at the same
// URL, so captures are told apart by what the response contains).
const responseText = new WeakMap<Capture, string>();
export function textOfCapture(c: Capture): string {
  let t = responseText.get(c);
  if (t == null) {
    t = typeof c.body === "string" ? c.body : c.body == null ? "" : JSON.stringify(c.body);
    responseText.set(c, t);
  }
  return t;
}

/** `url`, `url @@ request-body`, or `url ## response-body`; each part a substring or /regex/. */
export function makeMatcher(pattern: string): (c: Capture) => boolean {
  const [urlAndReq, respPart] = pattern.split(" ## ");
  const [urlPart, bodyPart] = urlAndReq.split(" @@ ");
  const urlOk = textMatcher(urlPart.trim());
  const reqOk = bodyPart ? textMatcher(bodyPart.trim()) : null;
  const respOk = respPart ? textMatcher(respPart.trim()) : null;
  return (c) => urlOk(c.url) && (!reqOk || reqOk(c.request_body ?? "")) && (!respOk || respOk(textOfCapture(c)));
}
