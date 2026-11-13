"use client";

import type { TrainBase } from "@wasifyai/client";
import { ChevronDown } from "lucide-react";
import { Popover as PopoverPrimitive } from "radix-ui";
import { type ReactNode, useId, useState } from "react";
import { cn } from "../cn";
import { Button } from "../components/button";
import { ReadyDot } from "../models/marks";
import { field, fieldLabel, hint } from "../styles";

function stateLine(b: TrainBase): string {
  if (!b.can_teach) return b.reason || "Cannot be taught yet";
  return b.installed ? "On this computer" : "To download before teaching";
}

/**
 * "Model to teach" (ADR-0073, amendment 2026-11-07, owner): the model a training card teaches, chosen on the card
 * itself from a drop-down under the button, the same on pictures, video, writing and decisions. Every model that can
 * be taught is a row, with what it is good for and what a real run measured; one on this computer that cannot be
 * taught is listed with the reason, never offered. `below` holds what the card shows for the chosen model (getting
 * it, with its size and progress).
 */
export function TeachModelSelect({
  bases,
  chosen,
  onPick,
  below,
  disabled,
}: {
  bases: TrainBase[];
  chosen: string;
  onPick: (id: string) => void;
  below?: ReactNode;
  disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const labelId = useId();
  const panelId = useId();
  const row = bases.find((b) => b.id !== "" && b.id === chosen) ?? null;
  const offered = bases.filter((b) => b.id !== "" && b.can_teach).length;
  if (bases.length === 0) return null;
  return (
    <div className={field}>
      <span id={labelId} className={fieldLabel}>
        Model to teach
      </span>
      <div>
        <PopoverPrimitive.Root open={open} onOpenChange={setOpen}>
          <PopoverPrimitive.Trigger asChild>
            <Button
              type="button"
              variant="outline"
              className="max-w-full"
              disabled={disabled}
              aria-labelledby={`${labelId} ${panelId}-value`}
            >
              <ReadyDot state={!row ? "none" : row.installed ? "ready" : "needs"} />
              <span id={`${panelId}-value`} className="min-w-0 max-w-[18rem] truncate">
                {row?.title ?? "Choose a model"}
              </span>
              <ChevronDown className="size-4" aria-hidden="true" />
            </Button>
          </PopoverPrimitive.Trigger>
          <PopoverPrimitive.Portal>
            <PopoverPrimitive.Content
              id={panelId}
              aria-label="Models that can be taught"
              align="start"
              sideOffset={6}
              collisionPadding={16}
              className="z-50 grid max-h-[min(34rem,var(--radix-popover-content-available-height))] w-[min(28rem,calc(100vw-2rem))] grid-cols-[minmax(0,1fr)] content-start gap-1 overflow-y-auto rounded-xl border bg-popover p-2 text-popover-foreground shadow-card"
            >
              <ul className="m-0 grid list-none gap-1 p-0" aria-label="Models that can be taught">
                {bases.map((b) => {
                  const can = b.id !== "" && b.can_teach;
                  return (
                    <li key={b.id || b.title}>
                      <button
                        type="button"
                        disabled={!can}
                        aria-current={b.id === chosen ? "true" : undefined}
                        className={cn(
                          "grid w-full grid-cols-[minmax(0,1fr)] gap-0.5 rounded-lg px-3 py-2 text-start outline-none transition-colors hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60 disabled:hover:bg-transparent",
                          b.id !== "" && b.id === chosen && "bg-accent",
                        )}
                        onClick={() => {
                          onPick(b.id);
                          setOpen(false);
                        }}
                      >
                        <span className="flex items-center gap-2">
                          <span className="min-w-0 flex-1 truncate font-medium text-sm">
                            {b.title}
                          </span>
                          {b.recommended ? (
                            <span className="rounded-full border px-2 py-0.5 text-xs">
                              Recommended
                            </span>
                          ) : null}
                        </span>
                        {can && b.note ? (
                          <span className="text-muted-foreground text-sm [overflow-wrap:anywhere]">
                            {b.note}
                          </span>
                        ) : null}
                        {can && b.measured ? (
                          <span className="text-muted-foreground text-xs [overflow-wrap:anywhere]">
                            Measured here: {b.measured}.
                          </span>
                        ) : null}
                        <span
                          className={cn(
                            "flex items-center gap-1.5 text-xs",
                            can && b.installed ? "text-ok" : "text-muted-foreground",
                          )}
                        >
                          <ReadyDot state={!can ? "cannot" : b.installed ? "ready" : "needs"} />
                          {stateLine(b)}
                        </span>
                      </button>
                    </li>
                  );
                })}
              </ul>
              {offered < 2 ? (
                <p className={cn(hint, "m-0 px-3 py-1")}>
                  This is the only model that can be taught for this yet. More come as they are
                  measured on this computer.
                </p>
              ) : null}
            </PopoverPrimitive.Content>
          </PopoverPrimitive.Portal>
        </PopoverPrimitive.Root>
      </div>
      {row?.note ? <p className={cn(hint, "m-0")}>{row.note}</p> : null}
      {below}
    </div>
  );
}
