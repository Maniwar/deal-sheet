// Prepare the Khronos "Car Concept" (CC BY 4.0) for the app: remove logos, keep one paint set,
// make the glass cheap to draw, simplify the mesh and shrink the textures.
import { NodeIO } from '@gltf-transform/core';
import { ALL_EXTENSIONS } from '@gltf-transform/extensions';
import { dedup, prune, weld, simplify, quantize, textureCompress, resample } from '@gltf-transform/functions';
import { MeshoptSimplifier } from 'meshoptimizer';
import sharp from 'sharp';

const [src, out, ratio] = [process.argv[2], process.argv[3], parseFloat(process.argv[4] || '0.45')];
const io = new NodeIO().registerExtensions(ALL_EXTENSIONS);
const doc = await io.read(src);
const root = doc.getRoot();

const logo = (t) => t && /khronos/i.test((t.getName() || '') + (t.getURI() || ''));
const byName = {};
root.listTextures().forEach((t, i) => { byName[i] = t; });
// 1. logos: the Khronos mark is a trademark and is not covered by the model's licence
let logoTex = null;
for (const m of root.listMaterials()) {
  for (const slot of ['BaseColor', 'Emissive']) {
    const t = m['get' + slot + 'Texture']();
    if (!t) continue;
    const img = t.getImage(); const meta = await sharp(Buffer.from(img)).metadata();
    if (meta.width === 512 && meta.height === 128) { logoTex = t; m['set' + slot + 'Texture'](null); if (slot === 'Emissive') m.setEmissiveFactor([0, 0, 0]); }
  }
}
for (const m of root.listMaterials()) {
  const n = m.getName();
  if (n === 'License') m.setBaseColorFactor([0.02, 0.025, 0.035, 1]).setRoughnessFactor(0.6).setMetallicFactor(0);
  if (n === 'Tireside') m.setBaseColorTexture(null).setNormalTexture(null).setBaseColorFactor([0.012, 0.012, 0.014, 1]).setRoughnessFactor(0.85);   // sidewall lettering carries the logos too
  if (n === 'Glass') { m.listExtensions().forEach((e) => m.setExtension(e.extensionName, null)); m.setAlphaMode('BLEND').setBaseColorFactor([0.02, 0.035, 0.06, 0.5]).setRoughnessFactor(0.04).setMetallicFactor(0.1); }
  if (n === 'Paint 1 Carmine') m.setName('Paint');
  if (n === 'Paint 2 Carmine') m.setName('Trim');
  if (n === 'Interior 3 Carmine') m.setName('Interior');
}
// 2. keep the default look only: drop the material variants and what only they used
for (const ext of root.listExtensionsUsed()) if (ext.extensionName === 'KHR_materials_variants') ext.dispose();
// 3. parts nobody sees on a turntable
for (const node of root.listNodes()) if (/^(Engine|Axles|InteriorPedal|BodyHoodInterior|BodyHoodUnder|InteriorSteeringEmblem)/.test(node.getName())) node.dispose();

await MeshoptSimplifier.ready;
await doc.transform(
  dedup(), prune(), weld(),
  simplify({ simplifier: MeshoptSimplifier, ratio, error: 0.0012 }),
  prune(), dedup(),
  textureCompress({ encoder: sharp, resize: [1024, 1024], targetFormat: 'webp', quality: 82 }),
  quantize({ quantizePosition: 14, quantizeNormal: 10, quantizeTexcoord: 12 }),
);
let tris = 0;
for (const mesh of root.listMeshes()) for (const p of mesh.listPrimitives()) tris += (p.getIndices() ? p.getIndices().getCount() : p.getAttribute('POSITION').getCount()) / 3;
await io.write(out, doc);
console.log('triangles', Math.round(tris), '| materials', root.listMaterials().map((m) => m.getName() || '(unnamed)').join(', '));
console.log('extensions', root.listExtensionsUsed().map((e) => e.extensionName).join(', '), '| logo texture left:', root.listTextures().some(logo), '| textures', root.listTextures().length);
