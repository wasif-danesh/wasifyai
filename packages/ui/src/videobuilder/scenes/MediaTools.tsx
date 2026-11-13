"use client";
// A project's files in the editor (ADR-0096 MX5): add them, put them on a scene, and hear them.
import type { ProjectAsset, Scene, SceneDocument } from "@wasifyai/client";
import { Film, Music, Trash2 } from "lucide-react";
import { type ChangeEvent, useRef, useState } from "react";
import { cn } from "../../cn";
import { Button } from "../../components/button";
import { Modal } from "../../components/dialog";

/** Something of the person's Library that can be brought into a project. */
export type LibraryItem = { kind: "image" | "video" | "audio"; id: string; title: string };

export type MediaLibrary = {
  list(): Promise<LibraryItem[]>;
  /** The file itself, to add to the project as any other. */
  read(item: LibraryItem): Promise<File>;
};

const fileOf = (doc: SceneDocument, id?: string) => doc.assets?.find((a) => a.id === id) ?? null;

const ACCEPT = "image/png,image/jpeg,image/webp,video/mp4,video/quicktime,video/webm,audio/*";

function Thumb({ file, base }: { file: ProjectAsset; base: string | null }) {
  if (file.kind === "image" && base) {
    return <img src={`${base}assets/${file.file}`} alt="" className="size-full object-cover" />;
  }
  return file.kind === "video" ? (
    <Film className="size-5" aria-hidden="true" />
  ) : (
    <Music className="size-5" aria-hidden="true" />
  );
}

/** Add a file from this computer, or from the Library. */
export function AddFile({
  onFile,
  library,
  accept = ACCEPT,
  what = "photo or clip",
}: {
  onFile: (file: File) => Promise<void>;
  library?: MediaLibrary;
  accept?: string;
  what?: string;
}) {
  const input = useRef<HTMLInputElement>(null);
  const [adding, setAdding] = useState(false);
  const [items, setItems] = useState<LibraryItem[] | null>(null);
  const [problem, setProblem] = useState<string | null>(null);

  async function add(file: File) {
    setAdding(true);
    setProblem(null);
    try {
      await onFile(file);
    } catch (e) {
      setProblem(e instanceof Error ? e.message : "That file could not be added.");
    } finally {
      setAdding(false);
    }
  }

  function picked(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (file) void add(file);
  }

  return (
    <div className="grid gap-1.5">
      <div className="flex flex-wrap gap-1.5">
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={adding}
          onClick={() => input.current?.click()}
        >
          {adding ? "Adding…" : "From this computer"}
        </Button>
        {library ? (
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={adding}
            onClick={() => {
              setProblem(null);
              void library
                .list()
                .then(setItems)
                .catch(() => setProblem("Your Library could not be read."));
            }}
          >
            From Library
          </Button>
        ) : null}
      </div>
      <input
        ref={input}
        type="file"
        hidden
        accept={accept}
        aria-label={`Add a ${what}`}
        onChange={picked}
      />
      {problem ? (
        <p role="alert" className="m-0 text-destructive text-xs">
          {problem}
        </p>
      ) : null}
      {items && library ? (
        <Modal label="Choose from your Library" onClose={() => setItems(null)}>
          {items.length === 0 ? (
            <p className="m-0 text-muted-foreground text-sm">Nothing in your Library yet.</p>
          ) : (
            <ul className="m-0 grid max-h-96 list-none gap-1 overflow-auto p-0">
              {items.map((item) => (
                <li key={`${item.kind}:${item.id}`}>
                  <button
                    type="button"
                    className="w-full truncate rounded-md border p-2 text-start text-sm hover:bg-muted"
                    onClick={() => {
                      setItems(null);
                      setAdding(true);
                      void library
                        .read(item)
                        .then(add)
                        .catch(() => setProblem("That could not be read from your Library."))
                        .finally(() => setAdding(false));
                    }}
                  >
                    {item.title || "Untitled"}{" "}
                    <span className="text-muted-foreground text-xs">({item.kind})</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Modal>
      ) : null}
    </div>
  );
}

export function MediaTools({
  doc,
  scene,
  number,
  base,
  library,
  onFile,
  onRemoveFile,
  onChangeScene,
  onCapture,
}: {
  doc: SceneDocument;
  scene: Scene | undefined;
  number: number;
  /** where the page's files are, for their small pictures */
  base: string | null;
  library?: MediaLibrary;
  onFile: (file: File) => Promise<void>;
  onRemoveFile: (id: string) => void;
  onChangeScene: (label: string, change: (s: Scene) => Scene) => void;
  onCapture: () => Promise<void>;
}) {
  const [chosen, setChosen] = useState<string | null>(null);
  const files = (doc.assets ?? []).filter((a) => a.kind !== "audio");
  const file = files.find((a) => a.id === chosen) ?? null;
  return (
    <>
      <h2 className="m-0 font-semibold text-sm">Photos and clips</h2>
      <p className="m-0 text-muted-foreground text-xs">
        For scene {number}. MP4 or MOV with H.264 works best. Up to 100 MB each.
      </p>
      <AddFile
        onFile={async (file) => {
          await onFile(file);
        }}
        library={library}
      />
      {files.length > 0 ? (
        <>
          <h3 className="m-0 font-medium text-sm">In this project</h3>
          <div className="grid grid-cols-3 gap-1.5">
            {files.map((a) => (
              <button
                key={a.id}
                type="button"
                aria-pressed={chosen === a.id}
                aria-label={a.name}
                title={a.name}
                onClick={() => setChosen(a.id)}
                className={cn(
                  "grid aspect-square place-items-center overflow-hidden rounded-md border bg-muted",
                  chosen === a.id && "outline-2 outline-primary outline-offset-1",
                )}
              >
                <Thumb file={a} base={base} />
              </button>
            ))}
          </div>
        </>
      ) : null}
      {file && scene ? (
        <div className="grid gap-1.5">
          <p className="m-0 truncate text-xs">{file.name}</p>
          {file.kind === "video" && file.codec && file.codec !== "h264" ? (
            <p className="m-0 text-muted-foreground text-xs">
              This clip is {file.codec}. It may not play in the preview, and H.264 is safer.
            </p>
          ) : null}
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() =>
              onChangeScene("Use as the background", (s) => ({
                ...s,
                background: { asset: file.id, fit: "cover", x: 50, y: 50, trim: 0, volume: 0 },
              }))
            }
          >
            Use as background
          </Button>
          {file.kind === "image" ? (
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() =>
                onChangeScene("Place a picture", (s) => ({
                  ...s,
                  images: [...(s.images ?? []), { asset: file.id }],
                }))
              }
            >
              Place on scene
            </Button>
          ) : null}
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={() => {
              onRemoveFile(file.id);
              setChosen(null);
            }}
          >
            <Trash2 className="size-4" aria-hidden="true" /> Remove from the project
          </Button>
        </div>
      ) : null}
      <Button type="button" variant="ghost" size="sm" onClick={() => void onCapture()}>
        Save this scene as a picture
      </Button>
    </>
  );
}

export function SoundTools({
  doc,
  scene,
  number,
  library,
  onFile,
  onChangeScene,
}: {
  doc: SceneDocument;
  scene: Scene | undefined;
  number: number;
  library?: MediaLibrary;
  onFile: (file: File) => Promise<ProjectAsset | undefined>;
  onChangeScene: (label: string, change: (s: Scene) => Scene) => void;
}) {
  const sounds = (doc.assets ?? []).filter((a) => a.kind === "audio");
  const sound = scene?.sound;
  const use = (id: string) =>
    onChangeScene("Add a sound", (s) => ({ ...s, sound: { asset: id, volume: 0.8, loop: false } }));
  const current = fileOf(doc, sound?.asset);
  return (
    <>
      <h2 className="m-0 font-semibold text-sm">Sound for scene {number}</h2>
      <p className="m-0 text-muted-foreground text-xs">
        It plays only during this scene. Music for the whole video is in the row at the bottom.
      </p>
      {sound ? (
        <div className="grid gap-2 rounded-md border p-2">
          <p className="m-0 truncate text-sm">{current?.name ?? "A sound"}</p>
          <label className="grid gap-1 text-xs">
            Volume
            <input
              type="range"
              min={0}
              max={1}
              step={0.05}
              value={sound.volume}
              className="accent-primary"
              onChange={(ev) => {
                const volume = Number(ev.target.value);
                onChangeScene("Change the volume", (s) =>
                  s.sound ? { ...s, sound: { ...s.sound, volume } } : s,
                );
              }}
            />
          </label>
          <label className="flex items-center gap-2 text-xs">
            <input
              type="checkbox"
              checked={sound.loop}
              onChange={(ev) => {
                const loop = ev.target.checked;
                onChangeScene("Change the sound", (s) =>
                  s.sound ? { ...s, sound: { ...s.sound, loop } } : s,
                );
              }}
            />
            Repeat it to fill the scene
          </label>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={() => onChangeScene("Remove the sound", (s) => ({ ...s, sound: null }))}
          >
            Remove the sound
          </Button>
        </div>
      ) : null}
      <AddFile
        accept="audio/*"
        what="sound"
        library={library}
        onFile={async (file) => {
          const added = await onFile(file);
          if (added) use(added.id);
        }}
      />
      {sounds.length > 0 ? (
        <div className="grid gap-1">
          <h3 className="m-0 font-medium text-sm">In this project</h3>
          {sounds.map((a) => (
            <button
              key={a.id}
              type="button"
              className="truncate rounded-md border p-2 text-start text-xs hover:bg-muted"
              onClick={() => use(a.id)}
            >
              {a.name}
            </button>
          ))}
        </div>
      ) : null}
    </>
  );
}

export function FilmSoundtrack({
  doc,
  library,
  onFile,
  onChange,
}: {
  doc: SceneDocument;
  library?: MediaLibrary;
  onFile: (file: File) => Promise<ProjectAsset | undefined>;
  onChange: (label: string, track: SceneDocument["soundtrack"]) => void;
}) {
  const track = doc.soundtrack;
  const sounds = (doc.assets ?? []).filter((a) => a.kind === "audio");
  const current = fileOf(doc, track?.asset);
  const use = (id: string) =>
    onChange("Add music", { asset: id, volume: 0.4, loop: true, start: 0 });
  return (
    <div className="flex flex-wrap items-center gap-2 rounded-md border px-2 py-1 text-xs">
      <Music className="size-4" aria-hidden="true" />
      <span className="font-medium">Music for the whole video</span>
      {track ? (
        <>
          <span className="max-w-40 truncate text-muted-foreground">{current?.name}</span>
          <label className="ms-auto flex items-center gap-1">
            Volume
            <input
              type="range"
              min={0}
              max={1}
              step={0.05}
              value={track.volume}
              className="w-20 accent-primary"
              onChange={(ev) =>
                onChange("Change the music", { ...track, volume: Number(ev.target.value) })
              }
            />
          </label>
          <label className="flex items-center gap-1">
            Starts at
            <input
              type="number"
              min={0}
              max={doc.seconds}
              value={track.start}
              className="w-14 rounded border border-input bg-transparent px-1"
              onChange={(ev) =>
                onChange("Change the music", { ...track, start: Number(ev.target.value) || 0 })
              }
            />
          </label>
          <label className="flex items-center gap-1">
            <input
              type="checkbox"
              checked={track.loop}
              onChange={(ev) => onChange("Change the music", { ...track, loop: ev.target.checked })}
            />
            Repeat
          </label>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={() => onChange("Remove the music", null)}
          >
            Remove
          </Button>
        </>
      ) : (
        <span className="ms-auto flex flex-wrap items-center gap-1.5">
          {sounds.map((a) => (
            <Button key={a.id} type="button" variant="ghost" size="sm" onClick={() => use(a.id)}>
              {a.name}
            </Button>
          ))}
          <AddFile
            accept="audio/*"
            what="music file"
            library={library}
            onFile={async (file) => {
              const added = await onFile(file);
              if (added) use(added.id);
            }}
          />
        </span>
      )}
    </div>
  );
}

export function BackgroundDetails({
  scene,
  doc,
  onChange,
}: {
  scene: Scene;
  doc: SceneDocument;
  onChange: (label: string, change: (s: Scene) => Scene, together?: string) => void;
}) {
  const { background: back, images: pictures = [] } = scene;
  const file = fileOf(doc, back?.asset);
  if ((!back || !file) && pictures.length === 0) return null;
  const set = (label: string, part: Partial<NonNullable<Scene["background"]>>, key: string) =>
    onChange(
      label,
      (s) => (s.background ? { ...s, background: { ...s.background, ...part } } : s),
      `${scene.id}:${key}`,
    );
  return (
    <div className="grid gap-2 rounded-md border p-2">
      {back && file ? (
        <>
          <p className="m-0 truncate font-medium text-sm">Behind: {file.name}</p>
          <label className="flex items-center gap-2 text-xs">
            <input
              type="checkbox"
              checked={back.fit === "contain"}
              onChange={(ev) =>
                set("Change how it fits", { fit: ev.target.checked ? "contain" : "cover" }, "fit")
              }
            />
            Show the whole of it
          </label>
          <label className="grid gap-1 text-xs">
            Left and right
            <input
              type="range"
              min={0}
              max={100}
              value={back.x}
              className="accent-primary"
              onChange={(ev) => set("Move the background", { x: Number(ev.target.value) }, "x")}
            />
          </label>
          <label className="grid gap-1 text-xs">
            Up and down
            <input
              type="range"
              min={0}
              max={100}
              value={back.y}
              className="accent-primary"
              onChange={(ev) => set("Move the background", { y: Number(ev.target.value) }, "y")}
            />
          </label>
          {file.kind === "video" ? (
            <label className="grid gap-1 text-xs">
              Starts {back.trim} seconds in
              <input
                type="range"
                min={0}
                max={Math.max(0, file.seconds - 0.5)}
                step={0.1}
                value={back.trim}
                className="accent-primary"
                onChange={(ev) => set("Trim the clip", { trim: Number(ev.target.value) }, "trim")}
              />
            </label>
          ) : null}
          {file.kind === "video" && file.has_audio ? (
            <label className="grid gap-1 text-xs">
              Its own sound
              <input
                type="range"
                min={0}
                max={1}
                step={0.05}
                value={back.volume}
                className="accent-primary"
                onChange={(ev) =>
                  set("Change its sound", { volume: Number(ev.target.value) }, "vol")
                }
              />
            </label>
          ) : null}
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={() => onChange("Remove the background", (s) => ({ ...s, background: null }))}
          >
            Remove the background
          </Button>
        </>
      ) : null}
      {pictures.map((p, i) => (
        <div key={`${p.asset}-${i}`} className="flex items-center justify-between gap-2 text-xs">
          <span className="truncate">
            Placed: {doc.assets?.find((a) => a.id === p.asset)?.name ?? "A picture"}
          </span>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={() =>
              onChange("Remove a picture", (s) => {
                const images = (s.images ?? []).filter((_, n) => n !== i);
                const arrange = { ...s.arrange };
                delete arrange[`image-${i}`];
                // the pictures after it move up one, with their places
                for (let n = i + 1; n <= images.length; n++) {
                  const place = arrange[`image-${n}`];
                  if (place) arrange[`image-${n - 1}`] = place;
                  delete arrange[`image-${n}`];
                }
                return { ...s, images, arrange };
              })
            }
          >
            Remove
          </Button>
        </div>
      ))}
    </div>
  );
}
