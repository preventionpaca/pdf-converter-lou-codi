const connection = document.querySelector("#connection");
const spacesNode = document.querySelector("#spaces");
const message = document.querySelector("#message");
const titleInput = document.querySelector("#space-title");
const accountInput = document.querySelector("#space-account");
const captureEditor = document.querySelector("#capture-editor");
const captureTitle = document.querySelector("#capture-title");
const captureExcerpt = document.querySelector("#capture-excerpt");
const captureSource = document.querySelector("#capture-source");
const BRIDGE = "http://127.0.0.1:47632";

async function liveSpaces() {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 2500);
  try {
    const response = await fetch(`${BRIDGE}/spaces`, {signal: controller.signal});
    if (!response.ok) throw new Error(`Erreur locale ${response.status}`);
    const payload = await response.json();
    await chrome.storage.local.set({
      spaces: payload.spaces || [],
      accounts: payload.accounts || [],
      bridgeOnline: true,
      lastError: "",
    });
    return payload.spaces || [];
  } finally {
    clearTimeout(timeout);
  }
}

async function currentPage() {
  const [tab] = await chrome.tabs.query({active: true, currentWindow: true});
  if (!tab?.url?.startsWith("http")) throw new Error("Cette page ne possède pas d’adresse Web enregistrable.");
  return {url: tab.url, title: tab.title || ""};
}

async function render() {
  let liveError = "";
  try {
    await liveSpaces();
    chrome.runtime.sendMessage({action: "refresh"}).catch(() => {});
  } catch (error) {
    liveError = error.name === "AbortError"
      ? "Le Workshop ne répond pas. Fermez ses anciennes fenêtres puis relancez la version de développement."
      : String(error.message || error);
    await chrome.storage.local.set({bridgeOnline: false, lastError: liveError});
  }
  const state = await chrome.storage.local.get({spaces: [], accounts: [], bridgeOnline: false, lastError: "", lastResult: "", pendingCapture: null, menuReady: false, menuError: ""});
  const knowledgeCapture = state.pendingCapture?.kind === "ai_knowledge";
  captureEditor.hidden = !knowledgeCapture;
  if (knowledgeCapture) {
    captureTitle.value = state.pendingCapture.title || "Fiche de connaissance IA";
    captureExcerpt.value = state.pendingCapture.excerpt || "";
    captureSource.textContent = `Source : ${state.pendingCapture.pageTitle || state.pendingCapture.url}`;
  }
  connection.textContent = state.bridgeOnline ? "Workshop connecté" : "Ouvrez Lou Còdi Workshop pour utiliser la capture.";
  connection.classList.toggle("offline", !state.bridgeOnline);
  message.textContent = liveError || state.menuError || state.lastResult || state.lastError || "";
  spacesNode.replaceChildren();
  accountInput.replaceChildren();
  for (const account of state.accounts) {
    const option = document.createElement("option");
    option.value = account;
    option.textContent = account;
    accountInput.append(option);
  }
  if (!state.accounts.length) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "Aucun compte Google disponible";
    accountInput.append(option);
  }
  for (const space of state.spaces) {
    const row = document.createElement("div");
    row.className = "space";
    const label = document.createElement("span");
    label.className = "space-label";
    const title = document.createElement("span");
    title.textContent = space.title;
    const account = document.createElement("span");
    account.className = "space-account";
    account.textContent = space.account || "Local — aucun compte rattaché";
    label.append(title, account);
    const actions = document.createElement("div");
    actions.className = "space-actions";
    const addButton = document.createElement("button");
    addButton.textContent = "Ajouter";
    addButton.addEventListener("click", async () => {
      let capture = state.pendingCapture;
      try {
        capture = capture || await currentPage();
      } catch (error) {
        message.textContent = String(error.message || error);
        return;
      }
      const request = {action: "capture", payload: {...capture, spaceId: space.id}};
      if (capture.kind === "ai_knowledge") {
        request.payload.title = captureTitle.value.trim() || "Fiche de connaissance IA";
        request.payload.excerpt = captureExcerpt.value.trim();
      }
      const result = await chrome.runtime.sendMessage(request);
      message.textContent = result?.error || (result?.added === false
        ? `Déjà présent dans « ${space.title} ».`
        : `Ajouté à « ${space.title} ».`);
      if (!result?.error) await chrome.storage.local.remove("pendingCapture");
    });
    const openButton = document.createElement("button");
    openButton.className = "secondary";
    openButton.textContent = "Ouvrir";
    openButton.addEventListener("click", async () => {
      const result = await chrome.runtime.sendMessage({action: "open", spaceId: space.id});
      message.textContent = result?.error || "Ouverture demandée.";
    });
    actions.append(addButton, openButton);
    row.append(label, actions);
    spacesNode.append(row);
  }
}

document.querySelector("#create").addEventListener("click", async () => {
  const title = titleInput.value.trim();
  if (!title) { message.textContent = "Indiquez un nom d’espace."; return; }
  const result = await chrome.runtime.sendMessage({action: "create", title, account: accountInput.value});
  if (result?.error) { message.textContent = result.error; return; }
  titleInput.value = "";
  message.textContent = `Espace « ${result.title} » créé.`;
  await render();
  const state = await chrome.storage.local.get({pendingCapture: null});
  if (state.pendingCapture) {
    await chrome.runtime.sendMessage({action: "capture", payload: {...state.pendingCapture, spaceId: result.id}});
    await chrome.storage.local.remove("pendingCapture");
  }
  await chrome.runtime.sendMessage({action: "open", spaceId: result.id});
});

if (new URLSearchParams(location.search).has("create")) titleInput.focus();
render();
