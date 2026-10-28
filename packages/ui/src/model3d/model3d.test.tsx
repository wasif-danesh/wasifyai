// @vitest-environment jsdom
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type {
  Model3d as Model,
  Model3dApi,
  Model3dComponent,
  PictureInput,
} from "@wasifyai/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Model3d } from "./Model3d";

vi.mock("./viewer-loader", () => ({ loadViewer: () => Promise.resolve() }));

const BYTES = 8_977_179_071;

function component(over: Partial<Model3dComponent> = {}): Model3dComponent {
  return {
    installed: false,
    source: null,
    plan: {
      supported: true,
      platform: "darwin-arm64",
      bytes: BYTES,
      parts: [
        {
          name: "3D engine (pixal3d.cpp)",
          version: "v0.10.1",
          bytes: 2_440_967,
          licence: "MIT",
          source: "github.com",
        },
        {
          name: "Pixal3D models",
          version: "single view, Q8_0",
          bytes: 8_091_975_360,
          licence: "MIT, and the DINOv3 licence",
          source: "huggingface.co",
        },
        {
          name: "Cut-out model (BiRefNet)",
          version: "Q8_0",
          bytes: 882_749_024,
          licence: "MIT",
          source: "huggingface.co",
        },
      ],
      found: null,
    },
    progress: { state: "idle", step: null, message: "", done_bytes: 0, total_bytes: 0 },
    fit: { verdict: "fits", reason: "It fits." },
    about: {
      built_with: "Built with DINOv3",
      licence: "Models: MIT, and the DINOv3 licence for the image encoder.",
      where: "Everything runs on this computer.",
    },
    ...over,
  };
}

const READY = component({ installed: true });

function picture(over: Partial<PictureInput> = {}): PictureInput {
  return {
    id: "p".repeat(32),
    status: "ready",
    name: "frog.png",
    width: 600,
    height: 400,
    stage: "",
    checks: [
      {
        code: "one_object",
        level: "ok",
        message: "One object, in the middle, with all of it showing.",
      },
      { code: "tip", level: "ok", message: "A straight-on picture at eye level works best." },
    ],
    error: null,
    can_go_on: true,
    created_at: "2026-10-21T10:00:00Z",
    ...over,
  };
}

function model(over: Partial<Model> = {}): Model {
  return {
    id: "m".repeat(32),
    title: "Frog mug",
    prompt: "",
    input_id: "p".repeat(32),
    status: "working",
    stage: "Building the shape",
    progress: 0.4,
    error: null,
    detail: "standard",
    seed: 42,
    recipe: {},
    elapsed_s: null,
    peak_gb: null,
    glb_bytes: null,
    created_at: "2026-10-21T10:01:00Z",
    finished_at: null,
    live: true,
    ...over,
  };
}

function api(over: Partial<Model3dApi> = {}): Model3dApi {
  return {
    component: vi.fn().mockResolvedValue(READY),
    install: vi.fn(),
    cancelInstall: vi.fn().mockResolvedValue(component()),
    uninstall: vi.fn(),
    status: vi.fn().mockResolvedValue({
      ready: true,
      problem: null,
      fit: { verdict: "fits", reason: "It fits." },
      busy: false,
      active: null,
      details: ["light", "standard", "detailed"],
    }),
    addPicture: vi.fn().mockResolvedValue(picture()),
    picture: vi.fn().mockResolvedValue(picture()),
    pictureImage: vi.fn().mockImplementation(async (_id, which) => `blob:${which}`),
    removePicture: vi.fn().mockResolvedValue(undefined),
    make: vi.fn().mockResolvedValue(model()),
    list: vi.fn().mockResolvedValue([]),
    get: vi.fn().mockResolvedValue(
      model({
        status: "done",
        progress: 1,
        stage: "",
        elapsed_s: 611,
        glb_bytes: 35_000_000,
        live: false,
      }),
    ),
    cancel: vi
      .fn()
      .mockResolvedValue({ ...model({ status: "cancelled", error: "Stopped." }), stopped: true }),
    again: vi.fn().mockResolvedValue(model({ id: "n".repeat(32) })),
    rename: vi.fn().mockImplementation(async (_id, title) => model({ title, status: "done" })),
    remove: vi.fn().mockResolvedValue(undefined),
    fileUrl: vi.fn().mockImplementation(async (_id, which) => `blob:${which}`),
    exportCopy: vi
      .fn()
      .mockResolvedValue({ name: "frog-mug.glb", path: "/Downloads/frog-mug.glb" }),
    ...over,
  };
}

const file = () => new File([new Uint8Array([137, 80, 78, 71])], "frog.png", { type: "image/png" });

beforeEach(() => {
  // jsdom has no object URLs: the screen revokes the ones it was given
  Object.defineProperty(URL, "revokeObjectURL", {
    value: vi.fn(),
    configurable: true,
    writable: true,
  });
});
afterEach(() => {
  localStorage.clear();
  vi.restoreAllMocks();
});

describe("setting up 3D", () => {
  it("shows every part with its size and licence, and sets up with the size that was shown", async () => {
    const a = api({
      component: vi.fn().mockResolvedValue(component()),
      install: vi.fn().mockResolvedValue(
        component({
          progress: {
            state: "installing",
            step: "models",
            message: "Getting dinov3.gguf",
            done_bytes: 1e9,
            total_bytes: BYTES,
          },
        }),
      ),
    });
    const user = userEvent.setup();
    render(<Model3d api={a} />);
    expect(await screen.findByRole("heading", { name: "Set up 3D" })).toBeInTheDocument();
    for (const name of ["3D engine (pixal3d.cpp)", "Pixal3D models", "Cut-out model (BiRefNet)"]) {
      expect(screen.getByText(name)).toBeInTheDocument();
    }
    expect(
      screen.getByText(/MIT, and the DINOv3 licence · from huggingface\.co/),
    ).toBeInTheDocument();
    expect(screen.getByText(/Built with DINOv3\. The models need about 19 GB/)).toBeInTheDocument();
    expect(a.install).not.toHaveBeenCalled(); // nothing is fetched before the click
    await user.click(screen.getByRole("button", { name: "Download and set up (9.0 GB)" }));
    expect(a.install).toHaveBeenCalledWith(BYTES);
    expect(await screen.findByText("Getting dinov3.gguf")).toBeInTheDocument();
    expect(
      screen.getByRole("progressbar", { name: "Setup progress", hidden: true }),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Cancel/ }));
    expect(a.cancelInstall).toHaveBeenCalled();
  });

  it("says plainly when the computer is not one it was measured on", async () => {
    const c = component();
    c.plan.supported = false;
    render(<Model3d api={api({ component: vi.fn().mockResolvedValue(c) })} />);
    expect(await screen.findByText(/not offered on other computers yet/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Download/ })).toBeNull();
  });

  it("reports a failed setup in the engine's words and offers it again", async () => {
    const c = component({
      progress: {
        state: "failed",
        step: "models",
        message: "dinov3.gguf did not match its published checksum, so it was not kept. Try again.",
        done_bytes: 0,
        total_bytes: 0,
      },
    });
    render(<Model3d api={api({ component: vi.fn().mockResolvedValue(c) })} />);
    expect(await screen.findByText(/did not match its published checksum/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Download and set up/ })).toBeInTheDocument();
  });

  it("follows the setup and shows the start screen when it is ready", async () => {
    const installing = component({
      progress: {
        state: "installing",
        step: "models",
        message: "Getting the models",
        done_bytes: 10,
        total_bytes: 100,
      },
    });
    const first = vi.fn().mockResolvedValueOnce(installing).mockResolvedValue(READY);
    render(<Model3d api={api({ component: first })} />);
    expect(await screen.findByText("Getting the models")).toBeInTheDocument();
    expect(
      await screen.findByRole("heading", { name: "Make a 3D model" }, { timeout: 3000 }),
    ).toBeInTheDocument();
    expect(
      await screen.findByRole("button", { name: "Choose a picture" }, { timeout: 3000 }),
    ).toBeInTheDocument();
  });
});

describe("starting from a picture", () => {
  it("sends the chosen file and then shows it, its cut-out and what was found", async () => {
    const user = userEvent.setup();
    const a = api();
    render(<Model3d api={a} />);
    await user.upload(await screen.findByLabelText("Choose a picture"), file());
    expect(a.addPicture).toHaveBeenCalledWith(expect.any(File), "frog.png");
    expect(await screen.findByRole("heading", { name: "Check the picture" })).toBeInTheDocument();
    expect(await screen.findByAltText("The object cut out")).toHaveAttribute("src", "blob:cutout");
    expect(screen.getByAltText("The original, as you gave it")).toHaveAttribute(
      "src",
      "blob:picture",
    );
    const found = screen.getByRole("list", { name: "What was found" });
    expect(
      within(found).getByText("One object, in the middle, with all of it showing."),
    ).toBeInTheDocument();
  });

  it("takes a dropped picture", async () => {
    const a = api();
    render(<Model3d api={a} />);
    const zone = await screen.findByRole("region", { name: "Add a picture" });
    const { fireEvent } = await import("@testing-library/react");
    fireEvent.drop(zone, { dataTransfer: { files: [file()] } });
    await waitFor(() => expect(a.addPicture).toHaveBeenCalledWith(expect.any(File), "frog.png"));
  });

  it("says why a picture was refused and stays on the start screen", async () => {
    const user = userEvent.setup();
    const a = api({
      addPicture: vi
        .fn()
        .mockRejectedValue(
          new Error("That picture is too small. Use one at least 128 pixels wide."),
        ),
    });
    render(<Model3d api={a} />);
    await user.upload(await screen.findByLabelText("Choose a picture"), file());
    const alert = await screen.findByRole("alert");
    expect(within(alert).getByText(/too small/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Choose a picture" })).toBeInTheDocument();
  });

  it("shows the cut-out being made, then a failed one in words with a way out", async () => {
    const user = userEvent.setup();
    const a = api({
      addPicture: vi.fn().mockResolvedValue(
        picture({
          status: "checking",
          stage: "Cutting out the object",
          checks: [],
          can_go_on: false,
        }),
      ),
      picture: vi.fn().mockResolvedValue(
        picture({
          status: "failed",
          error: "The cut-out did not work.",
          checks: [],
          can_go_on: false,
        }),
      ),
    });
    render(<Model3d api={a} />);
    await user.upload(await screen.findByLabelText("Choose a picture"), file());
    expect(await screen.findByText("Cutting out the object…")).toBeInTheDocument();
    expect(screen.getByRole("progressbar", { name: "Checking the picture" })).toBeInTheDocument();
    expect(
      await screen.findByText("The cut-out did not work.", undefined, { timeout: 3000 }),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Try another picture" }));
    expect(a.removePicture).toHaveBeenCalled();
    expect(await screen.findByRole("button", { name: "Choose a picture" })).toBeInTheDocument();
  });
});

describe("checking and making", () => {
  async function toCheck(a: Model3dApi) {
    const user = userEvent.setup();
    render(<Model3d api={a} />);
    await user.upload(await screen.findByLabelText("Choose a picture"), file());
    await screen.findByRole("form", { name: "Make the model" });
    return user;
  }

  it("will not make a model until the person says they may use the picture", async () => {
    const a = api();
    const user = await toCheck(a);
    const make = screen.getByRole("button", { name: "Make the 3D model" });
    expect(make).toBeDisabled();
    await user.click(screen.getByLabelText(/I may use this picture/));
    expect(make).toBeEnabled();
    expect(screen.getByText(/about 5 to 25 minutes/)).toBeInTheDocument();
  });

  it("makes the model with the name, the detail and the statement of rights", async () => {
    const a = api();
    const user = await toCheck(a);
    await user.type(screen.getByLabelText(/Name/), "Frog mug");
    await user.click(screen.getByRole("button", { name: "Detailed" }));
    expect(screen.getByText(/The sharpest texture \(4096\)/)).toBeInTheDocument();
    await user.click(screen.getByLabelText(/I may use this picture/));
    await user.click(screen.getByRole("button", { name: "Make the 3D model" }));
    expect(a.make).toHaveBeenCalledWith({
      input_id: "p".repeat(32),
      title: "Frog mug",
      prompt: "",
      detail: "detailed",
      rights: true,
    });
    expect(await screen.findByText("Making your 3D model")).toBeInTheDocument();
    expect(screen.getByText("Building the shape")).toBeInTheDocument();
  });

  it("says each warning and still lets the person go on, but not when nothing was found", async () => {
    const warn = api({
      addPicture: vi.fn().mockResolvedValue(
        picture({
          checks: [
            {
              code: "cut_off",
              level: "warn",
              message: "The object touches the edge of the picture, so part of it may be cut off.",
            },
            { code: "tip", level: "ok", message: "tip" },
          ],
        }),
      ),
    });
    const user = await toCheck(warn);
    expect(screen.getByText(/touches the edge of the picture/)).toBeInTheDocument();
    await user.click(screen.getByLabelText(/I may use this picture/));
    expect(screen.getByRole("button", { name: "Make the 3D model" })).toBeEnabled();
  });

  it("offers only another picture when nothing was found in this one", async () => {
    const user = userEvent.setup();
    const a = api({
      addPicture: vi.fn().mockResolvedValue(
        picture({
          can_go_on: false,
          checks: [
            {
              code: "no_object",
              level: "stop",
              message:
                "No object was found in this picture. Use a picture of one object on a plain background.",
            },
          ],
        }),
      ),
    });
    render(<Model3d api={a} />);
    await user.upload(await screen.findByLabelText("Choose a picture"), file());
    expect(await screen.findByText(/No object was found in this picture/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Make the 3D model" })).toBeNull();
    await user.click(screen.getByRole("button", { name: "Use another picture" }));
    expect(await screen.findByRole("button", { name: "Choose a picture" })).toBeInTheDocument();
  });

  it("refuses to start when memory cannot hold it, and while another model is being made", async () => {
    const big = api({
      status: vi.fn().mockResolvedValue({
        ready: true,
        problem: null,
        fit: { verdict: "too_big", reason: "It needs 20 GB and 12 GB is free." },
        busy: false,
        active: null,
        details: [],
      }),
    });
    const user = await toCheck(big);
    expect(screen.getByText("Not enough memory for a 3D model")).toBeInTheDocument();
    await user.click(screen.getByLabelText(/I may use this picture/));
    expect(screen.getByRole("button", { name: "Make the 3D model" })).toBeDisabled();
  });

  it("shows the engine's refusal when a model cannot start", async () => {
    const a = api({
      make: vi
        .fn()
        .mockRejectedValue(new Error("A 3D model is already being made. Wait for it to finish.")),
    });
    const user = await toCheck(a);
    await user.click(screen.getByLabelText(/I may use this picture/));
    await user.click(screen.getByRole("button", { name: "Make the 3D model" }));
    const alert = await screen.findByRole("alert");
    expect(
      within(alert).getByText("A 3D model is already being made. Wait for it to finish."),
    ).toBeInTheDocument();
  });

  it("follows the model to the end, opens the viewer, and offers to save, rename, repeat and delete", async () => {
    const user = userEvent.setup();
    const onOpenLibrary = vi.fn();
    const a = api();
    render(<Model3d api={a} canSave onOpenLibrary={onOpenLibrary} />);
    await user.upload(await screen.findByLabelText("Choose a picture"), file());
    await user.click(await screen.findByLabelText(/I may use this picture/));
    await user.click(screen.getByRole("button", { name: "Make the 3D model" }));
    expect(
      await screen.findByText("Your 3D model is ready", undefined, { timeout: 4000 }),
    ).toBeInTheDocument();
    expect(a.fileUrl).toHaveBeenCalledWith("m".repeat(32), "file");
    await waitFor(() => expect(document.querySelector("model-viewer")).not.toBeNull());
    const viewer = document.querySelector("model-viewer");
    expect(viewer).toHaveAttribute("src", "blob:file");
    expect(viewer).toHaveAttribute("loading", "eager");
    expect(viewer).toHaveAttribute("camera-orbit", "180deg 80deg auto");
    expect(screen.getByText(/It took about 10 minutes/)).toBeInTheDocument();
    expect(screen.getByText(/not watertight/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Save a copy/ }));
    expect(a.exportCopy).toHaveBeenCalledWith("m".repeat(32), undefined);
    expect(await screen.findByText("Saved as frog-mug.glb in Downloads.")).toBeInTheDocument();
    // three actions on the stage, the rest (Delete) in its More menu (ADR-0093 U10)
    await user.click(screen.getByRole("button", { name: /Library/ }));
    expect(onOpenLibrary).toHaveBeenCalled();
    const name = screen.getByLabelText("Name");
    await user.clear(name);
    await user.type(name, "Green frog");
    await user.click(screen.getByRole("button", { name: "Rename" }));
    expect(a.rename).toHaveBeenCalledWith("m".repeat(32), "Green frog");
    await user.click(screen.getByRole("button", { name: "More" }));
    await user.click(await screen.findByRole("menuitem", { name: /Delete/ }));
    expect(a.remove).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    await user.click(screen.getByRole("button", { name: "More" }));
    await user.click(await screen.findByRole("menuitem", { name: /Delete/ }));
    await user.click(screen.getByRole("button", { name: "Delete it for good" }));
    expect(a.remove).toHaveBeenCalledWith("m".repeat(32));
  });

  it("stops a model that is being made and says it was stopped", async () => {
    const user = userEvent.setup();
    const a = api({ get: vi.fn().mockResolvedValue(model()) });
    render(<Model3d api={a} />);
    await user.upload(await screen.findByLabelText("Choose a picture"), file());
    await user.click(await screen.findByLabelText(/I may use this picture/));
    await user.click(screen.getByRole("button", { name: "Make the 3D model" }));
    await user.click(await screen.findByRole("button", { name: "Stop" }));
    expect(a.cancel).toHaveBeenCalledWith("m".repeat(32));
    expect(await screen.findByText("Stopped")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });

  it("says why a model could not be made and offers to try again", async () => {
    const user = userEvent.setup();
    const a = api({
      make: vi
        .fn()
        .mockResolvedValue(
          model({ status: "failed", error: "The 3D engine stopped with an error." }),
        ),
    });
    render(<Model3d api={a} />);
    await user.upload(await screen.findByLabelText("Choose a picture"), file());
    await user.click(await screen.findByLabelText(/I may use this picture/));
    await user.click(screen.getByRole("button", { name: "Make the 3D model" }));
    expect(await screen.findByText("The 3D model could not be made")).toBeInTheDocument();
    expect(screen.getByText("The 3D engine stopped with an error.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(a.again).toHaveBeenCalled();
  });
});

describe("coming back and the models already made", () => {
  it("picks up a model that was being made when the person left", async () => {
    const a = api({
      status: vi.fn().mockResolvedValue({
        ready: true,
        problem: null,
        fit: { verdict: "fits", reason: "" },
        busy: true,
        active: { kind: "model", id: "m".repeat(32) },
        details: [],
      }),
      get: vi.fn().mockResolvedValue(model({ progress: 0.6, stage: "Painting the surface" })),
    });
    render(<Model3d api={a} />);
    expect(await screen.findByText("Making your 3D model")).toBeInTheDocument();
    expect(screen.getByText("Painting the surface")).toBeInTheDocument();
  });

  it("lists finished models with their pictures and opens one", async () => {
    const user = userEvent.setup();
    const done = model({
      status: "done",
      progress: 1,
      glb_bytes: 5_000_000,
      elapsed_s: 300,
      live: false,
    });
    const a = api({
      list: vi.fn().mockResolvedValue([done]),
      get: vi.fn().mockResolvedValue(done),
    });
    render(<Model3d api={a} />);
    const card = await screen.findByRole("button", { name: /Frog mug/ });
    await waitFor(() => expect(card.querySelector("img")).toHaveAttribute("src", "blob:thumb"));
    await user.click(card);
    expect(a.get).toHaveBeenCalledWith("m".repeat(32));
    expect(await screen.findByText("Your 3D model is ready")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Make another" }));
    expect(await screen.findByRole("button", { name: "Choose a picture" })).toBeInTheDocument();
  });

  it("says when 3D is not ready and what to do", async () => {
    const a = api({
      status: vi.fn().mockResolvedValue({
        ready: false,
        problem: "The 3D component is not set up yet. Set it up first.",
        fit: null,
        busy: false,
        active: null,
        details: [],
      }),
    });
    render(<Model3d api={a} />);
    expect(await screen.findByText("3D is not ready")).toBeInTheDocument();
    expect(screen.getByText(/not set up yet/)).toBeInTheDocument();
  });

  it("warns that memory is tight", async () => {
    const a = api({
      status: vi.fn().mockResolvedValue({
        ready: true,
        problem: null,
        fit: { verdict: "tight", reason: "About 21 GB is free." },
        busy: false,
        active: null,
        details: [],
      }),
    });
    render(<Model3d api={a} />);
    expect(await screen.findByText("Memory is tight")).toBeInTheDocument();
  });

  it("always names the encoder's licence", async () => {
    render(<Model3d api={api()} />);
    expect(await screen.findByText(/Built with DINOv3\. Models: MIT/)).toBeInTheDocument();
  });
});

describe("from words", () => {
  function runs(urls: string[]) {
    let i = 0;
    return vi.fn().mockImplementation(async (_product, _input, _signal, onEvent) => {
      const url = urls[i++] ?? "";
      onEvent({
        event: "node",
        data: { status: "started", node: "generate_image", label: "Painting", run_id: "r", seq: 1 },
      });
      onEvent({
        event: "done",
        data: {
          run_id: "r",
          seq: 2,
          outputs: {
            image_id: `i${i}`,
            image_url: url,
            thumb_url: url,
            width: 1024,
            height: 1024,
            prompt: "x",
            mode: "text",
          },
        },
      });
    });
  }

  it("is not offered without the image engine", async () => {
    render(<Model3d api={api()} />);
    expect(await screen.findByRole("button", { name: "Words" })).toBeDisabled();
  });

  it("makes four pictures one after another, asks for the front view, and uses the one picked", async () => {
    const user = userEvent.setup();
    const startRun = runs(["http://x/1.png", "http://x/2.png", "http://x/3.png", "http://x/4.png"]);
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          new Response(new Uint8Array([1, 2, 3]), { headers: { "content-type": "image/png" } }),
        ),
    );
    const a = api();
    render(<Model3d api={a} images={{ startRun }} />);
    await user.click(await screen.findByRole("button", { name: "Words" }));
    await user.type(screen.getByLabelText("Describe the object"), "a ceramic frog mug");
    await user.click(screen.getByRole("button", { name: "Make 4 pictures" }));
    await waitFor(() =>
      expect(screen.getAllByRole("button", { name: "Use this picture" })).toHaveLength(4),
    );
    expect(startRun).toHaveBeenCalledTimes(4);
    const first = startRun.mock.calls[0];
    expect(first?.[0]).toBe("wasifyai-image");
    expect(first?.[1]).toMatchObject({ mode: "text", size: "1024x1024" });
    expect((first?.[1] as { prompt: string }).prompt).toBe(
      "a ceramic frog mug, a single object, centred, plain light background, front view at eye level, soft even light",
    );
    const seeds = startRun.mock.calls.map((c) => (c[1] as { seed: number }).seed);
    expect(new Set(seeds).size).toBe(4);
    await user.click(screen.getAllByRole("button", { name: "Use this picture" })[1] as HTMLElement);
    await waitFor(() =>
      expect(a.addPicture).toHaveBeenCalledWith(expect.anything(), "candidate-2.png"),
    );
    expect(await screen.findByRole("heading", { name: "Check the picture" })).toBeInTheDocument();
    vi.unstubAllGlobals();
  });

  it("says when a picture was refused or failed and keeps the others", async () => {
    const user = userEvent.setup();
    const startRun = vi
      .fn()
      .mockImplementationOnce(async (_p, _i, _s, onEvent) =>
        onEvent({
          event: "done",
          data: {
            run_id: "r",
            seq: 1,
            outputs: {
              status: "refused",
              refusal: { code: "x", message: "That request can't be made into an image." },
            },
          },
        }),
      )
      .mockRejectedValueOnce(new Error("The engine is busy."))
      .mockImplementation(async (_p, _i, _s, onEvent) =>
        onEvent({
          event: "done",
          data: {
            run_id: "r",
            seq: 1,
            outputs: {
              image_id: "i",
              image_url: "http://x/ok.png",
              thumb_url: "",
              width: 1,
              height: 1,
              prompt: "x",
              mode: "text",
            },
          },
        }),
      );
    render(<Model3d api={api()} images={{ startRun }} />);
    await user.click(await screen.findByRole("button", { name: "Words" }));
    await user.type(screen.getByLabelText("Describe the object"), "a thing");
    await user.click(screen.getByRole("button", { name: "Make 4 pictures" }));
    expect(
      await screen.findByText("That request can't be made into an image."),
    ).toBeInTheDocument();
    expect(await screen.findByText("The engine is busy.")).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getAllByRole("button", { name: "Use this picture" })).toHaveLength(2),
    );
  });
});
