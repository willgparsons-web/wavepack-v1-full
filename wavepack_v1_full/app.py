from flask import Flask, render_template, request, jsonify, send_file
import math, io, datetime, base64
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas

app = Flask(__name__, static_url_path="/static", static_folder="static", template_folder="templates")

# ------------------------------
# CONSTANTS
# ------------------------------
C0 = 299792458.0  # speed of light (m/s)
G = 9.80665        # gravity (m/s²)
PI = math.pi

# ------------------------------
# UNIT CONVERSIONS
# ------------------------------
def in_to_m(x): return x * 0.0254
def ft_to_m(x): return x * 0.3048
def psi_to_pa(x): return x * 6894.757
def pa_to_psi(x): return x / 6894.757
def cfm_to_m3s(x): return x * 0.00047194745
def m3s_to_cfm(x): return x / 0.00047194745
def lbft3_to_kgm3(x): return x * 16.0185
def kgm3_to_lbft3(x): return x / 16.0185

def F_to_C(F): return (F - 32.0) * 5.0 / 9.0
def C_to_F(C): return C * 9.0 / 5.0 + 32.0
def F_to_K(F): return F_to_C(F) + 273.15

# ------------------------------
# MATERIAL PROPERTIES (for weight & roughness)
# ------------------------------
MATERIALS = {
    "stainless_304": {"name": "Stainless 304", "density_lbft3": 499.0, "roughness_ft": 5e-6, "color": "#C0C0C0"},
    "aluminum_6061": {"name": "Aluminum 6061-T6", "density_lbft3": 169.0, "roughness_ft": 1.5e-6, "color": "#A9C0DE"},
    "copper_c110": {"name": "Copper C110", "density_lbft3": 559.0, "roughness_ft": 1.2e-6, "color": "#B87333"},
    "brass_c360": {"name": "Brass C360", "density_lbft3": 532.0, "roughness_ft": 1.8e-6, "color": "#D4AF37"},
    "carbon_steel": {"name": "Carbon Steel", "density_lbft3": 490.0, "roughness_ft": 7e-6, "color": "#6E7074"}
}

# ------------------------------
# FLUID PROPERTIES
# Density (kg/m³) and dynamic viscosity (Pa·s) tables vs. temperature
# ------------------------------
def air_props(T_F):
    T_K = F_to_K(T_F)
    p = 101325
    R = 287.05
    rho = p / (R * T_K)
    mu = 1.458e-6 * T_K ** 1.5 / (T_K + 110.4)
    return rho, mu

def water_props(T_F):
    T_C = F_to_C(T_F)
    rho = 999.84 - 0.07 * (T_C - 4.0) ** 2
    mu = 0.001 * (1 + 0.0337 * (T_C - 20) + 0.00022 * (T_C - 20) ** 2)
    return rho, mu

def diesel_props(T_F):
    T_C = F_to_C(T_F)
    rho = 830 - 0.6 * (T_C - 15)
    mu = 0.0025 * math.exp(-0.02 * (T_C - 20))
    return rho, mu

def oil_iso46_props(T_F):
    T_C = F_to_C(T_F)
    rho = 870 - 0.65 * (T_C - 15)
    mu = 0.041 * math.exp(-0.045 * (T_C - 40))
    return rho, mu

def hydrogen_props(T_F):
    T_K = F_to_K(T_F)
    rho = 0.0899 * (273.15 / T_K)
    mu = 8.76e-6 * (T_K / 300) ** 0.7
    return rho, mu

def nitrogen_props(T_F):
    T_K = F_to_K(T_F)
    rho = 1.25 * (273.15 / T_K)
    mu = 1.76e-5 * (T_K / 300) ** 0.7
    return rho, mu

def glycol_props(T_F):
    T_C = F_to_C(T_F)
    rho = 1110 - 0.7 * (T_C - 20)
    mu = 0.015 * math.exp(-0.04 * (T_C - 20))
    return rho, mu

FLUIDS = {
    "air": {"name": "Air", "func": air_props},
    "water": {"name": "Water", "func": water_props},
    "diesel": {"name": "Diesel", "func": diesel_props},
    "oil_iso46": {"name": "Hydraulic Oil (ISO VG 46)", "func": oil_iso46_props},
    "hydrogen": {"name": "Hydrogen", "func": hydrogen_props},
    "nitrogen": {"name": "Nitrogen", "func": nitrogen_props},
    "glycol": {"name": "Ethylene Glycol", "func": glycol_props},
}
# ------------------------------
# FLOW PHYSICS FUNCTIONS
# ------------------------------

def hydraulic_diameter_rect(a_m, b_m):
    """Hydraulic diameter for rectangular duct (used for Re & f)."""
    return 2.0 * a_m * b_m / (a_m + b_m)

def reynolds_number(rho, v, Dh, mu):
    """Calculate Reynolds number."""
    return (rho * v * Dh) / mu

def colebrook_white(Re, rel_rough):
    """Colebrook-White friction factor using Haaland approximation."""
    if Re <= 0: 
        return 0.02
    if Re < 2300: 
        return 64.0 / Re  # laminar flow
    # turbulent regime
    return ( -1.8 * math.log10( (rel_rough / 3.7)**1.11 + 6.9/Re ) ) ** -2

def darcy_delta_p(f, L_m, Dh_m, rho, v):
    """Pressure loss (Pa) via Darcy–Weisbach."""
    return f * (L_m / Dh_m) * (rho * v**2 / 2.0)

def cutoff_frequency_rect(a_m):
    """Rectangular TE10 cutoff frequency (Hz)."""
    return C0 / (2.0 * a_m)

def se_below_cutoff_db(a_m, L_m, f_hz):
    """Shielding effectiveness below cutoff (attenuation)."""
    fc = cutoff_frequency_rect(a_m)
    if f_hz >= fc:
        return 0.0
    kc = 2.0 * math.pi * fc / C0
    k = 2.0 * math.pi * f_hz / C0
    alpha = math.sqrt(max(kc**2 - k**2, 0.0))
    return 8.686 * alpha * L_m  # in dB

def tube_weight_lbm(a_in, b_in, t_in, L_ft, material):
    """Estimate tube weight using wall volume × density."""
    a_out_in = a_in + 2*t_in
    b_out_in = b_in + 2*t_in
    A_out_ft2 = (a_out_in/12.0)*(b_out_in/12.0)
    A_in_ft2 = (a_in/12.0)*(b_in/12.0)
    wall_area = max(0.0, A_out_ft2 - A_in_ft2)
    vol_ft3 = wall_area * L_ft
    rho = MATERIALS[material]["density_lbft3"]
    return vol_ft3 * rho

# ------------------------------
# AUTO TUBE SOLVER
# ------------------------------

def solve_tube_count(payload):
    """
    Automatically determine tube count that satisfies velocity and ΔP constraints.
    Rounds up to the nearest full rectangular (n×m) array.
    """
    # Extract inputs
    a_in = float(payload.get("a_in", 2.0))
    b_in = float(payload.get("b_in", a_in))
    L_ft = float(payload.get("L_ft", 3.0))
    t_in = float(payload.get("t_in", 0.125))
    cfm_total = float(payload.get("cfm", 100.0))
    Tmax_F = float(payload.get("Tmax_F", 100.0))
    fluid = payload.get("fluid", "air")
    material = payload.get("material", "stainless_304")
    v_target = float(payload.get("v_target", 200.0))  # ft/s
    dP_max_psi = float(payload.get("dP_max", 1.0))    # psi

    # Convert key units
    a_m, b_m, L_m = in_to_m(a_in), in_to_m(b_in), ft_to_m(L_ft)
    rho, mu = FLUIDS[fluid]["func"](Tmax_F)
    rho_lbft3 = kgm3_to_lbft3(rho)

    # Derived geometry
    Dh_m = hydraulic_diameter_rect(a_m, b_m)
    A_inner_m2 = a_m * b_m
    rel_rough = (MATERIALS[material]["roughness_ft"] * 0.3048) / Dh_m

    # Start iterating tube count
    tube_count = 1
    meets = False
    best_dp = 0.0
    best_v = 0.0

    while tube_count <= 2500:  # hard cap
        Q_m3s_each = cfm_to_m3s(cfm_total / tube_count)
        v = Q_m3s_each / A_inner_m2
        Re = reynolds_number(rho, v, Dh_m, mu)
        f = colebrook_white(Re, rel_rough)
        dP_pa = darcy_delta_p(f, L_m, Dh_m, rho, v)
        dP_psi = pa_to_psi(dP_pa)

        # Check constraints
        if v <= ft_to_m(v_target) and dP_psi <= dP_max_psi:
            meets = True
            best_dp, best_v = dP_psi, v
            break
        tube_count += 1

    # Round to full rectangular array
    n = math.ceil(math.sqrt(tube_count))
    m = math.ceil(tube_count / n)
    rounded_count = n * m

    per_tube_wt = tube_weight_lbm(a_in, b_in, t_in, L_ft, material)
    total_weight = per_tube_wt * rounded_count

    # Attenuation vs frequency
    freqs = [10**(5 + j*(5/100)) for j in range(101)]
    SE_db = [se_below_cutoff_db(max(a_m,b_m), L_m, f) for f in freqs]
    fc_hz = cutoff_frequency_rect(max(a_m,b_m))

    return {
        "tube_count": rounded_count,
        "array_dims": [n, m],
        "velocity_fts": best_v / 0.3048,
        "deltaP_psi": best_dp,
        "total_weight_lbm": total_weight,
        "Dh_in": Dh_m / 0.0254,
        "fc_GHz": fc_hz / 1e9,
        "freqs": freqs,
        "SE_db": SE_db,
        "material_color": MATERIALS[material]["color"],
        "a_in": a_in,
        "b_in": b_in,
        "L_ft": L_ft,
        "t_in": t_in
    }
# ------------------------------
# FLASK ROUTES
# ------------------------------

@app.route("/")
def index():
    """Render main interface."""
    return render_template("index.html", materials=MATERIALS, fluids=FLUIDS)

@app.route("/calculate", methods=["POST"])
def calculate():
    """Perform waveguide calculation and return JSON results."""
    payload = request.get_json(force=True)
    result = solve_tube_count(payload)
    return jsonify(result)

@app.route("/report", methods=["POST"])
def report():
    """Generate PDF report and send it to browser."""
    payload = request.get_json(force=True)
    result = solve_tube_count(payload)

    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter

    # --- Header ---
    c.setFont("Helvetica-Bold", 16)
    c.drawString(72, height - 72, "Wave Pack Analysis Report")
    c.setFont("Helvetica", 10)
    c.drawString(72, height - 90, f"Generated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # --- Inputs ---
    c.setFont("Helvetica-Bold", 12)
    c.drawString(72, height - 120, "Input Parameters")
    c.setFont("Helvetica", 10)
    y = height - 135
    for k, v in [
        ("Shape", "Rectangular"),
        ("Material", MATERIALS[payload['material']]['name']),
        ("Fluid", FLUIDS[payload['fluid']]['name']),
        ("Dimensions (in)", f"A={result['a_in']:.3f}, B={result['b_in']:.3f}, t={result['t_in']:.3f}"),
        ("Length (ft)", f"{result['L_ft']:.2f}"),
        ("Flow Rate (CFM)", f"{payload['cfm']:.1f}"),
        ("Target Velocity (ft/s)", f"{payload['v_target']}"),
        ("Max ΔP (psi)", f"{payload['dP_max']}")
    ]:
        c.drawString(90, y, f"{k}: {v}")
        y -= 14

    # --- Results ---
    y -= 10
    c.setFont("Helvetica-Bold", 12)
    c.drawString(72, y, "Computed Results")
    y -= 15
    c.setFont("Helvetica", 10)
    for k, v in [
        ("Tube Count", f"{result['tube_count']}  ({result['array_dims'][0]}x{result['array_dims'][1]})"),
        ("Velocity (ft/s)", f"{result['velocity_fts']:.2f}"),
        ("ΔP (psi)", f"{result['deltaP_psi']:.3f}"),
        ("Weight (lbm)", f"{result['total_weight_lbm']:.2f}"),
        ("Hydraulic Diameter (in)", f"{result['Dh_in']:.3f}"),
        ("Cutoff Frequency (GHz)", f"{result['fc_GHz']:.3f}")
    ]:
        c.drawString(90, y, f"{k}: {v}")
        y -= 14

    # --- Notes ---
    y -= 10
    c.setFont("Helvetica-Oblique", 9)
    c.drawString(72, y, "Note: Results computed for worst-case (max temperature) flow condition.")

    c.showPage()
    c.save()
    buffer.seek(0)

    return send_file(buffer, as_attachment=True, download_name="Wavepack_Report.pdf", mimetype="application/pdf")

# ------------------------------
# MAIN SERVER LAUNCH
# ------------------------------
if __name__ == "__main__":
    import os
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)
