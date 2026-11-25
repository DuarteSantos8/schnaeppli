import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { DealCard, DealGridSkeleton, DealRow } from "@/components/deal";
import { Button, Empty, ErrorBox, Notice, Panel, PanelHeader, Skeleton } from "@/components/ui";
import { get } from "@/lib/api";
import { useMe } from "@/lib/auth";
import { dayTime, plural, relTime, usd } from "@/lib/format";
import type { Dashboard, Outage } from "@/lib/types";
import { usePrefs } from "@/lib/prefs";

function greeting() {
  const h = new Date().getHours();
  return h < 5 ? "Good night" : h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening";
}

function Setup({ d }: { d: Dashboard }) {
  const [hidden, setHidden] = useState(() => localStorage.getItem("schnaeppli.more-sources-hidden") === "1");
  if (!d.setup.ai_ready)
    return (
      <Panel className="mb-6">
        <Link to="/setup#ai" className="hover-lift flex items-center gap-4 rounded-[var(--radius-card)] p-4">
          <span className="min-w-0 flex-1">
            <span className="block text-[0.9375rem] font-semibold">One step before you start: choose the AI</span>
            <span className="block text-[0.8125rem] text-muted">Schnäppli needs it to understand what you want and to judge listings.</span>
          </span>
          <Button size="sm" variant="primary">Set up</Button>
        </Link>
      </Panel>
    );
  if (d.setup.mail_connected || hidden) return null;
  return (
    <div className="mb-6 flex flex-wrap items-center gap-3 rounded-[var(--radius-card)] border border-border bg-surface px-4 py-3 text-sm">
      <p className="min-w-0 flex-1">
        <span className="font-medium">Want Ricardo, tutti, Facebook and Toppreise too?</span>{" "}
        <span className="text-muted">Optional, about two minutes.</span>
      </p>
      <Link to="/setup#mail"><Button size="sm">Add them</Button></Link>
      <button
        type="button"
        className="text-[0.8125rem] text-muted hover:text-ink"
        onClick={() => {
          localStorage.setItem("schnaeppli.more-sources-hidden", "1");
          setHidden(true);
        }}
      >
        Not now
      </button>
    </div>
  );
}

/** Admins only: shown for two days after the server was offline, until dismissed. */
function OutageNotice({ o }: { o: Outage }) {
  const key = `schnaeppli.outage-seen.${o.to}`;
  const [hidden, setHidden] = useState(() => localStorage.getItem(key) === "1");
  if (hidden) return null;
  const from = new Date(o.from);
  const to = new Date(o.to);
  const fmt = (x: Date) => x.toLocaleString("de-CH", { day: "numeric", month: "numeric", hour: "2-digit", minute: "2-digit" });
  const span = o.minutes < 60 ? `${o.minutes} min` : `${Math.floor(o.minutes / 60)} h ${o.minutes % 60} min`;
  const caught = [
    o.searches_caught_up ? `${o.searches_caught_up} search${o.searches_caught_up === 1 ? "" : "es"} ran again` : null,
    o.runs_restarted.length ? `${o.runs_restarted.length} interrupted run${o.runs_restarted.length === 1 ? "" : "s"} restarted` : null,
    o.analyses_requeued ? `${o.analyses_requeued} analyses queued again` : null,
    "missed digests sent late",
  ].filter(Boolean);
  return (
    <div className="mb-6">
      <Notice
        tone="warning"
        action={<Button size="sm" variant="ghost" onClick={() => { localStorage.setItem(key, "1"); setHidden(true); }}>Dismiss</Button>}
      >
        <p className="font-medium">The server was offline for {span} ({fmt(from)} to {fmt(to)}).</p>
        <p className="mt-0.5">
          {o.clean ? "It was shut down normally." : "It stopped without shutting down: probably a crash or power loss."} Caught up: {caught.join(", ")}. No data was lost.
        </p>
      </Notice>
    </div>
  );
}

export default function Home() {
  const me = useMe();
  const show = new Set(usePrefs().home_sections);
  const q = useQuery({ queryKey: ["dashboard"], queryFn: () => get<Dashboard>("/api/dashboard"), refetchInterval: 60_000 });
  const d = q.data;
  const good = d?.top.filter((x) => x.deal_label === "exceptional" || x.deal_label === "good") ?? [];
  const finding = !d
    ? null
    : d.active_searches === 0
      ? "No searches yet. Tell Schnäppli what you're after and it starts looking."
      : good.length > 0
        ? `${plural(good.length, "good deal")} this week. The best scores ${good[0].deal_score}.`
        : d.new_today > 0
          ? `${plural(d.new_today, "new listing")} today, none that beat the market yet.`
          : `Nothing new today. Next search ${dayTime(d.next_run_at)}.`;
  const budget = d?.ai_budget;
  const monthPct = budget?.monthly_limit_usd ? Math.min(100, (budget.month_usd / budget.monthly_limit_usd) * 100) : 0;

  return (
    <>
      <header className="mb-6">
        <h1 className="text-[1.5rem] font-semibold tracking-[-0.02em]">
          {greeting()}, {me.display_name.split(" ")[0]}
        </h1>
        <p className="mt-1 text-[0.9375rem] text-muted">{finding ?? <Skeleton className="inline-block h-4 w-64" />}</p>
      </header>

      {q.error ? <ErrorBox error={q.error} onRetry={() => q.refetch()} /> : null}
      {d && <Setup d={d} />}

      {d?.last_outage && <OutageNotice o={d.last_outage} />}

      {d?.ai_budget.paused_reason && (
        <Panel className="mb-6 px-4 py-3 text-sm">
          AI analysis is paused: {d.ai_budget.paused_reason}.{" "}
          <Link to="/settings/ai" className="font-medium underline underline-offset-2">
            Review limits
          </Link>
        </Panel>
      )}

      {/* Counts as one divided strip: label over value, no icons. */}
      {show.has("stats") && <div className="mb-8 grid grid-cols-2 overflow-hidden rounded-[var(--radius-card)] border border-border bg-surface md:grid-cols-4">
        {[
          { label: "Active searches", value: d?.active_searches, to: "/searches" },
          { label: "New listings today", value: d?.new_today, to: "/deals?sort=newest" },
          { label: "Good deals this week", value: d?.good_this_week, to: "/deals?label=good" },
          {
            label: "AI spend this month",
            value: budget ? usd(budget.month_usd) : undefined,
            sub: budget?.monthly_limit_usd ? `of ${usd(budget.monthly_limit_usd)}` : undefined,
            to: "/usage",
          },
        ].map((k, i) => (
          <Link
            key={k.label}
            to={k.to}
            className={`hover-lift block px-4 py-3.5 sm:px-5 ${i % 2 ? "border-l border-rule" : ""} ${i >= 2 ? "border-t border-rule md:border-t-0" : ""} ${i === 2 ? "md:border-l" : ""}`}
          >
            <div className="text-[0.8125rem] text-muted">{k.label}</div>
            <div className="num mt-1 text-[1.625rem] leading-tight font-medium tracking-[-0.02em]">
              {k.value === undefined ? <Skeleton className="h-7 w-12" /> : k.value}
              {k.sub && <span className="ml-1.5 text-[0.8125rem] font-normal text-muted">{k.sub}</span>}
            </div>
          </Link>
        ))}
      </div>}

      {show.has("best") && <section aria-labelledby="best-heading" className="mb-10">
        <div className="mb-4 flex items-end justify-between">
          <h2 id="best-heading" className="text-[1.125rem] font-semibold tracking-[-0.01em]">
            Best this week
          </h2>
          <Link to="/deals" className="text-sm text-muted hover:text-ink">
            All deals
          </Link>
        </div>
        {!d ? (
          <DealGridSkeleton n={4} />
        ) : d.top.length === 0 ? (
          <Panel>
            <Empty
              title={d.active_searches ? "No scored listings this week" : "Nothing to show yet"}
              action={
                <Link to="/searches/new">
                  <Button variant="primary">New search</Button>
                </Link>
              }
            >
              {d.active_searches
                ? "Schnäppli scores listings after each search run. If AI analysis is limited or no source is enabled, listings stay unscored."
                : "Describe what you'd like to buy, in your own words. Schnäppli turns it into a search and keeps watching."}
            </Empty>
          </Panel>
        ) : (
          <div className="grid grid-cols-2 gap-x-3 gap-y-6 sm:gap-x-4 md:grid-cols-3 xl:grid-cols-4">
            {d.top.slice(0, 8).map((deal, i) => (
              <DealCard key={deal.id} deal={deal} eager={i < 4} />
            ))}
          </div>
        )}
      </section>}

      <div className="grid gap-4 lg:grid-cols-12">
        {show.has("drops") && <Panel className={show.has("activity") ? "lg:col-span-7" : "lg:col-span-12"}>
          <PanelHeader title="Price drops" sub="On listings you've seen or that scored well" />
          <div className="px-2 pb-2">
            {!d ? (
              <Skeleton className="m-2 h-14" />
            ) : d.price_drops.length === 0 ? (
              <p className="px-2 pb-3 text-sm text-muted">No price drops this week.</p>
            ) : (
              d.price_drops.map((x) => <DealRow key={x.id} deal={x} showSearch />)
            )}
          </div>
        </Panel>}
        {show.has("activity") && <Panel className={show.has("drops") ? "lg:col-span-5" : "lg:col-span-12"}>
          <PanelHeader
            title="Search activity"
            sub={d?.next_run_at ? `Next run ${dayTime(d.next_run_at)}` : undefined}
          />
          <ul className="px-4 pb-3 sm:px-5">
            {!d ? (
              <Skeleton className="h-14" />
            ) : d.recent_runs.length === 0 ? (
              <li className="pb-1 text-sm text-muted">No runs yet.</li>
            ) : (
              d.recent_runs.slice(0, 6).map((r, i) => (
                <li key={i} className="flex items-baseline justify-between gap-3 border-t border-rule py-2.5 first:border-t-0">
                  <span className="min-w-0">
                    <span className="block truncate text-sm">{r.search}</span>
                    <span className="block truncate text-[0.8125rem] text-muted">
                      {r.status === "failed" ? <span className="text-negative">Failed: {r.error}</span> : `${r.fetched} checked`}
                    </span>
                  </span>
                  <span className="num shrink-0 text-right text-[0.8125rem] text-muted">
                    {r.new_matches > 0 ? <span className="text-ink">{r.new_matches} new</span> : "0 new"} · {relTime(r.started_at)}
                  </span>
                </li>
              ))
            )}
          </ul>
          {budget?.monthly_limit_usd ? (
            <div className="border-t border-rule px-4 py-3 sm:px-5">
              <div className="flex justify-between text-[0.8125rem]">
                <span className="text-muted">AI budget this month</span>
                <span className="num">
                  {usd(budget.month_usd)} of {usd(budget.monthly_limit_usd)}
                </span>
              </div>
              <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-raised" aria-hidden>
                <div
                  className="h-full rounded-full"
                  style={{
                    width: `${monthPct}%`,
                    background: monthPct >= budget.warn_pct ? "var(--color-warning)" : "var(--color-ink)",
                  }}
                />
              </div>
            </div>
          ) : null}
        </Panel>}
      </div>
    </>
  );
}
