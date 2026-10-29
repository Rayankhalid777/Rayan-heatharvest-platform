"""Engine checks: physics sanity, limits and economics."""
import pytest

from app.engine import SiteInput, run_study
from app.engine.cycle import cycle
from app.engine.quick import QuickInput, quick_estimate


def site(**kw):
    base = dict(company="T", site_name="S", city="Riyadh", sector="other",
                heat_sources=[dict(name="Stack", mass_flow_kg_s=80, temp_in_c=350)], operating_hours=8000)
    base.update(kw)
    return SiteInput(**base)


def test_cycle_respects_carnot():
    st = cycle("Toluene", 220.0, 42.0)
    carnot = 1 - (42 + 273.15) / (220 + 273.15)
    assert st is not None
    assert 0.1 < st.efficiency < carnot


def test_energy_balance():
    st = cycle("Cyclopentane", 200.0, 40.0)
    # heat in = net work + heat out, within rounding and generator/pump losses
    assert abs(st.q_in - (st.w_turbine - st.w_pump) - st.q_cond) < 0.02 * st.q_in


def test_cement_reference_plant_order_of_magnitude():
    # Two kiln lines of about 10,000 t/d clinker, similar to Saudi Arabia's first cement ORC (13 MW, ~80 GWh/yr).
    s = site(sector="cement", heat_sources=[
        dict(name="Preheater", mass_flow_kg_s=234, temp_in_c=330, min_outlet_c=210, dust="high"),
        dict(name="Cooler", mass_flow_kg_s=150, temp_in_c=300, min_outlet_c=120, cp_kj_kgk=1.03, dust="medium")],
        operating_hours=7800)
    r = run_study(s)
    assert r.feasible
    assert 8000 < r.net_power_kw < 15000
    assert 60_000 < r.annual_energy_mwh < 100_000
    assert 0.18 < r.cycle_efficiency < 0.26


def test_hotter_month_gives_less_power():
    r = run_study(site())
    assert r.summer_net_power_kw < max(r.monthly_power_kw)


def test_more_heat_more_power():
    a = run_study(site(heat_sources=[dict(name="A", mass_flow_kg_s=50, temp_in_c=350)]))
    b = run_study(site(heat_sources=[dict(name="A", mass_flow_kg_s=100, temp_in_c=350)]))
    assert b.net_power_kw > a.net_power_kw * 1.8


def test_small_source_is_too_small():
    r = run_study(site(heat_sources=[dict(name="A", mass_flow_kg_s=5, temp_in_c=250)]))
    assert r.verdict in ("too_small", "too_cold")


def test_source_below_outlet_limit_is_too_cold():
    r = run_study(site(heat_sources=[dict(name="A", mass_flow_kg_s=50, temp_in_c=140)]))
    assert r.verdict == "too_cold" and not r.feasible


def test_never_recommends_negative_npv():
    r = run_study(site(electricity_value_sar_kwh=0.02))
    assert r.verdict in ("not_economic", "too_small")
    assert r.scenarios[1].npv_sar < 0


def test_gas_value_basis():
    low = run_study(site(sector="gas_compression", value_basis="gas", gas_price_usd_mmbtu=1.25))
    high = run_study(site(sector="gas_compression", value_basis="gas", gas_price_usd_mmbtu=6.0))
    assert high.scenarios[1].npv_sar > low.scenarios[1].npv_sar


def test_volume_flow_input():
    r = run_study(site(heat_sources=[dict(name="A", volume_flow_nm3_h=223_000, temp_in_c=350)]))
    assert r.sources[0]["mass_flow_kg_s"] == pytest.approx(80, rel=0.01)


def test_city_must_be_known():
    with pytest.raises(ValueError):
        site(city="Atlantis")


def test_quick_estimate_matches_website_rules():
    q = quick_estimate(QuickInput(mode="kiln", clinker_tpd=5000, hours=7500, price_sar_kwh=0.18))
    assert q["mwe"] == [2.5, 5.0]
