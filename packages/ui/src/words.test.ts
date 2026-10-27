import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { AVOID, appearsHere, makeLabel, makingLabel, plural } from "./words";

/**
 * How often the screens still say a word the design guide avoids, in what a person reads (JSX text and quoted
 * sentences; not identifiers, not class names). The numbers are the state on 2026-10-27, when stage U1 of the UI
 * plan added `words.ts` (stage U3 lowered "generate" to 1 and "image" to 28 when it rebuilt the Images screen). A
 * later stage lowers a number when it rewrites a screen; this test keeps a number from going up. Lower a number
 * here when the run says it can be lowered.
 */
const BASELINE: Record<string, number> = { generate: 1, image: 28, asset: 0, Takes: 4 };

function files(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) files(p, out);
    else if (p.endsWith(".tsx") && !p.endsWith(".test.tsx")) out.push(p);
  }
  return out;
}

/** The sentences of a screen: JSX text between tags, and quoted strings with a space in them. */
function sentences(source: string): string[] {
  const out: string[] = [];
  for (const m of source.matchAll(/>([^<>{}]*[A-Za-z][^<>{}]*)</g)) out.push(m[1] ?? "");
  // a label on its own, such as {busy ? "Making…" : "Generate"}
  for (const m of source.matchAll(/"([A-Z][a-z]+)"/g)) out.push(m[1] ?? "");
  for (const m of source.matchAll(/"([^"\n]* [^"\n]*)"/g)) {
    const s = m[1] ?? "";
    if (!/^[\w\s:/\-[\]().,*&>%!=#@']*$/.test(s) || /[a-z]/.test(s)) {
      if (!/[-:[\]]\w+[-:[\]]|className|\$\{|\/\//.test(s)) out.push(s);
    }
  }
  return out;
}

/** A word written with a capital ("Takes", the label) is matched as written; the others in any case. */
function count(word: string, text: string): number {
  const flags = /^[A-Z]/.test(word) ? "g" : "gi";
  return (text.match(new RegExp(`\\b${word}s?\\b`, flags)) ?? []).length;
}

describe("the words", () => {
  it("make one label per noun", () => {
    expect(makeLabel("picture")).toBe("Make the picture");
    expect(makeLabel("model3d")).toBe("Make the 3D model");
    expect(makingLabel("song")).toBe("Making your song…");
    expect(appearsHere("video")).toBe("Your video appears here.");
    expect(plural("picture")).toBe("pictures");
    expect(plural("speech")).toBe("speeches");
  });

  it("do not drift back into the screens", () => {
    const text = files(__dirname)
      .filter((f) => !f.includes("/components/"))
      .flatMap((f) => sentences(readFileSync(f, "utf8")))
      .join("\n");
    const now: Record<string, number> = {};
    for (const word of Object.keys(AVOID)) now[word] = count(word, text);
    for (const [word, n] of Object.entries(now)) {
      expect(
        n,
        `"${word}" (say "${AVOID[word]}") appears ${n} times; the baseline is ${BASELINE[word]}`,
      ).toBeLessThanOrEqual(BASELINE[word] ?? 0);
    }
    const lower = Object.entries(now).filter(([w, n]) => n < (BASELINE[w] ?? 0));
    if (lower.length)
      console.info(`words.test: the baseline can be lowered: ${JSON.stringify(now)}`);
  });
});
