"use client";

import { AuthUnavailable } from "@/components/auth/AuthShell";
import { SetPasswordPanel } from "@/components/auth/SetPasswordPanel";
import { hasPublicAuthConfig } from "@/lib/auth/client";

export default function AcceptInvitePage() {
  if (!hasPublicAuthConfig()) return <AuthUnavailable />;
  return (
    <SetPasswordPanel
      expected="invite"
      formTitle="Accept your invitation"
      invalidNotice="This invitation link is invalid, expired, or already used."
      invalidHint="Ask an administrator to send a new invitation."
      successNotice="Your Trendora password is set."
    />
  );
}
