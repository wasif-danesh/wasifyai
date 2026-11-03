"use client";
// The brief of a project: the song or the story, the idea, who is in it and where. The analysis tool is
// set up from here, with its size shown first, because a song's plan cannot start without it. A story is
// read aloud by saved voices instead, so it needs none.
import {
  type AnalysisState,
  type CastMember,
  type CreativeApi,
  type CreativeBrief,
  type CreativeShape,
  type CreativeSkill,
  type FixedWords,
  gigabytes,
} from "@wasifyai/client";
import { Plus, X } from "lucide-react";
import { useEffect, useState } from "react";
import { Button } from "../components/button";
import { Checkbox } from "../components/checkbox";
import { JobMeter, WorkingCard } from "../components/create";
import { Modal } from "../components/dialog";
import { Field } from "../components/field";
import { Input } from "../components/input";
import { Notice } from "../components/notice";
import { Segmented } from "../components/segmented";
import { Select } from "../components/select";
import { Textarea } from "../components/textarea";
import { actions, hint, panel } from "../styles";
import type { CreativeSong } from "./Creative";

const POLL_SETUP_MS = 700;
const CUT_SPEEDS = [
  { value: "-2", label: "Slowest" },
  { value: "-1", label: "Slow" },
  { value: "0", label: "Medium" },
  { value: "1", label: "Fast" },
  { value: "2", label: "Fastest" },
];
const SKILLS = [
  { value: "song", label: "A song" },
  { value: "story", label: "A story" },
];
const STORY_MIN = 40;
const STORY_MAX = 12000;
const BUILT_IN = "built-in";

/** A saved voice of the person's, to read a story or say a person's words. */
export type CreativeVoice = { id: string; name: string };

const SHAPES = [
  { value: "landscape", label: "Landscape" },
  { value: "portrait", label: "Portrait" },
  { value: "square", label: "Square" },
];

function clock(seconds: number): string {
  const whole = Math.round(seconds);
  return `${Math.floor(whole / 60)}:${(whole % 60).toString().padStart(2, "0")}`;
}

/** The analysis tool: the card to set it up, and whether a plan can start. */
export function useAnalysis(api: CreativeApi) {
  const [state, setState] = useState<AnalysisState | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const installing = state?.state === "installing";
  useEffect(() => {
    let live = true;
    const read = () =>
      api
        .analysis()
        .then((s) => live && setState(s))
        .catch((e: unknown) => {
          if (live) setProblem(e instanceof Error ? e.message : "The engine did not answer.");
        });
    void read();
    const timer = installing ? setInterval(read, POLL_SETUP_MS) : undefined;
    return () => {
      live = false;
      clearInterval(timer);
    };
  }, [api, installing]);
  return {
    state,
    problem,
    install: (bytes: number) =>
      api
        .installAnalysis(bytes)
        .then(() => setState({ state: "installing", share: null, label: "Starting" }))
        .catch((e: unknown) => setProblem(e instanceof Error ? e.message : "It did not start.")),
    cancel: () => api.cancelAnalysis().then(() => api.analysis().then(setState)),
  };
}

export function AnalysisCard({ analysis }: { analysis: ReturnType<typeof useAnalysis> }) {
  const { state, problem } = analysis;
  if (problem) {
    return (
      <Notice tone="error" title="Music analysis">
        {problem}
      </Notice>
    );
  }
  if (!state || state.state === "ready") return null;
  if (state.state === "unsupported") {
    return (
      <Notice tone="info" title="Not on this computer yet">
        {state.reason}
      </Notice>
    );
  }
  if (state.state === "elsewhere") {
    return (
      <Notice tone="info" title="Song analysis is not set up">
        {state.reason} A story needs no analysis.
      </Notice>
    );
  }
  if (state.state === "installing") {
    return (
      <WorkingCard label={state.label || "Setting up"} onCancel={() => void analysis.cancel()}>
        <JobMeter
          title="Setting up music analysis"
          text={state.share === null ? "Working" : `${Math.round(state.share * 100)}%`}
          value={state.share ?? undefined}
          label="Setup progress"
        />
      </WorkingCard>
    );
  }
  return (
    <section className={panel} aria-label="Set up music analysis">
      <h2 className="m-0 font-semibold text-lg">Set up music analysis</h2>
      <p className="m-0 text-muted-foreground">
        A plan needs the beats and sections of the song. The tool that finds them is not in the app.
        It is downloaded once, every file checked, and kept in the app's own folder.
      </p>
      {state.state === "failed" ? (
        <Notice tone="error" title="Setting up did not finish">
          {state.message}
        </Notice>
      ) : null}
      <div className={actions}>
        <Button type="button" onClick={() => void analysis.install(state.bytes)}>
          Download and set up ({gigabytes(state.bytes)})
        </Button>
        <span className="text-muted-foreground">It continues where it stopped.</span>
      </div>
    </section>
  );
}

export type LibraryPicture = { id: string; url: string; title: string };

/** Up to three pictures of a person from the library. With none, two are made from their words. */
function PicturesOf({
  name,
  chosen,
  pictures,
  onChange,
}: {
  name: string;
  chosen: string[];
  pictures: () => Promise<LibraryPicture[]>;
  onChange: (next: string[]) => void;
}) {
  const [found, setFound] = useState<LibraryPicture[] | null>(null);
  const open = () => {
    setFound([]);
    pictures()
      .then(setFound)
      .catch(() => setFound([]));
  };
  return (
    <>
      <Button type="button" variant="outline" size="sm" onClick={open}>
        Pictures{chosen.length ? ` (${chosen.length})` : ""}
      </Button>
      {found ? (
        <Modal label={`Pictures of ${name}`} onClose={() => setFound(null)} wide>
          <div className="grid max-h-[70dvh] gap-3 overflow-auto">
            <p className={`${hint} m-0`}>
              Choose up to three. With none, two are made from their words when the stills start.
            </p>
            {found.length === 0 ? (
              <p className={`${hint} m-0`}>There are no pictures in your Library yet.</p>
            ) : null}
            <ul className="m-0 grid list-none grid-cols-[repeat(auto-fill,minmax(7rem,1fr))] gap-2 p-0">
              {found.map((p) => {
                const on = chosen.includes(p.id);
                return (
                  <li key={p.id}>
                    <button
                      type="button"
                      aria-pressed={on}
                      aria-label={p.title}
                      disabled={!on && chosen.length >= 3}
                      className={`w-full cursor-pointer rounded-md border-2 p-0.5 outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50 disabled:cursor-default disabled:opacity-50 ${on ? "border-primary" : "border-transparent"}`}
                      onClick={() =>
                        onChange(on ? chosen.filter((c) => c !== p.id) : [...chosen, p.id])
                      }
                    >
                      <img
                        src={p.url}
                        alt=""
                        className="aspect-square w-full rounded object-cover"
                      />
                    </button>
                  </li>
                );
              })}
            </ul>
            <div className={actions}>
              <Button type="button" onClick={() => setFound(null)}>
                Done
              </Button>
            </div>
          </div>
        </Modal>
      ) : null}
    </>
  );
}

const EMPTY: CreativeBrief = {
  skill: "song",
  track_id: "",
  story: null,
  narrator: null,
  idea: "",
  style: "",
  cast: [],
  places: [],
  fixed: [],
  lyrics: null,
  shape: "landscape",
  cut_speed: 0,
};

export function BriefForm({
  api,
  songs,
  initial,
  initialTitle = "",
  submitLabel,
  onSubmit,
  onCancel,
  onMakeSong,
  pictures,
  voices,
}: {
  api: CreativeApi;
  songs: () => Promise<CreativeSong[]>;
  /** the person's saved voices, for a story's narrator and people */
  voices?: () => Promise<CreativeVoice[]>;
  /** the pictures of the library a person can be drawn from */
  pictures?: () => Promise<LibraryPicture[]>;
  initial?: CreativeBrief;
  initialTitle?: string;
  submitLabel: string;
  onSubmit: (title: string, brief: CreativeBrief) => Promise<void>;
  onCancel: () => void;
  onMakeSong?: () => void;
}) {
  const analysis = useAnalysis(api);
  const [list, setList] = useState<CreativeSong[] | null>(null);
  const [title, setTitle] = useState(initialTitle);
  const [brief, setBrief] = useState<CreativeBrief>(initial ?? EMPTY);
  const [places, setPlaces] = useState((initial?.places ?? []).join("\n"));
  const [lyrics, setLyrics] = useState(initial?.lyrics ?? "");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const change = (part: Partial<CreativeBrief>) => setBrief((b) => ({ ...b, ...part }));
  const person = (i: number, part: Partial<CastMember>) =>
    change({ cast: brief.cast.map((p, k) => (k === i ? { ...p, ...part } : p)) });
  const fixed = brief.fixed ?? [];
  const fixedRow = (i: number, part: Partial<FixedWords>) =>
    change({ fixed: fixed.map((f, k) => (k === i ? { ...f, ...part } : f)) });
  const [known, setKnown] = useState<CastMember[]>([]);
  useEffect(() => {
    api
      .characters()
      .then(setKnown)
      .catch(() => setKnown([]));
  }, [api]);
  const usable = known.filter((k) => !brief.cast.some((p) => p.name === k.name));
  const [saved, setSaved] = useState<CreativeVoice[]>([]);
  useEffect(() => {
    voices?.()
      .then(setSaved)
      .catch(() => setSaved([]));
  }, [voices]);
  const story = brief.skill === "story";
  const voiceOptions = [
    { value: BUILT_IN, label: "The model's own voice" },
    ...saved.map((v) => ({ value: v.id, label: v.name })),
  ];

  useEffect(() => {
    songs()
      .then(setList)
      .catch((e: unknown) =>
        setProblem(e instanceof Error ? e.message : "Your music could not be read."),
      );
  }, [songs]);

  const song = list?.find((s) => s.id === brief.track_id);
  const ready = analysis.state?.state === "ready";
  const missingName = brief.cast.some((p) => !p.name.trim());
  const sourceReady = story
    ? (brief.story ?? "").trim().length >= STORY_MIN
    : ready && !!brief.track_id;
  const canGo = sourceReady && brief.idea.trim().length >= 3 && !missingName && !busy;

  const submit = async () => {
    setBusy(true);
    setProblem(null);
    try {
      await onSubmit(title.trim(), {
        ...brief,
        idea: brief.idea.trim(),
        style: brief.style.trim(),
        story: story ? (brief.story ?? "").trim() : null,
        narrator: story ? (brief.narrator ?? null) : null,
        track_id: story && !initial ? "" : brief.track_id,
        places: places
          .split("\n")
          .map((p) => p.trim())
          .filter(Boolean),
        lyrics: story ? null : lyrics.trim() || null,
      });
    } catch (e) {
      setProblem(e instanceof Error ? e.message : "The plan did not start.");
      setBusy(false);
    }
  };

  return (
    <form
      className="grid gap-5"
      onSubmit={(e) => {
        e.preventDefault();
        if (canGo) void submit();
      }}
    >
      <header className="grid gap-1.5">
        <h1 className="m-0 font-semibold text-xl">
          {initial ? "Change the brief" : "New project"}
        </h1>
        <p className="m-0 text-muted-foreground">
          {story
            ? "Your story is read aloud first, a line at a time, then planned like a song. Only the reading and words are made at this stage."
            : "With an 8B chat model a 3-minute song takes about a minute to plan; a larger model can take many minutes. Only words are made at this stage."}
        </p>
      </header>
      {initial ? null : (
        <Segmented
          label="What the video is made from"
          value={brief.skill ?? "song"}
          onValueChange={(v) => change({ skill: v as CreativeSkill })}
          options={SKILLS}
        />
      )}
      {story ? null : <AnalysisCard analysis={analysis} />}
      {!story && list && list.length === 0 ? (
        <Notice
          tone="info"
          title="There is no song yet"
          actions={
            onMakeSong ? (
              <Button type="button" onClick={onMakeSong}>
                Make a song
              </Button>
            ) : null
          }
        >
          A project starts from a song in Your music.
        </Notice>
      ) : null}
      <div className={panel}>
        {story ? (
          <>
            <Field
              label="The story"
              hint="What the narrator reads. Leave a blank line between paragraphs. Words in quotes are said by the person named in the same sentence, in their voice."
            >
              {({ id, describedBy }) => (
                <Textarea
                  id={id}
                  aria-describedby={describedBy}
                  rows={8}
                  maxLength={STORY_MAX}
                  value={brief.story ?? ""}
                  onChange={(e) => change({ story: e.target.value })}
                />
              )}
            </Field>
            <Field
              label="Who reads it"
              hint={
                saved.length
                  ? "A saved voice, or the model's own."
                  : "You have no saved voices yet: make one under Voices, or the model's own voice reads it."
              }
            >
              {({ id, describedBy }) => (
                <Select
                  id={id}
                  aria-describedby={describedBy}
                  value={brief.narrator || BUILT_IN}
                  onValueChange={(v) => change({ narrator: v === BUILT_IN ? null : v })}
                  options={voiceOptions}
                />
              )}
            </Field>
          </>
        ) : (
          <Field label="Song">
            {({ id, describedBy }) => (
              <Select
                id={id}
                aria-describedby={describedBy}
                value={brief.track_id || undefined}
                onValueChange={(track_id) => change({ track_id })}
                placeholder="Choose a song"
                options={(list ?? []).map((s) => ({
                  value: s.id,
                  label: s.title || "Untitled song",
                  hint: clock(s.seconds),
                }))}
              />
            )}
          </Field>
        )}
        <Field label="What is the video about?" hint="A line is enough.">
          {({ id, describedBy }) => (
            <Textarea
              id={id}
              aria-describedby={describedBy}
              rows={2}
              maxLength={600}
              value={brief.idea}
              onChange={(e) => change({ idea: e.target.value })}
            />
          )}
        </Field>
        <Field label="Name" optional hint="Left empty, it is named after the idea.">
          {({ id, describedBy }) => (
            <Input
              id={id}
              aria-describedby={describedBy}
              maxLength={200}
              value={title}
              onChange={(e) => setTitle(e.target.value)}
            />
          )}
        </Field>
        <Field label="The look" optional hint="Warm film photo, for instance.">
          {({ id, describedBy }) => (
            <Input
              id={id}
              aria-describedby={describedBy}
              maxLength={120}
              value={brief.style}
              onChange={(e) => change({ style: e.target.value })}
            />
          )}
        </Field>
      </div>
      <section className={panel} aria-labelledby="creative-people">
        <h2 id="creative-people" className="m-0 font-semibold text-base">
          People
        </h2>
        <p className={`${hint} m-0`}>
          Only these people appear in the plan. Their words for how they look are used in every
          picture, so they stay the same person.
          {story ? " Choose the voice that says the words in quotes after their name." : ""}
        </p>
        {brief.cast.map((p, i) => (
          <div key={`person-${i.toString()}`} className="grid gap-2 sm:grid-cols-[1fr_2fr_auto]">
            <Input
              aria-label={`Name of person ${i + 1}`}
              placeholder="Name"
              maxLength={60}
              value={p.name}
              onChange={(e) => person(i, { name: e.target.value })}
            />
            <Input
              aria-label={`How ${p.name || `person ${i + 1}`} looks`}
              placeholder="How they look"
              maxLength={240}
              value={p.look}
              onChange={(e) => person(i, { look: e.target.value })}
            />
            {story ? (
              <Select
                aria-label={`Voice of ${p.name || `person ${i + 1}`}`}
                className="sm:col-span-2"
                value={p.voice || BUILT_IN}
                onValueChange={(v) => person(i, { voice: v === BUILT_IN ? null : v })}
                options={[
                  { value: BUILT_IN, label: "The narrator says their words" },
                  ...saved.map((v) => ({ value: v.id, label: v.name })),
                ]}
              />
            ) : null}
            <div className="flex items-center gap-2">
              <Checkbox
                label="Only in photos"
                checked={p.photos_only}
                onCheckedChange={(v) => person(i, { photos_only: v })}
              />
              {pictures ? (
                <PicturesOf
                  name={p.name || `person ${i + 1}`}
                  chosen={p.pictures ?? []}
                  pictures={pictures}
                  onChange={(next) => person(i, { pictures: next })}
                />
              ) : null}
              <Button
                type="button"
                variant="ghost"
                size="icon"
                aria-label={`Remove ${p.name || `person ${i + 1}`}`}
                onClick={() => change({ cast: brief.cast.filter((_, k) => k !== i) })}
              >
                <X aria-hidden />
              </Button>
            </div>
          </div>
        ))}
        {brief.cast.length < 8 ? (
          <div className="flex flex-wrap items-center gap-2">
            {usable.length ? (
              <Select
                aria-label="Someone you have used before"
                className="w-56"
                value=""
                placeholder="Someone you have used"
                options={usable.map((k) => ({ value: k.name, label: k.name }))}
                onValueChange={(name) => {
                  const found = usable.find((k) => k.name === name);
                  if (found) change({ cast: [...brief.cast, found] });
                }}
              />
            ) : null}
            <Button
              type="button"
              variant="outline"
              onClick={() =>
                change({ cast: [...brief.cast, { name: "", look: "", photos_only: false }] })
              }
            >
              <Plus aria-hidden /> Add a person
            </Button>
          </div>
        ) : null}
      </section>
      <section className={`${panel} grid gap-3`} aria-labelledby="creative-fixed">
        <h2 id="creative-fixed" className="m-0 font-semibold text-base">
          Objects and places that stay the same
        </h2>
        <p className={`${hint} m-0`}>
          Things do not carry over from one picture to the next by themselves. These words are used
          in every shot that names the thing.
        </p>
        {fixed.map((f, i) => (
          <div key={`fixed-${i.toString()}`} className="grid gap-2 sm:grid-cols-[1fr_2fr_auto]">
            <Input
              aria-label={`Name of thing ${i + 1}`}
              placeholder="The car"
              maxLength={60}
              value={f.name}
              onChange={(e) => fixedRow(i, { name: e.target.value })}
            />
            <Input
              aria-label={`How ${f.name || `thing ${i + 1}`} looks`}
              placeholder="An old red estate car with a dent in the door"
              maxLength={200}
              value={f.words}
              onChange={(e) => fixedRow(i, { words: e.target.value })}
            />
            <Button
              type="button"
              variant="ghost"
              size="icon"
              aria-label={`Remove ${f.name || `thing ${i + 1}`}`}
              onClick={() => change({ fixed: fixed.filter((_, k) => k !== i) })}
            >
              <X aria-hidden />
            </Button>
          </div>
        ))}
        {fixed.length < 12 ? (
          <div>
            <Button
              type="button"
              variant="outline"
              onClick={() => change({ fixed: [...fixed, { name: "", words: "" }] })}
            >
              <Plus aria-hidden /> Add an object or place
            </Button>
          </div>
        ) : null}
      </section>
      <div className={panel}>
        <Field
          label="Places"
          optional
          hint="One on each line, in the order the story visits them. Left empty, the writer chooses."
        >
          {({ id, describedBy }) => (
            <Textarea
              id={id}
              aria-describedby={describedBy}
              rows={3}
              value={places}
              onChange={(e) => setPlaces(e.target.value)}
            />
          )}
        </Field>
        {story ? null : (
          <Field
            label="The song's words"
            optional
            hint={
              song?.lyrics
                ? "Left empty, the words the song was made with are used. They are used as typed, never changed."
                : "They are used as typed. Listening only finds when each line is sung."
            }
          >
            {({ id, describedBy }) => (
              <Textarea
                id={id}
                aria-describedby={describedBy}
                rows={4}
                maxLength={20000}
                value={lyrics}
                onChange={(e) => setLyrics(e.target.value)}
              />
            )}
          </Field>
        )}
        <Field label="Shape">
          <Segmented
            label="Shape"
            value={brief.shape}
            onValueChange={(v) => change({ shape: v as CreativeShape })}
            options={SHAPES}
          />
        </Field>
        <Field label="How fast it cuts" hint="Changing this later means planning again.">
          <Segmented
            label="How fast it cuts"
            value={String(brief.cut_speed)}
            onValueChange={(v) => change({ cut_speed: Number(v) })}
            options={CUT_SPEEDS}
          />
        </Field>
      </div>
      {problem ? (
        <Notice tone="error" title="That did not work">
          {problem}
        </Notice>
      ) : null}
      <div className={actions}>
        <Button type="submit" size="lg" disabled={!canGo}>
          {submitLabel}
        </Button>
        <Button type="button" variant="ghost" onClick={onCancel}>
          Back
        </Button>
      </div>
    </form>
  );
}
