import vue from '@vitejs/plugin-vue'

/**
 * * unocss插件，原子css
 * https://github.com/antfu/unocss
 */
import Unocss from 'unocss/vite'

// rollup打包分析插件
import visualizer from 'rollup-plugin-visualizer'
// 压缩
import viteCompression from 'vite-plugin-compression'
// Monaco Editor web worker 支持（解决编辑器初始化卡死 / 白屏）
import monacoEditorPlugin from 'vite-plugin-monaco-editor'

import { configHtmlPlugin } from './html'
import unplugin from './unplugin'

export function createVitePlugins(viteEnv, isBuild) {
  const plugins = [
    vue(),
    ...unplugin,
    configHtmlPlugin(viteEnv, isBuild),
    Unocss(),
    // Monaco 只加载需要的 worker，减少构建体积
    monacoEditorPlugin({
      languageWorkers: ['editorWorkerService'],
    }),
  ]

  if (viteEnv.VITE_USE_COMPRESS) {
    plugins.push(viteCompression({ algorithm: viteEnv.VITE_COMPRESS_TYPE || 'gzip' }))
  }

  if (isBuild) {
    plugins.push(
      visualizer({
        open: true,
        gzipSize: true,
        brotliSize: true,
      }),
    )
  }

  return plugins
}
