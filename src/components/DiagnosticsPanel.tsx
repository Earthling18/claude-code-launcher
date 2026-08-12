import { useEffect, useState } from 'react';
import { diagnosticsApi } from '../api';
import { toast } from '../lib/toast';
import type { DiagnosticsStatus } from '../types';

export const DiagnosticsPanel: React.FC = () => {
  const [status, setStatus] = useState<DiagnosticsStatus | null>(null);
  const [expanded, setExpanded] = useState(false);
  const [sending, setSending] = useState(false);

  const reload = () => diagnosticsApi.getStatus().then(setStatus).catch((error) => {
    console.error('Failed to load diagnostics status:', error);
  });

  useEffect(() => { reload(); }, []);

  if (!status) return null;

  const toggleAutoReport = async () => {
    const enabled = !status.auto_report_enabled;
    setStatus({ ...status, auto_report_enabled: enabled });
    try {
      await diagnosticsApi.setAutoReport(enabled);
    } catch (error) {
      setStatus({ ...status, auto_report_enabled: !enabled });
      toast.error(`保存诊断设置失败：${error}`);
    }
  };

  const sendManual = async () => {
    setSending(true);
    try {
      const reportId = await diagnosticsApi.submit();
      toast.success(`诊断已发送：${reportId}`);
      reload();
    } catch (error) {
      toast.error(`诊断发送失败，已保留在本地：${error}`);
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="border-b border-[#3a3a3a] bg-[#24282d]">
      <button type="button" onClick={() => setExpanded((value) => !value)} className="w-full px-4 py-2.5 flex items-center justify-between text-left hover:bg-[#2e3338] transition-colors">
        <div>
          <div className="text-[12px] text-[#DCE4EE]">运行诊断</div>
          <div className="text-[10.5px] text-[#8b949e] mt-0.5">{status.compatibility_label} · {status.pending_reports > 0 ? `${status.pending_reports} 条待发送` : '无待发送报告'}</div>
        </div>
        <span className="text-[11px] text-[#8b949e]">{expanded ? '收起' : '设置'}</span>
      </button>

      {expanded && (
        <div className="px-4 pb-3 space-y-3">
          <label className="flex items-start gap-2 cursor-pointer">
            <input type="checkbox" checked={status.auto_report_enabled} onChange={toggleAutoReport} className="mt-0.5 accent-[#3b82f6]" />
            <span><span className="block text-[11.5px] text-[#DCE4EE]">仅在白屏或原生崩溃时自动发送</span><span className="block text-[10px] text-[#8b949e] mt-0.5">普通前端、模型、代理、更新和网络错误不会自动上报；报告排除路径、模型、URL 和密钥。</span></span>
          </label>

          {!status.endpoint_configured && <div className="text-[10px] text-[#d9a441] bg-[#3b321f] border border-[#5c4b28] rounded px-2 py-1.5">当前构建未配置诊断服务，故障报告只保存在本地。</div>}

          {status.last_report_id && <div className="text-[10px] font-mono text-[#8b949e] truncate" title={status.last_report_id}>最近报告：{status.last_report_kind} · {status.last_report_id}</div>}

          <div className="flex flex-wrap gap-2">
            <button type="button" onClick={() => diagnosticsApi.openFolder().catch((error) => toast.error(String(error)))} className="px-2.5 py-1 text-[10.5px] bg-[#343a40] hover:bg-[#424950] text-[#DCE4EE] rounded">打开诊断目录</button>
            <button type="button" onClick={sendManual} disabled={sending || !status.endpoint_configured} className="px-2.5 py-1 text-[10.5px] bg-[#343a40] hover:bg-[#424950] disabled:opacity-40 text-[#DCE4EE] rounded">{sending ? '发送中…' : '手动发送诊断'}</button>
            {status.compatibility_stage !== 'standard' && <button type="button" onClick={() => { if (window.confirm('恢复标准 WebView 模式并立即重启？')) diagnosticsApi.resetCompatibilityAndRestart(); }} className="px-2.5 py-1 text-[10.5px] bg-[#4a302c] hover:bg-[#5a3832] text-[#f2b8ad] rounded">恢复标准模式</button>}
          </div>
        </div>
      )}
    </div>
  );
};
