import { useState, useEffect } from 'react';
import { remoteApi, bridgeApi } from '../api';
import { BridgeConfigForm } from '../components/BridgeConfigForm';
import { BridgeStatusPanel } from '../components/BridgeStatusPanel';
import { ModeSwitch } from '../components/ModeSwitch';
import { DEFAULT_PROJECT_CONFIG } from '../types/project';
import type { ProjectConfig } from '../types/project';
import ailingQrcode from '../assets/ailing-qrcode.png';

const REMOTE_PROJECT_ID = '__remote__';

export const RemoteBridgePage: React.FC = () => {
  const [config, setConfig] = useState<ProjectConfig>({
    ...DEFAULT_PROJECT_CONFIG,
    mode: 'remote',
  });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saveSuccess, setSaveSuccess] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [fetchingKey, setFetchingKey] = useState(false);
  const [hostname, setHostname] = useState('');
  const [showQrCode, setShowQrCode] = useState(false);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    loadConfig();
    bridgeApi.getHostname().then(setHostname).catch(() => {});
  }, []);

  const loadConfig = async () => {
    try {
      setLoading(true);
      const data = await remoteApi.loadConfig();
      setConfig(data);
    } catch (err) {
      console.error('Failed to load remote config:', err);
    } finally {
      setLoading(false);
    }
  };

  const handleSave = async () => {
    // Validate
    const newErrors: Record<string, string> = {};
    if (!config.bridge_bind_key.trim()) {
      newErrors.bridgeBindKey = '请输入 Bind Key';
    }
    if (Object.keys(newErrors).length > 0) {
      setErrors(newErrors);
      return;
    }
    setErrors({});

    try {
      setSaving(true);
      await remoteApi.saveConfig(config);
      setSaveSuccess(true);
      setTimeout(() => setSaveSuccess(false), 2000);
    } catch (err: any) {
      alert(`保存失败: ${err}`);
    } finally {
      setSaving(false);
    }
  };

  const handleFetchKey = async () => {
    setFetchingKey(true);
    setErrors((e) => {
      const { bridgeBindKey, ...rest } = e;
      return rest;
    });
    try {
      const username = await bridgeApi.getUsername();
      const key = await bridgeApi.getOrCreateKey(username);
      const newConfig = { ...config, bridge_bind_key: key };
      setConfig(newConfig);
      // Auto-save after getting key
      await remoteApi.saveConfig(newConfig);
      setSaveSuccess(true);
      setTimeout(() => setSaveSuccess(false), 2000);
    } catch {
      setErrors({ bridgeBindKey: '获取失败，请联系管理员' });
    } finally {
      setFetchingKey(false);
    }
  };

  const bridgeCommand = hostname && config.bridge_bind_key
    ? `/变身 bridge:${hostname}:${config.bridge_bind_key}`
    : '';

  const handleCopyCommand = async () => {
    if (!bridgeCommand) return;
    try {
      await navigator.clipboard.writeText(bridgeCommand);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // fallback: select text
    }
  };

  if (loading) {
    return (
      <div className="h-screen bg-[#212121] text-[#DCE4EE] flex items-center justify-center">
        <div className="text-[#999999]">加载中...</div>
      </div>
    );
  }

  return (
    <div className="h-screen bg-[#212121] text-[#DCE4EE] overflow-auto">
      <div className="max-w-full p-4">
        <div className="px-5 py-3">
          <div className="card-frame">
            {/* Header */}
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-3">
                <ModeSwitch active="remote" />
                <h2 className="text-base font-bold">远程桥接</h2>
              </div>
            </div>

            {/* Config section */}
            <div className="mb-4">
              <BridgeConfigForm
                bridgeServerUrl={config.bridge_server_url}
                bridgeBindKey={config.bridge_bind_key}
                bridgeAgentPort={config.bridge_agent_port}
                bridgeAgentTimeout={config.bridge_agent_timeout}
                bridgeReconnectInterval={config.bridge_reconnect_interval}
                bridgeHeartbeatInterval={config.bridge_heartbeat_interval}
                bridgeAgentMode={config.bridge_agent_mode}
                bridgeMaxTurns={config.bridge_max_turns}
                modelProxy={config.proxy}
                modelName={config.model}
                modelBaseUrl={config.base_url}
                modelToken={config.token}
                onServerUrlChange={(v) => setConfig((c) => ({ ...c, bridge_server_url: v }))}
                onBindKeyChange={(v) => {
                  setConfig((c) => ({ ...c, bridge_bind_key: v }));
                  if (v.trim()) setErrors((e) => { const { bridgeBindKey, ...rest } = e; return rest; });
                }}
                onAgentPortChange={(v) => setConfig((c) => ({ ...c, bridge_agent_port: v }))}
                onAgentTimeoutChange={(v) => setConfig((c) => ({ ...c, bridge_agent_timeout: v }))}
                onReconnectIntervalChange={(v) => setConfig((c) => ({ ...c, bridge_reconnect_interval: v }))}
                onHeartbeatIntervalChange={(v) => setConfig((c) => ({ ...c, bridge_heartbeat_interval: v }))}
                onAgentModeChange={(v) => setConfig((c) => ({ ...c, bridge_agent_mode: v }))}
                onMaxTurnsChange={(v) => setConfig((c) => ({ ...c, bridge_max_turns: v }))}
                onModelProxyChange={(v) => setConfig((c) => ({ ...c, proxy: v }))}
                onModelNameChange={(v) => setConfig((c) => ({ ...c, model: v }))}
                onModelBaseUrlChange={(v) => setConfig((c) => ({ ...c, base_url: v }))}
                onModelTokenChange={(v) => setConfig((c) => ({ ...c, token: v }))}
                errors={errors}
                onFetchKey={handleFetchKey}
                fetchingKey={fetchingKey}
              />

              <div className="mt-4 flex items-center gap-3">
                <button
                  onClick={handleSave}
                  disabled={saving}
                  className="px-6 h-[36px] bg-[#3b82f6] hover:bg-[#2563eb] disabled:opacity-50 text-white text-[13px] font-medium rounded-lg transition-colors"
                >
                  {saving ? '保存中...' : '保存配置'}
                </button>
                {saveSuccess && (
                  <span className="text-[12px] text-[#10b981]">已保存</span>
                )}
              </div>
            </div>

            {/* Divider */}
            <div className="my-4 h-px bg-gradient-to-r from-transparent via-[#565B5E] to-transparent" />

            {/* Status section */}
            <div>
              <h3 className="text-[13px] font-medium mb-3">桥接状态</h3>
              <BridgeStatusPanel
                projectId={REMOTE_PROJECT_ID}
                agentMode={config.bridge_agent_mode}
                modelProxy={config.proxy}
                onBeforeStart={async () => {
                  await remoteApi.saveConfig(config);
                }}
              />
            </div>

            {/* Divider */}
            <div className="my-4 h-px bg-gradient-to-r from-transparent via-[#565B5E] to-transparent" />

            {/* Connection Tips */}
            <div>
              <h3 className="text-[13px] font-medium mb-3">连接方式</h3>
              <div className="bg-[#2a2a2a] border border-[#3a3a3a] rounded-lg p-3 space-y-3">
                <p className="text-[11px] text-[#999999]">
                  在企微中添加艾灵（测试号），发送以下口令即可连接，输入 /重置 可解绑
                </p>

                {bridgeCommand ? (
                  <div className="flex items-center gap-2 bg-[#1a1a1a] rounded px-3 py-2">
                    <code className="text-[12px] text-[#10b981] flex-1 select-all break-all">
                      {bridgeCommand}
                    </code>
                    <button
                      type="button"
                      onClick={handleCopyCommand}
                      className="px-2 py-1 text-[10px] bg-[#565B5E] hover:bg-[#7A8488] text-white rounded shrink-0 transition-colors"
                    >
                      {copied ? '已复制' : '复制'}
                    </button>
                  </div>
                ) : (
                  <p className="text-[11px] text-[#666666] bg-[#1a1a1a] rounded px-3 py-2">
                    请先获取 Bind Key 并保存配置
                  </p>
                )}

                {/* QR Code */}
                <div>
                  <button
                    type="button"
                    onClick={() => setShowQrCode(!showQrCode)}
                    className="flex items-center gap-1 text-[12px] text-[#999999] hover:text-white transition-colors"
                  >
                    <span className={`transition-transform ${showQrCode ? 'rotate-90' : ''}`}>
                      ▸
                    </span>
                    点击查看二维码，艾灵(测试号)
                  </button>
                  {showQrCode && (
                    <div className="mt-2 flex justify-center">
                      <img
                        src={ailingQrcode}
                        alt="艾灵企微二维码"
                        className="w-36 h-36 rounded"
                      />
                    </div>
                  )}
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
