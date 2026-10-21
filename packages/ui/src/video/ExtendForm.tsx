"use client";

import { type VideoSummary, type VideosApi, canExtend, clipLength } from "@wasifyai/client";
import { Upload } from "lucide-react";
import { type ChangeEvent, type FormEvent, useEffect, useId, useRef, useState } from "react";
import { cn } from "../cn";
import { Button } from "../components/button";
import { PromptField } from "../components/create";
import { Notice } from "../components/notice";
import { Spinner } from "../components/spinner";
import { field, fieldLabel, panel } from "../styles";

const MAX_PROMPT = 500;
const EXAMPLES = [
  "The fox keeps walking through the snow",
  "The waves keep rolling onto the beach",
  "The camera keeps slowly moving forward",
];

/** What the form hands over: the clip to carry on and what should keep happening. */
export type ExtendValue = { source: VideoSummary; prompt: string };

/**
 * Carry on one of the person's videos (Extend video): choose a finished clip or add a video file from this
 * computer, say what should keep happening, and about two more seconds are made from its last second. The
 * words of a clip made here fill in from its own; they steer only weakly: the movement of the last second
 * carries on, and the form says so.
 */
export function ExtendForm({
  videos,
  onSubmit,
  initial,
  hint,
}: {
  videos: Pick<VideosApi, "list"> & Partial<Pick<VideosApi, "importVideo">>;
  onSubmit: (value: ExtendValue) => void;
  initial?: { source: VideoSummary; prompt: string };
  hint?: string;
}) {
  const id = useId();
  const [clips, setClips] = useState<VideoSummary[] | null>(null);
  const [next, setNext] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [failed, setFailed] = useState(false);
  const [hidden, setHidden] = useState(false); // some of the person's clips are too long to carry on
  const [source, setSource] = useState<VideoSummary | null>(initial?.source ?? null);
  const [prompt, setPrompt] = useState(initial?.prompt ?? "");
  const [edited, setEdited] = useState(Boolean(initial));
  const [adding, setAdding] = useState(false);
  const [addProblem, setAddProblem] = useState<string | null>(null);
  const picker = useRef<HTMLInputElement>(null);

  async function load(before?: string | null) {
    setLoading(true);
    setFailed(false);
    try {
      const page = await videos.list({ limit: 24, before, status: "done" });
      const fit = page.videos.filter((v) => canExtend(v) && v.video_url);
      if (fit.length < page.videos.length) setHidden(true);
      setClips((old) => [...(before ? (old ?? []) : []), ...fit]);
      setNext(page.next_before);
    } catch {
      setFailed(true);
    } finally {
      setLoading(false);
    }
  }

  // biome-ignore lint/correctness/useExhaustiveDependencies: load once, when the screen opens
  useEffect(() => {
    void load();
  }, []);

  function choose(clip: VideoSummary) {
    setSource(clip);
    // a clip made here has the words that made it; a file the person added only has its name
    if (!edited) setPrompt(clip.mode === "import" ? "" : clip.prompt.slice(0, MAX_PROMPT));
  }

  async function add(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = ""; // the same file can be chosen again
    if (!file || !videos.importVideo) return;
    setAdding(true);
    setAddProblem(null);
    try {
      const clip = await videos.importVideo(file);
      setClips((old) => [clip, ...(old ?? [])]);
      choose(clip);
    } catch (err) {
      setAddProblem(
        err instanceof Error && err.message
          ? err.message
          : "That video could not be added. Try another file.",
      );
    } finally {
      setAdding(false);
    }
  }

  const trimmed = prompt.trim();
  const valid = source !== null && trimmed.length > 0 && prompt.length <= MAX_PROMPT;

  function submit(e?: FormEvent) {
    e?.preventDefault();
    if (valid && source) onSubmit({ source, prompt: trimmed });
  }

  return (
    <form className={cn(panel, "gap-6")} onSubmit={submit}>
      <fieldset className={cn(field, "m-0 border-0 p-0")}>
        <legend className={cn(fieldLabel, "mb-1.5")}>Which video should carry on?</legend>
        {videos.importVideo ? (
          <div className="flex flex-wrap items-center gap-3">
            <input
              ref={picker}
              type="file"
              accept="video/*,.mp4,.mov,.m4v,.webm,.mkv"
              className="sr-only"
              tabIndex={-1}
              aria-label="Choose a video file"
              onChange={(e) => void add(e)}
            />
            <Button
              type="button"
              variant="outline"
              disabled={adding}
              onClick={() => picker.current?.click()}
            >
              {adding ? <Spinner /> : <Upload className="size-4" />} Add a video from this computer
            </Button>
            <span className="text-muted-foreground text-sm" aria-live="polite">
              {adding
                ? "Adding your video… this takes a moment."
                : "Up to 30 seconds. It is made to fit the model; the original is not changed."}
            </span>
          </div>
        ) : null}
        {addProblem ? (
          <Notice tone="error" title="That video could not be added">
            {addProblem}
          </Notice>
        ) : null}
        {clips === null && !failed ? (
          <p className="flex items-center gap-2 text-muted-foreground">
            <Spinner /> Looking for your videos…
          </p>
        ) : null}
        {failed ? (
          <Notice
            tone="error"
            title="Your videos could not be loaded"
            actions={
              <Button type="button" variant="outline" onClick={() => void load()}>
                Try again
              </Button>
            }
          >
            Check that the app is running and try again.
          </Notice>
        ) : null}
        {clips && clips.length === 0 && !failed ? (
          <p className="text-muted-foreground">
            {hidden && !next
              ? "Your videos are all too long to carry on. A video can be carried on until it is about 4 seconds long."
              : "You have no videos to carry on yet. Add one from your computer, or make one in Create."}
          </p>
        ) : null}
        {clips && clips.length > 0 ? (
          <ul className="m-0 grid list-none grid-cols-2 gap-3 p-0 sm:grid-cols-3">
            {clips.map((clip) => (
              <li key={clip.id}>
                <button
                  type="button"
                  aria-pressed={source?.id === clip.id}
                  onClick={() => choose(clip)}
                  className={cn(
                    "grid w-full gap-1.5 rounded-xl border p-2 text-left outline-none transition-colors hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring",
                    source?.id === clip.id && "border-primary bg-accent",
                  )}
                >
                  {clip.poster_url ? (
                    <img
                      src={clip.poster_url}
                      alt=""
                      className="aspect-video w-full rounded-lg bg-muted object-cover"
                    />
                  ) : (
                    <span className="aspect-video w-full rounded-lg bg-muted" />
                  )}
                  <span className="line-clamp-2 text-sm">{clip.prompt}</span>
                  <span className="text-muted-foreground text-xs">{clipLength(clip.seconds)}</span>
                </button>
              </li>
            ))}
          </ul>
        ) : null}
        {next ? (
          <div>
            <Button
              type="button"
              variant="outline"
              disabled={loading}
              onClick={() => void load(next)}
            >
              Show older videos
            </Button>
          </div>
        ) : null}
        {hidden && clips && clips.length > 0 ? (
          <span className="text-muted-foreground text-sm">
            Videos longer than about 4 seconds are not shown: they cannot be carried on.
          </span>
        ) : null}
      </fieldset>

      <PromptField
        id={id}
        label="What should keep happening?"
        value={prompt}
        onChange={(v) => {
          setPrompt(v);
          setEdited(true);
        }}
        placeholder={EXAMPLES[0] ?? ""}
        hintText="Describe what carries on. The movement of the last second continues whatever you write, so a different action usually will not take. Press Ctrl or ⌘ + Enter to start."
        max={MAX_PROMPT}
        examples={EXAMPLES}
        exampleLabel={(ex) => ex}
        enhance={null}
        onSubmit={submit}
      />

      <div className="flex flex-wrap items-center gap-4">
        <Button type="submit" size="lg" disabled={!valid}>
          Carry on my video
        </Button>
        <span className="text-muted-foreground">
          {hint ?? "About 2 seconds are added, and it takes about as long as a 2 second video."}
        </span>
      </div>
      <p className="m-0 text-muted-foreground text-sm">
        The new video is saved beside the original. Its picture gets a little softer each time.
      </p>
    </form>
  );
}
