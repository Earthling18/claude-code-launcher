import { useState, useEffect } from 'react';
import { DirectoryPicker } from './DirectoryPicker';
import { PresetSelect } from './PresetSelect';
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

const MODES: { value: 'custom' | 'claude' | 'codex'; label: string }[] = [
  { value: 'custom', label: '自定义模型' },
  { value: 'claude', label: 'Claude 账号' },
  { value: 'codex',  label: 'Codex 账号'  },
];

/** Property-sheet row: left-aligned label + right-side content. Hint/error sit under the content. */
const Row: React.FC<{
  label: string;
  required?: boolean;
  hint?: React.ReactNode;
  error?: string;
  children: React.ReactNode;
  alignTop?: boolean;
}> = ({ label, required, hint, error, children, alignTop = false }) => (
  <div className={`grid grid-cols-[84px_1fr] gap-x-4 ${alignTop ? 'items-start pt-2' : 'items-baseline'}`}>
    <label className={`text-[12px] text-text-secondary leading-[34px] ${alignTop ? '!leading-tight pt-0.5' : ''} text-right pr-1 select-none`}>
      {label}
      {required && <span className="text-accent ml-0.5">*</span>}
    </label>
    <div className="min-w-0">
      {children}
      {error && <p className="text-[11px] text-error mt-1.5">{error}</p>}
      {hint && !error && <p className="text-[11px] text-text-tertiary mt-1.5 leading-snug">{hint}</p>}
    </div>
  </div>
);

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
    initialConfig?.mode === 'claude' || initialConfig?.mode === 'custom' || initialConfig?.mode === 'codex'
      ? initialConfig.mode
      : 'custom'
  );
  const [isPinned, setIsPinned] = useState(initialIsPinned);
  const [proxyPresetId, setProxyPresetId] = useState<string | null>(initialConfig?.proxy_preset_id ?? null);
  const [modelPresetId, setModelPresetId] = useState<string | null>(initialConfig?.model_preset_id ?? null);
  const [skipPermissions, setSkipPermissions] = useState(initialConfig?.skip_permissions ?? true);
  const [customCli, setCustomCli] = useState<'claude' | 'codex'>(initialConfig?.custom_cli || 'claude');
  const [errors, setErrors] = useState<Record<string, string>>({});

  useEffect(() => {
    if (initialWorkingDirectory) {
      setWorkingDirectory(initialWorkingDirectory);
      if (!name) {
        const folderName = initialWorkingDirectory.replace(/[\\/]+$/, '').split(/[\\/]/).pop();
        if (folderName) setName(folderName);
      }
    }
  }, [initialWorkingDirectory]);

  useEffect(() => {
    if (initialConfig) {
      if (initialConfig.mode === 'claude' || initialConfig.mode === 'custom' || initialConfig.mode === 'codex') setMode(initialConfig.mode);
      if (initialConfig.proxy_preset_id !== undefined) setProxyPresetId(initialConfig.proxy_preset_id ?? null);
      if (initialConfig.model_preset_id !== undefined) setModelPresetId(initialConfig.model_preset_id ?? null);
      if (initialConfig.skip_permissions !== undefined) setSkipPermissions(initialConfig.skip_permissions);
      if (initialConfig.custom_cli) setCustomCli(initialConfig.custom_cli);
    }
  }, [initialConfig]);

  useEffect(() => { setIsPinned(initialIsPinned); }, [initialIsPinned]);

  const validate = (): boolean => {
    const newErrors: Record<string, string> = {};
    if (!name.trim()) newErrors.name = '请输入项目名称';
    if (!workingDirectory.trim()) newErrors.workingDirectory = '请选择工作目录';
    if (mode === 'custom' && !modelPresetId) newErrors.modelPreset = '请选择或新建一个模型配置';
    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!validate()) return;

    const config: ProjectConfig = {
      mode,
      proxy: '',
      model: '',
      base_url: '',
      token: '',
      skip_permissions: skipPermissions,
      codex_api_key: '',
      custom_cli: customCli,
      proxy_preset_id: (mode === 'claude' || mode === 'codex') ? proxyPresetId : null,
      model_preset_id: mode === 'custom' ? modelPresetId : null,
    };

    onSubmit(name.trim(), workingDirectory.trim(), config, isPinned);
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-3">
      <Row label="项目名称" required error={errors.name}>
        <input
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="输入项目名称"
          disabled={isDefault}
          className="disabled:opacity-50"
        />
      </Row>

      <Row
        label="工作目录"
        required
        error={errors.workingDirectory}
        hint={isDefault ? '默认项目的工作目录不可修改' : undefined}
      >
        <DirectoryPicker
          value={workingDirectory}
          onChange={setWorkingDirectory}
          placeholder="选择项目工作目录"
          disabled={isDefault}
        />
      </Row>

      {/* Soft separator */}
      <div className="h-px bg-line my-1.5 ml-[100px]" />

      <Row label="配置模式">
        <div className="inline-flex p-0.5 bg-surface-1 border border-line rounded">
          {MODES.map(m => (
            <button
              key={m.value}
              type="button"
              onClick={() => setMode(m.value)}
              className={[
                'h-7 px-3 text-[12px] font-medium rounded transition-colors',
                mode === m.value
                  ? 'bg-surface-3 text-text-primary shadow-card'
                  : 'text-text-secondary hover:text-text-primary',
              ].join(' ')}
            >
              <span className="inline-flex items-center gap-1.5">
                <span className="mode-dot" data-mode={m.value} style={{ opacity: mode === m.value ? 1 : 0.55 }} />
                {m.label}
              </span>
            </button>
          ))}
        </div>
      </Row>

      {mode === 'custom' && (
        <Row
          label="模型配置"
          required
          error={errors.modelPreset}
          hint="包含模型名、Base URL、Auth Token；改一处对所有引用项目生效"
        >
          <PresetSelect
            kind="model"
            value={modelPresetId}
            onChange={setModelPresetId}
            allowEmpty
            emptyLabel="请选择或新建模型配置"
          />
        </Row>
      )}

      {(mode === 'claude' || mode === 'codex') && (
        <Row label="代理" hint={`原版 ${mode === 'claude' ? 'Claude' : 'Codex'} 服务可能需要翻墙；不需要请留空`}>
          <PresetSelect kind="proxy" value={proxyPresetId} onChange={setProxyPresetId} allowEmpty />
        </Row>
      )}

      <div className="h-px bg-line my-1.5 ml-[100px]" />

      <Row label="启动模式" hint="跳过确认模式会跳过权限确认提示，适合自动化场景">
        <div className="flex items-center gap-4 h-[34px]">
          <label className="flex items-center gap-1.5 cursor-pointer">
            <input
              type="radio"
              name="launchMode"
              checked={skipPermissions}
              onChange={() => setSkipPermissions(true)}
              className="accent-accent w-3.5 h-3.5"
            />
            <span className="text-[12.5px]">跳过确认</span>
          </label>
          <label className="flex items-center gap-1.5 cursor-pointer">
            <input
              type="radio"
              name="launchMode"
              checked={!skipPermissions}
              onChange={() => setSkipPermissions(false)}
              className="accent-accent w-3.5 h-3.5"
            />
            <span className="text-[12.5px]">普通</span>
          </label>
        </div>
      </Row>

      {!isDefault && (
        <Row label="">
          <label className="flex items-center gap-2 cursor-pointer h-[34px]">
            <input
              type="checkbox"
              checked={isPinned}
              onChange={(e) => setIsPinned(e.target.checked)}
              className="w-3.5 h-3.5 accent-accent"
            />
            <span className="text-[12.5px]">置顶此项目</span>
          </label>
        </Row>
      )}

      {/* Action bar */}
      <div className="flex items-center gap-3 pt-3 mt-2 border-t border-line">
        {!isDefault && onDelete && (
          <button type="button" onClick={onDelete} className="btn btn-danger">删除项目</button>
        )}
        <div className="flex-1" />
        <button type="button" onClick={onCancel} className="btn btn-ghost">取消</button>
        <button type="submit" className="btn btn-primary">{submitLabel}</button>
      </div>
    </form>
  );
};
