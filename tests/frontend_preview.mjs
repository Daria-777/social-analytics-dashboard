// Isolated browser: all requests fulfilled locally; no provider API or credentials.
// PLAYWRIGHT_MODULE may point at the host's bundled playwright/index.mjs.
import fs from "node:fs";
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || "playwright");
const policy = fs.readFileSync(new URL("../app/main.py", import.meta.url), "utf8").match(/Content-Security-Policy'\]="([^"]+)"/)[1];
const root = new URL("../app/web/", import.meta.url);
const browser = await chromium.launch({ headless: true, ...(process.env.PLAYWRIGHT_CHANNEL ? { channel: process.env.PLAYWRIGHT_CHANNEL } : {}) });
try {
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  const content = { id: "fixture", platform: "instagram", content_type: "photo", caption: "Тестовая публикация", preview_url: "https://s.cdninstagram.com/photo.svg", permalink: "https://www.instagram.com/p/fixture/" };
  const snapshot = { source: "instagram_api", metric_scope: "lifetime", snapshot_status: "confirmed", views: 0 };
  await page.route("**/*", async (route) => {
    const url = new URL(route.request().url());
    if (url.hostname === "s.cdninstagram.com") {
      assert.equal(route.request().headers().referer, undefined);
      return route.fulfill({ headers: { "Cache-Control": "no-store" }, contentType: "image/svg+xml", body: '<svg xmlns="http://www.w3.org/2000/svg" width="600" height="800"><rect width="600" height="800" fill="#067462"/><circle cx="300" cy="300" r="150" fill="#e8f1eb"/></svg>' });
    }
    assert.equal(url.hostname, "127.0.0.1", "Unexpected external request");
    if (url.pathname === "/dashboard" || url.pathname.startsWith("/dashboard/assets/")) {
      const name = url.pathname === "/dashboard" ? "dashboard.html" : url.pathname.split("/").at(-1);
      return route.fulfill({ headers: { "Content-Security-Policy": policy }, contentType: name.endsWith(".html") ? "text/html" : name.endsWith(".css") ? "text/css" : name.endsWith(".svg") ? "image/svg+xml" : "text/javascript", body: fs.readFileSync(new URL(name, root)) });
    }
    if (url.pathname === '/content/fixture/preview') return route.fulfill({headers:{'Cache-Control':'no-store'},contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="600" height="800"><rect width="600" height="800" fill="#067462"/></svg>'});
    const payload = {
      "/dashboard/config": { display_timezone: "Europe/Moscow" },
      "/accounts": [], "/content": [content], "/experiments": [],
      "/collectors/status": { instagram: {}, tiktok: {} }, "/collectors/runs": [],
      "/analytics/content-comparison": { rows: [{ content, snapshot, derived: {} }], groups: [] },
    }[url.pathname];
    assert.notEqual(payload, undefined, "Unexpected API request " + url.pathname);
    await route.fulfill({ json: payload });
  });
  await page.goto("http://127.0.0.1:8769/dashboard");
  await page.locator('[data-view="content"]').first().click();
  const thumbnail = page.getByRole("button", { name: "Увеличить фото: Тестовая публикация" }).last();
  await thumbnail.click();
  const dialog = page.getByRole("dialog");
  await dialog.waitFor({ state: "visible" });
  assert.equal(await page.locator("#photo-close").evaluate((el) => el === document.activeElement), true);
  await page.keyboard.press("Escape");
  await dialog.waitFor({ state: "hidden" });
  assert.equal(await thumbnail.evaluate((el) => el === document.activeElement), true);
  await thumbnail.focus();
  await page.keyboard.press("Enter");
  await dialog.waitFor({ state: "visible" });
  await page.mouse.click(5, 5);
  await dialog.waitFor({ state: "hidden" });
  await thumbnail.click();
  await page.getByRole("button", { name: "Закрыть фото" }).click();
  await dialog.waitFor({ state: "hidden" });
  await page.waitForFunction(() => !document.querySelector("#photo-dialog img").hasAttribute("src"));
  await page.setViewportSize({ width: 320, height: 640 });
  await thumbnail.click();
  const bounds = await dialog.boundingBox();
  assert.ok(bounds.x >= 0 && bounds.x + bounds.width <= 320);
  if (process.env.PREVIEW_SCREENSHOT) await page.screenshot({ path: process.env.PREVIEW_SCREENSHOT });
  await page.keyboard.press("Escape");
  // Signed link expiration must degrade to readable fallback, not a broken image.
  await page.route("https://s.cdninstagram.com/**", (route) => route.fulfill({ status: 404, body: "" }));
  content.preview_url = "https://s.cdninstagram.com/expired.svg";
  await page.reload();
  await page.locator('[data-view="content"]').first().click();
  await page.locator("#content-cards").getByText("Фото недоступно", { exact: true }).waitFor({ state: "visible" });
  content.platform = 'tiktok'; content.preview_url = null;
  await page.reload();
  await page.locator('[data-view="content"]').first().click();
  const tt = page.locator('#content-cards .content-preview img').first();
  await tt.waitFor({state:'visible'});
  assert.equal(await tt.getAttribute('src'),'/content/fixture/preview');
  await page.waitForFunction(()=>document.querySelector('#content-cards .content-preview img')?.naturalWidth>0);
  await tt.click();
  await dialog.waitFor({state:'visible'});
  assert.equal(await page.locator('#photo-dialog img').getAttribute('src'),'/content/fixture/preview');
  await page.keyboard.press('Escape');
  assert.deepEqual(errors, []);
  console.log("Photo preview: click, keyboard, focus return, Escape, backdrop, close, mobile and expired image passed");
} finally { await browser.close(); }
