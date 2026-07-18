from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple
import math

MONTHS = [
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
]
DAYS_IN_MONTH = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]

# Protected workbook constants.
C1_CONST = 57000.0
C2_CONST = 0.51
ALBEDO_DAYS_PER_INCH_INTERCEPT = 1.87
ALBEDO_DAYS_PER_INCH_SLOPE = -0.048
POA_BOOST_INTERCEPT = -0.0001
POA_BOOST_SLOPE = 0.4144
MODULE_TEMP_INTERCEPT_C = 11.448
MODULE_TEMP_POA_COEFFICIENT = 2.715
SNOW_DUST_TRANSITION_PCT = 5.0
START_MONTH_SNOW_THRESHOLD_PCT = 3.0


@dataclass(frozen=True)
class SnowMonthlyInputs:
    avg_temp_c: List[float]
    snow_depth: List[Optional[float]]
    snow_units: str
    snow_events_ge_1in: Optional[List[Optional[float]]] = None
    snow_events_any: Optional[List[Optional[float]]] = None
    rh_all_day: Optional[List[Optional[float]]] = None
    rh_am: Optional[List[Optional[float]]] = None
    rh_pm: Optional[List[Optional[float]]] = None
    front_poa: List[float] = None
    albedo: Optional[List[Optional[float]]] = None
    back_poa: Optional[List[Optional[float]]] = None
    front_mwh: Optional[List[Optional[float]]] = None
    back_mwh: Optional[List[Optional[float]]] = None


@dataclass(frozen=True)
class SnowSystemInputs:
    tilt_deg: float
    row_length_in: float
    drop_height_in: float
    pileup_angle_deg: float
    M: float
    bifacial: bool
    temperature_coefficient: float = -0.004


@dataclass(frozen=True)
class DustInputs:
    precip: List[Optional[float]]
    precip_units: str
    ramp_dec_feb: float
    ramp_mar_may: float
    ramp_jun_aug: float
    ramp_sep_nov: float
    manual_washes: int


@dataclass(frozen=True)
class BifacialRearFactors:
    bifaciality_factor: float
    rear_shading: float
    rear_mismatch: float


@dataclass(frozen=True)
class RampRateGuidance:
    spring_ramp: float
    summer_ramp: float
    fall_ramp: float
    winter_ramp: float
    spring_precip_in: float
    summer_precip_in: float
    fall_precip_in: float
    winter_precip_in: float
    annual_precip_in: float
    spring_rank: int
    summer_rank: int
    fall_rank: int
    winter_rank: int


@dataclass(frozen=True)
class ModelOutputs:
    snow_loss_pct: List[float]
    snow_loss_raw_pct: List[float]
    dust_loss_pct: List[float]
    combined_loss_pct: List[float]
    dust_no_wash_pct: List[float]
    dust_one_wash_pct: List[float]
    dust_two_wash_pct: List[float]
    best_wash_month_1: Optional[int]
    best_wash_month_2: Optional[int]
    annual_snow_loss_pct: float
    annual_dust_loss_pct: float
    annual_combined_loss_pct: float
    annual_dust_no_wash_pct: float
    annual_dust_one_wash_pct: float
    annual_dust_two_wash_pct: float
    energy_weights: List[float]
    estimated_albedo: List[float]
    calculated_back_poa: List[float]
    monofacial_fraction: List[float]
    monthly_energy_proxy: List[float]
    module_temperature_c: List[float]
    temperature_adjustment: List[float]
    dust_month_type: List[str]
    dust_increment_pct: List[float]
    dust_fixed_pct: List[float]
    manual_wash_month_residual_pct: List[float]
    ramp_guidance: RampRateGuidance


def _ensure_len12(values: Optional[Sequence[object]], name: str) -> None:
    if values is None or len(values) != 12:
        raise ValueError(f"{name} must contain exactly 12 monthly values.")


def _is_number(value: object) -> bool:
    if value is None or isinstance(value, bool):
        return False
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(number)


def _optional_number(value: object) -> Optional[float]:
    return float(value) if _is_number(value) else None


def _required_numbers(values: Sequence[object], name: str) -> List[float]:
    _ensure_len12(values, name)
    output: List[float] = []
    for index, value in enumerate(values):
        if not _is_number(value):
            raise ValueError(f"{name}: {MONTHS[index]} must contain a number.")
        output.append(float(value))
    return output


def _blank_as_zero(values: Optional[Sequence[object]], name: str) -> List[float]:
    if values is None:
        return [0.0] * 12
    _ensure_len12(values, name)
    return [float(value) if _is_number(value) else 0.0 for value in values]


def _optional_months(values: Optional[Sequence[object]], name: str) -> List[Optional[float]]:
    if values is None:
        return [None] * 12
    _ensure_len12(values, name)
    return [_optional_number(value) for value in values]


def convert_to_inches(values: Sequence[object], units: str, name: str = "monthly values") -> List[float]:
    converted = _blank_as_zero(values, name)
    unit = units.lower().strip()
    if unit == "in":
        return converted
    if unit == "mm":
        return [value / 25.4 for value in converted]
    raise ValueError("Units must be 'in' or 'mm'.")


def compute_events_gt1in(
    events_ge_1in: Optional[Sequence[object]],
    events_any: Optional[Sequence[object]],
) -> List[float]:
    """Replicate SnowInputs row 18 and SnowCalcs row 6 month by month."""
    direct = _optional_months(events_ge_1in, "snow_events_ge_1in")
    any_events = _optional_months(events_any, "snow_events_any")
    output: List[float] = []
    for direct_value, all_value in zip(direct, any_events):
        row18 = direct_value if direct_value is not None else (0.0 if all_value is None else 0.49 * all_value)
        output.append(1.0 if row18 < 1.0 else row18)
    return output


def compute_avg_rh(
    rh_all_day: Optional[Sequence[object]],
    rh_am: Optional[Sequence[object]],
    rh_pm: Optional[Sequence[object]],
) -> List[float]:
    """Replicate AVERAGE(primary RH cell:PM RH cell) for each month."""
    primary_source = rh_all_day if rh_all_day is not None else rh_am
    primary = _optional_months(primary_source, "primary relative humidity")
    pm = _optional_months(rh_pm, "PM relative humidity")
    output: List[float] = []
    for index, (first, second) in enumerate(zip(primary, pm)):
        numeric = [value for value in (first, second) if value is not None]
        if not numeric:
            raise ValueError(f"Relative humidity: enter at least one value for {MONTHS[index]}.")
        output.append(sum(numeric) / len(numeric))
    return output


def compute_albedo(
    temp_c: Sequence[float],
    snow_in: Sequence[float],
    user_albedo: Optional[Sequence[object]],
) -> List[float]:
    temperatures = _required_numbers(temp_c, "average temperature")
    _ensure_len12(snow_in, "snowfall in inches")
    overrides = _optional_months(user_albedo, "albedo")
    output: List[float] = []
    for index in range(12):
        if overrides[index] is not None:
            output.append(float(overrides[index]))
            continue
        snow_cover_fraction = min(
            1.0,
            (ALBEDO_DAYS_PER_INCH_INTERCEPT + ALBEDO_DAYS_PER_INCH_SLOPE * temperatures[index])
            * float(snow_in[index])
            / DAYS_IN_MONTH[index],
        )
        output.append(0.2 + 0.55 * snow_cover_fraction)
    return output


def compute_back_poa(
    bifacial: bool,
    front_poa: Sequence[float],
    albedo: Sequence[float],
    user_back_poa: Optional[Sequence[object]] = None,
) -> List[float]:
    """
    Replicate SnowInputs E25:E36.

    The attached workbook displays N25:N36 as optional back-POA inputs, but its
    E25:E36 formulas do not reference those cells. To preserve literal workbook
    parity, user_back_poa is intentionally retained only for API compatibility
    and is not used in the calculation.
    """
    front = _required_numbers(front_poa, "front POA")
    _ensure_len12(albedo, "albedo")
    if not bifacial:
        return [0.0] * 12
    return [
        (POA_BOOST_INTERCEPT + POA_BOOST_SLOPE * float(albedo[index])) * front[index]
        for index in range(12)
    ]


def compute_c70(factors: BifacialRearFactors) -> float:
    return (
        float(factors.bifaciality_factor)
        * (1.0 - float(factors.rear_shading))
        * (1.0 - float(factors.rear_mismatch))
    )


def _monthly_mwh_available(
    index: int,
    front_mwh: Sequence[Optional[float]],
    back_mwh: Sequence[Optional[float]],
) -> bool:
    return front_mwh[index] is not None and back_mwh[index] is not None


def compute_monofacial_fraction(
    front_poa: Sequence[float],
    back_poa: Sequence[float],
    c70: float,
    front_mwh: Optional[Sequence[object]],
    back_mwh: Optional[Sequence[object]],
) -> List[float]:
    front = _required_numbers(front_poa, "front POA")
    _ensure_len12(back_poa, "calculated back POA")
    front_energy = _optional_months(front_mwh, "front MWh")
    back_energy = _optional_months(back_mwh, "back MWh")
    output: List[float] = []
    for index in range(12):
        if _monthly_mwh_available(index, front_energy, back_energy):
            numerator = float(front_energy[index])
            denominator = numerator + float(back_energy[index])
        else:
            numerator = front[index]
            denominator = numerator + float(back_poa[index]) * c70
        if denominator == 0:
            raise ValueError(f"Monofacial fraction is undefined for {MONTHS[index]} because its denominator is zero.")
        output.append(numerator / denominator)
    return output


def compute_monthly_energy_proxy(
    front_poa: Sequence[float],
    back_poa: Sequence[float],
    c70: float,
    front_mwh: Optional[Sequence[object]],
    back_mwh: Optional[Sequence[object]],
) -> List[float]:
    front = _required_numbers(front_poa, "front POA")
    _ensure_len12(back_poa, "calculated back POA")
    front_energy = _optional_months(front_mwh, "front MWh")
    back_energy = _optional_months(back_mwh, "back MWh")
    output: List[float] = []
    for index in range(12):
        if _monthly_mwh_available(index, front_energy, back_energy):
            output.append(float(front_energy[index]) + float(back_energy[index]))
        else:
            output.append(front[index] + float(back_poa[index]) * c70)
    return output


def compute_temperature_adjusted_energy_weights(
    avg_temp_c: Sequence[float],
    total_poa: Sequence[float],
    monthly_energy_proxy: Sequence[float],
    temperature_coefficient: float,
) -> Tuple[List[float], List[float], List[float]]:
    temperatures = _required_numbers(avg_temp_c, "average temperature")
    _ensure_len12(total_poa, "total POA")
    _ensure_len12(monthly_energy_proxy, "monthly energy proxy")

    annual_avg_temp = sum(temperatures[i] * DAYS_IN_MONTH[i] for i in range(12)) / 365.0
    annual_total_poa = sum(float(value) for value in total_poa)
    annual_module_temp = (
        annual_avg_temp
        + MODULE_TEMP_INTERCEPT_C
        + MODULE_TEMP_POA_COEFFICIENT * annual_total_poa / 365.0
    )

    module_temp = [
        temperatures[i]
        + MODULE_TEMP_INTERCEPT_C
        + MODULE_TEMP_POA_COEFFICIENT * float(total_poa[i]) / DAYS_IN_MONTH[i]
        for i in range(12)
    ]
    adjustment = [
        1.0 + (module_temp[i] - annual_module_temp) * float(temperature_coefficient)
        for i in range(12)
    ]
    adjusted_energy = [float(monthly_energy_proxy[i]) * adjustment[i] for i in range(12)]
    annual_adjusted_energy = sum(adjusted_energy)
    if annual_adjusted_energy == 0:
        raise ValueError("Temperature-adjusted annual energy is zero, so annual weighting cannot be calculated.")
    weights = [value / annual_adjusted_energy for value in adjusted_energy]
    return weights, module_temp, adjustment


def compute_snow_loss_pct(
    sys: SnowSystemInputs,
    avg_temp_c: Sequence[float],
    snow_in: Sequence[float],
    n_events: Sequence[float],
    avg_rh: Sequence[float],
    total_poa: Sequence[float],
    monofacial_fraction: Sequence[float],
    apply_bifacial_adjustment: bool,
) -> List[float]:
    temperatures = _required_numbers(avg_temp_c, "average temperature")
    for values, name in (
        (snow_in, "snowfall in inches"),
        (n_events, "snow events"),
        (avg_rh, "average relative humidity"),
        (total_poa, "total POA"),
        (monofacial_fraction, "monofacial fraction"),
    ):
        _ensure_len12(values, name)

    tan_p = math.tan(math.radians(float(sys.pileup_angle_deg)))
    if tan_p == 0:
        raise ValueError("Pileup angle produces a zero tangent and cannot be used.")

    for index, poa in enumerate(total_poa):
        if float(poa) <= 0:
            raise ValueError(f"Total POA for {MONTHS[index]} must be greater than zero.")

    effective_snow = [
        0.5 * (1.0 + 1.0 / float(n_events[i])) * float(snow_in[i])
        for i in range(12)
    ]
    previous_effective_snow = [effective_snow[(i - 1) % 12] for i in range(12)]
    weighted_effective_snow = [
        0.667 * effective_snow[i] + 0.333 * previous_effective_snow[i]
        for i in range(12)
    ]

    cos_t = math.cos(math.radians(float(sys.tilt_deg)))
    output: List[float] = []
    for i in range(12):
        denominator_subcalc = max(
            0.1,
            float(sys.drop_height_in) ** 2 - weighted_effective_snow[i] ** 2,
        )
        gamma_denominator = 0.5 * (1.0 / tan_p) * denominator_subcalc
        gamma_numerator = float(sys.row_length_in) * cos_t * weighted_effective_snow[i]
        gamma = gamma_numerator / gamma_denominator
        ground_interference = 1.0 - C2_CONST * math.exp(-gamma)
        air_temp_k = temperatures[i] + 273.15
        loss = (
            C1_CONST
            * weighted_effective_snow[i]
            * (cos_t ** 2)
            * ground_interference
            * float(avg_rh[i])
            * (1.0 / (air_temp_k ** 2))
            * (1.0 / (float(total_poa[i]) ** 0.67))
            * float(sys.M)
        )
        loss = min(100.0, loss)
        if sys.bifacial and apply_bifacial_adjustment:
            loss *= float(monofacial_fraction[i])
        output.append(loss)
    return output


def _seasonal_ramps(dust: DustInputs) -> List[float]:
    ramps = [0.0] * 12
    for index in (11, 0, 1):
        ramps[index] = float(dust.ramp_dec_feb)
    for index in (2, 3, 4):
        ramps[index] = float(dust.ramp_mar_may)
    for index in (5, 6, 7):
        ramps[index] = float(dust.ramp_jun_aug)
    for index in (8, 9, 10):
        ramps[index] = float(dust.ramp_sep_nov)
    if any(value < 0 for value in ramps):
        raise ValueError("Dust ramp rates must be nonnegative.")
    return ramps


def _excel_rank_desc(values: Sequence[float]) -> List[int]:
    return [1 + sum(1 for other in values if other > value) for value in values]


def _suggested_ramp(annual_rain: float, rank: int) -> float:
    if annual_rain < 10:
        return 0.025
    if annual_rain < 15:
        return 0.05 if rank == 4 else 0.025
    if annual_rain < 25:
        if rank == 4:
            return 0.15
        if rank in (2, 3):
            return 0.05
        return 0.025
    if annual_rain < 40:
        return 0.1 if rank > 2 else 0.05
    return 0.1


def compute_ramp_rate_guidance(precip: Sequence[object], units: str) -> RampRateGuidance:
    rain = convert_to_inches(precip, units, "precipitation")
    quarter_totals = [
        sum(rain[2:5]),
        sum(rain[5:8]),
        sum(rain[8:11]),
        rain[11] + rain[0] + rain[1],
    ]
    ranks = _excel_rank_desc(quarter_totals)
    annual = sum(quarter_totals)
    suggestions = [_suggested_ramp(annual, rank) for rank in ranks]
    return RampRateGuidance(
        spring_ramp=suggestions[0],
        summer_ramp=suggestions[1],
        fall_ramp=suggestions[2],
        winter_ramp=suggestions[3],
        spring_precip_in=quarter_totals[0],
        summer_precip_in=quarter_totals[1],
        fall_precip_in=quarter_totals[2],
        winter_precip_in=quarter_totals[3],
        annual_precip_in=annual,
        spring_rank=ranks[0],
        summer_rank=ranks[1],
        fall_rank=ranks[2],
        winter_rank=ranks[3],
    )


def compute_dust_baseline_pct(
    precip_in: Sequence[float],
    ramps: Sequence[float],
    snow_loss_raw_pct: Sequence[float],
    snow_loss_report_pct: Sequence[float],
    monofacial_fraction: Sequence[float],
    bifacial: bool,
) -> Tuple[List[float], List[str], List[float], List[float], float, int]:
    for values, name in (
        (precip_in, "precipitation in inches"),
        (ramps, "seasonal ramp rates"),
        (snow_loss_raw_pct, "raw snow loss"),
        (snow_loss_report_pct, "reported snow loss"),
        (monofacial_fraction, "monofacial fraction"),
    ):
        _ensure_len12(values, name)

    max_precip = max(float(value) for value in precip_in)
    start_index = next(i for i, value in enumerate(precip_in) if float(value) == max_precip)
    start_snow = (
        float(snow_loss_report_pct[start_index])
        if bifacial
        else float(snow_loss_raw_pct[start_index])
    )
    if start_snow >= START_MONTH_SNOW_THRESHOLD_PCT:
        start_soil = 0.0
    elif max_precip >= 4.0:
        start_soil = 0.0
    elif max_precip >= 2.0:
        start_soil = 1.0
    else:
        start_soil = 2.0

    month_type: List[str] = []
    for index, precip in enumerate(precip_in):
        if index == start_index:
            month_type.append("Start")
        elif float(precip) >= 2.0:
            month_type.append("Const.")
        else:
            month_type.append("Additive")

    increment = [0.0] * 12
    fixed = [0.0] * 12
    for index in range(12):
        precip = float(precip_in[index])
        if month_type[index] in ("Const.", "Start"):
            increment[index] = 0.0
        elif precip < 0.5:
            increment[index] = DAYS_IN_MONTH[index] * float(ramps[index])
        else:
            previous = (index - 1) % 12
            buildup_days = DAYS_IN_MONTH[index] // 2 if month_type[previous] == "Additive" else 8
            increment[index] = buildup_days * float(ramps[index])

        if month_type[index] == "Const.":
            fixed[index] = 0.0 if precip >= 4.0 else 1.0
        else:
            fixed[index] = start_soil

    baseline = [0.0] * 12
    for step in range(12):
        index = (start_index + step) % 12
        if float(snow_loss_raw_pct[index]) >= SNOW_DUST_TRANSITION_PCT:
            soil = 0.0
        elif month_type[index] == "Additive":
            soil = increment[index] + baseline[(index - 1) % 12]
        else:
            soil = fixed[index]
        soil = min(30.0, soil)
        if bifacial:
            soil *= float(monofacial_fraction[index])
        baseline[index] = soil

    return baseline, month_type, increment, fixed, start_soil, start_index


def compute_manual_wash_month_residual_pct(
    precip_in: Sequence[float],
    ramps: Sequence[float],
    snow_loss_raw_pct: Sequence[float],
    monofacial_fraction: Sequence[float],
    bifacial: bool,
) -> List[float]:
    for values, name in (
        (precip_in, "precipitation in inches"),
        (ramps, "seasonal ramp rates"),
        (snow_loss_raw_pct, "raw snow loss"),
        (monofacial_fraction, "monofacial fraction"),
    ):
        _ensure_len12(values, name)

    residual: List[float] = []
    for index in range(12):
        precip = float(precip_in[index])
        if float(snow_loss_raw_pct[index]) >= SNOW_DUST_TRANSITION_PCT:
            value = 0.0
        elif precip >= 4.0:
            value = 0.0
        elif precip >= 2.0:
            value = 0.5
        elif precip >= 0.5:
            value = (DAYS_IN_MONTH[index] // 2) * float(ramps[index]) / 2.0
        else:
            value = DAYS_IN_MONTH[index] * float(ramps[index]) / 2.0
        if bifacial:
            value *= float(monofacial_fraction[index])
        residual.append(value)
    return residual


def _weighted_score(profile: Sequence[float], weights: Sequence[float]) -> float:
    return sum(float(profile[i]) * float(weights[i]) for i in range(12))


def _build_wash_candidate(
    reference: Sequence[float],
    residual: Sequence[float],
    wash_index: int,
) -> List[float]:
    candidate = [float(value) for value in reference]
    candidate[wash_index] = float(residual[wash_index])
    for index in range(wash_index + 1, 12):
        delta = float(reference[index]) - float(reference[index - 1])
        continued = candidate[index - 1] + delta
        if float(reference[index]) > float(reference[index - 1]):
            candidate[index] = continued
        else:
            candidate[index] = max(float(reference[index]), continued)
    return candidate


def _best_candidate(
    candidates: Sequence[Sequence[float]],
    weights: Sequence[float],
) -> Optional[int]:
    scores = [_weighted_score(candidate, weights) for candidate in candidates]
    minimum = min(scores)
    average = sum(scores) / len(scores)
    if abs(minimum - average) < 1e-12:
        return None
    return scores.index(minimum)


def _solve_selected_wash_profile(
    reference: Sequence[float],
    candidate: Sequence[float],
    month_type: Sequence[str],
    increment: Sequence[float],
    fixed: Sequence[float],
    start_soil: float,
) -> List[float]:
    """Solve the circular I11:I22 or J11:J22 worksheet recurrence."""
    profile = [float(value) for value in reference]
    for _ in range(200):
        previous_profile = profile.copy()
        for index in range(12):
            if month_type[index] == "Additive":
                rule_value = profile[(index - 1) % 12] + float(increment[index])
            elif month_type[index] == "Const.":
                rule_value = float(fixed[index])
            else:
                rule_value = float(start_soil)
            profile[index] = min(
                float(candidate[index]),
                rule_value,
                float(reference[index]),
            )
        if max(abs(profile[i] - previous_profile[i]) for i in range(12)) < 1e-12:
            break
    else:
        raise ValueError("The wash-profile recurrence did not converge.")
    return profile


def compute_wash_profiles(
    baseline: Sequence[float],
    residual: Sequence[float],
    weights: Sequence[float],
    month_type: Sequence[str],
    increment: Sequence[float],
    fixed: Sequence[float],
    start_soil: float,
) -> Tuple[List[float], List[float], Optional[int], Optional[int]]:
    one_wash_candidates = [
        _build_wash_candidate(baseline, residual, wash_index)
        for wash_index in range(12)
    ]
    best_one_index = _best_candidate(one_wash_candidates, weights)
    if best_one_index is None:
        one_wash = [float(value) for value in baseline]
    else:
        one_wash = _solve_selected_wash_profile(
            reference=baseline,
            candidate=one_wash_candidates[best_one_index],
            month_type=month_type,
            increment=increment,
            fixed=fixed,
            start_soil=start_soil,
        )

    two_wash_candidates = [
        _build_wash_candidate(one_wash, residual, wash_index)
        for wash_index in range(12)
    ]
    best_two_index = _best_candidate(two_wash_candidates, weights)
    if best_two_index is None:
        two_wash = one_wash.copy()
    else:
        two_wash = _solve_selected_wash_profile(
            reference=one_wash,
            candidate=two_wash_candidates[best_two_index],
            month_type=month_type,
            increment=increment,
            fixed=fixed,
            start_soil=start_soil,
        )

    return (
        one_wash,
        two_wash,
        None if best_one_index is None else best_one_index + 1,
        None if best_two_index is None else best_two_index + 1,
    )


def compute_combined_loss_pct(
    snow_loss_pct: Sequence[float],
    dust_loss_pct: Sequence[float],
) -> List[float]:
    _ensure_len12(snow_loss_pct, "reported snow loss")
    _ensure_len12(dust_loss_pct, "selected dust loss")
    output: List[float] = []
    for snow, dust in zip(snow_loss_pct, dust_loss_pct):
        snow_fraction = float(snow) / 100.0
        dust_fraction = float(dust) / 100.0
        if snow_fraction >= 0.05:
            combined = snow_fraction
        elif snow_fraction == 0:
            combined = dust_fraction
        else:
            combined = snow_fraction + dust_fraction - snow_fraction * dust_fraction
        output.append(combined * 100.0)
    return output


def run_model(
    sys: SnowSystemInputs,
    monthly: SnowMonthlyInputs,
    dust: DustInputs,
    rear: Optional[BifacialRearFactors],
) -> ModelOutputs:
    avg_temp = _required_numbers(monthly.avg_temp_c, "average temperature")
    front_poa = _required_numbers(monthly.front_poa, "front POA")
    snow_in = convert_to_inches(monthly.snow_depth, monthly.snow_units, "snowfall")
    n_events = compute_events_gt1in(monthly.snow_events_ge_1in, monthly.snow_events_any)
    avg_rh = compute_avg_rh(monthly.rh_all_day, monthly.rh_am, monthly.rh_pm)

    if sys.bifacial:
        if rear is None:
            raise ValueError("Bifacial systems require bifaciality, rear-shading, and rear-mismatch factors.")
        c70 = compute_c70(rear)
    else:
        c70 = 1.0

    albedo = compute_albedo(avg_temp, snow_in, monthly.albedo)
    back_poa = compute_back_poa(
        bifacial=sys.bifacial,
        front_poa=front_poa,
        albedo=albedo,
        user_back_poa=monthly.back_poa,
    )
    total_poa = [
        front_poa[i] + back_poa[i] if sys.bifacial else front_poa[i]
        for i in range(12)
    ]
    monofacial_fraction = compute_monofacial_fraction(
        front_poa=front_poa,
        back_poa=back_poa,
        c70=c70,
        front_mwh=monthly.front_mwh,
        back_mwh=monthly.back_mwh,
    )
    monthly_energy_proxy = compute_monthly_energy_proxy(
        front_poa=front_poa,
        back_poa=back_poa,
        c70=c70,
        front_mwh=monthly.front_mwh,
        back_mwh=monthly.back_mwh,
    )
    weights, module_temp, temp_adjustment = compute_temperature_adjusted_energy_weights(
        avg_temp_c=avg_temp,
        total_poa=total_poa,
        monthly_energy_proxy=monthly_energy_proxy,
        temperature_coefficient=float(sys.temperature_coefficient),
    )

    snow_raw = compute_snow_loss_pct(
        sys=sys,
        avg_temp_c=avg_temp,
        snow_in=snow_in,
        n_events=n_events,
        avg_rh=avg_rh,
        total_poa=total_poa,
        monofacial_fraction=monofacial_fraction,
        apply_bifacial_adjustment=False,
    )
    snow_report = compute_snow_loss_pct(
        sys=sys,
        avg_temp_c=avg_temp,
        snow_in=snow_in,
        n_events=n_events,
        avg_rh=avg_rh,
        total_poa=total_poa,
        monofacial_fraction=monofacial_fraction,
        apply_bifacial_adjustment=True,
    )

    precip_in = convert_to_inches(dust.precip, dust.precip_units, "precipitation")
    ramps = _seasonal_ramps(dust)
    guidance = compute_ramp_rate_guidance(dust.precip, dust.precip_units)
    baseline, month_type, increment, fixed, start_soil, _ = compute_dust_baseline_pct(
        precip_in=precip_in,
        ramps=ramps,
        snow_loss_raw_pct=snow_raw,
        snow_loss_report_pct=snow_report,
        monofacial_fraction=monofacial_fraction,
        bifacial=sys.bifacial,
    )
    residual = compute_manual_wash_month_residual_pct(
        precip_in=precip_in,
        ramps=ramps,
        snow_loss_raw_pct=snow_raw,
        monofacial_fraction=monofacial_fraction,
        bifacial=sys.bifacial,
    )
    one_wash, two_wash, best_one, best_two = compute_wash_profiles(
        baseline=baseline,
        residual=residual,
        weights=weights,
        month_type=month_type,
        increment=increment,
        fixed=fixed,
        start_soil=start_soil,
    )

    washes = int(dust.manual_washes)
    if washes not in (0, 1, 2):
        raise ValueError("Manual washes must be 0, 1, or 2.")
    selected_dust = [baseline, one_wash, two_wash][washes]
    combined = compute_combined_loss_pct(snow_report, selected_dust)

    annual_snow = _weighted_score(snow_report, weights)
    annual_dust = _weighted_score(selected_dust, weights)
    annual_combined = _weighted_score(combined, weights)
    annual_no_wash = _weighted_score(baseline, weights)
    annual_one_wash = _weighted_score(one_wash, weights)
    annual_two_wash = _weighted_score(two_wash, weights)

    return ModelOutputs(
        snow_loss_pct=snow_report,
        snow_loss_raw_pct=snow_raw,
        dust_loss_pct=selected_dust,
        combined_loss_pct=combined,
        dust_no_wash_pct=baseline,
        dust_one_wash_pct=one_wash,
        dust_two_wash_pct=two_wash,
        best_wash_month_1=best_one,
        best_wash_month_2=best_two,
        annual_snow_loss_pct=annual_snow,
        annual_dust_loss_pct=annual_dust,
        annual_combined_loss_pct=annual_combined,
        annual_dust_no_wash_pct=annual_no_wash,
        annual_dust_one_wash_pct=annual_one_wash,
        annual_dust_two_wash_pct=annual_two_wash,
        energy_weights=weights,
        estimated_albedo=albedo,
        calculated_back_poa=back_poa,
        monofacial_fraction=monofacial_fraction,
        monthly_energy_proxy=monthly_energy_proxy,
        module_temperature_c=module_temp,
        temperature_adjustment=temp_adjustment,
        dust_month_type=month_type,
        dust_increment_pct=increment,
        dust_fixed_pct=fixed,
        manual_wash_month_residual_pct=residual,
        ramp_guidance=guidance,
    )
