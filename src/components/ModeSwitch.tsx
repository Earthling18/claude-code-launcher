import { useNavigate } from 'react-router-dom';
import { getCurrentWindow } from '@tauri-apps/api/window';

interface ModeSwitchProps {
  active: 'local' | 'remote';
  disabled?: boolean;
}

export const ModeSwitch: React.FC<ModeSwitchProps> = ({ active, disabled }) => {
  const navigate = useNavigate();
  const target = active === 'local' ? '/remote' : '/local';
  const label = active === 'local' ? '远程' : '本地';

  const handleSwitch = () => {
    if (disabled) return;
    navigate(target);
    try {
      const win = getCurrentWindow();
      if (target === '/remote') {
        win.maximize().catch(() => {});
      } else {
        win.unmaximize().catch(() => {});
      }
    } catch {}
  };

  return (
    <button
      onClick={handleSwitch}
      disabled={disabled}
      className={`text-[11px] px-2.5 py-1 rounded-md transition-colors ${
        disabled
          ? 'text-[#565B5E] bg-[#1a1a1a] cursor-not-allowed'
          : 'text-[#6b9fff] hover:text-[#93b8ff] bg-[#1e2a3a] hover:bg-[#253448]'
      }`}
      title={disabled ? '远程服务处理中，请等待完成' : undefined}
    >
      ⇌ {label}
    </button>
  );
};
