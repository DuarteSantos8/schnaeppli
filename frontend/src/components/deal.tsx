import { ArrowDownRight, ImageOff, MapPin } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { img } from "@/lib/api";
import { CONDITION_TEXT, LABEL_SHORT, money, relTime, SOURCE_NAME } from "@/lib/format";
import type { Deal, Label } from "@/lib/types";
import { cx, Pill } from "./ui";
import { usePrefs } from "@/lib/prefs";

/** The Deal Score: the screen's main data element, the one place the cobalt hue appears. */
export function ScoreMark({ score, label, size = "md" }: { score: number | null; label: Label | null; size?: "sm" | "md" | "lg" }) {
  const dims = { sm: 34, md: 44, lg: 72 }[size];
  const stroke = size === "lg" ? 5 : 3.5;
  const r = (dims - stroke) / 2;
  const c = 2 * Math.PI * r;
  const pct = score === null ? 0 : Math.max(0, Math.min(100, score)) / 100;
  const risky = label === "risky";
  const color = risky ? "var(--color-warning)" : label === "overpriced" ? "var(--color-faint)" : "var(--color-score)";
  return (
    <div
      className="relative inline-flex shrink-0 items-center justify-center"
      style={{ width: dims, height: dims }}
      role="img"
      aria-label={score === null ? "Not scored yet" : `Deal score ${score} of 100${label ? `, ${LABEL_SHORT[label]}` : ""}`}
    >
      <svg width={dims} height={dims} className="-rotate-90" aria-hidden>
        <circle cx={dims / 2} cy={dims / 2} r={r} fill="none" stroke="var(--color-raised)" strokeWidth={stroke} />
        {score !== null && (
          <circle
            cx={dims / 2}
            cy={dims / 2}
            r={r}
            fill="none"
            stroke={color}
            strokeWidth={stroke}
            strokeLinecap="round"
            strokeDasharray={`${c * pct} ${c}`}
          />
        )}
      </svg>
      <span
        className={cx(
          "num absolute font-semibold tracking-[-0.02em]",
          size === "lg" ? "text-[1.5rem]" : size === "md" ? "text-[0.9375rem]" : "text-[0.75rem]",
        )}
      >
        {score ?? "–"}
      </span>
    </div>
  );
}

export function LabelPill({ label }: { label: Label | null }) {
  if (!label) return <Pill>Not scored</Pill>;
  const tone = label === "exceptional" || label === "good" ? "score" : label === "risky" ? "warning" : "neutral";
  return <Pill tone={tone}>{LABEL_SHORT[label]}</Pill>;
}

/**
 * Price ruler: what you'd pay against the estimated market range. It shows *why*
 * a listing scored well or badly, at a glance.
 */
export function PriceRuler({
  price,
  low,
  high,
  mid,
  currency,
  compact,
  estimated,
}: {
  price: number | null;
  low?: number | null;
  high?: number | null;
  mid?: number | null;
  currency: string;
  compact?: boolean;
  estimated?: boolean;
}) {
  const lo = low ?? (mid ? mid * 0.9 : null);
  const hi = high ?? (mid ? mid * 1.1 : null);
  if (price === null || lo === null || hi === null) {
    return compact ? null : <p className="text-[0.8125rem] text-muted">No reliable market estimate yet.</p>;
  }
  const min = Math.min(price, lo) * 0.85;
  const max = Math.max(price, hi) * 1.1;
  const pos = (v: number) => `${((v - min) / (max - min)) * 100}%`;
  const below = price < lo;
  return (
    <div className={compact ? "" : "pt-1"}>
      <div className="relative h-5" aria-hidden>
        <div className="absolute top-1/2 h-[3px] w-full -translate-y-1/2 rounded-full bg-raised" />
        <div
          className="absolute top-1/2 h-[7px] -translate-y-1/2 rounded-full bg-track"
          style={{ left: pos(lo), width: `calc(${pos(hi)} - ${pos(lo)})` }}
        />
        <div
          className="absolute top-1/2 size-[13px] -translate-x-1/2 -translate-y-1/2 rounded-full border-[2.5px] border-surface"
          style={{ left: pos(price), background: below ? "var(--color-score)" : "var(--color-ink)" }}
        />
      </div>
      {!compact && (
        <div className="mt-1 flex justify-between text-[0.75rem] text-muted">
          <span className="num">
            You pay <span className="font-semibold text-ink">{money(price, currency)}</span>
            {estimated ? " (est.)" : ""}
          </span>
          <span className="num">
            Market {money(Math.round(lo), currency)}–{money(Math.round(hi), currency).replace(`${currency} `, "")}
          </span>
        </div>
      )}
      <span className="sr-only">
        You pay {money(price, currency)}; estimated market range {money(lo, currency)} to {money(hi, currency)}.
      </span>
    </div>
  );
}

export function Photo({
  src,
  alt,
  className,
  width = 640,
  eager,
}: {
  src?: string | null;
  alt: string;
  className?: string;
  width?: number;
  eager?: boolean;
}) {
  const [failed, setFailed] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const url = img(src, width);
  if (!url || failed) {
    return (
      <div className={cx("flex items-center justify-center bg-raised text-faint", className)} role="img" aria-label={alt}>
        <ImageOff className="size-5" aria-hidden />
      </div>
    );
  }
  return (
    <div className={cx("overflow-hidden bg-raised", className)}>
      <img
        src={url}
        srcSet={`${img(src, Math.round(width / 2))} ${Math.round(width / 2)}w, ${url} ${width}w, ${img(src, width * 2)} ${width * 2}w`}
        sizes={`${width}px`}
        alt={alt}
        loading={eager ? "eager" : "lazy"}
        decoding="async"
        onError={() => setFailed(true)}
        onLoad={() => setLoaded(true)}
        className={cx("size-full object-cover transition-opacity duration-300", loaded ? "opacity-100" : "opacity-0")}
      />
    </div>
  );
}

function sourceLine(d: Deal) {
  const parts = [SOURCE_NAME[d.listing.source] || d.listing.source];
  if (d.listing.condition) parts.push(CONDITION_TEXT[d.listing.condition] || d.listing.condition);
  return parts.join(" · ");
}

/** Discovery card: big photo first, like browsing a catalogue. */
export function DealCard({ deal, eager }: { deal: Deal; eager?: boolean }) {
  const dropped = deal.price_dropped_at && deal.previous_price;
  const { show_photos } = usePrefs();
  return (
    <Link
      to={`/deals/${deal.id}`}
      className="group pressable flex flex-col rounded-[var(--radius-card)] outline-offset-4"
      aria-label={`${deal.listing.title}, ${money(deal.effective_price, deal.listing.currency)}`}
    >
      {show_photos ? (
        <div className="relative">
          <Photo
            src={deal.listing.images[0]}
            alt=""
            eager={eager}
            width={480}
            className="aspect-[4/3] w-full rounded-[var(--radius-photo)] transition-transform"
          />
          <div className="absolute top-2 left-2 rounded-full bg-surface/95 p-0.5">
            <ScoreMark score={deal.deal_score} label={deal.deal_label} size="sm" />
          </div>
          {deal.status === "new" && (
            <span className="absolute top-2.5 right-2.5 rounded-full bg-surface px-2 py-0.5 text-[0.75rem] font-medium">New</span>
          )}
        </div>
      ) : (
        <div className="flex items-center justify-between border-t border-rule pt-2.5">
          <ScoreMark score={deal.deal_score} label={deal.deal_label} size="sm" />
          {deal.status === "new" && <span className="text-[0.75rem] font-medium text-muted">New</span>}
        </div>
      )}
      <div className="mt-2.5 min-w-0 px-0.5">
        <div className="flex items-baseline justify-between gap-2">
          <p className="num text-[0.9375rem] font-semibold tracking-[-0.01em]">
            {money(deal.effective_price, deal.listing.currency)}
            {deal.effective_price_estimated && <span className="ml-1 text-[0.75rem] font-normal text-muted">est.</span>}
          </p>
          {dropped ? (
            <span className="num inline-flex items-center gap-0.5 text-[0.75rem] font-medium text-positive">
              <ArrowDownRight className="size-3.5" aria-hidden />
              {money(deal.previous_price, deal.listing.currency)}
            </span>
          ) : deal.market_mid ? (
            <span className="num text-[0.75rem] text-muted">≈ {money(Math.round(deal.market_mid), deal.listing.currency)}</span>
          ) : null}
        </div>
        <p className="mt-0.5 line-clamp-2 text-[0.875rem] leading-snug text-ink group-hover:underline group-hover:decoration-control group-hover:underline-offset-2">
          {deal.listing.title}
        </p>
        <p className="mt-1 truncate text-[0.8125rem] text-muted">
          {sourceLine(deal)}
          {deal.distance_km !== null && (
            <>
              {" · "}
              <MapPin className="-mt-0.5 inline size-3" aria-hidden /> {Math.round(deal.distance_km)} km
            </>
          )}
        </p>
      </div>
    </Link>
  );
}

/** Compact row for lists inside panels. */
export function DealRow({ deal, showSearch }: { deal: Deal; showSearch?: boolean }) {
  const { show_photos } = usePrefs();
  return (
    <Link
      to={`/deals/${deal.id}`}
      className="hover-lift pressable flex items-center gap-3 rounded-[var(--radius-control)] px-2 py-2"
    >
      {show_photos && <Photo src={deal.listing.images[0]} alt="" width={160} className="size-14 shrink-0 rounded-[var(--radius-photo)]" />}
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium">{deal.listing.title}</p>
        <p className="mt-0.5 truncate text-[0.8125rem] text-muted">
          {showSearch && deal.search_title ? `${deal.search_title} · ` : ""}
          {sourceLine(deal)} · {relTime(deal.first_seen_at)}
        </p>
      </div>
      <div className="flex shrink-0 items-center gap-3">
        <span className="num text-sm font-semibold">{money(deal.effective_price, deal.listing.currency)}</span>
        <ScoreMark score={deal.deal_score} label={deal.deal_label} size="sm" />
      </div>
    </Link>
  );
}

export function DealGridSkeleton({ n = 8 }: { n?: number }) {
  return (
    <div className="grid grid-cols-2 gap-x-3 gap-y-6 sm:gap-x-4 md:grid-cols-3 xl:grid-cols-4">
      {Array.from({ length: n }).map((_, i) => (
        <div key={i}>
          <div className="skeleton aspect-[4/3] w-full" />
          <div className="skeleton mt-3 h-4 w-1/3" />
          <div className="skeleton mt-2 h-4 w-5/6" />
          <div className="skeleton mt-2 h-3 w-1/2" />
        </div>
      ))}
    </div>
  );
}
