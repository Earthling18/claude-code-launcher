import { dialogApi } from '../api';

interface DirectoryPickerProps {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  disabled?: boolean;
}

export const DirectoryPicker: React.FC<DirectoryPickerProps> = ({
  value,
  onChange,
  placeholder = '选择工作目录',
  disabled = false,
}) => {
  const handleBrowse = async () => {
    try {
      const selected = await dialogApi.selectDirectory();
      if (selected) {
        onChange(selected);
      }
    } catch (error) {
      console.error('选择目录失败:', error);
    }
  };

  return (
    <div className="flex min-w-0 items-center gap-2">
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        disabled={disabled}
        className="min-w-0 flex-1 font-mono disabled:opacity-50"
      />
      <button
        type="button"
        onClick={handleBrowse}
        disabled={disabled}
        className="btn btn-secondary shrink-0"
      >
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>
        浏览
      </button>
    </div>
  );
};
