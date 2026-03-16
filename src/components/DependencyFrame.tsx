import { useEffect, useState, useRef } from 'react';
import { api } from '../api';
import type { DependencyStatus } from '../types';
import type { Project } from '../types/project';
import { CcConfigPanel } from './CcConfigPanel';

interface DependencyFrameProps {
  projects?: Project[];
  platform?: string;
}

export const DependencyFrame: React.FC<DependencyFrameProps> = ({ projects = [], platform = 'macos' }) => {
  const [deps, setDeps] = useState<Record<string, { status: DependencyStatus | null; loading: boolean }>>({
    nodejs: { status: null, loading: false },
    git: { status: null, loading: false },
    claude: { status: null, loading: false },
    codex: { status: null, loading: false },
  });
  const [checking, setChecking] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [showCcConfig, setShowCcConfig] = useState(false);
  const hasChecked = useRef(false);

  const depConfig: Record<string, { label: string; checkFn: () => Promise<DependencyStatus>; installFn: () => Promise<unknown>; updateFn: () => Promise<unknown>; checkUpdateFn: () => Promise<DependencyStatus> }> = {
    nodejs: { label: 'Node.js', checkFn: api.checkNodejs, installFn: api.installNodejs, updateFn: api.updateNodejs, checkUpdateFn: api.checkNodejsWithUpdate },
    git: { label: 'Git', checkFn: api.checkGitbash, installFn: api.installGitbash, updateFn: api.updateGitbash, checkUpdateFn: api.checkGitbashWithUpdate },
    claude: { label: 'Claude Code', checkFn: api.checkClaude, installFn: api.installClaude, updateFn: api.updateClaude, checkUpdateFn: api.checkClaudeWithUpdate },
    codex: { label: 'Codex', checkFn: api.checkCodex, installFn: api.installCodex, updateFn: api.updateCodex, checkUpdateFn: api.checkCodexWithUpdate },
  };

  // Parallel silent check on mount
  useEffect(() => {
    if (hasChecked.current) return;
    hasChecked.current = true;

    // Use cached results if available
    try {
      const cached = sessionStorage.getItem('dependencyStatus');
      if (cached) {
        const c = JSON.parse(cached);
        setDeps({
          nodejs: { status: c.nodejs || null, loading: false },
          git: { status: c.gitbash || null, loading: false },
          claude: { status: c.claude || null, loading: false },
          codex: { status: c.codex || null, loading: false },
        });
        return;
      }
    } catch (_) {}

    runParallelCheck();
  }, []);

  const runParallelCheck = async () => {
    setChecking(true);
    try {
      const [nodeResult, gitResult, claudeResult, codexResult] = await Promise.all([
        api.checkNodejs().catch(() => null),
        api.checkGitbash().catch(() => null),
        api.checkClaude().catch(() => null),
        api.checkCodex().catch(() => null),
      ]);

      const newDeps = {
        nodejs: { status: nodeResult, loading: false },
        git: { status: gitResult, loading: false },
        claude: { status: claudeResult, loading: false },
        codex: { status: codexResult, loading: false },
      };
      setDeps(newDeps);

      // Auto-expand only if something is missing (not for updates)
      const hasMissing = [nodeResult, gitResult, claudeResult, codexResult].some(r => r && !r.installed);
      if (hasMissing) setExpanded(true);

      sessionStorage.setItem('dependencyStatus', JSON.stringify({
        nodejs: nodeResult,
        gitbash: gitResult,
        claude: claudeResult,
        codex: codexResult,
      }));
    } catch (error) {
      console.error('检测失败:', error);
    } finally {
      setChecking(false);
    }
  };

  const checkWithUpdates = async () => {
    sessionStorage.removeItem('dependencyStatus');
    setChecking(true);
    try {
      await api.refreshSystemPath();
      const [nodeResult, gitResult, claudeResult, codexResult] = await Promise.all([
        api.checkNodejsWithUpdate().catch(() => null),
        api.checkGitbashWithUpdate().catch(() => null),
        api.checkClaudeWithUpdate().catch(() => null),
        api.checkCodexWithUpdate().catch(() => null),
      ]);

      const newDeps = {
        nodejs: { status: nodeResult, loading: false },
        git: { status: gitResult, loading: false },
        claude: { status: claudeResult, loading: false },
        codex: { status: codexResult, loading: false },
      };
      setDeps(newDeps);

      sessionStorage.setItem('dependencyStatus', JSON.stringify({
        nodejs: nodeResult,
        gitbash: gitResult,
        claude: claudeResult,
        codex: codexResult,
      }));
    } catch (error) {
      console.error('检测失败:', error);
    } finally {
      setChecking(false);
    }
  };

  const handleAction = async (key: string, action: 'install' | 'update') => {
    const config = depConfig[key];
    setDeps(prev => ({ ...prev, [key]: { ...prev[key], loading: true } }));
    try {
      if (action === 'install') {
        await config.installFn();
      } else {
        await config.updateFn();
      }
      // Re-check after action
      setTimeout(async () => {
        try {
          const result = await config.checkFn();
          setDeps(prev => ({ ...prev, [key]: { status: result, loading: false } }));
        } catch {
          setDeps(prev => ({ ...prev, [key]: { ...prev[key], loading: false } }));
        }
      }, 2000);
    } catch (error: any) {
      alert(`操作失败: ${error}`);
      setDeps(prev => ({ ...prev, [key]: { ...prev[key], loading: false } }));
    }
  };

  // Check if any issues exist
  const hasIssues = Object.values(deps).some(d => d.status && (!d.status.installed || d.status.update_available));
  const allChecked = Object.values(deps).every(d => d.status !== null);
  const isInstalling = Object.values(deps).some(d => d.loading);

  // Don't show anything while initial check is running (no previous data)
  if (!allChecked && !checking) {
    return null;
  }
  if (!allChecked && checking && !Object.values(deps).some(d => d.status !== null)) {
    return null;
  }

  // Show CC config panel
  if (showCcConfig) {
    return (
      <div className="px-5 py-2">
        <CcConfigPanel
          projects={projects}
          platform={platform}
          onClose={() => setShowCcConfig(false)}
        />
      </div>
    );
  }

  // Show expanded dependency detail panel
  if (expanded) {
    return (
      <div className="px-5 py-2">
        <div className="card-frame">
          <div className="flex items-center justify-between mb-2">
            <h2 className="text-[13px] font-bold">
              {hasIssues ? '⚠ 依赖需要处理' : '系统依赖'}
            </h2>
            <div className="flex items-center gap-2">
              <button
                onClick={checkWithUpdates}
                disabled={checking}
                className="px-3 py-1 text-[10px] bg-[#666666] hover:bg-[#555555] text-white rounded disabled:opacity-50"
              >
                {isInstalling ? '安装中...' : checking ? '检测中...' : '刷新'}
              </button>
              <button
                onClick={() => setExpanded(false)}
                className="text-[10px] text-[#cccccc] hover:text-white transition-colors"
              >
                收起
              </button>
            </div>
          </div>
          <div className="flex items-center gap-4 flex-wrap">
            {Object.entries(deps).map(([key, d]) => {
              const config = depConfig[key];
              return (
                <div key={key} className="flex items-center gap-2">
                  <span className="text-[10px]">{config.label}:</span>
                  {!d.status ? (
                    <span className="text-[#999999] text-[10px]">⏳</span>
                  ) : !d.status.installed ? (
                    <>
                      <span className="text-red-500 text-[10px]">✗</span>
                      {!d.loading && (
                        <button onClick={() => handleAction(key, 'install')} className="px-3 py-1 text-[10px] bg-[#3b82f6] hover:bg-[#2563eb] rounded text-white">
                          安装
                        </button>
                      )}
                    </>
                  ) : d.status.update_available ? (
                    <>
                      <span className="text-yellow-500 text-[10px]">⚠ {d.status.version} → {d.status.latest_version}</span>
                      {!d.loading && (
                        <button onClick={() => handleAction(key, 'update')} className="px-3 py-1 text-[10px] bg-[#3b82f6] hover:bg-[#2563eb] rounded text-white">
                          更新
                        </button>
                      )}
                    </>
                  ) : (
                    <span className="text-[#10b981] text-[10px]">✓ {d.status.version}</span>
                  )}
                  {d.loading && <span className="text-[10px] text-[#999999]">处理中...</span>}
                </div>
              );
            })}
          </div>
        </div>
      </div>
    );
  }

  // Collapsed — show minimal bar with two buttons
  return (
    <div className="px-5 py-1">
      <div className="flex items-center justify-between py-1">
        <div className="flex items-center gap-2">
          {isInstalling
            ? <span className="text-[10px] text-[#3b82f6]">⏳ 安装中...</span>
            : checking
            ? <span className="text-[10px] text-[#999999]">⏳ 检测中...</span>
            : hasIssues
            ? <span className="text-[10px] text-yellow-500">⚠ 有更新可用</span>
            : <span className="text-[10px] text-[#10b981]">✓ 依赖就绪</span>
          }
          {Object.entries(deps).map(([key, d]) => (
            <span key={key} className="text-[10px] text-[#999999]">
              {depConfig[key].label} {d.status?.version}
            </span>
          ))}
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={() => { setExpanded(true); checkWithUpdates(); }}
            disabled={checking}
            className="text-[10px] text-[#cccccc] hover:text-white transition-colors disabled:opacity-50"
          >
            检查更新
          </button>
          <button
            onClick={() => setShowCcConfig(true)}
            className="text-[10px] text-[#cccccc] hover:text-white transition-colors"
          >
            CC修复
          </button>
        </div>
      </div>
    </div>
  );
};
