import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { Search as SearchIcon } from "lucide-react";
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { DealCard, DealRow, DealGridSkeleton } from "@/components/deal";
import { Button, Chip, Empty, ErrorBox, Input, PageHeader, Panel } from "@/components/ui";
import { get } from "@/lib/api";
import type { Deal, Search } from "@/lib/types";
import { Picker } from "@/components/Picker";
import { usePrefs } from "@/lib/prefs";

const FILTERS = [
  { key: "all", label: "All" },
  { key: "exceptional", label: "Exceptional", params: { label: "exceptional" } },
  { key: "good", label: "Good", params: { label: "good" } },
  { key: "drops", label: "Price drops", params: { sort: "drop" } },
  { key: "favorite", label: "Favorites", params: { status: "favorite" } },
  { key: "planned", label: "Planned", params: { status: "planned" } },
  { key: "risky", label: "Risky", params: { label: "risky" } },
  { key: "rejected", label: "Rejected", params: { status: "rejected" } },
] as const;

const PAGE = 24;

export default function Deals() {
  const layout = usePrefs().deal_layout;
  const [params, setParams] = useSearchParams();
  const filter = params.get("f") || (params.get("label") === "good" ? "good" : "all");
  const sort = params.get("sort") || "score";
  const searchId = params.get("search") || "";
  const [text, setText] = useState(params.get("q") || "");
  const searches = useQuery({ queryKey: ["searches"], queryFn: () => get<Search[]>("/api/searches") });

  const f = FILTERS.find((x) => x.key === filter) ?? FILTERS[0];
  const qs = new URLSearchParams({ sort: "params" in f && f.params && "sort" in f.params ? f.params.sort : sort, days: "90" });
  if ("params" in f && f.params) for (const [k, v] of Object.entries(f.params)) if (k !== "sort") qs.set(k, v);
  if (searchId) qs.set("search_id", searchId);
  if (params.get("q")) qs.set("q", params.get("q")!);

  const q = useInfiniteQuery({
    queryKey: ["deals", qs.toString()],
    queryFn: ({ pageParam }) => get<Deal[]>(`/api/deals?${qs}&limit=${PAGE}&offset=${pageParam}`),
    initialPageParam: 0,
    getNextPageParam: (last, all) => (last.length === PAGE ? all.length * PAGE : undefined),
  });
  const deals = q.data?.pages.flat() ?? [];

  const set = (k: string, v: string) => {
    const next = new URLSearchParams(params);
    if (v) next.set(k, v);
    else next.delete(k);
    if (k === "f") next.delete("label");
    setParams(next, { replace: true });
  };

  return (
    <>
      <PageHeader title="Deals" sub="Every listing Schnäppli found for your searches, scored against the market." />

      <div className="mb-5 flex flex-col gap-3">
        <div className="-mx-4 flex gap-2 overflow-x-auto px-4 no-scrollbar sm:mx-0 sm:flex-wrap sm:px-0" role="toolbar" aria-label="Filter deals">
          {FILTERS.map((x) => (
            <Chip key={x.key} active={filter === x.key} onClick={() => set("f", x.key === "all" ? "" : x.key)}>
              {x.label}
            </Chip>
          ))}
        </div>
        <div className="flex flex-wrap gap-2">
          <form
            className="relative w-full sm:w-auto sm:min-w-[200px] sm:flex-1"
            onSubmit={(e) => {
              e.preventDefault();
              set("q", text.trim());
            }}
          >
            <SearchIcon className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-faint" aria-hidden />
            <Input
              value={text}
              onChange={(e) => setText(e.target.value)}
              onBlur={() => set("q", text.trim())}
              placeholder="Filter by title"
              aria-label="Filter by title"
              className="pl-9"
            />
          </form>
          <div className="min-w-0 flex-1 sm:w-[200px] sm:flex-none">
            <Picker label="Search" value={searchId} onChange={(v) => set("search", v)}
              options={[{ value: "", label: "All searches" }, ...(searches.data || []).map((s) => ({ value: s.id, label: s.title }))]} />
          </div>
          <div className="min-w-0 flex-1 sm:w-[160px] sm:flex-none">
            <Picker label="Sort by" value={sort} onChange={(v) => set("sort", v)}
              options={[{ value: "score", label: "Best score" }, { value: "newest", label: "Newest" }, { value: "price", label: "Lowest price" }]} />
          </div>
        </div>
      </div>

      {q.error ? (
        <ErrorBox error={q.error} onRetry={() => q.refetch()} />
      ) : q.isLoading ? (
        <DealGridSkeleton />
      ) : deals.length === 0 ? (
        <Panel>
          <Empty
            title="No deals match"
            action={
              filter !== "all" || params.get("q") ? (
                <Button onClick={() => setParams({}, { replace: true })}>Clear filters</Button>
              ) : (
                <Link to="/searches/new">
                  <Button variant="primary">New search</Button>
                </Link>
              )
            }
          >
            {filter !== "all" || params.get("q")
              ? "Try a different filter."
              : "Listings appear here after your searches run and Schnäppli has scored them."}
          </Empty>
        </Panel>
      ) : (
        <>
          {layout === "rows" ? (
            <Panel className="p-1.5">
              {deals.map((d) => (
                <DealRow key={d.id} deal={d} showSearch={!searchId} />
              ))}
            </Panel>
          ) : (
            <div className="grid grid-cols-2 gap-x-3 gap-y-6 sm:gap-x-4 md:grid-cols-3 xl:grid-cols-4">
              {deals.map((d, i) => (
                <DealCard key={d.id} deal={d} eager={i < 4} />
              ))}
            </div>
          )}
          {q.hasNextPage && (
            <div className="mt-8 flex justify-center">
              <Button onClick={() => q.fetchNextPage()} loading={q.isFetchingNextPage}>
                Show more
              </Button>
            </div>
          )}
        </>
      )}
    </>
  );
}
