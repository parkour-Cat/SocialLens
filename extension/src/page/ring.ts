// The capture ring buffer: the last RING_SIZE responses the page saw, plus the waiters of
// wait_capture-style actions. Responses are forwarded to the background only while capture
// (record mode) is enabled.

import type { Capture } from "../shared/messages";

export const RING_SIZE = 200;

export interface Waiter {
  test: (c: Capture) => boolean;
  resolve: (c: Capture) => void;
}

export class CaptureRing {
  readonly items: Capture[] = [];
  readonly waiters: Waiter[] = [];
  captureEnabled = false;

  constructor(
    private readonly forward: (c: Capture) => void,
    private readonly size = RING_SIZE,
  ) {}

  record(c: Capture): void {
    // status 0 = aborted / network-failed / CORS-blocked request: nothing usable, and it must not
    // satisfy a waiter (sites often cancel a duplicate request right before the real one).
    if (c.status === 0) return;
    this.items.push(c);
    if (this.items.length > this.size) this.items.shift();
    for (let i = this.waiters.length - 1; i >= 0; i--) {
      if (this.waiters[i].test(c)) {
        const w = this.waiters.splice(i, 1)[0];
        w.resolve(c);
      }
    }
    if (this.captureEnabled) this.forward(c);
  }
}
