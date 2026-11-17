// Used only by tests/ui/vite.config.ts; never included in production builds.
import { DEFAULT_PROJECT_CONFIG, type Project } from '../../src/types/project';
const projects: Project[] = Array.from({ length: 48 }, (_, i) => ({
  id: `qa-${i}`, name: `滚动验收项目 ${String(i + 1).padStart(2, '0')}`,
  working_directory: '/tmp/连接 验收', config: { ...DEFAULT_PROJECT_CONFIG, mode: 'codex', skip_permissions: false },
  is_default: i === 0, is_pinned: false, created_at: 0, updated_at: 0, sort_order: i,
}));
let reads = 0;
export async function invoke(command: string, args: Record<string, any> = {}): Promise<any> {
  if (command === 'get_projects') {
    if (reads++) await new Promise(resolve => setTimeout(resolve, 1200));
    return structuredClone(projects);
  }
  if (command === 'get_project') return structuredClone(projects.find(p => p.id === args.id));
  if (command === 'update_project') {
    const p = projects.find(p => p.id === args.id)!;
    if (args.name !== undefined) p.name = args.name;
    if (args.config) p.config = args.config;
    if (args.isPinned !== undefined) p.is_pinned = args.isPinned;
    return structuredClone(p);
  }
  if (command === 'get_platform') return new URLSearchParams(location.search).get('platform') || 'macos';
  if (command === 'get_onboarding_status') return true;
  if (command === 'get_global_presets') return { proxies: [], models: [] };
  if (command.startsWith('check_')) return { installed: true, version: 'test', message: '验收环境' };
  if (command === 'record_frontend_error') throw new Error(args.message);
  return null;
}
export async function listen() { return () => {}; }
export async function getVersion() { return '1.3.1'; }
export async function check() { return null; }
export async function openUrl() {}
export async function writeText() {}
export async function exit() {}
export async function relaunch() {}
