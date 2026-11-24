import { Check } from "lucide-react";
import { useState, type ReactNode } from "react";
import { Picker } from "@/components/Picker";
import { NAV } from "@/components/shell";
import { cx, Field, Segmented, SwitchRow } from "@/components/ui";
import { type HomeSection, type NavTab, type UIPrefs, useUpdatePrefs } from "@/lib/prefs";

const ACCENTS: { id: UIPrefs["accent"]; name: string; light: string; dark: string }[] = [
  { id: "cobalt", name: "Cobalt", light: "#1d5fbf", dark: "#6a9cea" },
  { id: "forest", name: "Forest", light: "#23784a", dark: "#5fc08a" },
  { id: "plum", name: "Plum", light: "#7a3fa6", dark: "#bb93e3" },
  { id: "ember", name: "Ember", light: "#bb3f0b", dark: "#f08c5e" },
  { id: "graphite", name: "Graphite", light: "#3b3b42", dark: "#d0d0d8" },
];

const SECTIONS: { id: HomeSection; name: string; text: string }[] = [
  { id: "stats", name: "Numbers", text: "Active searches, new today, good deals, AI spend" },
  { id: "best", name: "Best this week", text: "The highest-scoring listings" },
  { id: "drops", name: "Price drops", text: "Listings that got cheaper" },
  { id: "activity", name: "Search activity", text: "Recent runs and the AI budget" },
];

function Row({ title, description, children }: { title: string; description?: ReactNode; children: ReactNode }) {
  return (
    <section className="grid gap-3 border-t border-border py-7 first:border-t-0 first:pt-0 md:grid-cols-[minmax(0,320px)_1fr] md:gap-10">
      <div>
        <h2 className="text-[0.9375rem] font-semibold">{title}</h2>
        {description && <div className="mt-1 text-[0.8125rem] leading-relaxed text-muted">{description}</div>}
      </div>
      <div className="min-w-0 rounded-[12px] bg-surface p-4 sm:p-5">{children}</div>
    </section>
  );
}

export default function Appearance() {
  const { prefs, set } = useUpdatePrefs();
  const dark = document.documentElement.dataset.theme === "dark";

  // The bar needs exactly four tabs, so a swap is a local draft until four are chosen.
  const [tabs, setTabs] = useState<NavTab[]>(prefs.phone_tabs);
  const toggleTab = (id: NavTab) => {
    let next: NavTab[];
    if (tabs.includes(id)) next = tabs.filter((t) => t !== id);
    else if (tabs.length >= 4) return;
    // Same order as the menu, so the bar never feels shuffled.
    else next = NAV.map((n) => n.id).filter((t) => t === id || tabs.includes(t));
    setTabs(next);
    if (next.length === 4) set({ phone_tabs: next });
  };
  const tabsIncomplete = tabs.length !== 4;

  return (
    <>
      <Row title="Look" description="Changes apply right away, on this device and the others you sign in on.">
        <div className="flex flex-col gap-5">
          <Field label="Theme">
            <Segmented label="Theme" value={prefs.theme} onChange={(theme) => set({ theme })}
              options={[{ value: "system", label: "Like the device" }, { value: "light", label: "Light" }, { value: "dark", label: "Dark" }]} />
          </Field>
          <Field label="Accent" hint="Used for the Deal Score, the price ruler and the logo. Everything else stays neutral.">
            <div role="radiogroup" aria-label="Accent" className="flex flex-wrap gap-2">
              {ACCENTS.map((a) => {
                const on = prefs.accent === a.id;
                return (
                  <button key={a.id} type="button" role="radio" aria-checked={on} onClick={() => set({ accent: a.id })}
                    className={cx("pressable flex h-10 items-center gap-2 rounded-full border pr-3.5 pl-1.5 text-sm", on ? "border-ink" : "border-border hover:border-control")}>
                    <span className="flex size-7 items-center justify-center rounded-full" style={{ background: dark ? a.dark : a.light }}>
                      {on && <Check className="size-4" strokeWidth={2.5} style={{ color: dark ? "#121211" : "#fff" }} aria-hidden />}
                    </span>
                    {a.name}
                  </button>
                );
              })}
            </div>
          </Field>
        </div>
      </Row>

      <Row title="Reading" description="Larger text scales the whole interface. Compact fits more on the screen.">
        <div className="flex flex-col gap-5">
          <Field label="Text size">
            <Segmented label="Text size" value={prefs.text_size} onChange={(text_size) => set({ text_size })}
              options={[{ value: "default", label: "Default" }, { value: "large", label: "Larger" }]} />
          </Field>
          <Field label="Spacing">
            <Segmented label="Spacing" value={prefs.density} onChange={(density) => set({ density })}
              options={[{ value: "comfortable", label: "Comfortable" }, { value: "compact", label: "Compact" }]} />
          </Field>
          <div className="-my-3">
            <SwitchRow title="Reduce motion" description="No sliding sheets or press animations. Your device's own setting is always respected too."
              checked={prefs.reduce_motion} onChange={(reduce_motion) => set({ reduce_motion })} />
          </div>
        </div>
      </Row>

      <Row title="Deals" description="How listings are shown in the deal list and on Home.">
        <div className="flex flex-col gap-5">
          <Field label="Deal list">
            <Segmented label="Deal list" value={prefs.deal_layout} onChange={(deal_layout) => set({ deal_layout })}
              options={[{ value: "cards", label: "Photo cards" }, { value: "rows", label: "Compact rows" }]} />
          </Field>
          <div className="-my-3">
            <SwitchRow title="Show photos" description="Turn off for a text-only list that loads faster on mobile data."
              checked={prefs.show_photos} onChange={(show_photos) => set({ show_photos })} />
          </div>
        </div>
      </Row>

      <Row title="Home" description="Choose what Home shows and which screen opens when you start the app.">
        <div className="flex flex-col gap-5">
          <Field label="Open the app on">
            <div className="sm:max-w-[260px]">
              <Picker label="Open the app on" value={prefs.start_page} onChange={(start_page) => set({ start_page })}
                options={NAV.map((n) => ({ value: n.id, label: n.label }))} />
            </div>
          </Field>
          <div>
            <p className="text-sm font-medium">Sections on Home</p>
            <div className="divide-y divide-rule">
              {SECTIONS.map((s) => (
                <SwitchRow key={s.id} title={s.name} description={s.text} checked={prefs.home_sections.includes(s.id)}
                  onChange={(on) => set({ home_sections: on ? SECTIONS.map((x) => x.id).filter((x) => x === s.id || prefs.home_sections.includes(x)) : prefs.home_sections.filter((x) => x !== s.id) })} />
              ))}
            </div>
          </div>
        </div>
      </Row>

      <Row title="Phone tab bar" description="Pick the four screens in the bar at the bottom of your phone. Everything else stays under More.">
        <ul className="grid grid-cols-2 gap-2 sm:grid-cols-3" aria-describedby="tabs-count">
          {NAV.map((n) => {
            const on = tabs.includes(n.id);
            const full = !on && tabs.length >= 4;
            return (
              <li key={n.id}>
                <button type="button" aria-pressed={on} disabled={full} onClick={() => toggleTab(n.id)}
                  className={cx("pressable flex h-12 w-full items-center gap-2.5 rounded-[10px] border px-3 text-left text-sm disabled:opacity-40",
                    on ? "border-ink bg-sunk font-medium" : "border-border")}>
                  <n.icon className="size-[1.125rem] shrink-0" strokeWidth={on ? 2.1 : 1.7} aria-hidden />
                  <span className="flex-1 truncate">{n.label}</span>
                  {on && <span className="num text-[0.75rem] text-muted">{tabs.indexOf(n.id) + 1}</span>}
                </button>
              </li>
            );
          })}
        </ul>
        <p id="tabs-count" className={cx("mt-3 text-[0.8125rem]", tabsIncomplete ? "text-warning" : "text-muted")} role="status">
          {tabsIncomplete ? `${tabs.length} of 4 chosen. Pick ${4 - tabs.length} more to save.` : "4 of 4 chosen. Tap one to swap it out."}
        </p>
      </Row>
    </>
  );
}
