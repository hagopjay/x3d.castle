// Khronos glTF-Validator over a list of .glb files. Usage: node gltf_validate.mjs out.json a.glb b.glb ...
// Prints one line per file and writes the validator's counts and first messages to out.json.
import fs from 'node:fs'; import path from 'node:path'; import { createRequire } from 'node:module';
const require = createRequire(import.meta.url); const v = require('gltf-validator');
const [out, ...files] = process.argv.slice(2); const rows = [];
console.log('gltf-validator', v.version());
for (const f of files) {
  try {
    const bytes = new Uint8Array(fs.readFileSync(f));
    const r = await v.validateBytes(bytes, { uri: path.basename(f), maxIssues: 0 });
    const i = r.issues;
    rows.push({ file: f, bytes: bytes.length, errors: i.numErrors, warnings: i.numWarnings, infos: i.numInfos, hints: i.numHints,
      generator: r.info.generator, extensionsUsed: r.info.extensionsUsed || [], extensionsRequired: r.info.extensionsRequired || [],
      stats: { meshes: r.info.drawCallCount, materials: r.info.materialCount, triangles: r.info.totalTriangleCount, vertices: r.info.totalVertexCount, animations: r.info.animationCount },
      messages: i.messages.filter(m => m.severity <= 1).slice(0, 6).map(m => `${m.code} @ ${m.pointer}`) });
    console.log(`${path.basename(f).padEnd(80)} E=${i.numErrors} W=${i.numWarnings} I=${i.numInfos} ${bytes.length}B ${r.info.generator || ''}`);
  } catch (e) { rows.push({ file: f, fail: String(e).slice(0, 200) }); console.log(path.basename(f), 'FAIL', String(e).slice(0, 120)); }
}
fs.writeFileSync(out, JSON.stringify(rows, null, 1));
