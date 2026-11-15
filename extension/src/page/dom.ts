// Reading the page: window globals (Vue refs unwrapped, cycles cut), scrollable containers,
// clickable elements. No side effects at import.

export function resolvePath(path: string): unknown {
  let cur: unknown = window;
  for (const seg of path.split(".")) {
    if (cur == null || (typeof cur !== "object" && typeof cur !== "function")) return undefined;
    cur = unwrapRef((cur as Record<string, unknown>)[seg]);
  }
  return cur;
}

/** Vue refs expose the real value under `.value`; unwrap so paths read naturally. */
export function unwrapRef(v: unknown): unknown {
  if (v && typeof v === "object" && (v as Record<string, unknown>).__v_isRef === true) {
    return (v as { value: unknown }).value;
  }
  return v;
}

/** JSON-safe deep copy: unwraps Vue refs/reactive proxies, drops functions, cuts cycles, bounds depth. */
export function safeClone(v: unknown, seen = new WeakSet<object>(), depth = 0): unknown {
  v = unwrapRef(v);
  if (v == null) return v;
  const t = typeof v;
  if (t === "function" || t === "symbol") return undefined;
  if (t === "bigint") return String(v);
  if (t !== "object") return v;
  if (depth > 48) return "[depth]"; // YouTube's ytInitialData nests 20+ levels deep
  const obj = v as object;
  if (seen.has(obj)) return "[cycle]";
  seen.add(obj);
  try {
    if (Array.isArray(obj)) return obj.map((x) => safeClone(x, seen, depth + 1));
    if (obj instanceof Map) return Object.fromEntries([...obj.entries()].map(([k, x]) => [String(k), safeClone(x, seen, depth + 1)]));
    if (obj instanceof Set) return [...obj].map((x) => safeClone(x, seen, depth + 1));
    if (obj instanceof Date) return obj.toISOString();
    const out: Record<string, unknown> = {};
    for (const k of Object.keys(obj)) {
      if (k.startsWith("__v_") || k === "_rawValue" || k === "_value" || k === "dep") continue;
      const c = safeClone((obj as Record<string, unknown>)[k], seen, depth + 1);
      if (c !== undefined) out[k] = c;
    }
    return out;
  } finally {
    seen.delete(obj); // shared (non-cyclic) references are fine; only true cycles are cut
  }
}

/** Elements that actually scroll (overflow auto/scroll with hidden content), tallest first. */
export function findScrollables(limit = 8): { el: HTMLElement; selector: string; scrollHeight: number; clientHeight: number }[] {
  const out: { el: HTMLElement; selector: string; scrollHeight: number; clientHeight: number }[] = [];
  const all = document.querySelectorAll<HTMLElement>("body *");
  for (let i = 0; i < all.length && i < 5000; i++) {
    const el = all[i];
    if (el.scrollHeight - el.clientHeight < 50 || el.clientHeight < 100) continue;
    const oy = getComputedStyle(el).overflowY;
    if (oy !== "auto" && oy !== "scroll") continue;
    const sel = el.tagName.toLowerCase() + (el.id ? `#${el.id}` : "") + (el.classList.length ? "." + [...el.classList].slice(0, 2).join(".") : "");
    out.push({ el, selector: sel, scrollHeight: el.scrollHeight, clientHeight: el.clientHeight });
  }
  out.sort((a, b) => b.scrollHeight - b.clientHeight - (a.scrollHeight - a.clientHeight));
  return out.slice(0, limit);
}

/** Click an element (the site's own handlers run), optionally waiting for it to appear first. */
export function findClickable(selector: string | undefined, text: string | undefined): HTMLElement | null {
  if (!text) return selector ? document.querySelector<HTMLElement>(selector) : null;
  // Smallest element whose own visible text equals `text` (a tab label, a button caption).
  const candidates = [...document.querySelectorAll<HTMLElement>(selector || "a,button,span,div,li,p")];
  // "/regex/flags" matches the visible text as a regular expression (e.g. "/^\d+ 条评论$/").
  const rx = text.length > 2 && text.startsWith("/") && /\/[a-z]*$/.test(text) ? new RegExp(text.slice(1, text.lastIndexOf("/")), text.slice(text.lastIndexOf("/") + 1)) : null;
  let best: HTMLElement | null = null;
  for (const el of candidates) {
    const own = (el.innerText || "").replace(/[​-‍﻿]/g, "").trim(); // 知乎 pads captions with zero-width chars
    if (rx ? !rx.test(own) : own !== text) continue;
    if (!best || el.innerHTML.length < best.innerHTML.length) best = el;
  }
  return best;
}
