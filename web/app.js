"use strict";

const state = {
  q: "", sort: "name", category: "152",
  limit: 60, offset: 0, total: 0,
  county: null, store: null,
};

const $ = (sel) => document.querySelector(sel);
const api = (path) => fetch(path).then((r) => {
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
function esc(s) { return (s || "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }

// ---- product grid ----
async function loadProducts(reset = true) {
  if (reset) { state.offset = 0; $("#grid").innerHTML = ""; }
  const params = new URLSearchParams({
    sort: state.sort, limit: state.limit, offset: state.offset, category: state.category,
  });
  if (state.q) params.set("q", state.q);
  const data = await api("/api/products?" + params);
  state.total = data.total;
  for (const p of data.items) $("#grid").insertAdjacentHTML("beforeend", card(p));
  $("#result-meta").textContent =
    `${data.total} bourbon${data.total === 1 ? "" : "s"}` + (state.q ? ` matching “${state.q}”` : "");
  state.offset += data.items.length;
  $("#more").classList.toggle("hidden", state.offset >= state.total);
  bindCards();
}

function card(p) {
  const upc = p.upcs && p.upcs.length ? `<div class="upc">UPC ${esc(p.upcs[0])}</div>` : "";
  const img = p.image_url ? `<img src="${esc(p.image_url)}" alt="" loading="lazy">` : "";
  return `<article class="card" data-code="${esc(p.product_code)}">
    <div class="img">${img}</div>
    <p class="nm">${esc(p.name || "Unnamed")}</p>
    <div class="meta">${esc(p.size || "")} ${p.varietal ? "· " + esc(p.varietal) : ""}</div>
    ${upc}
    <div class="row"><span class="price">${money(p.price)}</span>${badge(p.statewide_status)}</div>
  </article>`;
}

function bindCards() {
  document.querySelectorAll(".card").forEach((el) => {
    el.onclick = () => openDrawer(el.dataset.code);
  });
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

// ---- drawer / detail ----
async function openDrawer(code) {
  const d = $("#drawer");
  d.classList.remove("hidden");
  $("#drawer-body").innerHTML = "<p>Loading…</p>";
  const p = await api(`/api/products/${code}`);
  const upcs = (p.upcs || []).map((u) => `<li>${esc(u)}</li>`).join("") || "<li class='muted'>—</li>";
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
    <div class="kv"><span>Price</span><span class="price">${money(p.price)}</span></div>
    <div class="kv"><span>Statewide</span><span>${badge(p.statewide_status)}</span></div>
    <div class="kv"><span>Product code</span><span>${esc(p.product_code)}</span></div>
    <div><div class="muted" style="margin-top:10px">UPC(s)</div><ul class="upclist">${upcs}</ul></div>
    <p><a href="${esc(p.url)}" target="_blank" rel="noopener">View on Fine Wine &amp; Good Spirits ↗</a></p>
    ${storeCheck}`;

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
        } else {
          out.textContent = "No store result.";
        }
      } catch (e) {
        out.textContent = "Live check unavailable right now.";
      }
    };
  }
}

function closeDrawer() { $("#drawer").classList.add("hidden"); }

// ---- meta + wiring ----
async function loadMeta() {
  try {
    const m = await api("/api/meta");
    $("#stat-line").textContent = `${m.products} products · ${m.upcs} UPCs indexed.`;
    $("#disclosure").textContent = m.disclosure ? m.disclosure +
      " This is an independent informational tool, not affiliated with the PLCB." : $("#disclosure").textContent;
  } catch { /* keep default */ }
}

let searchTimer;
$("#search").addEventListener("input", (e) => {
  clearTimeout(searchTimer);
  state.q = e.target.value.trim();
  searchTimer = setTimeout(() => loadProducts(true), 250);
});
$("#sort").addEventListener("change", (e) => { state.sort = e.target.value; loadProducts(true); });
$("#more").addEventListener("click", () => loadProducts(false));
$("#drawer-close").addEventListener("click", closeDrawer);
$("#drawer").addEventListener("click", (e) => { if (e.target.id === "drawer") closeDrawer(); });

loadMeta();
loadCounties();
loadProducts(true);
