import { ProductCard } from "@/components/ProductCard";
import { PRODUCTS } from "@/lib/products";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: { absolute: "WasifyAI Studio" },
  description: "Turn your ideas into music, images and video.",
};

export default function Home() {
  return (
    <div data-home>
      <header className="grid justify-items-start gap-[0.85rem] pb-[1.8rem] text-start md:pb-9">
        <span className="inline-flex items-center gap-[0.65rem] text-step--1 font-bold tracking-[0.13em] text-muted-foreground uppercase before:size-[0.45rem] before:rounded-full before:bg-[oklch(74%_0.16_135)] before:shadow-[0_0_0_4px_color-mix(in_oklch,oklch(74%_0.16_135)_18%,transparent)] before:content-['']">
          Your creative space
        </span>
        <h1 className="text-[clamp(2rem,8vw,2.55rem)] leading-[1.02] font-[680] tracking-[-0.065em] md:text-[clamp(2.55rem,5.3vw,3.9rem)]">
          Bring Your{" "}
          <span
            data-accent
            className="bg-linear-to-r from-primary to-brand-2 bg-clip-text text-transparent"
          >
            Ideas
          </span>{" "}
          to Life
        </h1>
        <p className="max-w-[38rem] leading-normal text-muted-foreground">
          Create stunning images, immersive music, and captivating videos with the power of AI — all
          in one place.
        </p>
      </header>
      <div className="mb-[0.9rem] flex items-center justify-between gap-4">
        <h2 className="text-[0.95rem] font-semibold tracking-[-0.01em]">Choose your canvas</h2>
        <p className="text-step--1 text-muted-foreground max-[420px]:hidden">
          Pick a tool and make it yours
        </p>
      </div>
      <ul
        className="grid list-none grid-cols-1 gap-[1.05rem] p-0 md:grid-cols-[repeat(auto-fit,minmax(min(100%,18rem),1fr))]"
        aria-label="What you can make"
      >
        {PRODUCTS.map((p) => (
          <li key={p.id} className="grid">
            <ProductCard product={p} />
          </li>
        ))}
      </ul>
    </div>
  );
}
