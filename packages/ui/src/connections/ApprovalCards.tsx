"use client";
// The card an agent waits for (ADR-0069 decision 8): "Codex wants to make a picture". The engine raises an event on the
// window's stream; the pending list is read on open, so a card raised while the window was away is not lost. Allow and
// Deny go to the engine; the agent follows the answer with approval_status. Never "always": the connection's setting
// is changed in Settings, on purpose.
import type { ConnectionsApi, PendingApproval } from "@wasifyai/client";
import { useCallback, useEffect, useState } from "react";
import { Button } from "../components/button";

const RETRY_MS = 5000;

export function useApprovals(api: ConnectionsApi, enabled = true) {
  const [pending, setPending] = useState<PendingApproval[]>([]);
  const refresh = useCallback(() => {
    api
      .pendingApprovals()
      .then((r) => setPending(r.approvals))
      .catch(() => {});
  }, [api]);
  useEffect(() => {
    if (!enabled) return;
    refresh();
    const control = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    const listen = () => {
      api
        .events(() => refresh(), control.signal)
        .catch(() => {})
        .finally(() => {
          if (!control.signal.aborted) timer = setTimeout(listen, RETRY_MS);
        });
    };
    listen();
    return () => {
      control.abort();
      if (timer) clearTimeout(timer);
    };
  }, [api, enabled, refresh]);
  const decide = useCallback(
    async (approvalId: string, approved: boolean) => {
      setPending((ps) => ps.filter((p) => p.approval_id !== approvalId));
      try {
        await api.decide(approvalId, approved);
      } finally {
        refresh();
      }
    },
    [api, refresh],
  );
  return { pending, decide };
}

export function ApprovalCard({
  approval,
  onDecide,
}: {
  approval: PendingApproval;
  onDecide: (approved: boolean) => void;
}) {
  const title = `${approval.connection} wants to: ${approval.title}`;
  const params = Object.entries(approval.params).slice(0, 6);
  return (
    <section
      aria-label={title}
      className="grid gap-2 rounded-lg border bg-background p-3 text-sm shadow-lg"
    >
      <p className="m-0 font-medium">{title}</p>
      {approval.summary && approval.summary !== approval.title ? (
        <p className="m-0 text-muted-foreground">{approval.summary}</p>
      ) : null}
      {params.length ? (
        <dl className="m-0 grid gap-0.5">
          {params.map(([k, v]) => (
            <div key={k} className="flex gap-2">
              <dt className="shrink-0 text-muted-foreground">{k}</dt>
              <dd dir="auto" className="m-0 min-w-0 break-words">
                {String(v).length > 200 ? `${String(v).slice(0, 199)}…` : String(v)}
              </dd>
            </div>
          ))}
        </dl>
      ) : null}
      <div className="flex flex-wrap gap-2">
        <Button type="button" size="sm" onClick={() => onDecide(true)}>
          Allow once
        </Button>
        <Button type="button" size="sm" variant="outline" onClick={() => onDecide(false)}>
          Deny
        </Button>
      </div>
    </section>
  );
}

/** The cards, one above the other at the window's corner. */
export function ApprovalCards({ api, enabled = true }: { api: ConnectionsApi; enabled?: boolean }) {
  const { pending, decide } = useApprovals(api, enabled);
  if (!pending.length) return null;
  return (
    <div
      aria-live="polite"
      className="fixed right-4 bottom-4 z-40 grid max-w-sm gap-2"
      data-approval-cards=""
    >
      {pending.map((p) => (
        <ApprovalCard
          key={p.approval_id}
          approval={p}
          onDecide={(approved) => void decide(p.approval_id, approved)}
        />
      ))}
    </div>
  );
}
