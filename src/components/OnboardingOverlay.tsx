import { useState, useEffect, useCallback } from 'react';

interface OnboardingStep {
  id: string;
  title: string;
  description: string;
  targetSelector?: string;
  position?: 'center' | 'top' | 'bottom' | 'left' | 'right';
}

const ONBOARDING_STEPS: OnboardingStep[] = [
  {
    id: 'welcome',
    title: '欢迎使用 CC 启动器',
    description: '这是一个帮助您管理和启动 Claude Code 项目的工具。接下来让我们快速了解主要功能。',
    position: 'center',
  },
  {
    id: 'dependencies',
    title: '依赖检测',
    description: '这里显示运行 Claude Code 所需的依赖状态。如果显示未安装，点击对应按钮可一键安装或更新。',
    targetSelector: '[data-onboarding="dependencies"]',
    position: 'bottom',
  },
  {
    id: 'default-project',
    title: '默认项目',
    description: '这是系统自带的默认项目，工作目录为您的用户主目录。\n\n⚠️ 首次使用请先点击右上角的编辑图标配置模型！\n\n您可以选择使用 Claude 原版（需代理）或切换到自定义模型（如内部 API）。',
    targetSelector: '[data-onboarding="default-project"]',
    position: 'bottom',
  },
  {
    id: 'create',
    title: '新建项目',
    description: '有两种方式创建新项目：\n1. 直接将文件夹拖入窗口\n2. 点击"+ 新建项目"按钮手动创建',
    targetSelector: '[data-onboarding="create-btn"]',
    position: 'bottom',
  },
  {
    id: 'launch',
    title: '启动项目',
    description: '点击"启动"按钮直接在新窗口运行 Claude Code。也可以点击"复制PS/CMD"按钮复制启动命令，自己在终端中执行。',
    targetSelector: '[data-onboarding="launch-buttons"]',
    position: 'top',
  },
  {
    id: 'finish',
    title: '开始使用吧！',
    description: '现在您已了解基本功能。如需再次查看引导，可点击右下角的帮助按钮。',
    position: 'center',
  },
];

interface OnboardingOverlayProps {
  onComplete: () => void;
}

interface TargetRect {
  top: number;
  left: number;
  width: number;
  height: number;
}

export const OnboardingOverlay: React.FC<OnboardingOverlayProps> = ({ onComplete }) => {
  const [currentStep, setCurrentStep] = useState(0);
  const [targetRect, setTargetRect] = useState<TargetRect | null>(null);

  const step = ONBOARDING_STEPS[currentStep];
  const isFirstStep = currentStep === 0;
  const isLastStep = currentStep === ONBOARDING_STEPS.length - 1;

  const updateTargetRect = useCallback(() => {
    if (step.targetSelector) {
      const element = document.querySelector(step.targetSelector);
      if (element) {
        const rect = element.getBoundingClientRect();
        setTargetRect({
          top: rect.top,
          left: rect.left,
          width: rect.width,
          height: rect.height,
        });
      } else {
        setTargetRect(null);
      }
    } else {
      setTargetRect(null);
    }
  }, [step.targetSelector]);

  useEffect(() => {
    updateTargetRect();

    // Update on window resize
    window.addEventListener('resize', updateTargetRect);
    return () => window.removeEventListener('resize', updateTargetRect);
  }, [updateTargetRect]);

  const handleNext = () => {
    if (isLastStep) {
      onComplete();
    } else {
      setCurrentStep(prev => prev + 1);
    }
  };

  const handlePrev = () => {
    if (!isFirstStep) {
      setCurrentStep(prev => prev - 1);
    }
  };

  const handleSkip = () => {
    onComplete();
  };

  // Calculate tooltip position based on target element and preferred position
  const getTooltipStyle = (): React.CSSProperties => {
    if (!targetRect || step.position === 'center') {
      // Center position
      return {
        position: 'fixed',
        top: '50%',
        left: '50%',
        transform: 'translate(-50%, -50%)',
      };
    }

    const padding = 16;
    const tooltipWidth = 360;
    const tooltipHeight = 200; // estimated

    let top: number;
    let left: number;

    switch (step.position) {
      case 'bottom':
        top = targetRect.top + targetRect.height + padding;
        left = targetRect.left + targetRect.width / 2 - tooltipWidth / 2;
        break;
      case 'top':
        top = targetRect.top - tooltipHeight - padding;
        left = targetRect.left + targetRect.width / 2 - tooltipWidth / 2;
        break;
      case 'left':
        top = targetRect.top + targetRect.height / 2 - tooltipHeight / 2;
        left = targetRect.left - tooltipWidth - padding;
        break;
      case 'right':
        top = targetRect.top + targetRect.height / 2 - tooltipHeight / 2;
        left = targetRect.left + targetRect.width + padding;
        break;
      default:
        top = targetRect.top + targetRect.height + padding;
        left = targetRect.left + targetRect.width / 2 - tooltipWidth / 2;
    }

    // Keep tooltip within viewport
    const viewportWidth = window.innerWidth;
    const viewportHeight = window.innerHeight;

    if (left < padding) left = padding;
    if (left + tooltipWidth > viewportWidth - padding) {
      left = viewportWidth - tooltipWidth - padding;
    }
    if (top < padding) top = padding;
    if (top + tooltipHeight > viewportHeight - padding) {
      top = viewportHeight - tooltipHeight - padding;
    }

    return {
      position: 'fixed',
      top: `${top}px`,
      left: `${left}px`,
    };
  };

  // Generate clip-path for spotlight effect
  const getOverlayStyle = (): React.CSSProperties => {
    if (!targetRect) {
      return {};
    }

    const padding = 8;
    const borderRadius = 8;
    const x = targetRect.left - padding;
    const y = targetRect.top - padding;
    const w = targetRect.width + padding * 2;
    const h = targetRect.height + padding * 2;

    // Create a rounded rectangle cutout using clip-path
    // The clip-path creates the inverse (everything except the spotlight)
    const clipPath = `
      polygon(
        0% 0%,
        0% 100%,
        ${x}px 100%,
        ${x}px ${y + borderRadius}px,
        ${x + borderRadius}px ${y}px,
        ${x + w - borderRadius}px ${y}px,
        ${x + w}px ${y + borderRadius}px,
        ${x + w}px ${y + h - borderRadius}px,
        ${x + w - borderRadius}px ${y + h}px,
        ${x + borderRadius}px ${y + h}px,
        ${x}px ${y + h - borderRadius}px,
        ${x}px 100%,
        100% 100%,
        100% 0%
      )
    `;

    return { clipPath };
  };

  return (
    <div className="fixed inset-0 z-[100]">
      {/* Dark overlay with spotlight cutout */}
      <div
        className="absolute inset-0 bg-black/70 transition-all duration-300"
        style={getOverlayStyle()}
        onClick={handleSkip}
      />

      {/* Highlight border around target element */}
      {targetRect && (
        <div
          className="absolute border-2 border-[#3b82f6] rounded-lg pointer-events-none transition-all duration-300"
          style={{
            top: targetRect.top - 8,
            left: targetRect.left - 8,
            width: targetRect.width + 16,
            height: targetRect.height + 16,
            boxShadow: '0 0 0 4px rgba(59, 130, 246, 0.3)',
          }}
        />
      )}

      {/* Tooltip card */}
      <div
        className="bg-[#2a2a2a] border border-[#565B5E] rounded-lg p-5 w-[360px] shadow-xl"
        style={getTooltipStyle()}
      >
        {/* Step indicator */}
        <div className="flex items-center gap-2 mb-3">
          <span className="text-[12px] text-[#999999]">
            {currentStep + 1} / {ONBOARDING_STEPS.length}
          </span>
          <div className="flex gap-1">
            {ONBOARDING_STEPS.map((_, idx) => (
              <div
                key={idx}
                className={`w-2 h-2 rounded-full transition-colors ${
                  idx === currentStep ? 'bg-[#3b82f6]' : 'bg-[#565B5E]'
                }`}
              />
            ))}
          </div>
        </div>

        {/* Title */}
        <h3 className="text-[16px] font-bold text-white mb-3">{step.title}</h3>

        {/* Description */}
        <p className="text-[13px] text-[#DCE4EE] leading-relaxed whitespace-pre-line mb-5">
          {step.description}
        </p>

        {/* Buttons */}
        <div className="flex items-center justify-between">
          <button
            onClick={handleSkip}
            className="text-[12px] text-[#999999] hover:text-white transition-colors"
          >
            跳过引导
          </button>
          <div className="flex gap-2">
            {!isFirstStep && (
              <button
                onClick={handlePrev}
                className="px-4 py-1.5 text-[12px] bg-[#565B5E] hover:bg-[#7A8488] text-white rounded transition-colors"
              >
                上一步
              </button>
            )}
            <button
              onClick={handleNext}
              className="px-4 py-1.5 text-[12px] bg-[#3b82f6] hover:bg-[#2563eb] text-white rounded transition-colors"
            >
              {isLastStep ? '完成' : '下一步'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
