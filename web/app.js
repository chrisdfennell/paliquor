"use strict";

const state = {
  q: "", sort: "name", category: "",
  chairmans: false, on_sale: false, in_stock: false,
  limit: 60, offset: 0, total: 0,
  county: null, store: null,
};

const $ = (sel) => document.querySelector(sel);
const api = (path, opts) => fetch(path, opts).then((r) => {
  if (!r.ok) throw new Error(r.status);
  return r.json();
});

function badge(status) {
  const s = (status || "").toUpperCase();
  if (s === "IN_STOCK") return '<span class="badge in">In stock</span>';
  if (s === "OUT_OF_STOCK") return '<span class="badge out">Out of stock</span>';
  return '<span class="badge unk">Unknown</span>';
}
function money(p) { return p == null ? "—" : "$" + Number(p).toFixed(2); }
function esc(s) { return (s == null ? "" : String(s)).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }

// ---- product grid ----
async function loadProducts(reset = true) {
  if (reset) { state.offset = 0; $("#grid").innerHTML = ""; }
  const params = new URLSearchParams({
    sort: state.sort, limit: state.limit, offset: state.offset,
  });
  if (state.category) params.set("category", state.category);
  if (state.q) params.set("q", state.q);
  if (state.chairmans) params.set("chairmans", "true");
  if (state.on_sale) params.set("on_sale", "true");
  if (state.in_stock) params.set("in_stock", "true");
  const data = await api("/api/products?" + params);
  state.total = data.total;
  for (const p of data.items) $("#grid").insertAdjacentHTML("beforeend", card(p));
  $("#result-meta").textContent =
    `${data.total} bottle${data.total === 1 ? "" : "s"}` + (state.q ? ` matching “${state.q}”` : "");
  state.offset += data.items.length;
  $("#more").classList.toggle("hidden", state.offset >= state.total);
  bindCards();
}

function tags(p) {
  const t = [];
  if (p.is_chairmans) t.push('<span class="tag chair">Chairman\'s</span>');
  if (p.on_sale) t.push(`<span class="tag sale">${p.discount_pct}% off · save ${money(p.savings)}</span>`);
  if (p.proof) t.push(`<span class="tag proof">${p.proof}°</span>`);
  return t.length ? `<div class="tags">${t.join("")}</div>` : "";
}

function priceBlock(p) {
  if (p.on_sale) {
    return `<span class="price">${money(p.price)}</span> <span class="was">${money(p.list_price)}</span>`;
  }
  return `<span class="price">${money(p.price)}</span>`;
}

function card(p) {
  const upc = p.upcs && p.upcs.length ? `<div class="upc">UPC ${esc(p.upcs[0])}</div>` : "";
  const img = p.image_url ? `<img src="${esc(p.image_url)}" alt="" loading="lazy">` : "";
  const value = p.price_per_750 ? `<div class="value">${money(p.price_per_750)}/750mL</div>` : "";
  return `<article class="card" data-code="${esc(p.product_code)}">
    <div class="img">${img}</div>
    ${tags(p)}
    <p class="nm">${esc(p.name || "Unnamed")}</p>
    <div class="meta">${esc(p.size || "")} ${p.varietal ? "· " + esc(p.varietal) : ""}</div>
    ${upc}${value}
    <div class="row">${priceBlock(p)}${badge(p.statewide_status)}</div>
  </article>`;
}

function bindCards() {
  document.querySelectorAll(".card").forEach((el) => {
    el.onclick = () => openDrawer(el.dataset.code);
  });
}

// ---- categories (filter dropdown) ----
async function loadMeta() {
  try {
    const m = await api("/api/meta");
    $("#stat-line").textContent = `${m.products} products · ${m.upcs} UPCs indexed.`;
    const sel = $("#category");
    sel.innerHTML = '<option value="">All whiskey</option>' +
      Object.entries(m.categories).map(([code, label]) =>
        `<option value="${esc(code)}">${esc(label)}</option>`).join("");
    sel.value = "152"; state.category = "152";  // default to bourbon
    if (m.disclosure) $("#disclosure").textContent =
      m.disclosure + " This is an independent informational tool, not affiliated with the PLCB.";
  } catch { /* keep defaults */ }
}

// ---- counties ----
async function loadCounties() {
  const data = await api("/api/counties");
  const ul = $("#county-list");
  ul.innerHTML = data.counties.map((c) =>
    `<li><button data-county="${esc(c.county)}">
       <span>${esc(c.county)}</span><span class="count">${c.store_count || ""}</span>
     </button></li>`).join("");
  ul.querySelectorAll("button").forEach((b) => {
    b.onclick = () => selectCounty(b.dataset.county, b);
  });
}

async function selectCounty(county, btn) {
  document.querySelectorAll("#county-list button").forEach((b) => b.classList.remove("active"));
  btn.classList.add("active");
  state.county = county;
  const data = await api(`/api/counties/${encodeURIComponent(county)}/stores`);
  const banner = $("#store-banner");
  if (!data.stores.length) {
    banner.classList.remove("hidden");
    banner.innerHTML = `<span>No stores loaded for <b>${esc(county)}</b> yet. Load the official PLCB store list to enable per-store checks.</span><button id="clr">clear</button>`;
  } else {
    const opts = data.stores.map((s) =>
      `<option value="${esc(s.store_code)}">${esc(s.name || s.city || s.store_code)}</option>`).join("");
    banner.classList.remove("hidden");
    banner.innerHTML = `<span><b>${esc(county)}</b> · choose a store, then open any bottle to check it:
      <select id="store-pick">${opts}</select></span><button id="clr">clear</button>`;
    $("#store-pick").onchange = (e) => { state.store = e.target.value; };
    state.store = data.stores[0].store_code;
  }
  $("#clr").onclick = clearCounty;
}

function clearCounty() {
  state.county = null; state.store = null;
  $("#store-banner").classList.add("hidden");
  document.querySelectorAll("#county-list button").forEach((b) => b.classList.remove("active"));
}

// ---- price history sparkline (inline SVG) ----
function sparkline(history) {
  const pts = history.filter((h) => h.price != null);
  if (pts.length < 2) return '<p class="note">Not enough history yet — price tracking starts now.</p>';
  const w = 380, h = 60, pad = 6;
  const prices = pts.map((p) => p.price);
  const min = Math.min(...prices), max = Math.max(...prices);
  const span = max - min || 1;
  const x = (i) => pad + (i * (w - 2 * pad)) / (pts.length - 1);
  const y = (v) => h - pad - ((v - min) / span) * (h - 2 * pad);
  const d = pts.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p.price).toFixed(1)}`).join(" ");
  return `<svg class="spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">
    <path d="${d}" fill="none" stroke="#a8541a" stroke-width="2"/>
  </svg>
  <div class="spark-legend"><span>${money(min)}</span><span>${pts.length} points</span><span>${money(max)}</span></div>`;
}

// ---- drawer / detail ----
async function openDrawer(code) {
  const d = $("#drawer");
  d.classList.remove("hidden");
  $("#drawer-body").innerHTML = "<p>Loading…</p>";
  const [p, hist] = await Promise.all([
    api(`/api/products/${code}`),
    api(`/api/products/${code}/history`).catch(() => ({ history: [] })),
  ]);
  const upcs = (p.upcs || []).map((u) => `<li>${esc(u)}</li>`).join("") || "<li class='muted'>—</li>";

  const priceRow = p.on_sale
    ? `<span class="price">${money(p.price)}</span> <span class="was">${money(p.list_price)}</span> <span class="tag sale">Save ${money(p.savings)}</span>`
    : `<span class="price">${money(p.price)}</span>`;

  const storeCheck = state.store ? `
    <div class="avail-box">
      <h4>Check a store</h4>
      <div class="muted">Selected county: ${esc(state.county)}</div>
      <button class="btn" id="check-btn" style="margin-top:8px">Check this store (live)</button>
      <div id="check-result" class="note"></div>
    </div>` : `
    <div class="avail-box">
      <h4>Check a store</h4>
      <p class="note">Pick a county and store on the left to enable a best-effort per-store check.</p>
    </div>`;

  $("#drawer-body").innerHTML = `
    <h3>${esc(p.name || "")}</h3>
    <div class="muted">${esc(p.size || "")} ${p.varietal ? "· " + esc(p.varietal) : ""} · ${esc(p.category || "")}</div>
    <div class="d-img">${p.image_url ? `<img src="${esc(p.image_url)}" alt="">` : ""}</div>
    ${tags(p)}
    <div class="kv"><span>Price</span><span>${priceRow}</span></div>
    ${p.price_per_750 ? `<div class="kv"><span>Value</span><span>${money(p.price_per_750)} / 750mL</span></div>` : ""}
    ${p.proof ? `<div class="kv"><span>Proof</span><span>${p.proof}° (${(p.proof / 2).toFixed(1)}% ABV)</span></div>` : ""}
    <div class="kv"><span>Statewide</span><span>${badge(p.statewide_status)}</span></div>
    <div class="kv"><span>Product code</span><span>${esc(p.product_code)}</span></div>
    <div><div class="muted" style="margin-top:10px">UPC(s)</div><ul class="upclist">${upcs}</ul></div>

    <div class="hist-box">
      <h4>Price history</h4>
      ${sparkline(hist.history || [])}
    </div>

    <div class="avail-box">
      <h4>Watch this bottle</h4>
      <p class="note">Get an email when it’s back in stock statewide or the price drops.</p>
      <input id="watch-email" type="email" placeholder="you@example.com" />
      <button class="btn" id="watch-btn" style="margin-top:8px">Watch</button>
      <div id="watch-result" class="note"></div>
    </div>

    <p><a href="${esc(p.url)}" target="_blank" rel="noopener">View on Fine Wine &amp; Good Spirits ↗</a></p>
    ${storeCheck}`;

  $("#watch-btn").onclick = async () => {
    const email = $("#watch-email").value.trim();
    const out = $("#watch-result");
    if (!email || !email.includes("@")) { out.textContent = "Enter a valid email."; return; }
    out.textContent = "Saving…";
    try {
      await api(`/api/products/${code}/watch`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email }),
      });
      out.textContent = "✓ Watching. You’ll be emailed on a restock or price drop.";
    } catch { out.textContent = "Couldn’t save the watch."; }
  };

  if (state.store) {
    $("#check-btn").onclick = async () => {
      const out = $("#check-result");
      out.textContent = "Checking… (a single polite live lookup)";
      try {
        const r = await api(`/api/products/${code}/availability?store_code=${encodeURIComponent(state.store)}`);
        const st = r.store;
        if (st) {
          const link = st.verify_url
            ? `<br><a href="${esc(st.verify_url)}" target="_blank" rel="noopener">Confirm at this store on Fine Wine &amp; Good Spirits ↗</a>`
            : "";
          out.innerHTML = `<b>${esc(st.name || st.store_code)}:</b> ${badge(st.status)} ${st.quantity != null ? "(" + st.quantity + ")" : ""}<br>${esc(st.note || st.source || "")}${link}`;
        } else { out.textContent = "No store result."; }
      } catch { out.textContent = "Live check unavailable right now."; }
    };
  }
}

function closeDrawer() { $("#drawer").classList.add("hidden"); }

// ---- wiring ----
let searchTimer;
$("#search").addEventListener("input", (e) => {
  clearTimeout(searchTimer);
  state.q = e.target.value.trim();
  searchTimer = setTimeout(() => loadProducts(true), 250);
});
$("#category").addEventListener("change", (e) => { state.category = e.target.value; loadProducts(true); });
$("#sort").addEventListener("change", (e) => { state.sort = e.target.value; loadProducts(true); });
$("#f-sale").addEventListener("change", (e) => { state.on_sale = e.target.checked; loadProducts(true); });
$("#f-instock").addEventListener("change", (e) => { state.in_stock = e.target.checked; loadProducts(true); });
$("#more").addEventListener("click", () => loadProducts(false));

// ---- dark mode (persisted) ----
function applyTheme(theme) {
  document.body.classList.toggle("dark", theme === "dark");
  const btn = $("#theme-toggle");
  if (btn) btn.textContent = theme === "dark" ? "☀️" : "🌙";
}
(function initTheme() {
  const saved = localStorage.getItem("paliquor-theme")
    || (window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  applyTheme(saved);
})();
$("#theme-toggle").addEventListener("click", () => {
  const next = document.body.classList.contains("dark") ? "light" : "dark";
  localStorage.setItem("paliquor-theme", next);
  applyTheme(next);
});
$("#drawer-close").addEventListener("click", closeDrawer);
$("#drawer").addEventListener("click", (e) => { if (e.target.id === "drawer") closeDrawer(); });

(async () => {
  await loadMeta();      // sets category options + default
  loadCounties();
  loadProducts(true);
})();
