// Meetings (ADR-0108): a recording, its transcript and its speakers as one meeting. Stage MT1 makes a
// meeting from a file: the speakers are told apart on this computer and the words are written down with
// the chosen speech-to-text model, in the background. The same engine routes serve the desktop window;
// the web gets them in stage MT6, where a meeting is made from a file by the cloud transcription model.
import { HttpError, type Transport, errorMessage } from "./transport";

export const MEETINGS_PRODUCT_ID = "wasifyai-meetings";
const BASE = "/products/wasifyai-meetings";

export type MeetingsStatus = {
  /** the speaker model is on this computer */
  speaker_model: boolean;
  /** the voiceprint model is on this computer: People can suggest who a speaker is (MT3) */
  voiceprint_model: boolean;
  voiceprint_model_id: string;
  /** its id in Models, to fetch it from there */
  speaker_model_id: string;
  /** a speech-to-text model is chosen and ready */
  speech: boolean;
  speech_model: { id: string; title: string } | null;
  speech_problem: string | null;
  /** the speech-to-text models ready on this computer and the languages each writes down: a meeting in
   * a language the chosen one does not know goes to one of these that does */
  speech_models: { id: string; title: string; languages: string[] }[];
  busy: boolean;
  /** the meeting being made */
  active: string | null;
  converter: boolean;
  formats: string[];
  /** recordings made in the window (MT2) not made into a meeting yet: the window was closed, or making
   * one was refused */
  recordings: WaitingRecording[];
};

/** `modified` is seconds since 1970 */
export type WaitingRecording = { name: string; bytes: number; seconds: number; modified: number };

export type MeetingSpeaker = {
  /** "S1", "S2" … in the order they first speak */
  key: string;
  /** "Speaker 1" … what an empty name gives back */
  default: string;
  name: string;
  /** how long they spoke */
  seconds: number;
  /** the person of People they are (MT3) */
  person_id?: string;
  /** people they were said not to be */
  not?: string[];
  /** who they may be, by voice: never given without the person (only on a meeting's own page) */
  suggestion?: SpeakerSuggestion | null;
};

export type SpeakerSuggestion = {
  person_id: string;
  name: string;
  /** "likely": enough speech and evidence; "possible": less sure */
  status: "likely" | "possible";
  distance: number;
};

/** A person the meetings know (MT3). */
export type MeetingPerson = {
  id: string;
  name: string;
  created_at: string;
  /** meetings they were named in */
  meetings: number;
  /** voiceprints of them kept */
  voices: number;
  last_named: string | null;
};

export type ReportTemplate = { id: string; title: string; instructions: string; own: boolean };

/** A report of a meeting, written from a template (MT4). */
export type MeetingReport = {
  id: string;
  meeting_id: string;
  template: string;
  title: string;
  status: MeetingState;
  stage: string;
  progress: number;
  error: string | null;
  /** Markdown */
  text: string;
  created_at: string;
  finished_at: string | null;
};

export type MeetingLine = { start: number; end: number; speaker: string; text: string };

export type MeetingState = "working" | "done" | "failed" | "cancelled";

export type MeetingSummary = {
  id: string;
  title: string;
  source_name: string;
  /** "file" (chosen from the computer) or "recorded" (recorded in the window, MT2) */
  source: "file" | "recorded";
  status: MeetingState;
  /** what it is doing now, in words, while working */
  stage: string;
  progress: number;
  error: string | null;
  language: string;
  model_id: string;
  seconds: number | null;
  speakers: MeetingSpeaker[];
  /** the start of the transcript */
  text: string;
  elapsed_s: number | null;
  created_at: string;
  finished_at: string | null;
  /** being made right now */
  live: boolean;
};

export type Meeting = MeetingSummary & {
  lines: MeetingLine[];
  timings: Record<string, number>;
  reports: MeetingReport[];
  /** the notebooks it is a source of, the last added first (MT5) */
  notebooks: MeetingInNotebook[];
  /** questions asked about it on its page, oldest first (MT5) */
  questions: MeetingQuestion[];
};

export type MeetingInNotebook = {
  notebook_id: string;
  notebook_title: string;
  /** the meeting's source in that notebook */
  document_id: string;
  added_at: string;
};

/** A passage an answer cites by its `[n]` label. */
/** A passage the answer cites: `n` is the number in the answer's [n]. */
export type MeetingCitation = { n?: number; document_id?: string; title?: string; text?: string };

/** A question about a meeting, answered by a notebook it is in (MT5). */
export type MeetingQuestion = {
  id: string;
  meeting_id: string;
  question: string;
  status: MeetingState;
  stage: string;
  error: string | null;
  /** Markdown with `[n]` labels */
  reply: string;
  citations: MeetingCitation[];
  notebook_id: string;
  conversation_id: string;
  created_at: string;
  finished_at: string | null;
};

export type MeetingsApi = {
  status(signal?: AbortSignal): Promise<MeetingsStatus>;
  list(signal?: AbortSignal): Promise<MeetingSummary[]>;
  get(id: string, signal?: AbortSignal): Promise<Meeting>;
  /** start making a meeting from a recording; follow it with `get` */
  fromFile(file: File, opts?: { title?: string; language?: string }): Promise<Meeting>;
  /** start making a meeting from a recording the window made (its name in the recordings folder) */
  fromRecording(name: string, opts?: { title?: string; language?: string }): Promise<Meeting>;
  /** throw away a recording that is waiting */
  discardRecording(name: string): Promise<void>;
  rename(id: string, title: string): Promise<Meeting>;
  /** name a speaker: they become that person of People (by `personId`, or by the name) */
  nameSpeaker(id: string, key: string, name: string, personId?: string): Promise<Meeting>;
  /** "No" to a suggestion: the speaker is not that person */
  notThisPerson(id: string, key: string, personId: string): Promise<Meeting>;
  people(signal?: AbortSignal): Promise<MeetingPerson[]>;
  renamePerson(personId: string, name: string): Promise<MeetingPerson>;
  /** delete a person with every voiceprint of them */
  forgetPerson(personId: string): Promise<void>;
  templates(signal?: AbortSignal): Promise<ReportTemplate[]>;
  addTemplate(title: string, instructions: string): Promise<ReportTemplate>;
  deleteTemplate(templateId: string): Promise<void>;
  /** start writing a report; follow it with `report` or `get` */
  writeReport(id: string, template: string): Promise<MeetingReport>;
  report(reportId: string, signal?: AbortSignal): Promise<MeetingReport>;
  stopReport(reportId: string): Promise<MeetingReport>;
  deleteReport(reportId: string): Promise<void>;
  /** the report as a Markdown file */
  exportReport(reportId: string): Promise<Blob>;
  /** the person's notebooks, to add a meeting to (MT5) */
  notebooks(signal?: AbortSignal): Promise<{ id: string; title: string }[]>;
  /** add the meeting to a notebook as a source; without `notebookId` a new notebook is made */
  addToNotebook(
    id: string,
    to: { notebookId?: string; title?: string },
  ): Promise<{ notebook_id: string; notebook_title: string; document_id: string }>;
  /** ask about the meeting; follow it with `question` or `get` */
  ask(id: string, question: string): Promise<MeetingQuestion>;
  question(questionId: string, signal?: AbortSignal): Promise<MeetingQuestion>;
  stopQuestion(questionId: string): Promise<MeetingQuestion>;
  deleteQuestion(questionId: string): Promise<void>;
  stop(id: string): Promise<Meeting>;
  remove(id: string): Promise<void>;
  /** the recording as heard, for playing back: a signed link the player reads in ranges, or, where
   * there is none, the whole file as an object URL (`blob:`; revoke it when done) */
  audioUrl(id: string): Promise<string>;
  /** the transcript as text, with the speakers' names */
  exportText(id: string): Promise<Blob>;
};

export function createMeetingsApi(transport: Transport): MeetingsApi {
  async function fail(res: Response): Promise<never> {
    if (res.status === 401) transport.onUnauthorized?.();
    throw new HttpError(res.status, await errorMessage(res));
  }
  async function json<T>(path: string, init?: RequestInit): Promise<T> {
    const res = await transport.fetch(`${BASE}${path}`, init);
    if (!res.ok) return fail(res);
    return (await res.json()) as T;
  }
  async function blob(path: string): Promise<Blob> {
    const res = await transport.fetch(`${BASE}${path}`);
    if (!res.ok) return fail(res);
    return res.blob();
  }
  const patch = (body: unknown): RequestInit => ({
    method: "PATCH",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  return {
    status: (signal) => json("/status", { signal }),
    list: async (signal) =>
      (await json<{ items: MeetingSummary[] }>("/meetings", { signal })).items,
    get: (id, signal) => json(`/meetings/${encodeURIComponent(id)}`, { signal }),
    fromFile: (file, opts) => {
      const form = new FormData();
      form.append("file", file, file.name);
      if (opts?.title) form.append("title", opts.title);
      if (opts?.language) form.append("language", opts.language);
      return json("/meetings", { method: "POST", body: form });
    },
    fromRecording: (name, opts) =>
      json("/meetings/recorded", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ name, title: opts?.title, language: opts?.language }),
      }),
    discardRecording: async (name) => {
      const res = await transport.fetch(`${BASE}/recordings/${encodeURIComponent(name)}`, {
        method: "DELETE",
      });
      if (!res.ok) await fail(res);
    },
    rename: (id, title) => json(`/meetings/${encodeURIComponent(id)}`, patch({ title })),
    nameSpeaker: (id, key, name, personId) =>
      json(
        `/meetings/${encodeURIComponent(id)}/speakers/${encodeURIComponent(key)}`,
        patch(personId ? { name, person_id: personId } : { name }),
      ),
    notThisPerson: (id, key, personId) =>
      json(`/meetings/${encodeURIComponent(id)}/speakers/${encodeURIComponent(key)}/not`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ person_id: personId }),
      }),
    people: async (signal) => (await json<{ items: MeetingPerson[] }>("/people", { signal })).items,
    renamePerson: (personId, name) =>
      json(`/people/${encodeURIComponent(personId)}`, patch({ name })),
    forgetPerson: async (personId) => {
      const res = await transport.fetch(`${BASE}/people/${encodeURIComponent(personId)}`, {
        method: "DELETE",
      });
      if (!res.ok) await fail(res);
    },
    templates: async (signal) =>
      (await json<{ items: ReportTemplate[] }>("/templates", { signal })).items,
    addTemplate: (title, instructions) =>
      json("/templates", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ title, instructions }),
      }),
    deleteTemplate: async (templateId) => {
      const res = await transport.fetch(`${BASE}/templates/${encodeURIComponent(templateId)}`, {
        method: "DELETE",
      });
      if (!res.ok) await fail(res);
    },
    writeReport: (id, template) =>
      json(`/meetings/${encodeURIComponent(id)}/reports`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ template }),
      }),
    report: (reportId, signal) => json(`/reports/${encodeURIComponent(reportId)}`, { signal }),
    stopReport: (reportId) =>
      json(`/reports/${encodeURIComponent(reportId)}/stop`, { method: "POST" }),
    deleteReport: async (reportId) => {
      const res = await transport.fetch(`${BASE}/reports/${encodeURIComponent(reportId)}`, {
        method: "DELETE",
      });
      if (!res.ok) await fail(res);
    },
    exportReport: (reportId) => blob(`/reports/${encodeURIComponent(reportId)}/export`),
    notebooks: async (signal) =>
      (await json<{ items: { id: string; title: string }[] }>("/notebooks", { signal })).items,
    addToNotebook: (id, to) =>
      json(`/meetings/${encodeURIComponent(id)}/notebook`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ notebook_id: to.notebookId ?? null, title: to.title ?? null }),
      }),
    ask: (id, question) =>
      json(`/meetings/${encodeURIComponent(id)}/questions`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ question }),
      }),
    question: (questionId, signal) =>
      json(`/questions/${encodeURIComponent(questionId)}`, { signal }),
    stopQuestion: (questionId) =>
      json(`/questions/${encodeURIComponent(questionId)}/stop`, { method: "POST" }),
    deleteQuestion: async (questionId) => {
      const res = await transport.fetch(`${BASE}/questions/${encodeURIComponent(questionId)}`, {
        method: "DELETE",
      });
      if (!res.ok) await fail(res);
    },
    stop: (id) => json(`/meetings/${encodeURIComponent(id)}/stop`, { method: "POST" }),
    remove: async (id) => {
      const res = await transport.fetch(`${BASE}/meetings/${encodeURIComponent(id)}`, {
        method: "DELETE",
      });
      if (!res.ok) await fail(res);
    },
    audioUrl: async (id) => {
      const at = encodeURIComponent(id);
      const res = await transport.fetch(`${BASE}/meetings/${at}/audio-link`);
      if (res.ok) return ((await res.json()) as { url: string }).url;
      if (res.status !== 404) return fail(res);
      return URL.createObjectURL(await blob(`/meetings/${at}/audio`));
    },
    exportText: (id) => blob(`/meetings/${encodeURIComponent(id)}/export`),
  };
}
