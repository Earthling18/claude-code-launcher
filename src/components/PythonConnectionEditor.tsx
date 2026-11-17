import { useRef, useState } from 'react';
import { connectionApi } from '../api';
import type { PythonConnection } from '../types/presets';

export function PythonConnectionEditor({ value, onChange }: {
  value?: PythonConnection | null;
  onChange: (value: PythonConnection | null) => void;
}) {
  const [open, setOpen] = useState(!!value);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [profiles, setProfiles] = useState<string[]>([]);
  const [profileLabels, setProfileLabels] = useState<Record<string, string>>({});
  const revision = useRef(0);
  const connection = value ?? { python: '', script: '', profile: 'default' };
  const change = (next: PythonConnection | null) => {
    revision.current += 1;
    setMessage('');
    setProfiles([]);
    setProfileLabels({});
    onChange(next);
  };
  const action = async (kind: 'detect' | 'menu' | 'doctor' | 'script' | 'python') => {
    const version = revision.current;
    setBusy(true);
    setMessage('');
    try {
      if (kind === 'script' || kind === 'python') {
        const file = await connectionApi.selectFile(kind === 'script');
        if (file && version === revision.current) change({ ...connection, [kind]: file });
      } else if (kind === 'detect') {
        const result = await connectionApi.info(connection);
        if (version === revision.current) {
          setProfiles(result.profiles);
          setProfileLabels(result.profile_labels ?? {});
          setMessage(`Python ${result.version} · ${result.python}${connection.script && !result.profiles.length ? '\n尚无连接方案，请先“管理连接与分流”添加云节点或订阅，然后重新检测。' : ''}`);
        }
      } else {
        await connectionApi.action(connection, kind);
        if (version === revision.current) setMessage(kind === 'menu'
          ? '已打开连接管理；新版脚本使用本地网页，旧版使用终端菜单。保存后，点击“检测 / 刷新方案”更新列表。'
          : '已打开诊断终端；请查看各阶段结果。网络响应不等于模型请求成功。');
      }
    } catch (error) {
      if (version === revision.current) setMessage(String(error));
    } finally {
      setBusy(false);
    }
  };
  return <div className="border-t border-line pt-3">
    <button type="button" className="text-[12px] text-text-secondary hover:text-text-primary" aria-expanded={open} onClick={() => setOpen(!open)}>
      {open ? '▾' : '▸'} 高级：使用 Python 连接工具{value ? ' · 已启用' : ''}
    </button>
    {open && <div className="space-y-3 mt-3">
      <label className="flex items-center gap-2 text-[12px] text-text-secondary">
        <input type="checkbox" className="!w-auto" checked={!!value} disabled={busy} onChange={e => change(e.target.checked ? connection : null)} />
        为此代理配置启用 Python 连接
      </label>
      {value && <>
        <label className="block text-[11px] text-text-secondary">Python 环境
          <div className="flex gap-2 mt-1"><input type="text" className="min-w-0 flex-1" aria-label="Python 环境" value={connection.python} disabled={busy} placeholder="留空自动检测 Python 3.11+" onChange={e => change({ ...connection, python: e.target.value })} /><button type="button" className="btn btn-ghost btn-sm" disabled={busy} onClick={() => action('python')}>浏览</button></div>
        </label>
        <label className="block text-[11px] text-text-secondary">连接工具脚本
          <div className="flex gap-2 mt-1"><input type="text" className="min-w-0 flex-1" aria-label="连接工具脚本" value={connection.script} disabled={busy} placeholder="选择解压目录中的 ai-connection.py" onChange={e => change({ ...connection, script: e.target.value })} /><button type="button" className="btn btn-ghost btn-sm" disabled={busy} onClick={() => action('script')}>浏览</button></div>
        </label>
        <label className="block text-[11px] text-text-secondary">连接方案
          <select aria-label="连接方案" className="mt-1 w-full rounded border border-line bg-surface-input p-2" disabled={busy} value={connection.profile} onChange={e => onChange({ ...connection, profile: e.target.value })}>
            {[...new Set([connection.profile, ...profiles])].map(id => <option key={id} value={id}>{profileLabels[id] || id}{!profiles.includes(id) ? '（待检测）' : ''}</option>)}
          </select>
        </label>
        <div className="flex flex-wrap gap-2">
          <button type="button" className="btn btn-ghost btn-sm" disabled={busy} onClick={() => action('detect')}>{busy ? '处理中…' : '检测 / 刷新方案'}</button>
          <button type="button" className="btn btn-ghost btn-sm" disabled={busy || !connection.script} onClick={() => action('menu')}>管理连接与分流</button>
          <button type="button" className="btn btn-ghost btn-sm" disabled={busy || !connection.script} onClick={() => action('doctor')}>测试连接</button>
        </div>
        <p className="text-[11px] text-text-tertiary">仅对通过此方案启动的 CLI 生效。凭据和分流保存在 Python 方案目录；Windows 会显示 Python 进程。</p>
        {message && <p role="status" className="whitespace-pre-wrap break-all text-[11px] text-text-secondary">{message}</p>}
      </>}
    </div>}
  </div>;
}
