// Turn a workflow's settings schema into form fields and back into the
// `settings` object the Studio API validates against the real config.

import type { Setting, WorkflowInfo } from './api';

/** One editable value: nested configs are flattened to `parent__child` keys. */
export interface Field {
  key: string;
  setting: Setting;
  group: string | null;
}

export function fieldsOf(settings: Setting[], prefix = '', group: string | null = null): Field[] {
  return settings.flatMap((setting) =>
    setting.type === 'config'
      ? fieldsOf(setting.fields ?? [], `${prefix}${setting.name}__`, setting.name)
      : [{ key: prefix + setting.name, setting, group }],
  );
}

/** Values shown when a workflow is first opened. */
export function defaultsOf(workflow: WorkflowInfo): Record<string, unknown> {
  const values: Record<string, unknown> = {};
  for (const { key, setting } of fieldsOf(workflow.settings)) values[key] = defaultValue(setting, key, workflow);
  return values;
}

function defaultValue(setting: Setting, key: string, workflow: WorkflowInfo): unknown {
  if (!key.includes('__')) return setting.default;
  const parent = workflow.settings.find((s) => s.name === key.split('__')[0]);
  const nested = parent?.default as Record<string, unknown> | undefined;
  return nested?.[setting.name] ?? setting.default;
}

/** Only what differs from the defaults, plus required fields. */
export function changedSettings(
  workflow: WorkflowInfo,
  values: Record<string, unknown>,
): Record<string, unknown> {
  const defaults = defaultsOf(workflow);
  const changed: Record<string, unknown> = {};
  for (const { key, setting } of fieldsOf(workflow.settings)) {
    const value = values[key];
    if (setting.required || JSON.stringify(value) !== JSON.stringify(defaults[key])) {
      changed[key] = value;
    }
  }
  return changed;
}

/** Text shown in an input for a value. */
export function toText(setting: Setting, value: unknown): string {
  if (value === null || value === undefined) return '';
  if (setting.type === 'list' && (setting.items === 'int' || setting.items === 'float' || setting.items === 'str')) {
    return (value as unknown[]).join(', ');
  }
  if (setting.type === 'mapping' || setting.type === 'list') return JSON.stringify(value, null, 2);
  return String(value);
}

/** Parse input text back to a value, or explain why it cannot be. */
export function fromText(setting: Setting, text: string): { value?: unknown; error?: string } {
  const trimmed = text.trim();
  const optional = !setting.required && setting.default === null;
  if (trimmed === '') {
    if (optional) return { value: null };
    if (setting.type === 'str') return { value: '' };
    if (setting.type === 'list' && setting.items !== undefined && setting.items !== 'config') return { value: [] };
    return { error: 'Enter a value.' };
  }
  switch (setting.type) {
    case 'int':
    case 'float': {
      const number = Number(trimmed);
      if (!Number.isFinite(number)) return { error: 'Enter a number.' };
      if (setting.type === 'int' && !Number.isInteger(number)) return { error: 'Enter a whole number.' };
      return { value: number };
    }
    case 'list': {
      if (setting.items === 'config' || setting.items === 'object' || setting.items === undefined) {
        return parseJson(trimmed);
      }
      const parts = trimmed.split(',').map((part) => part.trim()).filter(Boolean);
      if (setting.items === 'str') return { value: parts };
      const numbers = parts.map(Number);
      if (numbers.some((n) => !Number.isFinite(n))) return { error: 'Enter numbers separated by commas.' };
      if (setting.length && numbers.length !== setting.length) {
        return { error: `Enter exactly ${setting.length} numbers.` };
      }
      return { value: numbers };
    }
    case 'mapping':
      return parseJson(trimmed);
    default:
      return { value: trimmed };
  }
}

function parseJson(text: string): { value?: unknown; error?: string } {
  try {
    return { value: JSON.parse(text) };
  } catch {
    return { error: 'Enter valid JSON.' };
  }
}

/** Human label for a field key: `valis__num_features` -> `Num features`. */
export function labelOf(key: string): string {
  const name = key.split('__').pop() ?? key;
  const words = name.replace(/_/g, ' ');
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/** Drop reStructuredText markup from docstring help. */
export function plain(text: string): string {
  return text.replace(/``/g, '').replace(/:(func|class|meth):/g, '').replace(/`/g, '');
}
