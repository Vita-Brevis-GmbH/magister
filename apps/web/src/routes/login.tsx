import { createFileRoute } from "@tanstack/react-router";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "@/api/client";
import { useAdLogin, useAuthCapabilities, useLocalLogin } from "@/api/hooks";
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

function adLoginErrorKey(err: ApiError): string {
  if (err.status === 401) return "auth.errors.invalid_credentials";
  if (err.status === 403) return "auth.errors.ad_login_disabled";
  if (err.status === 429) return "errors.rate_limited";
  return "errors.generic";
}

export function LoginPage(): JSX.Element {
  const { t } = useTranslation();
  const caps = useAuthCapabilities();
  const oidcEnabled = caps.data?.oidc_enabled ?? false;
  const localEnabled = caps.data?.local_login_enabled ?? false;
  const adEnabled = caps.data?.ad_login_enabled ?? false;
  // While the capabilities are loading, render only the title — avoids a
  // flicker where the OIDC button appears, then disappears, then the local
  // form replaces it.
  const showLocal = caps.isSuccess && localEnabled;
  const showOidc = caps.isSuccess && oidcEnabled;
  const showAd = caps.isSuccess && adEnabled;

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

          {showAd && showOidc ? (
            <details>
              <summary className="cursor-pointer text-sm text-muted-foreground hover:text-foreground">
                {t("auth.login_ad_disclosure")}
              </summary>
              <div className="mt-4">
                <AdLoginForm />
              </div>
            </details>
          ) : null}
          {showAd && !showOidc ? <AdLoginForm /> : null}

          {showLocal && (showOidc || showAd) ? (
            <details>
              <summary className="cursor-pointer text-sm text-muted-foreground hover:text-foreground">
                {t("auth.login_local_disclosure")}
              </summary>
              <div className="mt-4">
                <LocalLoginForm />
              </div>
            </details>
          ) : null}
          {showLocal && !showOidc && !showAd ? <LocalLoginForm /> : null}
        </CardContent>
      </Card>
    </div>
  );
}

export function AdLoginForm(): JSX.Element {
  const { t } = useTranslation();
  const [login_, setLogin] = useState("");
  const [password, setPassword] = useState("");
  const login = useAdLogin();

  function handleSubmit(e: FormEvent<HTMLFormElement>): void {
    e.preventDefault();
    login.mutate(
      { login: login_, password },
      {
        onSuccess: () => {
          window.location.assign("/");
        },
      },
    );
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-3">
      {login.isError ? (
        <div
          role="alert"
          className="rounded-md border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive"
        >
          {t(adLoginErrorKey(login.error))}
        </div>
      ) : null}
      <div className="space-y-1">
        <Label htmlFor="ad-login">{t("auth.login_ad_username")}</Label>
        <Input
          id="ad-login"
          name="username"
          autoComplete="username"
          value={login_}
          onChange={(e) => setLogin(e.target.value)}
          required
        />
      </div>
      <div className="space-y-1">
        <Label htmlFor="ad-password">{t("auth.login_ad_password")}</Label>
        <Input
          id="ad-password"
          name="password"
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
        />
      </div>
      <Button type="submit" className="w-full" disabled={login.isPending}>
        {login.isPending ? t("common.loading") : t("auth.login_ad_submit")}
      </Button>
    </form>
  );
}

export function LocalLoginForm(): JSX.Element {
  const { t } = useTranslation();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const login = useLocalLogin();

  function handleSubmit(e: FormEvent<HTMLFormElement>): void {
    e.preventDefault();
    login.mutate(
      { username, password },
      {
        onSuccess: () => {
          // The cookie is set; do a hard navigation so React-Query's `me`
          // query refetches with the fresh session and the auth-guard layout
          // sees an authenticated user on the next paint.
          window.location.assign("/");
        },
      },
    );
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-3">
      {login.isError ? (
        <div
          role="alert"
          className="rounded-md border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive"
        >
          {t(localLoginErrorKey(login.error))}
        </div>
      ) : null}
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
