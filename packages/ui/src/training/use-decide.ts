"use client";

import type {
  DecisionExample,
  DecisionPatch,
  DecisionPlan,
  DecisionSet,
  DecisionStatus,
  TrainRun,
  TrainedModel,
  TrainingApi,
} from "@wasifyai/client";
import { useCallback, useEffect, useRef, useState } from "react";

export type DecideState = {
  loading: boolean;
  error: string | null;
  status: DecisionStatus | null;
  sets: DecisionSet[];
  /** the set being made */
  current: DecisionSet | null;
  rows: DecisionExample[];
  plan: DecisionPlan | null;
  /** the examples are being saved / were saved */
  saving: boolean;
  saved: boolean;
  /** the run being followed, and the model it left */
  run: TrainRun | null;
  result: TrainedModel | null;
  busy: boolean;
};

const START: DecideState = {
  loading: true,
  error: null,
  status: null,
  sets: [],
  current: null,
  rows: [],
  plan: null,
  saving: false,
  saved: false,
  run: null,
  result: null,
  busy: false,
};

const words = (e: unknown, fallback: string) =>
  e instanceof Error && e.message ? e.message : fallback;

/** How long a typed change waits before it is saved (a pause in typing, not every key). */
const SAVE_AFTER_MS = 700;

/**
 * The state of the "Teach it to decide" screen (ADR-0075): the sets of examples, the one being made
 * (saved as it is typed), the run being followed and the model it leaves. A set lives on the engine; this keeps what
 * the screen shows and reads the run again while it goes.
 */
export function useDecide(api: TrainingApi, pollMs = 1500) {
  const [state, setState] = useState<DecideState>(START);
  const alive = useRef(true);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pending = useRef<{ id: string; rows: DecisionExample[] } | null>(null);

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      if (timer.current) clearTimeout(timer.current);
    };
  }, []);

  const set = useCallback((change: Partial<DecideState>) => {
    if (alive.current) setState((s) => ({ ...s, ...change }));
  }, []);

  const fail = useCallback(
    (e: unknown, fallback: string) =>
      set({ error: words(e, fallback), busy: false, saving: false }),
    [set],
  );

  const refresh = useCallback(async () => {
    try {
      const [status, sets] = await Promise.all([api.decisionStatus(), api.decisionSets()]);
      set({ loading: false, error: null, status, sets });
      if (status.active_run) {
        const run = await api.run(status.active_run);
        set({ run });
      }
    } catch (e) {
      fail(e, "Teaching it to decide could not be reached.");
      set({ loading: false });
    }
  }, [api, set, fail]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const take = useCallback(
    (s: DecisionSet) =>
      set({ current: s, rows: s.rows ?? [], plan: s.plan ?? null, saved: true, saving: false }),
    [set],
  );

  /** Send what was typed now, if there is something waiting. */
  const flush = useCallback(async () => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = null;
    const todo = pending.current;
    pending.current = null;
    if (!todo) return;
    try {
      set({ saving: true });
      const s = await api.setDecisionExamples(todo.id, todo.rows);
      // what was typed meanwhile stays: only the plan is taken from the answer
      set({ plan: s.plan ?? null, saving: false, saved: true });
    } catch (e) {
      fail(e, "The examples could not be saved.");
    }
  }, [api, set, fail]);

  const openSet = useCallback(
    async (id: string) => {
      try {
        set({ busy: true, run: null, result: null, error: null });
        take(await api.decisionSet(id));
        set({ busy: false });
      } catch (e) {
        fail(e, "That set could not be opened.");
      }
    },
    [api, set, take, fail],
  );

  const newSet = useCallback(async () => {
    try {
      set({ busy: true, run: null, result: null, error: null });
      take(await api.createDecisionSet(""));
      set({ busy: false });
    } catch (e) {
      fail(e, "A new set could not be made.");
    }
  }, [api, set, take, fail]);

  const removeSet = useCallback(
    async (id: string) => {
      try {
        await api.removeDecisionSet(id);
        await refresh();
      } catch (e) {
        fail(e, "The set could not be removed.");
      }
    },
    [api, refresh, fail],
  );

  const setRows = useCallback(
    (rows: DecisionExample[]) => {
      const id = state.current?.id;
      if (!id) return;
      set({ rows, saved: false });
      pending.current = { id, rows };
      if (timer.current) clearTimeout(timer.current);
      timer.current = setTimeout(() => void flush(), SAVE_AFTER_MS);
    },
    [state.current?.id, set, flush],
  );

  const patch = useCallback(
    async (change: DecisionPatch) => {
      const id = state.current?.id;
      if (!id) return;
      try {
        await flush();
        const s = await api.updateDecisionSet(id, change);
        set({ current: { ...s, rows: undefined }, plan: s.plan ?? null, error: null });
      } catch (e) {
        fail(e, "That could not be changed.");
      }
    },
    [api, state.current?.id, flush, set, fail],
  );

  /** Read the plan of the set again (a model arrived, so what was missing may not be any more). */
  const replan = useCallback(async () => {
    const id = state.current?.id;
    if (!id) return;
    try {
      const s = await api.decisionSet(id);
      set({ plan: s.plan ?? null, current: { ...s, rows: undefined } });
      const status = await api.decisionStatus();
      set({ status });
    } catch {
      /* the next change reads it again */
    }
  }, [api, state.current?.id, set]);

  const teach = useCallback(async () => {
    const id = state.current?.id;
    if (!id) return;
    try {
      set({ busy: true, error: null });
      await flush();
      const run = await api.startDecisionRun(id);
      set({ run, busy: false, result: null });
    } catch (e) {
      fail(e, "The teaching could not be started.");
    }
  }, [api, state.current?.id, flush, set, fail]);

  const stop = useCallback(async () => {
    const id = state.run?.id;
    if (!id) return;
    try {
      await api.cancelRun(id);
      set({ run: await api.run(id) });
    } catch (e) {
      fail(e, "It could not be stopped.");
    }
  }, [api, state.run?.id, set, fail]);

  /** Follow the run until it is over, then fetch the model it left. */
  const runId = state.run?.id;
  const working = state.run?.status === "working";
  useEffect(() => {
    if (!runId || !working) return;
    const tick = setInterval(() => {
      void (async () => {
        try {
          const run = await api.run(runId);
          if (!alive.current) return;
          if (run.status === "done" && run.model_id) {
            const result = await api.model(run.model_id);
            set({ run, result });
          } else {
            set({ run });
          }
        } catch (e) {
          fail(e, "The run could not be followed.");
        }
      })();
    }, pollMs);
    return () => clearInterval(tick);
  }, [api, runId, working, pollMs, set, fail]);

  const leave = useCallback(async () => {
    await flush();
    set({ current: null, rows: [], plan: null, run: null, result: null, error: null });
    await refresh();
  }, [flush, set, refresh]);

  return {
    state,
    refresh,
    openSet,
    newSet,
    removeSet,
    setRows,
    patch,
    replan,
    teach,
    stop,
    leave,
    flush,
  };
}

export type DecideHook = ReturnType<typeof useDecide>;
