import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from '@playwright/test';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const distDir = path.resolve(__dirname, '../dist');
const artifactDir = path.resolve(__dirname, '../../artifacts/navigation-polish');

if (!fs.existsSync(artifactDir)) {
  fs.mkdirSync(artifactDir, { recursive: true });
}

// Static file server with SPA fallback
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
  console.log(`Static server listening on http://127.0.0.1:${port}`);

  const chromePath = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
  const browser = await chromium.launch({
    executablePath: fs.existsSync(chromePath) ? chromePath : undefined,
    headless: true,
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-gpu'],
  });

  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();

  // 1. Home
  await page.addInitScript(() => {
    window.sessionStorage.setItem('indusopt.landing.entered', '1');
    window.localStorage.setItem('indusopt.landing.entered', '1');
    window.localStorage.setItem('indusopt.sidebar_collapsed', 'false');
  });

  await page.goto(`http://127.0.0.1:${port}/home`);
  await page.waitForTimeout(600);
  await page.screenshot({ path: path.join(artifactDir, 'home.png'), fullPage: false });
  console.log('Captured home.png');

  // 2. Sidebar Expanded
  await page.screenshot({ path: path.join(artifactDir, 'sidebar-expanded.png'), fullPage: false });
  console.log('Captured sidebar-expanded.png');

  // 3. Sidebar Collapsed (click the toggle button)
  await page.click('.nav-toggle-btn');
  await page.waitForTimeout(400);
  await page.screenshot({ path: path.join(artifactDir, 'sidebar-collapsed.png'), fullPage: false });
  console.log('Captured sidebar-collapsed.png');

  // Re-expand sidebar for subsequent screenshots
  await page.click('.nav-toggle-btn');
  await page.waitForTimeout(400);

  // 4. History Empty
  await page.evaluate(() => {
    window.localStorage.setItem('indusopt.sidebar_collapsed', 'false');
    window.localStorage.removeItem('indusopt.recent_executions');
  });
  await page.goto(`http://127.0.0.1:${port}/runs`);
  await page.waitForTimeout(600);
  await page.screenshot({ path: path.join(artifactDir, 'history-empty.png'), fullPage: false });
  console.log('Captured history-empty.png');

  // 5. History Populated (List)
  await page.evaluate(() => {
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
      },
      {
        execution_id: "exec_s4_noise_9981da4f0012",
        workflow_status: "RUNNING",
        created_at: new Date(Date.now() - 7200000).toISOString(),
        plan: {
          goal: "S4 强噪声与多点异常脉冲自动清洗",
          steps: [{ name: "clean" }, { name: "filter" }]
        },
        artifacts: {}
      }
    ];
    window.localStorage.setItem('indusopt.recent_executions', JSON.stringify(mockList));
  });
  await page.reload();
  await page.waitForTimeout(600);
  await page.screenshot({ path: path.join(artifactDir, 'history-list.png'), fullPage: false });
  console.log('Captured history-list.png');

  await browser.close();
  server.close();
  console.log('All navigation polish screenshots captured!');
  process.exit(0);
});
