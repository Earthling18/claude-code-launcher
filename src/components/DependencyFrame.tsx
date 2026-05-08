import { useEffect, useState, useRef } from 'react';
import { api } from '../api';
import { toast } from '../lib/toast';
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

  const handleAction = async (key: string, action: 'install' | 'update' | 'reinstall') => {
    const config = depConfig[key];
    setDeps(prev => ({ ...prev, [key]: { ...prev[key], loading: true } }));
    try {
      if (action === 'install') {
        await config.installFn();
      } else if (action === 'update') {
        await config.updateFn();
      } else if (action === 'reinstall') {
        if (key === 'claude') await api.reinstallClaude();
        else if (key === 'codex') await api.reinstallCodex();
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
      toast.error(`操作失败: ${error}`);
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
      <div>
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
      <div className="card p-4">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <span className={`dot ${hasIssues ? 'dot-warn dot-pulse' : 'dot-ok'}`} />
            <h2 className="text-[13px] font-semibold text-text-primary">
              {hasIssues ? '依赖需要处理' : '系统依赖就绪'}
            </h2>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={checkWithUpdates}
              disabled={checking}
              className="btn btn-ghost btn-sm"
            >
              {isInstalling ? '安装中…' : checking ? '检测中…' : '刷新'}
            </button>
            <button
              onClick={() => setExpanded(false)}
              className="btn btn-ghost btn-sm"
            >
              收起
            </button>
          </div>
        </div>
        <div className="grid grid-cols-2 gap-x-6 gap-y-2.5">
          {Object.entries(deps).map(([key, d]) => {
            const config = depConfig[key];
            const dotClass = !d.status
              ? 'dot'
              : !d.status.installed
              ? 'dot dot-error'
              : d.status.update_available
              ? 'dot dot-warn'
              : 'dot dot-ok';
            const canReinstall = (key === 'claude' || key === 'codex') && d.status?.installed;
            return (
              <div key={key} className="flex items-center gap-2.5">
                <span className={`${dotClass} ${d.loading ? 'dot-pulse' : ''}`} />
                <span className="text-[12px] text-text-primary w-20 flex-shrink-0">{config.label}</span>
                {!d.status ? (
                  <span className="font-mono text-[10.5px] text-text-tertiary">checking…</span>
                ) : !d.status.installed ? (
                  <>
                    <span className="font-mono text-[10.5px] text-error/90">missing</span>
                    {!d.loading && (
                      <button onClick={() => handleAction(key, 'install')} className="btn btn-secondary btn-sm ml-auto">安装</button>
                    )}
                  </>
                ) : d.status.update_available ? (
                  <>
                    <span className="font-mono text-[10.5px] text-warn">{d.status.version} → {d.status.latest_version}</span>
                    {!d.loading && (
                      <div className="ml-auto flex items-center gap-1">
                        <button onClick={() => handleAction(key, 'update')} className="btn btn-secondary btn-sm">更新</button>
                        {canReinstall && (
                          <button onClick={() => handleAction(key, 'reinstall')} className="btn btn-ghost btn-sm" title="卸载后重新安装">重装</button>
                        )}
                      </div>
                    )}
                  </>
                ) : (
                  <>
                    <span className="font-mono text-[10.5px] text-text-tertiary">{d.status.version}</span>
                    {canReinstall && !d.loading && (
                      <button
                        onClick={() => handleAction(key, 'reinstall')}
                        className="btn btn-ghost btn-sm ml-auto opacity-60 hover:opacity-100"
                        title="卸载后重新安装"
                      >
                        重装
                      </button>
                    )}
                  </>
                )}
                {d.loading && <span className="font-mono text-[10.5px] text-text-tertiary">…</span>}
              </div>
            );
          })}
        </div>
      </div>
    );
  }

  // Collapsed — show minimal bar
  const summaryDot = isInstalling
    ? 'dot dot-info dot-pulse'
    : checking
    ? 'dot dot-info dot-pulse'
    : hasIssues
    ? 'dot dot-warn'
    : 'dot dot-ok';
  const summaryText = isInstalling
    ? '安装中'
    : checking
    ? '检测中'
    : hasIssues
    ? '有更新可用'
    : '依赖就绪';

  return (
    <div className="flex items-center justify-between py-1.5 px-1">
      <div className="flex items-center gap-3">
        <div className="flex items-center gap-2">
          <span className={summaryDot} />
          <span className="text-[11.5px] text-text-secondary">{summaryText}</span>
        </div>
        <div className="hidden md:flex items-center gap-3 font-mono text-[10px] text-text-tertiary">
          {Object.entries(deps).map(([key, d]) => (
            <span key={key} className="lowercase">
              {depConfig[key].label.toLowerCase()} <span className="text-text-disabled">{d.status?.version || '—'}</span>
            </span>
          ))}
        </div>
      </div>
      <div className="flex items-center gap-1">
        <button
          onClick={() => { setExpanded(true); checkWithUpdates(); }}
          disabled={checking}
          className="btn btn-ghost btn-sm"
        >
          检查更新
        </button>
        <button
          onClick={() => setShowCcConfig(true)}
          className="btn btn-ghost btn-sm"
        >
          CC 修复
        </button>
      </div>
    </div>
  );
};
