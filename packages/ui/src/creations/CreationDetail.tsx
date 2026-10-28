"use client";

import { type CreationKind, type CreationsApi, type MadeFrom, when } from "@wasifyai/client";
import {
  BookOpen,
  Box,
  ExternalLink,
  Film,
  GraduationCap,
  Maximize2,
  Pencil,
  RefreshCw,
  Save,
  Scissors,
  Shapes,
  Shuffle,
  Trash2,
} from "lucide-react";
import { useEffect, useState } from "react";
import type { Action } from "../components/actions-row";
import { ActionsRow } from "../components/actions-row";
import { ConfirmDialog, Modal } from "../components/dialog";
import { Player } from "../components/player";
import { Spinner } from "../components/spinner";
import { fileNameFor, savedText, useSaveCopy } from "../save";
import { clock } from "../voice/format";
import { type CreationsNav, type Entry, KIND_LABEL, type UseAction, toRow } from "./model";

/** The kind the products' routes and the search index use for an entry. */
export function apiKindOf(entry: Entry): CreationKind {
  return entry.kind === "song" ? "track" : entry.kind;
}

/** The file an entry is, to save a copy of: a picture, a clip, a recording; none for the tools' own kinds. */
export function fileOf(entry: Entry): { url: string; ext: string; name: string } | null {
  switch (entry.kind) {
    case "image":
      return { url: entry.image.image_url, ext: "png", name: entry.image.prompt };
    case "video":
      return entry.video.video_url
        ? { url: entry.video.video_url, ext: "mp4", name: entry.video.prompt }
        : null;
    case "song":
      return { url: entry.song.audio_url, ext: "wav", name: entry.song.title };
    case "speech":
      return { url: entry.speech.audio_url, ext: "wav", name: entry.speech.text.slice(0, 40) };
    case "lipsync":
      return { url: entry.lipsync.video_url, ext: "mp4", name: entry.lipsync.text || "lip sync" };
    default:
      return null;
  }
}

/** Where an entry came from, as the cards it can be looked up by: a picture, a clip or a track. */
function sourceOf(entry: Entry): { kind: "image" | "video" | "track"; id: string } | null {
  if (entry.kind === "image" && entry.image.source_id) {
    return { kind: "image", id: entry.image.source_id };
  }
  if (entry.kind === "video" && entry.video.source_id) {
    return { kind: entry.video.mode === "extend" ? "video" : "image", id: entry.video.source_id };
  }
  if (entry.kind === "song" && entry.song.parent_id) {
    return { kind: "track", id: entry.song.parent_id };
  }
  return null;
}

/** The entries a lookup found, as the Library's entries. */
function entriesOf(found: MadeFrom): Entry[] {
  return [
    ...found.images.map(
      (image): Entry => ({ kind: "image", id: image.id, createdAt: image.created_at, image }),
    ),
    ...found.videos.map(
      (video): Entry => ({ kind: "video", id: video.id, createdAt: video.created_at, video }),
    ),
    ...found.songs.map(
      (song): Entry => ({ kind: "song", id: song.id, createdAt: song.created_at, song }),
    ),
  ].sort((a, b) => Date.parse(b.createdAt) - Date.parse(a.createdAt));
}

const ICON = { model3d: Box, composition: Shapes, notebook: BookOpen, taught: GraduationCap };

/** A small tile for a related entry: its picture or poster when it has one, else its kind. */
function Tile({ entry, onOpen }: { entry: Entry; onOpen: (entry: Entry) => void }) {
  const row = toRow(entry);
  const cover =
    entry.kind === "image"
      ? entry.image.thumb_url
      : entry.kind === "video"
        ? (entry.video.poster_url ?? null)
        : null;
  return (
    <button
      type="button"
      onClick={() => onOpen(entry)}
      aria-label={`Open: ${row.title}`}
      className="grid w-24 shrink-0 gap-1 rounded-md border p-1 text-start outline-none hover:border-primary/50 focus-visible:ring-2 focus-visible:ring-ring"
    >
      {cover ? (
        <img src={cover} alt="" className="aspect-square w-full rounded object-cover" />
      ) : (
        <span className="grid aspect-square w-full place-items-center rounded bg-muted text-muted-foreground text-xs">
          {row.kindLabel}
        </span>
      )}
      <span className="line-clamp-2 text-[0.6875rem] leading-tight">{row.title}</span>
    </button>
  );
}

/**
 * One creation, large (ADR-0093, stage U8): the thing itself, what made it, where it came from and what was made
 * from it, three actions and a menu for the rest. Opened from any card of the Library; a related entry opens here
 * too.
 */
export function CreationDetail({
  entry,
  api,
  nav,
  onOpen,
  onClose,
  onRemoved,
}: {
  entry: Entry;
  api: CreationsApi;
  nav: CreationsNav;
  /** open another entry here (where it came from, what was made from it) */
  onOpen: (entry: Entry) => void;
  onClose: () => void;
  /** it was deleted: the Library takes it off its list */
  onRemoved: (entry: Entry) => void;
}) {
  const row = toRow(entry);
  const [source, setSource] = useState<Entry | null | "gone">(null);
  const [children, setChildren] = useState<Entry[] | null>(null);
  const [asking, setAsking] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const saveCopy = useSaveCopy();

  // where it came from
  const from = sourceOf(entry);
  const fromKey = from ? `${from.kind}:${from.id}` : "";
  // biome-ignore lint/correctness/useExhaustiveDependencies: `fromKey` is `from` as a value
  useEffect(() => {
    setSource(null);
    if (!from) return;
    let gone = false;
    api
      .cards({ [from.kind]: [from.id] })
      .then((found) => {
        if (gone) return;
        const all = entriesOf({
          images: found.images?.images ?? [],
          videos: found.videos?.videos ?? [],
          songs: found.songs,
        });
        setSource(all[0] ?? "gone");
      })
      .catch(() => !gone && setSource("gone"));
    return () => {
      gone = true;
    };
  }, [api, fromKey]);

  // what was made from it
  useEffect(() => {
    setChildren(null);
    const kind = entry.kind === "song" ? "track" : entry.kind;
    if (kind !== "image" && kind !== "video" && kind !== "track") return;
    let gone = false;
    api
      .madeFrom(kind, entry.id)
      .then((found) => !gone && setChildren(entriesOf(found)))
      .catch(() => !gone && setChildren([]));
    return () => {
      gone = true;
    };
  }, [api, entry.kind, entry.id]);

  const file = fileOf(entry);
  async function save() {
    if (!file) return;
    setProblem(null);
    try {
      const out = await saveCopy({
        name: fileNameFor(file.name, file.ext, KIND_LABEL[entry.kind].toLowerCase()),
        blob: async () => {
          const res = await fetch(file.url);
          if (!res.ok) throw new Error("That file could not be read.");
          return res.blob();
        },
      });
      if (out) setNote(savedText(out));
    } catch (e) {
      setProblem(e instanceof Error ? e.message : "That could not be saved.");
    }
  }

  async function remove() {
    setAsking(false);
    setProblem(null);
    try {
      await api.remove(apiKindOf(entry), entry.id);
      onRemoved(entry);
    } catch (e) {
      setProblem(e instanceof Error ? e.message : "That could not be deleted.");
    }
  }

  const can = (action: UseAction) =>
    Boolean(nav.use) && (nav.canUse ? nav.canUse(entry, action) : true);
  const use = (action: UseAction) => () => nav.use?.(entry, action);
  const tool = (action: UseAction, label: string, icon: React.ReactNode): Action[] =>
    can(action) ? [{ label, onSelect: use(action), icon }] : [];
  const madeHere =
    entry.kind === "song" &&
    (entry.song.mode === undefined || /^(song|sfx)$/.test(entry.song.mode));
  const ready =
    entry.kind !== "video" || entry.video.status === "done"
      ? entry.kind !== "model3d" || entry.model3d.status === "done"
      : false;

  const actions: Action[] = [
    ...(entry.kind === "image"
      ? [
          ...tool("edit", "Edit this", <Pencil aria-hidden="true" />),
          ...tool("animate", "Animate this", <Film aria-hidden="true" />),
        ]
      : []),
    ...(entry.kind === "video" && ready
      ? tool("extend", "Extend this", <Maximize2 aria-hidden="true" />)
      : []),
    ...(entry.kind === "song"
      ? [
          ...(madeHere ? tool("again", "Make it again", <RefreshCw aria-hidden="true" />) : []),
          ...tool("split", "Split into parts", <Scissors aria-hidden="true" />),
        ]
      : []),
    ...(entry.kind === "speech"
      ? [
          ...tool("convert", "Change the voice", <Shuffle aria-hidden="true" />),
          ...tool("speechedit", "Edit the words", <Pencil aria-hidden="true" />),
        ]
      : []),
    ...(file && ready
      ? [{ label: "Save a copy", onSelect: () => void save(), icon: <Save aria-hidden="true" /> }]
      : []),
    ...(entry.kind === "image" && entry.image.recipe
      ? tool("again", "Make it again", <RefreshCw aria-hidden="true" />)
      : []),
    ...(entry.kind === "song"
      ? [
          ...tool("convert", "Change the voice", <Shuffle aria-hidden="true" />),
          ...tool("speechedit", "Edit the words", <Pencil aria-hidden="true" />),
        ]
      : []),
    {
      label: "Open in its tool",
      onSelect: () => {
        onClose();
        nav.open(entry);
      },
      icon: <ExternalLink aria-hidden="true" />,
    },
    {
      label: "Delete",
      onSelect: () => setAsking(true),
      icon: <Trash2 aria-hidden="true" />,
      destructive: true,
    },
  ];

  const Icon = entry.kind in ICON ? ICON[entry.kind as keyof typeof ICON] : null;
  const preview =
    entry.kind === "image" ? (
      <img
        src={entry.image.image_url}
        alt={entry.image.prompt}
        className="max-h-[50vh] w-full rounded-lg bg-muted object-contain"
      />
    ) : entry.kind === "video" ? (
      entry.video.video_url ? (
        // biome-ignore lint/a11y/useMediaCaption: made clips have no speech to caption
        <video
          controls
          playsInline
          preload="metadata"
          poster={entry.video.poster_url ?? undefined}
          src={entry.video.video_url}
          className="max-h-[50vh] w-full rounded-lg bg-black"
        />
      ) : (
        <p className="m-0 flex items-center gap-2 text-muted-foreground">
          {entry.video.status === "working" ? <Spinner /> : null}
          {entry.video.status === "working"
            ? "This clip is still being made."
            : (entry.video.error ?? "This clip could not be made.")}
        </p>
      )
    ) : entry.kind === "lipsync" ? (
      // biome-ignore lint/a11y/useMediaCaption: a talking video made from the person's own words
      <video
        controls
        playsInline
        preload="metadata"
        poster={entry.lipsync.poster_url ?? undefined}
        src={entry.lipsync.video_url}
        className="max-h-[50vh] w-full rounded-lg bg-black"
      />
    ) : entry.kind === "song" || entry.kind === "speech" ? (
      <Player
        src={entry.kind === "song" ? entry.song.audio_url : entry.speech.audio_url}
        title={row.title}
        duration={entry.kind === "song" ? entry.song.seconds : entry.speech.seconds}
        waveform
      />
    ) : entry.kind === "transcript" ? (
      <p className="m-0 max-h-60 overflow-auto whitespace-pre-wrap rounded-md border bg-surface p-3 text-sm">
        {entry.transcript.preview}
      </p>
    ) : Icon ? (
      <div className="grid h-40 place-items-center rounded-lg bg-muted text-muted-foreground">
        <Icon className="size-12" aria-hidden="true" />
      </div>
    ) : null;

  const facts: [string, string][] = [
    ["Kind", KIND_LABEL[entry.kind]],
    ["Made", when(entry.createdAt)],
    ...(entry.kind === "image"
      ? ([
          ["Size", `${entry.image.width}×${entry.image.height}`],
          ...(entry.image.recipe
            ? ([
                ["Seed", String(entry.image.recipe.seed)],
                ...(entry.image.recipe.loras?.length
                  ? ([
                      [
                        "Styles",
                        entry.image.recipe.loras.map((l) => `${l.name} (${l.weight})`).join(", "),
                      ],
                    ] as [string, string][])
                  : []),
              ] as [string, string][])
            : []),
        ] as [string, string][])
      : []),
    ...(entry.kind === "video"
      ? ([["Length", clock(entry.video.seconds)]] as [string, string][])
      : []),
    ...(entry.kind === "song" && entry.song.seconds
      ? ([["Length", clock(entry.song.seconds)]] as [string, string][])
      : []),
    ...(entry.kind === "speech"
      ? ([
          ["Voice", entry.speech.voice],
          ["Length", clock(entry.speech.seconds)],
        ] as [string, string][])
      : []),
    ...(row.detail && !["image", "video", "speech"].includes(entry.kind)
      ? ([["About", row.detail]] as [string, string][])
      : []),
  ];

  return (
    <>
      <Modal label={row.title.slice(0, 80) || KIND_LABEL[entry.kind]} wide onClose={onClose}>
        <div className="grid gap-4" data-slot="creation-detail">
          {preview}
          <ActionsRow actions={actions} />
          {note ? <output className="text-sm">{note}</output> : null}
          {problem ? (
            <p role="alert" className="m-0 text-destructive text-sm">
              {problem}
            </p>
          ) : null}
          {row.title.length > 80 || entry.kind === "image" || entry.kind === "video" ? (
            <p className="m-0">{row.title}</p>
          ) : null}
          <dl className="m-0 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
            {facts.map(([k, v]) => (
              <div key={k} className="contents">
                <dt className="text-muted-foreground">{k}</dt>
                <dd className="m-0">{v}</dd>
              </div>
            ))}
          </dl>
          {from ? (
            <section aria-label="Made from" className="grid gap-2">
              <h3 className="m-0 font-semibold text-sm">Made from</h3>
              {source === null ? (
                <Spinner />
              ) : source === "gone" ? (
                <p className="m-0 text-muted-foreground text-sm">
                  It came from something that is no longer in the Library.
                </p>
              ) : (
                <div className="flex">
                  <Tile entry={source} onOpen={onOpen} />
                </div>
              )}
            </section>
          ) : null}
          {children && children.length > 0 ? (
            <section aria-label="Made from this" className="grid gap-2">
              <h3 className="m-0 font-semibold text-sm">Made from this</h3>
              <div className="flex gap-2 overflow-x-auto pb-1">
                {children.map((c) => (
                  <Tile key={`${c.kind}:${c.id}`} entry={c} onOpen={onOpen} />
                ))}
              </div>
            </section>
          ) : null}
        </div>
      </Modal>
      {asking ? (
        <ConfirmDialog
          title={`Delete this ${KIND_LABEL[entry.kind].toLowerCase()}?`}
          message={`“${row.title.slice(0, 80)}” is deleted for good.`}
          onConfirm={() => void remove()}
          onCancel={() => setAsking(false)}
        />
      ) : null}
    </>
  );
}
