import { Notice } from "@/components/Notice";
import { ModelsTable } from "@/components/admin/tables";
import { TableCell, TableHead, TableRow } from "@/components/ui/table";
import { TextLink } from "@/components/ui/text-link";
import { apiGet } from "@/lib/api";
import { fullDate } from "@/lib/format";
import { muted } from "@/lib/styles";
import type { ModelList } from "@wasifyai/contracts";
import type { Metadata } from "next";

export const metadata: Metadata = { title: "Models" };
export const dynamic = "force-dynamic";

export default async function Models() {
  let list: ModelList | null = null;
  try {
    list = await apiGet<ModelList>("/admin/models");
  } catch {
    // shown below
  }
  if (!list) {
    return (
      <Notice tone="error" title="Couldn't load the models">
        The model gateway isn't answering, or you aren't allowed to see this.
      </Notice>
    );
  }
  const label = new Map(list.providers.map((p) => [p.id, p.label]));
  return (
    <>
      <p className={muted}>
        Each name below is what the products ask for. Point it at a local model or a hosted
        provider; changes apply to new requests at once.
      </p>
      <ModelsTable
        rows={list.models.map((m) => ({
          alias: m.alias,
          purpose: m.purpose,
          servedBy: m.provider
            ? `${label.get(m.provider) ?? m.provider} · ${m.model}`
            : "not set up yet",
          keySaved: m.key_set,
          source: m.source,
          changed: m.updated_at && m.source === "custom" ? fullDate(m.updated_at) : "—",
        }))}
      />
    </>
  );
}
