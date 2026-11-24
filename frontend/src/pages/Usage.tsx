import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { Bars, Meter } from "@/components/charts";
import { Button, ErrorBox, Notice, PageHeader, Panel, PanelHeader, Segmented, Skeleton } from "@/components/ui";
import { get } from "@/lib/api";
import { relTime, tokens, usd } from "@/lib/format";
import type { BudgetStatus } from "@/lib/types";

interface Agg { key: string; calls: number; input_tokens: number; output_tokens: number; cache_read_tokens: number; cost_usd: number; failed: number; price_unknown: number; title?: string }
interface UsageData {
  days: number;
  budget: BudgetStatus;
  totals: { calls: number; input_tokens: number; output_tokens: number; cache_read_tokens: number; cost_usd: number; plan_calls: number; plan_api_equivalent_usd: number };
  avg_cost_per_listing: number | null;
  avg_cost_per_deep: number | null;
  by_provider: Agg[]; by_model: Agg[]; by_kind: Agg[]; by_search: Agg[]; by_scope: Agg[];
  daily: { date: string; cost_usd: number; tokens: number; calls: number }[];
  recent: { at: string; kind: string; model: string; provider: string; input_tokens: number; output_tokens: number; cost_usd: number; success: boolean; error: string | null }[];
}

const KIND: Record<string, string> = {
  prompt_interpretation: "Understanding requests", quick_scan: "Quick scans", deep_analysis: "Deep analyses",
  vision_analysis: "Photo checks", market_comparison: "Market comparisons", digest_generation: "Digests",
  chat: "Assistant chat", connection_test: "Connection tests",
};

function Table({ rows, name }: { rows: Agg[]; name: (r: Agg) => string }) {
  if (rows.length === 0) return <p className="px-4 pb-4 text-sm text-muted sm:px-5">Nothing yet.</p>;
  return (
    <div className="overflow-x-auto px-4 pb-3 sm:px-5">
      <table className="num w-full text-sm">
        <thead>
          <tr className="text-left text-[0.75rem] text-muted">
            <th className="pb-2 font-normal">Name</th>
            <th className="pb-2 text-right font-normal">Calls</th>
            <th className="hidden pb-2 text-right font-normal sm:table-cell">Tokens</th>
            <th className="pb-2 text-right font-normal">Cost</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.key} className="border-t border-rule">
              <td className="max-w-[220px] truncate py-2 pr-3">
                {name(r)}
                {r.price_unknown > 0 && <span className="ml-1.5 text-[0.75rem] text-warning">price unknown</span>}
              </td>
              <td className="py-2 text-right">{r.calls}</td>
              <td className="hidden py-2 text-right sm:table-cell">{tokens(r.input_tokens + r.output_tokens + r.cache_read_tokens)}</td>
              <td className="py-2 text-right">{usd(r.cost_usd, r.cost_usd < 1 ? 3 : 2)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function Usage() {
  const [days, setDays] = useState<"7" | "30" | "90">("30");
  const q = useQuery({ queryKey: ["usage", days], queryFn: () => get<UsageData>(`/api/ai/usage?days=${days}`) });
  const u = q.data;
  const b = u?.budget;
  const monthPct = b?.monthly_limit_usd ? (b.month_usd / b.monthly_limit_usd) * 100 : 0;
  const dayPct = b?.daily_limit_usd ? (b.day_usd / b.daily_limit_usd) * 100 : 0;
  const series = (u?.daily || []).map((d) => ({ key: d.date, label: new Date(`${d.date}T12:00:00`).toLocaleDateString("en-CH", { day: "numeric", month: "short" }), value: d.cost_usd }));

  return (
    <>
      <PageHeader
        title="AI usage"
        sub="Token counts are what the providers report. Costs are estimated from them and the model price list."
        actions={<Link to="/settings/ai"><Button>Limits & keys</Button></Link>}
      />
      {b?.paused_reason && (
        <div className="mb-4">
          <Notice tone="warning" action={<Link to="/settings/ai"><Button size="sm" variant="primary">Review limits</Button></Link>}>
            AI analysis is paused: {b.paused_reason}. New listings are collected but not scored until you raise the limit or the month resets.
          </Notice>
        </div>
      )}
      {q.error ? <ErrorBox error={q.error} onRetry={() => q.refetch()} /> : !u || !b ? <Skeleton className="h-72" /> : (
        <>
          <div className="mb-4 grid gap-4 md:grid-cols-2">
            {[
              { label: "This month", spent: b.month_usd, limit: b.monthly_limit_usd, pct: monthPct },
              { label: "Today", spent: b.day_usd, limit: b.daily_limit_usd, pct: dayPct },
            ].map((x) => (
              <Panel key={x.label} className="px-4 py-4 sm:px-5">
                <div className="flex items-baseline justify-between">
                  <span className="text-[0.8125rem] text-muted">{x.label}, estimated</span>
                  {x.limit ? <span className="num text-[0.8125rem] text-muted">limit {usd(x.limit)}</span> : null}
                </div>
                <p className="num mt-1 text-[1.75rem] leading-tight font-bold tracking-[-0.02em]">{usd(x.spent, x.spent < 1 ? 3 : 2)}</p>
                {x.limit ? (
                  <div className="mt-3">
                    <Meter total={x.limit} label={`${Math.round(x.pct)}% of the limit`} parts={[{ value: x.spent, color: x.pct >= b.warn_pct ? "var(--color-warning)" : "var(--color-ink)", label: "Used" }]} />
                    <p className="num mt-1.5 text-[0.75rem] text-muted">
                      {Math.round(x.pct)}% used · warning at {b.warn_pct}% · analysis pauses at {b.pause_pct}%
                    </p>
                  </div>
                ) : <p className="mt-2 text-[0.75rem] text-muted">No limit set.</p>}
              </Panel>
            ))}
          </div>

          {u.totals.plan_calls > 0 && (
            <div className="mb-4">
              <Notice>
                {u.totals.plan_calls} calls ran on your Claude plan through Claude Code: no API cost. On the API they would have cost about {usd(u.totals.plan_api_equivalent_usd)}.
              </Notice>
            </div>
          )}
          <Panel className="mb-4">
            <PanelHeader
              title="Cost per day"
              sub={`${usd(u.totals.cost_usd, 3)} over ${u.days} days · ${tokens(u.totals.input_tokens + u.totals.output_tokens)} tokens · ${u.totals.calls} calls`}
              action={<Segmented size="sm" label="Period" value={days} onChange={setDays} options={[{ value: "7", label: "7 d" }, { value: "30", label: "30 d" }, { value: "90", label: "90 d" }]} />}
            />
            <div className="px-4 pb-4 sm:px-5">
              <Bars data={series} format={(v) => (v === 0 ? "$0" : v < 0.1 ? `$${v.toFixed(3)}` : `$${v.toFixed(2)}`)} label="Estimated AI cost per day" />
            </div>
            <dl className="num grid grid-cols-2 border-t border-rule text-sm sm:grid-cols-4">
              {[
                ["Input tokens", tokens(u.totals.input_tokens)],
                ["Output tokens", tokens(u.totals.output_tokens)],
                ["Per listing", u.avg_cost_per_listing !== null ? usd(u.avg_cost_per_listing, 4) : "—"],
                ["Per deep analysis", u.avg_cost_per_deep !== null ? usd(u.avg_cost_per_deep, 4) : "—"],
              ].map(([k, v], i) => (
                <div key={k} className={`px-4 py-3 sm:px-5 ${i % 2 ? "border-l border-rule" : ""} ${i >= 2 ? "border-t border-rule sm:border-t-0 sm:border-l" : ""}`}>
                  <dt className="text-[0.75rem] text-muted">{k}</dt>
                  <dd className="mt-0.5">{v}</dd>
                </div>
              ))}
            </dl>
          </Panel>

          <div className="grid gap-4 lg:grid-cols-2">
            <Panel><PanelHeader title="By task" /><Table rows={u.by_kind} name={(r) => KIND[r.key] || r.key} /></Panel>
            <Panel><PanelHeader title="By search" /><Table rows={u.by_search} name={(r) => r.title || "—"} /></Panel>
            <Panel><PanelHeader title="By model" /><Table rows={u.by_model} name={(r) => r.key.split(":")[1]} /></Panel>
            <Panel><PanelHeader title="By provider and key" /><Table rows={[...u.by_provider, ...u.by_scope.map((s) => ({ ...s, key: s.key === "byok" ? "Your own key" : "Shared key" }))]} name={(r) => r.key} /></Panel>
          </div>

          <Panel className="mt-4">
            <PanelHeader title="Recent calls" />
            <div className="overflow-x-auto px-4 pb-3 sm:px-5">
              <table className="num w-full text-sm">
                <thead>
                  <tr className="text-left text-[0.75rem] text-muted">
                    <th className="pb-2 font-normal">When</th>
                    <th className="pb-2 font-normal">Task</th>
                    <th className="hidden pb-2 font-normal md:table-cell">Model</th>
                    <th className="pb-2 text-right font-normal">In / out</th>
                    <th className="pb-2 text-right font-normal">Cost</th>
                  </tr>
                </thead>
                <tbody>
                  {u.recent.slice(0, 20).map((r, i) => (
                    <tr key={i} className="border-t border-rule">
                      <td className="py-2 pr-3 whitespace-nowrap text-muted">{relTime(r.at)}</td>
                      <td className="py-2 pr-3">{KIND[r.kind] || r.kind}{!r.success && <span className="ml-1.5 text-[0.75rem] text-negative" title={r.error || ""}>failed</span>}</td>
                      <td className="hidden py-2 pr-3 text-muted md:table-cell">{r.model}</td>
                      <td className="py-2 text-right whitespace-nowrap">{tokens(r.input_tokens)} / {tokens(r.output_tokens)}</td>
                      <td className="py-2 text-right">{usd(r.cost_usd, 4)}</td>
                    </tr>
                  ))}
                  {u.recent.length === 0 && <tr><td colSpan={5} className="py-3 text-muted">No AI calls yet.</td></tr>}
                </tbody>
              </table>
            </div>
          </Panel>
        </>
      )}
    </>
  );
}
