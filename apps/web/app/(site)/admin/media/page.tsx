import { Notice } from "@/components/Notice";
import { MediaTable } from "@/components/admin/tables";
import { TableCell, TableHead, TableRow } from "@/components/ui/table";
import { TextLink } from "@/components/ui/text-link";
import { apiGet } from "@/lib/api";
import { fullDate } from "@/lib/format";
import { muted } from "@/lib/styles";
import type { MediaList } from "@wasifyai/contracts";
import type { Metadata } from "next";

export const metadata: Metadata = { title: "Media" };
export const dynamic = "force-dynamic";

export default async function Media() {
  let list: MediaList | null = null;
  try {
    list = await apiGet<MediaList>("/admin/media");
  } catch {
    // shown below
  }
  if (!list) {
    return (
      <Notice tone="error" title="Couldn't load the media settings">
        The service isn't answering, or you aren't allowed to see this.
      </Notice>
    );
  }
  const label = new Map(list.backends.map((b) => [b.id, b.label]));
  return (
    <>
      <p className={muted}>
        Pictures, clips and music run on ComfyUI by default, speaking and 3D models on the engine
        workers. Point any of them at fal.ai, Comfy Cloud or another service instead; the next job
        uses it.
      </p>
      {list.secrets_ready ? null : (
        <Notice tone="warn" title="API keys can't be saved yet">
          Set MEDIA_SECRETS_KEY (run make setup) and restart the API and the worker. Backends that
          need no key still work.
        </Notice>
      )}
      <MediaTable
        rows={list.items.map((m) => ({
          product: m.product_id,
          capability: m.capability,
          workflow: m.workflow ?? "",
          runsOn: [label.get(m.backend) ?? m.backend, m.config.model].filter(Boolean).join(" · "),
          keySaved: m.key_set,
          keyProblem: m.check && !m.check.ok ? m.check.message : null,
          source: m.source,
          changed: m.updated_at && m.source === "custom" ? fullDate(m.updated_at) : "—",
        }))}
      />
    </>
  );
}
