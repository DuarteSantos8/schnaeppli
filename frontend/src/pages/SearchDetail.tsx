import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Link2, Play } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { DealCard, DealGridSkeleton } from "@/components/deal";
import { FormActions, SearchForm, type SearchValues } from "@/components/SearchForm";
import { Button, Chip, Empty, ErrorBox, Field, Input, Notice, Panel, Pill, Segmented, Sheet, Skeleton, useToast } from "@/components/ui";
import { get, patch, post } from "@/lib/api";
import { dayTime, money, relTime, SOURCE_NAME } from "@/lib/format";
import type { Deal, DealDetail, InboxInfo, MailConnection, Search } from "@/lib/types";
import { AlertButtons } from "@/components/alerts";
import { SearchMenu, StatusPill } from "./Searches";

interface Run {
  id: string;
  started_at: string;
  finished_at: string | null;
  status: string;
  fetched: number;
  new_matches: number;
  source_report: Record<string, { queries?: number; results?: number; new?: number; error?: string }>;
  error: string | null;
}

function AddByLink({ searchId, open, onOpenChange }: { searchId: string; open: boolean; onOpenChange: (v: boolean) => void }) {
  const [url, setUrl] = useState("");
  const nav = useNavigate();
  const qc = useQueryClient();
  const m = useMutation({
    mutationFn: () => post<DealDetail>("/api/deals/import", { url, search_id: searchId }),
    onSuccess: (d) => {
      qc.invalidateQueries({ queryKey: ["matches", searchId] });
      onOpenChange(false);
      nav(`/deals/${d.id}`);
    },
  });
  return (
    <Sheet
      open={open}
      onOpenChange={onOpenChange}
      title="Add a listing by link"
      description="Schnäppli reads the page once, only if the site's robots.txt allows it, and scores it for this search."
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button variant="primary" loading={m.isPending} disabled={!url.startsWith("https://")} onClick={() => m.mutate()}>Add and analyse</Button>
        </>
      }
    >
      <Field label="Link" htmlFor="link" hint="Works with shops that publish product data (most retailers). Some marketplaces block automated reading.">
        <Input id="link" type="url" inputMode="url" value={url} onChange={(e) => setUrl(e.target.value.trim())} placeholder="https://" autoCapitalize="none" />
      </Field>
      {m.error ? <div className="mt-3"><ErrorBox error={m.error} /></div> : null}
    </Sheet>
  );
}

/** The searches to save on Ricardo and tutti, so their alert mails reach Schnäppli. */
function AlertLinks({ s }: { s: Search }) {
  const inbox = useQuery({ queryKey: ["inbox"], queryFn: () => get<InboxInfo>("/api/sources/inbox"), staleTime: 300_000 });
  const own = useQuery({ queryKey: ["setup-mail"], queryFn: () => get<{ connection: MailConnection | null }>("/api/setup/mail"), staleTime: 300_000 });
  const key = `schnaeppli.alerts-done.${s.id}`;
  const [done, setDone] = useState(() => localStorage.getItem(key) === "1");
  if (!inbox.data || !own.data || done || s.status !== "active") return null;
  const c = own.data.connection;
  if (!c && !inbox.data.configured) {
    return (
      <div className="mb-4">
        <Notice action={<Link to="/setup#mail"><Button size="sm">Connect</Button></Link>}>
          Ricardo, tutti, Facebook and Toppreise can feed this search through their own alert e-mails. Connect your mailbox once to get them.
        </Notice>
      </div>
    );
  }
  const terms = (s.spec.queries?.length ? s.spec.queries : [s.title]).slice(0, 3);
  return (
    <Panel className="mb-4 px-4 py-4 sm:px-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 max-w-prose">
          <h2 className="text-[0.9375rem] font-semibold">Also watch Ricardo, tutti, Facebook and Toppreise</h2>
          <p className="mt-1 text-[0.8125rem] text-muted">
            Open each search and save it there with e-mail alerts. Ricardo: “Suche speichern”. tutti: “Suchauftrag speichern”. Facebook: “Suche speichern” and turn on e-mail for Marketplace under Settings → Notifications. Toppreise: open the product you want and tap the bell (price alert) with your e-mail.
            {c
              ? <> Schnäppli reads the alerts from <span className="font-medium text-ink">{c.address}</span>, and new listings show up here, scored.</>
              : <> Their alert mails are forwarded to {inbox.data.address ? <span className="font-medium text-ink">{inbox.data.address}</span> : "Schnäppli's inbox"}, and new listings show up here, scored.</>}
          </p>
        </div>
        <Button size="sm" variant="ghost" onClick={() => { localStorage.setItem(key, "1"); setDone(true); }}>Done</Button>
      </div>
      <ul className="mt-3 divide-y divide-rule">
        {terms.map((t) => (
          <li key={t} className="flex flex-wrap items-center justify-between gap-2 py-2">
            <span className="min-w-0 truncate text-sm">{t}</span>
            <AlertButtons term={t} />
          </li>
        ))}
      </ul>
    </Panel>
  );
}

function Results({ s }: { s: Search }) {
  const [sort, setSort] = useState<"score" | "newest" | "price">("score");
  const [showSkipped, setShowSkipped] = useState(false);
  const q = useQuery({
    queryKey: ["matches", s.id, sort, showSkipped],
    queryFn: () => get<Deal[]>(`/api/searches/${s.id}/matches?sort=${sort}&include_irrelevant=${showSkipped}`),
  });
  return (
    <>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <Segmented
          size="sm"
          label="Sort"
          value={sort}
          onChange={setSort}
          options={[
            { value: "score", label: "Best score" },
            { value: "newest", label: "Newest" },
            { value: "price", label: "Lowest price" },
          ]}
        />
        <Chip active={showSkipped} onClick={() => setShowSkipped((v) => !v)}>Show filtered-out</Chip>
      </div>
      {q.error ? (
        <ErrorBox error={q.error} onRetry={() => q.refetch()} />
      ) : q.isLoading ? (
        <DealGridSkeleton n={4} />
      ) : (q.data || []).length === 0 ? (
        <Panel>
          <Empty title={s.last_run_at ? "No matches yet" : "Waiting for the first run"}>
            {s.last_run_at
              ? "The last run found nothing that fits. Try broader search terms or a higher budget in Settings."
              : `The first run is queued. Next run ${dayTime(s.next_run_at)}.`}
          </Empty>
        </Panel>
      ) : (
        <div className="grid grid-cols-2 gap-x-3 gap-y-6 sm:gap-x-4 md:grid-cols-3 xl:grid-cols-4">
          {q.data!.map((d, i) => (
            <div key={d.id} className={d.relevance === "irrelevant" ? "opacity-60" : ""}>
              <DealCard deal={d} eager={i < 4} />
              {d.relevance === "irrelevant" && d.skip_reason && <p className="mt-1 text-[0.75rem] text-muted">Skipped: {d.skip_reason}</p>}
              {d.analysis_state === "limited" && <p className="mt-1 text-[0.75rem] text-warning">Not analysed: AI limit reached</p>}
            </div>
          ))}
        </div>
      )}
    </>
  );
}

function History({ s }: { s: Search }) {
  const q = useQuery({ queryKey: ["runs", s.id], queryFn: () => get<Run[]>(`/api/searches/${s.id}/runs`) });
  if (q.isLoading) return <Skeleton className="h-40" />;
  if (!q.data?.length) return <Panel><Empty title="No runs yet" /></Panel>;
  return (
    <Panel>
      <ul>
        {q.data.map((r) => (
          <li key={r.id} className="border-t border-rule px-4 py-3 first:border-t-0 sm:px-5">
            <div className="flex items-baseline justify-between gap-3">
              <span className="text-sm">
                {dayTime(r.started_at)}{" "}
                {r.status !== "ok" && <Pill tone={r.status === "failed" ? "negative" : "warning"}>{r.status}</Pill>}
              </span>
              <span className="num text-[0.8125rem] text-muted">
                {r.fetched} checked · <span className={r.new_matches ? "text-ink" : ""}>{r.new_matches} new</span>
              </span>
            </div>
            <div className="mt-1 flex flex-wrap gap-x-4 text-[0.75rem] text-muted">
              {Object.entries(r.source_report).map(([src, rep]) => (
                <span key={src}>
                  {SOURCE_NAME[src] || src}: {rep.error ? <span className="text-negative">{rep.error}</span> : `${rep.results ?? 0} results from ${rep.queries ?? 0} queries`}
                </span>
              ))}
            </div>
          </li>
        ))}
      </ul>
    </Panel>
  );
}

function Edit({ s }: { s: Search }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [v, setV] = useState<SearchValues>(s);
  useEffect(() => setV(s), [s]);
  const save = useMutation({
    mutationFn: () => patch<Search>(`/api/searches/${s.id}`, {
      title: v.title, category: v.category, spec: v.spec, max_budget: v.max_budget, condition: v.condition,
      prefer_condition: v.prefer_condition, postal_code: v.postal_code, radius_km: v.radius_km, delivery: v.delivery,
      sources: v.sources, schedule: v.schedule, notify: v.notify, priority: v.priority, min_score: v.min_score,
    }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["search", s.id] });
      qc.invalidateQueries({ queryKey: ["searches"] });
      toast.show("Saved. Changes apply from the next run.");
    },
    onError: toast.error,
  });
  const dirty = JSON.stringify(v) !== JSON.stringify(s);
  return (
    <>
      {s.prompt && (
        <Panel className="mb-4 px-4 py-3 sm:px-5">
          <p className="text-[0.75rem] text-muted">Your original request</p>
          <p className="mt-1 text-sm whitespace-pre-line">{s.prompt}</p>
        </Panel>
      )}
      <Panel className="px-4 py-5 sm:px-6">
        <SearchForm value={v} onChange={setV} />
      </Panel>
      {dirty && (
        <FormActions>
          <Button variant="ghost" onClick={() => setV(s)}>Discard</Button>
          <Button variant="primary" loading={save.isPending} onClick={() => save.mutate()}>Save changes</Button>
        </FormActions>
      )}
    </>
  );
}

export default function SearchDetail() {
  const { id } = useParams();
  const nav = useNavigate();
  const qc = useQueryClient();
  const toast = useToast();
  const [tab, setTab] = useState<"results" | "settings" | "history">("results");
  const [linkOpen, setLinkOpen] = useState(false);
  const q = useQuery({ queryKey: ["search", id], queryFn: () => get<Search>(`/api/searches/${id}`) });
  const run = useMutation({
    mutationFn: () => post(`/api/searches/${id}/run`),
    onSuccess: () => {
      toast.show("Run started. New results appear in a minute or two.");
      setTimeout(() => {
        qc.invalidateQueries({ queryKey: ["matches", id] });
        qc.invalidateQueries({ queryKey: ["search", id] });
      }, 20_000);
    },
    onError: toast.error,
  });
  if (q.error) return <ErrorBox error={q.error} onRetry={() => q.refetch()} />;
  const s = q.data;
  if (!s) return <div className="space-y-3"><Skeleton className="h-8 w-64" /><Skeleton className="h-64" /></div>;

  return (
    <>
      <Link to="/searches" className="mb-3 inline-flex items-center gap-1 text-sm text-muted hover:text-ink">
        <ArrowLeft className="size-4" aria-hidden /> Searches
      </Link>
      <header className="mb-5 flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <h1 className="truncate text-[1.375rem] font-semibold tracking-[-0.02em] sm:text-[1.5rem]">{s.title}</h1>
            <StatusPill status={s.status} />
          </div>
          <p className="num mt-1 text-sm text-muted">
            {s.max_budget !== null ? `Up to ${money(s.max_budget, s.currency)}` : "No budget"} ·{" "}
            {s.stats.matches ?? 0} matches · {s.stats.good_deals ?? 0} good deals ·{" "}
            {s.status === "active" ? `checked ${relTime(s.last_run_at)}, next ${dayTime(s.next_run_at)}` : "not running"}
          </p>
          {s.last_error && <p className="mt-1 text-[0.8125rem] text-negative">Last run: {s.last_error}</p>}
        </div>
        <div className="flex items-center gap-2">
          <Button onClick={() => setLinkOpen(true)} icon={<Link2 className="size-4" aria-hidden />}>
            <span className="hidden sm:inline">Add by link</span>
            <span className="sm:hidden">Link</span>
          </Button>
          {s.status === "active" && (
            <Button variant="primary" onClick={() => run.mutate()} loading={run.isPending} icon={<Play className="size-4" aria-hidden />}>
              Run now
            </Button>
          )}
          <SearchMenu s={s} onDeleted={() => nav("/searches")} />
        </div>
      </header>
      <div className="mb-5">
        <Segmented
          label="Section"
          value={tab}
          onChange={setTab}
          options={[
            { value: "results", label: "Results" },
            { value: "settings", label: "Settings" },
            { value: "history", label: "History" },
          ]}
        />
      </div>
      {tab === "results" && <><AlertLinks s={s} /><Results s={s} /></>}
      {tab === "settings" && <Edit s={s} />}
      {tab === "history" && <History s={s} />}
      <AddByLink searchId={s.id} open={linkOpen} onOpenChange={setLinkOpen} />
    </>
  );
}
