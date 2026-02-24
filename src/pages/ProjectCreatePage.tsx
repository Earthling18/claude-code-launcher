import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { projectApi, systemApi } from '../api';
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
      const projects = await projectApi.getAll();
      if (projects.length > 0) {
        // 取最后一个项目的配置作为默认配置
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
      navigate('/local');
    } catch (err: any) {
      alert(`创建失败: ${err}`);
    } finally {
      setSaving(false);
    }
  };

  const handleCancel = () => {
    navigate('/local');
  };

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
              <h2 className="text-base font-bold">新建项目</h2>
            </div>

            {/* 表单 */}
            <ProjectForm
              initialWorkingDirectory={defaultWorkingDirectory}
              initialConfig={lastConfig}
              onSubmit={handleSubmit}
              onCancel={handleCancel}
              submitLabel={saving ? '创建中...' : '创建项目'}
            />
          </div>
        </div>
      </div>
    </div>
  );
};
