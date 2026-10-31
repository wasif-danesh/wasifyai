"use client";
// The person's brand in the editor (ADR-0096 MX7): set once, on every new project; here it is
// turned on or off for this project, and changed.
import type { BrandKit, VideoBuilderApi } from "@wasifyai/client";
import { useEffect, useId, useState } from "react";
import { Button } from "../../components/button";
import { Modal } from "../../components/dialog";
import { Notice } from "../../components/notice";
import { say } from "./use-scene-editor";

type Colour = "background" | "second" | "text" | "accent";
const COLOURS: { id: Colour; label: string }[] = [
  { id: "background", label: "Background" },
  { id: "second", label: "It fades to" },
  { id: "text", label: "Words" },
  { id: "accent", label: "Accent" },
];
const FIRST_KIT: BrandKit = {
  name: "",
  background: "#0b1220",
  second: "#1c2b4a",
  text: "#f5f7fb",
  accent: "#4f8cff",
  font: "sans",
  action: "",
  address: "",
  logo_on_scenes: true,
  logo_asset: null,
};

function brightness(hex: string) {
  const channel = (at: number) => {
    const c = Number.parseInt(hex.slice(at, at + 2), 16) / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * channel(1) + 0.7152 * channel(3) + 0.0722 * channel(5);
}

/** How far apart two colours are to read, 1 to 21: below 3, large words are hard to read. */
export function contrast(a: string, b: string) {
  const [dark, light] = [brightness(a), brightness(b)].sort((x, y) => x - y) as [number, number];
  return (light + 0.05) / (dark + 0.05);
}

export function BrandTools({
  api,
  kit,
  on,
  fonts,
  onKit,
  onUse,
}: {
  api: VideoBuilderApi;
  kit: BrandKit | null;
  on: boolean;
  fonts: Record<string, string>;
  onKit: (kit: BrandKit) => void;
  onUse: (use: boolean, kit?: BrandKit) => Promise<void>;
}) {
  const [editing, setEditing] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  async function use(wanted: boolean, saved?: BrandKit) {
    setProblem(null);
    try {
      await onUse(wanted, saved);
    } catch (e) {
      setProblem(say(e, "That could not be changed."));
    }
  }

  return (
    <div className="grid gap-2 rounded-md border p-2">
      <h2 className="m-0 font-semibold text-sm">Your brand</h2>
      {kit ? (
        <>
          <div className="flex items-center gap-1.5">
            {COLOURS.map((c) => (
              <span
                key={c.id}
                className="size-5 rounded-full border"
                style={{ background: kit[c.id] }}
              />
            ))}
            <span className="min-w-0 truncate text-xs">{kit.name}</span>
          </div>
          <label className="flex items-center gap-2 text-xs">
            <input type="checkbox" checked={on} onChange={(ev) => void use(ev.target.checked)} />
            Use it in this video
          </label>
        </>
      ) : (
        <p className="m-0 text-muted-foreground text-xs">
          Your logo, colours and end card, set once and used in every new video.
        </p>
      )}
      <Button type="button" variant="outline" size="sm" onClick={() => setEditing(true)}>
        {kit ? "Change your brand" : "Set up your brand"}
      </Button>
      {problem ? (
        <Notice tone="error" title="That did not work">
          {problem}
        </Notice>
      ) : null}
      {editing ? (
        <BrandDialog
          api={api}
          kit={kit ?? FIRST_KIT}
          fonts={fonts}
          onClose={() => setEditing(false)}
          onSaved={(saved) => {
            onKit(saved);
            setEditing(false);
            // what is on this video follows what was just saved; a first brand goes on it as well
            if (on || !kit) void use(true, saved);
          }}
        />
      ) : null}
    </div>
  );
}

function BrandDialog({
  api,
  kit,
  fonts,
  onClose,
  onSaved,
}: {
  api: VideoBuilderApi;
  kit: BrandKit;
  fonts: Record<string, string>;
  onClose: () => void;
  onSaved: (kit: BrandKit) => void;
}) {
  const [draft, setDraft] = useState(kit);
  const [logo, setLogo] = useState<File | null>(null);
  const [shown, setShown] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const id = useId();
  const change = (more: Partial<BrandKit>) => setDraft((d) => ({ ...d, ...more }));
  const hard = contrast(draft.text, draft.background) < 3 || contrast(draft.text, draft.second) < 3;

  useEffect(() => {
    let url: string | null = null;
    let current = true;
    if (logo) {
      url = URL.createObjectURL(logo);
      setShown(url);
    } else if (kit.logo_asset) {
      api.brandLogo().then(
        (found) => {
          if (current) {
            url = found;
            setShown(found);
          } else URL.revokeObjectURL(found);
        },
        () => {},
      );
    }
    return () => {
      current = false;
      if (url) URL.revokeObjectURL(url);
    };
  }, [api, kit.logo_asset, logo]);

  async function save() {
    setSaving(true);
    setProblem(null);
    try {
      const { logo_asset: _kept, ...words } = draft;
      let saved = (await api.setBrand(words)).kit;
      if (logo) saved = (await api.setBrandLogo(logo)).kit;
      if (saved) onSaved(saved);
    } catch (e) {
      setProblem(say(e, "Your brand could not be saved."));
      setSaving(false);
    }
  }

  return (
    <Modal label="Your brand" onClose={onClose}>
      <div className="grid gap-3">
        <label className="grid gap-1 text-sm" htmlFor={`${id}-name`}>
          Name
          <input
            id={`${id}-name`}
            className="rounded-md border border-input bg-transparent px-3 py-1.5 text-sm"
            maxLength={60}
            value={draft.name}
            onChange={(ev) => change({ name: ev.target.value })}
          />
        </label>
        <div className="flex items-center gap-3">
          {shown ? <img src={shown} alt="Your logo" className="max-h-12 max-w-32" /> : null}
          <label className="cursor-pointer rounded-md border px-3 py-1.5 text-sm hover:bg-muted">
            {shown ? "Choose another logo" : "Add your logo"}
            <input
              type="file"
              className="sr-only"
              accept="image/png,image/jpeg,image/webp"
              onChange={(ev) => setLogo(ev.target.files?.[0] ?? null)}
            />
          </label>
        </div>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={draft.logo_on_scenes}
            onChange={(ev) => change({ logo_on_scenes: ev.target.checked })}
          />
          Show the logo in the corner of every scene
        </label>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          {COLOURS.map((c) => (
            <label key={c.id} className="grid gap-1 text-xs">
              {c.label}
              <input
                type="color"
                className="h-9 w-full rounded-md border border-input bg-transparent"
                value={draft[c.id]}
                onChange={(ev) => change({ [c.id]: ev.target.value })}
              />
            </label>
          ))}
        </div>
        {hard ? (
          <p className="m-0 text-muted-foreground text-xs">
            The words may be hard to read on these colours.
          </p>
        ) : null}
        <label className="grid gap-1 text-sm">
          Letters
          <select
            className="rounded-md border border-input bg-background px-2 py-1.5 text-sm"
            value={draft.font}
            onChange={(ev) => change({ font: ev.target.value })}
          >
            {Object.entries(fonts).map(([value, family]) => (
              <option key={value} value={value}>
                {family}
              </option>
            ))}
          </select>
        </label>
        <label className="grid gap-1 text-sm">
          What should people do at the end?
          <input
            className="rounded-md border border-input bg-transparent px-3 py-1.5 text-sm"
            maxLength={60}
            placeholder="Try it today"
            value={draft.action}
            onChange={(ev) => change({ action: ev.target.value })}
          />
        </label>
        <label className="grid gap-1 text-sm">
          Where? A web address or a place
          <input
            className="rounded-md border border-input bg-transparent px-3 py-1.5 text-sm"
            maxLength={80}
            value={draft.address}
            onChange={(ev) => change({ address: ev.target.value })}
          />
        </label>
        {problem ? (
          <Notice tone="error" title="That did not work">
            {problem}
          </Notice>
        ) : null}
        <div className="flex justify-end gap-2">
          <Button type="button" variant="outline" onClick={onClose}>
            Not now
          </Button>
          <Button type="button" disabled={saving} onClick={() => void save()}>
            Save your brand
          </Button>
        </div>
      </div>
    </Modal>
  );
}
