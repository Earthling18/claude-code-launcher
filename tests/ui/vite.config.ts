import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { fileURLToPath } from 'node:url';
const mock = fileURLToPath(new URL('./tauri-mock.ts', import.meta.url));
export default defineConfig({
  plugins: [react(), { name: 'ui-fixture', transformIndexHtml: html => html.replace('/src/main.tsx', '/tests/ui/main.tsx') }],
  resolve: { alias: [
    { find: /^@tauri-apps\/api\/(core|event|app)$/, replacement: mock },
    { find: /^@tauri-apps\/plugin-(updater|opener|process|clipboard-manager)$/, replacement: mock },
  ] },
  server: { host: '127.0.0.1', port: 1427, strictPort: true },
});
