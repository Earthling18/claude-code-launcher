import { useState } from 'react';

interface ConfigPanelProps {
  mode: 'claude' | 'custom' | 'codex';
  onModeChange: (mode: 'claude' | 'custom' | 'codex') => void;
  proxy: string;
  onProxyChange: (value: string) => void;
  model: string;
  onModelChange: (value: string) => void;
  baseUrl: string;
  onBaseUrlChange: (value: string) => void;
  token: string;
  onTokenChange: (value: string) => void;
  skipPermissions: boolean;
  onSkipPermissionsChange: (value: boolean) => void;
  codexProxy: string;
  onCodexProxyChange: (value: string) => void;
  customCli: 'claude' | 'codex';
  onCustomCliChange: (value: 'claude' | 'codex') => void;
  onLaunch: () => void;
  onCopyPowershell: () => void;
  onCopyCmd: () => void;
  onCopyBash: () => void;
  copySuccess: boolean;
  platform: 'windows' | 'macos' | 'linux' | 'unknown';
}

export const ConfigPanel: React.FC<ConfigPanelProps> = ({
  mode,
  onModeChange,
  proxy,
  onProxyChange,
  model,
  onModelChange,
  baseUrl,
  onBaseUrlChange,
  token,
  onTokenChange,
  skipPermissions,
  onSkipPermissionsChange,
  codexProxy,
  onCodexProxyChange,
  customCli,
  onCustomCliChange,
  onLaunch,
  onCopyPowershell,
  onCopyCmd,
  onCopyBash,
  copySuccess,
  platform,
}) => {
  const [showToken, setShowToken] = useState(false);

  return (
    <div className="px-5 py-3">
      <div className="card-frame">
        {/* 标题和模式选择 */}
        <div className="flex items-center gap-4 mb-3">
          <h2 className="text-base font-bold">配置参数</h2>

          <label className="flex items-center gap-2 cursor-pointer">
          <input
            type="radio"
            name="mode"
            value="claude"
            checked={mode === 'claude'}
            onChange={() => onModeChange('claude')}
            className="w-4 h-4"
          />
          <span className="text-[12px]">Claude 账号</span>
        </label>

        <label className="flex items-center gap-2 cursor-pointer">
          <input
            type="radio"
            name="mode"
            value="codex"
            checked={mode === 'codex'}
            onChange={() => onModeChange('codex')}
            className="w-4 h-4"
          />
          <span className="text-[12px]">Codex 账号</span>
        </label>

        <label className="flex items-center gap-2 cursor-pointer">
          <input
            type="radio"
            name="mode"
            value="custom"
            checked={mode === 'custom'}
            onChange={() => onModeChange('custom')}
            className="w-4 h-4"
          />
          <span className="text-[12px]">自定义模型</span>
        </label>
      </div>

      {/* Claude 账号模式 */}
      {mode === 'claude' && (
        <div>
          <label className="block text-[12px] px-5 py-1">
            代理地址 (可选):
          </label>
          <input
            type="text"
            value={proxy}
            onChange={(e) => onProxyChange(e.target.value)}
            placeholder="例: http://127.0.0.1:7890"
            className="w-full px-3 py-2 bg-[#343638] border border-[#565B5E] rounded text-[12px] mx-5"
            style={{ width: 'calc(100% - 40px)' }}
          />
          <p className="text-[10px] text-[#999999] px-5 py-1 max-w-[480px]">
            原版claude服务需要翻墙,可在此处配置代理地址,也可不填写,自行翻墙后使用
          </p>
        </div>
      )}

      {/* Codex 账号模式 */}
      {mode === 'codex' && (
        <div>
          <label className="block text-[12px] px-5 py-1">
            代理地址 (可选):
          </label>
          <input
            type="text"
            value={codexProxy}
            onChange={(e) => onCodexProxyChange(e.target.value)}
            placeholder="例: http://127.0.0.1:7890"
            className="w-full px-3 py-2 bg-[#343638] border border-[#565B5E] rounded text-[12px] mx-5"
            style={{ width: 'calc(100% - 40px)' }}
          />
          <p className="text-[10px] text-[#999999] px-5 py-1 max-w-[480px]">
            原版 Codex 服务需要翻墙，可在此处配置代理地址
          </p>
        </div>
      )}

      {/* 自定义模型模式 */}
      {mode === 'custom' && (
        <div className="space-y-3">
          {/* CLI 工具选择 */}
          <div className="px-5">
            <label className="block text-[12px] mb-2">CLI 工具:</label>
            <div className="flex items-center gap-4">
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="radio"
                  name="customCli"
                  value="claude"
                  checked={customCli === 'claude'}
                  onChange={() => onCustomCliChange('claude')}
                  className="w-4 h-4"
                />
                <span className="text-[12px]">Claude Code</span>
              </label>
              <label className="flex items-center gap-2 opacity-40 cursor-not-allowed">
                <input
                  type="radio"
                  name="customCli"
                  value="codex"
                  disabled
                  className="w-4 h-4"
                />
                <span className="text-[12px]">Codex (暂不支持)</span>
              </label>
            </div>
          </div>

          {/* Model Name */}
          <div>
            <label className="block text-[12px] px-5 py-1">
              Model Name (可选):
            </label>
            <input
              type="text"
              value={model}
              onChange={(e) => onModelChange(e.target.value)}
              placeholder="输入模型名称，留空使用默认模型"
              className="w-full px-3 py-2 bg-[#343638] border border-[#565B5E] rounded text-[12px] mx-5"
              style={{ width: 'calc(100% - 40px)' }}
            />
          </div>

          {/* Base URL / Provider */}
          <div>
            <label className="block text-[12px] px-5 py-1">
              Base URL (可选):
            </label>
            <input
              type="text"
              value={baseUrl}
              onChange={(e) => onBaseUrlChange(e.target.value)}
              placeholder="例: http://api.example.com"
              className="w-full px-3 py-2 bg-[#343638] border border-[#565B5E] rounded text-[12px] mx-5"
              style={{ width: 'calc(100% - 40px)' }}
            />
            {customCli !== 'codex' && (
              <p className="text-[10px] text-[#999999] px-5 py-1 max-w-[480px]">
                行内模型,请使用uat环境的,API可联系艾灵申请
              </p>
            )}
          </div>

          {/* Auth Token / API Key */}
          <div>
            <label className="block text-[12px] px-5 py-1">
              {customCli === 'codex' ? 'API Key (可选):' : 'Auth Token (可选):'}
            </label>
            <div className="flex items-center gap-2 mx-5" style={{ width: 'calc(100% - 40px)' }}>
              <input
                type={showToken ? 'text' : 'password'}
                value={token}
                onChange={(e) => onTokenChange(e.target.value)}
                placeholder={customCli === 'codex' ? '输入 API Key' : '输入认证令牌'}
                className="flex-1 px-3 py-2 bg-[#343638] border border-[#565B5E] rounded text-[12px]"
              />
              <button
                onClick={() => setShowToken(!showToken)}
                className="px-3 py-2 text-[12px] bg-[#565B5E] hover:bg-[#7A8488] text-white rounded"
              >
                {showToken ? '隐藏' : '显示'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 启动模式选择 */}
      <div className="px-5 mt-4">
        <div className="flex items-center gap-4">
          <span className="text-[12px]">启动模式:</span>
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="radio"
              name="launchMode"
              checked={!skipPermissions}
              onChange={() => onSkipPermissionsChange(false)}
              className="w-4 h-4"
            />
            <span className="text-[12px]">普通模式</span>
          </label>
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="radio"
              name="launchMode"
              checked={skipPermissions}
              onChange={() => onSkipPermissionsChange(true)}
              className="w-4 h-4"
            />
            <span className="text-[12px]">跳过确认模式</span>
          </label>
        </div>
        <p className="text-[10px] text-[#999999] mt-1">
          跳过确认模式会跳过权限确认提示，适合自动化场景
        </p>
      </div>

      {/* Separator line */}
      <div className="my-4 mx-5 h-px bg-gradient-to-r from-transparent via-[#565B5E] to-transparent" />

      {/* Launch controls section */}
      <div className="px-5">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-4">
            <span className="text-[12px] text-[#999999]">复制命令:</span>
            {platform === 'windows' ? (
              <>
                <button
                  onClick={onCopyPowershell}
                  className="text-[12px] text-[#3b82f6] hover:text-[#2563eb] hover:underline cursor-pointer"
                >
                  PowerShell
                </button>
                <button
                  onClick={onCopyCmd}
                  className="text-[12px] text-[#3b82f6] hover:text-[#2563eb] hover:underline cursor-pointer"
                >
                  CMD
                </button>
              </>
            ) : (
              <button
                onClick={onCopyBash}
                className="text-[12px] text-[#3b82f6] hover:text-[#2563eb] hover:underline cursor-pointer"
              >
                Bash / Zsh
              </button>
            )}
            {copySuccess && (
              <span className="text-[10px] text-[#10b981]">✓ 已复制</span>
            )}
          </div>
        </div>

        <button
          onClick={onLaunch}
          className="w-full h-[42px] bg-[#3b82f6] hover:bg-[#2563eb] text-white text-[14px] font-semibold rounded-lg transition-all duration-200 hover:shadow-lg hover:-translate-y-0.5"
        >
          {mode === 'codex' ? '启动 Codex' : '启动 Claude Code'}
        </button>
      </div>
      </div>
    </div>
  );
};
