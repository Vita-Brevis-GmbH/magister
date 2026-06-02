import { useTranslation } from "react-i18next";

import { subjectAccessCsvUrl, useSubjectAccess } from "@/api/hooks";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

interface Props {
  guid: string | null;
  onClose: () => void;
}

export function SubjectAccessModal({ guid, onClose }: Props): JSX.Element {
  const { t } = useTranslation();
  const q = useSubjectAccess(guid);

  return (
    <Dialog
      open={guid !== null}
      onOpenChange={(next) => {
        if (!next) onClose();
      }}
    >
      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle>{t("privacy.title")}</DialogTitle>
          <DialogDescription>{t("privacy.description")}</DialogDescription>
        </DialogHeader>

        {q.isLoading ? (
          <p>{t("common.loading")}</p>
        ) : q.isError ? (
          <p className="rounded-md border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive">
            {t("errors.generic")}
          </p>
        ) : q.data ? (
          <div className="max-h-[60vh] space-y-4 overflow-y-auto">
            <Section title={t("privacy.section_identity")}>
              <KvList data={q.data.user} />
            </Section>

            {q.data.school && (
              <Section title={t("privacy.section_school")}>
                <KvList data={q.data.school as Record<string, unknown>} />
              </Section>
            )}

            <Section title={t("privacy.section_memberships", { count: q.data.memberships.length })}>
              {q.data.memberships.length === 0 ? (
                <p className="text-sm text-muted-foreground">{t("privacy.none")}</p>
              ) : (
                <Pre data={q.data.memberships} />
              )}
            </Section>

            <Section
              title={t("privacy.section_teacher_roles", {
                count: q.data.teacher_roles.length,
              })}
            >
              {q.data.teacher_roles.length === 0 ? (
                <p className="text-sm text-muted-foreground">{t("privacy.none")}</p>
              ) : (
                <Pre data={q.data.teacher_roles} />
              )}
            </Section>

            <Section title={t("privacy.section_audit", { count: q.data.audit_events.length })}>
              {q.data.audit_events.length === 0 ? (
                <p className="text-sm text-muted-foreground">{t("privacy.none")}</p>
              ) : (
                <div className="space-y-1">
                  {q.data.audit_events.slice(0, 100).map((ev) => (
                    <div key={ev.id} className="rounded-md border bg-muted/30 px-3 py-2 text-xs">
                      <div className="flex justify-between text-muted-foreground">
                        <span>{new Date(ev.ts).toLocaleString()}</span>
                        <span className="font-medium">
                          {ev.role === "actor" ? t("privacy.role_actor") : t("privacy.role_target")}
                        </span>
                      </div>
                      <div className="mt-0.5">
                        <code className="text-xs">{ev.action}</code> ·{" "}
                        <span className="text-muted-foreground">
                          {ev.target_kind}/{ev.target_id.slice(0, 8)}…
                        </span>
                      </div>
                    </div>
                  ))}
                  {q.data.audit_events.length > 100 && (
                    <p className="text-xs text-muted-foreground">
                      {t("privacy.audit_truncated", { total: q.data.audit_events.length })}
                    </p>
                  )}
                </div>
              )}
            </Section>
          </div>
        ) : null}

        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            {t("common.close")}
          </Button>
          {guid && (
            <a
              href={subjectAccessCsvUrl(guid)}
              download={`subject-access-${guid}.csv`}
              className="inline-flex h-10 items-center justify-center rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90"
            >
              ⬇ {t("privacy.download_csv")}
            </a>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }): JSX.Element {
  return (
    <section className="space-y-1">
      <h3 className="text-sm font-semibold">{title}</h3>
      {children}
    </section>
  );
}

function KvList({ data }: { data: Record<string, unknown> }): JSX.Element {
  const entries = Object.entries(data).filter(([, v]) => v !== null && v !== "");
  return (
    <div className="grid grid-cols-1 gap-x-3 gap-y-0.5 rounded-md border bg-muted/30 px-3 py-2 text-xs sm:grid-cols-2">
      {entries.map(([k, v]) => (
        <div key={k} className="flex gap-2">
          <span className="text-muted-foreground">{k}:</span>
          <span className="break-all font-mono">{String(v)}</span>
        </div>
      ))}
    </div>
  );
}

function Pre({ data }: { data: unknown }): JSX.Element {
  return (
    <pre className="overflow-x-auto rounded-md border bg-muted/30 px-3 py-2 text-xs">
      {JSON.stringify(data, null, 2)}
    </pre>
  );
}
