"""HeatHarvest study engine: sizes an ORC waste-heat plant for a site and evaluates it."""
from __future__ import annotations

import math

from . import economics as eco
from .climate import MONTH_HOURS, annual_mean, monthly_temps
from .cycle import ETA_GENERATOR, ETA_MOTOR, FLUIDS, cycle, match_carrier
from .models import DEFAULT_MIN_OUTLET, SECTOR_LABELS, Scenario, SiteInput, StudyResult

ENGINE_VERSION = "1.0.0"

ACC_APPROACH_K = 15.0        # condensing temperature above ambient, air-cooled condenser
MIN_COND_C = 30.0
GAS_PINCH_K = 20.0           # exhaust gas to working fluid or oil
OIL_PINCH_K = 10.0           # thermal oil to working fluid
OIL_MAX_C = 310.0
OIL_BELOW_SOURCE_K = 30.0
ACC_FAN_SHARE = 0.015        # fan power as share of heat rejected
OIL_PUMP_SHARE = 0.012       # oil pump power as share of heat transferred
GAS_FAN_SHARE = 0.005        # extra fan power for exhaust-side pressure drop
AVAILABILITY = 0.97
MIN_UNIT_KW = 500.0
MAX_UNIT_KW = 20000.0
FOOTPRINT_M2_PER_MW = (120.0, 220.0)
FOOTPRINT_MIN_M2 = 400.0
DIRECT_MAX_C = 380.0


def _min_out(src, sector: str) -> float:
    return src.min_outlet_c if src.min_outlet_c is not None else DEFAULT_MIN_OUTLET[sector]


def _uses_oil_loop(site: SiteInput) -> bool:
    if len(site.heat_sources) > 1:
        return True
    s = site.heat_sources[0]
    return s.dust == "high" or s.temp_in_c > DIRECT_MAX_C


def heat_available_kw(site: SiteInput) -> float:
    total = 0.0
    for s in site.heat_sources:
        dt = s.temp_in_c - _min_out(s, site.sector)
        if dt > 0:
            total += s.m_dot * s.cp_kj_kgk * s.hours_share * dt
    return total


def _evap_grid(fluid: str, t_cond: float, t_top: float):
    hi = min(FLUIDS[fluid]["max_evap_c"], t_top)
    t = t_cond + 30.0
    while t <= hi:
        yield round(t, 1)
        t += 4.0


def _evaluate(st, m, q_carrier, oil: bool):
    gross = m * st.w_turbine * ETA_GENERATOR
    pump = m * st.w_pump / ETA_MOTOR
    q_rej = m * st.q_cond
    parasitic = pump + ACC_FAN_SHARE * q_rej + GAS_FAN_SHARE * q_carrier + (OIL_PUMP_SHARE * q_carrier if oil else 0.0)
    return gross, parasitic, gross - parasitic


def design(site: SiteInput, t_amb: float, fluids: list[str] | None = None) -> dict | None:
    """Best design at one ambient temperature. Returns a dict or None if nothing works."""
    t_cond = round(max(t_amb + ACC_APPROACH_K, MIN_COND_C) * 2) / 2
    oil = _uses_oil_loop(site)
    fluids = fluids or list(FLUIDS)
    best = None
    srcs = [(s.m_dot * s.cp_kj_kgk * s.hours_share, s.temp_in_c, _min_out(s, site.sector)) for s in site.heat_sources]

    if not oil:
        c, t_in, t_min = srcs[0]
        for f in fluids:
            for te in _evap_grid(f, t_cond, t_in - GAS_PINCH_K - 2):
                st = cycle(f, te, t_cond)
                if not st:
                    continue
                r = match_carrier(st, c, t_in, t_min, GAS_PINCH_K)
                if not r:
                    continue
                m, q, t_out = r
                gross, par, net = _evaluate(st, m, q, False)
                if best is None or net > best["net"]:
                    best = dict(fluid=f, st=st, m=m, q=q, gross=gross, par=par, net=net,
                                supply=t_in, ret=t_out, oil=False, t_cond=t_cond)
        return best

    t_max = max(t for _, t, _ in srcs)
    t_oil_hot = min(t_max - OIL_BELOW_SOURCE_K, OIL_MAX_C)
    t_ret = 120.0
    rets = []
    while t_ret <= t_oil_hot - 40:
        rets.append(t_ret)
        t_ret += 10.0
    for f in fluids:
        for te in _evap_grid(f, t_cond, t_oil_hot - OIL_PINCH_K - 2):
            st = cycle(f, te, t_cond)
            if not st:
                continue
            for tr in rets:
                q_src = 0.0
                for c, t_in, t_min in srcs:
                    t_out = max(t_min, tr + GAS_PINCH_K)
                    if t_in > t_out:
                        q_src += c * (t_in - t_out)
                if q_src <= 0:
                    continue
                c_oil = q_src / (t_oil_hot - tr)
                r = match_carrier(st, c_oil, t_oil_hot, tr, OIL_PINCH_K)
                if not r:
                    continue
                m, q, t_back = r
                gross, par, net = _evaluate(st, m, q, True)
                if best is None or net > best["net"]:
                    best = dict(fluid=f, st=st, m=m, q=q, gross=gross, par=par, net=net,
                                supply=t_oil_hot, ret=t_back, oil=True, t_cond=t_cond)
    return best


def _fmt_c(x):
    return f"{x:.0f} °C"


def run_study(site: SiteInput) -> StudyResult:
    warnings: list[str] = []
    oil = _uses_oil_loop(site)
    temps = monthly_temps(site.city)
    t_design = annual_mean(site.city)
    t_summer = max(temps)
    q_avail = heat_available_kw(site)
    value = eco.value_per_kwh(site.value_basis, site.electricity_value_sar_kwh,
                              site.gas_price_usd_mmbtu, site.gas_generation_efficiency)

    src_rows = []
    for s in site.heat_sources:
        t_min = _min_out(s, site.sector)
        src_rows.append({
            "name": s.name, "mass_flow_kg_s": round(s.m_dot, 2), "temp_in_c": s.temp_in_c,
            "min_outlet_c": t_min, "dust": s.dust, "hours_share": s.hours_share,
            "heat_kw": round(max(0.0, s.m_dot * s.cp_kj_kgk * s.hours_share * (s.temp_in_c - t_min))),
        })
        if s.temp_in_c - t_min <= 0:
            warnings.append(f"{s.name}: the gas is already at or below its lowest allowed outlet temperature, so it adds no heat.")
        if s.dust == "high":
            warnings.append(f"{s.name}: high dust load. Heat-recovery units need soot blowing or rapping, and a thermal-oil loop is assumed.")

    d = design(site, t_design) if q_avail > 0 else None

    base_assumptions = [
        ("Ambient temperature (design, annual mean)", _fmt_c(t_design)),
        ("Hottest month mean", _fmt_c(t_summer)),
        ("Condenser", f"Air-cooled, condensing {ACC_APPROACH_K:.0f} K above ambient"),
        ("Turbine / pump / generator efficiency", "82% / 70% / 96.5%"),
        ("Exhaust-side pinch; oil-side pinch", f"{GAS_PINCH_K:.0f} K; {OIL_PINCH_K:.0f} K"),
        ("Plant availability", f"{AVAILABILITY:.0%}"),
        ("Value of electricity", f"{value:.3f} SAR/kWh" + (f" ({eco.mmbtu_note(site.gas_price_usd_mmbtu, site.gas_generation_efficiency)})" if site.value_basis == "gas" else "")),
        ("Installed cost basis", f"{eco.CAPEX_REF_USD_PER_KW:,.0f} USD/kWe at 5 MWe, scaled with size (indicative, to be replaced by supplier quotes)"),
        ("Operation and maintenance", "1.5% of investment per year (1–2% range)"),
        ("Discount rate; project life", f"{site.discount_rate:.0%}; {site.project_life_years} years"),
        ("CO2 factor", f"{site.co2_t_per_mwh:.2f} t per MWh"),
        ("Exchange rate", "3.75 SAR per USD"),
    ]

    def empty(verdict, text):
        return StudyResult(
            engine_version=ENGINE_VERSION, feasible=False, verdict=verdict, verdict_text=text,
            heat_available_kw=round(q_avail), heat_recovered_kw=0, configuration="None",
            fluid="", fluid_label="", evaporating_c=None, condensing_c=None, carrier_supply_c=None,
            carrier_return_c=None, cycle_efficiency=None, gross_power_kw=0, parasitic_kw=0,
            net_power_kw=0, units=0, design_ambient_c=round(t_design, 1), summer_ambient_c=t_summer,
            summer_net_power_kw=0, monthly_power_kw=[0] * 12, monthly_energy_mwh=[0] * 12,
            annual_energy_mwh=0, capacity_factor=0, co2_t_per_year=0, value_sar_per_kwh=value,
            sources=src_rows, footprint_m2_low=0, footprint_m2_high=0, space_ok=None,
            capex_breakdown_sar={}, scenarios=[], cashflow_base_sar=[], assumptions=base_assumptions,
            warnings=warnings)

    if not d or d["net"] <= 0:
        return empty("too_cold", "The heat at this site is too little or too cold to drive an ORC unit. "
                     "A heat pump or direct use of the heat for drying or process heating is worth assessing instead.")

    fluid = d["fluid"]
    nameplate = d["net"]
    # Monthly performance: re-optimised at each month's mean temperature, capped near nameplate.
    monthly_p, monthly_e = [], []
    for t, h in zip(temps, MONTH_HOURS):
        dm = design(site, t, [fluid])
        p = min(dm["net"], nameplate * 1.08) if dm else 0.0
        run_h = site.operating_hours * h / 8760.0 * AVAILABILITY
        monthly_p.append(round(p, 1))
        monthly_e.append(round(p * run_h / 1000.0, 1))
    energy = sum(monthly_e)
    summer_p = monthly_p[temps.index(t_summer)]

    if nameplate < MIN_UNIT_KW:
        warnings.append("Net output is below the smallest commercial ORC units (about 500 kWe).")
    units = eco.ceil_div(nameplate, MAX_UNIT_KW)
    mw = nameplate / 1000.0
    fp_lo = max(FOOTPRINT_MIN_M2, mw * FOOTPRINT_M2_PER_MW[0])
    fp_hi = max(FOOTPRINT_MIN_M2 * 1.5, mw * FOOTPRINT_M2_PER_MW[1])
    space_ok = None
    if site.available_area_m2:
        space_ok = site.available_area_m2 >= fp_lo
        if site.available_area_m2 < fp_lo:
            warnings.append("The available area looks smaller than a plant of this size usually needs. A smaller unit or a split layout may be required.")

    scen = {n: eco.scenario(n, nameplate, energy, d["oil"], value, site.discount_rate, site.project_life_years)
            for n in ("low", "base", "high")}
    base = scen["base"]
    cap_bd = eco.capex_breakdown(base["capex_sar"], d["oil"])

    if nameplate < MIN_UNIT_KW:
        verdict, vtext = "too_small", ("The recoverable power is below the smallest commercial ORC units. "
                                       "A heat pump or direct use of the heat is likely a better fit.")
    elif base["npv_sar"] > 0 and (base["payback_years"] or 99) <= 7 and scen["low"]["npv_sar"] >= 0:
        verdict, vtext = "recommended", ("Recommended for detailed engineering. The project pays back in the base case "
                                         "and stays positive in the cautious case.")
    elif base["npv_sar"] > 0:
        verdict, vtext = "promising", ("Promising. The base case pays back, but the result depends on the value of "
                                       "electricity, the final installed cost and the real gas flows.")
    else:
        verdict, vtext = "not_economic", ("Not economic at the current value of electricity. It may become viable if the "
                                          "avoided energy is valued higher (for example gas at its opportunity cost) or costs fall.")

    st = d["st"]
    config = ("Thermal-oil loop: heat-recovery units on each source feed one oil circuit, which heats the ORC"
              if d["oil"] else "Direct: the exhaust heats the ORC working fluid in one heat-recovery exchanger")
    if site.value_basis == "electricity" and site.sector in ("gas_compression", "power"):
        warnings.append("For gas-fired sites, consider valuing the output as avoided gas at its opportunity cost, not only the regulated price.")

    def to_sc(x):
        return Scenario(**{k: v for k, v in x.items() if not k.startswith("_")})

    return StudyResult(
        engine_version=ENGINE_VERSION,
        feasible=True,
        verdict=verdict,
        verdict_text=vtext,
        heat_available_kw=round(q_avail),
        heat_recovered_kw=round(d["q"]),
        configuration=config,
        fluid=fluid,
        fluid_label=FLUIDS[fluid]["label"],
        evaporating_c=st.t_evap_c,
        condensing_c=st.t_cond_c,
        carrier_supply_c=round(d["supply"], 1),
        carrier_return_c=round(d["ret"], 1),
        cycle_efficiency=round(st.efficiency, 4),
        gross_power_kw=round(d["gross"], 1),
        parasitic_kw=round(d["par"], 1),
        net_power_kw=round(nameplate, 1),
        units=units,
        design_ambient_c=round(t_design, 1),
        summer_ambient_c=t_summer,
        summer_net_power_kw=summer_p,
        monthly_power_kw=monthly_p,
        monthly_energy_mwh=monthly_e,
        annual_energy_mwh=round(energy, 1),
        capacity_factor=round(energy / (nameplate * 8.76), 3) if nameplate > 0 else 0,
        co2_t_per_year=round(energy * site.co2_t_per_mwh),
        value_sar_per_kwh=round(value, 4),
        sources=src_rows,
        footprint_m2_low=round(fp_lo, -1),
        footprint_m2_high=round(fp_hi, -1),
        space_ok=space_ok,
        capex_breakdown_sar=cap_bd,
        scenarios=[to_sc(scen[n]) for n in ("low", "base", "high")],
        cashflow_base_sar=[round(x) for x in base["_flows"]],
        assumptions=base_assumptions,
        warnings=warnings,
    )
