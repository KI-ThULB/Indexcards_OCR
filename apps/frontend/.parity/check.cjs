// src/features/results/groupValue.ts
function childNames(group2) {
  return (group2.fields ?? []).map((child) => child.name);
}

// .parity/check.ts
var group = {
  description: null,
  max_items: 20,
  fields: [{ name: "Lfd_Nr" }, { name: "Titel" }, { name: "Spieldauer" }]
};
function groupColumns(label, g) {
  const children = childNames(g);
  const columns = [`${label}_count`];
  for (let i = 1; i <= g.max_items; i++) {
    for (const child of children) {
      const base = `${label}_${i}_${child}`;
      columns.push(`${base}_ocr`, `${base}_edited`, `${base}_confidence`);
    }
  }
  columns.push(`${label}_overflow_json`);
  return columns;
}
console.log(JSON.stringify(groupColumns("Titel_Tracks", group)));
