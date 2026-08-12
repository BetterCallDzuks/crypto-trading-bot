// Dashboard client: polls the JSON API and renders state. Token (if the server
// requires one) is read from the URL ?token=... and forwarded on every call.
const TOKEN = new URLSearchParams(location.search).get("token");
const auth = (url) => TOKEN ? url + (url.includes("?") ? "&" : "?") + "token=" + encodeURIComponent(TOKEN) : url;

const fmt = (n, d = 2) => (n == null || isNaN(n)) ? "—" :
  Number(n).toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d });
const usd = (n) => (n == null || isNaN(n)) ? "—" : "$" + fmt(n);
const cls = (n) => n > 0 ? "pos" : n < 0 ? "neg" : "";
const signed = (n) => (n > 0 ? "+" : "") + fmt(n);

let chart;

async function api(path, method = "GET") {
  const res = await fetch(auth(path), { method });
  if (!res.ok) throw new Error(`${path} -> ${res.status}`);
  return res.json();
}

function setBanner(msg, isError) {
  const b = document.getElementById("banner");
  if (!msg) { b.classList.add("hidden"); return; }
  b.textContent = msg;
  b.classList.remove("hidden");
  b.classList.toggle("error", !!isError);
}

async function refreshStatus() {
  let s;
  try {
    s = await api("/api/status");
  } catch (e) {
    setBanner("Cannot reach the bot API. Is the server running? " + e.message, true);
    return;
  }
  const st = s.stats || {};

  document.getElementById("context").textContent =
    `${s.exchange} · ${s.market_type} · ${(s.symbols || []).join(", ")}`;

  const modeBadge = document.getElementById("mode-badge");
  modeBadge.textContent = s.mode === "live" ? "LIVE" : "PAPER";
  modeBadge.className = "badge " + (s.mode === "live" ? "live" : "paper");

  const statusBadge = document.getElementById("status-badge");
  statusBadge.textContent = s.running ? "Running" : "Stopped";
  statusBadge.className = "badge " + (s.running ? "on" : "off");

  // Warnings.
  if (s.halted) setBanner("⚠ Trading HALTED — max drawdown circuit breaker tripped. No new positions will open.", true);
  else if (s.last_error) setBanner("Last cycle error: " + s.last_error, true);
  else if (s.mode === "live" && !s.live_confirmed) setBanner("Live mode selected but not confirmed — orders are blocked. Set TRADING_LIVE_CONFIRM to enable.", false);
  else setBanner("");

  document.getElementById("equity").textContent = usd(st.equity);
  const ret = st.total_return_pct || 0;
  const delta = document.getElementById("equity-delta");
  delta.textContent = signed(ret) + "% vs start";
  delta.className = "delta " + cls(ret);
  const retEl = document.getElementById("return");
  retEl.textContent = signed(ret) + "%"; retEl.className = "value " + cls(ret);
  const realEl = document.getElementById("realized");
  realEl.textContent = usd(st.realized_pnl); realEl.className = "value " + cls(st.realized_pnl);
  document.getElementById("winrate").textContent = fmt(st.win_rate, 1) + "%";
  document.getElementById("pf").textContent = fmt(st.profit_factor, 2);
  const ddEl = document.getElementById("drawdown");
  ddEl.textContent = fmt(s.drawdown_pct, 1) + "%";
  ddEl.className = "value " + (s.drawdown_pct > 10 ? "neg" : "");

  renderPositions(s.positions || []);
  renderSignals(s.signals || {});
}

function renderPositions(positions) {
  const tbody = document.querySelector("#positions tbody");
  const empty = document.getElementById("positions-empty");
  tbody.innerHTML = "";
  empty.style.display = positions.length ? "none" : "block";
  for (const p of positions) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${p.symbol}</td>
      <td><span class="pill ${p.side}">${p.side.toUpperCase()}</span></td>
      <td>${fmt(p.quantity, 6)}</td>
      <td>${fmt(p.entry_price)}</td>
      <td>${fmt(p.current_price)}</td>
      <td>${fmt(p.stop_loss)}</td>
      <td>${fmt(p.take_profit)}</td>
      <td class="${cls(p.unrealized_pnl)}">${signed(p.unrealized_pnl)} (${signed(p.unrealized_pnl_pct)}%)</td>`;
    tbody.appendChild(tr);
  }
}

function renderSignals(signals) {
  const tbody = document.querySelector("#signals tbody");
  tbody.innerHTML = "";
  for (const sym of Object.keys(signals)) {
    const sig = signals[sym];
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${sym}</td>
      <td><span class="pill ${sig.action}">${sig.action.toUpperCase()}</span></td>
      <td>${fmt(sig.score, 2)}</td>
      <td>${fmt(sig.price)}</td>
      <td class="reasons">${(sig.reasons || []).join(" · ")}</td>`;
    tbody.appendChild(tr);
  }
}

async function refreshTrades() {
  let trades;
  try { trades = await api("/api/trades?limit=100"); } catch { return; }
  const tbody = document.querySelector("#trades tbody");
  const empty = document.getElementById("trades-empty");
  tbody.innerHTML = "";
  empty.style.display = trades.length ? "none" : "block";
  for (const t of trades) {
    const tr = document.createElement("tr");
    const when = new Date(t.closed_at * 1000).toLocaleString();
    tr.innerHTML = `
      <td>${when}</td>
      <td>${t.symbol}</td>
      <td><span class="pill ${t.side}">${t.side.toUpperCase()}</span></td>
      <td>${fmt(t.entry_price)}</td>
      <td>${fmt(t.exit_price)}</td>
      <td class="${cls(t.pnl)}">${signed(t.pnl)}</td>
      <td class="${cls(t.pnl_pct)}">${signed(t.pnl_pct)}%</td>
      <td class="reasons">${t.reason}</td>`;
    tbody.appendChild(tr);
  }
}

async function refreshEquity() {
  let points;
  try { points = await api("/api/equity?limit=1000"); } catch { return; }
  const labels = points.map(p => new Date(p.ts * 1000).toLocaleTimeString());
  const data = points.map(p => p.equity);
  const ctx = document.getElementById("equity-chart");
  if (!chart) {
    chart = new Chart(ctx, {
      type: "line",
      data: { labels, datasets: [{
        data, borderColor: "#4a9eff", backgroundColor: "rgba(74,158,255,.1)",
        fill: true, tension: .25, pointRadius: 0, borderWidth: 2 }] },
      options: {
        plugins: { legend: { display: false } },
        scales: {
          x: { ticks: { color: "#8b98a9", maxTicksLimit: 8 }, grid: { color: "#232b3a" } },
          y: { ticks: { color: "#8b98a9" }, grid: { color: "#232b3a" } },
        },
        animation: false,
      },
    });
  } else {
    chart.data.labels = labels;
    chart.data.datasets[0].data = data;
    chart.update();
  }
}

document.getElementById("btn-start").onclick = async () => { await api("/api/start", "POST"); refreshStatus(); };
document.getElementById("btn-stop").onclick = async () => { await api("/api/stop", "POST"); refreshStatus(); };

async function tick() { await refreshStatus(); await refreshTrades(); await refreshEquity(); }
tick();
setInterval(refreshStatus, 5000);
setInterval(refreshTrades, 15000);
setInterval(refreshEquity, 15000);
