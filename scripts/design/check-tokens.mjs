#!/usr/bin/env node
// The token lint (ADR-0081 decision 5). Fails when a screen defines its own colour, font size or radius instead of using a
// design token: raw hex, rgb/hsl/oklch literals, Tailwind arbitrary colour/size/radius values, inline style colours.
// Exceptions live in design/token-allowlist.json, each with a reason. No dependencies.
import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const ROOTS = ["apps/web/app", "apps/web/components", "apps/web/lib", "apps/web/hooks", "apps/desktop/src", "packages/ui/src"];
const SKIP_DIRS = new Set(["node_modules", ".next", "dist", "results", "e2e"]);
const EXT = /\.(ts|tsx|css)$/;
const SKIP_FILE = /(\.test\.|\.spec\.|\.d\.ts$)/;

const allow = JSON.parse(readFileSync(join(root, "design/token-allowlist.json"), "utf8"));
const problems = [];
for (const f of allow.files ?? []) if (!existsSync(join(root, f.path))) problems.push(`allow-list: ${f.path} does not exist (remove the entry)`);
for (const f of allow.lines ?? []) if (!existsSync(join(root, f.path))) problems.push(`allow-list: ${f.path} does not exist (remove the entry)`);
const wholeFile = new Set((allow.files ?? []).map((f) => f.path));
const lineRules = allow.lines ?? [];
const usedLineRules = new Set();

const COLOUR_FN = String.raw`(?:rgba?|hsla?|oklch|oklab|lab|lch)\(`;
const RULES = [
  { name: "raw hex colour", re: /(?<![&\w/.-])#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3,4})(?![\w-])/g },
  { name: "raw colour function", re: new RegExp(String.raw`(?<![\w-])${COLOUR_FN}`, "g") },
  {
    name: "arbitrary font size",
    re: /\btext-\[(?:-?[\d.]+(?:rem|px|em)|clamp\([^\]]*)\]/g,
  },
  { name: "arbitrary radius", re: /\brounded(?:-[a-z]{1,2})?-\[(?!inherit\]|var\(|--)[^\]]+\]/g },
  {
    name: "arbitrary colour value",
    re: new RegExp(String.raw`\b(?:bg|text|border|fill|stroke|from|to|via|outline|decoration|caret|accent|divide|ring|shadow)-\[[^\]]*(?:#[0-9a-fA-F]{3,8}|${COLOUR_FN})[^\]]*\]`, "g"),
  },
  {
    name: "inline style with a literal value",
    re: /style=\{\{[^}]*\b(?:color|background|backgroundColor|borderColor|fill|stroke|fontSize|borderRadius|boxShadow)\s*:\s*["'`](?!var\()[^"'`]+["'`]/g,
  },
];

function* walk(dir) {
  for (const name of readdirSync(dir)) {
    if (SKIP_DIRS.has(name)) continue;
    const p = join(dir, name);
    const st = statSync(p);
    if (st.isDirectory()) yield* walk(p);
    else if (EXT.test(name) && !SKIP_FILE.test(name)) yield p;
  }
}

let files = 0;
for (const r of ROOTS) {
  const dir = join(root, r);
  if (!existsSync(dir)) continue;
  for (const file of walk(dir)) {
    const rel = relative(root, file);
    if (wholeFile.has(rel)) continue;
    files += 1;
    const lines = readFileSync(file, "utf8").split("\n");
    lines.forEach((line, i) => {
      for (const rule of RULES) {
        rule.re.lastIndex = 0;
        for (const m of line.matchAll(rule.re)) {
          const exempt = lineRules.findIndex((e) => e.path === rel && line.includes(e.match));
          if (exempt >= 0) {
            usedLineRules.add(exempt);
            continue;
          }
          problems.push(`${rel}:${i + 1}  ${rule.name}: ${m[0].slice(0, 60)}`);
        }
      }
    });
  }
}
lineRules.forEach((e, i) => {
  if (!usedLineRules.has(i) && existsSync(join(root, e.path))) problems.push(`allow-list: "${e.match}" in ${e.path} matches nothing now (remove the entry)`);
});

if (problems.length) {
  console.error(`design tokens: ${problems.length} problem${problems.length === 1 ? "" : "s"} (use a token from design/DESIGN.md, or add a reviewed entry to design/token-allowlist.json)`);
  for (const p of problems) console.error(`  - ${p}`);
  process.exit(1);
}
console.log(`design tokens: ${files} files checked, no hard-coded colours, font sizes or radii`);
