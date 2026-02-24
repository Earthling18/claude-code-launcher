import { useState, useEffect } from 'react';
import { DirectoryPicker } from './DirectoryPicker';
import { BridgeConfigForm } from './BridgeConfigForm';
import type { ProjectConfig } from '../types/project';

interface ProjectFormProps {
  initialName?: string;
  initialWorkingDirectory?: string;
  initialConfig?: ProjectConfig;
  initialIsPinned?: boolean;
  onSubmit: (name: string, workingDirectory: string, config: ProjectConfig, isPinned: boolean) => void;
  onCancel: () => void;
  onDelete?: () => void;
  submitLabel?: string;
  isDefault?: boolean;
}

export const ProjectForm: React.FC<ProjectFormProps> = ({
  initialName = '',
  initialWorkingDirectory = '',
  initialConfig,
  initialIsPinned = false,
  onSubmit,
  onCancel,
  onDelete,
  submitLabel = '创建项目',
  isDefault = false,
}) => {
  const [name, setName] = useState(initialName);
  const [workingDirectory, setWorkingDirectory] = useState(initialWorkingDirectory);
  const [mode, setMode] = useState<'claude' | 'custom' | 'remote'>(initialConfig?.mode || 'claude');
  const [isPinned, setIsPinned] = useState(initialIsPinned);

  // Update workingDirectory when initialWorkingDirectory changes (for async loading or drag-drop)
  useEffect(() => {
    if (initialWorkingDirectory) {
      setWorkingDirectory(initialWorkingDirectory);
    }
  }, [initialWorkingDirectory]);

  // Update config fields when initialConfig changes (for async loading of last project config)
  useEffect(() => {
    if (initialConfig) {
      if (initialConfig.mode) setMode(initialConfig.mode);
      if (initialConfig.proxy) setProxy(initialConfig.proxy);
      if (initialConfig.model) setModel(initialConfig.model);
      if (initialConfig.base_url) setBaseUrl(initialConfig.base_url);
      if (initialConfig.token) setToken(initialConfig.token);
      if (initialConfig.skip_permissions !== undefined) setSkipPermissions(initialConfig.skip_permissions);
      // Bridge fields
      if (initialConfig.bridge_server_url) setBridgeServerUrl(initialConfig.bridge_server_url);
      if (initialConfig.bridge_bind_key) setBridgeBindKey(initialConfig.bridge_bind_key);
      if (initialConfig.bridge_client_id) setBridgeClientId(initialConfig.bridge_client_id);
      if (initialConfig.bridge_agent_port) setBridgeAgentPort(initialConfig.bridge_agent_port);
      if (initialConfig.bridge_agent_timeout) setBridgeAgentTimeout(initialConfig.bridge_agent_timeout);
      if (initialConfig.bridge_reconnect_interval) setBridgeReconnectInterval(initialConfig.bridge_reconnect_interval);
      if (initialConfig.bridge_heartbeat_interval) setBridgeHeartbeatInterval(initialConfig.bridge_heartbeat_interval);
      if (initialConfig.bridge_agent_mode) setBridgeAgentMode(initialConfig.bridge_agent_mode);
      if (initialConfig.bridge_max_turns) setBridgeMaxTurns(initialConfig.bridge_max_turns);
    }
  }, [initialConfig]);

  // Update isPinned when initialIsPinned changes
  useEffect(() => {
    setIsPinned(initialIsPinned);
  }, [initialIsPinned]);

  const [proxy, setProxy] = useState(initialConfig?.proxy || '');
  const [model, setModel] = useState(initialConfig?.model || '');
  const [baseUrl, setBaseUrl] = useState(initialConfig?.base_url || 'http://litellm.uattest.weoa.com');
  const [token, setToken] = useState(initialConfig?.token || '');
  const [skipPermissions, setSkipPermissions] = useState(initialConfig?.skip_permissions ?? false);
  const [showToken, setShowToken] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});

  // Bridge config state
  const [bridgeServerUrl, setBridgeServerUrl] = useState(initialConfig?.bridge_server_url || 'ws://172.21.11.82:80/bridge');
  const [bridgeBindKey, setBridgeBindKey] = useState(initialConfig?.bridge_bind_key || '');
  const [bridgeClientId, setBridgeClientId] = useState(initialConfig?.bridge_client_id || '');
  const [bridgeAgentPort, setBridgeAgentPort] = useState(initialConfig?.bridge_agent_port || 5000);
  const [bridgeAgentTimeout, setBridgeAgentTimeout] = useState(initialConfig?.bridge_agent_timeout || 1800);
  const [bridgeReconnectInterval, setBridgeReconnectInterval] = useState(initialConfig?.bridge_reconnect_interval || 5);
  const [bridgeHeartbeatInterval, setBridgeHeartbeatInterval] = useState(initialConfig?.bridge_heartbeat_interval || 30);
  const [bridgeAgentMode, setBridgeAgentMode] = useState<'claude' | 'custom'>(initialConfig?.bridge_agent_mode || 'claude');
  const [bridgeMaxTurns, setBridgeMaxTurns] = useState(initialConfig?.bridge_max_turns || 3);

  const validate = (): boolean => {
    const newErrors: Record<string, string> = {};

    if (!name.trim()) {
      newErrors.name = '请输入项目名称';
    }

    if (!workingDirectory.trim()) {
      newErrors.workingDirectory = '请选择工作目录';
    }

    if (mode === 'claude' && proxy && !proxy.startsWith('http://') && !proxy.startsWith('https://')) {
      newErrors.proxy = '代理地址必须以 http:// 或 https:// 开头';
    }

    if (mode === 'custom' && baseUrl && !baseUrl.startsWith('http://') && !baseUrl.startsWith('https://')) {
      newErrors.baseUrl = 'Base URL 必须以 http:// 或 https:// 开头';
    }

    if (mode === 'remote') {
      if (!bridgeBindKey.trim()) {
        newErrors.bridgeBindKey = '请输入 Bind Key';
      }
      if (!bridgeServerUrl.trim()) {
        newErrors.bridgeServerUrl = '请输入 Bridge Server URL';
      }
    }

    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();

    if (!validate()) {
      return;
    }

    const config: ProjectConfig = {
      mode,
      proxy,
      model,
      base_url: baseUrl,
      token,
      skip_permissions: skipPermissions,
      bridge_server_url: bridgeServerUrl,
      bridge_bind_key: bridgeBindKey,
      bridge_client_id: bridgeClientId,
      bridge_agent_port: bridgeAgentPort,
      bridge_agent_timeout: bridgeAgentTimeout,
      bridge_proxy: '',
      bridge_reconnect_interval: bridgeReconnectInterval,
      bridge_heartbeat_interval: bridgeHeartbeatInterval,
      bridge_agent_mode: bridgeAgentMode,
      bridge_max_turns: bridgeMaxTurns,
    };

    onSubmit(name.trim(), workingDirectory.trim(), config, isPinned);
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      {/* 项目名称 */}
      <div>
        <label className="block text-[12px] mb-1">
          项目名称 <span className="text-red-500">*</span>
        </label>
        <input
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="输入项目名称"
          disabled={isDefault}
          className="w-full px-3 py-2 bg-[#343638] border border-[#565B5E] rounded text-[12px] disabled:opacity-50"
        />
        {errors.name && <p className="text-[10px] text-red-500 mt-1">{errors.name}</p>}
      </div>

      {/* 工作目录 */}
      <div>
        <label className="block text-[12px] mb-1">
          工作目录 <span className="text-red-500">*</span>
        </label>
        <DirectoryPicker
          value={workingDirectory}
          onChange={setWorkingDirectory}
          placeholder="选择项目工作目录"
          disabled={isDefault}
        />
        {errors.workingDirectory && (
          <p className="text-[10px] text-red-500 mt-1">{errors.workingDirectory}</p>
        )}
        {isDefault && (
          <p className="text-[10px] text-[#999999] mt-1">默认项目的工作目录不可修改</p>
        )}
      </div>

      {/* 分隔线 */}
      <div className="h-px bg-gradient-to-r from-transparent via-[#565B5E] to-transparent" />

      {/* 模式选择 */}
      <div>
        <label className="block text-[12px] mb-2">配置模式</label>
        <div className="flex items-center gap-4">
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="radio"
              name="mode"
              value="claude"
              checked={mode === 'claude'}
              onChange={() => setMode('claude')}
              className="w-4 h-4"
            />
            <span className="text-[12px]">Claude 原版</span>
          </label>
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="radio"
              name="mode"
              value="custom"
              checked={mode === 'custom'}
              onChange={() => setMode('custom')}
              className="w-4 h-4"
            />
            <span className="text-[12px]">自定义模型</span>
          </label>
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="radio"
              name="mode"
              value="remote"
              checked={mode === 'remote'}
              onChange={() => setMode('remote')}
              className="w-4 h-4"
            />
            <span className="text-[12px]">远程桥接</span>
          </label>
        </div>
      </div>

      {/* Claude 原版模式 */}
      {mode === 'claude' && (
        <div>
          <label className="block text-[12px] mb-1">代理地址 (可选)</label>
          <input
            type="text"
            value={proxy}
            onChange={(e) => setProxy(e.target.value)}
            placeholder="例: http://127.0.0.1:7890"
            className="w-full px-3 py-2 bg-[#343638] border border-[#565B5E] rounded text-[12px]"
          />
          {errors.proxy && <p className="text-[10px] text-red-500 mt-1">{errors.proxy}</p>}
          <p className="text-[10px] text-[#999999] mt-1">
            原版 Claude 服务需要翻墙，可在此处配置代理地址
          </p>
        </div>
      )}

      {/* 自定义模型模式 */}
      {mode === 'custom' && (
        <div className="space-y-3">
          {/* Model Name */}
          <div>
            <label className="block text-[12px] mb-1">Model Name (可选)</label>
            <input
              type="text"
              value={model}
              onChange={(e) => setModel(e.target.value)}
              placeholder="输入模型名称，留空使用默认模型"
              className="w-full px-3 py-2 bg-[#343638] border border-[#565B5E] rounded text-[12px]"
            />
          </div>

          {/* Base URL */}
          <div>
            <label className="block text-[12px] mb-1">Base URL (可选)</label>
            <input
              type="text"
              value={baseUrl}
              onChange={(e) => setBaseUrl(e.target.value)}
              placeholder="例: http://api.example.com"
              className="w-full px-3 py-2 bg-[#343638] border border-[#565B5E] rounded text-[12px]"
            />
            {errors.baseUrl && <p className="text-[10px] text-red-500 mt-1">{errors.baseUrl}</p>}
          </div>

          {/* Auth Token */}
          <div>
            <label className="block text-[12px] mb-1">Auth Token (可选)</label>
            <div className="flex items-center gap-2">
              <input
                type={showToken ? 'text' : 'password'}
                value={token}
                onChange={(e) => setToken(e.target.value)}
                placeholder="输入认证令牌"
                className="flex-1 px-3 py-2 bg-[#343638] border border-[#565B5E] rounded text-[12px]"
              />
              <button
                type="button"
                onClick={() => setShowToken(!showToken)}
                className="px-3 py-2 text-[12px] bg-[#565B5E] hover:bg-[#7A8488] text-white rounded"
              >
                {showToken ? '隐藏' : '显示'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 远程桥接模式 */}
      {mode === 'remote' && (
        <BridgeConfigForm
          bridgeServerUrl={bridgeServerUrl}
          bridgeBindKey={bridgeBindKey}
          bridgeAgentPort={bridgeAgentPort}
          bridgeAgentTimeout={bridgeAgentTimeout}
          bridgeReconnectInterval={bridgeReconnectInterval}
          bridgeHeartbeatInterval={bridgeHeartbeatInterval}
          bridgeAgentMode={bridgeAgentMode}
          bridgeMaxTurns={bridgeMaxTurns}
          modelProxy={proxy}
          modelName={model}
          modelBaseUrl={baseUrl}
          modelToken={token}
          onServerUrlChange={setBridgeServerUrl}
          onBindKeyChange={setBridgeBindKey}
          onAgentPortChange={setBridgeAgentPort}
          onAgentTimeoutChange={setBridgeAgentTimeout}
          onReconnectIntervalChange={setBridgeReconnectInterval}
          onHeartbeatIntervalChange={setBridgeHeartbeatInterval}
          onAgentModeChange={setBridgeAgentMode}
          onMaxTurnsChange={setBridgeMaxTurns}
          onModelProxyChange={setProxy}
          onModelNameChange={setModel}
          onModelBaseUrlChange={setBaseUrl}
          onModelTokenChange={setToken}
          errors={errors}
        />
      )}

      {/* 启动模式 - only for claude/custom modes */}
      {mode !== 'remote' && (
        <div>
          <label className="block text-[12px] mb-2">启动模式</label>
          <div className="flex items-center gap-4">
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="radio"
                name="launchMode"
                checked={!skipPermissions}
                onChange={() => setSkipPermissions(false)}
                className="w-4 h-4"
              />
              <span className="text-[12px]">普通模式</span>
            </label>
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="radio"
                name="launchMode"
                checked={skipPermissions}
                onChange={() => setSkipPermissions(true)}
                className="w-4 h-4"
              />
              <span className="text-[12px]">dangerously-skip 模式</span>
            </label>
          </div>
          <p className="text-[10px] text-[#999999] mt-1">
            dangerously-skip 模式会跳过权限确认提示，适合自动化场景
          </p>
        </div>
      )}

      {/* 置顶设置 - 仅非默认项目显示 */}
      {!isDefault && (
        <div>
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={isPinned}
              onChange={(e) => setIsPinned(e.target.checked)}
              className="w-4 h-4 rounded border-[#565B5E] bg-[#343638] accent-[#f59e0b]"
            />
            <span className="text-[12px]">置顶此项目</span>
          </label>
          <p className="text-[10px] text-[#999999] mt-1">
            置顶项目会显示在列表前面（默认项目之后）
          </p>
        </div>
      )}

      {/* 分隔线 */}
      <div className="h-px bg-gradient-to-r from-transparent via-[#565B5E] to-transparent" />

      {/* 按钮 */}
      <div className="flex items-center gap-3">
        {!isDefault && onDelete && (
          <button
            type="button"
            onClick={onDelete}
            className="px-6 py-2 text-[12px] bg-red-600 hover:bg-red-700 text-white rounded"
          >
            删除
          </button>
        )}
        <div className="flex-1" />
        <button
          type="button"
          onClick={onCancel}
          className="px-6 py-2 text-[12px] bg-[#565B5E] hover:bg-[#7A8488] text-white rounded"
        >
          取消
        </button>
        <button
          type="submit"
          className="px-6 py-2 text-[12px] bg-[#3b82f6] hover:bg-[#2563eb] text-white rounded"
        >
          {submitLabel}
        </button>
      </div>
    </form>
  );
};
