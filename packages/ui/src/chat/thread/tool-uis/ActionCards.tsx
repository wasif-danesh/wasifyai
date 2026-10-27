"use client";
// The cards of the meta-tools (ADR-0071 decision 3): what a proposed action came to, the guides how_to found, and the
// button open_screen offers. Plain text only: everything shown came from the assistant or the app's own files.
import type { ChatPart } from "@wasifyai/client";
import { BookOpen, ExternalLink, Wrench } from "lucide-react";
import { Button } from "../../../components/button";
import { Spinner } from "../../../components/spinner";

type Tool = Extract<ChatPart, { type: "tool" }>;

/** The creation a result names, by the id key an action's output uses. */
const CREATION_KEYS: Record<string, string> = {
  image_id: "image",
  track_id: "track",
  speech_id: "speech",
  transcript_id: "transcript",
  video_id: "video",
  voice_id: "voice",
  lipsync_id: "lipsync",
  notebook_id: "notebook",
};

function creationOf(output: Record<string, unknown> | undefined): [string, string] | null {
  for (const [key, kind] of Object.entries(CREATION_KEYS)) {
    const id = output?.[key];
    if (typeof id === "string" && id) return [kind, id];
  }
  return null;
}

/** What a proposed action came to, for an action without a card of its own (speech, video, a notebook ...). */
export function ActionResultCard({
  tool,
  onOpenCreation,
  onOpenScreen,
}: {
  tool: Tool;
  onOpenCreation?: (kind: string, id: string) => void;
  onOpenScreen?: (screenId: string) => void;
}) {
  if (tool.status === "running") {
    const pct = typeof tool.progress === "number" ? Math.round(tool.progress * 100) : null;
    return (
      <output className="flex items-center gap-3 rounded-lg border p-3 text-sm">
        <Spinner />
        <span>
          {tool.jobStatus === "queued"
            ? "Waiting for a turn"
            : pct !== null && pct > 0
              ? `Working on it, ${pct}%`
              : "Working on it"}
        </span>
      </output>
    );
  }
  const out = tool.output ?? {};
  const message = typeof out.message === "string" ? out.message : "";
  const made = tool.status === "ok" ? creationOf(out) : null;
  const setup = typeof out.setup === "string" ? out.setup : "";
  const screen = typeof out.screen === "string" ? out.screen : "";
  return (
    <div className="grid max-w-md gap-2 rounded-lg border p-3 text-sm">
      <p className="flex items-start gap-2">
        <Wrench className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
        <span dir="auto" className="min-w-0 break-words">
          {message ||
            (tool.status === "ok"
              ? "Done."
              : tool.status === "refused"
                ? "That was not done."
                : "That could not be done.")}
        </span>
      </p>
      {setup ? <p className="text-muted-foreground">{setup}</p> : null}
      <div className="flex flex-wrap gap-2">
        {made && onOpenCreation ? (
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={() => onOpenCreation(made[0], made[1])}
          >
            Open
          </Button>
        ) : null}
        {setup && screen && onOpenScreen ? (
          <Button type="button" size="sm" variant="outline" onClick={() => onOpenScreen(screen)}>
            Go there
          </Button>
        ) : null}
      </div>
    </div>
  );
}

type Guide = { action: string; title: string; screen?: string | null; where?: string };

function guidesOf(output: Record<string, unknown> | undefined): Guide[] {
  const raw = output?.guides;
  if (!Array.isArray(raw)) return [];
  return raw.flatMap((g): Guide[] => {
    if (!g || typeof g !== "object") return [];
    const r = g as Record<string, unknown>;
    if (typeof r.action !== "string" || typeof r.title !== "string") return [];
    return [
      {
        action: r.action,
        title: r.title,
        screen: typeof r.screen === "string" ? r.screen : null,
        where: typeof r.where === "string" ? r.where : "",
      },
    ];
  });
}

/** The guides how_to read: their names and where the screen is, with a way to go there. */
export function GuideCard({
  tool,
  onOpenScreen,
}: {
  tool: Tool;
  onOpenScreen?: (screenId: string) => void;
}) {
  if (tool.status === "running")
    return (
      <output className="flex items-center gap-2 text-muted-foreground text-sm">
        <Spinner /> Looking it up
      </output>
    );
  const guides = guidesOf(tool.output);
  if (!guides.length) return null;
  return (
    <ul className="m-0 grid list-none gap-1 p-0 text-sm">
      {guides.map((g) => (
        <li key={g.action} className="flex flex-wrap items-center gap-2">
          <BookOpen className="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
          <span>{g.title}</span>
          {g.where ? <span className="text-muted-foreground">{g.where}</span> : null}
          {g.screen && onOpenScreen ? (
            <Button
              type="button"
              size="sm"
              variant="ghost"
              onClick={() => g.screen && onOpenScreen(g.screen)}
            >
              Open
            </Button>
          ) : null}
        </li>
      ))}
    </ul>
  );
}

/** The button open_screen offers. */
export function OpenScreenCard({
  tool,
  onOpenScreen,
}: {
  tool: Tool;
  onOpenScreen?: (screenId: string) => void;
}) {
  if (tool.status !== "ok") {
    const msg = tool.output?.message;
    return typeof msg === "string" && msg ? (
      <p className="text-muted-foreground text-sm">{msg}</p>
    ) : null;
  }
  const screen = tool.output?.screen;
  if (typeof screen !== "string" || !screen) return null;
  const where = tool.output?.where;
  const title = tool.output?.title;
  const label = typeof where === "string" && where ? where : String(title ?? screen);
  return (
    <Button
      type="button"
      size="sm"
      variant="outline"
      disabled={!onOpenScreen}
      onClick={() => onOpenScreen?.(screen)}
    >
      <ExternalLink className="size-4" aria-hidden="true" />
      Open {label}
    </Button>
  );
}
