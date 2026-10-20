export const fmt = (v: number | null | undefined, d = 2, unit = "") =>
  v === null || v === undefined || Number.isNaN(v) ? "—" : `${v.toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d })}${unit}`;
export const int = (v: number | null | undefined) => (v === null || v === undefined ? "—" : v.toLocaleString());
