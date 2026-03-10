import React from 'react';
import { UpdateStatus } from '../hooks/useUpdateChecker';

interface UpdateNotificationProps {
  status: UpdateStatus;
  version: string | null;
  progress: number;
  error: string | null;
  isPortable: boolean;
  onUpdate: () => void;
  onDismiss: () => void;
  onRetry: () => void;
}

export const UpdateNotification: React.FC<UpdateNotificationProps> = ({
  status,
  version,
  progress,
  error,
  isPortable,
  onUpdate,
  onDismiss,
  onRetry,
}) => {
  if (status === 'idle' || status === 'checking') return null;

  return (
    <div className="bg-[#2a2a2a] border-b border-[#565B5E] px-4 py-3">
      {status === 'available' && (
        <div className="flex items-center justify-between">
          <span className="text-[13px] text-[#DCE4EE]">
            发现新版本 <span className="font-semibold text-[#3b82f6]">v{version}</span>，建议更新以获得最佳体验
          </span>
          <div className="flex gap-2 ml-4 shrink-0">
            <button
              onClick={onDismiss}
              className="px-3 py-1 text-[12px] bg-[#565B5E] hover:bg-[#7A8488] text-white rounded transition-colors"
            >
              稍后再说
            </button>
            <button
              onClick={onUpdate}
              className="px-3 py-1 text-[12px] bg-[#3b82f6] hover:bg-[#2563eb] text-white rounded transition-colors"
            >
              {isPortable ? '前往下载' : '立即更新'}
            </button>
          </div>
        </div>
      )}

      {status === 'downloading' && (
        <div className="flex items-center gap-3">
          <span className="text-[13px] text-[#DCE4EE] shrink-0">正在下载更新...</span>
          <div className="flex-1 bg-[#1a1a1a] rounded-full h-2 overflow-hidden">
            <div
              className="h-full bg-[#3b82f6] rounded-full transition-all duration-300"
              style={{ width: `${progress}%` }}
            />
          </div>
          <span className="text-[12px] text-[#999999] shrink-0 w-10 text-right">{progress}%</span>
        </div>
      )}

      {status === 'error' && (
        <div className="flex items-center justify-between">
          <span className="text-[13px] text-[#ef4444]">
            更新失败：{error || '未知错误'}
          </span>
          <div className="flex gap-2 ml-4 shrink-0">
            <button
              onClick={onDismiss}
              className="px-3 py-1 text-[12px] bg-[#565B5E] hover:bg-[#7A8488] text-white rounded transition-colors"
            >
              关闭
            </button>
            <button
              onClick={onRetry}
              className="px-3 py-1 text-[12px] bg-[#3b82f6] hover:bg-[#2563eb] text-white rounded transition-colors"
            >
              重试
            </button>
          </div>
        </div>
      )}
    </div>
  );
};
