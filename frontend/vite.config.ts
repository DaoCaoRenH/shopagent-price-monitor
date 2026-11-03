import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'

export default defineConfig({
    plugins: [vue()],
    base: '/static/',
    build: {
        license: { fileName: 'third-party-licenses.md' },
        outDir: fileURLToPath(new URL('../src/shopagent_monitor/app/static', import.meta.url)),
        emptyOutDir: true,
    },
    server: { proxy: { '/api': 'http://127.0.0.1:8092' } },
})
