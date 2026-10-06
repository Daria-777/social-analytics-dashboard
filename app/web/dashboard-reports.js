import { $ } from './dashboard-core.js';

export function setupReports() {
  const menu = $('report-menu'), period = $('report-period'), error = $('report-error');
  const recipient = $('report-recipient'), telegram = $('report-telegram');
  let summary = null, requestId = 0;
  const params = () => new URLSearchParams({days: period.value, timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'});
  function link() {
    const username = recipient.value.trim().replace(/^@/, '');
    const valid = /^[A-Za-z][A-Za-z0-9_]{4,31}$/.test(username);
    recipient.setCustomValidity(recipient.value && !valid ? 'Укажите имя пользователя Telegram: @username' : '');
    telegram.removeAttribute('href');
    telegram.setAttribute('aria-disabled', 'true');
    if (!valid || !summary) return;
    const url = new URL(`https://t.me/${username}`);
    url.searchParams.set('text', summary.text);
    telegram.href = url.href;
    telegram.removeAttribute('aria-disabled');
  }
  async function load() {
    const id = ++requestId;
    summary = null; link(); error.textContent = '';
    $('report-preview').textContent = 'Готовим сводку…';
    try {
      const response = await fetch('/reports/summary?' + params(), {credentials: 'same-origin'});
      if (!response.ok) throw new Error(response.status === 401 ? 'Войдите снова, чтобы подготовить отчёт' : 'Не удалось подготовить сводку. Откройте меню снова');
      const result = await response.json();
      if (id !== requestId || !menu.open) return;
      summary = result;
      $('report-preview').textContent = `Измерения: ${result.period}`;
      link();
    } catch (e) {
      if (id !== requestId) return;
      $('report-preview').textContent = '';
      error.textContent = e.message || 'Не удалось подготовить отчёт';
    }
  }
  menu.addEventListener('toggle', () => { if (menu.open) load(); else { ++requestId; summary = null; link(); } });
  period.addEventListener('change', load);
  recipient.addEventListener('input', link);
  telegram.addEventListener('click', e => {
    if (!telegram.hasAttribute('href')) { e.preventDefault(); recipient.reportValidity(); if (!recipient.value) recipient.focus(); }
  });
  $('report-copy').addEventListener('click', async () => {
    if (!summary) { await load(); if (!summary) return; }
    try { await navigator.clipboard.writeText(summary.text); error.textContent = 'Сводка скопирована'; }
    catch { error.textContent = 'Не удалось скопировать. Откройте отчёт в Telegram или скачайте PDF'; }
  });
  document.querySelectorAll('[data-report-format]').forEach(button => button.addEventListener('click', async () => {
    error.textContent = ''; button.disabled = true;
    const original = button.textContent;
    button.textContent = 'Готовим файл…';
    try {
      const format = button.dataset.reportFormat;
      const response = await fetch(`/reports/export.${format}?${params()}`, {credentials: 'same-origin'});
      if (!response.ok) {
        const body = await response.json().catch(() => null);
        throw new Error(typeof body?.detail === 'string' ? body.detail : response.status === 401 ? 'Войдите снова, чтобы скачать отчёт' : 'Не удалось скачать отчёт');
      }
      const blob = await response.blob(), url = URL.createObjectURL(blob);
      const anchor = document.createElement('a'); anchor.href = url;
      const filename = response.headers.get('Content-Disposition')?.match(/filename="([^"]+)"/)?.[1];
      anchor.download = filename || `dash-report.${format}`; anchor.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      error.textContent = `${format === 'pdf' ? 'PDF' : 'Excel'} готов к скачиванию`;
    } catch (e) { error.textContent = e.message; }
    finally { button.disabled = false; button.textContent = original; }
  }));
  document.addEventListener('pointerdown', e => { if (menu.open && !menu.contains(e.target)) menu.open = false; });
  document.addEventListener('keydown', e => { if (e.key === 'Escape' && menu.open) { menu.open = false; menu.querySelector('summary').focus(); } });
  $('logout').addEventListener('click', () => { menu.open = false; summary = null; recipient.value = ''; link(); });
}
