import { useState, useEffect, useRef } from 'react';
import { getCurrentWindow } from '@tauri-apps/api/window';
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
  const [iframeLoaded, setIframeLoaded] = useState(false);
  const [iframeError, setIframeError] = useState(false);
  const logsRef = useRef<HTMLDivElement>(null);
  const isUserScrolling = useRef(false);
  const pollRef = useRef<number | null>(null);
  const lastAutoStartRef = useRef<number>(0);
  const hasEverLoaded = useRef(false);
  const iframeMountedAt = useRef<number>(0);
  const consecutiveFailures = useRef(0);
  const MAX_FAILURES_BEFORE_STOP = 5; // 5 × 3s = 15s grace period for hot-update restart

  useEffect(() => {
    getCurrentWindow().maximize().catch(() => {});
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
          // Pre-cache python path for potential auto-restart after hot-update
          mobotApi.detectPython().then(p => { if (p) setPythonPath(p); }).catch(() => {});
          setViewState('running');
          startPolling();
          return;
        }
        if ('Installed' in installStatus) {
          setBridgePath(installStatus.Installed.path);
          // Check if service is already running on the port (e.g. restarted by restart_helper)
          try {
            const health = await mobotApi.checkHealth(port);
            if (health?.healthy) {
              // Pre-cache python path for potential auto-restart after hot-update
              mobotApi.detectPython().then(p => { if (p) setPythonPath(p); }).catch(() => {});
              setViewState('running');
              startPolling();
              return;
            }
          } catch {}
          // Detect python and auto-start
          const python = await mobotApi.detectPython();
          if (python) {
            setPythonPath(python);
            autoStart(installStatus.Installed.path, python);
          } else {
            setViewState('installed_stopped');
          }
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
          // Service not tracked by Tauri — but it may have been restarted
          // externally (e.g. by restart_helper after hot-update). Check port.
          try {
            const health = await mobotApi.checkHealth(port);
            if (health?.healthy) {
              consecutiveFailures.current = 0;
              setViewState('running');
              return; // keep polling, service is alive
            }
          } catch {}
          // Skip auto-restart if mobot is updating itself
          try {
            const updating = await mobotApi.isUpdating();
            if (updating) {
              consecutiveFailures.current = 0;
              return; // keep polling, update in progress
            }
          } catch {}
          // Grace period: during hot-update restart, service may be briefly
          // unavailable. Keep polling for a while before giving up.
          consecutiveFailures.current++;
          if (consecutiveFailures.current < MAX_FAILURES_BEFORE_STOP) {
            return; // keep polling, wait for service to come back
          }
          // Grace period exhausted — give up and try auto-restart
          consecutiveFailures.current = 0;
          if (pollRef.current) clearInterval(pollRef.current);
          // Auto-restart with 10s cooldown to prevent rapid loops
          const now = Date.now();
          if (now - lastAutoStartRef.current < 10000) {
            setViewState('installed_stopped');
            return;
          }
          const python = pythonPath || await mobotApi.detectPython();
          if (python && bridgePath) {
            autoStart(bridgePath, python);
          } else {
            setViewState('installed_stopped');
          }
        } else {
          // Service is running — reset failure counter
          consecutiveFailures.current = 0;
        }
      } catch {}
    };

    poll();
    pollRef.current = window.setInterval(poll, 3000);
  };

  const handleSetupComplete = (installPath: string, python: string) => {
    setBridgePath(installPath);
    setPythonPath(python);
    setError(null);
    setIframeLoaded(false);
    hasEverLoaded.current = false;
    setIframeError(false);
    setViewState('running');
    startPolling();
  };

  const autoStart = async (path: string, python: string) => {
    lastAutoStartRef.current = Date.now();
    setLoading(true);
    setError(null);
    try {
      await mobotApi.startService(path, python, port);
      await new Promise((r) => setTimeout(r, 2000));
      // Verify service is actually running after startup
      const s = await mobotApi.getStatus(port);
      if (!s.running) {
        // Process exited immediately (e.g. missing dependencies)
        const recentLogs = await mobotApi.getLogs(10).catch(() => [] as string[]);
        const errorHint = recentLogs.find(l => /error|traceback|no module/i.test(l));
        setError(errorHint || '服务启动后立即退出，请尝试重装依赖');
        setViewState('installed_stopped');
        return;
      }
      setIframeLoaded(false);
      hasEverLoaded.current = false;
      setIframeError(false);
      setViewState('running');
      startPolling();
    } catch (err: any) {
      setError(err?.toString() || '启动失败');
      setViewState('installed_stopped');
    } finally {
      setLoading(false);
    }
  };


  // Auto-dismiss loading overlay after iframe mounts (don't wait for onLoad)
  useEffect(() => {
    if ((status?.healthy || hasEverLoaded.current) && !iframeLoaded && !iframeError) {
      if (!iframeMountedAt.current) {
        iframeMountedAt.current = Date.now();
      }
      const timer = setTimeout(() => {
        setIframeLoaded(true);
        hasEverLoaded.current = true;
      }, 1500);
      return () => clearTimeout(timer);
    }
  }, [status?.healthy, iframeLoaded, iframeError]);

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
            <ModeSwitch active="remote" disabled={viewState === 'not_installed' || loading} />
            <h2 className="text-base font-bold">Mobot Bridge</h2>
          </div>

          {(viewState === 'running' || viewState === 'installed_stopped') && (
            <div className="flex items-center gap-2">
              {getStatusIndicator()}
              <span className="text-[12px]">
                {viewState === 'installed_stopped'
                  ? (loading ? '正在启动...' : error ? '启动失败' : '未运行')
                  : status?.healthy ? '运行中' : status?.running ? '启动中...' : '未运行'}
              </span>
              {viewState === 'running' && (
                <button
                  type="button"
                  onClick={() => setShowLogs(!showLogs)}
                  className="text-[11px] text-[#666666] hover:text-white transition-colors ml-1"
                >
                  {showLogs ? '隐藏日志' : '日志'}
                </button>
              )}
            </div>
          )}
        </div>

        {error && viewState !== 'running' && (
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

        {/* Installed but stopped — auto-starting or error */}
        {viewState === 'installed_stopped' && (
          <div className="h-full flex items-center justify-center">
            <div className="text-center space-y-4">
              {loading ? (
                <>
                  <div className="w-8 h-8 border-2 border-[#10b981] border-t-transparent rounded-full animate-spin mx-auto" />
                  <p className="text-[14px] text-[#999999]">正在启动 mobot-bridge...</p>
                </>
              ) : error ? (
                <>
                  <p className="text-[14px] text-red-400">{error}</p>
                  <button
                    onClick={() => setViewState('not_installed')}
                    className="px-4 py-1.5 text-[12px] bg-[#3b82f6] hover:bg-[#2563eb] text-white rounded-lg transition-colors"
                  >
                    重装
                  </button>
                </>
              ) : (
                <>
                  <p className="text-[14px] text-[#999999]">服务未运行</p>
                  <button
                    onClick={async () => {
                      setError(null);
                      const python = await mobotApi.detectPython();
                      if (python && bridgePath) {
                        autoStart(bridgePath, python);
                      } else {
                        setError('未找到 Python 3.10+，请重装');
                      }
                    }}
                    className="px-4 py-1.5 text-[12px] bg-[#10b981] hover:bg-[#059669] text-white rounded-lg transition-colors"
                  >
                    重新启动
                  </button>
                </>
              )}
              <p className="text-[11px] text-[#666666]">安装路径: {bridgePath}</p>
            </div>
          </div>
        )}

        {/* Running: iframe + optional logs */}
        {viewState === 'running' && (
          <div className="h-full flex flex-col">
            {showLogs && (
              <div className="flex-shrink-0 px-6 py-2 border-b border-[#3a3a3a] bg-[#1e1e1e]">
                <div
                  ref={logsRef}
                  onScroll={() => {
                    const el = logsRef.current;
                    if (!el) return;
                    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 30;
                    isUserScrolling.current = !atBottom;
                  }}
                  className="bg-[#1a1a1a] border border-[#3a3a3a] rounded p-2 max-h-40 overflow-y-auto font-mono"
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
              </div>
            )}

            {/* iframe: mobot-bridge Web Config UI */}
            <div className="flex-1 relative">
              {/* Show loading overlay before first successful load */}
              {!iframeLoaded && !iframeError && (
                <div className="absolute inset-0 flex items-center justify-center bg-[#212121] z-10">
                  <div className="text-center space-y-3">
                    <div className="w-8 h-8 border-2 border-[#3b82f6] border-t-transparent rounded-full animate-spin mx-auto" />
                    <p className="text-[13px] text-[#999999]">
                      {!status?.healthy ? '等待服务就绪...' : '加载配置界面...'}
                    </p>
                    <p className="text-[11px] text-[#666666]">
                      服务启动可能需要几秒钟
                    </p>
                  </div>
                </div>
              )}
              {iframeError && !iframeLoaded && (
                <div className="absolute inset-0 flex items-center justify-center bg-[#212121] z-10">
                  <div className="text-center space-y-3">
                    <p className="text-[13px] text-red-400">配置界面加载失败</p>
                    <p className="text-[11px] text-[#666666]">
                      请确认 mobot-bridge 服务正常运行
                    </p>
                    <button
                      onClick={() => {
                        setIframeError(false);
                        setIframeLoaded(false);
                        hasEverLoaded.current = false;
                      }}
                      className="px-4 py-1.5 text-[12px] bg-[#3b82f6] hover:bg-[#2563eb] text-white rounded-lg transition-colors"
                    >
                      重试
                    </button>
                  </div>
                </div>
              )}
              {/* Keep iframe mounted once healthy; never unmount after first load */}
              {(status?.healthy || hasEverLoaded.current) && (
                <iframe
                  src={`http://127.0.0.1:${port}/config`}
                  className="w-full h-full border-0"
                  title="Mobot Bridge Config"
                  allow="clipboard-read; clipboard-write"
                  onLoad={() => {
                    setIframeLoaded(true);
                    hasEverLoaded.current = true;
                  }}
                  onError={() => setIframeError(true)}
                />
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
