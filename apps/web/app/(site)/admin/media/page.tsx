import { Notice } from "@/components/Notice";
import { ServiceKeys } from "@/components/admin/ServiceKeys";
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
      {/* the web runs only cloud models (ADR-0099; ADR-0100, CP11): the service's keys and each product's model */}
      <ServiceKeys />
      <section aria-labelledby="media-other" className="grid gap-4">
        <h2 id="media-other" className="font-semibold text-lg">
          Other services
        </h2>
        <p className={muted}>
          A picture or clip with no cloud model above can be sent to Comfy Cloud or an
          OpenAI-compatible picture service instead, per tool. The cloud models above come first.
        </p>
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
      </section>
    </>
  );
}
