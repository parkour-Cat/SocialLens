import { describe, expect, it } from "vitest";

import { runUntilSettled } from "./settle";

const never = () => new Promise<never>(() => {});

describe("runUntilSettled", () => {
  it("returns the value when the work finishes in the first document", async () => {
    const out = await runUntilSettled("doc1", {
      deadline: 10_000,
      now: () => 0,
      run: async () => "ok",
      watchReplaced: never,
    });
    expect(out).toEqual({ value: "ok", doc: "doc1" });
  });

  it("re-runs the work in the document that replaced the first one", async () => {
    const runs: [string, number][] = [];
    const cancelled: string[] = [];
    const out = await runUntilSettled("doc1", {
      deadline: 10_000,
      now: () => 0,
      run: (doc, attempt) => {
        runs.push([doc, attempt]);
        return doc === "doc2" ? Promise.resolve("from doc2") : never();
      },
      watchReplaced: (doc) => (doc === "doc1" ? Promise.resolve("doc2") : never()),
      cancel: (doc) => cancelled.push(doc),
    });
    expect(out).toEqual({ value: "from doc2", doc: "doc2" });
    expect(runs).toEqual([
      ["doc1", 0],
      ["doc2", 1],
    ]);
    expect(cancelled).toEqual(["doc1"]); // the stranded first attempt is told to stop
  });

  it("times out instead of looping when the deadline passes without a replacement", async () => {
    let clock = 0;
    const cancelled: string[] = [];
    const out = await runUntilSettled("doc1", {
      deadline: 5_000,
      now: () => clock,
      run: never,
      watchReplaced: async () => {
        clock = 6_000; // the watch resolved with nothing at the deadline
        return null;
      },
      cancel: (doc) => cancelled.push(doc),
    });
    expect(out).toEqual({ timedOut: true, doc: "doc1", attempts: 1 });
    expect(cancelled).toEqual(["doc1"]);
  });

  it("treats a failing watch like no replacement (the action's own timeout wins)", async () => {
    let clock = 0;
    const out = await runUntilSettled("doc1", {
      deadline: 5_000,
      now: () => clock,
      run: never,
      watchReplaced: async () => {
        clock = 9_000;
        throw new Error("navigated document did not become reachable");
      },
    });
    expect(out).toMatchObject({ timedOut: true, doc: "doc1" });
  });

  it("does not start when the deadline has already passed", async () => {
    let started = false;
    const out = await runUntilSettled("doc1", {
      deadline: 100,
      now: () => 200,
      run: async () => {
        started = true;
        return 1;
      },
      watchReplaced: never,
    });
    expect(started).toBe(false);
    expect(out).toMatchObject({ timedOut: true, attempts: 1 });
  });

  it("gives the watcher the time left, not the whole budget", async () => {
    let clock = 1_000;
    const budgets: number[] = [];
    await runUntilSettled("doc1", {
      deadline: 4_000,
      now: () => clock,
      run: never,
      watchReplaced: async (_doc, remaining) => {
        budgets.push(remaining);
        clock += 1_500;
        return budgets.length < 2 ? `doc${budgets.length + 1}` : null;
      },
    });
    expect(budgets).toEqual([3_000, 1_500]);
  });
});
