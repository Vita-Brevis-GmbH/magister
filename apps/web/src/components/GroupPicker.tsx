import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type { AdGroupOut } from "@/api/types";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

/** Checkbox picker over the synced AD group catalog. Any selected DN that is
 *  not (yet) in the catalog is still shown as a checked row so an existing
 *  selection is never silently dropped. Shared by the per-school AD-config
 *  group templates and the per-user group editor. */
export function GroupPicker({
  label,
  hint,
  catalog,
  selected,
  onChange,
}: {
  label?: string;
  hint?: string;
  catalog: AdGroupOut[];
  selected: string[];
  onChange: (next: string[]) => void;
}): JSX.Element {
  const { t } = useTranslation();
  const [filter, setFilter] = useState("");

  // Union of catalog DNs + any already-selected DN missing from the catalog.
  const rows = useMemo(() => {
    const byDn = new Map<string, { dn: string; cn: string; inCatalog: boolean }>();
    for (const g of catalog) {
      byDn.set(g.distinguished_name, { dn: g.distinguished_name, cn: g.cn, inCatalog: true });
    }
    for (const dn of selected) {
      if (!byDn.has(dn)) {
        const cn = dn.startsWith("CN=") ? dn.slice(3).split(",")[0] : dn;
        byDn.set(dn, { dn, cn, inCatalog: false });
      }
    }
    return [...byDn.values()].sort((a, b) => a.cn.localeCompare(b.cn));
  }, [catalog, selected]);

  const needle = filter.trim().toLowerCase();
  const visible = needle
    ? rows.filter((r) => r.cn.toLowerCase().includes(needle) || r.dn.toLowerCase().includes(needle))
    : rows;

  function toggle(dn: string, checked: boolean): void {
    onChange(checked ? [...selected, dn] : selected.filter((d) => d !== dn));
  }

  return (
    <div className="space-y-1">
      {label ? <Label>{label}</Label> : null}
      {hint ? <p className="text-xs text-muted-foreground">{hint}</p> : null}
      {rows.length > 8 ? (
        <Input
          className="mb-1 h-8"
          placeholder={t("admin.user_settings.group_filter")}
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        />
      ) : null}
      <div className="max-h-48 space-y-1 overflow-y-auto rounded-md border p-2">
        {rows.length === 0 ? (
          <p className="px-1 py-2 text-xs text-muted-foreground">
            {t("admin.user_settings.group_empty")}
          </p>
        ) : visible.length === 0 ? (
          <p className="px-1 py-2 text-xs text-muted-foreground">
            {t("admin.user_settings.group_no_match")}
          </p>
        ) : (
          visible.map((r) => {
            const checked = selected.includes(r.dn);
            return (
              <label key={r.dn} className="flex items-start gap-2 text-sm">
                <input
                  type="checkbox"
                  className="mt-0.5 h-4 w-4 rounded border-input"
                  checked={checked}
                  onChange={(e) => toggle(r.dn, e.target.checked)}
                />
                <span className="min-w-0">
                  <span className="font-medium">{r.cn}</span>
                  {!r.inCatalog ? (
                    <span className="ml-1 text-xs text-amber-600">
                      {t("admin.user_settings.group_not_synced")}
                    </span>
                  ) : null}
                  <span className="block truncate font-mono text-xs text-muted-foreground">
                    {r.dn}
                  </span>
                </span>
              </label>
            );
          })
        )}
      </div>
      <p className="text-xs text-muted-foreground">
        {t("admin.user_settings.group_selected_count", { count: selected.length })}
      </p>
    </div>
  );
}
