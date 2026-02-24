import { useState } from 'react';
import { agentConfigApi } from '../api';

interface BridgeConfigFormProps {
  bridgeServerUrl: string;
  bridgeBindKey: string;
  bridgeAgentPort: number;
  bridgeAgentTimeout: number;
  bridgeReconnectInterval: number;
  bridgeHeartbeatInterval: number;
  bridgeAgentMode: 'claude' | 'custom';
  bridgeMaxTurns: number;
  modelProxy: string;
  modelName: string;
  modelBaseUrl: string;
  modelToken: string;
  onServerUrlChange: (v: string) => void;
  onBindKeyChange: (v: string) => void;
  onAgentPortChange: (v: number) => void;
  onAgentTimeoutChange: (v: number) => void;
  onReconnectIntervalChange: (v: number) => void;
  onHeartbeatIntervalChange: (v: number) => void;
  onAgentModeChange: (v: 'claude' | 'custom') => void;
  onMaxTurnsChange: (v: number) => void;
  onModelProxyChange: (v: string) => void;
  onModelNameChange: (v: string) => void;
  onModelBaseUrlChange: (v: string) => void;
  onModelTokenChange: (v: string) => void;
  errors?: Record<string, string>;
}

export const BridgeConfigForm: React.FC<BridgeConfigFormProps> = ({
  bridgeServerUrl,
  bridgeBindKey,
  bridgeAgentPort,
  bridgeAgentTimeout,
  bridgeReconnectInterval,
  bridgeHeartbeatInterval,
  bridgeAgentMode,
  bridgeMaxTurns,
  modelProxy,
  modelName,
  modelBaseUrl,
  modelToken,
  onServerUrlChange,
  onBindKeyChange,
  onAgentPortChange,
  onAgentTimeoutChange,
  onReconnectIntervalChange,
  onHeartbeatIntervalChange,
  onAgentModeChange,
  onMaxTurnsChange,
  onModelProxyChange,
  onModelNameChange,
  onModelBaseUrlChange,
  onModelTokenChange,
  errors = {},
}) => {
  const [showBindKey, setShowBindKey] = useState(false);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [showModelToken, setShowModelToken] = useState(false);
  const [showAgentConfig, setShowAgentConfig] = useState(false);

  return (
    <div className="space-y-3">
      {/* Bind Key — always visible at top */}
      <div>
        <label className="block text-[12px] mb-1">
          Bind Key <span className="text-red-500">*</span>
        </label>
        <div className="flex items-center gap-2">
          <input
            type={showBindKey ? 'text' : 'password'}
            value={bridgeBindKey}
            onChange={(e) => onBindKeyChange(e.target.value)}
            placeholder="请联系管理员获取 Bind Key"
            className="flex-1 px-3 py-2 bg-[#343638] border border-[#565B5E] rounded text-[12px]"
          />
          <button
            type="button"
            onClick={() => setShowBindKey(!showBindKey)}
            className="px-3 py-2 text-[12px] bg-[#565B5E] hover:bg-[#7A8488] text-white rounded"
          >
            {showBindKey ? '隐藏' : '显示'}
          </button>
        </div>
        {errors.bridgeBindKey && (
          <p className="text-[10px] text-red-500 mt-1">{errors.bridgeBindKey}</p>
        )}
        <p className="text-[10px] text-[#999999] mt-1">
          请联系管理员获取，格式如 sk-xxxxxxxx
        </p>
      </div>

      {/* Model Config section */}
      <div className="pt-1">
        <label className="block text-[12px] mb-2">模型配置</label>
        <div className="flex items-center gap-4 mb-3">
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="radio"
              name="bridgeAgentMode"
              value="claude"
              checked={bridgeAgentMode === 'claude'}
              onChange={() => onAgentModeChange('claude')}
              className="w-4 h-4"
            />
            <span className="text-[12px]">原版</span>
          </label>
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="radio"
              name="bridgeAgentMode"
              value="custom"
              checked={bridgeAgentMode === 'custom'}
              onChange={() => onAgentModeChange('custom')}
              className="w-4 h-4"
            />
            <span className="text-[12px]">自定义</span>
          </label>
        </div>

        {bridgeAgentMode === 'claude' && (
          <div>
            <label className="block text-[12px] mb-1">代理地址 (可选)</label>
            <input
              type="text"
              value={modelProxy}
              onChange={(e) => onModelProxyChange(e.target.value)}
              placeholder="例: http://127.0.0.1:7890"
              className="w-full px-3 py-2 bg-[#343638] border border-[#565B5E] rounded text-[12px]"
            />
            {errors.modelProxy && (
              <p className="text-[10px] text-red-500 mt-1">{errors.modelProxy}</p>
            )}
            <p className="text-[10px] text-[#999999] mt-1">
              原版 Claude 服务需要翻墙，可在此处配置代理地址（Agent Server 专用）
            </p>
          </div>
        )}

        {bridgeAgentMode === 'custom' && (
          <div className="space-y-3">
            {/* Model Name */}
            <div>
              <label className="block text-[12px] mb-1">Model Name</label>
              <input
                type="text"
                value={modelName}
                onChange={(e) => onModelNameChange(e.target.value)}
                placeholder="输入模型名称"
                className="w-full px-3 py-2 bg-[#343638] border border-[#565B5E] rounded text-[12px]"
              />
            </div>

            {/* Base URL */}
            <div>
              <label className="block text-[12px] mb-1">Base URL</label>
              <input
                type="text"
                value={modelBaseUrl}
                onChange={(e) => onModelBaseUrlChange(e.target.value)}
                placeholder="例: http://api.example.com"
                className="w-full px-3 py-2 bg-[#343638] border border-[#565B5E] rounded text-[12px]"
              />
              {errors.modelBaseUrl && (
                <p className="text-[10px] text-red-500 mt-1">{errors.modelBaseUrl}</p>
              )}
            </div>

            {/* Auth Token */}
            <div>
              <label className="block text-[12px] mb-1">Auth Token</label>
              <div className="flex items-center gap-2">
                <input
                  type={showModelToken ? 'text' : 'password'}
                  value={modelToken}
                  onChange={(e) => onModelTokenChange(e.target.value)}
                  placeholder="输入认证令牌"
                  className="flex-1 px-3 py-2 bg-[#343638] border border-[#565B5E] rounded text-[12px]"
                />
                <button
                  type="button"
                  onClick={() => setShowModelToken(!showModelToken)}
                  className="px-3 py-2 text-[12px] bg-[#565B5E] hover:bg-[#7A8488] text-white rounded"
                >
                  {showModelToken ? '隐藏' : '显示'}
                </button>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Advanced Config — collapsible */}
      <button
        type="button"
        onClick={() => setShowAdvanced(!showAdvanced)}
        className="flex items-center gap-1 text-[12px] text-[#999999] hover:text-white transition-colors"
      >
        <span className={`transition-transform ${showAdvanced ? 'rotate-90' : ''}`}>
          ▸
        </span>
        高级配置
      </button>

      {showAdvanced && (
        <div className="space-y-3 pl-2 border-l-2 border-[#3a3a3a]">
          {/* Bridge Server URL */}
          <div>
            <label className="block text-[12px] mb-1">Bridge Server URL</label>
            <input
              type="text"
              value={bridgeServerUrl}
              onChange={(e) => onServerUrlChange(e.target.value)}
              placeholder="ws://172.21.11.82:80/bridge"
              className="w-full px-3 py-2 bg-[#343638] border border-[#565B5E] rounded text-[12px]"
            />
            {errors.bridgeServerUrl && (
              <p className="text-[10px] text-red-500 mt-1">{errors.bridgeServerUrl}</p>
            )}
          </div>

          {/* Agent Port */}
          <div>
            <label className="block text-[12px] mb-1">Agent 端口</label>
            <input
              type="number"
              value={bridgeAgentPort}
              onChange={(e) => onAgentPortChange(parseInt(e.target.value, 10) || 5000)}
              min={1}
              max={65535}
              className="w-full px-3 py-2 bg-[#343638] border border-[#565B5E] rounded text-[12px]"
            />
          </div>

          {/* Agent Timeout */}
          <div>
            <label className="block text-[12px] mb-1">Agent 超时 (秒)</label>
            <input
              type="number"
              value={bridgeAgentTimeout}
              onChange={(e) => onAgentTimeoutChange(parseInt(e.target.value, 10) || 1800)}
              min={10}
              max={7200}
              className="w-full px-3 py-2 bg-[#343638] border border-[#565B5E] rounded text-[12px]"
            />
          </div>

          {/* Reconnect Interval */}
          <div>
            <label className="block text-[12px] mb-1">重连间隔 (秒)</label>
            <input
              type="number"
              value={bridgeReconnectInterval}
              onChange={(e) => onReconnectIntervalChange(parseInt(e.target.value, 10) || 5)}
              min={1}
              max={60}
              className="w-full px-3 py-2 bg-[#343638] border border-[#565B5E] rounded text-[12px]"
            />
          </div>

          {/* Heartbeat Interval */}
          <div>
            <label className="block text-[12px] mb-1">心跳间隔 (秒)</label>
            <input
              type="number"
              value={bridgeHeartbeatInterval}
              onChange={(e) => onHeartbeatIntervalChange(parseInt(e.target.value, 10) || 30)}
              min={5}
              max={120}
              className="w-full px-3 py-2 bg-[#343638] border border-[#565B5E] rounded text-[12px]"
            />
          </div>
        </div>
      )}

      {/* Agent Config — collapsible */}
      <button
        type="button"
        onClick={() => setShowAgentConfig(!showAgentConfig)}
        className="flex items-center gap-1 text-[12px] text-[#999999] hover:text-white transition-colors"
      >
        <span className={`transition-transform ${showAgentConfig ? 'rotate-90' : ''}`}>
          ▸
        </span>
        Agent 配置
      </button>

      {showAgentConfig && (
        <div className="space-y-1.5 pl-2 border-l-2 border-[#3a3a3a]">
          <p className="text-[10px] text-[#999999] mb-2">
            配置文件位于用户数据目录，修改后重启桥接生效
          </p>

          {/* Max Turns */}
          <div>
            <label className="block text-[12px] mb-1">Max Turns</label>
            <input
              type="number"
              value={bridgeMaxTurns}
              onChange={(e) => onMaxTurnsChange(parseInt(e.target.value, 10) || 3)}
              min={1}
              max={200}
              className="w-full px-3 py-2 bg-[#343638] border border-[#565B5E] rounded text-[12px]"
            />
          </div>
          {[
            { label: '身份人格', desc: 'soul.md', type: 'file' as const, name: 'soul' },
            { label: '系统提示', desc: 'system_prompt.md', type: 'file' as const, name: 'system_prompt' },
            { label: 'MCP 配置', desc: '.mcp.json', type: 'file' as const, name: 'mcp' },
            { label: '技能目录', desc: '.claude/skills/', type: 'folder' as const, name: 'skills' },
            { label: '允许工具', desc: 'allowed_tools.txt', type: 'file' as const, name: 'allowed_tools' },
            { label: '项目说明', desc: 'CLAUDE.md', type: 'file' as const, name: 'claude_md' },
            { label: '环境配置', desc: '.env', type: 'file' as const, name: 'env' },
          ].map((item) => (
            <div key={item.name} className="flex items-center justify-between py-1">
              <div className="flex-1 min-w-0">
                <span className="text-[12px] text-white">{item.label}</span>
                <span className="text-[10px] text-[#999999] ml-2">({item.desc})</span>
              </div>
              <button
                type="button"
                onClick={() => {
                  if (item.type === 'folder') {
                    agentConfigApi.openFolder(item.name).catch(() => {});
                  } else {
                    agentConfigApi.openFile(item.name).catch(() => {});
                  }
                }}
                className="px-2 py-1 text-[10px] bg-[#565B5E] hover:bg-[#7A8488] text-white rounded shrink-0 ml-2"
              >
                打开
              </button>
            </div>
          ))}
          {/* Quick access to root folder */}
          <div className="flex items-center justify-between py-1 mt-1 pt-2 border-t border-[#3a3a3a]">
            <div className="flex-1 min-w-0">
              <span className="text-[12px] text-white">数据目录</span>
              <span className="text-[10px] text-[#999999] ml-2">(全部配置文件)</span>
            </div>
            <button
              type="button"
              onClick={() => agentConfigApi.openFolder('root').catch(() => {})}
              className="px-2 py-1 text-[10px] bg-[#565B5E] hover:bg-[#7A8488] text-white rounded shrink-0 ml-2"
            >
              打开文件夹
            </button>
          </div>
        </div>
      )}
    </div>
  );
};
