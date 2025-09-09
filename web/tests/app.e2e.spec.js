// @ts-check
import { test, expect } from '@playwright/test';

async function setRange(page, selector, value) {
  await page.evaluate(({ selector, value }) => {
    const el = document.querySelector(selector);
    if (el) {
      el.value = String(value);
      el.dispatchEvent(new Event('input', { bubbles: true }));
      el.dispatchEvent(new Event('change', { bubbles: true }));
    }
  }, { selector, value });

test('simple template fills subject', async ({ page }) => {
  await page.goto('/');
  const tplBtn = page.locator('#simpleTemplates button').first();
  const subj = await tplBtn.getAttribute('data-subject');
  await tplBtn.click();
  await expect(page.locator('#subject')).toHaveValue(subj || '');
});

test('advanced template sets subject and controls and sends recommended params', async ({ page }) => {
  await page.goto('/');

  // Capture body of sections request
  /** @type {any[]} */
  const bodies = [];
  await page.route('**/api/sections/stream', async route => {
    const postData = route.request().postDataJSON();
    bodies.push(postData);
    // Return a minimal successful stream
    const title = 'Fejezet 1';
    const body = ndjson([
      { type: 'section_start', title },
      { type: 'section_end', title },
      { type: 'done' },
    ]);
    await route.fulfill({ status: 200, headers: { 'content-type': 'application/x-ndjson' }, body });
  });

  await mockStructure(page, { 'Fejezet 1': 'Leírás' });

  // Click any advanced template
  const advTpl = page.locator('#advancedTemplates button').first();
  const tplSubject = await advTpl.getAttribute('data-subject');
  const tplStyle = await advTpl.getAttribute('data-style');
  const tplLevel = await advTpl.getAttribute('data-level');
  const tplTemp = Number(await advTpl.getAttribute('data-temp'));
  const tplTopP = Number(await advTpl.getAttribute('data-top-p'));
  const tplTarget = Number(await advTpl.getAttribute('data-target'));
  await advTpl.click();

  // Subject applied
  await expect(page.locator('#subject')).toHaveValue(tplSubject || '');

  // Generate
  await page.click('#generateBtn');

  await expect.poll(() => bodies.length, { timeout: 5000 }).toBeGreaterThan(0);
  const params = bodies[0].params;
  expect(params.style).toBe(tplStyle);
  expect(params.reading_level).toBe(tplLevel);
  expect(Number(params.temperature)).toBeCloseTo(tplTemp, 1);
  expect(Number(params.top_p)).toBeCloseTo(tplTopP, 1);
  expect(Number(params.target_length)).toBeCloseTo(tplTarget, 0);
});

test('extra instructions propagate to both structure and stream requests', async ({ page }) => {
  await page.goto('/');

  /** @type {any | null} */
  let capturedStructure = null;
  /** @type {any | null} */
  let capturedStream = null;

  await page.route('**/api/structure', async route => {
    capturedStructure = route.request().postDataJSON();
    await route.fulfill({
      status: 200,
      headers: { 'content-type': 'application/json; charset=utf-8' },
      body: JSON.stringify({ statistics: { model_name: 'openai/gpt-oss-20b', input_time: 0, output_time: 0, input_tokens: 0, output_tokens: 0, total_time: 0 }, structure: { 'Fejezet 1': 'Leírás' } })
    });
  });

  await page.route('**/api/sections/stream', async route => {
    capturedStream = route.request().postDataJSON();
    const title = 'Fejezet 1';
    const body = ndjson([
      { type: 'section_start', title },
      { type: 'section_end', title },
      { type: 'done' },
    ]);
    await route.fulfill({ status: 200, headers: { 'content-type': 'application/x-ndjson' }, body });
  });

  // Open extra panel and fill fields
  await page.click('#extraToggle');
  await page.fill('#instrRequired', 'Legyenek hivatkozások és esettanulmányok.');
  await page.fill('#instrQuestions', 'Mik a fő kihívások? Hogyan kezeljük őket?');
  await page.fill('#instrGoal', 'Oktatási cél, közönség: kezdők.');

  // Subject + generate
  await page.fill('#subject', 'Teszt téma');
  await page.click('#generateBtn');

  await expect.poll(() => !!capturedStructure && !!capturedStream, { timeout: 5000 }).toBeTruthy();
  expect(capturedStructure.params.extra_instructions).toContain('hivatkozások');
  expect(capturedStream.params.extra_instructions).toContain('Oktatási cél');
});

test('structure request uses selected model and sliders (temp, top_p)', async ({ page }) => {
  await page.goto('/');

  /** @type {any|null} */
  let captured = null;

  await page.route('**/api/structure', async route => {
    captured = route.request().postDataJSON();
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

  await page.click('#modeToggle');
  await page.click('[data-model="openai/gpt-oss-120b"]');
  await setRange(page, '#temperature', 0.55);
  await setRange(page, '#topP', 0.85);

  await page.fill('#subject', 'Teszt téma');
  await page.click('#generateBtn');

  await expect.poll(() => !!captured, { timeout: 5000 }).toBeTruthy();
  expect(captured.params.model).toBe('openai/gpt-oss-120b');
  expect(Number(captured.params.temperature)).toBeCloseTo(0.55, 2);
  expect(Number(captured.params.top_p)).toBeCloseTo(0.85, 2);
});

test('downloads disabled during generation and progress visible; enabled after done', async ({ page }) => {
  await page.goto('/');

  await mockStructure(page, { 'Fejezet 1': 'Leírás' });

  await page.route('**/api/sections/stream', async route => {
    const title = 'Fejezet 1';
    // Delay stream to observe in-progress state
    await new Promise(r => setTimeout(r, 700));
    const body = ndjson([{ type: 'section_start', title }, { type: 'section_end', title }, { type: 'done' }]);
    await route.fulfill({ status: 200, headers: { 'content-type': 'application/x-ndjson' }, body });
  });

  await page.fill('#subject', 'Teszt téma');
  await page.click('#generateBtn');

  // While generating
  await expect(page.locator('#downloadTxt')).toBeDisabled();
  await expect(page.locator('#downloadPdf')).toBeDisabled();
  await expect(page.locator('#progressOuter')).toBeVisible();

  // After done
  await expect(page.locator('#downloadTxt')).toBeEnabled();
  await expect(page.locator('#downloadPdf')).toBeEnabled();
});

test('stats panel shows fixed model label and estimated word count', async ({ page }) => {
  await page.goto('/');

  await mockStructure(page, { 'Fejezet 1': 'Leírás' });

  await page.route('**/api/sections/stream', async route => {
    const title = 'Fejezet 1';
    const body = ndjson([
      { type: 'section_start', title },
      { type: 'token', title, delta: 'Hello ' },
      { type: 'token', title, delta: 'világ' },
      { type: 'stats', title, statistics: { model_name: 'any/real-model', input_time: 0.1, output_time: 0.2, input_tokens: 2, output_tokens: 2, total_time: 0.3 } },
      { type: 'section_end', title },
      { type: 'done' },
    ]);
    await route.fulfill({ status: 200, headers: { 'content-type': 'application/x-ndjson' }, body });
  });

  await page.fill('#subject', 'Teszt téma');
  await page.click('#generateBtn');

  await expect(page.locator('#statModel')).toHaveText('HunBook-Agent_v0.6');
  await expect(page.locator('#statTokens')).toHaveText('2');
});

test('stop during structure phase resets UI immediately', async ({ page }) => {
  await page.goto('/');

  // Slow down structure to click Stop before it completes
  await page.route('**/api/structure', async route => {
    await new Promise(r => setTimeout(r, 1200));
    await route.fulfill({
      status: 200,
      headers: { 'content-type': 'application/json; charset=utf-8' },
      body: JSON.stringify({ statistics: { model_name: 'openai/gpt-oss-20b', input_time: 0, output_time: 0, input_tokens: 0, output_tokens: 0, total_time: 0 }, structure: { 'Fejezet 1': 'Leírás' } })
    });
  });

  await page.fill('#subject', 'Teszt téma');
  await page.click('#generateBtn');

  // Click Stop quickly while /api/structure is pending
  await page.click('#stopBtn');

  // Expect reset + toast
  await expect(page.locator('#notify')).toBeVisible();
  const text = await page.locator('#notifyText').innerText();
  expect(text.toLowerCase()).toContain('megszakítva');

  // Structure area remains empty and Stop disabled again
  await expect(page.locator('#structure').locator('> div')).toHaveCount(0);
  await expect(page.locator('#stopBtn')).toBeDisabled();
});

test('BYOK required: backend returns 401 -> modal opens and warning appears', async ({ page }) => {
  await page.goto('/');

  // Return 401 for /api/structure when no Authorization header
  await page.route('**/api/structure', async route => {
    const headers = route.request().headers();
    const hasAuth = headers['authorization'] || headers['Authorization'];
    if (!hasAuth) {
      await route.fulfill({ status: 401, headers: { 'content-type': 'application/json' }, body: JSON.stringify({ detail: 'API key required' }) });
      return;
    }
    await route.fulfill({ status: 200, headers: { 'content-type': 'application/json' }, body: JSON.stringify({ statistics: { model_name: 'm', input_time: 0, output_time: 0, input_tokens: 0, output_tokens: 0, total_time: 0 }, structure: { 'Fejezet 1': 'Leírás' } }) });
  });

  // Ensure subject is provided
  await page.fill('#subject', 'Teszt téma');
  await page.click('#generateBtn');

  // Expect BYOK modal to be visible
  await expect(page.locator('#byokModal')).toBeVisible();
  await expect(page.locator('#notify')).toBeVisible();
  const text = await page.locator('#notifyText').innerText();
  expect(text).toContain('API-kulcs');
});

test('BYOK saved: Authorization header is attached to requests', async ({ page }) => {
  await page.goto('/');

  // Force BYOK requirement via /config
  await page.route('**/config', async route => {
    await route.fulfill({ status: 200, headers: { 'content-type': 'application/json' }, body: JSON.stringify({ require_byok: true }) });
  });

  /** @type {any|null} */
  let capturedStructure = null;
  await page.route('**/api/structure', async route => {
    capturedStructure = {
      headers: route.request().headers(),
      body: route.request().postDataJSON(),
    };
    await route.fulfill({ status: 200, headers: { 'content-type': 'application/json' }, body: JSON.stringify({ statistics: { model_name: 'm', input_time: 0, output_time: 0, input_tokens: 0, output_tokens: 0, total_time: 0 }, structure: { 'Fejezet 1': 'Leírás' } }) });
  });

  await page.route('**/api/sections/stream', async route => {
    const title = 'Fejezet 1';
    const body = ndjson([{ type: 'section_start', title }, { type: 'done' }]);
    await route.fulfill({ status: 200, headers: { 'content-type': 'application/x-ndjson' }, body });
  });

  // Open BYOK modal and save a key
  await page.click('#byokOpen');
  await page.fill('#byokInput', 'gsk_test_123');
  await page.click('#byokSave');

  // Generate
  await page.fill('#subject', 'Teszt téma');
  await page.click('#generateBtn');

  await expect.poll(() => !!capturedStructure, { timeout: 5000 }).toBeTruthy();
  expect(capturedStructure.headers['authorization'] || capturedStructure.headers['Authorization']).toContain('gsk_test_123');
});
}

function ndjson(lines) {
  return lines.map(l => JSON.stringify(l)).join('\n') + '\n';
}

// Route helpers
async function mockStructure(page, structure) {
  await page.route('**/api/structure', async route => {
    await route.fulfill({
      status: 200,
      headers: { 'content-type': 'application/json; charset=utf-8' },
      body: JSON.stringify({
        statistics: {
          model_name: 'openai/gpt-oss-20b',
          input_time: 0.1,
          output_time: 0.2,
          input_tokens: 10,
          output_tokens: 20,
          total_time: 0.3,
        },
        structure,
      })
    });
  });
}

async function mockSectionsDone(page, title = 'Fejezet 1') {
  await page.route('**/api/sections/stream', async route => {
    const body = ndjson([
      { type: 'section_start', title },
      { type: 'token', title, delta: 'Hello ' },
      { type: 'token', title, delta: 'World' },
      { type: 'stats', title, statistics: { model_name: 'openai/gpt-oss-20b', input_time: 0.1, output_time: 0.2, input_tokens: 10, output_tokens: 20, total_time: 0.3 } },
      { type: 'section_end', title },
      { type: 'done' },
    ]);
    await route.fulfill({
      status: 200,
      headers: { 'content-type': 'application/x-ndjson; charset=utf-8' },
      body,
    });
  });
}

async function mockSectionsAborted(page, title = 'Fejezet 1') {
  await page.route('**/api/sections/stream', async route => {
    const body = ndjson([
      { type: 'section_start', title },
      { type: 'aborted' },
    ]);
    await route.fulfill({
      status: 200,
      headers: { 'content-type': 'application/x-ndjson; charset=utf-8' },
      body,
    });
  });
}

async function mockExportMarkdown(page) {
  await page.route('**/api/export/markdown', async route => {
    await route.fulfill({
      status: 200,
      headers: {
        'content-type': 'text/plain; charset=utf-8',
        'content-disposition': 'attachment; filename="groqbook.txt"'
      },
      body: 'Hello World',
    });
  });
}

async function mockStructure429(page) {
  await page.route('**/api/structure', async route => {
    await route.fulfill({
      status: 429,
      headers: { 'content-type': 'application/json; charset=utf-8' },
      body: JSON.stringify({ detail: 'Structure generation failed: Error code: 429 - rate limit' })
    });
  });
}

// Tests

test('happy path: structure -> stream -> done, download resets UI', async ({ page }) => {
  await page.goto('/');
  await mockStructure(page, { 'Fejezet 1': 'Leírás' });
  await mockSectionsDone(page, 'Fejezet 1');
  await mockExportMarkdown(page);

  await page.fill('#subject', 'Teszt téma');
  await page.click('#generateBtn');

  const item = page.locator('#structure > div');
  await expect(item).toHaveCount(1);

  // Wait for completion toast and enabled download
  const dlBtn = page.locator('#downloadTxt');
  await expect(dlBtn).toBeEnabled();

  // Download triggers reset
  await dlBtn.click();
  await expect(page.locator('#structure').locator('> div')).toHaveCount(0);
});

test('stop/aborted path resets UI and shows toast', async ({ page }) => {
  await page.goto('/');
  await mockStructure(page, { 'Fejezet 1': 'Leírás' });
  await mockSectionsAborted(page, 'Fejezet 1');

  await page.fill('#subject', 'Teszt téma');
  await page.click('#generateBtn');

  // Toast appears and UI reset occurs
  await expect(page.locator('#notify')).toBeVisible();
  const text = await page.locator('#notifyText').innerText();
  expect(text.toLowerCase()).toContain('megszakítva');
  await expect(page.locator('#structure').locator('> div')).toHaveCount(0);
});

test('rate-limit (429) shows specific toast', async ({ page }) => {
  await page.goto('/');
  await mockStructure429(page);

  await page.fill('#subject', 'Teszt téma');
  await page.click('#generateBtn');

  await expect(page.locator('#notify')).toBeVisible();
  const text = await page.locator('#notifyText').innerText();
  expect(text).toContain('Elérted a napi keretet');
});

test('advanced parameters are sent to backend', async ({ page }) => {
  await page.goto('/');

  // Capture body of sections request
  /** @type {any[]} */
  const bodies = [];
  await page.route('**/api/sections/stream', async route => {
    const postData = route.request().postDataJSON();
    bodies.push(postData);
    // Return a minimal successful stream
    const title = 'Fejezet 1';
    const body = ndjson([
      { type: 'section_start', title },
      { type: 'section_end', title },
      { type: 'done' },
    ]);
    await route.fulfill({ status: 200, headers: { 'content-type': 'application/x-ndjson' }, body });
  });

  await mockStructure(page, { 'Fejezet 1': 'Leírás' });

  // Switch to advanced mode
  await page.click('#modeToggle');

  // Choose 120B model
  await page.click('[data-model="openai/gpt-oss-120b"]');

  // Adjust sliders
  await setRange(page, '#temperature', 0.5);
  await setRange(page, '#topP', 0.9);
  await setRange(page, '#targetLength', 900);

  // Style + level
  await page.click('[data-style="közérthető"]');
  await page.click('[data-level="egyetemi"]');

  await page.fill('#subject', 'Teszt téma');
  await page.click('#generateBtn');

  await expect.poll(() => bodies.length, { timeout: 5000 }).toBeGreaterThan(0);
  const params = bodies[0].params;
  expect(params.model).toBe('openai/gpt-oss-120b');
  expect(Number(params.temperature)).toBeCloseTo(0.5, 1);
  expect(Number(params.top_p)).toBeCloseTo(0.9, 1);
  expect(Number(params.target_length)).toBe(900);
  expect(params.style).toBe('közérthető');
  expect(params.reading_level).toBe('egyetemi');
});
