"""Organic Rankine Cycle thermodynamics using CoolProp.

A subcritical, recuperated ORC: pump -> recuperator -> preheater/evaporator -> turbine ->
recuperator -> air-cooled condenser. Properties come from CoolProp's reference equations of state.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import CoolProp.CoolProp as CP

K = 273.15

# Candidate working fluids. max_evap_c keeps a margin below the critical point and within
# typical thermal-stability limits for commercial ORC units.
FLUIDS = {
    "Isopentane": {"label": "Isopentane (R601a)", "max_evap_c": 172.0},
    "Cyclopentane": {"label": "Cyclopentane", "max_evap_c": 222.0},
    "MM": {"label": "Hexamethyldisiloxane (MM, siloxane)", "max_evap_c": 232.0},
    "Toluene": {"label": "Toluene", "max_evap_c": 290.0},
}

ETA_TURBINE = 0.82
ETA_PUMP = 0.70
ETA_GENERATOR = 0.965
ETA_MOTOR = 0.95
RECUP_EFFECTIVENESS = 0.85
SUPERHEAT_K = 3.0
RECUP_APPROACH_K = 10.0


@dataclass(frozen=True)
class CycleState:
    fluid: str
    t_evap_c: float
    t_cond_c: float
    t_liquid_in_c: float  # liquid entering the heat-input exchanger, after the recuperator
    q_in: float  # kJ/kg heat added from the carrier
    q_preheat: float  # kJ/kg up to the bubble point
    q_evap: float  # kJ/kg bubble point to turbine inlet
    q_cond: float  # kJ/kg rejected in the condenser
    w_turbine: float  # kJ/kg
    w_pump: float  # kJ/kg

    @property
    def net_specific(self) -> float:
        return self.w_turbine * ETA_GENERATOR - self.w_pump / ETA_MOTOR

    @property
    def efficiency(self) -> float:
        return self.net_specific / self.q_in if self.q_in > 0 else 0.0


@lru_cache(maxsize=20000)
def cycle(fluid: str, t_evap_c: float, t_cond_c: float) -> CycleState | None:
    """Return the cycle state per kg of working fluid, or None if it is not a valid cycle."""
    try:
        te, tc = t_evap_c + K, t_cond_c + K
        if t_evap_c - t_cond_c < 25 or t_evap_c > FLUIDS[fluid]["max_evap_c"]:
            return None
        pc = CP.PropsSI("P", "T", tc, "Q", 0, fluid)
        pe = CP.PropsSI("P", "T", te, "Q", 0, fluid)
        h1 = CP.PropsSI("H", "P", pc, "Q", 0, fluid)
        s1 = CP.PropsSI("S", "P", pc, "Q", 0, fluid)
        h2s = CP.PropsSI("H", "P", pe, "S", s1, fluid)
        h2 = h1 + (h2s - h1) / ETA_PUMP
        t2 = CP.PropsSI("T", "P", pe, "H", h2, fluid)
        h_bub = CP.PropsSI("H", "P", pe, "Q", 0, fluid)
        h4 = CP.PropsSI("H", "P", pe, "T", te + SUPERHEAT_K, fluid)
        s4 = CP.PropsSI("S", "P", pe, "T", te + SUPERHEAT_K, fluid)
        h5s = CP.PropsSI("H", "P", pc, "S", s4, fluid)
        h5 = h4 - ETA_TURBINE * (h4 - h5s)
        t5 = CP.PropsSI("T", "P", pc, "H", h5, fluid)
        h_vap_sat = CP.PropsSI("H", "P", pc, "Q", 1, fluid)
        if h5 < h_vap_sat:  # wet expansion: not acceptable for a dry-fluid turbine
            return None
        # Recuperator: vapour side can cool to the higher of (pump outlet + approach) and saturation.
        t_v_min = max(t2 + RECUP_APPROACH_K, tc + 1.0)
        q_rec = 0.0
        if t5 > t_v_min:
            h_v_min = CP.PropsSI("H", "P", pc, "T", t_v_min, fluid)
            q_rec = max(0.0, RECUP_EFFECTIVENESS * (h5 - h_v_min))
        h3 = h2 + q_rec
        if h3 >= h_bub:
            h3 = h_bub
        t3 = CP.PropsSI("T", "P", pe, "H", h3, fluid)
        return CycleState(
            fluid=fluid,
            t_evap_c=t_evap_c,
            t_cond_c=t_cond_c,
            t_liquid_in_c=t3 - K,
            q_in=(h4 - h3) / 1000.0,
            q_preheat=(h_bub - h3) / 1000.0,
            q_evap=(h4 - h_bub) / 1000.0,
            q_cond=(h5 - q_rec - h1) / 1000.0,
            w_turbine=(h4 - h5) / 1000.0,
            w_pump=(h2 - h1) / 1000.0,
        )
    except ValueError:
        return None


def match_carrier(st: CycleState, c_kw_k: float, t_hot_c: float, t_min_out_c: float, pinch_k: float = 10.0):
    """Working-fluid flow (kg/s) that a heat carrier can support.

    The carrier (exhaust gas or thermal oil) with capacity rate c_kw_k enters at t_hot_c and may
    cool no lower than t_min_out_c. Returns (m_wf, heat_kw, carrier_out_c) or None.
    """
    if c_kw_k <= 0:
        return None
    t_pinch = st.t_evap_c + pinch_k
    if t_hot_c <= t_pinch:
        return None
    m_pinch = c_kw_k * (t_hot_c - t_pinch) / st.q_evap
    m_outlet = c_kw_k * (t_hot_c - t_min_out_c) / st.q_in
    m_cold_end = c_kw_k * (t_hot_c - (st.t_liquid_in_c + pinch_k)) / st.q_in
    m = min(m_pinch, m_outlet, m_cold_end)
    if m <= 0:
        return None
    q = m * st.q_in
    return m, q, t_hot_c - q / c_kw_k
