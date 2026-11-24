import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { patch } from "./api";
import { useAuth } from "./auth";
import type { User } from "./types";

export type NavTab = "home" | "deals" | "searches" | "wishlist" | "assistant" | "budget" | "usage";
export type HomeSection = "stats" | "best" | "drops" | "activity";

export interface UIPrefs {
  theme: "system" | "light" | "dark";
  accent: "cobalt" | "forest" | "plum" | "ember" | "graphite";
  density: "comfortable" | "compact";
  text_size: "default" | "large";
  start_page: NavTab;
  deal_layout: "cards" | "rows";
  phone_tabs: NavTab[];
  show_photos: boolean;
  reduce_motion: boolean;
  home_sections: HomeSection[];
}

export const DEFAULT_PREFS: UIPrefs = {
  theme: "system",
  accent: "cobalt",
  density: "comfortable",
  text_size: "default",
  start_page: "home",
  deal_layout: "cards",
  phone_tabs: ["home", "deals", "searches", "assistant"],
  show_photos: true,
  reduce_motion: false,
  home_sections: ["stats", "best", "drops", "activity"],
};

const KEY = "schnaeppli.ui";
const dark = () => window.matchMedia("(prefers-color-scheme: dark)");

/** Write the choices onto <html> (the CSS reads data attributes) and remember them for boot.js. */
export function applyPrefs(p: UIPrefs) {
  const r = document.documentElement;
  const isDark = p.theme === "dark" || (p.theme === "system" && dark().matches);
  r.dataset.theme = isDark ? "dark" : "light";
  r.dataset.accent = p.accent;
  r.dataset.density = p.density;
  r.dataset.text = p.text_size;
  if (p.reduce_motion) r.dataset.motion = "reduce";
  else delete r.dataset.motion;
  document.querySelector('meta[name="theme-color"]')?.setAttribute("content", isDark ? "#121211" : "#f4f3f1");
  try {
    localStorage.setItem(KEY, JSON.stringify(p));
  } catch {
    /* private mode: fine, the server copy still applies after load */
  }
}

export function usePrefs(): UIPrefs {
  const { user } = useAuth();
  return { ...DEFAULT_PREFS, ...(user?.ui_prefs || {}) };
}

/** Keeps <html> in sync with the signed-in user's prefs and the system theme. */
export function usePrefsEffect() {
  const p = usePrefs();
  const key = JSON.stringify(p);
  useEffect(() => {
    applyPrefs(p);
    if (p.theme !== "system") return;
    const mq = dark();
    const on = () => applyPrefs(p);
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
}

/** Saves a change: on screen at once, then on the server; rolls back if the server refuses. */
export function useUpdatePrefs() {
  const qc = useQueryClient();
  const prefs = usePrefs();
  const save = useMutation({
    mutationFn: (next: UIPrefs) => patch<User>("/api/me", { ui_prefs: next }),
    onMutate: (next: UIPrefs) => {
      const prev = qc.getQueryData<User>(["me"]);
      if (prev) qc.setQueryData(["me"], { ...prev, ui_prefs: next });
      applyPrefs(next);
      return { prev };
    },
    onError: (_e, _n, ctx) => {
      if (ctx?.prev) {
        qc.setQueryData(["me"], ctx.prev);
        applyPrefs({ ...DEFAULT_PREFS, ...(ctx.prev.ui_prefs || {}) });
      }
    },
    onSuccess: (u) => qc.setQueryData(["me"], u),
  });
  return { prefs, set: (change: Partial<UIPrefs>) => save.mutate({ ...prefs, ...change }), saving: save.isPending, error: save.error };
}
