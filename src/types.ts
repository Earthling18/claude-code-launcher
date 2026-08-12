export interface DependencyStatus {
  installed: boolean;
  version: string | null;
  meets_requirement: boolean;
  latest_version: string | null;
  update_available: boolean;
  error: string | null;
}

export interface AppConfig {
  mode: 'claude' | 'custom';
  proxy: string;
  model: string;
  base_url: string;
  token: string;
  skip_permissions: boolean;
}

export type CompatibilityStage = 'standard' | 'no_sandbox' | 'no_sandbox_disable_gpu';

export interface DiagnosticsStatus {
  auto_report_enabled: boolean;
  compatibility_stage: CompatibilityStage;
  compatibility_label: string;
  log_directory: string;
  endpoint_configured: boolean;
  pending_reports: number;
  last_report_id: string | null;
  last_report_kind: string | null;
  last_report_at: number | null;
}

export const DEFAULT_CONFIG: AppConfig = {
  mode: 'claude',
  proxy: '',
  model: 'qwen3-coder-480b-a35b',
  base_url: 'http://litellm.uattest.weoa.com',
  token: '',
  skip_permissions: true,
};

export const MODEL_OPTIONS = [
  'deepseek-v3',
  'qwen3-235b-a22b',
  'qwen3-coder-480b-a35b',
];
