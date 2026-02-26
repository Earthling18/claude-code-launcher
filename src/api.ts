import { invoke } from '@tauri-apps/api/core';
import type { DependencyStatus, AppConfig } from './types';
import type { Project, ProjectConfig, ProjectOrderItem, PinnedOrderItem, BridgeStatus } from './types/project';

export const api = {
  // 依赖检测
  checkNodejs: () => invoke<DependencyStatus>('check_nodejs'),
  checkClaude: () => invoke<DependencyStatus>('check_claude'),
  checkGitbash: () => invoke<DependencyStatus>('check_gitbash'),
  checkNodejsWithUpdate: () => invoke<DependencyStatus>('check_nodejs_with_update'),
  checkClaudeWithUpdate: () => invoke<DependencyStatus>('check_claude_with_update'),
  checkGitbashWithUpdate: () => invoke<DependencyStatus>('check_gitbash_with_update'),
  refreshSystemPath: () => invoke('refresh_system_path'),

  // 安装/更新
  installNodejs: () => invoke('install_nodejs'),
  updateNodejs: () => invoke('update_nodejs'),
  installClaude: () => invoke('install_claude'),
  updateClaude: () => invoke('update_claude'),
  installGitbash: () => invoke('install_gitbash'),
  updateGitbash: () => invoke('update_gitbash'),

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
  // Get all projects
  getAll: () => invoke<Project[]>('get_projects'),

  // Get a single project by ID
  get: (id: string) => invoke<Project>('get_project', { id }),

  // Create a new project
  create: (name: string, workingDirectory: string, config: ProjectConfig) =>
    invoke<Project>('create_project', {
      name,
      workingDirectory,
      config,
    }),

  // Update an existing project
  update: (
    id: string,
    name?: string,
    workingDirectory?: string,
    config?: ProjectConfig,
    isPinned?: boolean
  ) =>
    invoke<Project>('update_project', {
      id,
      name,
      workingDirectory,
      config,
      isPinned,
    }),

  // Delete a project
  delete: (id: string) => invoke<void>('delete_project', { id }),

  // Launch a project
  launch: (id: string) => invoke<void>('launch_project', { id }),

  // Generate commands for a project
  generatePowershellCommand: (id: string) =>
    invoke<string>('generate_project_powershell_command', { id }),
  generateCmdCommand: (id: string) =>
    invoke<string>('generate_project_cmd_command', { id }),
  generateBashCommand: (id: string) =>
    invoke<string>('generate_project_bash_command', { id }),

  // Update sort order for non-pinned projects (batch)
  updateProjectsOrder: (orders: ProjectOrderItem[]) =>
    invoke<void>('update_projects_order', { orders }),

  // Update pinned_at for pinned projects (batch)
  updatePinnedOrder: (orders: PinnedOrderItem[]) =>
    invoke<void>('update_pinned_order', { orders }),

  // Toggle project pinned status
  togglePinned: (id: string, isPinned: boolean) =>
    invoke<Project>('toggle_project_pinned', { id, isPinned }),
};

// Bridge management API
export const bridgeApi = {
  start: (id: string) => invoke<void>('start_bridge', { id }),
  stop: (id: string) => invoke<void>('stop_bridge', { id }),
  getStatus: (id: string) => invoke<BridgeStatus>('get_bridge_status', { id }),
  getLogs: (id: string, maxLines?: number) =>
    invoke<string[]>('get_bridge_logs', { id, maxLines }),
  restart: (id: string) => invoke<void>('restart_bridge', { id }),
  checkDeps: () => invoke<void>('check_bridge_deps'),
  prepareEnv: () => invoke<void>('prepare_bridge_env'),
  getHostname: () => invoke<string>('get_hostname'),
  getUsername: () => invoke<string>('get_username'),
  getOrCreateKey: (username: string) => invoke<string>('bridge_get_or_create_key', { username }),
};

// Claude login check API
export const claudeLoginApi = {
  checkLogin: () => invoke<boolean>('check_claude_login'),
  launchForLogin: (proxy?: string) => invoke<void>('launch_claude_for_login', { proxy }),
};

// Remote config API
export const remoteApi = {
  loadConfig: () => invoke<ProjectConfig>('load_remote_config'),
  saveConfig: (config: ProjectConfig) => invoke<void>('save_remote_config', { config }),
  startBridge: () => invoke<void>('start_remote_bridge'),
};

// Agent config API
export const agentConfigApi = {
  openFile: (name: string) => invoke<void>('open_agent_config_file', { name }),
  openFolder: (name: string) => invoke<void>('open_agent_config_folder', { name }),
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
