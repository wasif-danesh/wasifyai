"use client";
// The editor's state (ADR-0096): one document, one selection, an Undo that groups a typing session
// into one step, and a save queue that never lets an old save overwrite a newer edit.
import type {
  BuilderProject,
  BuilderRender,
  Scene,
  SceneDocument,
  VideoBuilderApi,
} from "@wasifyai/client";
import { useCallback, useEffect, useRef, useState } from "react";

const SAVE_AFTER_MS = 500;
const POLL_MS = 700;
const KEEP_STEPS = 100;
const RENEW_BEFORE_S = 300;

export type SaveState = "saved" | "saving" | "failed";

/** One Undo step; `toolId` when the assistant made it, so its card in the chat can undo it. */
type Step = { label: string; document: SceneDocument; toolId?: string };

export const say = (e: unknown, fallback: string) =>
  e instanceof Error && e.message ? e.message : fallback;

export const lengthOf = (document: SceneDocument) =>
  document.scenes.reduce((sum, s) => sum + (Number(s.fields.seconds) || 0), 0);

export const startOf = (document: SceneDocument, index: number) =>
  document.scenes.slice(0, index).reduce((sum, s) => sum + (Number(s.fields.seconds) || 0), 0);

/** The scene playing at a moment of the film. */
export function sceneAt(document: SceneDocument, seconds: number): number {
  let index = 0;
  while (index < document.scenes.length - 1 && seconds >= startOf(document, index + 1)) index++;
  return index;
}

/** An id of the kind the engine keeps: eight hex digits, unused in this document. */
export function newSceneId(document: SceneDocument): string {
  for (;;) {
    const id = Math.floor(Math.random() * 0xffffffff)
      .toString(16)
      .padStart(8, "0");
    if (!document.scenes.some((s) => s.id === id)) return id;
  }
}

/** What the engine worked out and the screen did not: lengths of captions, default names. It does
 * not replace the words, which are the person's as they type them. */
export function withWorkedOut(local: SceneDocument, saved: SceneDocument): SceneDocument {
  const scenes = local.scenes.map((scene) => {
    const from = saved.scenes.find((s) => s.id === scene.id);
    if (!from) return scene;
    return {
      ...scene,
      name: scene.name || from.name,
      fields: { ...scene.fields, seconds: from.fields.seconds },
    };
  });
  return { ...local, scenes };
}

export function useSceneEditor(api: VideoBuilderApi, project: BuilderProject) {
  const [document, setDocument] = useState<SceneDocument>(
    project.slots as unknown as SceneDocument,
  );
  const [selected, setSelected] = useState<string>(document.scenes[0]?.id ?? "");
  const [past, setPast] = useState<Step[]>([]);
  const [future, setFuture] = useState<Step[]>([]);
  const [saveState, setSaveState] = useState<SaveState>("saved");
  const [problem, setProblem] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);
  const [canUndoSaved, setCanUndoSaved] = useState(project.can_undo);
  const [live, setLive] = useState<{ url: string; expires_at: number } | null>(null);
  const [render, setRender] = useState<BuilderRender | null>(null);

  const alive = useRef(true);
  const latest = useRef(document);
  latest.current = document;
  const group = useRef<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const saving = useRef<Promise<void> | null>(null);
  const dirty = useRef(false);
  const madeByTools = useRef(new Set<string>());

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  const renewLive = useCallback(async () => {
    try {
      const address = await api.live(project.id);
      if (alive.current) setLive(address);
    } catch (e) {
      if (alive.current) setProblem(say(e, "The preview could not be opened."));
    }
  }, [api, project.id]);

  useEffect(() => {
    void renewLive();
  }, [renewLive]);

  const saveNow = useCallback(async (): Promise<void> => {
    if (saving.current) {
      await saving.current; // one at a time, and the next one sends whatever is newest
      return saveNow();
    }
    if (!dirty.current) return;
    dirty.current = false;
    const sent = latest.current;
    setSaveState("saving");
    saving.current = api
      .update(project.id, sent)
      .then((saved) => {
        if (!alive.current) return;
        setCanUndoSaved(saved.can_undo);
        setProblem(null);
        setDocument((now) => withWorkedOut(now, saved.slots as unknown as SceneDocument));
        setRevision((r) => r + 1);
        setSaveState(dirty.current ? "saving" : "saved");
      })
      .catch((e) => {
        if (!alive.current) return;
        dirty.current = true; // kept: the next change, or a retry, sends it
        setSaveState("failed");
        setProblem(say(e, "Your change could not be saved."));
      })
      .finally(() => {
        saving.current = null;
      });
    await saving.current;
  }, [api, project.id]);

  const saveSoon = useCallback(() => {
    dirty.current = true;
    setSaveState("saving");
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => void saveNow(), SAVE_AFTER_MS);
  }, [saveNow]);

  // leaving the editor: what was typed last is not lost
  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
      if (dirty.current) void api.update(project.id, latest.current).catch(() => {});
    },
    [api, project.id],
  );

  /** One change. Changes with the same `together` key (one typing session) are one Undo step. */
  const apply = useCallback(
    (label: string, change: (d: SceneDocument) => SceneDocument, together?: string) => {
      const before = latest.current;
      const after = change(before);
      if (after === before) return;
      if (!together || group.current !== together) {
        setPast((p) => [...p.slice(1 - KEEP_STEPS), { label, document: before }]);
        setFuture([]);
      }
      group.current = together ?? null;
      latest.current = after;
      setDocument(after);
      saveSoon();
    },
    [saveSoon],
  );

  const endGroup = useCallback(() => {
    group.current = null;
  }, []);

  const keepSelection = useCallback((d: SceneDocument) => {
    setSelected((id) => (d.scenes.some((s) => s.id === id) ? id : (d.scenes[0]?.id ?? "")));
  }, []);

  const undo = useCallback(async () => {
    group.current = null;
    const step = past[past.length - 1];
    if (step) {
      const now = latest.current;
      setPast(past.slice(0, -1));
      setFuture((f) => [...f, { label: step.label, document: now }]);
      latest.current = step.document;
      setDocument(step.document);
      keepSelection(step.document);
      saveSoon();
      return;
    }
    // nothing from this visit: the versions kept with the project
    try {
      await saveNow();
      const back = await api.undo(project.id);
      const restored = back.slots as unknown as SceneDocument;
      if (!alive.current || !restored.scenes) return;
      latest.current = restored;
      setDocument(restored);
      keepSelection(restored);
      setCanUndoSaved(back.can_undo);
      setRevision((r) => r + 1);
    } catch (e) {
      setProblem(say(e, "That could not be undone."));
    }
  }, [past, keepSelection, saveSoon, saveNow, api, project.id]);

  /** What the assistant just changed, read from the engine: one Undo step of its own. */
  const adopt = useCallback(
    async (toolId: string, label: string, sceneId?: string) => {
      try {
        const found = await api.get(project.id);
        const next = found.slots as unknown as SceneDocument;
        if (!alive.current || !next.scenes) return;
        const before = latest.current;
        group.current = null;
        setPast((p) => [...p.slice(1 - KEEP_STEPS), { label, document: before, toolId }]);
        setFuture([]);
        madeByTools.current.add(toolId);
        latest.current = next;
        setDocument(next);
        if (sceneId && next.scenes.some((s) => s.id === sceneId)) setSelected(sceneId);
        else keepSelection(next);
        setCanUndoSaved(found.can_undo);
        setRevision((r) => r + 1);
      } catch (e) {
        if (alive.current) setProblem(say(e, "The assistant's change could not be read."));
      }
    },
    [api, project.id, keepSelection],
  );

  /** Undo on a change's card: back to before that change, and so also before the ones after it. */
  const undoOfTool = useCallback(
    (toolId: string) => {
      if (!madeByTools.current.has(toolId)) return null; // from an earlier visit, or nothing changed
      const at = past.findIndex((s) => s.toolId === toolId);
      return {
        undone: at < 0,
        undo: () => {
          const step = past[at];
          if (!step) return;
          const now = latest.current;
          group.current = null;
          setPast(past.slice(0, at));
          setFuture((f) => [...f, { label: step.label, document: now }]);
          latest.current = step.document;
          setDocument(step.document);
          keepSelection(step.document);
          saveSoon();
        },
      };
    },
    [past, keepSelection, saveSoon],
  );

  const redo = useCallback(() => {
    group.current = null;
    const step = future[future.length - 1];
    if (!step) return;
    const now = latest.current;
    setFuture(future.slice(0, -1));
    setPast((p) => [...p, { label: step.label, document: now }]);
    latest.current = step.document;
    setDocument(step.document);
    keepSelection(step.document);
    saveSoon();
  }, [future, keepSelection, saveSoon]);

  const changeScene = useCallback(
    (id: string, label: string, change: (s: Scene) => Scene, together?: string) => {
      apply(
        label,
        (d) => ({ ...d, scenes: d.scenes.map((s) => (s.id === id ? change(s) : s)) }),
        together,
      );
    },
    [apply],
  );

  const moveScene = useCallback(
    (id: string, to: number) => {
      apply("Move a scene", (d) => {
        const from = d.scenes.findIndex((s) => s.id === id);
        if (from < 0 || to < 0 || to >= d.scenes.length || from === to) return d;
        const scenes = [...d.scenes];
        const [scene] = scenes.splice(from, 1);
        if (scene) scenes.splice(to, 0, scene);
        return { ...d, scenes };
      });
    },
    [apply],
  );

  /** Add a scene right after the selected one, and select it. */
  const addScene = useCallback(
    (scene: Omit<Scene, "id">) => {
      const id = newSceneId(latest.current);
      apply("Add a scene", (d) => {
        const at = d.scenes.findIndex((s) => s.id === selected);
        const scenes = [...d.scenes];
        scenes.splice(at + 1, 0, { ...scene, id });
        return { ...d, scenes };
      });
      setSelected(id);
    },
    [apply, selected],
  );

  const duplicateScene = useCallback(
    (id: string) => {
      const scene = latest.current.scenes.find((s) => s.id === id);
      if (!scene) return;
      const copy = newSceneId(latest.current);
      apply("Copy a scene", (d) => {
        const at = d.scenes.findIndex((s) => s.id === id);
        const scenes = [...d.scenes];
        scenes.splice(at + 1, 0, { ...scene, id: copy });
        return { ...d, scenes };
      });
      setSelected(copy);
    },
    [apply],
  );

  const removeScene = useCallback(
    (id: string) => {
      const scenes = latest.current.scenes;
      if (scenes.length < 2) return;
      const at = scenes.findIndex((s) => s.id === id);
      const next = scenes[at + 1] ?? scenes[at - 1];
      apply("Remove a scene", (d) => ({ ...d, scenes: d.scenes.filter((s) => s.id !== id) }));
      if (next) setSelected(next.id);
    },
    [apply],
  );

  // a preview address runs out: ask again before the next load of the player
  useEffect(() => {
    if (live && live.expires_at - Date.now() / 1000 < RENEW_BEFORE_S) void renewLive();
  }, [live, renewLive]);

  // while a video is being made, follow it
  const renderId = render?.status === "working" ? render.id : null;
  useEffect(() => {
    if (!renderId) return;
    const poll = setInterval(() => {
      api
        .renderStatus(renderId)
        .then((r) => {
          if (alive.current) setRender(r);
        })
        .catch(() => {});
    }, POLL_MS);
    return () => clearInterval(poll);
  }, [api, renderId]);

  const make = useCallback(async () => {
    setProblem(null);
    try {
      if (timer.current) clearTimeout(timer.current);
      await saveNow();
      if (dirty.current) return; // the last change could not be saved: `problem` says why
      setRender(await api.render(project.id, "mp4"));
    } catch (e) {
      setProblem(say(e, "The video could not be started."));
    }
  }, [api, project.id, saveNow]);

  const cancel = useCallback(async () => {
    if (!render) return;
    try {
      setRender(await api.cancel(render.id));
    } catch (e) {
      setProblem(say(e, "The video could not be stopped."));
    }
  }, [api, render]);

  return {
    document,
    selected,
    select: setSelected,
    saveState,
    problem,
    revision,
    live,
    render,
    clearRender: () => setRender(null),
    canUndo: past.length > 0 || canUndoSaved,
    undoLabel: past[past.length - 1]?.label ?? null,
    canRedo: future.length > 0,
    apply,
    endGroup,
    undo,
    redo,
    adopt,
    undoOfTool,
    changeScene,
    moveScene,
    addScene,
    duplicateScene,
    removeScene,
    make,
    cancel,
    saveNow,
  };
}
