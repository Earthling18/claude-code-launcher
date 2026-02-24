import { useNavigate } from 'react-router-dom';

interface ModeSwitchProps {
  active: 'local' | 'remote';
}

export const ModeSwitch: React.FC<ModeSwitchProps> = ({ active }) => {
  const navigate = useNavigate();
  const target = active === 'local' ? '/remote' : '/local';
  const label = active === 'local' ? '远程' : '本地';

  return (
    <button
      onClick={() => navigate(target)}
      className="text-[11px] text-[#6b9fff] hover:text-[#93b8ff] bg-[#1e2a3a] hover:bg-[#253448] px-2.5 py-1 rounded-md transition-colors"
    >
      ⇌ {label}
    </button>
  );
};
