"use client";

import { MoreHorizontal, Pencil, Trash2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { cn } from "../cn";
import { ConfirmDialog, NameDialog } from "../components/dialog";

/** One recent chat. `rename` and `remove` are left out where the app cannot do them: no menu then. */
export type RecentChat = {
  id: string;
  title: string;
  current?: boolean;
  onSelect: () => void;
  rename?: (name: string) => void | Promise<void>;
  remove?: () => void | Promise<void>;
};

export type Recents = {
  label?: string;
  empty?: string;
  items: RecentChat[];
};

const ITEM =
  "flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left text-ui-lg outline-none transition-colors hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring";
const MENU_ITEM =
  "flex w-full items-center gap-2 rounded-md px-2.5 py-1.5 text-left text-sm outline-none hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring";

/**
 * The recent chats: each opens on a click; a "⋯" button (and a right click) offers Rename and Delete.
 * The questions are the app's own dialogs, because the desktop window shows no browser prompts.
 */
export function RecentChats({ recents }: { recents: Recents }) {
  const [menu, setMenu] = useState<string | null>(null);
  const [asking, setAsking] = useState<{ kind: "rename" | "delete"; chat: RecentChat } | null>(
    null,
  );
  const [failed, setFailed] = useState<string | null>(null);
  const root = useRef<HTMLDivElement>(null);

  // a click outside the menu or Escape closes it
  useEffect(() => {
    if (menu === null) return;
    const down = (e: MouseEvent) => {
      if (root.current && !root.current.contains(e.target as Node)) setMenu(null);
    };
    const key = (e: KeyboardEvent) => e.key === "Escape" && setMenu(null);
    document.addEventListener("mousedown", down);
    document.addEventListener("keydown", key);
    return () => {
      document.removeEventListener("mousedown", down);
      document.removeEventListener("keydown", key);
    };
  }, [menu]);

  async function run(work: () => void | Promise<void>, problem: string) {
    setFailed(null);
    try {
      await work();
    } catch {
      setFailed(problem);
    }
  }

  return (
    <div ref={root}>
      <div className="mt-4 px-3 text-muted-foreground text-sm">{recents.label ?? "Recents"}</div>
      {recents.items.length === 0 ? (
        <div className="px-3 py-1 text-muted-foreground/80 text-sm">
          {recents.empty ?? "No chats yet"}
        </div>
      ) : (
        <ul className="grid grid-cols-[minmax(0,1fr)] gap-0.5" aria-label="Recent chats">
          {recents.items.map((c) => {
            const has = Boolean(c.rename || c.remove);
            const open = menu === c.id;
            return (
              <li
                key={c.id}
                className="group relative min-w-0"
                onContextMenu={(e) => {
                  if (!has) return;
                  e.preventDefault();
                  setMenu(c.id);
                }}
              >
                <button
                  type="button"
                  title={c.title}
                  aria-current={c.current ? "page" : undefined}
                  className={cn(ITEM, "py-1.5 text-ui", has && "pe-9", c.current && "bg-accent")}
                  onClick={c.onSelect}
                >
                  <span className="truncate">{c.title || "New chat"}</span>
                </button>
                {has ? (
                  <button
                    type="button"
                    aria-label={`Options for ${c.title || "New chat"}`}
                    aria-haspopup="menu"
                    aria-expanded={open}
                    className={cn(
                      "absolute end-1 top-1/2 -translate-y-1/2 rounded-md p-1.5 text-muted-foreground outline-none hover:bg-background focus-visible:opacity-100 focus-visible:ring-2 focus-visible:ring-ring",
                      open
                        ? "opacity-100"
                        : "opacity-0 group-focus-within:opacity-100 group-hover:opacity-100",
                    )}
                    onClick={() => setMenu(open ? null : c.id)}
                  >
                    <MoreHorizontal className="size-4" aria-hidden="true" />
                  </button>
                ) : null}
                {open ? (
                  <div
                    role="menu"
                    aria-label={`Options for ${c.title || "New chat"}`}
                    className="absolute end-1 top-full z-30 mt-1 grid w-40 gap-0.5 rounded-lg border bg-background p-1 shadow-card"
                  >
                    {c.rename ? (
                      <button
                        type="button"
                        role="menuitem"
                        className={MENU_ITEM}
                        onClick={() => {
                          setMenu(null);
                          setAsking({ kind: "rename", chat: c });
                        }}
                      >
                        <Pencil className="size-4" aria-hidden="true" /> Rename
                      </button>
                    ) : null}
                    {c.remove ? (
                      <button
                        type="button"
                        role="menuitem"
                        className={cn(MENU_ITEM, "text-destructive")}
                        onClick={() => {
                          setMenu(null);
                          setAsking({ kind: "delete", chat: c });
                        }}
                      >
                        <Trash2 className="size-4" aria-hidden="true" /> Delete
                      </button>
                    ) : null}
                  </div>
                ) : null}
              </li>
            );
          })}
        </ul>
      )}
      {failed ? (
        <p role="alert" className="px-3 py-1 text-destructive text-sm">
          {failed}
        </p>
      ) : null}
      {asking?.kind === "rename" ? (
        <NameDialog
          title="Rename this chat"
          label="Name"
          initial={asking.chat.title}
          onSubmit={(name) => {
            const chat = asking.chat;
            setAsking(null);
            void run(() => chat.rename?.(name), "The chat could not be renamed.");
          }}
          onCancel={() => setAsking(null)}
        />
      ) : null}
      {asking?.kind === "delete" ? (
        <ConfirmDialog
          title="Delete this chat?"
          message={`“${asking.chat.title || "New chat"}” will be deleted. What it made stays in your library.`}
          onConfirm={() => {
            const chat = asking.chat;
            setAsking(null);
            void run(() => chat.remove?.(), "The chat could not be deleted.");
          }}
          onCancel={() => setAsking(null)}
        />
      ) : null}
    </div>
  );
}
