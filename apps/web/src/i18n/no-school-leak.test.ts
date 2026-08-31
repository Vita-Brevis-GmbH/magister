import { describe, expect, it } from "vitest";

import deJson from "./de.json";
import enJson from "./en.json";
import frJson from "./fr.json";
import itJson from "./it.json";

type Catalog = Record<string, unknown>;

/**
 * M6 hard-separation guard (ADR-0009): the SHARED feature modules render in
 * BOTH the school and the company edition, so every unit label they show MUST
 * come from the term-pack ({{unit}} / {{unit_plural}}, resolved by `useTerms`),
 * never a hardcoded "Schule"/"Schulen". A hardcoded school word in one of these
 * namespaces is exactly the school→company bleed we are eliminating, so it
 * fails CI here.
 *
 * School-only modules (classes, letters) keep their school vocabulary — they
 * never mount in the company edition — and the `terms.*` block is the term-pack
 * definition itself, so both are out of scope for this guard.
 */
const SHARED_NAMESPACES = ["devices", "dashboard", "reports"] as const;

/**
 * Per-locale forbidden substrings (lower-cased). The plain unit words come from
 * each locale's own `terms.school` block so the guard auto-follows the term-pack;
 * German additionally bans the "schul" stem to catch compound leaks like
 * "Schul-Scope" / "Schulhaus" that don't contain the bare word "Schule".
 */
const EXTRA_STEMS: Record<string, string[]> = {
  de: ["schul"],
};

/**
 * Key-path substrings exempt from the guard: sub-features that live inside a
 * shared namespace but are themselves school-only and gated out of the company
 * edition at render time (e.g. the "Schüler pro Schuljahr" report only mounts
 * when the classes module is on). Their labels legitimately use school-domain
 * vocabulary — that is not unit bleed.
 */
const EXEMPT_PATH_SUBSTRINGS = ["school_year"];

function collectStrings(
  obj: Catalog,
  prefix: string,
  out: { path: string; value: string }[],
): void {
  for (const [k, v] of Object.entries(obj)) {
    const path = prefix ? `${prefix}.${k}` : k;
    if (v && typeof v === "object" && !Array.isArray(v)) {
      collectStrings(v as Catalog, path, out);
    } else if (typeof v === "string") {
      out.push({ path, value: v });
    }
  }
}

/**
 * Edition-neutral keys: strings that DO render in the company edition (page
 * headers, /me, audit, imports, privacy modal, danger zone, Standort delete,
 * user list + status modal, department placeholder). Each MUST read from the
 * term-pack or stay generic — never a hardcoded school word. This list is the
 * regression guard for the company-mode text audit: adding a school word back
 * to any of these keys fails CI here, in every locale.
 *
 * NOT guarded (deliberately): keys that only render in school-only branches
 * even though they live in a company-visible namespace — e.g.
 * `admin.settings.provisioning_section_desc` (the school variant; the company
 * edition renders `…_company`), or the student/grade fields gated on
 * `kind === "student"`.
 */
const EDITION_NEUTRAL_KEYS = [
  "app.tagline",
  "auth.login_intro",
  "auth.school_scope",
  "audit.intro",
  "imports.intro",
  "imports.credentials_hint",
  "privacy.section_school",
  "privacy.section_memberships",
  "privacy.section_teacher_roles",
  "departments.name_placeholder",
  "users.intro",
  "user_status.reason_placeholder",
  "user_status.consequence_disable",
  "admin.settings.oidc_section_desc",
  "admin.settings.provisioning_section_desc_company",
  "admin.settings.provisioning_perschool_hint",
  "admin.settings.password_store_hint",
  "admin.settings.purge_demo_desc",
  "admin.settings.purge_demo_ok",
  "schools.delete_title",
  "schools.delete_confirm",
  "schools.error_in_use",
  "schools.ad_config.ou_section_desc",
] as const;

/** School-domain stems per locale — the unit/member/group/lead vocabulary that
 *  must not appear literally in an edition-neutral string. */
const GUARD_STEMS: Record<string, string[]> = {
  de: ["schul", "schüler", "klasse", "lehr"],
  en: ["school", "student", "class", "teacher"],
  fr: ["école", "élève", "classe", "enseignant"],
  it: ["scuola", "studente", "classe", "docente"],
};

function lookup(cat: Catalog, path: string): string | undefined {
  let node: unknown = cat;
  for (const part of path.split(".")) {
    if (node && typeof node === "object" && part in (node as Catalog)) {
      node = (node as Catalog)[part];
    } else {
      return undefined;
    }
  }
  return typeof node === "string" ? node : undefined;
}

describe("edition-neutral keys carry no hardcoded school vocabulary", () => {
  const locales: [string, Catalog][] = [
    ["de", deJson as Catalog],
    ["en", enJson as Catalog],
    ["fr", frJson as Catalog],
    ["it", itJson as Catalog],
  ];
  for (const [loc, cat] of locales) {
    const stems = GUARD_STEMS[loc];
    it(`${loc}: every edition-neutral key is term-pack or generic`, () => {
      const leaks: { key: string; value: string }[] = [];
      for (const key of EDITION_NEUTRAL_KEYS) {
        const value = lookup(cat, key);
        expect(value, `${loc}: missing edition-neutral key ${key}`).toBeDefined();
        // Term-pack placeholders ({{unit}}, {{classes}}, …) are not leaks.
        const literal = (value ?? "").replace(/\{\{[^}]*\}\}/g, "").toLowerCase();
        if (stems.some((s) => literal.includes(s))) leaks.push({ key, value: value ?? "" });
      }
      expect(
        leaks,
        `${loc}: hardcoded school word in an edition-neutral key — use the term-pack or a generic word`,
      ).toEqual([]);
    });
  }
});

describe("shared modules use the term-pack, never a hardcoded school word", () => {
  const locales: [string, Catalog][] = [
    ["de", deJson as Catalog],
    ["en", enJson as Catalog],
    ["fr", frJson as Catalog],
    ["it", itJson as Catalog],
  ];

  for (const [loc, cat] of locales) {
    const school = ((cat.terms as Catalog).school ?? {}) as Record<string, string>;
    const forbidden = [school.unit, school.unit_plural, ...(EXTRA_STEMS[loc] ?? [])]
      .filter(Boolean)
      .map((s) => s.toLowerCase());

    for (const ns of SHARED_NAMESPACES) {
      it(`${loc}: "${ns}" carries no hardcoded school vocabulary`, () => {
        const strings: { path: string; value: string }[] = [];
        collectStrings((cat[ns] ?? {}) as Catalog, ns, strings);
        const leaks = strings.filter(({ path, value }) => {
          if (EXEMPT_PATH_SUBSTRINGS.some((p) => path.includes(p))) return false;
          const lower = value.toLowerCase();
          return forbidden.some((w) => lower.includes(w));
        });
        expect(
          leaks,
          `hardcoded school word in ${loc}/${ns} — use the term-pack {{unit}} instead`,
        ).toEqual([]);
      });
    }
  }
});
