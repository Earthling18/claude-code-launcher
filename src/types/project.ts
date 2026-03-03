export interface ProjectConfig {
  mode: 'claude' | 'custom' | 'codex' | 'remote';
  proxy: string;
  model: string;
  base_url: string;
  token: string;
  skip_permissions: boolean;
  codex_api_key: string;
  custom_cli: 'claude' | 'codex';

  // Remote bridge fields
  bridge_server_url: string;
  bridge_bind_key: string;
  bridge_client_id: string;
  bridge_agent_port: number;
  bridge_agent_timeout: number;
  bridge_proxy: string;
  bridge_reconnect_interval: number;
  bridge_heartbeat_interval: number;
  bridge_agent_mode: 'claude' | 'custom';
  bridge_max_turns: number;
}

export interface Project {
  id: string;
  name: string;
  working_directory: string;
  config: ProjectConfig;
  is_default: boolean;
  created_at: number;
  updated_at: number;
  last_launched_at?: number;
  is_pinned: boolean;
  pinned_at?: number;
  sort_order: number;
}

export interface CreateProjectInput {
  name: string;
  working_directory: string;
  config: ProjectConfig;
}

export interface UpdateProjectInput {
  name?: string;
  working_directory?: string;
  config?: ProjectConfig;
  is_pinned?: boolean;
}

export interface ProjectOrderItem {
  id: string;
  sort_order: number;
}

export interface PinnedOrderItem {
  id: string;
  pinned_at: number;
}

export interface BridgeStatus {
  running: boolean;
  agent_ok: boolean;
  client_connected: boolean;
  started_at: number | null;
  agent_port: number | null;
}

export const DEFAULT_PROJECT_CONFIG: ProjectConfig = {
  mode: 'claude',
  proxy: '',
  model: 'qwen3-coder-480b-a35b',
  base_url: 'http://litellm.uattest.weoa.com',
  token: '',
  skip_permissions: true,
  codex_api_key: '',
  custom_cli: 'claude',
  bridge_server_url: 'ws://172.21.11.82:80/bridge',
  bridge_bind_key: '',
  bridge_client_id: '',
  bridge_agent_port: 5000,
  bridge_agent_timeout: 1800,
  bridge_proxy: '',
  bridge_reconnect_interval: 5,
  bridge_heartbeat_interval: 30,
  bridge_agent_mode: 'claude',
  bridge_max_turns: 3,
};
