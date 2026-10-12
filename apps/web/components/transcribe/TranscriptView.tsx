"use client";

import { Notice } from "@/components/Notice";
import { DeleteControls } from "@/components/create/shared";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { clock, fullDate } from "@/lib/format";
import { actions, eyebrow, panel } from "@/lib/styles";
import { cn } from "@/lib/utils";
import type { TranscriptDetail } from "@wasifyai/contracts";
import { Check, ChevronDown, Copy } from "lucide-react";
import { useEffect, useState } from "react";

const POLL_MS = 10_000;
const FORMATS = [
  ["txt", "Plain text (.txt)"],
  ["srt", "Subtitles (.srt)"],
  ["vtt", "Web subtitles (.vtt)"],
  ["json", "Data (.json)"],
] as const;

/** One transcript: the words (plain, or with the time of each line), copy, downloads in four formats, and a
 * two-step delete. While it is being made it checks again until it is ready. The words are text, never HTML. */
export function TranscriptView({ initial }: { initial: TranscriptDetail }) {
  const [t, setT] = useState(initial);
  const [view, setView] = useState<"text" | "timed">("text");
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (t.status !== "working") return;
    const timer = setInterval(async () => {
      try {
        const res = await fetch(`/api/products/wasifyai-stt/transcripts/${t.id}`);
        if (res.ok) setT((await res.json()) as TranscriptDetail);
      } catch {
        // try again at the next tick
      }
    }, POLL_MS);
    return () => clearInterval(timer);
  }, [t.id, t.status]);

  async function copy() {
    try {
      await navigator.clipboard.writeText(t.text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // the clipboard can be blocked; the text is selectable on the page
    }
  }

  const download = (format: string) =>
    `/api/products/wasifyai-stt/transcripts/${t.id}/download?format=${format}`;

  return (
    <article className={cn(panel, "@container")}>
      <div className="grid gap-[0.9rem]">
        <span className={eyebrow}>
          {t.language_name || t.language} · {clock(t.seconds)} · {fullDate(t.created_at)}
        </span>
        {t.status === "working" ? (
          <Notice tone="info" title="Your recording is being transcribed">
            This takes a few minutes for a long recording. You can leave this page: it will be here
            when it's ready, and we'll tell you.
          </Notice>
        ) : t.status === "failed" ? (
          <Notice tone="error" title="This recording couldn't be transcribed">
            {t.error ?? "Please try again."}
          </Notice>
        ) : (
          <>
            <h1
              className="text-step-2 leading-[1.1] font-semibold tracking-[-0.025em]"
              lang={t.language}
            >
              {t.title}
            </h1>
            <div className={actions}>
              <Button type="button" variant="outline" onClick={copy}>
                {copied ? <Check aria-hidden="true" /> : <Copy aria-hidden="true" />}
                {copied ? "Copied" : "Copy"}
              </Button>
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button type="button">
                    Download <ChevronDown aria-hidden="true" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="start">
                  {FORMATS.map(([format, label]) => (
                    <DropdownMenuItem key={format} asChild>
                      <a href={download(format)} download>
                        {label}
                      </a>
                    </DropdownMenuItem>
                  ))}
                </DropdownMenuContent>
              </DropdownMenu>
              <ToggleGroup
                type="single"
                value={view}
                onValueChange={(v) => v && setView(v as "text" | "timed")}
                variant="outline"
                size="sm"
                aria-label="How to show the words"
              >
                <ToggleGroupItem value="text">Text</ToggleGroupItem>
                <ToggleGroupItem value="timed">Timestamps</ToggleGroupItem>
              </ToggleGroup>
            </div>
            {view === "text" ? (
              <p
                lang={t.language}
                className="max-h-[36rem] overflow-y-auto rounded-lg border bg-background p-4 leading-[1.7] whitespace-pre-wrap"
              >
                {t.text}
              </p>
            ) : (
              <ol
                lang={t.language}
                className="grid max-h-[36rem] list-none gap-2 overflow-y-auto rounded-lg border bg-background p-4 leading-[1.6]"
              >
                {t.segments.map((s) => (
                  <li key={`${s.start}-${s.end}`} className="grid grid-cols-[4.5rem_1fr] gap-3">
                    <time className="text-muted-foreground tabular-nums">{clock(s.start)}</time>
                    <span>{s.text}</span>
                  </li>
                ))}
              </ol>
            )}
          </>
        )}
        <div className={actions}>
          {t.status === "working" ? null : (
            <DeleteControls
              url={`/api/products/wasifyai-stt/transcripts/${t.id}`}
              noun="transcript"
              label={t.status === "failed" ? "Remove" : "Delete"}
            />
          )}
        </div>
      </div>
    </article>
  );
}
