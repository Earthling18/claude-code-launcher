import { useState, useEffect, useMemo } from 'react';
import { ccConfigApi, api } from '../api';
import { toast } from '../lib/toast';
import type { Project, ConfigConflict, BomFileIssue, McpMisplaced } from '../types/project';

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
  const [bomFiles, setBomFiles] = useState<BomFileIssue[]>([]);
  const [mcpMisplaced, setMcpMisplaced] = useState<McpMisplaced[]>([]);
  const [scanning, setScanning] = useState(false);
  const [cleaning, setCleaning] = useState(false);
  const [reinstallingCc, setReinstallingCc] = useState(false);

  const doScan = async () => {
    setScanning(true);
    try {
      const projectInfos = projects.map(p => ({
        name: p.name,
        working_directory: p.working_directory,
      }));
      const result = await ccConfigApi.scan(projectInfos);
      setConflicts(result.conflicts);
      setBomFiles(result.bom_files);
      setMcpMisplaced(result.mcp_misplaced);
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
        if (c.source === 'shell_profile') {
          const fileName = c.file_path?.split('/').pop() ?? '';
          label = `Shell 配置 ~/${fileName}`;
        } else if (c.source === 'registry_user') {
          label = '用户环境变量 (系统属性 > 环境变量 > 用户变量)';
        } else if (c.source === 'registry_system') {
          label = '系统环境变量 (系统属性 > 环境变量 > 系统变量，需管理员权限修改)';
        } else if (c.source === 'global') {
          label = '全局配置 ~/.claude/settings.json';
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
  const totalIssues = conflicts.length + bomFiles.length + mcpMisplaced.length;
  // All MCP issues are fixable: can_fix=true → migrate, can_fix=false → remove mcpServers
  const totalFixable = cleanableConflicts.length + bomFiles.length + mcpMisplaced.length;

  const handleCleanField = async (filePath: string, key: string) => {
    try {
      await ccConfigApi.cleanField(filePath, key);
      await doScan();
    } catch (err: any) {
      toast.error(`清理失败: ${err}`);
    }
  };

  const handleCleanAll = async () => {
    if (totalFixable === 0) return;
    setCleaning(true);
    try {
      let fixed = 0;
      // Clean config conflicts
      if (cleanableConflicts.length > 0) {
        const targets = cleanableConflicts.map(c => ({
          file_path: c.file_path!,
          key: c.key,
        }));
        fixed += await ccConfigApi.cleanAll(targets);
      }
      // Fix BOMs
      for (const bom of bomFiles) {
        await ccConfigApi.fixBom(bom.file_path);
        fixed++;
      }
      // Fix MCP misplaced
      for (const mcp of mcpMisplaced) {
        if (mcp.can_fix) {
          // Project-level: migrate to .mcp.json
          await ccConfigApi.fixMcpMisplaced(mcp.file_path, mcp.target_path);
        } else {
          // Global: just remove mcpServers from settings.json
          await ccConfigApi.removeMcpServers(mcp.file_path);
        }
        fixed++;
      }
      toast.success(`已修复 ${fixed} 项问题`);
      await doScan();
    } catch (err: any) {
      toast.error(`修复失败: ${err}`);
    } finally {
      setCleaning(false);
    }
  };

  const handleFixBom = async (filePath: string) => {
    try {
      await ccConfigApi.fixBom(filePath);
      await doScan();
    } catch (err: any) {
      toast.error(`修复失败: ${err}`);
    }
  };

  const handleFixMcp = async (filePath: string, targetPath: string) => {
    try {
      await ccConfigApi.fixMcpMisplaced(filePath, targetPath);
      await doScan();
    } catch (err: any) {
      toast.error(`修复失败: ${err}`);
    }
  };

  const handleRemoveMcp = async (filePath: string) => {
    try {
      await ccConfigApi.removeMcpServers(filePath);
      await doScan();
    } catch (err: any) {
      toast.error(`清理失败: ${err}`);
    }
  };

  const handleOpenFile = async (filePath: string) => {
    try {
      await ccConfigApi.openFile(filePath);
    } catch (err: any) {
      toast.error(`打开失败: ${err}`);
    }
  };

  const handleReinstallClaude = async () => {
    setReinstallingCc(true);
    try {
      await api.reinstallClaude();
      toast.info('已打开重装窗口，请等待终端执行完毕');
    } catch (err: any) {
      toast.error(`重装失败: ${err}`);
    } finally {
      setReinstallingCc(false);
    }
  };

  const shortPath = (p: string) => {
    const home = '~';
    // Show relative-ish path
    const parts = p.replace(/\\/g, '/').split('/');
    if (parts.length > 3) {
      return `${home}/.../${parts.slice(-2).join('/')}`;
    }
    return p;
  };

  return (
    <div className="card p-4">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <span className={`dot ${totalIssues > 0 ? 'dot-warn' : 'dot-ok'}`} />
          <h2 className="text-[13px] font-semibold text-text-primary">CC 修复</h2>
        </div>
        <button onClick={onClose} className="btn btn-ghost btn-sm">收起</button>
      </div>

      {/* Section 1: 安装修复 */}
      <SectionHeader title="安装修复" />
      <div className="mb-5 p-3 rounded border border-line bg-surface-1">
        <p className="text-[11.5px] text-text-secondary mb-2.5 leading-snug">
          如果 Claude Code 命令报错、卡住或行为异常，可尝试一次完整重装（卸载后重新安装）。
        </p>
        <button onClick={handleReinstallClaude} disabled={reinstallingCc} className="btn btn-secondary btn-sm">
          {reinstallingCc ? '处理中…' : '重装 Claude Code'}
        </button>
      </div>

      {/* Section 2: CC 配置修复 */}
      <div className="flex items-center justify-between mb-1.5">
        <SectionHeader title="CC 配置修复" inline />
        <div className="flex items-center gap-1">
          <button onClick={doScan} disabled={scanning} className="btn btn-ghost btn-sm">
            {scanning ? '扫描中…' : '重新扫描'}
          </button>
          {totalFixable > 0 && (
            <button onClick={handleCleanAll} disabled={cleaning} className="btn btn-secondary btn-sm">
              {cleaning ? '修复中…' : `一键修复 ${totalFixable}`}
            </button>
          )}
        </div>
      </div>

      {scanning && totalIssues === 0 ? (
        <div className="text-[11.5px] text-text-tertiary py-3 text-center">扫描配置中…</div>
      ) : totalIssues === 0 ? (
        <div className="text-[11.5px] text-ok py-3 text-center">✓ 未检测到配置问题</div>
      ) : (
        <div className="space-y-3">
          {/* Section 1: Config conflicts */}
          {grouped.length > 0 && (
            <>
              <div className="text-[11px] text-[#cccccc] font-bold">配置冲突</div>
              {grouped.map((group) => (
                <div key={group.label} className="border border-[#3a3a3a] rounded px-3 py-2">
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-[11px] text-[#999999]">{group.label}</span>
                    <div className="flex items-center gap-2">
                      {group.filePath && (
                        <button
                          onClick={() => handleOpenFile(group.filePath!)}
                          className="text-[10px] text-[#3b82f6] hover:text-[#60a5fa] transition-colors"
                        >
                          打开
                        </button>
                      )}
                    </div>
                  </div>
                  {!group.canClean && (
                    <div className="text-[10px] text-[#ef9a3a] mb-1">
                      {group.source === 'shell_profile'
                        ? `请手动编辑该文件，删除或注释对应的 export 行`
                        : group.source === 'registry_user'
                        ? `打开 系统属性 → 高级 → 环境变量，在"用户变量"中删除对应项`
                        : group.source === 'registry_system'
                        ? `打开 系统属性 → 高级 → 环境变量，在"系统变量"中删除对应项（需管理员权限）`
                        : ''}
                    </div>
                  )}
                  <div className="space-y-1">
                    {group.items.map((item) => (
                      <div key={`${item.key}-${item.source}-${item.file_path}`} className="flex items-center justify-between">
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
                </div>
              ))}
            </>
          )}

          {/* Section 2: BOM issues */}
          {bomFiles.length > 0 && (
            <>
              <div className="text-[11px] text-[#cccccc] font-bold mt-2">JSON 文件问题</div>
              {bomFiles.map((bom) => (
                <div key={bom.file_path} className="border border-[#3a3a3a] rounded px-3 py-2 flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className="text-[11px] text-[#ef9a3a]">!</span>
                    <span className="text-[11px] text-[#999999]">{shortPath(bom.file_path)}</span>
                    <span className="text-[10px] text-[#666666]">包含 UTF-8 BOM，可能导致配置不生效</span>
                  </div>
                  <button
                    onClick={() => handleFixBom(bom.file_path)}
                    className="text-[10px] text-[#3b82f6] hover:text-[#60a5fa] transition-colors flex-shrink-0"
                  >
                    修复
                  </button>
                </div>
              ))}
            </>
          )}

          {/* Section 3: MCP misplaced */}
          {mcpMisplaced.length > 0 && (
            <>
              <div className="text-[11px] text-[#cccccc] font-bold mt-2">MCP 配置位置</div>
              {mcpMisplaced.map((mcp) => (
                <div key={mcp.file_path} className="border border-[#3a3a3a] rounded px-3 py-2">
                  <div className="flex items-center justify-between mb-1">
                    <div className="flex items-center gap-2">
                      <span className="text-[11px] text-[#ef9a3a]">!</span>
                      <span className="text-[11px] text-[#999999]">{shortPath(mcp.file_path)}</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <button
                        onClick={() => handleOpenFile(mcp.file_path)}
                        className="text-[10px] text-[#3b82f6] hover:text-[#60a5fa] transition-colors"
                      >
                        打开
                      </button>
                      {mcp.can_fix ? (
                        <button
                          onClick={() => handleFixMcp(mcp.file_path, mcp.target_path)}
                          className="text-[10px] text-[#3b82f6] hover:text-[#60a5fa] transition-colors"
                        >
                          迁移到 .mcp.json
                        </button>
                      ) : (
                        <button
                          onClick={() => handleRemoveMcp(mcp.file_path)}
                          className="text-[10px] text-[#ef4444] hover:text-[#f87171] transition-colors"
                        >
                          清理
                        </button>
                      )}
                    </div>
                  </div>
                  <div className="text-[10px] text-[#666666]">
                    {mcp.can_fix
                      ? `mcpServers (${mcp.keys.join(', ')}) 应放在项目根目录 .mcp.json 中才能被 Claude Code 加载`
                      : `mcpServers (${mcp.keys.join(', ')}) 不应放在 settings.json 中，清理后请用 claude mcp add --scope user 重新添加`
                    }
                  </div>
                </div>
              ))}
            </>
          )}
        </div>
      )}
    </div>
  );
};

const SectionHeader: React.FC<{ title: string; inline?: boolean }> = ({ title, inline = false }) => (
  <div className={`flex items-baseline gap-3 ${inline ? '' : 'mb-2'}`}>
    <h3 className="font-mono text-[10px] uppercase tracking-[0.20em] text-text-tertiary">{title}</h3>
    {!inline && <div className="flex-1 h-px bg-line" />}
  </div>
);
