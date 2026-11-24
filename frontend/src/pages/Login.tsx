import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Centered, Mark, Wordmark } from "@/components/shell";
import { Button, ErrorBox, Field, Input } from "@/components/ui";
import { get, post } from "@/lib/api";
import type { User } from "@/lib/types";

export default function Login() {
  const qc = useQueryClient();
  const status = useQuery({
    queryKey: ["auth-status"],
    queryFn: () => get<{ setup_required: boolean; setup_token_required: boolean; registration_mode: string }>("/api/auth/status"),
  });
  const invite = new URLSearchParams(location.search).get("invite");
  const [mode, setMode] = useState<"login" | "register">(invite ? "register" : "login");
  const setup = status.data?.setup_required;
  const registering = setup || mode === "register";
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [code, setCode] = useState(invite || "");
  const [setupToken, setSetupToken] = useState(new URLSearchParams(location.search).get("setup") || "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const user = registering
        ? await post<User>("/api/auth/register", { email, password, display_name: name, invite_code: code || null, setup_token: setupToken || null })
        : await post<User>("/api/auth/login", { email, password });
      qc.setQueryData(["me"], user);
      history.replaceState(null, "", "/");
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Centered>
      <div className="mb-8 flex items-center gap-2.5">
        <Mark size={30} />
        <Wordmark height={26} />
      </div>
      <h1 className="text-[1.375rem] font-semibold tracking-[-0.02em]">
        {setup ? "Set up Schnäppli" : registering ? "Create your account" : "Sign in"}
      </h1>
      <p className="mt-1 mb-6 text-sm text-muted">
        {setup
          ? "You're the first person here, so this account becomes the administrator."
          : registering
            ? "You'll need the invite code you were given."
            : "Your personal shopping agent."}
      </p>
      <form onSubmit={submit} className="flex flex-col gap-4">
        {registering && (
          <Field label="Your name" htmlFor="name">
            <Input id="name" value={name} onChange={(e) => setName(e.target.value)} required maxLength={80} autoComplete="name" />
          </Field>
        )}
        <Field label="E-mail" htmlFor="email">
          <Input
            id="email"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            autoComplete="email"
            autoCapitalize="none"
          />
        </Field>
        <Field label="Password" htmlFor="password" hint={registering ? "At least 10 characters. A few random words work well." : undefined}>
          <Input
            id="password"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            minLength={registering ? 10 : 1}
            autoComplete={registering ? "new-password" : "current-password"}
          />
        </Field>
        {setup && status.data?.setup_token_required && (
          <Field label="Setup token" htmlFor="setup" hint="From the server's configuration (SCHNAEPPLI_SETUP_TOKEN). Only needed once.">
            <Input id="setup" name="setup-token" className="secret-field" value={setupToken} onChange={(e) => setSetupToken(e.target.value.trim())} required autoComplete="off" autoCorrect="off" autoCapitalize="none" spellCheck={false} data-1p-ignore data-lpignore="true" data-form-type="other" />
          </Field>
        )}
        {registering && !setup && (
          <Field label="Invite code" htmlFor="code">
            <Input id="code" name="invite-code" value={code} onChange={(e) => setCode(e.target.value.trim())} required autoComplete="off" autoCorrect="off" autoCapitalize="none" spellCheck={false} data-1p-ignore data-lpignore="true" data-form-type="other" />
          </Field>
        )}
        {error ? <ErrorBox error={error} /> : null}
        <Button type="submit" variant="primary" size="lg" loading={busy} className="mt-1 w-full">
          {setup ? "Create admin account" : registering ? "Create account" : "Sign in"}
        </Button>
      </form>
      {!setup && status.data?.registration_mode !== "closed" && (
        <button
          className="mt-5 text-sm text-muted underline-offset-2 hover:text-ink hover:underline"
          onClick={() => {
            setMode(registering ? "login" : "register");
            setError(null);
          }}
        >
          {registering ? "I already have an account" : "I have an invite code"}
        </button>
      )}
    </Centered>
  );
}
