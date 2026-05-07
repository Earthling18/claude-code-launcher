import { useState, useEffect } from 'react';
import { DirectoryPicker } from './DirectoryPicker';
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
  const [mode, setMode] = useState<'claude' | 'custom' | 'codex'>(
    initialConfig?.mode === 'claude' || initialConfig?.mode === 'custom' || initialConfig?.mode === 'codex' ? initialConfig.mode : 'claude'
  );
  const [isPinned, setIsPinned] = useState(initialIsPinned);

  // Update workingDirectory when initialWorkingDirectory changes (for async loading or drag-drop)
  useEffect(() => {
    if (initialWorkingDirectory) {
      setWorkingDirectory(initialWorkingDirectory);
      // Auto-fill project name from folder name if name is empty
      if (!name) {
        const folderName = initialWorkingDirectory.replace(/[\\/]+$/, '').split(/[\\/]/).pop();
        if (folderName) setName(folderName);
      }
    }
  }, [initialWorkingDirectory]);

  // Update config fields when initialConfig changes (for async loading of last project config)
  useEffect(() => {
    if (initialConfig) {
      if (initialConfig.mode === 'claude' || initialConfig.mode === 'custom' || initialConfig.mode === 'codex') setMode(initialConfig.mode);
      if (initialConfig.proxy) setProxy(initialConfig.proxy);
      if (initialConfig.model) setModel(initialConfig.model);
      if (initialConfig.base_url) setBaseUrl(initialConfig.base_url);
      if (initialConfig.token) setToken(initialConfig.token);
      if (initialConfig.skip_permissions !== undefined) setSkipPermissions(initialConfig.skip_permissions);
      if (initialConfig.codex_api_key) setCodexApiKey(initialConfig.codex_api_key);
      if (initialConfig.custom_cli) setCustomCli(initialConfig.custom_cli);
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
  const [codexApiKey, setCodexApiKey] = useState(initialConfig?.codex_api_key || '');
  const [customCli, setCustomCli] = useState<'claude' | 'codex'>(initialConfig?.custom_cli || 'claude');
  const [showToken, setShowToken] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});

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

    if (mode === 'codex' && codexApiKey && !codexApiKey.startsWith('http://') && !codexApiKey.startsWith('https://')) {
      newErrors.codexProxy = '代理地址必须以 http:// 或 https:// 开头';
    }

    if (mode === 'custom' && baseUrl && !baseUrl.startsWith('http://') && !baseUrl.startsWith('https://')) {
      newErrors.baseUrl = 'Base URL 必须以 http:// 或 https:// 开头';
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
      codex_api_key: codexApiKey,
      custom_cli: customCli,
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
            <span className="text-[12px]">Claude 账号</span>
          </label>
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="radio"
              name="mode"
              value="codex"
              checked={mode === 'codex'}
              onChange={() => setMode('codex')}
              className="w-4 h-4"
            />
            <span className="text-[12px]">Codex 账号</span>
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
        </div>
      </div>

      {/* Claude 账号模式 */}
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

      {/* Codex 账号模式 */}
      {mode === 'codex' && (
        <div>
          <label className="block text-[12px] mb-1">代理地址 (可选)</label>
          <input
            type="text"
            value={codexApiKey}
            onChange={(e) => setCodexApiKey(e.target.value)}
            placeholder="例: http://127.0.0.1:7890"
            className="w-full px-3 py-2 bg-[#343638] border border-[#565B5E] rounded text-[12px]"
          />
          {errors.codexProxy && <p className="text-[10px] text-red-500 mt-1">{errors.codexProxy}</p>}
          <p className="text-[10px] text-[#999999] mt-1">
            原版 Codex 服务需要翻墙，可在此处配置代理地址
          </p>
        </div>
      )}

      {/* 自定义模型模式 */}
      {mode === 'custom' && (
        <div className="space-y-3">
          {/* CLI 工具选择 */}
          <div>
            <label className="block text-[12px] mb-2">CLI 工具</label>
            <div className="flex items-center gap-4">
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="radio"
                  name="customCli"
                  value="claude"
                  checked={customCli === 'claude'}
                  onChange={() => setCustomCli('claude')}
                  className="w-4 h-4"
                />
                <span className="text-[12px]">Claude Code</span>
              </label>
              <label className="flex items-center gap-2 opacity-40 cursor-not-allowed">
                <input
                  type="radio"
                  name="customCli"
                  value="codex"
                  disabled
                  className="w-4 h-4"
                />
                <span className="text-[12px]">Codex (暂不支持)</span>
              </label>
            </div>
          </div>

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

          {/* Base URL / Provider */}
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
            <label className="block text-[12px] mb-1">{customCli === 'codex' ? 'API Key (可选)' : 'Auth Token (可选)'}</label>
            <div className="flex items-center gap-2">
              <input
                type={showToken ? 'text' : 'password'}
                value={token}
                onChange={(e) => setToken(e.target.value)}
                placeholder={customCli === 'codex' ? '输入 API Key' : '输入认证令牌'}
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

      {/* 启动模式 */}
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
              <span className="text-[12px]">跳过确认模式</span>
            </label>
          </div>
          <p className="text-[10px] text-[#999999] mt-1">
            跳过确认模式会跳过权限确认提示，适合自动化场景
          </p>
        </div>

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
