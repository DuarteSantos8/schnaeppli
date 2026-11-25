import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowUp, Sparkles } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { emptySpec, FormActions, SearchForm, type SearchValues } from "@/components/SearchForm";
import { Button, ErrorBox, Notice, PageHeader, Panel, Textarea, useToast } from "@/components/ui";
import { ApiError, post } from "@/lib/api";
import { useMe } from "@/lib/auth";
import { money } from "@/lib/format";
import type { Interpretation, Search } from "@/lib/types";

const EXAMPLES = [
  "A digital camera under CHF 300. I like vintage Sony Cyber-shots, but an Alpha 6400 or something comparable would also work.",
  "An RTX 4070 Ti Super or better for less than CHF 600.",
  "A used MacBook Pro with an M4 Pro chip.",
  "A good NAS with at least four drive bays.",
  "Sony E-mount lenses, preferably Sigma or Sony, under CHF 200.",
];

type Turn = { role: "user" | "assistant"; content: string };

function toValues(i: Interpretation, currency: string): SearchValues {
  const d = i.draft;
  return {
    title: d.title,
    category: d.category,
    spec: { ...emptySpec(), ...d.spec },
    max_budget: d.max_budget,
    currency: d.currency || currency,
    condition: d.condition,
    prefer_condition: d.prefer_condition,
    postal_code: null,
    radius_km: d.radius_km,
    delivery: d.delivery,
    sources: {},
    schedule: { mode: "default" },
    notify: { instant_min_score: 85, digest: true },
    priority: d.priority || 2,
    min_score: 55,
  };
}

const DRAFT_KEY = "schnaeppli.new-search-draft";

export default function NewSearch() {
  const me = useMe();
  const nav = useNavigate();
  const qc = useQueryClient();
  const toast = useToast();
  // The draft survives leaving the page (and a slow AI answer arriving while you're elsewhere).
  const saved = (() => { try { return JSON.parse(sessionStorage.getItem(DRAFT_KEY) || "null"); } catch { return null; } })();
  const [text, setText] = useState("");
  const [turns, setTurns] = useState<Turn[]>(saved?.turns ?? []);
  const [result, setResult] = useState<Interpretation | null>(saved?.result ?? null);
  const [values, setValues] = useState<SearchValues | null>(saved?.values ?? null);
  useEffect(() => {
    if (turns.length || result) sessionStorage.setItem(DRAFT_KEY, JSON.stringify({ turns, result, values }));
    else sessionStorage.removeItem(DRAFT_KEY);
  }, [turns, result, values]);
  const [manual, setManual] = useState(false);

  const interpret = useMutation({
    mutationFn: (t: Turn[]) => post<Interpretation>("/api/searches/interpret", { turns: t }),
    onSuccess: (r, t) => {
      setResult(r);
      setValues(toValues(r, me.currency));
      if (r.needs_clarification && r.questions.length) setTurns([...t, { role: "assistant", content: r.questions.join("\n") }]);
      else setTurns(t);
    },
  });

  const create = useMutation({
    mutationFn: (v: SearchValues) => post<Search>("/api/searches", { ...v, prompt: turns.filter((t) => t.role === "user").map((t) => t.content).join("\n\n") }),
    onSuccess: (s) => {
      qc.invalidateQueries({ queryKey: ["searches"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      sessionStorage.removeItem(DRAFT_KEY);
      toast.show("Search created. The first run has started.");
      nav(`/searches/${s.id}`);
    },
    onError: toast.error,
  });

  const send = () => {
    const t = text.trim();
    if (!t) return;
    const next = [...turns, { role: "user" as const, content: t }];
    setTurns(next);
    setText("");
    interpret.mutate(next);
  };

  const submit = (v: SearchValues) =>
    create.mutate({ ...v, spec: { ...v.spec, desired_products: v.spec.desired_products.filter((p) => p.name.trim()), alternatives: v.spec.alternatives.filter((p) => p.name.trim()) } });

  const noProvider = interpret.error instanceof ApiError && interpret.error.status === 409;
  const asking = result?.needs_clarification && result.questions.length > 0;

  if (manual || (values && !asking)) {
    const v = values ?? {
      title: "", category: null, spec: emptySpec(), max_budget: null, currency: me.currency, condition: "any" as const,
      prefer_condition: null, postal_code: null, radius_km: null, delivery: null, sources: {}, schedule: { mode: "default" as const },
      notify: { instant_min_score: 85, digest: true }, priority: 2, min_score: 55,
    };
    return (
      <>
        <PageHeader
          title={manual && !result ? "New search" : "Check what I understood"}
          sub={manual && !result ? "Fill in what you're looking for." : "Change anything that's off, then press Create search. Nothing is searched until then."}
          actions={result ? <Button variant="primary" loading={create.isPending} disabled={!v.title.trim()} onClick={() => submit(v)}>Create search</Button> : undefined}
        />
        {result && (
          <Panel className="mb-6 px-4 py-4 sm:px-5">
            <p className="text-[0.9375rem] leading-relaxed">{result.draft.summary}</p>
            <div className="mt-3 flex flex-wrap gap-x-6 gap-y-1 text-[0.8125rem] text-muted">
              {result.draft.max_budget !== null && <span>Budget {money(result.draft.max_budget, result.draft.currency)}</span>}
              <span>{result.draft.spec.desired_products.length} products, {result.draft.spec.alternatives.length} alternatives</span>
              <span>{result.draft.spec.queries.length} search terms</span>
            </div>
            {result.assumptions.length > 0 && (
              <div className="mt-4 border-t border-rule pt-3">
                <p className="text-[0.8125rem] font-medium">Assumptions to check</p>
                <ul className="mt-1 list-disc space-y-0.5 pl-5 text-[0.8125rem] text-muted">
                  {result.assumptions.map((a, i) => <li key={i}>{a}</li>)}
                </ul>
              </div>
            )}
          </Panel>
        )}
        <Panel className="px-4 py-5 sm:px-6">
          <SearchForm value={v} onChange={setValues} />
        </Panel>
        <FormActions>
          <Button
            variant="ghost"
            onClick={() => {
              setResult(null);
              setValues(null);
              setManual(false);
              setTurns([]);
              sessionStorage.removeItem(DRAFT_KEY);
            }}
          >
            Start over
          </Button>
          <Button
            variant="primary"
            loading={create.isPending}
            disabled={!v.title.trim()}
            onClick={() => submit(v)}
          >
            Create search
          </Button>
        </FormActions>
      </>
    );
  }

  return (
    <div className="mx-auto max-w-[680px]">
      <PageHeader title="What are you looking for?" sub="Describe it the way you'd tell a friend. Budget, models you like, what's a deal-breaker." />

      {turns.length > 0 && (
        <ol className="mb-4 flex flex-col gap-3" aria-label="Conversation">
          {turns.map((t, i) => (
            <li
              key={i}
              className={
                t.role === "user"
                  ? "ml-auto max-w-[85%] rounded-[14px] rounded-br-[4px] bg-ink px-4 py-2.5 text-[0.9375rem] text-on-ink"
                  : "max-w-[90%] rounded-[14px] rounded-bl-[4px] bg-surface px-4 py-3 text-[0.9375rem] whitespace-pre-line"
              }
            >
              {t.role === "assistant" && <span className="mb-1 block text-[0.75rem] font-medium text-muted">A few questions before Schnäppli starts searching</span>}
              {t.content}
            </li>
          ))}
        </ol>
      )}

      {interpret.isPending && (
        <p className="mb-4 flex items-center gap-2 text-sm text-muted" role="status">
          <Sparkles className="size-4 animate-pulse" aria-hidden /> Reading your request… this can take up to a minute. You can leave the page; your draft stays.
        </p>
      )}
      {interpret.error && !noProvider ? <div className="mb-4"><ErrorBox error={interpret.error} onRetry={() => interpret.mutate(turns)} /></div> : null}
      {noProvider && (
        <div className="mb-4">
          <Notice
            tone="warning"
            action={
              <div className="flex gap-2">
                <Link to="/settings/ai"><Button size="sm" variant="primary">Add a key</Button></Link>
                <Button size="sm" onClick={() => setManual(true)}>Set up by hand</Button>
              </div>
            }
          >
            No AI provider is configured yet, so Schnäppli can't read your request.
          </Notice>
        </div>
      )}

      <div className="rounded-[12px] border border-border bg-surface p-2 focus-within:border-ink">
        <Textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) send();
          }}
          rows={asking ? 3 : 5}
          maxLength={4000}
          placeholder={asking ? "Your answers" : "I'm looking for…"}
          aria-label={asking ? "Your answers" : "Describe what you're looking for"}
          className="border-0 px-2 focus:border-0"
        />
        <div className="flex items-center justify-between gap-2 px-1 pt-1">
          <button onClick={() => setManual(true)} className="px-1 text-[0.8125rem] text-muted hover:text-ink">
            Set up by hand instead
          </button>
          <Button variant="primary" onClick={send} disabled={!text.trim()} loading={interpret.isPending} icon={!interpret.isPending ? <ArrowUp className="size-4" aria-hidden /> : undefined}>
            {asking ? "Answer" : "Continue"}
          </Button>
        </div>
      </div>
      {asking && values && (
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <Button size="sm" onClick={() => setResult({ ...result!, needs_clarification: false })}>Skip the questions</Button>
          <span className="text-[0.8125rem] text-muted">Nothing is searched yet. Answer above, or skip and check the search.</span>
        </div>
      )}

      {turns.length === 0 && (
        <div className="mt-8">
          <p className="mb-2 text-[0.8125rem] text-muted">For example</p>
          <ul className="flex flex-col">
            {EXAMPLES.map((e) => (
              <li key={e}>
                <button onClick={() => setText(e)} className="hover-lift w-full rounded-[var(--radius-control)] px-3 py-2.5 text-left text-sm text-ink-2">
                  {e}
                </button>
              </li>
            ))}
          </ul>
          <p className="mt-6 text-[0.8125rem] text-muted">
            Your request goes to your configured AI provider. Your postal code and address are never included.
          </p>
        </div>
      )}
    </div>
  );
}
