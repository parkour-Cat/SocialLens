// Pure helpers for turning captured requests / responses into Capture fields. No side effects:
// safe to import anywhere (the page script installs its hooks explicitly, see hooks.ts).

// 抖音 feed / search responses run past 1 MB; the backend WebSocket accepts up to 16 MB.
export const MAX_BODY_CHARS = 6_000_000;
export const MAX_REQ_BODY = 4096;

export function wantsCapture(contentType: string | null): boolean {
  if (!contentType) return true;
  const ct = contentType.toLowerCase();
  // text/x-component: React Server Components payloads (LinkedIn flagship-web)
  return ct.includes("json") || ct.includes("text/plain") || ct.includes("xml") || ct.includes("javascript") || ct.includes("x-component");
}

export function parseBody(text: string, contentType: string | null): { body: unknown; truncated: boolean } {
  const truncated = text.length > MAX_BODY_CHARS;
  const slice = truncated ? text.slice(0, MAX_BODY_CHARS) : text;
  const looksJson = (contentType ?? "").includes("json") || /^\s*[[{]/.test(slice);
  if (looksJson && !truncated) {
    try {
      return { body: JSON.parse(slice), truncated };
    } catch {
      /* fall through */
    }
  }
  return { body: slice, truncated };
}

export function absolute(url: string): string {
  try {
    return new URL(url, location.href).href;
  } catch {
    return url;
  }
}

export function bodyPreview(b: unknown): string | undefined {
  if (b == null) return undefined;
  if (typeof b === "string") return b.slice(0, MAX_REQ_BODY);
  if (b instanceof URLSearchParams) return b.toString().slice(0, MAX_REQ_BODY);
  if (b instanceof FormData) return [...b.entries()].map(([k, v]) => `${k}=${typeof v === "string" ? v : "[file]"}`).join("&").slice(0, MAX_REQ_BODY);
  return undefined; // binary bodies are not interesting here
}

export function headersToObject(h: HeadersInit | undefined): Record<string, string> {
  const out: Record<string, string> = {};
  if (!h) return out;
  if (h instanceof Headers) h.forEach((v, k) => (out[k] = v));
  else if (Array.isArray(h)) h.forEach(([k, v]) => (out[k.toLowerCase()] = v));
  else Object.entries(h).forEach(([k, v]) => (out[k.toLowerCase()] = String(v)));
  return out;
}

/** Bytes a worker posted back (知乎 hands gzip-compressed JSON to the page this way) -> text. */
export async function bytesToText(d: unknown): Promise<string | null> {
  let bytes: Uint8Array | null = null;
  if (d instanceof ArrayBuffer) bytes = new Uint8Array(d);
  else if (ArrayBuffer.isView(d)) bytes = new Uint8Array(d.buffer, d.byteOffset, d.byteLength);
  else if (d && typeof d === "object" && !Array.isArray(d) && "0" in (d as object) && typeof (d as Record<string, unknown>)[0] === "number") {
    const o = d as Record<string, number>;
    const n = Object.keys(o).length;
    bytes = new Uint8Array(n);
    for (let i = 0; i < n; i++) bytes[i] = o[i];
  }
  if (!bytes || bytes.length < 20) return null;
  if (bytes[0] === 0x1f && bytes[1] === 0x8b && typeof DecompressionStream === "function") {
    const stream = new Blob([bytes.slice() as unknown as BlobPart]).stream().pipeThrough(new DecompressionStream("gzip"));
    return await new Response(stream).text();
  }
  // Plain text (JSON, or line-oriented streams such as React Server Components): keep whatever
  // decodes as UTF-8 without control bytes; real binary (media, protobuf) stays out.
  let text: string;
  try {
    text = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
  } catch {
    return null;
  }
  // eslint-disable-next-line no-control-regex
  return /[\x00-\x08\x0e-\x1f]/.test(text.slice(0, 2000)) ? null : text;
}
