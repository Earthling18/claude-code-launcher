import type { ProjectConfig } from './project';

export interface ProxyPreset {
  id: string;
  name: string;
  url: string;
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
}
