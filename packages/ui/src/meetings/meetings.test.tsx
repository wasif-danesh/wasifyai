// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type {
  Meeting,
  MeetingQuestion,
  MeetingReport,
  MeetingsApi,
  MeetingsStatus,
} from "@wasifyai/client";
import { beforeAll, describe, expect, it, vi } from "vitest";
import { Meetings } from "./Meetings";

beforeAll(() => {
  // Radix's list box asks for these, which jsdom does not have
  Element.prototype.scrollIntoView ??= () => undefined;
  Element.prototype.hasPointerCapture ??= () => false;
  Element.prototype.releasePointerCapture ??= () => undefined;
});

const parakeet = { id: "parakeet", title: "Parakeet", languages: ["en", "de", "fr"] };
const indic = { id: "indic", title: "IndicConformer", languages: ["bn", "hi"] };

const status = (over: Partial<MeetingsStatus> = {}): MeetingsStatus => ({
  speaker_model: true,
  speaker_model_id: "sortformer-4spk-v2.1",
  speech: true,
  speech_model: { id: parakeet.id, title: parakeet.title },
  speech_problem: null,
  speech_models: [parakeet, indic],
  busy: false,
  active: null,
  converter: true,
  formats: [".wav", ".m4a"],
  recordings: [],
  voiceprint_model: true,
  voiceprint_model_id: "eres2net-voxceleb",
  ...over,
});

const meeting = (over: Partial<Meeting> = {}): Meeting => ({
  id: "0b7c1f9e000040008000000000000000",
  title: "Budget call",
  source_name: "budget.m4a",
  source: "file",
  status: "done",
  stage: "",
  progress: 1,
  error: null,
  language: "",
  model_id: "parakeet",
  seconds: 12,
  speakers: [
    { key: "S1", default: "Speaker 1", name: "Speaker 1", seconds: 7 },
    { key: "S2", default: "Speaker 2", name: "Speaker 2", seconds: 4 },
  ],
  text: "Good morning",
  elapsed_s: 1,
  created_at: "2026-11-16T10:00:00Z",
  finished_at: "2026-11-16T10:00:01Z",
  live: false,
  lines: [
    { start: 0.3, end: 4.5, speaker: "S1", text: "Good morning, shall we start?" },
    { start: 5.2, end: 8.6, speaker: "S2", text: "Yes, the budget first." },
  ],
  timings: {},
  reports: [],
  notebooks: [],
  questions: [],
  ...over,
});

const api = (over: Partial<MeetingsApi> = {}): MeetingsApi => ({
  status: vi.fn(async () => status()),
  list: vi.fn(async () => []),
  get: vi.fn(async () => meeting()),
  fromFile: vi.fn(async () => meeting({ status: "working", stage: "Reading the recording" })),
  fromRecording: vi.fn(async () => meeting({ status: "working", source: "recorded" })),
  discardRecording: vi.fn(async () => undefined),
  rename: vi.fn(async (_id, title) => meeting({ title })),
  nameSpeaker: vi.fn(async (_id, key, name) =>
    meeting({
      speakers: meeting().speakers.map((s) => (s.key === key ? { ...s, name } : s)),
    }),
  ),
  stop: vi.fn(async () => meeting({ status: "cancelled" })),
  remove: vi.fn(async () => undefined),
  audioUrl: vi.fn(async () => "http://127.0.0.1:9/files/t/wasifyai-meetings/u/m/audio.wav?e=1&s=x"),
  exportText: vi.fn(async () => new Blob(["text"])),
  notThisPerson: vi.fn(async () => meeting()),
  people: vi.fn(async () => [
    { id: "p1", name: "Asha", created_at: "", meetings: 2, voices: 2, last_named: null },
  ]),
  renamePerson: vi.fn(async (id, name) => ({
    id,
    name,
    created_at: "",
    meetings: 2,
    voices: 2,
    last_named: null,
  })),
  forgetPerson: vi.fn(async () => undefined),
  templates: vi.fn(async () => [
    { id: "summary", title: "Summary", instructions: "A summary.", own: false },
    { id: "actions", title: "Action items", instructions: "Tasks.", own: false },
  ]),
  addTemplate: vi.fn(async (title, instructions) => ({
    id: "own-1",
    title,
    instructions,
    own: true,
  })),
  deleteTemplate: vi.fn(async () => undefined),
  writeReport: vi.fn(async () => report({ status: "working", stage: "Writing", text: "" })),
  report: vi.fn(async () => report()),
  stopReport: vi.fn(async () => report({ status: "cancelled" })),
  deleteReport: vi.fn(async () => undefined),
  exportReport: vi.fn(async () => new Blob(["# Summary"])),
  notebooks: vi.fn(async () => [{ id: "nb-acme", title: "Acme" }]),
  addToNotebook: vi.fn(async (_id, to) => ({
    notebook_id: to.notebookId ?? "nb-new",
    notebook_title: to.title ?? "Acme",
    document_id: "d1",
  })),
  ask: vi.fn(async (_id, q) => question({ question: q, status: "working", reply: "" })),
  question: vi.fn(async () => question()),
  stopQuestion: vi.fn(async () => question({ status: "cancelled" })),
  deleteQuestion: vi.fn(async () => undefined),
  ...over,
});

const question = (over: Partial<MeetingQuestion> = {}): MeetingQuestion => ({
  id: "q1",
  meeting_id: "0b7c1f9e000040008000000000000000",
  question: "What was agreed?",
  status: "done",
  stage: "",
  error: null,
  reply: "The budget was agreed [1].",
  citations: [{ n: 1, text: "Speaker 2: Yes, the budget first." }],
  notebook_id: "nb-acme",
  conversation_id: "c1",
  created_at: "2026-11-16T10:02:00Z",
  finished_at: "2026-11-16T10:02:05Z",
  ...over,
});

const report = (over: Partial<MeetingReport> = {}): MeetingReport => ({
  id: "r1",
  meeting_id: "0b7c1f9e000040008000000000000000",
  template: "summary",
  title: "Summary",
  status: "done",
  stage: "",
  progress: 1,
  error: null,
  text: "# Summary\n\n- The budget was agreed.",
  created_at: "2026-11-16T10:01:00Z",
  finished_at: "2026-11-16T10:01:09Z",
  ...over,
});

const file = () => new File([new Uint8Array([1, 2, 3])], "budget.m4a", { type: "audio/mp4" });

describe("Meetings", () => {
  it("asks for the speaker model first, and opens Models at it", async () => {
    const onGetModel = vi.fn();
    render(
      <Meetings
        api={api({ status: vi.fn(async () => status({ speaker_model: false })) })}
        onGetModel={onGetModel}
      />,
    );
    expect(await screen.findByText("Get the speaker model first")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /New meeting from a file/ })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Open Models" }));
    expect(onGetModel).toHaveBeenCalledWith("sortformer-4spk-v2.1");
  });

  it("leaves the language to the model unless one is chosen, and then sends it", async () => {
    const a = api();
    render(<Meetings api={a} />);
    const field = await screen.findByRole("combobox", { name: "Language of the meeting" });
    expect(field).toHaveTextContent("Find it by itself");
    expect(screen.getByText(/Written down with Parakeet/)).toBeInTheDocument();

    await userEvent.click(field);
    await userEvent.click(await screen.findByRole("option", { name: /^Bengali/ }));
    // Parakeet does not know Bengali: the ready model that does writes it down
    expect(screen.getByText(/Written down with IndicConformer/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Recording of a meeting"), {
      target: { files: [file()] },
    });
    await waitFor(() =>
      expect(a.fromFile).toHaveBeenCalledWith(expect.any(File), { language: "bn" }),
    );
  });

  it("says when no model here knows the language, and does not start", async () => {
    const onGetModel = vi.fn();
    render(<Meetings api={api()} onGetModel={onGetModel} />);
    await userEvent.click(await screen.findByRole("combobox", { name: "Language of the meeting" }));
    await userEvent.click(await screen.findByRole("option", { name: /^Japanese/ }));
    expect(
      screen.getByText(/No speech-to-text model on this computer knows Japanese/),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /New meeting from a file/ })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Get one in Models" }));
    expect(onGetModel).toHaveBeenCalled();
  });

  it("opens a meeting: speakers, lines, the recording by its link, and naming a speaker", async () => {
    const a = api();
    render(<Meetings api={a} initialId="0b7c1f9e000040008000000000000000" />);
    const speakers = await screen.findByRole("region", { name: "Speakers" });
    const transcript = screen.getByRole("region", { name: "Transcript" });
    expect(within(transcript).getByText("Yes, the budget first.")).toBeInTheDocument();
    await waitFor(() =>
      expect(document.querySelector("audio")?.getAttribute("src")).toContain("/files/"),
    );

    await userEvent.click(within(speakers).getByRole("button", { name: "Name Speaker 1" }));
    const name = await screen.findByLabelText("Their name");
    await userEvent.clear(name);
    await userEvent.type(name, "Asha{Enter}");
    await waitFor(() =>
      expect(a.nameSpeaker).toHaveBeenCalledWith("0b7c1f9e000040008000000000000000", "S1", "Asha"),
    );
    expect(await within(transcript).findByText("Asha")).toBeInTheDocument();
  });

  it("follows a meeting being made, and stops it", async () => {
    const a = api({
      get: vi.fn(async () =>
        meeting({ status: "working", stage: "Telling the speakers apart", progress: 0.4 }),
      ),
    });
    render(<Meetings api={a} initialId="0b7c1f9e000040008000000000000000" />);
    expect(await screen.findByText("Telling the speakers apart")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Stop/ }));
    expect(a.stop).toHaveBeenCalled();
    expect(await screen.findByText("Stopped")).toBeInTheDocument();
  });

  it("suggests a known person by voice, names them only on Yes, and remembers No", async () => {
    const id = "0b7c1f9e000040008000000000000000";
    const hinted = meeting({
      speakers: [
        {
          key: "S1",
          default: "Speaker 1",
          name: "Speaker 1",
          seconds: 7,
          suggestion: { person_id: "p1", name: "Asha", status: "likely", distance: 0.2 },
        },
        {
          key: "S2",
          default: "Speaker 2",
          name: "Speaker 2",
          seconds: 4,
          suggestion: { person_id: "p1", name: "Asha", status: "possible", distance: 0.35 },
        },
      ],
    });
    const a = api({
      get: vi.fn(async () => hinted),
      nameSpeaker: vi.fn(async () => hinted),
      notThisPerson: vi.fn(async () => hinted),
    });
    render(<Meetings api={a} initialId={id} />);
    const speakers = await screen.findByRole("region", { name: "Speakers" });
    expect(within(speakers).getByText(/Is this/)).toBeInTheDocument();
    expect(within(speakers).getByText(/Could this be/)).toBeInTheDocument();
    expect(a.nameSpeaker).not.toHaveBeenCalled();
    await userEvent.click(within(speakers).getByRole("button", { name: "Yes, Speaker 1 is Asha" }));
    await waitFor(() => expect(a.nameSpeaker).toHaveBeenCalledWith(id, "S1", "Asha", "p1"));
    await userEvent.click(
      within(speakers).getByRole("button", { name: "No, Speaker 2 is not Asha" }),
    );
    await waitFor(() => expect(a.notThisPerson).toHaveBeenCalledWith(id, "S2", "p1"));
  });

  it("points to the voiceprint model when it is missing", async () => {
    const onGetModel = vi.fn();
    const a = api({ status: vi.fn(async () => status({ voiceprint_model: false })) });
    render(
      <Meetings api={a} initialId="0b7c1f9e000040008000000000000000" onGetModel={onGetModel} />,
    );
    expect(await screen.findByText(/get the voiceprint model/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Open Models" }));
    expect(onGetModel).toHaveBeenCalledWith("eres2net-voxceleb");
  });

  it("writes a report from a template, shows it, and deletes it only when asked", async () => {
    const id = "0b7c1f9e000040008000000000000000";
    const a = api({ get: vi.fn(async () => meeting({ reports: [report()] })) });
    render(<Meetings api={a} initialId={id} />);
    const reports = await screen.findByRole("region", { name: "Reports" });
    expect(await within(reports).findByText("The budget was agreed.")).toBeInTheDocument();
    await waitFor(() =>
      expect(within(reports).getByRole("button", { name: /Write/ })).toBeEnabled(),
    );
    await userEvent.click(within(reports).getByRole("button", { name: /Write/ }));
    await waitFor(() => expect(a.writeReport).toHaveBeenCalledWith(id, "summary"));

    await userEvent.click(within(reports).getByRole("button", { name: "Delete Summary" }));
    const dialog = await screen.findByRole("dialog", { hidden: true });
    expect(a.deleteReport).not.toHaveBeenCalled();
    await userEvent.click(within(dialog).getByRole("button", { name: "Delete", hidden: true }));
    await waitFor(() => expect(a.deleteReport).toHaveBeenCalledWith("r1"));
  });

  it("shows a report being written, with Stop", async () => {
    const a = api({
      get: vi.fn(async () =>
        meeting({
          reports: [report({ status: "working", stage: "Reading part 2 of 5", text: "" })],
        }),
      ),
    });
    render(<Meetings api={a} initialId="0b7c1f9e000040008000000000000000" />);
    const reports = await screen.findByRole("region", { name: "Reports" });
    expect(await within(reports).findByText("Reading part 2 of 5")).toBeInTheDocument();
    await userEvent.click(within(reports).getByRole("button", { name: /Stop/ }));
    await waitFor(() => expect(a.stopReport).toHaveBeenCalledWith("r1"));
  });

  it("asks about the meeting, shows the answer with its lines, and opens the notebook", async () => {
    const id = "0b7c1f9e000040008000000000000000";
    const onOpenNotebook = vi.fn();
    const a = api({
      get: vi.fn(async () =>
        meeting({
          questions: [question()],
          notebooks: [
            { notebook_id: "nb-acme", notebook_title: "Acme", document_id: "d1", added_at: "" },
          ],
        }),
      ),
    });
    render(<Meetings api={a} initialId={id} onOpenNotebook={onOpenNotebook} />);
    const ask = await screen.findByRole("region", { name: "Ask" });
    expect(within(ask).getByText("Speaker 2: Yes, the budget first.")).toBeInTheDocument();
    await userEvent.type(within(ask).getByLabelText(/Your question/), "Who spoke first?{Enter}");
    await waitFor(() => expect(a.ask).toHaveBeenCalledWith(id, "Who spoke first?"));
    await userEvent.click(within(ask).getByRole("button", { name: "Go on in the notebook" }));
    expect(onOpenNotebook).toHaveBeenCalledWith("nb-acme");
  });

  it("says the first question makes a notebook, and adds the meeting to one", async () => {
    const id = "0b7c1f9e000040008000000000000000";
    const a = api();
    render(<Meetings api={a} initialId={id} />);
    const ask = await screen.findByRole("region", { name: "Ask" });
    expect(
      within(ask).getByText(/first question adds the meeting to a new notebook/),
    ).toBeInTheDocument();
    await userEvent.click(within(ask).getByRole("button", { name: /Add to a notebook/ }));
    const dialog = await screen.findByRole("dialog", { hidden: true });
    await waitFor(() => expect(a.notebooks).toHaveBeenCalled());
    await waitFor(() =>
      expect(within(dialog).getByRole("button", { name: "Add", hidden: true })).toBeEnabled(),
    );
    await userEvent.click(within(dialog).getByRole("button", { name: "Add", hidden: true }));
    await waitFor(() => expect(a.addToNotebook).toHaveBeenCalledWith(id, { title: "Budget call" }));
  });

  it("shows a question being answered, with Stop", async () => {
    const a = api({
      get: vi.fn(async () =>
        meeting({
          questions: [question({ status: "working", stage: "Asking the notebook", reply: "" })],
        }),
      ),
    });
    render(<Meetings api={a} initialId="0b7c1f9e000040008000000000000000" />);
    const ask = await screen.findByRole("region", { name: "Ask" });
    expect(await within(ask).findByText("Asking the notebook")).toBeInTheDocument();
    await userEvent.click(within(ask).getByRole("button", { name: /Stop/ }));
    await waitFor(() => expect(a.stopQuestion).toHaveBeenCalledWith("q1"));
  });
});
