"use client";

import { useEffect, useSyncExternalStore, useState, type FormEvent } from "react";
import Link from "next/link";

import { AuthNotice, AuthShell } from "@/components/auth/AuthShell";
import { PasswordField } from "@/components/auth/PasswordField";
import { resolveCallbackAcceptance, updatePassword } from "@/lib/auth/client";
import {
  deriveCallbackPhase,
  getInitialAuthHash,
  parseAuthCallback,
  type AuthCallbackPhase,
  type AuthCallbackType,
} from "@/lib/auth/callback";
import { useSession } from "@/lib/auth/use-session";

interface SetPasswordPanelProps {
  expected: AuthCallbackType;
  formTitle: string;
  invalidNotice: string;
  invalidHint: string;
  successNotice: string;
}

// The hash never changes while this screen is mounted (it was captured at
// module load), so the subscription is inert.
const subscribeNever = () => () => {};
const getServerHash = (): string | null => null;

/**
 * Invite + recovery password screens. The link's hash identifies the flow;
 * the form only appears once Supabase has adopted the token that the link
 * itself delivered, so expired, reused, incomplete, or foreign-session links
 * land on the invalid panel.
 */
export function SetPasswordPanel({
  expected,
  formTitle,
  invalidNotice,
  invalidHint,
  successNotice,
}: SetPasswordPanelProps) {
  const session = useSession();
  const hash = useSyncExternalStore<string | null>(
    subscribeNever,
    getInitialAuthHash,
    getServerHash,
  );
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [done, setDone] = useState(false);
  const [accepted, setAccepted] = useState<boolean | null>(null);

  useEffect(() => {
    let live = true;
    void resolveCallbackAcceptance().then((ok) => {
      if (live) setAccepted(ok);
    });
    return () => {
      live = false;
    };
  }, []);

  const phase: AuthCallbackPhase =
    hash === null
      ? "checking"
      : deriveCallbackPhase(
          parseAuthCallback(hash),
          expected,
          session.status,
          session.establishedToken,
          accepted,
        );

  if (done) {
    return (
      <AuthShell title="Password updated">
        <AuthNotice kind="ok">{successNotice}</AuthNotice>
        <div className="auth-actions">
          <Link className="primary-button" href="/">
            Continue to Trendora
          </Link>
        </div>
      </AuthShell>
    );
  }

  if (phase === "checking") {
    return (
      <AuthShell title={formTitle}>
        <p className="loading-note" role="status">
          Checking link…
        </p>
      </AuthShell>
    );
  }

  if (phase === "invalid") {
    return (
      <AuthShell title={formTitle}>
        <AuthNotice kind="error">{invalidNotice}</AuthNotice>
        <p className="auth-lede">{invalidHint}</p>
        <div className="auth-actions">
          <Link className="secondary-button" href="/login">
            Go to sign in
          </Link>
        </div>
      </AuthShell>
    );
  }

  async function handleSubmit(event: FormEvent): Promise<void> {
    event.preventDefault();
    if (pending) return;
    if (password !== confirm) {
      setError("Passwords don't match.");
      return;
    }
    setPending(true);
    setError(null);
    const failure = await updatePassword(password);
    setPending(false);
    if (failure) {
      setError(failure);
      return;
    }
    setDone(true);
  }

  return (
    <AuthShell
      title={formTitle}
      lede={expected === "invite" ? "Choose a password for your Trendora account." : undefined}
    >
      <form className="auth-form" onSubmit={handleSubmit}>
        <PasswordField
          id="set-password"
          label="New password"
          autoComplete="new-password"
          value={password}
          onChange={setPassword}
          required
        />
        <PasswordField
          id="set-password-confirm"
          label="Confirm new password"
          autoComplete="new-password"
          value={confirm}
          onChange={setConfirm}
          required
        />
        {error && <AuthNotice kind="error">{error}</AuthNotice>}
        <button type="submit" className="primary-button" disabled={pending}>
          {pending ? "Saving…" : "Set password"}
        </button>
      </form>
    </AuthShell>
  );
}
