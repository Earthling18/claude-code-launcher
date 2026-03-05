/**
 * Mobot Bridge Configuration UI
 *
 * Single-page application for managing Mobot Bridge configuration,
 * channels, services, and skills.
 */

(function () {
    'use strict';

    // ========== API Client ==========

    const API = {
        base: '/api/config',

        async get(path) {
            const resp = await fetch(this.base + path);
            if (!resp.ok) throw new Error(`GET ${path}: ${resp.status} ${resp.statusText}`);
            return resp.json();
        },

        async post(path, body, options = {}) {
            const resp = await fetch(this.base + path, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
                ...options,  // 支持传入signal等选项
            });
            if (!resp.ok) {
                const text = await resp.text();
                throw new Error(`POST ${path}: ${resp.status} - ${text}`);
            }
            return resp.json();
        },

        async del(path) {
            const resp = await fetch(this.base + path, { method: 'DELETE' });
            if (!resp.ok) throw new Error(`DELETE ${path}: ${resp.status} ${resp.statusText}`);
            return resp.json();
        },
    };

    // ========== Toast Notifications ==========

    function toast(message, type = 'success', duration = 3000) {
        const container = document.getElementById('toast-container');
        const el = document.createElement('div');
        el.className = `toast ${type}`;
        const iconMap = { success: 'check_circle', error: 'cancel', warning: 'warning' };
        const iconName = iconMap[type] || 'info';
        el.innerHTML = `<span class="ms" style="font-size:16px">${iconName}</span> ${esc(message)}`;
        container.appendChild(el);
        setTimeout(() => {
            el.classList.add('fade-out');
            el.addEventListener('animationend', () => el.remove());
        }, duration);
    }

    // ========== Confirm Dialog ==========

    function confirm(title, message) {
        return new Promise((resolve) => {
            const overlay = document.createElement('div');
            overlay.className = 'dialog-overlay';
            overlay.innerHTML = `
                <div class="dialog">
                    <div class="dialog-title">${esc(title)}</div>
                    <div class="dialog-message">${esc(message)}</div>
                    <div class="dialog-actions">
                        <button class="btn btn-secondary btn-sm" data-action="cancel">取消</button>
                        <button class="btn btn-danger btn-sm" data-action="confirm">确认</button>
                    </div>
                </div>
            `;
            document.body.appendChild(overlay);
            overlay.addEventListener('click', (e) => {
                const action = e.target.dataset.action;
                if (action === 'confirm') { overlay.remove(); resolve(true); }
                else if (action === 'cancel' || e.target === overlay) { overlay.remove(); resolve(false); }
            });
        });
    }

    // ========== Utility ==========

    function esc(str) {
        if (str == null) return '';
        const div = document.createElement('div');
        div.textContent = String(str);
        return div.innerHTML;
    }

    function loading() {
        return '<div class="loading-overlay"><div class="spinner"></div> 加载中...</div>';
    }

    function statusBadge(running) {
        if (running === true) return '<span class="badge badge-success"><span class="badge-dot badge-dot-success"></span> 运行中</span>';
        if (running === false) return '<span class="badge badge-danger"><span class="badge-dot badge-dot-danger"></span> 已停止</span>';
        return '<span class="badge badge-muted"><span class="badge-dot badge-dot-muted"></span> 未知</span>';
    }

    function formatUptime(seconds) {
        if (!seconds || seconds < 0) return '-';

        const days = Math.floor(seconds / 86400);
        const hours = Math.floor((seconds % 86400) / 3600);
        const minutes = Math.floor((seconds % 3600) / 60);
        const secs = seconds % 60;

        if (days > 0) {
            return `${days}d ${hours}h`;
        } else if (hours > 0) {
            return `${hours}h ${minutes}m`;
        } else if (minutes > 0) {
            return `${minutes}m ${secs}s`;
        } else {
            return `${secs}s`;
        }
    }

    function startUptimeCounter() {
        // 清除已有定时器
        if (uptimeInterval) {
            clearInterval(uptimeInterval);
        }

        // 每秒更新一次
        uptimeInterval = setInterval(() => {
            if (!serviceStartTime) return;

            const now = Math.floor(Date.now() / 1000);
            const uptime = now - serviceStartTime;
            const uptimeEl = document.querySelector('.uptime-value');

            if (uptimeEl) {
                uptimeEl.textContent = formatUptime(uptime);
            }
        }, 1000);
    }

    // ========== State ==========

    let currentPage = 'model';
    let envData = {};
    let serviceStartTime = null;  // 服务启动时间戳（秒）
    let uptimeInterval = null;     // 倒计时定时器

    // ========== Router ==========

    const pages = {
        model: { title: '模型设置', render: renderModelConfig },
        soul: { title: 'Persona 编辑器', render: renderSoulEditor },
        channels: { title: '消息通道', render: renderChannels },
        whitelist: { title: '白名单', render: renderWhitelist },
        skills: { title: 'Skills', render: renderSkills },
        cron: { title: '定时任务', render: renderCronJobs },
        logs: { title: '服务日志', render: renderLogs },
    };

    function navigate(page) {
        if (!pages[page]) return;
        currentPage = page;

        // Clean up logs auto-refresh when navigating away
        if (_logsAutoRefresh) {
            clearInterval(_logsAutoRefresh);
            _logsAutoRefresh = null;
        }

        // Update nav
        document.querySelectorAll('.nav-item').forEach((el) => {
            el.classList.toggle('active', el.dataset.page === page);
        });

        // Update title
        document.getElementById('page-title').textContent = pages[page].title;

        // Close mobile sidebar
        document.getElementById('sidebar').classList.remove('open');

        // Render
        const body = document.getElementById('content-body');
        body.innerHTML = loading();
        pages[page].render(body);
    }

    // ========== Page: Model Config ==========

    async function renderModelConfig(container) {
        try {
            const resp = await API.get('/env');
            envData = resp.env || {};
        } catch (e) {
            container.innerHTML = `<div class="card"><div class="card-body"><p style="color:var(--error)">加载配置失败： ${esc(e.message)}</p></div></div>`;
            return;
        }

        // Determine current auth mode
        const authMode = envData.WECOM_CLAUDE_AUTH_MODE || 'oauth';

        let oauthStatusHtml = '';
        if (authMode === 'oauth') {
            try {
                const oauthData = await API.get('/oauth/status');
                const valid = oauthData.valid;
                oauthStatusHtml = `
                    <div class="oauth-status">
                        ${valid
                            ? '<span class="badge badge-success"><span class="badge-dot badge-dot-success"></span> 已连接</span>'
                            : '<span class="badge badge-danger"><span class="badge-dot badge-dot-danger"></span> 未连接 - 请运行 <code>claude login</code></span>'}
                    </div>
                `;
            } catch {
                oauthStatusHtml = '<div class="oauth-status"><span class="badge badge-muted">无法检查 OAuth 状态</span></div>';
            }
        }

        container.innerHTML = `
            <div class="card">
                <div class="card-header">
                    <div>
                        <div class="card-title">认证方式</div>
                        <div class="card-subtitle">选择连接 Mbot 的方式</div>
                    </div>
                    <span class="auth-mode-badge">
                        ${authMode === 'oauth' ? 'OAuth' : 'API Key'}
                    </span>
                </div>
                <div class="card-body">
                    <div class="tab-group">
                        <button class="tab-btn ${authMode === 'key' ? 'active' : ''}" data-tab="key">API Key</button>
                        <button class="tab-btn ${authMode === 'oauth' ? 'active' : ''}" data-tab="oauth">OAuth 登录</button>
                    </div>

                    <!-- OAuth Tab -->
                    <div class="tab-content ${authMode === 'oauth' ? 'active' : ''}" id="tab-oauth">
                        ${oauthStatusHtml}
                        <p class="form-hint">OAuth 模式使用 Claude Code 登录凭证。运行 <code>claude login</code> 完成认证。</p>

                        <div class="form-group">
                            <label class="form-label">当前模型</label>
                            <input class="form-input" value="claude-opus-4-6" readonly style="background:var(--bg-input);color:var(--text-hint)">
                            <div class="form-hint">OAuth 模式使用默认模型</div>
                        </div>

                        <hr class="section-divider">
                        <div class="form-group">
                            <label class="form-label">代理 <span style="color:var(--text-hint);font-weight:normal">（可选）</span></label>
                            <input class="form-input" id="env-proxy-oauth" value="${esc(envData.WECOM_CLAUDE_HTTP_PROXY || envData.WECOM_CLAUDE_HTTPS_PROXY || '')}" placeholder="http://proxy.company.com:8080">
                            <div class="form-hint">自动检测：http:// 写入 HTTP_PROXY，https:// 写入 HTTPS_PROXY</div>
                        </div>
                    </div>

                    <!-- API Key Tab -->
                    <div class="tab-content ${authMode === 'key' ? 'active' : ''}" id="tab-key">
                        <div class="form-group">
                            <label class="form-label">API 地址</label>
                            <input class="form-input" id="env-api-base" value="${esc(envData.WECOM_CLAUDE_API_BASE || '')}" placeholder="https://api.anthropic.com">
                            <div class="form-hint">Claude API 端点（支持第三方 API）</div>
                        </div>
                        <div class="form-group">
                            <label class="form-label">API Key</label>
                            <input class="form-input" id="env-api-key" value="${esc(envData.WECOM_CLAUDE_API_KEY || '')}" placeholder="sk-ant-...">
                        </div>
                        <div class="form-group">
                            <label class="form-label">模型</label>
                            <input class="form-input" id="env-model" value="${esc(envData.WECOM_CLAUDE_MODEL || '')}" placeholder="glm-5">
                            <div class="form-hint" style="line-height:1.6;">
                                <strong>推荐：</strong>GLM-5（深度适配）、Minimax M2.5（暂不支持视觉）<br>
                                <span style="color:var(--warning);">Qwen 系列模型兼容性较差</span>
                            </div>
                        </div>
                        <div class="form-group">
                            <label class="form-label">轻量/快速模型 <span style="color:var(--text-hint);font-weight:normal">（可选）</span></label>
                            <input class="form-input" id="env-small-model" value="${esc(envData.WECOM_CLAUDE_SMALL_FAST_MODEL || '')}" placeholder="留空使用默认模型 (Haiku)">
                            <div class="form-hint">用于预检查和快速任务的模型</div>
                        </div>
                        <hr class="section-divider">
                        <div class="form-group">
                            <label class="form-label">代理 <span style="color:var(--text-hint);font-weight:normal">（可选）</span></label>
                            <input class="form-input" id="env-proxy-key" value="${esc(envData.WECOM_CLAUDE_HTTP_PROXY || envData.WECOM_CLAUDE_HTTPS_PROXY || '')}" placeholder="http://proxy.company.com:8080">
                            <div class="form-hint">自动检测：http:// 写入 HTTP_PROXY，https:// 写入 HTTPS_PROXY</div>
                        </div>
                    </div>

                    <div class="btn-group" style="margin-top:16px">
                        <button class="btn btn-primary" onclick="App.saveModelConfig()"><span class="ms" style="font-size:14px">save</span> 保存</button>
                    </div>
                </div>
            </div>
        `;

        // Tab switching
        container.querySelectorAll('.tab-btn').forEach((btn) => {
            btn.addEventListener('click', () => {
                container.querySelectorAll('.tab-btn').forEach((b) => b.classList.remove('active'));
                container.querySelectorAll('.tab-content').forEach((c) => c.classList.remove('active'));
                btn.classList.add('active');
                document.getElementById('tab-' + btn.dataset.tab).classList.add('active');
            });
        });
    }

    // ========== Page: Soul.md Editor ==========

    async function renderSoulEditor(container) {
        let content = '';
        try {
            const resp = await API.get('/soul');
            content = resp.content || '';
        } catch (e) {
            container.innerHTML = `<div class="card"><div class="card-body"><p style="color:var(--error)">加载 Persona 配置失败： ${esc(e.message)}</p></div></div>`;
            return;
        }

        container.innerHTML = `
            <div class="card">
                <div class="card-header">
                    <div>
                        <div class="card-title">Persona 编辑器</div>
                        <div class="card-subtitle">定义 AI 的身份、人格和行为风格</div>
                    </div>
                    <button class="btn btn-primary" onclick="App.saveSoul()"><span class="ms" style="font-size:14px">save</span> 保存</button>
                </div>
                <div class="card-body">
                    <div class="form-group">
                        <textarea class="form-textarea soul-editor" id="soul-editor" spellcheck="false">${esc(content)}</textarea>
                    </div>
                </div>
            </div>
        `;
    }

    // ========== Page: Channel Management ==========

    function onlineIndicator(running) {
        if (running === true) {
            return '<div style="display:flex;align-items:center;gap:8px;"><div style="width:10px;height:10px;border-radius:50%;background:var(--success);box-shadow:0 0 6px var(--success);animation:pulse 2s ease-in-out infinite;"></div><span style="color:var(--success);font-weight:600;font-size:13px;">在线</span></div>';
        }
        if (running === null) {
            return '<div style="display:flex;align-items:center;gap:8px;"><div style="width:10px;height:10px;border-radius:50%;background:var(--warning);animation:pulse 1.5s ease-in-out infinite;"></div><span style="color:var(--warning);font-size:13px;">检测中...</span></div>';
        }
        return '<div style="display:flex;align-items:center;gap:8px;"><div style="width:10px;height:10px;border-radius:50%;background:var(--text-hint);"></div><span style="color:var(--text-hint);font-size:13px;">离线</span></div>';
    }

    async function renderChannels(container) {
        let bridgeConfig = {};
        let feishuConfig = {};
        let svcBridge = {};
        let svcFeishu = {};

        try {
            const results = await Promise.allSettled([
                API.get('/bridge'),
                API.get('/env'),
            ]);
            if (results[0].status === 'fulfilled') {
                bridgeConfig = results[0].value.config || {};
            }
            if (results[1].status === 'fulfilled') {
                const env = results[1].value.env || {};
                feishuConfig = {
                    enabled: !!(env.FEISHU_APP_ID && env.FEISHU_APP_SECRET),
                    app_id: env.FEISHU_APP_ID || '',
                    app_secret: env.FEISHU_APP_SECRET || '',
                };
                envData = env;
            }
            svcBridge = { running: null };
            svcFeishu = { running: null };
        } catch (e) {
            // partial load is ok
        }

        // Extract bridge client config
        const client = bridgeConfig.client || {};

        container.innerHTML = `
            <div class="channels-row">
                <!-- 企业微信通道 -->
                <div class="channel-section">
                    <div class="card">
                        <div class="card-header">
                            <div>
                                <div class="card-title">企业微信</div>
                                <div class="card-subtitle">企业微信通道</div>
                            </div>
                            <div class="bridge-online-indicator" style="display:flex;flex-direction:column;align-items:flex-end;gap:4px;">
                                ${onlineIndicator(svcBridge.running)}
                            </div>
                        </div>
                        <div class="card-body">
                            <div class="form-group">
                                <label class="form-label">机器人 ID</label>
                                <input class="form-input" id="wecom-dep-user-id" value="${esc(envData.WECOM_SENDMSG_DEP_USER_ID || '')}" placeholder="请联系管理员">
                            </div>
                            <div class="form-group">
                                <label class="form-label">推送密钥</label>
                                <input class="form-input" id="wecom-sendmsg-auth-key" value="${esc(envData.WECOM_SENDMSG_AUTH_KEY || '')}" placeholder="请联系管理员">
                            </div>
                            <hr class="section-divider">
                            <div class="btn-group">
                                <button class="btn btn-primary" onclick="App.saveWecomConfig()"><span class="ms" style="font-size:14px">save</span> 保存</button>
                            </div>
                            <hr class="section-divider">
                            <div class="bind-key-section">
                                <label class="form-label">Bridge 连接</label>
                                <div id="bind-key-area"><div class="loading-overlay" style="padding:16px"><div class="spinner"></div></div></div>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- 飞书通道 -->
                <div class="channel-section">
                    <div class="card">
                        <div class="card-header">
                            <div>
                                <div class="card-title">飞书</div>
                                <div class="card-subtitle">飞书通道</div>
                            </div>
                            <div class="feishu-online-indicator">
                                ${onlineIndicator(svcFeishu.running)}
                            </div>
                        </div>
                        <div class="card-body">
                            <div class="form-row">
                                <div class="form-group">
                                    <label class="form-label">App ID</label>
                                    <input class="form-input" id="feishu-app-id" value="${esc(feishuConfig.app_id)}" placeholder="cli_...">
                                </div>
                                <div class="form-group">
                                    <label class="form-label">App Secret</label>
                                    <input class="form-input" id="feishu-app-secret" value="${esc(feishuConfig.app_secret)}">
                                </div>
                            </div>
                            <hr class="section-divider">
                            <div class="btn-group">
                                <button class="btn btn-primary" onclick="App.saveFeishu()"><span class="ms" style="font-size:14px">save</span> 保存</button>
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            <div style="text-align:center;font-size:11px;color:var(--text-hint);margin-top:8px;">
                通道状态每 2 秒自动刷新
            </div>
        `;

        // Load bind key status (async, non-blocking)
        initBindKeyArea();

        // Immediately fetch service status and update indicators (async, non-blocking)
        (async () => {
            try {
                const resp = await API.get('/services/status');
                const services = resp.services || {};

                const bridgeIndicator = document.querySelector('.bridge-online-indicator');
                if (bridgeIndicator) {
                    const bridgeCs = services.bridge?.channel_status;
                    const bridgeOnline = bridgeCs === 'connected' ? true : bridgeCs === 'starting' ? null : false;
                    const bridgePid = services.bridge?.pid;
                    const bridgeMultiple = services.bridge?.multiple_processes;
                    let html = onlineIndicator(bridgeOnline);
                    if (bridgeOnline && bridgePid) {
                        html += `<span style="font-size:11px;color:var(--text-hint);">PID: ${bridgePid}</span>`;
                    }
                    if (bridgeMultiple) {
                        html += '<span class="badge badge-warning" style="font-size:10px;">检测到多个进程</span>';
                    }
                    bridgeIndicator.innerHTML = html;
                }

                const feishuIndicator = document.querySelector('.feishu-online-indicator');
                if (feishuIndicator) {
                    const feishuCs = services.feishu?.channel_status;
                    const feishuOnline = feishuCs === 'connected' ? true : feishuCs === 'starting' ? null : false;
                    feishuIndicator.innerHTML = onlineIndicator(feishuOnline);
                }
            } catch (e) {
                // On error, show offline state
                const bridgeIndicator = document.querySelector('.bridge-online-indicator');
                if (bridgeIndicator) bridgeIndicator.innerHTML = onlineIndicator(false);
                const feishuIndicator = document.querySelector('.feishu-online-indicator');
                if (feishuIndicator) feishuIndicator.innerHTML = onlineIndicator(false);
            }
        })();

        // 启动自动刷新（仅在channels页面）
        if (window.channelRefreshInterval) {
            clearInterval(window.channelRefreshInterval);
        }

        window.channelRefreshInterval = setInterval(async () => {
            if (currentPage === 'channels') {
                // 静默刷新状态，不重新渲染整个页面
                try {
                    const resp = await API.get('/services/status');

                    // 更新在线指示器
                    const bridgeIndicator = document.querySelector('.bridge-online-indicator');
                    const feishuIndicator = document.querySelector('.feishu-online-indicator');

                    if (bridgeIndicator && resp.services && resp.services.bridge) {
                        const bridgeCs = resp.services.bridge.channel_status;
                        const bridgeOnline = bridgeCs === 'connected' ? true : bridgeCs === 'starting' ? null : false;
                        bridgeIndicator.querySelector('div').outerHTML = onlineIndicator(bridgeOnline);
                    }
                    if (feishuIndicator && resp.services && resp.services.feishu) {
                        const feishuCs = resp.services.feishu.channel_status;
                        const feishuOnline = feishuCs === 'connected' ? true : feishuCs === 'starting' ? null : false;
                        feishuIndicator.innerHTML = onlineIndicator(feishuOnline);
                    }
                } catch (e) {
                    // Ignore errors
                }
            } else {
                // 离开channels页面时清除定时器
                if (window.channelRefreshInterval) {
                    clearInterval(window.channelRefreshInterval);
                    window.channelRefreshInterval = null;
                }
            }
        }, 2000);  // 每2秒刷新一次
    }

    // ========== Page: Whitelist & Permissions ==========

    async function renderWhitelist(container) {
        let userWhitelist = '';
        let adminWhitelist = '';
        let feishuUserWhitelist = '';

        try {
            const [envResp, whitelistResp] = await Promise.allSettled([
                API.get('/env'),
                API.get('/whitelist'),
            ]);

            if (envResp.status === 'fulfilled') {
                envData = envResp.value.env || {};
            }

            if (whitelistResp.status === 'fulfilled') {
                userWhitelist = whitelistResp.value.user_whitelist || '';
                adminWhitelist = whitelistResp.value.admin_whitelist || '';
                feishuUserWhitelist = whitelistResp.value.feishu_user_whitelist || '';
            } else if (whitelistResp.status === 'rejected') {
                console.warn('Whitelist API failed, falling back to env:', whitelistResp.reason);
                userWhitelist = envData.WECOM_USER_WHITELIST || '';
                adminWhitelist = envData.WECOM_ADMIN_WHITELIST || '';
                feishuUserWhitelist = envData.FEISHU_USER_WHITELIST || '';
            }
        } catch (e) {
            container.innerHTML = `<div class="card"><div class="card-body"><p style="color:var(--error)">加载权限配置失败： ${esc(e.message)}</p></div></div>`;
            return;
        }

        const userCount = userWhitelist ? userWhitelist.split(',').filter(s => s.trim()).length : 0;
        const feishuCount = feishuUserWhitelist ? feishuUserWhitelist.split(',').filter(s => s.trim()).length : 0;
        const avatarCount = adminWhitelist ? adminWhitelist.split(',').filter(s => s.trim()).length : 0;

        container.innerHTML = `
            <div class="card">
                <div class="card-header">
                    <div>
                        <div class="card-title">企业微信权限</div>
                        <div class="card-subtitle">控制哪些企业微信用户可以发送消息</div>
                    </div>
                    <span class="badge badge-muted">${userCount} 位用户</span>
                </div>
                <div class="card-body">
                    <div class="form-group">
                        <label class="form-label">企业微信 UM（逗号分隔）</label>
                        <textarea class="form-textarea" id="whitelist-users" rows="4" placeholder="zhangsan(张三), xiaomo(小莫)&#10;留空表示允许所有用户">${esc(userWhitelist)}</textarea>
                        <div class="form-hint">仅列出的用户可以通过企业微信与 Agent 交互。留空 = 不限制。</div>
                    </div>
                </div>
            </div>

            <div class="card">
                <div class="card-header">
                    <div>
                        <div class="card-title">飞书权限</div>
                        <div class="card-subtitle">控制哪些飞书用户可以发送消息</div>
                    </div>
                    <span class="badge badge-muted">${feishuCount} 位用户</span>
                </div>
                <div class="card-body">
                    <div class="form-group">
                        <label class="form-label">Open ID（逗号分隔）</label>
                        <textarea class="form-textarea" id="whitelist-feishu-users" rows="4" placeholder="ou_xxx1, ou_xxx2&#10;留空表示允许所有用户">${esc(feishuUserWhitelist)}</textarea>
                        <div class="form-hint">仅列出的用户可以通过飞书与 Agent 交互。使用 open_id (ou_xxx)。留空 = 不限制。</div>
                    </div>
                </div>
            </div>

            <div class="card">
                <div class="card-header">
                    <div>
                        <div class="card-title">分身管理员</div>
                        <div class="card-subtitle">控制哪些用户可以切换分身的协作和托管模式以及清空历史上下文。企业微信填 UM，飞书填 open_id</div>
                    </div>
                    <span class="badge badge-muted">${avatarCount} 位用户</span>
                </div>
                <div class="card-body">
                    <div class="form-group">
                        <label class="form-label">用户 ID（逗号分隔）</label>
                        <textarea class="form-textarea" id="whitelist-avatar" rows="4" placeholder="zhangsan(张三), xiaomo(小莫)&#10;飞书填 ou_xxx&#10;留空表示不允许任何人切换">${esc(adminWhitelist)}</textarea>
                        <div class="form-hint">留空 = 不允许任何人操作</div>
                    </div>
                </div>
            </div>

            <div class="btn-group" style="margin-top:16px">
                <button class="btn btn-primary" onclick="App.saveWhitelist()"><span class="ms" style="font-size:14px">save</span> 保存</button>
            </div>
        `;

        // Radio button interaction: highlight selected option
        container.querySelectorAll('.avatar-mode-option input[type="radio"]').forEach((radio) => {
            radio.addEventListener('change', () => {
                container.querySelectorAll('.avatar-mode-option').forEach((opt) => opt.classList.remove('selected'));
                radio.closest('.avatar-mode-option').classList.add('selected');
            });
        });
    }

    // ========== Page: Skill Management ==========

    async function renderSkills(container) {
        let skills = [];
        try {
            const resp = await API.get('/skills');
            skills = resp.skills || [];
        } catch (e) {
            container.innerHTML = `<div class="card"><div class="card-body"><p style="color:var(--error)">加载 Skills 失败： ${esc(e.message)}</p></div></div>`;
            return;
        }

        const skillCards = skills.length === 0
            ? `<div class="empty-state">
                <div class="empty-icon"><span class="ms">stars</span></div>
                <p>尚未安装 Skills。上传一个 Skill 文件夹以开始使用。</p>
            </div>`
            : `<div class="skills-grid">
                ${skills.map((s) => `
                    <div class="skill-card">
                        <div class="skill-card-header">
                            <span class="skill-name">${esc(s.display_name || s.name)}</span>
                            <button class="btn btn-danger btn-sm btn-icon" onclick="App.deleteSkill('${esc(s.name)}')" title="删除 Skill">
                                <span class="ms" style="font-size:14px">delete</span>
                            </button>
                        </div>
                        <div class="skill-description">${esc(s.description || '暂无描述')}</div>
                        <div class="skill-meta">
                            ${s.version ? `v${esc(s.version)}` : ''}
                            <span style="color:var(--text-hint);font-family:var(--font-mono)">${esc(s.name)}</span>
                        </div>
                    </div>
                `).join('')}
            </div>`;

        container.innerHTML = `
            <div class="skills-header">
                <div>
                    <h3 style="font-size:14px;font-weight:600;color:var(--text-primary);margin-bottom:4px">已安装的 Skills</h3>
                    <p style="font-size:12px;color:var(--text-hint)">${skills.length} 个 Skills</p>
                </div>
                <div class="btn-group">
                    <button class="btn btn-primary" onclick="App.triggerSkillUpload()"><span class="ms" style="font-size:14px">upload</span> 上传</button>
                    <input type="file" id="skill-folder-input" class="hidden-input" webkitdirectory directory multiple>
                </div>
            </div>
            <div id="skill-drop-zone" class="skill-drop-zone">
                <span class="ms" style="font-size:36px;color:var(--text-hint);margin-bottom:8px;opacity:0.5">upload</span>
                <p style="font-size:13px;color:var(--text-body)">将 Skill 文件夹拖放到此处</p>
                <p style="font-size:11px;color:var(--text-hint);margin-top:4px">文件夹须包含 SKILL.md 文件</p>
            </div>
            ${skillCards}
        `;

        // Set up folder input change handler
        const folderInput = document.getElementById('skill-folder-input');
        folderInput.addEventListener('change', (e) => {
            const files = Array.from(e.target.files);
            if (files.length > 0) uploadSkillFiles(files);
            folderInput.value = '';
        });

        // Set up drag and drop on the drop zone
        const dropZone = document.getElementById('skill-drop-zone');
        dropZone.addEventListener('dragover', (e) => {
            e.preventDefault();
            dropZone.classList.add('drag-over');
        });
        dropZone.addEventListener('dragleave', (e) => {
            e.preventDefault();
            dropZone.classList.remove('drag-over');
        });
        dropZone.addEventListener('drop', async (e) => {
            e.preventDefault();
            dropZone.classList.remove('drag-over');
            const items = e.dataTransfer.items;
            if (!items || items.length === 0) return;
            const files = await readDroppedFolder(items);
            if (files.length > 0) uploadSkillFiles(files);
        });
    }

    // ========== Page: Logs ==========

    let _logsAutoRefresh = null;

    async function renderLogs(container) {
        container.innerHTML = `
            <div class="card">
                <div class="card-body" style="padding:16px">
                    <div style="display:flex;align-items:center;gap:12px;margin-bottom:12px;flex-wrap:wrap">
                        <div style="display:flex;align-items:center;gap:8px">
                            <label style="font-size:12px;color:var(--text-hint);white-space:nowrap">来源</label>
                            <select id="logs-source" style="padding:4px 8px;border:1px solid var(--border);border-radius:var(--radius-sm);background:var(--bg-input);font-size:12px;font-family:var(--font-sans)">
                                <option value="all" selected>全部</option>
                                <option value="service">服务端</option>
                                <option value="bridge">Bridge</option>
                            </select>
                        </div>
                        <div style="display:flex;align-items:center;gap:8px">
                            <label style="font-size:12px;color:var(--text-hint);white-space:nowrap">行数</label>
                            <select id="logs-lines" style="padding:4px 8px;border:1px solid var(--border);border-radius:var(--radius-sm);background:var(--bg-input);font-size:12px;font-family:var(--font-sans)">
                                <option value="100">100</option>
                                <option value="300" selected>300</option>
                                <option value="500">500</option>
                                <option value="1000">1000</option>
                            </select>
                        </div>
                        <div style="display:flex;align-items:center;gap:8px;flex:1;min-width:200px">
                            <label style="font-size:12px;color:var(--text-hint);white-space:nowrap">筛选</label>
                            <input id="logs-filter" type="text" placeholder="如 WORKER, SENDMSG, ERROR"
                                style="padding:4px 8px;border:1px solid var(--border);border-radius:var(--radius-sm);background:var(--bg-input);font-size:12px;font-family:var(--font-mono);flex:1">
                        </div>
                        <div style="display:flex;align-items:center;gap:8px">
                            <label style="font-size:12px;color:var(--text-hint);display:flex;align-items:center;gap:4px;cursor:pointer">
                                <input type="checkbox" id="logs-auto-refresh"> 自动 (5s)
                            </label>
                            <button class="btn btn-secondary btn-sm" onclick="App.copyLogs(this)">
                                <span class="ms" style="font-size:14px">content_copy</span> 复制
                            </button>
                            <button class="btn btn-primary btn-sm" onclick="App.refreshLogs()">
                                <span class="ms" style="font-size:14px">refresh</span> 刷新
                            </button>
                        </div>
                    </div>
                    <div id="logs-status" style="font-size:11px;color:var(--text-hint);margin-bottom:8px"></div>
                    <pre id="logs-content" style="background:#1e1e1e;color:#d4d4d4;padding:16px;border-radius:var(--radius-sm);font-family:var(--font-mono);font-size:11px;line-height:1.6;overflow:auto;max-height:calc(100vh - 220px);white-space:pre;tab-size:4"></pre>
                </div>
            </div>
        `;

        // Auto-refresh checkbox
        document.getElementById('logs-auto-refresh').addEventListener('change', (e) => {
            if (e.target.checked) {
                _logsAutoRefresh = setInterval(() => fetchLogs(), 5000);
            } else {
                clearInterval(_logsAutoRefresh);
                _logsAutoRefresh = null;
            }
        });

        // Source change triggers refresh
        document.getElementById('logs-source').addEventListener('change', () => fetchLogs());

        // Enter key in filter input triggers refresh
        document.getElementById('logs-filter').addEventListener('keydown', (e) => {
            if (e.key === 'Enter') fetchLogs();
        });

        await fetchLogs();
    }

    async function fetchLogs() {
        const linesEl = document.getElementById('logs-lines');
        const filterEl = document.getElementById('logs-filter');
        const sourceEl = document.getElementById('logs-source');
        const contentEl = document.getElementById('logs-content');
        const statusEl = document.getElementById('logs-status');
        if (!contentEl) return; // navigated away

        const lines = linesEl?.value || '300';
        const filter = filterEl?.value || '';
        const source = sourceEl?.value || 'all';

        try {
            let url = `/logs?lines=${lines}&source=${source}`;
            if (filter) url += `&filter=${encodeURIComponent(filter)}`;
            const resp = await API.get(url);
            contentEl.textContent = resp.content || '（空）';
            statusEl.textContent = `${resp.lines} 行 · ${new Date().toLocaleTimeString()}`;
            // Scroll to bottom
            contentEl.scrollTop = contentEl.scrollHeight;
        } catch (e) {
            contentEl.textContent = '加载日志失败：' + e.message;
            statusEl.textContent = '错误';
        }
    }

    // ========== Actions ==========

    // Save model config (writes to .env via partial update)
    async function saveModelConfig() {
        const activeTab = document.querySelector('.tab-btn.active');
        const authMode = activeTab ? activeTab.dataset.tab : 'oauth';

        // Read proxy from whichever tab is active
        const suffix = authMode === 'key' ? '-key' : '-oauth';
        const proxyValue = (document.getElementById('env-proxy' + suffix)?.value || '').trim();

        const updates = {
            WECOM_CLAUDE_AUTH_MODE: authMode,
        };

        // Auto-detect: http:// → HTTP_PROXY, https:// → HTTPS_PROXY
        if (proxyValue.startsWith('https://')) {
            updates.WECOM_CLAUDE_HTTPS_PROXY = proxyValue;
            updates.WECOM_CLAUDE_HTTP_PROXY = '';
        } else if (proxyValue) {
            updates.WECOM_CLAUDE_HTTP_PROXY = proxyValue;
            updates.WECOM_CLAUDE_HTTPS_PROXY = '';
        } else {
            updates.WECOM_CLAUDE_HTTP_PROXY = '';
            updates.WECOM_CLAUDE_HTTPS_PROXY = '';
        }

        if (authMode === 'key') {
            // API Key 模式：读取表单值
            updates.WECOM_CLAUDE_API_BASE = document.getElementById('env-api-base')?.value || '';
            updates.WECOM_CLAUDE_API_KEY = document.getElementById('env-api-key')?.value || '';
            updates.WECOM_CLAUDE_MODEL = document.getElementById('env-model')?.value || '';
            updates.WECOM_CLAUDE_SMALL_FAST_MODEL = document.getElementById('env-small-model')?.value || '';
        } else {
            // OAuth 模式：清除所有 API Key 模式字段
            // 空字符串 → 后端 comment out → pydantic 用默认值
            updates.WECOM_CLAUDE_API_BASE = '';
            updates.WECOM_CLAUDE_API_KEY = '';
            updates.WECOM_CLAUDE_MODEL = '';
            updates.WECOM_CLAUDE_SMALL_FAST_MODEL = '';
        }

        try {
            await API.post('/env', { env: updates });
            toast('配置已保存');
            checkRestartNeeded();
        } catch (e) {
            toast('保存失败：' + e.message, 'error');
        }
    }

    // Save soul.md
    async function saveSoul() {
        const content = document.getElementById('soul-editor')?.value || '';
        try {
            await API.post('/soul', { content });
            toast('Persona 配置已保存');
        } catch (e) {
            toast('保存失败：' + e.message, 'error');
        }
    }


    // ========== Bind Key Management ==========

    async function initBindKeyArea() {
        const area = document.getElementById('bind-key-area');
        if (!area) return;

        try {
            const resp = await fetch('/api/config/bridge/bind-key-status');
            if (!resp.ok) throw new Error(resp.statusText);
            const data = await resp.json();

            if (data.has_key) {
                renderBindKeyCommand(area, data);
            } else {
                renderBindKeyEmpty(area);
            }
        } catch (e) {
            area.innerHTML = `<div style="font-size:12px;color:var(--error)">加载 Bind Key 状态失败</div>`;
        }
    }

    function renderBindKeyCommand(area, data) {
        area.innerHTML = `
            <div class="bind-key-command-box">
                <code class="bind-key-command-text">${esc(data.command)}</code>
                <button class="btn btn-secondary btn-sm" onclick="App.copyBindCommand()" title="复制命令">
                    <span class="ms" style="font-size:14px">content_copy</span>
                </button>
            </div>
            <div class="bind-key-hint">复制此命令，发送给测试环境的艾灵，收到成功回复即表示绑定完成。</div>
            <div class="qrcode-section">
                <div class="qrcode-hint">还没有添加分身？扫码添加企业微信账号：</div>
                <img class="qrcode-img" src="/static/config/ailing-qrcode.jpg" alt="艾灵 企业微信二维码">
            </div>
        `;
    }

    function renderBindKeyEmpty(area) {
        area.innerHTML = `
            <div class="bind-key-empty">
                <p style="margin:0 0 12px;font-size:12px;color:var(--text-hint)">尚未配置 Bind Key。生成一个以连接 Bridge 客户端。</p>
                <button class="btn btn-primary btn-sm" onclick="App.generateBindKey()">
                    <span class="ms" style="font-size:14px">key</span> 生成 Bind Key
                </button>
            </div>
            <div class="qrcode-section">
                <div class="qrcode-hint">还没有添加分身？扫码添加企业微信账号：</div>
                <img class="qrcode-img" src="/static/config/ailing-qrcode.jpg" alt="艾灵 企业微信二维码">
            </div>
        `;
    }

    async function generateBindKey() {
        const area = document.getElementById('bind-key-area');
        if (!area) return;

        // Show loading
        area.innerHTML = `<div class="loading-overlay" style="padding:16px"><div class="spinner"></div> 生成中...</div>`;

        try {
            const resp = await fetch('/api/config/bridge/generate-bind-key', { method: 'POST' });
            if (!resp.ok) {
                const errData = await resp.json().catch(() => ({}));
                throw new Error(errData.detail || `Server returned ${resp.status}`);
            }
            const data = await resp.json();
            renderBindKeyCommand(area, data);
            toast('Bind Key 生成成功');
        } catch (e) {
            toast('生成失败：' + e.message, 'error');
            // Reload status to restore UI
            initBindKeyArea();
        }
    }

    async function copyBindCommand() {
        try {
            const resp = await fetch('/api/config/bridge/bind-key-status');
            if (!resp.ok) throw new Error();
            const data = await resp.json();
            if (!data.command) throw new Error('No command available');

            if (navigator.clipboard) {
                await navigator.clipboard.writeText(data.command);
            } else {
                // Fallback for non-HTTPS
                const ta = document.createElement('textarea');
                ta.value = data.command;
                ta.style.position = 'fixed';
                ta.style.left = '-9999px';
                document.body.appendChild(ta);
                ta.select();
                document.execCommand('copy');
                document.body.removeChild(ta);
            }
            toast('命令已复制到剪贴板');
        } catch (e) {
            toast('复制失败', 'error');
        }
    }

    // Save WeCom (企业微信) configuration (Bot ID + Push Key only; bind key managed separately)
    async function saveWecomConfig() {
        const depUserIdVal = document.getElementById('wecom-dep-user-id')?.value || '';
        const sendmsgAuthKeyVal = document.getElementById('wecom-sendmsg-auth-key')?.value || '';

        const envUpdates = {
            WECOM_SENDMSG_DEP_USER_ID: depUserIdVal,
        };

        if (sendmsgAuthKeyVal) {
            envUpdates.WECOM_SENDMSG_AUTH_KEY = sendmsgAuthKeyVal;
        }

        try {
            await API.post('/env', { env: envUpdates });
            toast('企业微信配置已保存');
            checkRestartNeeded();
        } catch (e) {
            toast('保存失败：' + e.message, 'error');
        }
    }

    // Save Feishu config (writes to .env via partial update)
    async function saveFeishu() {
        const appId = (document.getElementById('feishu-app-id')?.value || '').trim();
        const appSecret = (document.getElementById('feishu-app-secret')?.value || '').trim();

        // Validate: app_id and app_secret must both be set or both be empty
        if ((appId && !appSecret) || (!appId && appSecret)) {
            toast('APP ID 和 APP Secret 须同时填写或同时留空', 'warning');
            return;
        }

        const updates = {
            FEISHU_APP_ID: appId,
            FEISHU_APP_SECRET: appSecret,
        };

        try {
            await API.post('/env', { env: updates });

            // Read back to verify write succeeded
            const readback = await API.get('/env');
            const env = readback.env || {};
            if (appId && env.FEISHU_APP_ID !== appId) {
                toast('配置已保存但回读不一致 — 请手动检查 .env 文件', 'warning');
                return;
            }

            if (appId && appSecret) {
                toast('飞书配置已保存 — 重启服务以启用飞书通道');
            } else {
                toast('飞书配置已清除');
            }
            checkRestartNeeded();
        } catch (e) {
            toast('飞书配置保存失败：' + e.message, 'error');
        }
    }

    // Save avatar mode
    async function saveAvatarMode() {
        const selected = document.querySelector('input[name="avatar-mode"]:checked');
        if (!selected) return;

        try {
            await API.post('/env', { env: { WECOM_AVATAR_MODE: selected.value } });
            toast('响应模式已保存');
        } catch (e) {
            toast('保存响应模式失败：' + e.message, 'error');
        }
    }

    // Save whitelist configuration
    async function saveWhitelist() {
        const userWhitelist = document.getElementById('whitelist-users')?.value || '';
        const feishuUserWhitelist = document.getElementById('whitelist-feishu-users')?.value || '';
        const adminWhitelist = document.getElementById('whitelist-avatar')?.value || '';

        try {
            await API.post('/whitelist', {
                user_whitelist: userWhitelist.trim(),
                feishu_user_whitelist: feishuUserWhitelist.trim(),
                admin_whitelist: adminWhitelist.trim(),
            });
            toast('权限配置已保存');
        } catch (e) {
            toast('保存失败：' + e.message, 'error');
        }
    }

    // Restart service (the only service action the backend supports)
    async function restartService(serviceId) {
        try {
            await API.post('/services/restart', { service: serviceId });
            toast(`${serviceId}：已发送重启请求`);
            setTimeout(() => {
                if (currentPage === 'channels') navigate('channels');
            }, 2000);
        } catch (e) {
            toast(`重启 ${serviceId} 失败：` + e.message, 'error');
        }
    }

    // Trigger hidden folder input click for skill upload
    function triggerSkillUpload() {
        document.getElementById('skill-folder-input')?.click();
    }

    // Read all files from a dropped folder using webkitGetAsEntry API
    async function readDroppedFolder(items) {
        const files = [];

        async function readEntry(entry, path) {
            if (entry.isFile) {
                const file = await new Promise((resolve) => entry.file(resolve));
                Object.defineProperty(file, 'relativePath', { value: path + file.name });
                files.push(file);
            } else if (entry.isDirectory) {
                const reader = entry.createReader();
                const entries = await new Promise((resolve) => {
                    const all = [];
                    const readBatch = () => {
                        reader.readEntries((batch) => {
                            if (batch.length === 0) { resolve(all); return; }
                            all.push(...batch);
                            readBatch();
                        });
                    };
                    readBatch();
                });
                for (const child of entries) {
                    await readEntry(child, path + entry.name + '/');
                }
            }
        }

        for (let i = 0; i < items.length; i++) {
            const entry = items[i].webkitGetAsEntry?.() || items[i].getAsEntry?.();
            if (entry) {
                await readEntry(entry, '');
            }
        }
        return files;
    }

    // Upload skill files to backend via multipart form data
    async function uploadSkillFiles(files) {
        let skillName = '';
        const hasSkillMd = files.some((f) => {
            const relPath = f.webkitRelativePath || f.relativePath || f.name;
            const parts = relPath.replace(/\\/g, '/').split('/');
            if (parts.length > 1 && !skillName) {
                skillName = parts[0];
            }
            return parts[parts.length - 1] === 'SKILL.md';
        });

        if (!hasSkillMd) {
            toast('文件夹须包含 SKILL.md 文件', 'error');
            return;
        }

        if (!skillName) {
            const first = files[0];
            const relPath = first.webkitRelativePath || first.relativePath || first.name;
            const parts = relPath.replace(/\\/g, '/').split('/');
            skillName = parts.length > 1 ? parts[0] : 'unnamed-skill';
        }

        const formData = new FormData();
        formData.append('skill_name', skillName);
        for (const file of files) {
            const relPath = file.webkitRelativePath || file.relativePath || file.name;
            formData.append('files', file, relPath);
        }

        try {
            const resp = await fetch(API.base + '/skills', {
                method: 'POST',
                body: formData,
            });
            if (!resp.ok) {
                const text = await resp.text();
                throw new Error(`${resp.status} - ${text}`);
            }
            toast(`Skill "${skillName}" 上传成功`);
            navigate('skills');
        } catch (e) {
            toast('上传失败：' + e.message, 'error');
        }
    }

    // Delete skill
    async function deleteSkill(skillName) {
        const ok = await confirm('删除 Skill', `确定要删除 "${skillName}" 吗？此操作无法撤销。`);
        if (!ok) return;

        try {
            await API.del('/skills/' + encodeURIComponent(skillName));
            toast(`Skill "${skillName}" 已删除`);
            navigate('skills');
        } catch (e) {
            toast('删除失败：' + e.message, 'error');
        }
    }

    // ========== Page: Cron Jobs ==========

    function formatRelativeTime(isoStr) {
        const diff = new Date(isoStr) - new Date();
        if (diff <= 0) return '即将执行';
        const mins = Math.floor(diff / 60000);
        if (mins < 60) return `${mins} 分钟后`;
        const hours = Math.floor(diff / 3600000);
        if (hours < 24) return `${hours} 小时后`;
        const days = Math.floor(diff / 86400000);
        if (days < 7) return `${days} 天后`;
        const d = new Date(isoStr);
        return `${d.getMonth()+1}月${d.getDate()}日 ${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}`;
    }

    function formatCronTime(j) {
        if (j.delete_after_run && j.next_run_time) {
            return formatRelativeTime(j.next_run_time);
        }
        return j.cron_desc;
    }

    function cronFreqLabel(cron_desc) {
        const freq = (cron_desc || '').replace(/\s*\d{2}:\d{2}$/, '').trim();
        return freq || '周期性';
    }

    async function renderCronJobs(container) {
        let jobs = [];
        try {
            const resp = await API.get('/cron/jobs');
            jobs = resp.jobs || [];
        } catch (e) {
            container.innerHTML = `<div class="card"><div class="card-body"><p style="color:var(--error)">加载定时任务失败：${esc(e.message)}</p></div></div>`;
            return;
        }

        const typeLabels = { skill: 'Skill', command: '命令', message: '消息' };
        const typeColors = { skill: 'badge-brand', command: 'badge-warning', message: 'badge-info' };

        const jobCards = jobs.length === 0
            ? `<div class="cron-empty">
                <span class="ms" style="font-size:36px;color:var(--text-hint);opacity:0.5">schedule</span>
                <p>暂无定时任务</p>
                <p style="font-size:12px;color:var(--text-hint);margin-top:4px">直接向数字分身说出你的需求即可新建，也可发送「查看我的定时任务」随时查询</p>
            </div>`
            : `<div class="cron-list">
                ${jobs.map((j) => `
                    <div class="cron-card">
                        <div class="cron-card-header">
                            <span class="cron-time">${esc(formatCronTime(j))}</span>
                            <div class="cron-badges">
                                <span class="badge ${typeColors[j.task_type] || 'badge-muted'}">${esc(typeLabels[j.task_type] || j.task_type)}</span>
                                ${j.delete_after_run
                                    ? '<span class="badge badge-warning"><span class="ms" style="font-size:12px;line-height:1;vertical-align:middle">alarm</span> 一次性</span>'
                                    : `<span class="badge badge-info"><span class="ms" style="font-size:12px;line-height:1;vertical-align:middle">autorenew</span> ${esc(cronFreqLabel(j.cron_desc))}</span>`}
                                <span class="badge ${j.enabled ? 'badge-success' : 'badge-muted'}">${j.enabled ? '已启用' : '已停用'}</span>
                            </div>
                        </div>
                        <div class="cron-card-body">
                            <div class="cron-field">
                                <span class="cron-label">内容：</span>
                                <span class="cron-value">${esc(j.task_content)}</span>
                            </div>
                            <div class="cron-field">
                                <span class="cron-label">发送到：</span>
                                <span class="cron-value">${esc(j.target)}</span>
                            </div>
                            ${j.owner_name ? `<div class="cron-field">
                                <span class="cron-label">创建人：</span>
                                <span class="cron-value">${esc(j.owner_name)}${j.created_at ? ' · ' + esc(j.created_at.slice(0, 10)) : ''}</span>
                            </div>` : ''}
                        </div>
                        <div class="cron-card-footer">
                            <button class="btn btn-danger btn-sm" onclick="App.deleteCronJob('${esc(j.id)}')">
                                <span class="ms" style="font-size:14px">delete</span> 删除
                            </button>
                        </div>
                    </div>
                `).join('')}
            </div>`;

        container.innerHTML = `
            <div class="cron-onboarding card">
                <div class="card-body">
                    <div class="cron-onboarding-title">
                        <span class="ms" style="font-size:18px;color:var(--brand)">lightbulb</span>
                        如何新建定时任务
                    </div>
                    <p class="cron-onboarding-desc">在私聊或群聊中，直接向数字分身描述需求即可：</p>
                    <div style="font-size:11px;color:var(--text-hint);font-weight:600;letter-spacing:.5px;margin:8px 0 4px">任务类型</div>
                    <div class="cron-examples">
                        <div class="cron-example"><span class="ms" style="font-size:14px;color:var(--brand)">campaign</span> 设置提醒 &nbsp;—&nbsp; 定期发固定消息 &nbsp;—&nbsp; <em>"每天早上9点提醒我喝水"</em> &nbsp;<span class="badge badge-info" style="vertical-align:middle"><span class="ms" style="font-size:12px;line-height:1;vertical-align:middle">autorenew</span> 每天</span></div>
                        <div class="cron-example"><span class="ms" style="font-size:14px;color:var(--brand)">smart_toy</span> 触发 Skill &nbsp;—&nbsp; 定期执行分析/报告 &nbsp;—&nbsp; <em>"每月25日帮我分析人力投入"</em> &nbsp;<span class="badge badge-warning" style="vertical-align:middle"><span class="ms" style="font-size:12px;line-height:1;vertical-align:middle">autorenew</span> 每月</span></div>
                    </div>
                    <div style="font-size:11px;color:var(--text-hint);font-weight:600;letter-spacing:.5px;margin:8px 0 4px">时间类型</div>
                    <div class="cron-examples">
                        <div class="cron-example"><span class="ms" style="font-size:14px;color:var(--brand)">autorenew</span> 周期性 &nbsp;—&nbsp; 每天 / 每周一 / 每月15日…</div>
                        <div class="cron-example"><span class="ms" style="font-size:14px;color:var(--brand)">alarm</span> 指定时间 &nbsp;—&nbsp; 3月1日10点（执行一次后自动结束）</div>
                    </div>
                    <p class="cron-onboarding-tip">私聊新建 → 结果发给自己 &nbsp;·&nbsp; 群聊 @数字分身 新建 → 可选"发到群"或"发给自己"<br><span class="ms" style="font-size:13px;color:var(--text-hint)">chat</span> 也可随时向分身发送「查看我的定时任务」查询名下任务</p>
                </div>
            </div>
            <div class="cron-list-header">
                <h3 style="font-size:14px;font-weight:600;color:var(--text-primary)">已设置的任务</h3>
                <span style="font-size:12px;color:var(--text-hint)">${jobs.length} 个任务</span>
            </div>
            ${jobCards}
        `;
    }

    // Delete cron job
    async function deleteCronJob(jobId) {
        const ok = await confirm('删除定时任务', '删除后定时任务将停止执行，不可恢复。');
        if (!ok) return;

        try {
            await API.del('/cron/jobs/' + encodeURIComponent(jobId));
            toast('定时任务已删除');
            navigate('cron');
        } catch (e) {
            toast('删除失败：' + e.message, 'error');
        }
    }

    // ========== Global Restart Mechanism ==========

    async function checkRestartNeeded() {
        try {
            const resp = await API.get('/config-changes/status');
            const btn = document.getElementById('global-restart-btn');

            if (!btn) return;

            btn.classList.remove('btn-disabled');
            btn.disabled = false;

            if (resp.has_changes) {
                btn.innerHTML = '<span class="ms" style="font-size:14px">refresh</span> 重启（有变更）';
            } else {
                btn.innerHTML = '<span class="ms" style="font-size:14px">refresh</span> 重启';
            }
        } catch (e) {
            const btn = document.getElementById('global-restart-btn');
            if (btn) {
                btn.classList.remove('btn-disabled');
                btn.disabled = false;
                btn.innerHTML = '<span class="ms" style="font-size:14px">refresh</span> 重启';
            }
        }
    }

    async function updateServiceUptime() {
        try {
            const resp = await API.get('/services/status');
            const uptimeEl = document.querySelector('.uptime-value');
            const pidEl = document.querySelector('.service-pid-value');

            const anyOnline = resp.any_online;

            if (anyOnline && resp.services && resp.services.main) {
                const mainService = resp.services.main;

                if (pidEl && mainService.pid) {
                    pidEl.textContent = mainService.pid;
                }

                if (mainService.start_time && !serviceStartTime) {
                    serviceStartTime = mainService.start_time;
                    startUptimeCounter();
                } else if (!mainService.start_time && uptimeEl) {
                    uptimeEl.textContent = mainService.uptime || '运行中';
                }
            } else if (uptimeEl) {
                uptimeEl.textContent = '-';
                if (pidEl) {
                    pidEl.textContent = '-';
                }
                serviceStartTime = null;
                if (uptimeInterval) {
                    clearInterval(uptimeInterval);
                    uptimeInterval = null;
                }
            }
        } catch (e) {
            // Silently fail
        }
    }

    // ---- Restart modal helpers ----

    function createRestartModal() {
        const overlay = document.createElement('div');
        overlay.className = 'restart-modal-overlay';
        overlay.innerHTML = `
            <div class="restart-modal">
                <div class="restart-modal-header">
                    <span class="restart-modal-title">重启服务</span>
                    <span class="restart-elapsed" id="restart-elapsed">0s</span>
                </div>
                <div class="restart-steps">
                    <div class="restart-step" data-step="1">
                        <span class="step-dot"></span>
                        <span class="step-label">发送重启命令</span>
                        <span class="step-status"></span>
                    </div>
                    <div class="restart-step" data-step="2">
                        <span class="step-dot"></span>
                        <span class="step-label">停止旧服务</span>
                        <span class="step-status"></span>
                    </div>
                    <div class="restart-step" data-step="3">
                        <span class="step-dot"></span>
                        <span class="step-label">启动新服务</span>
                        <span class="step-status"></span>
                    </div>
                    <div class="restart-step" data-step="4">
                        <span class="step-dot"></span>
                        <span class="step-label">等待通道连接</span>
                        <span class="step-status"></span>
                    </div>
                    <div class="channel-status-detail" id="channel-status-detail" style="display:none"></div>
                    <div class="restart-step" data-step="5">
                        <span class="step-dot"></span>
                        <span class="step-label">验证服务状态</span>
                        <span class="step-status"></span>
                    </div>
                </div>
                <div class="restart-result" id="restart-result"></div>
                <div class="restart-actions" id="restart-actions" style="display:none">
                    <button class="btn btn-secondary" id="restart-close-btn">关闭</button>
                </div>
            </div>
        `;
        document.body.appendChild(overlay);
        return overlay;
    }

    function updateRestartStep(modal, stepNum, state) {
        const step = modal.querySelector(`.restart-step[data-step="${stepNum}"]`);
        if (!step) return;
        step.classList.remove('step-pending', 'step-active', 'step-done', 'step-error', 'step-warning');
        step.classList.add(`step-${state}`);
    }

    async function waitForServerDown(maxWaitMs) {
        await new Promise(r => setTimeout(r, 2500));
        const deadline = Date.now() + maxWaitMs;
        while (Date.now() < deadline) {
            try {
                const controller = new AbortController();
                const tid = setTimeout(() => controller.abort(), 2000);
                await fetch('/health', { signal: controller.signal });
                clearTimeout(tid);
                await new Promise(r => setTimeout(r, 500));
            } catch {
                return true;
            }
        }
        return false;
    }

    async function waitForServerUp(maxWaitMs) {
        await new Promise(r => setTimeout(r, 3000));
        const deadline = Date.now() + maxWaitMs;
        while (Date.now() < deadline) {
            try {
                const controller = new AbortController();
                const tid = setTimeout(() => controller.abort(), 3000);
                const resp = await fetch('/health', { signal: controller.signal });
                clearTimeout(tid);
                if (resp.ok) {
                    return await resp.json();
                }
            } catch {
                // Not ready yet
            }
            await new Promise(r => setTimeout(r, 2000));
        }
        return null;
    }

    function updateChannelDisplay(el, channels) {
        const labels = { feishu: '飞书 WebSocket', wecom_bridge: '企微 Bridge' };
        const statusLabels = {
            connected: '已连接',
            starting: '连接中...',
            disconnected: '已断开',
            error: '错误',
            disabled: '已禁用',
        };
        let html = '';
        for (const [name, info] of Object.entries(channels)) {
            const label = labels[name] || name;
            const sLabel = statusLabels[info.status] || info.status;
            const elapsed = info.since ? Math.round((Date.now() / 1000 - info.since)) + 's' : '';
            const icon = info.status === 'connected' ? '&#10003;' : info.status === 'error' ? '!' : '';
            const cls = `channel-${info.status}`;
            const extTag = info.managed === false ? ' <span class="channel-external">(external)</span>' : '';
            html += `<div class="channel-item ${cls}">
                <span class="channel-name">${label}${extTag}:</span>
                <span class="channel-state">${sLabel}${icon ? ' ' + icon : ''}</span>
                ${elapsed && info.status !== 'connected' ? `<span class="channel-elapsed">(${elapsed})</span>` : ''}
                ${info.error ? `<span class="channel-${info.status === 'error' ? 'error' : 'detail'}">${info.error}</span>` : ''}
            </div>`;
        }
        el.innerHTML = html;
        el.style.display = html ? 'block' : 'none';
    }

    async function waitForChannelsReady(maxWaitMs, modal) {
        const deadline = Date.now() + maxWaitMs;
        const channelDetailEl = modal.querySelector('#channel-status-detail');

        while (Date.now() < deadline) {
            try {
                const controller = new AbortController();
                const tid = setTimeout(() => controller.abort(), 3000);
                const resp = await fetch('/health', { signal: controller.signal });
                clearTimeout(tid);
                if (resp.ok) {
                    const health = await resp.json();
                    if (channelDetailEl && health.channels) {
                        updateChannelDisplay(channelDetailEl, health.channels);
                    }
                    // Check both channels_ready (managed) and no channel still starting (unmanaged)
                    const noStarting = !health.channels || Object.values(health.channels).every(
                        ch => ch.status !== 'starting'
                    );
                    if (health.channels_ready && noStarting) {
                        return { ready: true, health };
                    }
                }
            } catch {
                // Not ready yet
            }
            await new Promise(r => setTimeout(r, 2000));
        }
        try {
            const resp = await fetch('/health');
            if (resp.ok) {
                const health = await resp.json();
                if (channelDetailEl && health.channels) {
                    updateChannelDisplay(channelDetailEl, health.channels);
                }
                return { ready: false, health };
            }
        } catch {}
        return { ready: false };
    }

    async function restartAllServices() {
        const confirmed = await confirm(
            '重启服务',
            '即将重启 Agent 及相关服务。重启期间无法处理消息。是否继续？'
        );
        if (!confirmed) return;

        const btn = document.getElementById('global-restart-btn');
        const originalHTML = btn.innerHTML;
        btn.disabled = true;
        btn.classList.add('btn-disabled');
        btn.textContent = '重启中...';

        // Create modal
        const modal = createRestartModal();
        const resultDiv = modal.querySelector('#restart-result');
        const actionsDiv = modal.querySelector('#restart-actions');
        const elapsedEl = modal.querySelector('#restart-elapsed');

        // Start elapsed timer
        const startTime = Date.now();
        const timerInterval = setInterval(() => {
            const sec = Math.round((Date.now() - startTime) / 1000);
            elapsedEl.textContent = `${sec}s`;
        }, 1000);

        let oldPid = null;

        try {
            // Step 1: Send restart command
            updateRestartStep(modal, 1, 'active');
            try {
                const controller = new AbortController();
                const tid = setTimeout(() => controller.abort(), 5000);
                const resp = await API.post('/services/restart-all', {}, { signal: controller.signal });
                clearTimeout(tid);
                oldPid = resp.message ? parseInt(resp.message, 10) : null;
            } catch (e) {
                if (e.name === 'AbortError') {
                    console.log('Restart API call interrupted (expected):', e.message);
                } else {
                    throw e;
                }
            }
            updateRestartStep(modal, 1, 'done');

            // Step 2: Wait for old server to go down
            updateRestartStep(modal, 2, 'active');
            const serverDown = await waitForServerDown(8000);
            if (!serverDown) {
                throw new Error('服务未关闭 — 可能缺少 restart_helper.py，请检查 logs/restart.log');
            }
            updateRestartStep(modal, 2, 'done');

            // Step 3: Wait for new server to come up
            updateRestartStep(modal, 3, 'active');

            const step3El = modal.querySelector('.restart-step[data-step="3"]');
            const hintEl = document.createElement('div');
            hintEl.className = 'step-hint';
            step3El.after(hintEl);
            const step3Start = Date.now();
            const hintInterval = setInterval(() => {
                const elapsed = Math.round((Date.now() - step3Start) / 1000);
                if (elapsed > 45) {
                    hintEl.textContent = `Windows 下进程清理可能需要较长时间... ${elapsed}s`;
                } else if (elapsed > 15) {
                    hintEl.textContent = `等待旧进程退出... ${elapsed}s`;
                }
            }, 1000);

            let health = await waitForServerUp(210000);
            clearInterval(hintInterval);

            if (!health) {
                hintEl.remove();
                updateRestartStep(modal, 3, 'warning');
                resultDiv.innerHTML = `
                    <div class="restart-warning">
                        <div class="restart-warning-icon">!</div>
                        <div>服务启动时间超出预期...</div>
                        <div class="restart-pid-info">仍在后台检查中</div>
                    </div>`;

                const lateHealth = await waitForServerUp(90000);
                if (lateHealth) {
                    health = lateHealth;
                } else {
                    resultDiv.innerHTML = `
                        <div class="restart-warning">
                            <div class="restart-warning-icon">!</div>
                            <div>服务启动耗时过长</div>
                            <div class="restart-pid-info">请检查 logs/restart.log 查看详情</div>
                        </div>`;
                    toast('服务启动耗时过长，请稍后检查', 'warning');
                    return;
                }
            }

            // SDK warmup — show elapsed counter so user sees progress
            if (health && health.sdk_ready === false) {
                hintEl.textContent = 'SDK 初始化中...';
                step3El.after(hintEl);
                const warmupStart = Date.now();
                const warmupHintInterval = setInterval(() => {
                    const elapsed = Math.round((Date.now() - warmupStart) / 1000);
                    hintEl.textContent = `SDK 初始化中... ${elapsed}s`;
                }, 1000);
                const warmupDeadline = Date.now() + 180000;
                while (Date.now() < warmupDeadline) {
                    await new Promise(r => setTimeout(r, 2000));
                    try {
                        const resp = await fetch('/health', { signal: AbortSignal.timeout(3000) });
                        if (resp.ok) {
                            const h = await resp.json();
                            if (h.sdk_ready !== false) {
                                health = h;
                                break;
                            }
                        }
                    } catch {}
                }
                clearInterval(warmupHintInterval);
                hintEl.remove();
            } else {
                hintEl.remove();
            }

            updateRestartStep(modal, 3, 'done');

            // Step 4: Wait for channel connections
            updateRestartStep(modal, 4, 'active');
            const hasChannels = health.channels && Object.keys(health.channels).length > 0;
            let channelsOk = true;
            if (hasChannels) {
                // Show current channel status (even if already connected)
                const channelDetailEl = modal.querySelector('#channel-status-detail');
                if (channelDetailEl && health.channels) {
                    updateChannelDisplay(channelDetailEl, health.channels);
                }
                // Check if any channel is still starting (including managed=false Bridge)
                const anyStarting = Object.values(health.channels).some(
                    ch => ch.status === 'starting'
                );
                if (!health.channels_ready || anyStarting) {
                    const chanResult = await waitForChannelsReady(180000, modal);
                    channelsOk = chanResult.ready;
                }
            }
            if (channelsOk) {
                updateRestartStep(modal, 4, 'done');
            } else {
                updateRestartStep(modal, 4, 'warning');
            }

            // Step 5: Verify PID changed
            updateRestartStep(modal, 5, 'active');
            const newPid = health.pid || null;

            try { await API.post('/config-changes/clear', {}); } catch {}

            serviceStartTime = null;
            if (uptimeInterval) {
                clearInterval(uptimeInterval);
                uptimeInterval = null;
            }
            await updateServiceUptime();

            updateRestartStep(modal, 5, 'done');

            // Show success
            if (!channelsOk) {
                resultDiv.innerHTML = `
                    <div class="restart-warning">
                        <div class="restart-warning-icon">!</div>
                        <div>服务已重启，部分通道仍在连接中</div>
                        <div class="restart-pid-info">通道将在后台继续连接</div>
                    </div>`;
                toast('服务已重启，部分通道仍在连接中', 'warning');
            } else if (oldPid && newPid && oldPid !== newPid) {
                resultDiv.innerHTML = `
                    <div class="restart-success">
                        <div class="restart-success-icon">&#10003;</div>
                        <div>重启完成</div>
                        <div class="restart-pid-info">PID: ${oldPid} &rarr; ${newPid}</div>
                    </div>`;
                toast('服务重启成功', 'success');
            } else if (oldPid && newPid && oldPid === newPid) {
                resultDiv.innerHTML = `
                    <div class="restart-warning">
                        <div class="restart-warning-icon">!</div>
                        <div>服务已响应但 PID 未变化</div>
                        <div class="restart-pid-info">PID: ${newPid}</div>
                    </div>`;
                toast('服务重启成功', 'success');
            } else {
                resultDiv.innerHTML = `
                    <div class="restart-success">
                        <div class="restart-success-icon">&#10003;</div>
                        <div>重启完成</div>
                    </div>`;
                toast('服务重启成功', 'success');
            }

            await checkRestartNeeded();

        } catch (e) {
            const failedStep = modal.querySelector('.step-active');
            if (failedStep) {
                const stepNum = failedStep.dataset.step;
                updateRestartStep(modal, parseInt(stepNum), 'error');
            }
            resultDiv.innerHTML = `
                <div class="restart-error">
                    <div class="restart-error-icon">!</div>
                    <div>重启失败</div>
                    <div class="restart-error-msg">${e.message || '未知错误'}</div>
                </div>`;
            toast('重启可能已失败，请检查服务状态', 'error');
        } finally {
            clearInterval(timerInterval);
            actionsDiv.style.display = 'flex';

            btn.disabled = false;
            btn.classList.remove('btn-disabled');
            btn.innerHTML = originalHTML;
            checkRestartNeeded();

            const closeBtn = modal.querySelector('#restart-close-btn');
            const hasSuccess = resultDiv.querySelector('.restart-success');

            if (hasSuccess) {
                let countdown = 3;
                closeBtn.textContent = `关闭 (${countdown}s)`;
                const autoCloseInterval = setInterval(() => {
                    countdown--;
                    if (countdown <= 0) {
                        clearInterval(autoCloseInterval);
                        modal.remove();
                        navigate(currentPage);
                    } else {
                        closeBtn.textContent = `关闭 (${countdown}s)`;
                    }
                }, 1000);
                closeBtn.addEventListener('click', () => {
                    clearInterval(autoCloseInterval);
                    modal.remove();
                    navigate(currentPage);
                });
            } else {
                closeBtn.addEventListener('click', () => {
                    modal.remove();
                    navigate(currentPage);
                });
            }
        }
    }

    // ========== Update Check ==========

    let _updateInfo = null; // cached update check result

    async function checkForUpdates() {
        const btn = document.getElementById('global-update-btn');
        const text = document.getElementById('update-btn-text');
        if (!btn || !text) return;

        try {
            const data = await API.get('/updates/check');
            _updateInfo = data;

            if (data.available) {
                btn.disabled = false;
                btn.className = 'btn btn-update btn-update-available';
                text.textContent = `更新 v${data.latest_version}`;
                btn.title = `有可用更新：v${data.current_version} → v${data.latest_version}`;
            } else {
                btn.disabled = true;
                btn.className = 'btn btn-update btn-update-disabled';
                text.textContent = '已是最新';
                btn.title = `当前版本：v${data.current_version}`;
            }
        } catch {
            // Network failure — keep disabled silently
            btn.disabled = true;
            btn.className = 'btn btn-update btn-update-disabled';
            text.textContent = '已是最新';
        }
    }

    async function applyUpdate() {
        if (!_updateInfo || !_updateInfo.available) return;

        const ver = _updateInfo.latest_version;
        let changelog = _updateInfo.changelog || 'No changelog provided.';
        // Strip ## Checksums section and everything after it
        const checksumIdx = changelog.indexOf('## Checksums');
        if (checksumIdx !== -1) changelog = changelog.substring(0, checksumIdx).trimEnd();
        const sizeMB = _updateInfo.asset_size ? ((_updateInfo.asset_size / 1024 / 1024).toFixed(1) + ' MB') : '';

        const confirmed = await confirm(
            `更新至 v${ver}`,
            `确认下载并应用从 v${_updateInfo.current_version} 到 v${ver} 的更新？\n\n` +
            (sizeMB ? `安装包大小：${sizeMB}\n` : '') +
            `\n更新日志：\n${changelog.substring(0, 500)}${changelog.length > 500 ? '...' : ''}`
        );
        if (!confirmed) return;

        const btn = document.getElementById('global-update-btn');
        const text = document.getElementById('update-btn-text');
        btn.disabled = true;
        btn.className = 'btn btn-update btn-update-busy';
        text.textContent = '更新中...';

        // Step 1: Download and apply update (before modal)
        let applyResp;
        try {
            const controller = new AbortController();
            const tid = setTimeout(() => controller.abort(), 300000);
            applyResp = await API.post('/updates/apply', {}, { signal: controller.signal });
            clearTimeout(tid);
        } catch (e) {
            if (e.name === 'AbortError') {
                toast('更新超时', 'warning');
            } else {
                toast(`更新失败：${e.message}`, 'error');
            }
            checkForUpdates();
            return;
        }

        if (!applyResp.success) {
            toast(applyResp.message || '更新失败', 'error');
            btn.className = 'btn btn-update btn-update-available';
            btn.disabled = false;
            text.textContent = `更新 v${ver}`;
            return;
        }

        toast(`v${ver} 更新已应用，正在重启...`, 'success', 5000);

        // Create modal — full restart flow (same as restartAllServices)
        const modal = createRestartModal();
        modal.querySelector('.restart-modal-title').textContent = '更新服务';
        const resultDiv = modal.querySelector('#restart-result');
        const actionsDiv = modal.querySelector('#restart-actions');
        const elapsedEl = modal.querySelector('#restart-elapsed');

        const startTime = Date.now();
        const timerInterval = setInterval(() => {
            elapsedEl.textContent = `${Math.round((Date.now() - startTime) / 1000)}s`;
        }, 1000);

        const oldPid = applyResp.message ? parseInt(applyResp.message, 10) : null;

        try {
            // Step 1: Download + apply already done
            updateRestartStep(modal, 1, 'done');
            modal.querySelector('.restart-step[data-step="1"] .step-label').textContent = '下载并应用更新';

            // Step 2: Wait for old server to go down
            updateRestartStep(modal, 2, 'active');
            const serverDown = await waitForServerDown(8000);
            if (!serverDown) {
                throw new Error('服务未关闭 — 请检查 logs/restart.log');
            }
            updateRestartStep(modal, 2, 'done');

            // Step 3: Wait for new server to come up (with SDK warmup)
            updateRestartStep(modal, 3, 'active');

            const step3El = modal.querySelector('.restart-step[data-step="3"]');
            const hintEl = document.createElement('div');
            hintEl.className = 'step-hint';
            step3El.after(hintEl);
            const step3Start = Date.now();
            const hintInterval = setInterval(() => {
                const elapsed = Math.round((Date.now() - step3Start) / 1000);
                if (elapsed > 45) {
                    hintEl.textContent = `Windows 下进程清理可能需要较长时间... ${elapsed}s`;
                } else if (elapsed > 15) {
                    hintEl.textContent = `等待旧进程退出... ${elapsed}s`;
                }
            }, 1000);

            let health = await waitForServerUp(210000);
            clearInterval(hintInterval);

            if (!health) {
                hintEl.remove();
                updateRestartStep(modal, 3, 'warning');
                resultDiv.innerHTML = `
                    <div class="restart-warning">
                        <div class="restart-warning-icon">!</div>
                        <div>服务启动时间超出预期...</div>
                        <div class="restart-pid-info">仍在后台检查中</div>
                    </div>`;

                const lateHealth = await waitForServerUp(90000);
                if (lateHealth) {
                    health = lateHealth;
                } else {
                    resultDiv.innerHTML = `
                        <div class="restart-warning">
                            <div class="restart-warning-icon">!</div>
                            <div>服务启动耗时过长</div>
                            <div class="restart-pid-info">请检查 logs/restart.log 查看详情</div>
                        </div>`;
                    toast('服务启动耗时过长，请稍后检查', 'warning');
                    return;
                }
            }

            // SDK warmup
            if (health && health.sdk_ready === false) {
                hintEl.textContent = 'SDK 初始化中...';
                step3El.after(hintEl);
                const warmupStart = Date.now();
                const warmupHintInterval = setInterval(() => {
                    const elapsed = Math.round((Date.now() - warmupStart) / 1000);
                    hintEl.textContent = `SDK 初始化中... ${elapsed}s`;
                }, 1000);
                const warmupDeadline = Date.now() + 180000;
                while (Date.now() < warmupDeadline) {
                    await new Promise(r => setTimeout(r, 2000));
                    try {
                        const resp = await fetch('/health', { signal: AbortSignal.timeout(3000) });
                        if (resp.ok) {
                            const h = await resp.json();
                            if (h.sdk_ready !== false) {
                                health = h;
                                break;
                            }
                        }
                    } catch {}
                }
                clearInterval(warmupHintInterval);
                hintEl.remove();
            } else {
                hintEl.remove();
            }

            updateRestartStep(modal, 3, 'done');

            // Step 4: Wait for channel connections (with real-time display)
            updateRestartStep(modal, 4, 'active');
            const hasChannels2 = health.channels && Object.keys(health.channels).length > 0;
            let channelsOk2 = true;
            if (hasChannels2) {
                // Show current channel status (even if already connected)
                const channelDetailEl2 = modal.querySelector('#channel-status-detail');
                if (channelDetailEl2 && health.channels) {
                    updateChannelDisplay(channelDetailEl2, health.channels);
                }
                // Check if any channel is still starting (including managed=false Bridge)
                const anyStarting2 = Object.values(health.channels).some(
                    ch => ch.status === 'starting'
                );
                if (!health.channels_ready || anyStarting2) {
                    const chanResult = await waitForChannelsReady(180000, modal);
                    channelsOk2 = chanResult.ready;
                }
            }
            if (channelsOk2) {
                updateRestartStep(modal, 4, 'done');
            } else {
                updateRestartStep(modal, 4, 'warning');
            }

            // Step 5: Verify PID changed + cleanup
            updateRestartStep(modal, 5, 'active');
            const newPid = health.pid || null;

            try { await API.post('/config-changes/clear', {}); } catch {}

            serviceStartTime = null;
            if (uptimeInterval) {
                clearInterval(uptimeInterval);
                uptimeInterval = null;
            }
            await updateServiceUptime();

            updateRestartStep(modal, 5, 'done');

            // Show success result
            if (!channelsOk2) {
                resultDiv.innerHTML = `
                    <div class="restart-warning">
                        <div class="restart-warning-icon">!</div>
                        <div>已更新至 v${ver}，部分通道仍在连接中</div>
                        <div class="restart-pid-info">通道将在后台继续连接</div>
                    </div>`;
                toast(`已更新至 v${ver}，部分通道仍在连接中`, 'warning');
            } else if (oldPid && newPid && oldPid !== newPid) {
                resultDiv.innerHTML = `
                    <div class="restart-success">
                        <div class="restart-success-icon">&#10003;</div>
                        <div>已更新至 v${ver}</div>
                        <div class="restart-pid-info">PID: ${oldPid} &rarr; ${newPid}</div>
                    </div>`;
                toast(`已成功更新至 v${ver}`, 'success');
            } else {
                resultDiv.innerHTML = `
                    <div class="restart-success">
                        <div class="restart-success-icon">&#10003;</div>
                        <div>已更新至 v${ver}</div>
                    </div>`;
                toast(`已成功更新至 v${ver}`, 'success');
            }

            await checkRestartNeeded();

        } catch (e) {
            const failedStep = modal.querySelector('.step-active');
            if (failedStep) {
                const stepNum = failedStep.dataset.step;
                updateRestartStep(modal, parseInt(stepNum), 'error');
            }
            resultDiv.innerHTML = `
                <div class="restart-error">
                    <div class="restart-error-icon">!</div>
                    <div>更新重启失败</div>
                    <div class="restart-error-msg">${e.message || '未知错误'}</div>
                </div>`;
            toast('更新已应用但重启可能失败，请检查服务状态', 'error');
        } finally {
            clearInterval(timerInterval);
            actionsDiv.style.display = 'flex';

            btn.disabled = false;
            btn.classList.remove('btn-update-busy');
            checkForUpdates();

            const closeBtn = modal.querySelector('#restart-close-btn');
            const hasSuccess = resultDiv.querySelector('.restart-success');

            // After update, force hard reload to pick up new static files
            const hardReload = () => { location.href = '/config?' + Date.now(); };

            if (hasSuccess) {
                let countdown = 3;
                closeBtn.textContent = `关闭 (${countdown}s)`;
                const autoCloseInterval = setInterval(() => {
                    countdown--;
                    if (countdown <= 0) {
                        clearInterval(autoCloseInterval);
                        modal.remove();
                        hardReload();
                    } else {
                        closeBtn.textContent = `关闭 (${countdown}s)`;
                    }
                }, 1000);
                closeBtn.addEventListener('click', () => {
                    clearInterval(autoCloseInterval);
                    modal.remove();
                    hardReload();
                });
            } else {
                closeBtn.addEventListener('click', () => {
                    modal.remove();
                    hardReload();
                });
            }
        }
    }

    // ========== Init ==========

    async function fetchAppVersion() {
        try {
            const resp = await fetch('/health', { signal: AbortSignal.timeout(3000) });
            if (resp.ok) {
                const data = await resp.json();
                const el = document.getElementById('app-version');
                if (el && data.version) {
                    el.textContent = 'v' + data.version;
                }
            }
        } catch { /* ignore */ }
    }

    function init() {
        // Navigation click handler
        document.querySelectorAll('.nav-item').forEach((item) => {
            item.addEventListener('click', () => navigate(item.dataset.page));
        });

        // Sidebar toggle (mobile)
        document.getElementById('sidebar-toggle').addEventListener('click', () => {
            document.getElementById('sidebar').classList.toggle('open');
        });

        // Expose actions globally for onclick handlers
        window.App = {
            saveModelConfig,
            saveSoul,
            saveWecomConfig,
            saveFeishu,
            saveAvatarMode,
            saveWhitelist,
            restartService,
            restartAllServices,
            applyUpdate,
            triggerSkillUpload,
            deleteSkill,
            deleteCronJob,
            refreshLogs: fetchLogs,
            copyLogs(btn) {
                const text = document.getElementById('logs-content').textContent;
                navigator.clipboard.writeText(text).then(() => {
                    const orig = btn.innerHTML;
                    btn.innerHTML = '<span class="ms" style="font-size:14px">check</span> 已复制';
                    setTimeout(() => btn.innerHTML = orig, 1500);
                });
            },
            generateBindKey,
            copyBindCommand,
        };

        // Fetch and display app version from /health
        fetchAppVersion();

        // Check for updates on load
        checkForUpdates();

        // Navigate to initial page
        navigate('model');

        // Start periodic config change checking (every 5 seconds)
        setInterval(checkRestartNeeded, 5000);
        checkRestartNeeded();

        // Start periodic service uptime update (every 10 seconds)
        setInterval(updateServiceUptime, 10000);
        updateServiceUptime();
    }

    // Start
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
