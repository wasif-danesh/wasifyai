import { cn } from "@/lib/utils";
import Link from "next/link";

const STILL = [0.5, 0.9, 0.65, 0.4];
const MOVING = [
  { delay: "0s", duration: "1.1s" },
  { delay: "-0.35s", duration: "0.9s" },
  { delay: "-0.7s", duration: "1.3s" },
  { delay: "-0.2s", duration: "1s" },
];

/** The equaliser mark: four bars that dance, or stand still where motion would distract. `mark` is the logo's dark tile. */
export function Equaliser({ still = false, mark = false }: { still?: boolean; mark?: boolean }) {
  return (
    <span
      aria-hidden="true"
      data-still={still || undefined}
      className={cn(
        "inline-flex items-end gap-0.5",
        mark
          ? "size-[1.55rem] items-center gap-[0.12rem] rounded-lg bg-foreground p-[0.3rem]"
          : "h-[1.4rem] w-[1.4rem]",
      )}
    >
      {MOVING.map((m, i) => (
        <i
          key={m.delay}
          className={cn(
            "block h-full flex-1 origin-bottom rounded-[2px] animate-eq",
            mark ? "bg-brand-3" : "bg-linear-to-t from-primary to-brand-2",
          )}
          style={
            still
              ? { animation: "none", scale: `1 ${STILL[i]}` }
              : { scale: "1 0.35", animationDelay: m.delay, animationDuration: m.duration }
          }
        />
      ))}
    </span>
  );
}

export function Logo() {
  return (
    <Link
      href="/"
      className="inline-flex items-center gap-[0.65rem] text-[1.15rem] font-bold tracking-[-0.02em] whitespace-nowrap text-foreground no-underline hover:text-foreground"
      aria-label="WasifyAI Studio, home"
    >
      <Equaliser still mark />
      <span>WasifyAI Studio</span>
    </Link>
  );
}
