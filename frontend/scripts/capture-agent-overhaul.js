import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from '@playwright/test';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const distDir = path.resolve(__dirname, '../dist');
const artifactDir = path.resolve(__dirname, '../../artifacts/agent-workspace-overhaul');

if (!fs.existsSync(artifactDir)) {
  fs.mkdirSync(artifactDir, { recursive: true });
}

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
    const indexPath = path.join(distDir, 'index.html');
    res.writeHead(200, { 'Content-Type': 'text/html' });
    fs.createReadStream(indexPath).pipe(res);
  }
});

server.listen(0, '127.0.0.1', async () => {
  const port = server.address().port;
  console.log(`Static server listening on http://127.0.0.1:${port}`);

  const chromePath = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
  const browser = await chromium.launch({
    executablePath: fs.existsSync(chromePath) ? chromePath : undefined,
    headless: true,
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-gpu'],
  });

  const viewports = [
    { name: '1366x768', width: 1366, height: 768 },
    { name: '1440x900', width: 1440, height: 900 },
    { name: '1920x1080', width: 1920, height: 1080 },
  ];

  for (const vp of viewports) {
    const context = await browser.newContext({ viewport: { width: vp.width, height: vp.height } });
    const page = await context.newPage();

    await page.addInitScript(() => {
      window.sessionStorage.setItem('indusopt.landing.entered', '1');
      window.localStorage.setItem('indusopt.landing.entered', '1');
      window.localStorage.setItem('indusopt.sidebar_collapsed', 'false');

      const mockList = [
        {
          execution_id: "exec_s6_dyn_8a1f49b2c3d1",
          workflow_status: "SUCCEEDED",
          created_at: new Date().toISOString(),
          plan: {
            goal: "S6 动态建模与参数全流程优化",
            steps: [{ name: "clean" }, { name: "segment" }, { name: "delay" }, { name: "collin" }, { name: "arx" }, { name: "optuna" }, { name: "report" }]
          },
          artifacts: {
            arx_model: { na: 2, nb: 2 },
            optimization_study: { best_fit: 0.89 },
            report: { id: "rep_01" }
          }
        },
        {
          execution_id: "exec_s3_delay_39d01be7a21f",
          workflow_status: "WAITING_CONFIRMATION",
          created_at: new Date(Date.now() - 3600000).toISOString(),
          plan: {
            goal: "S3 时序分析与长滞后通道校准",
            steps: [{ name: "clean" }, { name: "delay" }, { name: "confirm" }]
          },
          artifacts: {
            arx_model: { na: 1, nb: 1 }
          }
        }
      ];
      window.localStorage.setItem('indusopt.recent_executions', JSON.stringify(mockList));
    });

    // 1. Home
    await page.goto(`http://127.0.0.1:${port}/home`);
    await page.waitForTimeout(600);
    await page.screenshot({ path: path.join(artifactDir, `home-${vp.name}.png`), fullPage: false });
    console.log(`Captured home-${vp.name}.png`);

    // 2. Workspace Empty / Composer
    await page.goto(`http://127.0.0.1:${port}/workspace`);
    await page.waitForTimeout(600);
    await page.screenshot({ path: path.join(artifactDir, `workspace-empty-${vp.name}.png`), fullPage: false });
    console.log(`Captured workspace-empty-${vp.name}.png`);

    // 3. Runs (History)
    await page.goto(`http://127.0.0.1:${port}/runs`);
    await page.waitForTimeout(600);
    await page.screenshot({ path: path.join(artifactDir, `runs-${vp.name}.png`), fullPage: false });
    console.log(`Captured runs-${vp.name}.png`);

    // 4. Assets
    await page.goto(`http://127.0.0.1:${port}/assets`);
    await page.waitForTimeout(600);
    await page.screenshot({ path: path.join(artifactDir, `assets-${vp.name}.png`), fullPage: false });
    console.log(`Captured assets-${vp.name}.png`);

    await context.close();
  }

  await browser.close();
  server.close();
  console.log('All visual screenshots captured successfully!');
  process.exit(0);
});
