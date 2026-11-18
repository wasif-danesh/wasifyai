// What each menu group needs before it works on this computer (ADR-0109): `GET /desktop/setup/groups`. The engine
// generates each group's card from its actions' needs, priced from the catalogues and judged by its fit figures;
// the window says it in words and runs the parts with the routes that already set them up.
import type { Transport } from "./transport";
import { HttpError } from "./transport";

/** One part of a group: an optional component, a catalogue model, or the chat model (whose size the window's
 * chat choice knows). */
export type SetupPart = {
  /** `component:audiocpp`, `model:kokoro-82m`, `chat` */
  id: string;
  kind: "component" | "model" | "chat";
  /** the component or catalogue model id; empty for the chat */
  ref: string;
  title: string;
  /** what it still costs to download (0 when set up) */
  bytes: number;
  set_up: boolean;
  installing: boolean;
  memory_bytes: number | null;
  /** false: not made for this computer; `reason` says why */
  available: boolean;
  reason: string;
  /** include: part of the download; on_request: only under "Download instead"; cannot_run: too big here */
  fit: "include" | "on_request" | "cannot_run";
  /** part of the group's download on this computer */
  included: boolean;
  /** the menu items that need it */
  items: string[];
};

export type SetupItemState = "ready" | "needs_setup" | "partly" | "left_out" | "unavailable";

export type SetupItem = { id: string; parts: string[]; state: SetupItemState };

export type SetupGroup = {
  id: string;
  items: SetupItem[];
  parts: SetupPart[];
  /** groups this one's button sets up too (Creative Studio: Video and Voice) */
  uses: string[];
  /** Train: each kind sets itself up when it is chosen */
  explain_only: boolean;
  state: "ready" | "needs_setup";
  download_bytes: number;
  download_instead_bytes: number;
  /** covers: a cloud key does every item; first: the key is the main button; only: nothing here can run it */
  key: { covers: boolean; first: boolean; only: boolean };
  memory_bytes: number | null;
  /** the groups it uses, and whether each is key first on this computer */
  with?: Record<string, { key_first: boolean }>;
};

export function createSetupApi(transport: Transport) {
  return {
    async groups(): Promise<{ groups: SetupGroup[]; memory_bytes: number | null }> {
      const res = await transport.fetch("/desktop/setup/groups");
      if (!res.ok) throw new HttpError(res.status, `The engine answered ${res.status}`);
      return (await res.json()) as { groups: SetupGroup[]; memory_bytes: number | null };
    },
  };
}

export type SetupApi = ReturnType<typeof createSetupApi>;
