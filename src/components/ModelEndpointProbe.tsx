import { useEffect, useRef, useState } from 'react';
import { presetsApi } from '../api';
import type { ModelApiFormat, ModelProbeResult } from '../types/presets';

type RequestState =
  | { kind: 'idle' }
  | { kind: 'loading' }
  | { kind: 'success'; result: ModelProbeResult }
  | { kind: 'error'; error: string };

interface ModelEndpointProbeProps {
  baseUrl: string;
  token: string;
  model: string;
  apiFormat: ModelApiFormat;
  onPick: (model: string) => void;
}

export const ModelEndpointProbe: React.FC<ModelEndpointProbeProps> = ({ baseUrl, token, model, apiFormat, onPick }) => {
  const [discovery, setDiscovery] = useState<RequestState>({ kind: 'idle' });
  const [probe, setProbe] = useState<RequestState>({ kind: 'idle' });
  const [search, setSearch] = useState('');
  const discoveryRequest = useRef(0);
  const probeRequest = useRef(0);

  useEffect(() => {
    setDiscovery({ kind: 'idle' });
    setProbe({ kind: 'idle' });
    setSearch('');
    return () => {
      // A response for a previous key or endpoint must never replace this list.
      discoveryRequest.current += 1;
      probeRequest.current += 1;
    };
  }, [baseUrl, token, apiFormat]);

  useEffect(() => {
    setProbe({ kind: 'idle' });
    return () => { probeRequest.current += 1; };
  }, [model]);

  const run = async (discoverOnly: boolean) => {
    const setState = discoverOnly ? setDiscovery : setProbe;
    const requestRef = discoverOnly ? discoveryRequest : probeRequest;
    const requestId = ++requestRef.current;
    if (!/^https?:\/\//i.test(baseUrl.trim())) {
      setState({ kind: 'error', error: '请先填写有效的 HTTP(S) Base URL' });
      return;
    }
    if (!discoverOnly && !model.trim()) {
      setState({ kind: 'error', error: '请先选择或填写模型名称' });
      return;
    }
    setState({ kind: 'loading' });
    try {
      const result = await presetsApi.probeModel(baseUrl.trim(), token, discoverOnly ? '' : model.trim(), apiFormat);
      if (requestId !== requestRef.current) return;
      setState(result.ok
        ? { kind: 'success', result }
        : { kind: 'error', error: result.error || `HTTP ${result.status}` });
    } catch (reason) {
      if (requestId === requestRef.current) setState({ kind: 'error', error: String(reason) });
    }
  };

  const models = discovery.kind === 'success' ? discovery.result.models : [];
  const query = search.trim().toLowerCase();
  const filteredModels = models.filter((id) => id.toLowerCase().includes(query));
  const busy = discovery.kind === 'loading' || probe.kind === 'loading';
  const protocol = apiFormat === 'openai_responses' ? 'Responses' : 'Messages';

  return (
    <div className="space-y-2.5">
      <div className="flex flex-wrap items-center gap-2">
        <button type="button" onClick={() => run(true)} disabled={busy} className="btn btn-secondary btn-sm">
          {discovery.kind === 'loading' ? '获取中…' : '获取模型列表'}
        </button>
        <button type="button" onClick={() => run(false)} disabled={busy || !model.trim()} className="btn btn-secondary btn-sm">
          {probe.kind === 'loading' ? '测试中…' : '测试模型'}
        </button>
      </div>
      <p className="text-[10.5px] text-text-tertiary">获取列表不消耗推理 Token；测试模型会发送一条简短请求，消耗少量 Token。</p>
      <div aria-live="polite" className="space-y-2">
        {probe.kind === 'error' && <p className="text-[11px] text-error break-all">{probe.error}</p>}
        {probe.kind === 'success' && <p className="text-[11px] text-ok break-all">{model.trim()} · {protocol} 请求成功 · {probe.result.latency_ms}ms</p>}
        {discovery.kind === 'error' && <p className="text-[11px] text-error break-all">{discovery.error}</p>}
        {discovery.kind === 'success' && (
          <>
            <p className="text-[11px] text-text-secondary">当前 Key · {discovery.result.warning ? '已获取' : '获取到'} {models.length} 个模型 · {discovery.result.latency_ms}ms</p>
            {discovery.result.warning && <p className="text-[11px] text-amber-400 break-all">{discovery.result.warning}</p>}
            {models.length === 0 && <p className="text-[10.5px] text-text-tertiary">服务返回了空列表，可以手动填写模型名称后测试。</p>}
          </>
        )}
      </div>
      {models.length > 0 && (
        <div className="rounded border border-line bg-surface-input p-2.5 space-y-2">
          <div className="flex items-center gap-2">
            <input type="search" aria-label="搜索模型" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="搜索模型名称，例如 glm、deepseek" className="input min-w-0 flex-1" />
            <span className="shrink-0 text-[10px] font-mono text-text-tertiary">{filteredModels.length} / {models.length}</span>
          </div>
          <div className="max-h-48 overflow-y-auto grid grid-cols-1 sm:grid-cols-2 gap-1.5" aria-label="模型列表">
            {filteredModels.map((id) => (
              <button key={id} type="button" aria-pressed={id === model.trim()} onClick={() => onPick(id)} className={`min-w-0 rounded border px-2 py-1.5 text-left text-[11px] font-mono break-all transition-colors ${id === model.trim() ? 'border-accent bg-surface-3 text-text-primary' : 'border-line text-text-secondary hover:border-accent hover:text-text-primary'}`}>
                {id}
              </button>
            ))}
          </div>
          {filteredModels.length === 0 && <p className="text-[11px] text-text-tertiary">没有匹配的模型，可以直接在上方填写模型名称后测试。</p>}
          <p className="text-[10px] text-text-tertiary">列表由当前服务和 Key 返回，尚未逐个验证 {protocol} 兼容性。点击模型可填入名称，再测试是否可用。</p>
        </div>
      )}
    </div>
  );
};
