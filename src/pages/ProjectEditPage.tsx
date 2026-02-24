import { useEffect, useState, useRef } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { projectApi } from '../api';
import { ProjectForm } from '../components/ProjectForm';
import { ConfirmDialog } from '../components/ConfirmDialog';
import { useDragContext } from '../App';
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
        project.is_default ? undefined : isPinned
      );
      alert('项目配置已更新');
      navigate('/local');
    } catch (err: any) {
      alert(`保存失败: ${err}`);
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
      alert(`删除失败: ${err}`);
    }
  };

  const handleDeleteCancel = () => {
    setShowDeleteConfirm(false);
  };

  if (loading) {
    return (
      <div className="h-screen bg-[#212121] text-[#DCE4EE] flex items-center justify-center">
        <div className="text-[#999999]">加载中...</div>
      </div>
    );
  }

  if (error || !project) {
    return (
      <div className="h-screen bg-[#212121] text-[#DCE4EE] flex flex-col items-center justify-center">
        <div className="text-red-500 mb-4">{error || '项目不存在'}</div>
        <button
          onClick={handleCancel}
          className="px-4 py-2 text-[12px] bg-[#565B5E] hover:bg-[#7A8488] text-white rounded"
        >
          返回列表
        </button>
      </div>
    );
  }

  return (
    <div className="h-screen bg-[#212121] text-[#DCE4EE] overflow-auto">
      <div className="max-w-full p-4">
        <div className="px-5 py-3">
          <div className="card-frame">
            {/* 标题栏 */}
            <div className="flex items-center gap-4 mb-4">
              <button
                onClick={handleCancel}
                className="text-[#3b82f6] hover:text-[#2563eb] text-[14px]"
              >
                ← 返回
              </button>
              <h2 className="text-base font-bold">编辑项目: {project.name}</h2>
              {project.is_default && (
                <span className="px-2 py-0.5 text-[10px] bg-green-600 text-white rounded">
                  默认项目
                </span>
              )}
            </div>

            {/* 表单 */}
            <ProjectForm
              initialName={project.name}
              initialWorkingDirectory={droppedWorkingDirectory || project.working_directory}
              initialConfig={project.config}
              initialIsPinned={project.is_pinned}
              onSubmit={handleSubmit}
              onCancel={handleCancel}
              onDelete={project.is_default ? undefined : handleDeleteClick}
              submitLabel={saving ? '保存中...' : '保存修改'}
              isDefault={project.is_default}
            />
          </div>
        </div>
      </div>

      {/* 删除确认对话框 */}
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
