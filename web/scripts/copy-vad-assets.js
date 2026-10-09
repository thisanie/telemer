import { copyFileSync, mkdirSync, readdirSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const projectRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const vadDist = path.join(projectRoot, 'node_modules', '@ricky0123', 'vad-web', 'dist')
const onnxDist = path.join(projectRoot, 'node_modules', 'onnxruntime-web', 'dist')
const outputDir = path.join(projectRoot, 'public', 'vad-assets')

mkdirSync(outputDir, { recursive: true })

for (const asset of ['vad.worklet.bundle.min.js', 'silero_vad_v5.onnx']) {
  copyFileSync(path.join(vadDist, asset), path.join(outputDir, asset))
}

const wasmAssets = readdirSync(onnxDist).filter((asset) => asset.endsWith('.wasm'))
if (wasmAssets.length === 0) {
  throw new Error('No ONNX Runtime WebAssembly assets found')
}
for (const asset of wasmAssets) {
  copyFileSync(path.join(onnxDist, asset), path.join(outputDir, asset))
}
