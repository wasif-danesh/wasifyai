import { Button } from "@/components/ui/button";
import { eyebrow, panel } from "@/lib/styles";
import { cn } from "@/lib/utils";
import Link from "next/link";

/** The page behind a product card that is not built yet. */
export function ComingSoon({ title, children }: { title: string; children: string }) {
  return (
    <section className={cn(panel, "mx-auto max-w-[34rem] justify-items-start gap-[0.9rem]")}>
      <span className={eyebrow}>Coming soon</span>
      <h1 className="text-step-2 leading-[1.1] font-semibold tracking-[-0.025em]">{title}</h1>
      <p className="text-muted-foreground">{children}</p>
      <Button asChild variant="outline">
        <Link href="/">
          <span aria-hidden="true">←</span> Back to Wasify AI
        </Link>
      </Button>
    </section>
  );
}
