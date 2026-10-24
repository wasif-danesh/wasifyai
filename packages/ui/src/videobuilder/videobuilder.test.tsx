// @vitest-environment jsdom
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type {
  BuilderComponent,
  BuilderProject,
  BuilderRender,
  BuilderStatus,
  FieldInfo,
  TemplateCatalogue,
  TemplateInfo,
  VideoBuilderApi,
} from "@wasifyai/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { VideoBuilder } from "./VideoBuilder";

const BYTES = 287_600_345;

function component(over: Partial<BuilderComponent> = {}): BuilderComponent {
  return {
    installed: false,
    tools: { ready: true, message: "" },
    source: null,
    plan: {
      supported: true,
      platform: "darwin-arm64",
      bytes: BYTES,
      parts: [
        {
          name: "Node.js",
          version: "22.23.1",
          bytes: 50_067_502,
          licence: "MIT",
          source: "nodejs.org",
        },
        {
          name: "Chrome headless shell",
          version: "152",
          bytes: 97_532_843,
          licence: "Chromium",
          source: "googleapis.com",
        },
        {
          name: "HyperFrames and GSAP",
          version: "0.8.171",
          bytes: 140_000_000,
          licence: "Apache-2.0",
          source: "registry.npmjs.org",
        },
      ],
      found: null,
    },
    progress: { state: "idle", step: null, message: "", done_bytes: 0, total_bytes: 0 },
    sandbox: {
      network: "A video can reach nothing outside its own folder.",
      telemetry: "Nothing is sent anywhere while it runs.",
    },
    ...over,
  };
}

const text = (id: string, label: string, over: Partial<FieldInfo> = {}): FieldInfo => ({
  id,
  kind: "text",
  label,
  required: false,
  max_chars: 80,
  min: 0,
  max: 0,
  default: "",
  choices: [],
  hint: "",
  ...over,
});
const common: FieldInfo[] = [
  text("shape", "Shape", {
    kind: "choice",
    default: "landscape",
    choices: [
      { id: "landscape", label: "Landscape" },
      { id: "portrait", label: "Portrait" },
      { id: "square", label: "Square" },
    ],
  }),
  text("seconds", "Length", { kind: "seconds", min: 3, max: 90, default: 30 }),
  text("theme", "Look", {
    kind: "choice",
    default: "midnight",
    choices: [
      { id: "midnight", label: "Midnight" },
      { id: "sunrise", label: "Sunrise" },
      { id: "forest", label: "Forest" },
      { id: "paper", label: "Paper" },
    ],
  }),
  text("font", "Letters", {
    kind: "choice",
    default: "sans",
    choices: [
      { id: "sans", label: "Sans (Inter)" },
      { id: "serif", label: "Serif (Source Serif 4)" },
    ],
  }),
];

const TEMPLATE: TemplateInfo = {
  id: "title",
  title: "Animated title",
  description: "A title and a line under it, animated in on a colour you pick.",
  fields: [
    text("title", "Title", { required: true }),
    text("subtitle", "A line under it", { max_chars: 140 }),
    ...common,
  ],
  transparent: false,
  formats: ["mp4"],
};
const CHART: TemplateInfo = {
  id: "chart",
  title: "Bar chart",
  description: "Bars that grow, from your own numbers.",
  fields: [
    text("title", "Title", { required: true }),
    text("data", "Numbers", {
      kind: "rows",
      required: true,
      max_chars: 24,
      min: 2,
      max: 8,
      hint: "One per line: a label, a comma and a number, like  Sales, 120",
    }),
    ...common,
  ],
  transparent: false,
  formats: ["mp4"],
};
const THIRD: TemplateInfo = {
  id: "lower_third",
  title: "Lower third",
  description: "A name strap for the bottom of a video. Transparent.",
  fields: [
    text("name", "Name", { required: true, max_chars: 60 }),
    text("role", "Role"),
    ...common,
  ],
  transparent: true,
  formats: ["webm", "mov", "mp4"],
};
const CATALOGUE: TemplateCatalogue = {
  templates: [TEMPLATE, CHART, THIRD],
  shapes: {
    landscape: { width: 1280, height: 720 },
    portrait: { width: 720, height: 1280 },
    square: { width: 1080, height: 1080 },
  },
  themes: {
    midnight: { from: "#0b1220", to: "#1c2b4a", ink: "#fff", accent: "#4f8cff" },
    sunrise: { from: "#2a0f2e", to: "#7a2f3b", ink: "#fff", accent: "#ffb347" },
    forest: { from: "#0d1f16", to: "#1f4d3a", ink: "#fff", accent: "#5ad19a" },
    paper: { from: "#f6f1e7", to: "#e4dccb", ink: "#111", accent: "#c2410c" },
  },
  fonts: { sans: "Inter", serif: "Source Serif 4" },
};

function project(over: Partial<BuilderProject> = {}): BuilderProject {
  return {
    id: "a".repeat(32),
    title: "Launch day",
    template: "title",
    slots: {
      title: "Launch day",
      subtitle: "Here we go",
      shape: "landscape",
      seconds: 30,
      theme: "sunrise",
      font: "sans",
    },
    created_at: "2026-10-20T10:00:00Z",
    updated_at: "2026-10-20T10:00:00Z",
    renders: [],
    formats: ["mp4"],
    preview_times: [0.6, 2.5, 4.9],
    can_undo: false,
    code: "<html>the page</html>",
    ...over,
  };
}

const OK_CHECK = {
  ok: true,
  checked: 2,
  problems: [],
  message: "Checked: exactly what you wrote.",
};

function aRender(over: Partial<BuilderRender> = {}): BuilderRender {
  return {
    id: "r1",
    composition_id: "a".repeat(32),
    status: "working",
    progress: 0,
    stage: "drawing",
    format: "mp4",
    check: null,
    error: null,
    video_id: null,
    video_url: null,
    poster_url: null,
    elapsed_s: null,
    peak_mb: null,
    blocked: 0,
    started_at: "2026-10-20T10:01:00Z",
    finished_at: null,
    ...over,
  };
}

function api(over: Partial<VideoBuilderApi> = {}): VideoBuilderApi {
  const status: BuilderStatus = {
    ready: true,
    fit: { verdict: "fits", reason: "It fits." },
    busy: false,
  };
  return {
    component: vi.fn().mockResolvedValue(component({ installed: true })),
    install: vi.fn(),
    uninstall: vi.fn(),
    status: vi.fn().mockResolvedValue(status),
    templates: vi.fn().mockResolvedValue(CATALOGUE),
    list: vi.fn().mockResolvedValue([project()]),
    get: vi.fn().mockResolvedValue(project()),
    create: vi.fn().mockImplementation(async (template, s) =>
      project({
        template,
        title: String(s.title ?? s.name),
        slots: { ...project().slots, ...s },
      }),
    ),
    update: vi
      .fn()
      .mockImplementation(async (_id, s) =>
        project({ slots: { ...project().slots, ...s }, title: String(s.title ?? "Launch day") }),
      ),
    draft: vi.fn().mockResolvedValue({
      template: "lower_third",
      fields: { name: "Maya Chen", role: "Head of Design" },
      warnings: [],
      summary: "Lower third: name “Maya Chen”, role “Head of Design”",
    }),
    undo: vi.fn().mockResolvedValue(project()),
    check: vi.fn().mockResolvedValue(OK_CHECK),
    remove: vi.fn().mockResolvedValue(undefined),
    lint: vi.fn().mockResolvedValue({ ok: true, findings: [] }),
    preview: vi.fn().mockResolvedValue("blob:preview"),
    render: vi.fn().mockResolvedValue(aRender()),
    renderStatus: vi.fn().mockResolvedValue(aRender({ progress: 0.5 })),
    cancel: vi
      .fn()
      .mockResolvedValue(aRender({ status: "cancelled", error: "The video was cancelled." })),
    ...over,
  };
}

afterEach(() => {
  localStorage.clear();
  vi.restoreAllMocks();
});

describe("setting up Motion graphics", () => {
  it("shows every part with its size and licence, and sets up with the size that was shown", async () => {
    const a = api({
      component: vi.fn().mockResolvedValue(component()),
      install: vi.fn().mockResolvedValue(
        component({
          progress: {
            state: "installing",
            step: "node",
            message: "Getting Node.js",
            done_bytes: 50_000_000,
            total_bytes: BYTES,
          },
        }),
      ),
    });
    const user = userEvent.setup();
    render(<VideoBuilder api={a} />);
    expect(
      await screen.findByRole("heading", { name: "Set up Motion graphics" }),
    ).toBeInTheDocument();
    for (const name of ["Node.js", "Chrome headless shell", "HyperFrames and GSAP"]) {
      expect(screen.getByText(name)).toBeInTheDocument();
    }
    expect(screen.getByText(/MIT · from nodejs\.org|50 MB · MIT/)).toBeInTheDocument();
    expect(
      screen.getByText(
        "A video can reach nothing outside its own folder. Nothing is sent anywhere while it runs.",
      ),
    ).toBeInTheDocument();
    expect(a.install).not.toHaveBeenCalled(); // nothing is fetched before the click
    await user.click(screen.getByRole("button", { name: "Download and set up (288 MB)" }));
    expect(a.install).toHaveBeenCalledWith(BYTES);
    expect(await screen.findByText("Getting Node.js")).toBeInTheDocument();
    expect(
      screen.getByRole("progressbar", { name: "Setup progress", hidden: true }),
    ).toBeInTheDocument();
  });

  it("says plainly when the computer is not one it was measured on", async () => {
    const c = component();
    c.plan.supported = false;
    render(<VideoBuilder api={api({ component: vi.fn().mockResolvedValue(c) })} />);
    expect(await screen.findByText(/not offered on other computers yet/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Download/ })).toBeNull();
  });

  it("reports a failed setup in the engine's words and offers it again", async () => {
    const c = component({
      progress: {
        state: "failed",
        step: "node",
        message: "A download did not match what was expected. Nothing was kept.",
        done_bytes: 0,
        total_bytes: 0,
      },
    });
    render(<VideoBuilder api={api({ component: vi.fn().mockResolvedValue(c) })} />);
    expect(await screen.findByText(/did not match what was expected/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Download and set up/ })).toBeInTheDocument();
  });

  it("follows the setup and shows the projects when it is ready", async () => {
    const installing = component({
      progress: {
        state: "installing",
        step: "node",
        message: "Getting Node.js",
        done_bytes: 10,
        total_bytes: 100,
      },
    });
    const component_ = vi
      .fn()
      .mockResolvedValueOnce(installing)
      .mockResolvedValue(
        component({
          installed: true,
          progress: {
            state: "ready",
            step: null,
            message: "Ready",
            done_bytes: 100,
            total_bytes: 100,
          },
        }),
      );
    render(<VideoBuilder api={api({ component: component_ })} />);
    expect(await screen.findByText("Getting Node.js")).toBeInTheDocument();
    expect(
      await screen.findByRole("button", { name: /Launch day/ }, { timeout: 3000 }),
    ).toBeInTheDocument();
  });
});

describe("writing and making a video", () => {
  it("lists the projects and opens one with its words, settings and code", async () => {
    const user = userEvent.setup();
    const a = api();
    render(<VideoBuilder api={a} />);
    await user.click(await screen.findByRole("button", { name: /Launch day/ }));
    expect(a.get).toHaveBeenCalledWith("a".repeat(32));
    expect(await screen.findByLabelText("Title")).toHaveValue("Launch day");
    expect(screen.getByLabelText(/A line under it/)).toHaveValue("Here we go");
    expect(screen.getByText("Animated title")).toBeInTheDocument(); // a project keeps its template
    expect(screen.getByRole("button", { name: /Sunrise/ })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: /Landscape/ })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByRole("button", { name: "30 seconds" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByText("<html>the page</html>")).toBeInTheDocument(); // the code view
  });

  it("has a way out of the form: Cancel on a new draft, Close on a saved project", async () => {
    const user = userEvent.setup();
    const a = api({ list: vi.fn().mockResolvedValue([]) });
    render(<VideoBuilder api={a} />);
    await user.click(await screen.findByRole("button", { name: "Or fill in the form yourself" }));
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(await screen.findByLabelText("Describe what to make")).toBeInTheDocument();
    expect(screen.queryByLabelText("Title")).toBeNull();
  });

  it("creates a project from a new draft and will not make one without a title", async () => {
    const user = userEvent.setup();
    const a = api({ list: vi.fn().mockResolvedValue([]) });
    render(<VideoBuilder api={a} />);
    await user.click(await screen.findByRole("button", { name: "Or fill in the form yourself" }));
    expect(screen.getByRole("button", { name: "Make the video" })).toBeDisabled();
    expect(screen.getByText("Fill in the title to go on.")).toBeInTheDocument();
    await user.type(screen.getByLabelText("Title"), "Big day");
    await user.click(screen.getByRole("button", { name: /Forest/ }));
    await user.click(screen.getByRole("button", { name: "60 seconds" }));
    await user.click(screen.getByRole("button", { name: /Portrait/ }));
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(a.create).toHaveBeenCalledWith("title", {
      title: "Big day",
      subtitle: "",
      shape: "portrait",
      seconds: 60,
      theme: "forest",
      font: "sans",
    });
  });

  it("builds the form of whatever is picked, and sends numbers as they were typed", async () => {
    const user = userEvent.setup();
    const a = api({ list: vi.fn().mockResolvedValue([]) });
    render(<VideoBuilder api={a} />);
    await user.click(await screen.findByRole("button", { name: "Or fill in the form yourself" }));
    await user.click(screen.getByRole("button", { name: "Bar chart" }));
    expect(screen.getByText(/One per line: a label, a comma and a number/)).toBeInTheDocument();
    expect(screen.queryByLabelText(/A line under it/)).toBeNull();
    await user.type(screen.getByLabelText("Title"), "Sales");
    await user.type(screen.getByLabelText("Numbers"), "North, $1,200.5{Enter}South, 45%");
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(a.create).toHaveBeenCalledWith(
      "chart",
      expect.objectContaining({ title: "Sales", data: "North, $1,200.5\nSouth, 45%" }),
    );
  });

  it("shows rows of a saved chart as the lines they were typed as", async () => {
    const user = userEvent.setup();
    const chart = project({
      template: "chart",
      title: "Sales",
      slots: {
        title: "Sales",
        data: [
          { label: "North", value: "120" },
          { label: "South", value: "$95" },
        ],
        shape: "landscape",
        seconds: 8,
        theme: "midnight",
        font: "sans",
      },
    });
    const a = api({
      list: vi.fn().mockResolvedValue([chart]),
      get: vi.fn().mockResolvedValue(chart),
    });
    render(<VideoBuilder api={a} />);
    await user.click(await screen.findByRole("button", { name: /Sales/ }));
    expect(await screen.findByLabelText("Numbers")).toHaveValue("North, 120\nSouth, $95");
    expect(screen.getByText("Bar chart · 8 seconds", { exact: false })).toBeInTheDocument();
  });

  it("offers the file kinds of a see-through template and asks for the one picked", async () => {
    const user = userEvent.setup();
    const third = project({
      template: "lower_third",
      title: "Maya Chen",
      slots: {
        name: "Maya Chen",
        role: "Head of Design",
        shape: "landscape",
        seconds: 30,
        theme: "midnight",
        font: "sans",
      },
      formats: ["webm", "mov", "mp4"],
    });
    const a = api({
      list: vi.fn().mockResolvedValue([third]),
      get: vi.fn().mockResolvedValue(third),
    });
    render(<VideoBuilder api={a} />);
    await user.click(await screen.findByRole("button", { name: /Maya Chen/ }));
    expect(await screen.findByRole("button", { name: "WebM, transparent" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    await user.click(screen.getByRole("button", { name: "MOV, transparent" }));
    await user.click(screen.getByRole("button", { name: "Make the video" }));
    expect(a.render).toHaveBeenCalledWith("a".repeat(32), "mov");
  });

  it("does not offer a choice of file for a template that makes one kind", async () => {
    const user = userEvent.setup();
    render(<VideoBuilder api={api()} />);
    await user.click(await screen.findByRole("button", { name: /Launch day/ }));
    await screen.findByLabelText("Title");
    expect(screen.queryByText("File")).toBeNull();
    expect(screen.queryByRole("button", { name: /MP4/ })).toBeNull();
  });

  it("saves changes, then shows stills of the saved words at the moments the engine named", async () => {
    const user = userEvent.setup();
    const a = api({
      preview: vi
        .fn()
        .mockResolvedValueOnce("blob:one")
        .mockResolvedValueOnce("blob:two")
        .mockResolvedValueOnce("blob:three"),
    });
    render(<VideoBuilder api={a} />);
    await user.click(await screen.findByRole("button", { name: /Launch day/ }));
    const title = await screen.findByLabelText("Title");
    await user.clear(title);
    await user.type(title, "Big day");
    await user.click(screen.getByRole("button", { name: "Preview" }));
    await waitFor(() =>
      expect(a.update).toHaveBeenCalledWith(
        "a".repeat(32),
        expect.objectContaining({ title: "Big day" }),
      ),
    );
    await waitFor(() => expect(a.preview).toHaveBeenCalledTimes(3));
    expect(vi.mocked(a.preview).mock.calls.map((c) => c[1])).toEqual([0.6, 2.5, 4.9]);
    expect(await screen.findByAltText("A still of your video at 0.6 seconds")).toHaveAttribute(
      "src",
      "blob:one",
    );
    expect(screen.getByAltText("A still of your video at 4.9 seconds")).toHaveAttribute(
      "src",
      "blob:three",
    );
  });

  it("checks the words alone and says what is wrong in the engine's words", async () => {
    const user = userEvent.setup();
    const a = api({
      check: vi
        .fn()
        .mockResolvedValueOnce(OK_CHECK)
        .mockResolvedValueOnce({
          ok: false,
          checked: 2,
          problems: [
            {
              slot: "name",
              code: "text_mismatch",
              message: "The screen says “Maya Chan” but you wrote “Maya Chen”.",
            },
          ],
          message: "x",
        }),
    });
    render(<VideoBuilder api={a} />);
    await user.click(await screen.findByRole("button", { name: /Launch day/ }));
    await user.click(await screen.findByRole("button", { name: "Check the words" }));
    expect(await screen.findByText("The words are right")).toBeInTheDocument();
    expect(screen.getByText(/Checked: exactly what you wrote/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Check the words" }));
    expect(await screen.findByText("The words on the screen are not right")).toBeInTheDocument();
    expect(
      screen.getByText(/The screen says “Maya Chan” but you wrote “Maya Chen”/),
    ).toBeInTheDocument();
  });

  it("brings back the words before the last change", async () => {
    const user = userEvent.setup();
    const changed = project({
      can_undo: true,
      title: "Big day",
      slots: { ...project().slots, title: "Big day" },
    });
    const a = api({
      get: vi.fn().mockResolvedValue(changed),
      draft: vi.fn().mockResolvedValue({
        template: "lower_third",
        fields: { name: "Maya Chen", role: "Head of Design" },
        warnings: [],
        summary: "Lower third: name “Maya Chen”, role “Head of Design”",
      }),
      undo: vi.fn().mockResolvedValue(project()),
    });
    render(<VideoBuilder api={a} />);
    await user.click(await screen.findByRole("button", { name: /Big day|Launch day/ }));
    expect(await screen.findByLabelText("Title")).toHaveValue("Big day");
    await user.click(screen.getByRole("button", { name: "Undo the last change" }));
    expect(a.undo).toHaveBeenCalledWith("a".repeat(32));
    await waitFor(() => expect(screen.getByLabelText("Title")).toHaveValue("Launch day"));
    expect(screen.queryByRole("button", { name: "Undo the last change" })).toBeNull();
  });

  it("does not offer Undo when there is nothing to undo", async () => {
    const user = userEvent.setup();
    render(<VideoBuilder api={api()} />);
    await user.click(await screen.findByRole("button", { name: /Launch day/ }));
    await screen.findByLabelText("Title");
    expect(screen.queryByRole("button", { name: "Undo the last change" })).toBeNull();
  });

  it("makes the video, shows the progress, then the player and a way to keep it", async () => {
    const user = userEvent.setup();
    const done = aRender({
      status: "done",
      progress: 1,
      video_id: "v1",
      video_url: "http://127.0.0.1:1/v.mp4",
      poster_url: "http://127.0.0.1:1/p.jpg",
      elapsed_s: 3.4,
      blocked: 2,
      check: OK_CHECK,
    });
    const a = api({
      renderStatus: vi
        .fn()
        .mockResolvedValueOnce(aRender({ progress: 0.5 }))
        .mockResolvedValue(done),
    });
    const videos = {
      exportCopy: vi
        .fn()
        .mockResolvedValue({ name: "launch-day.mp4", path: "/Downloads/launch-day.mp4" }),
    };
    const onOpenLibrary = vi.fn();
    render(<VideoBuilder api={a} videos={videos} canSave onOpenLibrary={onOpenLibrary} />);
    await user.click(await screen.findByRole("button", { name: /Launch day/ }));
    await user.click(await screen.findByRole("button", { name: "Make the video" }));
    expect(a.render).toHaveBeenCalledWith("a".repeat(32), "mp4");
    expect(await screen.findByText("Making your video")).toBeInTheDocument();
    expect(await screen.findByText("50%", undefined, { timeout: 3000 })).toBeInTheDocument();
    expect(
      await screen.findByText("Your video is ready", undefined, { timeout: 3000 }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/tried to reach outside its folder 2 times; every try was refused/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Every word on the screen was checked against what you typed/),
    ).toBeInTheDocument();
    expect(document.querySelector("video")).toHaveAttribute("src", "http://127.0.0.1:1/v.mp4");
    await user.click(screen.getByRole("button", { name: /Save a copy/ }));
    expect(videos.exportCopy).toHaveBeenCalledWith("v1", undefined);
    expect(await screen.findByText("Saved as launch-day.mp4 in Downloads.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Your videos/ }));
    expect(onOpenLibrary).toHaveBeenCalled();
  });

  it("stops a video that is being made and says it was stopped", async () => {
    const user = userEvent.setup();
    const a = api();
    render(<VideoBuilder api={a} />);
    await user.click(await screen.findByRole("button", { name: /Launch day/ }));
    await user.click(await screen.findByRole("button", { name: "Make the video" }));
    await user.click(await screen.findByRole("button", { name: /Cancel/ }));
    expect(a.cancel).toHaveBeenCalled();
    expect(await screen.findByText("Stopped")).toBeInTheDocument();
    expect(screen.getByText("The video was cancelled.")).toBeInTheDocument();
  });

  it("says that the words are checked first, then drawn", async () => {
    const user = userEvent.setup();
    const a = api({
      render: vi.fn().mockResolvedValue(aRender({ stage: "checking" })),
      renderStatus: vi.fn().mockResolvedValue(aRender({ stage: "checking" })),
    });
    render(<VideoBuilder api={a} />);
    await user.click(await screen.findByRole("button", { name: /Launch day/ }));
    await user.click(await screen.findByRole("button", { name: "Make the video" }));
    expect(await screen.findByText("Checking the words")).toBeInTheDocument();
  });

  it("shows the words that did not pass when the check stopped a video", async () => {
    const user = userEvent.setup();
    const a = api({
      render: vi.fn().mockResolvedValue(
        aRender({
          status: "failed",
          error: "The words on the screen are not exactly what you wrote: x",
          check: {
            ok: false,
            checked: 2,
            problems: [
              { slot: "name", code: "clipped", message: "Part of “Maya Chen” is cut off." },
            ],
            message: "x",
          },
        }),
      ),
    });
    render(<VideoBuilder api={a} />);
    await user.click(await screen.findByRole("button", { name: /Launch day/ }));
    await user.click(await screen.findByRole("button", { name: "Make the video" }));
    expect(await screen.findByText("The video could not be made")).toBeInTheDocument();
    expect(screen.getByText("Part of “Maya Chen” is cut off.")).toBeInTheDocument();
  });

  it("says why a video could not be made", async () => {
    const user = userEvent.setup();
    const a = api({
      render: vi.fn().mockResolvedValue(
        aRender({
          status: "failed",
          error: "The video was stopped because it asked for too much memory.",
        }),
      ),
    });
    render(<VideoBuilder api={a} />);
    await user.click(await screen.findByRole("button", { name: /Launch day/ }));
    await user.click(await screen.findByRole("button", { name: "Make the video" }));
    expect(await screen.findByText("The video could not be made")).toBeInTheDocument();
    expect(screen.getByText(/asked for too much memory/)).toBeInTheDocument();
  });

  it("asks before deleting and deletes the project with its videos", async () => {
    const user = userEvent.setup();
    const a = api();
    render(<VideoBuilder api={a} />);
    await user.click(await screen.findByRole("button", { name: /Launch day/ }));
    await user.click(await screen.findByRole("button", { name: /Delete/ }));
    expect(a.remove).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Keep it" }));
    expect(a.remove).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: /Delete/ }));
    await user.click(screen.getByRole("button", { name: "Delete it and its videos" }));
    expect(a.remove).toHaveBeenCalledWith("a".repeat(32));
  });

  it("warns about tight memory and refuses a video that cannot fit", async () => {
    const tight = api({
      status: vi.fn().mockResolvedValue({
        ready: true,
        fit: { verdict: "tight", reason: "About 2 GB is free." },
        busy: false,
      }),
    });
    const user = userEvent.setup();
    const { unmount } = render(<VideoBuilder api={tight} />);
    await user.click(await screen.findByRole("button", { name: /Launch day/ }));
    expect(await screen.findByText("Memory is tight")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Make the video" })).toBeEnabled();
    unmount();
    const big = api({
      status: vi.fn().mockResolvedValue({
        ready: true,
        fit: { verdict: "too_big", reason: "It needs 3 GB and 1 GB is free." },
        busy: false,
      }),
    });
    render(<VideoBuilder api={big} />);
    await user.click(await screen.findByRole("button", { name: /Launch day/ }));
    expect(await screen.findByText("Not enough memory for a video")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Make the video" })).toBeDisabled();
  });

  it("shows the engine's refusal when a video cannot start", async () => {
    const user = userEvent.setup();
    const a = api({
      render: vi
        .fn()
        .mockRejectedValue(new Error("A video is already being made. Wait for it to finish.")),
    });
    render(<VideoBuilder api={a} />);
    await user.click(await screen.findByRole("button", { name: /Launch day/ }));
    await user.click(await screen.findByRole("button", { name: "Make the video" }));
    const alert = await screen.findByRole("alert");
    expect(
      within(alert).getByText("A video is already being made. Wait for it to finish."),
    ).toBeInTheDocument();
  });
});

describe("FFmpeg, which a video needs", () => {
  it("says what to install and offers to look again, while the form still works", async () => {
    const user = userEvent.setup();
    const missing = component({
      installed: true,
      tools: {
        ready: false,
        message:
          "Motion graphics also needs FFmpeg (with ffprobe). In Terminal run: brew install ffmpeg.",
      },
    });
    const a = api({
      component: vi
        .fn()
        .mockResolvedValueOnce(missing)
        .mockResolvedValue(component({ installed: true })),
    });
    render(<VideoBuilder api={a} />);
    expect(await screen.findByText("One more thing is needed to make videos")).toBeInTheDocument();
    expect(screen.getByText(/brew install ffmpeg/)).toBeInTheDocument();
    expect(screen.getByLabelText("Describe what to make")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Check again" }));
    await waitFor(() =>
      expect(screen.queryByText("One more thing is needed to make videos")).toBeNull(),
    );
  });

  it("says nothing when it is there", async () => {
    render(<VideoBuilder api={api()} />);
    await screen.findByLabelText("Describe what to make");
    expect(screen.queryByText("One more thing is needed to make videos")).toBeNull();
  });
});

describe("saying what to make in your own words", () => {
  const ask = 'Lower third for "Maya Chen", Head of Design';

  it("opens on a prompt box and fills the form from what was said, making nothing", async () => {
    const user = userEvent.setup();
    const a = api({ list: vi.fn().mockResolvedValue([]) });
    render(<VideoBuilder api={a} />);
    expect(await screen.findByText("What should we make?")).toBeInTheDocument();
    await user.type(screen.getByLabelText("Describe what to make"), ask);
    await user.click(screen.getByRole("button", { name: "Fill in the form" }));
    expect(a.draft).toHaveBeenCalledWith({ prompt: ask, attachment: undefined, shape: undefined });
    expect(await screen.findByLabelText("Name")).toHaveValue("Maya Chen");
    expect(screen.getByLabelText(/Role/)).toHaveValue("Head of Design");
    expect(screen.getByText("Here is what was understood")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Lower third" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(a.create).not.toHaveBeenCalled();
    expect(a.render).not.toHaveBeenCalled();
  });

  it("sends with Enter, keeps a new line for Shift+Enter and ignores an empty box", async () => {
    const user = userEvent.setup();
    const a = api({ list: vi.fn().mockResolvedValue([]) });
    render(<VideoBuilder api={a} />);
    const box = await screen.findByLabelText("Describe what to make");
    await user.type(box, "{Enter}");
    expect(a.draft).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Fill in the form" })).toBeDisabled();
    await user.type(box, "A title{Shift>}{Enter}{/Shift}more");
    expect(box).toHaveValue("A title\nmore");
    await user.type(box, "{Enter}");
    expect(a.draft).toHaveBeenCalledWith(expect.objectContaining({ prompt: "A title\nmore" }));
  });

  it("fills the box from an example and sends the shape that was picked", async () => {
    const user = userEvent.setup();
    const a = api({ list: vi.fn().mockResolvedValue([]) });
    render(<VideoBuilder api={a} />);
    await user.click(await screen.findByRole("button", { name: "Lower third" }));
    expect(screen.getByLabelText("Describe what to make")).toHaveValue(ask);
    await user.click(screen.getByRole("button", { name: "9:16" }));
    expect(screen.getByRole("button", { name: "9:16" })).toHaveAttribute("aria-pressed", "true");
    await user.click(screen.getByRole("button", { name: "Fill in the form" }));
    expect(a.draft).toHaveBeenCalledWith({ prompt: ask, attachment: undefined, shape: "portrait" });
  });

  it("reads a CSV file here and sends its text, so the rows are never retyped", async () => {
    const user = userEvent.setup();
    const a = api({ list: vi.fn().mockResolvedValue([]) });
    render(<VideoBuilder api={a} />);
    const file = new File(["Region,Sales\nNorth,$120\nSouth,95"], "sales.csv", {
      type: "text/csv",
    });
    await user.upload(await screen.findByLabelText("Choose a CSV file"), file);
    expect(await screen.findByText("sales.csv")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Fill in the form" })); // a file is enough
    expect(a.draft).toHaveBeenCalledWith({
      prompt: "",
      attachment: { name: "sales.csv", text: "Region,Sales\nNorth,$120\nSouth,95" },
      shape: undefined,
    });
  });

  it("removes an attached file, and refuses one that is too big", async () => {
    const user = userEvent.setup();
    render(<VideoBuilder api={api({ list: vi.fn().mockResolvedValue([]) })} />);
    const input = await screen.findByLabelText("Choose a CSV file");
    await user.upload(input, new File(["a,1\nb,2"], "a.csv", { type: "text/csv" }));
    await user.click(await screen.findByRole("button", { name: "Remove a.csv" }));
    expect(screen.queryByText("a.csv")).toBeNull();
    await user.upload(input, new File(["x".repeat(41_000)], "big.csv", { type: "text/csv" }));
    expect(await screen.findByText(/too big for a chart/)).toBeInTheDocument();
    expect(screen.queryByText("big.csv")).toBeNull();
  });

  it("shows what to check when the model changed a quoted word", async () => {
    const user = userEvent.setup();
    const a = api({
      list: vi.fn().mockResolvedValue([]),
      draft: vi.fn().mockResolvedValue({
        template: "lower_third",
        fields: { name: "Maya Chan" },
        warnings: [
          "“Maya Chen” is not in the form exactly as you wrote it. Check the words before you go on.",
        ],
        summary: "Lower third: name “Maya Chan”",
      }),
    });
    render(<VideoBuilder api={a} />);
    await user.type(await screen.findByLabelText("Describe what to make"), `${ask}{Enter}`);
    expect(await screen.findByText("Check these before you go on")).toBeInTheDocument();
    expect(
      screen.getByText(/“Maya Chen” is not in the form exactly as you wrote it/),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Name")).toHaveValue("Maya Chan"); // still there to correct
  });

  it("says why a request could not be read and keeps the form one click away", async () => {
    const user = userEvent.setup();
    const a = api({
      list: vi.fn().mockResolvedValue([]),
      draft: vi.fn().mockRejectedValue(new Error("Choose a language model first.")),
    });
    render(<VideoBuilder api={a} />);
    await user.type(await screen.findByLabelText("Describe what to make"), "A title{Enter}");
    const alert = await screen.findByRole("alert");
    expect(within(alert).getByText("Choose a language model first.")).toBeInTheDocument();
    expect(screen.getByLabelText("Describe what to make")).toHaveValue("A title");
    await user.click(screen.getByRole("button", { name: "Or fill in the form yourself" }));
    expect(await screen.findByLabelText("Title")).toBeInTheDocument();
  });

  it("offers 30, 60 and 90 seconds and any other length typed in", async () => {
    const user = userEvent.setup();
    const a = api({ list: vi.fn().mockResolvedValue([]) });
    render(<VideoBuilder api={a} />);
    await user.click(await screen.findByRole("button", { name: "Or fill in the form yourself" }));
    expect(screen.getByRole("button", { name: "30 seconds" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    for (const n of [60, 90]) {
      expect(screen.getByRole("button", { name: `${n} seconds` })).toBeInTheDocument();
    }
    expect(screen.queryByRole("button", { name: "5 seconds" })).toBeNull();
    await user.click(screen.getByRole("button", { name: "90 seconds" }));
    expect(screen.getByLabelText("Length in seconds")).toHaveValue(90);
    await user.clear(screen.getByLabelText("Length in seconds"));
    await user.type(screen.getByLabelText("Length in seconds"), "45");
    await user.type(screen.getByLabelText("Title"), "Hi");
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(a.create).toHaveBeenCalledWith("title", expect.objectContaining({ seconds: 45 }));
  });
});
