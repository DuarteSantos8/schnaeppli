import { ExternalLink } from "lucide-react";

const linkCls =
  "pressable inline-flex h-8 items-center gap-1.5 rounded-[var(--radius-control)] bg-raised px-3 text-[0.8125rem] font-medium hover:bg-raised-hover";

/** Opens the same search on Ricardo and tutti, where the user saves it once to get alert mails. */
export function AlertButtons({ term }: { term: string }) {
  return (
    <span className="flex flex-wrap gap-2">
      <a className={linkCls} href={`https://www.ricardo.ch/de/s/${encodeURIComponent(term)}`} target="_blank" rel="noreferrer noopener">
        Ricardo <ExternalLink className="size-3.5" aria-hidden />
      </a>
      <a className={linkCls} href={`https://www.tutti.ch/de/q/suche?query=${encodeURIComponent(term)}`} target="_blank" rel="noreferrer noopener">
        tutti <ExternalLink className="size-3.5" aria-hidden />
      </a>
      <a className={linkCls} href={`https://www.facebook.com/marketplace/search/?query=${encodeURIComponent(term)}`} target="_blank" rel="noreferrer noopener">
        Facebook <ExternalLink className="size-3.5" aria-hidden />
      </a>
      <a className={linkCls} href={`https://www.toppreise.ch/produktsuche?q=${encodeURIComponent(term)}`} target="_blank" rel="noreferrer noopener">
        Toppreise <ExternalLink className="size-3.5" aria-hidden />
      </a>
    </span>
  );
}
