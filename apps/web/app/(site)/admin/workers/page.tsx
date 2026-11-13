import { Notice } from "@/components/Notice";
import { ModelsAdmin } from "@/components/models/ModelsAdmin";
import { TrainersAdmin } from "@/components/models/TrainersAdmin";
import { apiGet } from "@/lib/api";
import { muted } from "@/lib/styles";
import type { WorkerInfo } from "@wasifyai/client";
import type { Metadata } from "next";

export const metadata: Metadata = { title: "Models and workers" };
export const dynamic = "force-dynamic";

export default async function Workers() {
  let workers: WorkerInfo[] | null = null;
  try {
    workers = (await apiGet<{ workers: WorkerInfo[] }>("/admin/workers")).workers;
  } catch {
    // shown below
  }
  if (!workers) {
    return (
      <Notice tone="error" title="Couldn't load the workers">
        This deployment has no engine workers, the service isn't answering, or you aren't allowed to
        see this.
      </Notice>
    );
  }
  return (
    <>
      <section aria-label="Workers" className="grid gap-1">
        <p className={muted}>
          Workers run the heavy work: voices, music, lip sync, 3D and Motion graphics. A worker does
          one job at a time, so a big download makes other work wait.
        </p>
        {workers.length === 0 ? (
          <output className={`${muted} block`}>
            No worker is running. Start one with <code>scripts/worker.sh start</code> (or run the
            worker image), and it appears here within a few seconds.
          </output>
        ) : (
          <ul className="m-0 grid list-none gap-1 p-0 text-sm">
            {workers.map((w) => (
              <li key={w.id}>
                <span className="font-medium">{w.id}</span>{" "}
                <span className={muted}>{w.busy ? "busy" : "idle"}</span>
              </li>
            ))}
          </ul>
        )}
      </section>
      <TrainersAdmin workers={workers} />
      <ModelsAdmin />
    </>
  );
}
