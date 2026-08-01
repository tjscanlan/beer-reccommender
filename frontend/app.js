const state = {
  beers: [],
  selected: new Set(),
};

const $ = (id) => document.getElementById(id);

async function init() {
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/sw.js").catch(() => {});
  }
  try {
    const resp = await fetch("/api/beers");
    state.beers = await resp.json();
  } catch (err) {
    $("beer-grid").innerHTML = "<p class='hint'>Couldn't load beers — is the server running?</p>";
    return;
  }
  renderGrid();

  $("beer-search").addEventListener("input", renderGrid);
  $("recommend-btn").addEventListener("click", getRecommendations);
  $("reset-btn").addEventListener("click", reset);
  $("scan-btn").addEventListener("click", () => $("menu-photo").click());
  $("menu-photo").addEventListener("change", (e) => {
    const file = e.target.files && e.target.files[0];
    if (file) scanMenu(file);
  });
  $("rescan-btn").addEventListener("click", () => {
    $("menu-results").hidden = true;
    $("menu-photo").click();
  });
}

function renderGrid() {
  const query = $("beer-search").value.trim().toLowerCase();
  const grid = $("beer-grid");
  grid.innerHTML = "";
  const matches = state.beers.filter((b) =>
    !query || `${b.name} ${b.brewery} ${b.style}`.toLowerCase().includes(query)
  );
  for (const beer of matches) {
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "beer-chip" + (state.selected.has(beer.id) ? " selected" : "");
    chip.innerHTML = `${escapeHtml(beer.name)}<span class="style">${escapeHtml(beer.style)}</span>`;
    chip.addEventListener("click", () => toggle(beer.id));
    grid.appendChild(chip);
  }
  updateCount();
}

function toggle(id) {
  if (state.selected.has(id)) state.selected.delete(id);
  else state.selected.add(id);
  renderGrid();
}

function updateCount() {
  const n = state.selected.size;
  $("picked-count").textContent = n
    ? `${n} beer${n === 1 ? "" : "s"} picked 🍻`
    : "Nothing picked yet — tap a few favorites.";
}

async function getRecommendations() {
  const btn = $("recommend-btn");
  const results = $("results");
  const list = $("results-list");
  btn.disabled = true;
  results.hidden = false;
  list.innerHTML = "<div class='spinner'></div>";
  results.scrollIntoView({ behavior: "smooth" });

  try {
    const resp = await fetch("/api/recommend", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        liked_beer_ids: [...state.selected],
        taste_text: $("taste-text").value.trim(),
        limit: 5,
      }),
    });
    const data = await resp.json();
    renderResults(data);
  } catch (err) {
    list.innerHTML = "<p class='hint'>Something went wrong — try again.</p>";
  } finally {
    btn.disabled = false;
  }
}

function renderResults(data) {
  const list = $("results-list");
  $("personalized-note").hidden = !data.personalized;
  list.innerHTML = "";
  for (const rec of data.recommendations) {
    const card = document.createElement("div");
    card.className = "rec-card";
    const pct = Math.round(Math.max(0, Math.min(1, rec.score)) * 100);
    card.innerHTML = `
      <div class="rec-head">
        <div>
          <h3>${escapeHtml(rec.name)}</h3>
          <div class="brewery">${escapeHtml(rec.brewery)}</div>
        </div>
        ${rec.score ? `<span class="match">${pct}% match</span>` : ""}
      </div>
      <div class="meta">
        <span class="badge">${escapeHtml(rec.style)}</span>
        <span class="badge">${rec.abv}% ABV</span>
        <span class="badge">${rec.ibu} IBU</span>
      </div>
      <p class="reason">${escapeHtml(rec.reason)}</p>
    `;
    list.appendChild(card);
  }
}

const MAX_EDGE = 1600;
const JPEG_QUALITY = 0.8;

// Downscale + re-encode as JPEG on a canvas. Re-encoding also sidesteps HEIC:
// the browser decodes whatever the camera produced, we always upload JPEG.
function downscaleImage(file) {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => {
      URL.revokeObjectURL(url);
      const scale = Math.min(1, MAX_EDGE / Math.max(img.width, img.height));
      const canvas = document.createElement("canvas");
      canvas.width = Math.round(img.width * scale);
      canvas.height = Math.round(img.height * scale);
      canvas.getContext("2d").drawImage(img, 0, 0, canvas.width, canvas.height);
      const dataUrl = canvas.toDataURL("image/jpeg", JPEG_QUALITY);
      resolve({ dataUrl, base64: dataUrl.split(",")[1], mediaType: "image/jpeg" });
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error("Couldn't read that photo"));
    };
    img.src = url;
  });
}

async function scanMenu(file) {
  const btn = $("scan-btn");
  const status = $("scan-status");
  const results = $("menu-results");
  const list = $("menu-results-list");
  btn.disabled = true;
  status.hidden = true;

  try {
    const { dataUrl, base64, mediaType } = await downscaleImage(file);
    const preview = $("menu-preview");
    preview.src = dataUrl;
    preview.hidden = false;

    results.hidden = false;
    $("menu-note").hidden = true;
    list.innerHTML = "<div class='spinner'></div>";
    results.scrollIntoView({ behavior: "smooth" });

    const resp = await fetch("/api/scan-menu", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        image_base64: base64,
        media_type: mediaType,
        liked_beer_ids: [...state.selected],
        taste_text: $("taste-text").value.trim(),
        limit: 8,
      }),
    });
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      results.hidden = true;
      status.textContent = err.detail || "Menu scan failed — try again.";
      status.hidden = false;
      return;
    }
    const data = await resp.json();
    if (!data.menu_beers.length) {
      list.innerHTML = "<p class='hint'>Couldn't spot any beers on that menu — try a clearer shot.</p>";
      return;
    }
    renderMenuResults(data);
  } catch (err) {
    results.hidden = true;
    status.textContent = "Something went wrong — try again.";
    status.hidden = false;
  } finally {
    btn.disabled = false;
    $("menu-photo").value = ""; // re-picking the same photo re-fires change
  }
}

function renderMenuResults(data) {
  const list = $("menu-results-list");
  const note = $("menu-note");
  note.textContent = data.personalized
    ? "✨ Menu read by Claude · ranked against your taste"
    : "Menu read by Claude — pick beers or describe your taste for a personal ranking.";
  note.hidden = false;
  list.innerHTML = "";
  for (const rec of data.menu_beers) {
    const card = document.createElement("div");
    card.className = "rec-card";
    const pct = Math.round(Math.max(0, Math.min(1, rec.score)) * 100);
    const sourceBadge = rec.matched
      ? '<span class="badge">in catalog</span>'
      : '<span class="badge est">estimated</span>';
    const likedBadge = rec.id !== null && state.selected.has(rec.id)
      ? '<span class="badge">⭐ you like this</span>'
      : "";
    card.innerHTML = `
      <div class="rec-head">
        <div>
          <h3>${escapeHtml(rec.name)}</h3>
          <div class="brewery">${escapeHtml(rec.brewery)}</div>
        </div>
        ${rec.score ? `<span class="match">${pct}% match</span>` : ""}
      </div>
      <div class="meta">
        <span class="badge">${escapeHtml(rec.style)}</span>
        <span class="badge">${rec.abv}% ABV</span>
        <span class="badge">${rec.ibu} IBU</span>
        ${sourceBadge}
        ${likedBadge}
      </div>
      <p class="reason">${escapeHtml(rec.reason)}</p>
    `;
    list.appendChild(card);
  }
}

function reset() {
  state.selected.clear();
  $("taste-text").value = "";
  $("beer-search").value = "";
  $("results").hidden = true;
  $("menu-results").hidden = true;
  $("menu-preview").hidden = true;
  $("menu-preview").src = "";
  $("scan-status").hidden = true;
  $("menu-photo").value = "";
  renderGrid();
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function escapeHtml(str) {
  return String(str).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

init();
