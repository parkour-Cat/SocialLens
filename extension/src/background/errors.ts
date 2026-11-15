import type { TaskError } from "../shared/messages";

export class ExtError extends Error {
  constructor(
    public code: string,
    message: string,
    public details?: Record<string, unknown>,
  ) {
    super(message);
  }
}

export function toError(e: unknown): TaskError {
  if (e instanceof ExtError) return { code: e.code, message: e.message, details: e.details };
  return { code: "extension_error", message: e instanceof Error ? e.message : String(e) };
}
