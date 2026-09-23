// Typed client for the Studio API served by `rocqipath studio`.

export type SettingType =
  | 'bool'
  | 'int'
  | 'float'
  | 'str'
  | 'choice'
  | 'list'
  | 'mapping'
  | 'config'
  | 'object';

export interface Setting {
  name: string;
  type: SettingType;
  default: unknown;
  required: boolean;
  choices: unknown[] | null;
  advanced: boolean;
  local_only: boolean;
  help: string;
  doc: string;
  items?: string;
  length?: number;
  fields?: Setting[];
}

export interface WorkflowInfo {
  name: string;
  label: string;
  summary: string;
  extra: string;
  available: boolean;
  missing: string[];
  inputs: { kind: string; help: string };
  options: { name: string; help: string }[];
  settings: Setting[];
}

export interface Folder {
  id: string;
  name: string;
  path: string;
  count: number;
  demo: boolean;
  truncated: boolean;
}

export interface Slide {
  id: string;
  name: string;
  path: string;
  folder_id: string;
  relative: string;
  size: number;
  format: string;
  demo: boolean;
}

export interface SlideInfo {
  width: number;
  height: number;
  max_level: number;
  tile_size: number;
  objective: string | null;
  mpp: string | null;
  backend: string;
  levels: number;
}

export type JobStatus = 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled';

export interface Job {
  id: string;
  workflow: string;
  status: JobStatus;
  created: string;
  started: string | null;
  finished: string | null;
  error: string | null;
  inputs: string[];
  output_dir: string;
}

export interface JobDetail extends Job {
  artifacts: { name: string; path: string; size: number }[];
  log: string;
}

export interface InputRef {
  kind: 'slide' | 'folder' | 'job';
  id: string;
}

export interface JobRequest {
  workflow: string;
  inputs: InputRef[];
  options: Record<string, InputRef>;
  settings: Record<string, unknown>;
}

export class ApiError extends Error {}

function describe(detail: unknown): string {
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((d) => (typeof d === 'object' && d && 'msg' in d ? String((d as { msg: unknown }).msg) : String(d)))
      .join('; ');
  }
  return 'Request failed.';
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: init?.body ? { 'Content-Type': 'application/json' } : undefined,
  });
  if (!response.ok) {
    let detail: unknown = response.statusText;
    try {
      detail = (await response.json()).detail;
    } catch {
      // keep the status text
    }
    throw new ApiError(describe(detail));
  }
  return (await response.json()) as T;
}

const post = <T>(path: string, body: unknown) =>
  request<T>(path, { method: 'POST', body: JSON.stringify(body) });

export const api = {
  status: () => request<{ version: string; workspace: string }>('/api/status'),
  workflows: () => request<WorkflowInfo[]>('/api/workflows'),
  browse: (path?: string) =>
    request<{ path: string; parent: string; directories: { name: string; path: string }[] }>(
      '/api/browse' + (path ? `?path=${encodeURIComponent(path)}` : ''),
    ),
  folders: () => request<Folder[]>('/api/folders'),
  addFolder: (path: string) => post<Folder>('/api/folders', { path }),
  demo: () => post<Folder>('/api/demo', {}),
  slides: () => request<Slide[]>('/api/slides'),
  slideInfo: (id: string) => request<SlideInfo>(`/api/slides/${id}/info`),
  thumbnailUrl: (id: string) => `/api/slides/${id}/thumbnail`,
  tileUrl: (id: string, level: number, x: number, y: number) =>
    `/api/slides/${id}/tiles/${level}/${x}/${y}.jpg`,
  jobs: () => request<Job[]>('/api/jobs'),
  job: (id: string) => request<JobDetail>(`/api/jobs/${id}`),
  submit: (body: JobRequest) => post<Job>('/api/jobs', body),
  cancel: (id: string) => post<Job>(`/api/jobs/${id}/cancel`, {}),
  artifactUrl: (id: string, path: string) =>
    `/api/jobs/${id}/artifact?path=${encodeURIComponent(path)}`,
};
