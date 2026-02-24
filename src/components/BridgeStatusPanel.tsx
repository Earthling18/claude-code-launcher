import { useState, useEffect, useRef } from 'react';
import { bridgeApi, claudeLoginApi } from '../api';
import type { BridgeStatus } from '../types/project';

interface BridgeStatusPanelProps {
  projectId: string;
  agentMode?: 'claude' | 'custom';
  modelProxy?: string;
  onStatusChange?: (status: BridgeStatus) => void;
}

export const BridgeStatusPanel: React.FC<BridgeStatusPanelProps> = ({
  projectId,
  agentMode = 'claude',
  modelProxy = '',
  onStatusChange,
}) => {
  const [status, setStatus] = useState<BridgeStatus>({
    running: false,
    agent_ok: false,
    client_connected: false,
    started_at: null,
    agent_port: null,
  });
  const [logs, setLogs] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [preparing, setPreparing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showLogs, setShowLogs] = useState(false);
  const [loginWarning, setLoginWarning] = useState(false);
  const [launchingLogin, setLaunchingLogin] = useState(false);
  const logsContainerRef = useRef<HTMLDivElement>(null);
  const isUserScrolling = useRef(false);
  const pollRef = useRef<number | null>(null);

  // Poll status every 3 seconds
  useEffect(() => {
    const pollStatus = async () => {
      try {
        const s = await bridgeApi.getStatus(projectId);
        setStatus(s);
        onStatusChange?.(s);
      } catch {}
    };

    pollStatus();
    pollRef.current = window.setInterval(pollStatus, 3000);

    return () => {
      if (pollRef.current) {
        clearInterval(pollRef.current);
      }
    };
  }, [projectId]);

  // Poll logs when visible
  useEffect(() => {
    if (!showLogs || !status.running) return;

    const pollLogs = async () => {
      try {
        const l = await bridgeApi.getLogs(projectId, 200);
        setLogs(l);
      } catch {}
    };

    pollLogs();
    const interval = setInterval(pollLogs, 2000);
    return () => clearInterval(interval);
  }, [projectId, showLogs, status.running]);

  // Auto-scroll logs only when user is at the bottom (use scrollTop to avoid affecting outer containers)
  useEffect(() => {
    if (!isUserScrolling.current && logsContainerRef.current) {
      logsContainerRef.current.scrollTop = logsContainerRef.current.scrollHeight;
    }
  }, [logs]);

  const handleStart = async () => {
    setError(null);
    setLoginWarning(false);

    // Login check for claude mode only
    if (agentMode === 'claude') {
      try {
        const loggedIn = await claudeLoginApi.checkLogin();
        if (!loggedIn) {
          setLoginWarning(true);
          return;
        }
      } catch (err: any) {
        // If check fails, proceed anyway
        console.warn('Login check failed:', err);
      }
    }

    setLoading(true);
    try {
      // Step 1: Prepare Python environment (venv + pip install, may take minutes on first run)
      setPreparing(true);
      try {
        await bridgeApi.prepareEnv();
      } finally {
        setPreparing(false);
      }

      // Step 2: Start bridge processes (fast, venv already ready)
      await bridgeApi.start(projectId);
      // Wait a moment for processes to start
      await new Promise((r) => setTimeout(r, 1500));
      const s = await bridgeApi.getStatus(projectId);
      setStatus(s);
      onStatusChange?.(s);
    } catch (err: any) {
      setError(err?.toString() || '启动失败');
    } finally {
      setPreparing(false);
      setLoading(false);
    }
  };

  const handleLaunchLogin = async () => {
    setLaunchingLogin(true);
    try {
      await claudeLoginApi.launchForLogin(modelProxy || undefined);
    } catch (err: any) {
      setError(err?.toString() || '启动 Claude Code 失败');
    } finally {
      setLaunchingLogin(false);
    }
  };

  const handleStop = async () => {
    setLoading(true);
    setError(null);
    try {
      await bridgeApi.stop(projectId);
      const s = await bridgeApi.getStatus(projectId);
      setStatus(s);
      onStatusChange?.(s);
    } catch (err: any) {
      setError(err?.toString() || '停止失败');
    } finally {
      setLoading(false);
    }
  };

  const handleRestart = async () => {
    setLoading(true);
    setError(null);
    try {
      await bridgeApi.restart(projectId);
      await new Promise((r) => setTimeout(r, 1500));
      const s = await bridgeApi.getStatus(projectId);
      setStatus(s);
      onStatusChange?.(s);
    } catch (err: any) {
      setError(err?.toString() || '重启失败');
    } finally {
      setLoading(false);
    }
  };

  const getStatusIndicator = () => {
    if (!status.running) {
      return <span className="inline-block w-2.5 h-2.5 rounded-full bg-gray-500" title="未启动" />;
    }
    if (status.agent_ok && status.client_connected) {
      return <span className="inline-block w-2.5 h-2.5 rounded-full bg-green-500 animate-pulse" title="已连接" />;
    }
    return <span className="inline-block w-2.5 h-2.5 rounded-full bg-yellow-500 animate-pulse" title="连接中" />;
  };

  const getStatusText = () => {
    if (!status.running) return '未启动';
    if (status.agent_ok && status.client_connected) return '已连接';
    return '连接中...';
  };

  const formatDuration = (startedAt: number | null) => {
    if (!startedAt) return '-';
    const now = Math.floor(Date.now() / 1000);
    const seconds = now - startedAt;
    if (seconds < 60) return `${seconds}秒`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)}分${seconds % 60}秒`;
    const hours = Math.floor(seconds / 3600);
    const mins = Math.floor((seconds % 3600) / 60);
    return `${hours}时${mins}分`;
  };

  return (
    <div className="space-y-3">
      {/* Login warning */}
      {loginWarning && (
        <div className="bg-[#3d3520] border border-[#f59e0b] rounded-lg p-3">
          <p className="text-[12px] text-[#fbbf24] mb-2">
            首次使用需在本地登录 Claude Code，请先完成登录后再启动桥接。
          </p>
          <div className="flex items-center gap-2">
            <button
              onClick={handleLaunchLogin}
              disabled={launchingLogin}
              className="px-3 py-1.5 text-[12px] bg-[#f59e0b] hover:bg-[#d97706] disabled:opacity-50 text-black font-medium rounded transition-colors"
            >
              {launchingLogin ? '启动中...' : '打开 Claude Code 登录'}
            </button>
            <button
              onClick={() => setLoginWarning(false)}
              className="px-3 py-1.5 text-[12px] text-[#999999] hover:text-white transition-colors"
            >
              关闭
            </button>
          </div>
        </div>
      )}

      {/* Status overview */}
      <div className="bg-[#2a2a2a] border border-[#3a3a3a] rounded-lg p-3">
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-2">
            {getStatusIndicator()}
            <span className="text-[13px] font-medium">{getStatusText()}</span>
          </div>
          <div className="flex items-center gap-2">
            {!status.running ? (
              <button
                onClick={handleStart}
                disabled={loading}
                className="px-3 py-1.5 text-[12px] bg-[#10b981] hover:bg-[#059669] disabled:opacity-50 text-white rounded transition-colors"
              >
                {preparing ? '准备 Python 环境...' : loading ? '启动中...' : '启动桥接'}
              </button>
            ) : (
              <>
                <button
                  onClick={handleRestart}
                  disabled={loading}
                  className="px-3 py-1.5 text-[12px] bg-[#f59e0b] hover:bg-[#d97706] disabled:opacity-50 text-white rounded transition-colors"
                >
                  重启
                </button>
                <button
                  onClick={handleStop}
                  disabled={loading}
                  className="px-3 py-1.5 text-[12px] bg-red-600 hover:bg-red-700 disabled:opacity-50 text-white rounded transition-colors"
                >
                  停止
                </button>
              </>
            )}
          </div>
        </div>

        {error && (
          <p className="text-[11px] text-red-400 mb-2">{error}</p>
        )}

        {status.running && (
          <div className="grid grid-cols-2 gap-2 text-[11px]">
            <div>
              <span className="text-[#999999]">Agent Server: </span>
              <span className={status.agent_ok ? 'text-green-400' : 'text-yellow-400'}>
                {status.agent_ok ? `运行中 (:${status.agent_port})` : '启动中...'}
              </span>
            </div>
            <div>
              <span className="text-[#999999]">Bridge Client: </span>
              <span className={status.client_connected ? 'text-green-400' : 'text-yellow-400'}>
                {status.client_connected ? '已连接' : '连接中...'}
              </span>
            </div>
            <div>
              <span className="text-[#999999]">运行时长: </span>
              <span>{formatDuration(status.started_at)}</span>
            </div>
          </div>
        )}
      </div>

      {/* Logs section */}
      {status.running && (
        <div>
          <button
            type="button"
            onClick={() => setShowLogs(!showLogs)}
            className="flex items-center gap-1 text-[12px] text-[#999999] hover:text-white transition-colors mb-2"
          >
            <span className={`transition-transform ${showLogs ? 'rotate-90' : ''}`}>
              ▸
            </span>
            实时日志
          </button>

          {showLogs && (
            <div
              ref={logsContainerRef}
              onScroll={() => {
                const el = logsContainerRef.current;
                if (!el) return;
                // User is "at bottom" if within 30px of the end
                const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 30;
                isUserScrolling.current = !atBottom;
              }}
              className="bg-[#1a1a1a] border border-[#3a3a3a] rounded-lg p-2 max-h-60 overflow-y-auto font-mono"
            >
              {logs.length === 0 ? (
                <p className="text-[10px] text-[#666666]">暂无日志...</p>
              ) : (
                logs.map((line, i) => (
                  <div key={i} className="text-[10px] text-[#cccccc] leading-relaxed whitespace-pre-wrap break-all">
                    {line}
                  </div>
                ))
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
};
