"use client";

import { useEffect, useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";

import { AuthNotice, AuthShell, AuthUnavailable } from "@/components/auth/AuthShell";
import { PasswordField } from "@/components/auth/PasswordField";
import {
  hasPublicAuthConfig,
  sendPasswordResetEmail,
  signInWithPassword,
} from "@/lib/auth/client";
import { useSession } from "@/lib/auth/use-session";

export default function LoginPage() {
  const router = useRouter();
  const session = useSession();
  const configured = hasPublicAuthConfig();
  const [mode, setMode] = useState<"signin" | "recovery">("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [recoverySent, setRecoverySent] = useState(false);

  useEffect(() => {
    if (session.status === "signedIn") router.replace("/");
  }, [session.status, router]);

  if (!configured) return <AuthUnavailable />;

  if (recoverySent) {
    return (
      <AuthShell title="Check your email">
        <AuthNotice kind="ok">
          If that email has a Trendora account, a recovery link is on its way.
        </AuthNotice>
        <div className="auth-actions">
          <button
            type="button"
            className="secondary-button"
            onClick={() => {
              setRecoverySent(false);
              setMode("signin");
            }}
          >
            Back to sign in
          </button>
        </div>
      </AuthShell>
    );
  }

  async function handleSubmit(event: FormEvent): Promise<void> {
    event.preventDefault();
    if (pending) return;
    setPending(true);
    setError(null);
    try {
      if (mode === "signin") {
        const failure = await signInWithPassword(email.trim(), password);
        if (failure) setError(failure);
        // Success: the SIGNED_IN event flips the store and the effect above
        // routes to the workspace.
      } else {
        const failure = await sendPasswordResetEmail(email.trim());
        if (failure) setError(failure);
        else setRecoverySent(true);
      }
    } finally {
      setPending(false);
    }
  }

  return (
    <AuthShell
      title={mode === "signin" ? "Sign in" : "Reset your password"}
      lede={
        mode === "signin"
          ? "Use your workspace email and password."
          : "Enter your account email and we'll send a recovery link."
      }
    >
      <form className="auth-form" onSubmit={handleSubmit}>
        <div className="form-field">
          <label htmlFor="login-email">Email</label>
          <input
            id="login-email"
            name="email"
            type="email"
            autoComplete="email"
            required
            value={email}
            onChange={(event) => setEmail(event.target.value)}
          />
        </div>
        {mode === "signin" && (
          <PasswordField
            id="login-password"
            label="Password"
            autoComplete="current-password"
            value={password}
            onChange={setPassword}
            required
          />
        )}
        {error && <AuthNotice kind="error">{error}</AuthNotice>}
        <button type="submit" className="primary-button" disabled={pending}>
          {pending
            ? mode === "signin"
              ? "Signing in…"
              : "Sending…"
            : mode === "signin"
              ? "Sign in"
              : "Send recovery link"}
        </button>
      </form>
      <div className="auth-alt">
        {mode === "signin" ? (
          <button
            type="button"
            className="text-link"
            onClick={() => {
              setMode("recovery");
              setError(null);
            }}
          >
            Forgot your password?
          </button>
        ) : (
          <button
            type="button"
            className="text-link"
            onClick={() => {
              setMode("signin");
              setError(null);
            }}
          >
            Back to sign in
          </button>
        )}
      </div>
    </AuthShell>
  );
}
