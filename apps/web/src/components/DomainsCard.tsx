import { useState } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "@/api/client";
import { useDomains, useUpdateDomains } from "@/api/hooks";
import type { DomainsOut } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";

function lines(text: string): string[] {
  return text
    .split(/[\s,;]+/)
    .map((d) => d.trim().toLowerCase())
    .filter(Boolean);
}

/**
 * Mail- und UPN-Domains für die Auswahl im Benutzerformular.
 *
 * Gehört dem Kunden, auch gehostet — welche Domains seine Konten tragen,
 * weiss er, nicht der Betreiber.
 */
export function DomainsCard(): JSX.Element {
  const { t } = useTranslation();
  const q = useDomains();
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{t("admin.domains.title")}</CardTitle>
        <CardDescription>{t("admin.domains.desc")}</CardDescription>
      </CardHeader>
      <CardContent>
        {q.isError ? (
          <p className="text-sm text-destructive">{t("errors.generic")}</p>
        ) : q.data ? (
          <DomainsForm data={q.data} />
        ) : (
          <p className="text-sm text-muted-foreground">{t("common.loading")}</p>
        )}
      </CardContent>
    </Card>
  );
}

/** Domains aus dem AD als Knöpfe: ein Klick übernimmt sie in die Liste. */
function AdChips({
  label,
  domains,
  onPick,
}: {
  label: string;
  domains: string[];
  onPick: (domain: string) => void;
}): JSX.Element | null {
  const { t } = useTranslation();
  if (domains.length === 0) return null;
  return (
    <div className="space-y-1">
      <p className="text-xs text-muted-foreground">{label}</p>
      <ul className="flex flex-wrap gap-1.5">
        {domains.map((d) => (
          <li key={d}>
            <button
              type="button"
              onClick={() => onPick(d)}
              title={t("admin.domains.adopt", { domain: d })}
              aria-label={t("admin.domains.adopt", { domain: d })}
              className="rounded-full border border-dashed px-2.5 py-0.5 font-mono text-xs text-muted-foreground hover:border-solid hover:text-foreground"
            >
              + {d}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

function DomainsForm({ data }: { data: DomainsOut }): JSX.Element {
  const { t } = useTranslation();
  const save = useUpdateDomains();
  const [mail, setMail] = useState(data.mail_domains.join("\n"));
  const [upn, setUpn] = useState(data.upn_domains.join("\n"));
  // Was schon in einem der Felder steht, wird nicht mehr vorgeschlagen.
  const listed = new Set([...lines(mail), ...lines(upn)]);
  const upnFromAd = data.upn_choices.filter((d) => !listed.has(d));
  const mailFromAd = (data.mail_suggestions ?? []).filter((d) => !lines(mail).includes(d));
  const error =
    save.error instanceof ApiError && save.error.status === 422
      ? t("admin.domains.invalid")
      : save.isError
        ? t("errors.generic")
        : null;

  function append(text: string, domain: string): string {
    const trimmed = text.trimEnd();
    return trimmed ? `${trimmed}\n${domain}` : domain;
  }

  return (
    <form
      className="space-y-4"
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate(
          { mail_domains: lines(mail), upn_domains: lines(upn) },
          {
            // Was der Server daraus macht (klein, ohne Doppelte) zurück ins Feld.
            onSuccess: (out) => {
              setMail(out.mail_domains.join("\n"));
              setUpn(out.upn_domains.join("\n"));
            },
          },
        );
      }}
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="space-y-2">
          <div className="space-y-1">
            <Label htmlFor="domains-mail">{t("admin.domains.mail")}</Label>
            <textarea
              id="domains-mail"
              rows={4}
              value={mail}
              onChange={(e) => {
                setMail(e.target.value);
                save.reset();
              }}
              placeholder="schule.ch"
              className="w-full rounded-md border border-input bg-background px-3 py-2 font-mono text-sm"
            />
            <p className="text-xs text-muted-foreground">{t("admin.domains.mail_hint")}</p>
          </div>
          <AdChips
            label={t("admin.domains.ad_mail")}
            domains={mailFromAd}
            onPick={(d) => {
              setMail((prev) => append(prev, d));
              save.reset();
            }}
          />
        </div>
        <div className="space-y-2">
          <div className="space-y-1">
            <Label htmlFor="domains-upn">{t("admin.domains.upn")}</Label>
            <textarea
              id="domains-upn"
              rows={4}
              value={upn}
              onChange={(e) => {
                setUpn(e.target.value);
                save.reset();
              }}
              placeholder="sus-schule.ch"
              className="w-full rounded-md border border-input bg-background px-3 py-2 font-mono text-sm"
            />
            <p className="text-xs text-muted-foreground">{t("admin.domains.upn_hint")}</p>
          </div>
          <AdChips
            label={t("admin.domains.ad_upn")}
            domains={upnFromAd}
            onPick={(d) => {
              setUpn((prev) => append(prev, d));
              save.reset();
            }}
          />
        </div>
      </div>
      <div className="flex items-center gap-3">
        <Button type="submit" disabled={save.isPending}>
          {save.isPending ? t("common.loading") : t("admin.domains.save")}
        </Button>
        {save.isSuccess ? (
          <span role="status" className="text-sm text-emerald-700">
            {t("admin.domains.saved")}
          </span>
        ) : null}
        {error ? <span className="text-sm text-destructive">{error}</span> : null}
      </div>
    </form>
  );
}
