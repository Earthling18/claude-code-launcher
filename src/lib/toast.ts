// Lightweight toast bus. Imperative API so any module can call `toast.error('...')`.

export type ToastType = 'success' | 'error' | 'info';

export interface Toast {
  id: number;
  type: ToastType;
  message: string;
}

let nextId = 0;
let queue: Toast[] = [];
const subs = new Set<(toasts: Toast[]) => void>();

function emit() {
  for (const fn of subs) fn(queue);
}

function show(message: string, type: ToastType, durationMs = 3200) {
  const id = ++nextId;
  queue = [...queue, { id, type, message }];
  emit();
  if (durationMs > 0) {
    setTimeout(() => dismiss(id), durationMs);
  }
  return id;
}

function dismiss(id: number) {
  queue = queue.filter(t => t.id !== id);
  emit();
}

export const toast = {
  success: (m: string, d?: number) => show(m, 'success', d),
  error:   (m: string, d?: number) => show(m, 'error', d ?? 4500),
  info:    (m: string, d?: number) => show(m, 'info', d),
  dismiss,
  subscribe(fn: (toasts: Toast[]) => void) {
    subs.add(fn);
    fn(queue);
    return () => { subs.delete(fn); };
  },
};
