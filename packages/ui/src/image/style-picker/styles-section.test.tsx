// @vitest-environment jsdom
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Look, Style, StyleChoice, StylesApi, StylesList } from "@wasifyai/client";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { ImportStyleDialog } from "./ImportStyleDialog";
import { StylesSection } from "./StylesSection";
import { fitLine } from "./fit";

const style = (over: Partial<Style>): Style => ({
  id: "a1",
  title: "Ink",
  source: { kind: "file" },
  sha256: "x",
  size: 83 * 1024 * 1024,
  model: "FLUX.2 klein 4B",
  fit: "fits",
  made_for_base: false,
  rank: 16,
  unused_parts: 0,
  trigger: null,
  added_at: 1,
  selectable: true,
  ...over,
});

function fakeApi(list: StylesList, looks: Look[] = []) {
  let state = list;
  let kept = looks;
  const api = {
    list: vi.fn(async () => state),
    looks: vi.fn(async () => kept),
    saveLook: vi.fn(async (l: Omit<Look, "saved_at">) => {
      const saved = { ...l, saved_at: 1 };
      kept = [...kept.filter((x) => x.name !== l.name), saved];
      return saved;
    }),
    deleteLook: vi.fn(async (name: string) => {
      kept = kept.filter((x) => x.name !== name);
    }),
    hubFiles: vi.fn(async (repo: string) => ({
      repo,
      commit: null,
      gated: false,
      files: [],
      refused: [],
      made_for_base: null,
      trigger: null,
      stale: false,
    })),
    importFile: vi.fn(async (_f: Blob, name: string) => {
      const s = style({
        id: "new1",
        title: name.replace(".safetensors", ""),
        trigger: "ena",
        added_at: Date.now() / 1000,
      });
      state = { ...state, styles: [...state.styles, s] };
      return s;
    }),
    fromFound: vi.fn(async (id: string) => {
      const s = style({
        id: `copy-${id}`,
        title: "Anime",
        source: { kind: "found", tool: "ComfyUI" },
      });
      state = { ...state, found: [], styles: [...state.styles, s] };
      return s;
    }),
    update: vi.fn(async (id: string, change: { title?: string; trigger?: string }) => {
      const s = { ...(state.styles.find((x) => x.id === id) as Style), ...change };
      state = { ...state, styles: state.styles.map((x) => (x.id === id ? s : x)) };
      return s;
    }),
    remove: vi.fn(async (id: string) => {
      state = { ...state, styles: state.styles.filter((x) => x.id !== id) };
    }),
  };
  return api as unknown as StylesApi & typeof api;
}

function Harness({
  api,
  start = [],
  onWord = () => {},
  onChosen = () => {},
  onLook,
}: {
  api: StylesApi;
  start?: StyleChoice[];
  onWord?: (w: string) => void;
  onChosen?: (c: StyleChoice[]) => void;
  onLook?: (s: {
    size: string | null;
    width: number | null;
    height: number | null;
    steps: number | null;
  }) => void;
}) {
  const [chosen, setChosen] = useState(start);
  return (
    <StylesSection
      api={api}
      chosen={chosen}
      onChange={(c) => {
        setChosen(c);
        onChosen(c);
      }}
      onUseWord={onWord}
      onOpenFolders={() => {}}
      settings={onLook ? { size: "wide", width: null, height: null, steps: 8 } : undefined}
      onApplyLook={onLook}
    />
  );
}

const ena = style({
  id: "e1",
  title: "Ena",
  source: { kind: "trained", run: "b37ba287" },
  trigger: "ena",
  made_for_base: true,
});
const nine = style({
  id: "n9",
  title: "Arcane",
  model: "FLUX.2 klein 9B",
  fit: "other",
  selectable: false,
});

async function openAdd() {
  await userEvent.click(await screen.findByRole("button", { name: /Add a style/ }));
}

describe("the Styles section", () => {
  it("is always there, and offers yours first, the ones kept here, another app's and a file", async () => {
    const api = fakeApi({
      styles: [ena, style({}), nine],
      found: [{ id: "f1", title: "Anime", tool: "ComfyUI", size: 1 }],
      max: 8,
    });
    render(<Harness api={api} />);
    expect(screen.getByRole("heading", { name: /Styles \(optional\)/ })).toBeInTheDocument();
    await waitFor(() => expect(api.list).toHaveBeenCalled());
    await openAdd();
    const items = (await screen.findAllByRole("menuitem")).map((i) => [
      i.textContent,
      i.getAttribute("data-disabled") !== null,
    ]);
    expect(items).toEqual([
      ["Ena (yours)", false],
      ["Ink", false],
      ["Arcane", true], // made for another model: shown, never chosen
      ["Anime (ComfyUI)", false],
      ["From this computer…", false],
      ["From Hugging Face…", false],
      ["Look in a folder…", false],
    ]);
  });

  it("offers the recommended styles that are not here yet, and opens them from Hugging Face", async () => {
    const rec = {
      title: "Anime",
      repo: "Sawata97/flux2_4b_koni_animestyle",
      file: "k.safetensors",
      size: 184832664,
      sha256: "c".repeat(64),
      word: "anime_style",
      note: "",
    };
    const api = fakeApi({ styles: [], found: [], max: 8, recommended: [rec] });
    render(<Harness api={api} />);
    await openAdd();
    await userEvent.click(
      await screen.findByRole("menuitem", { name: "Anime (recommended, 185 MB)" }),
    );
    await waitFor(() =>
      expect(api.hubFiles).toHaveBeenCalledWith("Sawata97/flux2_4b_koni_animestyle"),
    );
  });

  it("a chosen style shows its strength, what it was made for and its word", async () => {
    const onWord = vi.fn();
    const onChosen = vi.fn();
    const api = fakeApi({ styles: [ena], found: [], max: 8 });
    render(<Harness api={api} onWord={onWord} onChosen={onChosen} />);
    await openAdd();
    await userEvent.click(await screen.findByRole("menuitem", { name: "Ena (yours)" }));
    expect(onChosen).toHaveBeenLastCalledWith([{ id: "e1", strength: 1 }]);
    expect(screen.getByText("Made by you")).toBeInTheDocument();
    expect(
      screen.getByText(/made for klein base: the look may not show on this model/),
    ).toBeInTheDocument();
    expect(screen.getByRole("slider", { name: "Strength of Ena" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Use this word" }));
    expect(onWord).toHaveBeenCalledWith("ena");
  });

  it("a style from another app is copied in when chosen", async () => {
    const onChosen = vi.fn();
    const api = fakeApi({
      styles: [],
      found: [{ id: "f1", title: "Anime", tool: "ComfyUI", size: 1 }],
      max: 8,
    });
    render(<Harness api={api} onChosen={onChosen} />);
    await openAdd();
    await userEvent.click(await screen.findByRole("menuitem", { name: "Anime (ComfyUI)" }));
    await waitFor(() =>
      expect(onChosen).toHaveBeenLastCalledWith([{ id: "copy-f1", strength: 1 }]),
    );
    expect(api.fromFound).toHaveBeenCalledWith("f1");
  });

  it("delete asks first and takes the style out of the picture", async () => {
    const onChosen = vi.fn();
    const api = fakeApi({ styles: [style({})], found: [], max: 8 });
    render(<Harness api={api} start={[{ id: "a1", strength: 0.5 }]} onChosen={onChosen} />);
    await userEvent.click(await screen.findByRole("button", { name: "More for Ink" }));
    await userEvent.click(
      await screen.findByRole("menuitem", { name: "Delete from this computer…" }),
    );
    expect(api.remove).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(api.remove).toHaveBeenCalledWith("a1"));
    expect(onChosen).toHaveBeenLastCalledWith([]);
  });

  it("a style that is not here any more can be taken out", async () => {
    const onChosen = vi.fn();
    render(
      <Harness
        api={fakeApi({ styles: [], found: [], max: 8 })}
        start={[{ id: "gone", strength: 1 }]}
        onChosen={onChosen}
      />,
    );
    await userEvent.click(await screen.findByRole("button", { name: "Take it out" }));
    expect(onChosen).toHaveBeenLastCalledWith([]);
  });

  it("says when several styles weaken each other", async () => {
    const styles = ["a", "b", "c", "d"].map((id) => style({ id, title: id }));
    render(
      <Harness
        api={fakeApi({ styles, found: [], max: 8 })}
        start={styles.map((s) => ({ id: s.id, strength: 1 }))}
      />,
    );
    expect(
      await screen.findByText(/Several styles blend and weaken each other/),
    ).toBeInTheDocument();
  });

  it("names the model in words", () => {
    expect(fitLine(nine)).toBe("Made for FLUX.2 klein 9B: it would give noise here");
    expect(fitLine(style({ fit: "unsure", model: null }))).toMatch(/^Not sure which model/);
    expect(fitLine(style({ unused_parts: 6 }))).toMatch(/a few parts of it are not used here/);
  });
});

describe("saved looks and finding a style again", () => {
  it("saves the screen's size, steps and styles under a name, and applies a look", async () => {
    const onLook = vi.fn();
    const onChosen = vi.fn();
    const look: Look = {
      name: "Anime wide",
      size: "wide",
      width: null,
      height: null,
      steps: 6,
      styles: [{ id: "a1", strength: 0.7 }],
      saved_at: 1,
    };
    const api = fakeApi({ styles: [style({})], found: [], max: 8 }, [look]);
    render(
      <Harness api={api} start={[{ id: "a1", strength: 1 }]} onLook={onLook} onChosen={onChosen} />,
    );
    await userEvent.click(await screen.findByRole("button", { name: /Saved looks/ }));
    await userEvent.click(await screen.findByRole("menuitem", { name: "Anime wide" }));
    expect(onLook).toHaveBeenCalledWith({ size: "wide", width: null, height: null, steps: 6 });
    expect(onChosen).toHaveBeenLastCalledWith([{ id: "a1", strength: 0.7 }]);

    await userEvent.click(screen.getByRole("button", { name: /Saved looks/ }));
    await userEvent.click(await screen.findByRole("menuitem", { name: "Save this look…" }));
    await userEvent.type(screen.getByLabelText("Its name"), "Soft");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(api.saveLook).toHaveBeenCalledWith({
        name: "Soft",
        size: "wide",
        width: null,
        height: null,
        steps: 8,
        styles: [{ id: "a1", strength: 0.7 }],
      }),
    ); // fmt: skip
  });

  it("a style that came back under another id is found by its checksum", async () => {
    const onChosen = vi.fn();
    const api = fakeApi({ styles: [style({ id: "new", sha256: "same" })], found: [], max: 8 });
    render(
      <Harness
        api={api}
        start={[{ id: "old", strength: 0.6, sha256: "same", title: "Ink" }]}
        onChosen={onChosen}
      />,
    );
    await waitFor(() =>
      expect(onChosen).toHaveBeenLastCalledWith([
        { id: "new", strength: 0.6, sha256: "same", title: "Ink" },
      ]),
    );
  });

  it("a missing style is named, and one from Hugging Face can be got again", async () => {
    const api = fakeApi({ styles: [], found: [], max: 8 });
    render(
      <Harness
        api={api}
        start={[
          {
            id: "gone",
            strength: 1,
            sha256: "x",
            title: "Koni anime",
            source: { kind: "hub", repo: "Sawata97/flux2_4b_koni_animestyle" },
          },
        ]}
      />,
    ); // fmt: skip
    expect(
      await screen.findByText(
        /Koni anime is not on this computer any more \(it came from Hugging Face, Sawata97\/flux2_4b_koni_animestyle\)/,
      ),
    ).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Get it again" }));
    await waitFor(() =>
      expect(api.hubFiles).toHaveBeenCalledWith("Sawata97/flux2_4b_koni_animestyle"),
    );
  });
});

describe("on the web, read only", () => {
  it("offers only the admin's styles: no files, Hugging Face, folders, looks or delete", async () => {
    const api = fakeApi({
      styles: [style({ id: "s1", title: "Anime", source: { kind: "hub", repo: "a/b" } })],
      found: [],
      max: 8,
    });
    const onChosen = vi.fn();
    render(
      <StylesSection
        api={api}
        chosen={[]}
        onChange={onChosen}
        onUseWord={() => {}}
        readOnly
        settings={{ size: "square", width: null, height: null, steps: null }}
        onApplyLook={() => {}}
      />,
    ); // fmt: skip
    await waitFor(() => expect(api.list).toHaveBeenCalled());
    expect(screen.queryByRole("button", { name: /Saved looks/ })).not.toBeInTheDocument();
    await openAdd();
    const items = (await screen.findAllByRole("menuitem")).map((i) => i.textContent);
    expect(items).toEqual(["Anime"]);
    await userEvent.click(screen.getByRole("menuitem", { name: "Anime" }));
    expect(onChosen).toHaveBeenLastCalledWith([{ id: "s1", strength: 1 }]);
  });

  it("a chosen style shows who added it, and has no delete", async () => {
    const api = fakeApi({ styles: [style({ id: "s1", title: "Anime" })], found: [], max: 8 });
    render(
      <StylesSection
        api={api}
        chosen={[{ id: "s1", strength: 1 }]}
        onChange={() => {}}
        onUseWord={() => {}}
        readOnly
      />,
    ); // fmt: skip
    expect(await screen.findByText("Added by your admin")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "More for Anime" }));
    expect((await screen.findAllByRole("menuitem")).map((i) => i.textContent)).toEqual([
      "Take it out of this picture",
    ]);
  });

  it("a style the admin removed is said to be gone from the service", async () => {
    const api = fakeApi({ styles: [], found: [], max: 8 });
    render(
      <StylesSection
        api={api}
        chosen={[{ id: "x", strength: 1, title: "Anime" }]}
        onChange={() => {}}
        onUseWord={() => {}}
        readOnly
      />,
    ); // fmt: skip
    expect(await screen.findByText(/Anime is not on this service any more/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Get it again" })).not.toBeInTheDocument();
  });
});

describe("Add a style from this computer", () => {
  it("checks the file, lets it be named, and adds it", async () => {
    const api = fakeApi({ styles: [], found: [], max: 8 });
    const onAdded = vi.fn();
    render(<ImportStyleDialog api={api} onClose={() => {}} onAdded={onAdded} />);
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    await userEvent.upload(input, new File([new Uint8Array([1])], "ena_klein.safetensors"));
    expect(await screen.findByText(/Checked: Made for FLUX.2 klein 4B/)).toBeInTheDocument();
    expect(screen.getByLabelText(/Word/)).toHaveValue("ena");
    await userEvent.clear(screen.getByLabelText("Name"));
    await userEvent.type(screen.getByLabelText("Name"), "Ena");
    await userEvent.click(screen.getByRole("button", { name: "Add this style" }));
    await waitFor(() => expect(onAdded).toHaveBeenCalled());
    expect(api.update).toHaveBeenCalledWith("new1", { title: "Ena" });
  });

  it("refuses other files before sending them, and Cancel takes a new copy away", async () => {
    const api = fakeApi({ styles: [], found: [], max: 8 });
    const onClose = vi.fn();
    render(<ImportStyleDialog api={api} onClose={onClose} onAdded={() => {}} />);
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    await userEvent.upload(input, new File([new Uint8Array([1])], "model.ckpt"), {
      applyAccept: false,
    });
    expect(await screen.findByRole("alert")).toHaveTextContent(/can run code/);
    expect(api.importFile).not.toHaveBeenCalled();
    await userEvent.upload(input, new File([new Uint8Array([1])], "x.safetensors"));
    await screen.findByText(/Checked:/);
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(api.remove).toHaveBeenCalledWith("new1");
  });
});
