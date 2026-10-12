"use client";

import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Spinner } from "@/components/ui/spinner";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useMedia } from "@/hooks/use-media";
import { usePictureEvents } from "@/hooks/use-picture-events";
import { useRecorder } from "@/hooks/use-recorder";
import { clock } from "@/lib/format";
import { actions, field, fieldError, fieldLabel, hint, panel } from "@/lib/styles";
import { cn } from "@/lib/utils";
import type { SpokenLanguages } from "@wasifyai/contracts";
import { type FormEvent, useEffect, useId, useRef, useState } from "react";
import { Bar } from "../create/Progress";
import { Recorder } from "./Recorder";

export const PRODUCT = "wasifyai-stt";
export const AUTO = "auto";

export type TranscribeFormValue = { audioKey: string; language: string };

const QUALITY_NOTE: Record<string, string> = {
  limited: "Transcripts in this language have more mistakes than in most others.",
  fair: "Transcripts in this language are usually good, with a few mistakes.",
};

/** Upload a file or record with the microphone, choose the language (or let it be detected), and go. */
export function TranscribeForm({
  catalog,
  onSubmit,
  initial,
  busy = false,
}: {
  catalog: SpokenLanguages;
  onSubmit: (value: TranscribeFormValue) => void;
  initial?: Partial<TranscribeFormValue>;
  busy?: boolean;
}) {
  const id = useId();
  const input = useRef<HTMLInputElement>(null);
  const [source, setSource] = useState("upload");
  const [language, setLanguage] = useState(initial?.language ?? AUTO);
  const media = useMedia(PRODUCT, catalog.max_bytes);
  const recorder = useRecorder();
  const uploading = media.status === "uploading";
  // A file dropped or pasted anywhere on the page is taken, and switches to the upload tab.
  const { dragging } = usePictureEvents((file) => {
    setSource("upload");
    void media.choose(file, file.name);
  });

  // A finished recording goes to the server the same way as a chosen file.
  const made = recorder.recording?.blob;
  // biome-ignore lint/correctness/useExhaustiveDependencies: upload once per new recording
  useEffect(() => {
    if (made) void media.choose(made, "recording");
  }, [made]);

  const known = catalog.languages.find((l) => l.id === language);
  const valid = media.recording !== null && !uploading && !busy;
  const limit = `${Math.round(catalog.max_seconds / 60)} minutes`;

  function submit(e?: FormEvent) {
    e?.preventDefault();
    if (!valid || !media.recording) return;
    media.handOver(); // the run owns the recording from here
    onSubmit({ audioKey: media.recording.key, language });
  }

  function discardRecording() {
    recorder.discard();
    media.clear();
  }

  return (
    <form
      className={cn(
        panel,
        "gap-6 data-[dragging]:outline-2 data-[dragging]:outline-offset-4 data-[dragging]:outline-primary data-[dragging]:outline-dashed",
      )}
      onSubmit={submit}
      data-dragging={dragging || undefined}
    >
      <Tabs value={source} onValueChange={setSource}>
        <TabsList>
          <TabsTrigger value="upload">Upload a file</TabsTrigger>
          <TabsTrigger value="record">Record</TabsTrigger>
        </TabsList>

        <TabsContent value="upload" className="grid gap-3 pt-3">
          <input
            ref={input}
            id={`${id}-file`}
            className="sr-only"
            type="file"
            accept="audio/*,video/*"
            aria-label="Audio or video file"
            tabIndex={-1}
            onChange={(e) => {
              const file = e.target.files?.[0];
              e.target.value = ""; // choosing the same file again must still fire
              if (file) void media.choose(file, file.name);
            }}
          />
          {media.recording && source === "upload" && recorder.state !== "recorded" ? (
            <div className="grid gap-3 rounded-lg border bg-surface p-5">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <span className="font-semibold break-all">{media.recording.name}</span>
                <span className="text-muted-foreground tabular-nums">
                  {clock(media.recording.seconds)}
                </span>
              </div>
              {/* biome-ignore lint/a11y/useMediaCaption: this is the user's own file, played back to check it */}
              <audio
                controls
                src={media.recording.previewUrl}
                className="block h-12 w-full rounded-full"
              >
                Your browser can't play this audio.
              </audio>
              <div className={actions}>
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => input.current?.click()}
                  disabled={uploading}
                >
                  Replace
                </Button>
                <Button type="button" variant="outline" onClick={media.clear}>
                  Remove
                </Button>
              </div>
            </div>
          ) : (
            <button
              type="button"
              className="grid cursor-pointer justify-items-center gap-1 rounded-lg border-2 border-dashed bg-surface px-4 py-8 text-center text-foreground transition-colors enabled:hover:border-primary enabled:hover:bg-accent disabled:cursor-progress disabled:opacity-60 data-[dragging]:border-primary data-[dragging]:bg-accent"
              data-dragging={dragging || undefined}
              aria-describedby={`${id}-hint`}
              onClick={() => input.current?.click()}
              disabled={uploading}
            >
              <span className="font-semibold">Choose an audio or video file</span>
              <span className={hint}>or drag one here</span>
            </button>
          )}
        </TabsContent>

        <TabsContent value="record" className="pt-3">
          <Recorder recorder={recorder} onDiscard={discardRecording} uploading={uploading} />
        </TabsContent>
      </Tabs>

      {uploading ? (
        <output className="grid gap-[0.6rem]">
          <div className="flex justify-between gap-4 text-[0.95rem] text-muted-foreground">
            <span>Uploading your recording…</span>
            <Button type="button" variant="link" size="xs" onClick={media.cancel}>
              Cancel
            </Button>
          </div>
          <Bar />
        </output>
      ) : null}
      {media.error ? (
        <span className={fieldError} role="alert">
          {media.error}
        </span>
      ) : null}
      <span className={hint} id={`${id}-hint`}>
        Up to {limit} and {Math.round(catalog.max_bytes / (1024 * 1024))} MB: MP3, WAV, M4A, MP4,
        WebM and more. Your recording is deleted once the transcript is made.
      </span>

      <div className={field}>
        <Label htmlFor={`${id}-language`} className={fieldLabel}>
          Language
        </Label>
        <Select value={language} onValueChange={setLanguage}>
          <SelectTrigger id={`${id}-language`} className="w-full sm:w-80">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={AUTO}>Detect the language</SelectItem>
            {catalog.languages.map((l) => (
              <SelectItem key={l.id} value={l.id} lang={l.id}>
                {l.name === l.english ? l.name : `${l.name} · ${l.english}`}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <span className={hint} aria-live="polite">
          {known
            ? (QUALITY_NOTE[known.quality] ?? "")
            : "We listen to the start of the recording to find the language. Choose it if it's wrong."}
        </span>
      </div>

      <div className="flex flex-wrap items-center gap-4">
        <Button type="submit" size="lg" disabled={!valid}>
          {busy ? <Spinner /> : null}
          Transcribe
        </Button>
        <span className="text-muted-foreground">
          You can leave this page while it works: we'll tell you when it's ready.
        </span>
      </div>
    </form>
  );
}
