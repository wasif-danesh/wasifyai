#!/usr/bin/env node
// Reads design/DESIGN.md (ADR-0081): the fenced JSON block tagged `tokens`. Validates it, then writes
//   packages/ui/src/tokens.generated.css     the CSS variables and the Tailwind @theme values
//   packages/ui/src/tokens.gen.ts      the resolved values, for the catalogue and tests
//   docs/design-system/tokens.md             a table of every token
// `--check` writes nothing and fails if a file on disk differs from what would be written, or if validation fails.
// `--use <name>` puts the tokens block of design/themes/<name>.md into design/DESIGN.md first, then builds.
// No dependencies: Node 22 only.
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const DESIGN = join(root, "design/DESIGN.md");
const OUT_CSS = join(root, "packages/ui/src/tokens.generated.css");
const OUT_TS = join(root, "packages/ui/src/tokens.gen.ts");
const OUT_DOC = join(root, "docs/design-system/tokens.md");
const BASE_CSS = join(root, "packages/ui/src/tailwind.css");

const args = process.argv.slice(2);
const check = args.includes("--check");
const useIdx = args.indexOf("--use");
if (useIdx >= 0) {
  const name = args[useIdx + 1];
  const src = join(root, "design/themes", `${name}.md`);
  if (!name || !existsSync(src)) fail([`design/themes/${name}.md does not exist`]);
  // A theme file holds only a tokens block; the rules (the prose) stay in DESIGN.md.
  const block = readFileSync(src, "utf8").match(/```json tokens\n[\s\S]*?\n```/);
  if (!block) fail([`design/themes/${name}.md has no fenced block tagged \`json tokens\``]);
  const current = readFileSync(DESIGN, "utf8");
  if (!/```json tokens\n[\s\S]*?\n```/.test(current)) fail(["design/DESIGN.md has no tokens block to replace"]);
  writeFileSync(DESIGN, current.replace(/```json tokens\n[\s\S]*?\n```/, () => block[0]));
}

// ---------------------------------------------------------------------------------------------- the schema
// Every template must define all of these CSS variables: this is what makes a template swappable.
const REQUIRED = [
  "--bg", "--surface", "--surface-solid", "--surface-2", "--text", "--muted", "--border",
  "--accent", "--accent-2", "--accent-3", "--on-accent", "--accent-soft",
  "--ok", "--warn", "--danger", "--ok-soft", "--on-ok-soft", "--scrim", "--on-scrim",
  "--radius-sm", "--radius", "--radius-lg", "--radius-control", "--shadow",
  "--font", "--font-serif", "--space",
  "--text-step--1", "--text-step-0", "--text-step-1", "--text-step-2", "--text-step-3",
  "--text-2xs", "--text-ui-sm", "--text-ui", "--text-ui-lg", "--text-lead", "--text-title", "--text-display", "--text-display-lg",
  "--ease-out-soft",
];

function fail(errors) {
  console.error(`design: ${errors.length} problem${errors.length === 1 ? "" : "s"}`);
  for (const e of errors) console.error(`  - ${e}`);
  process.exit(1);
}

// ---------------------------------------------------------------------------------------------- read
const md = readFileSync(DESIGN, "utf8");
const m = md.match(/```json tokens\n([\s\S]*?)\n```/);
if (!m) fail(["design/DESIGN.md has no fenced block tagged `json tokens`"]);
let doc;
try {
  doc = JSON.parse(m[1]);
} catch (e) {
  fail([`the tokens block is not valid JSON: ${e.message}`]);
}

const errors = [];
const warnings = [];

// flatten the primitive tree into { "color.violet.600": "oklch(...)" }
const primitives = {};
(function walk(node, path) {
  if (node && typeof node === "object" && "$value" in node) {
    primitives[path.join(".")] = node.$value;
    return;
  }
  for (const [k, v] of Object.entries(node ?? {})) walk(v, [...path, k]);
})(doc.primitive, []);

// semantic tokens: a flat map name -> { css, value, type, description }
const semantic = [];
(function walk(node, path) {
  if (node && typeof node === "object" && "$value" in node) {
    semantic.push({
      path: path.join("."),
      css: node.css ?? `--${path.slice(1).join("-")}`,
      type: node.$type ?? "other",
      value: node.$value,
      description: node.$description ?? "",
    });
    return;
  }
  for (const [k, v] of Object.entries(node ?? {})) walk(v, [...path, k]);
})(doc.semantic, []);

const byCss = new Map(semantic.map((t) => [t.css, t]));
const byPath = new Map(semantic.map((t) => [t.path, t]));

// ---------------------------------------------------------------------------------------------- aliases
// {primitive.color.violet.600} -> its literal; {color.accent} -> var(--accent) in CSS, or its value when evaluating.
function expand(str, mode, asVar) {
  return str.replace(/\{([^}]+)\}/g, (_, p) => {
    if (p.startsWith("primitive.")) {
      const v = primitives[p.slice("primitive.".length)];
      if (v === undefined) {
        errors.push(`alias {${p}} points to nothing`);
        return "";
      }
      return v;
    }
    const t = byPath.get(p);
    if (!t) {
      errors.push(`alias {${p}} points to nothing`);
      return "";
    }
    return asVar ? `var(${t.css})` : modeValue(t, mode, false);
  });
}
function modeValue(t, mode, asVar) {
  const v = typeof t.value === "object" ? t.value[mode] : t.value;
  if (v === undefined) {
    errors.push(`${t.path} has no ${mode} value`);
    return "";
  }
  return expand(String(v), mode, asVar);
}
const isPair = (t) => typeof t.value === "object";
function cssValue(t) {
  if (!isPair(t)) return modeValue(t, "light", true);
  const l = modeValue(t, "light", true);
  const d = modeValue(t, "dark", true);
  return l === d ? l : `light-dark(${l}, ${d})`;
}

// ---------------------------------------------------------------------------------------------- colour maths
// OKLCH -> linear sRGB (Ottosson), WCAG relative luminance and contrast ratio.
function parseOklch(s) {
  const mm = s.trim().match(/^oklch\(\s*([\d.]+)%\s+([\d.]+)\s+([\d.]+)(?:\s*\/\s*([\d.]+))?\s*\)$/);
  if (!mm) return null;
  return { L: +mm[1] / 100, C: +mm[2], h: +mm[3], a: mm[4] === undefined ? 1 : +mm[4] };
}
function toLinear({ L, C, h }) {
  const a = C * Math.cos((h * Math.PI) / 180);
  const b = C * Math.sin((h * Math.PI) / 180);
  const l_ = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3;
  const m_ = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3;
  const s_ = (L - 0.0894841775 * a - 1.291485548 * b) ** 3;
  return [
    4.0767416621 * l_ - 3.3077115913 * m_ + 0.2309699292 * s_,
    -1.2684380046 * l_ + 2.6097574011 * m_ - 0.3413193965 * s_,
    -0.0041960863 * l_ - 0.7034186147 * m_ + 1.707614701 * s_,
  ];
}
const inGamut = (lin) => lin.every((v) => v >= -0.001 && v <= 1.001);
const clamp01 = (x) => Math.max(0, Math.min(1, x));
const encode = (x) => {
  x = clamp01(x);
  return x <= 0.0031308 ? 12.92 * x : 1.055 * x ** (1 / 2.4) - 0.055;
};
const luminance = (lin) => 0.2126 * clamp01(lin[0]) + 0.7152 * clamp01(lin[1]) + 0.0722 * clamp01(lin[2]);
const hex = (lin) => `#${lin.map((v) => Math.round(encode(v) * 255).toString(16).padStart(2, "0")).join("")}`;
function contrast(a, b) {
  const la = luminance(a);
  const lb = luminance(b);
  return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
}

// A colour to { lin: [r,g,b], alpha }: oklch(...) literals, and color-mix(in oklch, <colour> P%, transparent).
function colourOf(expr, mode) {
  const e = expr.trim();
  const direct = parseOklch(e);
  if (direct) return { lin: toLinear(direct), alpha: direct.a, gamutOk: inGamut(toLinear(direct)) };
  const mix = e.match(/^color-mix\(in oklch,\s*(.+?)\s+([\d.]+)%,\s*transparent\)$/);
  if (mix) {
    const inner = colourOf(mix[1], mode);
    return inner && { ...inner, alpha: inner.alpha * (+mix[2] / 100) };
  }
  const v = e.match(/^var\((--[\w-]+)\)$/);
  if (v) {
    const t = byCss.get(v[1]);
    return t ? colourOf(modeValue(t, mode, false), mode) : null;
  }
  return null;
}
function over(fg, bg) {
  const a = fg.alpha;
  return fg.lin.map((c, i) => c * a + bg.lin[i] * (1 - a));
}

// ---------------------------------------------------------------------------------------------- validation
// 1. completeness
for (const name of REQUIRED) if (!byCss.has(name)) errors.push(`required token ${name} is missing`);
if (!doc.meta?.id || !doc.meta?.version) errors.push("meta.id and meta.version are required");

// 2. every colour: parseable, and inside sRGB (a template can set checks.gamut to "warn"; the default is an error)
for (const t of semantic) {
  if (t.type !== "color") continue;
  for (const mode of isPair(t) ? ["light", "dark"] : ["light"]) {
    const c = colourOf(modeValue(t, mode, false), mode);
    if (!c) errors.push(`${t.path} (${mode}) is not a colour this tool understands: ${modeValue(t, mode, false)}`);
    else if (!c.gamutOk && c.gamutOk !== undefined)
      (doc.checks?.gamut === "warn" ? warnings : errors).push(`${t.path} (${mode}) is outside sRGB and would be clipped`);
  }
}

// 3. contrast (WCAG 2.2 AA): each rule is [foreground, background, minimum ratio, optional backdrop for transparent backgrounds]
const contrastRows = [];
for (const rule of doc.checks?.contrast ?? []) {
  const [fgName, bgName, min, backdropName] = rule;
  const fgT = byCss.get(fgName);
  const bgT = byCss.get(bgName);
  const bdT = backdropName ? byCss.get(backdropName) : null;
  if (!fgT || !bgT || (backdropName && !bdT)) {
    errors.push(`contrast rule ${JSON.stringify(rule)} names a token that does not exist`);
    continue;
  }
  for (const mode of ["light", "dark"]) {
    const bgC = colourOf(modeValue(bgT, mode, false), mode);
    const fgC = colourOf(modeValue(fgT, mode, false), mode);
    if (!bgC || !fgC) continue;
    let bgLin = bgC.lin;
    if (bgC.alpha < 1) {
      const back = bdT ? colourOf(modeValue(bdT, mode, false), mode) : null;
      if (!back) {
        errors.push(`contrast rule ${JSON.stringify(rule)}: ${bgName} is transparent and needs a backdrop token as the fourth item`);
        continue;
      }
      bgLin = over(bgC, back);
    }
    const fgLin = fgC.alpha < 1 ? over(fgC, { lin: bgLin }) : fgC.lin;
    const ratio = contrast(fgLin, bgLin);
    contrastRows.push({ fg: fgName, bg: bgName, mode, min, ratio });
    if (ratio + 1e-9 < min) errors.push(`contrast ${fgName} on ${bgName} (${mode}) is ${ratio.toFixed(2)}:1, needs ${min}:1`);
  }
}

// 4. the base stylesheet still switches motion off for people who ask for less
if (existsSync(BASE_CSS) && !/prefers-reduced-motion:\s*reduce/.test(readFileSync(BASE_CSS, "utf8")))
  errors.push("packages/ui/src/tailwind.css no longer has a prefers-reduced-motion rule");

if (errors.length) fail(errors);

// ---------------------------------------------------------------------------------------------- outputs
const groups = { root: [], theme: [] };
for (const t of semantic) (t.type === "dimension-theme" || t.type === "cubicBezier" ? groups.theme : groups.root).push(t);

const header = (what) =>
  `/* ${what}. GENERATED from design/DESIGN.md by scripts/design/build-tokens.mjs (ADR-0081). Do not edit by hand:\n   change design/DESIGN.md and run \`pnpm design:build\`. Template: ${doc.meta.id} ${doc.meta.version}. */\n`;

let css = header("The design tokens") + "\n:root {\n  color-scheme: light dark;\n";
let lastGroup = "";
for (const t of groups.root) {
  const grp = t.path.split(".")[0];
  if (grp !== lastGroup) {
    css += `${lastGroup ? "\n" : ""}`;
    lastGroup = grp;
  }
  css += `  ${t.css}: ${cssValue(t)};\n`;
}
css += "}\n\n/* sizes and easing that Tailwind reads as theme values (fluid type steps, the soft ease) */\n@theme {\n";
for (const t of groups.theme) css += `  ${t.css}: ${cssValue(t)};\n`;
css += "}\n";

const resolved = {};
for (const t of semantic) {
  resolved[t.css] = isPair(t)
    ? { light: modeValue(t, "light", false), dark: modeValue(t, "dark", false) }
    : modeValue(t, "light", false);
}
const bgT = byCss.get("--bg");
const themeColor = {
  light: hex(colourOf(modeValue(bgT, "light", false), "light").lin),
  dark: hex(colourOf(modeValue(bgT, "dark", false), "dark").lin),
};
const ts =
  header("The resolved design tokens, for the catalogue and tests") +
  `\nexport const templateId = ${JSON.stringify(doc.meta.id)};\nexport const templateVersion = ${JSON.stringify(doc.meta.version)};\n\n` +
  `/** The page background as hex, for the browser's own chrome (the \`theme-color\` meta tag). */\nexport const themeColor = ${JSON.stringify(themeColor)} as const;\n\n/** CSS variable name -> value, or { light, dark } where the colour differs by scheme. */\nexport const tokens = ${JSON.stringify(resolved, null, 2)} as const;\n\nexport type TokenName = keyof typeof tokens;\n`;

let docMd = `# Design tokens\n\nGenerated from \`design/DESIGN.md\` (template **${doc.meta.id}**, version ${doc.meta.version}) by \`scripts/design/build-tokens.mjs\`. Do not edit by hand.\n\n`;
docMd += "| Token | CSS variable | Type | Light | Dark | Use |\n|---|---|---|---|---|---|\n";
for (const t of semantic) {
  const l = modeValue(t, "light", false);
  const d = isPair(t) ? modeValue(t, "dark", false) : "same";
  const swatch = (s) => (parseOklch(s) ? `\`${s}\` ≈ \`${hex(toLinear(parseOklch(s)))}\`` : `\`${s}\``);
  docMd += `| \`${t.path}\` | \`${t.css}\` | ${t.type} | ${swatch(l)} | ${d === "same" ? "same" : swatch(d)} | ${t.description} |\n`;
}
if (contrastRows.length) {
  docMd += "\n## Contrast checks (WCAG 2.2 AA)\n\n| Foreground | Background | Scheme | Ratio | Needs |\n|---|---|---|---|---|\n";
  for (const r of contrastRows) docMd += `| \`${r.fg}\` | \`${r.bg}\` | ${r.mode} | ${r.ratio.toFixed(2)}:1 | ${r.min}:1 |\n`;
}

const outputs = [
  [OUT_CSS, css],
  [OUT_TS, ts],
  [OUT_DOC, docMd],
];
if (check) {
  const stale = outputs.filter(([p, body]) => !existsSync(p) || readFileSync(p, "utf8") !== body).map(([p]) => p.replace(`${root}/`, ""));
  if (stale.length) fail([`generated files are out of date, run \`pnpm design:build\`: ${stale.join(", ")}`]);
  console.log(`design: ${semantic.length} tokens, ${contrastRows.length} contrast checks, generated files are current (${doc.meta.id} ${doc.meta.version})`);
} else {
  for (const [p, body] of outputs) {
    mkdirSync(dirname(p), { recursive: true });
    writeFileSync(p, body);
  }
  for (const w of warnings) console.warn(`design: warning: ${w}`);
  console.log(`design: wrote ${outputs.length} files from ${doc.meta.id} ${doc.meta.version} (${semantic.length} tokens, ${contrastRows.length} contrast checks)`);
}
