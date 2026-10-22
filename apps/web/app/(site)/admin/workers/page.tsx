import { Notice } from "@/components/Notice";
import { WorkersPanel } from "@/components/admin/WorkersPanel";
import { apiGet } from "@/lib/api";
import { muted } from "@/lib/styles";
import type { WorkerInfo } from "@wasifyai/client";
import type { Metadata } from "next";

export const metadata: Metadata = { title: "Workers" };
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
      <p className={muted}>
        Workers run the heavy work: voices, music, lip sync, 3D and Video Builder. Get a model onto
        a worker here; it downloads and checks the files itself, and people can choose it on their
        screens as soon as it is there. A worker does one job at a time, so a big download makes
        other work wait.
      </p>
      <WorkersPanel initial={workers} />
    </>
  );
}
