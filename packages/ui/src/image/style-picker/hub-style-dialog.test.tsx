// @vitest-environment jsdom
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { type HubStyleFiles, type Style, StyleError, type StylesApi } from "@wasifyai/client";
import { StrictMode } from "react";
import { describe, expect, it, vi } from "vitest";
import { HubStyleDialog } from "./HubStyleDialog";

const FILES: HubStyleFiles = {
  repo: "Sawata97/flux2_4b_koni_animestyle",
  commit: "a".repeat(40),
  gated: false,
  files: [{ name: "Flux_klein_4b_anime_Koni.safetensors", size: 184832664 }],
  refused: [{ name: "old.ckpt", why: "not offered: it can run code" }],
  made_for_base: false,
  trigger: "anime_style",
  stale: false,
};

const KONI = { id: "k1", title: "Flux klein 4b anime Koni" } as Style;

function fakeApi(over: Partial<Record<keyof StylesApi, unknown>> = {}) {
  let polls = 0;
  return {
    hubFiles: vi.fn(async () => FILES),
    allowHub: vi.fn(async () => ({ enabled: true })),
    hubDownload: vi.fn(async () => ({
      id: "d1",
      status: "running",
      bytes_total: 184832664,
      bytes_done: 0,
      error: "",
    })),
    hubJob: vi.fn(async () => {
      polls += 1;
      const done = polls > 1;
      return {
        download: {
          id: "d1",
          status: done ? "done" : "running",
          bytes_total: 184832664,
          bytes_done: done ? 184832664 : 92416332,
          error: "",
        },
        ...(done ? { style: KONI } : {}),
      };
    }),
    ...over,
  } as unknown as StylesApi & Record<string, ReturnType<typeof vi.fn>>;
}

async function look(repo = "https://huggingface.co/Sawata97/flux2_4b_koni_animestyle") {
  await userEvent.type(screen.getByLabelText("Name or address"), repo);
  await userEvent.click(screen.getByRole("button", { name: "Look" }));
}

describe("Get a style from Hugging Face", () => {
  it("offers only the .safetensors files with their size, says why others are not offered, and what it was made for", async () => {
    const api = fakeApi();
    render(<HubStyleDialog api={api} onClose={() => {}} onAdded={() => {}} pollMs={1} />);
    await look();
    expect(api.hubFiles).toHaveBeenCalledWith(
      "https://huggingface.co/Sawata97/flux2_4b_koni_animestyle",
    );
    expect(
      await screen.findByRole("radio", { name: /Flux_klein_4b_anime_Koni.safetensors/ }),
    ).toBeChecked();
    expect(screen.getByText(/not offered: it can run code/)).toBeInTheDocument();
    expect(screen.getByText(/Its word: anime_style/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Download 185 MB and add" })).toBeEnabled();
    expect(api.hubDownload).not.toHaveBeenCalled(); // nothing is fetched before the person chooses
  });

  it("downloads the file the person confirmed, shows the progress, and adds the checked style", async () => {
    const api = fakeApi();
    const onAdded = vi.fn();
    render(<HubStyleDialog api={api} onClose={() => {}} onAdded={onAdded} pollMs={1} />);
    await look("Sawata97/flux2_4b_koni_animestyle");
    await userEvent.click(await screen.findByRole("button", { name: /Download .* and add/ }));
    expect(api.hubDownload).toHaveBeenCalledWith(
      "Sawata97/flux2_4b_koni_animestyle",
      "Flux_klein_4b_anime_Koni.safetensors",
      184832664,
      undefined,
    );
    expect(await screen.findByText(/was checked and added/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Use it in this picture" }));
    expect(onAdded).toHaveBeenCalledWith(KONI);
  });

  it("asks to allow browsing first, and looks again once allowed", async () => {
    let allowed = false;
    const api = fakeApi({
      hubFiles: vi.fn(async () => {
        if (!allowed) throw new StyleError(403, "Turn it on first.", "consent_needed");
        return FILES;
      }),
      allowHub: vi.fn(async () => {
        allowed = true;
        return { enabled: true };
      }),
    });
    render(<HubStyleDialog api={api} onClose={() => {}} onAdded={() => {}} pollMs={1} />);
    await look("Sawata97/flux2_4b_koni_animestyle");
    await userEvent.click(
      await screen.findByRole("button", { name: "Allow browsing Hugging Face" }),
    );
    expect(await screen.findByRole("radio", { name: /Koni/ })).toBeInTheDocument();
  });

  it("a file that turns out not to be a style is said, and nothing is added", async () => {
    const onAdded = vi.fn();
    const api = fakeApi({
      hubJob: vi.fn(async () => ({
        download: { id: "d1", status: "done", bytes_total: 1, bytes_done: 1, error: "" },
        refused: "This is a model, not a style (a LoRA).",
      })),
    });
    render(<HubStyleDialog api={api} onClose={() => {}} onAdded={onAdded} pollMs={1} />);
    await look("Sawata97/flux2_4b_koni_animestyle");
    await userEvent.click(await screen.findByRole("button", { name: /Download .* and add/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("This is a model, not a style");
    expect(onAdded).not.toHaveBeenCalled();
  });

  it("an offline answer from before is said", async () => {
    const api = fakeApi({ hubFiles: vi.fn(async () => ({ ...FILES, stale: true })) });
    render(<HubStyleDialog api={api} onClose={() => {}} onAdded={() => {}} pollMs={1} />);
    await look("Sawata97/flux2_4b_koni_animestyle");
    await waitFor(() =>
      expect(
        screen.getByText(/could not be reached: this list is from before/),
      ).toBeInTheDocument(),
    );
  });

  it("keeps following the download when React mounts it twice (its development checks)", async () => {
    const api = fakeApi();
    render(
      <StrictMode>
        <HubStyleDialog api={api} onClose={() => {}} onAdded={() => {}} pollMs={1} />
      </StrictMode>,
    );
    await look("Sawata97/flux2_4b_koni_animestyle");
    await userEvent.click(await screen.findByRole("button", { name: /Download .* and add/ }));
    expect(await screen.findByText(/was checked and added/)).toBeInTheDocument();
  });

  it("a recommended style is chosen for the person and fetched only with the checksum we checked", async () => {
    const api = fakeApi();
    const sha = "c".repeat(64);
    render(
      <HubStyleDialog
        api={api}
        onClose={() => {}}
        onAdded={() => {}}
        pollMs={1}
        initialRepo="Sawata97/flux2_4b_koni_animestyle"
        pinned={{ file: "Flux_klein_4b_anime_Koni.safetensors", sha256: sha }}
      />,
    ); // fmt: skip
    expect(await screen.findByRole("radio", { name: /Koni/ })).toBeChecked();
    await userEvent.click(screen.getByRole("button", { name: /Download .* and add/ }));
    await waitFor(() =>
      expect(api.hubDownload).toHaveBeenCalledWith(
        "Sawata97/flux2_4b_koni_animestyle",
        "Flux_klein_4b_anime_Koni.safetensors",
        184832664,
        sha,
      ),
    ); // fmt: skip
  });
});
