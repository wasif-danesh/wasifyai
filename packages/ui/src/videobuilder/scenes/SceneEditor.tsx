"use client";
// The Motion graphics editor (ADR-0096, mockup docs/spikes/motion-editor-mockup.html): add on the left,
// the film in the middle, the selected scene on the right, the scenes along the bottom. MX3 adds the
// assistant beside the scene's details, MX4 arranging on the preview, MX5 and MX6 more tools on the left.
import type {
  AssistantApi,
  BuilderProject,
  BuilderShape,
  BuilderSlots,
  BuilderTheme,
  Scene,
  SceneDocument,
  TemplateCatalogue,
  TemplateInfo,
  VideoBuilderApi,
  VideosApi,
} from "@wasifyai/client";
import {
  ArrowLeft,
  ArrowRight,
  ChevronLeft,
  ChevronRight,
  Copy,
  Pause,
  Play,
  Redo2,
  Trash2,
  Undo2,
} from "lucide-react";
import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { ChatScreen, type ChatScreenProps } from "../../chat/ChatScreen";
import type { ChatToolResult } from "../../chat/thread/use-thread-chat";
import { cn } from "../../cn";
import { Button } from "../../components/button";
import { Modal } from "../../components/dialog";
import { Notice } from "../../components/notice";
import { Bar } from "../../components/progress-bar";
import { Segmented } from "../../components/segmented";
import { extensionOf, fileNameFor, savedText, useSaveCopy } from "../../save";
import { FormField } from "../FormField";
import { toDraft } from "../slots";
import { ArrangeOverlay, type MeasuredPart, laidOut } from "./ArrangeOverlay";
import { LivePreview, type LivePreviewHandle } from "./LivePreview";
import { lengthOf, sceneAt, startOf, useSceneEditor } from "./use-scene-editor";

const SIZES: Record<BuilderShape, { width: number; height: number; label: string }> = {
  landscape: { width: 1280, height: 720, label: "16:9" },
  portrait: { width: 720, height: 1280, label: "9:16" },
  square: { width: 1080, height: 1080, label: "1:1" },
};
const WHOLE_PROJECT = new Set(["shape", "font", "seconds", "theme"]);
const TRANSITIONS = [
  { value: "none", label: "Cut" },
  { value: "fade", label: "Fade" },
  { value: "slide", label: "Slide" },
];
const FIRST_WORDS: Record<string, Record<string, string | number>> = {
  title: { title: "A few words", seconds: 5 },
  quote: { quote: "What someone said", seconds: 5 },
  chart: { title: "Your numbers", data: "First, 10\nSecond, 20", seconds: 5 },
  lower_third: { name: "A name", seconds: 5 },
  captions: { lines: "Your first line", per_line: "3" },
};

/** The actions whose result the screen reads back. Making the video changes nothing here. */
const CHANGES_THE_PROJECT =
  /^motion\.(set_project|add_scene|change_scene|move_scene|duplicate_scene|remove_scene|undo)$/;

const LAYOUTS = [
  { where: "design", label: "As designed" },
  { where: "top", label: "Top" },
  { where: "middle", label: "Middle" },
  { where: "bottom", label: "Bottom" },
] as const;
const MEASURE_AFTER_MS = [400, 900, 1600, 3000];

/** A moment in a scene with everything on it: the same idea as the engine's `hold`. */
function settledMoment(scene: Scene): number {
  const seconds = Number(scene.fields.seconds) || 0;
  if (scene.kind === "captions") return Math.min(1, seconds / 2);
  if (scene.kind === "lower_third") return (0.7 + seconds - 0.6) / 2;
  return Math.max(0, seconds - 0.1);
}

const clock = (seconds: number) =>
  `${Math.floor(seconds / 60)}:${String(Math.floor(seconds % 60)).padStart(2, "0")}`;

const firstWords = (scene: Scene) => {
  const f = scene.fields;
  const said = f.title ?? f.quote ?? f.name ?? f.lines ?? "";
  const text = Array.isArray(said) ? said[0] : said;
  return String(text ?? "");
};

/** What the app gives the editor so the assistant can be docked in it (ADR-0096 MX3). */
export type EditorAssistant = Pick<
  ChatScreenProps,
  | "runs"
  | "images"
  | "tracks"
  | "notices"
  | "blockedReason"
  | "onNeedModel"
  | "onOpenSettings"
  | "model"
> & { api: AssistantApi };

const SUGGESTIONS = [
  "Shorten this scene",
  "Add an end card",
  "Try a calmer look",
  "Make a square version",
];

export function SceneEditor({
  api,
  project,
  catalogue,
  videos,
  canSave,
  downloadHref,
  onBack,
  onOpenLibrary,
  assistant,
  brief,
}: {
  api: VideoBuilderApi;
  project: BuilderProject;
  catalogue: TemplateCatalogue;
  videos?: Pick<VideosApi, "exportCopy">;
  canSave?: boolean;
  downloadHref?: (videoId: string) => string;
  onBack: () => void;
  onOpenLibrary?: () => void;
  assistant?: EditorAssistant;
  /** What the person asked for on the first screen: sent to the assistant when the editor opens. */
  brief?: string;
}) {
  const e = useSceneEditor(api, project);
  const [panel, setPanel] = useState<"assistant" | "scene">(brief ? "assistant" : "scene");
  // while the assistant works, the project is its: a save from here would undo what it just did
  const [busy, setBusy] = useState(false);
  const { document: doc, selected } = e;
  const player = useRef<LivePreviewHandle>(null);
  // a moment in, not the very start: a film that fades in is black at 0:00
  const [time, setTime] = useState(() =>
    Math.min(0.9, (Number(doc.scenes[0]?.fields.seconds) || 0) / 2),
  );
  const [playing, setPlaying] = useState(false);
  const [tool, setTool] = useState<"add" | "looks">("add");
  const [making, setMaking] = useState(false);
  const shape = SIZES[doc.shape];
  const index = Math.max(
    0,
    doc.scenes.findIndex((s) => s.id === selected),
  );
  const scene = doc.scenes[index];
  const total = lengthOf(doc);

  // a scene chosen, added or brought back by Undo is shown; one the film or the slider reached is
  // already there, and the film must not be moved back to its start
  const reached = useRef<string | null>(selected);
  const shown = useRef({ doc, seek: (at: number) => player.current?.seek(at) });
  shown.current.doc = doc;
  useEffect(() => {
    if (reached.current === selected) return;
    reached.current = selected;
    const at = shown.current.doc.scenes.findIndex((s) => s.id === selected);
    const target = shown.current.doc.scenes[at];
    if (!target) return;
    const seconds = Number(target.fields.seconds) || 0;
    const moment = startOf(shown.current.doc, at) + Math.min(0.9, seconds / 2);
    setTime(moment);
    shown.current.seek(moment);
  }, [selected]);

  // arranging: the scene with everything on it, and where the page says its parts are now
  const [mode, setMode] = useState<"watch" | "arrange">("watch");
  const [measured, setMeasured] = useState<Record<string, MeasuredPart> | null>(null);
  const scenePlace = scene ? `${scene.id}:${index}:${doc.shape}` : "";
  const settled = scene ? startOf(doc, index) + settledMoment(scene) : 0;
  // biome-ignore lint/correctness/useExhaustiveDependencies: a save reloads the page, so it is asked again
  useEffect(() => {
    if (mode !== "arrange" || !selected) return;
    setTime(settled);
    player.current?.seek(settled);
    const timers = MEASURE_AFTER_MS.map((ms) =>
      setTimeout(() => {
        void player.current?.measure(selected).then((parts) => {
          if (parts) setMeasured(parts);
        });
      }, ms),
    );
    return () => {
      for (const timer of timers) clearTimeout(timer);
    };
  }, [mode, selected, scenePlace, settled, e.revision]);

  /** A layout, or back to the design: from where the parts are now. */
  const layOut = useCallback(
    async (where: "design" | "top" | "middle" | "bottom") => {
      if (!scene) return;
      if (where === "design") {
        e.changeScene(scene.id, "Back to the design", (s) => ({ ...s, arrange: {} }));
        return;
      }
      player.current?.pause();
      const moment = startOf(doc, index) + settledMoment(scene);
      setTime(moment);
      player.current?.seek(moment);
      await new Promise((go) => setTimeout(go, 150));
      const parts = await player.current?.measure(scene.id);
      if (!parts) return;
      const next = laidOut(where, parts, scene.arrange ?? {});
      e.changeScene(scene.id, "Change the layout", (s) => ({ ...s, arrange: next }));
    },
    [scene, doc, index, e.changeScene],
  );

  const goTo = useCallback(
    (id: string) => {
      player.current?.pause();
      e.select(id);
    },
    [e.select],
  );

  // playing, the selection follows the film; choosing a scene is what moves it otherwise
  const onTime = useCallback(
    (seconds: number) => {
      // paused, the screen says where the film is: an older page, shorter than the film is now, would
      // answer with its own end while the new one loads
      if (!playing) return;
      setTime(seconds);
      const now = doc.scenes[sceneAt(doc, seconds)];
      if (now && now.id !== selected) {
        reached.current = now.id;
        e.select(now.id);
      }
    },
    [doc, playing, selected, e.select],
  );

  // typing stops the film, so the scene does not change under the person's hands
  const stopForEdit = useCallback(() => player.current?.pause(), []);

  const url = e.live ? `${e.live.url}?v=${e.revision}` : null;

  const [conversation, setConversation] = useState(project.conversation_id ?? null);
  const keepConversation = useCallback(
    (id: string) => {
      setConversation((known) => {
        if (known !== id) void api.keepConversation(project.id, id).catch(() => {});
        return id;
      });
    },
    [api, project.id],
  );
  const workingOn = useMemo(
    () => ({
      working_on: {
        action_id: "motion.read_project",
        params: { composition_id: project.id, scene_id: selected || undefined },
      },
    }),
    [project.id, selected],
  );
  const adopt = e.adopt;
  const onToolResult = useCallback(
    (result: ChatToolResult) => {
      const action = String(result.output?.action_id ?? "");
      if (result.status !== "ok" || !CHANGES_THE_PROJECT.test(action)) return;
      const sceneId = result.output?.scene_id;
      void adopt(
        result.id,
        "The assistant's change",
        typeof sceneId === "string" ? sceneId : undefined,
      );
    },
    [adopt],
  );

  return (
    <div className="@container flex min-h-0 flex-1 flex-col" data-slot="scene-editor">
      <header className="flex flex-wrap items-center gap-2 border-b bg-background px-3 py-2">
        <Button type="button" variant="ghost" size="sm" onClick={onBack}>
          <ArrowLeft className="size-4" aria-hidden="true" /> Motion graphics
        </Button>
        <input
          aria-label="Project name"
          className="w-44 min-w-0 rounded-md border border-transparent bg-transparent px-2 py-1 font-semibold text-sm hover:border-input"
          value={doc.name}
          placeholder="Name your project"
          maxLength={80}
          onChange={(ev) =>
            e.apply("Change the name", (d) => ({ ...d, name: ev.target.value }), "name")
          }
          onBlur={e.endGroup}
        />
        <output className="text-muted-foreground text-xs" data-save={e.saveState}>
          {e.saveState === "saved" ? "Saved" : e.saveState === "saving" ? "Saving…" : "Not saved"}
        </output>
        <div className="mx-auto">
          <Segmented
            size="sm"
            label="Shape"
            value={doc.shape}
            onValueChange={(v) =>
              e.apply("Change the shape", (d) => ({ ...d, shape: v as BuilderShape }))
            }
            options={Object.entries(SIZES).map(([value, s]) => ({ value, label: s.label }))}
          />
        </div>
        <Button
          type="button"
          variant="ghost"
          size="icon-sm"
          disabled={!e.canUndo || busy}
          aria-label={e.undoLabel ? `Undo: ${e.undoLabel}` : "Undo"}
          title={e.undoLabel ? `Undo: ${e.undoLabel}` : "Undo"}
          onClick={() => void e.undo()}
        >
          <Undo2 className="size-4" aria-hidden="true" />
        </Button>
        <Button
          type="button"
          variant="ghost"
          size="icon-sm"
          disabled={!e.canRedo || busy}
          aria-label="Redo"
          title="Redo"
          onClick={e.redo}
        >
          <Redo2 className="size-4" aria-hidden="true" />
        </Button>
        <Button
          type="button"
          size="sm"
          disabled={busy}
          onClick={() => {
            setMaking(true);
            void e.make();
          }}
        >
          Make the video
        </Button>
      </header>
      {e.problem ? (
        <div className="px-3 pt-2">
          <Notice tone="error" title="That did not work">
            {e.problem}
          </Notice>
        </div>
      ) : null}
      <div className="grid min-h-0 flex-1 grid-cols-1 overflow-auto @4xl:grid-cols-[15rem_minmax(0,1fr)_18rem] @4xl:overflow-hidden @6xl:grid-cols-[16rem_minmax(0,1fr)_20rem]">
        <aside
          aria-label="Add to your video"
          inert={busy}
          className="order-3 flex min-h-0 flex-col border-t @4xl:order-1 @4xl:border-e @4xl:border-t-0"
        >
          <div className="p-2">
            <Segmented
              size="sm"
              label="Tools"
              className="w-full"
              value={tool}
              onValueChange={(v) => setTool(v as "add" | "looks")}
              options={[
                { value: "add", label: "Add" },
                { value: "looks", label: "Looks" },
              ]}
            />
          </div>
          <div className="grid flex-1 content-start gap-3 overflow-auto p-3 pt-1">
            {tool === "add" ? (
              <AddTools catalogue={catalogue} onAdd={e.addScene} />
            ) : (
              <LooksTools
                catalogue={catalogue}
                scene={scene}
                index={index}
                onLook={(theme) => {
                  if (scene) {
                    e.changeScene(scene.id, "Change the look", (s) => ({
                      ...s,
                      fields: { ...s.fields, theme },
                    }));
                  }
                }}
                onEvery={() => {
                  const theme = scene?.fields.theme;
                  e.apply("Use this look on every scene", (d) => ({
                    ...d,
                    scenes: d.scenes.map((s) => ({ ...s, fields: { ...s.fields, theme } })),
                  }));
                }}
              />
            )}
          </div>
        </aside>
        <main className="order-1 flex h-[26rem] min-w-0 flex-col gap-2 p-3 @4xl:order-2 @4xl:h-auto @4xl:min-h-0">
          <div className="flex items-center gap-1">
            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              aria-label="Scene before"
              disabled={index === 0}
              onClick={() => {
                const s = doc.scenes[index - 1];
                if (s) goTo(s.id);
              }}
            >
              <ChevronLeft className="size-4" aria-hidden="true" />
            </Button>
            <span className="font-medium text-sm">
              Scene {index + 1} of {doc.scenes.length}
            </span>
            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              aria-label="Scene after"
              disabled={index === doc.scenes.length - 1}
              onClick={() => {
                const s = doc.scenes[index + 1];
                if (s) goTo(s.id);
              }}
            >
              <ChevronRight className="size-4" aria-hidden="true" />
            </Button>
            <div className="ms-auto">
              <Segmented
                size="sm"
                label="Watch or arrange"
                value={mode}
                onValueChange={(v) => {
                  player.current?.pause();
                  setMode(v as "watch" | "arrange");
                }}
                options={[
                  { value: "watch", label: "Watch" },
                  { value: "arrange", label: "Arrange" },
                ]}
              />
            </div>
          </div>
          <div className="grid min-h-0 flex-1 place-items-center overflow-hidden rounded-lg bg-muted p-2">
            <LivePreview
              ref={player}
              url={url}
              width={shape.width}
              height={shape.height}
              at={time}
              onTime={onTime}
              onPlaying={setPlaying}
              over={
                mode === "arrange" && scene && !busy ? (
                  <ArrangeOverlay
                    parts={measured}
                    placed={scene.arrange ?? {}}
                    ratio={shape.width / shape.height}
                    onLive={(part, rect) => player.current?.place(scene.id, part, rect)}
                    onCommit={(part, rect, together) =>
                      e.changeScene(
                        scene.id,
                        "Move on the scene",
                        (s) => ({ ...s, arrange: { ...s.arrange, [part]: rect } }),
                        together,
                      )
                    }
                  />
                ) : null
              }
            />
          </div>
          <div className="flex items-center gap-2">
            <Button
              type="button"
              size="icon-sm"
              aria-label={playing ? "Pause" : "Play"}
              onClick={() => {
                setMode("watch");
                if (playing) player.current?.pause();
                else player.current?.play();
              }}
            >
              {playing ? (
                <Pause className="size-4" aria-hidden="true" />
              ) : (
                <Play className="size-4" aria-hidden="true" />
              )}
            </Button>
            <span className="w-9 text-muted-foreground text-xs tabular-nums">{clock(time)}</span>
            <input
              type="range"
              aria-label="Move through the video"
              className="min-w-0 flex-1 accent-primary"
              min={0}
              max={total}
              step={0.05}
              value={Math.min(time, total)}
              onChange={(ev) => {
                const at = Number(ev.target.value);
                player.current?.pause();
                setTime(at);
                player.current?.seek(at);
                const now = doc.scenes[sceneAt(doc, at)];
                if (now) {
                  reached.current = now.id;
                  e.select(now.id);
                }
              }}
            />
            <span className="w-9 text-muted-foreground text-xs tabular-nums">{clock(total)}</span>
          </div>
          <p className="m-0 text-muted-foreground text-xs">
            {mode === "arrange"
              ? "Drag a part to move it, or a corner to resize it. Keep words inside the dashed line."
              : "The preview is close. The video you make is the final word."}
          </p>
        </main>
        <aside
          aria-label="Assistant and scene details"
          className="order-4 flex min-h-[28rem] flex-col border-t @4xl:order-3 @4xl:min-h-0 @4xl:border-s @4xl:border-t-0"
        >
          {assistant ? (
            <div className="p-2">
              <Segmented
                size="sm"
                label="Assistant or scene details"
                className="w-full"
                value={panel}
                onValueChange={(v) => setPanel(v as "assistant" | "scene")}
                options={[
                  { value: "assistant", label: "Assistant" },
                  { value: "scene", label: `Scene ${index + 1}` },
                ]}
              />
            </div>
          ) : null}
          {assistant ? (
            // kept while the other tab shows: a chat that is working must not be stopped by a click
            <div hidden={panel !== "assistant"} className="min-h-0 flex-1">
              <ChatScreen
                runs={assistant.runs}
                assistant={assistant.api}
                images={assistant.images}
                tracks={assistant.tracks}
                notices={assistant.notices}
                blockedReason={assistant.blockedReason}
                onNeedModel={assistant.onNeedModel}
                onOpenSettings={assistant.onOpenSettings}
                model={assistant.model}
                examples={SUGGESTIONS}
                conversationId={conversation}
                onConversation={keepConversation}
                runInput={workingOn}
                beforeTurn={e.saveNow}
                onToolResult={onToolResult}
                onWorking={setBusy}
                undoOfTool={e.undoOfTool}
                firstMessage={brief}
              />
            </div>
          ) : null}
          <div
            hidden={Boolean(assistant) && panel !== "scene"}
            inert={busy}
            className="min-h-0 flex-1 overflow-auto p-3"
          >
            {scene ? (
              <SceneDetails
                key={scene.id}
                scene={scene}
                number={index + 1}
                catalogue={catalogue}
                canRemove={doc.scenes.length > 1}
                onFocus={stopForEdit}
                onBlur={e.endGroup}
                onChange={(label, change, together) =>
                  e.changeScene(scene.id, label, change, together)
                }
                onLayout={(where) => void layOut(where)}
                onDuplicate={() => e.duplicateScene(scene.id)}
                onRemove={() => e.removeScene(scene.id)}
              />
            ) : null}
          </div>
        </aside>
        <section
          aria-label="Your scenes"
          inert={busy}
          className="order-2 border-t @4xl:order-4 @4xl:col-span-3"
        >
          <SceneStrip
            doc={doc}
            selected={selected}
            catalogue={catalogue}
            total={total}
            onSelect={goTo}
            onMove={e.moveScene}
            onAdd={() =>
              e.addScene({
                name: "",
                kind: "title",
                caption: "",
                transition: "fade",
                fields: { ...FIRST_WORDS.title, theme: scene?.fields.theme ?? "midnight" },
              })
            }
          />
        </section>
      </div>
      {making ? (
        <MakeDialog
          editor={e}
          title={doc.name || project.title}
          videos={videos}
          canSave={canSave}
          downloadHref={downloadHref}
          onOpenLibrary={onOpenLibrary}
          onClose={() => {
            setMaking(false);
            e.clearRender();
          }}
        />
      ) : null}
    </div>
  );
}

function AddTools({
  catalogue,
  onAdd,
}: {
  catalogue: TemplateCatalogue;
  onAdd: (scene: Omit<Scene, "id">) => void;
}) {
  return (
    <>
      <h2 className="m-0 font-semibold text-sm">Add a scene</h2>
      <p className="m-0 text-muted-foreground text-xs">It goes after the scene you are on.</p>
      <div className="grid gap-1.5">
        {catalogue.templates.map((t: TemplateInfo) => (
          <button
            key={t.id}
            type="button"
            className="grid gap-0.5 rounded-md border p-2 text-start hover:bg-muted"
            onClick={() =>
              onAdd({
                name: "",
                kind: t.id,
                caption: "",
                transition: "fade",
                fields: { ...FIRST_WORDS[t.id] },
              })
            }
          >
            <span className="font-medium text-sm">{t.title}</span>
            <span className="text-muted-foreground text-xs">{t.description}</span>
          </button>
        ))}
      </div>
    </>
  );
}

function LooksTools({
  catalogue,
  scene,
  index,
  onLook,
  onEvery,
}: {
  catalogue: TemplateCatalogue;
  scene: Scene | undefined;
  index: number;
  onLook: (theme: string) => void;
  onEvery: () => void;
}) {
  const current = String(scene?.fields.theme ?? "midnight");
  return (
    <>
      <h2 className="m-0 font-semibold text-sm">Look of scene {index + 1}</h2>
      <div className="grid grid-cols-2 gap-1.5">
        {Object.entries(catalogue.themes).map(([id, t]) => (
          <button
            key={id}
            type="button"
            aria-pressed={current === id}
            className={cn(
              "overflow-hidden rounded-md border text-start text-xs",
              current === id && "outline-2 outline-primary outline-offset-1",
            )}
            onClick={() => onLook(id)}
          >
            <span
              className="block h-9"
              style={{ background: `linear-gradient(135deg, ${t.from}, ${t.to})` }}
            />
            <span className="block px-2 py-1 capitalize">{id}</span>
          </button>
        ))}
      </div>
      <Button type="button" variant="outline" size="sm" onClick={onEvery}>
        Use this look on every scene
      </Button>
    </>
  );
}

function SceneDetails({
  scene,
  number,
  catalogue,
  canRemove,
  onFocus,
  onBlur,
  onChange,
  onLayout,
  onDuplicate,
  onRemove,
}: {
  scene: Scene;
  number: number;
  catalogue: TemplateCatalogue;
  canRemove: boolean;
  onFocus: () => void;
  onBlur: () => void;
  onChange: (label: string, change: (s: Scene) => Scene, together?: string) => void;
  onLayout: (where: "design" | "top" | "middle" | "bottom") => void;
  onDuplicate: () => void;
  onRemove: () => void;
}) {
  const nameId = useId();
  const captionId = useId();
  const template = catalogue.templates.find((t) => t.id === scene.kind);
  if (!template) return null;
  const draft = toDraft(template, scene.fields as BuilderSlots);
  const length = template.fields.find((f) => f.kind === "seconds");
  const seconds = Number(scene.fields.seconds) || 0;
  return (
    <form
      className="grid gap-4"
      aria-label={`Scene ${number}`}
      onFocus={onFocus}
      onBlur={onBlur}
      onSubmit={(ev) => ev.preventDefault()}
    >
      <div className="grid gap-1">
        <label className="font-medium text-sm" htmlFor={nameId}>
          Scene name
        </label>
        <input
          id={nameId}
          className="rounded-md border border-input bg-transparent px-3 py-2 text-sm"
          value={scene.name}
          maxLength={60}
          onChange={(ev) =>
            onChange(
              "Change the name",
              (s) => ({ ...s, name: ev.target.value }),
              `${scene.id}:name`,
            )
          }
        />
      </div>
      {template.fields
        .filter((f) => !WHOLE_PROJECT.has(f.id))
        .map((f) => (
          <FormField
            key={f.id}
            info={f}
            value={draft[f.id] ?? ""}
            catalogue={catalogue}
            onChange={(v) =>
              onChange(
                "Change the words",
                (s) => ({ ...s, fields: { ...s.fields, [f.id]: v } }),
                `${scene.id}:${f.id}`,
              )
            }
          />
        ))}
      {scene.kind !== "captions" ? (
        <div className="grid gap-1">
          <label className="font-medium text-sm" htmlFor={captionId}>
            Captions <span className="font-normal text-muted-foreground">(optional)</span>
          </label>
          <textarea
            id={captionId}
            rows={2}
            maxLength={140}
            className="rounded-md border border-input bg-transparent px-3 py-2 text-sm"
            value={scene.caption}
            onChange={(ev) =>
              onChange(
                "Change the captions",
                (s) => ({ ...s, caption: ev.target.value }),
                `${scene.id}:caption`,
              )
            }
          />
        </div>
      ) : null}
      {length ? (
        <div className="grid gap-1">
          <span className="font-medium text-sm">How long is it on screen?</span>
          <div className="flex items-center gap-2">
            <Button
              type="button"
              variant="outline"
              size="icon-sm"
              aria-label="One second less"
              disabled={seconds <= length.min}
              onClick={() =>
                onChange("Change the length", (s) => ({
                  ...s,
                  fields: { ...s.fields, seconds: seconds - 1 },
                }))
              }
            >
              −
            </Button>
            <output className="min-w-20 text-center text-sm">{seconds} seconds</output>
            <Button
              type="button"
              variant="outline"
              size="icon-sm"
              aria-label="One second more"
              disabled={seconds >= length.max}
              onClick={() =>
                onChange("Change the length", (s) => ({
                  ...s,
                  fields: { ...s.fields, seconds: seconds + 1 },
                }))
              }
            >
              +
            </Button>
          </div>
        </div>
      ) : null}
      <div className="grid gap-1">
        <span className="font-medium text-sm">How it starts</span>
        <Segmented
          size="sm"
          label="How it starts"
          className="w-full"
          value={scene.transition}
          onValueChange={(v) =>
            onChange("Change how it starts", (s) => ({
              ...s,
              transition: v as Scene["transition"],
            }))
          }
          options={TRANSITIONS}
        />
      </div>
      <div className="grid gap-1">
        <span className="font-medium text-sm">Where the words go</span>
        <div className="flex flex-wrap gap-1.5">
          {LAYOUTS.map(({ where, label }) => (
            <Button
              key={where}
              type="button"
              variant="outline"
              size="sm"
              onClick={() => onLayout(where)}
            >
              {label}
            </Button>
          ))}
        </div>
        <p className="m-0 text-muted-foreground text-xs">
          Then move anything yourself with Arrange, above the preview.
        </p>
      </div>
      <div className="flex gap-2">
        <Button type="button" variant="outline" size="sm" className="flex-1" onClick={onDuplicate}>
          <Copy className="size-4" aria-hidden="true" /> Duplicate
        </Button>
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="flex-1"
          disabled={!canRemove}
          onClick={onRemove}
        >
          <Trash2 className="size-4" aria-hidden="true" /> Remove
        </Button>
      </div>
    </form>
  );
}

function SceneStrip({
  doc,
  selected,
  catalogue,
  total,
  onSelect,
  onMove,
  onAdd,
}: {
  doc: SceneDocument;
  selected: string;
  catalogue: TemplateCatalogue;
  total: number;
  onSelect: (id: string) => void;
  onMove: (id: string, to: number) => void;
  onAdd: () => void;
}) {
  const from = useRef<string | null>(null);
  const at = doc.scenes.findIndex((s) => s.id === selected);
  return (
    <div className="grid gap-1.5 p-2">
      <div className="flex items-center justify-between gap-2 text-xs">
        <span className="font-semibold text-sm">Your scenes</span>
        <span className="flex items-center gap-1 text-muted-foreground">
          {doc.scenes.length} {doc.scenes.length === 1 ? "scene" : "scenes"}, {clock(total)}
          <Button
            type="button"
            variant="ghost"
            size="icon-xs"
            aria-label="Move this scene earlier"
            disabled={at <= 0}
            onClick={() => onMove(selected, at - 1)}
          >
            <ArrowLeft aria-hidden="true" />
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="icon-xs"
            aria-label="Move this scene later"
            disabled={at >= doc.scenes.length - 1}
            onClick={() => onMove(selected, at + 1)}
          >
            <ArrowRight aria-hidden="true" />
          </Button>
        </span>
      </div>
      <ol className="m-0 flex list-none gap-2 overflow-x-auto p-0.5">
        {doc.scenes.map((scene, i) => {
          const look = catalogue.themes[String(scene.fields.theme ?? "midnight") as BuilderTheme];
          return (
            <li key={scene.id} className="shrink-0">
              <button
                type="button"
                draggable
                aria-current={scene.id === selected ? "true" : undefined}
                aria-label={`Scene ${i + 1}, ${scene.name}, ${scene.fields.seconds} seconds`}
                onClick={() => onSelect(scene.id)}
                onDragStart={() => {
                  from.current = scene.id;
                }}
                onDragOver={(ev) => ev.preventDefault()}
                onDrop={(ev) => {
                  ev.preventDefault();
                  if (from.current && from.current !== scene.id) onMove(from.current, i);
                  from.current = null;
                }}
                className={cn(
                  "grid w-36 gap-1 rounded-md border p-1 text-start",
                  scene.id === selected && "outline-2 outline-primary",
                )}
              >
                <span
                  className="flex h-14 items-center overflow-hidden rounded-sm px-2 font-semibold text-xs leading-tight"
                  style={{
                    background: look
                      ? `linear-gradient(135deg, ${look.from}, ${look.to})`
                      : undefined,
                    color: look?.ink,
                  }}
                >
                  <span className="line-clamp-3">{firstWords(scene)}</span>
                </span>
                <span className="flex justify-between gap-2 text-xs">
                  <span className="truncate font-medium">
                    {i + 1}. {scene.name}
                  </span>
                  <span className="text-muted-foreground">
                    {clock(Number(scene.fields.seconds) || 0)}
                  </span>
                </span>
              </button>
            </li>
          );
        })}
        <li className="shrink-0">
          <button
            type="button"
            onClick={onAdd}
            className="grid h-full w-24 place-items-center rounded-md border border-dashed text-muted-foreground text-xs hover:bg-muted"
          >
            + Add a scene
          </button>
        </li>
      </ol>
    </div>
  );
}

function MakeDialog({
  editor,
  title,
  videos,
  canSave,
  downloadHref,
  onOpenLibrary,
  onClose,
}: {
  editor: ReturnType<typeof useSceneEditor>;
  title: string;
  videos?: Pick<VideosApi, "exportCopy">;
  canSave?: boolean;
  downloadHref?: (videoId: string) => string;
  onOpenLibrary?: () => void;
  onClose: () => void;
}) {
  const { render, problem } = editor;
  const save = useSaveCopy();
  const [saved, setSaved] = useState<string | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  const working = render?.status === "working";
  const done = render?.status === "done" && render.video_url;
  useEffect(() => setSaved(null), []);

  async function saveCopy(videoId: string) {
    if (!videos) return;
    setFailed(null);
    try {
      const wrote = await save({
        name: fileNameFor(title, extensionOf(render?.video_url ?? "", "mp4"), "video"),
        copy: (path) => videos.exportCopy(videoId, path),
      });
      if (wrote) setSaved(savedText(wrote));
    } catch (e) {
      setFailed(e instanceof Error ? e.message : "The video could not be saved.");
    }
  }

  return (
    <Modal label="Make the video" onClose={onClose}>
      <div className="grid gap-3">
        {done ? <p className="m-0 font-medium">Your video is in the Library.</p> : null}
        {working || !render ? (
          <div className="grid gap-1.5">
            <p className="m-0 text-sm">
              {!render
                ? "Saving your changes…"
                : render.stage === "checking"
                  ? "Checking the words on the screen…"
                  : "Drawing the video…"}
            </p>
            <Bar value={render && render.progress > 0 ? render.progress * 100 : undefined} />
            <p className="m-0 text-muted-foreground text-xs">You can keep working while it runs.</p>
          </div>
        ) : null}
        {problem ? (
          <Notice tone="error" title="That did not work">
            {problem}
          </Notice>
        ) : null}
        {render?.status === "failed" || render?.status === "cancelled" ? (
          <Notice tone="error" title="The video was not made">
            {render.error ?? "It was stopped."}
          </Notice>
        ) : null}
        {done && render.video_url ? (
          <>
            {/* biome-ignore lint/a11y/useMediaCaption: the words are the picture; a made video has no track */}
            <video
              controls
              src={render.video_url}
              poster={render.poster_url ?? undefined}
              className="max-h-72 w-full rounded-md bg-black"
            />
            {render.check?.ok ? (
              <p className="m-0 text-muted-foreground text-xs">{render.check.message}</p>
            ) : null}
          </>
        ) : null}
        {saved ? <p className="m-0 text-sm">{saved}</p> : null}
        {failed ? (
          <Notice tone="error" title="That did not work">
            {failed}
          </Notice>
        ) : null}
        <div className="flex flex-wrap justify-end gap-2">
          {working ? (
            <Button type="button" variant="outline" onClick={() => void editor.cancel()}>
              Stop
            </Button>
          ) : null}
          {done && render.video_id && canSave ? (
            <Button
              type="button"
              variant="outline"
              onClick={() => void saveCopy(render.video_id as string)}
            >
              Save a copy
            </Button>
          ) : null}
          {done && render.video_id && downloadHref ? (
            <Button asChild variant="outline">
              <a href={downloadHref(render.video_id)} download>
                Download
              </a>
            </Button>
          ) : null}
          {done && onOpenLibrary ? (
            <Button type="button" variant="outline" onClick={onOpenLibrary}>
              Open in Library
            </Button>
          ) : null}
          <Button type="button" onClick={onClose}>
            {working ? "Keep working" : "Close"}
          </Button>
        </div>
      </div>
    </Modal>
  );
}
