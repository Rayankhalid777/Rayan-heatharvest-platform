"""Cost and financial model. All money in SAR unless named otherwise."""
from __future__ import annotations

import math

SAR_PER_USD = 3.75
KWH_PER_MMBTU = 293.07

# Indicative installed cost of an ORC waste-heat plant (USD per kWe net) at 5 MWe, scaled with
# size by an exponent. Replace with supplier quotations when they are available.
CAPEX_REF_USD_PER_KW = 3100.0
CAPEX_REF_MW = 5.0
CAPEX_SCALE_EXP = -0.25
OIL_LOOP_FACTOR = 1.12

CAPEX_SHARES_DIRECT = {
    "ORC module and generator": 0.50,
    "Heat-recovery exchanger": 0.18,
    "Air-cooled condensers": 0.12,
    "Civil works, electrical and installation": 0.13,
    "Engineering and contingency": 0.07,
}
CAPEX_SHARES_OIL = {
    "ORC module and generator": 0.45,
    "Heat-recovery units and thermal-oil loop": 0.25,
    "Air-cooled condensers": 0.11,
    "Civil works, electrical and installation": 0.12,
    "Engineering and contingency": 0.07,
}

OPEX_SHARE = {"low": 0.020, "base": 0.015, "high": 0.010}
POWER_FACTOR = {"low": 0.85, "base": 1.00, "high": 1.08}
CAPEX_FACTOR = {"low": 1.35, "base": 1.00, "high": 0.80}
DEGRADATION = 0.003


def specific_capex_usd(net_kw: float, oil_loop: bool) -> float:
    mw = max(net_kw / 1000.0, 0.5)
    c = CAPEX_REF_USD_PER_KW * (mw / CAPEX_REF_MW) ** CAPEX_SCALE_EXP
    return c * (OIL_LOOP_FACTOR if oil_loop else 1.0)


def capex_sar(net_kw: float, oil_loop: bool) -> float:
    return specific_capex_usd(net_kw, oil_loop) * net_kw * SAR_PER_USD


def capex_breakdown(total_sar: float, oil_loop: bool) -> dict[str, float]:
    shares = CAPEX_SHARES_OIL if oil_loop else CAPEX_SHARES_DIRECT
    return {k: round(total_sar * v) for k, v in shares.items()}


def value_per_kwh(basis: str, electricity_sar_kwh: float, gas_usd_mmbtu: float, gen_eff: float) -> float:
    if basis == "gas":
        return gas_usd_mmbtu * SAR_PER_USD / (gen_eff * KWH_PER_MMBTU)
    return electricity_sar_kwh


def npv(rate: float, flows: list[float]) -> float:
    return sum(f / (1 + rate) ** i for i, f in enumerate(flows))


def irr(flows: list[float]) -> float | None:
    lo, hi = -0.99, 2.0
    f_lo, f_hi = npv(lo, flows), npv(hi, flows)
    if f_lo * f_hi > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        f_mid = npv(mid, flows)
        if abs(f_mid) < 1e-6:
            break
        if f_lo * f_mid < 0:
            hi, f_hi = mid, f_mid
        else:
            lo, f_lo = mid, f_mid
    return (lo + hi) / 2


def crf(rate: float, years: int) -> float:
    if rate == 0:
        return 1 / years
    return rate * (1 + rate) ** years / ((1 + rate) ** years - 1)


def scenario(name: str, net_kw: float, energy_mwh: float, oil_loop: bool, value_sar_kwh: float,
             rate: float, years: int) -> dict:
    p = net_kw * POWER_FACTOR[name]
    e = energy_mwh * POWER_FACTOR[name]
    cap = capex_sar(net_kw, oil_loop) * CAPEX_FACTOR[name]
    opex = cap * OPEX_SHARE[name]
    flows = [-cap]
    for y in range(1, years + 1):
        e_y = e * (1 - DEGRADATION) ** (y - 1)
        flows.append(e_y * 1000 * value_sar_kwh - opex)
    rev1 = e * 1000 * value_sar_kwh
    margin = rev1 - opex
    payback = cap / margin if margin > 0 else None
    lcoe = (cap * crf(rate, years) + opex) / (e * 1000) if e > 0 else None
    return {
        "name": name,
        "net_power_kw": round(p, 1),
        "energy_mwh": round(e, 1),
        "capex_sar": round(cap),
        "opex_sar": round(opex),
        "revenue_sar": round(rev1),
        "npv_sar": round(npv(rate, flows)),
        "irr": irr(flows) if margin > 0 else None,
        "payback_years": round(payback, 1) if payback is not None and payback < 100 else None,
        "lcoe_sar_kwh": round(lcoe, 4) if lcoe else None,
        "_flows": flows,
    }


def mmbtu_note(gas_usd_mmbtu: float, gen_eff: float) -> str:
    v = value_per_kwh("gas", 0, gas_usd_mmbtu, gen_eff)
    return f"{gas_usd_mmbtu:g} USD/MMBtu at {gen_eff:.0%} generation efficiency = {v:.3f} SAR/kWh"


def ceil_div(a: float, b: float) -> int:
    return max(1, math.ceil(a / b))
