import { useSortable } from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import { ProjectCard } from './ProjectCard';
import type { Project } from '../types/project';
import type { GlobalPresets } from '../types/presets';

interface SortableProjectCardProps {
  project: Project;
  platform: string;
  presets?: GlobalPresets | null;
  onLaunch: (id: string) => void;
  onSelect: (id: string) => void;
}

export const SortableProjectCard: React.FC<SortableProjectCardProps> = ({
  project,
  platform,
  presets,
  onLaunch,
  onSelect,
}) => {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: project.id });

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
  };

  return (
    <div ref={setNodeRef} style={style} {...attributes} {...listeners}>
      <ProjectCard
        project={project}
        platform={platform}
        presets={presets}
        onLaunch={onLaunch}
        onSelect={onSelect}
        isDragging={isDragging}
      />
    </div>
  );
};
