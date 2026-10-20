"use client";

import type { ToolCallMessagePartProps } from "@assistant-ui/react";

/**
 * Where the assistant's `confirm_action` card will be (ADR-0071, stage CU2 with A2): the person approves or declines and the
 * answer goes back through the tool-result path. Until then the engine sends none; this keeps the name registered so a
 * paused run shows something sensible instead of nothing.
 */
export function ConfirmActionCard({ args }: ToolCallMessagePartProps) {
  const title = String(
    (args as { title?: unknown } | undefined)?.title ?? "Waiting for your answer",
  );
  return (
    <output className="grid gap-1 rounded-lg border p-3 text-sm">
      <span className="font-medium">{title}</span>
      <span className="text-muted-foreground">
        This step needs your answer, which this screen cannot take yet.
      </span>
    </output>
  );
}
