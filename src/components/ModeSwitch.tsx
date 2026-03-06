import { useNavigate } from 'react-router-dom';
import { getCurrentWindow } from '@tauri-apps/api/window';

interface ModeSwitchProps {
  active: 'local' | 'remote';
}

export const ModeSwitch: React.FC<ModeSwitchProps> = ({ active }) => {
  const navigate = useNavigate();
  const target = active === 'local' ? '/remote' : '/local';
  const label = active === 'local' ? '远程' : '本地';

  const handleSwitch = () => {
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
      className="text-[11px] text-[#6b9fff] hover:text-[#93b8ff] bg-[#1e2a3a] hover:bg-[#253448] px-2.5 py-1 rounded-md transition-colors"
    >
      ⇌ {label}
    </button>
  );
};
