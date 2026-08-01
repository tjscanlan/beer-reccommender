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

function reset() {
  state.selected.clear();
  $("taste-text").value = "";
  $("beer-search").value = "";
  $("results").hidden = true;
  renderGrid();
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function escapeHtml(str) {
  return String(str).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

init();
