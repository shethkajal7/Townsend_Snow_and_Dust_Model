from __future__ import annotations

import pandas as pd
import streamlit as st

st.set_page_config(page_title="Solar Snow and Dust Loss Calculator (Townsend Model)", page_icon="❄️", layout="wide")

st.title("Solar Snow and Dust Loss Calculator (Townsend Model)")
# --- Hero image (half size) just below the title ---
from pathlib import Path
try:
    from PIL import Image
except ImportError:
    Image = None

img_candidates = [Path("image_snow_loss.png"), Path("/mnt/data/image_snow_loss.png")]
img_path = next((p for p in img_candidates if p.exists()), None)
if img_path is not None:
    if Image is not None:
        im = Image.open(img_path)
        st.image(im, width=max(300, im.width // 2))  # half width with a sensible minimum
    else:
        st.image(str(img_path), width=600)  # fallback width
        # --- Subtitle (combined) ---
st.markdown(
    "_Townsend snow loss (via pvlib) + precipitation-aware soiling model using monthly "
    "climate inputs (manual-clean option); month-by-month results to support EPC yield "
    "estimates and O&M cleaning plans._"

)
# --- Transition text ---
st.markdown(
    "Flat “2% soiling” assumptions hide seasonal risk and can distort both EPC yield models "
    "and O&M decisions. Soiling is dynamic and seasonal; losses during high-irradiance months "
    "hit hardest, and the right cleaning cadence balances cost against energy recovery. Use the "
    "tool below to convert those principles into numbers: it applies pvlib’s Townsend snow model and "
    "a simple precipitation-aware soiling progression (with a manual-clean toggle) to produce stacked "
    "monthly loss percentages one can use in EPC financials and O&M planning."
)
with st.sidebar:

    st.header("📘How to use this webpage")

    st.markdown("""
    1. Enter **snow system inputs** such as tilt, row length, drop height, and module type.

    2. Select **monthly data availability** such as snowfall events and humidity.

    3. Enable **optional inputs** only if you have that data.

    4. Enter **dust inputs** including ramp rate category and number of washes.

    5. Fill the **monthly table** for all 12 months.

    6. Click **Run model** to calculate snow loss, dust loss, and combined loss.

    7. Review the **outputs, plots, and CSV download** below.
    """)

    st.divider()

    st.header("Snow system inputs")
from soiling_models import (
    MONTHS,
    SnowSystemInputs,
    SnowMonthlyInputs,
    DustInputs,
    BifacialRearFactors,
    run_model,
)

st.set_page_config(page_title="Townsend Snow + Dust Model", layout="wide")
st.title("Townsend Snow + Dust Model")

with st.sidebar:
    st.header("Snow system inputs")

    tilt_deg = st.number_input("Tilt T (deg)", value=30.0, step=0.5)
    row_length_in = st.number_input("Row length R (in)", value=118.0, step=1.0)
    drop_height_in = st.number_input("Drop height H (in)", value=36.0, step=1.0)

    pileup_angle_deg = st.number_input(
        "Pileup angle P (deg)",
        value=40.0,
        step=1.0,
        help="Leave at 40 unless you have special knowledge of snow moisture and structure for your site.",
    )

    M = st.radio("M (multiple-string factor)", options=[0.75, 1.0], horizontal=True, index=0)
    bifacial = st.radio("Bifacial?", options=["NO", "YES"], horizontal=True, index=1) == "YES"
    snow_units = st.radio("Snow units", options=["in", "mm"], horizontal=True, index=0)

    st.divider()
    st.header("Monthly input availability")

    events_have_ge1 = st.radio(
        'Do you have the number of days with at least 1" (25 mm) snow ?',
        options=["YES", "NO (I only have all snow events)"],
        index=0,
    )
    rh_mode = st.radio(
        "Relative humidity input type",
        options=["All-day average", "AM and PM values"],
        index=0,
    )

    st.divider()
    st.header("Optional POA/energy inputs")

    st.write("Only enable these if you actually have the data.")
    have_albedo = st.checkbox("I can provide monthly Albedo", value=False)
    have_back_poa = st.checkbox("I can provide monthly Back POA", value=False)
    have_mwh = st.checkbox("I can provide monthly Front and Back MWh (clean array)", value=False)

    st.divider()
    st.header("Dust inputs")

    precip_units = st.radio("Precipitation units", options=["in", "mm"], horizontal=True, index=0)

    manual_washes = st.radio("Manual washes per year", options=[0, 1, 2], horizontal=True, index=0)

    st.subheader("Ramp rate (%/day) by season")
    st.caption(
        "Choose one of the standard ramp-rate categories only. "
        "Summer tends to be worst."
    )
    
    RAMP_RATE_OPTIONS = {
        "Typical (0.10)": 0.10,
        "Ultra sandy (0.025)": 0.025,
        "Desert (0.05)": 0.05,
        "Humid/agri./sooty/birds (0.15)": 0.15,
    }
    
    ramp_dec_feb = RAMP_RATE_OPTIONS[
        st.selectbox("Dec–Feb", options=list(RAMP_RATE_OPTIONS.keys()), index=0)
    ]
    ramp_mar_may = RAMP_RATE_OPTIONS[
        st.selectbox("Mar–May", options=list(RAMP_RATE_OPTIONS.keys()), index=0)
    ]
    ramp_jun_aug = RAMP_RATE_OPTIONS[
        st.selectbox("Jun–Aug", options=list(RAMP_RATE_OPTIONS.keys()), index=0)
    ]
    ramp_sep_nov = RAMP_RATE_OPTIONS[
        st.selectbox("Sep–Nov", options=list(RAMP_RATE_OPTIONS.keys()), index=0)
    ]

    rear = None
    if bifacial:
        st.divider()
        st.header("Bifacial rear-side factors")
        bf = st.number_input("Bifaciality factor", value=0.65, step=0.01, format="%.3f")
        rs = st.number_input("Rear shading", value=0.125, step=0.005, format="%.3f")
        rm = st.number_input("Rear mismatch", value=0.024, step=0.002, format="%.3f")
        rear = BifacialRearFactors(bifaciality_factor=bf, rear_shading=rs, rear_mismatch=rm)

st.markdown("## Monthly inputs")

# Default template values (these are safe placeholders)
df = pd.DataFrame({"Month": MONTHS})
df["Avg Temp (°C)"] = [-9.6, -6.9, 3.3, 7.5, 16.2, 19.3, 23.0, 21.1, 15.0, 8.2, 1.4, -6.8]
df[f"Snowfall ({snow_units})"] = [12.9, 10.6, 7.0, 2.6, 0.2, 0.0, 0.0, 0.0, 0.0, 0.5, 3.6, 13.5]
df["Front POA (kWh/m²/mo)"] = [94.4, 106.3, 135.3, 153.1, 182.8, 189.3, 190.2, 178.4, 146.2, 115.9, 79.4, 78.2]
df["Precip"] = [4.0, 2.0, 1.5, 1.0, 0.2, 0.1, 0.1, 0.1, 0.3, 2.0, 2.1, 2.5]

# Events columns
if events_have_ge1.startswith("YES"):
    df['No of days with at least 1" of snow'] = [3.6, 3.2, 2.0, 0.7, 0.1, 0.0, 0.0, 0.0, 0.0, 0.1, 1.2, 3.8]
else:
    df["All snow events (any depth)"] = [None] * 12

# RH columns
if rh_mode == "All-day average":
    df["RH all-day (%)"] = [75.0, 74.5, 73.0, 69.5, 69.5, 72.0, 74.5, 78.5, 79.0, 74.5, 76.5, 77.5]
else:
    df["RH AM (%)"] = [75.0] * 12
    df["RH PM (%)"] = [None] * 12

# Optional columns
if have_albedo:
    df["Albedo"] = [None] * 12
if bifacial and have_back_poa:
    df["Back POA (kWh/m²/mo)"] = [None] * 12
if have_mwh:
    df["Front MWh (optional)"] = [None] * 12
    df["Back MWh (optional)"] = ([None] * 12) if bifacial else ([0.0] * 12)

edited = st.data_editor(df, use_container_width=True, hide_index=True, num_rows="fixed", height=460)

run = st.button("Run model", type="primary", use_container_width=True)

if run:
    sys = SnowSystemInputs(
        tilt_deg=float(tilt_deg),
        row_length_in=float(row_length_in),
        drop_height_in=float(drop_height_in),
        pileup_angle_deg=float(pileup_angle_deg),
        M=float(M),
        bifacial=bool(bifacial),
    )

    # Build monthly inputs
    avg_temp = edited["Avg Temp (°C)"].astype(float).tolist()
    snow_depth = edited[f"Snowfall ({snow_units})"].astype(float).tolist()
    front_poa = edited["Front POA (kWh/m²/mo)"].astype(float).tolist()

    # Events
    snow_events_ge_1in = None
    snow_events_any = None
    if events_have_ge1.startswith("YES"):
        snow_events_ge_1in = edited['No of days with at least 1" of snow'].astype(float).tolist()
    else:
        # allow blanks, but require numbers at runtime
        vals = edited["All snow events (any depth)"].tolist()
        if any(v is None or (isinstance(v, float) and pd.isna(v)) for v in vals):
            st.error("You selected all-events mode, please fill all 12 values in 'All snow events (any depth)'.")
            st.stop()
        snow_events_any = [float(v) for v in vals]

    # RH
    rh_all_day = rh_am = rh_pm = None
    if rh_mode == "All-day average":
        rh_all_day = edited["RH all-day (%)"].astype(float).tolist()
    else:
        rh_am = edited["RH AM (%)"].astype(float).tolist()
        # PM can contain blanks, treat blank as missing
        rh_pm_raw = edited["RH PM (%)"].tolist()
        rh_pm = [None if v is None or (isinstance(v, float) and pd.isna(v)) else float(v) for v in rh_pm_raw]

    # Optional albedo/back POA/MWh
    albedo = None
    back_poa = None
    front_mwh = None
    back_mwh = None

    if have_albedo:
        alb_raw = edited["Albedo"].tolist()
        albedo = [None if v is None or (isinstance(v, float) and pd.isna(v)) else float(v) for v in alb_raw]

    if bifacial and have_back_poa:
        bp_raw = edited["Back POA (kWh/m²/mo)"].tolist()
        back_poa = [None if v is None or (isinstance(v, float) and pd.isna(v)) else float(v) for v in bp_raw]

    if have_mwh:
        fm_raw = edited["Front MWh (optional)"].tolist()
        front_mwh = [None if v is None or (isinstance(v, float) and pd.isna(v)) else float(v) for v in fm_raw]

        if bifacial:
            bm_raw = edited["Back MWh (optional)"].tolist()
            back_mwh = [None if v is None or (isinstance(v, float) and pd.isna(v)) else float(v) for v in bm_raw]
        else:
            back_mwh = [0.0] * 12

    monthly = SnowMonthlyInputs(
        avg_temp_c=avg_temp,
        snow_depth=snow_depth,
        snow_units=snow_units,
        snow_events_ge_1in=snow_events_ge_1in,
        snow_events_any=snow_events_any,
        rh_all_day=rh_all_day,
        rh_am=rh_am,
        rh_pm=rh_pm,
        front_poa=front_poa,
        albedo=albedo,
        back_poa=back_poa,
        front_mwh=front_mwh,
        back_mwh=back_mwh,
    )

    # Dust inputs
    precip = edited["Precip"].astype(float).tolist()
    dust = DustInputs(
        precip=precip,
        precip_units=precip_units,
        ramp_dec_feb=float(ramp_dec_feb),
        ramp_mar_may=float(ramp_mar_may),
        ramp_jun_aug=float(ramp_jun_aug),
        ramp_sep_nov=float(ramp_sep_nov),
        manual_washes=int(manual_washes),
    )

    try:
        out = run_model(sys=sys, monthly=monthly, dust=dust, rear=rear)
    except Exception as e:
        st.error(str(e))
        st.stop()

    # Results table (rounded to 1 decimal)
    results_df = pd.DataFrame({
        "Month": MONTHS,
        "Snow loss (%)": [round(v, 1) for v in out.snow_loss_pct],
        "Dust loss (%)": [round(v, 1) for v in out.dust_loss_pct],
        "Combined soiling loss (%)": [round(v, 1) for v in out.combined_loss_pct],
    })

    st.success("Model ran successfully.")

    # Best wash months
    if int(manual_washes) == 0:
        st.info("Manual washes: None")
    else:
        b1 = "None" if out.best_wash_month_1 is None else f"{out.best_wash_month_1} ({MONTHS[out.best_wash_month_1-1]})"
        b2 = "None" if out.best_wash_month_2 is None else f"{out.best_wash_month_2} ({MONTHS[out.best_wash_month_2-1]})"
        st.info(f"Best wash month #1: {b1}")
        if int(manual_washes) == 2:
            st.info(f"Best wash month #2: {b2}")

    st.markdown("## Outputs")

    st.write(f"Approx. annual snow loss: {out.annual_snow_loss_pct:.1f}%")
    st.write(f"Approx. annual dust loss: {out.annual_dust_loss_pct:.1f}%")
    st.write(f"Approx. annual combined soiling loss: {out.annual_combined_loss_pct:.1f}%")

    st.dataframe(results_df.style.format({
        "Snow loss (%)": "{:.1f}",
        "Dust loss (%)": "{:.1f}",
        "Combined soiling loss (%)": "{:.1f}",
    }), use_container_width=True, hide_index=True, height=460)

    # Ensure calendar order Jan → Dec for plotting
    month_order = ["Jan","Feb","Mar","Apr","May","Jun",
                "Jul","Aug","Sep","Oct","Nov","Dec"]

    results_plot = results_df.copy()
    results_plot["Month"] = pd.Categorical(
        results_plot["Month"],
        categories=month_order,
        ordered=True,
    )
    results_plot = results_plot.sort_values("Month")

    st.line_chart(
        results_plot.set_index("Month")[
            ["Snow loss (%)", "Dust loss (%)", "Combined soiling loss (%)"]
        ]
    )

    st.download_button(
        "Download results (CSV)",
        data=results_df.to_csv(index=False).encode("utf-8"),
        file_name="townsend_snow_dust_results.csv",
        mime="text/csv",
        use_container_width=True,
    )
st.markdown("### References")

st.markdown("""
1. Townsend, Tim & Powers, Loren. (2011). *Photovoltaics and snow: An update from two winters of measurements in the SIERRA.* 37th IEEE Photovoltaic Specialists Conference, Seattle, WA, USA. DOI: 10.1109/PVSC.2011.6186627

2. Townsend, T. and Previtali, J. (2023). *A Fresh Dusting: Current Uses of the Townsend Snow Model.* In “Photovoltaic Reliability Workshop (PVRW) 2023 Proceedings: Posters.”, ed. Silverman, T. J. Dec. 2023. NREL/CP-5900-87918. Available at: https://docs.nlr.gov/docs/fy24osti/87918.pdf

3. Townsend, T. (2013). *Predicting PV Energy Loss Caused by Snow.* Solar Power International, Chicago IL. DOI: 10.13140/RG.2.2.14299.68647
""")
st.markdown('<p class="attrib">This webpage was created by <b>Sheth Kajal</b> 😊</p>',
            unsafe_allow_html=True)
