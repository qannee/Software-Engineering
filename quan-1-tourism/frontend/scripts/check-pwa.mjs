import { existsSync, readFileSync } from 'node:fs';

const manifest = JSON.parse(readFileSync(new URL('../public/manifest.webmanifest', import.meta.url), 'utf8'));
const requiredIcons = ['192x192', '512x512'];
for (const size of requiredIcons) {
  const icon = manifest.icons?.find((item) => item.sizes === size && item.type === 'image/png');
  if (!icon || !existsSync(new URL(`../public${icon.src}`, import.meta.url))) {
    throw new Error(`PWA manifest is missing its ${size} PNG icon`);
  }
}
for (const requiredFile of ['offline.html', 'sw.js']) {
  if (!existsSync(new URL(`../public/${requiredFile}`, import.meta.url))) throw new Error(`Missing PWA file: ${requiredFile}`);
}
console.log('PWA manifest, icons and offline files are present.');
