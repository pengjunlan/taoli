export function parseMoney(value) {
  const normalized = String(value || "")
    .trim()
    .toUpperCase()
    .replaceAll("$", "")
    .replaceAll(",", "");
  if (!normalized) return 0;
  if (normalized.endsWith("K")) return Number(normalized.slice(0, -1)) * 1000;
  if (normalized.endsWith("M")) return Number(normalized.slice(0, -1)) * 1000000;
  return Number(normalized);
}

export function formatMoney(value) {
  const amount = Number(value || 0);
  if (amount >= 1000000) {
    return `$${(amount / 1000000).toFixed(2).replace(/\.?0+$/, "")}M`;
  }
  if (amount >= 1000) {
    return `$${(amount / 1000).toFixed(amount % 1000 === 0 ? 0 : 1).replace(/\.?0+$/, "")}K`;
  }
  return `$${amount.toFixed(2).replace(/\.?0+$/, "")}`;
}

export function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}
