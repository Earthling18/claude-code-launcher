import { invoke } from '@tauri-apps/api/core';
import type { DependencyStatus, AppConfig } from './types';
import type { Project, ProjectConfig, ProjectOrderItem, PinnedOrderItem, InstallStatus, HealthStatus, MobotServiceStatus, ConfigScanResult } from './types/project';

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
  create: (name: string, workingDirectory: string, config: ProjectConfig) =>
    invoke<Project>('create_project', { name, workingDirectory, config }),
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

// Mobot bridge management API
export const mobotApi = {
  detectInstallation: () => invoke<InstallStatus>('detect_mobot_installation'),
  install: () => invoke<string>('install_mobot_bridge'),
  detectPython: () => invoke<string | null>('detect_python'),
  checkDepsInstalled: (bridgePath: string) =>
    invoke<boolean>('check_mobot_deps_installed', { bridgePath }),
  installDeps: (bridgePath: string, python: string) =>
    invoke<string>('install_mobot_deps', { bridgePath, python }),
  startService: (bridgePath: string, python: string, port: number) =>
    invoke<number>('start_mobot_service', { bridgePath, python, port }),
  stopService: () => invoke<void>('stop_mobot_service'),
  checkHealth: (port: number) => invoke<HealthStatus>('check_mobot_health', { port }),
  getStatus: (port: number) => invoke<MobotServiceStatus>('get_mobot_status', { port }),
  getLogs: (maxLines?: number) => invoke<string[]>('get_mobot_logs', { maxLines }),
  getHostname: () => invoke<string>('get_hostname'),
  getUsername: () => invoke<string>('get_username'),
  isUpdating: () => invoke<boolean>('is_mobot_updating'),
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

// Onboarding API
export const onboardingApi = {
  getStatus: () => invoke<boolean>('get_onboarding_status'),
  setCompleted: () => invoke<void>('set_onboarding_completed'),
};
