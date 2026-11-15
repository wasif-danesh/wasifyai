"use client";
// The Browser tab (mockup `browser`): a browser of the person's own beside the chat, for looking things up.
// The agent cannot open a page or reach the internet; it sees a page only when the person chooses "Add
// this page to the chat", and then as plain text.
//
// The page itself is not drawn here. It is a second webview that the desktop shell lays over this tab's
// empty area (`BrowserHost`); this component draws the bar above it and tells the host where the area is.
// Where there is no host (the web, a test) the tab says so.
import {
  ArrowLeft,
  ArrowRight,
  ExternalLink,
  Globe,
  MessageSquarePlus,
  RotateCw,
  X,
} from "lucide-react";
import { type FormEvent, useCallback, useEffect, useId, useRef, useState } from "react";
import { Button } from "../components/button";
import { EmptyState } from "../components/empty-state";
import { Input } from "../components/input";
import { Spinner } from "../components/spinner";

/** An area of the window, in the window's own points from its top left. */
export type BrowserArea = { x: number; y: number; width: number; height: number };
/** A page as plain text, for the chat. */
export type BrowserPage = { url: string; title: string; text: string; cut: boolean };

/** What shows the pages: the desktop shell's second webview. */
export type BrowserHost = {
  /** Show the browser over an area; with `url` (an address, or words to search for) go there. */
  show: (area: BrowserArea, url?: string) => Promise<void>;
  /** Take it off the screen; the page stays as it is. */
  hide: () => void;
  /** Remove it: the session was left. */
  close: () => void;
  go: (to: "back" | "forward" | "reload" | "stop") => Promise<void>;
  /** The page that is shown, as plain text. */
  text: () => Promise<BrowserPage>;
  /** Told when the address changes and when a page begins and ends loading. */
  onChange: (told: (now: { url: string; loading: boolean }) => void) => () => void;
  /** Open an address in the person's own browser. */
  openOutside: (url: string) => void;
};

const say = (e: unknown, fallback: string) =>
  typeof e === "string" && e ? e : e instanceof Error && e.message ? e.message : fallback;

/** The most of a page that is put into one message. */
export const MAX_IN_MESSAGE = 12_000;

/** A page as the words that go into the message box. */
export function pageForChat(page: BrowserPage): string {
  const text =
    page.text.length > MAX_IN_MESSAGE ? `${page.text.slice(0, MAX_IN_MESSAGE)}\n[…]` : page.text;
  const cut = page.cut || page.text.length > MAX_IN_MESSAGE;
  return [
    `A page I am reading${page.title ? `, "${page.title}"` : ""} (${page.url})${
      cut ? ", its beginning" : ""
    }:`,
    "",
    "<page>",
    text,
    "</page>",
    "",
    "",
  ].join("\n");
}

/** Whether something of the window lies over the page's area: a dialog or an open menu. */
function covered(): boolean {
  return Boolean(document.querySelector('dialog[open], [role="menu"], [role="dialog"]'));
}

export function BrowserPane({
  host,
  shown,
  onAddToChat,
}: {
  host: BrowserHost | undefined;
  /** this tab is the one on the screen */
  shown: boolean;
  /** put a page's text into the message box and show the chat */
  onAddToChat: (words: string) => void;
}) {
  const [typed, setTyped] = useState("");
  const [url, setUrl] = useState("");
  const [loading, setLoading] = useState(false);
  const [adding, setAdding] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const area = useRef<HTMLDivElement>(null);
  const opened = useRef(false);
  const addressId = useId();

  const where = useCallback((): BrowserArea | null => {
    const box = area.current?.getBoundingClientRect();
    if (!box || box.width < 2 || box.height < 2) return null;
    return { x: box.left, y: box.top, width: box.width, height: box.height };
  }, []);

  // the page lies over this tab's area for as long as the tab is shown, a page was opened, and nothing
  // of the window is over it; it follows the area when the window or the layout changes
  useEffect(() => {
    if (!host) return;
    // the host is told only when something changed: the chat beside it changes the page all the time
    let last = "";
    const place = () => {
      const at = where();
      const on = shown && opened.current && at !== null && !covered();
      const now = on && at ? `${at.x},${at.y},${at.width},${at.height}` : "off";
      if (now === last) return;
      last = now;
      if (on && at) void host.show(at).catch(() => {});
      else host.hide();
    };
    place();
    const sizes = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(place);
    if (area.current) sizes?.observe(area.current);
    const over = new MutationObserver(place);
    over.observe(document.body, { childList: true, subtree: true, attributeFilter: ["open"] });
    window.addEventListener("resize", place);
    return () => {
      sizes?.disconnect();
      over.disconnect();
      window.removeEventListener("resize", place);
      host.hide();
    };
  }, [host, shown, where]);

  useEffect(() => {
    if (!host) return;
    const stop = host.onChange((now) => {
      setLoading(now.loading);
      if (now.url && now.url !== "about:blank") {
        setUrl(now.url);
        setTyped(now.url);
      }
    });
    return () => {
      stop();
      host.close(); // the session's page was left: the browser goes with it
    };
  }, [host]);

  if (!host)
    return (
      <EmptyState
        icon={Globe}
        title="The browser is part of the desktop app"
        text="In Wasify AI's own window this tab is a browser of your own beside the chat. The agent cannot open pages; it sees one only when you add it to the chat."
      />
    );

  const open = async (e: FormEvent) => {
    e.preventDefault();
    const at = where();
    if (!typed.trim() || !at) return;
    try {
      setProblem(null);
      opened.current = true;
      setLoading(true);
      await host.show(at, typed.trim());
    } catch (err) {
      setLoading(false);
      setProblem(say(err, "That page could not be opened."));
    }
  };
  const step = (to: "back" | "forward" | "reload" | "stop") =>
    void host.go(to).catch((err) => setProblem(say(err, "That did not work.")));
  const add = async () => {
    setAdding(true);
    try {
      setProblem(null);
      onAddToChat(pageForChat(await host.text()));
    } catch (err) {
      setProblem(say(err, "The page could not be added."));
    }
    setAdding(false);
  };

  return (
    <div className="flex h-full min-h-0 flex-col">
      <form onSubmit={open} className="flex flex-wrap items-center gap-1.5 border-b px-3 py-1.5">
        <Button
          type="button"
          size="icon"
          variant="ghost"
          aria-label="Back"
          disabled={!url}
          onClick={() => step("back")}
        >
          <ArrowLeft />
        </Button>
        <Button
          type="button"
          size="icon"
          variant="ghost"
          aria-label="Forward"
          disabled={!url}
          onClick={() => step("forward")}
        >
          <ArrowRight />
        </Button>
        {loading ? (
          <Button
            type="button"
            size="icon"
            variant="ghost"
            aria-label="Stop loading"
            onClick={() => step("stop")}
          >
            <X />
          </Button>
        ) : (
          <Button
            type="button"
            size="icon"
            variant="ghost"
            aria-label="Load again"
            disabled={!url}
            onClick={() => step("reload")}
          >
            <RotateCw />
          </Button>
        )}
        <label htmlFor={addressId} className="sr-only">
          An address, or words to search for
        </label>
        <Input
          id={addressId}
          value={typed}
          onChange={(e) => setTyped(e.target.value)}
          onFocus={(e) => e.target.select()}
          placeholder="An address, or words to search for"
          autoCapitalize="off"
          autoCorrect="off"
          spellCheck={false}
          className="min-w-40 flex-1"
        />
        {loading ? <Spinner className="size-3.5" /> : null}
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={!url || adding}
          onClick={() => void add()}
        >
          <MessageSquarePlus /> <span className="hidden xl:inline">Add this page to the chat</span>
          <span className="sr-only xl:hidden">Add this page to the chat</span>
        </Button>
        <Button
          type="button"
          size="icon"
          variant="ghost"
          aria-label="Open in your own browser"
          title="Open in your own browser"
          disabled={!url}
          onClick={() => host.openOutside(url)}
        >
          <ExternalLink />
        </Button>
      </form>
      {problem ? (
        <p role="alert" className="m-0 border-b px-3 py-1.5 text-sm text-destructive">
          {problem}
        </p>
      ) : null}
      <div ref={area} className="min-h-0 flex-1" data-slot="browser-area">
        {url ? null : (
          <EmptyState
            icon={Globe}
            title="A browser of your own"
            text="Type an address or a few words above to look something up while you work. Searches go to DuckDuckGo."
          />
        )}
      </div>
      <p className="m-0 border-t px-3 py-1.5 text-xs text-muted-foreground">
        This browser is yours. The agent cannot open pages or reach the internet; it sees a page
        only when you add it to the chat.
      </p>
    </div>
  );
}
