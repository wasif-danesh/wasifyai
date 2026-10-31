"use client";
// Making something for a scene without leaving the editor (ADR-0096 MX6). The products' own actions
// make it and keep it in the Library; here is only what to ask for and where it goes.
import type {
  BuilderMakeRequest,
  MakeVoice,
  MakeWhat,
  ProjectAsset,
  Scene,
  SceneDocument,
} from "@wasifyai/client";
import { useId, useState } from "react";
import { Button } from "../../components/button";
import { Segmented } from "../../components/segmented";
import type { MakingNow } from "./use-scene-editor";

/** Where a picture goes: behind the scene, or on it where it can be moved. */
type PictureUse = "background" | "place";

const ASK: Record<MakeWhat, { label: string; hint: string; time: string; noun: string }> = {
  picture: {
    label: "What should it show?",
    hint: "A red can on a marble table, soft morning light",
    time: "This can take a minute or two.",
    noun: "picture",
  },
  clip: {
    label: "What should happen in it?",
    hint: "Steam rising from a cup, slowly",
    time: "This can take several minutes.",
    noun: "clip",
  },
  speech: {
    label: "What should it say?",
    hint: "Mornings are hard. Northbean makes them easier.",
    time: "This usually takes under a minute.",
    noun: "voiceover",
  },
  music: {
    label: "What should it sound like?",
    hint: "Warm acoustic guitar, unhurried",
    time: "This can take a few minutes.",
    noun: "music",
  },
};

/** Long enough to say it: the scene's own length, as far as that kind of scene can go. */
const lengthFor = (scene: Scene, seconds: number, maximum: number) => {
  const now = Number(scene.fields.seconds);
  if (!now || seconds <= now) return scene;
  return { ...scene, fields: { ...scene.fields, seconds: Math.min(Math.ceil(seconds), maximum) } };
};

export function MakeTools({
  doc,
  scene,
  number,
  making,
  longestScene,
  voices,
  onMake,
  onStop,
}: {
  doc: SceneDocument;
  scene: Scene | undefined;
  number: number;
  making: MakingNow | null;
  /** How long this scene can be, in seconds. */
  longestScene: number;
  voices: MakeVoice[];
  onMake: (
    request: BuilderMakeRequest,
    label: string,
    place: (d: SceneDocument, file: ProjectAsset, cues: Scene["cues"]) => SceneDocument,
  ) => void;
  onStop: () => void;
}) {
  const [what, setWhat] = useState<MakeWhat>("picture");
  const [texts, setTexts] = useState<Partial<Record<MakeWhat, string>>>({});
  const [use, setUse] = useState<PictureUse>("background");
  const [voice, setVoice] = useState("");
  const [captions, setCaptions] = useState(true);
  const boxId = useId();
  const ask = ASK[what];
  const text = (texts[what] ?? "").trim();
  const sceneId = scene?.id;

  // a scene that was removed meanwhile keeps nothing: the file stays in the project's files
  const onScene = (d: SceneDocument, change: (s: Scene) => Scene) => ({
    ...d,
    scenes: d.scenes.map((s) => (s.id === sceneId ? change(s) : s)),
  });

  function start() {
    if (what === "picture") {
      onMake({ what, text }, "Add a picture", (d, file) =>
        onScene(d, (s) =>
          use === "background"
            ? {
                ...s,
                background: { asset: file.id, fit: "cover", x: 50, y: 50, trim: 0, volume: 0 },
              }
            : { ...s, images: [...(s.images ?? []), { asset: file.id }] },
        ),
      );
    } else if (what === "clip") {
      const seconds = Number(scene?.fields.seconds) || 5;
      onMake({ what, text, seconds }, "Add a clip", (d, file) =>
        onScene(d, (s) => ({
          ...s,
          background: { asset: file.id, fit: "cover", x: 50, y: 50, trim: 0, volume: 0 },
        })),
      );
    } else if (what === "speech") {
      const request = { what, text, captions, ...(voice ? { voice } : {}) };
      onMake(request, "Add a voiceover", (d, file, cues) =>
        onScene(d, (s) => ({
          ...lengthFor(s, file.seconds, longestScene),
          sound: { asset: file.id, volume: 1, loop: false },
          cues: cues ?? [],
        })),
      );
    } else {
      onMake({ what, text, seconds: Math.max(5, doc.seconds) }, "Add music", (d, file) => ({
        ...d,
        soundtrack: { asset: file.id, volume: 0.4, start: 0, loop: true },
      }));
    }
  }

  return (
    <>
      <h2 className="m-0 font-semibold text-sm">
        {what === "music" ? "Make music for the whole video" : `Make for scene ${number}`}
      </h2>
      <Segmented
        size="sm"
        label="What to make"
        className="w-full"
        value={what}
        onValueChange={(v) => setWhat(v as MakeWhat)}
        options={[
          { value: "picture", label: "Picture" },
          { value: "clip", label: "Clip" },
          { value: "speech", label: "Speech" },
          { value: "music", label: "Music" },
        ]}
      />
      <div className="grid gap-1">
        <label className="font-medium text-sm" htmlFor={boxId}>
          {ask.label}
        </label>
        <textarea
          id={boxId}
          rows={3}
          maxLength={2000}
          placeholder={ask.hint}
          className="rounded-md border border-input bg-transparent px-3 py-2 text-sm"
          value={texts[what] ?? ""}
          onChange={(ev) => setTexts((t) => ({ ...t, [what]: ev.target.value }))}
        />
      </div>
      {what === "picture" ? (
        <Segmented
          size="sm"
          label="Where it goes"
          className="w-full"
          value={use}
          onValueChange={(v) => setUse(v as PictureUse)}
          options={[
            { value: "background", label: "Behind the scene" },
            { value: "place", label: "On the scene" },
          ]}
        />
      ) : null}
      {what === "speech" ? (
        <>
          {voices.length ? (
            <label className="grid gap-1 text-xs">
              Voice
              <select
                className="rounded-md border border-input bg-background px-2 py-1 text-sm"
                value={voice}
                onChange={(ev) => setVoice(ev.target.value)}
              >
                <option value="">The usual voice</option>
                {voices.map((v) => (
                  <option key={v.id} value={v.id}>
                    {v.name}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
          <label className="flex items-center gap-2 text-xs">
            <input
              type="checkbox"
              checked={captions}
              onChange={(ev) => setCaptions(ev.target.checked)}
            />
            Show the words as captions, in time
          </label>
        </>
      ) : null}
      {making ? (
        <output className="grid gap-2 rounded-md border p-2">
          <p className="m-0 text-sm">
            Making the {ASK[making.what].noun}…
            {making.progress != null ? ` ${Math.round(making.progress * 100)}%` : ""}
          </p>
          <p className="m-0 text-muted-foreground text-xs">
            You can keep working. {ASK[making.what].time}
          </p>
          <Button type="button" variant="outline" size="sm" onClick={onStop}>
            Stop
          </Button>
        </output>
      ) : (
        <>
          <Button
            type="button"
            size="sm"
            disabled={!text || (what !== "music" && !scene)}
            onClick={start}
          >
            Make the {ask.noun}
          </Button>
          <p className="m-0 text-muted-foreground text-xs">
            {ask.time} It is also kept in your Library.
          </p>
        </>
      )}
    </>
  );
}
