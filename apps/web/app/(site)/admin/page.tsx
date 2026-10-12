import { Notice } from "@/components/Notice";
import { DailyEventsTable, UsageTotalsTable } from "@/components/admin/tables";
import { TextLink } from "@/components/ui/text-link";
import { apiGet } from "@/lib/api";
import { pager } from "@/lib/styles";
import type { UsageReport } from "@wasifyai/contracts";

export const dynamic = "force-dynamic";

const PERIODS = [1, 7, 30];

export default async function Overview({
  searchParams,
}: {
  searchParams: Promise<{ days?: string }>;
}) {
  const requested = Number((await searchParams).days);
  const days = PERIODS.includes(requested) ? requested : 7;
  let report: UsageReport | null = null;
  try {
    report = await apiGet<UsageReport>(`/admin/usage?days=${days}`);
  } catch {
    // shown below
  }
  if (!report) {
    return (
      <Notice tone="error" title="Couldn't load usage">
        The service isn't answering right now.
      </Notice>
    );
  }
  return (
    <>
      <p className={pager}>
        Last{" "}
        {PERIODS.map((p) => (
          <TextLink
            key={p}
            href={`/admin?days=${p}`}
            aria-current={p === days ? "true" : undefined}
          >
            {p === 1 ? "24 hours" : `${p} days`}
          </TextLink>
        ))}
      </p>
      <UsageTotalsTable
        caption={`Usage, last ${days} day${days === 1 ? "" : "s"}`}
        rows={report.totals}
      />
      <DailyEventsTable rows={report.daily} />
    </>
  );
}
