import { useEffect, useState, useRef } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { projectApi, presetsApi, api } from '../api';
import { ProjectForm } from '../components/ProjectForm';
import { ConfirmDialog } from '../components/ConfirmDialog';
import { CopyCommandButton } from '../components/CopyCommandButton';
import { useDragContext } from '../App';
import { toast } from '../lib/toast';
import type { Project, ProjectConfig } from '../types/project';

export const ProjectEditPage: React.FC = () => {
  const navigate = useNavigate();
  const { id } = useParams<{ id: string }>();
  const { registerDragHandler, unregisterDragHandler } = useDragContext();
  const [project, setProject] = useState<Project | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [droppedWorkingDirectory, setDroppedWorkingDirectory] = useState<string | null>(null);
  const [platform, setPlatform] = useState<string>('windows');

  useEffect(() => {
    api.getPlatform().then(setPlatform).catch(() => {});
  }, []);

  // 用 ref 存储 handler 逻辑，确保引用稳定
  const dragHandlerRef = useRef<((path: string) => boolean) | null>(null);

  useEffect(() => {
    if (id) {
      loadProject(id);
    }
  }, [id]);

  // 更新 handler 逻辑（不改变引用）
  useEffect(() => {
    dragHandlerRef.current = (path: string): boolean => {
      // 如果是默认项目，不处理拖拽（工作目录不可修改）
      if (project?.is_default) {
        return false;
      }
      setDroppedWorkingDirectory(path);
      return true;
    };
  }, [project?.is_default]);

  // 只注册一次包装函数，确保注册和注销使用同一个引用
  useEffect(() => {
    const handler = (path: string) => dragHandlerRef.current?.(path) ?? false;
    registerDragHandler(handler);
    return () => unregisterDragHandler(handler);
  }, [registerDragHandler, unregisterDragHandler]);

  const loadProject = async (projectId: string) => {
    try {
      setLoading(true);
      setError(null);
      const data = await projectApi.get(projectId);
      setProject(data);
    } catch (err: any) {
      setError(err?.toString() || '加载项目失败');
    } finally {
      setLoading(false);
    }
  };

  const handleSubmit = async (name: string, workingDirectory: string, config: ProjectConfig, isPinned: boolean) => {
    if (!project) return;

    try {
      setSaving(true);
      await projectApi.update(
        project.id,
        project.is_default ? undefined : name,
        project.is_default ? undefined : workingDirectory,
        config,
        isPinned
      );
      // Persist as last-used so the next "新建项目" pre-fills with this choice.
      presetsApi.setLastUsed(config).catch((err) => {
        console.error('Failed to save last_used_config:', err);
      });
      toast.success('项目配置已更新');
      navigate('/local');
    } catch (err: any) {
      toast.error(`保存失败: ${err}`);
    } finally {
      setSaving(false);
    }
  };

  const handleCancel = () => {
    navigate('/local');
  };

  const handleDeleteClick = () => {
    setShowDeleteConfirm(true);
  };

  const handleDeleteConfirm = async () => {
    if (!project) return;

    try {
      await projectApi.delete(project.id);
      setShowDeleteConfirm(false);
      navigate('/local');
    } catch (err: any) {
      setShowDeleteConfirm(false);
      toast.error(`删除失败: ${err}`);
    }
  };

  const handleDeleteCancel = () => {
    setShowDeleteConfirm(false);
  };

  if (loading) {
    return (
      <div className="h-screen flex items-center justify-center">
        <div className="font-mono text-[11px] text-text-tertiary uppercase tracking-[0.2em]">loading…</div>
      </div>
    );
  }

  if (error || !project) {
    return (
      <div className="h-screen flex flex-col items-center justify-center">
        <div className="text-error mb-4 text-[13px]">{error || '项目不存在'}</div>
        <button onClick={handleCancel} className="btn btn-secondary">返回列表</button>
      </div>
    );
  }

  const handleLaunch = async () => {
    try { await presetsApi.validateLaunch(project.id); }
    catch (err: any) { toast.error(`${err}`); return; }
    try { await projectApi.launch(project.id); }
    catch (err: any) { toast.error(`启动失败: ${err}`); }
  };

  return (
    <div className="h-screen flex flex-col overflow-hidden">
      <div className="flex-shrink-0 px-5 py-2.5 border-b border-line">
        <div className="flex items-center gap-2">
          <button onClick={handleCancel} className="btn btn-ghost btn-sm">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><polyline points="15 18 9 12 15 6"/></svg>
            返回
          </button>
          <div className="h-4 w-px bg-line-strong mx-1" />
          <span className="mode-dot" data-mode={project.config.mode} />
          <h2 className="text-[13px] font-semibold text-text-primary truncate flex-1">{project.name}</h2>
          {project.is_default && (
            <span className="font-mono text-[9.5px] uppercase tracking-[0.18em] text-text-tertiary border border-line-strong px-1.5 py-0.5 rounded-sm">默认</span>
          )}
          <button onClick={handleLaunch} className="btn btn-primary btn-sm">
            <svg width="9" height="9" viewBox="0 0 24 24" fill="currentColor" style={{ color: 'var(--accent)' }}><path d="M8 5v14l11-7z" /></svg>
            启动
          </button>
          <CopyCommandButton projectId={project.id} platform={platform} size="sm" />
        </div>
      </div>

      <div className="flex-1 overflow-auto px-5 py-5">
        <ProjectForm
          initialName={project.name}
          initialWorkingDirectory={droppedWorkingDirectory || project.working_directory}
          initialConfig={project.config}
          initialIsPinned={project.is_pinned}
          onSubmit={handleSubmit}
          onCancel={handleCancel}
          onDelete={project.is_default ? undefined : handleDeleteClick}
          submitLabel={saving ? '保存中…' : '保存修改'}
          isDefault={project.is_default}
        />
      </div>

      <ConfirmDialog
        isOpen={showDeleteConfirm}
        title="删除项目"
        message={`确定要删除项目 "${project.name}" 吗？\n此操作不可撤销。`}
        confirmLabel="删除"
        cancelLabel="取消"
        onConfirm={handleDeleteConfirm}
        onCancel={handleDeleteCancel}
        variant="danger"
      />
    </div>
  );
};
