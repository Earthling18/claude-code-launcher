import { useState, useEffect, useRef } from 'react';
import { motion } from 'framer-motion';
import { api } from '../api';
import type { DependencyStatus } from '../types';

type StepStatus = 'pending' | 'running' | 'done' | 'error' | 'skipped';
type SkipSignal = 'current' | 'all' | null;

interface Step {
  label: string;
  status: StepStatus;
  detail?: string;
}

interface LocalSetupWizardProps {
  onComplete: () => void;
}

export const LocalSetupWizard: React.FC<LocalSetupWizardProps> = ({ onComplete }) => {
  const [steps, setSteps] = useState<Step[]>([
    { label: 'Node.js', status: 'pending' },
    { label: 'Git', status: 'pending' },
    { label: 'Claude Code', status: 'pending' },
    { label: 'Codex', status: 'pending' },
    { label: 'Webank 技能市场', status: 'pending' },
  ]);
  const [isRunning, setIsRunning] = useState(false);
  const [waitingInstall, setWaitingInstall] = useState<string | null>(null);
  const hasStarted = useRef(false);
  const skipSignalRef = useRef<SkipSignal>(null);

  const updateStep = (index: number, update: Partial<Step>) => {
    setSteps(prev => prev.map((s, i) => (i === index ? { ...s, ...update } : s)));
  };

  const waitForInstall = async (
    checkFn: () => Promise<DependencyStatus>,
    maxAttempts = 60
  ): Promise<{ result: DependencyStatus | null; skipped: SkipSignal }> => {
    for (let i = 0; i < maxAttempts; i++) {
      if (skipSignalRef.current) return { result: null, skipped: skipSignalRef.current };
      await new Promise(r => setTimeout(r, 3000));
      if (skipSignalRef.current) return { result: null, skipped: skipSignalRef.current };
      try {
        await api.refreshSystemPath();
        const result = await checkFn();
        if (result.installed) return { result, skipped: null };
      } catch {}
    }
    return { result: null, skipped: null };
  };

  const runSetup = async () => {
    setIsRunning(true);
    skipSignalRef.current = null;

    type StepDef = {
      index: number;
      label: string;
      check: () => Promise<DependencyStatus>;
      install: () => Promise<unknown>;
      /** When true, install runs silently (no terminal) and resolves on success/failure
          right away. Failures are silenced as 'skipped' rather than 'error' so the wizard
          completes even when the resource is unreachable (intranet-only). */
      silent?: boolean;
    };

    const stepDefs: StepDef[] = [
      { index: 0, label: 'Node.js',     check: api.checkNodejs,  install: api.installNodejs },
      { index: 1, label: 'Git',         check: api.checkGitbash, install: api.installGitbash },
      { index: 2, label: 'Claude Code', check: api.checkClaude,  install: api.installClaude },
      { index: 3, label: 'Codex',       check: api.checkCodex,   install: api.installCodex },
      { index: 4, label: 'Webank 技能市场', check: api.checkSkillMarket, install: api.installSkillMarket, silent: true },
    ];

    const finishWithSkipAll = (fromIndex: number) => {
      setSteps(prev =>
        prev.map((s, i) =>
          i >= fromIndex && (s.status === 'pending' || s.status === 'running')
            ? { ...s, status: 'skipped', detail: '已跳过' }
            : s
        )
      );
      setWaitingInstall(null);
      setIsRunning(false);
      localStorage.setItem('local_deps_ok', '1');
      onComplete();
    };

    for (const def of stepDefs) {
      if (skipSignalRef.current === 'all') {
        finishWithSkipAll(def.index);
        return;
      }

      updateStep(def.index, { status: 'running', detail: '检测中…' });

      try {
        const status = await def.check();
        if (status.installed) {
          updateStep(def.index, { status: 'done', detail: status.version || '已就绪' });
          continue;
        }

        // Silent install path: no terminal, in-process; on failure mark skipped and continue.
        if (def.silent) {
          updateStep(def.index, { status: 'running', detail: '安装中…' });
          try {
            await def.install();
            const recheck = await def.check();
            if (recheck.installed) {
              updateStep(def.index, { status: 'done', detail: recheck.version || '已就绪' });
            } else {
              updateStep(def.index, { status: 'skipped', detail: '已跳过（未检测到安装）' });
            }
          } catch (e: any) {
            // Network unreachable / timeout / extract failed — best-effort, just skip.
            const msg = String(e || '').toLowerCase();
            const isTimeout = msg.includes('timeout') || msg.includes('timed out');
            updateStep(def.index, { status: 'skipped', detail: isTimeout ? '已跳过（超时）' : '已跳过' });
          }
          continue;
        }

        updateStep(def.index, { status: 'running', detail: '正在打开安装程序…' });
        setWaitingInstall(def.label);
        await def.install();
        updateStep(def.index, { detail: '等待安装完成…' });

        const { result, skipped } = await waitForInstall(def.check);
        setWaitingInstall(null);

        if (skipped === 'all') {
          updateStep(def.index, { status: 'skipped', detail: '已跳过' });
          finishWithSkipAll(def.index + 1);
          return;
        }
        if (skipped === 'current') {
          updateStep(def.index, { status: 'skipped', detail: '已跳过' });
          skipSignalRef.current = null;
          continue;
        }
        if (result) {
          updateStep(def.index, { status: 'done', detail: result.version || '已就绪' });
        } else {
          updateStep(def.index, { status: 'error', detail: '安装超时，请手动安装后重试' });
          setIsRunning(false);
          return;
        }
      } catch (err: any) {
        setWaitingInstall(null);
        updateStep(def.index, { status: 'error', detail: err?.toString() });
        setIsRunning(false);
        return;
      }
    }

    setIsRunning(false);
    localStorage.setItem('local_deps_ok', '1');
    onComplete();
  };

  useEffect(() => {
    if (hasStarted.current) return;
    hasStarted.current = true;
    runSetup();
  }, []);

  const hasError = steps.some(s => s.status === 'error');
  const completedCount = steps.filter(s => s.status === 'done' || s.status === 'skipped').length;
  const progress = (completedCount / steps.length) * 100;

  return (
    <div className="h-full flex items-center justify-center px-6">
      <div className="w-full max-w-md">
        {/* Header */}
        <div className="text-center mb-6">
          <div className="font-mono text-[10px] uppercase tracking-[0.22em] text-text-tertiary mb-1.5">
            FIRST RUN · 环境配置
          </div>
          <h2 className="text-[18px] font-semibold text-text-primary mb-1.5">为 CC 启动器准备依赖</h2>
          <p className="text-[12px] text-text-tertiary leading-relaxed">
            如果 Node 和 Git 安装失败，可前往软件管家自行下载
          </p>
        </div>

        {/* Progress bar */}
        <div className="mb-6">
          <div className="flex items-center justify-between mb-1.5">
            <span className="font-mono text-[10px] uppercase tracking-[0.18em] text-text-tertiary">
              进度
            </span>
            <span className="font-mono text-[10.5px] text-text-secondary">
              {completedCount} / {steps.length}
            </span>
          </div>
          <div className="h-1 bg-surface-1 rounded-full overflow-hidden border border-line">
            <motion.div
              className="h-full bg-accent"
              initial={{ width: 0 }}
              animate={{ width: `${progress}%` }}
              transition={{ duration: 0.5, ease: [0.2, 0.8, 0.2, 1] }}
            />
          </div>
        </div>

        {/* Steps */}
        <div className="space-y-1.5 mb-5">
          {steps.map((step, i) => (
            <StepRow key={i} step={step} />
          ))}
        </div>

        {/* Status of current install */}
        {waitingInstall && (
          <div className="mt-5 p-3 bg-surface-1 border border-line rounded space-y-2">
            <div className="text-center">
              <span className="font-mono text-[10px] uppercase tracking-[0.18em] text-accent">
                INSTALLING
              </span>
            </div>
            <div className="text-center text-[12.5px] text-text-primary">
              请完成 <strong className="text-accent font-semibold">{waitingInstall}</strong> 安装程序
            </div>
            <div className="text-center text-[11px] text-text-tertiary leading-snug">
              检测到安装完成将自动继续
            </div>
          </div>
        )}

        {/* Skip controls — visible whenever wizard is actively running.
            "跳过此项" only enabled while a current install is being awaited. */}
        {isRunning && !hasError && (
          <div className="flex justify-center gap-3 pt-3">
            <button
              type="button"
              onClick={() => { if (waitingInstall) skipSignalRef.current = 'current'; }}
              disabled={!waitingInstall}
              className="text-[11px] text-text-tertiary hover:text-text-primary underline-offset-2 hover:underline transition-colors disabled:opacity-40 disabled:cursor-not-allowed disabled:no-underline"
            >
              跳过此项
            </button>
            <span className="text-text-disabled text-[11px]">·</span>
            <button
              type="button"
              onClick={() => { skipSignalRef.current = 'all'; }}
              className="text-[11px] text-text-tertiary hover:text-text-primary underline-offset-2 hover:underline transition-colors"
            >
              全部跳过
            </button>
          </div>
        )}

        {/* Error state */}
        {hasError && !isRunning && (
          <div className="flex justify-center gap-2 mt-5">
            <button
              onClick={() => {
                hasStarted.current = false;
                setSteps(steps.map(s => ({ ...s, status: 'pending', detail: undefined })));
                hasStarted.current = true;
                runSetup();
              }}
              className="btn btn-primary"
            >
              重试
            </button>
            <button
              onClick={() => {
                localStorage.setItem('local_deps_ok', '1');
                onComplete();
              }}
              className="btn btn-secondary"
            >
              跳过
            </button>
          </div>
        )}
      </div>
    </div>
  );
};

const StepRow: React.FC<{ step: Step }> = ({ step }) => {
  const { status, label, detail } = step;
  return (
    <motion.div
      initial={{ opacity: 0, x: -4 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ duration: 0.2 }}
      className={[
        'flex items-center gap-3 px-3 py-2.5 rounded border transition-colors',
        status === 'running' ? 'border-accent/40 bg-accent/[0.04]'
        : status === 'done' ? 'border-line bg-surface-1'
        : status === 'error' ? 'border-error/40 bg-error/[0.04]'
        : status === 'skipped' ? 'border-line bg-transparent opacity-60'
        : 'border-line bg-surface-1',
      ].join(' ')}
    >
      <StatusIcon status={status} />
      <span className="text-[12.5px] font-medium text-text-primary flex-1">{label}</span>
      {detail && (
        <span className={`font-mono text-[10.5px] ${
          status === 'error' ? 'text-error'
          : status === 'done' ? 'text-text-tertiary'
          : status === 'running' ? 'text-accent'
          : 'text-text-tertiary'
        }`}>
          {detail}
        </span>
      )}
    </motion.div>
  );
};

const StatusIcon: React.FC<{ status: StepStatus }> = ({ status }) => {
  const base = 'w-5 h-5 rounded-full flex items-center justify-center flex-shrink-0';
  switch (status) {
    case 'pending':
      return (
        <span className={`${base} border border-line-strong`}>
          <span className="dot" style={{ background: 'var(--text-disabled)' }} />
        </span>
      );
    case 'running':
      return (
        <span className={`${base} border border-accent/50 relative`}>
          <span className="absolute inset-0 rounded-full border-2 border-accent border-t-transparent animate-spin" />
        </span>
      );
    case 'done':
      return (
        <span className={`${base}`} style={{ background: 'rgba(107, 191, 122, 0.12)', border: '1px solid rgba(107, 191, 122, 0.4)' }}>
          <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="var(--ok)" strokeWidth="3.2" strokeLinecap="round" strokeLinejoin="round">
            <polyline points="20 6 9 17 4 12" />
          </svg>
        </span>
      );
    case 'error':
      return (
        <span className={`${base}`} style={{ background: 'rgba(214, 114, 110, 0.12)', border: '1px solid rgba(214, 114, 110, 0.4)' }}>
          <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="var(--error)" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
            <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
          </svg>
        </span>
      );
    case 'skipped':
      return (
        <span className={`${base} border border-line-strong`}>
          <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="var(--text-tertiary)" strokeWidth="2.5" strokeLinecap="round"><line x1="5" y1="12" x2="19" y2="12"/></svg>
        </span>
      );
  }
};
