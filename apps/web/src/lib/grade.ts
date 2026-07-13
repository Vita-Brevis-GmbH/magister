/**
 * Grade-level display helpers.
 *
 * Grades are stored numerically: -1 = 1. Kindergarten, 0 = 2. Kindergarten,
 * 1..13 = Klassen. A class may span a range (jahrgangsstufe .. jahrgangsstufe_bis);
 * a null/absent upper bound means a single-grade class.
 */

/** Label a single grade value. KG years render as "KG1"/"KG2". */
export function gradeLabel(n: number): string {
  if (n === -1) return "KG1";
  if (n === 0) return "KG2";
  return String(n);
}

/** Label a (possibly single) grade range, e.g. "3", "1–3", "KG1–1". */
export function gradeRangeLabel(von: number, bis?: number | null): string {
  if (bis == null || bis === von) return gradeLabel(von);
  return `${gradeLabel(von)}–${gradeLabel(bis)}`;
}
