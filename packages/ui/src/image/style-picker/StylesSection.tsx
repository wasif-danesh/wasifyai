"use client";

import type { FoundStyle, Look, Style, StyleChoice, StylesApi, StylesList } from "@wasifyai/client";
import { Check, ChevronDown, CircleHelp, Ellipsis, Plus, TriangleAlert, X } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { Button } from "../../components/button";
import { ConfirmDialog, NameDialog } from "../../components/dialog";
import { Menu, type MenuItem } from "../../components/menu";
import { Slider } from "../../components/slider";
import { formatBytes } from "../../notebook/format";
import { HubStyleDialog } from "./HubStyleDialog";
import { ImportStyleDialog } from "./ImportStyleDialog";
import { fitLine } from "./fit";

const TOO_MANY = 3; // S0: more than this and they blend and weaken each other

const KIND_TAG: Record<Style["source"]["kind"], string> = {
  trained: "Made by you",
  file: "From this computer",
  found: "From another app",
  hub: "From Hugging Face",
};

function FitIcon({ fit }: { fit: Style["fit"] }) {
  const Icon = fit === "fits" ? Check : fit === "other" ? X : CircleHelp;
  return <Icon className="size-4 shrink-0" aria-hidden="true" />;
}

/**
 * Styles (LoRAs) in the image screens, always in view (ADR-0091): the chosen ones as rows with their
 * strength, what they were made for and their word; an Add menu with yours first, the ones kept here,
 * the ones another app keeps (copied in when chosen) and a file from this computer.
 */
/** What a saved look keeps besides its styles: the screen's size and steps. */
export type LookSettings = Pick<Look, "size" | "width" | "height" | "steps">;

export function StylesSection({
  api,
  chosen,
  onChange,
  onUseWord,
  onOpenFolders,
  disabled = false,
  settings,
  onApplyLook,
  readOnly = false,
}: {
  api: StylesApi;
  chosen: StyleChoice[];
  onChange: (next: StyleChoice[]) => void;
  /** "Use this word": the screen adds it to the prompt */
  onUseWord: (word: string) => void;
  /** "Look in a folder…": where the folders another app keeps models in are set */
  onOpenFolders?: () => void;
  disabled?: boolean;
  /** Saved looks (ADR-0091 decision 11): the screen's size and steps now, and how to apply a look's */
  settings?: LookSettings;
  onApplyLook?: (settings: LookSettings) => void;
  /** the web (S5): the styles an admin added; a person chooses, nothing is added or deleted here */
  readOnly?: boolean;
}) {
  const [list, setList] = useState<StylesList | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [importing, setImporting] = useState(false);
  const [fromHub, setFromHub] = useState(false);
  const [deleting, setDeleting] = useState<Style | null>(null);
  const [busy, setBusy] = useState(false);
  const [hubRepo, setHubRepo] = useState<string | undefined>(undefined);
  const [pinned, setPinned] = useState<{ file: string; sha256: string } | undefined>(undefined);
  const [looks, setLooks] = useState<Look[]>([]);
  const [naming, setNaming] = useState(false);
  const [unlooking, setUnlooking] = useState<Look | null>(null);

  const reload = useCallback(async () => {
    try {
      setList(await api.list());
    } catch (e) {
      setProblem(e instanceof Error ? e.message : "The styles could not be read.");
    }
    if (onApplyLook) {
      try {
        setLooks(await api.looks());
      } catch {
        setLooks([]); // the looks are a convenience: the styles work without them
      }
    }
  }, [api, onApplyLook]);

  useEffect(() => {
    void reload();
  }, [reload]);

  // a style of a recipe or a look that came back under another id (got again) is the same file: same checksum
  useEffect(() => {
    if (!list) return;
    const ids = new Set(list.styles.map((s) => s.id));
    let moved = false;
    const next = chosen.map((c) => {
      if (ids.has(c.id) || !c.sha256) return c;
      const same = list.styles.find((s) => s.sha256 === c.sha256);
      if (!same) return c;
      moved = true;
      return { ...c, id: same.id };
    });
    if (moved) onChange(next);
  }, [list, chosen, onChange]);

  const max = list?.max ?? 8;
  const byId = new Map((list?.styles ?? []).map((s) => [s.id, s]));
  const full = chosen.length >= max;

  function add(style: Style) {
    if (!style.selectable || chosen.some((c) => c.id === style.id) || full) return;
    onChange([...chosen, { id: style.id, strength: 1 }]);
  }

  async function addFound(f: FoundStyle) {
    setBusy(true);
    setProblem(null);
    try {
      const style = await api.fromFound(f.id);
      await reload();
      add(style);
    } catch (e) {
      setProblem(e instanceof Error ? e.message : "That style could not be copied.");
    } finally {
      setBusy(false);
    }
  }

  async function remove(style: Style) {
    setDeleting(null);
    setProblem(null);
    try {
      await api.remove(style.id);
      onChange(chosen.filter((c) => c.id !== style.id));
      await reload();
    } catch (e) {
      setProblem(e instanceof Error ? e.message : "That style could not be deleted.");
    }
  }

  const unchosen = (list?.styles ?? []).filter((s) => !chosen.some((c) => c.id === s.id));
  const items: MenuItem[] = [
    ...unchosen.map((s) => ({
      label: s.source.kind === "trained" ? `${s.title} (yours)` : s.title,
      onSelect: () => add(s),
      disabled: !s.selectable || full,
    })),
    ...(list?.found ?? []).map((f) => ({
      label: `${f.title} (${f.tool})`,
      onSelect: () => void addFound(f),
      disabled: full,
    })),
    ...(readOnly ? [] : (list?.recommended ?? [])).map((r) => ({
      label: `${r.title} (recommended, ${formatBytes(r.size)})`,
      onSelect: () => {
        setPinned({ file: r.file, sha256: r.sha256 });
        setHubRepo(r.repo);
      },
      disabled: full,
    })),
    ...(readOnly
      ? []
      : [
          { label: "From this computer…", onSelect: () => setImporting(true) },
          {
            label: "From Hugging Face…",
            onSelect: () => {
              setHubRepo(undefined);
              setPinned(undefined);
              setFromHub(true);
            },
          },
          ...(onOpenFolders ? [{ label: "Look in a folder…", onSelect: onOpenFolders }] : []),
        ]),
  ];

  return (
    <section className="grid gap-2" aria-label="Styles">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="m-0 font-semibold text-ui-lg">
          Styles{" "}
          <span className="font-normal text-muted-foreground">
            {chosen.length ? `(${chosen.length} chosen · up to ${max})` : "(optional)"}
          </span>
        </h2>
        <span className="flex-1" />
        {onApplyLook && settings && !readOnly ? (
          <Menu
            align="end"
            items={[
              ...looks.map((l) => ({
                label: l.name,
                onSelect: () => {
                  onApplyLook({ size: l.size, width: l.width, height: l.height, steps: l.steps });
                  onChange(l.styles.slice(0, max));
                },
              })),
              { label: "Save this look…", onSelect: () => setNaming(true) },
              ...looks.map((l) => ({
                label: `Delete “${l.name}”…`,
                destructive: true,
                onSelect: () => setUnlooking(l),
              })),
            ]}
            trigger={
              <Button type="button" size="sm" variant="ghost" disabled={disabled}>
                Saved looks <ChevronDown className="size-4" aria-hidden="true" />
              </Button>
            }
          />
        ) : null}
        <Menu
          align="end"
          items={items}
          trigger={
            <Button type="button" size="sm" variant="outline" disabled={disabled || busy}>
              <Plus className="size-4" aria-hidden="true" /> Add a style
              <ChevronDown className="size-4" aria-hidden="true" />
            </Button>
          }
        />
      </div>

      {chosen.map((c) => {
        const s = byId.get(c.id);
        if (!s) {
          const repo = c.source?.kind === "hub" ? c.source.repo : undefined;
          return list ? (
            <p key={c.id} className="m-0 rounded-md border px-3 py-2 text-sm">
              {c.title ? `${c.title} is` : "A style of this picture is"} not{" "}
              {readOnly ? "on this service" : "on this computer"} any more
              {repo && !readOnly ? ` (it came from Hugging Face, ${repo})` : ""}.{" "}
              {repo && !readOnly ? (
                <>
                  <button
                    type="button"
                    className="underline underline-offset-4"
                    onClick={() => setHubRepo(repo)}
                  >
                    Get it again
                  </button>{" "}
                </>
              ) : null}
              <button
                type="button"
                className="underline underline-offset-4"
                onClick={() => onChange(chosen.filter((x) => x.id !== c.id))}
              >
                Take it out
              </button>
            </p>
          ) : null;
        }
        return (
          <div key={c.id} className="grid gap-2 rounded-md border px-3 py-2">
            <div className="flex items-start gap-2">
              <div className="grid min-w-0 flex-1 gap-0.5">
                <span className="font-medium">
                  {s.title}{" "}
                  <span className="font-normal text-muted-foreground text-xs">
                    {readOnly ? "Added by your admin" : KIND_TAG[s.source.kind]}
                  </span>
                </span>
                <span
                  className={`flex items-center gap-1 text-xs ${
                    s.fit === "fits" && !s.made_for_base ? "text-muted-foreground" : "text-warn"
                  }`}
                >
                  {s.made_for_base ? (
                    <TriangleAlert className="size-4 shrink-0" aria-hidden="true" />
                  ) : (
                    <FitIcon fit={s.fit} />
                  )}
                  {fitLine(s)}
                </span>
              </div>
              <Menu
                items={[
                  {
                    label: "Take it out of this picture",
                    onSelect: () => onChange(chosen.filter((x) => x.id !== c.id)),
                  },
                  ...(readOnly
                    ? []
                    : [
                        {
                          label: "Delete from this computer…",
                          destructive: true,
                          onSelect: () => setDeleting(s),
                        },
                      ]),
                ]}
                trigger={
                  <Button
                    type="button"
                    size="icon"
                    variant="ghost"
                    aria-label={`More for ${s.title}`}
                  >
                    <Ellipsis className="size-4" aria-hidden="true" />
                  </Button>
                }
              />
            </div>
            <Slider
              label={`Strength of ${s.title}`}
              value={c.strength}
              min={0.05}
              max={2}
              step={0.05}
              format={(v) => v.toFixed(2)}
              onValueChange={(v) =>
                onChange(chosen.map((x) => (x.id === c.id ? { ...x, strength: v } : x)))
              }
            />
            {s.trigger ? (
              <p className="m-0 flex flex-wrap items-center gap-2 text-sm">
                <span className="text-muted-foreground">Word</span>
                <span className="font-mono">{s.trigger}</span>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  onClick={() => onUseWord(s.trigger as string)}
                >
                  Use this word
                </Button>
              </p>
            ) : (
              <p className="m-0 text-muted-foreground text-xs">
                This style's word is not known. Many styles need one in the prompt; see where it
                came from.
              </p>
            )}
          </div>
        );
      })}

      {problem ? (
        <p role="alert" className="m-0 text-destructive text-sm">
          {problem}
        </p>
      ) : null}
      <p className="m-0 text-muted-foreground text-xs">
        A style, also called a LoRA, changes the look. Changing styles adds a few seconds to the
        next picture.
        {chosen.length > TOO_MANY ? " Several styles blend and weaken each other." : ""}
      </p>

      {importing ? (
        <ImportStyleDialog
          api={api}
          onClose={() => setImporting(false)}
          onAdded={(style) => {
            setImporting(false);
            void reload();
            add(style);
          }}
        />
      ) : null}
      {naming && settings ? (
        <NameDialog
          title="Save this look"
          label="Its name"
          initial=""
          confirmLabel="Save"
          onCancel={() => setNaming(false)}
          onSubmit={(name) => {
            setNaming(false);
            void api
              .saveLook({ name, ...settings, styles: chosen.filter((c) => byId.has(c.id)) })
              .then(reload)
              .catch((e) =>
                setProblem(e instanceof Error ? e.message : "The look could not be saved."),
              );
          }}
        />
      ) : null}
      {unlooking ? (
        <ConfirmDialog
          title={`Delete the look “${unlooking.name}”?`}
          message="Only the saved settings go. The styles stay on this computer."
          onCancel={() => setUnlooking(null)}
          onConfirm={() => {
            const name = unlooking.name;
            setUnlooking(null);
            void api.deleteLook(name).then(reload);
          }}
        />
      ) : null}
      {fromHub || hubRepo ? (
        <HubStyleDialog
          api={api}
          initialRepo={hubRepo}
          pinned={pinned}
          onClose={() => {
            setFromHub(false);
            setHubRepo(undefined);
            void reload(); // a download left going shows up once it is done
          }}
          onAdded={(style) => {
            setFromHub(false);
            setHubRepo(undefined);
            void reload();
            add(style);
          }}
        />
      ) : null}
      {deleting ? (
        <ConfirmDialog
          title={`Delete ${deleting.title}?`}
          message="The app's copy of this style is removed from this computer. Pictures made with it stay."
          onConfirm={() => void remove(deleting)}
          onCancel={() => setDeleting(null)}
        />
      ) : null}
    </section>
  );
}
