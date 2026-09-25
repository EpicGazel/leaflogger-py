/* leaflogger-py frontend. Vanilla JS + fetch, no jQuery.
   Trip path uses the /track feed (timestamp, lat/lon, speed, power).
   Segments are coloured green->red by efficiency relative to the points
   shown; parked points draw grey. (The old chart1.html parser expected 5
   columns the PHP feed never emitted, so its colouring never worked.) */
"use strict";

const state = {
  start: null, end: null,           // current view range
  tripStart: null, tripEnd: null,   // full selected trip extent
  units: "US", rows: [], fullRows: [],
  rowIndexByTs: {}, trackByTs: {},
  dark: false, lastSoc: "", lastThermal: ""
};
let map = null, tripLayer = null;

function qs() {
  const q = new URLSearchParams();
  if (state.start) q.set("start", state.start);
  if (state.end) q.set("end", state.end);
  q.set("units", state.units);
  return q.toString();
}

async function get(path, asJson) {
  const res = await fetch(path + "?" + qs());
  if (!res.ok) throw new Error(path + " -> HTTP " + res.status);
  return asJson ? res.json() : res.text();
}

/* Statute miles between two points (spherical law of cosines),
   ported from DistanceBetweenPoints.js. */
function distance(lat1, lon1, lat2, lon2) {
  const rad = (d) => Math.PI * d / 180;
  const theta = lon1 - lon2;
  let dist = Math.sin(rad(lat1)) * Math.sin(rad(lat2)) +
             Math.cos(rad(lat1)) * Math.cos(rad(lat2)) * Math.cos(rad(theta));
  dist = Math.min(1, Math.max(-1, dist)); // clamp float drift for acos
  return Math.acos(dist) * 180 / Math.PI * 60 * 1.1515;
}

function initMap() {
  map = L.map("map").setView([37.722121, -122.478676], 8);
  // OSM standard tiles in both themes: the dark CARTO layer needs an API
  // key, so the map simply stays light.
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: "&copy; <a href=\"https://www.openstreetmap.org/copyright\">OpenStreetMap</a> contributors"
  }).addTo(map);
}

function clearTripLayer() {
  if (tripLayer) { map.removeLayer(tripLayer); tripLayer = null; }
}

function makeLabelMarker(latlng, text, title) {
  return L.marker(latlng, {
    icon: L.divIcon({ className: "labels", html: text, iconSize: null }),
    title: title || text
  });
}

/* Segment colour: green (efficient) .. yellow .. red (inefficient).
   Efficiency = speed (mph) per kW, min-max normalised over the moving
   points shown, so it is relative to the current view. Parked points
   (speed < 1 mph or no power draw) draw grey. */
function efficiencyOf(p) {
  const kw = ((p.motor_w || 0) + (p.aux_w || 0) + (p.ac_w || 0)) / 1000;
  if ((p.speed || 0) < 1 || kw <= 0) return null;
  return p.speed / kw;
}

function efficiencyColor(t) {
  // t: 0 = worst -> red, 1 = best -> green, via yellow (255, 192, 0).
  const r = Math.round(t < 0.5 ? 255 : 255 * (1 - (t - 0.5) * 2));
  const g = Math.round(t < 0.5 ? 192 * t * 2 : 192 + (255 - 192) * (t - 0.5) * 2);
  return `rgb(${r},${g},0)`;
}

function renderMap(track) {
  clearTripLayer();
  tripLayer = L.layerGroup().addTo(map);
  const pts = (track || []).filter((p) =>
    p.lat && p.lon && p.lat !== 0 && !isNaN(p.lat) && !isNaN(p.lon));
  if (!pts.length) return;
  const effs = pts.map(efficiencyOf);
  const moving = effs.filter((e) => e !== null);
  const lo = Math.min(...moving), hi = Math.max(...moving);
  const span = hi - lo;
  if (moving.length < 2 || span <= 0) {
    // No usable power data: one plain polyline.
    const line = L.polyline(pts.map((p) => [p.lat, p.lon]),
      { color: "#3388ff", weight: 5 }).addTo(tripLayer);
    line.on("mouseover", (ev) => highlightNearest(ev.latlng.lat, ev.latlng.lng));
  } else {
    for (let i = 1; i < pts.length; i++) {
      const eff = effs[i - 1];
      const color = eff === null ? "#888888" : efficiencyColor((eff - lo) / span);
      const seg = L.polyline([[pts[i - 1].lat, pts[i - 1].lon], [pts[i].lat, pts[i].lon]],
        { color, weight: 5 }).addTo(tripLayer);
      seg.on("mouseover", (ev) => highlightNearest(ev.latlng.lat, ev.latlng.lng));
    }
  }
  makeLabelMarker([pts[0].lat, pts[0].lon], "Start", pts[0].t).addTo(tripLayer);
  makeLabelMarker([pts[pts.length - 1].lat, pts[pts.length - 1].lon], "End",
    pts[pts.length - 1].t).addTo(tripLayer);
  map.fitBounds(L.latLngBounds(pts.map((p) => [p.lat, p.lon])));
}

function highlightTableRow(i) {
  document.querySelectorAll("#dataTable tbody tr.highlight")
    .forEach((tr) => tr.classList.remove("highlight"));
  if (i < 0) return;
  const tr = document.querySelector(`#dataTable tbody tr[data-i="${i}"]`);
  if (tr) {
    tr.classList.add("highlight");
    tr.scrollIntoView({ block: "nearest" });
  }
}

function highlightNearest(lat, lon) {
  let best = -1, bestDist = Infinity;
  state.rows.forEach((r, i) => {
    const d = distance(parseFloat(r[2]), parseFloat(r[3]), lat, lon);
    if (d < bestDist) { bestDist = d; best = i; }
  });
  highlightTableRow(best);
}

/* Chart hover -> table: match by timestamp so ignored rows (present in
   the charts, absent from the table) simply highlight nothing. */
function wireChartHover(divId) {
  const div = document.getElementById(divId);
  div.removeAllListeners("plotly_hover");
  div.on("plotly_hover", (data) => {
    const ts = data.points && data.points[0] && data.points[0].x;
    const i = state.rowIndexByTs[ts];
    highlightTableRow(i === undefined ? -1 : i);
  });
}

function parseCsv(text) {
  const lines = text.trim().split("\n");
  return { header: lines[0].split(","), rows: lines.slice(1).map((l) => l.split(",")) };
}

function pointNumbers(n) {
  return Array.from({ length: n }, (_, i) => i + 1); // 1-based point # in view
}

function chartLayout(title) {
  const layout = { title, hovermode: "x unified", margin: { t: 40 } };
  if (state.dark) {
    layout.paper_bgcolor = "#1e1e1e";
    layout.plot_bgcolor = "#1e1e1e";
    layout.font = { color: "#e0e0e0" };
    layout.xaxis = { gridcolor: "#444444", zerolinecolor: "#666666" };
    layout.yaxis = { gridcolor: "#444444", zerolinecolor: "#666666" };
  }
  return layout;
}

function renderSoc(text) {
  state.lastSoc = text;
  const { rows } = parseCsv(text);
  const x = rows.map((r) => r[0]);
  Plotly.newPlot("socChart", [
    { x, y: rows.map((r) => (r[1] === "" ? null : parseFloat(r[1]))),
      customdata: pointNumbers(rows.length),
      hovertemplate: "Point #%{customdata}<br>%{x}<br>SOC: %{y}<extra></extra>",
      mode: "lines", name: "SOC", line: { width: 3 } },
    { x, y: rows.map((r) => (r[2] === "" ? null : parseFloat(r[2]))),
      customdata: pointNumbers(rows.length),
      hovertemplate: "Point #%{customdata}<br>%{x}<br>GIDs: %{y}<extra></extra>",
      mode: "lines", name: "GIDs", line: { width: 3 } }
  ], chartLayout("SOC"));
  wireChartHover("socChart");
}

function renderThermal(text) {
  state.lastThermal = text;
  const { header, rows } = parseCsv(text);
  const traces = [];
  for (let c = 1; c < header.length; c++) {
    if (header[c] === "empty" || header[c] === "") continue; // hidden series
    traces.push({
      x: rows.map((r) => r[0]),
      y: rows.map((r) => (r[c] === "" || r[c] === undefined ? null : parseFloat(r[c]))),
      customdata: pointNumbers(rows.length),
      hovertemplate: `Point #%{customdata}<br>%{x}<br>${header[c]}: %{y}<extra></extra>`,
      mode: "lines", name: header[c], line: { width: 3 }
    });
  }
  Plotly.newPlot("thermalChart", traces, chartLayout("Thermal"));
  wireChartHover("thermalChart");
}

function renderSummary(s) {
  const num = (v) => Number(v).toLocaleString("en-US");
  document.getElementById("summary").innerHTML =
    `<b>Length: </b>${s.trip_length} mins | <b>Dist: </b>${s.trip} ${s.distance_units} | ` +
    `<b>Avg Spd: </b>${s.averageSpeed} ${s.speed_units} | <b>SOC Diff: </b>${s.socDifference}% | ` +
    `<b>GIDS Diff: </b>${s.gidsDifference} | <b>Odo: </b>${num(s.start)}-${num(s.end)}`;
}

function renderTable(aaData) {
  state.rows = aaData;
  state.rowIndexByTs = {};
  aaData.forEach((r, i) => { state.rowIndexByTs[r[1]] = i; });
  // Trip-absolute node numbers from the full trip rows, so a 29-32 view
  // starts at 29 instead of renumbering from 1.
  const absIndexByTs = {};
  state.fullRows.forEach((r, i) => { absIndexByTs[r[1]] = i + 1; });
  // Cumulative distance/efficiency are miles-based server-side; convert
  // for SI display.
  const metric = state.units === "SI";
  const MI_TO_KM = 1.609344;
  document.getElementById("miHead").textContent = metric ? "km" : "Mi";
  document.getElementById("effHead").textContent = metric ? "km/kWh" : "mi/kWh";
  const tbody = document.querySelector("#dataTable tbody");
  tbody.innerHTML = "";
  for (let i = 0; i < aaData.length; i++) {
    const r = aaData[i];
    const tr = document.createElement("tr");
    tr.dataset.i = i;
    const numTd = document.createElement("td");
    const abs = absIndexByTs[r[1]];
    numTd.textContent = abs === undefined ? r[0] : abs;
    tr.appendChild(numTd);
    // aaData columns: [n, ts, lat, lon, elev, elev_fixed, speed, soc,
    // gids, soh, ts2]. elev_fixed is dead data (nothing ever wrote it —
    // the Google Elevation lookup script is long gone), so it is skipped.
    for (const c of [1, 2, 3, 4, 6, 7, 8, 9]) {
      const td = document.createElement("td");
      td.textContent = r[c];
      tr.appendChild(td);
    }
    const cum = state.trackByTs[r[1]];
    const miTd = document.createElement("td");
    miTd.textContent = !cum ? "—"
      : ((metric ? cum.cum_mi * MI_TO_KM : cum.cum_mi).toFixed(1));
    tr.appendChild(miTd);
    const effTd = document.createElement("td");
    const eff = cum ? cum.cum_eff : null;
    effTd.textContent = (eff === null || eff === undefined) ? "—"
      : ((metric ? eff * MI_TO_KM : eff).toFixed(1));
    tr.appendChild(effTd);
    const td = document.createElement("td");
    const btn = document.createElement("button");
    btn.className = "ignoreBtn";
    btn.textContent = "\u2716";
    btn.title = "Ignore " + r[1];
    btn.addEventListener("click", () => ignorePoint(r[1]));
    td.appendChild(btn);
    tr.appendChild(td);
    tbody.appendChild(tr);
  }
}

async function ignorePoint(date) {
  await fetch("/ignore?date=" + encodeURIComponent(date), { method: "POST" });
  await refreshFullRows(); // membership changed: renumber + remap sliders
  updateData(state.start, state.end);
}

/* Empty the whole view after a deletion (trip or all). */
function clearView() {
  state.start = state.end = state.tripStart = state.tripEnd = null;
  state.rows = []; state.fullRows = [];
  state.rowIndexByTs = {}; state.trackByTs = {};
  state.lastSoc = ""; state.lastThermal = "";
  document.getElementById("tripSelect").value = "";
  document.getElementById("summary").textContent = "";
  document.getElementById("rangeLabel").textContent = "";
  document.getElementById("fromBox").value = "";
  document.getElementById("toBox").value = "";
  setSliderRange(0);
  setSliders(0, 0);
  document.querySelector("#dataTable tbody").innerHTML = "";
  Plotly.purge("socChart");
  Plotly.purge("thermalChart");
  clearTripLayer();
}

async function deleteTrip() {
  if (!state.tripStart) return;
  const n = state.fullRows.length;
  if (!window.confirm(
      `Delete the selected trip (${state.tripStart} → ${state.tripEnd}, ` +
      `${n} points)? This cannot be undone.`)) return;
  const res = await fetch(
    `/trip?start=${encodeURIComponent(state.tripStart)}` +
    `&end=${encodeURIComponent(state.tripEnd)}`, { method: "DELETE" });
  const stats = await res.json();
  clearView();
  await loadTrips(false);
  document.getElementById("uploadStatus").textContent =
    `Deleted trip: ${stats.rows} records removed.`;
}

async function deleteAll() {
  const health = await (await fetch("/health")).json();
  if (!window.confirm(
      `Delete ALL ${health.records} records? This cannot be undone ` +
      `short of re-uploading.`)) return;
  if (!window.confirm("Really delete everything? Last chance.")) return;
  const res = await fetch("/records", { method: "DELETE" });
  const stats = await res.json();
  clearView();
  await loadTrips(false);
  document.getElementById("uploadStatus").textContent =
    `Deleted all: ${stats.rows} records removed.`;
}

async function updateData(start, end) {
  state.start = start; state.end = end;
  const [summary, soc, thermal, track, table] = await Promise.all([
    get("/summary", true), get("/soc"), get("/thermal"),
    get("/track", true), get("/table", true)
  ]);
  state.trackByTs = {};
  track.forEach((p) => { state.trackByTs[p.t] = p; });
  renderSummary(summary);
  renderSoc(soc);
  renderThermal(thermal);
  renderMap(track);
  renderTable(table.aaData);
  reconcileSliders();
  const [cs, ce] = sliderValues();
  if (state.fullRows.length) updatePointBoxes(cs, ce);
  document.getElementById("rangeLabel").textContent =
    `Showing ${start} → ${end} (${table.aaData.length} of ${state.fullRows.length} points)`;
}

/* Full trip selection: caches the trip's rows so the sliders always map
   across the whole trip and the range can be widened again. */
async function refreshFullRows() {
  const s = state.start, e = state.end;
  state.start = state.tripStart; state.end = state.tripEnd;
  try {
    state.fullRows = (await get("/table", true)).aaData;
  } finally {
    state.start = s; state.end = e;
  }
}

async function selectTrip(start, end) {
  state.tripStart = start; state.tripEnd = end;
  state.start = start; state.end = end;
  await refreshFullRows();
  setSliderRange(state.fullRows.length);
  setSliders(0, Math.max(0, state.fullRows.length - 1));
  await updateData(start, end);
}

function resetRange() {
  if (!state.tripStart) return;
  setSliderRange(state.fullRows.length);
  setSliders(0, Math.max(0, state.fullRows.length - 1));
  updateData(state.tripStart, state.tripEnd).catch((e) => console.error(e));
}

async function loadTrips(selectLast) {
  const trips = await get("/trips", true);
  const sel = document.getElementById("tripSelect");
  sel.innerHTML = "";
  const placeholder = document.createElement("option");
  placeholder.value = "";
  placeholder.textContent = "----------";
  sel.appendChild(placeholder);
  for (const t of trips) {
    const opt = document.createElement("option");
    opt.value = t.start + "|" + t.end;
    opt.textContent = `${t.start} to ${t.end} ( ${t.records} )`;
    sel.appendChild(opt);
  }
  if (selectLast && trips.length) {
    sel.value = sel.options[sel.options.length - 1].value;
    onTripChange();
  }
}

function onTripChange() {
  const v = document.getElementById("tripSelect").value;
  if (!v) return;
  const [start, end] = v.split("|");
  selectTrip(start, end).catch((e) => console.error(e));
}

/* Sliders snap per point: positions ARE row indices into the full trip
   (min 0, max N-1, step 1 — range set on trip select). No quantization,
   so From/To boxes show exact points and a 1-step gap is a 1-row gap. */
function sliderValues() {
  return [+document.getElementById("sliderStart").value,
          +document.getElementById("sliderEnd").value];
}
function sliderMax() {
  return +document.getElementById("sliderStart").max || 0;
}
/* Blue fill between the two thumbs on the shared bar. */
function updateSliderFill() {
  const max = sliderMax() || 1;
  const [s, e] = sliderValues();
  const fill = document.getElementById("dualfill");
  fill.style.left = (s / max * 100) + "%";
  fill.style.right = (100 - e / max * 100) + "%";
}
function setSliders(s, e) {
  document.getElementById("sliderStart").value = s;
  document.getElementById("sliderEnd").value = e;
  updateSliderFill();
}
function setSliderRange(n) {
  const max = Math.max(0, n - 1);
  document.getElementById("sliderStart").max = max;
  document.getElementById("sliderEnd").max = max;
}
/* Clamp stale handle positions into [0, max] (e.g. rows were ignored). */
function reconcileSliders() {
  const n = state.fullRows.length;
  setSliderRange(n);
  const max = Math.max(0, n - 1);
  const sEl = document.getElementById("sliderStart");
  const eEl = document.getElementById("sliderEnd");
  sEl.value = Math.min(max, Math.max(0, +sEl.value));
  eEl.value = Math.min(max, Math.max(0, +eEl.value));
  updateSliderFill();
}
/* Halt the dragged handle one row short of the other: a strict ≥1-row
   gap, so the thumbs can never fully coincide. */
function haltHandles(changed) {
  const sEl = document.getElementById("sliderStart");
  const eEl = document.getElementById("sliderEnd");
  if (state.fullRows.length < 2) return;
  if (changed !== sEl && changed !== eEl) return;
  const max = sliderMax();
  let [s, e] = sliderValues();
  if (changed === sEl) {
    if (s >= e) {
      if (e > 0) s = e - 1;
      else { s = 0; e = Math.min(max, 1); }
    }
  } else {
    if (e <= s) {
      if (s < max) e = s + 1;
      else { e = max; s = Math.max(0, max - 1); }
    }
  }
  sEl.value = s; eEl.value = e;
}

function updatePointBoxes(lo, hi) {
  document.getElementById("fromBox").value = lo + 1;
  document.getElementById("toBox").value = hi + 1;
}

function onSlider(evt) {
  haltHandles(evt && evt.target);
  updateSliderFill();
  if (state.fullRows.length < 2) return;
  const [s, e] = sliderValues();
  updatePointBoxes(s, e);
  updateData(state.fullRows[s][1], state.fullRows[e][1])
    .catch((err) => console.error(err));
}

/* Live box update while dragging; reload happens on release (change). */
function onSliderInput(evt) {
  haltHandles(evt && evt.target);
  updateSliderFill();
  if (state.fullRows.length < 2) return;
  const [s, e] = sliderValues();
  updatePointBoxes(s, e);
}

/* Editable point-number boxes: apply on change, move sliders to match.
   Out-of-range input snaps to the nearest valid selection instead of
   reverting: the box being edited gives way (to lowered to from+1,
   from raised to to-1), clamped into [1, N]. */
function onRangeBox(changed) {
  const n = state.fullRows.length;
  const fromBox = document.getElementById("fromBox");
  const toBox = document.getElementById("toBox");
  if (n < 2) {
    const [s, e] = sliderValues();
    updatePointBoxes(s, e);
    return; // nothing selectable: revert
  }
  let from = Math.round(Number(fromBox.value));
  let to = Math.round(Number(toBox.value));
  if (!isFinite(from) || !isFinite(to)) {
    const [s, e] = sliderValues();
    updatePointBoxes(s, e);
    return; // not a number: revert
  }
  from = Math.min(n, Math.max(1, from));
  to = Math.min(n, Math.max(1, to));
  if (from >= to) {
    if (changed === toBox) {
      to = from + 1;
      if (to > n) { to = n; from = n - 1; }
    } else {
      from = to - 1;
      if (from < 1) { from = 1; to = 2; }
    }
  }
  setSliders(from - 1, to - 1);
  updateData(state.fullRows[from - 1][1], state.fullRows[to - 1][1])
    .catch((err) => console.error(err));
}

function applyDark() {
  document.body.classList.toggle("dark", state.dark);
  document.getElementById("darkToggle").textContent =
    state.dark ? "\u2600\uFE0F" : "\uD83C\uDF19";
  try { localStorage.setItem("leaflogger-theme", state.dark ? "dark" : "light"); } catch (e) { /* private mode */ }
  if (state.lastSoc) renderSoc(state.lastSoc);
  if (state.lastThermal) renderThermal(state.lastThermal);
}

document.addEventListener("DOMContentLoaded", () => {
  let stored = null;
  try { stored = localStorage.getItem("leaflogger-theme"); } catch (e) { /* private mode */ }
  state.dark = stored ? stored === "dark"
    : (window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches);
  document.body.classList.toggle("dark", state.dark);
  initMap();
  document.getElementById("darkToggle").textContent =
    state.dark ? "\u2600\uFE0F" : "\uD83C\uDF19";
  document.getElementById("darkToggle").addEventListener("click", () => {
    state.dark = !state.dark;
    applyDark();
  });
  document.getElementById("tripSelect").addEventListener("change", onTripChange);
  document.getElementById("sliderStart").addEventListener("change", onSlider);
  document.getElementById("sliderEnd").addEventListener("change", onSlider);
  document.getElementById("sliderStart").addEventListener("input", onSliderInput);
  document.getElementById("sliderEnd").addEventListener("input", onSliderInput);
  document.getElementById("resetRange").addEventListener("click", resetRange);
  document.getElementById("fromBox").addEventListener("change",
    (e) => onRangeBox(e.target));
  document.getElementById("toBox").addEventListener("change",
    (e) => onRangeBox(e.target));
  document.getElementById("deleteTrip").addEventListener("click", () => {
    deleteTrip().catch((e) => console.error(e));
  });
  document.getElementById("deleteAll").addEventListener("click", () => {
    deleteAll().catch((e) => console.error(e));
  });
  document.getElementById("expandMap").addEventListener("click", () => {
    const panel = document.getElementById("mapPanel");
    if (document.fullscreenElement) document.exitFullscreen();
    else if (panel.requestFullscreen) panel.requestFullscreen();
  });
  document.addEventListener("fullscreenchange", () => {
    // Leaflet sizes to its container once; re-measure after the change.
    setTimeout(() => map.invalidateSize(), 50);
  });
  document.getElementById("unitsSelect").addEventListener("change", (e) => {
    state.units = e.target.value;
    if (state.start) updateData(state.start, state.end).catch((err) => console.error(err));
  });
  document.getElementById("uploadForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const file = document.getElementById("uploadFile").files[0];
    if (!file) return;
    const status = document.getElementById("uploadStatus");
    status.textContent = "uploading...";
    const form = new FormData();
    form.append("file", file);
    const res = await fetch("/upload", { method: "POST", body: form });
    if (!res.ok) {
      status.textContent = `upload failed: HTTP ${res.status}`;
      return;
    }
    const stats = await res.json();
    status.textContent =
      `${stats.inserted} inserted, ${stats.dups} dups, ${stats.errors} errors ` +
      `(${stats.processed} processed)`;
    loadTrips(true).catch((err) => console.error(err));
  });
  loadTrips(true).catch((e) => console.error(e));
});
