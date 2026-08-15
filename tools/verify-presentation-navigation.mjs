#!/usr/bin/env node

import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const runtimeModules = process.env.RUNTIME_NODE_MODULES;
assert(runtimeModules, 'RUNTIME_NODE_MODULES is required');

const require = createRequire(path.join(runtimeModules, 'package.json'));
const { chromium } = require('playwright');
const edge = process.argv[2] || 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const deck = path.resolve('docs/presentation/index.html');
const url = `${pathToFileURL(deck).href}?slide=1`;

const browser = await chromium.launch({
  executablePath: edge,
  headless: true,
  args: ['--disable-gpu', '--disable-software-rasterizer', '--no-sandbox'],
});

try {
  const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });
  await page.goto(url);
  const input = page.locator('[data-page-input]');
  const deckBox = await page.locator('.deck').boundingBox();
  const navBox = await page.locator('.chrome').boundingBox();
  assert(deckBox && navBox, 'deck and navigation must be visible');
  assert(deckBox.y + deckBox.height <= navBox.y, 'navigation must not overlap the slide');

  await input.fill('7');
  await page.locator('.chrome button.go').click();
  assert.equal(await input.inputValue(), '7');
  assert.match(page.url(), /[?&]slide=7(?:&|$)/);

  await page.locator('[data-action="next"]').click();
  assert.equal(await input.inputValue(), '8');

  await page.keyboard.press('Home');
  assert.equal(await input.inputValue(), '1');

  await input.fill('99');
  await page.locator('.chrome button.go').click();
  assert.equal(await input.inputValue(), '10');

  console.log('presentation_direct_page_input=PASS');
  console.log('presentation_next_button=PASS');
  console.log('presentation_keyboard_navigation=PASS');
  console.log('presentation_page_clamp=PASS');
  console.log('presentation_navigation_safe_area=PASS');
} finally {
  await browser.close();
}
