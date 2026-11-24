import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Copy, ExternalLink, Trash2 } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { NavLink, useParams } from "react-router-dom";
import { TagInput } from "@/components/SearchForm";
import { Button, Confirm, cx, ErrorBox, Field, IconButton, Input, Notice, PageHeader, Pill, Segmented, Sheet, Skeleton, SwitchRow, useToast } from "@/components/ui";
import { del, get, patch, post, put } from "@/lib/api";
import { useAuth, useMe } from "@/lib/auth";
import { relTime, usd } from "@/lib/format";
import type { AILimits, InboxInfo, NotificationPrefs, SourceInfo, User } from "@/lib/types";
import { Picker } from "@/components/Picker";
import Appearance from "./Appearance";

const TABS = [
  { id: "", label: "General" },
  { id: "appearance", label: "Appearance" },
  { id: "notifications", label: "Notifications" },
  { id: "ai", label: "AI" },
  { id: "sources", label: "Sources" },
  { id: "security", label: "Security" },
  { id: "data", label: "Privacy & data" },
  { id: "admin", label: "Admin", admin: true },
];

function Row({ title, description, children }: { title: string; description?: ReactNode; children: ReactNode }) {
  return (
    <section className="grid gap-3 border-t border-border py-7 first:border-t-0 first:pt-0 md:grid-cols-[minmax(0,320px)_1fr] md:gap-10">
      <div>
        <h2 className="text-[0.9375rem] font-semibold">{title}</h2>
        {description && <div className="mt-1 text-[0.8125rem] leading-relaxed text-muted">{description}</div>}
      </div>
      <div className="min-w-0 rounded-[12px] bg-surface p-4 sm:p-5">{children}</div>
    </section>
  );
}

function useSaveMe() {
  const qc = useQueryClient();
  const toast = useToast();
  return useMutation({
    mutationFn: (body: Partial<User> | Record<string, unknown>) => patch<User>("/api/me", body),
    onSuccess: (u) => {
      qc.setQueryData(["me"], u);
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      toast.show("Saved");
    },
    onError: toast.error,
  });
}

/* ------------------------------------------------------------------ General */
function General() {
  const me = useMe();
  const save = useSaveMe();
  const [v, setV] = useState({
    display_name: me.display_name, postal_code: me.postal_code || "", city: me.city || "", radius_km: String(me.radius_km),
    delivery: me.delivery, timezone: me.timezone, currency: me.currency,
  });
  const [times, setTimes] = useState(me.search_schedule.times);
  const zones = typeof Intl.supportedValuesOf === "function" ? Intl.supportedValuesOf("timeZone") : [me.timezone];
  return (
    <>
      <Row title="Profile">
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Name" htmlFor="g-name"><Input id="g-name" value={v.display_name} onChange={(e) => setV({ ...v, display_name: e.target.value })} /></Field>
          <Field label="E-mail"><Input value={me.email} disabled /></Field>
          <Field label="Timezone">
            <Picker label="Timezone" value={v.timezone} onChange={(z) => setV({ ...v, timezone: z })} searchable
              options={zones.map((z) => ({ value: z, label: z.replace(/_/g, " ") }))} />
          </Field>
          <Field label="Currency">
            <Picker label="Currency" value={v.currency} onChange={(c) => setV({ ...v, currency: c })}
              options={[{ value: "CHF", label: "CHF", hint: "Swiss franc" }, { value: "EUR", label: "EUR", hint: "Euro" }, { value: "USD", label: "USD", hint: "US dollar" }, { value: "GBP", label: "GBP", hint: "Pound sterling" }]} />
          </Field>
        </div>
        <div className="mt-4 flex justify-end">
          <Button variant="primary" loading={save.isPending} onClick={() => save.mutate({ display_name: v.display_name, timezone: v.timezone, currency: v.currency })}>Save</Button>
        </div>
      </Row>
      <Row
        title="Location"
        description="Used on this server to estimate pickup distances (straight line × 1.3, always shown as an estimate). Your street address is never asked for, and your location is not sent to AI providers unless you allow it under AI."
      >
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Postal code" htmlFor="g-plz" hint={me.has_coordinates ? `Found: ${me.city || "ok"}` : me.postal_code ? "Not found in the Swiss postal code list" : undefined}>
            <Input id="g-plz" inputMode="numeric" autoComplete="postal-code" value={v.postal_code} onChange={(e) => setV({ ...v, postal_code: e.target.value })} placeholder="8001" />
          </Field>
          <Field label="City" htmlFor="g-city"><Input id="g-city" value={v.city} onChange={(e) => setV({ ...v, city: e.target.value })} placeholder="Zürich" /></Field>
          <Field label="Pickup radius (km)" htmlFor="g-radius"><Input id="g-radius" inputMode="numeric" value={v.radius_km} onChange={(e) => setV({ ...v, radius_km: e.target.value })} /></Field>
        </div>
        <div className="mt-4">
          <Field label="Delivery">
            <Segmented label="Delivery" value={v.delivery} onChange={(d) => setV({ ...v, delivery: d })} options={[{ value: "both", label: "Ship or pick up" }, { value: "ship", label: "Shipping only" }, { value: "pickup", label: "Pickup only" }]} />
          </Field>
        </div>
        <div className="mt-4 flex justify-end">
          <Button
            variant="primary"
            loading={save.isPending}
            onClick={() => save.mutate({ postal_code: v.postal_code || null, city: v.city || null, radius_km: Number(v.radius_km) || 50, delivery: v.delivery })}
          >
            Save
          </Button>
        </div>
      </Row>
      <Row title="Daily search runs" description="When your searches run, unless a search has its own schedule. Default: before each digest.">
        <Field label="Times (24-hour)" hint="Press Enter after each time.">
          <TagInput label="Search times" value={times} onChange={(t) => setTimes(t.filter((x) => /^([01]\d|2[0-3]):[0-5]\d$/.test(x)))} placeholder="06:30" />
        </Field>
        <div className="mt-4 flex justify-end">
          <Button variant="primary" disabled={!times.length} loading={save.isPending} onClick={() => save.mutate({ search_schedule: { times } })}>Save</Button>
        </div>
      </Row>
    </>
  );
}

/* ------------------------------------------------------------ Notifications */
function Telegram() {
  const qc = useQueryClient();
  const toast = useToast();
  const status = useQuery({
    queryKey: ["telegram"],
    queryFn: () => get<{ configured: boolean; bot_username: string | null; linked: boolean; username: string | null; linked_at: string | null }>("/api/notifications/telegram"),
    refetchInterval: (q) => (q.state.data && !q.state.data.linked ? 4000 : false),
  });
  const [code, setCode] = useState<{ code: string; deep_link: string | null } | null>(null);
  const gen = useMutation({ mutationFn: () => post<{ code: string; deep_link: string | null }>("/api/notifications/telegram/code"), onSuccess: setCode, onError: toast.error });
  const unlink = useMutation({ mutationFn: () => del("/api/notifications/telegram"), onSuccess: () => qc.invalidateQueries({ queryKey: ["telegram"] }) });
  const test = useMutation({ mutationFn: () => post("/api/notifications/telegram/test"), onSuccess: () => toast.show("Test message sent"), onError: toast.error });
  const digest = useMutation({ mutationFn: () => post<{ result: string }>("/api/notifications/digest"), onSuccess: (r) => toast.show(`Digest: ${r.result}`), onError: toast.error });
  const s = status.data;
  if (!s) return <Skeleton className="h-20" />;
  if (!s.configured) return <Notice tone="warning">Telegram isn't set up on this server yet. The administrator needs to add a bot token (see the docs, “Telegram setup”).</Notice>;
  if (s.linked)
    return (
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm">Connected{s.username ? ` as @${s.username}` : ""} {s.linked_at ? `· ${relTime(s.linked_at)}` : ""}</p>
        <div className="flex gap-2">
          <Button size="sm" onClick={() => test.mutate()} loading={test.isPending}>Send test</Button>
          <Button size="sm" onClick={() => digest.mutate()} loading={digest.isPending}>Digest now</Button>
          <Button size="sm" variant="danger" onClick={() => unlink.mutate()}>Disconnect</Button>
        </div>
      </div>
    );
  return code ? (
    <div className="flex flex-col gap-3 text-sm">
      <p>Open the bot and press Start, or send it this code. It expires in 10 minutes.</p>
      <p className="num text-[1.75rem] font-semibold tracking-[0.12em]">{code.code}</p>
      <div className="flex flex-wrap gap-2">
        {code.deep_link && (
          <a href={code.deep_link} target="_blank" rel="noopener noreferrer">
            <Button variant="primary" icon={<ExternalLink className="size-4" aria-hidden />}>Open @{s.bot_username}</Button>
          </a>
        )}
        <Button icon={<Copy className="size-4" aria-hidden />} onClick={() => navigator.clipboard?.writeText(`/start ${code.code}`).then(() => toast.show("Copied"))}>Copy “/start {code.code}”</Button>
      </div>
      <p className="text-[0.8125rem] text-muted">Waiting for Telegram…</p>
    </div>
  ) : (
    <div className="flex flex-wrap items-center justify-between gap-3">
      <p className="text-sm text-muted">Get deal alerts and your digest in Telegram.</p>
      <Button variant="primary" onClick={() => gen.mutate()} loading={gen.isPending}>Connect Telegram</Button>
    </div>
  );
}

function Notifications() {
  const me = useMe();
  const save = useSaveMe();
  const [p, setP] = useState<NotificationPrefs>(me.notification_prefs);
  useEffect(() => setP(me.notification_prefs), [me.notification_prefs]);
  const set = <K extends keyof NotificationPrefs>(k: K, val: NotificationPrefs[K]) => setP({ ...p, [k]: val });
  const dirty = JSON.stringify(p) !== JSON.stringify(me.notification_prefs);
  const days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
  return (
    <>
      <Row title="Telegram" description="Linking uses a one-time code. Schnäppli stores only your chat id; the bot token stays on the server.">
        <Telegram />
      </Row>
      <Row title="Instant alerts" description="Sent the moment a listing is analysed. Mediocre offers never alert.">
        <div className="divide-y divide-rule">
          <SwitchRow title="Exceptional deals" description="Score 85 and up, or your per-search threshold." checked={p.instant_exceptional} onChange={(v) => set("instant_exceptional", v)} />
          <SwitchRow title="Good deals" description="Score 70 to 84. Can be chatty." checked={p.instant_good} onChange={(v) => set("instant_good", v)} />
          <SwitchRow title="Price drops" description="On listings you saved or that scored well." checked={p.price_drops} onChange={(v) => set("price_drops", v)} />
          <SwitchRow title="Search problems" description="When a search fails, at most once a day." checked={p.search_failures} onChange={(v) => set("search_failures", v)} />
          <SwitchRow title="AI budget warnings" description="When spending crosses your warning threshold." checked={p.usage_warnings} onChange={(v) => set("usage_warnings", v)} />
        </div>
      </Row>
      <Row title="Daily digest" description="A summary of what's new. It never re-analyses listings, and when nothing interesting turned up it says so in one line, or stays quiet if there was nothing at all.">
        <SwitchRow title="Send digests" checked={p.digest_enabled} onChange={(v) => set("digest_enabled", v)} />
        {p.digest_enabled && (
          <div className="mt-2 flex flex-col gap-4">
            <Field label="Times" hint="24-hour, your timezone. Press Enter after each.">
              <TagInput label="Digest times" value={p.digest_times} onChange={(t) => set("digest_times", t.filter((x) => /^([01]\d|2[0-3]):[0-5]\d$/.test(x)))} />
            </Field>
            <Field label="Days">
              <div className="flex flex-wrap gap-1.5">
                {days.map((d, i) => {
                  const on = p.digest_days.includes(i);
                  return (
                    <button key={d} aria-pressed={on} onClick={() => set("digest_days", on ? p.digest_days.filter((x) => x !== i) : [...p.digest_days, i].sort())}
                      className={cx("pressable h-9 w-12 rounded-[var(--radius-control)] text-[0.8125rem] font-medium", on ? "bg-ink text-on-ink" : "bg-raised text-muted")}>
                      {d}
                    </button>
                  );
                })}
              </div>
            </Field>
            <div className="grid grid-cols-2 gap-4">
              <Field label="Minimum score" htmlFor="d-min"><Input id="d-min" inputMode="numeric" value={p.digest_min_score} onChange={(e) => set("digest_min_score", Math.min(100, Number(e.target.value) || 0))} /></Field>
              <Field label="Max results" htmlFor="d-max"><Input id="d-max" inputMode="numeric" value={p.digest_max_results} onChange={(e) => set("digest_max_results", Math.max(1, Math.min(30, Number(e.target.value) || 1)))} /></Field>
            </div>
            <div className="divide-y divide-rule">
              <SwitchRow title="Include price drops" checked={p.digest_include_price_drops} onChange={(v) => set("digest_include_price_drops", v)} />
              <SwitchRow title="Include alternatives" checked={p.digest_include_alternatives} onChange={(v) => set("digest_include_alternatives", v)} />
              <SwitchRow title="Include accessories" checked={p.digest_include_accessories} onChange={(v) => set("digest_include_accessories", v)} />
            </div>
          </div>
        )}
      </Row>
      {dirty && (
        <div className="sticky bottom-[calc(var(--safe-bottom)+64px)] flex justify-end gap-2 lg:bottom-4">
          <Button variant="ghost" onClick={() => setP(me.notification_prefs)}>Discard</Button>
          <Button variant="primary" loading={save.isPending} onClick={() => save.mutate({ notification_prefs: p })}>Save changes</Button>
        </div>
      )}
    </>
  );
}

/* ----------------------------------------------------------------------- AI */
interface Cred { id: string; provider: string; label: string; key_hint: string; base_url: string | null; models: Record<string, string>; shared: boolean; shared_with_users: boolean; last_tested_at: string | null; last_test_ok: boolean | null; last_test_error: string | null }
interface Catalog { providers: string[]; defaults: Record<string, string>; kinds: string[]; models: { provider: string; id: string; label: string; vision: boolean; input_per_m: number | null; output_per_m: number | null; notes: string }[] }

const PROVIDER_NAME: Record<string, string> = { anthropic: "Anthropic (Claude)", openai: "OpenAI", gemini: "Google Gemini", claude_code: "Claude Code (your plan)" };
const KIND_NAME: Record<string, string> = { default: "Default", prompt_interpretation: "Understanding requests", quick_scan: "Quick scans", deep_analysis: "Deep analysis", vision_analysis: "Photo checks", digest_generation: "Digests", chat: "Assistant" };

function AddKey({ open, onOpenChange, shared }: { open: boolean; onOpenChange: (v: boolean) => void; shared?: boolean }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [v, setV] = useState({ provider: "anthropic", label: "", api_key: "", shared_with_users: true });
  const m = useMutation({
    mutationFn: async () => {
      const c = await post<Cred>(`/api/ai/credentials${shared ? "?shared=true" : ""}`, { ...v, label: v.label || PROVIDER_NAME[v.provider] });
      return post<Cred>(`/api/ai/credentials/${c.id}/test`);
    },
    onSuccess: (c) => {
      qc.invalidateQueries({ queryKey: ["creds"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      onOpenChange(false);
      setV({ provider: "anthropic", label: "", api_key: "", shared_with_users: true });
      if (c.last_test_ok) toast.show("Key works and is saved");
      else toast.error(new Error(`Saved, but the test failed: ${c.last_test_error}`));
    },
    onError: toast.error,
  });
  return (
    <Sheet
      open={open}
      onOpenChange={onOpenChange}
      title={shared ? "Add a shared key" : "Add your API key"}
      description="Encrypted on the server (AES-256-GCM). It is never shown again, never sent to your browser and never written to logs."
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button variant="primary" disabled={v.api_key.length < 8} loading={m.isPending} onClick={() => m.mutate()}>Save and test</Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <Field label="Provider">
          <Picker label="Provider" value={v.provider} onChange={(p) => setV({ ...v, provider: p })}
            options={Object.entries(PROVIDER_NAME).filter(([k]) => k !== "claude_code").map(([k, n]) => ({ value: k, label: n }))} />
        </Field>
        <Field label="API key" htmlFor="k-key" hint={v.provider === "anthropic" ? "From console.anthropic.com → API keys. A Claude.ai subscription can't be used here." : undefined}>
          <Input id="k-key" name="provider-api-key" className="secret-field" autoComplete="off" autoCorrect="off" autoCapitalize="none" spellCheck={false} data-1p-ignore data-lpignore="true" data-form-type="other" value={v.api_key} onChange={(e) => setV({ ...v, api_key: e.target.value.trim() })} />
        </Field>
        <Field label="Name (optional)" htmlFor="k-label"><Input id="k-label" value={v.label} onChange={(e) => setV({ ...v, label: e.target.value })} placeholder={PROVIDER_NAME[v.provider]} /></Field>
        {shared && <SwitchRow title="Let all users use this key" description="Users without their own key fall back to it. Their usage counts against their own limits." checked={v.shared_with_users} onChange={(x) => setV({ ...v, shared_with_users: x })} />}
      </div>
    </Sheet>
  );
}

function CredRow({ c, catalog }: { c: Cred; catalog?: Catalog }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [models, setModels] = useState<Record<string, string>>(c.models);
  const [available, setAvailable] = useState<string[]>([]);
  const [confirm, setConfirm] = useState(false);
  const test = useMutation({
    mutationFn: () => post<Cred & { available_models: string[] }>(`/api/ai/credentials/${c.id}/test`),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ["creds"] });
      setAvailable(r.available_models || []);
      if (r.last_test_ok) toast.show("Connection works");
      else toast.error(new Error(r.last_test_error || "Test failed"));
    },
    onError: toast.error,
  });
  const save = useMutation({ mutationFn: () => patch(`/api/ai/credentials/${c.id}`, { models }), onSuccess: () => { qc.invalidateQueries({ queryKey: ["creds"] }); toast.show("Models saved"); }, onError: toast.error });
  const remove = useMutation({ mutationFn: () => del(`/api/ai/credentials/${c.id}`), onSuccess: () => { qc.invalidateQueries({ queryKey: ["creds"] }); qc.invalidateQueries({ queryKey: ["dashboard"] }); } });
  const options = Array.from(new Set([...(catalog?.models.filter((m) => m.provider === c.provider).map((m) => m.id) || []), ...available]));
  const priceOf = (id: string) => catalog?.models.find((m) => m.provider === c.provider && m.id === id);
  return (
    <div className="border-t border-rule py-4 first:border-t-0 first:pt-0">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <div className="flex items-center gap-2 text-sm font-medium">
            {c.label}
            {c.last_test_ok === true && <Pill tone="positive">Working</Pill>}
            {c.last_test_ok === false && <Pill tone="negative">Failed</Pill>}
            {c.shared && <Pill>Shared</Pill>}
          </div>
          <div className="text-[0.8125rem] text-muted">
            {PROVIDER_NAME[c.provider]} · key {c.key_hint}
            {c.last_tested_at && ` · tested ${relTime(c.last_tested_at)}`}
          </div>
          {c.last_test_error && <div className="mt-1 text-[0.8125rem] text-negative">{c.last_test_error}</div>}
        </div>
        <div className="flex items-center gap-1">
          <Button size="sm" onClick={() => test.mutate()} loading={test.isPending}>Test</Button>
          <IconButton label={`Remove ${c.label}`} onClick={() => setConfirm(true)}><Trash2 className="size-4" /></IconButton>
        </div>
      </div>
      <details className="mt-3">
        <summary className="cursor-pointer text-[0.8125rem] font-medium text-muted hover:text-ink">Models per task</summary>
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          {(catalog?.kinds || []).map((k) => (
            <Field key={k} label={KIND_NAME[k] || k}>
              <Picker label={KIND_NAME[k] || k} value={models[k] || ""} onChange={(m) => setModels({ ...models, [k]: m })}
                options={[
                  { value: "", label: k === "default" ? `Provider default (${catalog?.defaults[c.provider]})` : "Same as default" },
                  ...options.map((o) => {
                    const p = priceOf(o);
                    const hint = [p?.input_per_m != null ? `$${p.input_per_m} in / $${p.output_per_m} out per M tokens` : "", k === "vision_analysis" && p && !p.vision ? "can't read photos" : ""].filter(Boolean).join(" · ");
                    return { value: o, label: o, hint: hint || undefined };
                  }),
                ]} />
            </Field>
          ))}
        </div>
        <p className="mt-2 text-[0.75rem] text-muted">Prices per million input/output tokens. Models without a listed price are counted at a conservative fallback rate so limits still hold.</p>
        <div className="mt-3 flex justify-end"><Button size="sm" variant="primary" loading={save.isPending} onClick={() => save.mutate()}>Save models</Button></div>
      </details>
      <Confirm open={confirm} onOpenChange={setConfirm} title={`Remove ${c.label}?`} body="The encrypted key is deleted from the server." confirmLabel="Remove" danger loading={remove.isPending} onConfirm={() => remove.mutate()} />
    </div>
  );
}

function ClaudeCode() {
  const qc = useQueryClient();
  const toast = useToast();
  const st = useQuery({ queryKey: ["claude-code"], queryFn: () => get<{ available: boolean; configured: boolean; connected: Cred | null }>("/api/ai/claude-code") });
  const connect = useMutation({
    mutationFn: () => post<Cred>("/api/ai/claude-code/connect"),
    onSuccess: (c) => {
      qc.invalidateQueries({ queryKey: ["claude-code"] });
      qc.invalidateQueries({ queryKey: ["creds"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      if (c.last_test_ok) toast.show("Claude Code is connected");
      else toast.error(new Error(c.last_test_error || "Claude Code didn't answer"));
    },
    onError: toast.error,
  });
  const s = st.data;
  if (!s || !s.available) return null;
  const c = s.connected;
  return (
    <Row
      title="Claude Code on this server"
      description="Uses the Claude Code you're signed in to on the server, with your Claude plan. No API costs; your plan's usage limits apply. Only for your own account."
    >
      {c ? (
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="text-sm">
            <span className="font-medium">Connected</span>{" "}
            {c.last_test_ok === false ? <Pill tone="negative">Not answering</Pill> : <Pill tone="positive">Working</Pill>}
            {c.last_test_error && <p className="mt-1 text-[0.8125rem] text-negative">{c.last_test_error}</p>}
          </div>
          <Button size="sm" onClick={() => connect.mutate()} loading={connect.isPending}>Check again</Button>
        </div>
      ) : (
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="text-sm text-muted">Not connected yet.</p>
          <Button variant="primary" onClick={() => connect.mutate()} loading={connect.isPending}>Connect Claude Code</Button>
        </div>
      )}
    </Row>
  );
}

function AISettings() {
  const me = useMe();
  const save = useSaveMe();
  const [adding, setAdding] = useState<false | "own" | "shared">(false);
  const creds = useQuery({ queryKey: ["creds"], queryFn: () => get<{ own: Cred[]; shared: Cred[]; active: { scope: string; provider: string } | null }>("/api/ai/credentials") });
  const catalog = useQuery({ queryKey: ["catalog"], queryFn: () => get<Catalog>("/api/ai/catalog") });
  const [l, setL] = useState<AILimits>(me.ai_limits);
  const resume = useMutation({ mutationFn: () => post<User>("/api/me/ai/resume"), onSuccess: () => save.reset() });
  const qc = useQueryClient();
  return (
    <>
      {me.is_admin && <ClaudeCode />}
      <Row
        title="Your keys"
        description={
          <>
            Bring your own key: your requests are billed to your provider account. Without one, Schnäppli uses a shared key if the administrator set one up.
            {creds.data?.active ? <span className="mt-2 block text-ink">In use: {PROVIDER_NAME[creds.data.active.provider]} ({creds.data.active.scope === "byok" ? "your key" : "shared key"})</span> : <span className="mt-2 block text-warning">No AI provider available yet.</span>}
          </>
        }
      >
        {creds.isLoading ? <Skeleton className="h-16" /> : (
          <>
            {(creds.data?.own || []).filter((c) => c.provider !== "claude_code").map((c) => <CredRow key={c.id} c={c} catalog={catalog.data} />)}
            {(creds.data?.own || []).filter((c) => c.provider !== "claude_code").length === 0 && <p className="text-sm text-muted">No key added.</p>}
            <div className="mt-4"><Button variant="primary" onClick={() => setAdding("own")}>Add API key</Button></div>
          </>
        )}
      </Row>
      {me.is_admin && (
        <Row title="Shared keys" description="Administrator only. Available to every user who has no key of their own.">
          {(creds.data?.shared || []).map((c) => <CredRow key={c.id} c={c} catalog={catalog.data} />)}
          {(creds.data?.shared || []).length === 0 && <p className="text-sm text-muted">No shared key.</p>}
          <div className="mt-4"><Button onClick={() => setAdding("shared")}>Add shared key</Button></div>
        </Row>
      )}
      <Row title="Spending limits" description="Checked before every AI call, so a limit is never silently exceeded. Costs are estimated from reported tokens.">
        {me.ai_paused_reason && (
          <div className="mb-4">
            <Notice tone="warning" action={<Button size="sm" onClick={() => resume.mutate(undefined, { onSuccess: (u) => qc.setQueryData(["me"], u) })}>Resume</Button>}>Paused: {me.ai_paused_reason}</Notice>
          </div>
        )}
        <div className="grid gap-4 sm:grid-cols-2">
          {([
            ["monthly_limit_usd", "Monthly limit (USD)"],
            ["daily_limit_usd", "Daily limit (USD)"],
            ["warn_pct", "Warn at (%)"],
            ["pause_pct", "Pause at (%)"],
            ["max_deep_per_day", "Deep analyses per day"],
            ["max_vision_per_day", "Photo checks per day"],
            ["max_analyses_per_run", "Analyses per search run"],
          ] as [keyof AILimits, string][]).map(([k, label]) => (
            <Field key={k} label={label} htmlFor={`l-${k}`}>
              <Input id={`l-${k}`} inputMode="decimal" value={String(l[k])} onChange={(e) => setL({ ...l, [k]: Number(e.target.value.replace(",", ".")) || 0 })} />
            </Field>
          ))}
        </div>
        <SwitchRow title="Pause analysis when the monthly limit is reached" checked={l.auto_pause} onChange={(v) => setL({ ...l, auto_pause: v })} />
        <div className="mt-2 flex justify-end">
          <Button variant="primary" loading={save.isPending} onClick={() => save.mutate({ ai_limits: l })}>Save limits</Button>
        </div>
      </Row>
      <Row
        title="What's sent to the AI provider"
        description="Listing text and photos (public data), your search descriptions, and for the assistant your searches and budget. Never your e-mail, password, address or other users' data. Listing text is treated as untrusted and can't change instructions or settings."
      >
        <SwitchRow
          title="Share listing locations"
          description="Off: the AI only learns whether a pickup is inside your radius and the rough distance. On: it also sees the listing's town. Your own postal code is never sent."
          checked={me.share_location_with_ai}
          onChange={(v) => save.mutate({ share_location_with_ai: v })}
        />
      </Row>
      {catalog.data && (
        <Row title="Model prices" description="Used for cost estimates. Anthropic prices are built in; for other providers the administrator can enter current prices.">
          <ModelPrices catalog={catalog.data} admin={me.is_admin} />
        </Row>
      )}
      <AddKey open={!!adding} onOpenChange={(v) => !v && setAdding(false)} shared={adding === "shared"} />
    </>
  );
}

function ModelPrices({ catalog, admin }: { catalog: Catalog; admin: boolean }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [edit, setEdit] = useState<{ key: string; input: string; output: string } | null>(null);
  const save = useMutation({
    mutationFn: () => put("/api/ai/catalog", { key: edit!.key, input_per_m: Number(edit!.input), output_per_m: Number(edit!.output) }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["catalog"] }); setEdit(null); toast.show("Price saved"); },
    onError: toast.error,
  });
  return (
    <>
      <table className="num w-full text-sm">
        <thead><tr className="text-left text-[0.75rem] text-muted"><th className="pb-2 font-normal">Model</th><th className="pb-2 text-right font-normal">Input / M</th><th className="pb-2 text-right font-normal">Output / M</th><th /></tr></thead>
        <tbody>
          {catalog.models.map((m) => (
            <tr key={`${m.provider}:${m.id}`} className="border-t border-rule">
              <td className="py-2 pr-2">{m.label}<span className="block text-[0.75rem] text-muted">{PROVIDER_NAME[m.provider]}{m.vision ? " · images" : ""}</span></td>
              <td className="py-2 text-right">{m.input_per_m != null ? usd(m.input_per_m) : <span className="text-warning">unknown</span>}</td>
              <td className="py-2 text-right">{m.output_per_m != null ? usd(m.output_per_m) : <span className="text-warning">unknown</span>}</td>
              <td className="py-2 text-right">{admin && <button className="text-[0.8125rem] text-muted underline underline-offset-2 hover:text-ink" onClick={() => setEdit({ key: `${m.provider}:${m.id}`, input: String(m.input_per_m ?? ""), output: String(m.output_per_m ?? "") })}>Edit</button>}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <Sheet open={!!edit} onOpenChange={(v) => !v && setEdit(null)} title={`Price for ${edit?.key.split(":")[1]}`} footer={<Button variant="primary" loading={save.isPending} onClick={() => save.mutate()}>Save</Button>}>
        {edit && (
          <div className="grid grid-cols-2 gap-4">
            <Field label="Input, USD per M tokens"><Input inputMode="decimal" value={edit.input} onChange={(e) => setEdit({ ...edit, input: e.target.value })} /></Field>
            <Field label="Output, USD per M tokens"><Input inputMode="decimal" value={edit.output} onChange={(e) => setEdit({ ...edit, output: e.target.value })} /></Field>
          </div>
        )}
      </Sheet>
    </>
  );
}

/* ------------------------------------------------------------------ Sources */
function Sources() {
  const q = useQuery({ queryKey: ["sources"], queryFn: () => get<SourceInfo[]>("/api/sources") });
  const label = { ready: ["Working", "positive"], alerts: ["Via alert mails", "positive"], manual: ["By link", "score"], needs_credentials: ["Needs setup", "warning"], planned: ["Planned", "neutral"], unsupported: ["Not supported", "neutral"] } as const;
  return (
    <>
    <Inbox />
    <Row title="Marketplaces" description="Schnäppli only uses official APIs and permitted access. It does not scrape sites that forbid it or work around bot protection. Sources that can't be used legitimately are listed honestly with alternatives.">
      {q.isLoading ? <Skeleton className="h-40" /> : (
        <ul>
          {(q.data || []).map((s) => (
            <li key={s.id} className="border-t border-rule py-3 first:border-t-0 first:pt-0">
              <div className="flex items-center gap-2 text-sm font-medium">
                {s.name} <Pill tone={label[s.state][1]}>{label[s.state][0]}</Pill>
              </div>
              <p className="mt-0.5 text-[0.8125rem] text-muted">{s.reason}</p>
              {s.alternatives && <p className="mt-0.5 text-[0.8125rem] text-muted">{s.alternatives}</p>}
            </li>
          ))}
        </ul>
      )}
    </Row>
    </>
  );
}

function Inbox() {
  const me = useMe();
  const q = useQuery({ queryKey: ["inbox"], queryFn: () => get<InboxInfo>("/api/sources/inbox") });
  const i = q.data;
  return (
    <Row
      title="Ricardo and tutti"
      description="Neither site lets programs search it. Both e-mail new listings for a saved search, so Schnäppli reads those mails from a mailbox of its own, every five minutes."
    >
      {!i ? <Skeleton className="h-24" /> : !i.configured ? (
        <div className="text-sm">
          <p className="font-medium">No mailbox set up yet.</p>
          <p className="mt-1 text-muted">
            {me.is_admin
              ? "Create a mailbox only for Schnäppli (with an app password), then set SCHNAEPPLI_INBOX_IMAP_HOST, SCHNAEPPLI_INBOX_IMAP_USER and the secret inbox_password on the server. docs/marketplaces.md has the steps."
              : "Your administrator can set one up."}
          </p>
        </div>
      ) : (
        <div className="text-sm">
          <p>
            Forward Ricardo and tutti alert mails to <span className="font-medium">{i.address}</span>. Easiest: a filter in your own mailbox
            that forwards mails from ricardo.ch and tutti.ch there automatically.
          </p>
          <ol className="mt-3 list-decimal space-y-1 pl-5 text-muted">
            <li>Set up that forwarding filter once.</li>
            <li>On each search in Schnäppli, open the Ricardo and tutti links and save the search there.</li>
            <li>New listings from the alerts appear in the search, scored like any other.</li>
          </ol>
          <dl className="num mt-4 grid grid-cols-2 gap-3 border-t border-rule pt-3 sm:grid-cols-4">
            <div><dt className="text-[0.75rem] text-muted">Last check</dt><dd>{i.checked_at ? relTime(i.checked_at) : "Not yet"}</dd></div>
            <div><dt className="text-[0.75rem] text-muted">Last alert</dt><dd>{i.last_alert_at ? relTime(i.last_alert_at) : "None yet"}</dd></div>
            <div><dt className="text-[0.75rem] text-muted">From Ricardo</dt><dd>{i.totals.ricardo ?? 0}</dd></div>
            <div><dt className="text-[0.75rem] text-muted">From tutti</dt><dd>{i.totals.tutti ?? 0}</dd></div>
          </dl>
          {i.ok === false && <p className="mt-3 text-negative">The mailbox couldn't be read{i.error ? `: ${i.error}` : "."}</p>}
          {i.unreadable > 0 && <p className="mt-2 text-warning">{i.unreadable} alert mail(s) in the last check had listing links Schnäppli couldn't read. The mail layout may have changed.</p>}
          {i.unrouted > 0 && <p className="mt-2 text-muted">{i.unrouted} listing(s) in the last check didn't fit any active search and were skipped.</p>}
        </div>
      )}
    </Row>
  );
}

/* ----------------------------------------------------------------- Security */
function Security() {
  const toast = useToast();
  const qc = useQueryClient();
  const [pw, setPw] = useState({ current: "", next: "" });
  const change = useMutation({
    mutationFn: () => post("/api/auth/password", { current_password: pw.current, new_password: pw.next }),
    onSuccess: () => { toast.show("Password changed. Other devices were signed out."); setPw({ current: "", next: "" }); qc.invalidateQueries({ queryKey: ["sessions"] }); },
    onError: toast.error,
  });
  const sessions = useQuery({ queryKey: ["sessions"], queryFn: () => get<{ id: string; created_at: string; last_seen_at: string; ip: string | null; user_agent: string | null; current: boolean }[]>("/api/auth/sessions") });
  const revoke = useMutation({ mutationFn: (id: string) => del(`/api/auth/sessions/${id}`), onSuccess: () => qc.invalidateQueries({ queryKey: ["sessions"] }) });
  const logout = useMutation({ mutationFn: () => post("/api/auth/logout"), onSuccess: () => { qc.clear(); location.href = "/"; } });
  const device = (ua: string | null) => !ua ? "Unknown device" : /iPhone/.test(ua) ? "iPhone" : /iPad/.test(ua) ? "iPad" : /Android/.test(ua) ? "Android" : /Mac OS X/.test(ua) ? "Mac" : /Windows/.test(ua) ? "Windows" : /Linux/.test(ua) ? "Linux" : "Browser";
  return (
    <>
      <Row title="Password" description="Changing it signs out every other device.">
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Current password" htmlFor="pw-c"><Input id="pw-c" type="password" autoComplete="current-password" value={pw.current} onChange={(e) => setPw({ ...pw, current: e.target.value })} /></Field>
          <Field label="New password" htmlFor="pw-n" hint="At least 10 characters."><Input id="pw-n" type="password" autoComplete="new-password" value={pw.next} onChange={(e) => setPw({ ...pw, next: e.target.value })} /></Field>
        </div>
        <div className="mt-4 flex justify-end"><Button variant="primary" disabled={!pw.current || pw.next.length < 10} loading={change.isPending} onClick={() => change.mutate()}>Change password</Button></div>
      </Row>
      <Row title="Signed-in devices">
        {sessions.isLoading ? <Skeleton className="h-16" /> : (
          <ul>
            {(sessions.data || []).map((s) => (
              <li key={s.id} className="flex items-center justify-between gap-3 border-t border-rule py-2.5 first:border-t-0 first:pt-0">
                <div className="min-w-0 text-sm">
                  {device(s.user_agent)} {s.current && <Pill tone="score">This device</Pill>}
                  <div className="text-[0.8125rem] text-muted">Active {relTime(s.last_seen_at)}{s.ip ? ` · ${s.ip}` : ""}</div>
                </div>
                {s.current ? <Button size="sm" onClick={() => logout.mutate()}>Sign out</Button> : <Button size="sm" variant="danger" onClick={() => revoke.mutate(s.id)}>Sign out</Button>}
              </li>
            ))}
          </ul>
        )}
      </Row>
    </>
  );
}

/* --------------------------------------------------------------------- Data */
function Data() {
  const qc = useQueryClient();
  const toast = useToast();
  const learned = useQuery({ queryKey: ["learned"], queryFn: () => get<{ signals: number; items: { key: string; label: string; weight: number; direction: string }[] }>("/api/me/learned") });
  const reset = useMutation({ mutationFn: () => del("/api/me/learned"), onSuccess: () => { qc.invalidateQueries({ queryKey: ["learned"] }); toast.show("Learned preferences reset"); } });
  const [delOpen, setDelOpen] = useState(false);
  const [pw, setPw] = useState("");
  const [typed, setTyped] = useState("");
  const remove = useMutation({ mutationFn: () => del("/api/me", { password: pw, confirm: typed }), onSuccess: () => { qc.clear(); location.href = "/"; }, onError: toast.error });
  const exportData = async () => {
    try {
      const data = await get("/api/me/export");
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `schnaeppli-export-${new Date().toISOString().slice(0, 10)}.json`;
      a.click();
      URL.revokeObjectURL(a.href);
    } catch (e) {
      toast.error(e);
    }
  };
  return (
    <>
      <Row title="Learned preferences" description="Schnäppli nudges ranking (at most ±10 points) based on what you save, plan, buy or reject. It never hides listings, and nothing leaves this server or trains any model.">
        {learned.isLoading ? <Skeleton className="h-16" /> : learned.data!.items.length === 0 ? (
          <p className="text-sm text-muted">{learned.data!.signals < 3 ? `Nothing learned yet (${learned.data!.signals} of 3 signals needed before it affects ranking).` : "No clear preferences yet."}</p>
        ) : (
          <ul>
            {learned.data!.items.map((i) => (
              <li key={i.key} className="num flex justify-between border-t border-rule py-2 text-sm first:border-t-0 first:pt-0">
                <span>You {i.direction === "likes" ? "tend to like" : "tend to skip"} <strong className="font-medium">{i.label.toLowerCase()}</strong></span>
                <span className={i.weight > 0 ? "text-positive" : "text-negative"}>{i.weight > 0 ? "+" : ""}{i.weight.toFixed(2)}</span>
              </li>
            ))}
          </ul>
        )}
        <div className="mt-4 flex justify-end"><Button onClick={() => reset.mutate()} loading={reset.isPending} disabled={!learned.data?.signals}>Reset</Button></div>
      </Row>
      <Row title="Your data" description="Download everything stored about you, as JSON. API keys are excluded.">
        <Button onClick={exportData}>Download my data</Button>
      </Row>
      <Row title="Delete account" description="Permanently removes your account, searches, results, wishlist, budget, chats, keys and usage history.">
        <Button variant="danger" onClick={() => setDelOpen(true)}>Delete my account</Button>
      </Row>
      <Sheet
        open={delOpen}
        onOpenChange={setDelOpen}
        title="Delete your account?"
        description="This can't be undone."
        footer={<Button variant="primary" className="!bg-negative" disabled={!pw || typed !== "DELETE"} loading={remove.isPending} onClick={() => remove.mutate()}>Delete everything</Button>}
      >
        <div className="flex flex-col gap-4">
          <Field label="Password" htmlFor="del-pw"><Input id="del-pw" type="password" autoComplete="current-password" value={pw} onChange={(e) => setPw(e.target.value)} /></Field>
          <Field label="Type DELETE to confirm" htmlFor="del-c"><Input id="del-c" value={typed} onChange={(e) => setTyped(e.target.value)} autoCapitalize="characters" /></Field>
        </div>
      </Sheet>
    </>
  );
}

/* -------------------------------------------------------------------- Admin */
function Admin() {
  const qc = useQueryClient();
  const toast = useToast();
  const me = useMe();
  const users = useQuery({ queryKey: ["admin-users"], queryFn: () => get<{ id: string; email: string; display_name: string; is_admin: boolean; is_active: boolean; last_login_at: string | null; ai_month_usd: number }[]>("/api/admin/users") });
  const invites = useQuery({ queryKey: ["invites"], queryFn: () => get<{ id: string; note: string | null; expires_at: string; used: boolean }[]>("/api/admin/invites") });
  const audit = useQuery({ queryKey: ["audit"], queryFn: () => get<{ event: string; ip: string | null; detail: string | null; at: string }[]>("/api/admin/audit") });
  const [code, setCode] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const invite = useMutation({ mutationFn: () => post<{ code: string }>("/api/admin/invites", { note: note || null }), onSuccess: (r) => { setCode(r.code); setNote(""); qc.invalidateQueries({ queryKey: ["invites"] }); }, onError: toast.error });
  const upd = useMutation({ mutationFn: ({ id, body }: { id: string; body: object }) => patch(`/api/admin/users/${id}`, body), onSuccess: () => qc.invalidateQueries({ queryKey: ["admin-users"] }), onError: toast.error });
  const link = code ? `${location.origin}/?invite=${encodeURIComponent(code)}` : "";
  return (
    <>
      <Row title="Users">
        <ul>
          {(users.data || []).map((u) => (
            <li key={u.id} className="flex flex-wrap items-center justify-between gap-2 border-t border-rule py-2.5 first:border-t-0 first:pt-0">
              <div className="min-w-0 text-sm">
                {u.display_name} {u.is_admin && <Pill tone="score">Admin</Pill>} {!u.is_active && <Pill>Disabled</Pill>}
                <div className="num text-[0.8125rem] text-muted">{u.email} · AI this month {usd(u.ai_month_usd)} · {u.last_login_at ? `seen ${relTime(u.last_login_at)}` : "never signed in"}</div>
              </div>
              {u.id !== me.id && (
                <div className="flex gap-1">
                  <Button size="sm" onClick={() => upd.mutate({ id: u.id, body: { is_admin: !u.is_admin } })}>{u.is_admin ? "Remove admin" : "Make admin"}</Button>
                  <Button size="sm" variant="danger" onClick={() => upd.mutate({ id: u.id, body: { is_active: !u.is_active } })}>{u.is_active ? "Disable" : "Enable"}</Button>
                </div>
              )}
            </li>
          ))}
        </ul>
      </Row>
      <Row title="Invites" description="New people can only join with an invite. Codes are single use and expire after 7 days.">
        <div className="flex gap-2">
          <Input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Who is it for? (optional)" aria-label="Invite note" />
          <Button variant="primary" onClick={() => invite.mutate()} loading={invite.isPending}>Create</Button>
        </div>
        {code && (
          <div className="mt-3 rounded-[var(--radius-control)] bg-sunk p-3 text-sm">
            <p className="text-[0.8125rem] text-muted">Shown once. Share this link:</p>
            <p className="mt-1 break-all">{link}</p>
            <Button size="sm" className="mt-2" icon={<Copy className="size-3.5" aria-hidden />} onClick={() => navigator.clipboard?.writeText(link).then(() => toast.show("Copied"))}>Copy link</Button>
          </div>
        )}
        <ul className="mt-3">
          {(invites.data || []).slice(0, 8).map((i) => (
            <li key={i.id} className="flex justify-between border-t border-rule py-2 text-[0.8125rem]">
              <span>{i.note || "Invite"}</span>
              <span className="text-muted">{i.used ? "Used" : new Date(i.expires_at) < new Date() ? "Expired" : `Expires ${relTime(i.expires_at)}`}</span>
            </li>
          ))}
        </ul>
      </Row>
      <Row title="Security log" description="Sign-ins, failed attempts, lockouts and admin changes. No passwords or keys are ever logged.">
        <ul className="max-h-80 overflow-y-auto">
          {(audit.data || []).slice(0, 60).map((a, i) => (
            <li key={i} className="flex justify-between gap-3 border-t border-rule py-1.5 text-[0.8125rem] first:border-t-0">
              <span className={a.event.includes("fail") || a.event.includes("lock") ? "text-negative" : ""}>{a.event.replace(/_/g, " ")}{a.detail ? ` · ${a.detail}` : ""}</span>
              <span className="num shrink-0 text-muted">{a.ip} · {relTime(a.at)}</span>
            </li>
          ))}
        </ul>
      </Row>
    </>
  );
}

export default function Settings() {
  const { tab = "" } = useParams();
  const me = useMe();
  const { loading } = useAuth();
  const tabs = TABS.filter((t) => !t.admin || me.is_admin);
  return (
    <>
      <PageHeader title="Settings" />
      <nav aria-label="Settings sections" className="-mx-4 mb-6 flex gap-1 overflow-x-auto px-4 no-scrollbar sm:mx-0 sm:px-0">
        {tabs.map((t) => (
          <NavLink
            key={t.id}
            to={t.id ? `/settings/${t.id}` : "/settings"}
            end
            className={({ isActive }) => cx("pressable shrink-0 rounded-[var(--radius-control)] px-3 py-1.5 text-sm whitespace-nowrap", isActive ? "bg-raised font-medium" : "text-muted hover:text-ink")}
          >
            {t.label}
          </NavLink>
        ))}
      </nav>
      {loading ? <Skeleton className="h-64" /> : (
        <>
          {tab === "" && <General />}
          {tab === "appearance" && <Appearance />}
          {tab === "notifications" && <Notifications />}
          {tab === "ai" && <AISettings />}
          {tab === "sources" && <Sources />}
          {tab === "security" && <Security />}
          {tab === "data" && <Data />}
          {tab === "admin" && (me.is_admin ? <Admin /> : <ErrorBox error={new Error("Administrators only.")} />)}
        </>
      )}
    </>
  );
}
