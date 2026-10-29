function clean(value) {
  return String(value || "").replace(/\s+/g, " ").trim().slice(0, 220);
}

function filenameFromUrl(value) {
  try {
    const part = decodeURIComponent(new URL(value).pathname.split("/").filter(Boolean).pop() || "");
    return clean(part.replace(/\.(avif|gif|jpe?g|png|svg|webp)(\?.*)?$/i, ""));
  } catch (_error) {
    return "";
  }
}

document.addEventListener("contextmenu", event => {
  const element = event.target instanceof Element ? event.target : null;
  if (!element) return;
  const image = element.closest("img");
  const link = element.closest("a");
  const media = element.closest("video, audio");
  const url = image?.currentSrc || image?.src || media?.currentSrc || media?.src || link?.href || location.href;
  const nearby = image?.closest("figure, [role='img'], [aria-label]") || link;
  const title = clean(
    image?.alt ||
    image?.title ||
    media?.title ||
    element.getAttribute("aria-label") ||
    nearby?.getAttribute("aria-label") ||
    link?.title ||
    link?.textContent ||
    filenameFromUrl(url) ||
    document.querySelector("meta[property='og:title']")?.content ||
    document.title
  );
  chrome.runtime.sendMessage({action: "contextMetadata", title, url}).catch(() => {});
}, true);
