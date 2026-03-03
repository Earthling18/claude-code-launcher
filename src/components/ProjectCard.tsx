import { useState, useEffect } from 'react';
import { writeText } from '@tauri-apps/plugin-clipboard-manager';
import type { Project } from '../types/project';
import type { BridgeStatus } from '../types/project';
import { projectApi, bridgeApi } from '../api';

interface ProjectCardProps {
  project: Project;
  platform: string;
  onLaunch: (id: string) => void;
  onEdit: (id: string) => void;
  isDragging?: boolean;
}

export const ProjectCard: React.FC<ProjectCardProps> = ({
  project,
  platform,
  onLaunch,
  onEdit,
  isDragging = false,
}) => {
  const [copying, setCopying] = useState<string | null>(null);
  const [bridgeStatus, setBridgeStatus] = useState<BridgeStatus | null>(null);
  const [bridgeLoading, setBridgeLoading] = useState(false);

  const isRemote = project.config.mode === 'remote';

  // Poll bridge status for remote projects
  useEffect(() => {
    if (!isRemote) return;

    const poll = async () => {
      try {
        const s = await bridgeApi.getStatus(project.id);
        setBridgeStatus(s);
      } catch {}
    };

    poll();
    const interval = setInterval(poll, 3000);
    return () => clearInterval(interval);
  }, [project.id, isRemote]);

  const formatPath = (path: string) => {
    // Shorten long paths for display
    if (path.length > 40) {
      const parts = path.split(/[/\\]/);
      if (parts.length > 3) {
        return `${parts[0]}\\...\\${parts.slice(-2).join('\\')}`;
      }
    }
    return path;
  };

  const getModeLabel = () => {
    if (project.config.mode === 'claude') return 'Claude账号';
    if (project.config.mode === 'codex') return 'Codex账号';
    if (project.config.mode === 'remote') return '远程桥接';
    return '自定义模型';
  };

  const getModeLabelClass = () => {
    if (project.config.mode === 'remote') return 'bg-[#7c3aed] text-white';
    return 'bg-[#3a3a3a] text-[#999999]';
  };

  const handleCopyCommand = async (type: 'ps' | 'cmd' | 'bash') => {
    try {
      setCopying(type);
      let command: string;

      if (type === 'ps') {
        command = await projectApi.generatePowershellCommand(project.id);
      } else if (type === 'cmd') {
        command = await projectApi.generateCmdCommand(project.id);
      } else {
        command = await projectApi.generateBashCommand(project.id);
      }

      await writeText(command);

      // Show brief success feedback
      setTimeout(() => setCopying(null), 1000);
    } catch (err: any) {
      setCopying(null);
      alert(`复制失败: ${err}`);
    }
  };

  const handleBridgeStart = async () => {
    setBridgeLoading(true);
    try {
      await bridgeApi.start(project.id);
      await new Promise((r) => setTimeout(r, 1500));
      const s = await bridgeApi.getStatus(project.id);
      setBridgeStatus(s);
    } catch (err: any) {
      alert(`启动失败: ${err}`);
    } finally {
      setBridgeLoading(false);
    }
  };

  const handleBridgeStop = async () => {
    setBridgeLoading(true);
    try {
      await bridgeApi.stop(project.id);
      const s = await bridgeApi.getStatus(project.id);
      setBridgeStatus(s);
    } catch (err: any) {
      alert(`停止失败: ${err}`);
    } finally {
      setBridgeLoading(false);
    }
  };

  const getBridgeStatusIndicator = () => {
    if (!bridgeStatus || !bridgeStatus.running) {
      return <span className="inline-block w-2 h-2 rounded-full bg-gray-500" title="未启动" />;
    }
    if (bridgeStatus.agent_ok && bridgeStatus.client_connected) {
      return <span className="inline-block w-2 h-2 rounded-full bg-green-500 animate-pulse" title="已连接" />;
    }
    return <span className="inline-block w-2 h-2 rounded-full bg-yellow-500 animate-pulse" title="连接中" />;
  };

  return (
    <div className={`bg-[#2a2a2a] border rounded-lg p-4 transition-colors ${
      isDragging
        ? 'border-[#3b82f6] shadow-lg'
        : 'border-[#3a3a3a] hover:border-[#4a4a4a]'
    } ${!project.is_default ? 'cursor-grab active:cursor-grabbing' : ''}`}>
      {/* Title row: name + mode tag + pinned indicator + edit icon */}
      <div className="flex items-start justify-between mb-2">
        <div className="flex items-center gap-2 flex-1 min-w-0">
          <h3 className="text-[14px] font-medium text-white truncate">
            {project.name}
          </h3>
          {project.is_pinned && (
            <span className="px-2 py-0.5 text-[10px] bg-[#f59e0b] text-white rounded whitespace-nowrap" title="已置顶">
              置顶
            </span>
          )}
          {isRemote && getBridgeStatusIndicator()}
          <span className={`px-2 py-0.5 text-[10px] rounded whitespace-nowrap ${getModeLabelClass()}`}>
            {getModeLabel()}
          </span>
        </div>
        <button
          onClick={() => onEdit(project.id)}
          className="ml-2 p-1 text-[#999999] hover:text-white transition-colors"
          title="编辑项目"
        >
          <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M17 3a2.828 2.828 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5L17 3z"/>
          </svg>
        </button>
      </div>

      {/* Working directory */}
      <div className="mb-2">
        <p className="text-[11px] text-[#999999] truncate" title={project.working_directory}>
          {formatPath(project.working_directory)}
        </p>
      </div>

      {/* Last launched time or creation time */}
      <p className="text-[10px] text-[#666666] mb-3">
        {project.last_launched_at
          ? `上次启动: ${new Date(project.last_launched_at * 1000).toLocaleString()}`
          : `创建时间: ${new Date(project.created_at * 1000).toLocaleString()}`
        }
      </p>

      {/* Buttons row */}
      <div className="flex items-center gap-2" data-onboarding={project.is_default ? "launch-buttons" : undefined}>
        {isRemote ? (
          // Remote mode: bridge start/stop buttons
          <>
            {!bridgeStatus?.running ? (
              <button
                onClick={handleBridgeStart}
                disabled={bridgeLoading}
                className="px-3 py-1.5 text-[12px] bg-[#10b981] hover:bg-[#059669] disabled:opacity-50 text-white rounded transition-colors"
              >
                {bridgeLoading ? '处理中...' : '启动桥接'}
              </button>
            ) : (
              <button
                onClick={handleBridgeStop}
                disabled={bridgeLoading}
                className="px-3 py-1.5 text-[12px] bg-red-600 hover:bg-red-700 disabled:opacity-50 text-white rounded transition-colors"
              >
                {bridgeLoading ? '处理中...' : '停止桥接'}
              </button>
            )}
          </>
        ) : (
          // Non-remote mode: original launch buttons
          <>
            <button
              onClick={() => onLaunch(project.id)}
              className="px-3 py-1.5 text-[12px] bg-[#3b82f6] hover:bg-[#2563eb] text-white rounded transition-colors"
            >
              启动
            </button>

            {/* Copy buttons based on platform */}
            {platform === 'windows' ? (
              <>
                <button
                  onClick={() => handleCopyCommand('ps')}
                  className="px-3 py-1.5 text-[12px] bg-[#565B5E] hover:bg-[#7A8488] text-white rounded transition-colors"
                  disabled={copying === 'ps'}
                >
                  {copying === 'ps' ? '已复制' : '复制PS'}
                </button>
                <button
                  onClick={() => handleCopyCommand('cmd')}
                  className="px-3 py-1.5 text-[12px] bg-[#565B5E] hover:bg-[#7A8488] text-white rounded transition-colors"
                  disabled={copying === 'cmd'}
                >
                  {copying === 'cmd' ? '已复制' : '复制CMD'}
                </button>
              </>
            ) : (
              <button
                onClick={() => handleCopyCommand('bash')}
                className="px-3 py-1.5 text-[12px] bg-[#565B5E] hover:bg-[#7A8488] text-white rounded transition-colors"
                disabled={copying === 'bash'}
              >
                {copying === 'bash' ? '已复制' : '复制Bash'}
              </button>
            )}
          </>
        )}
      </div>
    </div>
  );
};
