import { useEffect, useState } from 'react';
import type { ProjectConfig } from '../types/project';
import { DirectoryPicker } from './DirectoryPicker';
import { PresetSelect } from './PresetSelect';

type CliKind = 'claude' | 'codex';
type ServiceSource = 'account' | 'custom_api';

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

const FormRow: React.FC<{
  label: string;
  required?: boolean;
  hint?: React.ReactNode;
  error?: string;
  children: React.ReactNode;
}> = ({ label, required, hint, error, children }) => (
  <div className="grid min-w-0 grid-cols-[72px_minmax(0,1fr)] gap-x-3">
    <label className="flex h-[34px] items-center justify-end text-right text-[11px] font-medium text-text-secondary select-none">
      {label}{required && <span className="ml-0.5 text-accent">*</span>}
    </label>
    <div className="min-w-0">
      {children}
      {error && <p className="mt-1 text-[10px] leading-snug text-error">{error}</p>}
      {hint && !error && <p className="mt-1 text-[10px] leading-snug text-text-tertiary">{hint}</p>}
    </div>
  </div>
);

const Section: React.FC<{
  title: string;
  description: string;
  summary?: string;
  children: React.ReactNode;
}> = ({ title, description, summary, children }) => (
  <section className="relative w-full min-w-0 overflow-visible rounded-lg border border-line bg-surface-1/80 shadow-[var(--shadow-card)]">
    <div className="flex min-h-[46px] items-center gap-2 px-4 pb-2 pt-3">
      <div className="min-w-0">
        <h3 className="text-[12px] font-semibold text-text-primary">{title}</h3>
        <p className="mt-0.5 text-[9.5px] text-text-tertiary">{description}</p>
      </div>
      {summary && (
        <span className="ml-auto shrink-0 rounded-full bg-surface-2 px-2 py-1 text-[9px] text-text-tertiary">
          {summary}
        </span>
      )}
    </div>
    <div className="min-w-0 px-3.5 pb-3.5 pt-1">{children}</div>
  </section>
);

const ChoiceGroup: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <div className="grid h-[34px] grid-cols-2 gap-1 rounded-md bg-surface-base/70 p-1">
    {children}
  </div>
);

const Choice: React.FC<{
  active: boolean;
  label: string;
  onClick: () => void;
}> = ({ active, label, onClick }) => (
  <button
    type="button"
    onClick={onClick}
    data-active={active}
    className="flex min-w-0 items-center justify-center gap-2 rounded border border-transparent px-2 text-[11px] font-medium text-text-tertiary transition-colors hover:bg-surface-2 hover:text-text-secondary data-[active=true]:border-[#454d59] data-[active=true]:bg-[#343a44] data-[active=true]:text-text-primary data-[active=true]:shadow-[0_1px_2px_rgba(0,0,0,0.28)]"
  >
    <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-transparent data-[active=true]:bg-accent" data-active={active} />
    <span className="truncate">{label}</span>
  </button>
);

const CompactToggle: React.FC<{
  checked: boolean;
  onChange: (checked: boolean) => void;
  label: string;
}> = ({ checked, onChange, label }) => (
  <label className="flex h-[34px] cursor-pointer items-center gap-2 rounded-md bg-surface-input px-3 text-[10.5px] text-text-secondary transition-colors hover:bg-surface-2">
    <input
      type="checkbox"
      checked={checked}
      onChange={(event) => onChange(event.target.checked)}
      className="h-3.5 w-3.5 accent-accent"
    />
    <span>{label}</span>
  </label>
);

const deriveCli = (config?: ProjectConfig): CliKind => {
  if (config?.mode === 'custom') return config.custom_cli === 'codex' ? 'codex' : 'claude';
  return config?.mode === 'codex' ? 'codex' : 'claude';
};

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
  const [cli, setCli] = useState<CliKind>(deriveCli(initialConfig));
  const [source, setSource] = useState<ServiceSource>(initialConfig?.mode === 'custom' ? 'custom_api' : 'account');
  const [isPinned, setIsPinned] = useState(initialIsPinned);
  const [moreOpen, setMoreOpen] = useState(true);
  const [claudeProxyPresetId, setClaudeProxyPresetId] = useState<string | null>(
    initialConfig?.claude_proxy_preset_id ?? (initialConfig?.mode === 'claude' ? initialConfig.proxy_preset_id : null) ?? null,
  );
  const [codexProxyPresetId, setCodexProxyPresetId] = useState<string | null>(
    initialConfig?.codex_proxy_preset_id ?? (initialConfig?.mode === 'codex' ? initialConfig.proxy_preset_id : null) ?? null,
  );
  const [claudeModelPresetId, setClaudeModelPresetId] = useState<string | null>(
    initialConfig?.claude_model_preset_id
      ?? (initialConfig?.mode === 'custom' && initialConfig.custom_cli !== 'codex' ? initialConfig.model_preset_id : null)
      ?? null,
  );
  const [codexModelPresetId, setCodexModelPresetId] = useState<string | null>(
    initialConfig?.codex_model_preset_id
      ?? (initialConfig?.mode === 'custom' && initialConfig.custom_cli === 'codex' ? initialConfig.model_preset_id : null)
      ?? null,
  );
  const [skipPermissions, setSkipPermissions] = useState(initialConfig?.skip_permissions ?? true);
  const [errors, setErrors] = useState<Record<string, string>>({});

  useEffect(() => {
    if (!initialWorkingDirectory) return;
    setWorkingDirectory(initialWorkingDirectory);
    if (!name) {
      const folder = initialWorkingDirectory.replace(/[\\/]+$/, '').split(/[\\/]/).pop();
      if (folder) setName(folder);
    }
  }, [initialWorkingDirectory]);

  useEffect(() => {
    if (!initialConfig) return;
    const nextCli = deriveCli(initialConfig);
    setCli(nextCli);
    setSource(initialConfig.mode === 'custom' ? 'custom_api' : 'account');
    setClaudeProxyPresetId(initialConfig.claude_proxy_preset_id ?? (initialConfig.mode === 'claude' ? initialConfig.proxy_preset_id : null) ?? null);
    setCodexProxyPresetId(initialConfig.codex_proxy_preset_id ?? (initialConfig.mode === 'codex' ? initialConfig.proxy_preset_id : null) ?? null);
    setClaudeModelPresetId(initialConfig.claude_model_preset_id ?? (initialConfig.mode === 'custom' && nextCli === 'claude' ? initialConfig.model_preset_id : null) ?? null);
    setCodexModelPresetId(initialConfig.codex_model_preset_id ?? (initialConfig.mode === 'custom' && nextCli === 'codex' ? initialConfig.model_preset_id : null) ?? null);
    setSkipPermissions(initialConfig.skip_permissions ?? true);
  }, [initialConfig]);

  useEffect(() => { setIsPinned(initialIsPinned); }, [initialIsPinned]);

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    const nextErrors: Record<string, string> = {};
    const selectedModel = cli === 'codex' ? codexModelPresetId : claudeModelPresetId;
    if (!name.trim()) nextErrors.name = '请输入项目名称';
    if (!workingDirectory.trim()) nextErrors.workingDirectory = '请选择工作目录';
    if (source === 'custom_api' && !selectedModel) nextErrors.modelPreset = '请选择或新建一个兼容的模型配置';
    setErrors(nextErrors);
    if (Object.keys(nextErrors).length > 0) return;

    const mode: ProjectConfig['mode'] = source === 'custom_api' ? 'custom' : cli;
    onSubmit(name.trim(), workingDirectory.trim(), {
      mode,
      proxy: '',
      model: '',
      base_url: '',
      token: '',
      skip_permissions: skipPermissions,
      codex_api_key: '',
      custom_cli: cli,
      proxy_preset_id: null,
      claude_proxy_preset_id: claudeProxyPresetId,
      codex_proxy_preset_id: codexProxyPresetId,
      model_preset_id: source === 'custom_api' ? selectedModel : null,
      claude_model_preset_id: claudeModelPresetId,
      codex_model_preset_id: codexModelPresetId,
    }, isPinned);
  };

  const activeProxy = cli === 'codex' ? codexProxyPresetId : claudeProxyPresetId;
  const setActiveProxy = cli === 'codex' ? setCodexProxyPresetId : setClaudeProxyPresetId;
  const activeModel = cli === 'codex' ? codexModelPresetId : claudeModelPresetId;
  const setActiveModel = cli === 'codex' ? setCodexModelPresetId : setClaudeModelPresetId;
  const toolName = cli === 'codex' ? 'Codex' : 'Claude Code';
  const sourceName = source === 'custom_api' ? '自定义 API' : '官方账号';

  return (
    <form onSubmit={submit} className="mx-auto w-full min-w-0 max-w-[680px] space-y-3 pb-2">
      <Section title="基础信息" description="项目名称与工作目录">
        <div className="space-y-3">
          <FormRow label="项目名称" required error={errors.name}>
            <input type="text" value={name} onChange={(event) => setName(event.target.value)} placeholder="输入项目名称" disabled={isDefault} className="disabled:opacity-50" />
          </FormRow>
          <FormRow label="工作目录" required error={errors.workingDirectory} hint={isDefault ? '默认项目的工作目录不可修改' : '支持直接拖入文件夹'}>
            <DirectoryPicker value={workingDirectory} onChange={setWorkingDirectory} placeholder="选择项目工作目录" disabled={isDefault} />
          </FormRow>
        </div>
      </Section>

      <Section title="运行方式" description="选择工具及其连接的服务" summary={`${toolName} · ${sourceName}`}>
        <div className="space-y-1 rounded-md bg-surface-input/40 p-1">
          <div className="rounded-md p-2.5">
            <FormRow label="启动工具">
              <ChoiceGroup>
                <Choice active={cli === 'claude'} label="Claude Code" onClick={() => setCli('claude')} />
                <Choice active={cli === 'codex'} label="Codex" onClick={() => setCli('codex')} />
              </ChoiceGroup>
            </FormRow>
          </div>

          <div className="rounded-md p-2.5">
            <FormRow label="服务来源">
              <ChoiceGroup>
                <Choice active={source === 'custom_api'} label="自定义 API" onClick={() => setSource('custom_api')} />
                <Choice active={source === 'account'} label="官方账号" onClick={() => setSource('account')} />
              </ChoiceGroup>
            </FormRow>
          </div>

          <div className="rounded-md bg-surface-2/60 p-2.5">
            {source === 'account' ? (
              <FormRow label="代理" hint={`用于连接原版 ${toolName} 服务；不需要可留空`}>
                <PresetSelect kind="proxy" value={activeProxy} onChange={setActiveProxy} allowEmpty />
              </FormRow>
            ) : (
              <FormRow
                label="模型"
                required
                error={errors.modelPreset}
                hint={cli === 'codex' ? '仅显示兼容 Responses API 的模型配置' : '仅显示兼容 Messages API 的模型配置'}
              >
                <PresetSelect
                  kind="model"
                  value={activeModel}
                  onChange={setActiveModel}
                  modelApiFormat={cli === 'codex' ? 'openai_responses' : 'anthropic_messages'}
                  allowEmpty
                  emptyLabel="请选择或新建模型配置"
                />
              </FormRow>
            )}
          </div>
        </div>

        <div className="mt-2.5 pt-1">
          <button
            type="button"
            onClick={() => setMoreOpen((open) => !open)}
            className="flex h-7 w-full items-center gap-2 px-1 text-left text-[10.5px] text-text-secondary hover:text-text-primary"
          >
            <svg className={`transition-transform ${moreOpen ? 'rotate-90' : ''}`} width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><polyline points="9 18 15 12 9 6" /></svg>
            <span className="font-medium">更多设置</span>
            <span className="ml-auto text-[9.5px] text-text-tertiary">{skipPermissions ? '跳过确认' : '普通模式'}{isPinned ? ' · 已置顶' : ''}</span>
          </button>
          {moreOpen && (
            <div className="grid grid-cols-2 gap-2 pt-2">
              <CompactToggle checked={skipPermissions} onChange={setSkipPermissions} label="跳过权限确认" />
              <CompactToggle checked={isPinned} onChange={setIsPinned} label="置顶项目" />
            </div>
          )}
        </div>
      </Section>

      <div className="flex items-center gap-2 pt-1">
        {!isDefault && onDelete && <button type="button" onClick={onDelete} className="btn btn-danger">删除项目</button>}
        <div className="flex-1" />
        <button type="button" onClick={onCancel} className="btn btn-ghost">取消</button>
        <button type="submit" className="btn btn-accent min-w-[84px]">{submitLabel}</button>
      </div>
    </form>
  );
};
