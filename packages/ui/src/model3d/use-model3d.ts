"use client";
// What the 3D screen keeps track of: the component (is it set up, how far has it got), the picture
// being prepared and its checks, the model being made or shown, and the models already made.
import type {
  Detail,
  Model3d,
  Model3dApi,
  Model3dComponent,
  Model3dStatus,
  PictureInput,
} from "@wasifyai/client";
import { useCallback, useEffect, useRef, useState } from "react";

const POLL_PICTURE_MS = 1000;
const POLL_MODEL_MS = 2000;
const POLL_SETUP_MS = 700;

export type Shown = {
  /** the cut-out and the picture, as object URLs */
  picture: string | null;
  cutout: string | null;
};

export type Model3dState = {
  component: Model3dComponent | null;
  status: Model3dStatus | null;
  models: Model3d[];
  /** thumbnails of the models, by id (object URLs) */
  thumbs: Record<string, string>;
  input: PictureInput | null;
  shown: Shown;
  model: Model3d | null;
  /** the GLB of the finished model shown, as an object URL */
  glb: string | null;
  loading: boolean;
  busyWith: string | null;
  error: string | null;
};

const say = (e: unknown, fallback: string) =>
  e instanceof Error && e.message ? e.message : fallback;

const revoke = (...urls: (string | null | undefined)[]) => {
  for (const u of urls) if (u) URL.revokeObjectURL(u);
};

export function useModel3d(api: Model3dApi) {
  const [state, setState] = useState<Model3dState>({
    component: null,
    status: null,
    models: [],
    thumbs: {},
    input: null,
    shown: { picture: null, cutout: null },
    model: null,
    glb: null,
    loading: true,
    busyWith: null,
    error: null,
  });
  const patch = useCallback((p: Partial<Model3dState>) => setState((s) => ({ ...s, ...p })), []);
  const alive = useRef(true);
  const latest = useRef(state);
  latest.current = state;
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      const s = latest.current;
      revoke(s.glb, s.shown.picture, s.shown.cutout, ...Object.values(s.thumbs));
    };
  }, []);

  const loadThumbs = useCallback(
    async (models: Model3d[]) => {
      const have = latest.current.thumbs;
      const next: Record<string, string> = { ...have };
      for (const m of models) {
        if (m.status !== "done" || next[m.id]) continue;
        try {
          next[m.id] = await api.fileUrl(m.id, "thumb");
        } catch {
          // a card without a picture is fine
        }
      }
      if (alive.current) patch({ thumbs: next });
    },
    [api, patch],
  );

  const refresh = useCallback(async () => {
    try {
      const component = await api.component();
      if (!alive.current) return;
      if (!component.installed) {
        patch({ component, loading: false, error: null });
        return;
      }
      const [status, models] = await Promise.all([api.status(), api.list()]);
      if (!alive.current) return;
      patch({ component, status, models, loading: false, error: null });
      void loadThumbs(models);
      // something is running: pick it up, as when the person left the screen and came back
      const active = status.active;
      if (active && !latest.current.model && !latest.current.input) {
        if (active.kind === "model") {
          const model = await api.get(active.id);
          if (alive.current) patch({ model });
        } else {
          const input = await api.picture(active.id);
          if (alive.current) patch({ input });
        }
      }
    } catch (e) {
      if (alive.current) patch({ loading: false, error: say(e, "3D could not be reached.") });
    }
  }, [api, patch, loadThumbs]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // while the component installs, follow it; when it is ready, load everything
  const installing = state.component?.progress.state === "installing";
  useEffect(() => {
    if (!installing) return;
    const timer = setInterval(() => {
      api
        .component()
        .then((component) => {
          if (!alive.current) return;
          patch({ component });
          if (component.progress.state !== "installing") void refresh();
        })
        .catch(() => {});
    }, POLL_SETUP_MS);
    return () => clearInterval(timer);
  }, [installing, api, patch, refresh]);

  // while a picture is being cut out, follow it, and show it and its cut-out when it is ready
  const checking = state.input?.status === "checking";
  const inputId = state.input?.id;
  useEffect(() => {
    if (!checking || !inputId) return;
    const timer = setInterval(() => {
      api
        .picture(inputId)
        .then((input) => {
          if (alive.current) patch({ input });
        })
        .catch(() => {});
    }, POLL_PICTURE_MS);
    return () => clearInterval(timer);
  }, [checking, inputId, api, patch]);

  const ready = state.input?.status === "ready";
  useEffect(() => {
    if (!inputId || !ready) return;
    let gone = false;
    Promise.all([api.pictureImage(inputId, "picture"), api.pictureImage(inputId, "cutout")])
      .then(([picture, cutout]) => {
        if (gone || !alive.current) return revoke(picture, cutout);
        revoke(latest.current.shown.picture, latest.current.shown.cutout);
        patch({ shown: { picture, cutout } });
      })
      .catch(() => {});
    return () => {
      gone = true;
    };
  }, [inputId, ready, api, patch]);

  // while a model is made, follow it; when it is done, load its file
  const working = state.model?.status === "working";
  const modelId = state.model?.id;
  useEffect(() => {
    if (!working || !modelId) return;
    const timer = setInterval(() => {
      api
        .get(modelId)
        .then(async (model) => {
          if (!alive.current) return;
          patch({ model });
          if (model.status !== "working") {
            const [status, models] = await Promise.all([api.status(), api.list()]);
            if (alive.current) patch({ status, models });
            void loadThumbs(models);
          }
        })
        .catch(() => {});
    }, POLL_MODEL_MS);
    return () => clearInterval(timer);
  }, [working, modelId, api, patch, loadThumbs]);

  const done = state.model?.status === "done";
  useEffect(() => {
    if (!modelId || !done) return;
    let gone = false;
    api
      .fileUrl(modelId, "file")
      .then((url) => {
        if (gone || !alive.current) return revoke(url);
        revoke(latest.current.glb);
        patch({ glb: url });
      })
      .catch(() => {
        if (!gone && alive.current) patch({ error: "The model could not be opened." });
      });
    return () => {
      gone = true;
    };
  }, [modelId, done, api, patch]);

  const install = useCallback(
    async (bytes: number) => {
      try {
        patch({ component: await api.install(bytes), error: null });
      } catch (e) {
        patch({ error: say(e, "3D could not be set up.") });
      }
    },
    [api, patch],
  );

  const cancelInstall = useCallback(async () => {
    try {
      patch({ component: await api.cancelInstall() });
    } catch (e) {
      patch({ error: say(e, "The download could not be stopped.") });
    }
  }, [api, patch]);

  const clearPicture = useCallback(() => {
    const s = latest.current;
    revoke(s.shown.picture, s.shown.cutout);
    patch({ input: null, shown: { picture: null, cutout: null } });
  }, [patch]);

  const addPicture = useCallback(
    async (picture: Blob, name = "") => {
      patch({ busyWith: "picture", error: null });
      try {
        clearPicture();
        const input = await api.addPicture(picture, name);
        patch({ input, busyWith: null, model: null, error: null });
      } catch (e) {
        patch({ busyWith: null, error: say(e, "That picture could not be used.") });
      }
    },
    [api, patch, clearPicture],
  );

  const discardPicture = useCallback(async () => {
    const id = latest.current.input?.id;
    clearPicture();
    if (id) await api.removePicture(id).catch(() => {});
  }, [api, clearPicture]);

  const make = useCallback(
    async (request: {
      title: string;
      prompt: string;
      detail: Detail;
      rights: boolean;
    }) => {
      const input = latest.current.input;
      if (!input) return;
      patch({ busyWith: "make", error: null });
      try {
        const model = await api.make({ input_id: input.id, ...request });
        patch({ model, busyWith: null, glb: null, status: await api.status() });
      } catch (e) {
        patch({ busyWith: null, error: say(e, "The model could not be started.") });
      }
    },
    [api, patch],
  );

  const cancel = useCallback(async () => {
    const id = latest.current.model?.id;
    if (!id) return;
    try {
      const { stopped: _stopped, ...model } = await api.cancel(id);
      const [status, models] = await Promise.all([api.status(), api.list()]);
      patch({ model: model as Model3d, status, models, error: null });
    } catch (e) {
      patch({ error: say(e, "The model could not be stopped.") });
    }
  }, [api, patch]);

  const open = useCallback(
    async (id: string) => {
      try {
        const model = await api.get(id);
        const s = latest.current;
        revoke(s.glb);
        patch({ model, glb: null, error: null });
      } catch (e) {
        patch({ error: say(e, "That model could not be opened.") });
      }
    },
    [api, patch],
  );

  const again = useCallback(async () => {
    const id = latest.current.model?.id;
    if (!id) return;
    patch({ busyWith: "make", error: null });
    try {
      const model = await api.again(id);
      revoke(latest.current.glb);
      patch({ model, glb: null, busyWith: null, status: await api.status() });
    } catch (e) {
      patch({ busyWith: null, error: say(e, "The model could not be started again.") });
    }
  }, [api, patch]);

  const rename = useCallback(
    async (title: string) => {
      const id = latest.current.model?.id;
      if (!id || !title.trim()) return;
      try {
        const model = await api.rename(id, title.trim());
        patch({ model, models: await api.list(), error: null });
      } catch (e) {
        patch({ error: say(e, "The model could not be renamed.") });
      }
    },
    [api, patch],
  );

  const remove = useCallback(
    async (id: string) => {
      try {
        await api.remove(id);
        const models = await api.list();
        const s = latest.current;
        revoke(s.glb, s.thumbs[id]);
        const { [id]: _gone, ...thumbs } = s.thumbs;
        patch({
          models,
          thumbs,
          model: s.model?.id === id ? null : s.model,
          glb: s.model?.id === id ? null : s.glb,
          status: await api.status(),
          error: null,
        });
      } catch (e) {
        patch({ error: say(e, "The model could not be deleted.") });
      }
    },
    [api, patch],
  );

  /** Back to the start: another model. */
  const startOver = useCallback(() => {
    const s = latest.current;
    revoke(s.glb, s.shown.picture, s.shown.cutout);
    patch({
      model: null,
      glb: null,
      input: null,
      shown: { picture: null, cutout: null },
      error: null,
    });
  }, [patch]);

  return {
    state,
    install,
    cancelInstall,
    addPicture,
    discardPicture,
    make,
    cancel,
    open,
    again,
    rename,
    remove,
    startOver,
    refresh,
  };
}
