export function getFormField(form, name) {
  if (!form || !name) {
    return null;
  }

  const byNamedItem = typeof form.elements?.namedItem === "function" ? form.elements.namedItem(name) : null;
  if (byNamedItem) {
    return byNamedItem;
  }

  const selectorSafeName = String(name).replace(/\\/gu, "\\\\").replace(/"/gu, '\\"');
  return form.querySelector(`[name="${selectorSafeName}"]`);
}
