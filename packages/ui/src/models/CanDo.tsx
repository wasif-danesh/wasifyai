"use client";

import { useEffect, useState } from "react";
import { formatBytes } from "../notebook/format";
import { useChoicesFor, useChoicesVersion } from "./context";
import { displayName } from "./copy";
import { type Readiness, ReadyDot } from "./marks";
import { GROUPS, type GroupId } from "./types";

type Line = { state: Readiness; text: string };

/** Groups whose tools use the ready model by themselves (each voice tool has its default): none is "chosen" here. */
const BY_ITSELF = new Set<GroupId>(["voice", "listening", "music", "faces"]);

/** One job: what it uses here and whether that is ready, from the same list the model button reads. */
function JobLine({ group, title }: { group: GroupId; title: string }) {
  const api = useChoicesFor(group);
  const version = useChoicesVersion();
  const [line, setLine] = useState<Line | null>(null);
  // biome-ignore lint/correctness/useExhaustiveDependencies: the version is the trigger
  useEffect(() => {
    if (!api) return;
    let gone = false;
    const read = () =>
      api
        .list()
        .then((l) => {
          if (gone) return;
          const chosen = l.choices.find((c) => c.chosen);
          const here = l.choices.filter((c) => c.state === "ready");
          if (chosen?.state === "ready")
            setLine({ state: "ready", text: `Ready: ${displayName(chosen.title)}` });
          else if (chosen)
            setLine({ state: "needs", text: `Needs a download: ${displayName(chosen.title)}` });
          else if (here.length > 0 && BY_ITSELF.has(group))
            setLine({
              state: "ready",
              text: `Ready: ${here
                .slice(0, 2)
                .map((c) => displayName(c.title))
                .join(", ")}${here.length > 2 ? ` and ${here.length - 2} more` : ""}`,
            });
          else if (here.length > 0)
            setLine({ state: "none", text: "A model is here; choose it on the model button" });
          else if (l.choices.some((c) => c.state === "needs_download"))
            setLine({ state: "needs", text: "Needs a download" });
          else setLine({ state: "cannot", text: "Not on this computer" });
        })
        .catch(() => !gone && setLine(null));
    void read();
    // what runs in another tool (Ollama, LM Studio) is found a moment after the app starts: read again, then now and then
    const soon = [setTimeout(read, 3000), setTimeout(read, 10_000)];
    const every = setInterval(read, 30_000);
    return () => {
      gone = true;
      for (const t of soon) clearTimeout(t);
      clearInterval(every);
    };
  }, [api, version, group]);
  if (!api || !line) return null;
  return (
    <li className="flex min-w-0 items-center gap-2 text-sm">
      <ReadyDot state={line.state} />
      <span className="w-24 shrink-0 font-medium">{title}</span>
      <span className="min-w-0 truncate text-muted-foreground">{line.text}</span>
    </li>
  );
}

/** Memory and free disk of this computer. */
function MachineLine() {
  const api = useChoicesFor("chat");
  const [text, setText] = useState<string | null>(null);
  useEffect(() => {
    if (!api) return;
    api
      .list()
      .then((l) => {
        const parts = [
          l.memoryBytes !== null ? `${formatBytes(l.memoryBytes)} of memory` : null,
          l.diskFreeBytes !== null ? `${formatBytes(l.diskFreeBytes)} free on the disk` : null,
        ].filter(Boolean);
        setText(parts.length > 0 ? parts.join(", ") : null);
      })
      .catch(() => setText(null));
  }, [api]);
  return text ? <p className="m-0 text-muted-foreground text-sm">This computer: {text}.</p> : null;
}

/**
 * What this computer can do (ADR-0093 U11): each job, what it uses and whether that is ready, and the memory and disk
 * it has, in words, at the top of Settings. The same facts the model button and the Models page show.
 */
export function ComputerCanDo() {
  return (
    <section aria-labelledby="can-do" className="grid gap-3 rounded-xl border bg-card p-5">
      <h2 id="can-do" className="m-0 font-semibold text-base">
        What this computer can do
      </h2>
      <MachineLine />
      <ul className="m-0 grid list-none gap-1.5 p-0">
        {GROUPS.map((g) => (
          <JobLine key={g.id} group={g.id} title={g.title} />
        ))}
      </ul>
    </section>
  );
}
