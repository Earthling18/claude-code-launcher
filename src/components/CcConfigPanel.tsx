import { useState, useEffect, useMemo } from 'react';
import { ccConfigApi } from '../api';
import type { Project } from '../types/project';
import type { ConfigConflict } from '../types/project';

interface CcConfigPanelProps {
  projects: Project[];
  platform: string;
  onClose: () => void;
}

interface GroupedConflicts {
  source: string;
  label: string;
  filePath: string | null;
  canClean: boolean;
  items: ConfigConflict[];
}

export const CcConfigPanel: React.FC<CcConfigPanelProps> = ({ projects, platform, onClose }) => {
  const [conflicts, setConflicts] = useState<ConfigConflict[]>([]);
  const [scanning, setScanning] = useState(false);
  const [cleaning, setCleaning] = useState(false);

  const doScan = async () => {
    setScanning(true);
    try {
      const projectInfos = projects.map(p => ({
        name: p.name,
        working_directory: p.working_directory,
      }));
      const result = await ccConfigApi.scan(projectInfos);
      setConflicts(result.conflicts);
    } catch (err) {
      console.error('Scan failed:', err);
    } finally {
      setScanning(false);
    }
  };

  useEffect(() => {
    doScan();
  }, []);

  // Group conflicts by source + file_path
  const grouped = useMemo(() => {
    const map = new Map<string, GroupedConflicts>();

    for (const c of conflicts) {
      const groupKey = c.file_path ?? c.source;
      if (!map.has(groupKey)) {
        let label: string;
        if (c.source === 'env') {
          const hint = platform === 'windows'
            ? '系统属性 > 环境变量 或 $PROFILE (PowerShell)'
            : '~/.zshrc 或 ~/.bashrc';
          label = `系统环境变量  (请在 ${hint} 中修改)`;
        } else if (c.source === 'global') {
          label = `全局配置 ~/.claude/settings.json`;
        } else if (c.source.startsWith('project:')) {
          const projectName = c.source.slice('project:'.length);
          const fileName = c.file_path?.split('/').pop() ?? c.file_path?.split('\\').pop() ?? 'settings.json';
          label = `项目: ${projectName} (${fileName})`;
        } else {
          label = c.source;
        }
        map.set(groupKey, {
          source: c.source,
          label,
          filePath: c.file_path,
          canClean: c.can_clean,
          items: [],
        });
      }
      map.get(groupKey)!.items.push(c);
    }

    return Array.from(map.values());
  }, [conflicts, platform]);

  const cleanableConflicts = conflicts.filter(c => c.can_clean);
  const hasConflicts = conflicts.length > 0;

  const handleCleanField = async (filePath: string, key: string) => {
    try {
      await ccConfigApi.cleanField(filePath, key);
      await doScan();
    } catch (err: any) {
      alert(`清理失败: ${err}`);
    }
  };

  const handleCleanAll = async () => {
    if (cleanableConflicts.length === 0) return;
    setCleaning(true);
    try {
      const targets = cleanableConflicts.map(c => ({
        file_path: c.file_path!,
        key: c.key,
      }));
      const count = await ccConfigApi.cleanAll(targets);
      alert(`已清理 ${count} 项配置`);
      await doScan();
    } catch (err: any) {
      alert(`清理失败: ${err}`);
    } finally {
      setCleaning(false);
    }
  };

  const handleOpenFile = async (filePath: string) => {
    try {
      await ccConfigApi.openFile(filePath);
    } catch (err: any) {
      alert(`打开失败: ${err}`);
    }
  };

  return (
    <div className="card-frame">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-[13px] font-bold">CC 配置检测</h2>
        <div className="flex items-center gap-2">
          <button
            onClick={doScan}
            disabled={scanning}
            className="px-3 py-1 text-[10px] bg-[#666666] hover:bg-[#555555] text-white rounded disabled:opacity-50"
          >
            {scanning ? '扫描中...' : '重新扫描'}
          </button>
          {cleanableConflicts.length > 0 && (
            <button
              onClick={handleCleanAll}
              disabled={cleaning}
              className="px-3 py-1 text-[10px] bg-[#ef4444] hover:bg-[#dc2626] text-white rounded disabled:opacity-50"
            >
              {cleaning ? '清理中...' : '一键清理'}
            </button>
          )}
          <button
            onClick={onClose}
            className="text-[10px] text-[#666666] hover:text-white transition-colors"
          >
            收起
          </button>
        </div>
      </div>

      {scanning && conflicts.length === 0 ? (
        <div className="text-[11px] text-[#999999] py-4 text-center">扫描中...</div>
      ) : !hasConflicts ? (
        <div className="text-[11px] text-[#10b981] py-4 text-center">
          未检测到冲突配置
        </div>
      ) : (
        <div className="space-y-3">
          {grouped.map((group) => (
            <div key={group.label} className="border border-[#3a3a3a] rounded px-3 py-2">
              <div className="flex items-center justify-between mb-1">
                <span className="text-[11px] text-[#999999]">{group.label}</span>
                {group.canClean && group.filePath && (
                  <button
                    onClick={() => handleOpenFile(group.filePath!)}
                    className="text-[10px] text-[#3b82f6] hover:text-[#60a5fa] transition-colors"
                  >
                    打开文件
                  </button>
                )}
              </div>
              {group.items.length === 0 ? (
                <div className="text-[10px] text-[#666666]">(无冲突配置)</div>
              ) : (
                <div className="space-y-1">
                  {group.items.map((item) => (
                    <div key={`${item.key}-${item.source}`} className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <span className="text-[11px] text-[#e5c07b] font-mono">{item.key}</span>
                        <span className="text-[10px] text-[#666666]">=</span>
                        <span className="text-[11px] text-[#98c379] font-mono truncate max-w-[300px]">{item.value}</span>
                      </div>
                      {item.can_clean && item.file_path && (
                        <button
                          onClick={() => handleCleanField(item.file_path!, item.key)}
                          className="text-[10px] text-[#ef4444] hover:text-[#f87171] transition-colors ml-2 flex-shrink-0"
                        >
                          清理
                        </button>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
