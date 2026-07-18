from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Optional

import altair as alt
import pandas as pd
import streamlit as st

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    Image = None

from soiling_models import (
    MONTHS,
    BifacialRearFactors,
    DustInputs,
    ModelOutputs,
    SnowMonthlyInputs,
    SnowSystemInputs,
    run_model,
)


APP_DIR = Path(__file__).resolve().parent
DEFAULT_TEMPERATURES = [7.0, 10.0, 10.0, 14.0, 17.0, 18.0, 20.0, 23.0, 21.0, 17.0, 11.0, 7.0]
DEFAULT_RH = [89.0, 80.0, 71.0, 63.0, 55.0, 52.0, 52.0, 54.0, 56.0, 61.0, 78.0, 86.0]
DEFAULT_FRONT_POA = [81.0, 114.0, 161.0, 193.0, 221.0, 220.0, 236.0, 232.0, 208.0, 171.0, 105.0, 80.0]
DEFAULT_PRECIP = [3.8, 4.0, 2.8, 1.2, 0.6, 0.05, 0.05, 0.05, 0.05, 0.9, 2.4, 3.5]


def excel_round(value: float, ndigits: int = 1) -> float:
    """Use Excel-style half-up rounding for report displays."""
    quantum = Decimal("1").scaleb(-ndigits)
    return float(Decimal(str(float(value))).quantize(quantum, rounding=ROUND_HALF_UP))


def default_monthly_table() -> pd.DataFrame:
    """Return the yellow monthly input cells from the attached workbook."""
    blank = [float("nan")] * 12
    return pd.DataFrame(
        {
            "Month": MONTHS,
            "Avg Temp (°C)": DEFAULT_TEMPERATURES,
            "Snowfall": blank,
            'Snow events ≥1 in': blank,
            "All snow events": blank,
            "RH primary (%)": DEFAULT_RH,
            "RH PM (%)": blank,
            "Front POA (kWh/m²/mo)": DEFAULT_FRONT_POA,
            "Albedo optional": blank,
            "Back POA optional": blank,
            "Front MWh optional": blank,
            "Back MWh optional": blank,
            "Precipitation": DEFAULT_PRECIP,
        }
    )


def optional_float(value: Any) -> Optional[float]:
    if value is None or pd.isna(value):
        return None
    return float(value)


def optional_column(frame: pd.DataFrame, column: str) -> list[Optional[float]]:
    return [optional_float(value) for value in frame[column].tolist()]


def required_column(frame: pd.DataFrame, column: str) -> list[float]:
    values = optional_column(frame, column)
    missing = [MONTHS[index] for index, value in enumerate(values) if value is None]
    if missing:
        raise ValueError(f"{column} is blank for: {', '.join(missing)}.")
    return [float(value) for value in values if value is not None]


def month_name(month_number: Optional[int]) -> str:
    if month_number is None:
        return "None"
    return f"{month_number} ({MONTHS[month_number - 1]})"


def make_output_tables(out: ModelOutputs) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    report = pd.DataFrame(
        {
            "Result": ["Monthly Snow Loss", "Monthly Dust Loss", "Total Soiling Loss"],
            **{
                month: [
                    excel_round(out.snow_loss_pct[index], 1),
                    excel_round(out.dust_loss_pct[index], 1),
                    excel_round(out.combined_loss_pct[index], 1),
                ]
                for index, month in enumerate(MONTHS)
            },
            "Annual": [
                excel_round(out.annual_snow_loss_pct, 1),
                excel_round(out.annual_dust_loss_pct, 1),
                excel_round(out.annual_combined_loss_pct, 1),
            ],
        }
    )

    monthly = pd.DataFrame(
        {
            "Month": MONTHS,
            "Snow loss (%)": out.snow_loss_pct,
            "Dust loss (%)": out.dust_loss_pct,
            "Combined loss (%)": out.combined_loss_pct,
            "No-wash dust (%)": out.dust_no_wash_pct,
            "1-wash dust (%)": out.dust_one_wash_pct,
            "2-wash dust (%)": out.dust_two_wash_pct,
            "Energy weight (%)": [value * 100.0 for value in out.energy_weights],
        }
    )

    details = pd.DataFrame(
        {
            "Month": MONTHS,
            "Raw snow loss (%)": out.snow_loss_raw_pct,
            "Reported snow loss (%)": out.snow_loss_pct,
            "Estimated albedo": out.estimated_albedo,
            "Calculated back POA": out.calculated_back_poa,
            "Monofacial fraction": out.monofacial_fraction,
            "Energy proxy": out.monthly_energy_proxy,
            "Module temperature (°C)": out.module_temperature_c,
            "Temperature adjustment": out.temperature_adjustment,
            "Energy weight": out.energy_weights,
            "Dust month type": out.dust_month_type,
            "Dust increment (%)": out.dust_increment_pct,
            "Dust fixed value (%)": out.dust_fixed_pct,
            "Wash-month residual (%)": out.manual_wash_month_residual_pct,
        }
    )
    return report, monthly, details


def combined_loss_chart(out: ModelOutputs) -> alt.Chart:
    chart_frame = pd.DataFrame(
        {
            "Month": MONTHS * 3,
            "Series": (
                ["Monthly Snow"] * 12
                + ["Monthly Dust"] * 12
                + ["Total Soiling"] * 12
            ),
            "Loss (%)": out.snow_loss_pct + out.dust_loss_pct + out.combined_loss_pct,
        }
    )
    return (
        alt.Chart(chart_frame)
        .mark_line(strokeWidth=2.5)
        .encode(
            x=alt.X("Month:N", sort=MONTHS, title=None),
            y=alt.Y("Loss (%):Q", title="Monthly Loss (%)", scale=alt.Scale(zero=True)),
            color=alt.Color(
                "Series:N",
                title=None,
                scale=alt.Scale(
                    domain=["Monthly Snow", "Monthly Dust", "Total Soiling"],
                    range=["#4472C4", "#A05A2C", "#ED7D31"],
                ),
                legend=alt.Legend(orient="bottom", direction="horizontal"),
            ),
            tooltip=["Month:N", "Series:N", alt.Tooltip("Loss (%):Q", format=".3f")],
        )
        .properties(title="Monthly Snow and Dust Losses", height=390)
    )


def dust_profiles_chart(out: ModelOutputs) -> alt.LayerChart:
    profiles = {
        "No wash": (out.dust_no_wash_pct, out.annual_dust_no_wash_pct),
        "1 wash": (out.dust_one_wash_pct, out.annual_dust_one_wash_pct),
        "2 wash": (out.dust_two_wash_pct, out.annual_dust_two_wash_pct),
    }
    line_rows: list[dict[str, Any]] = []
    annual_rows: list[dict[str, Any]] = []
    for profile_name, (monthly_values, annual_value) in profiles.items():
        for month, value in zip(MONTHS, monthly_values):
            line_rows.append({"Period": month, "Profile": profile_name, "Dust loss (%)": value})
        annual_rows.append({"Period": "Ann.", "Profile": profile_name, "Dust loss (%)": annual_value})

    color = alt.Color(
        "Profile:N",
        title=None,
        scale=alt.Scale(
            domain=["No wash", "1 wash", "2 wash"],
            range=["#4472C4", "#ED7D31", "#70AD47"],
        ),
        legend=alt.Legend(orient="bottom", direction="horizontal"),
    )
    x_axis = alt.X("Period:N", sort=MONTHS + ["Ann."], title=None)
    line = (
        alt.Chart(pd.DataFrame(line_rows))
        .mark_line(strokeWidth=2.5)
        .encode(
            x=x_axis,
            y=alt.Y("Dust loss (%):Q", title="Dust Loss (%)", scale=alt.Scale(zero=True)),
            color=color,
            tooltip=["Period:N", "Profile:N", alt.Tooltip("Dust loss (%):Q", format=".3f")],
        )
    )
    annual_points = (
        alt.Chart(pd.DataFrame(annual_rows))
        .mark_point(size=110, filled=True)
        .encode(
            x=x_axis,
            y=alt.Y("Dust loss (%):Q"),
            color=color,
            tooltip=["Period:N", "Profile:N", alt.Tooltip("Dust loss (%):Q", format=".3f")],
        )
    )
    return alt.layer(line, annual_points).properties(title="Monthly Dust Loss Profiles", height=390)


def run_current_model(
    edited: pd.DataFrame,
    *,
    tilt_deg: float,
    row_length_in: float,
    drop_height_in: float,
    pileup_angle_deg: float,
    multiple_string_factor: float,
    bifacial: bool,
    temperature_coefficient: float,
    snow_units: str,
    precip_units: str,
    manual_washes: int,
    winter_ramp: float,
    spring_ramp: float,
    summer_ramp: float,
    fall_ramp: float,
    bifaciality_factor: float,
    rear_shading: float,
    rear_mismatch: float,
) -> ModelOutputs:
    monthly = SnowMonthlyInputs(
        avg_temp_c=required_column(edited, "Avg Temp (°C)"),
        snow_depth=optional_column(edited, "Snowfall"),
        snow_units=snow_units,
        snow_events_ge_1in=optional_column(edited, 'Snow events ≥1 in'),
        snow_events_any=optional_column(edited, "All snow events"),
        rh_all_day=optional_column(edited, "RH primary (%)"),
        rh_pm=optional_column(edited, "RH PM (%)"),
        front_poa=required_column(edited, "Front POA (kWh/m²/mo)"),
        albedo=optional_column(edited, "Albedo optional"),
        back_poa=optional_column(edited, "Back POA optional"),
        front_mwh=optional_column(edited, "Front MWh optional"),
        back_mwh=optional_column(edited, "Back MWh optional"),
    )
    system = SnowSystemInputs(
        tilt_deg=float(tilt_deg),
        row_length_in=float(row_length_in),
        drop_height_in=float(drop_height_in),
        pileup_angle_deg=float(pileup_angle_deg),
        M=float(multiple_string_factor),
        bifacial=bool(bifacial),
        temperature_coefficient=float(temperature_coefficient),
    )
    dust = DustInputs(
        precip=required_column(edited, "Precipitation"),
        precip_units=precip_units,
        ramp_dec_feb=float(winter_ramp),
        ramp_mar_may=float(spring_ramp),
        ramp_jun_aug=float(summer_ramp),
        ramp_sep_nov=float(fall_ramp),
        manual_washes=int(manual_washes),
    )
    rear = None
    if bifacial:
        rear = BifacialRearFactors(
            bifaciality_factor=float(bifaciality_factor),
            rear_shading=float(rear_shading),
            rear_mismatch=float(rear_mismatch),
        )
    return run_model(sys=system, monthly=monthly, dust=dust, rear=rear)


st.set_page_config(
    page_title="Townsend Snow and Dust Model",
    page_icon="❄️",
    layout="wide",
)

st.markdown(
    """
    <style>
    .attrib {text-align:right; font-size:0.92rem; color:#666;}
    div[data-testid="stMetric"] {border:1px solid #e2e2e2; padding:0.7rem; border-radius:0.45rem;}
    </style>
    """,
    unsafe_allow_html=True,
)
st.markdown('<p class="attrib">Webpage Author <b>Kajal Sheth</b> 😊</p>', unsafe_allow_html=True)
st.title("Solar Snow and Dust Loss Calculator (Townsend Model)")
st.caption("Calculation logic and default values are synchronized to TownsendSnowAndDustModel20260717.xlsx.")

image_path = APP_DIR / "image_snow_loss.png"
if image_path.exists():
    if Image is not None:
        st.image(Image.open(image_path), width="stretch")
    else:
        st.image(str(image_path), width="stretch")

st.markdown(
    """
This calculator estimates monthly PV losses from snow using the Townsend model and monthly dust losses using the companion Townsend dust model. It reproduces the attached workbook's month-by-month blank handling, bifacial adjustments, temperature-adjusted annual weighting, seasonal dust accumulation, and optimization of up to two manual washes.

For months with at least 5% reported snow loss, the combined result uses snow loss alone. Below 5%, snow and dust overlap as `A + B - A × B`. Blank snowfall is treated as zero. For snow events, a numeric value in **Snow events ≥1 in** is used directly; otherwise **All snow events × 0.49** is used. The event count used by the snow equations has a minimum of one.
"""
)

with st.sidebar:
    st.header("Project and system")
    project_name = st.text_input("Project name", value="Davis")
    latitude = st.number_input("Latitude", value=38.5, format="%.4f")
    longitude = st.number_input("Longitude", value=-121.7, format="%.4f")
    elevation_m = st.number_input("Elevation (m)", value=16.0, format="%.1f")
    st.caption("Latitude, longitude, and elevation are retained for project records, as in the workbook. They do not enter the equations.")

    tilt_deg = st.number_input("Tilt T (deg)", value=30.0, step=0.5)
    row_length_in = st.number_input("Row length R (in)", value=79.0, step=1.0)
    drop_height_in = st.number_input("Drop height H (in)", value=24.0, step=1.0)
    pileup_angle_deg = st.number_input("Pileup angle P (deg)", value=40.0, step=1.0)
    multiple_string_factor = st.radio(
        "M, multiple-string factor",
        options=[0.75, 1.0],
        index=0,
        horizontal=True,
    )
    bifacial = st.radio("Bifacial?", options=["NO", "YES"], index=0, horizontal=True) == "YES"
    temperature_coefficient = st.number_input(
        "Power temperature coefficient (1/°C)",
        value=-0.004,
        step=0.0001,
        format="%.4f",
    )

    st.divider()
    st.header("Units and cleaning")
    snow_units = st.radio("Snowfall units", options=["in", "mm"], index=0, horizontal=True)
    precip_units = st.radio("Precipitation units", options=["in", "mm"], index=0, horizontal=True)
    manual_washes = st.radio("Manual washes per year", options=[0, 1, 2], index=1, horizontal=True)

    st.subheader("Dust ramp rate (%/day)")
    spring_ramp = st.number_input("Spring, Mar-May", value=0.05, step=0.025, format="%.3f")
    summer_ramp = st.number_input("Summer, Jun-Aug", value=0.15, step=0.025, format="%.3f")
    fall_ramp = st.number_input("Fall, Sep-Nov", value=0.05, step=0.025, format="%.3f")
    winter_ramp = st.number_input("Winter, Dec-Feb", value=0.025, step=0.025, format="%.3f")

    st.divider()
    st.header("Bifacial rear-side factors")
    bifaciality_factor = st.number_input("Bifaciality factor", value=0.65, step=0.01, format="%.3f")
    rear_shading = st.number_input("Rear shading fraction", value=0.125, step=0.005, format="%.3f")
    rear_mismatch = st.number_input("Rear mismatch fraction", value=0.024, step=0.002, format="%.3f")
    if not bifacial:
        st.caption("These factors are stored but only used when Bifacial is YES.")

st.subheader("Monthly spreadsheet inputs")
st.caption(
    f"Snowfall is currently interpreted in {snow_units}; precipitation is interpreted in {precip_units}. "
    "Leave optional cells blank to invoke the workbook formulas. The attached workbook displays an optional Back POA column, but its formulas do not reference it. This app preserves that behavior exactly."
)

if "monthly_editor_version" not in st.session_state:
    st.session_state.monthly_editor_version = 0

reset_col, note_col = st.columns([1, 5])
with reset_col:
    if st.button("Reset spreadsheet defaults", width="stretch"):
        st.session_state.monthly_editor_version += 1
        st.session_state.pop("model_output", None)
        st.rerun()
with note_col:
    st.info("Enter direct ≥1-inch event counts where available. Otherwise, enter all snow events. RH PM may remain blank when the primary RH value is already the monthly average.")

editor_key = f"monthly_inputs_{st.session_state.monthly_editor_version}"
edited = st.data_editor(
    default_monthly_table(),
    key=editor_key,
    width="stretch",
    hide_index=True,
    num_rows="fixed",
    height=500,
    disabled=["Month"],
    column_config={
        "Month": st.column_config.TextColumn(width="small"),
        "Avg Temp (°C)": st.column_config.NumberColumn(format="%.3f"),
        "Snowfall": st.column_config.NumberColumn(format="%.4f"),
        'Snow events ≥1 in': st.column_config.NumberColumn(format="%.4f"),
        "All snow events": st.column_config.NumberColumn(format="%.4f"),
        "RH primary (%)": st.column_config.NumberColumn(format="%.3f"),
        "RH PM (%)": st.column_config.NumberColumn(format="%.3f"),
        "Front POA (kWh/m²/mo)": st.column_config.NumberColumn(format="%.4f"),
        "Albedo optional": st.column_config.NumberColumn(format="%.5f"),
        "Back POA optional": st.column_config.NumberColumn(format="%.4f"),
        "Front MWh optional": st.column_config.NumberColumn(format="%.5f"),
        "Back MWh optional": st.column_config.NumberColumn(format="%.5f"),
        "Precipitation": st.column_config.NumberColumn(format="%.4f"),
    },
)

run_clicked = st.button("Run model", type="primary", width="stretch")

if run_clicked or "model_output" not in st.session_state:
    try:
        output = run_current_model(
            edited,
            tilt_deg=tilt_deg,
            row_length_in=row_length_in,
            drop_height_in=drop_height_in,
            pileup_angle_deg=pileup_angle_deg,
            multiple_string_factor=multiple_string_factor,
            bifacial=bifacial,
            temperature_coefficient=temperature_coefficient,
            snow_units=snow_units,
            precip_units=precip_units,
            manual_washes=manual_washes,
            winter_ramp=winter_ramp,
            spring_ramp=spring_ramp,
            summer_ramp=summer_ramp,
            fall_ramp=fall_ramp,
            bifaciality_factor=bifaciality_factor,
            rear_shading=rear_shading,
            rear_mismatch=rear_mismatch,
        )
        st.session_state.model_output = output
        st.session_state.model_project_name = project_name
        st.session_state.model_location = (latitude, longitude, elevation_m)
        st.session_state.model_washes = manual_washes
    except Exception as exc:
        if run_clicked:
            st.session_state.pop("model_output", None)
            st.error(str(exc))
            output = None
        else:
            output = st.session_state.get("model_output")
else:
    output = st.session_state.get("model_output")

if output is not None:
    out: ModelOutputs = output
    saved_project = st.session_state.get("model_project_name", project_name)
    saved_location = st.session_state.get("model_location", (latitude, longitude, elevation_m))
    saved_washes = int(st.session_state.get("model_washes", manual_washes))

    st.success("Model calculations completed. Results below reflect the last Run model action.")
    st.subheader("Report-format results")
    metric_cols = st.columns(3)
    metric_cols[0].metric("Annual snow loss", f"{excel_round(out.annual_snow_loss_pct, 1):.1f}%")
    metric_cols[1].metric("Annual dust loss", f"{excel_round(out.annual_dust_loss_pct, 1):.1f}%")
    metric_cols[2].metric("Annual combined loss", f"{excel_round(out.annual_combined_loss_pct, 1):.1f}%")

    if saved_washes == 0:
        st.info("Selected wash case: no manual washes.")
    elif saved_washes == 1:
        st.info(f"Optimal first wash month: {month_name(out.best_wash_month_1)}")
    else:
        st.info(
            f"Optimal wash months: {month_name(out.best_wash_month_1)} and {month_name(out.best_wash_month_2)}. "
            "The second optimized wash may occur earlier in the calendar year, matching the latest workbook logic."
        )

    report_df, monthly_df, details_df = make_output_tables(out)
    st.dataframe(report_df, width="stretch", hide_index=True)

    chart_col1, chart_col2 = st.columns(2)
    with chart_col1:
        st.altair_chart(combined_loss_chart(out), width="stretch")
    with chart_col2:
        st.altair_chart(dust_profiles_chart(out), width="stretch")

    st.subheader("Monthly result detail")
    st.dataframe(
        monthly_df.style.format(
            {
                "Snow loss (%)": "{:.6f}",
                "Dust loss (%)": "{:.6f}",
                "Combined loss (%)": "{:.6f}",
                "No-wash dust (%)": "{:.6f}",
                "1-wash dust (%)": "{:.6f}",
                "2-wash dust (%)": "{:.6f}",
                "Energy weight (%)": "{:.6f}",
            }
        ),
        width="stretch",
        hide_index=True,
    )

    st.subheader("Spreadsheet ramp-rate guidance")
    guidance = out.ramp_guidance
    guidance_df = pd.DataFrame(
        {
            "Season": ["Spring", "Summer", "Fall", "Winter"],
            "Quarter precipitation (in)": [
                guidance.spring_precip_in,
                guidance.summer_precip_in,
                guidance.fall_precip_in,
                guidance.winter_precip_in,
            ],
            "Descending wetness rank": [
                guidance.spring_rank,
                guidance.summer_rank,
                guidance.fall_rank,
                guidance.winter_rank,
            ],
            "Suggested ramp (%/day)": [
                guidance.spring_ramp,
                guidance.summer_ramp,
                guidance.fall_ramp,
                guidance.winter_ramp,
            ],
        }
    )
    st.caption(f"Annual precipitation used for guidance: {guidance.annual_precip_in:.4f} in")
    st.dataframe(guidance_df, width="stretch", hide_index=True)

    with st.expander("Detailed calculation audit"):
        st.dataframe(
            details_df.style.format(
                {
                    "Raw snow loss (%)": "{:.10f}",
                    "Reported snow loss (%)": "{:.10f}",
                    "Estimated albedo": "{:.10f}",
                    "Calculated back POA": "{:.10f}",
                    "Monofacial fraction": "{:.10f}",
                    "Energy proxy": "{:.10f}",
                    "Module temperature (°C)": "{:.10f}",
                    "Temperature adjustment": "{:.10f}",
                    "Energy weight": "{:.10f}",
                    "Dust increment (%)": "{:.10f}",
                    "Dust fixed value (%)": "{:.10f}",
                    "Wash-month residual (%)": "{:.10f}",
                }
            ),
            width="stretch",
            hide_index=True,
        )

    download_df = details_df.copy()
    download_df.insert(1, "Selected dust loss (%)", out.dust_loss_pct)
    download_df.insert(2, "Combined loss (%)", out.combined_loss_pct)
    download_df["No-wash dust (%)"] = out.dust_no_wash_pct
    download_df["1-wash dust (%)"] = out.dust_one_wash_pct
    download_df["2-wash dust (%)"] = out.dust_two_wash_pct
    safe_project = "".join(character if character.isalnum() or character in "-_" else "_" for character in saved_project)
    st.download_button(
        "Download detailed results (CSV)",
        data=download_df.to_csv(index=False).encode("utf-8"),
        file_name=f"{safe_project or 'townsend'}_snow_dust_results.csv",
        mime="text/csv",
        width="stretch",
    )
    st.caption(
        f"Saved run location record: latitude {saved_location[0]:.4f}, longitude {saved_location[1]:.4f}, elevation {saved_location[2]:.1f} m."
    )

st.divider()
st.subheader("Technical documentation")
for filename, label in (
    ("SnowModelTheory.pdf", "Download Snow Model Theory (PDF)"),
    ("DustModelTheory.pdf", "Download Dust Model Theory (PDF)"),
):
    pdf_path = APP_DIR / filename
    if pdf_path.exists():
        st.download_button(label=label, data=pdf_path.read_bytes(), file_name=filename, mime="application/pdf")
    else:
        st.warning(f"{filename} was not found in the application folder.")

st.markdown("### References")
st.markdown(
    """
1. Townsend, T., and Powers, L. (2011). *Photovoltaics and snow: An update from two winters of measurements in the Sierra.* 37th IEEE Photovoltaic Specialists Conference.
2. Townsend, T., and Previtali, J. (2023). *A Fresh Dusting: Current Uses of the Townsend Snow Model.* NREL Photovoltaic Reliability Workshop proceedings.
3. Townsend, T. (2013). *Predicting PV Energy Loss Caused by Snow.* Solar Power International.
"""
)
st.markdown('<p class="attrib">This webpage was created by <b>Sheth Kajal</b> 😊</p>', unsafe_allow_html=True)
