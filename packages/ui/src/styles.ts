// Class strings shared by many screens (Tailwind utilities, our design tokens). Not CSS: just names that go in className.

/** The raised surface the studio puts forms and results on. It slides in when it first appears. */
export const panel =
  "grid gap-[1.1rem] rounded-lg border bg-surface p-[clamp(1.1rem,2.5vw,1.75rem)] shadow-card transition-[opacity,translate] duration-[450ms] ease-out-soft starting:translate-y-3.5 starting:opacity-0";

/** A small capital label above a heading. */
export const eyebrow =
  "text-step--1 font-semibold tracking-[0.08em] text-muted-foreground uppercase";

/** The centred column every page sits in (on the home page it has more room above). */
export const page =
  "mx-auto grid w-[min(100%-2rem,70rem)] gap-(--space) pt-[clamp(1.5rem,4vw,3.5rem)] pb-20 sm:w-[min(100%-3rem,70rem)] has-[[data-home]]:gap-0 has-[[data-home]]:pt-[clamp(2.75rem,7vw,5rem)] has-[[data-home]]:pb-14";

/** A row of buttons or small controls that wraps on a narrow screen. */
export const actions = "flex flex-wrap items-center gap-2.5";

/** A link that looks like a quiet button with a back arrow. */
export const backLink =
  "-ms-2.5 inline-flex items-center gap-1.5 justify-self-start rounded-[0.65rem] py-1.5 ps-2.5 pe-3 font-semibold text-muted-foreground no-underline transition-colors hover:bg-accent hover:text-foreground";

/** An empty-state block: icon or art, a heading, a line and an action, centred. */
export const empty =
  "grid justify-items-center gap-3 py-12 text-center text-muted-foreground [&_h1]:text-foreground [&_h2]:text-foreground";

/** The media player bar. */
export const player = "block h-12 w-full rounded-full accent-primary";

/** The cover or picture tile used by the library cards and the song page. */
export const coverTile =
  "aspect-square w-full rounded-lg bg-linear-to-br from-primary to-brand-2 object-cover";

/** A form field: label, control and hint, stacked. */
export const field = "grid gap-1.5";
export const fieldLabel = "text-[0.95rem] font-semibold";
export const hint = "text-step--1 text-muted-foreground";
export const fieldError = "text-step--1 text-destructive";

/** A wrapping row of small controls or tags. */
export const chips = "flex flex-wrap gap-[0.45rem]";
export const tagRow = "flex flex-wrap gap-[0.35rem]";

/** The "12/500" character counter; it turns amber near the limit. */
export function counter(near: boolean) {
  return `text-step--1 tabular-nums ${near ? "text-warn" : "text-muted-foreground"}`;
}

/** "Last 7 days · Older": a row of small links where the current one is stronger. */
export const pager =
  "flex flex-wrap items-center gap-[0.6rem] text-muted-foreground [&_a[aria-current=true]]:font-semibold [&_a[aria-current=true]]:text-foreground";

/** Secondary text. */
export const muted = "text-muted-foreground";

/** Two lines of text, then an ellipsis. (Tailwind's own line-clamp does not clamp in current Chrome builds.) */
export const clamp2 =
  "overflow-hidden [-webkit-box-orient:vertical] [-webkit-line-clamp:2] [display:-webkit-box]";
