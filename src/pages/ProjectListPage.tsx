import { useEffect, useLayoutEffect, useState, useMemo, useRef } from 'react';
import { useNavigate } from 'react-router-dom';

// Module-level scroll memory: persists across mount/unmount of ProjectListPage
// (e.g., navigating to /edit and back). Reset only on full page reload.
let lastScrollTop = 0;
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
import { projectApi, api, presetsApi, onboardingApi } from '../api';
import { toast } from '../lib/toast';
import { DependencyFrame } from '../components/DependencyFrame';
import { LocalSetupWizard } from '../components/LocalSetupWizard';
import { ProjectCard } from '../components/ProjectCard';
import { SortableProjectCard } from '../components/SortableProjectCard';
import { PresetManagerDialog } from '../components/PresetManagerDialog';
import { OnboardingOverlay, type OnboardingStep } from '../components/OnboardingOverlay';
import { openUrl } from '@tauri-apps/plugin-opener';
import type { Project } from '../types/project';
import type { GlobalPresets } from '../types/presets';

// Sort projects:
//   1. Pinned projects first (sorted by pinned_at desc — newest first)
//   2. Non-pinned projects (default project included, NOT special-cased) sorted by sort_order asc
function sortProjects(projects: Project[]): Project[] {
  return [...projects].sort((a, b) => {
    if (a.is_pinned !== b.is_pinned) return a.is_pinned ? -1 : 1;
    if (a.is_pinned && b.is_pinned) {
      return (b.pinned_at || 0) - (a.pinned_at || 0);
    }
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
  const [showPresets, setShowPresets] = useState(false);
  const [presets, setPresets] = useState<GlobalPresets | null>(null);
  const [showOnboarding, setShowOnboarding] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const scrollRestoredRef = useRef(false);

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

  // Split into groups for drag constraints. Default project sits in its natural group based on is_pinned.
  const { pinnedProjects, normalProjects } = useMemo(() => {
    const pinned = sortedProjects.filter(p => p.is_pinned);
    const normal = sortedProjects.filter(p => !p.is_pinned);
    return { pinnedProjects: pinned, normalProjects: normal };
  }, [sortedProjects]);

  const activeProject = useMemo(
    () => (activeId ? projects.find(p => p.id === activeId) : null),
    [activeId, projects]
  );

  useEffect(() => {
    loadProjects();
    loadPlatform();
    presetsApi.getAll().then(setPresets).catch(() => setPresets(null));
  }, []);

  // First-time onboarding: only after deps are ready (avoids overlapping the wizard)
  useEffect(() => {
    if (!depsReady) return;
    onboardingApi.getStatus()
      .then(seen => { if (!seen) setShowOnboarding(true); })
      .catch(() => {});
  }, [depsReady]);

  // Allow other components (e.g. VersionManager popup) to re-trigger the tour.
  useEffect(() => {
    const handler = () => setShowOnboarding(true);
    window.addEventListener('cc-launcher:show-onboarding', handler);
    return () => window.removeEventListener('cc-launcher:show-onboarding', handler);
  }, []);

  // Keep listening from the initial mount, but do not let the empty loading state overwrite
  // the saved position before the project cards have been rendered.
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const onScroll = () => {
      if (scrollRestoredRef.current) lastScrollTop = el.scrollTop;
    };
    el.addEventListener('scroll', onScroll, { passive: true });
    return () => {
      if (scrollRestoredRef.current) lastScrollTop = el.scrollTop;
      el.removeEventListener('scroll', onScroll);
    };
  }, [depsReady]);

  // Restore only after loading finishes and the cards exist. Assign once synchronously to
  // avoid a visible jump, then once on the next frame for late layout measurements.
  useLayoutEffect(() => {
    if (!depsReady || loading || error || scrollRestoredRef.current) return;
    const el = scrollRef.current;
    if (!el) return;

    const target = lastScrollTop;
    el.scrollTop = target;
    const frame = requestAnimationFrame(() => {
      if (scrollRef.current) scrollRef.current.scrollTop = target;
      scrollRestoredRef.current = true;
    });
    return () => cancelAnimationFrame(frame);
  }, [depsReady, loading, error, sortedProjects.length]);

  const handleOnboardingComplete = () => {
    onboardingApi.setCompleted().catch(() => {});
  };

  // Build the onboarding tour steps. Re-built when projects load so step 3 has the default project id.
  const onboardingSteps: OnboardingStep[] = useMemo(() => {
    const defaultProj = projects.find(p => p.is_default);
    return [
      {
        targetSelector: '[data-onboarding="create"]',
        position: 'bottom',
        title: '快速创建项目',
        body: '把任意文件夹拖进窗口，会自动为该目录创建项目，配置好后一键启动 CC。也可以点这里手动新建。',
      },
      {
        targetSelector: '[data-onboarding="deps"]',
        position: 'bottom',
        title: '修复 / 检查更新',
        body:
          '[CC 修复]：Claude Code 出现配置冲突、命令异常时，点这里一键排查\n' +
          '[检查更新]：获取依赖（Node / Git / Claude / Codex）与启动器自身的新版本',
      },
      {
        targetSelector: '[data-onboarding="default-card"]',
        position: 'bottom',
        title: '从默认项目开始',
        body:
          '点击默认项目进入配置页面：\n' +
          '· 内部用户可使用 UAT 环境模型（自定义模型 → 选 / 新建 LiteLLM 配置）\n' +
          '· 也可使用原版 Claude / Codex 账号（登录后即可启动）',
        primaryLabel: '开始使用',
        onPrimary: () => {
          if (defaultProj) navigate(`/local/project/${defaultProj.id}/edit`);
        },
      },
    ];
  }, [projects, navigate]);

  const reloadPresets = () => presetsApi.getAll().then(setPresets).catch(() => {});

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
      await presetsApi.validateLaunch(id);
    } catch (err: any) {
      toast.error(`${err}`);
      return;
    }
    try {
      await projectApi.launch(id);
      // Silently refresh project data without loading state to preserve scroll position
      try {
        const data = await projectApi.getAll();
        setProjects(data);
      } catch (_) {}
    } catch (err: any) {
      toast.error(`启动失败: ${err}`);
    }
  };

  const handleSelect = (id: string) => {
    if (scrollRef.current) lastScrollTop = scrollRef.current.scrollTop;
    navigate(`/local/project/${id}/edit`);
  };

  const handleCreate = () => {
    if (scrollRef.current) lastScrollTop = scrollRef.current.scrollTop;
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
      <div className="h-screen flex flex-col overflow-hidden">
        <div className="flex-shrink-0 px-6 py-4 border-b border-line">
          <h2 className="text-[14px] font-semibold text-text-primary tracking-wide">本地启动</h2>
        </div>
        <div className="flex-1">
          <LocalSetupWizard onComplete={() => setDepsReady(true)} />
        </div>
      </div>
    );
  }

  const totalCount = sortedProjects.length;

  return (
    <div className="h-screen flex flex-col overflow-hidden">
      {/* Top bar */}
      <div className="flex-shrink-0 px-5 py-2.5 border-b border-line">
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-baseline gap-3">
            <h2 className="text-[13px] font-semibold text-text-primary">本地启动</h2>
            <span className="font-mono text-[10.5px] uppercase tracking-[0.18em] text-text-tertiary">
              {totalCount}
            </span>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setShowPresets(true)}
              className="btn btn-secondary"
              title="管理模型 / 代理配置"
            >
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="12" cy="12" r="3"/>
                <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/>
              </svg>
              管理模型
            </button>
            <button
              data-onboarding="create"
              onClick={handleCreate}
              className="btn btn-primary"
            >
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
              新建项目
            </button>
          </div>
        </div>
      </div>

      <PresetManagerDialog
        isOpen={showPresets}
        kind="model"
        showTabs
        onClose={() => { setShowPresets(false); reloadPresets(); }}
      />

      <OnboardingOverlay
        isOpen={showOnboarding}
        steps={onboardingSteps}
        onClose={() => setShowOnboarding(false)}
        onComplete={handleOnboardingComplete}
      />

      <div ref={scrollRef} className="flex-1 overflow-auto">
        <div className="px-5 pt-2 pb-5">
          <div data-onboarding="deps">
            <DependencyFrame projects={projects} platform={platform} />
          </div>

          <div className="mt-3">
            {loading && (
              <div className="text-center py-12 text-[12px] text-text-tertiary">加载中…</div>
            )}

            {error && (
              <div className="text-center py-12 text-[12px] text-error">
                {error}
                <button onClick={loadProjects} className="ml-2 text-accent hover:underline">重试</button>
              </div>
            )}

            {!loading && !error && (
              <>
                {sortedProjects.length === 0 ? (
                  <div className="flex flex-col items-center justify-center py-16">
                    <div className="font-mono text-[10px] uppercase tracking-[0.22em] text-text-tertiary mb-2">No projects yet</div>
                    <p className="text-[12.5px] text-text-secondary mb-4">点击右上角「新建项目」开始</p>
                  </div>
                ) : (
                  <DndContext
                    sensors={sensors}
                    collisionDetection={closestCenter}
                    onDragStart={handleDragStart}
                    onDragEnd={handleDragEnd}
                  >
                    {/* Pinned section */}
                    {pinnedProjects.length > 0 && (
                      <section className="mb-5">
                        <SectionLabel>置顶 · {pinnedProjects.length}</SectionLabel>
                        <SortableContext
                          items={pinnedProjects.map(p => p.id)}
                          strategy={verticalListSortingStrategy}
                        >
                          <div className="grid grid-cols-2 gap-2.5">
                            {pinnedProjects.map((project) => (
                              <div
                                key={project.id}
                                {...(project.is_default ? { 'data-onboarding': 'default-card' } : {})}
                              >
                                <SortableProjectCard
                                  project={project}
                                  platform={platform}
                                  presets={presets}
                                  onLaunch={handleLaunch}
                                  onSelect={handleSelect}
                                />
                              </div>
                            ))}
                          </div>
                        </SortableContext>
                      </section>
                    )}

                    {/* Non-pinned section (default project participates as a normal one) */}
                    {normalProjects.length > 0 && (
                      <section>
                        {pinnedProjects.length > 0 && <SectionLabel>项目 · {normalProjects.length}</SectionLabel>}
                        <SortableContext
                          items={normalProjects.map(p => p.id)}
                          strategy={verticalListSortingStrategy}
                        >
                          <div className="grid grid-cols-2 gap-2.5">
                            {normalProjects.map((project) => (
                              <div
                                key={project.id}
                                {...(project.is_default ? { 'data-onboarding': 'default-card' } : {})}
                              >
                                <SortableProjectCard
                                  project={project}
                                  platform={platform}
                                  presets={presets}
                                  onLaunch={handleLaunch}
                                  onSelect={handleSelect}
                                />
                              </div>
                            ))}
                          </div>
                        </SortableContext>
                      </section>
                    )}

                    <DragOverlay>
                      {activeProject ? (
                        <ProjectCard
                          project={activeProject}
                          platform={platform}
                          presets={presets}
                          onLaunch={() => {}}
                          onSelect={() => {}}
                          isDragging
                        />
                      ) : null}
                    </DragOverlay>
                  </DndContext>
                )}
              </>
            )}
          </div>

          {/* Footer credit + help link */}
          <div className="text-center text-[10.5px] text-text-tertiary mt-8 mb-1">
            <span>项目由 AI 中台提供，如有问题可咨询 shawnlin</span>
            <span className="text-text-disabled mx-2">·</span>
            <button
              type="button"
              onClick={() => {
                openUrl('https://ccn09t0pw557.feishu.cn/wiki/UrgHwXIeKiBgPzkLutBczEupnig?from=from_copylink')
                  .catch(() => {});
              }}
              className="text-info hover:brightness-125 underline underline-offset-2 transition-all"
              title="在浏览器打开使用帮助文档"
            >
              使用帮助
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};

const SectionLabel: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <div className="flex items-baseline gap-3 mb-2 px-0.5">
    <span className="font-mono text-[10px] uppercase tracking-[0.20em] text-text-tertiary">{children}</span>
    <div className="flex-1 h-px bg-line" />
  </div>
);
