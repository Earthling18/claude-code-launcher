import { useEffect, useLayoutEffect, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';

export interface OnboardingStep {
  /** CSS selector for the element to spotlight. Omit for centered welcome / final card. */
  targetSelector?: string;
  /** Tooltip placement relative to target. Default: bottom (or center if no target). */
  position?: 'top' | 'bottom' | 'center';
  title: string;
  body: string;
  /** Override the primary button label. Default: "下一步" or "完成" on last step. */
  primaryLabel?: string;
  /** Custom primary action. If set, replaces "advance" behavior; the tour also closes. */
  onPrimary?: () => void;
}

interface Props {
  isOpen: boolean;
  steps: OnboardingStep[];
  /** Always called when the tour ends (skip / complete / primary action). */
  onClose: () => void;
  /** Optional: called when user reaches the end naturally OR confirms via primary on last step. */
  onComplete?: () => void;
}

interface Rect {
  top: number;
  left: number;
  width: number;
  height: number;
}

const TOOLTIP_W = 360;
const PAD = 14;

export const OnboardingOverlay: React.FC<Props> = ({ isOpen, steps, onClose, onComplete }) => {
  const [idx, setIdx] = useState(0);
  const [rect, setRect] = useState<Rect | null>(null);

  // Reset to step 0 each time the tour opens.
  useEffect(() => { if (isOpen) setIdx(0); }, [isOpen]);

  const step = steps[idx];
  const isLast = idx === steps.length - 1;

  // Recompute target rect whenever step or window changes.
  useLayoutEffect(() => {
    if (!isOpen) return;
    if (!step?.targetSelector) { setRect(null); return; }

    const compute = () => {
      const el = document.querySelector(step.targetSelector!);
      if (!el) { setRect(null); return; }
      // Bring the target into view if needed.
      el.scrollIntoView({ block: 'center', inline: 'center', behavior: 'instant' as ScrollBehavior });
      const r = el.getBoundingClientRect();
      setRect({ top: r.top, left: r.left, width: r.width, height: r.height });
    };

    compute();
    // Recompute slightly later in case layout shifts.
    const t = setTimeout(compute, 60);
    window.addEventListener('resize', compute);
    return () => {
      clearTimeout(t);
      window.removeEventListener('resize', compute);
    };
  }, [isOpen, step?.targetSelector, idx]);

  const handleSkip = () => {
    onClose();
    onComplete?.();
  };

  const handlePrev = () => {
    if (idx > 0) setIdx(idx - 1);
  };

  const handlePrimary = () => {
    if (step.onPrimary) {
      step.onPrimary();
      onClose();
      onComplete?.();
      return;
    }
    if (isLast) {
      onClose();
      onComplete?.();
    } else {
      setIdx(idx + 1);
    }
  };

  // Tooltip positioning.
  const computeTooltipStyle = (): React.CSSProperties => {
    if (!rect || step.position === 'center') {
      return {
        left: '50%',
        top: '50%',
        transform: 'translate(-50%, -50%)',
        width: TOOLTIP_W,
      };
    }
    const tooltipH = 200;
    const targetCenterX = rect.left + rect.width / 2;
    let left = targetCenterX - TOOLTIP_W / 2;
    left = Math.max(PAD, Math.min(left, window.innerWidth - TOOLTIP_W - PAD));

    let top: number;
    const placeBottom = step.position !== 'top';
    if (placeBottom) {
      top = rect.top + rect.height + PAD;
      // Flip if would go off screen.
      if (top + tooltipH > window.innerHeight - PAD) top = rect.top - tooltipH - PAD;
    } else {
      top = rect.top - tooltipH - PAD;
      if (top < PAD) top = rect.top + rect.height + PAD;
    }
    return { left, top, width: TOOLTIP_W };
  };

  return (
    <AnimatePresence>
      {isOpen && (
        <div className="fixed inset-0 z-[100]">
          {/* Click-blocker: clicking anywhere outside tooltip / spotlight skips the tour. */}
          <motion.div
            className="absolute inset-0"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.15 }}
            onClick={handleSkip}
          />

          {/* When no target (centered card), darken everything. */}
          {!rect && (
            <div className="absolute inset-0 pointer-events-none" style={{ background: 'rgba(10, 12, 16, 0.78)' }} />
          )}

          {/* Spotlight: visual only (pointer-events-none). The dark surround is painted via box-shadow. */}
          {rect && (
            <motion.div
              className="absolute pointer-events-none"
              initial={false}
              animate={{
                top: rect.top - 6,
                left: rect.left - 6,
                width: rect.width + 12,
                height: rect.height + 12,
              }}
              transition={{ duration: 0.32, ease: [0.2, 0.8, 0.2, 1] }}
              style={{
                borderRadius: 8,
                border: '2px solid var(--accent)',
                boxShadow:
                  '0 0 0 9999px rgba(10, 12, 16, 0.78), 0 0 0 4px rgba(232, 165, 71, 0.18)',
              }}
            />
          )}

          {/* Tooltip card */}
          <motion.div
            key={idx} // re-mount on step change so animation plays
            className="absolute bg-surface-2 border border-line-strong rounded-lg shadow-elev"
            style={computeTooltipStyle()}
            initial={{ opacity: 0, y: 6, scale: 0.97 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, scale: 0.98 }}
            transition={{ duration: 0.2, ease: [0.2, 0.8, 0.2, 1] }}
            onClick={(e) => e.stopPropagation()}
          >
            <div className="px-4 pt-4 pb-2">
              <div className="flex items-center justify-between mb-2">
                <span className="font-mono text-[10px] uppercase tracking-[0.22em] text-text-tertiary">
                  STEP {idx + 1} / {steps.length}
                </span>
                <div className="flex gap-1">
                  {steps.map((_, i) => (
                    <span
                      key={i}
                      className="w-1.5 h-1.5 rounded-full transition-colors"
                      style={{
                        background: i === idx ? 'var(--accent)' : 'var(--line-strong)',
                      }}
                    />
                  ))}
                </div>
              </div>
              <h3 className="text-[14px] font-semibold text-text-primary mb-1.5">{step.title}</h3>
              <p className="text-[12px] text-text-secondary leading-relaxed whitespace-pre-line">
                {step.body}
              </p>
            </div>
            <div className="flex items-center justify-between gap-2 px-4 py-3 border-t border-line">
              <button
                type="button"
                onClick={handleSkip}
                className="text-[11px] text-text-tertiary hover:text-text-primary underline-offset-2 hover:underline transition-colors"
              >
                跳过引导
              </button>
              <div className="flex items-center gap-1.5">
                {idx > 0 && (
                  <button type="button" onClick={handlePrev} className="btn btn-ghost btn-sm">
                    上一步
                  </button>
                )}
                <button type="button" onClick={handlePrimary} className="btn btn-primary btn-sm">
                  {step.primaryLabel ?? (isLast ? '完成' : '下一步')}
                </button>
              </div>
            </div>
          </motion.div>
        </div>
      )}
    </AnimatePresence>
  );
};
