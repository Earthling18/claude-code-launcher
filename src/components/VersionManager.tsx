import { useState, useEffect, useRef, useCallback } from 'react';
import { getVersion } from '@tauri-apps/api/app';
import { invoke } from '@tauri-apps/api/core';
import { openUrl } from '@tauri-apps/plugin-opener';
import { exit } from '@tauri-apps/plugin-process';

interface GitHubAsset {
  name: string;
  browser_download_url: string;
  size: number;
}

interface GitHubRelease {
  tag_name: string;
  name: string;
  published_at: string;
  prerelease: boolean;
  html_url: string;
  body: string;
  assets: GitHubAsset[];
}

type Platform = 'windows' | 'macos' | 'linux' | 'unknown';

// In-app version list is served from Aliyun OSS first (reachable in mainland
// China without a VPN), falling back to the GitHub API. The OSS releases.json
// is a version-index array maintained by CI (.github/workflows/build.yml) and
// has a different shape than the GitHub API, so we map it onto GitHubRelease.
const OSS_RELEASES_URL =
  'https://cc-launcher-dist.oss-cn-shanghai.aliyuncs.com/releases/releases.json';
const GITHUB_RELEASES_URL =
  'https://api.github.com/repos/Earthling18/claude-code-launcher/releases';

interface OssReleaseEntry {
  version: string;
  pub_date: string;
  notes: string;
  prerelease: boolean;
  platforms: Record<string, { url: string }>;
}

// Derive a GitHubAsset-shaped object from an OSS download url. The filename is
// taken from the url tail so findInstaller's suffix matching still works. OSS
// releases.json carries no byte size, so size is 0 (the UI hides "(size)" then).
const ossAsset = (url?: string): GitHubAsset | null => {
  if (!url) return null;
  const name = url.split('/').pop() || url;
  return { name, browser_download_url: url, size: 0 };
};

// Map one OSS index entry to the internal GitHubRelease model the UI renders.
const ossEntryToRelease = (e: OssReleaseEntry): GitHubRelease => {
  const p = e.platforms || {};
  const assets = [
    ossAsset(p['windows-x86_64']?.url),
    ossAsset(p['darwin-universal-dmg']?.url),
    ossAsset(p['darwin-universal-tar']?.url),
    ossAsset(p['windows-portable']?.url),
  ].filter((a): a is GitHubAsset => a !== null);
  return {
    tag_name: e.version.startsWith('v') ? e.version : `v${e.version}`,
    name: e.version,
    published_at: e.pub_date,
    prerelease: !!e.prerelease,
    // No per-version OSS web page; point "查看" fallback at the bucket folder.
    html_url: `https://cc-launcher-dist.oss-cn-shanghai.aliyuncs.com/releases/v${e.version}/`,
    body: e.notes || '',
    assets,
  };
};

export const VersionManager: React.FC = () => {
  const [currentVersion, setCurrentVersion] = useState('');
  const [releases, setReleases] = useState<GitHubRelease[]>([]);
  const [isOpen, setIsOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hasFetched, setHasFetched] = useState(false);
  const [expandedTag, setExpandedTag] = useState<string | null>(null);
  const [downloading, setDownloading] = useState<string | null>(null);
  const [platform, setPlatform] = useState<Platform>('unknown');

  const popupRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    getVersion().then(setCurrentVersion).catch(() => setCurrentVersion('unknown'));
    invoke<string>('get_platform').then(p => setPlatform(p as Platform)).catch(() => {});
  }, []);

  // Try the OSS version index first (fast + reachable in mainland China).
  // Returns the mapped releases on success, or null to signal "fall back".
  const fetchFromOss = useCallback(async (): Promise<GitHubRelease[] | null> => {
    try {
      // Cache-bust so a freshly published version shows up promptly.
      const res = await fetch(`${OSS_RELEASES_URL}?t=${Date.now()}`);
      if (!res.ok) return null;
      const data = await res.json();
      if (!Array.isArray(data) || data.length === 0) return null;
      return (data as OssReleaseEntry[]).map(ossEntryToRelease);
    } catch {
      return null;
    }
  }, []);

  const fetchReleases = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      // 1) OSS first.
      const ossReleases = await fetchFromOss();
      if (ossReleases) {
        setReleases(ossReleases);
        setHasFetched(true);
        return;
      }

      // 2) Fall back to the GitHub API.
      const res = await fetch(GITHUB_RELEASES_URL);
      // Anonymous GitHub API is limited to 60 req/hour PER IP — behind a
      // corporate NAT/VPN the shared quota is often exhausted by others.
      if (res.status === 403 || res.status === 429) {
        throw new Error('GitHub 接口暂时限流（同出口 IP 共享额度），请约一小时后再试');
      }
      if (!res.ok) throw new Error(`GitHub API returned ${res.status}`);
      const data: GitHubRelease[] = await res.json();
      setReleases(data);
      setHasFetched(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to fetch releases');
    } finally {
      setLoading(false);
      setHasFetched(true);
    }
  }, [fetchFromOss]);

  const handleOpen = useCallback(() => {
    setIsOpen(true);
    if (!hasFetched) fetchReleases();
  }, [hasFetched, fetchReleases]);

  // Close on click outside
  useEffect(() => {
    if (!isOpen) return;
    const handler = (e: MouseEvent) => {
      if (
        popupRef.current && !popupRef.current.contains(e.target as Node) &&
        buttonRef.current && !buttonRef.current.contains(e.target as Node)
      ) {
        setIsOpen(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [isOpen]);

  const formatDate = (dateStr: string): string => {
    const d = new Date(dateStr);
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  };

  const formatSize = (bytes: number): string => {
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  // Find the platform-specific installer asset for this release.
  //   windows → NSIS .exe
  //   macos   → .dmg
  // Returns undefined for unknown / unsupported platforms; UI falls back to opening
  // the release page in the browser.
  const findInstaller = (release: GitHubRelease): GitHubAsset | undefined => {
    if (platform === 'windows') {
      return release.assets.find(a => a.name.endsWith('_x64-setup.exe'));
    }
    if (platform === 'macos') {
      return release.assets.find(a => a.name.endsWith('_universal.dmg') || a.name.endsWith('.dmg'));
    }
    return undefined;
  };

  // Compare semver strings, returns 1 / -1 / 0.
  const cmpSemver = (a: string, b: string): number => {
    const pa = a.replace(/^v/, '').split('.').map(Number);
    const pb = b.replace(/^v/, '').split('.').map(Number);
    for (let i = 0; i < 3; i++) {
      const va = pa[i] || 0;
      const vb = pb[i] || 0;
      if (va > vb) return 1;
      if (va < vb) return -1;
    }
    return 0;
  };

  const handleInstall = async (release: GitHubRelease) => {
    setDownloading(release.tag_name);
    try {
      // macOS: when upgrading to a version newer than current AND that version
      // matches the server's latest.json, route through Tauri Updater for a
      // proper in-place replace (no DMG drag, no Finder "Replace?" dialog).
      // Older / equal / mismatched targets fall back to the manual DMG flow.
      if (platform === 'macos') {
        const targetVer = release.tag_name.replace(/^v/, '');
        if (cmpSemver(targetVer, currentVersion) > 0) {
          try {
            const { check } = await import('@tauri-apps/plugin-updater');
            const update = await check();
            if (update && update.version === targetVer) {
              await update.downloadAndInstall();
              const { relaunch } = await import('@tauri-apps/plugin-process');
              await relaunch();
              return;
            }
            // No matching update from server (e.g., release is prerelease or
            // server hasn't picked it up yet) → fall through to manual flow.
          } catch (e) {
            // If updater path failed for any reason, drop down to manual flow.
            console.warn('[VersionManager] Tauri updater path failed, falling back to DMG:', e);
          }
        }
      }

      // Default path: download platform installer (NSIS / DMG) and run/open it.
      const asset = findInstaller(release);
      if (!asset) {
        try { await openUrl(release.html_url); } catch { window.open(release.html_url, '_blank'); }
        setDownloading(null);
        return;
      }
      await invoke('download_and_run_installer', {
        url: asset.browser_download_url,
        filename: asset.name,
      });
      // Installer launched, exit app to let it proceed.
      await exit(0);
    } catch (e: any) {
      setError(e?.toString() || 'Download failed');
      setDownloading(null);
    }
  };

  // Simple markdown-ish rendering: bold, lines
  const renderBody = (body: string) => {
    if (!body) return null;
    return body.split('\n').map((line, i) => {
      const trimmed = line.trim();
      if (!trimmed) return <br key={i} />;
      // Headings
      if (trimmed.startsWith('## ')) return <div key={i} className="text-[12px] font-semibold text-[#DCE4EE] mt-2 mb-1">{trimmed.slice(3)}</div>;
      if (trimmed.startsWith('### ')) return <div key={i} className="text-[11px] font-semibold text-[#DCE4EE] mt-1.5 mb-0.5">{trimmed.slice(4)}</div>;
      // List items
      if (trimmed.startsWith('- ') || trimmed.startsWith('* '))
        return <div key={i} className="text-[11px] text-[#aaaaaa] pl-3 leading-relaxed">{trimmed.slice(2)}</div>;
      return <div key={i} className="text-[11px] text-[#aaaaaa] leading-relaxed">{trimmed}</div>;
    });
  };

  return (
    <>
      <button
        ref={buttonRef}
        onClick={() => (isOpen ? setIsOpen(false) : handleOpen())}
        className="fixed bottom-4 right-4 w-8 h-8 rounded-full bg-[#3a3a3a]
                   hover:bg-[#4a4a4a] text-[#999999] hover:text-white
                   flex items-center justify-center transition-colors z-40"
        title={`v${currentVersion}`}
      >
        <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="12" cy="12" r="3" />
          <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
        </svg>
      </button>

      {isOpen && (
        <div
          ref={popupRef}
          className="fixed bottom-14 right-4 w-96 max-h-[70vh] bg-[#2a2a2a] border border-[#3a3a3a]
                     rounded-lg shadow-lg z-50 flex flex-col overflow-hidden"
        >
          {/* Header */}
          <div className="px-4 py-3 border-b border-[#3a3a3a] shrink-0">
            <div className="flex items-center justify-between gap-2">
              <span className="text-[13px] text-[#DCE4EE] truncate">
                当前版本：<span className="font-semibold text-[#3b82f6]">v{currentVersion}</span>
              </span>
              <div className="flex items-center gap-2 flex-shrink-0">
                <button
                  onClick={() => {
                    setIsOpen(false);
                    window.dispatchEvent(new CustomEvent('cc-launcher:show-onboarding'));
                  }}
                  className="text-[11px] text-[#aaaaaa] hover:text-white underline-offset-2 hover:underline transition-colors"
                  title="重新查看新手引导"
                >
                  新手引导
                </button>
                <button
                  onClick={fetchReleases}
                  disabled={loading}
                  className="px-3 py-1 text-[12px] bg-[#3b82f6] hover:bg-[#2563eb]
                             disabled:bg-[#565B5E] disabled:cursor-not-allowed
                             text-white rounded transition-colors"
                >
                  {loading ? '检查中...' : '检查更新'}
                </button>
              </div>
            </div>
          </div>

          {/* Content */}
          <div className="flex-1 overflow-y-auto">
            {loading && !hasFetched && (
              <div className="px-4 py-6 text-center text-[13px] text-[#999999]">
                正在获取版本列表...
              </div>
            )}

            {error && (
              <div className="px-4 py-4 text-center">
                <p className="text-[13px] text-[#ef4444] mb-2">{error}</p>
                <button
                  onClick={() => { setError(null); fetchReleases(); }}
                  className="px-3 py-1 text-[12px] bg-[#565B5E] hover:bg-[#7A8488]
                             text-white rounded transition-colors"
                >
                  重试
                </button>
              </div>
            )}

            {!loading && !error && releases.length === 0 && hasFetched && (
              <div className="px-4 py-6 text-center text-[13px] text-[#999999]">
                暂无版本信息
              </div>
            )}

            {releases.length > 0 && (
              <div className="py-1">
                {releases.slice(0, 5).map((release) => {
                  const tag = release.tag_name.replace(/^v/, '');
                  const isCurrent = tag === currentVersion;
                  const hasNotes = !!release.body?.trim();
                  const isExpanded = expandedTag === release.tag_name;
                  const installer = findInstaller(release);
                  const isDownloading = downloading === release.tag_name;

                  return (
                    <div key={release.tag_name} className={isCurrent ? 'bg-[#1a2a3a]' : ''}>
                      {/* Version row */}
                      <div
                        className={`px-4 py-2.5 flex items-center justify-between hover:bg-[#333333] transition-colors${hasNotes ? ' cursor-pointer' : ''}`}
                        onClick={hasNotes ? () => setExpandedTag(isExpanded ? null : release.tag_name) : undefined}
                      >
                        <div className="flex items-center gap-2 min-w-0">
                          {hasNotes && (
                            <span className="text-[11px] text-[#666666]">{isExpanded ? '\u25BC' : '\u25B6'}</span>
                          )}
                          <span className="text-[13px] text-[#DCE4EE] font-medium truncate">
                            {release.tag_name}
                          </span>
                          <span className="text-[11px] text-[#666666] shrink-0">
                            {formatDate(release.published_at)}
                          </span>
                          {isCurrent && (
                            <span className="text-[10px] px-1.5 py-0.5 bg-[#3b82f6] text-white rounded shrink-0">
                              当前
                            </span>
                          )}
                          {release.prerelease && (
                            <span className="text-[10px] px-1.5 py-0.5 bg-[#f59e0b] text-black rounded shrink-0">
                              Pre
                            </span>
                          )}
                        </div>
                        <button
                          onClick={(e) => { e.stopPropagation(); handleInstall(release); }}
                          disabled={!!downloading}
                          className={`px-2.5 py-1 text-[11px] disabled:bg-[#565B5E] disabled:cursor-not-allowed text-white rounded transition-colors shrink-0 ml-2 ${
                            isCurrent
                              ? 'bg-[#565B5E] hover:bg-[#7A8488]'
                              : 'bg-[#10b981] hover:bg-[#059669]'
                          }`}
                          title={isCurrent ? '下载并重装当前版本' : undefined}
                        >
                          {isDownloading
                            ? '下载中...'
                            : installer
                            // OSS-sourced assets carry no byte size (size 0);
                            // only append "(size)" when GitHub gave us one.
                            ? `${isCurrent ? '重装' : '安装'}${installer.size > 0 ? ` (${formatSize(installer.size)})` : ''}`
                            : '查看'}
                        </button>
                      </div>

                      {/* Expanded release notes */}
                      {isExpanded && hasNotes && (
                        <div className="px-4 pb-3 pt-0">
                          <div className="bg-[#1e1e1e] border border-[#333333] rounded p-3 max-h-48 overflow-y-auto">
                            {renderBody(release.body)}
                          </div>
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      )}
    </>
  );
};
