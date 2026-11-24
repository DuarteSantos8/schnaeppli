import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  Bookmark,
  Camera,
  Check,
  ExternalLink,
  Heart,
  MessageCircle,
  Sparkles,
  ThumbsDown,
} from "lucide-react";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { DealRow, LabelPill, Photo, PriceRuler, ScoreMark } from "@/components/deal";
import { Button, cx, ErrorBox, Field, Input, Panel, PanelHeader, Pill, Sheet, Skeleton, useToast } from "@/components/ui";
import { get, patch, post } from "@/lib/api";
import { CONDITION_TEXT, LABEL_TEXT, money, relTime, SOURCE_NAME, dayTime } from "@/lib/format";
import type { DealDetail as D, MatchStatus } from "@/lib/types";

function Gallery({ images, title }: { images: string[]; title: string }) {
  const [active, setActive] = useState(0);
  if (images.length === 0) return <Photo src={null} alt={title} className="aspect-[4/3] w-full rounded-[var(--radius-card)]" />;
  return (
    <div>
      {/* Phone: swipe through photos with scroll-snap */}
      <div
        className="-mx-4 flex snap-x snap-mandatory overflow-x-auto no-scrollbar sm:hidden"
        onScroll={(e) => {
          const el = e.currentTarget;
          setActive(Math.round(el.scrollLeft / el.clientWidth));
        }}
      >
        {images.map((src, i) => (
          <Photo key={src} src={src} alt={`${title}, photo ${i + 1}`} width={960} eager={i === 0} className="aspect-[4/3] w-full shrink-0 snap-center" />
        ))}
      </div>
      {images.length > 1 && (
        <div className="mt-2 flex justify-center gap-1.5 sm:hidden" aria-hidden>
          {images.map((_, i) => (
            <span key={i} className={cx("size-1.5 rounded-full transition-colors", i === active ? "bg-ink" : "bg-control")} />
          ))}
        </div>
      )}
      {/* Desktop: main photo and thumbnails */}
      <div className="hidden sm:block">
        <Photo src={images[active]} alt={`${title}, photo ${active + 1}`} width={1280} eager className="aspect-[4/3] w-full rounded-[var(--radius-card)]" />
        {images.length > 1 && (
          <div className="mt-2 flex gap-2 overflow-x-auto no-scrollbar">
            {images.map((src, i) => (
              <button
                key={src}
                onClick={() => setActive(i)}
                aria-label={`Show photo ${i + 1}`}
                aria-current={i === active}
                className={cx("pressable shrink-0 rounded-[var(--radius-photo)] ring-offset-2", i === active && "ring-2 ring-ink")}
              >
                <Photo src={src} alt="" width={160} className="size-16 rounded-[var(--radius-photo)]" />
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function PriceHistory({ points, currency }: { points: D["price_history"]; currency: string }) {
  if (points.length < 2) return <p className="text-[0.8125rem] text-muted">Only one price seen so far ({money(points[0]?.price ?? null, currency)}).</p>;
  const w = 320;
  const h = 72;
  const prices = points.map((p) => p.price);
  const min = Math.min(...prices) * 0.97;
  const max = Math.max(...prices) * 1.03;
  const t0 = new Date(points[0].at).getTime();
  const t1 = Math.max(new Date(points[points.length - 1].at).getTime(), t0 + 1);
  const x = (t: string) => ((new Date(t).getTime() - t0) / (t1 - t0)) * (w - 8) + 4;
  const y = (v: number) => h - 6 - ((v - min) / (max - min)) * (h - 12);
  let d = "";
  points.forEach((p, i) => {
    d += i === 0 ? `M${x(p.at)},${y(p.price)}` : ` H${x(p.at)} V${y(p.price)}`;
  });
  const last = points[points.length - 1];
  return (
    <figure>
      <svg viewBox={`0 0 ${w} ${h}`} className="h-[72px] w-full" role="img" aria-label={`Price went from ${money(points[0].price, currency)} to ${money(last.price, currency)}`}>
        <path d={d} fill="none" stroke="var(--color-ink)" strokeWidth="2" />
        <circle cx={x(last.at)} cy={y(last.price)} r="3.5" fill="var(--color-score)" />
      </svg>
      <figcaption className="num mt-1 flex justify-between text-[0.75rem] text-muted">
        <span>
          {money(points[0].price, currency)} · {relTime(points[0].at)}
        </span>
        <span className="text-ink">{money(last.price, currency)} now</span>
      </figcaption>
    </figure>
  );
}

function PurchaseSheet({ open, onOpenChange, onSave, price, currency }: {
  open: boolean; onOpenChange: (v: boolean) => void; onSave: (v: number) => void; price: number | null; currency: string;
}) {
  const [v, setV] = useState(price?.toString() ?? "");
  return (
    <Sheet
      open={open}
      onOpenChange={onOpenChange}
      title="Mark as purchased"
      description="This amount counts towards this month's budget. Schnäppli never buys anything for you."
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button variant="primary" onClick={() => onSave(Number(v))} disabled={!v || Number.isNaN(Number(v))}>Save</Button>
        </>
      }
    >
      <Field label={`What did you pay? (${currency})`} htmlFor="paid">
        <Input id="paid" inputMode="decimal" value={v} onChange={(e) => setV(e.target.value.replace(",", "."))} />
      </Field>
    </Sheet>
  );
}

export default function DealDetail() {
  const { id } = useParams();
  const nav = useNavigate();
  const qc = useQueryClient();
  const toast = useToast();
  const [buyOpen, setBuyOpen] = useState(false);
  const [showDesc, setShowDesc] = useState(false);
  const q = useQuery({ queryKey: ["deal", id], queryFn: () => get<D>(`/api/deals/${id}`) });
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["deal", id] });
    qc.invalidateQueries({ queryKey: ["deals"] });
    qc.invalidateQueries({ queryKey: ["dashboard"] });
  };
  const status = useMutation({
    mutationFn: (b: { status: MatchStatus; purchase_price?: number }) => patch(`/api/deals/${id}`, b),
    onSuccess: (_d, b) => {
      refresh();
      qc.invalidateQueries({ queryKey: ["budget"] });
      const prev = q.data?.status;
      const words: Record<string, string> = { favorite: "Saved to favorites", rejected: "Hidden from your feed", planned: "Added to planned purchases", purchased: "Marked as purchased", interested: "Marked as interested" };
      toast.show(words[b.status] || "Updated", prev ? { label: "Undo", run: () => status.mutate({ status: prev }) } : undefined);
    },
    onError: toast.error,
  });
  const deep = useMutation({ mutationFn: () => post(`/api/deals/${id}/analyze`), onSuccess: refresh, onError: toast.error });
  const vision = useMutation({ mutationFn: () => post(`/api/deals/${id}/vision`), onSuccess: refresh, onError: toast.error });

  if (q.error) return <ErrorBox error={q.error} onRetry={() => q.refetch()} />;
  const d = q.data;
  if (!d)
    return (
      <div className="grid gap-6 lg:grid-cols-12">
        <Skeleton className="aspect-[4/3] lg:col-span-7" />
        <div className="space-y-3 lg:col-span-5">
          <Skeleton className="h-8 w-3/4" />
          <Skeleton className="h-6 w-1/3" />
          <Skeleton className="h-32" />
        </div>
      </div>
    );
  const L = d.listing;
  const a = d.analysis;
  const r = a?.result;
  const mv = a?.market_value || {};
  const toggle = (s: MatchStatus) => status.mutate({ status: d.status === s ? "seen" : s });

  return (
    <article>
      <button onClick={() => (history.length > 1 ? nav(-1) : nav("/deals"))} className="mb-3 inline-flex items-center gap-1 text-sm text-muted hover:text-ink">
        <ArrowLeft className="size-4" aria-hidden /> Back
      </button>
      <div className="grid gap-6 lg:grid-cols-12 lg:gap-8">
        <div className="lg:col-span-7">
          <Gallery images={L.images} title={L.title} />
        </div>

        <div className="lg:col-span-5">
          <p className="text-[0.8125rem] text-muted">
            {SOURCE_NAME[L.source] || L.source} · for{" "}
            <Link to={`/searches/${d.search_id}`} className="underline-offset-2 hover:underline">
              {d.search_title}
            </Link>{" "}
            · found {relTime(d.first_seen_at)}
          </p>
          <h1 className="mt-1 text-[1.375rem] leading-tight font-semibold tracking-[-0.02em]">{L.title}</h1>

          <div className="mt-4 flex items-center gap-4">
            <ScoreMark score={d.deal_score} label={d.deal_label} size="lg" />
            <div>
              <div className="num text-[1.625rem] leading-none font-bold tracking-[-0.02em]">{money(d.effective_price, L.currency)}</div>
              <div className="mt-1.5 text-[0.8125rem] text-muted">
                {money(L.price, L.currency)}
                {L.shipping_cost !== null ? ` + ${money(L.shipping_cost, L.currency)} shipping` : d.effective_price_estimated ? " + estimated shipping" : ""}
                {L.price_type === "auction" ? " · current bid" : L.price_type === "negotiable" ? " · offers accepted" : ""}
              </div>
              <div className="mt-1.5 flex flex-wrap gap-1.5">
                <LabelPill label={d.deal_label} />
                {d.previous_price && <Pill tone="positive">Was {money(d.previous_price, L.currency)}</Pill>}
                {r?.possibly_undervalued && <Pill tone="score">Possibly undervalued</Pill>}
              </div>
            </div>
          </div>

          {a && (
            <div className="mt-5">
              <PriceRuler
                price={d.effective_price}
                low={r?.market_value_low}
                high={r?.market_value_high}
                mid={mv.mid}
                currency={L.currency}
                estimated={d.effective_price_estimated}
              />
              <p className="mt-2 text-[0.8125rem] text-muted">
                Market value: {mv.source || "unknown"}
                {mv.confidence && mv.confidence !== "none" ? `, ${mv.confidence} confidence` : ""}. These are asking prices, not completed sales.
              </p>
            </div>
          )}

          {r?.summary && <p className="mt-4 text-[0.9375rem] leading-relaxed">{r.summary}</p>}

          {/* Primary action first, then the feedback that trains ranking */}
          <div className="mt-5 flex flex-col gap-2">
            <a href={L.url} target="_blank" rel="noopener noreferrer nofollow">
              <Button variant="primary" size="lg" className="w-full" icon={<ExternalLink className="size-4" aria-hidden />}>
                Open on {SOURCE_NAME[L.source] || L.source}
              </Button>
            </a>
            <div className="grid grid-cols-4 gap-2">
              {[
                { s: "favorite" as const, label: "Save", icon: Heart },
                { s: "planned" as const, label: "Plan", icon: Bookmark },
                { s: "purchased" as const, label: "Bought", icon: Check },
                { s: "rejected" as const, label: "Not for me", icon: ThumbsDown },
              ].map((x) => (
                <button
                  key={x.s}
                  onClick={() => (x.s === "purchased" && d.status !== "purchased" ? setBuyOpen(true) : toggle(x.s))}
                  aria-pressed={d.status === x.s}
                  className={cx(
                    "pressable flex h-14 flex-col items-center justify-center gap-1 rounded-[var(--radius-control)] text-[0.75rem] font-medium",
                    d.status === x.s ? "bg-ink text-on-ink" : "bg-raised text-ink hover:bg-raised-hover",
                  )}
                >
                  <x.icon className="size-4" fill={d.status === x.s && x.s === "favorite" ? "currentColor" : "none"} aria-hidden />
                  {x.label}
                </button>
              ))}
            </div>
            <Link to={`/assistant?focus=${d.id}`}>
              <Button variant="ghost" className="w-full" icon={<MessageCircle className="size-4" aria-hidden />}>
                Ask the assistant about this
              </Button>
            </Link>
          </div>
        </div>
      </div>

      <div className="mt-8 grid gap-4 lg:grid-cols-12">
        <div className="flex flex-col gap-4 lg:col-span-7">
          {!a ? (
            <Panel>
              <PanelHeader title="Not analysed yet" />
              <div className="px-4 pb-4 text-sm text-muted sm:px-5">
                {d.analysis_state === "skipped"
                  ? `Skipped by the free pre-filter: ${d.skip_reason}.`
                  : d.analysis_state === "limited"
                    ? d.skip_reason
                    : d.analysis_state === "failed"
                      ? `Analysis failed: ${d.skip_reason}`
                      : "Queued for analysis."}
                <div className="mt-3">
                  <Button onClick={() => deep.mutate()} loading={deep.isPending} icon={<Sparkles className="size-4" aria-hidden />}>
                    Analyse now
                  </Button>
                </div>
              </div>
            </Panel>
          ) : (
            <>
              <Panel>
                <PanelHeader
                  title="Why this score"
                  sub={`${LABEL_TEXT[d.deal_label!] ?? ""} · ${a.kind === "deep_analysis" ? "deep analysis" : "quick scan"} by ${a.model}`}
                  action={
                    a.kind !== "deep_analysis" ? (
                      <Button size="sm" onClick={() => deep.mutate()} loading={deep.isPending} icon={<Sparkles className="size-3.5" aria-hidden />}>
                        Deep analysis
                      </Button>
                    ) : null
                  }
                />
                <ul className="px-4 pb-4 sm:px-5">
                  {a.breakdown.map((b, i) => (
                    <li key={i} className="flex items-baseline justify-between gap-4 border-t border-rule py-2 text-sm first:border-t-0">
                      <span className={b.kind === "info" ? "text-muted" : ""}>{b.label}</span>
                      {b.kind !== "info" && (
                        <span className={cx("num shrink-0", b.kind === "base" ? "font-medium" : b.points < 0 ? "text-negative" : "text-positive")}>
                          {b.kind === "base" ? Math.round(b.points) : `${b.points > 0 ? "+" : ""}${b.points}`}
                        </span>
                      )}
                    </li>
                  ))}
                  <li className="flex justify-between border-t border-border pt-2 text-sm font-semibold">
                    <span>Deal Score</span>
                    <span className="num text-score">{d.deal_score}</span>
                  </li>
                </ul>
              </Panel>

              <div className="grid gap-4 sm:grid-cols-2">
                <Panel>
                  <PanelHeader title="From the listing" sub="What the seller states" />
                  <ul className="list-disc space-y-1.5 pr-4 pb-4 pl-9 text-sm sm:pr-5">
                    {(r!.facts.length ? r!.facts : ["Nothing specific stated."]).map((f, i) => <li key={i}>{f}</li>)}
                  </ul>
                </Panel>
                <Panel>
                  <PanelHeader title="AI assumptions" sub="Inferred, not verified" />
                  <ul className="list-disc space-y-1.5 pr-4 pb-4 pl-9 text-sm text-muted sm:pr-5">
                    {(r!.assumptions.length ? r!.assumptions : ["None."]).map((f, i) => <li key={i}>{f}</li>)}
                  </ul>
                </Panel>
              </div>

              {(r!.red_flags.length > 0 || r!.requirement_misses.length > 0) && (
                <Panel>
                  <PanelHeader title="Worth checking" />
                  <ul className="space-y-2 px-4 pb-4 text-sm sm:px-5">
                    {r!.red_flags.map((f, i) => (
                      <li key={i} className="flex gap-2">
                        <Pill tone={["possible_defect", "seller_risk", "suspicious_price"].includes(f.type) ? "warning" : "neutral"}>
                          {f.type.replace(/_/g, " ")}
                        </Pill>
                        <span>{f.detail}</span>
                      </li>
                    ))}
                    {r!.requirement_misses.map((m, i) => (
                      <li key={`m${i}`} className="flex gap-2">
                        <Pill>requirement</Pill>
                        <span>{m}</span>
                      </li>
                    ))}
                  </ul>
                </Panel>
              )}

              <Panel>
                <PanelHeader
                  title="Photos"
                  sub={r!.vision ? "What the vision model could see. Possible issues, not confirmed defects." : "Not checked yet"}
                  action={
                    !r!.vision && L.images.length > 0 ? (
                      <Button size="sm" onClick={() => vision.mutate()} loading={vision.isPending} icon={<Camera className="size-3.5" aria-hidden />}>
                        Check photos
                      </Button>
                    ) : null
                  }
                />
                {r!.vision ? (
                  <div className="space-y-3 px-4 pb-4 text-sm sm:px-5">
                    <p>{r!.vision.summary}</p>
                    {r!.vision.possible_issues.length > 0 && (
                      <ul className="space-y-1.5">
                        {r!.vision.possible_issues.map((x, i) => (
                          <li key={i} className="flex gap-2">
                            <Pill tone={x.confidence === "high" ? "warning" : "neutral"}>{x.confidence}</Pill>
                            <span>
                              Possible: {x.issue} <span className="text-muted">(photo {x.image_index + 1})</span>
                            </span>
                          </li>
                        ))}
                      </ul>
                    )}
                    {r!.vision.looks_like_stock_photo && <p className="text-muted">These look like stock photos, not pictures of the actual item.</p>}
                  </div>
                ) : (
                  <p className="px-4 pb-4 text-sm text-muted sm:px-5">
                    {L.images.length ? "Photos are checked automatically for promising listings, or on request." : "This listing has no photos."}
                  </p>
                )}
              </Panel>
            </>
          )}

          {L.description && (
            <Panel>
              <PanelHeader title="Description" sub="As written by the seller" />
              <div className={cx("px-4 pb-4 text-sm whitespace-pre-line text-ink-2 sm:px-5", !showDesc && "line-clamp-6")}>{L.description}</div>
              {L.description.length > 400 && (
                <button className="mx-4 mb-4 text-sm font-medium underline underline-offset-2 sm:mx-5" onClick={() => setShowDesc((v) => !v)}>
                  {showDesc ? "Show less" : "Show all"}
                </button>
              )}
            </Panel>
          )}
        </div>

        <div className="flex flex-col gap-4 lg:col-span-5">
          <Panel>
            <PanelHeader title="Details" />
            <dl className="px-4 pb-3 text-sm sm:px-5">
              {[
                ["Condition", r ? CONDITION_TEXT[r.condition] : L.condition_text || (L.condition && CONDITION_TEXT[L.condition]) || "—"],
                ["Identified as", r?.identified_product || "—"],
                ["Included", r?.included_items.length ? r.included_items.join(", ") : "—"],
                ["Shipping", L.shipping_cost !== null ? `${money(L.shipping_cost, L.currency)}${L.shipping_known ? "" : " (calculated)"}` : L.shipping_possible === false ? "Pickup only" : "Unknown, estimated"],
                ["Pickup", L.pickup_possible === null ? "Not stated" : L.pickup_possible ? "Possible" : "No"],
                ["Distance", d.distance_km !== null ? `~${Math.round(d.distance_km)} km by road (estimate)${d.within_radius === false ? ", outside your radius" : ""}` : "Unknown"],
                ["Location", L.location_text || "—"],
                ["Seller", L.seller?.name ? `${L.seller.name}${L.seller.feedback_count !== undefined ? ` · ${L.seller.feedback_pct}% of ${L.seller.feedback_count}` : ""}` : "—"],
                ["Ends", L.ends_at ? dayTime(L.ends_at) : "—"],
              ].map(([k, v]) => (
                <div key={k} className="flex justify-between gap-4 border-t border-rule py-2 first:border-t-0">
                  <dt className="shrink-0 text-muted">{k}</dt>
                  <dd className="text-right">{v}</dd>
                </div>
              ))}
            </dl>
          </Panel>
          <Panel>
            <PanelHeader title="Price history" />
            <div className="px-4 pb-4 sm:px-5">
              <PriceHistory points={d.price_history} currency={L.currency} />
            </div>
          </Panel>
          {d.similar.length > 0 && (
            <Panel>
              <PanelHeader title="Same product elsewhere" />
              <div className="px-2 pb-2">
                {d.similar.map((s) => (
                  <DealRow key={s.id} deal={s} />
                ))}
              </div>
            </Panel>
          )}
        </div>
      </div>
      <PurchaseSheet
        open={buyOpen}
        onOpenChange={setBuyOpen}
        price={d.effective_price}
        currency={L.currency}
        onSave={(v) => {
          setBuyOpen(false);
          status.mutate({ status: "purchased", purchase_price: v });
        }}
      />
    </article>
  );
}
