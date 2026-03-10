import { useState, useEffect, useCallback } from 'react';
import { check, Update } from '@tauri-apps/plugin-updater';
import { relaunch } from '@tauri-apps/plugin-process';
import { invoke } from '@tauri-apps/api/core';
import { getVersion } from '@tauri-apps/api/app';

export type UpdateStatus = 'idle' | 'checking' | 'available' | 'downloading' | 'error';

interface UpdateState {
  status: UpdateStatus;
  version: string | null;
  progress: number;
  error: string | null;
  isPortable: boolean;
}

// Compare semver strings: returns 1 if a > b, -1 if a < b, 0 if equal
function compareSemver(a: string, b: string): number {
  const pa = a.replace(/^v/, '').split('.').map(Number);
  const pb = b.replace(/^v/, '').split('.').map(Number);
  for (let i = 0; i < 3; i++) {
    const va = pa[i] || 0;
    const vb = pb[i] || 0;
    if (va > vb) return 1;
    if (va < vb) return -1;
  }
  return 0;
}

export function useUpdateChecker() {
  const [state, setState] = useState<UpdateState>({
    status: 'idle',
    version: null,
    progress: 0,
    error: null,
    isPortable: false,
  });
  const [update, setUpdate] = useState<Update | null>(null);

  useEffect(() => {
    const timer = setTimeout(async () => {
      setState(prev => ({ ...prev, status: 'checking' }));
      try {
        const portable = await invoke<boolean>('is_portable_mode');
        setState(prev => ({ ...prev, isPortable: portable }));

        if (portable) {
          // Portable mode: manually check latest.json for new version
          await checkPortableUpdate();
        } else {
          // Installer mode: use Tauri's built-in updater
          await checkInstallerUpdate();
        }
      } catch (err) {
        console.error('Update check failed:', err);
        setState(prev => ({ ...prev, status: 'idle' }));
      }
    }, 3000);

    return () => clearTimeout(timer);
  }, []);

  async function checkInstallerUpdate() {
    const result = await check();
    if (result) {
      setUpdate(result);
      setState(prev => ({
        ...prev,
        status: 'available',
        version: result.version,
      }));
    } else {
      setState(prev => ({ ...prev, status: 'idle' }));
    }
  }

  async function checkPortableUpdate() {
    try {
      const currentVersion = await getVersion();
      // Fetch latest.json from the same endpoint the updater uses
      const resp = await fetch(
        'https://github.com/erthman18/claude-code-launcher/releases/latest/download/latest.json'
      );
      if (!resp.ok) {
        setState(prev => ({ ...prev, status: 'idle' }));
        return;
      }
      const data = await resp.json();
      const latestVersion: string = data.version;

      if (compareSemver(latestVersion, currentVersion) > 0) {
        setState(prev => ({
          ...prev,
          status: 'available',
          version: latestVersion,
        }));
      } else {
        setState(prev => ({ ...prev, status: 'idle' }));
      }
    } catch {
      // Silently fail — don't bother the user
      setState(prev => ({ ...prev, status: 'idle' }));
    }
  }

  const downloadAndInstall = useCallback(async () => {
    if (state.isPortable) {
      // Portable mode: open the download page in browser
      try {
        const url = await invoke<string>('get_portable_download_url');
        const { openUrl } = await import('@tauri-apps/plugin-opener');
        await openUrl(url);
        setState(prev => ({ ...prev, status: 'idle' }));
      } catch (err) {
        console.error('Failed to open download page:', err);
      }
      return;
    }

    // Installer mode: use Tauri updater
    if (!update) return;
    setState(prev => ({ ...prev, status: 'downloading', progress: 0, error: null }));

    try {
      let totalLength = 0;
      let downloaded = 0;

      await update.downloadAndInstall((event) => {
        if (event.event === 'Started') {
          totalLength = event.data.contentLength ?? 0;
        } else if (event.event === 'Progress') {
          downloaded += event.data.chunkLength;
          if (totalLength > 0) {
            setState(prev => ({
              ...prev,
              progress: Math.round((downloaded / totalLength) * 100),
            }));
          }
        } else if (event.event === 'Finished') {
          setState(prev => ({ ...prev, progress: 100 }));
        }
      });

      await relaunch();
    } catch (err) {
      console.error('Update download failed:', err);
      setState(prev => ({
        ...prev,
        status: 'error',
        error: err instanceof Error ? err.message : String(err),
      }));
    }
  }, [update, state.isPortable]);

  const dismiss = useCallback(() => {
    setState({ status: 'idle', version: null, progress: 0, error: null, isPortable: state.isPortable });
    setUpdate(null);
  }, [state.isPortable]);

  const retry = useCallback(() => {
    downloadAndInstall();
  }, [downloadAndInstall]);

  return {
    ...state,
    downloadAndInstall,
    dismiss,
    retry,
  };
}
