import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from '@playwright/test';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const distDir = path.resolve(__dirname, '../dist');
const artifactDir = path.resolve(__dirname, '../../artifacts/layout-refactor');

if (!fs.existsSync(artifactDir)) {
  fs.mkdirSync(artifactDir, { recursive: true });
}

// 1. Static file server with SPA fallback
const mimeTypes = {
  '.html': 'text/html',
  '.js': 'text/javascript',
  '.css': 'text/css',
  '.json': 'application/json',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.svg': 'image/svg+xml',
  '.woff': 'font/woff',
  '.woff2': 'font/woff2',
};

const server = http.createServer((req, res) => {
  let urlPath = req.url.split('?')[0];
  let filePath = path.join(distDir, urlPath);

  if (fs.existsSync(filePath) && fs.statSync(filePath).isFile()) {
    const ext = path.extname(filePath).toLowerCase();
    res.writeHead(200, { 'Content-Type': mimeTypes[ext] || 'application/octet-stream' });
    fs.createReadStream(filePath).pipe(res);
  } else {
    // SPA fallback
    const indexPath = path.join(distDir, 'index.html');
    res.writeHead(200, { 'Content-Type': 'text/html' });
    fs.createReadStream(indexPath).pipe(res);
  }
});

server.listen(0, '127.0.0.1', async () => {
  const port = server.address().port;
  console.log(`Static SPA server listening on http://127.0.0.1:${port}`);

  const chromePath = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
  const browser = await chromium.launch({
    executablePath: fs.existsSync(chromePath) ? chromePath : undefined,
    headless: true,
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-gpu'],
  });

  const context = await browser.newContext();
  const page = await context.newPage();

  // Set landing bypass in both sessionStorage and localStorage
  await page.addInitScript(() => {
    window.sessionStorage.setItem('indusopt.landing.entered', '1');
    window.localStorage.setItem('indusopt.landing.entered', '1');
  });

  const routes = [
    { name: 'home-1920x1080.png', path: '/home', width: 1920, height: 1080 },
    { name: 'home-1440x900.png', path: '/home', width: 1440, height: 900 },
    { name: 'workspace-1920x1080.png', path: '/workspace', width: 1920, height: 1080 },
    { name: 'workspace-1440x900.png', path: '/workspace', width: 1440, height: 900 },
    { name: 'datasets-1440x900.png', path: '/datasets', width: 1440, height: 900 },
    { name: 'arx-1440x900.png', path: '/modeling/arx', width: 1440, height: 900 },
    { name: 'optimization-1440x900.png', path: '/modeling/optimization', width: 1440, height: 900 },
    { name: 'deliverables-1440x900.png', path: '/deliverables', width: 1440, height: 900 },
  ];

  for (const r of routes) {
    console.log(`Capturing ${r.name} (${r.width}x${r.height}) on ${r.path}...`);
    await page.setViewportSize({ width: r.width, height: r.height });
    await page.goto(`http://127.0.0.1:${port}${r.path}`);
    await page.waitForTimeout(600);
    const savePath = path.join(artifactDir, r.name);
    await page.screenshot({ path: savePath, fullPage: false });
    console.log(`Saved screenshot: ${savePath}`);
  }

  await browser.close();
  server.close();
  console.log('All screenshots captured successfully!');
  process.exit(0);
});
