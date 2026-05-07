import { describe, expect, it } from "vitest";

import deJson from "./de.json";
import enJson from "./en.json";
import frJson from "./fr.json";
import itJson from "./it.json";

type Catalog = Record<string, unknown>;

function flatten(obj: Catalog, prefix = ""): string[] {
  const out: string[] = [];
  for (const [k, v] of Object.entries(obj)) {
    if (k.startsWith("_")) continue;
    const path = prefix ? `${prefix}.${k}` : k;
    if (v && typeof v === "object" && !Array.isArray(v)) {
      out.push(...flatten(v as Catalog, path));
    } else {
      out.push(path);
    }
  }
  return out;
}

describe("i18n catalogs", () => {
  it("DE is the source of truth and complete", () => {
    const keys = flatten(deJson as Catalog);
    expect(keys.length).toBeGreaterThan(20);
  });

  it("FR / IT / EN have the same set of keys as DE (no missing translations)", () => {
    const expected = new Set(flatten(deJson as Catalog));
    for (const [name, c] of [
      ["en", enJson],
      ["fr", frJson],
      ["it", itJson],
    ] as const) {
      const actual = new Set(flatten(c as Catalog));
      const missing = [...expected].filter((k) => !actual.has(k));
      const extra = [...actual].filter((k) => !expected.has(k));
      expect(missing, `${name} is missing keys`).toEqual([]);
      expect(extra, `${name} has extra keys not in DE`).toEqual([]);
    }
  });
});
