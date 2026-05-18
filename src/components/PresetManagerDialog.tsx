import { useCallback, useEffect, useRef, useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { presetsApi } from '../api';
import { toast } from '../lib/toast';
import { ConfirmDialog } from './ConfirmDialog';
import type { ProxyPreset, ModelPreset, ModelProbeResult } from '../types/presets';

type ProbeState =
  | { kind: 'idle' }
  | { kind: 'loading' }
  | { kind: 'success'; result: ModelProbeResult }
  | { kind: 'error'; error: string };

function useProbeModel() {
  const [state, setState] = useState<ProbeState>({ kind: 'idle' });
  const seqRef = useRef(0);
  const run = useCallback(async (baseUrl: string, token: string) => {
    const url = baseUrl.trim();
    if (!url) { setState({ kind: 'error', error: '请先填写 Base URL' }); return; }
    if (!url.startsWith('http://') && !url.startsWith('https://')) {
      setState({ kind: 'error', error: 'Base URL 必须以 http:// 或 https:// 开头' });
      return;
    }
    const mySeq = ++seqRef.current;
    setState({ kind: 'loading' });
    try {
      const result = await presetsApi.probeModel(url, token);
      if (mySeq !== seqRef.current) return;
      if (result.ok) setState({ kind: 'success', result });
      else setState({ kind: 'error', error: result.error || `HTTP ${result.status}` });
    } catch (err: any) {
      if (mySeq !== seqRef.current) return;
      setState({ kind: 'error', error: err?.toString() || '检测失败' });
    }
  }, []);
  const reset = useCallback(() => { seqRef.current++; setState({ kind: 'idle' }); }, []);
  return { state, run, reset };
}

type RowProbeState = 'loading' | { ok: true; latency_ms: number; models: string[] } | { ok: false; error: string };

type Kind = 'proxy' | 'model';

interface PresetManagerDialogProps {
  isOpen: boolean;
  kind: Kind;
  onClose: () => void;
  onChanged?: (newId?: string) => void;
  /** Show tab switcher between proxy/model at the top. */
  showTabs?: boolean;
}

interface ProxyDraft {
  id?: string;
  name: string;
  url: string;
}

interface ModelDraft {
  id?: string;
  // name auto-derived from `model`
  model: string;
  base_url: string;
  token: string;
}

function deriveModelName(model: string, baseUrl: string): string {
  if (model.trim()) return model.trim();
  const stripped = baseUrl.replace(/^https?:\/\//, '').replace(/\/+$/, '');
  const host = stripped.split('/')[0];
  return host || '未命名模型';
}

export const PresetManagerDialog: React.FC<PresetManagerDialogProps> = ({
  isOpen,
  kind: initialKind,
  onClose,
  onChanged,
  showTabs = false,
}) => {
  const [kind, setKind] = useState<Kind>(initialKind);
  const [proxies, setProxies] = useState<ProxyPreset[]>([]);
  const [models, setModels] = useState<ModelPreset[]>([]);
  const [loading, setLoading] = useState(false);
  const [draft, setDraft] = useState<ProxyDraft | ModelDraft | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showToken, setShowToken] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<{ id: string; refs: number; name: string } | null>(null);
  const { state: probeState, run: probeRun, reset: probeReset } = useProbeModel();
  const [rowProbes, setRowProbes] = useState<Record<string, RowProbeState>>({});

  // Auto-trigger endpoint probe (debounced) when both base_url and token are filled.
  useEffect(() => {
    if (kind !== 'model' || !draft) return;
    const d = draft as ModelDraft;
    const url = d.base_url.trim();
    const tok = d.token.trim();
    if (!url || !tok) {
      probeReset();
      return;
    }
    if (!url.startsWith('http://') && !url.startsWith('https://')) return;
    const handle = window.setTimeout(() => probeRun(url, tok), 600);
    return () => window.clearTimeout(handle);
  }, [
    kind,
    draft && (draft as ModelDraft).base_url,
    draft && (draft as ModelDraft).token,
    probeRun,
    probeReset,
  ]);

  useEffect(() => {
    if (isOpen) {
      setKind(initialKind);
      loadAll();
      setDraft(null);
      setError(null);
      probeReset();
      setRowProbes({});
    }
  }, [isOpen, initialKind]);

  useEffect(() => {
    if (isOpen) {
      setDraft(null);
      setError(null);
      probeReset();
    }
  }, [kind]);

  const loadAll = async () => {
    try {
      setLoading(true);
      const data = await presetsApi.getAll();
      setProxies(data.proxies);
      setModels(data.models);
    } catch (err: any) {
      setError(err?.toString() || '加载失败');
    } finally {
      setLoading(false);
    }
  };

  const startCreate = () => {
    setError(null);
    setShowToken(false);
    probeReset();
    if (kind === 'proxy') {
      setDraft({ name: '', url: '' });
    } else {
      setDraft({ model: '', base_url: '', token: '' });
    }
  };

  const startEditProxy = (p: ProxyPreset) => {
    setError(null);
    setDraft({ id: p.id, name: p.name, url: p.url });
  };

  const startEditModel = (m: ModelPreset) => {
    setError(null);
    setShowToken(false);
    probeReset();
    setDraft({ id: m.id, model: m.model, base_url: m.base_url, token: m.token });
  };

  const probeRow = async (m: ModelPreset) => {
    if (!m.base_url) {
      setRowProbes((s) => ({ ...s, [m.id]: { ok: false, error: '无 Base URL' } }));
      return;
    }
    setRowProbes((s) => ({ ...s, [m.id]: 'loading' }));
    try {
      const r = await presetsApi.probeModel(m.base_url, m.token);
      if (r.ok) {
        setRowProbes((s) => ({ ...s, [m.id]: { ok: true, latency_ms: r.latency_ms, models: r.models } }));
      } else {
        setRowProbes((s) => ({ ...s, [m.id]: { ok: false, error: r.error || `HTTP ${r.status}` } }));
      }
    } catch (err: any) {
      setRowProbes((s) => ({ ...s, [m.id]: { ok: false, error: err?.toString() || '检测失败' } }));
    }
  };

  const handleSave = async () => {
    if (!draft) return;
    try {
      setError(null);
      let newId: string | undefined;
      if (kind === 'proxy') {
        const d = draft as ProxyDraft;
        if (!d.name.trim()) { setError('请输入名称'); return; }
        if (!d.url.trim()) { setError('请输入代理地址'); return; }
        if (!d.url.startsWith('http://') && !d.url.startsWith('https://')) {
          setError('代理地址必须以 http:// 或 https:// 开头'); return;
        }
        if (d.id) {
          const p = await presetsApi.updateProxy(d.id, d.name.trim(), d.url.trim());
          newId = p.id;
        } else {
          const p = await presetsApi.createProxy(d.name.trim(), d.url.trim());
          newId = p.id;
        }
      } else {
        const d = draft as ModelDraft;
        if (!d.model.trim() && !d.base_url.trim()) {
          setError('请至少填写模型名称或 Base URL'); return;
        }
        if (d.base_url && !d.base_url.startsWith('http://') && !d.base_url.startsWith('https://')) {
          setError('Base URL 必须以 http:// 或 https:// 开头'); return;
        }
        const autoName = deriveModelName(d.model, d.base_url);
        if (d.id) {
          const m = await presetsApi.updateModel(d.id, autoName, d.model.trim(), d.base_url.trim(), d.token);
          newId = m.id;
        } else {
          const m = await presetsApi.createModel(autoName, d.model.trim(), d.base_url.trim(), d.token);
          newId = m.id;
        }
      }
      setDraft(null);
      probeReset();
      await loadAll();
      onChanged?.(newId);
    } catch (err: any) {
      setError(err?.toString() || '保存失败');
    }
  };

  // Step 1: ask backend for ref count, then open confirm dialog (no actual delete yet).
  const requestDelete = async (id: string, name: string) => {
    try {
      const refs = kind === 'proxy'
        ? await presetsApi.countProxyRefs(id)
        : await presetsApi.countModelRefs(id);
      setPendingDelete({ id, refs, name });
    } catch (err: any) {
      toast.error(`查询引用失败: ${err}`);
    }
  };

  // Step 2: actually delete after user confirms.
  const confirmDelete = async () => {
    if (!pendingDelete) return;
    const { id } = pendingDelete;
    try {
      if (kind === 'proxy') await presetsApi.deleteProxy(id);
      else await presetsApi.deleteModel(id);
      setPendingDelete(null);
      await loadAll();
      onChanged?.();
      toast.success(kind === 'proxy' ? '代理已删除' : '模型已删除');
    } catch (err: any) {
      setPendingDelete(null);
      toast.error(`删除失败: ${err}`);
    }
  };

  if (!isOpen) return null;

  const items = kind === 'proxy' ? proxies : models;

  return (
    <AnimatePresence>
      <motion.div
        className="modal-overlay"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        transition={{ duration: 0.15 }}
        onClick={onClose}
      >
        <motion.div
          className="modal-panel w-[600px] max-w-[92vw] max-h-[82vh]"
          initial={{ opacity: 0, scale: 0.96, y: 8 }}
          animate={{ opacity: 1, scale: 1, y: 0 }}
          exit={{ opacity: 0, scale: 0.98, y: 4 }}
          transition={{ duration: 0.18, ease: [0.2, 0.8, 0.2, 1] }}
          onClick={(e) => e.stopPropagation()}
        >
          {/* Header */}
          <div className="flex items-center justify-between px-5 pt-4 pb-0">
            {showTabs ? (
              <div className="flex items-center -mb-px">
                <button
                  type="button"
                  onClick={() => setKind('model')}
                  data-active={kind === 'model'}
                  className="tab"
                >
                  模型配置
                </button>
                <button
                  type="button"
                  onClick={() => setKind('proxy')}
                  data-active={kind === 'proxy'}
                  className="tab"
                >
                  代理配置
                </button>
              </div>
            ) : (
              <h3 className="text-[14px] font-semibold text-text-primary">
                {kind === 'proxy' ? '管理代理配置' : '管理模型配置'}
              </h3>
            )}
            <button
              type="button"
              onClick={onClose}
              className="btn btn-ghost btn-icon !h-7 !w-7 -mr-1"
              title="关闭"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
              </svg>
            </button>
          </div>

          {/* Divider under tabs */}
          <div className="h-px bg-line-strong mx-0" />

          {/* Body */}
          <div className="flex-1 overflow-auto min-h-0">
            {error && (
              <div className="mx-5 mt-3 px-3 py-2 text-[11px] text-error border border-error/30 bg-error/5 rounded">
                {error}
              </div>
            )}

            {/* Edit / Create form */}
            <AnimatePresence>
              {draft && (
                <motion.div
                  key="draft"
                  initial={{ opacity: 0, height: 0 }}
                  animate={{ opacity: 1, height: 'auto' }}
                  exit={{ opacity: 0, height: 0 }}
                  transition={{ duration: 0.18, ease: [0.2, 0.8, 0.2, 1] }}
                  className="overflow-hidden"
                >
                  <div className="mx-5 mt-3 mb-1 p-4 rounded bg-surface-1 border border-accent/30 relative">
                    <div className="absolute left-0 top-0 bottom-0 w-[3px] bg-accent rounded-l" />
                    <div className="font-mono text-[10px] uppercase tracking-[0.2em] text-accent mb-3">
                      {draft.id ? 'EDIT' : 'NEW'}
                    </div>
                    <div className="space-y-3">
                      {kind === 'proxy' && (
                        <Field label="名称">
                          <input
                            type="text"
                            value={(draft as ProxyDraft).name}
                            onChange={(e) => setDraft({ ...draft, name: e.target.value } as any)}
                            placeholder="例: 公司 VPN"
                          />
                        </Field>
                      )}
                      {kind === 'proxy' ? (
                        <Field label="代理地址">
                          <input
                            type="text"
                            value={(draft as ProxyDraft).url}
                            onChange={(e) => setDraft({ ...draft, url: e.target.value } as any)}
                            placeholder="http://127.0.0.1:7890"
                            className="font-mono"
                          />
                        </Field>
                      ) : (
                        <>
                          <Field label="Model">
                            <input
                              type="text"
                              value={(draft as ModelDraft).model}
                              onChange={(e) => setDraft({ ...draft, model: e.target.value } as any)}
                              placeholder="claude-sonnet-4.5"
                              className="font-mono"
                            />
                          </Field>
                          <Field label="Base URL">
                            <input
                              type="text"
                              value={(draft as ModelDraft).base_url}
                              onChange={(e) => setDraft({ ...draft, base_url: e.target.value } as any)}
                              placeholder="https://api.example.com"
                              className="font-mono"
                            />
                          </Field>
                          <Field label="Auth Token (可选)">
                            <div className="flex items-center gap-2">
                              <input
                                type={showToken ? 'text' : 'password'}
                                value={(draft as ModelDraft).token}
                                onChange={(e) => setDraft({ ...draft, token: e.target.value } as any)}
                                placeholder="sk-…"
                                className="font-mono flex-1"
                              />
                              <button
                                type="button"
                                onClick={() => setShowToken(!showToken)}
                                className="btn btn-ghost btn-sm"
                              >
                                {showToken ? '隐藏' : '显示'}
                              </button>
                            </div>
                          </Field>
                          <ProbeResultPanel
                            state={probeState}
                            currentModel={(draft as ModelDraft).model}
                            onPickModel={(id) => setDraft({ ...(draft as ModelDraft), model: id } as any)}
                            onRetry={() => {
                              const d = draft as ModelDraft;
                              probeRun(d.base_url, d.token);
                            }}
                          />
                        </>
                      )}
                    </div>
                    <div className="flex justify-end gap-2 mt-4">
                      <button
                        type="button"
                        onClick={() => { setDraft(null); setError(null); probeReset(); }}
                        className="btn btn-ghost btn-sm"
                      >
                        取消
                      </button>
                      <button
                        type="button"
                        onClick={handleSave}
                        className="btn btn-primary btn-sm"
                      >
                        保存
                      </button>
                    </div>
                  </div>
                </motion.div>
              )}
            </AnimatePresence>

            {/* List */}
            <div className="mt-2">
              {loading ? (
                <div className="text-center text-[12px] text-text-tertiary py-8">加载中…</div>
              ) : items.length === 0 && !draft ? (
                <EmptyState kind={kind} onCreate={startCreate} />
              ) : (
                <div>
                  {kind === 'proxy' && proxies.map((p, i) => (
                    <motion.div
                      key={p.id}
                      initial={{ opacity: 0, y: 4 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{ duration: 0.16, delay: i * 0.025 }}
                      className="list-row"
                    >
                      <div className="flex-1 min-w-0">
                        <div className="text-[12.5px] text-text-primary truncate">{p.name}</div>
                        <div className="font-mono text-[10.5px] text-text-tertiary truncate mt-0.5">{p.url}</div>
                      </div>
                      <div className="flex items-center gap-1">
                        <button type="button" onClick={() => startEditProxy(p)} className="btn btn-ghost btn-sm">编辑</button>
                        <button type="button" onClick={() => requestDelete(p.id, p.name)} className="btn btn-ghost btn-sm text-error/80 hover:!text-error">删除</button>
                      </div>
                    </motion.div>
                  ))}
                  {kind === 'model' && models.map((m, i) => (
                    <motion.div
                      key={m.id}
                      initial={{ opacity: 0, y: 4 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{ duration: 0.16, delay: i * 0.025 }}
                      className="list-row"
                    >
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 min-w-0">
                          <span className="font-mono text-[12px] text-text-primary truncate">{m.name}</span>
                          <RowProbeBadge state={rowProbes[m.id]} />
                        </div>
                        <div className="font-mono text-[10.5px] text-text-tertiary truncate mt-0.5">
                          {m.base_url || <span className="italic text-text-disabled">(无 Base URL)</span>}
                        </div>
                      </div>
                      <div className="flex items-center gap-1">
                        <button
                          type="button"
                          onClick={() => probeRow(m)}
                          disabled={rowProbes[m.id] === 'loading'}
                          className="btn btn-ghost btn-sm"
                          title="检测端点可达性"
                        >
                          {rowProbes[m.id] === 'loading' ? '检测中…' : '检测'}
                        </button>
                        <button type="button" onClick={() => startEditModel(m)} className="btn btn-ghost btn-sm">编辑</button>
                        <button type="button" onClick={() => requestDelete(m.id, m.name)} className="btn btn-ghost btn-sm text-error/80 hover:!text-error">删除</button>
                      </div>
                    </motion.div>
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* Footer */}
          <div className="px-5 py-3 border-t border-line flex items-center justify-between">
            <span className="font-mono text-[10px] text-text-tertiary uppercase tracking-[0.18em]">
              {kind === 'proxy' ? `${proxies.length} 个代理` : `${models.length} 个模型`}
            </span>
            <button
              type="button"
              onClick={() => { setDraft(null); startCreate(); }}
              className="btn btn-primary btn-sm"
            >
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
              新建{kind === 'proxy' ? '代理' : '模型'}
            </button>
          </div>
        </motion.div>
      </motion.div>

      {/* Delete confirmation dialog (rendered alongside; sits above the manager modal) */}
      <ConfirmDialog
        isOpen={!!pendingDelete}
        title={kind === 'proxy' ? '删除代理配置' : '删除模型配置'}
        message={
          pendingDelete
            ? (pendingDelete.refs > 0
                ? `「${pendingDelete.name}」正在被 ${pendingDelete.refs} 个项目使用，删除后这些项目将变为未配置${kind === 'model' ? '（自定义模式将无法启动）' : ''}。\n\n确定要删除吗？`
                : `确定要删除「${pendingDelete.name}」吗？`
              )
            : ''
        }
        confirmLabel="删除"
        cancelLabel="取消"
        variant="danger"
        onConfirm={confirmDelete}
        onCancel={() => setPendingDelete(null)}
      />
    </AnimatePresence>
  );
};

const Field: React.FC<{ label: string; children: React.ReactNode }> = ({ label, children }) => (
  <div>
    <label className="block font-mono text-[10px] uppercase tracking-[0.16em] text-text-tertiary mb-1.5">{label}</label>
    {children}
  </div>
);

const ProbeResultPanel: React.FC<{
  state: ProbeState;
  currentModel: string;
  onPickModel: (id: string) => void;
  onRetry: () => void;
}> = ({ state, currentModel, onPickModel, onRetry }) => {
  if (state.kind === 'idle') return null;
  if (state.kind === 'loading') {
    return (
      <div className="mt-1 px-3 py-2 rounded bg-surface-2 border border-line text-[11px] text-text-secondary">
        <span className="font-mono">检测中…</span>
      </div>
    );
  }
  if (state.kind === 'error') {
    return (
      <div className="mt-1 px-3 py-2 rounded bg-error/5 border border-error/30 flex items-start justify-between gap-2">
        <span className="font-mono text-[11px] text-error flex-1 break-all">✗ {state.error}</span>
        <button type="button" onClick={onRetry} className="btn btn-ghost btn-sm shrink-0 !h-6 !px-2 !text-[10px]">重新检测</button>
      </div>
    );
  }
  const { latency_ms, models } = state.result;
  return (
    <div className="mt-1 px-3 py-2 rounded bg-ok/5 border border-ok/30">
      <div className="flex items-center justify-between gap-2">
        <span className="font-mono text-[11px] text-ok">
          ✓ {latency_ms}ms · {models.length} 个模型可用
        </span>
        <button type="button" onClick={onRetry} className="btn btn-ghost btn-sm shrink-0 !h-6 !px-2 !text-[10px]">重新检测</button>
      </div>
      {models.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {models.map((id) => {
            const active = id === currentModel.trim();
            return (
              <button
                key={id}
                type="button"
                onClick={() => onPickModel(id)}
                data-active={active}
                className="font-mono text-[10.5px] px-2 py-0.5 rounded border border-line bg-surface-1 text-text-secondary hover:border-accent hover:text-text-primary transition-colors data-[active=true]:bg-accent/15 data-[active=true]:border-accent data-[active=true]:text-accent"
                title="点击填入 Model 字段"
              >
                {id}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
};

const RowProbeBadge: React.FC<{ state: RowProbeState | undefined }> = ({ state }) => {
  if (!state) return null;
  if (state === 'loading') {
    return <span className="font-mono text-[10px] text-text-tertiary">检测中…</span>;
  }
  if (state.ok) {
    const color = state.latency_ms < 300 ? 'text-ok' : state.latency_ms < 1000 ? 'text-warn' : 'text-error';
    return (
      <span className={`font-mono text-[10px] ${color}`} title={`${state.models.length} 个模型可用`}>
        {state.latency_ms}ms
      </span>
    );
  }
  return (
    <span className="font-mono text-[10px] text-error" title={state.error}>
      不可达
    </span>
  );
};

const EmptyState: React.FC<{ kind: Kind; onCreate: () => void }> = ({ kind, onCreate }) => (
  <div className="flex flex-col items-center justify-center py-12 px-6 text-center">
    <div className="w-10 h-10 rounded-full border border-dashed border-line-strong flex items-center justify-center text-text-tertiary mb-3">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
    </div>
    <p className="text-[12.5px] text-text-secondary mb-1">
      还没有{kind === 'proxy' ? '代理' : '模型'}配置
    </p>
    <p className="font-mono text-[10.5px] text-text-tertiary mb-4">
      {kind === 'proxy' ? '配置一个代理供多个项目共享使用' : '配置一组 model + Base URL，改一处所有项目生效'}
    </p>
    <button type="button" onClick={onCreate} className="btn btn-primary btn-sm">
      新建{kind === 'proxy' ? '代理' : '模型'}
    </button>
  </div>
);
