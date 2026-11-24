import * as Dialog from "@radix-ui/react-dialog";
import { Loader2, X, AlertTriangle } from "lucide-react";
import {
  createContext,
  forwardRef,
  useCallback,
  useContext,
  useState,
  type ButtonHTMLAttributes,
  type InputHTMLAttributes,
  type ReactNode,
  type TextareaHTMLAttributes,
} from "react";

export function cx(...c: (string | false | null | undefined)[]) {
  return c.filter(Boolean).join(" ");
}

/* ------------------------------------------------------------------ Button */
type Variant = "primary" | "secondary" | "ghost" | "danger";
const VARIANT: Record<Variant, string> = {
  primary: "bg-primary text-on-ink hover:bg-primary-hover disabled:opacity-45",
  secondary: "bg-raised text-ink hover:bg-raised-hover disabled:text-faint",
  ghost: "bg-transparent text-ink hover:bg-sunk disabled:text-faint",
  danger: "bg-transparent text-negative hover:bg-neg-bg disabled:text-faint",
};

export const Button = forwardRef<
  HTMLButtonElement,
  ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: "sm" | "md" | "lg"; loading?: boolean; icon?: ReactNode }
>(function Button({ variant = "secondary", size = "md", loading, icon, className, children, disabled, ...rest }, ref) {
  const sizes = { sm: "h-8 px-3 text-[0.8125rem] gap-1.5", md: "h-9 px-3.5 text-sm gap-2", lg: "h-11 px-5 text-[0.9375rem] gap-2" };
  return (
    <button
      ref={ref}
      disabled={disabled || loading}
      className={cx(
        "pressable inline-flex items-center justify-center rounded-[var(--radius-control)] font-medium whitespace-nowrap select-none disabled:cursor-not-allowed",
        sizes[size],
        VARIANT[variant],
        className,
      )}
      {...rest}
    >
      {loading ? <Loader2 className="size-4 animate-spin" aria-hidden /> : icon}
      {children}
    </button>
  );
});

export function IconButton({
  label,
  children,
  className,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { label: string }) {
  return (
    <button
      aria-label={label}
      title={label}
      className={cx(
        "pressable inline-flex size-9 items-center justify-center rounded-[var(--radius-control)] text-muted hover:bg-sunk hover:text-ink",
        className,
      )}
      {...rest}
    >
      {children}
    </button>
  );
}

/* ------------------------------------------------------------------ Fields */
export function Field({
  label,
  hint,
  error,
  children,
  htmlFor,
}: {
  label: string;
  hint?: ReactNode;
  error?: string | null;
  children: ReactNode;
  htmlFor?: string;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={htmlFor} className="text-sm font-medium text-ink">
        {label}
      </label>
      {children}
      {error ? (
        <p className="text-[0.8125rem] text-negative" role="alert">
          {error}
        </p>
      ) : hint ? (
        <p className="text-[0.8125rem] text-muted">{hint}</p>
      ) : null}
    </div>
  );
}

const fieldCls =
  "w-full rounded-[var(--radius-control)] border border-control bg-surface px-3 text-sm text-ink placeholder:text-faint outline-none transition-colors focus:border-ink focus-visible:outline-none disabled:bg-sunk";

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(function Input(
  { className, ...rest },
  ref,
) {
  return <input ref={ref} autoComplete="off" autoCorrect="off" spellCheck={false} className={cx(fieldCls, "h-10", className)} {...rest} />;
});

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement>>(function Textarea(
  { className, ...rest },
  ref,
) {
  return <textarea ref={ref} className={cx(fieldCls, "py-2.5 leading-relaxed resize-none", className)} {...rest} />;
});

/* ------------------------------------------------------------------ Switch */
export function Switch({
  checked,
  onChange,
  label,
  disabled,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label: string;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={cx(
        "relative inline-flex h-[22px] w-[38px] shrink-0 items-center rounded-full transition-colors duration-200 disabled:opacity-50",
        checked ? "bg-switch-on" : "bg-control",
      )}
    >
      <span
        className="absolute left-[3px] size-4 rounded-full bg-knob shadow-[0_1px_2px_rgba(0,0,0,0.2)] transition-transform duration-200"
        style={{ transform: checked ? "translateX(16px)" : "none", transitionTimingFunction: "var(--ease-out)" }}
      />
    </button>
  );
}

export function SwitchRow({
  title,
  description,
  checked,
  onChange,
  disabled,
}: {
  title: string;
  description?: ReactNode;
  checked: boolean;
  onChange: (v: boolean) => void;
  disabled?: boolean;
}) {
  return (
    <div className="flex items-start justify-between gap-4 py-3">
      <div className="min-w-0">
        <div className="text-sm font-medium">{title}</div>
        {description && <div className="mt-0.5 text-[0.8125rem] text-muted">{description}</div>}
      </div>
      <div className="pt-0.5">
        <Switch checked={checked} onChange={onChange} label={title} disabled={disabled} />
      </div>
    </div>
  );
}

/* ------------------------------------------------------------- Segmented */
export function Segmented<T extends string>({
  value,
  onChange,
  options,
  label,
  size = "md",
}: {
  value: T;
  onChange: (v: T) => void;
  options: { value: T; label: string }[];
  label: string;
  size?: "sm" | "md";
}) {
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex rounded-[var(--radius-control)] bg-raised p-0.5">
      {options.map((o) => (
        <button
          key={o.value}
          role="radio"
          aria-checked={value === o.value}
          onClick={() => onChange(o.value)}
          className={cx(
            "pressable rounded-[5px] px-3 font-medium whitespace-nowrap",
            size === "sm" ? "h-7 text-[0.8125rem]" : "h-8 text-sm",
            value === o.value ? "bg-surface text-ink shadow-[0_1px_2px_rgba(0,0,0,0.06)]" : "text-muted hover:text-ink",
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

/* ------------------------------------------------------------------- Chips */
export function Chip({
  active,
  children,
  onClick,
  count,
}: {
  active?: boolean;
  children: ReactNode;
  onClick?: () => void;
  count?: number;
}) {
  return (
    <button
      onClick={onClick}
      aria-pressed={active}
      className={cx(
        "pressable inline-flex h-8 shrink-0 items-center gap-1.5 rounded-full border px-3 text-[0.8125rem] font-medium whitespace-nowrap",
        active ? "border-ink bg-ink text-on-ink" : "border-border bg-surface text-ink hover:border-control",
      )}
    >
      {children}
      {count !== undefined && <span className={cx("num", active ? "text-on-ink/70" : "text-faint")}>{count}</span>}
    </button>
  );
}

type Tone = "neutral" | "positive" | "negative" | "warning" | "score";
const TONE: Record<Tone, string> = {
  neutral: "bg-raised text-ink-2",
  positive: "bg-pos-bg text-pos-ink",
  negative: "bg-neg-bg text-neg-ink",
  warning: "bg-warn-bg text-warn-ink",
  score: "bg-score-soft text-score",
};
export function Pill({ tone = "neutral", children, className }: { tone?: Tone; children: ReactNode; className?: string }) {
  return (
    <span
      className={cx(
        "inline-flex h-[22px] items-center gap-1 rounded-full px-2 text-[0.75rem] font-medium whitespace-nowrap",
        TONE[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}

/* ------------------------------------------------------------ Containers */
export function Panel({ children, className, as: As = "section" }: { children: ReactNode; className?: string; as?: any }) {
  return <As className={cx("rounded-[var(--radius-card)] border border-border bg-surface", className)}>{children}</As>;
}

export function PanelHeader({ title, action, sub }: { title: ReactNode; action?: ReactNode; sub?: ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3 px-4 pt-4 pb-3 sm:px-5">
      <div className="min-w-0">
        <h2 className="text-[0.9375rem] font-semibold tracking-[-0.01em]">{title}</h2>
        {sub && <p className="mt-0.5 text-[0.8125rem] text-muted">{sub}</p>}
      </div>
      {action}
    </div>
  );
}

export function PageHeader({
  title,
  sub,
  actions,
}: {
  title: ReactNode;
  sub?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <header className="mb-5 flex flex-wrap items-end justify-between gap-x-4 gap-y-3 sm:mb-6">
      <div className="min-w-0">
        <h1 className="text-[1.375rem] font-semibold tracking-[-0.02em] sm:text-[1.5rem]">{title}</h1>
        {sub && <p className="mt-1 text-sm text-muted">{sub}</p>}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </header>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cx("skeleton", className)} aria-hidden />;
}

export function Empty({
  title,
  children,
  action,
  className,
}: {
  title: string;
  children?: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cx("flex flex-col items-start gap-2 px-4 py-8 sm:px-5", className)}>
      <p className="text-[0.9375rem] font-medium">{title}</p>
      {children && <div className="max-w-prose text-sm text-muted">{children}</div>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}

export function ErrorBox({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const msg = error instanceof Error ? error.message : "Something went wrong.";
  return (
    <div role="alert" className="flex items-start gap-3 rounded-[var(--radius-card)] bg-neg-bg px-4 py-3 text-sm text-neg-ink">
      <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden />
      <div className="flex-1">{msg}</div>
      {onRetry && (
        <button className="font-medium underline underline-offset-2" onClick={onRetry}>
          Try again
        </button>
      )}
    </div>
  );
}

export function Notice({ tone = "neutral", children, action }: { tone?: Tone; children: ReactNode; action?: ReactNode }) {
  return (
    <div className={cx("flex flex-wrap items-center gap-x-4 gap-y-2 rounded-[var(--radius-card)] px-4 py-3 text-sm", TONE[tone])}>
      <div className="min-w-0 flex-1">{children}</div>
      {action}
    </div>
  );
}

/* ----------------------------------------------------------------- Sheet */
/** A dialog on desktop, a bottom sheet on the phone. */
export function Sheet({
  open,
  onOpenChange,
  title,
  description,
  children,
  footer,
  wide,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  title: string;
  description?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  wide?: boolean;
}) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="sheet-overlay fixed inset-0 z-50 bg-black/30" />
        <Dialog.Content
          className={cx(
            "sheet-content fixed z-50 flex max-h-[92dvh] flex-col bg-surface outline-none",
            "inset-x-0 bottom-0 rounded-t-[14px] pb-[var(--safe-bottom)]",
            "sm:inset-auto sm:top-1/2 sm:left-1/2 sm:w-[calc(100vw-48px)] sm:-translate-x-1/2 sm:-translate-y-1/2 sm:rounded-[10px] sm:pb-0 sm:shadow-[0_20px_60px_rgba(0,0,0,0.18)]",
            wide ? "sm:max-w-[720px]" : "sm:max-w-[480px]",
          )}
        >
          <div className="mx-auto mt-2 h-1 w-9 rounded-full bg-control sm:hidden" aria-hidden />
          <div className="flex items-start justify-between gap-4 px-5 pt-4 pb-2">
            <div>
              <Dialog.Title className="text-[1.0625rem] font-semibold tracking-[-0.01em]">{title}</Dialog.Title>
              {description && <Dialog.Description className="mt-1 text-sm text-muted">{description}</Dialog.Description>}
            </div>
            <Dialog.Close asChild>
              <IconButton label="Close" className="-mt-1 -mr-2">
                <X className="size-4" />
              </IconButton>
            </Dialog.Close>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto px-5 pt-2 pb-5">{children}</div>
          {footer && <div className="flex justify-end gap-2 border-t border-rule px-5 py-3">{footer}</div>}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

export function Confirm({
  open,
  onOpenChange,
  title,
  body,
  confirmLabel,
  danger,
  onConfirm,
  loading,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  title: string;
  body: ReactNode;
  confirmLabel: string;
  danger?: boolean;
  onConfirm: () => void;
  loading?: boolean;
}) {
  return (
    <Sheet
      open={open}
      onOpenChange={onOpenChange}
      title={title}
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            variant={danger ? "primary" : "primary"}
            className={danger ? "!bg-negative hover:!bg-[#a81e23]" : ""}
            onClick={onConfirm}
            loading={loading}
          >
            {confirmLabel}
          </Button>
        </>
      }
    >
      <div className="text-sm text-muted">{body}</div>
    </Sheet>
  );
}

/* ----------------------------------------------------------------- Toasts */
type Toast = { id: number; text: string; tone: "neutral" | "error"; action?: { label: string; run: () => void } };
const ToastCtx = createContext<(t: Omit<Toast, "id">) => void>(() => {});

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const push = useCallback((t: Omit<Toast, "id">) => {
    const id = Date.now() + Math.random();
    setToasts((xs) => [...xs.slice(-2), { ...t, id }]);
    setTimeout(() => setToasts((xs) => xs.filter((x) => x.id !== id)), t.action ? 6000 : 3500);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div
        aria-live="polite"
        className="pointer-events-none fixed inset-x-0 z-[60] flex flex-col items-center gap-2 px-4"
        style={{ bottom: "calc(var(--safe-bottom) + 84px)" }}
      >
        {toasts.map((t) => (
          <div
            key={t.id}
            className={cx(
              "toast pointer-events-auto flex max-w-md items-center gap-3 rounded-[10px] px-4 py-2.5 text-sm text-white shadow-[0_8px_30px_rgba(0,0,0,0.2)]",
              t.tone === "error" ? "bg-[#7c1d1f]" : "bg-toast",
            )}
          >
            <span>{t.text}</span>
            {t.action && (
              <button
                className="font-semibold text-toast-accent"
                onClick={() => {
                  t.action!.run();
                  setToasts((xs) => xs.filter((x) => x.id !== t.id));
                }}
              >
                {t.action.label}
              </button>
            )}
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}

export function useToast() {
  const push = useContext(ToastCtx);
  return {
    show: (text: string, action?: Toast["action"]) => push({ text, tone: "neutral", action }),
    error: (e: unknown) => push({ text: e instanceof Error ? e.message : String(e), tone: "error" }),
  };
}
