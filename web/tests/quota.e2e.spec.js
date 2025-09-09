// @ts-check
import { test, expect } from '@playwright/test';

function ndjson(lines) {
  return lines.map(l => JSON.stringify(l)).join('\n') + '\n';
}

// This E2E test simulates a minimal backend quota logic via route interceptions.
// It verifies that pressing the Generate button decrements the UI counter and
// after 3 attempts the 4th is blocked with a quota message.

test('quota: three generates decrement to 0/3, 4th shows daily limit message', async ({ page }) => {
  await page.goto('/');

  // Force BYOK not required to simplify UI gating for the test
  await page.route('**/config', async route => {
    await route.fulfill({ status: 200, headers: { 'content-type': 'application/json' }, body: JSON.stringify({ require_byok: false }) });
  });

  // Quota state simulated on the client-side for this test
  let remaining = 3;
  const perDay = 3;

  await page.route('**/api/quota', async route => {
    await route.fulfill({
      status: 200,
      headers: { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store' },
      body: JSON.stringify({ per_day: perDay, remaining }),
    });
  });

  await page.route('**/api/structure', async route => {
    if (remaining <= 0) {
      await route.fulfill({
        status: 429,
        headers: { 'content-type': 'application/json; charset=utf-8' },
        body: JSON.stringify({ detail: 'Daily quota exceeded. Please try again tomorrow.' })
      });
      return;
    }
    // Consume 1 attempt
    remaining -= 1;
    await route.fulfill({
      status: 200,
      headers: { 'content-type': 'application/json; charset=utf-8' },
      body: JSON.stringify({ statistics: { model_name: 'openai/gpt-oss-20b', input_time: 0, output_time: 0, input_tokens: 0, output_tokens: 0, total_time: 0 }, structure: { 'Fejezet 1': 'Leírás' } })
    });
  });

  await page.route('**/api/sections/stream', async route => {
    const title = 'Fejezet 1';
    const body = ndjson([{ type: 'section_start', title }, { type: 'done' }]);
    await route.fulfill({ status: 200, headers: { 'content-type': 'application/x-ndjson' }, body });
  });

  // Subject
  await page.fill('#subject', 'Kvóta teszt');

  // 1st generate -> 2/3
  await page.click('#generateBtn');
  await expect(page.locator('#quotaLabel')).toHaveText('2/3');

  // 2nd generate -> 1/3
  await page.click('#generateBtn');
  await expect(page.locator('#quotaLabel')).toHaveText('1/3');

  // 3rd generate -> 0/3
  await page.click('#generateBtn');
  await expect(page.locator('#quotaLabel')).toHaveText('0/3');

  // 4th generate -> blocked with toast
  await page.click('#generateBtn');
  await expect(page.locator('#notify')).toBeVisible();
  const text = (await page.locator('#notifyText').innerText()).toLowerCase();
  expect(text.includes('mai kvótát') || text.includes('napi keretet')).toBeTruthy();
});
