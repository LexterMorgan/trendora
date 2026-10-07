"use client";

import { AuthUnavailable } from "@/components/auth/AuthShell";
import { SetPasswordPanel } from "@/components/auth/SetPasswordPanel";
import { hasPublicAuthConfig } from "@/lib/auth/client";

export default function ResetPasswordPage() {
  if (!hasPublicAuthConfig()) return <AuthUnavailable />;
  return (
    <SetPasswordPanel
      expected="recovery"
      formTitle="Choose a new password"
      invalidNotice="This recovery link is invalid, expired, or already used."
      invalidHint="Request a new link from the sign-in page."
      successNotice="Your Trendora password is updated."
    />
  );
}
