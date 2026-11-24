import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { Bars, Meter } from "@/components/charts";
import { Button, Empty, ErrorBox, Field, IconButton, Input, PageHeader, Panel, PanelHeader, Sheet, Skeleton, useToast } from "@/components/ui";
import { Picker } from "@/components/Picker";
import { del, get, patch, post } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { money } from "@/lib/format";

interface Item { id: string; title: string; amount: number; currency: string; category: string | null; status: string; month: string; match_id: string | null }
interface Summary {
  month: string; currency: string; monthly_budget: number | null; purchased: number; planned: number; interested: number;
  remaining: number | null; remaining_after_planned: number | null; by_category: { category: string; amount: number }[];
  wishlist_planned: number; history: { month: string; purchased: number }[]; items: Item[];
}

const STATUS_TEXT: Record<string, string> = { planned: "Planned", interested: "Interested", purchased: "Bought", rejected: "Dropped" };

function shift(month: string, by: number) {
  const [y, m] = month.split("-").map(Number);
  const d = new Date(y, m - 1 + by, 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}
const monthName = (m: string) => new Date(`${m}-01T12:00:00`).toLocaleDateString("en-CH", { month: "long", year: "numeric" });

function AddItem({ open, onOpenChange, month }: { open: boolean; onOpenChange: (v: boolean) => void; month: string }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [v, setV] = useState({ title: "", amount: "", category: "", status: "planned" });
  const m = useMutation({
    mutationFn: () => post("/api/budget/items", { title: v.title, amount: Number(v.amount.replace(",", ".")), category: v.category || null, status: v.status, month }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["budget"] });
      onOpenChange(false);
      setV({ title: "", amount: "", category: "", status: "planned" });
    },
    onError: toast.error,
  });
  return (
    <Sheet
      open={open}
      onOpenChange={onOpenChange}
      title="Add to budget"
      description="For purchases outside Schnäppli, or planned ones."
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button variant="primary" disabled={!v.title || !v.amount} loading={m.isPending} onClick={() => m.mutate()}>Add</Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <Field label="What" htmlFor="b-title"><Input id="b-title" value={v.title} onChange={(e) => setV({ ...v, title: e.target.value })} /></Field>
        <div className="grid grid-cols-2 gap-4">
          <Field label="Amount" htmlFor="b-amount"><Input id="b-amount" inputMode="decimal" value={v.amount} onChange={(e) => setV({ ...v, amount: e.target.value })} /></Field>
          <Field label="Status">
            <Picker label="Status" value={v.status} onChange={(s) => setV({ ...v, status: s })}
              options={[{ value: "planned", label: "Planned" }, { value: "interested", label: "Interested" }, { value: "purchased", label: "Bought" }]} />
          </Field>
        </div>
        <Field label="Category" htmlFor="b-cat"><Input id="b-cat" value={v.category} onChange={(e) => setV({ ...v, category: e.target.value })} /></Field>
      </div>
    </Sheet>
  );
}

function SetBudget({ current, currency }: { current: number | null; currency: string }) {
  const qc = useQueryClient();
  const { refresh } = useAuth();
  const [open, setOpen] = useState(false);
  const [v, setV] = useState(current?.toString() ?? "");
  const m = useMutation({
    mutationFn: () => patch("/api/me", { monthly_budget: v ? Number(v.replace(",", ".")) : null }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["budget"] });
      refresh();
      setOpen(false);
    },
  });
  return (
    <>
      <Button size="sm" onClick={() => setOpen(true)}>{current === null ? "Set budget" : "Change"}</Button>
      <Sheet
        open={open}
        onOpenChange={setOpen}
        title="Monthly shopping budget"
        footer={<Button variant="primary" loading={m.isPending} onClick={() => m.mutate()}>Save</Button>}
      >
        <Field label={`Amount per month (${currency})`} htmlFor="mb" hint="Leave empty for no budget.">
          <Input id="mb" inputMode="decimal" value={v} onChange={(e) => setV(e.target.value)} />
        </Field>
      </Sheet>
    </>
  );
}

export default function Budget() {
  const [month, setMonth] = useState(() => new Date().toISOString().slice(0, 7));
  const [adding, setAdding] = useState(false);
  const qc = useQueryClient();
  const toast = useToast();
  const q = useQuery({ queryKey: ["budget", month], queryFn: () => get<Summary>(`/api/budget?month=${month}`) });
  const update = useMutation({ mutationFn: ({ id, status }: { id: string; status: string }) => patch(`/api/budget/items/${id}`, { status }), onSuccess: () => qc.invalidateQueries({ queryKey: ["budget"] }), onError: toast.error });
  const remove = useMutation({ mutationFn: (id: string) => del(`/api/budget/items/${id}`), onSuccess: () => qc.invalidateQueries({ queryKey: ["budget"] }), onError: toast.error });
  const b = q.data;
  const cur = b?.currency || "CHF";
  const over = b && b.remaining !== null && b.remaining < 0;
  const isCurrent = month === new Date().toISOString().slice(0, 7);

  return (
    <>
      <PageHeader
        title="Budget"
        sub="Found listings never count as spent. Only what you mark as bought does."
        actions={<Button variant="primary" onClick={() => setAdding(true)} icon={<Plus className="size-4" aria-hidden />}>Add</Button>}
      />
      <div className="mb-5 flex items-center gap-1">
        <IconButton label="Previous month" onClick={() => setMonth(shift(month, -1))}><ChevronLeft className="size-4" /></IconButton>
        <span className="min-w-[150px] text-center text-[0.9375rem] font-medium">{monthName(month)}</span>
        <IconButton label="Next month" onClick={() => setMonth(shift(month, 1))} disabled={isCurrent} className="disabled:opacity-30"><ChevronRight className="size-4" /></IconButton>
      </div>
      {q.error ? <ErrorBox error={q.error} onRetry={() => q.refetch()} /> : !b ? <Skeleton className="h-64" /> : (
        <>
          <Panel className="mb-4 px-4 py-4 sm:px-5">
            <div className="flex flex-wrap items-baseline justify-between gap-3">
              <div>
                <p className="text-[0.8125rem] text-muted">{b.monthly_budget === null ? "No monthly budget set" : over ? "Over budget by" : "Left this month"}</p>
                <p className={`num mt-0.5 text-[1.875rem] leading-tight font-bold tracking-[-0.02em] ${over ? "text-negative" : ""}`}>
                  {b.monthly_budget === null ? money(b.purchased, cur) : money(Math.abs(b.remaining!), cur)}
                </p>
                {b.monthly_budget === null && <p className="text-[0.8125rem] text-muted">spent so far</p>}
              </div>
              <SetBudget current={b.monthly_budget} currency={cur} />
            </div>
            {b.monthly_budget !== null && (
              <>
                <div className="mt-4">
                  <Meter
                    total={b.monthly_budget}
                    label={`${money(b.purchased, cur)} bought and ${money(b.planned, cur)} planned of ${money(b.monthly_budget, cur)}`}
                    parts={[
                      { value: b.purchased, color: "var(--color-ink)", label: "Bought" },
                      { value: b.planned, color: "var(--color-track-strong)", label: "Planned" },
                    ]}
                  />
                </div>
                <dl className="num mt-3 grid grid-cols-2 gap-y-2 text-[0.8125rem] sm:grid-cols-4">
                  <div><dt className="text-muted">Budget</dt><dd className="text-sm">{money(b.monthly_budget, cur)}</dd></div>
                  <div><dt className="flex items-center gap-1.5 text-muted"><span className="size-2 rounded-full bg-ink" />Bought</dt><dd className="text-sm">{money(b.purchased, cur)}</dd></div>
                  <div><dt className="flex items-center gap-1.5 text-muted"><span className="size-2 rounded-full bg-track-strong" />Planned</dt><dd className="text-sm">{money(b.planned, cur)}</dd></div>
                  <div><dt className="text-muted">Left after planned</dt><dd className={`text-sm ${(b.remaining_after_planned ?? 0) < 0 ? "text-negative" : ""}`}>{money(b.remaining_after_planned, cur)}</dd></div>
                </dl>
              </>
            )}
          </Panel>

          <div className="grid gap-4 lg:grid-cols-12">
            <Panel className="lg:col-span-7">
              <PanelHeader title="This month" sub={`${b.items.length} entries`} />
              {b.items.length === 0 ? (
                <Empty title="Nothing yet">Mark a deal as planned or bought, or add an entry by hand.</Empty>
              ) : (
                <ul className="px-4 pb-2 sm:px-5">
                  {b.items.map((it) => (
                    <li key={it.id} className="flex flex-wrap items-center gap-x-3 gap-y-2 border-t border-rule py-2.5 first:border-t-0 sm:flex-nowrap">
                      <div className="min-w-0 basis-full sm:basis-0 sm:flex-1">
                        <p className={`truncate text-sm ${it.status === "rejected" ? "text-muted line-through" : ""}`}>
                          {it.match_id ? <Link to={`/deals/${it.match_id}`} className="hover:underline">{it.title}</Link> : it.title}
                        </p>
                        <p className="text-[0.75rem] text-muted">{it.category || "No category"}</p>
                      </div>
                      <div className="w-[124px] shrink-0">
                        <Picker size="sm" label={`Status of ${it.title}`} value={it.status} onChange={(s) => update.mutate({ id: it.id, status: s })}
                          options={Object.entries(STATUS_TEXT).map(([k, t]) => ({ value: k, label: t }))} />
                      </div>
                      <span className="num ml-auto shrink-0 text-right text-sm sm:ml-0 sm:w-[90px]">{money(it.amount, it.currency)}</span>
                      <IconButton label={`Remove ${it.title}`} onClick={() => remove.mutate(it.id)}><Trash2 className="size-3.5" /></IconButton>
                    </li>
                  ))}
                </ul>
              )}
            </Panel>
            <div className="flex flex-col gap-4 lg:col-span-5">
              <Panel>
                <PanelHeader title="Spent by category" />
                <ul className="px-4 pb-3 sm:px-5">
                  {b.by_category.length === 0 ? <li className="pb-1 text-sm text-muted">Nothing bought this month.</li> : b.by_category.map((c) => (
                    <li key={c.category} className="num flex justify-between border-t border-rule py-2 text-sm first:border-t-0">
                      <span>{c.category}</span><span>{money(c.amount, cur)}</span>
                    </li>
                  ))}
                </ul>
                <div className="num flex justify-between border-t border-rule px-4 py-3 text-[0.8125rem] sm:px-5">
                  <Link to="/wishlist" className="text-muted hover:text-ink">Wishlist still to buy</Link>
                  <span>{money(b.wishlist_planned, cur)}</span>
                </div>
              </Panel>
              <Panel>
                <PanelHeader title="Bought per month" />
                <div className="px-4 pb-4 sm:px-5">
                  <Bars
                    label="Amount bought per month"
                    data={b.history.map((h) => ({ key: h.month, label: new Date(`${h.month}-01T12:00:00`).toLocaleDateString("en-CH", { month: "short" }), value: h.purchased }))}
                    format={(v) => money(Math.round(v), cur).replace(`${cur} `, "")}
                    height={140}
                  />
                </div>
              </Panel>
            </div>
          </div>
        </>
      )}
      <AddItem open={adding} onOpenChange={setAdding} month={month} />
    </>
  );
}
