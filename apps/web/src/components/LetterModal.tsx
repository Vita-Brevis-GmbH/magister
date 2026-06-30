import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "@/api/client";
import { downloadLetter, saveBlob } from "@/api/hooks";
import type { LetterRequest, LetterTemplate } from "@/api/types";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export interface LetterTarget {
  ad_object_guid: string;
  display_name: string | null;
  upn: string | null;
}

interface Props {
  target: LetterTarget | null;
  /** Pre-fill `old_class_name` for class_change letters when known. */
  currentClassName?: string | null;
  onClose: () => void;
}

const TEMPLATES: LetterTemplate[] = ["enrollment", "class_change", "password_handout"];

export function LetterModal({ target, currentClassName, onClose }: Props): JSX.Element {
  const { t } = useTranslation();
  const [template, setTemplate] = useState<LetterTemplate>("enrollment");
  const [schoolYear, setSchoolYear] = useState("");
  const [firstDay, setFirstDay] = useState("");
  const [oldClass, setOldClass] = useState("");
  const [effectiveDate, setEffectiveDate] = useState(todayIso());
  const [tempPassword, setTempPassword] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function reset(): void {
    setTemplate("enrollment");
    setSchoolYear("");
    setFirstDay("");
    setOldClass("");
    setEffectiveDate(todayIso());
    setTempPassword("");
    setPending(false);
    setError(null);
  }

  async function handleSubmit(e: FormEvent<HTMLFormElement>): Promise<void> {
    e.preventDefault();
    if (!target) return;
    setError(null);
    setPending(true);
    try {
      const body: LetterRequest = {
        student_guid: target.ad_object_guid,
        ...(template === "enrollment" && {
          school_year: schoolYear,
          first_day: formatDateForLetter(firstDay),
        }),
        ...(template === "class_change" && {
          old_class_name: oldClass || currentClassName || "",
          effective_date: formatDateForLetter(effectiveDate),
        }),
        ...(template === "password_handout" && {
          temp_password: tempPassword,
        }),
      };
      const { blob, filename } = await downloadLetter(template, body);
      saveBlob(blob, filename);
      reset();
      onClose();
    } catch (err) {
      setError(t(err instanceof ApiError ? letterErrorKey(err) : "errors.generic"));
    } finally {
      setPending(false);
    }
  }

  return (
    <Dialog
      open={target !== null}
      onOpenChange={(next) => {
        if (!next) {
          reset();
          onClose();
        }
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("letters.title")}</DialogTitle>
          <DialogDescription>
            {target ? `${target.display_name ?? target.upn ?? ""}` : ""}
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4">
          {error && (
            <div
              role="alert"
              className="rounded-md border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive"
            >
              {error}
            </div>
          )}

          <div className="space-y-1">
            <Label htmlFor="letter-template">{t("letters.template_label")}</Label>
            <select
              id="letter-template"
              value={template}
              onChange={(e) => setTemplate(e.target.value as LetterTemplate)}
              className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
            >
              {TEMPLATES.map((tmpl) => (
                <option key={tmpl} value={tmpl}>
                  {t(`letters.template_${tmpl}`)}
                </option>
              ))}
            </select>
            <p className="text-xs text-muted-foreground">
              {t(`letters.template_${template}_desc`)}
            </p>
          </div>

          {template === "enrollment" && (
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <Label htmlFor="letter-school-year">{t("letters.school_year")}</Label>
                <Input
                  id="letter-school-year"
                  value={schoolYear}
                  onChange={(e) => setSchoolYear(e.target.value)}
                  placeholder={t("letters.school_year_placeholder")}
                  required
                />
              </div>
              <div className="space-y-1">
                <Label htmlFor="letter-first-day">{t("letters.first_day")}</Label>
                <Input
                  id="letter-first-day"
                  type="date"
                  value={firstDay}
                  onChange={(e) => setFirstDay(e.target.value)}
                  required
                />
              </div>
            </div>
          )}

          {template === "class_change" && (
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <Label htmlFor="letter-old-class">{t("letters.old_class")}</Label>
                <Input
                  id="letter-old-class"
                  value={oldClass}
                  onChange={(e) => setOldClass(e.target.value)}
                  placeholder={currentClassName ?? ""}
                  required={!currentClassName}
                />
              </div>
              <div className="space-y-1">
                <Label htmlFor="letter-effective-date">{t("letters.effective_date")}</Label>
                <Input
                  id="letter-effective-date"
                  type="date"
                  value={effectiveDate}
                  onChange={(e) => setEffectiveDate(e.target.value)}
                  required
                />
              </div>
            </div>
          )}

          {template === "password_handout" && (
            <div className="space-y-1">
              <Label htmlFor="letter-temp-password">{t("letters.temp_password")}</Label>
              <Input
                id="letter-temp-password"
                value={tempPassword}
                onChange={(e) => setTempPassword(e.target.value)}
                placeholder={t("letters.temp_password_placeholder")}
                required
              />
              <p className="text-xs text-muted-foreground">{t("letters.temp_password_hint")}</p>
            </div>
          )}

          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => {
                reset();
                onClose();
              }}
            >
              {t("common.cancel")}
            </Button>
            <Button type="submit" disabled={pending}>
              {pending ? t("common.loading") : t("letters.generate_button")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

/** Map a backend error code to a translatable i18n key. */
function letterErrorKey(err: ApiError): string {
  switch (err.code) {
    case "student_not_found":
      return "letters.errors.student_not_found";
    case "unknown_template":
      return "letters.errors.unknown_template";
    case "letter_missing_active_class":
      return "letters.errors.missing_active_class";
    case "letter_missing_school_year_or_first_day":
      return "letters.errors.missing_school_year_or_first_day";
    case "letter_missing_old_class_or_effective_date":
      return "letters.errors.missing_old_class_or_effective_date";
    case "letter_missing_temp_password":
      return "letters.errors.missing_temp_password";
    default:
      return "errors.generic";
  }
}

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

function formatDateForLetter(iso: string): string {
  if (!iso) return "";
  const [y, m, d] = iso.split("-");
  return `${d}.${m}.${y}`;
}
