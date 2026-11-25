import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, ChevronDown, ExternalLink, Plus } from "lucide-react";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Link, useLocation } from "react-router-dom";
import { AlertButtons } from "@/components/alerts";
import { Picker } from "@/components/Picker";
import { Button, Confirm, cx, ErrorBox, Field, Input, Notice, PageHeader, Pill, Skeleton, Switch, useToast } from "@/components/ui";
import { del, get, patch, post, put } from "@/lib/api";
import { useMe } from "@/lib/auth";
import { relTime } from "@/lib/format";
import type { EbayState, MailConnection, MailProvider, Search, SetupState, SourceInfo, User } from "@/lib/types";
import { Telegram } from "./Settings";

const secretProps = {
  className: "secret-field",
  autoComplete: "off",
  autoCorrect: "off",
  autoCapitalize: "none",
  spellCheck: false,
  "data-1p-ignore": true,
  "data-lpignore": "true",
  "data-form-type": "other",
} as const;

function useRefreshSetup() {
  const qc = useQueryClient();
  return () => {
    qc.invalidateQueries({ queryKey: ["setup"] });
    qc.invalidateQueries({ queryKey: ["dashboard"] });
    qc.invalidateQueries({ queryKey: ["sources"] });
  };
}

/* One step: a numbered row that opens to show its content. */
function Step({
  id, n, title, why, done, optional, open, onToggle, children,
}: {
  id: string; n?: number; title: string; why: string; done: boolean; optional?: boolean; open: boolean; onToggle: () => void; children: ReactNode;
}) {
  return (
    <li id={id} className="scroll-mt-20 border-t border-border first:border-t-0">
      <button type="button" onClick={onToggle} aria-expanded={open} className="flex w-full items-center gap-4 py-4 text-left">
        <span
          className={cx(
            "num flex size-8 shrink-0 items-center justify-center rounded-full text-[0.8125rem] font-semibold",
            done ? "bg-ink text-on-ink" : "border-[1.5px] border-control text-muted",
            n === undefined && "size-6",
          )}
        >
          {done ? <Check className={n === undefined ? "size-3.5" : "size-4"} strokeWidth={3} aria-hidden /> : n}
        </span>
        <span className="min-w-0 flex-1">
          <span className="flex flex-wrap items-center gap-2 text-[0.9375rem] font-semibold">
            {title}
            {done ? <Pill tone="positive">Done</Pill> : optional && <Pill>Optional</Pill>}
          </span>
          <span className="mt-0.5 block text-[0.8125rem] text-muted">{why}</span>
        </span>
        <ChevronDown className={cx("size-4 shrink-0 text-faint transition-transform duration-200", open && "rotate-180")} aria-hidden />
      </button>
      {open && <div className="pb-6 sm:pl-12">{children}</div>}
    </li>
  );
}

/* ----------------------------------------------------------------------- AI */
function AIStep({ s }: { s: SetupState }) {
  const toast = useToast();
  const refresh = useRefreshSetup();
  const connect = useMutation({
    mutationFn: () => post<{ last_test_ok: boolean; last_test_error: string | null }>("/api/ai/claude-code/connect"),
    onSuccess: (c) => {
      refresh();
      if (c.last_test_ok) toast.show("Claude Code is connected");
      else toast.error(new Error(c.last_test_error || "Claude Code didn't answer"));
    },
    onError: toast.error,
  });
  if (s.ai) return <p className="text-sm text-muted">An AI provider is ready. You can change it under Settings → AI.</p>;
  return (
    <div className="flex flex-col gap-3 text-sm">
      {s.claude_code_available && (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-[12px] bg-surface p-4">
          <p className="min-w-0 flex-1">Use Claude Code on this server, with your Claude plan. No API costs.</p>
          <Button variant="primary" onClick={() => connect.mutate()} loading={connect.isPending}>Connect Claude Code</Button>
        </div>
      )}
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-[12px] bg-surface p-4">
        <p className="min-w-0 flex-1">{s.claude_code_available ? "Or add" : "Add"} an API key from Anthropic, OpenAI or Google. It's stored encrypted.</p>
        <Link to="/settings/ai"><Button>Add a key</Button></Link>
      </div>
    </div>
  );
}

/* ----------------------------------------------------------------- Location */
function LocationStep({ s }: { s: SetupState }) {
  const me = useMe();
  const qc = useQueryClient();
  const toast = useToast();
  const refresh = useRefreshSetup();
  const [code, setCode] = useState(me.postal_code || "");
  const save = useMutation({
    mutationFn: async () => {
      const u = await patch<User>("/api/me", { postal_code: code.trim() });
      return { u, found: (await get<SetupState>("/api/setup")).location };
    },
    onSuccess: ({ u, found }) => {
      qc.setQueryData(["me"], u);
      refresh();
      if (!found) toast.error(new Error("Saved, but that postal code wasn't found."));
      else toast.show(`Saved: ${u.city || code}`);
    },
    onError: toast.error,
  });
  return (
    <form className="flex flex-wrap items-end gap-3" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
      <Field label="Postal code" htmlFor="setup-plz">
        <Input id="setup-plz" inputMode="numeric" className="w-32" value={code} onChange={(e) => setCode(e.target.value)} placeholder="8001" />
      </Field>
      <Button type="submit" variant={s.location ? "secondary" : "primary"} disabled={code.trim().length < 4} loading={save.isPending}>Save</Button>
      <p className="w-full text-[0.8125rem] text-muted">Only used here to work out pickup distances. Never sent to AI providers.</p>
    </form>
  );
}

/* ------------------------------------------------------------------ Mailbox */
function MailStatus({ c }: { c: MailConnection }) {
  const toast = useToast();
  const qc = useQueryClient();
  const refresh = useRefreshSetup();
  const [confirm, setConfirm] = useState(false);
  const check = useMutation({
    mutationFn: () => post<{ connection: MailConnection; imported: number }>("/api/setup/mail/check"),
    onSuccess: (r) => {
      refresh();
      qc.invalidateQueries({ queryKey: ["setup-mail"] });
      if (r.connection.state !== "ok") toast.error(new Error(r.connection.state_detail || "The mailbox couldn't be read."));
      else toast.show(r.imported ? `${r.imported} new listing(s) added` : "Checked. Nothing new yet.");
    },
    onError: toast.error,
  });
  const toggle = useMutation({
    mutationFn: (enabled: boolean) => patch<MailConnection>("/api/setup/mail", { enabled }),
    onSuccess: () => { refresh(); qc.invalidateQueries({ queryKey: ["setup-mail"] }); },
    onError: toast.error,
  });
  const remove = useMutation({
    mutationFn: () => del("/api/setup/mail"),
    onSuccess: () => { refresh(); qc.invalidateQueries({ queryKey: ["setup-mail"] }); toast.show("Mailbox disconnected"); },
    onError: toast.error,
  });
  const total = Object.values(c.totals).reduce((a, b) => a + b, 0);
  return (
    <div className="flex flex-col gap-4 text-sm">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <p className="font-medium">{c.address}</p>
          <p className="text-[0.8125rem] text-muted">
            {c.provider_name} · {c.state === "ok" ? "Working" : c.state === "login" ? "Sign-in refused" : "Problem"}
            {c.checked_at ? ` · checked ${relTime(c.checked_at)}` : ""}
          </p>
        </div>
        <label className="flex items-center gap-2 text-[0.8125rem] text-muted">
          Read alert mails
          <Switch checked={c.enabled} onChange={(v) => toggle.mutate(v)} label="Read alert mails" />
        </label>
      </div>
      {c.state !== "ok" && c.state_detail && (
        <Notice tone="warning">{c.state_detail}{c.state === "login" ? " Connect again below with a new app password." : ""}</Notice>
      )}
      <dl className="num grid grid-cols-3 gap-3 border-t border-rule pt-3">
        <div><dt className="text-[0.75rem] text-muted">Last alert</dt><dd>{c.last_alert_at ? relTime(c.last_alert_at) : "None yet"}</dd></div>
        <div><dt className="text-[0.75rem] text-muted">Listings added</dt><dd>{total}</dd></div>
        <div><dt className="text-[0.75rem] text-muted">Alert mails</dt><dd>{c.mails_total}</dd></div>
      </dl>
      {c.unreadable > 0 && <p className="text-warning">{c.unreadable} alert mail(s) couldn't be read. The mail layout may have changed.</p>}
      {c.unrouted > 0 && <p className="text-muted">{c.unrouted} listing(s) in the last check fit none of your active searches.</p>}
      <div className="flex flex-wrap gap-2">
        <Button size="sm" onClick={() => check.mutate()} loading={check.isPending}>Check now</Button>
        <Button size="sm" variant="danger" onClick={() => setConfirm(true)}>Disconnect</Button>
      </div>
      <Confirm
        open={confirm}
        onOpenChange={setConfirm}
        title="Disconnect this mailbox?"
        body="Schnäppli deletes the saved password and stops reading. Listings already added stay."
        confirmLabel="Disconnect"
        danger
        loading={remove.isPending}
        onConfirm={() => remove.mutate()}
      />
    </div>
  );
}

function MailForm({ providers, existing }: { providers: MailProvider[]; existing: MailConnection | null }) {
  const toast = useToast();
  const qc = useQueryClient();
  const refresh = useRefreshSetup();
  const [address, setAddress] = useState(existing?.address.includes("@") ? existing.address : "");
  const [picked, setPicked] = useState<string | null>(null);
  const [password, setPassword] = useState("");
  const [host, setHost] = useState("");
  const [folder, setFolder] = useState("INBOX");
  const [more, setMore] = useState(false);
  const guessed = useMemo(() => {
    const domain = address.split("@")[1]?.trim().toLowerCase() || "";
    return providers.find((p) => p.domains.includes(domain))?.id || "other";
  }, [address, providers]);
  const pid = picked || guessed;
  const p = providers.find((x) => x.id === pid)!;
  useEffect(() => {
    if (pid === "other" && !host && address.includes("@")) setHost(`imap.${address.split("@")[1]}`);
  }, [pid, address, host]);
  const connect = useMutation({
    mutationFn: () =>
      post<{ connection: MailConnection; found: number }>("/api/setup/mail", {
        address: address.trim(), password, provider: pid, host: pid === "other" ? host.trim() : undefined, folder,
      }),
    onSuccess: (r) => {
      setPassword("");
      refresh();
      qc.invalidateQueries({ queryKey: ["setup-mail"] });
      toast.show(r.found ? `Connected. ${r.found} alert mail(s) from the last 14 days will be read.` : "Connected. No alert mails yet, that's fine.");
    },
    onError: toast.error,
  });
  const valid = address.includes("@") && password.length > 0 && p.supported && (pid !== "other" || host.includes("."));
  return (
    <form className="flex flex-col gap-4" onSubmit={(e) => { e.preventDefault(); if (valid) connect.mutate(); }}>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="The e-mail address those sites write to" htmlFor="mail-addr">
          <Input id="mail-addr" type="email" inputMode="email" value={address} onChange={(e) => { setAddress(e.target.value); setPicked(null); }} placeholder="you@gmail.com" />
        </Field>
        <Field label="Provider">
          <Picker label="Provider" value={pid} onChange={setPicked} options={providers.map((x) => ({ value: x.id, label: x.name }))} />
        </Field>
      </div>
      {!address.includes("@") ? null : !p.supported ? (
        <Notice tone="warning">{p.unsupported_text}</Notice>
      ) : (
        <>
          {p.steps.length > 0 && (
            <div className="rounded-[12px] bg-surface p-4 sm:p-5">
              <p className="text-sm font-medium">
                {p.password_name === "password" ? `${p.name}: what to do` : `${p.name} needs an ${p.password_name}. Here's how, takes two minutes:`}
              </p>
              <ol className="mt-4 flex flex-col gap-4">
                {p.steps.map((g, i) => (
                  <li key={g.title} className="flex gap-3">
                    <span className="num flex size-6 shrink-0 items-center justify-center rounded-full bg-raised text-[0.75rem] font-semibold">{i + 1}</span>
                    <div className="min-w-0 flex-1 text-sm">
                      <p className="font-medium">{g.title}</p>
                      {g.detail && <p className="mt-0.5 leading-relaxed text-muted">{g.detail}</p>}
                      {g.link && (
                        <a href={g.link} target="_blank" rel="noreferrer noopener" className="mt-2 inline-block">
                          <Button size="sm" icon={<ExternalLink className="size-4" aria-hidden />}>{g.link_label || "Open"}</Button>
                        </a>
                      )}
                    </div>
                  </li>
                ))}
              </ol>
              {p.trouble.length > 0 && (
                <details className="mt-4 border-t border-rule pt-3 text-[0.8125rem]">
                  <summary className="cursor-pointer font-medium">Doesn't work?</summary>
                  <ul className="mt-2 list-disc space-y-1 pl-5 text-muted">
                    {p.trouble.map((t) => <li key={t}>{t}</li>)}
                  </ul>
                </details>
              )}
            </div>
          )}
          {pid === "other" && (
            <Field label="IMAP server" htmlFor="mail-host" hint="Port 993 with TLS. Your provider's help pages list it.">
              <Input id="mail-host" value={host} onChange={(e) => setHost(e.target.value.trim())} placeholder="imap.example.ch" />
            </Field>
          )}
          <Field
            label={`Paste the ${p.password_name || "password"} here`}
            htmlFor="mail-pw"
            hint={p.password_name && p.password_name !== "password" ? "Not your normal password." : undefined}
          >
            <Input id="mail-pw" name="mailbox-app-secret" type="password" {...secretProps} value={password} onChange={(e) => setPassword(e.target.value)} />
          </Field>
          <button type="button" className="self-start text-[0.8125rem] text-muted underline-offset-2 hover:underline" onClick={() => setMore(!more)}>
            {more ? "Hide" : "Show"} more options
          </button>
          {more && (
            <Field label="Folder" htmlFor="mail-folder" hint="Where the alert mails land. Usually INBOX.">
              <Input id="mail-folder" className="max-w-60" value={folder} onChange={(e) => setFolder(e.target.value)} />
            </Field>
          )}
          <div className="flex flex-wrap items-center gap-3">
            <Button type="submit" variant="primary" disabled={!valid} loading={connect.isPending}>Connect and test</Button>
            <p className="min-w-0 flex-1 text-[0.8125rem] text-muted">Schnäppli signs in once to check, then saves the password encrypted.</p>
          </div>
        </>
      )}
    </form>
  );
}

function MailStep() {
  const q = useQuery({ queryKey: ["setup-mail"], queryFn: () => get<{ connection: MailConnection | null; providers: MailProvider[]; shared_inbox: boolean }>("/api/setup/mail") });
  if (q.error) return <ErrorBox error={q.error} onRetry={() => q.refetch()} />;
  if (!q.data) return <Skeleton className="h-40" />;
  const { connection: c, providers, shared_inbox } = q.data;
  return (
    <div className="flex flex-col gap-5">
      <div className="max-w-prose text-[0.8125rem] leading-relaxed text-muted">
        <p>
          Ricardo, tutti, Facebook Marketplace and Toppreise don't let programs search them, but all of them e-mail you: new listings
          for a saved search, or a price alert. Connect the mailbox those mails go to and Schnäppli picks them up every five minutes.
        </p>
        <p className="mt-2">
          <span className="font-medium text-ink">What Schnäppli reads:</span> only mails from ricardo.ch, tutti.ch, toppreise.ch and Facebook's notification address (and of those only the Marketplace
          listings). It opens the mailbox
          read-only: nothing is marked as read, moved or deleted. You can disconnect any time.
        </p>
      </div>
      {shared_inbox && !c && <Notice>Your administrator already forwards alert mails to a shared Schnäppli mailbox. Connecting your own is simpler and keeps them to you.</Notice>}
      {c && <MailStatus c={c} />}
      {(!c || c.state === "login") && <MailForm providers={providers} existing={c} />}
    </div>
  );
}

/* ----------------------------------------------------------- Saved searches */
function AlertsStep({ s }: { s: SetupState }) {
  const q = useQuery({ queryKey: ["searches"], queryFn: () => get<Search[]>("/api/searches") });
  const active = (q.data || []).filter((x) => x.status === "active").slice(0, 5);
  if (!s.search)
    return (
      <div className="flex flex-wrap items-center justify-between gap-3 text-sm">
        <p className="min-w-0 flex-1 text-muted">First tell Schnäppli what you're looking for.</p>
        <Link to="/searches/new"><Button variant="primary">Create a search</Button></Link>
      </div>
    );
  return (
    <div className="flex flex-col gap-3 text-sm">
      <p className="text-[0.8125rem] text-muted">Open a site, sign in there once and save the search with e-mail alerts on. A tick shows which ones you opened.</p>
      <ul className="grid gap-x-6 gap-y-1 text-[0.8125rem] text-muted sm:grid-cols-2">
        <li><span className="font-medium text-ink">Ricardo</span> · “Suche speichern”</li>
        <li><span className="font-medium text-ink">tutti</span> · “Suchauftrag speichern”</li>
        <li><span className="font-medium text-ink">Facebook</span> · “Suche speichern”, e-mail on under Notifications</li>
        <li><span className="font-medium text-ink">Toppreise</span> · open the product, tap the bell</li>
      </ul>
      {q.isLoading ? <Skeleton className="h-20" /> : (
        <ul className="divide-y divide-rule">
          {active.map((x) => {
            const t = x.spec.queries?.[0] || x.title;
            return (
              <li key={x.id} className="flex flex-wrap items-center justify-between gap-2 py-2.5">
                <span className="min-w-0 truncate font-medium">{t}</span>
                <AlertButtons term={t} />
              </li>
            );
          })}
        </ul>
      )}
      {s.alerts_arrived && <p className="text-[0.8125rem] text-positive">Alert mails are arriving.</p>}
    </div>
  );
}

/* --------------------------------------------------------------------- eBay */
function EbayStep({ e }: { e: EbayState }) {
  const toast = useToast();
  const refresh = useRefreshSetup();
  const [v, setV] = useState({ client_id: "", client_secret: "" });
  const save = useMutation({
    mutationFn: () => put<EbayState>("/api/setup/ebay", v),
    onSuccess: () => { refresh(); setV({ client_id: "", client_secret: "" }); toast.show("eBay key works and is saved"); },
    onError: toast.error,
  });
  const remove = useMutation({ mutationFn: () => del("/api/setup/ebay"), onSuccess: () => { refresh(); toast.show("eBay key removed"); }, onError: toast.error });
  if (e.configured)
    return (
      <div className="flex flex-wrap items-center justify-between gap-3 text-sm">
        <p>eBay is searched for everyone on this server{e.client_id_hint ? ` (App ID ${e.client_id_hint})` : ""}.</p>
        {e.from_config ? <span className="text-[0.8125rem] text-muted">Set in the server configuration.</span> : <Button size="sm" variant="danger" onClick={() => remove.mutate()} loading={remove.isPending}>Remove key</Button>}
      </div>
    );
  return (
    <form className="flex flex-col gap-4" onSubmit={(ev) => { ev.preventDefault(); save.mutate(); }}>
      <div className="rounded-[12px] bg-surface p-4 text-sm">
        <ol className="list-decimal space-y-1 pl-5 text-muted">
          <li>Sign up at the eBay Developers Program (free).</li>
          <li>Under Application Keys, create a <span className="font-medium text-ink">Production</span> keyset. eBay may first ask how you handle account-deletion notices; answer its form.</li>
          <li>Copy the App ID (Client ID) and the Cert ID (Client Secret) here.</li>
        </ol>
        <a href="https://developer.ebay.com/my/keys" target="_blank" rel="noreferrer noopener" className="mt-3 inline-block">
          <Button size="sm" icon={<ExternalLink className="size-4" aria-hidden />}>Open eBay Developers</Button>
        </a>
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="App ID (Client ID)" htmlFor="ebay-id"><Input id="ebay-id" {...secretProps} value={v.client_id} onChange={(x) => setV({ ...v, client_id: x.target.value.trim() })} /></Field>
        <Field label="Cert ID (Client Secret)" htmlFor="ebay-secret"><Input id="ebay-secret" type="password" name="ebay-app-secret" {...secretProps} value={v.client_secret} onChange={(x) => setV({ ...v, client_secret: x.target.value.trim() })} /></Field>
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <Button type="submit" variant="primary" disabled={v.client_id.length < 10 || v.client_secret.length < 10} loading={save.isPending}>Check and save</Button>
        <p className="min-w-0 flex-1 text-[0.8125rem] text-muted">Schnäppli asks eBay once whether the key works, then stores it encrypted.</p>
      </div>
    </form>
  );
}

/* --------------------------------------------------------------------- page */
function ReadyNow({ s }: { s: SetupState }) {
  const sources = useQuery({ queryKey: ["sources"], queryFn: () => get<SourceInfo[]>("/api/sources"), staleTime: 60_000 });
  const ready = (sources.data || []).filter((x) => x.state === "ready" || (x.state === "alerts" && s.mail?.state === "ok"));
  return (
    <section className="mb-8 rounded-[14px] border border-border bg-surface p-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0 flex-1">
          <h2 className="text-[1rem] font-semibold">{s.ai ? "Ready to go" : "Almost ready"}</h2>
          <p className="mt-1 text-[0.8125rem] text-muted">
            {s.ai ? "Create a search and Schnäppli starts right away in these places. Nothing else is needed." : "Choose the AI above, then Schnäppli searches these places for you right away."}
          </p>
        </div>
        {s.ai && <Link to="/searches/new"><Button variant="primary" icon={<Plus className="size-4" aria-hidden />}>New search</Button></Link>}
      </div>
      <ul className="mt-4 flex flex-wrap gap-2">
        {sources.isLoading && <Skeleton className="h-8 w-48" />}
        {ready.map((x) => (
          <li key={x.id} className="inline-flex h-8 items-center gap-1.5 rounded-full bg-raised px-3 text-[0.8125rem] font-medium">
            <Check className="size-3.5 text-positive" strokeWidth={3} aria-hidden />
            {x.name}
          </li>
        ))}
      </ul>
    </section>
  );
}

export default function Setup() {
  const q = useQuery({ queryKey: ["setup"], queryFn: () => get<SetupState>("/api/setup"), refetchInterval: 30_000 });
  const { hash } = useLocation();
  const [open, setOpen] = useState<string | null>(hash ? hash.slice(1) : null);
  const s = q.data;
  const mailOk = !!s?.mail && s.mail.state === "ok";
  const extras = s
    ? [
        {
          id: "mail",
          title: "Ricardo, tutti, Facebook and Toppreise",
          why: mailOk ? "Your mailbox is connected. Save your searches on those sites." : "Connect your mailbox once (about two minutes). Their alert mails bring the listings in.",
          done: mailOk && s.alerts_arrived,
          body: (
            <div className="flex flex-col gap-6">
              <MailStep />
              {(mailOk || s.shared_inbox) && <AlertsStep s={s} />}
            </div>
          ),
        },
        { id: "location", title: "Your postal code", why: "Shows how far away a pickup is.", done: s.location, body: <LocationStep s={s} /> },
        ...(s.telegram_configured ? [{ id: "telegram", title: "Telegram", why: "Good deals reach your phone straight away.", done: s.telegram, body: <Telegram /> }] : []),
        ...(s.is_admin && !s.ebay.configured ? [{ id: "ebay", title: "eBay for everyone", why: "A free developer key. Only you, the administrator, add it once.", done: false, body: <EbayStep e={s.ebay} /> }] : []),
      ]
    : [];
  useEffect(() => {
    if (hash) document.getElementById(hash.slice(1))?.scrollIntoView({ block: "start" });
  }, [hash, s === undefined]);
  return (
    <div className="mx-auto max-w-3xl">
      <PageHeader title="Set up Schnäppli" sub={s ? (s.ai ? "You can start now. Everything below is optional." : "One step, then you can start.") : undefined} />
      {q.error ? <ErrorBox error={q.error} onRetry={() => q.refetch()} /> : !s ? <Skeleton className="h-96" /> : (
        <>
          {!s.ai && (
            <section id="ai" className="mb-6 scroll-mt-20">
              <h2 className="mb-1 text-[1rem] font-semibold">Choose the AI</h2>
              <p className="mb-3 text-[0.8125rem] text-muted">Schnäppli uses it to understand what you want and to judge each listing.</p>
              <AIStep s={s} />
            </section>
          )}
          <ReadyNow s={s} />
          <h2 className="mb-1 text-[0.8125rem] font-medium text-muted">More, if you want it</h2>
          <ol>
            {extras.map((x) => (
              <Step key={x.id} id={x.id} title={x.title} why={x.why} done={x.done}
                open={open === x.id} onToggle={() => setOpen(open === x.id ? null : x.id)}>
                {x.body}
              </Step>
            ))}
          </ol>
          <p className="mt-6 text-[0.8125rem] text-muted">
            Your own shops, AI keys and everything else live in <Link to="/settings" className="underline decoration-control underline-offset-2 hover:text-ink">Settings</Link>.
          </p>
        </>
      )}
    </div>
  );
}
