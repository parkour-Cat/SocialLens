const PREFIX = "[SocialLens]";

let verbose = false;

export function setVerbose(v: boolean): void {
  verbose = v;
}

export const log = {
  debug: (...a: unknown[]) => verbose && console.debug(PREFIX, ...a),
  info: (...a: unknown[]) => console.info(PREFIX, ...a),
  warn: (...a: unknown[]) => console.warn(PREFIX, ...a),
  error: (...a: unknown[]) => console.error(PREFIX, ...a),
};
