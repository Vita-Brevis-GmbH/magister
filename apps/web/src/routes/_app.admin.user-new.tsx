import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "@/api/client";
import { useCreateAdUser } from "@/api/hooks";
import type { AdUserOuKey } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export const Route = createFileRoute("/_app/admin/user-new")({
  component: NewUserPage,
});

const OU_KEYS: AdUserOuKey[] = ["teacher", "student_zyklus3", "student_other"];

const selectClasses =
  "flex h-10 w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50";

function createErrorKey(err: ApiError): string {
  if (err.status === 409) return "admin.user_new.err_ou_not_configured";
  if (err.status === 503) return "admin.user_new.err_ad";
  if (err.status === 422) return "admin.user_new.err_invalid";
  return "errors.generic";
}

function NewUserPage(): JSX.Element {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const create = useCreateAdUser();

  const [form, setForm] = useState({
    given_name: "",
    surname: "",
    sam_account_name: "",
    user_principal_name: "",
    mail: "",
    ou_key: "teacher" as AdUserOuKey,
  });
  const [password, setPassword] = useState<string | null>(null);

  function field(key: keyof typeof form) {
    return {
      value: form[key],
      onChange: (e: React.ChangeEvent<HTMLInputElement>) =>
        setForm((prev) => ({ ...prev, [key]: e.target.value })),
    };
  }

  function handleSubmit(e: FormEvent<HTMLFormElement>): void {
    e.preventDefault();
    setPassword(null);
    create.mutate(
      {
        given_name: form.given_name,
        surname: form.surname,
        sam_account_name: form.sam_account_name,
        user_principal_name: form.user_principal_name,
        mail: form.mail || null,
        ou_key: form.ou_key,
      },
      { onSuccess: (res) => setPassword(res.temp_password) },
    );
  }

  if (password) {
    return (
      <div className="mx-auto max-w-lg space-y-6">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">{t("admin.user_new.created_title")}</CardTitle>
            <CardDescription>{t("admin.user_new.created_desc")}</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-1">
              <Label>{t("admin.user_new.temp_password")}</Label>
              <div className="rounded-md border bg-muted px-3 py-2 font-mono text-sm">
                {password}
              </div>
              <p className="text-xs text-muted-foreground">{t("admin.user_new.temp_hint")}</p>
            </div>
            <div className="flex gap-2">
              <Button type="button" onClick={() => navigate({ to: "/users" })}>
                {t("admin.user_new.to_users")}
              </Button>
              <Button
                type="button"
                variant="outline"
                onClick={() => {
                  setPassword(null);
                  setForm({
                    given_name: "",
                    surname: "",
                    sam_account_name: "",
                    user_principal_name: "",
                    mail: "",
                    ou_key: "teacher",
                  });
                }}
              >
                {t("admin.user_new.create_another")}
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-lg space-y-6">
      <header className="space-y-1">
        <h1 className="font-serif text-2xl font-semibold">{t("admin.user_new.title")}</h1>
        <p className="text-sm text-muted-foreground">{t("admin.user_new.description")}</p>
      </header>
      <Card>
        <CardContent className="pt-6">
          <form onSubmit={handleSubmit} className="space-y-4">
            {create.isError ? (
              <div
                role="alert"
                className="rounded-md border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive"
              >
                {t(createErrorKey(create.error))}
              </div>
            ) : null}
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <Label htmlFor="given">{t("admin.user_new.given_name")}</Label>
                <Input id="given" required {...field("given_name")} />
              </div>
              <div className="space-y-1">
                <Label htmlFor="surname">{t("admin.user_new.surname")}</Label>
                <Input id="surname" required {...field("surname")} />
              </div>
            </div>
            <div className="space-y-1">
              <Label htmlFor="sam">{t("admin.user_new.sam")}</Label>
              <Input id="sam" required autoComplete="off" {...field("sam_account_name")} />
            </div>
            <div className="space-y-1">
              <Label htmlFor="upn">{t("admin.user_new.upn")}</Label>
              <Input
                id="upn"
                required
                autoComplete="off"
                placeholder="vorname.nachname@schule.ch"
                {...field("user_principal_name")}
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="mail">{t("admin.user_new.mail")}</Label>
              <Input id="mail" type="email" autoComplete="off" {...field("mail")} />
            </div>
            <div className="space-y-1">
              <Label htmlFor="ou">{t("admin.user_new.ou")}</Label>
              <select
                id="ou"
                className={selectClasses}
                value={form.ou_key}
                onChange={(e) =>
                  setForm((prev) => ({ ...prev, ou_key: e.target.value as AdUserOuKey }))
                }
              >
                {OU_KEYS.map((k) => (
                  <option key={k} value={k}>
                    {t(`admin.user_new.ou_${k}`)}
                  </option>
                ))}
              </select>
              <p className="text-xs text-muted-foreground">{t("admin.user_new.ou_hint")}</p>
            </div>
            <Button type="submit" disabled={create.isPending}>
              {create.isPending ? t("common.loading") : t("admin.user_new.submit")}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
