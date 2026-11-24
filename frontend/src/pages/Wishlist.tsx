import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Search as SearchIcon, Trash2 } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Button, cx, Empty, ErrorBox, Field, IconButton, Input, PageHeader, Panel, Pill, Segmented, Sheet, Skeleton, Switch, useToast } from "@/components/ui";
import { del, get, patch, post } from "@/lib/api";
import { useMe } from "@/lib/auth";
import { money } from "@/lib/format";
import type { Search, WishItem } from "@/lib/types";
import { Picker } from "@/components/Picker";

type Draft = { title: string; parent_id: string; budget: string; essential: boolean; compat: string; category: string };

function ItemSheet({ open, onOpenChange, parents, initialParent }: { open: boolean; onOpenChange: (v: boolean) => void; parents: WishItem[]; initialParent?: string }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [d, setD] = useState<Draft>({ title: "", parent_id: initialParent || "", budget: "", essential: false, compat: "", category: "" });
  const create = useMutation({
    mutationFn: () => {
      const compatibility: Record<string, string> = {};
      for (const part of d.compat.split(",")) {
        const [k, ...rest] = part.split(":");
        if (k.trim() && rest.join(":").trim()) compatibility[k.trim()] = rest.join(":").trim();
        else if (k.trim()) compatibility["requires"] = k.trim();
      }
      return post("/api/wishlist", {
        title: d.title,
        parent_id: d.parent_id || null,
        budget: d.budget ? Number(d.budget.replace(",", ".")) : null,
        essential: d.essential,
        category: d.category || null,
        compatibility,
      });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["wishlist"] });
      onOpenChange(false);
      setD({ title: "", parent_id: "", budget: "", essential: false, compat: "", category: "" });
    },
    onError: toast.error,
  });
  return (
    <Sheet
      open={open}
      onOpenChange={onOpenChange}
      title={d.parent_id ? "Add accessory" : "Add to wishlist"}
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button variant="primary" disabled={!d.title.trim()} loading={create.isPending} onClick={() => create.mutate()}>Add</Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <Field label="What" htmlFor="w-title">
          <Input id="w-title" value={d.title} onChange={(e) => setD({ ...d, title: e.target.value })} placeholder="e.g. Sigma 30mm f/1.4" maxLength={160} />
        </Field>
        <Field label="Belongs to">
          <Picker label="Belongs to" value={d.parent_id} onChange={(id) => setD({ ...d, parent_id: id })}
            options={[{ value: "", label: "Nothing, it's a main item" }, ...parents.map((p) => ({ value: p.id, label: `Accessory for ${p.title}` }))]} />
        </Field>
        <div className="grid grid-cols-2 gap-4">
          <Field label="Budget" htmlFor="w-budget">
            <Input id="w-budget" inputMode="decimal" value={d.budget} onChange={(e) => setD({ ...d, budget: e.target.value })} />
          </Field>
          <Field label="Category" htmlFor="w-cat">
            <Input id="w-cat" value={d.category} onChange={(e) => setD({ ...d, category: e.target.value })} />
          </Field>
        </div>
        <Field label="Compatibility" htmlFor="w-compat" hint="e.g. “mount: Sony E, battery: NP-FW50”. Accessories inherit their main item's values.">
          <Input id="w-compat" value={d.compat} onChange={(e) => setD({ ...d, compat: e.target.value })} />
        </Field>
        {d.parent_id && (
          <div className="flex items-center justify-between">
            <span className="text-sm">Essential, not optional</span>
            <Switch checked={d.essential} onChange={(v) => setD({ ...d, essential: v })} label="Essential" />
          </div>
        )}
      </div>
    </Sheet>
  );
}

function Row({ item, nested, searches }: { item: WishItem; nested?: boolean; searches: Search[] }) {
  const me = useMe();
  const qc = useQueryClient();
  const nav = useNavigate();
  const toast = useToast();
  const inv = () => qc.invalidateQueries({ queryKey: ["wishlist"] });
  const setStatus = useMutation({ mutationFn: (status: string) => patch(`/api/wishlist/${item.id}`, { status }), onSuccess: inv, onError: toast.error });
  const remove = useMutation({ mutationFn: () => del(`/api/wishlist/${item.id}`), onSuccess: inv, onError: toast.error });
  const toSearch = useMutation({
    mutationFn: () => post<Search>(`/api/wishlist/${item.id}/search`),
    onSuccess: (s) => {
      inv();
      qc.invalidateQueries({ queryKey: ["searches"] });
      nav(`/searches/${s.id}`);
    },
    onError: toast.error,
  });
  const linked = searches.find((s) => s.id === item.search_id);
  const done = item.status === "purchased";
  return (
    <li className={cx("flex items-center gap-3 border-t border-rule py-3 first:border-t-0", nested && "pl-6 sm:pl-8")}>
      <button
        aria-label={done ? "Mark as not bought" : "Mark as bought"}
        onClick={() => setStatus.mutate(done ? "planned" : "purchased")}
        className={cx("flex size-5 shrink-0 items-center justify-center rounded-full border-[1.5px]", done ? "border-ink bg-ink" : "border-control hover:border-ink")}
      >
        {done && <span className="size-2 rounded-full bg-on-ink" />}
      </button>
      <div className="min-w-0 flex-1">
        <div className={cx("flex flex-wrap items-center gap-x-2 text-sm", done ? "text-muted line-through" : "font-medium")}>
          {item.title}
          {nested && item.essential && <Pill tone="warning">Essential</Pill>}
        </div>
        <div className="mt-0.5 truncate text-[0.8125rem] text-muted">
          {[item.budget !== null ? money(item.budget, me.currency) : null, ...Object.entries(item.compatibility).map(([k, v]) => `${k}: ${v}`)].filter(Boolean).join(" · ") || "No budget"}
          {linked && (
            <>
              {" · "}
              <Link to={`/searches/${linked.id}`} className="underline underline-offset-2">{linked.stats.matches ?? 0} matches</Link>
            </>
          )}
        </div>
      </div>
      {!linked && !done && (
        <Button size="sm" onClick={() => toSearch.mutate()} loading={toSearch.isPending} icon={<SearchIcon className="size-3.5" aria-hidden />}>
          <span className="hidden sm:inline">Find deals</span>
          <span className="sm:hidden">Find</span>
        </Button>
      )}
      <IconButton label={`Remove ${item.title}`} onClick={() => remove.mutate()}>
        <Trash2 className="size-4" />
      </IconButton>
    </li>
  );
}

export default function Wishlist() {
  const me = useMe();
  const [open, setOpen] = useState(false);
  const [view, setView] = useState<"open" | "all">("open");
  const q = useQuery({ queryKey: ["wishlist"], queryFn: () => get<WishItem[]>("/api/wishlist") });
  const searches = useQuery({ queryKey: ["searches"], queryFn: () => get<Search[]>("/api/searches") });
  const items = (q.data || []).filter((i) => view === "all" || (i.status !== "purchased" && i.status !== "rejected"));
  const mains = items.filter((i) => !i.parent_id);
  const orphans = items.filter((i) => i.parent_id && !mains.some((m) => m.id === i.parent_id));
  const planned = (q.data || []).filter((i) => i.status === "planned" || i.status === "interested").reduce((s, i) => s + (i.budget || 0), 0);

  return (
    <>
      <PageHeader
        title="Wishlist"
        sub={q.data?.length ? `Planned spend ${money(planned, me.currency)}, if everything comes in at budget.` : "Things you want, with the accessories that go with them."}
        actions={<Button variant="primary" onClick={() => setOpen(true)} icon={<Plus className="size-4" aria-hidden />}>Add</Button>}
      />
      <div className="mb-4">
        <Segmented label="Show" value={view} onChange={setView} options={[{ value: "open", label: "Still to buy" }, { value: "all", label: "Everything" }]} />
      </div>
      {q.error ? (
        <ErrorBox error={q.error} onRetry={() => q.refetch()} />
      ) : q.isLoading ? (
        <Skeleton className="h-48" />
      ) : mains.length === 0 && orphans.length === 0 ? (
        <Panel>
          <Empty title="Your wishlist is empty" action={<Button variant="primary" onClick={() => setOpen(true)}>Add an item</Button>}>
            Add a main product, like a camera, and its accessories: a lens, spare batteries, a bag. Accessories inherit compatibility, so a lens search knows the mount.
          </Empty>
        </Panel>
      ) : (
        <div className="flex flex-col gap-4">
          {mains.map((m) => {
            const acc = items.filter((i) => i.parent_id === m.id);
            const total = [m, ...acc].reduce((s, i) => s + (i.budget || 0), 0);
            return (
              <Panel key={m.id} className="px-4 sm:px-5">
                <ul>
                  <Row item={m} searches={searches.data || []} />
                  {acc.map((a) => <Row key={a.id} item={a} nested searches={searches.data || []} />)}
                </ul>
                <div className="flex items-center justify-between border-t border-rule py-2.5 text-[0.8125rem]">
                  <AddAccessory parent={m} parents={mains} />
                  {acc.length > 0 && <span className="num text-muted">Set total {money(total, me.currency)}</span>}
                </div>
              </Panel>
            );
          })}
          {orphans.length > 0 && (
            <Panel className="px-4 sm:px-5">
              <ul>{orphans.map((o) => <Row key={o.id} item={o} searches={searches.data || []} />)}</ul>
            </Panel>
          )}
        </div>
      )}
      <ItemSheet open={open} onOpenChange={setOpen} parents={mains} />
    </>
  );
}

function AddAccessory({ parent, parents }: { parent: WishItem; parents: WishItem[] }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button onClick={() => setOpen(true)} className="inline-flex items-center gap-1 font-medium text-muted hover:text-ink">
        <Plus className="size-3.5" aria-hidden /> Accessory
      </button>
      {open && <ItemSheet open={open} onOpenChange={setOpen} parents={parents} initialParent={parent.id} />}
    </>
  );
}
