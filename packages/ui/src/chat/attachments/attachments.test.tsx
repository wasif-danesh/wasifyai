// @vitest-environment jsdom
// Attaching files in the chat box (ADR-0083, stage CO2): the picker, drops and pastes, what the person sees while a file goes up,
// what the run is told, and what the sent message shows — on both chat screens.
import { act, fireEvent, render, renderHook, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type {
  AssistantApi,
  ChatOptions,
  Conversation,
  ImagesApi,
  OnEvent,
  ParsedEvent,
  UploadedAttachment,
} from "@wasifyai/client";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AssistantHome } from "../AssistantHome";
import { ChatScreen } from "../ChatScreen";
import { ChatScreenNext } from "../ChatScreenNext";
import { type AttachControl, MAX_ATTACHMENTS, useAttachments } from "./use-attachments";

const images = { get: async () => ({}) } as unknown as ImagesApi;
const ev = (event: string, data: Record<string, unknown> = {}): ParsedEvent =>
  ({ event, data: { run_id: "r1", seq: 1, ...data } }) as unknown as ParsedEvent;
const DONE = ev("done", { outputs: { status: "done", conversation_id: "c1", title: "T" } });

const png = (name = "fox.png") =>
  new File([new Uint8Array([137, 80, 78, 71])], name, { type: "image/png" });
const doc = (name = "plan.md") => new File(["# Plan"], name, { type: "text/markdown" });

function control(over: Partial<AttachControl> = {}): AttachControl {
  let n = 0;
  return {
    images: true,
    documents: true,
    imagesNote: "",
    upload: vi.fn(async (file: Blob, name: string): Promise<UploadedAttachment> => {
      n += 1;
      const picture = file.type.startsWith("image/");
      return picture
        ? { id: `id${n}`, kind: "image", name, width: 10, height: 10 }
        : { id: `id${n}`, kind: "document", name, chars: 1200, pages: 3 };
    }),
    discard: vi.fn(async () => {}),
    ...over,
  };
}

beforeEach(() => {
  localStorage.clear();
  URL.createObjectURL = vi.fn(() => "blob:preview");
  URL.revokeObjectURL = vi.fn();
});

describe("useAttachments", () => {
  it("has no Attach option where the engine cannot keep files", () => {
    const { result } = renderHook(() => useAttachments(undefined));
    expect(result.current.option).toBeNull();
    expect(result.current.runInput).toEqual({});
  });

  it("shows a file as uploading, then ready, and names the ready ones in the run input", async () => {
    const c = control();
    const { result } = renderHook(() => useAttachments(c));
    act(() => result.current.add([png(), doc()]));
    expect(result.current.busy).toBe(true);
    expect(result.current.runInput).toEqual({});
    await waitFor(() => expect(result.current.busy).toBe(false));
    expect(result.current.runInput).toEqual({
      attachments: [
        { id: "id1", name: "fox.png" },
        { id: "id2", name: "plan.md" },
      ],
    });
    expect(result.current.files.map((f) => f.kind)).toEqual(["image", "document"]);
    expect(result.current.files[0]?.url).toBe("blob:preview");
  });

  it("takes a file back: the engine is told and the preview is let go", async () => {
    const c = control();
    const { result, rerender } = renderHook(() => useAttachments(c));
    act(() => result.current.add([png()]));
    await waitFor(() => expect(result.current.count).toBe(1));
    rerender();
    render(<div>{result.current.chips}</div>);
    await userEvent.click(screen.getByRole("button", { name: "Remove fox.png" }));
    expect(c.discard).toHaveBeenCalledWith("id1");
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:preview");
  });

  it("refuses a picture for a model that cannot read pictures, in the engine's words, without uploading", () => {
    const c = control({ images: false, imagesNote: "This model has no picture reader." });
    const { result } = renderHook(() => useAttachments(c));
    act(() => result.current.add([png()]));
    expect(c.upload).not.toHaveBeenCalled();
    render(<div>{result.current.chips}</div>);
    expect(screen.getByText("This model has no picture reader.")).toBeInTheDocument();
    expect(result.current.runInput).toEqual({});
  });

  it("says what went wrong when the engine refuses a file", async () => {
    const c = control({
      upload: vi.fn(async () => {
        throw new Error("This kind of file cannot be added.");
      }),
    });
    const { result } = renderHook(() => useAttachments(c));
    act(() => result.current.add([doc("virus.exe")]));
    await waitFor(() => expect(result.current.busy).toBe(false));
    render(<div>{result.current.chips}</div>);
    expect(screen.getByText("This kind of file cannot be added.")).toBeInTheDocument();
    expect(result.current.runInput).toEqual({}); // a failed file is never sent along
  });

  it(`takes at most ${MAX_ATTACHMENTS} files and says so`, async () => {
    const c = control();
    const { result } = renderHook(() => useAttachments(c));
    act(() => result.current.add(Array.from({ length: 6 }, (_, i) => doc(`f${i}.md`))));
    await waitFor(() => expect(result.current.busy).toBe(false));
    expect(c.upload).toHaveBeenCalledTimes(MAX_ATTACHMENTS);
    render(<div>{result.current.chips}</div>);
    expect(screen.getAllByText(/At most 4 files/)).toHaveLength(2);
  });

  it("lets go of everything after the message was sent", async () => {
    const c = control();
    const { result } = renderHook(() => useAttachments(c));
    act(() => result.current.add([png()]));
    await waitFor(() => expect(result.current.count).toBe(1));
    act(() => result.current.clear());
    expect(result.current.count).toBe(0);
    expect(c.discard).not.toHaveBeenCalled(); // the message owns it now: nothing is deleted
  });

  it("attaches a pasted file and leaves pasted words alone", async () => {
    const c = control();
    const { result } = renderHook(() => useAttachments(c));
    const words = { clipboardData: { files: [] }, preventDefault: vi.fn() } as never;
    result.current.onPaste?.(words);
    expect(c.upload).not.toHaveBeenCalled();
    const shot = { clipboardData: { files: [png("shot.png")] }, preventDefault: vi.fn() } as never;
    act(() => result.current.onPaste?.(shot));
    expect(c.upload).toHaveBeenCalledTimes(1);
  });
});

function assistantWith(attach: ChatOptions["attach"]): AssistantApi {
  let n = 0;
  return {
    options: async () => ({ thinking: false, attach }),
    searchStatus: async () => {
      throw new Error("unused");
    },
    updateSearch: async () => {
      throw new Error("unused");
    },
    setHead: async () => {},
    attach: vi.fn(async (file: Blob, name: string): Promise<UploadedAttachment> => {
      n += 1;
      return file.type.startsWith("image/")
        ? { id: `p${n}`, kind: "image", name, width: 4, height: 4 }
        : { id: `d${n}`, kind: "document", name, chars: 900, pages: 2 };
    }),
    unattach: vi.fn(async () => {}),
    list: async () => [],
    get: async () => {
      throw new Error("unused");
    },
    rename: async () => {
      throw new Error("unused");
    },
    remove: async () => {},
  };
}

const OFFER = { available: true, images: true, documents: true, images_note: "" };

function runsRecording(inputs: object[]) {
  return {
    startRun: vi.fn(async (_p: string, input: object, _s: AbortSignal, on: OnEvent) => {
      inputs.push(input);
      on(ev("token", { text: "I see it." }));
      on(DONE);
    }),
    watchRun: vi.fn(async () => {}),
  };
}

describe.each([
  ["the usual chat", "classic"],
  ["the new chat", "next"],
] as const)("%s", (_name, screenKind) => {
  const home = (assistant: AssistantApi, inputs: object[] = []) =>
    render(
      <AssistantHome
        runs={runsRecording(inputs)}
        assistant={assistant}
        images={images}
        conversationId={null}
        onAdopt={() => {}}
        onNewChat={() => {}}
        screen={screenKind}
      />,
    );

  it("has no Attach button when the engine cannot keep files", async () => {
    home(assistantWith({ available: false, images: false, documents: false, images_note: "" }));
    await screen.findByRole("heading", { level: 1 });
    await new Promise((r) => setTimeout(r, 30));
    expect(screen.queryByRole("button", { name: /^Attach/ })).toBeNull();
  });

  it("attaches a picture and a document, shows them in the box, and sends their ids with the words", async () => {
    const inputs: object[] = [];
    const assistant = assistantWith(OFFER);
    const user = userEvent.setup();
    home(assistant, inputs);
    await screen.findByRole("button", { name: /^Attach/ });
    await user.upload(screen.getByLabelText("Choose files to attach"), [png(), doc()]);
    expect(await screen.findByAltText("fox.png")).toBeInTheDocument();
    expect(await screen.findByText("2 pages")).toBeInTheDocument();
    expect(assistant.attach).toHaveBeenCalledTimes(2);

    await user.type(screen.getByRole("textbox", { name: "Message" }), "what is this?{Enter}");
    await waitFor(() => expect(inputs).toHaveLength(1));
    expect(inputs[0]).toMatchObject({
      text: "what is this?",
      attachments: [
        { id: "p1", name: "fox.png" },
        { id: "d2", name: "plan.md" },
      ],
    });
    // the message shows what was attached, and the box let go of it
    expect(await screen.findByText("I see it.")).toBeInTheDocument();
    expect(screen.getAllByAltText("fox.png")).toHaveLength(1);
    expect(screen.getAllByText("plan.md")).toHaveLength(1);
    expect(screen.queryByRole("button", { name: "Remove fox.png" })).toBeNull();
    // the next message goes with nothing attached
    await user.type(screen.getByRole("textbox", { name: "Message" }), "and again{Enter}");
    await waitFor(() => expect(inputs).toHaveLength(2));
    expect(inputs[1]).not.toHaveProperty("attachments");
  });

  it("does not send while a file is still going up", async () => {
    const inputs: object[] = [];
    const assistant = assistantWith(OFFER);
    let release: (v: UploadedAttachment) => void = () => {};
    assistant.attach = vi.fn(
      () =>
        new Promise<UploadedAttachment>((r) => {
          release = r;
        }),
    );
    const user = userEvent.setup();
    home(assistant, inputs);
    await screen.findByRole("button", { name: /^Attach/ });
    await user.upload(screen.getByLabelText("Choose files to attach"), [doc()]);
    await user.type(screen.getByRole("textbox", { name: "Message" }), "read it{Enter}");
    expect(inputs).toHaveLength(0);
    act(() => release({ id: "d1", kind: "document", name: "plan.md", chars: 10 }));
    await waitFor(() => expect(screen.queryByText("Reading")).toBeNull());
    await user.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(inputs).toHaveLength(1));
  });

  it("takes a dropped file", async () => {
    const assistant = assistantWith(OFFER);
    home(assistant);
    const box = (await screen.findByRole("textbox", { name: "Message" })).closest(
      "form",
    ) as HTMLElement;
    fireEvent.drop(box, { dataTransfer: { files: [doc("dropped.md")], types: ["Files"] } });
    expect(await screen.findByText("dropped.md")).toBeInTheDocument();
    expect(assistant.attach).toHaveBeenCalledTimes(1);
  });

  it("says in words why a picture is refused for a model without a picture reader", async () => {
    const assistant = assistantWith({
      available: true,
      images: false,
      documents: true,
      images_note: "No picture reader was found for this model.",
    });
    const user = userEvent.setup();
    home(assistant);
    await screen.findByRole("button", { name: /^Attach/ });
    await user.upload(screen.getByLabelText("Choose files to attach"), [png()]);
    expect(
      await screen.findByText("No picture reader was found for this model."),
    ).toBeInTheDocument();
    expect(assistant.attach).not.toHaveBeenCalled();
  });
});

describe("a saved message with attachments", () => {
  const saved: Conversation = {
    id: "c9",
    title: "Saved",
    created_at: "",
    updated_at: "",
    head_id: "a",
    messages: [
      {
        id: "u",
        seq: 1,
        role: "user",
        created_at: "",
        parent_id: null,
        parts: [
          { type: "text", text: "What is in these?" },
          {
            type: "attachment",
            kind: "image",
            id: "p1",
            name: "fox.png",
            url: "https://files.test/fox.png",
          },
          { type: "attachment", kind: "document", id: "d1", name: "plan.md" },
        ],
      },
      {
        id: "a",
        seq: 2,
        role: "assistant",
        created_at: "",
        parent_id: "u",
        parts: [{ type: "text", text: "A fox and a plan." }],
      },
    ],
  };

  it.each([
    ["the usual chat", ChatScreen],
    ["the new chat", ChatScreenNext],
  ] as const)(
    "is shown on %s: a picture from its link, a document by name, the words as text",
    async (_n, Screen) => {
      const assistant = { ...assistantWith(OFFER), get: async () => saved };
      render(
        <Screen
          runs={runsRecording([])}
          assistant={assistant}
          images={images}
          conversationId="c9"
        />,
      );
      expect(await screen.findByText("A fox and a plan.")).toBeInTheDocument();
      const picture = screen.getByAltText("fox.png");
      expect(picture).toHaveAttribute("src", "https://files.test/fox.png");
      expect(screen.getByText("plan.md")).toBeInTheDocument();
      expect(screen.getByText("What is in these?")).toBeInTheDocument();
    },
  );
});
