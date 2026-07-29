import { readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import sharp from 'sharp';

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const sourcePath = path.join(repoRoot, 'static', 'static', 'favicon.svg');
const source = await readFile(sourcePath);

const outputs = [
	['static/favicon.png', 512],
	['static/static/favicon.png', 512],
	['static/static/favicon-dark.png', 512],
	['static/static/favicon-96x96.png', 96],
	['static/static/apple-touch-icon.png', 180],
	['static/static/web-app-manifest-192x192.png', 192],
	['static/static/web-app-manifest-512x512.png', 512],
	['static/static/splash.png', 512],
	['static/static/splash-dark.png', 512],
	['backend/open_webui/static/favicon.png', 512],
	['backend/open_webui/static/favicon-dark.png', 512],
	['backend/open_webui/static/favicon-96x96.png', 96],
	['backend/open_webui/static/apple-touch-icon.png', 180],
	['backend/open_webui/static/web-app-manifest-192x192.png', 192],
	['backend/open_webui/static/web-app-manifest-512x512.png', 512],
	['backend/open_webui/static/splash.png', 512],
	['backend/open_webui/static/splash-dark.png', 512],
	['backend/open_webui/static/logo.png', 512]
];

for (const [relativePath, size] of outputs) {
	const outputPath = path.join(repoRoot, relativePath);
	await sharp(source).resize(size, size).png({ compressionLevel: 9 }).toFile(outputPath);
}

const faviconPng = await sharp(source).resize(256, 256).png({ compressionLevel: 9 }).toBuffer();
const header = Buffer.alloc(22);
header.writeUInt16LE(0, 0);
header.writeUInt16LE(1, 2);
header.writeUInt16LE(1, 4);
header.writeUInt8(0, 6);
header.writeUInt8(0, 7);
header.writeUInt8(0, 8);
header.writeUInt8(0, 9);
header.writeUInt16LE(1, 10);
header.writeUInt16LE(32, 12);
header.writeUInt32LE(faviconPng.length, 14);
header.writeUInt32LE(22, 18);
const faviconIco = Buffer.concat([header, faviconPng]);

await writeFile(path.join(repoRoot, 'static', 'static', 'favicon.ico'), faviconIco);
await writeFile(path.join(repoRoot, 'backend', 'open_webui', 'static', 'favicon.ico'), faviconIco);

console.log(`Generated ${outputs.length + 2} OpenM brand assets from ${sourcePath}`);
