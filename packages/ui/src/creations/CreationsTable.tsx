"use client";

import {
  type ColumnDef,
  type SortingState,
  flexRender,
  getCoreRowModel,
  getSortedRowModel,
  useReactTable,
} from "@tanstack/react-table";
import { ArrowDown, ArrowUp, ArrowUpDown } from "lucide-react";
import { useMemo, useState } from "react";
import { Badge } from "../components/badge";
import { Button } from "../components/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../components/table";
import { NavLink } from "./NavLink";
import { timeAgo } from "./format";
import { type CreationsNav, type Entry, type Row, toRow } from "./model";

function SortHeader({
  label,
  sorted,
  onClick,
}: {
  label: string;
  sorted: false | "asc" | "desc";
  onClick: () => void;
}) {
  const Icon = sorted === "asc" ? ArrowUp : sorted === "desc" ? ArrowDown : ArrowUpDown;
  return (
    <Button variant="ghost" size="sm" className="-ms-3" onClick={onClick}>
      {label}
      <Icon aria-hidden="true" className="opacity-60" />
    </Button>
  );
}

function columnsFor(nav: CreationsNav): ColumnDef<Row>[] {
  return [
    {
      accessorKey: "kindLabel",
      header: ({ column }) => (
        <SortHeader
          label="Type"
          sorted={column.getIsSorted()}
          onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}
        />
      ),
      cell: ({ row }) => <Badge variant="secondary">{row.original.kindLabel}</Badge>,
    },
    {
      accessorKey: "title",
      header: "What it is",
      enableSorting: false,
      cell: ({ row }) => (
        <div className="grid max-w-[36ch] gap-0.5 sm:max-w-[60ch]">
          <NavLink
            nav={nav}
            to={row.original.entry}
            className="truncate font-medium hover:underline"
          >
            {row.original.title}
          </NavLink>
          {row.original.detail ? (
            <span className="truncate text-sm text-muted-foreground">{row.original.detail}</span>
          ) : null}
        </div>
      ),
    },
    {
      accessorKey: "status",
      header: "Status",
      enableSorting: false,
      cell: ({ row }) =>
        row.original.status === "working" ? (
          <Badge variant="outline">Making…</Badge>
        ) : row.original.status === "failed" ? (
          <Badge variant="destructive">Couldn't be made</Badge>
        ) : (
          <span className="text-muted-foreground">Ready</span>
        ),
    },
    {
      accessorKey: "createdAt",
      sortingFn: (a, b) => Date.parse(a.original.createdAt) - Date.parse(b.original.createdAt),
      header: ({ column }) => (
        <SortHeader
          label="Made"
          sorted={column.getIsSorted()}
          onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}
        />
      ),
      cell: ({ row }) => (
        <time dateTime={row.original.createdAt} className="whitespace-nowrap text-muted-foreground">
          {timeAgo(row.original.createdAt)}
        </time>
      ),
    },
  ];
}

/** My creations as a sortable table (ADR-0045): the same entries as the cards, in rows. */
export function CreationsTable({ entries, nav }: { entries: Entry[]; nav: CreationsNav }) {
  const data = useMemo(() => entries.map(toRow), [entries]);
  const columns = useMemo(() => columnsFor(nav), [nav]);
  const [sorting, setSorting] = useState<SortingState>([]);
  const table = useReactTable({
    data,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getRowId: (row) => row.key,
    // the list arrives newest first; clicking a header changes that, clicking again reverses it
    enableSortingRemoval: true,
  });
  return (
    <div className="overflow-x-auto rounded-lg border bg-card">
      <Table>
        <TableHeader>
          {table.getHeaderGroups().map((group) => (
            <TableRow key={group.id}>
              {group.headers.map((header) => (
                <TableHead
                  key={header.id}
                  aria-sort={
                    header.column.getIsSorted() === "asc"
                      ? "ascending"
                      : header.column.getIsSorted() === "desc"
                        ? "descending"
                        : undefined
                  }
                >
                  {header.isPlaceholder
                    ? null
                    : flexRender(header.column.columnDef.header, header.getContext())}
                </TableHead>
              ))}
            </TableRow>
          ))}
        </TableHeader>
        <TableBody>
          {table.getRowModel().rows.map((row) => (
            <TableRow key={row.id}>
              {row.getVisibleCells().map((cell) => (
                <TableCell key={cell.id}>
                  {flexRender(cell.column.columnDef.cell, cell.getContext())}
                </TableCell>
              ))}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
