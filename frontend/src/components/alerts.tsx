import { Check, ExternalLink } from "lucide-react";
import { useState } from "react";

const linkCls =
  "pressable inline-flex h-8 items-center gap-1.5 rounded-[var(--radius-control)] px-3 text-[0.8125rem] font-medium";

const SITES = [
  { id: "ricardo", name: "Ricardo", url: (t: string) => `https://www.ricardo.ch/de/s/${encodeURIComponent(t)}` },
  { id: "tutti", name: "tutti", url: (t: string) => `https://www.tutti.ch/de/q/suche?query=${encodeURIComponent(t)}` },
  { id: "facebook", name: "Facebook", url: (t: string) => `https://www.facebook.com/marketplace/search/?query=${encodeURIComponent(t)}` },
  { id: "toppreise", name: "Toppreise", url: (t: string) => `https://www.toppreise.ch/produktsuche?q=${encodeURIComponent(t)}` },
];

const KEY = "schnaeppli.alerts-opened";

function load(): Set<string> {
  try {
    return new Set(JSON.parse(localStorage.getItem(KEY) || "[]"));
  } catch {
    return new Set();
  }
}

/**
 * Opens the same search on each site, where the user saves it once to get alert mails.
 * Remembers on this device which ones were opened, so it's clear what's left.
 */
export function AlertButtons({ term }: { term: string }) {
  const [opened, setOpened] = useState(load);
  const mark = (id: string) => {
    const next = load();
    next.add(`${id}:${term.toLowerCase()}`);
    localStorage.setItem(KEY, JSON.stringify([...next].slice(-400)));
    setOpened(next);
  };
  return (
    <span className="flex flex-wrap gap-2">
      {SITES.map((s) => {
        const done = opened.has(`${s.id}:${term.toLowerCase()}`);
        return (
          <a
            key={s.id}
            className={`${linkCls} ${done ? "bg-pos-bg text-pos-ink" : "bg-raised hover:bg-raised-hover"}`}
            href={s.url(term)}
            target="_blank"
            rel="noreferrer noopener"
            onClick={() => mark(s.id)}
            title={done ? `Opened. Saved the search on ${s.name}?` : `Open “${term}” on ${s.name}`}
          >
            {s.name}
            {done ? <Check className="size-3.5" strokeWidth={2.5} aria-label="opened" /> : <ExternalLink className="size-3.5" aria-hidden />}
          </a>
        );
      })}
    </span>
  );
}
