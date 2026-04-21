from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st
import altair as alt

try:
    from PIL import Image
except ImportError:
    Image = None

from soiling_models import (
    MONTHS,
    SnowSystemInputs,
    SnowMonthlyInputs,
    DustInputs,
    BifacialRearFactors,
    run_model,
)

st.set_page_config(
    page_title="Solar Snow and Dust Loss Calculator (Townsend Model)",
    page_icon="❄️",
    layout="wide",
)

st.title("Solar Snow and Dust Loss Calculator (Townsend Model)")

# Intro paragraph below title and above image
st.markdown("""
Welcome to the first website where one can directly estimate the monthly photovoltaic (PV) generation lost due to snow using Townsend’s method. Snow on PV will significantly reduce its output, but by how much? This tool calculates that amount. The main influences are the quantity of snow and the tilt angle of the PV array. The calculation also relies on a few additional weather and system geometry inputs; please just follow the guidance on the left side of the page. Townsend’s snow loss equations were developed based on two winters of field measurements done near Lake Tahoe, California from 2009-11. The equation and the losses measured for several tilt angles were published in 2011 at the 37th IEEE PV Specialists Conference in Seattle, WA.
""")
# Hero image
img_candidates = [Path("image_snow_loss.png"), Path("/mnt/data/image_snow_loss.png")]
img_path = next((p for p in img_candidates if p.exists()), None)

caption_text = (
    "Snow accumulation on a south-facing PV array in Nevada City, California, "
    "February 2023. The array was set to a seasonally adjusted tilt of 53° at "
    "the time. Photo by Carl Schori, used with permission."
)

if img_path is not None:
    if Image is not None:
        im = Image.open(img_path)
        st.image(im, use_container_width=True, caption=caption_text)
    else:
        st.image(str(img_path), use_container_width=True, caption=caption_text)

# Remaining explanatory text below image
st.markdown("""
Prior to this webpage, users needed to create an Excel worksheet, obtain a courtesy worksheet from the author, or, since 2023, execute the model through a Python-based implementation that was added to the pvlib platform in 2023. Since its publication in 2011, the equation has been amended slightly to account for a broader amount of PV installation types. For example, bifacial PV is now a major commercial market. Compared to traditional monofacial PV, it will experience less snow loss, owing to its more absorptive and snow-free back side. This webpage allows the user to click a bifacial option. The resulting annual snow loss will typically decrease by a percent or so. Two other features implemented here include guidance for modeling tracking PV, as well as an option to reduce the estimated snow loss by 25% in the instances where multiple paralleled dc source circuits exist in the upslope direction. For example, if modules are oriented in landscape, bypass diodes will gradually restore generation as slow slides down and uncovers the upper portions of a module.

A link to a similar-looking and -functioning webpage is provided below. This option draws directly from the pvlib code and does not allow for the bifacial option to be run. Also, its dust loss component uses a sequence provided by Kajal Sheth, the author of both of these webpages. Results from either version of the offered webpages are likely to be close, and, as the user will see, are functionally nearly identical.

**A key usage tip:** 15 years of experience have shown that reporting the amount of monthly snowfall should be done with an eye on the snowfall measurement method. While not the only way to measure snow, once per day snow depth readings are prone to under-reporting the amount of true snowfall. Feedback suggests the Townsend model tends to be optimistic relative to that predicted by the other prominent snow model from NREL (Marion, 2013, as later amended by Freeman and others). As snow settles, compresses, melts, or evaporates, once per day snow depth readings will suggest less snowfall has occurred than if readings are taken more frequently. The NREL snow model does not consider the quantity of snowfall in its hourly-based loss calculations; rather, it simply compares the 7:00 a.m. snow depth to that of the previous morning as its logic filter for gauging whether the current day should be subject to further snow loss calculations. Once per day readings are probably the most common method of gauging snowfall. However, the author has observed differences approaching 50% between daily snow depth data and the more accurate snowfall recorded via hourly observation or other methods such as sonar or water-equivalent heated sensors. The provisional guidance offered here is to **consider increasing any** ***daily*** **snow depth-based records by 25%**. This will provide results that are in better accordance with the original snowfall records used to create the correlation.

Lastly, this webpage introduces a companion dust loss model, also developed by Townsend. It relies mostly on a series of monthly precipitation inputs. It allows the user to specify whether up to two manual washes per year are to be done (and if so, optimizes when these cleanings should be done). It also allows the user to specify a seasonally-appropriate daily dust build-up rate, with a nominally safe default ramp-up of 0.1%/day. The theory behind the Townsend dust model is available via a pdf link below, as is the theory associated with the snow model.

While the snow and dust models can be run here separately, the main use of either is to provide monthly soiling loss inputs for PVsyst or similar simulation programs. Therefore, it is anticipated that users will benefit from running both models in order to obtain a complete year of monthly inputs for PVsyst. For months in which there may be non-zero losses calculated for both snow and dust, the overlap logic for this webpage’s combined loss tables and graphic assumes a snow loss of 3% or more in any month will render that month’s dust loss to be zero. For transitional months with snow loss less than 3%, the dual losses are combined as a simple overlap equation: Loss = A+B-(A*B), where A and B represent the monthly fractional snow and dust loss.
""")

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

    plot_data = results_plot.melt(
    id_vars="Month",
    var_name="Type",
    value_name="Loss"
    )
    
    chart = alt.Chart(plot_data).mark_line(point=True).encode(
        x="Month",
        y=alt.Y("Loss", title="Loss (%)"),  # ✅ Y-axis label
        color="Type"
    ).properties(
        title="Monthly Snow and Dust Losses"
    )
    
    st.altair_chart(chart, use_container_width=True)

    st.download_button(
        "Download results (CSV)",
        data=results_df.to_csv(index=False).encode("utf-8"),
        file_name="townsend_snow_dust_results.csv",
        mime="text/csv",
        use_container_width=True,
    )
st.divider()
st.subheader("📄 Technical Documentation")

st.markdown(
    """
Download the technical documentation for Townsend’s monthly snow loss model, which includes its equations and descriptions of key aspects such as ground interference, guidance for tracking systems, bifacial applications, and the multiple parallel string factor.
"""
) 
pdf_path = Path(__file__).parent / "SnowModelTheory.pdf"

if pdf_path.exists():
    with open(pdf_path, "rb") as f:
        st.download_button(
            label="Download Snow Model Theory (PDF)",
            data=f,
            file_name="SnowModelTheory.pdf",
            mime="application/pdf"
        )
else:
    st.warning("SnowModelTheory.pdf was not found in the deployed app folder.")

pdf_candidates = [
    Path("DustModelTheory.pdf"),
    Path("/mnt/data/DustModelTheory.pdf"),
]

pdf_path = next((p for p in pdf_candidates if p.exists()), None)

if pdf_path is not None:
    st.markdown("Download the technical documentation for Townsend’s monthly dust loss model, which describes the model's rules, inputs, seasonal ramp rates, wash optimization logic, and its application to bifacial PV.")

    with open(pdf_path, "rb") as f:
        pdf_bytes = f.read()

    st.download_button(
        label="Download Dust Model Theory (PDF)",
        data=pdf_bytes,
        file_name=pdf_path.name,
        mime="application/pdf",
    )
else:
    st.warning("Dust model theory PDF is not available in the app folder.")
    
st.markdown("### Related Tool")
st.markdown(
    "Reference non-bifacial calculator: "
    "[PV Snow & Soiling Loss Calculator](https://pv-snow-soiling-losses.streamlit.app/)"
)
st.markdown("### References")

st.markdown("""
1. Townsend, Tim & Powers, Loren. (2011). *Photovoltaics and snow: An update from two winters of measurements in the SIERRA.* 37th IEEE Photovoltaic Specialists Conference, Seattle, WA, USA. DOI: 10.1109/PVSC.2011.6186627

2. Townsend, T. and Previtali, J. (2023). *A Fresh Dusting: Current Uses of the Townsend Snow Model.* In “Photovoltaic Reliability Workshop (PVRW) 2023 Proceedings: Posters.”, ed. Silverman, T. J. Dec. 2023. NREL/CP-5900-87918. Available at: https://docs.nlr.gov/docs/fy24osti/87918.pdf

3. Townsend, T. (2013). *Predicting PV Energy Loss Caused by Snow.* Solar Power International, Chicago IL. DOI: 10.13140/RG.2.2.14299.68647
""")
st.markdown('<p class="attrib">This webpage was created by <b>Sheth Kajal</b> 😊</p>',
            unsafe_allow_html=True)
