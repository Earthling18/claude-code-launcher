import { useState, useEffect } from 'react';
import { BrowserRouter, Routes, Route, useNavigate, useLocation } from 'react-router-dom';
import { listen } from '@tauri-apps/api/event';
import { ProjectListPage } from './pages/ProjectListPage';
import { ModeSelectPage } from './pages/ModeSelectPage';
import { ProjectDetailPage } from './pages/ProjectDetailPage';
import { ProjectEditPage } from './pages/ProjectEditPage';
import { ProjectCreatePage } from './pages/ProjectCreatePage';
import { RemoteBridgePage } from './pages/RemoteBridgePage';
import { UpdateNotification } from './components/UpdateNotification';
import { VersionManager } from './components/VersionManager';
import { useUpdateChecker } from './hooks/useUpdateChecker';
import './index.css';

// 全局拖拽上下文
import { createContext, useContext, useRef, useCallback } from 'react';

// 自定义拖拽处理器类型：返回 true 表示已处理，false 表示使用默认行为
type DragHandler = (path: string) => boolean;

interface DragContextType {
  droppedPath: string | null;
  setDroppedPath: (path: string | null) => void;
  registerDragHandler: (handler: DragHandler) => void;
  unregisterDragHandler: (handler: DragHandler) => void;
}

export const DragContext = createContext<DragContextType>({
  droppedPath: null,
  setDroppedPath: () => {},
  registerDragHandler: () => {},
  unregisterDragHandler: () => {},
});

export const useDragContext = () => useContext(DragContext);

function AppContent() {
  const navigate = useNavigate();
  const location = useLocation();
  const [isDragging, setIsDragging] = useState(false);
  const [droppedPath, setDroppedPath] = useState<string | null>(null);
  const updateChecker = useUpdateChecker();

  // 存储自定义拖拽处理器
  const dragHandlersRef = useRef<Set<(path: string) => boolean>>(new Set());

  const registerDragHandler = useCallback((handler: (path: string) => boolean) => {
    dragHandlersRef.current.add(handler);
  }, []);

  const unregisterDragHandler = useCallback((handler: (path: string) => boolean) => {
    dragHandlersRef.current.delete(handler);
  }, []);

  // 使用 Tauri 的 drag-drop 事件 API 获取文件路径
  useEffect(() => {
    const unlisten = listen<{ paths: string[] }>('tauri://drag-drop', (event) => {
      setIsDragging(false);
      const paths = event.payload.paths;
      if (paths && paths.length > 0) {
        const path = paths[0];

        // 尝试调用自定义处理器
        let handled = false;
        for (const handler of dragHandlersRef.current) {
          if (handler(path)) {
            handled = true;
            break;
          }
        }

        // 如果没有自定义处理器处理，使用默认行为（仅本地模式）
        if (!handled && location.pathname.startsWith('/local')) {
          setDroppedPath(path);
          navigate('/local/project/new');
        }
      }
    });

    return () => {
      unlisten.then(fn => fn());
    };
  }, [navigate, location.pathname]);

  // 处理拖拽视觉效果（dragover/dragleave 用于显示拖拽遮罩）
  useEffect(() => {
    const handleDragOver = (e: DragEvent) => {
      e.preventDefault();
      e.stopPropagation();
      setIsDragging(true);
    };

    const handleDragLeave = (e: DragEvent) => {
      e.preventDefault();
      e.stopPropagation();
      // 只有离开窗口时才取消拖拽状态
      if (e.relatedTarget === null) {
        setIsDragging(false);
      }
    };

    const handleDrop = (e: DragEvent) => {
      e.preventDefault();
      e.stopPropagation();
      // 注意：实际的文件路径处理由 Tauri 的 drag-drop 事件处理
      // 这里只需要阻止默认行为
      setIsDragging(false);
    };

    window.addEventListener('dragover', handleDragOver);
    window.addEventListener('dragleave', handleDragLeave);
    window.addEventListener('drop', handleDrop);

    return () => {
      window.removeEventListener('dragover', handleDragOver);
      window.removeEventListener('dragleave', handleDragLeave);
      window.removeEventListener('drop', handleDrop);
    };
  }, []);

  return (
    <DragContext.Provider value={{ droppedPath, setDroppedPath, registerDragHandler, unregisterDragHandler }}>
      <div className="relative">
        <UpdateNotification
          status={updateChecker.status}
          version={updateChecker.version}
          progress={updateChecker.progress}
          error={updateChecker.error}
          isPortable={updateChecker.isPortable}
          onUpdate={updateChecker.downloadAndInstall}
          onDismiss={updateChecker.dismiss}
          onRetry={updateChecker.retry}
        />
        {/* 拖拽遮罩层 — 仅本地模式显示 */}
        {isDragging && location.pathname.startsWith('/local') && (
          <div className="fixed inset-0 z-50 bg-[#212121]/90 flex items-center justify-center pointer-events-none">
            <div className="border-2 border-dashed border-[#3b82f6] rounded-xl p-12 text-center">
              <div className="text-[48px] mb-4">📁</div>
              <div className="text-[18px] text-[#3b82f6] font-semibold">拖放文件夹到此处</div>
              <div className="text-[14px] text-[#999999] mt-2">将自动创建新项目</div>
            </div>
          </div>
        )}

        <Routes>
          <Route path="/" element={<ModeSelectPage />} />
          <Route path="/local" element={<ProjectListPage />} />
          <Route path="/local/project/new" element={<ProjectCreatePage />} />
          <Route path="/local/project/:id" element={<ProjectDetailPage />} />
          <Route path="/local/project/:id/edit" element={<ProjectEditPage />} />
          <Route path="/remote" element={<RemoteBridgePage />} />
        </Routes>

        {/* Version manager button — only on local mode pages */}
        {location.pathname.startsWith('/local') && <VersionManager />}
      </div>
    </DragContext.Provider>
  );
}

function App() {
  return (
    <BrowserRouter>
      <AppContent />
    </BrowserRouter>
  );
}

export default App;
