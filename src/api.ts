import { invoke } from '@tauri-apps/api/core';
import type { DependencyStatus, AppConfig, DiagnosticsStatus } from './types';
import type { Project, ProjectConfig, ProjectOrderItem, PinnedOrderItem, ConfigScanResult } from './types/project';
import type { GlobalPresets, ProxyPreset, ModelPreset, ModelProbeResult, ModelApiFormat } from './types/presets';

export const api = {
  // 依赖检测
  checkNodejs: () => invoke<DependencyStatus>('check_nodejs'),
  checkClaude: () => invoke<DependencyStatus>('check_claude'),
  checkGitbash: () => invoke<DependencyStatus>('check_gitbash'),
  checkNodejsWithUpdate: () => invoke<DependencyStatus>('check_nodejs_with_update'),
  checkClaudeWithUpdate: () => invoke<DependencyStatus>('check_claude_with_update'),
  checkGitbashWithUpdate: () => invoke<DependencyStatus>('check_gitbash_with_update'),
  checkCodex: () => invoke<DependencyStatus>('check_codex'),
  checkCodexWithUpdate: () => invoke<DependencyStatus>('check_codex_with_update'),
  refreshSystemPath: () => invoke('refresh_system_path'),

  // 安装/更新
  installNodejs: () => invoke('install_nodejs'),
  updateNodejs: () => invoke('update_nodejs'),
  installClaude: () => invoke('install_claude'),
  updateClaude: () => invoke('update_claude'),
  installGitbash: () => invoke('install_gitbash'),
  updateGitbash: () => invoke('update_gitbash'),
  installCodex: () => invoke('install_codex'),
  updateCodex: () => invoke('update_codex'),
  reinstallClaude: () => invoke('reinstall_claude'),
  reinstallCodex: () => invoke('reinstall_codex'),
  updateClaudeSilent: () => invoke('update_claude_silent'),
  updateCodexSilent: () => invoke('update_codex_silent'),
  checkSkillMarket: () => invoke<DependencyStatus>('check_skill_market'),
  checkSkillMarketWithUpdate: () => invoke<DependencyStatus>('check_skill_market_with_update'),
  installSkillMarket: () => invoke('install_skill_market'),

  // 启动
  launchClaudeCode: (config: Record<string, string>) =>
    invoke('launch_claude_code', { config }),

  // 命令生成
  generatePowershellCommand: (config: Record<string, string>) =>
    invoke<string>('generate_powershell_command', { config }),
  generateCmdCommand: (config: Record<string, string>) =>
    invoke<string>('generate_cmd_command', { config }),
  generateBashCommand: (config: Record<string, string>) =>
    invoke<string>('generate_bash_command', { config }),

  // 平台检测
  getPlatform: () => invoke<string>('get_platform'),

  // 设置管理
  saveToSettings: (config: Record<string, string>) =>
    invoke('save_to_settings', { config }),
  resetSettings: () => invoke('reset_settings'),
  openSettingsFile: () => invoke('open_settings_file'),

  // 应用配置 (legacy API for backwards compatibility)
  saveAppConfig: (config: AppConfig) =>
    invoke('save_app_config', { config }),
  loadAppConfig: () => invoke<AppConfig>('load_app_config'),
};

// Project management API
export const projectApi = {
  getAll: () => invoke<Project[]>('get_projects'),
  get: (id: string) => invoke<Project>('get_project', { id }),
  create: (name: string, workingDirectory: string, config: ProjectConfig, createNamedDirectory = false) =>
    invoke<Project>('create_project', { name, workingDirectory, config, createNamedDirectory }),
  update: (
    id: string,
    name?: string,
    workingDirectory?: string,
    config?: ProjectConfig,
    isPinned?: boolean
  ) =>
    invoke<Project>('update_project', { id, name, workingDirectory, config, isPinned }),
  delete: (id: string) => invoke<void>('delete_project', { id }),
  launch: (id: string) => invoke<void>('launch_project', { id }),
  openFolder: (id: string) => invoke<void>('open_project_folder', { id }),
  generatePowershellCommand: (id: string) =>
    invoke<string>('generate_project_powershell_command', { id }),
  generateCmdCommand: (id: string) =>
    invoke<string>('generate_project_cmd_command', { id }),
  generateBashCommand: (id: string) =>
    invoke<string>('generate_project_bash_command', { id }),
  updateProjectsOrder: (orders: ProjectOrderItem[]) =>
    invoke<void>('update_projects_order', { orders }),
  updatePinnedOrder: (orders: PinnedOrderItem[]) =>
    invoke<void>('update_pinned_order', { orders }),
  togglePinned: (id: string, isPinned: boolean) =>
    invoke<Project>('toggle_project_pinned', { id, isPinned }),
};

// CC config checker API
export const ccConfigApi = {
  scan: (projects: { name: string; working_directory: string }[]) =>
    invoke<ConfigScanResult>('scan_cc_config', { projects }),
  cleanField: (filePath: string, key: string) =>
    invoke<void>('clean_cc_config_field', { filePath, key }),
  cleanAll: (targets: { file_path: string; key: string }[]) =>
    invoke<number>('clean_cc_config_all', { targets }),
  openFile: (filePath: string) =>
    invoke<void>('open_cc_config_file', { filePath }),
  fixBom: (filePath: string) =>
    invoke<void>('fix_cc_config_bom', { filePath }),
  fixMcpMisplaced: (filePath: string, targetPath: string) =>
    invoke<void>('fix_cc_mcp_misplaced', { filePath, targetPath }),
  removeMcpServers: (filePath: string) =>
    invoke<void>('remove_cc_mcp_servers', { filePath }),
};

// Claude login check API
export const claudeLoginApi = {
  checkLogin: () => invoke<boolean>('check_claude_login'),
  launchForLogin: (proxy?: string) => invoke<void>('launch_claude_for_login', { proxy }),
};

// Dialog API
export const dialogApi = {
  selectDirectory: () => invoke<string | null>('select_directory'),
};

// System API
export const systemApi = {
  getHomeDirectory: () => invoke<string>('get_home_directory'),
};

// Global presets API (proxy + model)
export const presetsApi = {
  getAll: () => invoke<GlobalPresets>('get_global_presets'),

  createProxy: (name: string, url: string) =>
    invoke<ProxyPreset>('create_proxy_preset', { name, url }),
  updateProxy: (id: string, name: string, url: string) =>
    invoke<ProxyPreset>('update_proxy_preset', { id, name, url }),
  deleteProxy: (id: string) => invoke<void>('delete_proxy_preset', { id }),
  countProxyRefs: (id: string) => invoke<number>('count_proxy_preset_refs', { id }),

  createModel: (name: string, model: string, claudeBaseUrl: string, codexBaseUrl: string, token: string) =>
    invoke<ModelPreset>('create_model_preset', { name, model, claudeBaseUrl, codexBaseUrl, token }),
  updateModel: (id: string, name: string, model: string, claudeBaseUrl: string, codexBaseUrl: string, token: string) =>
    invoke<ModelPreset>('update_model_preset', { id, name, model, claudeBaseUrl, codexBaseUrl, token }),
  deleteModel: (id: string) => invoke<void>('delete_model_preset', { id }),
  countModelRefs: (id: string) => invoke<number>('count_model_preset_refs', { id }),

  probeModel: (baseUrl: string, token: string, model: string, apiFormat: ModelApiFormat) =>
    invoke<ModelProbeResult>('probe_model_endpoint', { baseUrl, token, model, apiFormat }),

  getLastUsed: () => invoke<ProjectConfig | null>('get_last_used_project_config'),
  setLastUsed: (config: ProjectConfig) =>
    invoke<void>('set_last_used_project_config', { config }),

  validateLaunch: (id: string) => invoke<void>('validate_project_launch', { id }),
};

// Onboarding API
export const onboardingApi = {
  getStatus: () => invoke<boolean>('get_onboarding_status'),
  setCompleted: () => invoke<void>('set_onboarding_completed'),
};

export const diagnosticsApi = {
  getStatus: () => invoke<DiagnosticsStatus>('get_diagnostics_status'),
  setAutoReport: (enabled: boolean) => invoke<void>('set_diagnostics_auto_report', { enabled }),
  openFolder: () => invoke<void>('open_diagnostics_folder'),
  resetCompatibilityAndRestart: () => invoke<void>('reset_webview_compatibility_and_restart'),
  submit: (note?: string) => invoke<string>('submit_diagnostics', { note: note || null }),
  recordFrontendError: (message: string) => invoke<void>('record_frontend_error', { message }),
};

