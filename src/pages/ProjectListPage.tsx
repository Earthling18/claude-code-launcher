import { useEffect, useState, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  DndContext,
  closestCenter,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
  DragEndEvent,
  DragStartEvent,
  DragOverlay,
} from '@dnd-kit/core';
import {
  SortableContext,
  sortableKeyboardCoordinates,
  verticalListSortingStrategy,
} from '@dnd-kit/sortable';
import { projectApi, api } from '../api';
import { DependencyFrame } from '../components/DependencyFrame';
import { LocalSetupWizard } from '../components/LocalSetupWizard';
import { ProjectCard } from '../components/ProjectCard';
import { SortableProjectCard } from '../components/SortableProjectCard';
import { ModeSwitch } from '../components/ModeSwitch';
import type { Project } from '../types/project';

// Sort projects according to the priority rules
function sortProjects(projects: Project[]): Project[] {
  return [...projects].sort((a, b) => {
    // 1. Default project fixed at first
    if (a.is_default !== b.is_default) return a.is_default ? -1 : 1;

    // 2. Pinned projects come before non-pinned
    if (a.is_pinned !== b.is_pinned) return a.is_pinned ? -1 : 1;

    // 3. Pinned projects sorted by pinned_at descending (newer first)
    if (a.is_pinned && b.is_pinned) {
      return (b.pinned_at || 0) - (a.pinned_at || 0);
    }

    // 4. Non-pinned projects sorted by sort_order ascending
    return a.sort_order - b.sort_order;
  });
}

export const ProjectListPage: React.FC = () => {
  const navigate = useNavigate();
  const [depsReady, setDepsReady] = useState(() => localStorage.getItem('local_deps_ok') === '1');
  const [projects, setProjects] = useState<Project[]>([]);
  const [platform, setPlatform] = useState<string>('windows');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeId, setActiveId] = useState<string | null>(null);

  const sensors = useSensors(
    useSensor(PointerSensor, {
      activationConstraint: {
        distance: 8, // 8px movement required to start drag
      },
    }),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    })
  );

  // Sorted projects
  const sortedProjects = useMemo(() => sortProjects(projects), [projects]);

  // Split into groups for drag constraints
  const { pinnedProjects, normalProjects } = useMemo(() => {
    const pinned = sortedProjects.filter(p => p.is_pinned && !p.is_default);
    const normal = sortedProjects.filter(p => !p.is_pinned && !p.is_default);
    return { pinnedProjects: pinned, normalProjects: normal };
  }, [sortedProjects]);

  const defaultProject = useMemo(
    () => sortedProjects.find(p => p.is_default),
    [sortedProjects]
  );

  const activeProject = useMemo(
    () => (activeId ? projects.find(p => p.id === activeId) : null),
    [activeId, projects]
  );

  useEffect(() => {
    loadProjects();
    loadPlatform();
  }, []);

  const loadPlatform = async () => {
    try {
      const p = await api.getPlatform();
      setPlatform(p);
    } catch (err) {
      console.error('Failed to get platform:', err);
    }
  };

  const loadProjects = async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await projectApi.getAll();
      setProjects(data);
    } catch (err: any) {
      setError(err?.toString() || '加载项目列表失败');
    } finally {
      setLoading(false);
    }
  };

  const handleLaunch = async (id: string) => {
    try {
      await projectApi.launch(id);
      // Silently refresh project data without loading state to preserve scroll position
      try {
        const data = await projectApi.getAll();
        setProjects(data);
      } catch (_) {}
    } catch (err: any) {
      alert(`启动失败: ${err}`);
    }
  };

  const handleEdit = (id: string) => {
    navigate(`/local/project/${id}/edit`);
  };

  const handleCreate = () => {
    navigate('/local/project/new');
  };

  const handleDragStart = (event: DragStartEvent) => {
    setActiveId(event.active.id as string);
  };

  const handleDragEnd = async (event: DragEndEvent) => {
    const { active, over } = event;
    setActiveId(null);

    if (!over || active.id === over.id) return;

    const activeProject = projects.find(p => p.id === active.id);
    const overProject = projects.find(p => p.id === over.id);

    if (!activeProject || !overProject) return;

    // Don't allow dragging default projects
    if (activeProject.is_default) return;

    // Don't allow dragging between pinned and non-pinned groups
    if (activeProject.is_pinned !== overProject.is_pinned) return;

    // Don't allow dropping onto default project
    if (overProject.is_default) return;

    if (activeProject.is_pinned) {
      // Reorder pinned projects
      const oldIndex = pinnedProjects.findIndex(p => p.id === active.id);
      const newIndex = pinnedProjects.findIndex(p => p.id === over.id);

      if (oldIndex === -1 || newIndex === -1) return;

      // Create new order array
      const newPinnedProjects = [...pinnedProjects];
      const [removed] = newPinnedProjects.splice(oldIndex, 1);
      newPinnedProjects.splice(newIndex, 0, removed);

      // Assign new pinned_at values (higher = more recent = shown first)
      const now = Math.floor(Date.now() / 1000);
      const orders = newPinnedProjects.map((p, idx) => ({
        id: p.id,
        pinned_at: now - idx, // Earlier index = higher timestamp = shown first
      }));

      // Optimistic update
      setProjects(prev => {
        const updated = [...prev];
        for (const order of orders) {
          const project = updated.find(p => p.id === order.id);
          if (project) {
            project.pinned_at = order.pinned_at;
          }
        }
        return updated;
      });

      // Persist
      try {
        await projectApi.updatePinnedOrder(orders);
      } catch (err) {
        console.error('Failed to update pinned order:', err);
        loadProjects(); // Reload on error
      }
    } else {
      // Reorder normal projects
      const oldIndex = normalProjects.findIndex(p => p.id === active.id);
      const newIndex = normalProjects.findIndex(p => p.id === over.id);

      if (oldIndex === -1 || newIndex === -1) return;

      // Create new order array
      const newNormalProjects = [...normalProjects];
      const [removed] = newNormalProjects.splice(oldIndex, 1);
      newNormalProjects.splice(newIndex, 0, removed);

      // Assign new sort_order values
      const orders = newNormalProjects.map((p, idx) => ({
        id: p.id,
        sort_order: idx,
      }));

      // Optimistic update
      setProjects(prev => {
        const updated = [...prev];
        for (const order of orders) {
          const project = updated.find(p => p.id === order.id);
          if (project) {
            project.sort_order = order.sort_order;
          }
        }
        return updated;
      });

      // Persist
      try {
        await projectApi.updateProjectsOrder(orders);
      } catch (err) {
        console.error('Failed to update project order:', err);
        loadProjects(); // Reload on error
      }
    }
  };

  // Show setup wizard for first-time users
  if (!depsReady) {
    return (
      <div className="h-screen bg-[#212121] text-[#DCE4EE] flex flex-col overflow-hidden">
        <div className="flex-shrink-0 px-6 py-3 border-b border-[#3a3a3a]">
          <div className="flex items-center gap-3">
            <ModeSwitch active="local" />
            <h2 className="text-base font-bold">本地启动</h2>
          </div>
        </div>
        <div className="flex-1">
          <LocalSetupWizard onComplete={() => setDepsReady(true)} />
        </div>
      </div>
    );
  }

  return (
    <div className="h-screen bg-[#212121] text-[#DCE4EE] flex flex-col overflow-hidden">
      {/* Top bar — fixed */}
      <div className="flex-shrink-0 px-6 py-3 border-b border-[#3a3a3a]">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <ModeSwitch active="local" />
            <h2 className="text-base font-bold">本地启动</h2>
          </div>
          <button
            onClick={handleCreate}
            className="px-4 py-2 text-[12px] bg-[#3b82f6] hover:bg-[#2563eb] text-white rounded"
          >
            + 新建项目
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-auto">
        <div className="max-w-full p-4">
          {/* 依赖检测面板 — 返回用户静默检测 */}
          <DependencyFrame projects={projects} platform={platform} />

          {/* 项目列表面板 */}
          <div className="px-5 py-3">
            <div className="card-frame">

            {/* 加载状态 */}
            {loading && (
              <div className="text-center py-8 text-[#999999]">
                加载中...
              </div>
            )}

            {/* 错误信息 */}
            {error && (
              <div className="text-center py-8 text-red-500">
                {error}
                <button
                  onClick={loadProjects}
                  className="ml-2 text-[#3b82f6] hover:underline"
                >
                  重试
                </button>
              </div>
            )}

            {/* 项目列表 */}
            {!loading && !error && (
              <>
                {sortedProjects.length === 0 ? (
                  <div className="text-center py-8 text-[#999999]">
                    暂无项目，点击上方按钮创建
                  </div>
                ) : (
                  <DndContext
                    sensors={sensors}
                    collisionDetection={closestCenter}
                    onDragStart={handleDragStart}
                    onDragEnd={handleDragEnd}
                  >
                    <div className="grid grid-cols-2 gap-4">
                      {/* Default project - not draggable */}
                      {defaultProject && (
                        <div>
                          <ProjectCard
                            project={defaultProject}
                            platform={platform}
                            onLaunch={handleLaunch}
                            onEdit={handleEdit}
                          />
                        </div>
                      )}

                      {/* Pinned projects - draggable within group */}
                      {pinnedProjects.length > 0 && (
                        <SortableContext
                          items={pinnedProjects.map(p => p.id)}
                          strategy={verticalListSortingStrategy}
                        >
                          {pinnedProjects.map(project => (
                            <SortableProjectCard
                              key={project.id}
                              project={project}
                              platform={platform}
                              onLaunch={handleLaunch}
                              onEdit={handleEdit}
                            />
                          ))}
                        </SortableContext>
                      )}

                      {/* Normal projects - draggable within group */}
                      {normalProjects.length > 0 && (
                        <SortableContext
                          items={normalProjects.map(p => p.id)}
                          strategy={verticalListSortingStrategy}
                        >
                          {normalProjects.map(project => (
                            <SortableProjectCard
                              key={project.id}
                              project={project}
                              platform={platform}
                              onLaunch={handleLaunch}
                              onEdit={handleEdit}
                            />
                          ))}
                        </SortableContext>
                      )}
                    </div>

                    {/* Drag overlay for better visual feedback */}
                    <DragOverlay>
                      {activeProject ? (
                        <ProjectCard
                          project={activeProject}
                          platform={platform}
                          onLaunch={() => {}}
                          onEdit={() => {}}
                          isDragging
                        />
                      ) : null}
                    </DragOverlay>
                  </DndContext>
                )}
              </>
            )}
          </div>
        </div>
        </div>
      </div>
    </div>
  );
};
