import React, { useState, useEffect, useRef, useCallback } from 'react';
import { getVersion } from '@tauri-apps/api/app';
import { openUrl } from '@tauri-apps/plugin-opener';

interface GitHubRelease {
  tag_name: string;
  name: string;
  published_at: string;
  prerelease: boolean;
  html_url: string;
}

export const VersionManager: React.FC = () => {
  const [currentVersion, setCurrentVersion] = useState<string>('');
  const [releases, setReleases] = useState<GitHubRelease[]>([]);
  const [isOpen, setIsOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hasFetched, setHasFetched] = useState(false);

  const popupRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    getVersion().then(setCurrentVersion).catch(() => setCurrentVersion('unknown'));
  }, []);

  const fetchReleases = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(
        'https://api.github.com/repos/erthman18/claude-code-launcher/releases'
      );
      if (!res.ok) throw new Error(`GitHub API returned ${res.status}`);
      const data: GitHubRelease[] = await res.json();
      setReleases(data);
      setHasFetched(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to fetch releases');
    } finally {
      setLoading(false);
    }
  }, []);

  const handleOpen = useCallback(() => {
    setIsOpen(true);
    if (!hasFetched) {
      fetchReleases();
    }
  }, [hasFetched, fetchReleases]);

  const handleCheckUpdate = useCallback(() => {
    fetchReleases();
  }, [fetchReleases]);

  // Close on click outside
  useEffect(() => {
    if (!isOpen) return;
    const handler = (e: MouseEvent) => {
      if (
        popupRef.current &&
        !popupRef.current.contains(e.target as Node) &&
        buttonRef.current &&
        !buttonRef.current.contains(e.target as Node)
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

  const handleDownload = async (url: string) => {
    try {
      await openUrl(url);
    } catch {
      window.open(url, '_blank');
    }
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
          className="fixed bottom-14 right-4 w-80 max-h-96 bg-[#2a2a2a] border border-[#3a3a3a]
                     rounded-lg shadow-lg z-50 flex flex-col overflow-hidden"
        >
          {/* Header */}
          <div className="px-4 py-3 border-b border-[#3a3a3a] shrink-0">
            <div className="flex items-center justify-between">
              <span className="text-[13px] text-[#DCE4EE]">
                当前版本：<span className="font-semibold text-[#3b82f6]">v{currentVersion}</span>
              </span>
              <button
                onClick={handleCheckUpdate}
                disabled={loading}
                className="px-3 py-1 text-[12px] bg-[#3b82f6] hover:bg-[#2563eb]
                           disabled:bg-[#565B5E] disabled:cursor-not-allowed
                           text-white rounded transition-colors"
              >
                {loading ? '检查中...' : '检查更新'}
              </button>
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
                  onClick={handleCheckUpdate}
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
                {releases.map((release) => {
                  const tag = release.tag_name.replace(/^v/, '');
                  const isCurrent = tag === currentVersion;
                  return (
                    <div
                      key={release.tag_name}
                      className={`px-4 py-2.5 flex items-center justify-between hover:bg-[#333333] transition-colors ${
                        isCurrent ? 'bg-[#1a2a3a]' : ''
                      }`}
                    >
                      <div className="flex flex-col gap-0.5 min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="text-[13px] text-[#DCE4EE] font-medium truncate">
                            {release.tag_name}
                          </span>
                          {isCurrent && (
                            <span className="text-[10px] px-1.5 py-0.5 bg-[#3b82f6] text-white rounded shrink-0">
                              当前
                            </span>
                          )}
                          {release.prerelease && (
                            <span className="text-[10px] px-1.5 py-0.5 bg-[#f59e0b] text-black rounded shrink-0">
                              Pre-release
                            </span>
                          )}
                        </div>
                        <span className="text-[11px] text-[#999999]">
                          {formatDate(release.published_at)}
                        </span>
                      </div>
                      <button
                        onClick={() => handleDownload(release.html_url)}
                        className="px-2.5 py-1 text-[11px] bg-[#565B5E] hover:bg-[#7A8488]
                                   text-white rounded transition-colors shrink-0 ml-2"
                      >
                        下载
                      </button>
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
