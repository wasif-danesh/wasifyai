"use client";
// The brief of a project: the song, the idea, who is in it and where. The analysis tool is set up from
// here, with its size shown first, because a plan cannot start without it.
import {
  type AnalysisState,
  type CastMember,
  type CreativeApi,
  type CreativeBrief,
  type CreativeShape,
  gigabytes,
} from "@wasifyai/client";
import { Plus, X } from "lucide-react";
import { useEffect, useState } from "react";
import { Button } from "../components/button";
import { Checkbox } from "../components/checkbox";
import { JobMeter, WorkingCard } from "../components/create";
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

const EMPTY: CreativeBrief = {
  track_id: "",
  idea: "",
  style: "",
  cast: [],
  places: [],
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
}: {
  api: CreativeApi;
  songs: () => Promise<CreativeSong[]>;
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
  const canGo = ready && !!brief.track_id && brief.idea.trim().length >= 3 && !missingName && !busy;

  const submit = async () => {
    setBusy(true);
    setProblem(null);
    try {
      await onSubmit(title.trim(), {
        ...brief,
        idea: brief.idea.trim(),
        style: brief.style.trim(),
        places: places
          .split("\n")
          .map((p) => p.trim())
          .filter(Boolean),
        lyrics: lyrics.trim() || null,
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
          With an 8B chat model a 3-minute song takes about a minute to plan; a larger model can
          take many minutes. Only words are made at this stage.
        </p>
      </header>
      <AnalysisCard analysis={analysis} />
      {list && list.length === 0 ? (
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
            <div className="flex items-center gap-2">
              <Checkbox
                label="Only in photos"
                checked={p.photos_only}
                onCheckedChange={(v) => person(i, { photos_only: v })}
              />
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
          <div>
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
