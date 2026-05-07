import { useState, useEffect, useRef } from 'react';
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
  ]);
  const [isRunning, setIsRunning] = useState(false);
  const [waitingInstall, setWaitingInstall] = useState<string | null>(null);
  const hasStarted = useRef(false);
  const skipSignalRef = useRef<SkipSignal>(null);

  const updateStep = (index: number, update: Partial<Step>) => {
    setSteps(prev => prev.map((s, i) => (i === index ? { ...s, ...update } : s)));
  };

  // Returns { result, skipped }: result is the dependency status if it became installed,
  // skipped='current' or 'all' if the user pressed a skip button mid-wait.
  const waitForInstall = async (
    checkFn: () => Promise<DependencyStatus>,
    maxAttempts = 60
  ): Promise<{ result: DependencyStatus | null; skipped: SkipSignal }> => {
    for (let i = 0; i < maxAttempts; i++) {
      if (skipSignalRef.current) {
        return { result: null, skipped: skipSignalRef.current };
      }
      await new Promise(r => setTimeout(r, 3000));
      if (skipSignalRef.current) {
        return { result: null, skipped: skipSignalRef.current };
      }
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
    };

    const stepDefs: StepDef[] = [
      { index: 0, label: 'Node.js',     check: api.checkNodejs,  install: api.installNodejs },
      { index: 1, label: 'Git',         check: api.checkGitbash, install: api.installGitbash },
      { index: 2, label: 'Claude Code', check: api.checkClaude,  install: api.installClaude },
      { index: 3, label: 'Codex',       check: api.checkCodex,   install: api.installCodex },
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

      updateStep(def.index, { status: 'running', detail: '正在检测...' });

      try {
        const status = await def.check();
        if (status.installed) {
          updateStep(def.index, { status: 'done', detail: status.version || undefined });
          continue;
        }

        updateStep(def.index, { status: 'running', detail: '正在打开安装程序...' });
        setWaitingInstall(def.label);
        await def.install();
        updateStep(def.index, { detail: '等待安装完成...' });

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
          updateStep(def.index, { status: 'done', detail: result.version || undefined });
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

  const getIcon = (status: StepStatus) => {
    switch (status) {
      case 'pending': return <span className="w-6 h-6 rounded-full border-2 border-[#565B5E] flex items-center justify-center text-[10px] text-[#565B5E]">-</span>;
      case 'running': return <span className="w-6 h-6 rounded-full border-2 border-[#3b82f6] flex items-center justify-center text-[12px] text-[#3b82f6] animate-spin">&#x27F3;</span>;
      case 'done': return <span className="w-6 h-6 rounded-full bg-[#10b981] flex items-center justify-center text-[10px] text-white">&#x2713;</span>;
      case 'error': return <span className="w-6 h-6 rounded-full bg-red-500 flex items-center justify-center text-[10px] text-white">&#x2717;</span>;
      case 'skipped': return <span className="w-6 h-6 rounded-full bg-[#565B5E] flex items-center justify-center text-[10px] text-white">-</span>;
    }
  };

  return (
    <div className="h-full flex items-center justify-center">
      <div className="max-w-md w-full space-y-6">
        <div className="text-center mb-2">
          <h2 className="text-[16px] font-bold mb-1">环境配置</h2>
          <p className="text-[12px] text-[#999999]">首次使用需要安装依赖，检测到已安装的会自动跳过</p>
        </div>

        <div className="space-y-3">
          {steps.map((step, i) => (
            <div
              key={i}
              className={`flex items-center gap-3 p-3 rounded-lg transition-colors ${
                step.status === 'running'
                  ? 'bg-[#2a2f3a] border border-[#3b82f6]'
                  : step.status === 'done'
                  ? 'bg-[#2a3a2f] border border-[#10b981]/30'
                  : step.status === 'error'
                  ? 'bg-[#3a2a2a] border border-red-500/30'
                  : 'bg-[#2a2a2a] border border-[#3a3a3a]'
              }`}
            >
              {getIcon(step.status)}
              <div className="flex-1 min-w-0">
                <span className="text-[13px] font-medium">{step.label}</span>
                {step.detail && (
                  <span className="text-[11px] text-[#999999] ml-2">{step.detail}</span>
                )}
              </div>
            </div>
          ))}
        </div>

        {waitingInstall && (
          <div className="space-y-2">
            <div className="text-center text-[12px] text-[#6b9fff] animate-pulse">
              请完成 {waitingInstall} 安装程序，安装后将自动继续...
            </div>
            <div className="flex justify-center gap-3">
              <button
                onClick={() => { skipSignalRef.current = 'current'; }}
                className="px-3 py-1 text-[11px] text-[#999999] hover:text-[#DCE4EE] underline-offset-2 hover:underline transition-colors"
              >
                跳过此项
              </button>
              <button
                onClick={() => { skipSignalRef.current = 'all'; }}
                className="px-3 py-1 text-[11px] text-[#999999] hover:text-[#DCE4EE] underline-offset-2 hover:underline transition-colors"
              >
                全部跳过
              </button>
            </div>
            <p className="text-center text-[10px] text-[#666666]">
              网络受限时可跳过 Codex 等耗时项；之后仍可在「项目编辑」内手动配置
            </p>
          </div>
        )}

        {hasError && !isRunning && (
          <div className="flex justify-center gap-3">
            <button
              onClick={() => {
                hasStarted.current = false;
                setSteps(steps.map(s => ({ ...s, status: 'pending', detail: undefined })));
                hasStarted.current = true;
                runSetup();
              }}
              className="px-6 py-2 text-[13px] bg-[#3b82f6] hover:bg-[#2563eb] text-white rounded-lg transition-colors"
            >
              重试
            </button>
            <button
              onClick={() => {
                localStorage.setItem('local_deps_ok', '1');
                onComplete();
              }}
              className="px-6 py-2 text-[13px] bg-[#565B5E] hover:bg-[#7A8488] text-white rounded-lg transition-colors"
            >
              跳过
            </button>
          </div>
        )}
      </div>
    </div>
  );
};
