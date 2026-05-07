export interface ProjectConfig {
  mode: 'claude' | 'custom' | 'codex';
  proxy: string;
  model: string;
  base_url: string;
  token: string;
  skip_permissions: boolean;
  codex_api_key: string;
  custom_cli: 'claude' | 'codex';
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
};
