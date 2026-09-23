import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { api, type WorkflowInfo } from '../api';
import { WorkflowForm, type Sources } from '../components/WorkflowForm';
import { fieldsOf, labelOf } from '../settings';
import catalog from './workflows.json';

const workflows = catalog as unknown as WorkflowInfo[];
const sources: Sources = {
  slides: [{ id: 's1', name: 'case01_HE.svs', path: '/x', folder_id: 'f', relative: 'x', size: 1, format: 'SVS', demo: false }],
  folders: [],
  jobs: [],
};

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe.each(workflows.map((w) => [w.name, w] as const))('%s form', (_name, workflow) => {
  it('renders a labelled control for every setting', () => {
    render(<WorkflowForm workflow={workflow} sources={sources} onSubmitted={() => {}} />);
    const fields = fieldsOf(workflow.settings);
    for (const field of fields.filter((f) => !f.setting.advanced && f.group === null)) {
      expect(screen.getByLabelText(new RegExp(`^${labelOf(field.key)}`))).toBeTruthy();
    }
    const hidden = fields.filter((f) => f.setting.advanced || f.group !== null);
    if (hidden.length) {
      fireEvent.click(screen.getByRole('button', { name: /show advanced settings/i }));
      expect(screen.getAllByLabelText(/./).length).toBeGreaterThanOrEqual(fields.length);
    }
  });
});

describe('submitting', () => {
  const count = workflows.find((w) => w.name === 'count_cells')!;

  it('asks for an input first', () => {
    render(<WorkflowForm workflow={count} sources={sources} onSubmitted={() => {}} />);
    fireEvent.click(screen.getByRole('button', { name: /^run/i }));
    expect(screen.getByRole('alert').textContent).toMatch(/at least one input/);
  });

  it('sends the inputs and only the changed settings', async () => {
    const submit = vi.spyOn(api, 'submit').mockResolvedValue({ id: 'j1' } as never);
    const onSubmitted = vi.fn();
    render(
      <WorkflowForm workflow={count} sources={sources} initialInputs={[{ kind: 'slide', id: 's1' }]} onSubmitted={onSubmitted} />,
    );
    fireEvent.change(screen.getByLabelText(/^Label/), { target: { value: 'CD8' } });
    fireEvent.change(screen.getByLabelText(/^Min cell area/), { target: { value: '30' } });
    fireEvent.click(screen.getByRole('button', { name: /^run/i }));
    await waitFor(() => expect(onSubmitted).toHaveBeenCalled());
    expect(submit).toHaveBeenCalledWith({
      workflow: 'count_cells',
      inputs: [{ kind: 'slide', id: 's1' }],
      options: {},
      settings: { label: 'CD8', min_cell_area: 30 },
    });
  });

  it('blocks submission while a setting is invalid', () => {
    const submit = vi.spyOn(api, 'submit');
    render(<WorkflowForm workflow={count} sources={sources} initialInputs={[{ kind: 'slide', id: 's1' }]} onSubmitted={() => {}} />);
    fireEvent.change(screen.getByLabelText(/^Patch size/), { target: { value: 'big' } });
    fireEvent.click(screen.getByRole('button', { name: /^run/i }));
    expect(screen.getByRole('alert').textContent).toMatch(/Fix the highlighted settings/);
    expect(submit).not.toHaveBeenCalled();
  });
});
