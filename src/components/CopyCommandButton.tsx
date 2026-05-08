import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { presetsApi, projectApi } from '../api';
import { toast } from '../lib/toast';

interface CopyCommandButtonProps {
  projectId: string;
  platform: string;
  /** Visual size: 'sm' = 26px (row inline), 'md' = 32px (default), 'lg' = 38px. */
  size?: 'sm' | 'md' | 'lg';
}

export const CopyCommandButton: React.FC<CopyCommandButtonProps> = ({ projectId, platform, size = 'md' }) => {
  const [open, setOpen] = useState(false);
  const [copied, setCopied] = useState<null | string>(null);
  const btnRef = useRef<HTMLButtonElement>(null);
  const popRef = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState<{ top: number; right: number } | null>(null);

  const recalc = () => {
    if (!btnRef.current) return;
    const r = btnRef.current.getBoundingClientRect();
    setPos({
      top: r.bottom + 4,
      right: window.innerWidth - r.right,
    });
  };

  useLayoutEffect(() => { if (open) recalc(); }, [open]);

  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      const t = e.target as Node;
      if (btnRef.current?.contains(t)) return;
      if (popRef.current?.contains(t)) return;
      setOpen(false);
    };
    const onResize = () => recalc();
    const onScroll = () => recalc();
    window.addEventListener('mousedown', onClick);
    window.addEventListener('resize', onResize);
    window.addEventListener('scroll', onScroll, true);
    return () => {
      window.removeEventListener('mousedown', onClick);
      window.removeEventListener('resize', onResize);
      window.removeEventListener('scroll', onScroll, true);
    };
  }, [open]);

  const copy = async (kind: 'ps' | 'cmd' | 'bash') => {
    try {
      await presetsApi.validateLaunch(projectId);
    } catch (err: any) {
      toast.error(`${err}`);
      return;
    }
    try {
      const cmd =
        kind === 'ps' ? await projectApi.generatePowershellCommand(projectId)
        : kind === 'cmd' ? await projectApi.generateCmdCommand(projectId)
        : await projectApi.generateBashCommand(projectId);
      await navigator.clipboard.writeText(cmd);
      setCopied(kind);
      setTimeout(() => { setCopied(null); setOpen(false); }, 900);
    } catch (err: any) {
      toast.error(`复制失败: ${err}`);
    }
  };

  const sizeClass = size === 'sm' ? '!h-8' : size === 'lg' ? 'btn-lg' : '';

  // Mac/Linux: just one option, copy directly. No dropdown.
  if (platform !== 'windows') {
    return (
      <button
        type="button"
        onClick={(e) => { e.stopPropagation(); copy('bash'); }}
        className={`btn btn-secondary ${sizeClass} flex-shrink-0`}
        title="复制 Bash / Zsh 命令"
      >
        <CopyIcon />
        {copied === 'bash' ? '已复制' : '复制'}
      </button>
    );
  }

  return (
    <>
      <button
        ref={btnRef}
        type="button"
        onClick={(e) => { e.stopPropagation(); setOpen(v => !v); }}
        className={`btn btn-secondary ${sizeClass} flex-shrink-0`}
        title="复制启动命令"
      >
        <CopyIcon />
        {copied ? '已复制' : '复制'}
        <svg width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" className="-mr-0.5"><polyline points="6 9 12 15 18 9"/></svg>
      </button>
      {open && pos && createPortal(
        <div
          ref={popRef}
          className="fixed z-[200] min-w-[200px] py-1 bg-surface-2 border border-line-strong rounded shadow-elev"
          style={{ top: pos.top, right: pos.right }}
          onClick={(e) => e.stopPropagation()}
        >
          <MenuItem
            label={copied === 'ps' ? '已复制 PowerShell' : '复制 PowerShell 命令'}
            onClick={() => copy('ps')}
          />
          <MenuItem
            label={copied === 'cmd' ? '已复制 CMD' : '复制 CMD 命令'}
            onClick={() => copy('cmd')}
          />
        </div>,
        document.body
      )}
    </>
  );
};

const CopyIcon: React.FC = () => (
  <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <rect x="9" y="9" width="13" height="13" rx="2"/>
    <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>
  </svg>
);

const MenuItem: React.FC<{ label: string; onClick: () => void }> = ({ label, onClick }) => (
  <button
    type="button"
    onClick={onClick}
    className="block w-full text-left px-3 py-1.5 text-[12px] text-text-secondary hover:bg-surface-3 hover:text-text-primary transition-colors"
  >
    {label}
  </button>
);
