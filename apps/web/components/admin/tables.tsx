"use client";

import { DataTable, SortHeader } from "@/components/ui/data-table";
import { TextLink } from "@/components/ui/text-link";
import { muted } from "@/lib/styles";
import type { ColumnDef } from "@tanstack/react-table";
import type { ReactNode } from "react";

/** A sortable text or number column; `rowHeader` makes it the row's header cell. */
function col<T>(
  key: keyof T & string,
  label: string,
  opts: { rowHeader?: boolean; cell?: (row: T) => ReactNode } = {},
): ColumnDef<T> {
  return {
    accessorKey: key,
    header: ({ column }) => <SortHeader column={column} label={label} />,
    cell: ({ row }) => opts.cell?.(row.original) ?? String(row.original[key] ?? "—"),
    meta: { rowHeader: opts.rowHeader },
  };
}

/** A column that only shows something (a link, a button), with nothing to sort. */
function action<T>(label: string, cell: (row: T) => ReactNode): ColumnDef<T> {
  return {
    id: label,
    header: () => <span className="sr-only">{label}</span>,
    cell: ({ row }) => cell(row.original),
    enableSorting: false,
    enableGlobalFilter: false,
  };
}

const number = (n: number, digits = 0) => n.toLocaleString("en", { maximumFractionDigits: digits });

// ---------------------------------------------------------------- usage

export type TotalRow = { kind: string; events: number; quantity: number; unit: string };
export function UsageTotalsTable({ rows, caption }: { rows: TotalRow[]; caption: string }) {
  return (
    <DataTable
      caption={caption}
      filterLabel="Filter usage"
      empty="No usage in this period."
      data={rows}
      getRowId={(r) => `${r.kind}-${r.unit}`}
      columns={[
        col<TotalRow>("kind", "Kind", { rowHeader: true }),
        col<TotalRow>("events", "Events", { cell: (r) => number(r.events) }),
        col<TotalRow>("quantity", "Quantity", { cell: (r) => number(r.quantity, 2) }),
        col<TotalRow>("unit", "Unit"),
      ]}
    />
  );
}

export type DailyRow = { day: string; kind: string; events: number };
export function DailyEventsTable({ rows }: { rows: DailyRow[] }) {
  return (
    <DataTable
      caption="Events per day"
      filterLabel="Filter events"
      empty="Nothing yet."
      data={rows}
      getRowId={(r) => `${r.day}-${r.kind}`}
      columns={[
        col<DailyRow>("day", "Day", { rowHeader: true }),
        col<DailyRow>("kind", "Kind"),
        col<DailyRow>("events", "Events", { cell: (r) => number(r.events) }),
      ]}
    />
  );
}

// ---------------------------------------------------------------- users, audit

export type UserRow = {
  id: string;
  name: string;
  email: string;
  unverified: boolean;
  role: string;
  providers: string;
  joined: string; // formatted
  joinedAt: string; // for sorting
};
export function UsersTable({ rows, footer }: { rows: UserRow[]; footer?: ReactNode }) {
  return (
    <DataTable
      caption="Users, newest first"
      filterLabel="Filter users"
      empty="No users yet."
      data={rows}
      footer={footer}
      getRowId={(r) => r.id}
      columns={[
        col<UserRow>("name", "Name", { rowHeader: true }),
        col<UserRow>("email", "Email", {
          cell: (u) => (
            <>
              {u.email}
              {u.email !== "—" && u.unverified ? (
                <small className={muted}> unverified</small>
              ) : null}
            </>
          ),
        }),
        col<UserRow>("role", "Role"),
        col<UserRow>("providers", "Sign-in"),
        {
          ...col<UserRow>("joined", "Joined"),
          sortingFn: (a, b) => a.original.joinedAt.localeCompare(b.original.joinedAt),
        },
      ]}
    />
  );
}

export type AuditRow = {
  id: string;
  when: string;
  whenAt: string;
  who: string;
  action: string;
  detail: string;
};
export function AuditTable({ rows }: { rows: AuditRow[] }) {
  return (
    <DataTable
      caption="Admin actions, newest first"
      filterLabel="Filter the log"
      empty="Nothing recorded yet."
      data={rows}
      pageSizes={[25, 50, 100]}
      getRowId={(r) => r.id}
      columns={[
        {
          ...col<AuditRow>("when", "When", { rowHeader: true }),
          sortingFn: (a, b) => a.original.whenAt.localeCompare(b.original.whenAt),
        },
        col<AuditRow>("who", "Who"),
        col<AuditRow>("action", "Action"),
        col<AuditRow>("detail", "Detail", {
          cell: (r) => <code className="break-all">{r.detail}</code>,
        }),
      ]}
    />
  );
}

// ---------------------------------------------------------------- models and media

export type ModelRow = {
  alias: string;
  purpose: string;
  servedBy: string;
  keySaved: boolean;
  source: string;
  changed: string;
};
export function ModelsTable({ rows }: { rows: ModelRow[] }) {
  return (
    <DataTable
      caption="Model aliases"
      filterLabel="Filter models"
      data={rows}
      getRowId={(r) => r.alias}
      columns={[
        col<ModelRow>("alias", "Name", { rowHeader: true }),
        col<ModelRow>("purpose", "Used for"),
        col<ModelRow>("servedBy", "Served by", {
          cell: (m) => (
            <>
              {m.servedBy}
              {m.keySaved ? <small className={muted}> key saved</small> : null}
            </>
          ),
        }),
        col<ModelRow>("source", "Source"),
        col<ModelRow>("changed", "Changed"),
        action<ModelRow>("Edit", (m) => (
          <TextLink href={`/admin/models/${m.alias}`}>Edit</TextLink>
        )),
      ]}
    />
  );
}

export type MediaRow = {
  product: string;
  capability: string;
  workflow: string;
  runsOn: string;
  keySaved: boolean;
  /** the last test of the saved row, when it did not work: "Key not working" */
  keyProblem?: string | null;
  source: string;
  changed: string;
};
export function MediaTable({ rows }: { rows: MediaRow[] }) {
  return (
    <DataTable
      caption="Media capabilities"
      filterLabel="Filter capabilities"
      data={rows}
      getRowId={(r) => `${r.product}/${r.capability}`}
      columns={[
        col<MediaRow>("product", "Product", { rowHeader: true }),
        col<MediaRow>("capability", "Capability", {
          cell: (m) => (
            <>
              {m.capability}
              {m.workflow ? <small className={muted}> {m.workflow}</small> : null}
            </>
          ),
        }),
        col<MediaRow>("runsOn", "Runs on", {
          cell: (m) => (
            <>
              {m.runsOn}
              {m.keySaved ? <small className={muted}> key saved</small> : null}
              {m.keyProblem ? (
                <small className="block text-destructive">Key not working: {m.keyProblem}</small>
              ) : null}
            </>
          ),
        }),
        col<MediaRow>("source", "Source"),
        col<MediaRow>("changed", "Changed"),
        action<MediaRow>("Edit", (m) => (
          <TextLink href={`/admin/media/${m.product}/${m.capability}`}>Edit</TextLink>
        )),
      ]}
    />
  );
}
