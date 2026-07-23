import type { Project } from '../types/project';
import type { GlobalPresets } from '../types/presets';
import { projectApi } from '../api';
import { CopyCommandButton } from './CopyCommandButton';
import { toast } from '../lib/toast';

interface ProjectCardProps {
  project: Project;
  platform: string;
  presets?: GlobalPresets | null;
  onLaunch: (id: string) => void;
  onSelect: (id: string) => void;
  isDragging?: boolean;
}

const MODE_LABEL: Record<string, string> = {
  claude: 'Claude',
  codex: 'Codex',
  custom: 'Custom',
};

function formatPath(path: string) {
  if (path.length <= 36) return path;
  const parts = path.split(/[/\\]/);
  if (parts.length <= 3) return path;
  return `${parts[0]}\\…\\${parts.slice(-2).join('\\')}`;
}

function getDetailTag(project: Project, presets?: GlobalPresets | null): string | null {
  const cfg = project.config;
  if (cfg.mode === 'custom') {
    if (cfg.model_preset_id && presets) {
      const m = presets.models.find(m => m.id === cfg.model_preset_id);
      if (m) return m.name;
    }
    if (cfg.model) return cfg.model;
    return null;
  }
  if (cfg.mode === 'claude' || cfg.mode === 'codex') {
    const proxyPresetId = cfg.mode === 'claude'
      ? (cfg.claude_proxy_preset_id ?? cfg.proxy_preset_id)
      : (cfg.codex_proxy_preset_id ?? cfg.proxy_preset_id);
    if (proxyPresetId && presets) {
      const p = presets.proxies.find(p => p.id === proxyPresetId);
      if (p) return p.name;
    }
    const fallback = cfg.mode === 'codex' ? cfg.codex_api_key : cfg.proxy;
    if (fallback) return '已设置代理';
    return null;
  }
  return null;
}

export const ProjectCard: React.FC<ProjectCardProps> = ({
  project,
  platform,
  presets,
  onLaunch,
  onSelect,
  isDragging = false,
}) => {
  const mode = project.config.mode;
  const detailTag = getDetailTag(project, presets);

  const handleCardClick = () => onSelect(project.id);
  const handleLaunch = (e: React.MouseEvent) => {
    e.stopPropagation();
    onLaunch(project.id);
  };
  const handleOpenFolder = async (e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      await projectApi.openFolder(project.id);
    } catch (err) {
      toast.error(`打开文件夹失败: ${err}`);
    }
  };

  return (
    <div
      className="project-card group"
      data-dragging={isDragging}
      onClick={handleCardClick}
    >
      <button
        type="button"
        onPointerDown={(e) => e.stopPropagation()}
        onClick={handleOpenFolder}
        className="absolute top-2.5 right-2.5 z-10 flex h-6 w-6 items-center justify-center rounded text-text-disabled opacity-70 transition-all hover:bg-surface-1 hover:text-text-secondary hover:opacity-100"
        title="打开项目文件夹"
        aria-label={`打开 ${project.name} 文件夹`}
      >
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
          <path d="M3 6.5h6l2 2h10v9.5a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6.5Z" />
          <path d="M3 10h18" />
        </svg>
      </button>

      {/* Header row: mode dot + pinned star + name + default chip */}
      <div className="flex items-center gap-1.5 min-w-0 pr-6">
        <span className="mode-dot flex-shrink-0" data-mode={mode} aria-hidden />
        {project.is_pinned && (
          <svg width="10" height="10" viewBox="0 0 24 24" fill="var(--accent)" aria-label="已置顶" className="flex-shrink-0">
            <path d="M12 2l2.4 7.4H22l-6.2 4.5 2.4 7.4L12 16.8l-6.2 4.5 2.4-7.4L2 9.4h7.6z"/>
          </svg>
        )}
        <span className="text-[13px] font-medium text-text-primary truncate flex-1">
          {project.name}
        </span>
        {project.is_default && (
          <span className="font-mono text-[9.5px] uppercase tracking-[0.16em] text-text-tertiary border border-line-strong px-1.5 py-0.5 rounded-sm flex-shrink-0">
            默认
          </span>
        )}
      </div>

      {/* Meta: path + mode/detail */}
      <div className="space-y-0.5 min-w-0">
        <div
          className="font-mono text-[10.5px] text-text-tertiary truncate"
          title={project.working_directory}
        >
          {formatPath(project.working_directory)}
        </div>
        <div className="text-[10.5px] text-text-tertiary truncate flex items-center gap-1.5">
          <span className="flex-shrink-0">{MODE_LABEL[mode] || mode}</span>
          {detailTag && (
            <>
              <span className="text-text-disabled flex-shrink-0">·</span>
              <span className="font-mono truncate">{detailTag}</span>
            </>
          )}
        </div>
      </div>

      {/* Actions */}
      <div className="flex items-center gap-1.5 mt-auto pt-1">
        <button
          type="button"
          onClick={handleLaunch}
          className="btn btn-primary !h-8 flex-1 min-w-0"
          title="启动"
        >
          <svg width="9" height="9" viewBox="0 0 24 24" fill="currentColor" style={{ color: 'var(--accent)' }}><path d="M8 5v14l11-7z" /></svg>
          启动
        </button>
        <div onClick={(e) => e.stopPropagation()} className="flex-shrink-0">
          <CopyCommandButton projectId={project.id} platform={platform} size="sm" />
        </div>
      </div>
    </div>
  );
};
