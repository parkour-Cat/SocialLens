// Run something in a navigated tab while the site may still replace the document (redirects,
// "Please wait..." interstitials, login bounces). The work is re-issued in each new document
// until it answers or the deadline passes; pure so it can be unit-tested.

export interface SettleOpts<T> {
  /** Absolute time (same clock as `now`) after which we give up. */
  deadline: number;
  now?: () => number;
  /** Start the work in `doc`; resolves with its value. */
  run: (doc: string, attempt: number) => Promise<T>;
  /** Resolves with the id of the document that replaced `doc`, or null when nothing happened before the deadline. */
  watchReplaced: (doc: string, remainingMs: number) => Promise<string | null>;
  /** Called when the work in `doc` is abandoned (the document was replaced or time ran out). */
  cancel?: (doc: string, attempt: number) => void;
  onReplaced?: (doc: string, attempt: number) => void;
}

export type SettleOutcome<T> = { value: T; doc: string } | { timedOut: true; doc: string; attempts: number };

export async function runUntilSettled<T>(doc: string, opts: SettleOpts<T>): Promise<SettleOutcome<T>> {
  const now = opts.now ?? (() => Date.now());
  let attempt = 0;
  while (now() < opts.deadline) {
    const current = doc;
    const running = opts.run(current, attempt).then((v) => ({ value: v, doc: current }));
    const replaced = opts.watchReplaced(doc, opts.deadline - now()).then((d) => ({ replacedBy: d }), () => ({ replacedBy: null }));
    const outcome = await Promise.race([running, replaced]);
    if ("value" in outcome) return outcome;
    opts.cancel?.(doc, attempt);
    if (!outcome.replacedBy) break;
    doc = outcome.replacedBy;
    attempt++;
    opts.onReplaced?.(doc, attempt);
  }
  return { timedOut: true, doc, attempts: attempt + 1 };
}
