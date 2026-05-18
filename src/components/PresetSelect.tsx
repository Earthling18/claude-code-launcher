import { useCallback, useEffect, useRef, useState } from 'react';
import { presetsApi } from '../api';
import type { ProxyPreset, ModelPreset } from '../types/presets';
import { PresetManagerDialog } from './PresetManagerDialog';

type Kind = 'proxy' | 'model';
type RowProbe = 'loading' | { ok: true; latency_ms: number } | { ok: false };

interface PresetSelectProps {
  kind: Kind;
  value: string | null | undefined;
  onChange: (id: string | null) => void;
  allowEmpty?: boolean;
  emptyLabel?: string;
}

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
  const [probes, setProbes] = useState<Record<string, RowProbe>>({});
  const probingRef = useRef(false);
  const [open, setOpen] = useState(false);
  const wrapperRef = useRef<HTMLDivElement>(null);

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

  const probeAll = useCallback(() => {
    if (kind !== 'model' || probingRef.current) return;
    const targets = models.filter(m => m.base_url);
    if (targets.length === 0) return;
    probingRef.current = true;
    setProbes(s => {
      const next = { ...s };
      targets.forEach(m => { next[m.id] = 'loading'; });
      return next;
    });
    Promise.allSettled(
      targets.map(m =>
        presetsApi.probeModel(m.base_url, m.token).then(r => ({ m, r }))
      )
    ).then(results => {
      setProbes(s => {
        const next = { ...s };
        results.forEach(res => {
          if (res.status === 'fulfilled') {
            const { m, r } = res.value;
            next[m.id] = r.ok ? { ok: true, latency_ms: r.latency_ms } : { ok: false };
          }
        });
        return next;
      });
    }).finally(() => { probingRef.current = false; });
  }, [kind, models]);

  // Auto-probe once after models are loaded (first time only).
  useEffect(() => {
    if (kind === 'model' && !loading && models.length > 0 && Object.keys(probes).length === 0) {
      probeAll();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [kind, loading, models.length]);

  // Close on outside click / Esc.
  useEffect(() => {
    if (!open) return;
    const onDocPointer = (e: MouseEvent) => {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false);
    };
    document.addEventListener('mousedown', onDocPointer);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDocPointer);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  type Item = {
    id: string;
    label: string;
    subLabel?: string;
    tail?: string;
    color?: string;
  };

  const items: Item[] =
    kind === 'proxy'
      ? proxies.map(p => ({ id: p.id, label: p.name, subLabel: p.url }))
      : models.map(m => {
          const p = probes[m.id];
          let tail: string | undefined;
          let color: string | undefined;
          if (p === 'loading') {
            tail = '检测中…';
            color = 'var(--text-tertiary)';
          } else if (p && p.ok) {
            tail = `${p.latency_ms}ms`;
            color = p.latency_ms < 300 ? 'var(--ok)' : p.latency_ms < 1000 ? 'var(--warn)' : 'var(--error)';
          } else if (p && !p.ok) {
            tail = '不可达';
            color = 'var(--error)';
          }
          return { id: m.id, label: m.name, subLabel: m.base_url || undefined, tail, color };
        });

  const isStaleId = !!value && !items.some(i => i.id === value);
  const selectedItem = !isStaleId ? items.find(i => i.id === value) : undefined;
  const defaultEmptyLabel = kind === 'proxy' ? '不使用代理' : '请选择模型配置';

  const toggleOpen = () => {
    const next = !open;
    setOpen(next);
    if (next && kind === 'model') probeAll();
  };

  const pick = (id: string | null) => {
    onChange(id);
    setOpen(false);
  };

  return (
    <>
      <div className="relative" ref={wrapperRef}>
        {/* Trigger button: matches .input/select global styling */}
        <button
          type="button"
          onClick={toggleOpen}
          data-open={open}
          className="w-full h-[34px] px-3 pr-8 font-mono text-left text-[12.5px] bg-surface-input border border-line rounded-sm text-text-primary hover:border-line-strong data-[open=true]:border-accent data-[open=true]:shadow-[var(--shadow-focus)] transition-colors flex items-center"
        >
          <span className={`truncate ${selectedItem ? '' : 'text-text-tertiary'}`}>
            {selectedItem
              ? selectedItem.label
              : isStaleId
                ? '(已删除的配置)'
                : (emptyLabel ?? defaultEmptyLabel)}
          </span>
        </button>
        {/* Chevron */}
        <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-text-tertiary">
          <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><polyline points="6 9 12 15 18 9" /></svg>
        </span>

        {/* Dropdown panel */}
        {open && (
          <div className="absolute z-50 left-0 right-0 mt-1 max-h-72 overflow-auto rounded-sm border border-line bg-surface-1 shadow-lg py-1">
            {allowEmpty && (
              <DropdownRow
                onSelect={() => pick(null)}
                active={!selectedItem && !isStaleId}
              >
                <span className="text-text-tertiary italic">{emptyLabel ?? defaultEmptyLabel}</span>
              </DropdownRow>
            )}

            {items.length === 0 && !loading && (
              <div className="px-3 py-2 text-[11px] text-text-tertiary italic">
                还没有{kind === 'proxy' ? '代理' : '模型'}配置
              </div>
            )}

            {items.map(it => (
              <DropdownRow
                key={it.id}
                onSelect={() => pick(it.id)}
                active={it.id === value}
              >
                <div className="flex items-center gap-3 min-w-0 w-full">
                  <div className="min-w-0 flex-1">
                    <div className="font-mono text-[12px] text-text-primary truncate">
                      {it.label}
                    </div>
                    {it.subLabel && (
                      <div className="font-mono text-[10.5px] text-text-tertiary truncate mt-0.5">
                        {it.subLabel}
                      </div>
                    )}
                  </div>
                  {it.tail && (
                    <span
                      className="font-mono text-[11px] tabular-nums shrink-0 ml-auto"
                      style={{ color: it.color }}
                    >
                      {it.tail}
                    </span>
                  )}
                </div>
              </DropdownRow>
            ))}

            {!loading && items.length > 0 && (
              <div className="h-px bg-line mx-2 my-1" />
            )}

            {!loading && (
              <DropdownRow
                onSelect={() => { setShowManager(true); setOpen(false); }}
              >
                <span className="font-mono text-[12px] text-accent">
                  ⚙  管理{kind === 'proxy' ? '代理' : '模型'}…
                </span>
              </DropdownRow>
            )}
          </div>
        )}
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
