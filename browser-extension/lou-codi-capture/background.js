const BRIDGE = "http://127.0.0.1:47632";
const ROOT = "loucodi-root";
const OPEN = "loucodi-open";
const LAST = "loucodi-last";
const KNOWLEDGE = "loucodi-knowledge";

async function bridge(path, options = {}) {
  const response = await fetch(`${BRIDGE}${path}`, {
    headers: {"Content-Type": "application/json"},
    ...options,
  });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || "Lou Còdi n’est pas disponible.");
  return payload;
}

async function loadSpaces() {
  try {
    const payload = await bridge("/spaces");
    await chrome.storage.local.set({spaces: payload.spaces, accounts: payload.accounts || [], bridgeOnline: true, lastError: ""});
    return payload.spaces;
  } catch (error) {
    const stored = await chrome.storage.local.get({spaces: []});
    await chrome.storage.local.set({bridgeOnline: false, lastError: String(error.message || error)});
    return stored.spaces;
  }
}

let menuBuild = Promise.resolve();
const contextByTab = new Map();

async function doRebuildMenus() {
  const spaces = await loadSpaces();
  const stored = await chrome.storage.local.get({lastSpaceId: ""});
  const lastSpace = spaces.find(space => space.id === stored.lastSpaceId);
  await new Promise(resolve => chrome.contextMenus.removeAll(resolve));
  if (lastSpace) {
    await new Promise((resolve, reject) => {
      chrome.contextMenus.create({
        id: LAST,
        title: `Ajouter directement à « ${lastSpace.title} »`,
        contexts: ["page", "link", "image", "selection"],
      }, () => chrome.runtime.lastError ? reject(new Error(chrome.runtime.lastError.message)) : resolve());
    });
  }
  await new Promise((resolve, reject) => {
    chrome.contextMenus.create({
      id: KNOWLEDGE,
      title: "Transformer la sélection en fiche de connaissance…",
      contexts: ["selection"],
    }, () => chrome.runtime.lastError ? reject(new Error(chrome.runtime.lastError.message)) : resolve());
  });
  await new Promise((resolve, reject) => {
    chrome.contextMenus.create({
      id: ROOT,
      title: "Ajouter cette page à Lou Còdi Espace…",
      contexts: ["page", "link", "image", "selection"],
    }, () => chrome.runtime.lastError ? reject(new Error(chrome.runtime.lastError.message)) : resolve());
  });
  await new Promise((resolve, reject) => {
    chrome.contextMenus.create({
      id: OPEN,
      title: "Ouvrir Lou Còdi Espace",
      contexts: ["page"],
    }, () => chrome.runtime.lastError ? reject(new Error(chrome.runtime.lastError.message)) : resolve());
  });
  await chrome.storage.local.set({menuReady: true, menuError: ""});
}

function rebuildMenus() {
  const build = () => doRebuildMenus().catch(async error => {
    await chrome.storage.local.set({menuReady: false, menuError: String(error.message || error)});
    throw error;
  });
  menuBuild = menuBuild.then(build, build);
  return menuBuild;
}

function capturedUrl(info, tab) {
  return info.linkUrl || info.srcUrl || contextByTab.get(tab?.id)?.url || info.pageUrl || tab?.url || "";
}

function capturedTitle(info, tab) {
  return (tab?.title || contextByTab.get(tab?.id)?.title || "").trim();
}

function suggestedKnowledgeTitle(excerpt, fallback) {
  const firstMeaningfulLine = excerpt.split(/\n+/).map(value => value.trim()).find(Boolean) || "";
  const firstSentence = firstMeaningfulLine.split(/(?<=[.!?])\s+/)[0];
  const candidate = (firstSentence || fallback || "Fiche de connaissance IA").replace(/\s+/g, " ").trim();
  return candidate.length > 110 ? `${candidate.slice(0, 107).trim()}…` : candidate;
}

function capturedPayload(info, tab) {
  const excerpt = (info.selectionText || "").trim();
  return {
    url: capturedUrl(info, tab),
    title: excerpt ? suggestedKnowledgeTitle(excerpt, capturedTitle(info, tab)) : capturedTitle(info, tab),
    pageTitle: capturedTitle(info, tab),
    excerpt,
    kind: excerpt ? "ai_knowledge" : "",
  };
}

async function showResult(text, failed = false) {
  await chrome.storage.local.set({lastResult: text, lastResultFailed: failed});
  await chrome.action.setBadgeBackgroundColor({color: failed ? "#B3261E" : "#2368AF"});
  await chrome.action.setBadgeText({text: failed ? "!" : "✓"});
  setTimeout(() => chrome.action.setBadgeText({text: ""}), 3500);
}

chrome.runtime.onInstalled.addListener(() => { rebuildMenus().catch(() => {}); });
chrome.runtime.onStartup.addListener(() => { rebuildMenus().catch(() => {}); });

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  try {
    if (info.menuItemId === OPEN) {
      await bridge("/open", {method: "POST", body: JSON.stringify({})});
      return;
    }
    if (info.menuItemId === ROOT || info.menuItemId === KNOWLEDGE) {
      await chrome.storage.local.set({pendingCapture: capturedPayload(info, tab)});
      await chrome.windows.create({url: chrome.runtime.getURL("popup.html?choose=1"), type: "popup", width: 430, height: 570});
      return;
    }
    if (info.menuItemId === LAST) {
      const stored = await chrome.storage.local.get({lastSpaceId: ""});
      const result = await bridge("/capture", {
        method: "POST",
        body: JSON.stringify({
          spaceId: stored.lastSpaceId,
          ...capturedPayload(info, tab),
        }),
      });
      await showResult(result.added ? `Ajouté à ${result.space}` : `Déjà présent dans ${result.space}`);
      return;
    }
  } catch (error) {
    await showResult(String(error.message || error), true);
  }
});

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message.action === "contextMetadata") {
    if (_sender.tab?.id !== undefined) {
      contextByTab.set(_sender.tab.id, {title: message.title || "", url: message.url || ""});
    }
    sendResponse({ok: true});
    return false;
  }
  if (message.action === "refresh") {
    rebuildMenus()
      .then(() => sendResponse({ok: true}))
      .catch(error => sendResponse({ok: false, error: String(error.message || error)}));
    return true;
  }
  if (message.action === "open") {
    bridge("/open", {method: "POST", body: JSON.stringify({spaceId: message.spaceId || ""})})
      .then(sendResponse).catch(error => sendResponse({error: String(error.message || error)}));
    return true;
  }
  if (message.action === "create") {
    bridge("/spaces", {method: "POST", body: JSON.stringify({title: message.title, account: message.account || ""})})
      .then(async result => { await rebuildMenus(); sendResponse(result); })
      .catch(error => sendResponse({error: String(error.message || error)}));
    return true;
  }
  if (message.action === "capture") {
    bridge("/capture", {method: "POST", body: JSON.stringify(message.payload)})
      .then(async result => {
        await chrome.storage.local.set({lastSpaceId: message.payload.spaceId});
        await rebuildMenus();
        await showResult(result.added ? `Ajouté à ${result.space}` : `Déjà présent dans ${result.space}`);
        sendResponse(result);
      })
      .catch(error => sendResponse({error: String(error.message || error)}));
    return true;
  }
});

rebuildMenus().catch(() => {});
