import type { Product } from "@/lib/products";
import { cn } from "@/lib/utils";
import Link from "next/link";
import { ProductArt } from "./ProductArt";

/** One card on the home page; the whole card is the link. */
export function ProductCard({ product }: { product: Product }) {
  const live = product.status === "live";
  return (
    <Link
      href={product.href}
      data-product={product.id}
      data-status={product.status}
      className="group grid grid-rows-[auto_1fr] overflow-hidden rounded-xl border bg-surface p-[0.55rem] text-inherit no-underline transition-[translate,border-color,box-shadow] duration-[250ms] ease-out-soft hover:text-inherit hover:shadow-card data-[status=live]:hover:-translate-y-[3px] data-[status=live]:hover:border-primary/55"
    >
      <ProductArt id={product.id} />
      <div className="flex min-h-0 flex-col items-stretch px-[0.7rem] pt-4 pb-[0.35rem] md:min-h-[10.1rem]">
        <div className="flex items-center justify-between gap-3">
          <h2 className="text-step-1 font-semibold tracking-[-0.035em]">{product.title}</h2>
          <span
            className={cn(
              "shrink-0 rounded-full px-[0.55rem] py-[0.2rem] text-2xs font-semibold",
              live ? "bg-ok-soft text-ok-strong" : "bg-muted text-muted-foreground",
            )}
          >
            {live ? "Available" : "Coming soon"}
          </span>
        </div>
        <p className="mt-[0.45rem] text-step--1 leading-normal text-muted-foreground">
          {product.blurb}
        </p>
        <span
          className={cn(
            "mt-auto flex items-center justify-between gap-3 border-t pt-3 text-ui-sm font-semibold",
            !live && "text-muted-foreground",
          )}
        >
          {product.action}
          <span
            className={cn(
              "text-lead leading-none",
              live ? "text-primary" : "text-muted-foreground",
            )}
            aria-hidden="true"
          >
            {live ? "↗" : "···"}
          </span>
        </span>
      </div>
    </Link>
  );
}
