"use client";

import { Notice } from "@/components/Notice";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { useRouter } from "next/navigation";
import { useState } from "react";

export { FailedNotice, JobMeter, ModeTabs, PromptField, WorkingCard } from "@wasifyai/ui";

/** Delete with a second confirming click, then back to My creations. `noun` names the thing in the messages. */
export function DeleteControls({
  url,
  noun,
  label = "Delete",
}: {
  url: string;
  noun: string;
  label?: string;
}) {
  const router = useRouter();
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);

  async function remove() {
    setBusy(true);
    setFailed(false);
    try {
      const res = await fetch(url, { method: "DELETE" });
      if (!res.ok && res.status !== 404) throw new Error(String(res.status));
      router.push("/creations");
      router.refresh();
    } catch {
      setFailed(true);
      setBusy(false);
    }
  }

  return (
    <>
      {confirming ? (
        <>
          <Button type="button" variant="destructive" onClick={remove} disabled={busy}>
            {busy ? <Spinner /> : null}
            Yes, delete it
          </Button>
          <Button
            type="button"
            variant="outline"
            onClick={() => setConfirming(false)}
            disabled={busy}
          >
            Keep it
          </Button>
        </>
      ) : (
        <Button type="button" variant="outline" onClick={() => setConfirming(true)}>
          {label}
        </Button>
      )}
      {failed ? (
        <div className="basis-full">
          <Notice tone="error" title={`Couldn't delete that ${noun}`}>
            Try again in a moment.
          </Notice>
        </div>
      ) : null}
    </>
  );
}
