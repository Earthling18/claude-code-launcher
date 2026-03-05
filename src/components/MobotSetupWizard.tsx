import { useState, useEffect } from 'react';
import { mobotApi } from '../api';

type StepStatus = 'pending' | 'running' | 'done' | 'error';

interface Step {
  label: string;
  description: string;
  status: StepStatus;
  error?: string;
}

interface MobotSetupWizardProps {
  onComplete: (bridgePath: string, pythonPath: string) => void;
  onCancel: () => void;
}

export const MobotSetupWizard: React.FC<MobotSetupWizardProps> = ({
  onComplete,
  onCancel,
}) => {
  const [steps, setSteps] = useState<Step[]>([
    { label: '检测 Python', description: '检测系统 Python 3.10+', status: 'pending' },
    { label: '释放 mobot-bridge', description: '将 mobot-bridge 安装到本地目录', status: 'pending' },
    { label: '安装依赖', description: '安装 Python 依赖包 (pip install)', status: 'pending' },
    { label: '启动服务', description: '启动 mobot-bridge 服务并等待就绪', status: 'pending' },
  ]);
  const [currentStep, setCurrentStep] = useState(-1);
  const [isRunning, setIsRunning] = useState(false);
  const [logs, setLogs] = useState<string[]>([]);

  const addLog = (msg: string) => {
    setLogs((prev) => [...prev.slice(-50), msg]);
  };

  const updateStep = (index: number, update: Partial<Step>) => {
    setSteps((prev) => prev.map((s, i) => (i === index ? { ...s, ...update } : s)));
  };

  const startInstall = async () => {
    setIsRunning(true);
    setLogs([]);

    try {
      // Step 0: Detect Python
      setCurrentStep(0);
      updateStep(0, { status: 'running' });
      addLog('正在检测系统 Python...');

      const python = await mobotApi.detectPython();
      if (!python) {
        updateStep(0, { status: 'error', error: '未找到 Python 3.10+' });
        addLog('错误: 未找到 Python 3.10+，请先安装');
        addLog('macOS: brew install python@3.12');
        addLog('Windows: 从 python.org 下载安装');
        setIsRunning(false);
        return;
      }
      updateStep(0, { status: 'done' });
      addLog(`找到 Python: ${python}`);

      // Step 1: Install mobot-bridge
      setCurrentStep(1);
      updateStep(1, { status: 'running' });
      addLog('正在释放 mobot-bridge 文件...');

      const installPath = await mobotApi.install();
      updateStep(1, { status: 'done' });
      addLog(`mobot-bridge 已安装到: ${installPath}`);

      // Step 2: Install dependencies
      setCurrentStep(2);
      updateStep(2, { status: 'running' });
      addLog('正在安装 Python 依赖包，请稍候...');

      // installDeps returns the python path to use (venv python on macOS/Linux)
      const servicePython = await mobotApi.installDeps(installPath, python);
      updateStep(2, { status: 'done' });
      addLog('依赖安装完成');

      // Step 3: Start service
      setCurrentStep(3);
      updateStep(3, { status: 'running' });
      addLog('正在启动 mobot-bridge 服务...');

      const pid = await mobotApi.startService(installPath, servicePython, 8000);
      addLog(`服务已启动, PID: ${pid}`);

      // Wait for health check
      addLog('等待服务就绪...');
      let healthy = false;
      for (let i = 0; i < 15; i++) {
        await new Promise((r) => setTimeout(r, 2000));
        const health = await mobotApi.checkHealth(8000);
        if (health.healthy) {
          healthy = true;
          break;
        }
        addLog(`等待服务就绪... (${i + 1}/15)`);
      }

      if (healthy) {
        updateStep(3, { status: 'done' });
        addLog('mobot-bridge 服务已就绪!');
        onComplete(installPath, python);
      } else {
        updateStep(3, { status: 'error', error: '服务启动超时，请检查日志' });
        addLog('警告: 服务未在预期时间内就绪，但已启动');
        // Still call onComplete since the service is running
        onComplete(installPath, python);
      }
    } catch (err: any) {
      const errorMsg = err?.toString() || '未知错误';
      addLog(`错误: ${errorMsg}`);
      if (currentStep >= 0) {
        updateStep(currentStep, { status: 'error', error: errorMsg });
      }
    } finally {
      setIsRunning(false);
    }
  };

  // Auto-start on mount
  useEffect(() => {
    startInstall();
  }, []);

  const getStepIcon = (status: StepStatus) => {
    switch (status) {
      case 'pending':
        return <span className="w-6 h-6 rounded-full border-2 border-[#565B5E] flex items-center justify-center text-[10px] text-[#565B5E]">-</span>;
      case 'running':
        return <span className="w-6 h-6 rounded-full border-2 border-[#3b82f6] flex items-center justify-center animate-spin text-[10px] text-[#3b82f6]">⟳</span>;
      case 'done':
        return <span className="w-6 h-6 rounded-full bg-[#10b981] flex items-center justify-center text-[10px] text-white">✓</span>;
      case 'error':
        return <span className="w-6 h-6 rounded-full bg-red-500 flex items-center justify-center text-[10px] text-white">✗</span>;
    }
  };

  const hasError = steps.some((s) => s.status === 'error');

  return (
    <div className="space-y-6">
      <div className="text-center mb-2">
        <h2 className="text-[16px] font-bold mb-1">安装 Mobot Bridge</h2>
        <p className="text-[12px] text-[#999999]">首次使用需要安装，通常需要 1-3 分钟</p>
      </div>

      {/* Steps */}
      <div className="space-y-3">
        {steps.map((step, i) => (
          <div
            key={i}
            className={`flex items-start gap-3 p-3 rounded-lg transition-colors ${
              i === currentStep
                ? 'bg-[#2a2f3a] border border-[#3b82f6]'
                : step.status === 'done'
                ? 'bg-[#2a3a2f] border border-[#10b981]/30'
                : step.status === 'error'
                ? 'bg-[#3a2a2a] border border-red-500/30'
                : 'bg-[#2a2a2a] border border-[#3a3a3a]'
            }`}
          >
            {getStepIcon(step.status)}
            <div className="flex-1 min-w-0">
              <div className="text-[13px] font-medium">{step.label}</div>
              <div className="text-[11px] text-[#999999]">{step.description}</div>
              {step.error && (
                <div className="text-[11px] text-red-400 mt-1">{step.error}</div>
              )}
            </div>
          </div>
        ))}
      </div>

      {/* Logs */}
      {logs.length > 0 && (
        <div className="bg-[#1a1a1a] border border-[#3a3a3a] rounded-lg p-3 max-h-40 overflow-y-auto font-mono">
          {logs.map((line, i) => (
            <div key={i} className="text-[10px] text-[#cccccc] leading-relaxed">
              {line}
            </div>
          ))}
        </div>
      )}

      {/* Buttons */}
      {hasError && !isRunning && (
        <div className="flex items-center gap-3 justify-center">
          <button
            onClick={startInstall}
            className="px-6 py-2 text-[13px] bg-[#3b82f6] hover:bg-[#2563eb] text-white rounded-lg transition-colors"
          >
            重试
          </button>
          <button
            onClick={onCancel}
            className="px-6 py-2 text-[13px] bg-[#565B5E] hover:bg-[#7A8488] text-white rounded-lg transition-colors"
          >
            返回
          </button>
        </div>
      )}
    </div>
  );
};
