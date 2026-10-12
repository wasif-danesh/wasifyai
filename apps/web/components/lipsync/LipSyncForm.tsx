"use client";

import { PictureInput } from "@/components/PictureInput";
import { Recorder } from "@/components/transcribe/Recorder";
import { Button } from "@/components/ui/button";
import { Chip } from "@/components/ui/chip";
import { Input } from "@/components/ui/input";
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
import { Textarea } from "@/components/ui/textarea";
import { useMedia } from "@/hooks/use-media";
import { type Picture, usePicture } from "@/hooks/use-picture";
import { usePictureEvents } from "@/hooks/use-picture-events";
import { useRecorder } from "@/hooks/use-recorder";
import { clock } from "@/lib/format";
import type { Source } from "@/lib/lipsync-flow";
import { actions, chips, field, fieldError, fieldLabel, hint, panel } from "@/lib/styles";
import { cn } from "@/lib/utils";
import type { LanguageChoice, VoiceCatalog, VoiceChoice } from "@wasifyai/contracts";
import { type FormEvent, useEffect, useId, useRef, useState } from "react";
import { Bar } from "../create/Progress";

export const PRODUCT = "wasifyai-lipsync";
export const MAX_SCRIPT = 1000;
export const MAX_STYLE = 120;
/** A lip sync is at most 5 minutes (a song). It takes about six times as long as the clip. */
export const MAX_SECONDS = 300;
const MAX_AUDIO_BYTES = 50 * 1024 * 1024;
const GENDERS = [
  { id: "female", label: "Female" },
  { id: "male", label: "Male" },
] as const;

const hasVoice = (lang: LanguageChoice | undefined, gender: string) =>
  ((lang?.genders as Record<string, VoiceChoice[]> | undefined)?.[gender] ?? []).length > 0;

/** What the form hands over. The picture and the voice are already uploaded (ADR-0039, ADR-0043), so a
 * run needs only their keys; a script travels as text. */
export type LipSyncFormValue = {
  source: Source;
  picture: Picture;
  audioKey?: string;
  script?: string;
  language?: string;
  gender?: string;
  style: string;
};

export function LipSyncForm({
  catalog,
  onSubmit,
  initial,
  busy = false,
}: {
  catalog: VoiceCatalog;
  onSubmit: (value: LipSyncFormValue) => void;
  initial?: Partial<Pick<LipSyncFormValue, "script" | "language" | "gender" | "style">>;
  busy?: boolean;
}) {
  const id = useId();
  const file = useRef<HTMLInputElement>(null);
  const [tab, setTab] = useState("script");
  const [script, setScript] = useState(initial?.script ?? "");
  const [language, setLanguage] = useState(initial?.language ?? catalog.languages[0]?.id ?? "");
  const [gender, setGender] = useState(initial?.gender ?? "female");
  const [style, setStyle] = useState(initial?.style ?? "");
  const pic = usePicture(PRODUCT);
  const media = useMedia(PRODUCT, MAX_AUDIO_BYTES);
  const recorder = useRecorder();
  const uploading = media.status === "uploading";
  // A picture dropped or pasted anywhere on the page is taken.
  const { dragging } = usePictureEvents((f) => void pic.choose(f));

  // A finished recording goes to the server the same way as a chosen file.
  const made = recorder.recording?.blob;
  // biome-ignore lint/correctness/useExhaustiveDependencies: upload once per new recording
  useEffect(() => {
    if (made) void media.choose(made, "recording");
  }, [made]);

  const lang = catalog.languages.find((l) => l.id === language);
  const source: Source = tab === "script" ? "script" : "audio";
  const pictureReady = pic.picture !== null && pic.status !== "uploading";
  const voiceReady =
    source === "script"
      ? script.trim().length > 0 && script.length <= MAX_SCRIPT && hasVoice(lang, gender)
      : media.recording !== null && !uploading;
  const valid = pictureReady && voiceReady && style.length <= MAX_STYLE && !busy;

  function pickLanguage(next: string) {
    const l = catalog.languages.find((x) => x.id === next);
    setLanguage(next);
    // keep the gender if the new language has it; otherwise move to the one it has
    if (!hasVoice(l, gender)) {
      const other = GENDERS.find((g) => hasVoice(l, g.id));
      if (other) setGender(other.id);
    }
  }

  function submit(e?: FormEvent) {
    e?.preventDefault();
    if (!valid || !pic.picture) return;
    pic.handOver(); // the run owns the picture from here
    if (source === "audio" && media.recording) {
      media.handOver(); // and the voice
      onSubmit({
        source,
        picture: pic.picture,
        audioKey: media.recording.key,
        style: style.trim(),
      });
    } else {
      onSubmit({
        source: "script",
        picture: pic.picture,
        script: script.trim(),
        language,
        gender,
        style: style.trim(),
      });
    }
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
      <div className="grid gap-2">
        <span className={fieldLabel}>1. The character</span>
        <PictureInput
          picture={pic.picture}
          status={pic.status}
          error={pic.error}
          dragging={dragging}
          onChoose={(f) => void pic.choose(f)}
          onRemove={pic.clear}
          onCancel={pic.cancel}
        />
        <span className={hint}>
          Use a clear, front-facing face, looking at the camera. Only the mouth moves. Photographs
          of real people may be refused when the safeguards are on.
        </span>
      </div>

      <div className="grid gap-2">
        <span className={fieldLabel}>2. The voice</span>
        <Tabs value={tab} onValueChange={setTab}>
          <TabsList>
            <TabsTrigger value="script">Type a script</TabsTrigger>
            <TabsTrigger value="upload">Upload audio</TabsTrigger>
            <TabsTrigger value="record">Record</TabsTrigger>
          </TabsList>

          <TabsContent value="script" className="grid gap-4 pt-3">
            <div className={field}>
              <Label htmlFor={`${id}-script`} className="sr-only">
                What should the character say?
              </Label>
              <Textarea
                id={`${id}-script`}
                value={script}
                onChange={(e) => setScript(e.target.value)}
                rows={4}
                maxLength={MAX_SCRIPT}
                placeholder="Hello! Welcome to my channel. Today I'll show you something new."
                onKeyDown={(e) => {
                  if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) submit();
                }}
              />
              <span className={hint}>
                {script.length}/{MAX_SCRIPT} · a long script makes a long clip.
              </span>
            </div>
            <div className="flex flex-wrap items-end gap-4">
              <div className={field}>
                <Label htmlFor={`${id}-language`} className={fieldLabel}>
                  Language
                </Label>
                <Select value={language} onValueChange={pickLanguage}>
                  <SelectTrigger id={`${id}-language`} className="w-full sm:w-64">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {catalog.languages.map((l) => (
                      <SelectItem key={l.id} value={l.id} lang={l.id}>
                        {l.name === l.english ? l.name : `${l.name} · ${l.english}`}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <fieldset className={cn(field, "m-0 border-0 p-0")}>
                <legend className={cn(fieldLabel, "mb-1.5")}>Voice</legend>
                <div className={chips}>
                  {GENDERS.map((g) => (
                    <Chip
                      key={g.id}
                      aria-pressed={gender === g.id}
                      disabled={!hasVoice(lang, g.id)}
                      onClick={() => setGender(g.id)}
                    >
                      {g.label}
                    </Chip>
                  ))}
                </div>
              </fieldset>
            </div>
          </TabsContent>

          <TabsContent value="upload" className="grid gap-3 pt-3">
            <input
              ref={file}
              className="sr-only"
              type="file"
              accept="audio/*,video/*"
              aria-label="Audio or video file"
              tabIndex={-1}
              onChange={(e) => {
                const f = e.target.files?.[0];
                e.target.value = ""; // choosing the same file again must still fire
                if (f) void media.choose(f, f.name);
              }}
            />
            {media.recording && tab === "upload" ? (
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
                    onClick={() => file.current?.click()}
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
                className="grid cursor-pointer justify-items-center gap-1 rounded-lg border-2 border-dashed bg-surface px-4 py-8 text-center text-foreground transition-colors enabled:hover:border-primary enabled:hover:bg-accent disabled:cursor-progress disabled:opacity-60"
                onClick={() => file.current?.click()}
                disabled={uploading}
              >
                <span className="font-semibold">Choose a voice or a song</span>
                <span className={hint}>
                  An audio or video file of up to {MAX_SECONDS / 60} minutes
                </span>
              </button>
            )}
          </TabsContent>

          <TabsContent value="record" className="pt-3">
            <Recorder recorder={recorder} onDiscard={discardRecording} uploading={uploading} />
            <span className={cn(hint, "mt-2 block")}>
              Up to {MAX_SECONDS / 60} minutes: a longer recording is refused.
            </span>
          </TabsContent>
        </Tabs>

        {uploading ? (
          <output className="grid gap-[0.6rem]">
            <div className="flex justify-between gap-4 text-[0.95rem] text-muted-foreground">
              <span>Uploading your voice…</span>
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
      </div>

      <div className={field}>
        <Label htmlFor={`${id}-style`} className={fieldLabel}>
          3. Style (optional)
        </Label>
        <Input
          id={`${id}-style`}
          value={style}
          onChange={(e) => setStyle(e.target.value)}
          maxLength={MAX_STYLE}
          placeholder="calm, smiling"
        />
        <span className={hint}>How the character should look while speaking.</span>
      </div>

      <div className="flex flex-wrap items-center gap-4">
        <Button type="submit" size="lg" disabled={!valid}>
          {busy ? <Spinner /> : null}
          Make my lip sync
        </Button>
        <span className="text-muted-foreground">
          Leave while it's made: we'll tell you when it's ready. Your picture and voice are deleted
          afterwards.
        </span>
      </div>
    </form>
  );
}
