import { createFileRoute } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";

import { cn } from "@/lib/utils";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

export const Route = createFileRoute("/login")({
  component: LoginPage,
});

// Anchor-as-button: a <a> can't use the <Button> component (which is a
// <button>) — and doing OIDC redirects via <button onClick> blocks the
// browser's built-in middle-click / new-tab behaviour. Render an <a> with
// the same shadcn-button styles.
const buttonClasses =
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md text-sm font-medium ring-offset-background transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 bg-primary text-primary-foreground hover:bg-primary/90 h-10 px-4 py-2 w-full";

function LoginPage(): JSX.Element {
  const { t } = useTranslation();
  return (
    <div className="flex min-h-screen items-center justify-center bg-background p-4">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle className="font-serif">{t("auth.login_title")}</CardTitle>
          <CardDescription>{t("auth.login_intro")}</CardDescription>
        </CardHeader>
        <CardContent>
          <a href="/auth/login" className={cn(buttonClasses)}>
            {t("auth.login_button")}
          </a>
        </CardContent>
      </Card>
    </div>
  );
}
