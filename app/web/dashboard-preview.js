import { node, title } from "./dashboard-core.js";

export function previewURL(value) {
  try {
    const url = new URL(value);
    const domains = ["cdninstagram.com", "fbcdn.net", "tiktokcdn.com", "tiktokcdn-us.com", "tiktokcdn-eu.com", "ibytedtos.com"];
    const refresh = [...url.searchParams].filter(([k]) => k.toLowerCase() === "refresh_token");
    const tiktok = domains.slice(2,5).some(d => url.hostname === d || url.hostname.endsWith("." + d));
    const cdnMarker = tiktok && refresh.length === 1 && refresh[0][0] === "refresh_token" &&
      /^[0-9a-f]{8}$/.test(refresh[0][1]) && /^\d+$/.test(url.searchParams.get("x-expires") || "") &&
      Boolean(url.searchParams.get("x-signature"));
    if (url.protocol === "https:" && !url.username && !url.password &&
        (!url.port || url.port === "443") &&
        domains.some((d) => url.hostname === d || url.hostname.endsWith("." + d)) &&
        ![...url.searchParams.keys()].some((k) => ["access_token", "client_secret", "authorization", "code"].includes(k.toLowerCase())) && (!refresh.length || cdnMarker)) return url.href;
  } catch {}
  return null;
}

export function preview(c) {
  const url = c.platform === "tiktok" && c.id ? `/content/${encodeURIComponent(c.id)}/preview` : previewURL(c.preview_url);
  if (!url) return node("span", "Нет фото", "preview-placeholder");
  const b = node("button", null, "content-preview");
  b.type = "button";
  b.setAttribute("aria-label", "Увеличить фото: " + title(c));
  const image = node("img");
  image.alt = "";
  image.loading = "lazy";
  image.decoding = "async";
  image.referrerPolicy = "no-referrer";
  let failed = false, attempts = 0;
  image.addEventListener("error", () => {
    failed = true;
    b.classList.add("preview-placeholder");
    b.setAttribute("aria-label", "Загрузить фото: " + title(c));
    b.replaceChildren(node("span", attempts ? "Не загрузилось. Повторить" : "Загрузить фото"));
  });
  image.addEventListener("load", () => {
    failed = false;
    b.classList.remove("preview-placeholder");
    b.setAttribute("aria-label", "Увеличить фото: " + title(c));
    if (b.firstChild !== image) b.replaceChildren(image);
  });
  image.src = url;
  b.append(image);
  b.addEventListener("click", () => {
    if (!failed) { openPreview(c, url); return; }
    attempts++;
    failed = false;
    b.classList.remove("preview-placeholder");
    b.replaceChildren(image);
    // User initiated retry only. The server's provider cooldown remains in force.
    image.src = url + (url.startsWith("/") ? "?retry=" + attempts : "");
  });
  return b;
}

function openPreview(c, url) {
  const dialog = document.getElementById("photo-dialog");
  const image = dialog.querySelector("img");
  const error = document.getElementById("photo-error");
  document.getElementById("photo-title").textContent = title(c);
  error.hidden = true;
  image.hidden = false;
  image.alt = "Фото или обложка публикации: " + title(c);
  image.onerror = () => { image.hidden = true; error.hidden = false; };
  image.src = url;
  let retry = 0;
  error.querySelector("button").onclick = () => {
    error.hidden = true; image.hidden = false;
    image.src = url + (url.startsWith("/") ? "?retry=" + ++retry : "");
  };
  const link = document.getElementById("photo-permalink");
  link.hidden = true;
  link.removeAttribute("href");
  try {
    const original = new URL(c.permalink);
    if (["https:", "http:"].includes(original.protocol)) {
      link.href = original.href;
      link.hidden = false;
    }
  } catch {}
  dialog.showModal();
}

export function setupPreview() {
  const dialog = document.getElementById("photo-dialog");
  document.getElementById("photo-close").addEventListener("click", () => dialog.close());
  dialog.addEventListener("click", (e) => { if (e.target === dialog) dialog.close(); });
  dialog.addEventListener("close", () => {
    if (dialog.open) return;
    dialog.querySelector("img").removeAttribute("src");
    dialog.querySelector("img").onerror = null;
    document.getElementById("photo-title").textContent = "";
    document.getElementById("photo-permalink").removeAttribute("href");
  });
}
