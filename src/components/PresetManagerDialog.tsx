import { useEffect, useRef, useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { presetsApi } from '../api';
import { toast } from '../lib/toast';
import type { ModelApiFormat, ModelPreset, ModelProbeResult, ProxyPreset } from '../types/presets';
import { ConfirmDialog } from './ConfirmDialog';

type Kind = 'proxy' | 'model';
type ProbeState =
  | { kind: 'idle' }
  | { kind: 'loading' }
  | { kind: 'success'; result: ModelProbeResult; compatibilityTested: boolean }
  | { kind: 'error'; error: string };

interface PresetManagerDialogProps {
  isOpen: boolean;
  kind: Kind;
  onClose: () => void;
  onChanged?: (newId?: string, supportedFormats?: ModelApiFormat[]) => void;
  showTabs?: boolean;
  modelApiFormat?: ModelApiFormat;
}

interface ProxyDraft { id?: string; name: string; url: string }
interface ModelDraft { id?: string; model: string; claude_base_url: string; codex_base_url: string; token: string }

const formatLabel: Record<ModelApiFormat, string> = {
  anthropic_messages: 'Claude API',
  openai_responses: 'Codex Responses',
};

const deriveName = (model: string, baseUrl: string) => {
  if (model.trim()) return model.trim();
  return baseUrl.replace(/^https?:\/\//, '').replace(/\/+$/, '').split('/')[0] || '未命名模型';
};

const endpointFor = (value: Pick<ModelDraft, 'claude_base_url' | 'codex_base_url'>, format: ModelApiFormat) =>
  format === 'anthropic_messages' ? value.claude_base_url : value.codex_base_url;

const configuredFormats = (value: Pick<ModelDraft, 'claude_base_url' | 'codex_base_url'>): ModelApiFormat[] => [
  ...(value.claude_base_url.trim() ? ['anthropic_messages' as const] : []),
  ...(value.codex_base_url.trim() ? ['openai_responses' as const] : []),
];

const formatBadge = (value: Pick<ModelDraft, 'claude_base_url' | 'codex_base_url'>) => {
  const formats = configuredFormats(value);
  if (formats.length === 2) return 'Claude + Codex';
  return formats[0] === 'openai_responses' ? 'Codex' : 'Claude';
};

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
  const [draft, setDraft] = useState<ProxyDraft | ModelDraft | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showToken, setShowToken] = useState(false);
  const [probe, setProbe] = useState<ProbeState>({ kind: 'idle' });
  const [activeEndpoint, setActiveEndpoint] = useState<ModelApiFormat>('anthropic_messages');
  const [pendingDelete, setPendingDelete] = useState<{ id: string; refs: number; name: string } | null>(null);
  const contentRef = useRef<HTMLDivElement>(null);

  const revealDraft = () => {
    requestAnimationFrame(() => contentRef.current?.scrollTo({ top: 0, behavior: 'smooth' }));
  };

  const loadAll = async () => {
    try {
      setLoading(true);
      const data = await presetsApi.getAll();
      setProxies(data.proxies);
      setModels(data.models);
    } catch (reason) {
      setError(String(reason));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (!isOpen) return;
    setKind(initialKind);
    setDraft(null);
    setError(null);
    setProbe({ kind: 'idle' });
    loadAll();
  }, [isOpen, initialKind]);

  useEffect(() => {
    setDraft(null);
    setError(null);
    setProbe({ kind: 'idle' });
  }, [kind]);

  if (!isOpen) return null;

  const visibleModels = models;

  const startCreate = () => {
    setError(null);
    setProbe({ kind: 'idle' });
    setShowToken(false);
    if (kind === 'proxy') setDraft({ name: '', url: '' });
    else {
      setActiveEndpoint('anthropic_messages');
      setDraft({ model: '', claude_base_url: '', codex_base_url: '', token: '' });
    }
    revealDraft();
  };

  const startEditProxy = (proxy: ProxyPreset) => {
    setDraft({ id: proxy.id, name: proxy.name, url: proxy.url });
    setError(null);
    revealDraft();
  };

  const startEditModel = (model: ModelPreset) => {
    setDraft({
      id: model.id,
      model: model.model,
      claude_base_url: model.claude_base_url || (model.api_format !== 'openai_responses' ? model.base_url ?? '' : ''),
      codex_base_url: model.codex_base_url || (model.api_format === 'openai_responses' ? model.base_url ?? '' : ''),
      token: model.token,
    });
    setActiveEndpoint(model.claude_base_url || model.api_format !== 'openai_responses' ? 'anthropic_messages' : 'openai_responses');
    setProbe({ kind: 'idle' });
    setError(null);
    setShowToken(false);
    revealDraft();
  };

  const runProbe = async (modelDraft: ModelDraft) => {
    const baseUrl = endpointFor(modelDraft, activeEndpoint).trim();
    if (!/^https?:\/\//.test(baseUrl)) {
      setProbe({ kind: 'error', error: '请先填写有效的 HTTP(S) Base URL' });
      return;
    }
    const model = modelDraft.model.trim();
    setProbe({ kind: 'loading' });
    try {
      const result = await presetsApi.probeModel(baseUrl, modelDraft.token, model, activeEndpoint);
      setProbe(result.ok
        ? { kind: 'success', result, compatibilityTested: !!model }
        : { kind: 'error', error: result.error || `HTTP ${result.status}` });
    } catch (reason) {
      setProbe({ kind: 'error', error: String(reason) });
    }
  };

  const save = async () => {
    if (!draft) return;
    try {
      setError(null);
      let newId: string;
      if (kind === 'proxy') {
        const value = draft as ProxyDraft;
        if (!value.name.trim() || !/^https?:\/\//.test(value.url.trim())) {
          setError('请填写名称和有效的 HTTP(S) 代理地址');
          return;
        }
        const saved = value.id
          ? await presetsApi.updateProxy(value.id, value.name.trim(), value.url.trim())
          : await presetsApi.createProxy(value.name.trim(), value.url.trim());
        newId = saved.id;
      } else {
        const value = draft as ModelDraft;
        const urls = [value.claude_base_url.trim(), value.codex_base_url.trim()].filter(Boolean);
        if (urls.length === 0) {
          setError('Claude 和 Codex 地址至少填写一个');
          return;
        }
        if (urls.some((url) => !/^https?:\/\//.test(url))) {
          setError('请填写有效的 HTTP(S) Base URL');
          return;
        }
        if (value.codex_base_url.trim() && !value.model.trim()) {
          setError('配置 Codex 地址时必须填写模型名称');
          return;
        }
        const claudeBaseUrl = value.claude_base_url.trim().replace(/\/+$/, '');
        const codexBaseUrl = value.codex_base_url.trim().replace(/\/+$/, '');
        const name = deriveName(value.model, claudeBaseUrl || codexBaseUrl);
        const saved = value.id
          ? await presetsApi.updateModel(value.id, name, value.model.trim(), claudeBaseUrl, codexBaseUrl, value.token)
          : await presetsApi.createModel(name, value.model.trim(), claudeBaseUrl, codexBaseUrl, value.token);
        newId = saved.id;
      }
      setDraft(null);
      await loadAll();
      onChanged?.(newId, kind === 'model' ? configuredFormats(draft as ModelDraft) : undefined);
      toast.success(kind === 'proxy' ? '代理配置已保存' : '模型配置已保存');
    } catch (reason) {
      setError(String(reason));
    }
  };

  const requestDelete = async (id: string, name: string) => {
    try {
      const refs = kind === 'proxy' ? await presetsApi.countProxyRefs(id) : await presetsApi.countModelRefs(id);
      setPendingDelete({ id, refs, name });
    } catch (reason) {
      toast.error(`查询引用失败：${reason}`);
    }
  };

  const deleteSelected = async () => {
    if (!pendingDelete) return;
    try {
      if (kind === 'proxy') await presetsApi.deleteProxy(pendingDelete.id);
      else await presetsApi.deleteModel(pendingDelete.id);
      setPendingDelete(null);
      await loadAll();
      onChanged?.();
    } catch (reason) {
      setPendingDelete(null);
      toast.error(`删除失败：${reason}`);
    }
  };

  const items = kind === 'proxy' ? proxies : visibleModels;
  const modelDraft = kind === 'model' && draft ? draft as ModelDraft : null;

  return (
    <AnimatePresence>
      <motion.div className="modal-overlay" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={onClose}>
        <motion.div
          className="modal-panel w-[620px] max-w-[92vw] max-h-[84vh]"
          initial={{ opacity: 0, scale: 0.97, y: 8 }}
          animate={{ opacity: 1, scale: 1, y: 0 }}
          exit={{ opacity: 0, scale: 0.98, y: 4 }}
          onClick={(event) => event.stopPropagation()}
        >
          <div className="flex items-center justify-between px-5 pt-4 pb-3 border-b border-line">
            {showTabs ? (
              <div className="inline-flex p-0.5 bg-surface-1 border border-line rounded">
                {(['proxy', 'model'] as Kind[]).map((value) => (
                  <button key={value} type="button" onClick={() => setKind(value)} className={`h-7 px-3 text-[12px] rounded ${kind === value ? 'bg-surface-3 text-text-primary' : 'text-text-secondary'}`}>
                    {value === 'proxy' ? '代理配置' : '模型配置'}
                  </button>
                ))}
              </div>
            ) : <h2 className="text-[14px] font-medium text-text-primary">管理{kind === 'proxy' ? '代理' : '模型'}配置</h2>}
            <button type="button" onClick={onClose} className="btn btn-ghost btn-sm">关闭</button>
          </div>

          <div ref={contentRef} className="px-5 py-4 overflow-y-auto flex-1">
            {draft && (
              <div className="rounded border border-line bg-surface-1 p-4 mb-4 space-y-3">
                {kind === 'proxy' ? (
                  <>
                    <Field label="名称"><input value={(draft as ProxyDraft).name} onChange={(event) => setDraft({ ...(draft as ProxyDraft), name: event.target.value })} placeholder="例如：公司代理" /></Field>
                    <Field label="代理地址"><input value={(draft as ProxyDraft).url} onChange={(event) => setDraft({ ...(draft as ProxyDraft), url: event.target.value })} placeholder="http://127.0.0.1:7890" /></Field>
                  </>
                ) : modelDraft && (
                  <>
                    <Field label="模型名称">
                      <input
                        type="text"
                        value={modelDraft.model}
                        onChange={(event) => {
                          setDraft({ ...modelDraft, model: event.target.value });
                          setProbe({ kind: 'idle' });
                        }}
                        placeholder="例如：glm-5.2（可留空后检测可用模型）"
                      />
                    </Field>
                    <div>
                      <div className="mb-1.5 flex items-center justify-between gap-3">
                        <label className="font-mono text-[10px] uppercase tracking-[0.14em] text-text-tertiary">API Base URL</label>
                        <div className="inline-grid h-7 grid-cols-2 gap-0.5 rounded bg-surface-input p-0.5">
                          {(Object.keys(formatLabel) as ModelApiFormat[]).map((format) => {
                            const configured = !!endpointFor(modelDraft, format).trim();
                            return (
                              <button
                                key={format}
                                type="button"
                                onClick={() => { setActiveEndpoint(format); setProbe({ kind: 'idle' }); setError(null); }}
                                className={`flex items-center gap-1.5 rounded border px-2.5 text-[10.5px] transition-colors ${activeEndpoint === format ? 'border-[#454d59] bg-[#343a44] text-text-primary' : 'border-transparent text-text-tertiary hover:bg-surface-2 hover:text-text-secondary'}`}
                              >
                                <span className={`h-1.5 w-1.5 rounded-full ${configured ? 'bg-ok' : 'border border-text-tertiary/60'}`} />
                                {format === 'anthropic_messages' ? 'Claude' : 'Codex'}
                              </button>
                            );
                          })}
                        </div>
                      </div>
                      <input
                        type="text"
                        value={endpointFor(modelDraft, activeEndpoint)}
                        onChange={(event) => {
                          const key = activeEndpoint === 'anthropic_messages' ? 'claude_base_url' : 'codex_base_url';
                          setDraft({ ...modelDraft, [key]: event.target.value });
                          setProbe({ kind: 'idle' });
                          setError(null);
                        }}
                        placeholder={activeEndpoint === 'openai_responses' ? 'https://api.example.com/v1' : 'https://api.example.com'}
                      />
                      {activeEndpoint === 'openai_responses'
                        ? <p className="text-[10.5px] text-text-tertiary mt-1">必须支持 Responses API；只有 Chat Completions 的 OpenAI 兼容地址也不能使用。</p>
                        : <p className="text-[10.5px] text-text-tertiary mt-1">必须支持 Anthropic Messages API；是否兼容以实际检测结果为准。</p>}
                    </div>
                    <Field label="API Key（共用，可选）">
                      <div className="flex gap-2"><input type={showToken ? 'text' : 'password'} value={modelDraft.token} onChange={(event) => { setDraft({ ...modelDraft, token: event.target.value }); setProbe({ kind: 'idle' }); }} /><button type="button" onClick={() => setShowToken((value) => !value)} className="btn btn-ghost btn-sm">{showToken ? '隐藏' : '显示'}</button></div>
                    </Field>
                    <div className="flex items-center gap-2">
                      <button type="button" onClick={() => runProbe(modelDraft)} disabled={probe.kind === 'loading'} className="btn btn-sm border border-line-strong bg-surface-2 text-text-secondary shadow-[0_1px_2px_rgba(0,0,0,0.2)] hover:border-[#454d59] hover:bg-surface-3 hover:text-text-primary">{probe.kind === 'loading' ? '检测中…' : '检测连接'}</button>
                      <ProbeResult
                        state={probe}
                        apiFormat={activeEndpoint}
                        hasModel={!!modelDraft.model.trim()}
                        onPick={(model) => {
                          setDraft({ ...modelDraft, model });
                          setProbe({ kind: 'idle' });
                        }}
                      />
                    </div>
                  </>
                )}
                {error && <p className="text-[11px] text-error">{error}</p>}
                <div className="flex justify-end gap-2 pt-1"><button type="button" onClick={() => setDraft(null)} className="btn btn-ghost btn-sm">取消</button><button type="button" onClick={save} className="btn btn-primary btn-sm">保存</button></div>
              </div>
            )}

            {loading ? <div className="text-center py-8 text-text-tertiary">加载中…</div> : items.length === 0 && !draft ? (
              <div className="text-center py-10"><p className="text-[12px] text-text-secondary mb-3">还没有{kind === 'proxy' ? '代理' : '模型'}配置</p><button type="button" onClick={startCreate} className="btn btn-primary btn-sm">新建配置</button></div>
            ) : (
              <div className="space-y-1">
                {kind === 'proxy' ? proxies.map((proxy) => (
                  <PresetRow key={proxy.id} title={proxy.name} subtitle={proxy.url} onEdit={() => startEditProxy(proxy)} onDelete={() => requestDelete(proxy.id, proxy.name)} />
                )) : visibleModels.map((model) => (
                  <PresetRow
                    key={model.id}
                    title={model.name}
                    subtitle={[model.claude_base_url, model.codex_base_url].filter(Boolean).join(' · ') || model.base_url || ''}
                    badge={formatBadge({
                      claude_base_url: model.claude_base_url || (model.api_format !== 'openai_responses' ? model.base_url ?? '' : ''),
                      codex_base_url: model.codex_base_url || (model.api_format === 'openai_responses' ? model.base_url ?? '' : ''),
                    })}
                    onEdit={() => startEditModel(model)}
                    onDelete={() => requestDelete(model.id, model.name)}
                  />
                ))}
              </div>
            )}
          </div>

          <div className="px-5 py-3 border-t border-line flex justify-between items-center">
            <span className="font-mono text-[10px] text-text-tertiary">{items.length} 个配置</span>
            <button type="button" onClick={startCreate} className="btn btn-primary btn-sm">新建{kind === 'proxy' ? '代理' : '模型'}</button>
          </div>
        </motion.div>

        <ConfirmDialog
          isOpen={!!pendingDelete}
          title={`删除${kind === 'proxy' ? '代理' : '模型'}配置`}
          message={pendingDelete ? (pendingDelete.refs > 0 ? `“${pendingDelete.name}”正在被 ${pendingDelete.refs} 个项目使用，删除后这些项目需要重新配置。` : `确定删除“${pendingDelete.name}”吗？`) : ''}
          confirmLabel="删除"
          cancelLabel="取消"
          variant="danger"
          onConfirm={deleteSelected}
          onCancel={() => setPendingDelete(null)}
        />
      </motion.div>
    </AnimatePresence>
  );
};

const Field: React.FC<{ label: string; children: React.ReactNode }> = ({ label, children }) => <div><label className="block font-mono text-[10px] uppercase tracking-[0.14em] text-text-tertiary mb-1.5">{label}</label>{children}</div>;

const PresetRow: React.FC<{ title: string; subtitle: string; badge?: string; onEdit: () => void; onDelete: () => void }> = ({ title, subtitle, badge, onEdit, onDelete }) => (
  <div className="list-row"><div className="flex-1 min-w-0"><div className="flex items-center gap-2"><span className="font-mono text-[12px] text-text-primary truncate">{title}</span>{badge && <span className="text-[9.5px] border border-line-strong text-text-tertiary px-1.5 py-0.5 rounded-sm shrink-0">{badge}</span>}</div><div className="font-mono text-[10.5px] text-text-tertiary truncate mt-0.5">{subtitle}</div></div><button type="button" onClick={onEdit} className="btn btn-ghost btn-sm">编辑</button><button type="button" onClick={onDelete} className="btn btn-ghost btn-sm text-error/80">删除</button></div>
);

const ProbeResult: React.FC<{ state: ProbeState; apiFormat: ModelApiFormat; hasModel: boolean; onPick: (model: string) => void }> = ({ state, apiFormat, hasModel, onPick }) => {
  if (state.kind === 'idle') return <span className="text-[10.5px] text-text-tertiary">{hasModel ? `发送最小${apiFormat === 'openai_responses' ? ' Responses' : ' Messages'} 实测请求，会消耗极少量 Token` : '检测连接并获取模型列表，不发送推理请求'}</span>;
  if (state.kind === 'loading') return null;
  if (state.kind === 'error') return <span className="text-[10.5px] text-error break-all">{state.error}</span>;
  const status = state.compatibilityTested
    ? `${apiFormat === 'openai_responses' ? 'Responses' : 'Messages'} 可用`
    : state.result.models.length > 0
      ? `连接可用 · 获取到 ${state.result.models.length} 个模型`
      : '连接可用 · 未返回模型列表';
  return <div className="flex items-center gap-1.5 flex-wrap"><span className="text-[10.5px] text-ok">{status} · {state.result.latency_ms}ms</span>{state.result.models.slice(0, 8).map((model) => <button key={model} type="button" onClick={() => onPick(model)} className="text-[10px] font-mono border border-line px-1.5 py-0.5 rounded hover:border-accent">{model}</button>)}</div>;
};
