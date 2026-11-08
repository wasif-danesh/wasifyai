import { Notice } from "@/components/Notice";
import { MediaModelChoice } from "@/components/admin/MediaModelChoice";
import { MediaTable } from "@/components/admin/tables";
import { TableCell, TableHead, TableRow } from "@/components/ui/table";
import { TextLink } from "@/components/ui/text-link";
import { apiGet } from "@/lib/api";
import { fullDate } from "@/lib/format";
import { muted } from "@/lib/styles";
import type { MediaList, ProductModels } from "@wasifyai/contracts";
import type { Metadata } from "next";

export const metadata: Metadata = { title: "Media" };
export const dynamic = "force-dynamic";

export default async function Media() {
  let list: MediaList | null = null;
  let choices: ProductModels[] = [];
  try {
    [list, choices] = await Promise.all([
      apiGet<MediaList>("/admin/media"),
      apiGet<ProductModels[]>("/admin/media/models").catch(() => []),
    ]);
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
      {choices.length ? (
        <section aria-labelledby="media-models" className="grid gap-4">
          <h2 id="media-models" className="font-semibold text-lg">
            Models
          </h2>
          <p className={muted}>
            Images and Video can run several models. Choose the one each uses; its files must be on
            the ComfyUI host (<code>python -m wasifyai_api.comfy_models</code>).
          </p>
          <div className="grid gap-4 md:grid-cols-2">
            {choices.map((c) => (
              <MediaModelChoice key={c.product_id} choice={c} />
            ))}
          </div>
        </section>
      ) : null}
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
