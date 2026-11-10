import { defineConfig } from 'vitest/config';

export default defineConfig({
  base: './',
  build: { outDir: 'dist', emptyOutDir: true },
  server: { host: '127.0.0.1', strictPort: true },
  test: { include: ['tests/**/*.test.{ts,tsx}'], environment: 'jsdom', restoreMocks: true },
});
