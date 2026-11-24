// @vitest-environment jsdom
// The Your agent tab of the Code model button, and Settings › Code (ADR-0107, stage H2): the person's own
// Claude Code and Codex, set up once, each signed in on its own page, with the models its plan offers.
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createRef } from "react";
import { describe, expect, it, vi } from "vitest";
import { AgentPrograms } from "./AgentTab";
import { ModelSelect, type ModelSelectHandle } from "./ModelSelect";
import type { AgentProgram, AgentSetup, AgentsApi, ChoicesApi, ModelChoice } from "./types";

const program = (over: Partial<AgentProgram> = {}): AgentProgram => ({
  id: "claude-code",
  title: "Claude Code",
  payer: "Your Claude plan",
  account: "Claude",
  signedIn: true,
  plan: "Max",
  signingIn: false,
  page: "",
  ...over,
});
const CODEX = program({
  id: "codex",
  title: "Codex",
  payer: "Your ChatGPT plan",
  account: "ChatGPT",
  signedIn: false,
  plan: "",
});

const row = (over: Partial<ModelChoice>): ModelChoice => ({
  id: "claude-code:default",
  title: "Its own choice",
  plain: "Whatever Claude Code picks on your plan.",
  tier: "recommended",
  state: "ready",
  chosen: false,
  downloadBytes: 0,
  engineBytes: 0,
  engineName: null,
  fit: null,
  fitReason: null,
  source: "server",
  place: "agent",
  provider: "claude-code",
  providerTitle: "Claude Code",
  price: "Your Claude plan",
  ...over,
});
const ROWS = [
  row({}),
  row({ id: "claude-code:sonnet", title: "Sonnet", tier: "also", chosen: true }),
  row({ id: "claude-code:haiku", title: "Haiku", tier: "also" }),
];

function agents(setup: AgentSetup, programs: AgentProgram[]) {
  let now = { setup, programs };
  const api = {
    programs: vi.fn(async () => now),
    setUp: vi.fn(async () => {
      now = { ...now, setup: { state: "installing", fraction: 0.4, label: "Installing" } };
    }),
    remove: vi.fn(async () => {}),
    signIn: vi.fn(async (id: string) => {
      now = {
        ...now,
        programs: now.programs.map((p) =>
          p.id === id ? { ...p, signingIn: true, page: "https://auth.openai.com/x" } : p,
        ),
      };
    }),
    cancelSignIn: vi.fn(async () => {}),
  } satisfies AgentsApi;
  return api;
}

function choices(rows: ModelChoice[], agentsApi: AgentsApi): ChoicesApi {
  return {
    list: async () => ({ choices: rows, diskFreeBytes: null, memoryBytes: null }),
    choose: vi.fn(async () => {}),
    get: async () => {},
    agents: agentsApi,
  };
}

describe("the Your agent tab", () => {
  it("names the program and model in use, and opens on its tab with the plan's models", async () => {
    const user = userEvent.setup();
    const a = agents({ state: "installed", version: "1", bytes: 0 }, [program(), CODEX]);
    render(<ModelSelect group="code" api={choices(ROWS, a)} />);
    await user.click(await screen.findByRole("button", { name: /Claude Code · Sonnet/ }));
    expect(screen.getByRole("tab", { name: "Your agent" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    const claude = await screen.findByRole("list", { name: "Claude Code" });
    expect(within(claude).getByText("Claude Code · signed in · Max plan")).toBeTruthy();
    expect(within(claude).getByText("Its own choice")).toBeTruthy();
    expect(within(claude).getByText("In use · Your Claude plan")).toBeTruthy();
    // a program that is not signed in offers its own sign-in, and no models
    expect(screen.getByRole("button", { name: "Sign in to Codex" })).toBeTruthy();
    expect(screen.getByText(/Extensions and “Ask me” are for Wasify AI's own agent/)).toBeTruthy();
  });

  it("chooses a model of the program", async () => {
    const user = userEvent.setup();
    const api = choices(ROWS, agents({ state: "installed", version: "1", bytes: 0 }, [program()]));
    render(<ModelSelect group="code" api={api} />);
    await user.click(await screen.findByRole("button", { name: /Claude Code · Sonnet/ }));
    await user.click(await screen.findByRole("button", { name: /Haiku/ }));
    expect(api.choose).toHaveBeenCalledWith("claude-code:haiku");
  });

  it("signs in on the program's own page, and waits for it", async () => {
    const user = userEvent.setup();
    const a = agents({ state: "installed", version: "1", bytes: 0 }, [program(), CODEX]);
    render(<ModelSelect group="code" api={choices(ROWS, a)} />);
    await user.click(await screen.findByRole("button", { name: /Claude Code · Sonnet/ }));
    await user.click(await screen.findByRole("button", { name: "Sign in to Codex" }));
    expect(a.signIn).toHaveBeenCalledWith("codex");
    expect(await screen.findByText("Signing in…")).toBeTruthy();
    expect(screen.getByText(/never sees your password or token/)).toBeTruthy();
    expect(screen.getByRole("link", { name: "Open the page again" })).toHaveAttribute(
      "href",
      "https://auth.openai.com/x",
    );
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(a.cancelSignIn).toHaveBeenCalledWith("codex");
  });

  it("says the size before setting the programs up, and shows how far it is", async () => {
    const user = userEvent.setup();
    const a = agents({ state: "not_installed", bytes: 694_400_000 }, []);
    render(<ModelSelect group="code" api={choices([], a)} />);
    await user.click(await screen.findByRole("button", { name: /Select coding model/ }));
    await user.click(screen.getByRole("tab", { name: "Your agent" }));
    expect(await screen.findByText("Use your own Claude Code or Codex")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: /^Set up \(694/ }));
    expect(a.setUp).toHaveBeenCalledWith(694_400_000);
    expect(await screen.findByText(/Setting up… Installing, 40%/)).toBeTruthy();
  });

  it("is the chat's Your plan tab, with the chat's own words (ADR-0110)", async () => {
    const user = userEvent.setup();
    const a = agents({ state: "not_installed", bytes: 694_400_000 }, []);
    const api: ChoicesApi = {
      ...choices([], a),
      agentsTab: "Your plan",
      agentsWords: { intro: "The chat can answer on your plan.", foot: "Cards still ask." },
    };
    render(<ModelSelect group="chat" api={api} />);
    await user.click(await screen.findByRole("button", { name: /Select chat model/ }));
    expect(screen.queryByRole("tab", { name: "Your agent" })).toBeNull();
    await user.click(screen.getByRole("tab", { name: "Your plan" }));
    expect(await screen.findByText(/The chat can answer on your plan\. Setting up/)).toBeTruthy();
    expect(screen.getByText("Cards still ask.")).toBeTruthy();
    expect(screen.queryByText(/Sessions can run/)).toBeNull();
  });

  it("opens on Your plan when a screen asks (the first run's plan link, ADR-0110)", async () => {
    const a = agents({ state: "installed", version: "1", bytes: 0 }, [program(), CODEX]);
    const handle = createRef<ModelSelectHandle>();
    const api: ChoicesApi = { ...choices(ROWS, a), agentsTab: "Your plan" };
    render(<ModelSelect group="chat" api={api} handleRef={handle} />);
    await screen.findByRole("button", { name: /Claude Code · Sonnet|Select chat model/ });
    act(() => handle.current?.openOn("agent"));
    expect(await screen.findByRole("tab", { name: "Your plan" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  it("is not there for a group without agent programs", async () => {
    const user = userEvent.setup();
    const api: ChoicesApi = {
      list: async () => ({ choices: [], diskFreeBytes: null, memoryBytes: null }),
      choose: async () => {},
      get: async () => {},
    };
    render(<ModelSelect group="chat" api={api} />);
    await user.click(await screen.findByRole("button", { name: /Select chat model/ }));
    expect(screen.queryByRole("tab", { name: "Your agent" })).toBeNull();
  });
});

describe("Settings › Code", () => {
  it("lists each program's sign-in, signs in again, and removes the programs only after a yes", async () => {
    const user = userEvent.setup();
    const a = agents({ state: "installed", version: "0.99.1", bytes: 0 }, [program(), CODEX]);
    render(<AgentPrograms api={a} />);
    expect(await screen.findByText("Signed in · Max plan")).toBeTruthy();
    expect(screen.getByText(/To sign out, use Claude Code/)).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Sign in again" }));
    expect(a.signIn).toHaveBeenCalledWith("claude-code");
    expect(screen.getByText(/does not sign you out/)).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Remove" }));
    expect(a.remove).not.toHaveBeenCalled();
    await user.click(
      within(screen.getByRole("dialog")).getByRole("button", { name: /Remove|Yes|Delete/ }),
    );
    await waitFor(() => expect(a.remove).toHaveBeenCalled());
  });
});
