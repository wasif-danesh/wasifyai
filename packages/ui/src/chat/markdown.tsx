import { Fragment, type ReactNode } from "react";

/**
 * A small, safe Markdown renderer for a model's answer: headings, paragraphs, lists, fenced and
 * inline code, bold, italic and http(s) links. It builds React nodes (never HTML strings), so nothing
 * a model writes can run as markup, and a link only opens as itself.
 */

const INLINE =
  /(`[^`\n]+`)|(\*\*[^*\n]+\*\*)|(__[^_\n]+__)|(\*[^*\n]+\*)|(\b_[^_\n]+_\b)|(\[[^\]\n]+\]\(https?:\/\/[^\s)]+\))/g;

export function inline(text: string): ReactNode[] {
  const out: ReactNode[] = [];
  let last = 0;
  let n = 0;
  for (const m of text.matchAll(INLINE)) {
    const at = m.index ?? 0;
    if (at > last) out.push(text.slice(last, at));
    const tok = m[0];
    const key = `i${n++}`;
    if (tok.startsWith("`")) {
      out.push(
        <code key={key} className="rounded bg-muted px-1 py-0.5 font-mono text-[0.9em]">
          {tok.slice(1, -1)}
        </code>,
      );
    } else if (tok.startsWith("**") || tok.startsWith("__")) {
      out.push(<strong key={key}>{tok.slice(2, -2)}</strong>);
    } else if (tok.startsWith("[")) {
      const close = tok.indexOf("](");
      out.push(
        <a
          key={key}
          href={tok.slice(close + 2, -1)}
          target="_blank"
          rel="noreferrer noopener"
          className="underline underline-offset-4"
        >
          {tok.slice(1, close)}
        </a>,
      );
    } else {
      out.push(<em key={key}>{tok.slice(1, -1)}</em>);
    }
    last = at + tok.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

type Block =
  | { kind: "code"; lang: string; text: string }
  | { kind: "heading"; level: number; text: string }
  | { kind: "ul" | "ol"; items: string[] }
  | { kind: "p"; text: string };

export function parseBlocks(src: string): Block[] {
  const blocks: Block[] = [];
  const lines = src.replace(/\r\n/g, "\n").split("\n");
  let i = 0;
  let para: string[] = [];
  const flush = () => {
    if (para.length) blocks.push({ kind: "p", text: para.join("\n") });
    para = [];
  };
  while (i < lines.length) {
    const line = lines[i] ?? "";
    const fence = /^```\s*([\w+-]*)\s*$/.exec(line);
    if (fence) {
      flush();
      const code: string[] = [];
      i++;
      while (i < lines.length && !/^```\s*$/.test(lines[i] ?? "")) code.push(lines[i++] ?? "");
      i++; // the closing fence (an unclosed block runs to the end: a stream may be mid-way)
      blocks.push({ kind: "code", lang: fence[1] ?? "", text: code.join("\n") });
      continue;
    }
    const heading = /^(#{1,4})\s+(.*)$/.exec(line);
    if (heading) {
      flush();
      blocks.push({ kind: "heading", level: (heading[1] ?? "#").length, text: heading[2] ?? "" });
      i++;
      continue;
    }
    const bullet = /^\s*[-*+]\s+(.*)$/.exec(line);
    const numbered = /^\s*\d+[.)]\s+(.*)$/.exec(line);
    if (bullet || numbered) {
      flush();
      const kind = bullet ? "ul" : "ol";
      const items: string[] = [];
      while (i < lines.length) {
        const m = (kind === "ul" ? /^\s*[-*+]\s+(.*)$/ : /^\s*\d+[.)]\s+(.*)$/).exec(
          lines[i] ?? "",
        );
        if (!m) break;
        items.push(m[1] ?? "");
        i++;
      }
      blocks.push({ kind, items });
      continue;
    }
    if (line.trim() === "") {
      flush();
      i++;
      continue;
    }
    para.push(line);
    i++;
  }
  flush();
  return blocks;
}

export function Markdown({ text }: { text: string }) {
  const blocks = parseBlocks(text);
  return (
    <div className="grid gap-3 break-words leading-relaxed">
      {blocks.map((b, n) => {
        const key = `b${n}`;
        switch (b.kind) {
          case "code":
            return (
              <pre
                key={key}
                className="overflow-auto rounded-lg border bg-muted/50 p-3 font-mono text-[0.85rem]"
                data-lang={b.lang || undefined}
              >
                <code>{b.text}</code>
              </pre>
            );
          case "heading":
            return (
              <p key={key} className="font-semibold text-[1.05rem]">
                {inline(b.text)}
              </p>
            );
          case "ul":
            return (
              <ul key={key} className="list-disc ps-6">
                {b.items.map((it, j) => (
                  // biome-ignore lint/suspicious/noArrayIndexKey: parsed from text, never reordered
                  <li key={`${key}-${j}`}>{inline(it)}</li>
                ))}
              </ul>
            );
          case "ol":
            return (
              <ol key={key} className="list-decimal ps-6">
                {b.items.map((it, j) => (
                  // biome-ignore lint/suspicious/noArrayIndexKey: parsed from text, never reordered
                  <li key={`${key}-${j}`}>{inline(it)}</li>
                ))}
              </ol>
            );
          default:
            return (
              <p key={key}>
                {b.text.split("\n").map((l, j) => (
                  // biome-ignore lint/suspicious/noArrayIndexKey: lines of one paragraph, never reordered
                  <Fragment key={`${key}-${j}`}>
                    {j > 0 ? <br /> : null}
                    {inline(l)}
                  </Fragment>
                ))}
              </p>
            );
        }
      })}
    </div>
  );
}
