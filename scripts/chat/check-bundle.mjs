#!/usr/bin/env node
// The bundle check for the new chat (ADR-0082, stage CU1). It builds the first screen of the new chat on its own (a production build,
// packages/ui/bundle) and fails when:
//   - any file of the build, lazy chunks included, contains a host the library could call out to: assistant-api.com (assistant-cloud)
//     or auiusercontent.com (safe-content-frame's default sandbox host). The app must make no request to either (spike CU0, section 7).
//   - the JavaScript the first screen loads (the entry and everything it imports statically) is over the gzip budget of ADR-0082.
// `--json` prints the numbers. No dependencies of its own (harness.mjs uses the vite that apps/desktop builds with).
import { gzipSync } from "node:zlib";
import { mkdtempSync, readFileSync, readdirSync, rmSync, statSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { buildHarness } from "./harness.mjs";

/** The owner's budget for the first chat screen's JavaScript, in kilobytes of gzip (ADR-0082, 2026-10-20). */
export const BUDGET_GZIP_KB = 330;
export const FORBIDDEN = ["assistant-api.com", "auiusercontent.com"];

const out = mkdtempSync(join(tmpdir(), "chat-bundle-"));
try {
  await buildHarness(out);

  const files = [];
  (function walk(d) {
    for (const n of readdirSync(d)) {
      const p = join(d, n);
      if (statSync(p).isDirectory()) walk(p);
      else files.push(p);
    }
  })(out);
  const rel = (p) => p.slice(out.length + 1);

  const problems = [];
  for (const f of files.filter((p) => /\.(js|css|html)$/.test(p))) {
    const text = readFileSync(f, "utf8");
    for (const bad of FORBIDDEN) if (text.includes(bad)) problems.push(`${rel(f)} contains "${bad}"`);
  }

  const manifest = JSON.parse(readFileSync(join(out, ".vite/manifest.json"), "utf8"));
  const entry = Object.values(manifest).find((m) => m.isEntry);
  if (!entry) throw new Error("no entry chunk in the build");
  const seen = new Set();
  const stack = [entry];
  while (stack.length) {
    const c = stack.pop();
    if (seen.has(c.file)) continue;
    seen.add(c.file);
    for (const k of c.imports ?? []) stack.push(manifest[k]);
  }
  let raw = 0;
  let gz = 0;
  for (const f of seen) {
    const buf = readFileSync(join(out, f));
    raw += buf.length;
    gz += gzipSync(buf).length;
  }
  // the markdown renderer is a lazy chunk fetched right after the screen mounts: what it adds, for the record
  const body = Object.values(manifest).find((m) => /StreamdownBody/.test(m.src ?? ""));
  let extraGz = 0;
  if (body) {
    const more = new Set();
    const todo = [body];
    while (todo.length) {
      const c = todo.pop();
      if (more.has(c.file) || seen.has(c.file)) continue;
      more.add(c.file);
      for (const k of c.imports ?? []) todo.push(manifest[k]);
    }
    for (const f of more) extraGz += gzipSync(readFileSync(join(out, f))).length;
  }
  const kb = (n) => Math.round(n / 1024);
  const lazy = Object.values(manifest).filter((m) => !seen.has(m.file) && m.file.endsWith(".js")).length;
  if (gz / 1024 > BUDGET_GZIP_KB) problems.push(`the first chat screen is ${kb(gz)} KB gzip, over the budget of ${BUDGET_GZIP_KB} KB`);

  const summary = {
    firstScreen: { files: seen.size, rawKB: kb(raw), gzipKB: kb(gz), budgetKB: BUDGET_GZIP_KB },
    markdownRendererGzipKB: kb(extraGz),
    lazyChunks: lazy,
    problems,
  };
  if (process.argv.includes("--json")) console.log(JSON.stringify(summary, null, 2));
  else
    console.log(
      `chat bundle: first screen ${kb(raw)} KB raw, ${kb(gz)} KB gzip (budget ${BUDGET_GZIP_KB}); the markdown renderer adds ${kb(extraGz)} KB gzip right after; ${lazy} lazy chunks`,
    );
  if (problems.length) {
    for (const p of problems) console.error(`  - ${p}`);
    process.exitCode = 1;
  }
} finally {
  rmSync(out, { recursive: true, force: true });
}
