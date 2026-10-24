"use client";

import { Button } from "@/components/ui/button";
import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
} from "@/components/ui/command";
import { hrefOf } from "@/lib/creations-nav";
import { webCreations } from "@/lib/library";
import { PRODUCTS } from "@/lib/products";
import { longEnough, toRow, useCreationSearch } from "@wasifyai/ui";
import { Search } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

/** The search field in the top bar and the ⌘K palette behind it (ADR-0046): jump to a product or find a creation. */
export function CommandMenu() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const search = useCreationSearch(webCreations, open ? query : "", "all");
  const searching = longEnough(query);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key.toLowerCase() === "k" && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        setOpen((o) => !o);
      }
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  function go(href: string) {
    setOpen(false);
    setQuery("");
    router.push(href);
  }

  const needle = query.trim().toLowerCase();
  const places = [
    ...PRODUCTS.filter((p) => p.status === "live").map((p) => ({ label: p.title, href: p.href })),
    { label: "My creations", href: "/creations" },
  ].filter((p) => !needle || p.label.toLowerCase().includes(needle));

  return (
    <>
      <Button
        type="button"
        variant="outline"
        className="h-9 shrink-0 justify-start gap-2 text-muted-foreground sm:w-full sm:max-w-sm"
        onClick={() => setOpen(true)}
        aria-label="Search everything"
        aria-keyshortcuts="Control+K Meta+K"
      >
        <Search aria-hidden="true" />
        <span className="hidden truncate sm:inline">Search everything…</span>
        <kbd className="ms-auto hidden rounded border px-1.5 text-xs sm:inline">⌘K</kbd>
      </Button>
      <CommandDialog
        open={open}
        onOpenChange={setOpen}
        title="Search"
        description="Jump to a product, or search your creations by what they are about, in any language."
        shouldFilter={false}
      >
        <CommandInput
          value={query}
          onValueChange={setQuery}
          placeholder="Search your creations, or jump to a product…"
        />
        <CommandList>
          {searching && search.status === "searching" ? (
            <div className="py-6 text-center text-sm text-muted-foreground">Searching…</div>
          ) : null}
          {searching && search.status === "done" && search.entries.length === 0 ? (
            <CommandEmpty>Nothing matched “{search.query}”.</CommandEmpty>
          ) : null}
          {searching && search.status === "error" ? (
            <div className="py-6 text-center text-sm text-destructive">{search.message}</div>
          ) : null}
          {search.status === "done" && search.entries.length > 0 ? (
            <>
              <CommandGroup heading="Your creations">
                {search.entries.map((entry) => {
                  const row = toRow(entry);
                  return (
                    <CommandItem
                      key={row.key}
                      value={row.key}
                      onSelect={() => go(hrefOf(entry))}
                      className="gap-2"
                    >
                      <span className="shrink-0 text-xs text-muted-foreground">
                        {row.kindLabel}
                      </span>
                      <span className="truncate">{row.title}</span>
                    </CommandItem>
                  );
                })}
              </CommandGroup>
              <CommandSeparator />
            </>
          ) : null}
          {places.length > 0 ? (
            <CommandGroup heading="Go to">
              {places.map((p) => (
                <CommandItem key={p.href} value={p.href} onSelect={() => go(p.href)}>
                  {p.label}
                </CommandItem>
              ))}
            </CommandGroup>
          ) : null}
        </CommandList>
      </CommandDialog>
    </>
  );
}
