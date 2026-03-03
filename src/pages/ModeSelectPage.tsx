import { useNavigate } from 'react-router-dom';

export const ModeSelectPage: React.FC = () => {
  const navigate = useNavigate();

  return (
    <div className="h-screen bg-[#212121] text-[#DCE4EE] flex items-center justify-center">
      <div className="flex flex-col items-center gap-8">
        <h1 className="text-xl font-bold mb-2">选择使用模式</h1>

        <div className="grid grid-cols-2 gap-6">
          {/* 本地使用 */}
          <button
            onClick={() => navigate('/local')}
            className="group flex flex-col items-center gap-4 p-8 bg-[#2a2a2a] border border-[#3a3a3a] rounded-xl hover:border-[#3b82f6] hover:bg-[#2a2f3a] transition-all duration-200 cursor-pointer w-52"
          >
            <div className="text-[40px]">
              <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="text-[#3b82f6] group-hover:scale-110 transition-transform">
                <rect x="2" y="3" width="20" height="14" rx="2" ry="2" />
                <line x1="8" y1="21" x2="16" y2="21" />
                <line x1="12" y1="17" x2="12" y2="21" />
              </svg>
            </div>
            <div className="text-center">
              <div className="text-[15px] font-semibold mb-1">本地使用</div>
              <div className="text-[11px] text-[#999999] leading-relaxed">
                在本地使用 Claude Code 或 Codex
              </div>
            </div>
          </button>

          {/* 远程使用 */}
          <button
            onClick={() => navigate('/remote')}
            className="group flex flex-col items-center gap-4 p-8 bg-[#2a2a2a] border border-[#3a3a3a] rounded-xl hover:border-[#10b981] hover:bg-[#2a3a2f] transition-all duration-200 cursor-pointer w-52"
          >
            <div className="text-[40px]">
              <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="text-[#10b981] group-hover:scale-110 transition-transform">
                <circle cx="12" cy="12" r="10" />
                <line x1="2" y1="12" x2="22" y2="12" />
                <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z" />
              </svg>
            </div>
            <div className="text-center">
              <div className="text-[15px] font-semibold mb-1">Mobot (远程连接)</div>
              <div className="text-[11px] text-[#999999] leading-relaxed">
                生成服务，可对接企微
              </div>
            </div>
          </button>
        </div>
      </div>
    </div>
  );
};
