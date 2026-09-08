// Bundles each MV3 entry as a self-contained IIFE (content/page scripts cannot be ES modules)
// and copies static files into dist/. `node build.mjs --watch` rebuilds on change.
import { build, context } from "esbuild";
import { cpSync, mkdirSync, rmSync } from "node:fs";

const watch = process.argv.includes("--watch");
const outdir = "dist";

rmSync(outdir, { recursive: true, force: true });
mkdirSync(outdir, { recursive: true });

const entries = {
  background: "src/background/index.ts",
  content: "src/content/index.ts",
  page: "src/page/index.ts",
  popup: "src/popup/popup.ts",
};

const copyStatic = () => {
  cpSync("manifest.json", `${outdir}/manifest.json`);
  cpSync("src/popup/popup.html", `${outdir}/popup.html`);
  cpSync("src/popup/popup.css", `${outdir}/popup.css`);
};

const options = {
  entryPoints: Object.entries(entries).map(([name, path]) => ({ in: path, out: name })),
  bundle: true,
  format: "iife",
  target: "chrome120",
  outdir,
  sourcemap: watch ? "inline" : false,
  logLevel: "info",
  define: { "process.env.NODE_ENV": watch ? '"development"' : '"production"', __BUILD_ID__: JSON.stringify(new Date().toISOString().slice(0, 19)) },
};

copyStatic();
if (watch) {
  const ctx = await context({
    ...options,
    plugins: [{ name: "copy-static", setup: (b) => b.onEnd(copyStatic) }],
  });
  await ctx.watch();
  console.log("watching...");
} else {
  await build(options);
}
