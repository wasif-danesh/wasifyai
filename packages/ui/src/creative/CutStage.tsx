"use client";
// The Cut step (ADR-0090 decision 7): the video on the stage, and a small, real timeline under it. One row of
// pictures (each shot's chosen version, for its length) and one row of captions, over the song. A piece or a
// caption is chosen with a click; what can be done to it shows under the rows. Keys on the timeline: space plays,
// S splits, the arrows move by a beat, Z undoes and Shift+Z redoes. Nothing here changes a picture or the song.
import type {
  CreativeApi,
  CreativeProject,
  CutCaption,
  CutEdit,
  CutPiece,
  CutState,
} from "@wasifyai/client";
import { Redo2, Undo2 } from "lucide-react";
import { type KeyboardEvent, type RefObject, useState } from "react";
import { cn } from "../cn";
import { Button } from "../components/button";
import { WorkingCard } from "../components/create";
import { Input } from "../components/input";
import { Notice } from "../components/notice";
import { Select } from "../components/select";
import { actions, hint, panel } from "../styles";
import { RunNotice } from "./ShotsStage";

export function clock(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

function seconds(n: number): string {
  return `${Number(n.toFixed(1))} s`;
}

const SIZE = {
  landscape: "1920 by 1080",
  portrait: "1080 by 1920",
  square: "1080 by 1080",
} as const;

type Chosen = { kind: "piece" | "caption"; id: string } | null;

export function CutStage({
  api,
  project,
  cut,
  act,
  edit,
  video,
  saved,
}: {
  api: CreativeApi;
  project: CreativeProject;
  cut: CutState;
  act: (work: () => Promise<CreativeProject>) => Promise<void>;
  edit: (edits: CutEdit[]) => void;
  video: RefObject<HTMLVideoElement | null>;
  /** what Save a copy wrote, or why it could not */
  saved: string | null;
}) {
  const run = project.shots.run;
  const making = project.shots_live && run?.kind === "cut";
  const busy = project.shots_live || project.live;
  const made = cut.render;
  const { summary } = cut;
  return (
    <div className="grid content-start gap-4">
      {making ? (
        <WorkingCard
          label={run?.stage || "Making the video"}
          onCancel={() => void act(() => api.stopStills(project.id))}
        />
      ) : (
        <RunNotice project={project} />
      )}
      {summary.plan_changed ? (
        <Notice
          tone="info"
          title="The plan has changed since this cut was made"
          actions={
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={busy}
              onClick={() => edit([{ op: "reset" }])}
            >
              Start again from the plan
            </Button>
          }
        >
          The cut keeps its own pieces. Start again to take the plan's shots and times.
        </Notice>
      ) : null}
      {saved ? (
        <Notice tone="info" title="Save a copy">
          {saved}
        </Notice>
      ) : null}
      {made?.url ? (
        <figure className="m-0 grid gap-1.5">
          <video
            ref={video}
            key={made.url}
            src={made.url}
            controls
            aria-label="The video of the cut"
            className="max-h-[50dvh] w-full rounded-md bg-black"
          >
            <track kind="captions" />
          </video>
          <figcaption className={hint}>
            {SIZE[made.shape]}, {clock(made.seconds)}, made in {clock(made.took_s)}.
            {made.current ? "" : " The cut has changed since: make it again to see the changes."}
          </figcaption>
        </figure>
      ) : (
        <div className={`${panel} grid gap-2`}>
          <p className="m-0 font-medium text-sm">No video of this cut yet</p>
          <p className={`${hint} m-0`}>
            It is made at full size with the song and the captions. For a 3-minute song of stills it
            takes about a minute on a fast Mac.
          </p>
        </div>
      )}
      <div className={actions}>
        <Button
          type="button"
          variant="outline"
          disabled={busy || (made?.current ?? false)}
          onClick={() => void act(() => api.makeVideo(project.id))}
        >
          {made ? "Make it again to watch" : "Make a version to watch"}
        </Button>
        <span className={hint}>
          {[
            summary.empty
              ? `${summary.empty === 1 ? "1 piece has" : `${summary.empty} pieces have`} no picture yet, so ${summary.empty === 1 ? "it is" : "they are"} black.`
              : "",
            summary.black_tail > 0.05
              ? `The pictures end ${seconds(summary.black_tail)} before the song; the rest is black.`
              : "",
            summary.cut_short > 0.05
              ? `The pictures run ${seconds(summary.cut_short)} past the song; that part is not shown.`
              : "",
          ]
            .filter(Boolean)
            .join(" ")}
        </span>
      </div>
      {cut.exports.length ? (
        <div className="grid gap-1">
          <h3 className="m-0 font-semibold text-sm">Kept in Your videos</h3>
          <ul aria-label="Kept in Your videos" className="m-0 grid list-none gap-0.5 p-0 text-sm">
            {cut.exports.map((e) => (
              <li key={e.video_id}>
                {e.title} <span className={hint}>{new Date(e.created_at).toLocaleString()}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

/** The timeline under the stage: pictures, then captions, then what can be done to the one chosen. */
export function Timeline({
  api,
  project,
  cut,
  coverOf,
  act,
  edit,
  video,
}: {
  api: CreativeApi;
  project: CreativeProject;
  cut: CutState;
  coverOf: (kind: string, item: string) => string | undefined;
  act: (work: () => Promise<CreativeProject>) => Promise<void>;
  edit: (edits: CutEdit[]) => void;
  video: RefObject<HTMLVideoElement | null>;
}) {
  const [chosen, setChosen] = useState<Chosen>(null);
  const busy = project.shots_live || project.live;
  const total = Math.max(cut.summary.song_s, cut.summary.pictures_end, 1);
  const piece = chosen?.kind === "piece" ? cut.items.find((p) => p.id === chosen.id) : undefined;
  const caption =
    chosen?.kind === "caption" ? cut.captions.find((c) => c.id === chosen.id) : undefined;
  const undo = () => void act(() => api.undoCut(project.id));
  const redo = () => void act(() => api.redoCut(project.id));

  const onKey = (e: KeyboardEvent<HTMLFieldSetElement>) => {
    const target = e.target as HTMLElement;
    if (target.closest("input, textarea, [role=combobox], [role=listbox]")) return;
    if (busy && e.key !== " ") return;
    const nudge = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
    if (e.key === " ") {
      const v = video.current;
      if (!v) return;
      e.preventDefault();
      if (v.paused) void v.play().catch(() => {});
      else v.pause();
    } else if (e.key.toLowerCase() === "z" && !e.metaKey && !e.ctrlKey) {
      e.preventDefault();
      if (e.shiftKey ? cut.can_redo : cut.can_undo) (e.shiftKey ? redo : undo)();
    } else if (e.key.toLowerCase() === "s" && piece) {
      e.preventDefault();
      edit([{ op: "split", item_id: piece.id }]);
    } else if (nudge && piece) {
      e.preventDefault();
      edit([{ op: "length", item_id: piece.id, by_beats: nudge }]);
    } else if (nudge && caption) {
      e.preventDefault();
      edit([{ op: "caption", caption_id: caption.id, by_beats: nudge }]);
    }
  };

  return (
    <section aria-label="Timeline" className="grid gap-2 border-t pt-3">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="m-0 font-semibold text-sm">Timeline</h2>
        <span className={hint}>
          {cut.items.length} pieces · {cut.captions.length} captions · {clock(cut.summary.song_s)}
        </span>
        <span className="grow" />
        <Button
          type="button"
          variant="ghost"
          size="sm"
          disabled={busy || !cut.can_undo}
          onClick={undo}
          title="Z"
        >
          <Undo2 aria-hidden /> Undo
        </Button>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          disabled={busy || !cut.can_redo}
          onClick={redo}
          title="Shift+Z"
        >
          <Redo2 aria-hidden /> Redo
        </Button>
      </div>
      <fieldset
        className="m-0 grid min-w-0 gap-1.5 overflow-x-auto border-0 p-0 pb-1"
        aria-label="Pictures and captions"
        onKeyDown={onKey}
        aria-describedby="cut-keys"
      >
        <ol aria-label="Pictures" className="m-0 flex h-16 min-w-[36rem] list-none gap-px p-0">
          {cut.items.map((p, n) => (
            <li key={p.id} className="min-w-6" style={{ flexGrow: p.length, flexBasis: 0 }}>
              <PieceButton
                piece={p}
                n={n}
                cover={p.kind && p.item_id ? coverOf(p.kind, p.item_id) : undefined}
                chosen={chosen?.kind === "piece" && chosen.id === p.id}
                onChoose={() => setChosen({ kind: "piece", id: p.id })}
              />
            </li>
          ))}
          {cut.summary.black_tail > 0.05 ? (
            <li
              aria-label={`${seconds(cut.summary.black_tail)} of black to the end of the song`}
              className="rounded-sm bg-black/80"
              style={{ flexGrow: cut.summary.black_tail, flexBasis: 0 }}
            />
          ) : null}
        </ol>
        {(["line", "title"] as const).map((row) => (
          <CaptionRow
            key={row}
            name={row === "line" ? "Captions" : "Titles"}
            captions={cut.captions.filter((c) => (row === "line") === (c.kind === "line"))}
            dim={row === "line" && !cut.captions_on}
            total={total}
            chosen={chosen?.kind === "caption" ? chosen.id : null}
            onChoose={(id) => setChosen({ kind: "caption", id })}
          />
        ))}
      </fieldset>
      <p id="cut-keys" className={`${hint} m-0`}>
        Choose a piece or a caption. Keys: space plays, S splits, the arrows move by a beat, Z
        undoes, Shift+Z redoes.
      </p>
      {piece ? (
        <PieceActions
          api={api}
          project={project}
          cut={cut}
          piece={piece}
          busy={busy}
          act={act}
          edit={edit}
          onGone={() => setChosen(null)}
        />
      ) : null}
      {caption ? (
        <CaptionActions
          key={`${caption.id}:${caption.text}`}
          caption={caption}
          busy={busy}
          edit={edit}
          onGone={() => setChosen(null)}
        />
      ) : null}
    </section>
  );
}

const KIND_WORD = { line: "Caption", title: "Title", lower: "Lower third" } as const;

/** The narrowest a caption is drawn, as a share of the shortest timeline (36rem): big enough to press. */
const NARROWEST = 1.5 / 36;

/** Lines of the row: each caption goes on the first line where it touches nothing, so none covers another. */
export function lanesOf(captions: CutCaption[], total: number): number[] {
  const ends: number[] = [];
  return captions.map((c) => {
    const from = c.start / total;
    const to = Math.max(c.end / total, from + NARROWEST);
    let lane = ends.findIndex((end) => end <= from);
    if (lane < 0) lane = ends.length;
    ends[lane] = to;
    return lane;
  });
}

/** One row of words over the song: the song's lines, or the titles and lower thirds, so neither hides the other. */
function CaptionRow({
  name,
  captions,
  dim,
  total,
  chosen,
  onChoose,
}: {
  name: string;
  captions: CutCaption[];
  dim: boolean;
  total: number;
  chosen: string | null;
  onChoose: (id: string) => void;
}) {
  if (!captions.length && name === "Titles") return null;
  const sorted = [...captions].sort((a, b) => a.start - b.start);
  const lanes = lanesOf(sorted, total);
  const lines = Math.max(1, ...lanes.map((l) => l + 1));
  return (
    <ol
      aria-label={name}
      className="relative m-0 min-w-[36rem] list-none p-0"
      style={{ height: `${lines * 2}rem` }}
    >
      {sorted.map((c, n) => (
        <li
          key={c.id}
          className="absolute h-8"
          style={{
            top: `${(lanes[n] ?? 0) * 2}rem`,
            left: `${(c.start / total) * 100}%`,
            width: `${Math.max((c.end - c.start) / total, NARROWEST) * 100}%`,
          }}
        >
          <button
            type="button"
            aria-pressed={chosen === c.id}
            aria-label={`${KIND_WORD[c.kind]} at ${clock(c.start)}: ${c.text}`}
            onClick={() => onChoose(c.id)}
            className={cn(
              "h-full w-full cursor-pointer truncate rounded-sm border px-1 text-start text-xs outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50",
              c.kind === "line" ? "bg-muted" : "bg-primary/15",
              dim ? "opacity-40" : "",
              chosen === c.id ? "border-primary" : "border-transparent",
            )}
          >
            {c.text}
          </button>
        </li>
      ))}
    </ol>
  );
}

function PieceButton({
  piece,
  n,
  cover,
  chosen,
  onChoose,
}: {
  piece: CutPiece;
  n: number;
  cover: string | undefined;
  chosen: boolean;
  onChoose: () => void;
}) {
  const what = piece.number ? `shot ${piece.number}` : "something you put in";
  return (
    <button
      type="button"
      aria-pressed={chosen}
      aria-label={`Piece ${n + 1}: ${what}, ${seconds(piece.length)} from ${clock(piece.start)}${piece.fade ? ", fades in" : ""}${piece.item_id ? "" : ", no picture yet"}`}
      onClick={onChoose}
      className={cn(
        "relative h-full w-full cursor-pointer overflow-hidden rounded-sm border-2 bg-muted bg-center bg-cover outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50",
        chosen ? "border-primary" : "border-transparent",
        piece.item_id ? "" : "bg-black",
      )}
      style={cover ? { backgroundImage: `url(${cover})` } : undefined}
    >
      <span className="absolute start-0.5 top-0.5 rounded-sm bg-background/80 px-1 text-[0.625rem]">
        {piece.number ?? "+"}
      </span>
      {piece.fade ? (
        <span
          aria-hidden
          className="absolute inset-y-0 start-0 w-2 bg-gradient-to-r from-black to-transparent"
        />
      ) : null}
    </button>
  );
}

function PieceActions({
  api,
  project,
  cut,
  piece,
  busy,
  act,
  edit,
  onGone,
}: {
  api: CreativeApi;
  project: CreativeProject;
  cut: CutState;
  piece: CutPiece;
  busy: boolean;
  act: (work: () => Promise<CreativeProject>) => Promise<void>;
  edit: (edits: CutEdit[]) => void;
  onGone: () => void;
}) {
  const at = cut.items.findIndex((p) => p.id === piece.id);
  const versions = piece.shot_id ? (project.shots.takes[piece.shot_id] ?? []) : [];
  const chosenVersion = versions.find((t) => t.chosen);
  const one = (e: CutEdit) => edit([e]);
  return (
    <div className={`${panel} grid gap-2`} aria-label="The chosen piece">
      <p className="m-0 text-sm">
        <span className="font-medium">
          Piece {at + 1}
          {piece.number ? `, shot ${piece.number}` : ""}
        </span>{" "}
        <span className={hint}>
          {seconds(piece.length)}, from {clock(piece.start)} to {clock(piece.end)}
        </span>
      </p>
      <div className={actions}>
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={busy}
          onClick={() => one({ op: "length", item_id: piece.id, by_beats: -1 })}
        >
          Shorter
        </Button>
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={busy}
          onClick={() => one({ op: "length", item_id: piece.id, by_beats: 1 })}
        >
          Longer
        </Button>
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={busy}
          onClick={() => one({ op: "split", item_id: piece.id })}
        >
          Split
        </Button>
        <Button
          type="button"
          size="sm"
          variant="outline"
          aria-pressed={piece.fade}
          disabled={busy}
          onClick={() => one({ op: "fade", item_id: piece.id, fade: !piece.fade })}
        >
          {piece.fade ? "Fades in" : "Fade in"}
        </Button>
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={busy || at === 0}
          onClick={() => one({ op: "move", item_id: piece.id, to: at - 1 })}
        >
          Move earlier
        </Button>
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={busy || at === cut.items.length - 1}
          onClick={() => one({ op: "move", item_id: piece.id, to: at + 1 })}
        >
          Move later
        </Button>
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={busy || cut.items.length === 1}
          onClick={() => {
            one({ op: "remove", item_id: piece.id });
            onGone();
          }}
        >
          Take out
        </Button>
      </div>
      {piece.source ? (
        <div className={actions}>
          <span className={hint}>Put in by hand, in place of the shot's version.</span>
          {piece.shot_id ? (
            <Button
              type="button"
              size="sm"
              variant="ghost"
              disabled={busy}
              onClick={() => one({ op: "use", item_id: piece.id, source_id: null })}
            >
              Use the shot's version
            </Button>
          ) : null}
        </div>
      ) : versions.length > 1 && piece.shot_id ? (
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm">Version</span>
          <Select
            aria-label={`Version of shot ${piece.number}`}
            value={chosenVersion?.id}
            disabled={busy}
            onValueChange={(take) =>
              void act(() => api.chooseTake(project.id, piece.shot_id ?? "", take))
            }
            options={versions.map((t, i) => ({
              value: t.id,
              label: `Version ${i + 1}${t.kind === "video" ? ", a clip" : t.kind === "lipsync" ? ", a sung clip" : ""}`,
            }))}
          />
          <span className={hint}>The same version is used on the Shots step.</span>
        </div>
      ) : null}
    </div>
  );
}

function CaptionActions({
  caption,
  busy,
  edit,
  onGone,
}: {
  caption: CutCaption;
  busy: boolean;
  edit: (edits: CutEdit[]) => void;
  onGone: () => void;
}) {
  const [text, setText] = useState(caption.text);
  const save = () => {
    const words = text.trim();
    if (words && words !== caption.text)
      edit([{ op: "caption", caption_id: caption.id, text: words }]);
  };
  return (
    <div className={`${panel} grid gap-2`} aria-label="The chosen caption">
      <p className="m-0 text-sm">
        <span className="font-medium">{KIND_WORD[caption.kind]}</span>{" "}
        <span className={hint}>
          from {clock(caption.start)} to {clock(caption.end)}
        </span>
      </p>
      <Input
        aria-label="Its words"
        value={text}
        maxLength={160}
        disabled={busy}
        onChange={(e) => setText(e.target.value)}
        onBlur={save}
        onKeyDown={(e) => {
          if (e.key === "Enter") save();
        }}
      />
      <div className={actions}>
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={busy}
          onClick={() => edit([{ op: "caption", caption_id: caption.id, by_beats: -1 }])}
        >
          A beat earlier
        </Button>
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={busy}
          onClick={() => edit([{ op: "caption", caption_id: caption.id, by_beats: 1 }])}
        >
          A beat later
        </Button>
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={busy}
          onClick={() => {
            edit([{ op: "remove_caption", caption_id: caption.id }]);
            onGone();
          }}
        >
          Take out
        </Button>
      </div>
    </div>
  );
}
