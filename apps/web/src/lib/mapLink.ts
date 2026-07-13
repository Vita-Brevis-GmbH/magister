/**
 * OpenStreetMap link/embed helpers for the school location.
 *
 * These build links to openstreetmap.org (opened in a new tab) and an embed
 * URL for an <iframe>. The embed only renders if the viewer's browser may
 * reach openstreetmap.org; the plain links always work as a fallback.
 */

/** Search-by-address link (no coordinates needed). Null if no address parts. */
export function mapSearchUrl(parts: Array<string | null | undefined>): string | null {
  const query = parts
    .map((p) => (p ?? "").trim())
    .filter(Boolean)
    .join(", ");
  if (!query) return null;
  return `https://www.openstreetmap.org/search?query=${encodeURIComponent(query)}`;
}

/** Pin link for exact coordinates. */
export function mapPointUrl(lat: number, lon: number): string {
  return `https://www.openstreetmap.org/?mlat=${lat}&mlon=${lon}#map=16/${lat}/${lon}`;
}

/** Embeddable map (iframe src) centred on a marker at the coordinates. */
export function osmEmbedUrl(lat: number, lon: number): string {
  const d = 0.01;
  const bbox = `${lon - d},${lat - d},${lon + d},${lat + d}`;
  return `https://www.openstreetmap.org/export/embed.html?bbox=${bbox}&layer=mapnik&marker=${lat},${lon}`;
}
