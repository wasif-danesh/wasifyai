import { TextLink } from "@/components/ui/text-link";
import { muted } from "@/lib/styles";
import type { Metadata } from "next";

export const metadata: Metadata = { title: "Settings" };
export const dynamic = "force-dynamic";

type Row = { desktop: string; web: string; href?: string; note: string };

/** Where each section of the desktop's Settings page is on the web (docs/web-parity-ledger.md keeps the same table). */
const ROWS: Row[] = [
  {
    desktop: "Image generation",
    web: "Media",
    href: "/admin/media",
    note: "which backend makes images and video: the product's own workflow, Comfy Cloud or an images API",
  },
  {
    desktop: "Language models",
    web: "Models",
    href: "/admin/models",
    note: "what answers in chat and the other text jobs, with a test and a reset",
  },
  {
    desktop: "Finding models",
    web: "Models and workers",
    href: "/admin/workers",
    note: "the models each worker holds are listed there; a service has no folders to look in",
  },
  {
    desktop: "Browsing models (Hugging Face)",
    web: "Models and workers",
    href: "/admin/workers",
    note: "an admin gets a model onto a worker with its size shown first; there is no open-ended browsing on a service",
  },
  {
    desktop: "Searching the web",
    web: "Search",
    href: "/admin/search",
    note: "the search service and its key for everyone; each person allows it for themself",
  },
  {
    desktop: "Updates",
    web: "Not needed",
    note: "a service is updated by its deployment (new images), not from a page",
  },
  {
    desktop: "The engine (restart, repair)",
    web: "Not needed",
    note: "the engine and the workers are restarted by the deployment (Helm, Compose), not from a page",
  },
];

export default function Settings() {
  return (
    <>
      <p className={muted}>Every section of the desktop's Settings page and where it is here.</p>
      <table className="w-full text-start text-sm">
        <caption className="sr-only">
          The desktop's Settings, and where each section is on the web
        </caption>
        <thead>
          <tr className="border-b text-start">
            <th scope="col" className="py-2 pe-4 text-start font-medium">
              Desktop Settings
            </th>
            <th scope="col" className="py-2 pe-4 text-start font-medium">
              Here
            </th>
            <th scope="col" className="py-2 text-start font-medium">
              What it is
            </th>
          </tr>
        </thead>
        <tbody>
          {ROWS.map((r) => (
            <tr key={r.desktop} className="border-b align-top">
              <th scope="row" className="py-2 pe-4 text-start font-normal">
                {r.desktop}
              </th>
              <td className="py-2 pe-4">
                {r.href ? <TextLink href={r.href}>{r.web}</TextLink> : r.web}
              </td>
              <td className="py-2 text-muted-foreground">{r.note}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}
