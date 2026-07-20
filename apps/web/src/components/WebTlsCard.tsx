import { useState } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "@/api/client";
import { useUpdateAppSettings } from "@/api/hooks";
import type { AppSettingsUpdate } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

/** Import / remove the webserver TLS certificate (PEM pair or PFX). */
export function WebTlsCard({ certSet }: { certSet: boolean }): JSX.Element {
  const { t } = useTranslation();
  const update = useUpdateAppSettings();
  const [mode, setMode] = useState<"pem" | "pfx">("pem");
  const [certPem, setCertPem] = useState("");
  const [keyPem, setKeyPem] = useState("");
  const [pfxBase64, setPfxBase64] = useState("");
  const [pfxName, setPfxName] = useState("");
  const [pfxPassword, setPfxPassword] = useState("");
  const [done, setDone] = useState(false);

  function clearInputs(): void {
    setCertPem("");
    setKeyPem("");
    setPfxBase64("");
    setPfxName("");
    setPfxPassword("");
  }

  function onPfxFile(e: React.ChangeEvent<HTMLInputElement>): void {
    const file = e.target.files?.[0];
    if (!file) return;
    setPfxName(file.name);
    const reader = new FileReader();
    reader.onload = () => {
      const res = typeof reader.result === "string" ? reader.result : "";
      setPfxBase64(res.split(",")[1] ?? "");
    };
    reader.readAsDataURL(file);
  }

  function submit(): void {
    setDone(false);
    const payload: AppSettingsUpdate =
      mode === "pem"
        ? { web_tls_cert_pem: certPem, web_tls_key_pem: keyPem }
        : { web_tls_pfx_base64: pfxBase64, web_tls_pfx_password: pfxPassword || null };
    update.mutate(payload, {
      onSuccess: () => {
        setDone(true);
        clearInputs();
      },
    });
  }

  function removeCert(): void {
    setDone(false);
    update.mutate(
      { web_tls_cert_pem: "", web_tls_key_pem: "" },
      { onSuccess: () => setDone(true) },
    );
  }

  const canSubmit =
    mode === "pem" ? certPem.trim() !== "" && keyPem.trim() !== "" : pfxBase64.length > 0;
  const errorCode = update.isError && update.error instanceof ApiError ? update.error.code : null;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{t("admin.settings.web_tls.title")}</CardTitle>
        <CardDescription>{t("admin.settings.web_tls.desc")}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <p className="text-sm">
          {t("admin.settings.web_tls.status")}:{" "}
          <span className={certSet ? "font-medium text-emerald-700" : "font-medium"}>
            {certSet
              ? t("admin.settings.web_tls.status_custom")
              : t("admin.settings.web_tls.status_selfsigned")}
          </span>
        </p>

        <div className="inline-flex rounded-md border bg-card p-0.5 text-xs">
          {(["pem", "pfx"] as const).map((m) => (
            <button
              key={m}
              type="button"
              onClick={() => setMode(m)}
              className={
                mode === m
                  ? "rounded bg-primary px-3 py-1.5 font-medium text-primary-foreground"
                  : "rounded px-3 py-1.5 text-muted-foreground hover:text-foreground"
              }
            >
              {t(`admin.settings.web_tls.mode_${m}`)}
            </button>
          ))}
        </div>

        {mode === "pem" ? (
          <>
            <div className="space-y-1">
              <Label htmlFor="web-tls-cert">{t("admin.settings.web_tls.cert_label")}</Label>
              <textarea
                id="web-tls-cert"
                value={certPem}
                onChange={(e) => setCertPem(e.target.value)}
                rows={4}
                spellCheck={false}
                placeholder="-----BEGIN CERTIFICATE-----"
                className="w-full rounded-md border border-input bg-background px-3 py-2 font-mono text-xs"
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="web-tls-key">{t("admin.settings.web_tls.key_label")}</Label>
              <textarea
                id="web-tls-key"
                value={keyPem}
                onChange={(e) => setKeyPem(e.target.value)}
                rows={4}
                spellCheck={false}
                placeholder="-----BEGIN PRIVATE KEY-----"
                className="w-full rounded-md border border-input bg-background px-3 py-2 font-mono text-xs"
              />
            </div>
          </>
        ) : (
          <>
            <div className="space-y-1">
              <Label htmlFor="web-tls-pfx">{t("admin.settings.web_tls.pfx_label")}</Label>
              <input
                id="web-tls-pfx"
                type="file"
                accept=".pfx,.p12"
                onChange={onPfxFile}
                className="block text-sm"
              />
              {pfxName ? <p className="text-xs text-muted-foreground">{pfxName}</p> : null}
            </div>
            <div className="space-y-1">
              <Label htmlFor="web-tls-pfx-pw">{t("admin.settings.web_tls.pfx_password")}</Label>
              <Input
                id="web-tls-pfx-pw"
                type="password"
                value={pfxPassword}
                onChange={(e) => setPfxPassword(e.target.value)}
                autoComplete="off"
              />
            </div>
          </>
        )}

        <p className="text-xs text-muted-foreground">{t("admin.settings.web_tls.reload_hint")}</p>

        <div className="flex flex-wrap items-center gap-3">
          <Button type="button" onClick={submit} disabled={!canSubmit || update.isPending}>
            {update.isPending ? t("common.loading") : t("admin.settings.web_tls.import_button")}
          </Button>
          {certSet ? (
            <Button
              type="button"
              variant="outline"
              onClick={removeCert}
              disabled={update.isPending}
            >
              {t("admin.settings.web_tls.remove_button")}
            </Button>
          ) : null}
          {done && !update.isError ? (
            <span className="text-sm text-emerald-700">{t("admin.settings.web_tls.saved")}</span>
          ) : errorCode ? (
            <span className="text-sm text-destructive">
              {t("admin.settings.web_tls.error", { code: errorCode })}
            </span>
          ) : null}
        </div>
      </CardContent>
    </Card>
  );
}
