import * as Dialog from "@radix-ui/react-dialog";
import { useQuery } from "@tanstack/react-query";
import {
  Compass,
  Gauge,
  Heart,
  Home,
  LayoutList,
  MessageCircle,
  MoreHorizontal,
  PiggyBank,
  Plus,
  Search as SearchIcon,
  Settings,
  Sparkles,
  Tag,
  Wrench,
} from "lucide-react";
import { Suspense, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { get } from "@/lib/api";
import { useMe } from "@/lib/auth";
import { money } from "@/lib/format";
import { usePrefs, usePrefsEffect, type NavTab } from "@/lib/prefs";
import type { Deal, Search } from "@/lib/types";
import { cx } from "./ui";
import { Wordmark } from "./wordmark";

export { Wordmark };

/** The winking ä: one open eye, one wink. Takes the accent colour. */
export function Mark({ size = 22 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" aria-hidden>
      <rect width="64" height="64" rx="15" fill="var(--color-score)" />
      <g transform="translate(32 32) scale(0.86) translate(-29 -35.5)" fill="none" stroke="#fff">
        <circle cx="28" cy="39" r="12.5" strokeWidth="7.5" />
        <rect x="37.25" y="22.75" width="7.5" height="32.5" fill="#fff" stroke="none" />
        <circle cx="23.5" cy="16" r="4.3" fill="#fff" stroke="none" />
        <path d="M30.8 17.4 q4.3 -5.8 8.6 0" strokeWidth="3.8" strokeLinecap="round" />
      </g>
    </svg>
  );
}

export const NAV: { id: NavTab; to: string; label: string; icon: typeof Home; end?: boolean }[] = [
  { id: "home", to: "/", label: "Home", icon: Home, end: true },
  { id: "deals", to: "/deals", label: "Deals", icon: Compass },
  { id: "searches", to: "/searches", label: "Searches", icon: LayoutList },
  { id: "wishlist", to: "/wishlist", label: "Wishlist", icon: Heart },
  { id: "assistant", to: "/assistant", label: "Assistant", icon: MessageCircle },
  { id: "budget", to: "/budget", label: "Budget", icon: PiggyBank },
  { id: "usage", to: "/usage", label: "AI usage", icon: Gauge },
];

function useSearches() {
  return useQuery({ queryKey: ["searches"], queryFn: () => get<Search[]>("/api/searches"), staleTime: 30_000 });
}

function Sidebar({ onSearch }: { onSearch: () => void }) {
  const me = useMe();
  const searches = useSearches();
  const active = (searches.data || []).filter((s) => s.status === "active").slice(0, 6);
  return (
    <aside className="sticky top-0 hidden h-dvh w-[232px] shrink-0 flex-col border-r border-border bg-side px-3 pt-4 pb-3 lg:flex">
      <div className="flex items-center gap-2 px-2 pb-4">
        <Mark />
        <Wordmark height={20} />
      </div>
      <button
        onClick={onSearch}
        className="pressable mb-3 flex h-9 items-center gap-2 rounded-[var(--radius-control)] border border-border bg-surface px-2.5 text-left text-sm text-muted hover:border-control"
      >
        <SearchIcon className="size-4" aria-hidden />
        <span className="flex-1">Search</span>
        <kbd className="rounded bg-sunk px-1.5 text-[0.6875rem] font-medium text-muted">⌘K</kbd>
      </button>
      <nav aria-label="Main" className="flex flex-col gap-0.5">
        {NAV.map((n) => (
          <NavLink
            key={n.to}
            to={n.to}
            end={n.end}
            className={({ isActive }) =>
              cx(
                "pressable flex h-8 items-center gap-2.5 rounded-[var(--radius-control)] px-2 text-sm",
                isActive ? "bg-side-active font-medium text-ink shadow-[0_1px_2px_rgba(0,0,0,0.06)]" : "text-ink-2 hover:bg-side-hover hover:text-ink",
              )
            }
          >
            <n.icon className="size-4 shrink-0" strokeWidth={1.75} aria-hidden />
            {n.label}
          </NavLink>
        ))}
      </nav>

      <div className="mt-6 flex items-center justify-between px-2 pb-1">
        <span className="text-[0.75rem] text-muted">Active searches</span>
        <NavLink to="/searches/new" aria-label="New search" className="rounded p-0.5 text-muted hover:bg-side-hover hover:text-ink">
          <Plus className="size-3.5" aria-hidden />
        </NavLink>
      </div>
      <div className="flex min-h-0 flex-col gap-0.5 overflow-y-auto">
        {active.length === 0 && !searches.isLoading && (
          <NavLink to="/searches/new" className="px-2 py-1 text-[0.8125rem] text-muted hover:text-ink">
            Start your first search
          </NavLink>
        )}
        {active.map((s) => (
          <NavLink
            key={s.id}
            to={`/searches/${s.id}`}
            className={({ isActive }) =>
              cx(
                "flex h-8 items-center justify-between gap-2 rounded-[var(--radius-control)] px-2 text-[0.8125rem]",
                isActive ? "bg-side-active text-ink shadow-[0_1px_2px_rgba(0,0,0,0.06)]" : "text-ink-2 hover:bg-side-hover hover:text-ink",
              )
            }
          >
            <span className="truncate">{s.title}</span>
            {(s.stats.new ?? 0) > 0 && <span className="num shrink-0 text-[0.75rem] whitespace-nowrap text-muted">{s.stats.new} new</span>}
          </NavLink>
        ))}
      </div>

      <div className="mt-auto pt-3">
        <NavLink
          to="/settings"
          className={({ isActive }) =>
            cx(
              "flex h-10 items-center gap-2.5 rounded-[var(--radius-control)] px-2 text-sm",
              isActive ? "bg-side-active" : "hover:bg-side-hover",
            )
          }
        >
          <span className="flex size-6 items-center justify-center rounded-full bg-score-soft text-[0.75rem] font-semibold text-score">
            {me.display_name.slice(0, 1).toUpperCase()}
          </span>
          <span className="min-w-0 flex-1 truncate">{me.display_name}</span>
          <Settings className="size-4 text-muted" strokeWidth={1.75} aria-hidden />
        </NavLink>
      </div>
    </aside>
  );
}

function MobileTopBar({ onSearch }: { onSearch: () => void }) {
  return (
    <div
      className="sticky top-0 z-30 flex items-center justify-between bg-ground/95 px-4 lg:hidden"
      style={{ paddingTop: "var(--safe-top)", height: "calc(52px + var(--safe-top))" }}
    >
      <NavLink to="/" className="flex items-center gap-2" aria-label="Schnäppli home">
        <Mark size={22} />
        <Wordmark height={20} />
      </NavLink>
      <div className="flex items-center gap-1">
        <button onClick={onSearch} aria-label="Search" className="pressable flex size-10 items-center justify-center rounded-full text-ink">
          <SearchIcon className="size-[20px]" strokeWidth={1.75} />
        </button>
        <NavLink to="/searches/new" aria-label="New search" className="pressable flex size-10 items-center justify-center rounded-full text-ink">
          <Plus className="size-[22px]" strokeWidth={1.75} />
        </NavLink>
      </div>
    </div>
  );
}

function BottomNav() {
  const [more, setMore] = useState(false);
  const loc = useLocation();
  const prefs = usePrefs();
  useEffect(() => setMore(false), [loc.pathname]);
  const tabs = prefs.phone_tabs.map((id) => NAV.find((n) => n.id === id)!).filter(Boolean);
  const rest = [...NAV.filter((n) => !prefs.phone_tabs.includes(n.id)), { id: "settings", to: "/settings", label: "Settings", icon: Settings, end: false }];
  const inMore = rest.some((n) => (n.to === "/" ? loc.pathname === "/" : loc.pathname.startsWith(n.to)));
  return (
    <>
      <nav
        aria-label="Main"
        className="fixed inset-x-0 bottom-0 z-40 border-t border-border bg-surface lg:hidden"
        style={{ paddingBottom: "var(--safe-bottom)" }}
      >
        <div className="mx-auto grid h-[56px] max-w-lg grid-cols-5">
          {tabs.map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              end={n.end}
              className={({ isActive }) =>
                cx(
                  "pressable flex flex-col items-center justify-center gap-0.5 text-[0.6875rem] font-medium",
                  isActive ? "text-ink" : "text-faint",
                )
              }
            >
              {({ isActive }) => (
                <>
                  <n.icon className="size-[22px]" strokeWidth={isActive ? 2.1 : 1.6} aria-hidden />
                  {n.label}
                </>
              )}
            </NavLink>
          ))}
          <button
            onClick={() => setMore(true)}
            className={cx(
              "pressable flex flex-col items-center justify-center gap-0.5 text-[0.6875rem] font-medium",
              inMore ? "text-ink" : "text-faint",
            )}
          >
            <MoreHorizontal className="size-[22px]" strokeWidth={inMore ? 2.1 : 1.6} aria-hidden />
            More
          </button>
        </div>
      </nav>
      <Dialog.Root open={more} onOpenChange={setMore}>
        <Dialog.Portal>
          <Dialog.Overlay className="sheet-overlay fixed inset-0 z-50 bg-black/30" />
          <Dialog.Content
            className="sheet-content fixed inset-x-0 bottom-0 z-50 rounded-t-[14px] bg-surface px-3 pt-2 outline-none"
            style={{ paddingBottom: "calc(var(--safe-bottom) + 12px)" }}
          >
            <div className="mx-auto mb-2 h-1 w-9 rounded-full bg-control" aria-hidden />
            <Dialog.Title className="sr-only">More</Dialog.Title>
            {rest.map((n) => (
              <NavLink
                key={n.to}
                to={n.to}
                end={n.end}
                className="pressable flex h-[52px] items-center gap-3 rounded-[10px] px-3 text-[1rem] active:bg-sunk"
              >
                <n.icon className="size-5 text-muted" strokeWidth={1.75} aria-hidden />
                {n.label}
              </NavLink>
            ))}
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </>
  );
}

/** ⌘K: jump to any screen, search or recent deal. */
function CommandPalette({ open, onOpenChange }: { open: boolean; onOpenChange: (v: boolean) => void }) {
  const nav = useNavigate();
  const [q, setQ] = useState("");
  const [idx, setIdx] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const searches = useSearches();
  const deals = useQuery({
    queryKey: ["deals", "palette", q],
    queryFn: () => get<Deal[]>(`/api/deals?limit=8&q=${encodeURIComponent(q)}`),
    enabled: open && q.trim().length >= 2,
    staleTime: 15_000,
  });
  useEffect(() => {
    if (open) {
      setQ("");
      setIdx(0);
    }
  }, [open]);

  const items = useMemo(() => {
    const t = q.trim().toLowerCase();
    type Item = { key: string; group: string; label: string; hint: string; icon: typeof Home; go: () => void };
    const out: Item[] = [];
    out.push({ key: "new", group: "Actions", label: "New search", hint: "Describe what you want", icon: Plus, go: () => nav("/searches/new") });
    out.push({ key: "setup", group: "Actions", label: "Setup guide", hint: "Sources and alerts", icon: Wrench, go: () => nav("/setup") });
    for (const s of searches.data || []) out.push({ key: s.id, group: "Your searches", label: s.title, hint: s.status === "active" ? "Active" : s.status === "paused" ? "Paused" : "Done", icon: Sparkles, go: () => nav(`/searches/${s.id}`) });
    for (const n of [...NAV, { to: "/settings", label: "Settings", icon: Settings }]) out.push({ key: n.to, group: "Go to", label: n.label, hint: "", icon: n.icon, go: () => nav(n.to) });
    // Without a query: actions, the first few searches, then the screens.
    const filtered = t
      ? out.filter((o) => o.label.toLowerCase().includes(t))
      : [...out.filter((o) => o.group === "Actions"), ...out.filter((o) => o.group === "Your searches").slice(0, 4), ...out.filter((o) => o.group === "Go to")];
    for (const d of deals.data || [])
      filtered.push({
        key: d.id,
        group: "Deals",
        label: d.listing.title,
        hint: `${money(d.effective_price, d.listing.currency)}${d.deal_score != null ? ` · ${d.deal_score}` : ""}`,
        icon: Tag,
        go: () => nav(`/deals/${d.id}`),
      });
    return filtered.slice(0, 16);
  }, [q, searches.data, deals.data, nav]);

  const listRef = useRef<HTMLUListElement>(null);
  useEffect(() => {
    listRef.current?.querySelector('[aria-selected="true"]')?.scrollIntoView({ block: "nearest" });
  }, [idx]);

  const run = (i: number) => {
    items[i]?.go();
    onOpenChange(false);
  };

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="sheet-overlay fixed inset-0 z-50 bg-black/25" />
        <Dialog.Content
          onOpenAutoFocus={(e) => {
            e.preventDefault();
            inputRef.current?.focus();
          }}
          className="palette fixed top-[max(12px,var(--safe-top))] left-1/2 z-50 flex max-h-[min(560px,80dvh)] w-[calc(100vw-24px)] max-w-[600px] -translate-x-1/2 flex-col overflow-hidden rounded-[14px] border border-border bg-surface shadow-[0_24px_70px_rgba(0,0,0,0.22)] outline-none sm:top-[12vh]"
        >
          <Dialog.Title className="sr-only">Search Schnäppli</Dialog.Title>
          <div className="flex shrink-0 items-center gap-3 border-b border-rule px-4">
            <SearchIcon className="size-[18px] text-muted" aria-hidden />
            <input
              ref={inputRef}
              value={q}
              onChange={(e) => {
                setQ(e.target.value);
                setIdx(0);
              }}
              onKeyDown={(e) => {
                if (e.key === "ArrowDown") {
                  e.preventDefault();
                  setIdx((i) => Math.min(items.length - 1, i + 1));
                } else if (e.key === "ArrowUp") {
                  e.preventDefault();
                  setIdx((i) => Math.max(0, i - 1));
                } else if (e.key === "Enter") {
                  e.preventDefault();
                  run(idx);
                }
              }}
              placeholder="Search screens, searches and deals"
              aria-label="Search"
              className="h-14 min-w-0 flex-1 bg-transparent text-[1rem] outline-none placeholder:text-faint"
            />
            <kbd className="hidden rounded border border-border px-1.5 py-0.5 text-[0.6875rem] text-muted sm:block">esc</kbd>
          </div>
          <ul ref={listRef} role="listbox" aria-label="Results" className="min-h-0 flex-1 overflow-y-auto p-2">
            {items.length === 0 && (
              <li className="px-3 py-8 text-center text-sm text-muted">
                {q.trim().length >= 2 && deals.isFetching ? "Searching deals…" : "Nothing found."}
              </li>
            )}
            {items.map((it, i) => (
              <li key={it.key} role="presentation">
                {(i === 0 || items[i - 1].group !== it.group) && (
                  <div className="px-3 pt-3 pb-1.5 text-[0.6875rem] font-medium tracking-wide text-faint uppercase first:pt-1">{it.group}</div>
                )}
                <div
                  role="option"
                  aria-selected={i === idx}
                  onMouseMove={() => i !== idx && setIdx(i)}
                  onClick={() => run(i)}
                  className={cx(
                    "flex cursor-pointer items-center gap-3 rounded-[10px] px-3 py-2 text-sm",
                    i === idx ? "bg-raised text-ink" : "text-ink-2",
                  )}
                >
                  <span className={cx("flex size-7 shrink-0 items-center justify-center rounded-[8px]", i === idx ? "bg-surface text-ink" : "bg-sunk text-muted")}>
                    <it.icon className="size-4" strokeWidth={1.75} aria-hidden />
                  </span>
                  <span className="min-w-0 flex-1 truncate">{it.label}</span>
                  {it.hint && <span className="num shrink-0 text-[0.75rem] text-muted">{it.hint}</span>}
                </div>
              </li>
            ))}
          </ul>
          <div className="hidden shrink-0 items-center gap-4 border-t border-rule px-4 py-2 text-[0.75rem] text-muted sm:flex">
            <span><kbd className="font-sans">↑↓</kbd> to move</span>
            <span><kbd className="font-sans">↵</kbd> to open</span>
            <span className="ml-auto">Type 2 letters to search your deals</span>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function PageFallback() {
  return (
    <div className="space-y-4 pt-2" aria-busy="true">
      <div className="skeleton h-7 w-48" />
      <div className="skeleton h-40 w-full" />
    </div>
  );
}

/** Opens the chosen start page once per app launch (only when launched at "/"). */
function useStartPage() {
  const prefs = usePrefs();
  const nav = useNavigate();
  const loc = useLocation();
  useEffect(() => {
    if (sessionStorage.getItem("schnaeppli.started")) return;
    sessionStorage.setItem("schnaeppli.started", "1");
    const target = NAV.find((n) => n.id === prefs.start_page);
    if (loc.pathname === "/" && target && target.to !== "/") nav(target.to, { replace: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
}

/** Load every page's code in the background after the first screen, so tapping a tab never waits. */
function usePreloadPages(loaders: (() => Promise<unknown>)[]) {
  useEffect(() => {
    const run = () => loaders.forEach((l) => l().catch(() => {}));
    const w = window as Window & { requestIdleCallback?: (cb: () => void) => number };
    if (w.requestIdleCallback) w.requestIdleCallback(run);
    else setTimeout(run, 1200);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
}

export function AppShell({ preload = [] }: { preload?: (() => Promise<unknown>)[] }) {
  const [palette, setPalette] = useState(false);
  const loc = useLocation();
  usePrefsEffect();
  useStartPage();
  usePreloadPages(preload);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPalette((v) => !v);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  useEffect(() => {
    window.scrollTo({ top: 0 });
  }, [loc.pathname]);
  return (
    <div className="flex min-h-dvh">
      <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-50 focus:rounded focus:bg-surface focus:px-3 focus:py-2">
        Skip to content
      </a>
      <Sidebar onSearch={() => setPalette(true)} />
      <div className="flex min-w-0 flex-1 flex-col">
        <MobileTopBar onSearch={() => setPalette(true)} />
        <main
          id="main"
          className="mx-auto w-full max-w-[1240px] flex-1 px-4 pt-2 sm:px-6 lg:px-10 lg:pt-8"
          style={{ paddingBottom: "calc(var(--safe-bottom) + 96px)" }}
        >
          <Suspense fallback={<PageFallback />}>
            <Outlet />
          </Suspense>
        </main>
      </div>
      <BottomNav />
      <CommandPalette open={palette} onOpenChange={setPalette} />
    </div>
  );
}

export function Centered({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-dvh items-center justify-center px-4" style={{ paddingTop: "var(--safe-top)", paddingBottom: "var(--safe-bottom)" }}>
      <div className="w-full max-w-[380px]">{children}</div>
    </div>
  );
}
