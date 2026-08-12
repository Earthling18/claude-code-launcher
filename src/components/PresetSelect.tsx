import { useEffect, useRef, useState } from 'react';
import { presetsApi } from '../api';
import type { ModelApiFormat, ModelPreset, ProxyPreset } from '../types/presets';
import { PresetManagerDialog } from './PresetManagerDialog';

type Kind = 'proxy' | 'model';

const modelEndpoint = (model: ModelPreset, format: ModelApiFormat) => {
  const current = format === 'anthropic_messages' ? model.claude_base_url : model.codex_base_url;
  if (current) return current;
  return (model.api_format ?? 'anthropic_messages') === format ? model.base_url ?? '' : '';
};

const modelBadge = (model: ModelPreset) => {
  const claude = !!modelEndpoint(model, 'anthropic_messages');
  const codex = !!modelEndpoint(model, 'openai_responses');
  if (claude && codex) return 'Claude + Codex';
  return codex ? 'Codex' : 'Claude';
};

interface PresetSelectProps {
  kind: Kind;
  value: string | null | undefined;
  onChange: (id: string | null) => void;
  allowEmpty?: boolean;
  emptyLabel?: string;
  modelApiFormat?: ModelApiFormat;
}

export const PresetSelect: React.FC<PresetSelectProps> = ({
  kind,
  value,
  onChange,
  allowEmpty = true,
  emptyLabel,
  modelApiFormat,
}) => {
  const [proxies, setProxies] = useState<ProxyPreset[]>([]);
  const [models, setModels] = useState<ModelPreset[]>([]);
  const [showManager, setShowManager] = useState(false);
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState(false);
  const wrapperRef = useRef<HTMLDivElement>(null);

  const reload = async () => {
    try {
      setLoading(true);
      const data = await presetsApi.getAll();
      setProxies(data.proxies);
      setModels(data.models);
    } catch (error) {
      console.error('Failed to load presets:', error);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { reload(); }, []);

  useEffect(() => {
    if (!open) return;
    const onPointer = (event: MouseEvent) => {
      if (wrapperRef.current && !wrapperRef.current.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false);
    };
    document.addEventListener('mousedown', onPointer);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onPointer);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  const compatibleModels = models.filter((model) => {
    if (!modelApiFormat) return true;
    return !!modelEndpoint(model, modelApiFormat);
  });
  const items = kind === 'proxy'
    ? proxies.map((proxy) => ({ id: proxy.id, label: proxy.name, subLabel: proxy.url }))
    : compatibleModels.map((model) => ({
        id: model.id,
        label: model.name,
        subLabel: modelApiFormat
          ? modelEndpoint(model, modelApiFormat) || undefined
          : [modelEndpoint(model, 'anthropic_messages'), modelEndpoint(model, 'openai_responses')].filter(Boolean).join(' · ') || undefined,
        badge: modelBadge(model),
      }));

  const stale = !!value && !items.some((item) => item.id === value);
  const selected = stale ? undefined : items.find((item) => item.id === value);
  const fallbackLabel = kind === 'proxy' ? '不使用代理' : '请选择模型配置';
  const pick = (id: string | null) => {
    onChange(id);
    setOpen(false);
  };

  return (
    <>
      <div className={`relative ${open ? 'z-[60]' : ''}`} ref={wrapperRef}>
        <button
          type="button"
          onClick={() => setOpen((value) => !value)}
          data-open={open}
          className="w-full h-[34px] px-3 pr-8 font-mono text-left text-[12.5px] bg-surface-input border border-line rounded-sm text-text-primary hover:border-line-strong data-[open=true]:border-accent data-[open=true]:shadow-[var(--shadow-focus)] transition-colors flex items-center"
        >
          <span className={`truncate ${selected ? '' : 'text-text-tertiary'}`}>
            {selected ? selected.label : stale ? '(已删除或不兼容的配置)' : (emptyLabel ?? fallbackLabel)}
          </span>
        </button>
        <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-text-tertiary">
          <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><polyline points="6 9 12 15 18 9" /></svg>
        </span>

        {open && (
          <div className="absolute z-[70] left-0 right-0 mt-1 max-h-72 overflow-auto rounded-sm border border-line bg-surface-1 shadow-lg py-1">
            {allowEmpty && (
              <DropdownRow onSelect={() => pick(null)} active={!selected && !stale}>
                <span className="text-text-tertiary italic">{emptyLabel ?? fallbackLabel}</span>
              </DropdownRow>
            )}
            {items.length === 0 && !loading && (
              <div className="px-3 py-2 text-[11px] text-text-tertiary italic">
                还没有兼容的{kind === 'proxy' ? '代理' : '模型'}配置
              </div>
            )}
            {items.map((item) => (
              <DropdownRow key={item.id} onSelect={() => pick(item.id)} active={item.id === value}>
                <div className="flex items-center gap-3 min-w-0 w-full">
                  <div className="min-w-0 flex-1">
                    <div className="font-mono text-[12px] text-text-primary truncate">{item.label}</div>
                    {item.subLabel && <div className="font-mono text-[10.5px] text-text-tertiary truncate mt-0.5">{item.subLabel}</div>}
                  </div>
                  {'badge' in item && item.badge && (
                    <span className="text-[9.5px] text-text-tertiary border border-line-strong px-1.5 py-0.5 rounded-sm shrink-0">{item.badge}</span>
                  )}
                </div>
              </DropdownRow>
            ))}
            {!loading && items.length > 0 && <div className="h-px bg-line mx-2 my-1" />}
            {!loading && (
              <DropdownRow onSelect={() => { setShowManager(true); setOpen(false); }}>
                <span className="font-mono text-[12px] text-accent">管理{kind === 'proxy' ? '代理' : '模型'}…</span>
              </DropdownRow>
            )}
          </div>
        )}
      </div>

      <PresetManagerDialog
        isOpen={showManager}
        kind={kind}
        modelApiFormat={modelApiFormat}
        onClose={() => { setShowManager(false); reload(); }}
        onChanged={(newId, supportedFormats) => {
          reload();
          if (!newId) return;
          if (kind !== 'model' || !modelApiFormat || supportedFormats?.includes(modelApiFormat)) {
            onChange(newId);
          } else if (value === newId) {
            onChange(null);
          }
        }}
      />
    </>
  );
};

const DropdownRow: React.FC<{
  onSelect: () => void;
  active?: boolean;
  children: React.ReactNode;
}> = ({ onSelect, active, children }) => (
  <button
    type="button"
    onClick={onSelect}
    data-active={!!active}
    className="w-full text-left px-3 py-1.5 hover:bg-surface-2 data-[active=true]:bg-accent/10 transition-colors flex"
  >
    {children}
  </button>
);
