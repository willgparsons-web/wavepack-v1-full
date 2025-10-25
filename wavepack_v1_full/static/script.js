// -----------------------------
// Wavepack v1.2 Frontend Script
// -----------------------------

let currentUnits = "imperial"; // or "si"
let currentResult = null;

// Helper: Fetch calculation results from Flask
async function fetchResults() {
  const payload = {
    a_in: parseFloat(document.getElementById("a_in").value),
    b_in: parseFloat(document.getElementById("b_in").value),
    t_in: parseFloat(document.getElementById("t_in").value),
    L_ft: parseFloat(document.getElementById("L_ft").value),
    cfm: parseFloat(document.getElementById("cfm").value),
    Tmax_F: parseFloat(document.getElementById("Tmax_F").value),
    v_target: parseFloat(document.getElementById("v_target").value),
    dP_max: parseFloat(document.getElementById("dP_max").value),
    material: document.getElementById("material").value,
    fluid: document.getElementById("fluid").value
  };

  const response = await fetch("/calculate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });

  const result = await response.json();
  currentResult = result;
  updateOutputs(result);
  drawWavepack(result);
  updateCharts(result);
}

// Update output numbers
function updateOutputs(result) {
  document.getElementById("c_tubes").textContent = result.tube_count;
  document.getElementById("c_v").textContent = result.velocity_fts.toFixed(2);
  document.getElementById("c_dp").textContent = result.deltaP_psi.toFixed(3);
  document.getElementById("c_w").textContent = result.total_weight_lbm.toFixed(1);
  document.getElementById("c_fc").textContent = result.fc_GHz.toFixed(3);
}

// Event listeners for all inputs
document.querySelectorAll("input, select").forEach(el => {
  el.addEventListener("change", fetchResults);
  el.addEventListener("input", () => {
    // Live update with slight delay
    clearTimeout(window.inputTimer);
    window.inputTimer = setTimeout(fetchResults, 300);
  });
});

// Shape toggle behavior
document.getElementById("shape").addEventListener("change", e => {
  const shape = e.target.value;
  document.getElementById("sideBwrap").style.display = shape === "square" ? "none" : "block";
  if (shape === "square") {
    document.getElementById("b_in").value = document.getElementById("a_in").value;
  }
  fetchResults();
});

// Unit toggle
document.getElementById("unitToggle").addEventListener("change", e => {
  currentUnits = e.target.checked ? "si" : "imperial";
  convertUnits();
  fetchResults();
});

// Generate report
document.getElementById("exportBtn").addEventListener("click", async () => {
  const response = await fetch("/report", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      a_in: parseFloat(document.getElementById("a_in").value),
      b_in: parseFloat(document.getElementById("b_in").value),
      t_in: parseFloat(document.getElementById("t_in").value),
      L_ft: parseFloat(document.getElementById("L_ft").value),
      cfm: parseFloat(document.getElementById("cfm").value),
      Tmax_F: parseFloat(document.getElementById("Tmax_F").value),
      v_target: parseFloat(document.getElementById("v_target").value),
      dP_max: parseFloat(document.getElementById("dP_max").value),
      material: document.getElementById("material").value,
      fluid: document.getElementById("fluid").value
    })
  });
  const blob = await response.blob();
  const url = window.URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "Wavepack_Report.pdf";
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.URL.revokeObjectURL(url);
});

// -----------------------------
// Unit Conversion
// -----------------------------
function convertUnits() {
  const f = x => parseFloat(x) || 0;
  if (currentUnits === "si") {
    // Imperial → SI
    document.getElementById("a_in").value = (f(a_in.value) * 0.0254).toFixed(4);
    document.getElementById("b_in").value = (f(b_in.value) * 0.0254).toFixed(4);
    document.getElementById("t_in").value = (f(t_in.value) * 0.0254).toFixed(4);
    document.getElementById("L_ft").value = (f(L_ft.value) * 0.3048).toFixed(3);
    document.getElementById("v_target").value = (f(v_target.value) * 0.3048).toFixed(2);
    document.getElementById("dP_max").value = (f(dP_max.value) * 6894.76).toFixed(2);
  } else {
    // SI → Imperial
    document.getElementById("a_in").value = (f(a_in.value) / 0.0254).toFixed(3);
    document.getElementById("b_in").value = (f(b_in.value) / 0.0254).toFixed(3);
    document.getElementById("t_in").value = (f(t_in.value) / 0.0254).toFixed(3);
    document.getElementById("L_ft").value = (f(L_ft.value) / 0.3048).toFixed(2);
    document.getElementById("v_target").value = (f(v_target.value) / 0.3048).toFixed(1);
    document.getElementById("dP_max").value = (f(dP_max.value) / 6894.76).toFixed(3);
  }
}

// -----------------------------
// Initialize
// -----------------------------
window.addEventListener("load", fetchResults);
// -----------------------------
// Wavepack Visualization Engine
// -----------------------------

function drawWavepack(result) {
  const svg = document.getElementById("schematic");
  const group = document.getElementById("tubeArray");
  const meta = document.getElementById("meta");
  group.innerHTML = ""; // clear existing

  const nx = result.array_dims[0];
  const ny = result.array_dims[1];
  const a_in = result.a_in;
  const b_in = result.b_in;
  const L_ft = result.L_ft;
  const t_in = result.t_in;
  const color = result.material_color;

  // Geometry scaling and projection parameters
  const scale = 15; // visual scaling factor
  const depth = L_ft * 2; // controls isometric "depth"
  const offsetX = 300;
  const offsetY = 200;

  const maxRender = 50; // cap for browser performance
  const stepX = 1.0, stepY = 1.0;

  const drawCountX = Math.min(nx, maxRender);
  const drawCountY = Math.min(ny, maxRender);

  const tubeOuter = (a_in + 2 * t_in) * scale;
  const tubeInner = a_in * scale;
  const wall = t_in * scale;

  // Create metallic gradient
  let defs = svg.querySelector("defs");
  if (!defs) {
    defs = document.createElementNS("http://www.w3.org/2000/svg", "defs");
    svg.insertBefore(defs, svg.firstChild);
  }
  const grad = document.createElementNS("http://www.w3.org/2000/svg", "linearGradient");
  grad.id = "tubeGrad";
  grad.setAttribute("x1", "0%"); grad.setAttribute("y1", "0%");
  grad.setAttribute("x2", "100%"); grad.setAttribute("y2", "100%");
  const stop1 = document.createElementNS("http://www.w3.org/2000/svg", "stop");
  stop1.setAttribute("offset", "0%");
  stop1.setAttribute("stop-color", color);
  const stop2 = document.createElementNS("http://www.w3.org/2000/svg", "stop");
  stop2.setAttribute("offset", "100%");
  stop2.setAttribute("stop-color", "#222");
  grad.appendChild(stop1);
  grad.appendChild(stop2);
  defs.innerHTML = "";
  defs.appendChild(grad);

  // Draw each tube
  for (let i = 0; i < drawCountX; i++) {
    for (let j = 0; j < drawCountY; j++) {
      const x = offsetX + (i - nx / 2) * (tubeOuter + 2) * stepX - (j * depth * 0.15);
      const y = offsetY + (j - ny / 2) * (tubeOuter + 2) * stepY + (j * depth * 0.08);

      const outer = document.createElementNS("http://www.w3.org/2000/svg", "rect");
      outer.setAttribute("x", x);
      outer.setAttribute("y", y);
      outer.setAttribute("width", tubeOuter);
      outer.setAttribute("height", tubeOuter);
      outer.setAttribute("fill", "url(#tubeGrad)");
      outer.setAttribute("stroke", "#111");
      outer.setAttribute("stroke-width", 0.6);
      group.appendChild(outer);

      const inner = document.createElementNS("http://www.w3.org/2000/svg", "rect");
      inner.setAttribute("x", x + wall);
      inner.setAttribute("y", y + wall);
      inner.setAttribute("width", tubeInner);
      inner.setAttribute("height", tubeInner);
      inner.setAttribute("fill", "#0b1220"); // match background
      group.appendChild(inner);
    }
  }

  // Update meta text
  const dims = `${result.a_in.toFixed(2)} × ${result.b_in.toFixed(2)} in`;
  const w = result.total_weight_lbm.toFixed(1);
  const fc = result.fc_GHz.toFixed(3);
  meta.textContent = `Array: ${nx}×${ny} tubes | Dims: ${dims} | Weight: ${w} lbm | fc=${fc} GHz`;
}
// -----------------------------
// Charting + Output Integration
// -----------------------------

let chartPT = null;
let chartAF = null;

// Update charts with new results
function updateCharts(result) {
  const ctxPT = document.getElementById("chartPT").getContext("2d");
  const ctxAF = document.getElementById("chartAF").getContext("2d");

  // Dummy temperature range (worst-case sweep)
  const temps = [];
  const pVals = [];
  const vVals = [];
  const T_min = -40;
  const T_max = 120;
  for (let T = T_min; T <= T_max; T += 10) {
    const rho = 0.075 * (460 / (T + 460)); // approximate air density change
    const v = result.velocity_fts * (0.075 / rho); // constant flow scaling
    const dp = result.deltaP_psi * (rho / 0.075);
    temps.push(T);
    vVals.push(v);
    pVals.push(dp);
  }

  // Pressure / Velocity vs Temperature
  if (chartPT) chartPT.destroy();
  chartPT = new Chart(ctxPT, {
    type: "line",
    data: {
      labels: temps,
      datasets: [
        {
          label: "Velocity (ft/s)",
          yAxisID: "V",
          data: vVals,
          borderColor: "#39d0ff",
          backgroundColor: "rgba(57,208,255,0.2)",
          tension: 0.25
        },
        {
          label: "ΔP (psi)",
          yAxisID: "P",
          data: pVals,
          borderColor: "#ff9b39",
          backgroundColor: "rgba(255,155,57,0.2)",
          tension: 0.25
        }
      ]
    },
    options: {
      responsive: true,
      scales: {
        x: { title: { display: true, text: "Temperature (°F)" }, grid: { color: "#223" } },
        V: {
          position: "left",
          title: { display: true, text: "Velocity (ft/s)" },
          grid: { color: "#223" }
        },
        P: {
          position: "right",
          title: { display: true, text: "ΔP (psi)" },
          grid: { drawOnChartArea: false }
        }
      },
      plugins: {
        legend: { labels: { color: "#ccc" } },
        tooltip: { mode: "index", intersect: false }
      }
    }
  });

  // Attenuation vs Frequency (log scale)
  const freqs = result.freqs.map(f => f / 1e6); // MHz
  const SE = result.SE_db;

  if (chartAF) chartAF.destroy();
  chartAF = new Chart(ctxAF, {
    type: "line",
    data: {
      labels: freqs,
      datasets: [
        {
          label: "Shielding Effectiveness (dB)",
          data: SE,
          borderColor: "#39ff88",
          backgroundColor: "rgba(57,255,136,0.15)",
          tension: 0.2
        }
      ]
    },
    options: {
      responsive: true,
      scales: {
        x: {
          type: "logarithmic",
          title: { display: true, text: "Frequency (MHz)" },
          grid: { color: "#223" },
          ticks: {
            callback: (val) => val.toLocaleString()
          }
        },
        y: {
          title: { display: true, text: "Attenuation (dB)" },
          grid: { color: "#223" }
        }
      },
      plugins: {
        legend: { labels: { color: "#ccc" } }
      }
    }
  });
}
