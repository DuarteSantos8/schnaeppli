import { useQuery } from "@tanstack/react-query";
import { Plus, X } from "lucide-react";
import { useState, type KeyboardEvent, type ReactNode } from "react";
import { get } from "@/lib/api";
import type { ProductTarget, Search, SearchSpec, SourceInfo } from "@/lib/types";
import { Button, cx, Field, Input, Pill, Segmented, Switch } from "./ui";
import { Picker } from "./Picker";

export type SearchValues = Pick<
  Search,
  | "title" | "category" | "spec" | "max_budget" | "currency" | "condition" | "prefer_condition" | "postal_code"
  | "radius_km" | "delivery" | "sources" | "schedule" | "notify" | "priority" | "min_score"
>;

export const emptySpec = (): SearchSpec => ({
  desired_products: [], alternatives: [], allow_alternatives: true, excluded: [], preferred_brands: [],
  accessories: [], must_have: [], nice_to_have: [], queries: [], notes: null,
});

export function TagInput({ value, onChange, placeholder, label }: { value: string[]; onChange: (v: string[]) => void; placeholder?: string; label: string }) {
  const [text, setText] = useState("");
  const add = () => {
    const t = text.trim();
    if (t && !value.includes(t)) onChange([...value, t]);
    setText("");
  };
  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" || e.key === ",") {
      e.preventDefault();
      add();
    } else if (e.key === "Backspace" && !text && value.length) onChange(value.slice(0, -1));
  };
  return (
    <div className="flex min-h-10 flex-wrap items-center gap-1.5 rounded-[var(--radius-control)] border border-control bg-surface px-2 py-1.5 focus-within:border-ink">
      {value.map((v) => (
        <span key={v} className="inline-flex h-7 items-center gap-1 rounded-[5px] bg-raised pr-1 pl-2 text-[0.8125rem]">
          {v}
          <button type="button" aria-label={`Remove ${v}`} onClick={() => onChange(value.filter((x) => x !== v))} className="rounded p-0.5 text-muted hover:text-ink">
            <X className="size-3" />
          </button>
        </span>
      ))}
      <input
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={onKey}
        onBlur={add}
        aria-label={label}
        placeholder={value.length ? "" : placeholder}
        className="h-7 min-w-[120px] flex-1 bg-transparent text-sm outline-none placeholder:text-faint"
      />
    </div>
  );
}

function ProductList({ items, onChange, withReason, placeholder }: { items: ProductTarget[]; onChange: (v: ProductTarget[]) => void; withReason?: boolean; placeholder: string }) {
  return (
    <div className="flex flex-col gap-2">
      {items.map((p, i) => (
        <div key={i} className="flex items-start gap-2">
          <div className="flex min-w-0 flex-1 flex-col gap-1.5">
            <Input value={p.name} aria-label="Product" onChange={(e) => onChange(items.map((x, j) => (j === i ? { ...x, name: e.target.value } : x)))} />
            {withReason && (
              <Input
                value={p.reason || ""}
                aria-label="Why it fits"
                placeholder="Why it's a good alternative"
                className="h-9 text-[0.8125rem] text-muted"
                onChange={(e) => onChange(items.map((x, j) => (j === i ? { ...x, reason: e.target.value } : x)))}
              />
            )}
          </div>
          <button type="button" aria-label="Remove" onClick={() => onChange(items.filter((_, j) => j !== i))} className="mt-2 rounded p-1 text-muted hover:bg-sunk hover:text-ink">
            <X className="size-4" />
          </button>
        </div>
      ))}
      <button
        type="button"
        onClick={() => onChange([...items, { name: "", reason: null }])}
        className="inline-flex items-center gap-1.5 self-start rounded px-1 py-1 text-[0.8125rem] font-medium text-muted hover:text-ink"
      >
        <Plus className="size-3.5" /> {placeholder}
      </button>
    </div>
  );
}

function Section({ title, description, children }: { title: string; description?: string; children: ReactNode }) {
  return (
    <section className="grid gap-3 border-t border-rule py-6 first:border-t-0 first:pt-0 md:grid-cols-[220px_1fr] md:gap-8">
      <div>
        <h3 className="text-[0.9375rem] font-semibold">{title}</h3>
        {description && <p className="mt-1 text-[0.8125rem] text-muted">{description}</p>}
      </div>
      <div className="flex min-w-0 flex-col gap-4">{children}</div>
    </section>
  );
}

export function SearchForm({ value, onChange }: { value: SearchValues; onChange: (v: SearchValues) => void }) {
  const set = <K extends keyof SearchValues>(k: K, v: SearchValues[K]) => onChange({ ...value, [k]: v });
  const setSpec = <K extends keyof SearchSpec>(k: K, v: SearchSpec[K]) => onChange({ ...value, spec: { ...value.spec, [k]: v } });
  const sources = useQuery({ queryKey: ["sources"], queryFn: () => get<SourceInfo[]>("/api/sources") });
  const sched = value.schedule || { mode: "default" };

  return (
    <div>
      <Section title="What you want" description="Schnäppli searches for these and judges every listing against them.">
        <Field label="Title" htmlFor="sf-title">
          <Input id="sf-title" value={value.title} onChange={(e) => set("title", e.target.value)} maxLength={120} />
        </Field>
        <Field label="Products">
          <ProductList items={value.spec.desired_products} onChange={(v) => setSpec("desired_products", v)} placeholder="Add product" />
        </Field>
        <div className="flex items-start justify-between gap-4 rounded-[var(--radius-control)] bg-sunk px-3 py-3">
          <div>
            <div className="text-sm font-medium">Comparable alternatives are fine</div>
            <div className="text-[0.8125rem] text-muted">Schnäppli also considers similar products and explains why each one fits.</div>
          </div>
          <Switch checked={value.spec.allow_alternatives} onChange={(v) => setSpec("allow_alternatives", v)} label="Allow alternatives" />
        </div>
        {value.spec.allow_alternatives && (
          <Field label="Alternatives">
            <ProductList items={value.spec.alternatives} onChange={(v) => setSpec("alternatives", v)} withReason placeholder="Add alternative" />
          </Field>
        )}
        <Field label="Must have" hint="Hard requirements, e.g. “4 drive bays”, “E-mount”.">
          <TagInput label="Must have" value={value.spec.must_have} onChange={(v) => setSpec("must_have", v)} placeholder="Type and press Enter" />
        </Field>
        <Field label="Exclude" hint="Listings with these words are skipped before any AI cost.">
          <TagInput label="Exclude" value={value.spec.excluded} onChange={(v) => setSpec("excluded", v)} placeholder="e.g. defekt, box only" />
        </Field>
        <Field label="Preferred brands">
          <TagInput label="Preferred brands" value={value.spec.preferred_brands} onChange={(v) => setSpec("preferred_brands", v)} />
        </Field>
        <Field label="Marketplace search terms" hint="What Schnäppli types into each marketplace. Short, the way sellers title listings.">
          <TagInput label="Search terms" value={value.spec.queries} onChange={(v) => setSpec("queries", v.slice(0, 12))} placeholder="e.g. a6400, ILCE-6400" />
        </Field>
      </Section>

      <Section title="Budget and condition">
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label={`Maximum price (${value.currency})`} htmlFor="sf-budget" hint="Including shipping.">
            <Input
              id="sf-budget"
              inputMode="decimal"
              value={value.max_budget ?? ""}
              onChange={(e) => set("max_budget", e.target.value === "" ? null : Number(e.target.value.replace(",", ".")) || 0)}
            />
          </Field>
          <Field label="Category" htmlFor="sf-cat">
            <Input id="sf-cat" value={value.category || ""} onChange={(e) => set("category", e.target.value || null)} maxLength={80} />
          </Field>
        </div>
        <Field label="Condition">
          <Segmented
            label="Condition"
            value={value.condition}
            onChange={(v) => set("condition", v)}
            options={[
              { value: "any", label: "New or used" },
              { value: "used", label: "Used only" },
              { value: "new", label: "New only" },
            ]}
          />
        </Field>
        {value.condition === "any" && (
          <Field label="Prefer">
            <Segmented
              label="Prefer"
              value={value.prefer_condition || "none"}
              onChange={(v) => set("prefer_condition", v === "none" ? null : (v as "used" | "new"))}
              options={[
                { value: "none", label: "No preference" },
                { value: "used", label: "Used" },
                { value: "new", label: "New" },
              ]}
            />
          </Field>
        )}
      </Section>

      <Section title="Location and delivery" description="Leave empty to use your defaults from Settings.">
        <Field label="Delivery">
          <Segmented
            label="Delivery"
            value={value.delivery || "default"}
            onChange={(v) => set("delivery", v === "default" ? null : (v as "ship" | "pickup" | "both"))}
            options={[
              { value: "default", label: "Default" },
              { value: "both", label: "Ship or pick up" },
              { value: "ship", label: "Shipping" },
              { value: "pickup", label: "Pickup" },
            ]}
          />
        </Field>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Postal code" htmlFor="sf-plz" hint="Only if different from your home.">
            <Input id="sf-plz" inputMode="numeric" value={value.postal_code || ""} onChange={(e) => set("postal_code", e.target.value || null)} maxLength={10} />
          </Field>
          <Field label="Pickup radius (km)" htmlFor="sf-radius">
            <Input id="sf-radius" inputMode="numeric" value={value.radius_km ?? ""} onChange={(e) => set("radius_km", e.target.value ? Number(e.target.value) || null : null)} />
          </Field>
        </div>
      </Section>

      <Section title="Sources" description="All available sources are used unless you turn one off.">
        <ul className="flex flex-col">
          {(sources.data || []).filter((s) => s.id !== "link").map((s) => {
            const cfg = value.sources[s.id];
            const enabled = cfg?.enabled ?? true;
            return (
              <li key={s.id} className="flex items-start justify-between gap-4 border-t border-rule py-3 first:border-t-0 first:pt-0">
                <div className="min-w-0">
                  <div className="flex items-center gap-2 text-sm font-medium">
                    {s.name}
                    {s.state !== "ready" && (
                      <Pill tone={s.state === "needs_credentials" ? "warning" : "neutral"}>
                        {s.state === "needs_credentials" ? "Needs setup" : s.state === "planned" ? "Planned" : "Not supported"}
                      </Pill>
                    )}
                  </div>
                  <div className="mt-0.5 text-[0.8125rem] text-muted">{s.reason}</div>
                </div>
                <Switch
                  checked={s.available && enabled}
                  disabled={!s.available}
                  onChange={(v) => set("sources", { ...value.sources, [s.id]: { enabled: v, priority: cfg?.priority ?? 5 } })}
                  label={`Use ${s.name}`}
                />
              </li>
            );
          })}
        </ul>
      </Section>

      <Section title="Schedule and alerts">
        <Field label="How often to search">
          <Segmented
            label="Schedule"
            value={sched.mode}
            onChange={(v) => set("schedule", v === "interval" ? { mode: "interval", hours: 6 } : v === "custom" ? { mode: "custom", times: ["08:00"] } : { mode: "default" })}
            options={[
              { value: "default", label: "My daily runs" },
              { value: "interval", label: "Every few hours" },
              { value: "custom", label: "Custom times" },
            ]}
          />
        </Field>
        {sched.mode === "interval" && (
          <Field label="Every" htmlFor="sf-hours">
            <div className="w-40">
              <Picker id="sf-hours" label="Run every" value={String(sched.hours ?? 6)} onChange={(h) => set("schedule", { mode: "interval", hours: Number(h) })}
                options={[1, 2, 3, 4, 6, 8, 12, 24].map((h) => ({ value: String(h), label: h === 1 ? "hour" : `${h} hours` }))} />
            </div>
          </Field>
        )}
        {sched.mode === "custom" && (
          <Field label="Times" hint="24-hour, your timezone. Press Enter after each.">
            <TagInput
              label="Times"
              value={sched.times || []}
              onChange={(v) => set("schedule", { mode: "custom", times: v.filter((t) => /^([01]\d|2[0-3]):[0-5]\d$/.test(t)) })}
              placeholder="07:30"
            />
          </Field>
        )}
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Instant alert from score" htmlFor="sf-alert" hint="Exceptional deals always alert.">
            <Input
              id="sf-alert"
              inputMode="numeric"
              value={value.notify.instant_min_score}
              onChange={(e) => set("notify", { ...value.notify, instant_min_score: Math.max(0, Math.min(100, Number(e.target.value) || 0)) })}
            />
          </Field>
          <Field label="Priority">
            <Segmented
              label="Priority"
              value={String(value.priority) as "1" | "2" | "3"}
              onChange={(v) => set("priority", Number(v))}
              options={[
                { value: "1", label: "High" },
                { value: "2", label: "Normal" },
                { value: "3", label: "Low" },
              ]}
            />
          </Field>
        </div>
      </Section>
    </div>
  );
}

export function FormActions({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div
      className={cx(
        "sticky bottom-[calc(var(--safe-bottom)+56px)] z-20 -mx-4 mt-6 flex justify-end gap-2 border-t border-border bg-ground/95 px-4 py-3 sm:-mx-6 sm:px-6 lg:bottom-4 lg:mx-0 lg:rounded-[var(--radius-card)] lg:border lg:bg-surface lg:px-4",
        className,
      )}
    >
      {children}
    </div>
  );
}

export { Button };
