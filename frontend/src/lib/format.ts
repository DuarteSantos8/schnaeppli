import type { Label } from "./types";

const apostrophe = "’"; // Swiss thousands separator

export function money(v: number | null | undefined, currency = "CHF", opts: { cents?: boolean } = {}): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  const cents = opts.cents ?? !Number.isInteger(v);
  const s = v.toLocaleString("de-CH", {
    minimumFractionDigits: cents ? 2 : 0,
    maximumFractionDigits: cents ? 2 : 0,
  });
  return `${currency} ${s.replace(/[’']/g, apostrophe)}`;
}

export function usd(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined) return "—";
  if (v > 0 && v < 0.01) return "<$0.01";
  return `$${v.toFixed(digits)}`;
}

export function tokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(n >= 10_000_000 ? 0 : 1)}M`;
  if (n >= 10_000) return `${Math.round(n / 1000)}k`;
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
  return String(n);
}

export function relTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso).getTime();
  const diff = (Date.now() - d) / 1000;
  const future = diff < 0;
  const s = Math.abs(diff);
  const fmt = (n: number, u: string) => (future ? `in ${n} ${u}` : `${n} ${u} ago`);
  if (s < 60) return future ? "in a moment" : "just now";
  if (s < 3600) return fmt(Math.round(s / 60), "min");
  if (s < 86400) return fmt(Math.round(s / 3600), "h");
  if (s < 86400 * 7) return fmt(Math.round(s / 86400), Math.round(s / 86400) === 1 ? "day" : "days");
  return new Date(iso).toLocaleDateString("en-CH", { day: "numeric", month: "short" });
}

export function clock(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleTimeString("en-CH", { hour: "2-digit", minute: "2-digit" });
}

export function dayTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  const today = new Date();
  const tomorrow = new Date(Date.now() + 86400000);
  const t = clock(iso);
  if (d.toDateString() === today.toDateString()) return `today ${t}`;
  if (d.toDateString() === tomorrow.toDateString()) return `tomorrow ${t}`;
  return `${d.toLocaleDateString("en-CH", { weekday: "short", day: "numeric", month: "short" })} ${t}`;
}

export const LABEL_TEXT: Record<Label, string> = {
  exceptional: "Exceptional deal",
  good: "Good deal",
  fair: "Fair price",
  overpriced: "Overpriced",
  risky: "Risky",
};

export const LABEL_SHORT: Record<Label, string> = {
  exceptional: "Exceptional",
  good: "Good",
  fair: "Fair",
  overpriced: "Overpriced",
  risky: "Risky",
};

export const SOURCE_NAME: Record<string, string> = {
  ebay: "eBay",
  ricardo: "Ricardo",
  tutti: "tutti.ch",
  digitec: "Digitec",
  galaxus: "Galaxus",
  interdiscount: "Interdiscount",
  toppreise: "Toppreise",
  amazon: "Amazon",
  brack: "Brack",
  anibis: "anibis",
  web: "Web",
};

export const CONDITION_TEXT: Record<string, string> = {
  new: "New",
  like_new: "Like new",
  good: "Good",
  fair: "Fair",
  poor: "Poor",
  defective: "Defective",
  refurbished: "Refurbished",
  used: "Used",
  for_parts: "For parts",
  unknown: "Unknown",
};

export function plural(n: number, one: string, many = one + "s"): string {
  return `${n} ${n === 1 ? one : many}`;
}
