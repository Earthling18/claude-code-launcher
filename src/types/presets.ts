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
  base_url: string;
  token: string;
}

export interface GlobalPresets {
  proxies: ProxyPreset[];
  models: ModelPreset[];
  last_used_config: ProjectConfig | null;
}
