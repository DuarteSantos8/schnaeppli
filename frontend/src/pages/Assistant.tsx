import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, ArrowUp, Plus, Trash2, X } from "lucide-react";
import { Fragment, useEffect, useRef, useState, type ReactNode } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { Button, cx, ErrorBox, IconButton, Notice, Skeleton, Textarea, useToast } from "@/components/ui";
import { ApiError, del, get, post } from "@/lib/api";
import { relTime } from "@/lib/format";
import type { DealDetail } from "@/lib/types";

interface Thread { id: string; title: string; updated_at: string }
interface Msg { id: string; role: "user" | "assistant"; content: string; refs: Record<string, string>; created_at: string }

const PROMPTS = [
  "What's the best purchase within my remaining budget?",
  "Which of my current deals would you actually buy, and why?",
  "Which lens works with the camera I'm looking for?",
  "Compare the three best offers for my top search.",
];

/** Turns [L3] references into links and keeps paragraphs and bullet lists readable. */
function Rich({ text, refs }: { text: string; refs: Record<string, string> }) {
  const lines = text.split("\n");
  const inline = (s: string, k: number): ReactNode[] =>
    s.split(/(\[L\d+\]|\*\*[^*]+\*\*)/g).map((part, i) => {
      const m = part.match(/^\[(L\d+)\]$/);
      if (m && refs[m[1]])
        return (
          <Link key={`${k}-${i}`} to={`/deals/${refs[m[1]]}`} className="mx-0.5 inline-flex h-5 items-center rounded bg-score-soft px-1.5 text-[0.75rem] font-medium text-score no-underline">
            {m[1]}
          </Link>
        );
      if (part.startsWith("**") && part.endsWith("**")) return <strong key={`${k}-${i}`}>{part.slice(2, -2)}</strong>;
      return <Fragment key={`${k}-${i}`}>{part}</Fragment>;
    });
  const out: ReactNode[] = [];
  let list: ReactNode[] = [];
  const flush = () => {
    if (list.length) out.push(<ul key={`ul${out.length}`} className="my-1.5 list-disc space-y-1 pl-5">{list}</ul>);
    list = [];
  };
  lines.forEach((l, i) => {
    const b = l.match(/^\s*[-*•]\s+(.*)/);
    if (b) list.push(<li key={i}>{inline(b[1], i)}</li>);
    else {
      flush();
      if (l.trim()) out.push(<p key={i} className="my-1.5">{inline(l.replace(/^#+\s*/, ""), i)}</p>);
    }
  });
  flush();
  return <>{out}</>;
}

function ThreadList({ threads, active }: { threads: Thread[]; active?: string }) {
  const qc = useQueryClient();
  const nav = useNavigate();
  const remove = useMutation({
    mutationFn: (id: string) => del(`/api/chat/threads/${id}`),
    onSuccess: (_d, id) => {
      qc.invalidateQueries({ queryKey: ["threads"] });
      if (id === active) nav("/assistant");
    },
  });
  if (!threads.length) return <p className="px-2 py-3 text-sm text-muted">No conversations yet.</p>;
  return (
    <ul className="flex flex-col gap-0.5">
      {threads.map((t) => (
        <li key={t.id} className="group flex items-center">
          <Link
            to={`/assistant/${t.id}`}
            className={cx("min-w-0 flex-1 rounded-[var(--radius-control)] px-2.5 py-2", t.id === active ? "bg-raised" : "hover:bg-sunk")}
          >
            <span className="block truncate text-sm">{t.title}</span>
            <span className="block text-[0.75rem] text-muted">{relTime(t.updated_at)}</span>
          </Link>
          <IconButton label={`Delete ${t.title}`} onClick={() => remove.mutate(t.id)} className="opacity-0 group-hover:opacity-100 focus:opacity-100">
            <Trash2 className="size-3.5" />
          </IconButton>
        </li>
      ))}
    </ul>
  );
}

export default function Assistant() {
  const { threadId } = useParams();
  const [params, setParams] = useSearchParams();
  const focus = params.get("focus");
  const nav = useNavigate();
  const qc = useQueryClient();
  const toast = useToast();
  const [text, setText] = useState("");
  const [pending, setPending] = useState<string | null>(null);
  const endRef = useRef<HTMLDivElement>(null);

  const threads = useQuery({ queryKey: ["threads"], queryFn: () => get<Thread[]>("/api/chat/threads") });
  const thread = useQuery({
    queryKey: ["thread", threadId],
    queryFn: () => get<{ id: string; title: string; messages: Msg[] }>(`/api/chat/threads/${threadId}`),
    enabled: !!threadId,
  });
  const focusDeal = useQuery({ queryKey: ["deal", focus], queryFn: () => get<DealDetail>(`/api/deals/${focus}`), enabled: !!focus });

  const send = useMutation({
    mutationFn: async (msg: string) => {
      let id = threadId;
      if (!id) {
        const t = await post<Thread>("/api/chat/threads");
        id = t.id;
        nav(`/assistant/${id}${focus ? `?focus=${focus}` : ""}`, { replace: true });
      }
      await post<Msg>(`/api/chat/threads/${id}/messages`, { text: msg, focus: focus ? [focus] : [] });
      return id;
    },
    onMutate: (msg) => setPending(msg),
    onSettled: (id) => {
      setPending(null);
      qc.invalidateQueries({ queryKey: ["thread", id] });
      qc.invalidateQueries({ queryKey: ["threads"] });
    },
    onError: (e) => {
      if (!(e instanceof ApiError && e.status === 409)) toast.error(e);
    },
  });

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [thread.data?.messages.length, pending]);

  const submit = (msg = text) => {
    const t = msg.trim();
    if (!t || send.isPending) return;
    setText("");
    send.mutate(t);
  };

  const messages = thread.data?.messages || [];
  const noProvider = send.error instanceof ApiError && send.error.status === 409;
  const showList = !threadId;

  return (
    <div className="lg:grid lg:grid-cols-[240px_1fr] lg:gap-8">
      <aside className={cx("lg:block", threadId ? "hidden" : "block")}>
        <div className="mb-3 flex items-center justify-between">
          <h1 className="text-[1.375rem] font-semibold tracking-[-0.02em] lg:text-[0.9375rem]">Assistant</h1>
          <Link to="/assistant">
            <Button size="sm" icon={<Plus className="size-3.5" aria-hidden />}>New</Button>
          </Link>
        </div>
        {threads.isLoading ? <Skeleton className="h-24" /> : <ThreadList threads={threads.data || []} active={threadId} />}
      </aside>

      <section className={cx("flex min-h-[calc(100dvh-220px)] flex-col", showList && "mt-8 lg:mt-0")} aria-label="Conversation">
        {threadId && (
          <Link to="/assistant" className="mb-3 inline-flex items-center gap-1 text-sm text-muted hover:text-ink lg:hidden">
            <ArrowLeft className="size-4" aria-hidden /> Conversations
          </Link>
        )}
        <div className="flex-1">
          {!threadId && !pending && (
            <div className="max-w-xl">
              <h2 className="text-[1.125rem] font-semibold tracking-[-0.01em]">Ask about your deals</h2>
              <p className="mt-1 text-sm text-muted">
                The assistant sees your searches, budget and the listings Schnäppli found for you. It can't buy anything or change settings.
              </p>
              <ul className="mt-4 flex flex-col">
                {PROMPTS.map((p) => (
                  <li key={p}>
                    <button onClick={() => submit(p)} className="hover-lift w-full rounded-[var(--radius-control)] px-3 py-2.5 text-left text-sm">
                      {p}
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {thread.error ? <ErrorBox error={thread.error} /> : null}
          <ol className="flex flex-col gap-4">
            {messages.map((m) => (
              <li key={m.id} className={m.role === "user" ? "ml-auto max-w-[85%]" : "max-w-[46rem]"}>
                {m.role === "user" ? (
                  <div className="rounded-[14px] rounded-br-[4px] bg-ink px-4 py-2.5 text-[0.9375rem] whitespace-pre-line text-on-ink">{m.content}</div>
                ) : (
                  <div className="text-[0.9375rem] leading-relaxed text-ink">
                    <Rich text={m.content} refs={m.refs} />
                  </div>
                )}
              </li>
            ))}
            {pending && (
              <>
                <li className="ml-auto max-w-[85%] rounded-[14px] rounded-br-[4px] bg-ink px-4 py-2.5 text-[0.9375rem] whitespace-pre-line text-on-ink">{pending}</li>
                <li className="flex items-center gap-1.5 text-sm text-muted" role="status">
                  <span className="size-1.5 animate-pulse rounded-full bg-faint" />
                  <span className="size-1.5 animate-pulse rounded-full bg-faint [animation-delay:150ms]" />
                  <span className="size-1.5 animate-pulse rounded-full bg-faint [animation-delay:300ms]" />
                  <span className="sr-only">The assistant is replying</span>
                </li>
              </>
            )}
          </ol>
          <div ref={endRef} />
        </div>

        <div className="sticky bottom-[calc(var(--safe-bottom)+64px)] mt-6 lg:bottom-4">
          {noProvider && (
            <div className="mb-2">
              <Notice tone="warning" action={<Link to="/settings/ai"><Button size="sm" variant="primary">Add a key</Button></Link>}>
                Add an AI provider key to use the assistant.
              </Notice>
            </div>
          )}
          {focus && focusDeal.data && (
            <div className="mb-2 flex items-center gap-2 rounded-[var(--radius-control)] bg-score-soft px-3 py-2 text-[0.8125rem] text-score">
              <span className="min-w-0 flex-1 truncate">About: {focusDeal.data.listing.title}</span>
              <button
                aria-label="Remove focus"
                onClick={() => {
                  params.delete("focus");
                  setParams(params, { replace: true });
                }}
              >
                <X className="size-3.5" />
              </button>
            </div>
          )}
          <div className="flex items-end gap-2 rounded-[14px] border border-border bg-surface p-1.5 focus-within:border-ink">
            <Textarea
              value={text}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing && window.matchMedia("(pointer: fine)").matches) {
                  e.preventDefault();
                  submit();
                }
              }}
              rows={1}
              maxLength={4000}
              placeholder={focus ? "Is this worth it?" : "Ask anything about your shopping"}
              aria-label="Message"
              className="max-h-40 min-h-10 border-0 py-2 focus:border-0"
            />
            <Button variant="primary" onClick={() => submit()} disabled={!text.trim()} loading={send.isPending} aria-label="Send" className="size-10 shrink-0 !px-0">
              {!send.isPending && <ArrowUp className="size-4" />}
            </Button>
          </div>
        </div>
      </section>
    </div>
  );
}
