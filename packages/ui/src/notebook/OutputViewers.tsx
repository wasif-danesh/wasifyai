"use client";

import type {
  AudioScriptData,
  FlashcardsData,
  InfographicData,
  NotebookOutput,
  OverviewState,
  QuizData,
  SlidesData,
  TableData,
} from "@wasifyai/client";
import {
  ArrowLeft,
  ArrowRight,
  Check,
  ChevronDown,
  ChevronRight,
  Download,
  RotateCw,
  X,
} from "lucide-react";
import { type ReactNode, useEffect, useState } from "react";
import { Markdown } from "../chat/markdown";
import { cn } from "../cn";
import { Button } from "../components/button";
import { type MapNode, parseOutline } from "./outputs";

/** Cards one at a time: click or press Space to turn one over, arrows to move. */
export function FlashcardsViewer({ deck }: { deck: FlashcardsData }) {
  const [at, setAt] = useState(0);
  const [back, setBack] = useState(false);
  const card = deck.cards[at];
  const go = (to: number) => {
    setAt(Math.min(deck.cards.length - 1, Math.max(0, to)));
    setBack(false);
  };
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLElement && /INPUT|TEXTAREA|SELECT/.test(e.target.tagName)) return;
      if (e.key === "ArrowRight") go(at + 1);
      else if (e.key === "ArrowLeft") go(at - 1);
      else if (e.key === " ") {
        e.preventDefault();
        setBack((b) => !b);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });
  if (!card) return <p className="text-muted-foreground text-sm">This deck has no cards.</p>;
  return (
    <div className="grid grid-cols-[minmax(0,1fr)] gap-4">
      <p className="text-muted-foreground text-sm" aria-live="polite">
        Card {at + 1} of {deck.cards.length}
      </p>
      <button
        type="button"
        onClick={() => setBack((b) => !b)}
        aria-label={back ? "Show the question" : "Show the answer"}
        className={cn(
          "grid min-h-48 place-items-center rounded-2xl border p-6 text-center text-lg",
          back ? "border-primary bg-primary/5" : "bg-card",
        )}
      >
        <span className="grid gap-2">
          <span className="text-muted-foreground text-xs uppercase tracking-wide">
            {back ? "Answer" : "Question"}
          </span>
          {back ? card.back : card.front}
        </span>
      </button>
      <div className="flex items-center justify-between">
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={at === 0}
          onClick={() => go(at - 1)}
        >
          <ArrowLeft /> Previous
        </Button>
        <Button type="button" variant="ghost" size="sm" onClick={() => setBack((b) => !b)}>
          <RotateCw /> Turn over
        </Button>
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={at === deck.cards.length - 1}
          onClick={() => go(at + 1)}
        >
          Next <ArrowRight />
        </Button>
      </div>
    </div>
  );
}

/** One question at a time, the right answer shown with its reason, and a score at the end. */
export function QuizViewer({ quiz }: { quiz: QuizData }) {
  const [at, setAt] = useState(0);
  const [picked, setPicked] = useState<Record<number, number>>({});
  const q = quiz.questions[at];
  const done = at >= quiz.questions.length;
  const score = quiz.questions.filter((x, i) => picked[i] === x.answer_index).length;
  if (quiz.questions.length === 0)
    return <p className="text-muted-foreground text-sm">This quiz has no questions.</p>;
  if (done || !q) {
    return (
      <div className="grid gap-4 text-center">
        <p className="font-medium text-xl" aria-live="polite">
          You got {score} of {quiz.questions.length}
        </p>
        <div className="flex justify-center gap-2">
          <Button
            type="button"
            onClick={() => {
              setPicked({});
              setAt(0);
            }}
          >
            <RotateCw /> Try again
          </Button>
        </div>
      </div>
    );
  }
  const chosen = picked[at];
  const answered = chosen !== undefined;
  return (
    <div className="grid grid-cols-[minmax(0,1fr)] gap-4">
      <p className="text-muted-foreground text-sm">
        Question {at + 1} of {quiz.questions.length}
      </p>
      <h3 className="font-medium text-lg">{q.question}</h3>
      <ul className="grid gap-2">
        {q.options.map((option, i) => {
          const right = i === q.answer_index;
          return (
            <li key={option}>
              <button
                type="button"
                disabled={answered}
                onClick={() => setPicked((p) => ({ ...p, [at]: i }))}
                className={cn(
                  "flex w-full items-center gap-3 rounded-xl border px-4 py-2.5 text-start hover:bg-accent disabled:cursor-default disabled:hover:bg-transparent",
                  answered && right && "border-ok bg-ok/10",
                  answered && chosen === i && !right && "border-destructive bg-destructive/10",
                )}
              >
                <span className="grid size-5 shrink-0 place-items-center">
                  {answered && right ? <Check className="size-4" aria-label="Correct" /> : null}
                  {answered && chosen === i && !right ? (
                    <X className="size-4" aria-label="Wrong" />
                  ) : null}
                </span>
                {option}
              </button>
            </li>
          );
        })}
      </ul>
      {answered ? (
        <div className="grid gap-3">
          {q.explanation ? <p className="text-muted-foreground text-sm">{q.explanation}</p> : null}
          <div>
            <Button type="button" onClick={() => setAt(at + 1)}>
              {at + 1 === quiz.questions.length ? "See the score" : "Next question"} <ArrowRight />
            </Button>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function Branch({ node, depth }: { node: MapNode; depth: number }) {
  const [open, setOpen] = useState(depth < 1);
  if (node.children.length === 0) {
    return <li className="py-0.5 ps-6 text-sm">{node.label}</li>;
  }
  return (
    <li>
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1 py-0.5 text-start font-medium text-sm"
      >
        {open ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />}
        {node.label}
      </button>
      {open ? (
        <ul className="ms-3 border-s ps-2">
          {node.children.map((c) => (
            <Branch key={c.label} node={c} depth={depth + 1} />
          ))}
        </ul>
      ) : null}
    </li>
  );
}

/** The map as a tree you open branch by branch. */
export function MindMapViewer({ markdown }: { markdown: string }) {
  const { roots } = parseOutline(markdown);
  if (roots.length === 0) return <Markdown text={markdown} />;
  return (
    <ul className="grid gap-1" aria-label="Mind map">
      {roots.map((r) => (
        <Branch key={r.label} node={r} depth={0} />
      ))}
    </ul>
  );
}

/** The slides one at a time, with the notes under each. */
export function SlidesViewer({ deck }: { deck: SlidesData }) {
  const [at, setAt] = useState(0);
  const slide = deck.slides[at];
  if (!slide) return <p className="text-muted-foreground text-sm">This deck has no slides.</p>;
  return (
    <div className="grid grid-cols-[minmax(0,1fr)] gap-3">
      <p className="text-muted-foreground text-sm" aria-live="polite">
        Slide {at + 1} of {deck.slides.length}
      </p>
      <div className="grid min-h-48 content-start gap-3 rounded-xl border bg-card p-5">
        <h3 className="font-semibold text-lg">{slide.title}</h3>
        <ul className="list-disc space-y-1.5 ps-5">
          {slide.bullets.map((b) => (
            <li key={b}>{b}</li>
          ))}
        </ul>
      </div>
      {slide.notes ? (
        <p className="text-muted-foreground text-sm">
          <span className="font-medium">Notes: </span>
          {slide.notes}
        </p>
      ) : null}
      <div className="flex items-center justify-between">
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={at === 0}
          onClick={() => setAt(at - 1)}
        >
          <ArrowLeft /> Previous
        </Button>
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={at === deck.slides.length - 1}
          onClick={() => setAt(at + 1)}
        >
          Next <ArrowRight />
        </Button>
      </div>
    </div>
  );
}

/** The table as it is in the file. */
export function TableViewer({ table }: { table: TableData }) {
  return (
    <div className="overflow-auto rounded-lg border">
      <table className="w-full border-collapse text-start text-sm">
        <thead className="bg-muted/50">
          <tr>
            {table.columns.map((c) => (
              <th key={c} className="border-b px-3 py-1.5 text-start font-semibold">
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {table.rows.map((row) => (
            <tr key={row.join("\u0001")} className="border-b last:border-0">
              {row.map((cell, i) => (
                // biome-ignore lint/suspicious/noArrayIndexKey: a cell is its place in the row
                <td key={i} className="px-3 py-1.5 align-top">
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** What the audio overview needs to be spoken: the engine's calls for this one output. */
export type OverviewControl = {
  state: () => Promise<OverviewState>;
  start: () => Promise<OverviewState>;
  audio: () => Promise<Blob>;
  /** called when the voices are done, so the output is read again */
  changed: () => void;
};

function OverviewVoices({
  script,
  control,
}: { script: AudioScriptData; control: OverviewControl }) {
  const [src, setSrc] = useState<string | null>(null);
  const [job, setJob] = useState<OverviewState | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const working = job?.state === "working";

  // the sound, when it exists
  useEffect(() => {
    if (!script.audio) return;
    let gone = false;
    let url: string | null = null;
    control
      .audio()
      .then((b) => {
        if (gone) return;
        url = URL.createObjectURL(b);
        setSrc(url);
      })
      .catch(() => undefined);
    return () => {
      gone = true;
      if (url) URL.revokeObjectURL(url);
    };
  }, [script.audio, control]);

  // follow a job that is running (also one started before this screen was opened)
  useEffect(() => {
    let gone = false;
    const look = () =>
      control
        .state()
        .then((s) => {
          if (gone) return;
          setJob(s);
          if (s.state === "ready") control.changed();
        })
        .catch(() => undefined);
    void look();
    if (!working) {
      return () => {
        gone = true;
      };
    }
    const id = setInterval(() => void look(), 1000);
    return () => {
      gone = true;
      clearInterval(id);
    };
  }, [control, working]);

  async function start() {
    setProblem(null);
    try {
      setJob(await control.start());
    } catch (e) {
      setProblem(e instanceof Error ? e.message : "The voices could not be started.");
    }
  }

  return (
    <div className="grid gap-2 rounded-lg border p-3">
      {script.audio && src ? (
        // biome-ignore lint/a11y/useMediaCaption: the script is on the page, line by line
        <audio controls src={src} className="h-10 w-full" aria-label="The audio overview" />
      ) : null}
      {working ? (
        <output className="text-muted-foreground text-sm">
          Speaking turn {Math.min(job.done + 1, job.total)} of {job.total}…
        </output>
      ) : (
        <div className="flex flex-wrap items-center gap-2">
          <Button
            size="sm"
            variant={script.audio ? "outline" : "default"}
            onClick={() => void start()}
          >
            {script.audio ? "Make it again" : "Speak it"}
          </Button>
          <span className="text-muted-foreground text-xs">
            {script.audio
              ? "Two voices, made on this computer."
              : "Two voices read the conversation, made on this computer."}
          </span>
        </div>
      )}
      {job?.state === "failed" ? (
        <p role="alert" className="text-destructive text-sm">
          {job.message}
        </p>
      ) : null}
      {problem ? (
        <p role="alert" className="text-destructive text-sm">
          {problem}
        </p>
      ) : null}
    </div>
  );
}

/** The two hosts' script, and, when the speech engine is there, the conversation spoken. */
export function AudioScriptViewer({
  script,
  control,
}: {
  script: AudioScriptData;
  control?: OverviewControl;
}) {
  return (
    <div className="grid grid-cols-[minmax(0,1fr)] gap-3">
      {control ? (
        <OverviewVoices script={script} control={control} />
      ) : !script.audio ? (
        <p className="rounded-lg border border-dashed p-3 text-muted-foreground text-sm">
          This is the script of the conversation.
        </p>
      ) : null}
      <ul className="grid gap-3">
        {script.turns.map((t, i) => (
          // biome-ignore lint/suspicious/noArrayIndexKey: turns are spoken in this order
          <li key={i} className={cn("flex", t.speaker === 2 && "justify-end")}>
            <p
              className={cn(
                "max-w-[90%] rounded-2xl px-3.5 py-2 text-sm",
                t.speaker === 1 ? "bg-accent" : "bg-primary/10",
              )}
            >
              <span className="font-medium">{t.host}: </span>
              {t.text}
            </p>
          </li>
        ))}
      </ul>
    </div>
  );
}

/**
 * The picture, with the facts it was drawn from as exact text under it: an image model draws
 * letters and numbers imperfectly, so the text is what to trust.
 */
export function InfographicViewer({
  info,
  imageUrl,
}: {
  info: InfographicData;
  imageUrl?: (id: string) => Promise<string>;
}) {
  const [src, setSrc] = useState<string | null>(null);
  const id = info.image_id;
  useEffect(() => {
    if (!id || !imageUrl) return;
    let gone = false;
    imageUrl(id)
      .then((u) => !gone && setSrc(u))
      .catch(() => {});
    return () => {
      gone = true;
    };
  }, [id, imageUrl]);
  return (
    <div className="grid grid-cols-[minmax(0,1fr)] gap-4">
      {src ? (
        <img src={src} alt={info.title} className="w-full rounded-xl border" />
      ) : id ? (
        <p className="text-muted-foreground text-sm">Loading the picture…</p>
      ) : null}
      <p className="text-muted-foreground text-xs">
        The picture is drawn by an image model, which can misspell words and misdraw numbers. The
        facts below are exact.
      </p>
      <div className="grid gap-2">
        <h3 className="font-medium">{info.title}</h3>
        {info.summary ? <p className="text-sm">{info.summary}</p> : null}
        <ul className="grid gap-1.5">
          {info.sections.map((s) => (
            <li key={s.label} className="rounded-lg border p-2.5 text-sm">
              <span className="text-muted-foreground">{s.label}: </span>
              <span className="font-medium">{s.value}</span>
              {s.detail ? (
                <span className="block text-muted-foreground text-xs">{s.detail}</span>
              ) : null}
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

export type OutputViewerProps = {
  output: NotebookOutput;
  onBack: () => void;
  onDownload?: () => void;
  /** a place for more actions in the header (rename, delete) */
  actions?: ReactNode;
  /** A fresh link to a picture of the image product, for an infographic. */
  imageUrl?: (id: string) => Promise<string>;
  /** The calls that give an audio overview its voices (absent where there is no speech engine). */
  overview?: OverviewControl;
};

/** One output opened: the right viewer for its format, and the file to save. */
export function OutputViewer({
  output,
  onBack,
  onDownload,
  actions,
  imageUrl,
  overview,
}: OutputViewerProps) {
  let content: ReactNode;
  if (output.status !== "ready") {
    content = (
      <p className="text-muted-foreground text-sm">
        {output.status === "processing"
          ? "This is still being made."
          : (output.error ?? "This could not be made.")}
      </p>
    );
  } else if (output.format === "flashcards" && output.data) {
    content = <FlashcardsViewer deck={output.data as FlashcardsData} />;
  } else if (output.format === "quiz" && output.data) {
    content = <QuizViewer quiz={output.data as QuizData} />;
  } else if (output.format === "slides" && output.data) {
    content = <SlidesViewer deck={output.data as SlidesData} />;
  } else if (output.format === "datatable" && output.data) {
    content = <TableViewer table={output.data as TableData} />;
  } else if (output.format === "audio" && output.data) {
    content = <AudioScriptViewer script={output.data as AudioScriptData} control={overview} />;
  } else if (output.format === "infographic" && output.data) {
    content = <InfographicViewer info={output.data as InfographicData} imageUrl={imageUrl} />;
  } else if (output.format === "mindmap") {
    content = <MindMapViewer markdown={output.body ?? ""} />;
  } else {
    content = <Markdown text={output.body ?? ""} />;
  }
  return (
    <section aria-label="Output" className="flex h-full min-h-0 flex-col">
      <header className="flex items-center gap-2 border-b px-3 py-2.5">
        <Button
          type="button"
          variant="ghost"
          size="icon-sm"
          aria-label="Back to Studio"
          onClick={onBack}
        >
          <ArrowLeft />
        </Button>
        <h2 className="min-w-0 flex-1 truncate font-medium text-sm" title={output.title}>
          {output.title || "Untitled"}
        </h2>
        {output.has_file && onDownload ? (
          <Button
            type="button"
            variant="ghost"
            size="icon-sm"
            aria-label={`Save ${output.file_name ?? "the file"}`}
            onClick={onDownload}
          >
            <Download />
          </Button>
        ) : null}
        {actions}
      </header>
      <div className="min-h-0 flex-1 overflow-y-auto overflow-x-hidden px-4 py-4">
        <div className="grid grid-cols-[minmax(0,1fr)]">{content}</div>
      </div>
    </section>
  );
}
