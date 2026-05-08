import { useEffect, useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { toast, type Toast } from '../lib/toast';

export const ToastHost: React.FC = () => {
  const [toasts, setToasts] = useState<Toast[]>([]);

  useEffect(() => toast.subscribe(setToasts), []);

  return (
    <div className="fixed top-4 right-4 z-[100] flex flex-col items-end gap-2 pointer-events-none">
      <AnimatePresence>
        {toasts.map(t => (
          <motion.div
            key={t.id}
            initial={{ opacity: 0, y: -8, scale: 0.96 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -4, scale: 0.98 }}
            transition={{ duration: 0.18, ease: [0.2, 0.8, 0.2, 1] }}
            className={[
              'pointer-events-auto max-w-[360px] flex items-start gap-2.5 px-3.5 py-2.5 rounded border shadow-elev',
              'backdrop-blur-sm',
              t.type === 'error'   ? 'bg-error/[0.08] border-error/40' :
              t.type === 'success' ? 'bg-ok/[0.08] border-ok/40' :
                                     'bg-surface-2 border-line-strong',
            ].join(' ')}
            role="alert"
          >
            <Icon type={t.type} />
            <span className="text-[12.5px] text-text-primary leading-snug whitespace-pre-line break-words">
              {t.message}
            </span>
            <button
              onClick={() => toast.dismiss(t.id)}
              className="text-text-tertiary hover:text-text-primary transition-colors -mr-1 mt-0.5"
              title="关闭"
            >
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
            </button>
          </motion.div>
        ))}
      </AnimatePresence>
    </div>
  );
};

const Icon: React.FC<{ type: Toast['type'] }> = ({ type }) => {
  const stroke = type === 'error' ? 'var(--error)' : type === 'success' ? 'var(--ok)' : 'var(--info)';
  return (
    <span className="flex-shrink-0 mt-0.5">
      {type === 'error' && (
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke={stroke} strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/>
        </svg>
      )}
      {type === 'success' && (
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke={stroke} strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
          <polyline points="20 6 9 17 4 12"/>
        </svg>
      )}
      {type === 'info' && (
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke={stroke} strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/>
        </svg>
      )}
    </span>
  );
};
