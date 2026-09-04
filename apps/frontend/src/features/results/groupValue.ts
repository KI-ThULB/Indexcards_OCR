import type { FieldGroup } from '../../api/batchesApi';

/**
 * Shared helpers for the repeatable-group wire format.
 *
 * A group's value travels as a canonical JSON array serialised into a string in
 * `data[groupLabel]`, because the result model is `Record<string, string>` and
 * cannot hold nested values. Curator edits store the whole edited array under
 * `edited_data[groupLabel]`. These helpers are the single place that knows that,
 * so the Verify pane, the results table and the CSV exporter cannot disagree.
 */

export type GroupItem = Record<string, string>;

/** Parse a stored group value. Tolerant: a corrupt cell reads as "no entries". */
export function parseGroup(raw: string | undefined | null): GroupItem[] {
  if (!raw) return [];
  try {
    const parsed = JSON.parse(raw);
    if (Array.isArray(parsed)) {
      return parsed.filter((item) => item && typeof item === 'object' && !Array.isArray(item));
    }
    if (parsed && typeof parsed === 'object') return [parsed as GroupItem];
    return [];
  } catch {
    return [];
  }
}

/** Serialise items the same way the backend does, so values round-trip unchanged. */
export function serialiseGroup(items: GroupItem[]): string {
  return JSON.stringify(items);
}

/** The child field names of a group, in template order. */
export function childNames(group: FieldGroup): string[] {
  return (group.fields ?? []).map((child) => child.name);
}

/**
 * What the curator currently sees: the edited array when one exists, else the
 * raw extraction. Mirrors `effective_items` on the backend.
 */
export function effectiveItems(
  data: Record<string, string>,
  editedData: Record<string, string> | undefined,
  label: string
): GroupItem[] {
  const edited = editedData?.[label];
  if (edited !== undefined && edited !== '') return parseGroup(edited);
  return parseGroup(data?.[label]);
}

/** The flattened confidence key for one child of one entry. */
export function childConfidenceKey(label: string, index: number, child: string): string {
  return `${label}[${index}].${child}`;
}

/** True when this field label is a repeatable group in the given configuration. */
export function isGroupField(
  label: string,
  fieldGroups: Record<string, FieldGroup> | null | undefined
): boolean {
  const group = fieldGroups?.[label];
  return !!group && (group.fields ?? []).length > 0;
}

/**
 * True when a cell value is a serialised group array.
 *
 * Used where the group configuration is not at hand (the results table renders
 * whatever fields it is given), so the shape is detected rather than looked up.
 */
export function looksLikeGroupValue(value: string | undefined | null): boolean {
  if (!value) return false;
  const trimmed = value.trim();
  if (!trimmed.startsWith('[')) return false;
  try {
    const parsed = JSON.parse(trimmed);
    if (!Array.isArray(parsed)) return false;
    // A group value is an array of child *objects*. Requiring that keeps a
    // legacy scalar value which merely parses as an array — an editorial date
    // such as "[1953]" — out of the group path, where parseGroup would drop its
    // non-object element and the cell would summarise to nothing. An empty
    // array stays a group: [].every() is true.
    return parsed.every(
      (item) => item && typeof item === 'object' && !Array.isArray(item)
    );
  } catch {
    return false;
  }
}
