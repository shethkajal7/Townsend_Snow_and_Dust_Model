from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple
import math

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

DAYS_IN_MONTH = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]

# Excel constants used by the workbook
C1_CONST = 57000.0
C2_CONST = 0.51

ALBEDO_DAYS_PER_INCH_INTERCEPT = 1.87
ALBEDO_DAYS_PER_INCH_SLOPE = -0.048

POA_BOOST_INTERCEPT = -0.0001
POA_BOOST_SLOPE = 0.4144


def _ensure_len12(x: List[float], name: str) -> None:
    if x is None or len(x) != 12:
        raise ValueError(f"{name} must be a list of length 12.")


def _to_float_list(x: List[float | int]) -> List[float]:
    return [float(v) for v in x]


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


@dataclass(frozen=True)
class SnowMonthlyInputs:
    avg_temp_c: List[float]                 # row 13
    snow_depth: List[float]                 # row 14 (in user-selected units)
    snow_units: str                         # "in" or "mm"
    snow_events_ge_1in: Optional[List[float]] = None  # row 16 (if available)
    snow_events_any: Optional[List[float]] = None     # row 17 (if >=1in not available)
    rh_all_day: Optional[List[float]] = None          # row 19 if all-day
    rh_am: Optional[List[float]] = None               # row 19 if AM
    rh_pm: Optional[List[float]] = None               # row 20 if PM
    front_poa: List[float] = None                     # D25:D36 (Front POA Insol.)

    # Optional monthly inputs
    albedo: Optional[List[Optional[float]]] = None    # M25:M36
    back_poa: Optional[List[Optional[float]]] = None  # Back POA Insol, if known
    front_mwh: Optional[List[Optional[float]]] = None # G25:G36
    back_mwh: Optional[List[Optional[float]]] = None  # H25:H36 (bifacial only)


@dataclass(frozen=True)
class SnowSystemInputs:
    tilt_deg: float          # T
    row_length_in: float     # R
    drop_height_in: float    # H
    pileup_angle_deg: float  # P
    M: float                 # 0.75 or 1.0
    bifacial: bool


@dataclass(frozen=True)
class DustInputs:
    precip: List[float]
    precip_units: str  # "in" or "mm"
    ramp_dec_feb: float
    ramp_mar_may: float
    ramp_jun_aug: float
    ramp_sep_nov: float
    manual_washes: int  # 0, 1, 2


@dataclass(frozen=True)
class BifacialRearFactors:
    bifaciality_factor: float
    rear_shading: float
    rear_mismatch: float


@dataclass(frozen=True)
class ModelOutputs:
    snow_loss_pct: List[float]       # 12
    dust_loss_pct: List[float]       # 12
    combined_loss_pct: List[float]   # 12
    best_wash_month_1: Optional[int] # 1-12 or None
    best_wash_month_2: Optional[int] # 1-12 or None
    annual_snow_loss_pct: float
    annual_dust_loss_pct: float
    annual_combined_loss_pct: float


def convert_to_inches(values: List[float], units: str) -> List[float]:
    if units.lower() == "in":
        return _to_float_list(values)
    if units.lower() == "mm":
        return [float(v) / 25.4 for v in values]
    raise ValueError("Units must be 'in' or 'mm'.")


def compute_events_gt1in(
    events_ge_1in: Optional[List[float]],
    events_any: Optional[List[float]],
) -> List[float]:
    """
    Excel: row 18 = IF(ISNUMBER(row16), row16, row17*0.49)
    Then in snow calcs: N = IF(N<1, 1, N)
    """
    if events_ge_1in is not None:
        _ensure_len12(events_ge_1in, "snow_events_ge_1in")
        base = _to_float_list(events_ge_1in)
    else:
        if events_any is None:
            raise ValueError("Provide either snow_events_ge_1in or snow_events_any.")
        _ensure_len12(events_any, "snow_events_any")
        base = [0.49 * float(v) for v in events_any]

    # Excel forces <1 to 1 (includes 0)
    return [1.0 if v < 1.0 else float(v) for v in base]


def compute_avg_rh(
    rh_all_day: Optional[List[float]],
    rh_am: Optional[List[float]],
    rh_pm: Optional[List[float]],
) -> List[float]:
    """
    Excel: Average Relative Humidity = AVERAGE(AM_cell:PM_cell)
    If PM blank, average returns AM.
    """
    if rh_all_day is not None:
        _ensure_len12(rh_all_day, "rh_all_day")
        return _to_float_list(rh_all_day)

    if rh_am is None:
        raise ValueError("Provide rh_all_day or rh_am (and optionally rh_pm).")

    _ensure_len12(rh_am, "rh_am")
    am = _to_float_list(rh_am)

    if rh_pm is None:
        return am

    _ensure_len12(rh_pm, "rh_pm")
    pm = _to_float_list(rh_pm)
    out = []
    for a, p in zip(am, pm):
        # If user leaves PM blank (None) it should behave like Excel blank.
        if p is None:
            out.append(a)
        else:
            out.append((a + p) / 2.0)
    return out


def compute_albedo(
    temp_c: List[float],
    snow_in: List[float],
    user_albedo: Optional[List[Optional[float]]],
) -> List[float]:
    """
    Excel: C25 = IF(ISNUMBER(M25), M25, 0.2 + 0.55*O25)
    O25 = (B57 + B58*TempC) * SnowIn / days_in_month
    """
    _ensure_len12(temp_c, "avg_temp_c")
    _ensure_len12(snow_in, "snow_in")

    out = []
    for i in range(12):
        ua = None if user_albedo is None else user_albedo[i]
        if ua is not None:
            out.append(float(ua))
            continue

        days_per_inch = ALBEDO_DAYS_PER_INCH_INTERCEPT + ALBEDO_DAYS_PER_INCH_SLOPE * float(temp_c[i])
        o_month = days_per_inch * float(snow_in[i]) / float(DAYS_IN_MONTH[i])
        o_month = min(1.0, max(0.0, o_month))
        out.append(0.2 + 0.55 * o_month)
    return out


def compute_back_poa(
    bifacial: bool,
    front_poa: List[float],
    albedo: List[float],
    user_back_poa: Optional[List[Optional[float]]],
) -> List[float]:
    """
    Excel: E25 = IF(bifacial, (N44 + N45*Albedo) * FrontPOA, blank)
    If user supplies Back POA, use it.
    """
    _ensure_len12(front_poa, "front_poa")
    _ensure_len12(albedo, "albedo")

    if not bifacial:
        return [0.0] * 12

    out = []
    for i in range(12):
        ub = None if user_back_poa is None else user_back_poa[i]
        if ub is not None:
            out.append(float(ub))
        else:
            boost = POA_BOOST_INTERCEPT + POA_BOOST_SLOPE * float(albedo[i])
            out.append(boost * float(front_poa[i]))
    return out


def compute_c70(f: BifacialRearFactors) -> float:
    # Excel C70 = C67*(1-C68)*(1-C69)
    return float(f.bifaciality_factor) * (1.0 - float(f.rear_shading)) * (1.0 - float(f.rear_mismatch))


def compute_energy_k(
    front_poa: List[float],
    back_poa: List[float],
    bifacial: bool,
    c70: float,
    front_mwh: Optional[List[Optional[float]]],
    back_mwh: Optional[List[Optional[float]]],
) -> List[float]:
    """
    Excel K25 = IF(AND(ISNUMBER(G25),ISNUMBER(H25)), G25+H25, D25 + E25*C70)
    """
    _ensure_len12(front_poa, "front_poa")
    _ensure_len12(back_poa, "back_poa")

    have_mwh = (
        front_mwh is not None and back_mwh is not None
        and any(v is not None for v in front_mwh)
        and any(v is not None for v in back_mwh)
    )

    out = []
    for i in range(12):
        if have_mwh:
            fm = float(front_mwh[i] or 0.0)
            bm = float(back_mwh[i] or 0.0)
            out.append(fm + bm)
        else:
            if bifacial:
                out.append(float(front_poa[i]) + float(back_poa[i]) * float(c70))
            else:
                out.append(float(front_poa[i]))
    return out


def compute_energy_weights(k: List[float]) -> List[float]:
    total = sum(max(0.0, float(v)) for v in k)
    if total <= 0:
        return [1.0 / 12.0] * 12
    return [max(0.0, float(v)) / total for v in k]


def compute_monofacial_fraction(
    front_poa: List[float],
    back_poa: List[float],
    bifacial: bool,
    c70: float,
    front_mwh: Optional[List[Optional[float]]],
    back_mwh: Optional[List[Optional[float]]],
) -> List[float]:
    """
    Excel I25 = IF(AND(ISNUMBER(G25),ISNUMBER(H25)),
                   G25/(G25+H25),
                   D25/(D25+E25*C70))
    """
    if not bifacial:
        return [1.0] * 12

    have_mwh = (
        front_mwh is not None and back_mwh is not None
        and any(v is not None for v in front_mwh)
        and any(v is not None for v in back_mwh)
    )

    out = []
    for i in range(12):
        if have_mwh:
            f = float(front_mwh[i] or 0.0)
            b = float(back_mwh[i] or 0.0)
            denom = f + b
            out.append(1.0 if denom <= 0 else f / denom)
        else:
            f = float(front_poa[i])
            b = float(back_poa[i]) * float(c70)
            denom = f + b
            out.append(1.0 if denom <= 0 else f / denom)
    return out


def compute_total_poa(front_poa: List[float], back_poa: List[float], bifacial: bool) -> List[float]:
    if not bifacial:
        return _to_float_list(front_poa)
    return [float(f) + float(b) for f, b in zip(front_poa, back_poa)]


def compute_snow_loss_pct(
    sys: SnowSystemInputs,
    monthly: SnowMonthlyInputs,
    snow_in: List[float],
    n_events: List[float],
    avg_rh: List[float],
    total_poa: List[float],
    monofacial_fraction: List[float],
) -> List[float]:
    """
    Matches 5-SnowCalcs:
    loss% = MIN(100, C1 * Se' * cos(T)^2 * GIT * RH * (1/Ta^2) * (1/POA^0.67) * M)
    If bifacial, report uses loss% * monofacial_fraction.
    """
    _ensure_len12(snow_in, "snow_in")
    _ensure_len12(n_events, "n_events")
    _ensure_len12(avg_rh, "avg_rh")
    _ensure_len12(total_poa, "total_poa")
    _ensure_len12(monofacial_fraction, "monofacial_fraction")

    T = float(sys.tilt_deg)
    R = float(sys.row_length_in)
    H = float(sys.drop_height_in)
    P = float(sys.pileup_angle_deg)
    M = float(sys.M)

    cosT = math.cos(math.radians(T))
    cosT2 = cosT * cosT
    tanP = math.tan(math.radians(P))
    if abs(tanP) < 1e-12:
        raise ValueError("Pileup angle produces tan(P) ~ 0, invalid.")

    # Se = 0.5*(1+1/N)*S
    S = _to_float_list(snow_in)
    N = _to_float_list(n_events)
    Se = [0.5 * (1.0 + 1.0 / N[i]) * S[i] for i in range(12)]
    Se_prev = [Se[(i - 1) % 12] for i in range(12)]
    Se_prime = [0.667 * Se[i] + 0.333 * Se_prev[i] for i in range(12)]

    out = []
    for i in range(12):
        TaK = float(monthly.avg_temp_c[i]) + 273.15
        RH = float(avg_rh[i])
        POA = float(total_poa[i])

        # gamma pieces
        denom_sub = max(0.1, H * H - Se_prime[i] * Se_prime[i])
        gamma_denom = 0.5 * (1.0 / tanP) * denom_sub
        gamma_num = R * cosT * Se_prime[i]
        gamma = gamma_num / gamma_denom if gamma_denom != 0 else 0.0

        GIT = 1.0 - C2_CONST * math.exp(-gamma)

        if TaK <= 0 or POA <= 0:
            loss = 0.0
        else:
            loss = C1_CONST * Se_prime[i] * cosT2 * GIT * RH * (1.0 / (TaK * TaK)) * (1.0 / (POA ** 0.67)) * M

        loss = _clamp(loss, 0.0, 100.0)

        # If bifacial: reported loss% is reduced by front-energy fraction
        if sys.bifacial:
            loss *= float(monofacial_fraction[i])

        out.append(loss)

    return out


def _seasonal_ramps(d: DustInputs) -> List[float]:
    r = [0.0] * 12
    # Dec-Feb
    for i in [11, 0, 1]:
        r[i] = float(d.ramp_dec_feb)
    # Mar-May
    for i in [2, 3, 4]:
        r[i] = float(d.ramp_mar_may)
    # Jun-Aug
    for i in [5, 6, 7]:
        r[i] = float(d.ramp_jun_aug)
    # Sep-Nov
    for i in [8, 9, 10]:
        r[i] = float(d.ramp_sep_nov)
    return r


def _precip_in_inches(precip: List[float], units: str) -> List[float]:
    _ensure_len12(precip, "precip")
    if units.lower() == "in":
        return _to_float_list(precip)
    if units.lower() == "mm":
        return [float(v) / 25.4 for v in precip]
    raise ValueError("Precip units must be 'in' or 'mm'.")


def compute_dust_baseline_pct(
    precip_in: List[float],
    ramps: List[float],
    snow_loss_pct: List[float],
    monofacial_fraction: List[float],
    bifacial: bool,
) -> List[float]:
    """
    Matches 2-DustInputs&Results baseline H11:H22 logic.
    """
    _ensure_len12(precip_in, "precip_in")
    _ensure_len12(ramps, "ramps")
    _ensure_len12(snow_loss_pct, "snow_loss_pct")
    _ensure_len12(monofacial_fraction, "monofacial_fraction")

    # L20 max precip, L21 match index (1-based in Excel), we use 0-based
    max_p = max(precip_in)
    start_idx = precip_in.index(max_p)

    # P22 is snow loss at start month (used to zero out start soil logic)
    start_snow = float(snow_loss_pct[start_idx])

    # L22 start soil %
    if start_snow >= 3.0:
        start_soil = 0.0
    else:
        if max_p >= 4.0:
            start_soil = 0.0
        elif max_p >= 2.0:
            start_soil = 1.0
        else:
            start_soil = 2.0

    # Month types and increments/fixed terms
    mtype = [""] * 12
    inc = [0.0] * 12
    fixed = [0.0] * 12

    for i in range(12):
        if i == start_idx:
            mtype[i] = "Start"
        else:
            mtype[i] = "Const." if precip_in[i] >= 2.0 else "Additive"

    for i in range(12):
        if mtype[i] in ("Const.", "Start"):
            inc[i] = 0.0
        else:
            # additive
            if precip_in[i] < 1.0:
                inc[i] = DAYS_IN_MONTH[i] * ramps[i]
            else:
                # 1 <= precip < 2: grace depends on previous month type
                prev = (i - 1) % 12
                if mtype[prev] == "Additive":
                    inc[i] = 15.0 * ramps[i]
                else:
                    inc[i] = 8.0 * ramps[i]

        if mtype[i] == "Const.":
            if precip_in[i] >= 4.0:
                fixed[i] = 0.0
            elif precip_in[i] >= 2.0:
                fixed[i] = 1.0
            else:
                # Excel uses a placeholder text here, but it never happens because Const. implies >=2
                fixed[i] = start_soil
        else:
            fixed[i] = start_soil

    # Baseline pattern
    base = [0.0] * 12
    for i in range(12):
        if snow_loss_pct[i] >= 3.0:
            soil = 0.0
        else:
            if mtype[i] == "Additive":
                prev = (i - 1) % 12
                soil = base[prev] + inc[i]
            elif mtype[i] == "Const.":
                soil = fixed[i]
            else:  # Start
                soil = start_soil

        soil = _clamp(soil, 0.0, 30.0)  # Excel MIN(30,...)
        if bifacial:
            soil *= float(monofacial_fraction[i])
        base[i] = _clamp(soil, 0.0, 30.0)

    return base


def compute_month_only_soil_pct(
    precip_in: List[float],
    ramps: List[float],
    snow_loss_pct: List[float],
    monofacial_fraction: List[float],
    bifacial: bool,
) -> List[float]:
    """
    Matches 2-DustInputs&Results B30:B41 (updated workbook 2026-02-26):

    "Soil% for this month only. If a manual wash month, no grace period."
    The workbook sets the wash-month loss to ONE-HALF of the normal accumulation.

    Rules (before caps/bifacial):
      If snow >= 3%          => 0
      Else if precip >= 4    => 0
      Else if precip >= 2    => 1
      Else if precip >= 1    => floor(days_in_month/2) * ramp
      Else (precip < 1)      => (days_in_month/2) * ramp

    Then clamp to [0, 30]. If bifacial, multiply by monofacial_fraction, then clamp again.
    """
    _ensure_len12(precip_in, "precip_in")
    _ensure_len12(ramps, "ramps")
    _ensure_len12(snow_loss_pct, "snow_loss_pct")
    _ensure_len12(monofacial_fraction, "monofacial_fraction")

    out: List[float] = []
    for i in range(12):
        if float(snow_loss_pct[i]) >= 3.0:
            soil = 0.0
        else:
            p = float(precip_in[i])
            r = float(ramps[i])
            if p >= 4.0:
                soil = 0.0
            elif p >= 2.0:
                soil = 1.0
            elif p >= 1.0:
                soil = math.floor(DAYS_IN_MONTH[i] / 2.0) * r
            else:
                soil = (DAYS_IN_MONTH[i] / 2.0) * r

        soil = _clamp(soil, 0.0, 30.0)
        if bifacial:
            soil *= float(monofacial_fraction[i])
        out.append(_clamp(soil, 0.0, 30.0))

    return out


def optimize_washes(
    baseline: List[float],
    month_only: List[float],
    energy_weights: List[float],
    washes: int,
) -> Tuple[List[float], Optional[int], Optional[int]]:
    """
    Updated workbook behavior (2026-02-26):

    - The wash-month loss is ONE-HALF of the normal monthly accumulation. This is already
      encoded in month_only (B30:B41).
    - The 2nd wash is only allowed to occur in a month STRICTLY LATER than the 1st wash.
      Months earlier than (or equal to) the 1st wash month remain identical to the 1-wash profile.

    Implementation notes:
      * We keep the model year-ordered (Jan..Dec), no wrap-around improvements.
      * We use energy_weights as the objective weights (SUMPRODUCT in Excel).
      * Final washed patterns are capped so they never exceed the reference pattern:
          - 1-wash capped against baseline (no-wash final)
          - 2-wash capped against best 1-wash final
      * "None" wash behavior: if MIN(scores) == AVERAGE(scores) (within epsilon), return None.
    """
    _ensure_len12(baseline, "baseline")
    _ensure_len12(month_only, "month_only")
    _ensure_len12(energy_weights, "energy_weights")

    washes = int(max(0, min(2, washes)))

    def score(vec: List[float]) -> float:
        return sum(float(vec[i]) * float(energy_weights[i]) for i in range(12))

    def cap_against(raw: List[float], cap_series: List[float]) -> List[float]:
        return [min(float(raw[i]), float(cap_series[i])) for i in range(12)]

    def build_1wash_raw(w1: int) -> List[float]:
        raw = [float(v) for v in baseline]
        raw[w1] = float(month_only[w1])

        # propagate forward only (later months)
        for m in range(w1 + 1, 12):
            delta = float(baseline[m]) - float(baseline[m - 1])
            raw[m] = max(0.0, raw[m - 1] + delta)
        return raw

    def build_2wash_raw(final1: List[float], w1: int, w2: int) -> List[float]:
        # months up to w2-1 stay as 1-wash
        raw = [float(v) for v in final1]
        raw[w2] = float(month_only[w2])
        for m in range(w2 + 1, 12):
            delta = float(final1[m]) - float(final1[m - 1])
            raw[m] = max(0.0, raw[m - 1] + delta)
        return raw

    if washes == 0:
        return [float(v) for v in baseline], None, None

    # --- 1 wash ---
    raw_candidates_1 = [build_1wash_raw(w) for w in range(12)]
    final_candidates_1 = [cap_against(r, baseline) for r in raw_candidates_1]
    scores_1 = [score(r) for r in raw_candidates_1]  # Excel scores the raw grid

    min_s1 = min(scores_1)
    avg_s1 = sum(scores_1) / len(scores_1)

    if abs(min_s1 - avg_s1) < 1e-12:
        # Excel displays None, and the pattern stays baseline
        final1 = [float(v) for v in baseline]
        best1 = None
    else:
        best1_idx = scores_1.index(min_s1)  # MATCH first occurrence
        final1 = final_candidates_1[best1_idx]
        best1 = best1_idx + 1  # 1-12

    if washes == 1:
        return final1, best1, None

    # --- 2 washes ---
    if best1 is None:
        return final1, None, None

    w1 = best1 - 1

    # Only allow 2nd wash in a strictly later month (no wrap-around)
    possible_w2 = list(range(w1 + 1, 12))
    if not possible_w2:
        return final1, best1, None

    raw_candidates_2 = []
    final_candidates_2 = []
    scores_2 = []
    for w2 in possible_w2:
        raw2 = build_2wash_raw(final1, w1=w1, w2=w2)
        raw_candidates_2.append((w2, raw2))
        final2 = cap_against(raw2, final1)
        final_candidates_2.append(final2)
        scores_2.append(score(raw2))

    min_s2 = min(scores_2)
    avg_s2 = sum(scores_2) / len(scores_2)

    if abs(min_s2 - avg_s2) < 1e-12:
        return final1, best1, None

    best2_local_idx = scores_2.index(min_s2)
    best2_w2, _ = raw_candidates_2[best2_local_idx]
    final2 = final_candidates_2[best2_local_idx]
    best2 = best2_w2 + 1

    return final2, best1, best2


def compute_combined_loss_pct(snow_loss_pct: List[float], dust_loss_pct: List[float]) -> List[float]:
    """
    Excel report logic:
      if snow >= 3% then combined = snow
      else combined = snow + dust - snow*dust (fractions)
    """
    _ensure_len12(snow_loss_pct, "snow_loss_pct")
    _ensure_len12(dust_loss_pct, "dust_loss_pct")

    out = []
    for s, d in zip(snow_loss_pct, dust_loss_pct):
        if float(s) >= 3.0:
            out.append(float(s))
        else:
            sf = float(s) / 100.0
            df = float(d) / 100.0
            cf = sf + df - sf * df
            out.append(100.0 * cf)
    return out


def run_model(
    sys: SnowSystemInputs,
    monthly: SnowMonthlyInputs,
    dust: DustInputs,
    rear: Optional[BifacialRearFactors],
) -> ModelOutputs:
    # Validate core monthly inputs
    _ensure_len12(monthly.avg_temp_c, "avg_temp_c")
    _ensure_len12(monthly.snow_depth, "snow_depth")
    _ensure_len12(monthly.front_poa, "front_poa")

    # Convert snow to inches using units selector
    snow_in = convert_to_inches(monthly.snow_depth, monthly.snow_units)

    # Events logic
    n_events = compute_events_gt1in(monthly.snow_events_ge_1in, monthly.snow_events_any)

    # RH logic
    avg_rh = compute_avg_rh(monthly.rh_all_day, monthly.rh_am, monthly.rh_pm)

    # Bifacial factors
    if sys.bifacial:
        if rear is None:
            raise ValueError("Bifacial is YES, provide rear factors (bifaciality, shading, mismatch).")
        c70 = compute_c70(rear)
    else:
        c70 = 1.0

    # Albedo and back POA
    albedo = compute_albedo(monthly.avg_temp_c, snow_in, monthly.albedo)
    back_poa = compute_back_poa(sys.bifacial, monthly.front_poa, albedo, monthly.back_poa)

    # Total POA for snow model denominator (Excel B25)
    total_poa = compute_total_poa(monthly.front_poa, back_poa, sys.bifacial)

    # Monofacial fraction (Excel I25)
    mf = compute_monofacial_fraction(
        monthly.front_poa,
        back_poa,
        sys.bifacial,
        c70,
        monthly.front_mwh,
        monthly.back_mwh,
    )

    # Snow loss
    snow_loss = compute_snow_loss_pct(
        sys=sys,
        monthly=monthly,
        snow_in=snow_in,
        n_events=n_events,
        avg_rh=avg_rh,
        total_poa=total_poa,
        monofacial_fraction=mf,
    )

    # Dust components
    precip_in = _precip_in_inches(dust.precip, dust.precip_units)
    ramps = _seasonal_ramps(dust)

    baseline = compute_dust_baseline_pct(
        precip_in=precip_in,
        ramps=ramps,
        snow_loss_pct=snow_loss,
        monofacial_fraction=mf,
        bifacial=sys.bifacial,
    )

    month_only = compute_month_only_soil_pct(
        precip_in=precip_in,
        ramps=ramps,
        snow_loss_pct=snow_loss,
        monofacial_fraction=mf,
        bifacial=sys.bifacial,
    )

    # Energy weights for wash optimization (Excel L25 = K25/K37)
    k = compute_energy_k(
        front_poa=monthly.front_poa,
        back_poa=back_poa,
        bifacial=sys.bifacial,
        c70=c70,
        front_mwh=monthly.front_mwh,
        back_mwh=monthly.back_mwh,
    )
    weights = compute_energy_weights(k)

    dust_loss, best1, best2 = optimize_washes(
        baseline=baseline,
        month_only=month_only,
        energy_weights=weights,
        washes=dust.manual_washes,
    )

    combined = compute_combined_loss_pct(snow_loss, dust_loss)

    annual_snow = sum(float(weights[i]) * float(snow_loss[i]) for i in range(12))
    annual_dust = sum(float(weights[i]) * float(dust_loss[i]) for i in range(12))
    annual_combined = sum(float(weights[i]) * float(combined[i]) for i in range(12))

    return ModelOutputs(
        snow_loss_pct=snow_loss,
        dust_loss_pct=dust_loss,
        combined_loss_pct=combined,
        best_wash_month_1=best1,
        best_wash_month_2=best2,
        annual_snow_loss_pct=float(annual_snow),
        annual_dust_loss_pct=float(annual_dust),
        annual_combined_loss_pct=float(annual_combined),
    )