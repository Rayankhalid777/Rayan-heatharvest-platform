"""Input and output schemas for the HeatHarvest study engine."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from .climate import CITIES

Sector = Literal["cement", "glass", "steel", "gas_compression", "power", "chemicals", "other"]
Dust = Literal["low", "medium", "high"]

SECTOR_LABELS = {
    "cement": "Cement",
    "glass": "Glass",
    "steel": "Steel",
    "gas_compression": "Gas compression or pipeline pumping",
    "power": "Power generation",
    "chemicals": "Chemicals, aluminium or other process industry",
    "other": "Other",
}

# Lowest sensible exhaust outlet temperature by sector when the client does not give one (°C).
# Cement preheater gas is usually still needed for raw-mill drying; dusty or sulphur-bearing
# gas must stay above its acid dew point.
DEFAULT_MIN_OUTLET = {
    "cement": 200.0,
    "glass": 170.0,
    "steel": 160.0,
    "gas_compression": 120.0,
    "power": 120.0,
    "chemicals": 160.0,
    "other": 150.0,
}

NM3_DENSITY = 1.29  # kg per normal m³ for air-like flue gas


class HeatSource(BaseModel):
    name: str = Field(..., max_length=120)
    mass_flow_kg_s: Optional[float] = Field(None, gt=0, le=2000)
    volume_flow_nm3_h: Optional[float] = Field(None, gt=0, le=10_000_000)
    temp_in_c: float = Field(..., ge=80, le=1200)
    min_outlet_c: Optional[float] = Field(None, ge=40, le=600)
    cp_kj_kgk: float = Field(1.08, ge=0.9, le=1.5)
    dust: Dust = "low"
    hours_share: float = Field(1.0, gt=0, le=1.0, description="Share of plant running hours this source is available")

    @model_validator(mode="after")
    def _flow(self):
        if self.mass_flow_kg_s is None and self.volume_flow_nm3_h is None:
            raise ValueError("Give the gas flow, either in kg/s or in Nm³/h.")
        return self

    @property
    def m_dot(self) -> float:
        if self.mass_flow_kg_s is not None:
            return self.mass_flow_kg_s
        return self.volume_flow_nm3_h * NM3_DENSITY / 3600.0


class SiteInput(BaseModel):
    company: str = Field(..., max_length=160)
    site_name: str = Field(..., max_length=160)
    city: str
    sector: Sector = "other"
    heat_sources: list[HeatSource] = Field(..., min_length=1, max_length=12)
    operating_hours: float = Field(8000, ge=1000, le=8760)
    electricity_value_sar_kwh: float = Field(0.18, ge=0, le=3)
    value_basis: Literal["electricity", "gas"] = "electricity"
    gas_price_usd_mmbtu: float = Field(1.25, ge=0, le=40)
    gas_generation_efficiency: float = Field(0.33, ge=0.2, le=0.6)
    available_area_m2: Optional[float] = Field(None, gt=0, le=1_000_000)
    discount_rate: float = Field(0.08, ge=0.0, le=0.3)
    project_life_years: int = Field(25, ge=5, le=40)
    co2_t_per_mwh: float = Field(0.46, ge=0, le=1.5)
    notes: Optional[str] = Field(None, max_length=4000)

    @field_validator("city")
    @classmethod
    def _city(cls, v: str) -> str:
        if v not in CITIES:
            raise ValueError("Choose a city from the list.")
        return v


class Scenario(BaseModel):
    name: str
    net_power_kw: float
    energy_mwh: float
    capex_sar: float
    opex_sar: float
    revenue_sar: float
    npv_sar: float
    irr: Optional[float]
    payback_years: Optional[float]
    lcoe_sar_kwh: Optional[float]


class StudyResult(BaseModel):
    engine_version: str
    feasible: bool
    verdict: Literal["recommended", "promising", "not_economic", "too_small", "too_cold"]
    verdict_text: str
    # thermal
    heat_available_kw: float
    heat_recovered_kw: float
    configuration: str
    fluid: str
    fluid_label: str
    evaporating_c: Optional[float]
    condensing_c: Optional[float]
    carrier_supply_c: Optional[float]
    carrier_return_c: Optional[float]
    cycle_efficiency: Optional[float]
    gross_power_kw: float
    parasitic_kw: float
    net_power_kw: float
    units: int
    design_ambient_c: float
    summer_ambient_c: float
    summer_net_power_kw: float
    monthly_power_kw: list[float]
    monthly_energy_mwh: list[float]
    annual_energy_mwh: float
    capacity_factor: float
    co2_t_per_year: float
    value_sar_per_kwh: float
    sources: list[dict]
    # space
    footprint_m2_low: float
    footprint_m2_high: float
    space_ok: Optional[bool]
    # economics
    capex_breakdown_sar: dict[str, float]
    scenarios: list[Scenario]
    cashflow_base_sar: list[float]
    assumptions: list[tuple[str, str]]
    warnings: list[str]
