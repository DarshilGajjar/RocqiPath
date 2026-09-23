import { describe, expect, it } from 'vitest';

import type { WorkflowInfo } from '../api';
import { changedSettings, defaultsOf, fieldsOf, fromText } from '../settings';
import catalog from './workflows.json';

const workflows = catalog as unknown as WorkflowInfo[];
const byName = (name: string) => workflows.find((w) => w.name === name)!;

describe('fieldsOf', () => {
  it('flattens nested backend settings into parent__child keys', () => {
    const keys = fieldsOf(byName('align').settings).map((field) => field.key);
    expect(keys).toContain('backend');
    expect(keys).toContain('orb__ransac_threshold');
    expect(keys).toContain('valis__num_features');
    expect(keys).not.toContain('qc_output_dir');
  });
});

describe('changedSettings', () => {
  it('sends only values that differ from the defaults', () => {
    const align = byName('align');
    const values = { ...defaultsOf(align), backend: 'orb', orb__ransac_threshold: 12 };
    expect(changedSettings(align, values)).toEqual({ backend: 'orb', orb__ransac_threshold: 12 });
  });

  it('uses nested defaults from the parent config', () => {
    expect(defaultsOf(byName('align'))['orb__ransac_threshold']).toBe(20);
  });
});

describe('fromText', () => {
  const setting = (overrides: object) =>
    ({ name: 'x', type: 'float', default: 1, required: false, choices: null, advanced: false, local_only: false, help: '', doc: '', ...overrides }) as never;

  it('parses numbers and rejects text', () => {
    expect(fromText(setting({}), '2.5')).toEqual({ value: 2.5 });
    expect(fromText(setting({}), 'abc').error).toBeDefined();
    expect(fromText(setting({ type: 'int' }), '2.5').error).toBeDefined();
  });

  it('treats an empty optional value as automatic', () => {
    expect(fromText(setting({ default: null }), '')).toEqual({ value: null });
  });

  it('parses comma lists with a fixed length', () => {
    const tuple = setting({ type: 'list', items: 'int', length: 2, default: [8, 8] });
    expect(fromText(tuple, '4, 4')).toEqual({ value: [4, 4] });
    expect(fromText(tuple, '4').error).toBeDefined();
  });

  it('parses JSON for structured settings', () => {
    const mapping = setting({ type: 'mapping', default: null, required: true });
    expect(fromText(mapping, '{"he": {"color": [0, 0, 255]}}').value).toEqual({ he: { color: [0, 0, 255] } });
    expect(fromText(mapping, '{nope').error).toBeDefined();
  });
});
