import { createFileRoute } from "@tanstack/react-router";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "@/api/client";
import { useAuthCapabilities, useLocalEnroll, useLocalLogin, useLocalTotp } from "@/api/hooks";
import type { LocalLoginStageOut } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/login")({
  component: LoginPage,
});

// Anchor-as-button: a <a> can't use the <Button> component (which is a
// <button>) — and doing OIDC redirects via <button onClick> blocks the
// browser's built-in middle-click / new-tab behaviour. Render an <a> with
// the same shadcn-button styles.
const anchorButtonClasses =
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md text-sm font-medium ring-offset-background transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 bg-primary text-primary-foreground hover:bg-primary/90 h-10 px-4 py-2 w-full";

function localLoginErrorKey(err: ApiError): string {
  if (err.status === 401) return "auth.errors.invalid_credentials";
  if (err.status === 403) return "auth.errors.local_login_disabled";
  if (err.status === 423) return "auth.errors.account_locked";
  if (err.status === 429) return "errors.rate_limited";
  return "errors.generic";
}

function secondFactorErrorKey(err: ApiError): string {
  // 401 covers both a wrong code and an expired challenge; the detail tells
  // them apart, and they need different advice (retry vs. start over).
  if (err.status === 401) {
    return err.code === "expired" ? "auth.errors.challenge_expired" : "auth.errors.invalid_code";
  }
  if (err.status === 403) return "auth.errors.local_login_disabled";
  if (err.status === 423) return "auth.errors.account_locked";
  if (err.status === 429) return "errors.rate_limited";
  return "errors.generic";
}

/** Hard navigation so React-Query refetches `me` with the fresh session. */
function goToApp(): void {
  window.location.assign("/");
}

function ErrorBanner({ children }: { children: React.ReactNode }): JSX.Element {
  return (
    <div
      role="alert"
      className="rounded-md border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive"
    >
      {children}
    </div>
  );
}

export function LoginPage(): JSX.Element {
  const { t } = useTranslation();
  const caps = useAuthCapabilities();
  const oidcEnabled = caps.data?.oidc_enabled ?? false;
  const localEnabled = caps.data?.local_login_enabled ?? false;
  // While the capabilities are loading, render only the title — avoids a
  // flicker where the OIDC button appears, then disappears, then the local
  // form replaces it.
  const showLocal = caps.isSuccess && localEnabled;
  const showOidc = caps.isSuccess && oidcEnabled;

  return (
    <div className="flex min-h-screen items-center justify-center bg-background p-4">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle className="font-serif">{t("auth.login_title")}</CardTitle>
          <CardDescription>{t("auth.login_intro")}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          {showOidc ? (
            <a href="/api/auth/login" className={cn(anchorButtonClasses)}>
              {t("auth.login_button")}
            </a>
          ) : null}

          {showLocal && showOidc ? (
            <details>
              <summary className="cursor-pointer text-sm text-muted-foreground hover:text-foreground">
                {t("auth.login_local_disclosure")}
              </summary>
              <div className="mt-4">
                <LocalLoginForm />
              </div>
            </details>
          ) : null}
          {showLocal && !showOidc ? <LocalLoginForm /> : null}
        </CardContent>
      </Card>
    </div>
  );
}

type LocalStep =
  | { kind: "password" }
  | { kind: "totp"; challenge: string }
  | { kind: "enroll"; stage: LocalLoginStageOut }
  | { kind: "codes"; codes: string[] };

/**
 * The local break-glass login, in up to three steps (ADR-0015 D2).
 *
 * The password alone never yields a session: it returns a challenge plus the
 * stage that follows — a code, or forced enrolment for an account that has no
 * second factor yet. Only a suspended MFA requirement short-circuits to a
 * session, which the backend signals with 204 and no body.
 */
export function LocalLoginForm(): JSX.Element {
  const [step, setStep] = useState<LocalStep>({ kind: "password" });

  switch (step.kind) {
    case "totp":
      return (
        <LocalTotpForm
          challenge={step.challenge}
          onRestart={() => setStep({ kind: "password" })}
        />
      );
    case "enroll":
      return (
        <LocalEnrollForm
          stage={step.stage}
          onDone={(codes) => setStep({ kind: "codes", codes })}
          onRestart={() => setStep({ kind: "password" })}
        />
      );
    case "codes":
      return <LocalRecoveryCodes codes={step.codes} />;
    default:
      return (
        <LocalPasswordForm
          onStage={(stage) =>
            setStep(
              stage.stage === "enroll"
                ? { kind: "enroll", stage }
                : { kind: "totp", challenge: stage.challenge },
            )
          }
        />
      );
  }
}

function LocalPasswordForm({
  onStage,
}: {
  onStage: (stage: LocalLoginStageOut) => void;
}): JSX.Element {
  const { t } = useTranslation();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const login = useLocalLogin();

  function handleSubmit(e: FormEvent<HTMLFormElement>): void {
    e.preventDefault();
    login.mutate(
      { username, password },
      {
        onSuccess: (stage) => {
          // 204 with no body = the MFA requirement is suspended and the
          // session cookies are already set.
          if (!stage) {
            goToApp();
            return;
          }
          onStage(stage);
        },
      },
    );
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-3">
      {login.isError ? <ErrorBanner>{t(localLoginErrorKey(login.error))}</ErrorBanner> : null}
      <div className="space-y-1">
        <Label htmlFor="local-username">{t("auth.login_local_username")}</Label>
        <Input
          id="local-username"
          name="username"
          autoComplete="username"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          required
        />
      </div>
      <div className="space-y-1">
        <Label htmlFor="local-password">{t("auth.login_local_password")}</Label>
        <Input
          id="local-password"
          name="password"
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
        />
      </div>
      <Button type="submit" className="w-full" disabled={login.isPending}>
        {login.isPending ? t("common.loading") : t("auth.login_local_submit")}
      </Button>
    </form>
  );
}

function CodeInput({
  id,
  value,
  onChange,
  label,
}: {
  id: string;
  value: string;
  onChange: (next: string) => void;
  label: string;
}): JSX.Element {
  return (
    <div className="space-y-1">
      <Label htmlFor={id}>{label}</Label>
      <Input
        id={id}
        name="one-time-code"
        // Lets the OS offer the code from an SMS/authenticator prompt.
        autoComplete="one-time-code"
        inputMode="text"
        autoFocus
        value={value}
        onChange={(e) => onChange(e.target.value)}
        required
      />
    </div>
  );
}

function LocalTotpForm({
  challenge,
  onRestart,
}: {
  challenge: string;
  onRestart: () => void;
}): JSX.Element {
  const { t } = useTranslation();
  const [code, setCode] = useState("");
  const totp = useLocalTotp();

  function handleSubmit(e: FormEvent<HTMLFormElement>): void {
    e.preventDefault();
    totp.mutate({ challenge, code }, { onSuccess: goToApp });
  }

  const expired = totp.isError && totp.error.code === "expired";

  return (
    <form onSubmit={handleSubmit} className="space-y-3">
      {totp.isError ? <ErrorBanner>{t(secondFactorErrorKey(totp.error))}</ErrorBanner> : null}
      <p className="text-sm text-muted-foreground">{t("auth.totp_intro")}</p>
      <CodeInput id="local-totp" value={code} onChange={setCode} label={t("auth.totp_code")} />
      <p className="text-xs text-muted-foreground">{t("auth.totp_recovery_hint")}</p>
      {expired ? (
        <Button type="button" variant="outline" className="w-full" onClick={onRestart}>
          {t("auth.totp_restart")}
        </Button>
      ) : (
        <Button type="submit" className="w-full" disabled={totp.isPending}>
          {totp.isPending ? t("common.loading") : t("auth.totp_submit")}
        </Button>
      )}
    </form>
  );
}

function LocalEnrollForm({
  stage,
  onDone,
  onRestart,
}: {
  stage: LocalLoginStageOut;
  onDone: (codes: string[]) => void;
  onRestart: () => void;
}): JSX.Element {
  const { t } = useTranslation();
  const [code, setCode] = useState("");
  const enroll = useLocalEnroll();

  function handleSubmit(e: FormEvent<HTMLFormElement>): void {
    e.preventDefault();
    enroll.mutate(
      { challenge: stage.challenge, code },
      { onSuccess: (result) => onDone(result.recovery_codes) },
    );
  }

  const expired = enroll.isError && enroll.error.code === "expired";

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      {enroll.isError ? <ErrorBanner>{t(secondFactorErrorKey(enroll.error))}</ErrorBanner> : null}
      <div className="space-y-1">
        <p className="text-sm font-medium">{t("auth.enroll_title")}</p>
        <p className="text-sm text-muted-foreground">{t("auth.enroll_intro")}</p>
      </div>
      {stage.qr_data_uri ? (
        <div className="flex justify-center">
          <img
            src={stage.qr_data_uri}
            alt={t("auth.enroll_qr_alt")}
            className="h-44 w-44 rounded-lg border bg-background p-3"
          />
        </div>
      ) : null}
      {stage.secret ? (
        <div className="space-y-1">
          <Label htmlFor="local-enroll-secret">{t("auth.enroll_secret_label")}</Label>
          <Input
            id="local-enroll-secret"
            readOnly
            value={stage.secret}
            className="bg-muted font-mono text-xs"
          />
        </div>
      ) : null}
      <CodeInput id="local-enroll" value={code} onChange={setCode} label={t("auth.totp_code")} />
      {expired ? (
        <Button type="button" variant="outline" className="w-full" onClick={onRestart}>
          {t("auth.totp_restart")}
        </Button>
      ) : (
        <Button type="submit" className="w-full" disabled={enroll.isPending}>
          {enroll.isPending ? t("common.loading") : t("auth.enroll_submit")}
        </Button>
      )}
    </form>
  );
}

function LocalRecoveryCodes({ codes }: { codes: string[] }): JSX.Element {
  const { t } = useTranslation();
  return (
    <div className="space-y-4">
      <div className="space-y-1">
        <p className="text-sm font-medium">{t("auth.recovery_title")}</p>
        <p className="text-sm text-muted-foreground">{t("auth.recovery_intro")}</p>
      </div>
      <ul className="grid grid-cols-2 gap-x-4 gap-y-1 rounded-md border bg-muted/40 p-3 font-mono text-xs">
        {codes.map((code) => (
          <li key={code}>{code}</li>
        ))}
      </ul>
      <Button type="button" className="w-full" onClick={goToApp}>
        {t("auth.recovery_continue")}
      </Button>
    </div>
  );
}
