import { useEffect, useState, useRef } from 'react';
import { openUrl } from '@tauri-apps/plugin-opener';
import { api } from '../api';
import { toast } from '../lib/toast';
import type { DependencyStatus } from '../types';
import type { Project } from '../types/project';
import { CcConfigPanel } from './CcConfigPanel';

const SKILL_MARKET_URL = 'http://uat.aiep.weoa.com/#/assets/plugin?microPath=/assets/plugin';

// 单项检测最长等待时间。后端虽已加超时，这里再兜一层：任何一项卡住都不会
// 让整个面板永远停在"检测中"。超时按失败处理（resolve null），不影响其他项。
const CHECK_TIMEOUT_MS = 20000;
function withTimeout<T>(p: Promise<T>): Promise<T | null> {
  return Promise.race([
    p,
    new Promise<null>(resolve => setTimeout(() => resolve(null), CHECK_TIMEOUT_MS)),
  ]);
}

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
    skill_market: { status: null, loading: false },
  });
  const [checking, setChecking] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [showCcConfig, setShowCcConfig] = useState(false);
  const hasChecked = useRef(false);
  const manualActionInFlight = useRef(false);
  const skillAutoUpdateAttempted = useRef(false);
  // Concurrency guards: withTimeout (Promise.race) unblocks the UI at 20s but
  // does NOT cancel the underlying Tauri invoke — the backend keeps running.
  // checkInFlight stops a second round from stacking on top of a running one;
  // checkEpoch lets a fresh round discard the stale round's late results.
  const checkInFlight = useRef(false);
  const checkEpoch = useRef(0);
  // True once at least one full check round has completed, so a row that never
  // resolved shows a neutral "未检测到" instead of spinning on "checking…" forever.
  const [checkDone, setCheckDone] = useState(false);

  const depConfig: Record<string, { label: string; checkFn: () => Promise<DependencyStatus>; installFn: () => Promise<unknown>; updateFn: () => Promise<unknown>; checkUpdateFn: () => Promise<DependencyStatus> }> = {
    nodejs: { label: 'Node.js', checkFn: api.checkNodejs, installFn: api.installNodejs, updateFn: api.updateNodejs, checkUpdateFn: api.checkNodejsWithUpdate },
    git: { label: 'Git', checkFn: api.checkGitbash, installFn: api.installGitbash, updateFn: api.updateGitbash, checkUpdateFn: api.checkGitbashWithUpdate },
    claude: { label: 'Claude Code', checkFn: api.checkClaude, installFn: api.installClaude, updateFn: api.updateClaude, checkUpdateFn: api.checkClaudeWithUpdate },
    codex: { label: 'Codex', checkFn: api.checkCodex, installFn: api.installCodex, updateFn: api.updateCodex, checkUpdateFn: api.checkCodexWithUpdate },
    // skill-market: best-effort intranet resource. installFn is silent (no terminal); update reuses install.
    skill_market: {
      label: 'Webank 技能市场',
      checkFn: api.checkSkillMarket,
      installFn: api.installSkillMarket,
      updateFn: api.installSkillMarket,
      checkUpdateFn: api.checkSkillMarketWithUpdate,
    },
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
        // A cache with missing core statuses (e.g. a check failed last time)
        // would hide the panel for the whole session — re-check instead
        if (!c.nodejs || !c.gitbash || !c.claude || !c.codex) {
          throw new Error('incomplete cache');
        }
        setDeps({
          nodejs: { status: c.nodejs || null, loading: false },
          git: { status: c.gitbash || null, loading: false },
          claude: { status: c.claude || null, loading: false },
          codex: { status: c.codex || null, loading: false },
          skill_market: { status: c.skill_market || null, loading: false },
        });
        // Cache from a plain check has no update info — refresh it silently
        if (!c.__withUpdates) {
          checkWithUpdates(true);
        } else {
          autoUpdateSkillMarket(c.skill_market);
        }
        return;
      }
    } catch (_) {}

    // Fast check first for immediate UI, then silently fetch update info
    runParallelCheck().then(() => checkWithUpdates(true));
  }, []);

  // Only the skill marketplace may update automatically. Never route CLI
  // checks through the installer, including checks restored from the cache.
  const autoUpdateSkillMarket = async (status: DependencyStatus | null) => {
    if (!status?.installed || !status.update_available || skillAutoUpdateAttempted.current || manualActionInFlight.current) return;
    skillAutoUpdateAttempted.current = true;
    manualActionInFlight.current = true;
    setDeps(prev => ({ ...prev, skill_market: { ...prev.skill_market, loading: true } }));
    try {
      await api.installSkillMarket();
      const updated = await withTimeout(api.checkSkillMarket());
      setDeps(prev => ({ ...prev, skill_market: { status: updated ?? prev.skill_market.status, loading: false } }));
      if (updated?.installed) toast.success('技能市场已自动更新');
    } catch (reason) {
      console.warn('技能市场自动更新失败，可稍后手动重试:', reason);
      setDeps(prev => ({ ...prev, skill_market: { ...prev.skill_market, loading: false } }));
    } finally {
      manualActionInFlight.current = false;
      sessionStorage.removeItem('dependencyStatus');
    }
  };

  // Each check updates its own row as soon as it finishes — a slow check
  // (e.g. a slow CLI version probe) must not hide
  // the whole bar or block the other rows.
  const runParallelCheck = async () => {
    if (checkInFlight.current) return; // a round is already running — don't stack
    checkInFlight.current = true;
    const epoch = ++checkEpoch.current;
    setChecking(true);
    try {
      const checks: Array<{ key: string; fn: () => Promise<DependencyStatus> }> = [
        { key: 'nodejs', fn: api.checkNodejs },
        { key: 'git', fn: api.checkGitbash },
        { key: 'claude', fn: api.checkClaude },
        { key: 'codex', fn: api.checkCodex },
        { key: 'skill_market', fn: api.checkSkillMarket },
      ];
      const results: Record<string, DependencyStatus | null> = {};
      await Promise.all(checks.map(async ({ key, fn }) => {
        const status = await withTimeout(fn()).catch(() => null);
        results[key] = status;
        if (checkEpoch.current !== epoch) return; // newer round started — drop stale result
        // null = no result this round; keep any prior status rather than
        // regressing the row back to "checking…".
        setDeps(prev => prev[key].loading ? prev : ({ ...prev, [key]: { status: status ?? prev[key].status, loading: false } }));
      }));

      // Auto-expand only if a *required* dep is missing. skill-market is best-effort
      // and shouldn't force the panel open if just it is missing.
      const hasMissing = ['nodejs', 'git', 'claude', 'codex'].some(k => results[k] && !results[k]!.installed);
      if (hasMissing) setExpanded(true);

      sessionStorage.setItem('dependencyStatus', JSON.stringify({
        nodejs: results.nodejs,
        gitbash: results.git,
        claude: results.claude,
        codex: results.codex,
        skill_market: results.skill_market,
      }));
    } catch (error) {
      console.error('检测失败:', error);
    } finally {
      if (checkEpoch.current === epoch) {
        checkInFlight.current = false;
        setChecking(false);
        setCheckDone(true);
      }
    }
  };

  // silent=true runs in the background without flipping the UI into "检测中"
  const checkWithUpdates = async (silent = false) => {
    if (checkInFlight.current) return; // a round is already running — don't stack
    checkInFlight.current = true;
    const epoch = ++checkEpoch.current;
    try {
      if (!silent) {
        sessionStorage.removeItem('dependencyStatus');
        setChecking(true);
      }
      // Bounded like every other await in the guarded region: refresh_system_path
      // is registry I/O on Windows (no-op on macOS), but wrapping it guarantees a
      // stuck invoke can never strand checkInFlight and freeze all future checks.
      await withTimeout(api.refreshSystemPath());
      const checks: Array<{ key: string; fn: () => Promise<DependencyStatus> }> = [
        { key: 'nodejs', fn: api.checkNodejsWithUpdate },
        { key: 'git', fn: api.checkGitbashWithUpdate },
        { key: 'claude', fn: api.checkClaudeWithUpdate },
        { key: 'codex', fn: api.checkCodexWithUpdate },
        { key: 'skill_market', fn: api.checkSkillMarketWithUpdate },
      ];
      await Promise.all(checks.map(async ({ key, fn }) => {
        const status = await withTimeout(fn()).catch(() => null);
        if (checkEpoch.current !== epoch) return; // newer round started — drop stale result
        // null = couldn't fetch update info (timeout/offline); keep the prior
        // local status (no badge) — treat as "no new version", never error or stick.
        setDeps(prev => prev[key].loading ? prev : ({ ...prev, [key]: { status: status ?? prev[key].status, loading: false } }));
        if (key === 'skill_market') autoUpdateSkillMarket(status);
      }));

      // Cache the merged snapshot (reading latest state inside the updater)
      setDeps(prev => {
        sessionStorage.setItem('dependencyStatus', JSON.stringify({
          nodejs: prev.nodejs.status,
          gitbash: prev.git.status,
          claude: prev.claude.status,
          codex: prev.codex.status,
          skill_market: prev.skill_market.status,
          __withUpdates: true,
        }));
        return prev;
      });

      // CLI updates always require an explicit action button.
    } catch (error) {
      console.error('检测失败:', error);
    } finally {
      if (checkEpoch.current === epoch) {
        checkInFlight.current = false;
        setCheckDone(true);
        if (!silent) setChecking(false);
      }
    }
  };

  const handleAction = async (key: string, action: 'install' | 'update' | 'reinstall') => {
    if (manualActionInFlight.current) {
      toast.info('已有安装或更新正在执行，请等待完成后再操作');
      return;
    }
    manualActionInFlight.current = true;
    sessionStorage.removeItem('dependencyStatus');
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
      // Windows CLI actions now wait for the terminal and actual startup check.
      // Other platform/system installers still only open a terminal.
      const verifiedCli = platform === 'windows' && (key === 'claude' || key === 'codex');
      if (!verifiedCli && key !== 'skill_market') toast.info('已打开安装窗口，完成后请点击重新检测');
      const result = await withTimeout(config.checkFn());
      setDeps(prev => ({ ...prev, [key]: { status: result ?? prev[key].status, loading: false } }));
      if (verifiedCli) {
        if (result?.installed && result.meets_requirement && !result.error) {
          toast.success(`${config.label} 安装及启动验证成功`);
        } else {
          toast.error(`${config.label} 尚未通过启动验证，请查看安装日志`);
        }
      } else if (key === 'skill_market' && result?.installed) {
        toast.success('技能市场已安装或更新');
      }
    } catch (error: any) {
      toast.error(`操作失败: ${error}`);
      setDeps(prev => ({ ...prev, [key]: { ...prev[key], loading: false } }));
    } finally {
      manualActionInFlight.current = false;
      sessionStorage.removeItem('dependencyStatus');
    }
  };

  // Check if any issues exist. The bar is always rendered — rows fill in as
  // each check finishes, so users see progress and keep the manual entry.
  const hasIssues = Object.values(deps).some(d => d.status && (!d.status.installed || d.status.update_available || !!d.status.error));
  const isInstalling = Object.values(deps).some(d => d.loading);

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
              onClick={() => checkWithUpdates()}
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
              : !d.status.installed || d.status.error?.startsWith('REPAIR_REQUIRED:')
              ? 'dot dot-error'
              : d.status.update_available
              ? 'dot dot-warn'
              : 'dot dot-ok';
            const needsRepair = (key === 'claude' || key === 'codex')
              && !!d.status?.error?.startsWith('REPAIR_REQUIRED:');
            const canReinstall = (key === 'claude' || key === 'codex') && d.status?.installed;
            const isSkillMarket = key === 'skill_market';
            return (
              <div key={key} className="flex items-center gap-2.5 min-w-0">
                <span className={`${dotClass} ${d.loading ? 'dot-pulse' : ''}`} />
                <span className={`text-[12px] text-text-primary flex-shrink-0 ${isSkillMarket ? '' : 'w-20'}`}>
                  {config.label}
                  {isSkillMarket && (
                    <>
                      {' '}
                      <button
                        type="button"
                        onClick={(e) => { e.stopPropagation(); openUrl(SKILL_MARKET_URL).catch(() => {}); }}
                        className="text-[10.5px] text-info hover:brightness-125 underline underline-offset-2"
                        title="在浏览器打开 Webank 技能市场"
                      >
                        (跳转)
                      </button>
                    </>
                  )}
                </span>
                {!d.status ? (
                  <span className="font-mono text-[10.5px] text-text-tertiary">
                    {checkDone ? '未检测到' : 'checking…'}
                  </span>
                ) : needsRepair ? (
                  <>
                    <span
                      className="font-mono text-[10.5px] text-error/90"
                      title={d.status.error?.replace('REPAIR_REQUIRED:', '')}
                    >
                      需要修复
                    </span>
                    {!d.loading && (
                      <button onClick={() => handleAction(key, 'reinstall')} className="btn btn-secondary btn-sm ml-auto">
                        重装
                      </button>
                    )}
                  </>
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
