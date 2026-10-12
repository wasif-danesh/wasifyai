import { Notice } from "@/components/Notice";
import { SafeguardsForm } from "@/components/admin/SafeguardsForm";
import { apiGet } from "@/lib/api";
import { muted } from "@/lib/styles";
import type { SafeguardsStatus } from "@wasifyai/contracts";
import type { Metadata } from "next";

export const metadata: Metadata = { title: "Safeguards" };
export const dynamic = "force-dynamic";

export default async function Safeguards() {
  let status: SafeguardsStatus | null = null;
  try {
    status = await apiGet<SafeguardsStatus>("/admin/safeguards");
  } catch {
    // shown below
  }
  if (!status) {
    return (
      <Notice tone="error" title="Couldn't load the safeguards setting">
        The service isn't answering, or you aren't allowed to see this.
      </Notice>
    );
  }
  return (
    <>
      <p className={muted}>
        One switch for the whole system. With the safeguards on, every request is checked by the
        content moderator and the per-user quotas apply. With them off, neither applies. Upload
        checks, sign-in and the one-job-at-a-time rule always apply.
      </p>
      <SafeguardsForm enabled={status.enabled} forced={status.forced} />
    </>
  );
}
