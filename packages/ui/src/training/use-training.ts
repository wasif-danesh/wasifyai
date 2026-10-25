"use client";

import type {
  TrainDataset,
  TrainKind,
  TrainRun,
  TrainStatus,
  TrainedModel,
  TrainingApi,
} from "@wasifyai/client";
import { useCallback, useEffect, useRef, useState } from "react";

export type Busy = null | "picture" | "captions" | "run" | "dataset";

export type TrainState = {
  loading: boolean;
  error: string | null;
  status: TrainStatus | null;
  datasets: TrainDataset[];
  models: TrainedModel[];
  /** the set being made, with its pictures and suggestions */
  current: TrainDataset | null;
  /** the run being followed */
  run: TrainRun | null;
  /** runs paused with a checkpoint kept: they can be picked up where they stopped */
  paused: TrainRun[];
  busy: Busy;
  /** object URLs of the pictures and samples, by key */
  urls: Record<string, string>;
};

const START: TrainState = {
  loading: true,
  error: null,
  status: null,
  datasets: [],
  models: [],
  current: null,
  run: null,
  paused: [],
  busy: null,
  urls: {},
};

const words = (e: unknown, fallback: string) =>
  e instanceof Error && e.message ? e.message : fallback;

/**
 * The state of the Train screen: the sets of pictures, the run being followed and the trained models. A set
 * lives on the engine (a reload finds it again); this keeps what the screen shows, reads again while the
 * descriptions are being written or a run is going, and turns pictures into object URLs once.
 */
export function useTraining(api: TrainingApi, pollMs = 1500) {
  const [state, setState] = useState<TrainState>(START);
  const alive = useRef(true);
  const asked = useRef(new Set<string>());

  useEffect(() => {
    alive.current = true;
    const keep = asked.current;
    return () => {
      alive.current = false;
      keep.clear();
    };
  }, []);

  const set = useCallback((change: Partial<TrainState>) => {
    if (alive.current) setState((s) => ({ ...s, ...change }));
  }, []);

  const fail = useCallback(
    (e: unknown, fallback: string) => set({ error: words(e, fallback), busy: null }),
    [set],
  );

  /** Fetch a picture once and keep its object URL under `key`. */
  const url = useCallback((key: string, load: () => Promise<string>) => {
    if (asked.current.has(key)) return;
    asked.current.add(key);
    load()
      .then((u) => {
        if (alive.current) setState((s) => ({ ...s, urls: { ...s.urls, [key]: u } }));
      })
      .catch(() => asked.current.delete(key));
  }, []);

  const loadThumbs = useCallback(
    (d: TrainDataset) => {
      for (const i of d.items ?? []) {
        url(`item:${i.id}`, () => api.pictureUrl(d.id, i.id, "thumb"));
      }
    },
    [api, url],
  );

  const loadSamples = useCallback(
    (r: TrainRun) => {
      for (const name of r.samples) url(`sample:${r.id}/${name}`, () => api.sampleUrl(r.id, name));
    },
    [api, url],
  );

  const refresh = useCallback(async () => {
    try {
      const [status, datasets, models, runs] = await Promise.all([
        api.status(),
        api.datasets(),
        api.models(),
        api.runs().catch(() => [] as TrainRun[]),
      ]);
      set({
        loading: false,
        error: null,
        status,
        datasets,
        models,
        paused: runs.filter((r) => r.status === "paused"),
      });
      if (status.active_run) {
        const run = await api.run(status.active_run);
        set({ run });
        loadSamples(run);
      }
    } catch (e) {
      set({ loading: false, error: words(e, "Training could not be reached."), busy: null });
    }
  }, [api, set, loadSamples]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // ---- the set being made ---------------------------------------------------------------------

  const reread = useCallback(
    async (id: string) => {
      const d = await api.dataset(id);
      set({ current: d });
      loadThumbs(d);
      return d;
    },
    [api, set, loadThumbs],
  );

  const openDataset = useCallback(
    async (id: string) => {
      try {
        set({ busy: "dataset", run: null });
        await reread(id);
        set({ busy: null, error: null });
      } catch (e) {
        fail(e, "That set could not be opened.");
      }
    },
    [reread, set, fail],
  );

  const newDataset = useCallback(
    async (kind: TrainKind = "character") => {
      try {
        set({ busy: "dataset", run: null });
        const d = await api.createDataset(kind);
        set({ current: d, busy: null, error: null });
        return d;
      } catch (e) {
        fail(e, "A new set could not be made.");
        return null;
      }
    },
    [api, set, fail],
  );

  const change = useCallback(
    async (patch: Parameters<TrainingApi["updateDataset"]>[1]) => {
      const id = state.current?.id;
      if (!id) return;
      // shown at once: the choice sticks while the engine confirms it
      if (alive.current) {
        setState((s) => (s.current ? { ...s, current: { ...s.current, ...patch } } : s));
      }
      try {
        await api.updateDataset(id, patch);
        await reread(id);
        set({ error: null });
      } catch (e) {
        fail(e, "That could not be changed.");
      }
    },
    [api, state.current?.id, reread, set, fail],
  );

  const addPictures = useCallback(
    async (files: File[]) => {
      const id = state.current?.id;
      if (!id) return;
      set({ busy: "picture", error: null });
      const problems: string[] = [];
      for (const file of files) {
        try {
          await api.addPicture(id, file, file.name);
        } catch (e) {
          problems.push(`${file.name}: ${words(e, "it could not be added")}`);
        }
        await reread(id).catch(() => undefined);
      }
      set({ busy: null, error: problems.length ? problems.join(" ") : null });
    },
    [api, state.current?.id, reread, set],
  );

  const removePicture = useCallback(
    async (pictureId: string) => {
      const id = state.current?.id;
      if (!id) return;
      try {
        await api.removePicture(id, pictureId);
        await reread(id);
      } catch (e) {
        fail(e, "That picture could not be removed.");
      }
    },
    [api, state.current?.id, reread, fail],
  );

  const removeWithProblems = useCallback(async () => {
    const d = state.current;
    if (!d) return;
    try {
      for (const i of d.items ?? []) if (i.suggest_remove) await api.removePicture(d.id, i.id);
      await reread(d.id);
    } catch (e) {
      fail(e, "The pictures could not be removed.");
    }
  }, [api, state.current, reread, fail]);

  const writeCaptions = useCallback(
    async (options?: { again?: boolean; pictureIds?: string[] }) => {
      const id = state.current?.id;
      if (!id) return;
      try {
        set({ busy: "captions", error: null });
        await api.writeCaptions(id, options);
        await reread(id);
        set({ busy: null });
      } catch (e) {
        fail(e, "The descriptions could not be written.");
        await reread(id).catch(() => undefined);
      }
    },
    [api, state.current?.id, reread, set, fail],
  );

  const editCaption = useCallback(
    async (pictureId: string, caption: string) => {
      const id = state.current?.id;
      if (!id) return;
      try {
        await api.editCaption(id, pictureId, caption);
        await reread(id);
      } catch (e) {
        fail(e, "That description could not be saved.");
      }
    },
    [api, state.current?.id, reread, fail],
  );

  const removeDataset = useCallback(
    async (id: string) => {
      try {
        await api.removeDataset(id);
        set({ current: state.current?.id === id ? null : state.current });
        await refresh();
      } catch (e) {
        fail(e, "That set could not be removed.");
      }
    },
    [api, state.current, set, refresh, fail],
  );

  // ---- the run --------------------------------------------------------------------------------

  const teach = useCallback(async () => {
    const id = state.current?.id;
    if (!id) return;
    try {
      set({ busy: "run", error: null });
      const run = await api.startRun(id);
      set({ run, busy: null });
    } catch (e) {
      fail(e, "The teaching could not be started.");
    }
  }, [api, state.current?.id, set, fail]);

  const stop = useCallback(async () => {
    const id = state.run?.id;
    if (!id) return;
    try {
      await api.cancelRun(id);
      const run = await api.run(id);
      set({ run });
    } catch (e) {
      fail(e, "It could not be stopped.");
    }
  }, [api, state.run?.id, set, fail]);

  const pause = useCallback(async () => {
    const id = state.run?.id;
    if (!id) return;
    try {
      await api.pauseRun(id);
      const run = await api.run(id);
      set({ run });
      await refresh();
    } catch (e) {
      fail(e, "It could not be paused.");
    }
  }, [api, state.run?.id, set, fail, refresh]);

  const resume = useCallback(
    async (id: string) => {
      try {
        set({ error: null });
        const run = await api.resumeRun(id);
        set({ run });
        loadSamples(run);
        await refresh();
      } catch (e) {
        fail(e, "It could not be picked up again.");
      }
    },
    [api, set, fail, loadSamples, refresh],
  );

  const discard = useCallback(
    async (id: string) => {
      try {
        await api.cancelRun(id);
        set({ run: null });
        await refresh();
      } catch (e) {
        fail(e, "It could not be discarded.");
      }
    },
    [api, set, fail, refresh],
  );

  const leave = useCallback(async () => {
    set({ current: null, run: null, error: null });
    await refresh();
  }, [set, refresh]);

  // ---- models ---------------------------------------------------------------------------------

  const renameModel = useCallback(
    async (id: string, name: string) => {
      try {
        await api.renameModel(id, name);
        await refresh();
      } catch (e) {
        fail(e, "That could not be renamed.");
      }
    },
    [api, refresh, fail],
  );

  const removeModel = useCallback(
    async (id: string) => {
      try {
        await api.removeModel(id);
        await refresh();
      } catch (e) {
        fail(e, "That model could not be removed.");
      }
    },
    [api, refresh, fail],
  );

  // ---- reading again while something is going ---------------------------------------------------

  const writing = state.current?.writing === true;
  const going = state.run?.status === "working";
  const currentId = state.current?.id;
  const runId = state.run?.id;
  useEffect(() => {
    if (!writing && !going) return;
    const timer = setInterval(async () => {
      try {
        if (writing && currentId) await reread(currentId);
        if (going && runId) {
          const run = await api.run(runId);
          set({ run });
          loadSamples(run);
          if (run.status !== "working") await refresh();
        }
      } catch (e) {
        set({ error: words(e, "Training could not be reached.") });
      }
    }, pollMs);
    return () => clearInterval(timer);
  }, [writing, going, currentId, runId, api, reread, set, loadSamples, refresh, pollMs]);

  return {
    state,
    refresh,
    openDataset,
    newDataset,
    change,
    addPictures,
    removePicture,
    removeWithProblems,
    writeCaptions,
    editCaption,
    removeDataset,
    teach,
    stop,
    pause,
    resume,
    discard,
    leave,
    renameModel,
    removeModel,
    loadSamples,
    openRun: async (id: string) => {
      const run = await api.run(id);
      set({ run });
      loadSamples(run);
    },
  };
}
