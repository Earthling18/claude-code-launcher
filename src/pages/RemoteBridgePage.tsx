import { useState, useEffect, useRef } from 'react';
import { mobotApi } from '../api';
import { MobotSetupWizard } from '../components/MobotSetupWizard';
import { ModeSwitch } from '../components/ModeSwitch';
import type { MobotServiceStatus } from '../types/project';

type ViewState = 'loading' | 'not_installed' | 'installed_stopped' | 'running';

const DEFAULT_PORT = 8000;

export const RemoteBridgePage: React.FC = () => {
  const [viewState, setViewState] = useState<ViewState>('loading');
  const [status, setStatus] = useState<MobotServiceStatus | null>(null);
  const [bridgePath, setBridgePath] = useState('');
  const [pythonPath, setPythonPath] = useState('');
  const [port] = useState(DEFAULT_PORT);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [logs, setLogs] = useState<string[]>([]);
  const [showLogs, setShowLogs] = useState(false);
  const logsRef = useRef<HTMLDivElement>(null);
  const isUserScrolling = useRef(false);
  const pollRef = useRef<number | null>(null);

  useEffect(() => {
    checkInstallation();
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, []);

  // Auto-scroll logs
  useEffect(() => {
    if (!isUserScrolling.current && logsRef.current) {
      logsRef.current.scrollTop = logsRef.current.scrollHeight;
    }
  }, [logs]);

  const checkInstallation = async () => {
    try {
      const installStatus = await mobotApi.detectInstallation();

      if (installStatus === 'NotInstalled') {
        setViewState('not_installed');
        return;
      }

      if (typeof installStatus === 'object') {
        if ('Running' in installStatus) {
          setBridgePath(installStatus.Running.path);
          setViewState('running');
          startPolling();
          return;
        }
        if ('Installed' in installStatus) {
          setBridgePath(installStatus.Installed.path);
          // Detect python for later use
          const python = await mobotApi.detectPython();
          if (python) setPythonPath(python);
          setViewState('installed_stopped');
          return;
        }
      }

      setViewState('not_installed');
    } catch (err) {
      console.error('Failed to detect installation:', err);
      setViewState('not_installed');
    }
  };

  const startPolling = () => {
    if (pollRef.current) clearInterval(pollRef.current);

    const poll = async () => {
      try {
        const s = await mobotApi.getStatus(port);
        setStatus(s);
        if (!s.running) {
          setViewState('installed_stopped');
          if (pollRef.current) clearInterval(pollRef.current);
        }
      } catch {}
    };

    poll();
    pollRef.current = window.setInterval(poll, 3000);
  };

  const handleSetupComplete = (installPath: string, python: string) => {
    setBridgePath(installPath);
    setPythonPath(python);
    setViewState('running');
    startPolling();
  };

  const handleStart = async () => {
    setLoading(true);
    setError(null);
    try {
      let python = pythonPath;
      if (!python) {
        const detected = await mobotApi.detectPython();
        if (!detected) {
          setError('未找到 Python 3.10+，请先安装');
          return;
        }
        python = detected;
        setPythonPath(python);
      }

      await mobotApi.startService(bridgePath, python, port);

      // Wait briefly for process to start
      await new Promise((r) => setTimeout(r, 2000));

      setViewState('running');
      startPolling();
    } catch (err: any) {
      setError(err?.toString() || '启动失败');
    } finally {
      setLoading(false);
    }
  };

  const handleStop = async () => {
    setLoading(true);
    setError(null);
    try {
      await mobotApi.stopService();
      setStatus(null);
      setViewState('installed_stopped');
      if (pollRef.current) clearInterval(pollRef.current);
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
      await mobotApi.stopService();
      await new Promise((r) => setTimeout(r, 1000));

      let python = pythonPath;
      if (!python) {
        const detected = await mobotApi.detectPython();
        if (detected) {
          python = detected;
          setPythonPath(python);
        }
      }

      if (python) {
        await mobotApi.startService(bridgePath, python, port);
        await new Promise((r) => setTimeout(r, 2000));
        startPolling();
      }
    } catch (err: any) {
      setError(err?.toString() || '重启失败');
    } finally {
      setLoading(false);
    }
  };

  // Poll logs when visible
  useEffect(() => {
    if (!showLogs || viewState !== 'running') return;

    const pollLogs = async () => {
      try {
        const l = await mobotApi.getLogs(200);
        setLogs(l);
      } catch {}
    };

    pollLogs();
    const interval = setInterval(pollLogs, 2000);
    return () => clearInterval(interval);
  }, [showLogs, viewState]);

  const getStatusIndicator = () => {
    if (!status?.running) {
      return <span className="inline-block w-2.5 h-2.5 rounded-full bg-gray-500" title="未运行" />;
    }
    if (status.healthy) {
      return <span className="inline-block w-2.5 h-2.5 rounded-full bg-green-500 animate-pulse" title="运行中" />;
    }
    return <span className="inline-block w-2.5 h-2.5 rounded-full bg-yellow-500 animate-pulse" title="启动中" />;
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

  if (viewState === 'loading') {
    return (
      <div className="h-screen bg-[#212121] text-[#DCE4EE] flex items-center justify-center">
        <div className="text-[#999999]">检测 mobot-bridge 状态...</div>
      </div>
    );
  }

  return (
    <div className="h-screen bg-[#212121] text-[#DCE4EE] flex flex-col overflow-hidden">
      {/* Top bar — always visible */}
      <div className="flex-shrink-0 px-6 py-3 border-b border-[#3a3a3a]">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <ModeSwitch active="remote" />
            <h2 className="text-base font-bold">Mobot Bridge</h2>
          </div>

          {viewState === 'running' && (
            <div className="flex items-center gap-3">
              <div className="flex items-center gap-2">
                {getStatusIndicator()}
                <span className="text-[12px]">
                  {status?.healthy ? '运行中' : status?.running ? '启动中...' : '未运行'}
                </span>
                {status?.started_at && (
                  <span className="text-[11px] text-[#999999]">
                    ({formatDuration(status.started_at)})
                  </span>
                )}
              </div>
              <button
                onClick={handleRestart}
                disabled={loading}
                className="px-3 py-1 text-[11px] bg-[#f59e0b] hover:bg-[#d97706] disabled:opacity-50 text-white rounded transition-colors"
              >
                重启
              </button>
              <button
                onClick={handleStop}
                disabled={loading}
                className="px-3 py-1 text-[11px] bg-red-600 hover:bg-red-700 disabled:opacity-50 text-white rounded transition-colors"
              >
                停止
              </button>
            </div>
          )}

          {viewState === 'installed_stopped' && (
            <button
              onClick={handleStart}
              disabled={loading}
              className="px-4 py-1.5 text-[12px] bg-[#10b981] hover:bg-[#059669] disabled:opacity-50 text-white rounded-lg transition-colors"
            >
              {loading ? '启动中...' : '启动服务'}
            </button>
          )}
        </div>

        {error && (
          <p className="text-[11px] text-red-400 mt-2">{error}</p>
        )}
      </div>

      {/* Main content area */}
      <div className="flex-1 overflow-hidden">
        {/* Not installed: show setup wizard */}
        {viewState === 'not_installed' && (
          <div className="h-full overflow-auto p-6">
            <div className="max-w-lg mx-auto">
              <MobotSetupWizard
                onComplete={handleSetupComplete}
                onCancel={() => window.history.back()}
              />
            </div>
          </div>
        )}

        {/* Installed but stopped */}
        {viewState === 'installed_stopped' && (
          <div className="h-full flex items-center justify-center">
            <div className="text-center space-y-4">
              <div className="text-[48px] opacity-30">
                <svg width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1" strokeLinecap="round" strokeLinejoin="round" className="mx-auto text-[#10b981]">
                  <circle cx="12" cy="12" r="10" />
                  <line x1="2" y1="12" x2="22" y2="12" />
                  <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z" />
                </svg>
              </div>
              <p className="text-[14px] text-[#999999]">mobot-bridge 已安装，点击上方「启动服务」开始使用</p>
              <p className="text-[11px] text-[#666666]">安装路径: {bridgePath}</p>
            </div>
          </div>
        )}

        {/* Running: status bar + iframe */}
        {viewState === 'running' && (
          <div className="h-full flex flex-col">
            {/* Logs toggle */}
            <div className="flex-shrink-0 px-6 py-2 border-b border-[#3a3a3a] bg-[#1e1e1e]">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-4 text-[11px] text-[#999999]">
                  <span>端口: {status?.port || port}</span>
                  {status?.pid && <span>PID: {status.pid}</span>}
                  <span>
                    健康: {status?.healthy ? (
                      <span className="text-green-400">正常</span>
                    ) : (
                      <span className="text-yellow-400">检测中</span>
                    )}
                  </span>
                </div>
                <button
                  type="button"
                  onClick={() => setShowLogs(!showLogs)}
                  className="text-[11px] text-[#999999] hover:text-white transition-colors"
                >
                  {showLogs ? '隐藏日志' : '查看日志'}
                </button>
              </div>

              {showLogs && (
                <div
                  ref={logsRef}
                  onScroll={() => {
                    const el = logsRef.current;
                    if (!el) return;
                    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 30;
                    isUserScrolling.current = !atBottom;
                  }}
                  className="mt-2 bg-[#1a1a1a] border border-[#3a3a3a] rounded p-2 max-h-40 overflow-y-auto font-mono"
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

            {/* iframe: mobot-bridge Web Config UI */}
            <div className="flex-1">
              <iframe
                src={`http://127.0.0.1:${port}/config`}
                className="w-full h-full border-0"
                title="Mobot Bridge Config"
                allow="clipboard-read; clipboard-write"
              />
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
