import type { ProjectConfig } from './project';

export interface PythonConnection {
  python: string;
  script: string;
  profile: string;
}

export interface ProxyPreset {
  id: string;
  name: string;
  url: string;
  python_connection?: PythonConnection | null;
}

export interface ModelPreset {
  id: string;
  name: string;
  model: string;
  claude_base_url: string;
  codex_base_url: string;
  token: string;
  /** Legacy fields returned while old presets are being migrated. */
  base_url?: string;
  api_format?: ModelApiFormat | null;
}

export type ModelApiFormat = 'anthropic_messages' | 'openai_responses';

export interface GlobalPresets {
  proxies: ProxyPreset[];
  models: ModelPreset[];
  last_used_config: ProjectConfig | null;
}

export interface ModelProbeResult {
  ok: boolean;
  status: number;
  latency_ms: number;
  models: string[];
  error: string | null;
  warning: string | null;
}

export function proxySummary(proxy: ProxyPreset): string {
  if (proxy.python_connection) return `Python · ${proxy.python_connection.profile}`;
  try {
    const url = new URL(proxy.url);
    if (url.username || url.password) { url.username = '***'; url.password = '***'; }
    return url.toString();
  } catch { return '代理地址待检查'; }
}
