#!/usr/bin/env node
// The token-swap test (ADR-0081 decision 8): put each template in design/themes/ in place, rebuild the tokens and the
// web app, run the layout checks (no sideways scroll, menu present, screens fit), then put the original tokens back.
// Slow (a build and a browser run per template), so it is a manual or nightly check: `pnpm design:swap-test`.
import { execSync } from "node:child_process";
import { readFileSync, readdirSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const run = (cmd) => execSync(cmd, { cwd: root, stdio: "inherit", env: { ...process.env, CI: "1" } });
const original = readFileSync(join(root, "design/DESIGN.md"), "utf8");
const themes = readdirSync(join(root, "design/themes")).filter((f) => f.endsWith(".md")).map((f) => f.replace(/\.md$/, ""));
let failed = [];
try {
  for (const t of themes) {
    console.log(`\n=== template ${t} ===`);
    try {
      run(`node scripts/design/build-tokens.mjs --use ${t}`);
      run("pnpm --filter web build");
      run("pnpm --filter web test:e2e:layout");
    } catch {
      failed.push(t);
    }
  }
} finally {
  writeFileSync(join(root, "design/DESIGN.md"), original);
  run("node scripts/design/build-tokens.mjs");
}
if (failed.length) {
  console.error(`\nswap test failed for: ${failed.join(", ")}`);
  process.exit(1);
}
console.log(`\nswap test passed for: ${themes.join(", ")}`);
