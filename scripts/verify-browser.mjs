import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
const require = createRequire(path.resolve('frontend/package.json'));
const { chromium, expect } = require('@playwright/test');
if (!process.env.TALENT_ACCEPTANCE_PASSWORD) throw new Error('TALENT_ACCEPTANCE_PASSWORD is required');
fs.mkdirSync('.tmp/browser-verification', { recursive: true });
const browser = await chromium.launch({ channel: 'chrome', headless: true });
const context = await browser.newContext({ acceptDownloads: true, viewport: { width: 1440, height: 1000 } });
const page = await context.newPage();
const errors = [];
const origins = new Set();
page.on('pageerror', error => errors.push(error.message));
page.on('request', request => origins.add(new URL(request.url()).origin));
page.on('response', async response => {
  if (response.url().endsWith('/export.csv')) {
    fs.writeFileSync('.tmp/browser-verification/export-response.json', JSON.stringify({status: response.status(), headers: response.headers()}));
  }
});
try {
  await page.goto('http://127.0.0.1:18080');
  await page.getByLabel('账号', { exact: true }).fill('admin');
  await page.getByLabel('密码', { exact: true }).fill(process.env.TALENT_ACCEPTANCE_PASSWORD);
  await page.getByRole('button', { name: /登\s*录/ }).click();
  await expect(page.getByRole('heading', { name: '任务中心', exact: true })).toBeVisible();
  await page.screenshot({ path: '.tmp/browser-verification/ui-tasks.png', fullPage: true, animations: 'disabled' });
  await page.getByRole('menuitem', { name: '人才库' }).click();
  const verifyWorkflow = process.env.TALENT_VERIFY_WORKFLOW === '1';
  if (verifyWorkflow) {
    const workflow = JSON.parse(fs.readFileSync('data/resume-workflow-deployment.json', 'utf8'));
    if (workflow.status !== 'passed') throw new Error('Workflow deployment verification has not passed');
    await page.locator(`tr[data-row-key="${workflow.talent_ids[1]}"]`).getByRole('button', { name: '查看档案' }).click();
    await expect(page.getByText('简历核心信息待补充：姓名、有效联系方式、教育或工作经历', { exact: true })).toBeVisible();
  } else {
    await page.getByRole('button', { name: '查看档案' }).first().click();
  }
  await expect(page.locator('.ant-drawer-open')).toBeVisible();
  await page.screenshot({ path: '.tmp/browser-verification/ui-profile.png', fullPage: true, animations: 'disabled' });
  await page.locator('.ant-drawer-open .ant-drawer-close').last().click();
  await page.getByRole('menuitem', { name: '岗位与匹配' }).click();
  const offline = page.getByRole('row').filter({ hasText: '合成离线 Python 岗位' }).first();
  await expect(page.getByRole('heading', { name: '岗位列表', exact: true })).toBeVisible();
  await expect(page.locator('.ant-spin-spinning')).toHaveCount(0);
  for (let i = 0; i < 20 && !await offline.count(); i++) {
    await page.locator('.ant-pagination-next:not(.ant-pagination-disabled) button').click();
  }
  await offline.getByRole('button', { name: '条件与匹配结果' }).click();
  await page.getByRole('tab', { name: '匹配历史' }).click();
  const matchResponse = page.waitForResponse(response => /\/api\/v1\/matches\/[^/]+$/.test(response.url()) && response.request().method() === 'GET');
  await page.getByRole('button', { name: '查看结果', exact: true }).first().click();
  const match = await (await matchResponse).json();
  await expect(page.getByText('岗位匹配结果', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: '评分与依据' }).first()).toBeVisible();
  const namesakes = match.results.filter(candidate => candidate.name === '离线合成人才甲');
  if (namesakes.length !== 2) throw new Error('Expected two synthetic same-name candidates for comparison verification');
  const labels = [];
  for (const candidate of namesakes) {
    const checkbox = page.getByRole('checkbox', { name: new RegExp('^比较 离线合成人才甲（' + candidate.talent_id.slice(0, 8)) });
    labels.push((await checkbox.getAttribute('aria-label')).replace(/^比较 /, ''));
    await checkbox.check();
  }
  if (new Set(labels).size !== 2) throw new Error('Same-name comparison labels are not distinct');
  await expect(page.getByRole('img', { name: '候选人评分维度比较图' })).toBeVisible();
  await page.getByText('查看比较数值').click();
  const comparison = page.locator('.accessible-chart');
  for (const label of labels) await expect(comparison.getByRole('columnheader', { name: label, exact: true })).toBeVisible();
  for (const dimension of namesakes[0].score.dimensions) {
    await expect(comparison.getByRole('row').filter({ hasText: dimension.label }).getByRole('cell')).toHaveText(
      namesakes.map(candidate => candidate.score.dimensions.find(item => item.key === dimension.key).score.toFixed(1)),
    );
  }
  await page.getByRole('checkbox', { name: '比较 ' + labels[0], exact: true }).uncheck();
  await expect(page.getByRole('checkbox', { name: '比较 ' + labels[1], exact: true })).toBeChecked();
  await expect(comparison.getByRole('columnheader', { name: labels[1], exact: true })).toBeVisible();
  await page.getByRole('checkbox', { name: '比较 ' + labels[0], exact: true }).check();
  await page.screenshot({ path: '.tmp/browser-verification/ui-comparison.png', fullPage: true, animations: 'disabled' });
  const [download] = await Promise.all([
    page.waitForEvent('download'),
    page.locator('a[href$="/export.csv"]').click(),
  ]);
  await download.saveAs('.tmp/browser-verification/ui-candidates.csv');
  await page.getByRole('button', { name: '评分与依据' }).first().click();
  await expect(page.getByText('维度评分与依据', { exact: true })).toBeVisible();
  await page.screenshot({ path: '.tmp/browser-verification/ui-match-evidence.png', fullPage: true, animations: 'disabled' });
  if (errors.length) throw new Error(errors.join('\n'));
  if ([...origins].some(origin => origin !== 'http://127.0.0.1:18080')) throw new Error('Unexpected external browser request');
  const csv = fs.readFileSync('.tmp/browser-verification/ui-candidates.csv', 'utf8');
  if (!csv.includes('离线合成人才甲')) throw new Error('Real candidate export missing');
  fs.writeFileSync('data/browser-real.json', JSON.stringify({ status: 'passed', recorded_utc: new Date().toISOString(), scope: 'real production web and API; no mocked responses', checks: ['login', 'tasks', 'profile details', ...(verifyWorkflow ? ['partial workflow missing-field warning visible'] : []), 'job history', 'same-name comparison labels', 'comparison numbers agree with saved scores', 'stable labels after deselect', 'comparison chart', 'match explanation', 'real CSV download', 'no external browser requests'], page_errors: errors, request_origins: [...origins] }, null, 2));
  console.log('Real browser checks passed');
} catch (error) {
  await page.screenshot({ path: '.tmp/browser-verification/ui-error.png', fullPage: true, animations: 'disabled' });
  console.error(String(error).replaceAll(process.env.TALENT_ACCEPTANCE_PASSWORD, '[REDACTED]'));
  process.exitCode = 1;
} finally {
  await browser.close();
}
