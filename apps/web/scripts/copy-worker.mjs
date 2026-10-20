// MapLibre resolves its worker from import.meta.url, which bundlers rewrite. Serve the worker statically instead.
import { copyFileSync, mkdirSync } from 'node:fs';
const src = new URL('../node_modules/maplibre-gl/dist/maplibre-gl-worker.mjs', import.meta.url);
const dst = new URL('../public/maplibre-gl-worker.mjs', import.meta.url);
mkdirSync(new URL('../public/', import.meta.url), { recursive: true });
copyFileSync(src, dst);
console.log('copied maplibre-gl-worker.mjs → public/');
