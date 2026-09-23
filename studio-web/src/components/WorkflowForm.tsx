import { useMemo, useState } from 'react';

import { api, type Folder, type InputRef, type Job, type Setting, type Slide, type WorkflowInfo } from '../api';
import { changedSettings, defaultsOf, fieldsOf, fromText, labelOf, plain, toText, type Field } from '../settings';
import { Button, ErrorNote } from './ui';

export interface Sources {
  slides: Slide[];
  folders: Folder[];
  jobs: Job[];
}

interface WorkflowFormProps {
  workflow: WorkflowInfo;
  sources: Sources;
  initialInputs?: InputRef[];
  onSubmitted: (job: Job) => void;
}

/** One form for every workflow, generated from its settings schema. */
export function WorkflowForm({ workflow, sources, initialInputs = [], onSubmitted }: WorkflowFormProps) {
  const fields = useMemo(() => fieldsOf(workflow.settings), [workflow]);
  const [values, setValues] = useState<Record<string, unknown>>(() => defaultsOf(workflow));
  const [texts, setTexts] = useState<Record<string, string>>(() =>
    Object.fromEntries(fields.map(({ key, setting }) => [key, toText(setting, defaultsOf(workflow)[key])])),
  );
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [inputs, setInputs] = useState<InputRef[]>(initialInputs);
  const [options, setOptions] = useState<Record<string, InputRef | undefined>>({});
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const basic = fields.filter((field) => !field.setting.advanced && field.group === null);
  const advanced = fields.filter((field) => field.setting.advanced || field.group !== null);

  function setText(field: Field, text: string) {
    setTexts((current) => ({ ...current, [field.key]: text }));
    const parsed = fromText(field.setting, text);
    setErrors((current) => {
      const next = { ...current };
      if (parsed.error) next[field.key] = parsed.error;
      else delete next[field.key];
      return next;
    });
    if (!parsed.error) setValues((current) => ({ ...current, [field.key]: parsed.value }));
  }

  function setValue(key: string, value: unknown) {
    setValues((current) => ({ ...current, [key]: value }));
  }

  async function submit() {
    setSubmitError(null);
    if (inputs.length === 0) {
      setSubmitError('Choose at least one input.');
      return;
    }
    if (Object.keys(errors).length > 0) {
      setSubmitError('Fix the highlighted settings first.');
      return;
    }
    setSubmitting(true);
    try {
      const chosenOptions = Object.fromEntries(
        Object.entries(options).filter((entry): entry is [string, InputRef] => entry[1] !== undefined),
      );
      const job = await api.submit({
        workflow: workflow.name,
        inputs,
        options: chosenOptions,
        settings: changedSettings(workflow, values),
      });
      onSubmitted(job);
    } catch (exc) {
      setSubmitError((exc as Error).message);
    } finally {
      setSubmitting(false);
    }
  }

  const groups = new Map<string | null, Field[]>();
  for (const field of advanced) groups.set(field.group, [...(groups.get(field.group) ?? []), field]);

  return (
    <form
      aria-label={`${workflow.label} settings`}
      onSubmit={(event) => {
        event.preventDefault();
        void submit();
      }}
      className="space-y-6"
    >
      <fieldset className="space-y-2">
        <legend className="font-serif text-lg">Inputs</legend>
        <p className="text-sm text-muted">{plain(workflow.inputs.help || workflow.inputs.kind)}</p>
        <InputList refs={inputs} onChange={setInputs} sources={sources} />
      </fieldset>

      {workflow.options.map((option) => (
        <fieldset key={option.name} className="space-y-2">
          <legend className="font-serif text-lg">{labelOf(option.name)}</legend>
          <p className="text-sm text-muted">{plain(option.help)}</p>
          <SourceSelect
            label={labelOf(option.name)}
            sources={sources}
            value={options[option.name]}
            onChange={(ref) => setOptions((current) => ({ ...current, [option.name]: ref }))}
          />
        </fieldset>
      ))}

      <fieldset className="space-y-4">
        <legend className="font-serif text-lg">Settings</legend>
        <div className="grid gap-4 sm:grid-cols-2">
          {basic.map((field) => (
            <SettingControl
              key={field.key}
              field={field}
              value={values[field.key]}
              text={texts[field.key] ?? ''}
              error={errors[field.key]}
              onText={(text) => setText(field, text)}
              onValue={(value) => setValue(field.key, value)}
            />
          ))}
        </div>
        {advanced.length > 0 && (
          <div>
            <Button tone="ghost" aria-expanded={showAdvanced} onClick={() => setShowAdvanced((open) => !open)}>
              {showAdvanced ? 'Hide' : 'Show'} advanced settings ({advanced.length})
            </Button>
            {showAdvanced &&
              [...groups.entries()].map(([group, groupFields]) => (
                <div key={group ?? 'advanced'} className="mt-3 rounded-xl border border-line p-4">
                  <h3 className="mb-3 text-sm font-semibold text-muted">
                    {group ? `${labelOf(group)} backend` : 'Advanced'}
                  </h3>
                  <div className="grid gap-4 sm:grid-cols-2">
                    {groupFields.map((field) => (
                      <SettingControl
                        key={field.key}
                        field={field}
                        value={values[field.key]}
                        text={texts[field.key] ?? ''}
                        error={errors[field.key]}
                        onText={(text) => setText(field, text)}
                        onValue={(value) => setValue(field.key, value)}
                      />
                    ))}
                  </div>
                </div>
              ))}
          </div>
        )}
      </fieldset>

      <ErrorNote message={submitError} />
      <div className="flex items-center gap-3">
        <Button type="submit" tone="primary" disabled={submitting || !workflow.available}>
          {submitting ? 'Starting…' : `Run ${workflow.label.toLowerCase()}`}
        </Button>
        {!workflow.available && (
          <span className="text-sm text-warn">Install rocqipath[{workflow.extra}] to run this workflow.</span>
        )}
      </div>
    </form>
  );
}

interface SettingControlProps {
  field: Field;
  value: unknown;
  text: string;
  error?: string;
  onText: (text: string) => void;
  onValue: (value: unknown) => void;
}

function SettingControl({ field, value, text, error, onText, onValue }: SettingControlProps) {
  const { key, setting } = field;
  const id = `setting-${key}`;
  const help = plain(setting.help);
  const describedBy = error ? `${id}-error` : help ? `${id}-help` : undefined;
  const wide = setting.type === 'mapping' || (setting.type === 'list' && isJsonList(setting));

  if (setting.type === 'bool') {
    return (
      <div className="flex gap-3 sm:col-span-2">
        <input
          id={id}
          type="checkbox"
          checked={Boolean(value)}
          onChange={(event) => onValue(event.target.checked)}
          aria-describedby={describedBy}
          className="mt-1 h-4 w-4 accent-[var(--color-plum)]"
        />
        <div>
          <label htmlFor={id} className="text-sm font-medium">
            {labelOf(key)}
          </label>
          {help && (
            <p id={`${id}-help`} className="text-xs text-muted">
              {help}
            </p>
          )}
        </div>
      </div>
    );
  }

  const inputClass = `w-full rounded-lg border bg-panel px-3 py-1.5 text-sm ${error ? 'border-bad' : 'border-line'}`;
  return (
    <div className={wide ? 'sm:col-span-2' : ''}>
      <label htmlFor={id} className="mb-1 block text-sm font-medium">
        {labelOf(key)}
        {setting.required && <span className="text-bad"> *</span>}
      </label>
      {setting.type === 'choice' ? (
        <select
          id={id}
          value={String(value ?? '')}
          onChange={(event) => onValue(setting.choices?.find((choice) => String(choice) === event.target.value))}
          aria-describedby={describedBy}
          className={inputClass}
        >
          {(setting.choices ?? []).map((choice) => (
            <option key={String(choice)} value={String(choice)}>
              {String(choice)}
            </option>
          ))}
        </select>
      ) : wide ? (
        <textarea
          id={id}
          value={text}
          rows={4}
          onChange={(event) => onText(event.target.value)}
          aria-describedby={describedBy}
          aria-invalid={Boolean(error)}
          className={`${inputClass} font-mono`}
          placeholder="JSON"
        />
      ) : (
        <input
          id={id}
          value={text}
          inputMode={setting.type === 'int' || setting.type === 'float' ? 'decimal' : undefined}
          onChange={(event) => onText(event.target.value)}
          aria-describedby={describedBy}
          aria-invalid={Boolean(error)}
          placeholder={setting.default === null ? 'Automatic' : setting.type === 'list' ? 'a, b, c' : undefined}
          className={inputClass}
        />
      )}
      {error ? (
        <p id={`${id}-error`} className="mt-1 text-xs text-bad">
          {error}
        </p>
      ) : (
        help && (
          <p id={`${id}-help`} className="mt-1 text-xs text-muted">
            {help}
          </p>
        )
      )}
    </div>
  );
}

function isJsonList(setting: Setting): boolean {
  return setting.items === undefined || setting.items === 'config' || setting.items === 'object';
}

function refKey(ref: InputRef): string {
  return `${ref.kind}:${ref.id}`;
}

function describeRef(ref: InputRef, sources: Sources): string {
  if (ref.kind === 'slide') return sources.slides.find((s) => s.id === ref.id)?.name ?? 'Missing slide';
  if (ref.kind === 'folder') return `Folder: ${sources.folders.find((f) => f.id === ref.id)?.name ?? 'missing'}`;
  const job = sources.jobs.find((j) => j.id === ref.id);
  return job ? `Output of ${labelOf(job.workflow).toLowerCase()} (${job.id.slice(0, 6)})` : 'Missing job';
}

function InputList({ refs, onChange, sources }: { refs: InputRef[]; onChange: (refs: InputRef[]) => void; sources: Sources }) {
  return (
    <div className="space-y-2">
      {refs.length > 0 && (
        <ol className="flex flex-wrap gap-2">
          {refs.map((ref, index) => (
            <li key={refKey(ref)} className="flex items-center gap-1.5 rounded-full border border-line bg-panel py-1 pl-3 pr-1 text-sm">
              <span className="text-xs text-muted">{index + 1}.</span>
              {describeRef(ref, sources)}
              <button
                type="button"
                aria-label={`Remove ${describeRef(ref, sources)}`}
                className="rounded-full px-2 text-muted hover:bg-bad/10 hover:text-bad"
                onClick={() => onChange(refs.filter((_, i) => i !== index))}
              >
                ×
              </button>
            </li>
          ))}
        </ol>
      )}
      <SourceSelect
        label="Add input"
        sources={sources}
        value={undefined}
        exclude={refs}
        onChange={(ref) => ref && onChange([...refs, ref])}
      />
    </div>
  );
}

function SourceSelect({
  label,
  sources,
  value,
  exclude = [],
  onChange,
}: {
  label: string;
  sources: Sources;
  value: InputRef | undefined;
  exclude?: InputRef[];
  onChange: (ref: InputRef | undefined) => void;
}) {
  const taken = new Set(exclude.map(refKey));
  const finished = sources.jobs.filter((job) => job.status === 'succeeded');
  return (
    <select
      aria-label={label}
      value={value ? refKey(value) : ''}
      onChange={(event) => {
        const [kind, id] = event.target.value.split(/:(.*)/s);
        onChange(event.target.value ? { kind: kind as InputRef['kind'], id } : undefined);
      }}
      className="w-full max-w-md rounded-lg border border-line bg-panel px-3 py-1.5 text-sm"
    >
      <option value="">{value ? 'None' : `${label}…`}</option>
      {sources.slides.length > 0 && (
        <optgroup label="Slides">
          {sources.slides
            .filter((slide) => !taken.has(`slide:${slide.id}`))
            .map((slide) => (
              <option key={slide.id} value={`slide:${slide.id}`}>
                {slide.name}
              </option>
            ))}
        </optgroup>
      )}
      {sources.folders.length > 0 && (
        <optgroup label="Folders">
          {sources.folders
            .filter((folder) => !taken.has(`folder:${folder.id}`))
            .map((folder) => (
              <option key={folder.id} value={`folder:${folder.id}`}>
                {folder.name}
              </option>
            ))}
        </optgroup>
      )}
      {finished.length > 0 && (
        <optgroup label="Earlier results">
          {finished
            .filter((job) => !taken.has(`job:${job.id}`))
            .map((job) => (
              <option key={job.id} value={`job:${job.id}`}>
                {describeRef({ kind: 'job', id: job.id }, sources)}
              </option>
            ))}
        </optgroup>
      )}
    </select>
  );
}
