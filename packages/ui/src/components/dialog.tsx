"use client";

import { type FormEvent, type ReactNode, useEffect, useId, useRef, useState } from "react";
import { cn } from "../cn";
import { Button } from "./button";

/**
 * A modal box on the page, made of the browser's own `<dialog>` (focus stays inside, Escape closes it).
 * The desktop window cannot show `window.confirm` or `window.prompt` (its web view has no handler for
 * them, so they answer "no" at once), so every question to the person goes through these.
 */
export function Modal({
  label,
  onClose,
  children,
  wide,
}: {
  label: string;
  onClose: () => void;
  children: ReactNode;
  /** room for a whole tool (Make a voice), not just a question */
  wide?: boolean;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const labelId = useId();
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (typeof el.showModal === "function") el.showModal();
    else el.setAttribute("open", "");
  }, []);
  return (
    // biome-ignore lint/a11y/useKeyWithClickEvents: a click on the backdrop is a mouse shortcut; Escape closes it through the dialog's own cancel event
    <dialog
      ref={ref}
      aria-labelledby={labelId}
      onCancel={(e) => {
        e.preventDefault();
        onClose();
      }}
      onClick={(e) => {
        if (e.target === ref.current) onClose(); // a click on the dimmed page behind
      }}
      className={cn(
        "m-auto rounded-xl border bg-background p-0 text-foreground shadow-card",
        wide
          ? "max-h-[calc(100dvh-4rem)] w-[min(44rem,calc(100vw-2rem))] overflow-auto"
          : "w-[min(28rem,calc(100vw-2rem))]",
        "backdrop:bg-foreground/40",
      )}
    >
      <div className="grid gap-4 p-5">
        <h2 id={labelId} className="font-semibold text-lg">
          {label}
        </h2>
        {children}
      </div>
    </dialog>
  );
}

/** "Delete this?": a question with a way out. The confirm button says what it does. */
export function ConfirmDialog({
  title,
  message,
  confirmLabel = "Delete",
  destructive = true,
  onConfirm,
  onCancel,
}: {
  title: string;
  message?: ReactNode;
  confirmLabel?: string;
  destructive?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  return (
    <Modal label={title} onClose={onCancel}>
      {message ? <p className="m-0 text-muted-foreground">{message}</p> : null}
      <div className="flex flex-wrap justify-end gap-2">
        <Button type="button" variant="outline" onClick={onCancel}>
          Cancel
        </Button>
        <Button
          type="button"
          variant={destructive ? "destructive" : "default"}
          onClick={onConfirm}
          autoFocus
        >
          {confirmLabel}
        </Button>
      </div>
    </Modal>
  );
}

/** "Name this": one line of text, filled in with the current name. Empty or unchanged does nothing. */
export function NameDialog({
  title,
  label,
  initial,
  confirmLabel = "Save",
  onSubmit,
  onCancel,
}: {
  title: string;
  label: string;
  initial: string;
  confirmLabel?: string;
  onSubmit: (name: string) => void;
  onCancel: () => void;
}) {
  const id = useId();
  const [value, setValue] = useState(initial);
  const next = value.trim();
  function submit(e: FormEvent) {
    e.preventDefault();
    if (next && next !== initial) onSubmit(next);
    else onCancel();
  }
  return (
    <Modal label={title} onClose={onCancel}>
      <form className="grid gap-4" onSubmit={submit}>
        <label htmlFor={id} className="grid gap-1.5 text-sm">
          <span className="text-muted-foreground">{label}</span>
          <input
            id={id}
            // biome-ignore lint/a11y/noAutofocus: the dialog exists to type a name
            autoFocus
            value={value}
            maxLength={200}
            onChange={(e) => setValue(e.target.value)}
            onFocus={(e) => e.currentTarget.select()}
            className="h-10 rounded-md border bg-transparent px-3 text-base outline-none focus-visible:ring-2 focus-visible:ring-ring"
          />
        </label>
        <div className="flex flex-wrap justify-end gap-2">
          <Button type="button" variant="outline" onClick={onCancel}>
            Cancel
          </Button>
          <Button type="submit" disabled={!next}>
            {confirmLabel}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
