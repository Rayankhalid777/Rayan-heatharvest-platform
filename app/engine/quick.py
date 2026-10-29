"""Quick screening estimate used by the home-page estimator.

Simple rules so the answer is instant. The detailed study uses the full engine in study.py.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

CO2_T_PER_MWH = 0.46
ORC_ETA = (0.14, 0.19)


class QuickInput(BaseModel):
    mode: Literal["kiln", "turbine", "exhaust"]
    clinker_tpd: float = Field(5000, ge=100, le=30000)
    gt_mw: float = Field(25, ge=1, le=400)
    gt_exhaust_c: float = Field(500, ge=300, le=650)
    flow_kg_s: float = Field(50, ge=0.5, le=2000)
    gas_c: float = Field(350, ge=100, le=1200)
    hours: float = Field(7500, ge=1000, le=8760)
    price_sar_kwh: float = Field(0.18, ge=0, le=3)


def quick_estimate(q: QuickInput) -> dict:
    heat = None
    if q.mode == "kiln":
        lo, hi = q.clinker_tpd * 0.5 / 1000, q.clinker_tpd * 1.0 / 1000
        t = None
    elif q.mode == "turbine":
        t = q.gt_exhaust_c
        exh = q.gt_mw * (1 / 0.33 - 1) * 0.9
        heat = exh * max(0.0, t - 150) / (t - 35)
        lo, hi = heat * ORC_ETA[0], heat * ORC_ETA[1]
    else:
        t = q.gas_c
        heat = q.flow_kg_s * 1.1 * max(0.0, t - 150) / 1000
        lo, hi = heat * ORC_ETA[0], heat * ORC_ETA[1]
    g_lo, g_hi = lo * q.hours / 1000, hi * q.hours / 1000
    if hi < 0.5:
        verdict, tone = ("Below the smallest commercial ORC units, about 0.5 MWe. A heat pump or direct use "
                         "of the heat may fit better. We can check."), "low"
    elif lo < 5 and t is not None and t < 300:
        verdict, tone = ("At this size, heat below about 300 °C is rarely economic for ORC. "
                         "Worth checking other uses of the heat."), "low"
    elif lo < 0.5:
        verdict, tone = "Borderline. The result depends on your site data, so a closer look is worthwhile.", "ok"
    else:
        verdict, tone = "Worth a closer look. A site of this size can usually support an ORC unit.", "ok"
    return {
        "mwe": [round(lo, 3), round(hi, 3)],
        "heat_mw": round(heat, 2) if heat is not None else None,
        "gwh": [round(g_lo, 2), round(g_hi, 2)],
        "co2_t": [round(g_lo * 1000 * CO2_T_PER_MWH), round(g_hi * 1000 * CO2_T_PER_MWH)],
        "sar": [round(g_lo * 1e6 * q.price_sar_kwh), round(g_hi * 1e6 * q.price_sar_kwh)],
        "verdict": verdict,
        "tone": tone,
    }
