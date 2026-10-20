// @vitest-environment jsdom
// Web search in the chat (ADR-0083, stage CO3): the Search button and its consent card, the source cards, and the settings.
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type {
  AssistantApi,
  ChatOptions,
  ImagesApi,
  OnEvent,
  ParsedEvent,
  SearchStatus,
} from "@wasifyai/client";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AssistantHome } from "./AssistantHome";
import { SearchSettings } from "./SearchSettings";
import { ToolCard } from "./ToolCard";

const images = {} as ImagesApi;

const SEARCH = {
  available: true,
  consented: false,
  ready: false,
  provider: "duckduckgo",
  provider_title: "DuckDuckGo",
  consent_text:
    "Searching the web sends your question to DuckDuckGo. You can turn this off in Settings.",
  needs_key: false,
};

const status = (over: Partial<SearchStatus> = {}): SearchStatus => ({
  provider: "duckduckgo",
  consented: false,
  consent_text: SEARCH.consent_text,
  can_save_keys: true,
  providers: [
    {
      id: "duckduckgo",
      title: "DuckDuckGo",
      needs_key: false,
      key_set: false,
      key_url: "",
      sends_to: "DuckDuckGo",
      note: "No account needed.",
    },
    {
      id: "tavily",
      title: "Tavily",
      needs_key: true,
      key_set: false,
      key_url: "https://app.tavily.com/home",
      sends_to: "Tavily (tavily.com)",
      note: "Free key.",
    },
  ],
  ...over,
});

function assistantWith(options: ChatOptions, over: Partial<AssistantApi> = {}): AssistantApi {
  return {
    options: vi.fn(async () => options),
    searchStatus: vi.fn(async () => status()),
    updateSearch: vi.fn(async () => status({ consented: true })),
    setHead: vi.fn(async () => {}),
    attach: vi.fn(async () => {
      throw new Error("unused");
    }),
    unattach: vi.fn(async () => {}),
    list: vi.fn(async () => []),
    get: vi.fn(),
    rename: vi.fn(),
    remove: vi.fn(async () => {}),
    ...over,
  } as AssistantApi;
}

const DONE = {
  event: "done",
  data: { run_id: "r1", seq: 1, outputs: { status: "done", conversation_id: "c1", title: "T" } },
} as unknown as ParsedEvent;

function runsRecording(inputs: object[]) {
  return {
    startRun: vi.fn(async (_p: string, input: object, _s: AbortSignal, on: OnEvent) => {
      inputs.push(input);
      on(DONE);
    }),
    watchRun: vi.fn(async () => {}),
  };
}

function home(assistant: AssistantApi, inputs: object[] = [], extra: object = {}) {
  return render(
    <AssistantHome
      runs={runsRecording(inputs)}
      assistant={assistant}
      images={images}
      conversationId={null}
      onAdopt={() => {}}
      onNewChat={() => {}}
      {...extra}
    />,
  );
}

beforeEach(() => localStorage.clear());

describe("the Search button", () => {
  it("is not there when the engine cannot search", async () => {
    home(assistantWith({ thinking: false }));
    await screen.findByRole("heading", { level: 1 });
    await new Promise((r) => setTimeout(r, 20));
    expect(screen.queryByRole("button", { name: /^Search/ })).toBeNull();
  });

  it("asks first, names the service, and sends nothing about search until allowed", async () => {
    const inputs: object[] = [];
    const assistant = assistantWith({ thinking: false, search: SEARCH });
    const user = userEvent.setup();
    home(assistant, inputs);
    const button = await screen.findByRole("button", { name: /^Search/ });
    expect(button).toHaveAttribute("aria-pressed", "false");

    await user.click(button);
    const card = screen.getByRole("region", { name: "Allow the assistant to search the web?" });
    expect(card).toHaveTextContent("sends your question to DuckDuckGo");
    expect(assistant.updateSearch).not.toHaveBeenCalled();

    await user.click(within(card).getByRole("button", { name: "Not now" }));
    expect(screen.queryByRole("region", { name: /search the web/ })).toBeNull();
    await user.type(screen.getByRole("textbox", { name: "Message" }), "news{Enter}");
    await waitFor(() => expect(inputs).toHaveLength(1));
    expect(inputs[0]).not.toHaveProperty("search");
  });

  it("allows once, turns Search on, and asks for it with the next message", async () => {
    const inputs: object[] = [];
    const assistant = assistantWith(
      { thinking: false, search: SEARCH },
      { updateSearch: vi.fn(async () => status({ consented: true })) },
    );
    const user = userEvent.setup();
    home(assistant, inputs);
    await user.click(await screen.findByRole("button", { name: /^Search/ }));
    await user.click(screen.getByRole("button", { name: "Allow search" }));
    expect(assistant.updateSearch).toHaveBeenCalledWith({ consent: true });
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /^Search/ })).toHaveAttribute(
        "aria-pressed",
        "true",
      ),
    );
    expect(screen.queryByRole("region", { name: /search the web/ })).toBeNull();
    await user.type(screen.getByRole("textbox", { name: "Message" }), "news{Enter}");
    await waitFor(() => expect(inputs).toHaveLength(1));
    expect(inputs[0]).toMatchObject({ text: "news", search: true });
  });

  it("says in words when the choice could not be saved, and stays off", async () => {
    const assistant = assistantWith(
      { thinking: false, search: SEARCH },
      {
        updateSearch: vi.fn(async () => {
          throw new Error("Settings could not be written.");
        }),
      },
    );
    const user = userEvent.setup();
    home(assistant);
    await user.click(await screen.findByRole("button", { name: /^Search/ }));
    await user.click(screen.getByRole("button", { name: "Allow search" }));
    expect(await screen.findByText("Settings could not be written.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Search/ })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
  });

  it("points to Settings when the chosen service needs a key", async () => {
    const onOpenSettings = vi.fn();
    const user = userEvent.setup();
    home(
      assistantWith({
        thinking: false,
        search: {
          ...SEARCH,
          consented: true,
          provider: "tavily",
          provider_title: "Tavily",
          needs_key: true,
        },
      }),
      [],
      { onOpenSettings },
    );
    await user.click(await screen.findByRole("button", { name: /^Search/ }));
    const card = screen.getByRole("region", { name: "Search needs your Tavily key" });
    await user.click(within(card).getByRole("button", { name: "Open Settings" }));
    expect(onOpenSettings).toHaveBeenCalled();
  });
});

describe("the web cards", () => {
  const tool = (name: string, over: object) =>
    ({
      type: "tool",
      id: "t1",
      name,
      arguments: {},
      status: "ok",
      ...over,
    }) as never;

  it("lists the sources of a search with their sites, as links that open outside the app", () => {
    render(
      <ToolCard
        images={images}
        tool={tool("web_search", {
          output: {
            provider_title: "DuckDuckGo",
            results: [
              {
                title: "Foxes",
                url: "https://wiki.test/fox",
                site: "wiki.test",
                snippet: "Small.",
              },
              { title: "Bad", url: "javascript:alert(1)", site: "evil", snippet: "" },
            ],
          },
        })}
      />,
    );
    const link = screen.getByRole("link", { name: "Foxes" });
    expect(link).toHaveAttribute("href", "https://wiki.test/fox");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", expect.stringContaining("noopener"));
    expect(screen.getByText("wiki.test")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Bad" })).toBeNull(); // a script address is text, never a link
    expect(screen.getByText("Bad")).toBeInTheDocument();
  });

  it("says what went wrong, and that nothing was found, in words", () => {
    const { rerender } = render(
      <ToolCard
        images={images}
        tool={tool("web_search", { status: "error", output: { message: "DuckDuckGo is busy." } })}
      />,
    );
    expect(screen.getByText("DuckDuckGo is busy.")).toBeInTheDocument();
    rerender(<ToolCard images={images} tool={tool("web_search", { output: { results: [] } })} />);
    expect(screen.getByText("Nothing found on the web")).toBeInTheDocument();
    rerender(<ToolCard images={images} tool={tool("web_search", { status: "running" })} />);
    expect(screen.getByText("Searching the web")).toBeInTheDocument();
  });

  it("shows a page that was read, its site and a note when only the start was read", () => {
    render(
      <ToolCard
        images={images}
        tool={tool("web_read", {
          output: {
            title: "Foxes",
            url: "https://wiki.test/fox",
            final_url: "https://wiki.test/fox2",
            site: "wiki.test",
            excerpt: "Foxes are small.",
            truncated: true,
          },
        })}
      />,
    );
    expect(screen.getByRole("link", { name: "Foxes" })).toHaveAttribute(
      "href",
      "https://wiki.test/fox2",
    );
    expect(screen.getByText("Foxes are small.")).toBeInTheDocument();
    expect(screen.getByText("Only the start of this page was read.")).toBeInTheDocument();
  });
});

describe("SearchSettings", () => {
  it("is not shown by an engine that cannot search", async () => {
    const assistant = assistantWith(
      { thinking: false },
      {
        searchStatus: vi.fn(async () => {
          throw new Error("404");
        }),
      },
    );
    const { container } = render(<SearchSettings assistant={assistant} />);
    await new Promise((r) => setTimeout(r, 20));
    expect(container).toBeEmptyDOMElement();
  });

  it("changes the service, the permission and the key, and never shows a saved key", async () => {
    let current = status();
    const updateSearch = vi.fn(async (u: Parameters<AssistantApi["updateSearch"]>[0]) => {
      if (u.provider) current = status({ provider: u.provider });
      if (u.consent !== undefined) current = { ...current, consented: u.consent };
      if (u.key)
        current = {
          ...current,
          providers: current.providers.map((p) =>
            p.id === u.key?.provider ? { ...p, key_set: true } : p,
          ),
        };
      return current;
    });
    const assistant = assistantWith(
      { thinking: false },
      { searchStatus: async () => current, updateSearch },
    );
    const user = userEvent.setup();
    render(<SearchSettings assistant={assistant} />);
    await screen.findByRole("heading", { name: "Searching the web" });
    expect(screen.queryByLabelText(/DuckDuckGo key/)).toBeNull(); // DuckDuckGo needs none

    await user.click(screen.getByRole("radio", { name: /Tavily/ }));
    expect(updateSearch).toHaveBeenCalledWith({ provider: "tavily" });
    const field = await screen.findByLabelText(/Tavily key \(not saved yet\)/);
    expect(field).toHaveAttribute("type", "password");
    await user.type(field, "tvly-secret-1");
    await user.click(screen.getByRole("button", { name: "Save key" }));
    expect(updateSearch).toHaveBeenCalledWith({
      key: { provider: "tavily", value: "tvly-secret-1" },
    });
    expect(await screen.findByLabelText(/Tavily key \(saved\)/)).toHaveValue(""); // not shown again
    expect(screen.queryByDisplayValue("tvly-secret-1")).toBeNull();

    await user.click(screen.getByRole("checkbox", { name: /Allow searching the web with Tavily/ }));
    expect(updateSearch).toHaveBeenLastCalledWith({ consent: true });
    expect(screen.getByRole("link", { name: "Get a key" })).toHaveAttribute("data-external");
  });

  it("shows a refused key in words", async () => {
    const assistant = assistantWith(
      { thinking: false },
      {
        searchStatus: async () => status({ provider: "tavily" }),
        updateSearch: vi.fn(async () => {
          throw new Error("That does not look like a key: no spaces, 8 to 300 characters.");
        }),
      },
    );
    const user = userEvent.setup();
    render(<SearchSettings assistant={assistant} />);
    await user.type(await screen.findByLabelText(/Tavily key/), "short");
    await user.click(screen.getByRole("button", { name: "Save key" }));
    expect(await screen.findByText(/does not look like a key/)).toBeInTheDocument();
  });
});
