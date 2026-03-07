export interface ProjectConfig {
  mode: 'claude' | 'custom' | 'codex' | 'remote';
  proxy: string;
  model: string;
  base_url: string;
  token: string;
  skip_permissions: boolean;
  codex_api_key: string;
  custom_cli: 'claude' | 'codex';

  // Mobot bridge fields (simplified)
  mobot_bridge_path: string | null;
  mobot_bridge_port: number;
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

// Mobot bridge types
export type InstallStatus =
  | 'NotInstalled'
  | { Installed: { path: string } }
  | { Running: { path: string; port: number } };

export interface HealthStatus {
  healthy: boolean;
  details: string;
}

export interface MobotServiceStatus {
  installed: boolean;
  running: boolean;
  pid: number | null;
  port: number;
  install_path: string | null;
  healthy: boolean;
  started_at: number | null;
}

// CC config checker types
export interface ConfigConflict {
  source: string;
  file_path: string | null;
  key: string;
  value: string;
  can_clean: boolean;
}

export interface BomFileIssue {
  file_path: string;
}

export interface McpMisplaced {
  file_path: string;
  target_path: string;
  keys: string[];
  can_fix: boolean;
}

export interface ConfigScanResult {
  conflicts: ConfigConflict[];
  bom_files: BomFileIssue[];
  mcp_misplaced: McpMisplaced[];
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
  mobot_bridge_path: null,
  mobot_bridge_port: 8000,
};
