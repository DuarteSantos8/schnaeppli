import * as Menu from "@radix-ui/react-dropdown-menu";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { MoreHorizontal, Plus } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Photo } from "@/components/deal";
import { Button, Confirm, cx, Empty, ErrorBox, PageHeader, Panel, Pill, Segmented, Skeleton, useToast } from "@/components/ui";
import { del, get, patch, post } from "@/lib/api";
import { dayTime, money, relTime } from "@/lib/format";
import type { Search, SearchStatus } from "@/lib/types";

export function SearchMenu({ s, onDeleted }: { s: Search; onDeleted?: () => void }) {
  const qc = useQueryClient();
  const nav = useNavigate();
  const toast = useToast();
  const [confirm, setConfirm] = useState(false);
  const inv = () => {
    qc.invalidateQueries({ queryKey: ["searches"] });
    qc.invalidateQueries({ queryKey: ["search", s.id] });
    qc.invalidateQueries({ queryKey: ["dashboard"] });
  };
  const setStatus = useMutation({
    mutationFn: (status: SearchStatus) => patch(`/api/searches/${s.id}`, { status }),
    onSuccess: (_d, st) => {
      inv();
      toast.show(st === "paused" ? "Search paused" : st === "active" ? "Search resumed" : st === "archived" ? "Search archived" : "Marked as done");
    },
    onError: toast.error,
  });
  const dup = useMutation({
    mutationFn: () => post<Search>(`/api/searches/${s.id}/duplicate`),
    onSuccess: (c) => {
      inv();
      nav(`/searches/${c.id}`);
      toast.show("Copy created (paused)");
    },
    onError: toast.error,
  });
  const remove = useMutation({
    mutationFn: () => del(`/api/searches/${s.id}`),
    onSuccess: () => {
      inv();
      setConfirm(false);
      toast.show("Search deleted");
      onDeleted?.();
    },
    onError: toast.error,
  });
  const item = "flex h-9 cursor-pointer items-center rounded-[6px] px-2.5 text-sm outline-none data-[highlighted]:bg-sunk";
  return (
    <>
      <Menu.Root>
        <Menu.Trigger asChild>
          <button aria-label={`Options for ${s.title}`} className="pressable flex size-9 items-center justify-center rounded-[var(--radius-control)] text-muted hover:bg-sunk hover:text-ink">
            <MoreHorizontal className="size-4" />
          </button>
        </Menu.Trigger>
        <Menu.Portal>
          <Menu.Content align="end" sideOffset={4} className="menu-content z-50 min-w-[180px] rounded-[8px] border border-border bg-surface p-1 shadow-[0_10px_30px_rgba(0,0,0,0.12)]">
            {s.status === "active" ? (
              <Menu.Item className={item} onSelect={() => setStatus.mutate("paused")}>Pause</Menu.Item>
            ) : (
              <Menu.Item className={item} onSelect={() => setStatus.mutate("active")}>Resume</Menu.Item>
            )}
            <Menu.Item className={item} onSelect={() => dup.mutate()}>Duplicate</Menu.Item>
            {s.status !== "completed" && <Menu.Item className={item} onSelect={() => setStatus.mutate("completed")}>Mark as done</Menu.Item>}
            {s.status !== "archived" && <Menu.Item className={item} onSelect={() => setStatus.mutate("archived")}>Archive</Menu.Item>}
            <Menu.Separator className="my-1 h-px bg-rule" />
            <Menu.Item className={cx(item, "text-negative")} onSelect={() => setConfirm(true)}>Delete</Menu.Item>
          </Menu.Content>
        </Menu.Portal>
      </Menu.Root>
      <Confirm
        open={confirm}
        onOpenChange={setConfirm}
        title={`Delete “${s.title}”?`}
        body="Its results and history are removed too. Archive it instead if you might want it back."
        confirmLabel="Delete"
        danger
        loading={remove.isPending}
        onConfirm={() => remove.mutate()}
      />
    </>
  );
}

export function StatusPill({ status }: { status: SearchStatus }) {
  const map = { active: ["Active", "score"], paused: ["Paused", "neutral"], archived: ["Archived", "neutral"], completed: ["Done", "positive"] } as const;
  const [t, tone] = map[status];
  return <Pill tone={tone}>{t}</Pill>;
}

export default function Searches() {
  const [tab, setTab] = useState<"active" | "paused" | "done">("active");
  const q = useQuery({ queryKey: ["searches"], queryFn: () => get<Search[]>("/api/searches") });
  const all = q.data || [];
  const list = all.filter((s) => (tab === "active" ? s.status === "active" : tab === "paused" ? s.status === "paused" : s.status === "archived" || s.status === "completed"));
  const counts = { active: all.filter((s) => s.status === "active").length, paused: all.filter((s) => s.status === "paused").length };

  return (
    <>
      <PageHeader
        title="Searches"
        sub="Each one runs on its own schedule and keeps its own results."
        actions={
          <Link to="/searches/new">
            <Button variant="primary" icon={<Plus className="size-4" aria-hidden />}>New search</Button>
          </Link>
        }
      />
      <div className="mb-5">
        <Segmented
          label="Status"
          value={tab}
          onChange={setTab}
          options={[
            { value: "active", label: `Active ${counts.active || ""}`.trim() },
            { value: "paused", label: `Paused ${counts.paused || ""}`.trim() },
            { value: "done", label: "Done & archived" },
          ]}
        />
      </div>
      {q.error ? (
        <ErrorBox error={q.error} onRetry={() => q.refetch()} />
      ) : q.isLoading ? (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-72" />)}</div>
      ) : list.length === 0 ? (
        <Panel>
          <Empty
            title={tab === "active" ? "No active searches" : tab === "paused" ? "Nothing paused" : "Nothing here yet"}
            action={tab === "active" ? <Link to="/searches/new"><Button variant="primary">New search</Button></Link> : undefined}
          >
            {tab === "active" ? "Describe something you'd like to buy and Schnäppli keeps an eye out for it." : null}
          </Empty>
        </Panel>
      ) : (
        <div className="grid gap-x-4 gap-y-6 sm:grid-cols-2 xl:grid-cols-3">
          {list.map((s) => (
            <article key={s.id} className="group relative">
              <Link to={`/searches/${s.id}`} className="pressable block">
                <Photo
                  src={s.stats.image}
                  alt=""
                  width={640}
                  className="aspect-[16/10] w-full rounded-[var(--radius-card)]"
                  empty={(s.stats.matches ?? 0) === 0 ? (s.status === "active" ? "Looking. Nothing found yet." : "No matches") : "No photo"}
                />
                <div className="mt-3 flex items-start justify-between gap-3 pr-10">
                  <div className="min-w-0">
                    <h2 className="truncate text-[1rem] font-semibold tracking-[-0.01em] group-hover:underline group-hover:decoration-control group-hover:underline-offset-2">{s.title}</h2>
                    <p className="num mt-0.5 text-[0.8125rem] text-muted">
                      {s.max_budget !== null ? `Up to ${money(s.max_budget, s.currency)}` : "No budget set"}
                      {s.condition !== "any" ? ` · ${s.condition === "used" ? "used" : "new"}` : ""}
                    </p>
                  </div>
                </div>
                <dl className="num mt-3 grid grid-cols-3 gap-2 text-[0.8125rem]">
                  <div>
                    <dt className="text-muted">Matches</dt>
                    <dd className="text-[0.9375rem] font-medium">{s.stats.matches ?? 0}</dd>
                  </div>
                  <div>
                    <dt className="text-muted">Good deals</dt>
                    <dd className="text-[0.9375rem] font-medium">{s.stats.good_deals ?? 0}</dd>
                  </div>
                  <div>
                    <dt className="text-muted">Best</dt>
                    <dd className={cx("text-[0.9375rem] font-medium", s.stats.best_score ? "text-score" : "text-faint")}>{s.stats.best_score ?? "–"}</dd>
                  </div>
                </dl>
                <p className="mt-2 text-[0.75rem] text-muted">
                  {s.last_error ? (
                    <span className="text-negative">Last run had problems</span>
                  ) : s.status === "active" ? (
                    `Checked ${relTime(s.last_run_at)} · next ${dayTime(s.next_run_at)}`
                  ) : (
                    <StatusPill status={s.status} />
                  )}
                </p>
              </Link>
              <div className="absolute top-0 right-0 m-2 rounded-[var(--radius-control)] bg-surface/95">
                <SearchMenu s={s} />
              </div>
            </article>
          ))}
        </div>
      )}
    </>
  );
}
