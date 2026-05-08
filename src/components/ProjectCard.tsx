import type { Project } from '../types/project';
import type { GlobalPresets } from '../types/presets';
import { CopyCommandButton } from './CopyCommandButton';

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
    if (cfg.proxy_preset_id && presets) {
      const p = presets.proxies.find(p => p.id === cfg.proxy_preset_id);
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

  return (
    <div
      className="project-card group"
      data-dragging={isDragging}
      onClick={handleCardClick}
    >
      {/* Header row: mode dot + pinned star + name + default chip */}
      <div className="flex items-center gap-1.5 min-w-0">
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
