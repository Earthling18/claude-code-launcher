import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { projectApi, api } from '../api';
import { BridgeStatusPanel } from '../components/BridgeStatusPanel';
import type { Project } from '../types/project';

export const ProjectDetailPage: React.FC = () => {
  const navigate = useNavigate();
  const { id } = useParams<{ id: string }>();
  const [project, setProject] = useState<Project | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [copySuccess, setCopySuccess] = useState(false);
  const [platform, setPlatform] = useState<'windows' | 'macos' | 'linux' | 'unknown'>('windows');

  useEffect(() => {
    if (id) {
      loadProject(id);
      loadPlatform();
    }
  }, [id]);

  const loadPlatform = async () => {
    try {
      const p = await api.getPlatform();
      setPlatform(p as 'windows' | 'macos' | 'linux' | 'unknown');
    } catch (error) {
      console.log('获取平台信息失败');
    }
  };

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

  const handleLaunch = async () => {
    if (!project) return;

    try {
      await projectApi.launch(project.id);
      // Reload to update last_launched_at
      loadProject(project.id);
    } catch (err: any) {
      alert(`启动失败: ${err}`);
    }
  };

  const handleCopyPowershell = async () => {
    if (!project) return;
    try {
      const command = await projectApi.generatePowershellCommand(project.id);
      await navigator.clipboard.writeText(command);
      setCopySuccess(true);
      setTimeout(() => setCopySuccess(false), 2000);
    } catch (err: any) {
      alert(`复制失败: ${err}`);
    }
  };

  const handleCopyCmd = async () => {
    if (!project) return;
    try {
      const command = await projectApi.generateCmdCommand(project.id);
      await navigator.clipboard.writeText(command);
      setCopySuccess(true);
      setTimeout(() => setCopySuccess(false), 2000);
    } catch (err: any) {
      alert(`复制失败: ${err}`);
    }
  };

  const handleCopyBash = async () => {
    if (!project) return;
    try {
      const command = await projectApi.generateBashCommand(project.id);
      await navigator.clipboard.writeText(command);
      setCopySuccess(true);
      setTimeout(() => setCopySuccess(false), 2000);
    } catch (err: any) {
      alert(`复制失败: ${err}`);
    }
  };

  const handleEdit = () => {
    if (project) {
      navigate(`/local/project/${project.id}/edit`);
    }
  };

  const handleBack = () => {
    navigate('/local');
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
          onClick={handleBack}
          className="px-4 py-2 text-[12px] bg-[#565B5E] hover:bg-[#7A8488] text-white rounded"
        >
          返回列表
        </button>
      </div>
    );
  }

  const isRemote = project.config.mode === 'remote';

  const getModeLabel = () => {
    if (project.config.mode === 'claude') return 'Claude 账号';
    if (project.config.mode === 'codex') return 'Codex 账号';
    if (project.config.mode === 'remote') return '远程桥接';
    return '自定义模型';
  };

  return (
    <div className="h-screen bg-[#212121] text-[#DCE4EE] overflow-auto" style={{ overflowAnchor: 'none' }}>
      <div className="max-w-full p-4">
        <div className="px-5 py-3">
          <div className="card-frame">
            {/* 标题栏 */}
            <div className="flex items-center gap-4 mb-4">
              <button
                onClick={handleBack}
                className="text-[#3b82f6] hover:text-[#2563eb] text-[14px]"
              >
                ← 返回
              </button>
              <h2 className="text-base font-bold flex-1">{project.name}</h2>
              {project.is_default && (
                <span className="px-2 py-0.5 text-[10px] bg-green-600 text-white rounded">
                  默认项目
                </span>
              )}
            </div>

            {/* 项目信息 */}
            <div className="space-y-3 mb-6">
              <div className="flex items-start gap-2">
                <span className="text-[12px] text-[#999999] w-24 flex-shrink-0">工作目录:</span>
                <span className="text-[12px] break-all">{project.working_directory}</span>
              </div>

              <div className="flex items-center gap-2">
                <span className="text-[12px] text-[#999999] w-24 flex-shrink-0">配置模式:</span>
                <span className="text-[12px]">{getModeLabel()}</span>
              </div>

              {project.config.mode === 'claude' && project.config.proxy && (
                <div className="flex items-center gap-2">
                  <span className="text-[12px] text-[#999999] w-24 flex-shrink-0">代理地址:</span>
                  <span className="text-[12px]">{project.config.proxy}</span>
                </div>
              )}

              {project.config.mode === 'codex' && project.config.codex_api_key && (
                <div className="flex items-center gap-2">
                  <span className="text-[12px] text-[#999999] w-24 flex-shrink-0">代理地址:</span>
                  <span className="text-[12px]">{project.config.codex_api_key}</span>
                </div>
              )}

              {project.config.mode === 'custom' && (
                <>
                  <div className="flex items-center gap-2">
                    <span className="text-[12px] text-[#999999] w-24 flex-shrink-0">CLI 工具:</span>
                    <span className="text-[12px]">{project.config.custom_cli === 'codex' ? 'Codex' : 'Claude Code'}</span>
                  </div>
                  {project.config.model && (
                    <div className="flex items-center gap-2">
                      <span className="text-[12px] text-[#999999] w-24 flex-shrink-0">模型:</span>
                      <span className="text-[12px]">{project.config.model}</span>
                    </div>
                  )}
                  {project.config.base_url && (
                    <div className="flex items-center gap-2">
                      <span className="text-[12px] text-[#999999] w-24 flex-shrink-0">Base URL:</span>
                      <span className="text-[12px]">{project.config.base_url}</span>
                    </div>
                  )}
                  {project.config.token && (
                    <div className="flex items-center gap-2">
                      <span className="text-[12px] text-[#999999] w-24 flex-shrink-0">{project.config.custom_cli === 'codex' ? 'API Key:' : 'Token:'}</span>
                      <span className="text-[12px]">••••••••</span>
                    </div>
                  )}
                </>
              )}

              {isRemote && (
                <>
                  <div className="flex items-center gap-2">
                    <span className="text-[12px] text-[#999999] w-24 flex-shrink-0">Server URL:</span>
                    <span className="text-[12px]">{project.config.bridge_server_url}</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-[12px] text-[#999999] w-24 flex-shrink-0">Bind Key:</span>
                    <span className="text-[12px]">
                      {project.config.bridge_bind_key ? '••••••••' : '(未设置)'}
                    </span>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-[12px] text-[#999999] w-24 flex-shrink-0">Agent 端口:</span>
                    <span className="text-[12px]">{project.config.bridge_agent_port}</span>
                  </div>
                </>
              )}

              {!isRemote && (
                <div className="flex items-center gap-2">
                  <span className="text-[12px] text-[#999999] w-24 flex-shrink-0">启动模式:</span>
                  <span className="text-[12px]">
                    {project.config.skip_permissions ? '跳过确认模式' : '普通模式'}
                  </span>
                </div>
              )}

              {project.last_launched_at && (
                <div className="flex items-center gap-2">
                  <span className="text-[12px] text-[#999999] w-24 flex-shrink-0">上次启动:</span>
                  <span className="text-[12px]">
                    {new Date(project.last_launched_at * 1000).toLocaleString()}
                  </span>
                </div>
              )}
            </div>

            {/* 分隔线 */}
            <div className="my-4 h-px bg-gradient-to-r from-transparent via-[#565B5E] to-transparent" />

            {/* Remote mode: Bridge dashboard */}
            {isRemote && (
              <div className="mb-4">
                <h3 className="text-[13px] font-medium mb-3">桥接仪表板</h3>
                <BridgeStatusPanel projectId={project.id} />
              </div>
            )}

            {/* Non-remote mode: Copy command + launch */}
            {!isRemote && (
              <>
                {/* 复制命令 */}
                <div className="flex items-center gap-4 mb-4">
                  <span className="text-[12px] text-[#999999]">复制命令:</span>
                  {platform === 'windows' ? (
                    <>
                      <button
                        onClick={handleCopyPowershell}
                        className="text-[12px] text-[#3b82f6] hover:text-[#2563eb] hover:underline cursor-pointer"
                      >
                        PowerShell
                      </button>
                      <button
                        onClick={handleCopyCmd}
                        className="text-[12px] text-[#3b82f6] hover:text-[#2563eb] hover:underline cursor-pointer"
                      >
                        CMD
                      </button>
                    </>
                  ) : (
                    <button
                      onClick={handleCopyBash}
                      className="text-[12px] text-[#3b82f6] hover:text-[#2563eb] hover:underline cursor-pointer"
                    >
                      Bash / Zsh
                    </button>
                  )}
                  {copySuccess && (
                    <span className="text-[10px] text-[#10b981]">✓ 已复制</span>
                  )}
                </div>

                {/* 操作按钮 */}
                <div className="flex items-center gap-3">
                  <button
                    onClick={handleLaunch}
                    className="flex-1 h-[42px] bg-[#3b82f6] hover:bg-[#2563eb] text-white text-[14px] font-semibold rounded-lg transition-all duration-200"
                  >
                    {project.config.mode === 'codex' ? '启动 Codex' : '启动 Claude Code'}
                  </button>
                  <button
                    onClick={handleEdit}
                    className="px-6 h-[42px] bg-[#565B5E] hover:bg-[#7A8488] text-white text-[14px] rounded-lg transition-colors"
                  >
                    编辑配置
                  </button>
                </div>
              </>
            )}

            {/* Remote mode: Edit button */}
            {isRemote && (
              <div className="flex items-center gap-3">
                <button
                  onClick={handleEdit}
                  className="px-6 h-[42px] bg-[#565B5E] hover:bg-[#7A8488] text-white text-[14px] rounded-lg transition-colors"
                >
                  编辑配置
                </button>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
