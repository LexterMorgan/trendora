"use client";

import { type ReactNode } from "react";
import { useRouter } from "next/navigation";

import { SignOutButton } from "@/components/SignOutButton";

export interface ApiErrorState {
  code: string;
  message: string;
  kind?: string;
}

interface ApiErrorPanelProps {
  error: ApiErrorState;
  title: string;
  onRetry?: () => void;
  children?: ReactNode;
}

/**
 * One error surface for proxied GET pages. The kind decides the action:
 * 401 → sign in, 403 → sign out (no redirect loop), 503/network → retry.
 */
export function ApiErrorPanel({ error, title, onRetry, children }: ApiErrorPanelProps) {
  const router = useRouter();

  const heading =
    error.kind === "forbidden" ? "Access denied" : title;

  return (
    <section className="error-state" role="alert">
      <h2 className="section-title">{heading}</h2>
      <p>{error.message}</p>
      <div className="error-actions">
        {error.kind === "unauthenticated" && (
          <button
            type="button"
            className="primary-button"
            onClick={() => router.replace("/login")}
          >
            Sign in
          </button>
        )}
        {error.kind === "forbidden" && <SignOutButton />}
        {(error.kind === "unavailable" || error.kind === "network") &&
          onRetry && (
            <button type="button" className="secondary-button" onClick={onRetry}>
              Retry
            </button>
          )}
        {children}
      </div>
    </section>
  );
}
