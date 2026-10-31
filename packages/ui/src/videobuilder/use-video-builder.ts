"use client";
// What the Motion graphics screen keeps track of: the component (is it set up, how far has it got), the
// projects, the one being edited, its preview and the render that is running.
import type {
  BuilderCheck,
  BuilderComponent,
  BuilderDraft,
  BuilderFormat,
  BuilderProject,
  BuilderRender,
  BuilderShape,
  BuilderSlots,
  BuilderStatus,
  DraftRequest,
  TemplateCatalogue,
  TemplateInfo,
  VideoBuilderApi,
} from "@wasifyai/client";
import { useCallback, useEffect, useRef, useState } from "react";

const POLL_MS = 700;

export const NEW = "new";

export type Still = { at: number; url: string };

export type BuilderState = {
  component: BuilderComponent | null;
  status: BuilderStatus | null;
  catalogue: TemplateCatalogue | null;
  /** the template a new draft is made with */
  draft: string;
  /** what a description was understood as, until the person starts something else */
  drafted: BuilderDraft | null;
  /** a description is being read by the language model */
  drafting: boolean;
  projects: BuilderProject[];
  /** the project open, `new` for a draft, or null */
  selected: string | null;
  project: BuilderProject | null;
  render: BuilderRender | null;
  /** stills of the saved words, at the moments the engine named */
  stills: Still[];
  /** the last check of the words alone (a render's own check is on the render) */
  check: BuilderCheck | null;
  loading: boolean;
  error: string | null;
  /** what the person asked the assistant for, on the first screen: sent when the editor opens */
  brief: string | null;
  /** the person chose one graphic on the first screen, not a video of scenes */
  oneGraphic: boolean;
};

/** The template of the open project, or of the draft. */
export function templateOf(state: BuilderState): TemplateInfo | null {
  const id = state.project?.template ?? state.draft;
  return state.catalogue?.templates.find((t) => t.id === id) ?? null;
}

const revoke = (stills: Still[]) => {
  for (const s of stills) URL.revokeObjectURL(s.url);
};

const say = (e: unknown, fallback: string) =>
  e instanceof Error && e.message ? e.message : fallback;

export function useVideoBuilder(api: VideoBuilderApi) {
  const [state, setState] = useState<BuilderState>({
    component: null,
    status: null,
    catalogue: null,
    draft: "title",
    drafted: null,
    drafting: false,
    projects: [],
    selected: null,
    project: null,
    render: null,
    stills: [],
    check: null,
    loading: true,
    error: null,
    brief: null,
    oneGraphic: false,
  });
  const patch = useCallback((p: Partial<BuilderState>) => setState((s) => ({ ...s, ...p })), []);
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  const refresh = useCallback(async () => {
    try {
      const component = await api.component();
      if (!alive.current) return;
      if (!component.installed) {
        patch({ component, loading: false, error: null });
        return;
      }
      const [status, templates, projects] = await Promise.all([
        api.status(),
        api.templates(),
        api.list(),
      ]);
      if (!alive.current) return;
      patch({
        component,
        status,
        catalogue: templates,
        projects,
        loading: false,
        error: null,
      });
    } catch (e) {
      if (alive.current)
        patch({ loading: false, error: say(e, "Motion graphics could not be reached.") });
    }
  }, [api, patch]);

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
    }, POLL_MS);
    return () => clearInterval(timer);
  }, [installing, api, patch, refresh]);

  // while a render works, follow it
  const working = state.render?.status === "working";
  const renderId = state.render?.id;
  useEffect(() => {
    if (!working || !renderId) return;
    const timer = setInterval(() => {
      api
        .renderStatus(renderId)
        .then(async (render) => {
          if (!alive.current) return;
          patch({ render });
          if (render.status !== "working") {
            const [status, projects] = await Promise.all([api.status(), api.list()]);
            if (alive.current) patch({ status, projects });
          }
        })
        .catch(() => {});
    }, POLL_MS);
    return () => clearInterval(timer);
  }, [working, renderId, api, patch]);

  const install = useCallback(
    async (bytes: number) => {
      try {
        patch({ component: await api.install(bytes), error: null });
      } catch (e) {
        patch({ error: say(e, "Motion graphics could not be set up.") });
      }
    },
    [api, patch],
  );

  const open = useCallback(
    async (id: string | null, template?: string) => {
      revoke(state.stills);
      const clear = { stills: [], check: null, error: null, drafted: null };
      if (id === null || id === NEW) {
        patch({
          selected: id,
          project: null,
          render: null,
          draft: template ?? state.draft,
          ...clear,
        });
        return;
      }
      try {
        const project = await api.get(id);
        patch({ selected: id, project, render: project.renders[0] ?? null, ...clear });
      } catch (e) {
        patch({ error: say(e, "That project could not be opened.") });
      }
    },
    [api, patch, state.stills, state.draft],
  );

  /** Read a description (and a CSV file) with the language model and open the form filled in. */
  const draftFrom = useCallback(
    async (request: DraftRequest) => {
      patch({ drafting: true, error: null });
      try {
        const drafted = await api.draft(request);
        revoke(state.stills);
        patch({
          drafting: false,
          drafted,
          draft: drafted.template,
          selected: NEW,
          project: null,
          render: null,
          stills: [],
          check: null,
        });
      } catch (e) {
        patch({ drafting: false, error: say(e, "That could not be read. Try the form instead.") });
      }
    },
    [api, patch, state.stills],
  );

  const chooseTemplate = useCallback(
    (template: string) => {
      revoke(state.stills);
      patch({ draft: template, stills: [], check: null, error: null });
    },
    [patch, state.stills],
  );

  const save = useCallback(
    async (slots: BuilderSlots): Promise<BuilderProject | null> => {
      try {
        const saved =
          state.selected && state.selected !== NEW
            ? await api.update(state.selected, slots)
            : await api.create(state.draft, slots);
        const projects = await api.list();
        revoke(state.stills);
        patch({
          project: saved,
          selected: saved.id,
          projects,
          stills: [],
          check: null,
          drafted: null,
          error: null,
        });
        return saved;
      } catch (e) {
        patch({ error: say(e, "The project could not be saved.") });
        return null;
      }
    },
    [api, patch, state.selected, state.draft, state.stills],
  );

  const undo = useCallback(async () => {
    if (!state.project) return;
    try {
      const back = await api.undo(state.project.id);
      const projects = await api.list();
      revoke(state.stills);
      patch({ project: back, projects, stills: [], check: null, error: null });
    } catch (e) {
      patch({ error: say(e, "There is nothing to undo.") });
    }
  }, [api, patch, state.project, state.stills]);

  /** Stills of the saved words, one for each of the moments the engine named. */
  const showStills = useCallback(
    async (project: BuilderProject) => {
      try {
        const stills: Still[] = [];
        for (const at of project.preview_times) {
          stills.push({ at, url: await api.preview(project.id, at) });
        }
        revoke(state.stills);
        patch({ stills, error: null });
      } catch (e) {
        patch({ error: say(e, "No preview could be made.") });
      }
    },
    [api, patch, state.stills],
  );

  const checkWords = useCallback(
    async (id: string) => {
      try {
        patch({ check: await api.check(id), error: null });
      } catch (e) {
        patch({ error: say(e, "The words could not be checked.") });
      }
    },
    [api, patch],
  );

  const make = useCallback(
    async (id: string, format?: BuilderFormat) => {
      try {
        patch({ render: await api.render(id, format), check: null, error: null });
        patch({ status: await api.status() });
      } catch (e) {
        patch({ error: say(e, "The video could not be started.") });
      }
    },
    [api, patch],
  );

  const cancel = useCallback(async () => {
    if (!state.render) return;
    try {
      patch({ render: await api.cancel(state.render.id), error: null });
      patch({ status: await api.status() });
    } catch (e) {
      patch({ error: say(e, "The video could not be stopped.") });
    }
  }, [api, patch, state.render]);

  /** A new project of scenes (ADR-0096), opened in the editor. */
  const startScenes = useCallback(
    async (shape?: BuilderShape, brief?: string) => {
      try {
        const made = await api.create("scenes", {
          ...(shape ? { shape } : {}),
          scenes: [
            {
              kind: "title",
              transition: "fade",
              fields: { title: "Your first scene", seconds: 5 },
            },
          ],
        });
        patch({
          selected: made.id,
          project: made,
          render: null,
          stills: [],
          check: null,
          error: null,
          brief: brief ?? null,
        });
      } catch (e) {
        patch({ error: say(e, "The project could not be started.") });
      }
    },
    [api, patch],
  );

  /** A project made from one template becomes a project of scenes; Undo in the editor turns it back. */
  const toScenes = useCallback(
    async (id: string) => {
      try {
        const made = await api.update(id, {}, "scenes");
        patch({
          selected: made.id,
          project: made,
          render: null,
          stills: [],
          check: null,
          error: null,
        });
      } catch (e) {
        patch({ error: say(e, "The project could not be changed.") });
      }
    },
    [api, patch],
  );

  /** Back from the editor to the list, which has its changes. */
  const leaveEditor = useCallback(async () => {
    patch({ selected: null, project: null, render: null, brief: null });
    await refresh();
  }, [patch, refresh]);

  const remove = useCallback(
    async (id: string) => {
      try {
        await api.remove(id);
        const projects = await api.list();
        patch({
          projects,
          selected: null,
          project: null,
          render: null,
          stills: [],
          check: null,
          error: null,
        });
      } catch (e) {
        patch({ error: say(e, "The project could not be deleted.") });
      }
    },
    [api, patch],
  );

  return {
    state,
    startScenes,
    openOneGraphic: (template: string) => {
      patch({ oneGraphic: true, selected: NEW, project: null, render: null, draft: template });
    },
    toScenes,
    leaveEditor,
    install,
    open,
    draftFrom,
    chooseTemplate,
    save,
    undo,
    showStills,
    checkWords,
    make,
    cancel,
    remove,
    refresh,
  };
}
