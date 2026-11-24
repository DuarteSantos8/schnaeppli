import * as Dialog from "@radix-ui/react-dialog";
import * as Popover from "@radix-ui/react-popover";
import { Check, ChevronsUpDown, Search } from "lucide-react";
import { useEffect, useId, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { cx } from "./ui";

export interface PickerOption<T extends string = string> {
  value: T;
  label: string;
  hint?: string;
}

/** Below 640px the list opens as a bottom sheet with large rows; above, as a popover. */
function useWide() {
  const q = "(min-width: 640px)";
  const [wide, setWide] = useState(() => typeof window !== "undefined" && window.matchMedia(q).matches);
  useEffect(() => {
    const mq = window.matchMedia(q);
    const on = () => setWide(mq.matches);
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, []);
  return wide;
}

/**
 * A select that looks and behaves the same everywhere, instead of the platform's
 * wheel. Long lists (timezones, models) get a filter field.
 */
export function Picker<T extends string>({
  value,
  onChange,
  options,
  label,
  id,
  placeholder = "Choose…",
  size = "md",
  className,
  disabled,
  searchable,
}: {
  value: T | "" | null | undefined;
  onChange: (v: T) => void;
  options: PickerOption<T>[];
  /** Accessible name; also the sheet title on the phone. */
  label: string;
  id?: string;
  placeholder?: string;
  size?: "sm" | "md";
  className?: string;
  disabled?: boolean;
  searchable?: boolean;
}) {
  const wide = useWide();
  const [open, setOpen] = useState(false);
  const selected = options.find((o) => o.value === value);
  const trigger = (
    <button
      type="button"
      id={id}
      disabled={disabled}
      aria-haspopup="listbox"
      aria-expanded={open}
      aria-label={selected ? `${label}: ${selected.label}` : label}
      onClick={() => setOpen(true)}
      className={cx(
        "pressable flex w-full min-w-0 items-center justify-between gap-2 rounded-[var(--radius-control)] border border-control bg-surface text-left text-ink outline-none hover:border-faint focus-visible:border-ink disabled:bg-sunk disabled:text-faint",
        size === "sm" ? "h-8 px-2.5 text-[0.8125rem]" : "h-10 px-3 text-sm",
        className,
      )}
    >
      <span className={cx("truncate", !selected && "text-faint")}>{selected ? selected.label : placeholder}</span>
      <ChevronsUpDown className="size-3.5 shrink-0 text-muted" aria-hidden />
    </button>
  );
  const list = (
    <OptionList
      options={options}
      value={value}
      label={label}
      searchable={searchable ?? options.length > 12}
      large={!wide}
      onPick={(v) => {
        onChange(v);
        setOpen(false);
      }}
    />
  );

  if (wide)
    return (
      <Popover.Root open={open} onOpenChange={setOpen}>
        <Popover.Trigger asChild>{trigger}</Popover.Trigger>
        <Popover.Portal>
          <Popover.Content
            align="start"
            sideOffset={4}
            collisionPadding={12}
            className="menu-content z-50 w-[var(--radix-popover-trigger-width)] min-w-[220px] overflow-hidden rounded-[8px] border border-border bg-surface shadow-[0_10px_30px_rgba(0,0,0,0.14)] outline-none"
            style={{ transformOrigin: "var(--radix-popover-content-transform-origin)" }}
          >
            {list}
          </Popover.Content>
        </Popover.Portal>
      </Popover.Root>
    );

  return (
    <>
      {trigger}
      <Dialog.Root open={open} onOpenChange={setOpen}>
        <Dialog.Portal>
          <Dialog.Overlay className="sheet-overlay fixed inset-0 z-50 bg-black/30" />
          <Dialog.Content
            className="sheet-content fixed inset-x-0 bottom-0 z-50 flex max-h-[80dvh] flex-col rounded-t-[14px] bg-surface outline-none"
            style={{ paddingBottom: "var(--safe-bottom)" }}
            onOpenAutoFocus={(e) => e.preventDefault()}
          >
            <div className="mx-auto mt-2 h-1 w-9 shrink-0 rounded-full bg-control" aria-hidden />
            <Dialog.Title className="px-5 pt-3 pb-1 text-[1.0625rem] font-semibold tracking-[-0.01em]">{label}</Dialog.Title>
            <Dialog.Description className="sr-only">Choose one option</Dialog.Description>
            {list}
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </>
  );
}

function OptionList<T extends string>({
  options,
  value,
  label,
  searchable,
  large,
  onPick,
}: {
  options: PickerOption<T>[];
  value: T | "" | null | undefined;
  label: string;
  searchable: boolean;
  large: boolean;
  onPick: (v: T) => void;
}) {
  const [q, setQ] = useState("");
  const shown = useMemo(() => {
    const t = q.trim().toLowerCase();
    return t ? options.filter((o) => `${o.label} ${o.hint || ""}`.toLowerCase().includes(t)) : options;
  }, [q, options]);
  const [active, setActive] = useState(() => Math.max(0, options.findIndex((o) => o.value === value)));
  const listRef = useRef<HTMLUListElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const listId = useId();

  useEffect(() => {
    // Desktop: keyboard focus goes to the filter or the list. Phone: no keyboard pops up.
    if (large) {
      listRef.current?.querySelector<HTMLElement>('[aria-selected="true"]')?.scrollIntoView({ block: "center" });
      return;
    }
    if (searchable) inputRef.current?.focus();
    else listRef.current?.focus();
    listRef.current?.querySelector<HTMLElement>('[aria-selected="true"]')?.scrollIntoView({ block: "nearest" });
  }, [large, searchable]);

  useEffect(() => {
    listRef.current?.querySelector<HTMLElement>(`[data-i="${active}"]`)?.scrollIntoView({ block: "nearest" });
  }, [active]);

  const typeahead = useRef({ text: "", at: 0 });
  const onKey = (e: KeyboardEvent) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((i) => Math.min(shown.length - 1, i + 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((i) => Math.max(0, i - 1));
    } else if (e.key === "Home") {
      e.preventDefault();
      setActive(0);
    } else if (e.key === "End") {
      e.preventDefault();
      setActive(shown.length - 1);
    } else if (e.key === "Enter" || (e.key === " " && !searchable)) {
      e.preventDefault();
      const o = shown[active];
      if (o) onPick(o.value);
    } else if (!searchable && e.key.length === 1) {
      const now = Date.now();
      const t = typeahead.current;
      t.text = now - t.at > 700 ? e.key.toLowerCase() : t.text + e.key.toLowerCase();
      t.at = now;
      const i = shown.findIndex((o) => o.label.toLowerCase().startsWith(t.text));
      if (i >= 0) setActive(i);
    }
  };

  return (
    <div className="flex min-h-0 flex-col" onKeyDown={onKey}>
      {searchable && (
        <div className={cx("flex items-center gap-2 border-b border-rule", large ? "mx-5 mb-1 px-0" : "px-3")}>
          <Search className="size-4 shrink-0 text-muted" aria-hidden />
          <input
            ref={inputRef}
            value={q}
            onChange={(e) => {
              setQ(e.target.value);
              setActive(0);
            }}
            placeholder="Filter"
            aria-label={`Filter ${label}`}
            aria-controls={listId}
            aria-activedescendant={shown[active] ? `${listId}-${active}` : undefined}
            autoComplete="off"
            autoCorrect="off"
            autoCapitalize="none"
            spellCheck={false}
            enterKeyHint="done"
            className="h-11 min-w-0 flex-1 bg-transparent outline-none placeholder:text-faint"
          />
        </div>
      )}
      <ul
        ref={listRef}
        id={listId}
        role="listbox"
        aria-label={label}
        tabIndex={searchable ? -1 : 0}
        aria-activedescendant={!searchable && shown[active] ? `${listId}-${active}` : undefined}
        className={cx("min-h-0 overflow-y-auto overscroll-contain outline-none", large ? "flex-1 px-2 pb-3" : "max-h-[320px] p-1")}
      >
        {shown.length === 0 && <li className="px-3 py-4 text-sm text-muted">No match.</li>}
        {shown.map((o, i) => {
          const sel = o.value === value;
          return (
            <li
              key={o.value}
              id={`${listId}-${i}`}
              data-i={i}
              role="option"
              aria-selected={sel}
              onPointerMove={() => !large && setActive(i)}
              onClick={() => onPick(o.value)}
              className={cx(
                "flex cursor-pointer items-center gap-3 rounded-[7px] select-none",
                large ? "min-h-[50px] px-3 text-[1rem] active:bg-sunk" : "min-h-9 px-2.5 text-sm",
                !large && i === active && "bg-sunk",
              )}
            >
              <span className="min-w-0 flex-1">
                <span className={cx("block truncate", sel && "font-medium")}>{o.label}</span>
                {o.hint && <span className="block truncate text-[0.75rem] text-muted">{o.hint}</span>}
              </span>
              <Check className={cx("size-4 shrink-0 text-score", !sel && "invisible")} aria-hidden />
            </li>
          );
        })}
      </ul>
    </div>
  );
}
