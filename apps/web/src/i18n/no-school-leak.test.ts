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
