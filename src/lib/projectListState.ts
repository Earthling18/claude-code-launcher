import type { Project } from '../types/project';
import type { GlobalPresets } from '../types/presets';

// Window-local navigation state, never persisted to disk/localStorage (projects
// can contain credentials). A return visit renders cards before its first paint.
export const projectListState: {
  projects: Project[] | null;
  presets: GlobalPresets | null;
  platform: string;
  scrollTop: number;
} = { projects: null, presets: null, platform: 'windows', scrollTop: 0 };

export function rememberProject(project: Project) {
  const cached = projectListState.projects;
  if (!cached) return;
  projectListState.projects = cached.some(p => p.id === project.id)
    ? cached.map(p => p.id === project.id ? project : p)
    : [...cached, project];
}

export function forgetProject(id: string) {
  if (projectListState.projects) {
    projectListState.projects = projectListState.projects.filter(p => p.id !== id);
  }
}
