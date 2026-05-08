import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { projectApi, systemApi, presetsApi } from '../api';
import { toast } from '../lib/toast';
import { ProjectForm } from '../components/ProjectForm';
import { useDragContext } from '../App';
import type { ProjectConfig } from '../types/project';

export const ProjectCreatePage: React.FC = () => {
  const navigate = useNavigate();
  const { droppedPath, setDroppedPath } = useDragContext();
  const [saving, setSaving] = useState(false);
  const [defaultWorkingDirectory, setDefaultWorkingDirectory] = useState('');
  const [lastConfig, setLastConfig] = useState<ProjectConfig | undefined>(undefined);

  // 初始化：加载主目录和最后的项目配置
  useEffect(() => {
    // 如果有拖拽的路径，使用它；否则加载主目录
    if (droppedPath) {
      setDefaultWorkingDirectory(droppedPath);
      // 清除拖拽路径，防止重复使用
      setDroppedPath(null);
    } else {
      loadHomeDirectory();
    }
    loadLastProjectConfig();
  }, []);

  // 监听拖拽路径变化：当已在新建页面时拖入文件夹
  useEffect(() => {
    if (droppedPath) {
      setDefaultWorkingDirectory(droppedPath);
      setDroppedPath(null);
    }
  }, [droppedPath, setDroppedPath]);

  const loadHomeDirectory = async () => {
    try {
      const homeDir = await systemApi.getHomeDirectory();
      // 只在没有拖拽路径时设置
      if (!droppedPath) {
        setDefaultWorkingDirectory(homeDir);
      }
    } catch (err) {
      console.error('Failed to get home directory:', err);
    }
  };

  const loadLastProjectConfig = async () => {
    try {
      // Prefer the explicit last_used_config saved on previous create/edit; fall back to the most recent project's config.
      const lastUsed = await presetsApi.getLastUsed();
      if (lastUsed) {
        setLastConfig(lastUsed);
        return;
      }
      const projects = await projectApi.getAll();
      if (projects.length > 0) {
        const lastProject = projects[projects.length - 1];
        setLastConfig(lastProject.config);
      }
    } catch (err) {
      console.error('Failed to load last project config:', err);
    }
  };

  const handleSubmit = async (name: string, workingDirectory: string, config: ProjectConfig, isPinned: boolean) => {
    try {
      setSaving(true);
      const project = await projectApi.create(name, workingDirectory, config);
      if (isPinned) {
        await projectApi.togglePinned(project.id, true);
      }
      // Persist as last-used so the next "新建项目" pre-fills with this choice.
      presetsApi.setLastUsed(config).catch((err) => {
        console.error('Failed to save last_used_config:', err);
      });
      navigate('/local');
    } catch (err: any) {
      toast.error(`创建失败: ${err}`);
    } finally {
      setSaving(false);
    }
  };

  const handleCancel = () => {
    navigate('/local');
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
          <h2 className="text-[13px] font-semibold text-text-primary">新建项目</h2>
        </div>
      </div>

      <div className="flex-1 overflow-auto px-5 py-5">
        <ProjectForm
          initialWorkingDirectory={defaultWorkingDirectory}
          initialConfig={lastConfig}
          onSubmit={handleSubmit}
          onCancel={handleCancel}
          submitLabel={saving ? '创建中…' : '创建项目'}
        />
      </div>
    </div>
  );
};
