import { useState, useEffect, useRef } from 'react';
import { api } from '../api';
import type { DependencyStatus } from '../types';

type StepStatus = 'pending' | 'running' | 'done' | 'error' | 'skipped';

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

  const updateStep = (index: number, update: Partial<Step>) => {
    setSteps(prev => prev.map((s, i) => (i === index ? { ...s, ...update } : s)));
  };

  const waitForInstall = async (
    checkFn: () => Promise<DependencyStatus>,
    maxAttempts = 60
  ): Promise<DependencyStatus | null> => {
    for (let i = 0; i < maxAttempts; i++) {
      await new Promise(r => setTimeout(r, 3000));
      try {
        await api.refreshSystemPath();
        const result = await checkFn();
        if (result.installed) return result;
      } catch {}
    }
    return null;
  };

  const runSetup = async () => {
    setIsRunning(true);

    // Step 0: Node.js
    updateStep(0, { status: 'running' });
    try {
      const node = await api.checkNodejs();
      if (node.installed) {
        updateStep(0, { status: 'done', detail: node.version || undefined });
      } else {
        updateStep(0, { status: 'running', detail: '正在打开安装程序...' });
        setWaitingInstall('Node.js');
        await api.installNodejs();
        updateStep(0, { detail: '等待安装完成...' });
        const result = await waitForInstall(api.checkNodejs);
        setWaitingInstall(null);
        if (result) {
          updateStep(0, { status: 'done', detail: result.version || undefined });
        } else {
          updateStep(0, { status: 'error', detail: '安装超时，请手动安装后重试' });
          setIsRunning(false);
          return;
        }
      }
    } catch (err: any) {
      updateStep(0, { status: 'error', detail: err?.toString() });
      setIsRunning(false);
      return;
    }

    // Step 1: Git
    updateStep(1, { status: 'running' });
    try {
      const git = await api.checkGitbash();
      if (git.installed) {
        updateStep(1, { status: 'done', detail: git.version || undefined });
      } else {
        updateStep(1, { status: 'running', detail: '正在打开安装程序...' });
        setWaitingInstall('Git');
        await api.installGitbash();
        updateStep(1, { detail: '等待安装完成...' });
        const result = await waitForInstall(api.checkGitbash);
        setWaitingInstall(null);
        if (result) {
          updateStep(1, { status: 'done', detail: result.version || undefined });
        } else {
          updateStep(1, { status: 'error', detail: '安装超时，请手动安装后重试' });
          setIsRunning(false);
          return;
        }
      }
    } catch (err: any) {
      updateStep(1, { status: 'error', detail: err?.toString() });
      setIsRunning(false);
      return;
    }

    // Step 2: Claude Code
    updateStep(2, { status: 'running', detail: '正在检测...' });
    try {
      const claude = await api.checkClaude();
      if (claude.installed) {
        updateStep(2, { status: 'done', detail: claude.version || undefined });
      } else {
        updateStep(2, { status: 'running', detail: '正在打开安装程序...' });
        setWaitingInstall('Claude Code');
        await api.installClaude();
        updateStep(2, { detail: '等待安装完成...' });
        const result = await waitForInstall(api.checkClaude);
        setWaitingInstall(null);
        if (result) {
          updateStep(2, { status: 'done', detail: result.version || undefined });
        } else {
          updateStep(2, { status: 'error', detail: '安装超时，请手动安装后重试' });
          setIsRunning(false);
          return;
        }
      }
    } catch (err: any) {
      updateStep(2, { status: 'error', detail: err?.toString() });
      setIsRunning(false);
      return;
    }

    // Step 3: Codex
    updateStep(3, { status: 'running', detail: '正在检测...' });
    try {
      const codex = await api.checkCodex();
      if (codex.installed) {
        updateStep(3, { status: 'done', detail: codex.version || undefined });
      } else {
        updateStep(3, { status: 'running', detail: '正在打开安装程序...' });
        setWaitingInstall('Codex');
        await api.installCodex();
        updateStep(3, { detail: '等待安装完成...' });
        const result = await waitForInstall(api.checkCodex);
        setWaitingInstall(null);
        if (result) {
          updateStep(3, { status: 'done', detail: result.version || undefined });
        } else {
          updateStep(3, { status: 'error', detail: '安装超时，请手动安装后重试' });
          setIsRunning(false);
          return;
        }
      }
    } catch (err: any) {
      updateStep(3, { status: 'error', detail: err?.toString() });
      setIsRunning(false);
      return;
    }

    // All done - mark setup complete
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
          <div className="text-center text-[12px] text-[#6b9fff] animate-pulse">
            请完成 {waitingInstall} 安装程序，安装后将自动继续...
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
