// Build identity, shared by every background module.

declare const __BUILD_ID__: string;
export const VERSION = chrome.runtime.getManifest().version;
export const BUILD = typeof __BUILD_ID__ === "string" ? __BUILD_ID__ : "dev";
