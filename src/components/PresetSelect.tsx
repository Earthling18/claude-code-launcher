import { useEffect, useState } from 'react';
import { presetsApi } from '../api';
import type { ProxyPreset, ModelPreset } from '../types/presets';
import { PresetManagerDialog } from './PresetManagerDialog';

type Kind = 'proxy' | 'model';

interface PresetSelectProps {
  kind: Kind;
  value: string | null | undefined;
  onChange: (id: string | null) => void;
  allowEmpty?: boolean;
  emptyLabel?: string;
}

const MANAGE_SENTINEL = '__manage__';

export const PresetSelect: React.FC<PresetSelectProps> = ({
  kind,
  value,
  onChange,
  allowEmpty = true,
  emptyLabel,
}) => {
  const [proxies, setProxies] = useState<ProxyPreset[]>([]);
  const [models, setModels] = useState<ModelPreset[]>([]);
  const [showManager, setShowManager] = useState(false);
  const [loading, setLoading] = useState(true);

  const reload = async () => {
    try {
      setLoading(true);
      const data = await presetsApi.getAll();
      setProxies(data.proxies);
      setModels(data.models);
    } catch (err) {
      console.error('Failed to load presets:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { reload(); }, []);

  const items: { id: string; label: string; subLabel?: string }[] =
    kind === 'proxy'
      ? proxies.map(p => ({ id: p.id, label: p.name, subLabel: p.url }))
      : models.map(m => ({ id: m.id, label: m.name, subLabel: m.base_url || undefined }));

  const isStaleId = !!value && !items.some(i => i.id === value);
  const selectValue = value && !isStaleId ? value : '';
  const defaultEmptyLabel = kind === 'proxy' ? '不使用代理' : '请选择模型配置';

  const handleChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const v = e.target.value;
    if (v === MANAGE_SENTINEL) {
      setShowManager(true);
      return;
    }
    onChange(v || null);
  };

  return (
    <>
      <div className="relative">
        <select
          value={selectValue}
          onChange={handleChange}
          className="font-mono pr-8 appearance-none"
        >
          {allowEmpty && (
            <option value="">{emptyLabel ?? defaultEmptyLabel}</option>
          )}
          {!allowEmpty && !selectValue && (
            <option value="" disabled>{emptyLabel ?? defaultEmptyLabel}</option>
          )}
          {isStaleId && (
            <option value={value as string} disabled>(已删除的配置)</option>
          )}
          {items.map(it => (
            <option key={it.id} value={it.id}>
              {it.subLabel ? `${it.label}  —  ${it.subLabel}` : it.label}
            </option>
          ))}
          {!loading && items.length > 0 && (
            <option disabled>──────────────────</option>
          )}
          {!loading && (
            <option value={MANAGE_SENTINEL}>
              ⚙  管理{kind === 'proxy' ? '代理' : '模型'}…
            </option>
          )}
        </select>
        {/* Custom chevron */}
        <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-text-tertiary">
          <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><polyline points="6 9 12 15 18 9" /></svg>
        </span>
      </div>

      <PresetManagerDialog
        isOpen={showManager}
        kind={kind}
        onClose={() => { setShowManager(false); reload(); }}
        onChanged={(newId) => {
          reload();
          if (newId) onChange(newId);
        }}
      />
    </>
  );
};
