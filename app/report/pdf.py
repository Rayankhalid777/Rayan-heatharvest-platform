"""Builds the client pre-feasibility study as a PDF, following HeatHarvest_Document_Guide.md."""
from __future__ import annotations

import io
from datetime import date
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager  # noqa: E402
from reportlab.lib.colors import HexColor, white  # noqa: E402
from reportlab.lib.enums import TA_LEFT  # noqa: E402
from reportlab.lib.pagesizes import A4  # noqa: E402
from reportlab.lib.styles import ParagraphStyle  # noqa: E402
from reportlab.lib.units import mm  # noqa: E402
from reportlab.pdfbase import pdfmetrics  # noqa: E402
from reportlab.pdfbase.ttfonts import TTFont  # noqa: E402
from reportlab.platypus import (Flowable, Image, KeepTogether, Paragraph, SimpleDocTemplate,  # noqa: E402
                                Spacer, Table, TableStyle)

from ..engine.climate import MONTHS  # noqa: E402
from ..engine.models import SECTOR_LABELS, SiteInput, StudyResult  # noqa: E402

HERE = Path(__file__).parent
FONTS = HERE / "fonts"
BRAND = HERE / "brand"

INK = HexColor("#16191D")
GREY = HexColor("#5F6871")
RULE = HexColor("#DADFE3")
RED = HexColor("#F84746")
GREEN = HexColor("#318750")
BAND = HexColor("#F1F4F2")

for name, file in [("Inter", "Inter-Regular.ttf"), ("Inter-Medium", "Inter-Medium.ttf"),
                   ("Inter-SemiBold", "Inter-SemiBold.ttf"), ("Inter-Bold", "Inter-Bold.ttf")]:
    pdfmetrics.registerFont(TTFont(name, str(FONTS / file)))
pdfmetrics.registerFontFamily("Inter", normal="Inter", bold="Inter-SemiBold", italic="Inter", boldItalic="Inter-SemiBold")
for f in FONTS.glob("*.ttf"):
    font_manager.fontManager.addfont(str(f))

PAGE_W, PAGE_H = A4
M_TOP, M_BOTTOM, M_SIDE = 22 * mm, 18 * mm, 18 * mm
TEXT_W = PAGE_W - 2 * M_SIDE

S = {
    "body": ParagraphStyle("body", fontName="Inter", fontSize=9.2, leading=13.4, textColor=INK, alignment=TA_LEFT),
    "lead": ParagraphStyle("lead", fontName="Inter", fontSize=9.6, leading=14, textColor=INK, spaceAfter=3 * mm),
    "title": ParagraphStyle("title", fontName="Inter-Bold", fontSize=21, leading=24, textColor=INK),
    "k": ParagraphStyle("k", fontName="Inter-SemiBold", fontSize=6.8, leading=9, textColor=GREY),
    "v": ParagraphStyle("v", fontName="Inter-Medium", fontSize=9, leading=12, textColor=INK),
    "th": ParagraphStyle("th", fontName="Inter-SemiBold", fontSize=6.8, leading=9, textColor=white),
    "td": ParagraphStyle("td", fontName="Inter", fontSize=8.6, leading=12, textColor=INK),
    "tdb": ParagraphStyle("tdb", fontName="Inter-SemiBold", fontSize=8.6, leading=12, textColor=INK),
    "tdg": ParagraphStyle("tdg", fontName="Inter", fontSize=8.2, leading=11.5, textColor=GREY),
    "num": ParagraphStyle("num", fontName="Inter-SemiBold", fontSize=8.6, leading=12, textColor=RED),
    "cap": ParagraphStyle("cap", fontName="Inter", fontSize=7.8, leading=11, textColor=GREY),
    "sig": ParagraphStyle("sig", fontName="Inter-SemiBold", fontSize=9.6, leading=13, textColor=INK),
    "contact": ParagraphStyle("contact", fontName="Inter", fontSize=9, leading=14, textColor=GREY),
}


def esc(t) -> str:
    return (str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def sar_m(x: float) -> str:
    v = f"{abs(x) / 1e6:,.1f}"
    return f"SAR {'−' if x < 0 else ''}{v} million"


def kw_text(kw: float) -> str:
    return f"{kw / 1000:,.1f} MWe" if kw >= 1000 else f"{kw:,.0f} kWe"


class BrandLine(Flowable):
    def __init__(self, width):
        super().__init__()
        self.width, self.height = width, 3

    def draw(self):
        self.canv.drawImage(str(BRAND / "brand_line.png"), 0, 0, self.width, 2.2, mask=None)


class SectionBand(Flowable):
    def __init__(self, letter: str, title: str, width: float):
        super().__init__()
        self.letter, self.title, self.width, self.height = letter, title, width, 9 * mm

    def draw(self):
        c = self.canv
        c.setFillColor(BAND)
        c.rect(0, 0, self.width, self.height, stroke=0, fill=1)
        c.setStrokeColor(RULE)
        c.setLineWidth(0.6)
        c.line(0, self.height, self.width, self.height)
        b = 5.2 * mm
        y = (self.height - b) / 2
        c.setFillColor(GREEN)
        c.roundRect(2.5 * mm, y, b, b, 1.2 * mm, stroke=0, fill=1)
        c.setFillColor(white)
        c.setFont("Inter-Bold", 7.4)
        c.drawCentredString(2.5 * mm + b / 2, y + b / 2 - 2.6, self.letter)
        c.setFillColor(INK)
        c.setFont("Inter-Bold", 9)
        c.drawString(2.5 * mm + b + 2.5 * mm, self.height / 2 - 3.2, self.title)


def _table(rows, widths, header=None, num_col=False):
    data = []
    if header:
        data.append([Paragraph(esc(h).upper(), S["th"]) for h in header])
    data += rows
    t = Table(data, colWidths=widths, repeatRows=1 if header else 0)
    style = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 2.5 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2.5 * mm),
        ("TOPPADDING", (0, 0), (-1, -1), 2.2 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.2 * mm),
        ("LINEBELOW", (0, 1 if header else 0), (-1, -1), 0.5, RULE),
    ]
    if header:
        style += [("BACKGROUND", (0, 0), (-1, 0), INK)]
    t.setStyle(TableStyle(style))
    return t


def _p(text, style="td"):
    return Paragraph(text if isinstance(text, str) else esc(text), S[style])


def _chart_monthly(res: StudyResult) -> io.BytesIO:
    fig, ax = plt.subplots(figsize=(7.0, 2.4), dpi=200)
    xs = range(12)
    ax.bar(xs, [p / 1000 for p in res.monthly_power_kw], color="#318750", width=0.62)
    ax.axhline(res.net_power_kw / 1000, color="#F84746", lw=1.2)
    ax.text(11.45, res.net_power_kw / 1000, " rated", color="#F84746", va="center", fontsize=7, family="Inter")
    ax.set_xticks(list(xs), MONTHS, fontsize=7.5, family="Inter", color="#16191D")
    ax.set_ylabel("Net power (MWe)" if res.net_power_kw >= 1000 else "Net power (MWe)", fontsize=7.5, family="Inter", color="#5F6871")
    ax.tick_params(axis="y", labelsize=7.5, colors="#5F6871")
    ax.set_ylim(0, max(res.monthly_power_kw + [res.net_power_kw]) / 1000 * 1.18)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color("#DADFE3")
    ax.grid(axis="y", color="#ECEFEB", lw=0.6)
    ax.set_axisbelow(True)
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", transparent=True, dpi=170)
    plt.close(fig)
    buf.seek(0)
    return buf


def _chart_cash(res: StudyResult) -> io.BytesIO:
    flows = res.cashflow_base_sar
    cum, s = [], 0.0
    for f in flows:
        s += f
        cum.append(s / 1e6)
    fig, ax = plt.subplots(figsize=(7.0, 2.3), dpi=200)
    ax.plot(range(len(cum)), cum, color="#16191D", lw=1.6)
    ax.fill_between(range(len(cum)), cum, 0, where=[c >= 0 for c in cum], color="#318750", alpha=0.18, interpolate=True)
    ax.fill_between(range(len(cum)), cum, 0, where=[c < 0 for c in cum], color="#F84746", alpha=0.14, interpolate=True)
    ax.axhline(0, color="#5F6871", lw=0.8)
    ax.set_xlabel("Year", fontsize=7.5, family="Inter", color="#5F6871")
    ax.set_ylabel("Cumulative cash (SAR million)", fontsize=7.5, family="Inter", color="#5F6871")
    ax.tick_params(labelsize=7.5, colors="#5F6871")
    for sp in ("top", "right"):
        ax.spines[sp].set_visible(False)
    for sp in ("left", "bottom"):
        ax.spines[sp].set_color("#DADFE3")
    ax.grid(axis="y", color="#ECEFEB", lw=0.6)
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", transparent=True, dpi=170)
    plt.close(fig)
    buf.seek(0)
    return buf


def _on_page(canvas, doc):
    canvas.saveState()
    w = 120 * mm
    img = BRAND / "HeatHarvest_watermark.png"
    from PIL import Image as PImg
    iw, ih = PImg.open(img).size
    h = w * ih / iw
    canvas.drawImage(str(img), (PAGE_W - w) / 2, (PAGE_H - h) / 2 - 10 * mm, w, h, mask="auto")
    canvas.restoreState()


def build_study_pdf(site: SiteInput, res: StudyResult, *, prepared_for: str, reviewer: str | None = None,
                    signatory: tuple[str, str, str] = ("Prof. Awad Alquaity", "awad.alquaity@kfupm.edu.sa", "+966 53 194 6761"),
                    study_date: date | None = None, draft: bool = False) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=M_SIDE, rightMargin=M_SIDE, topMargin=M_TOP,
                            bottomMargin=M_BOTTOM, title=f"Waste-heat recovery study: {site.site_name}",
                            author="HeatHarvest", subject="Pre-feasibility study")
    d = study_date or date.today()
    story = []
    story.append(BrandLine(TEXT_W))
    story.append(Spacer(1, 6 * mm))
    logo = BRAND / "HeatHarvest_logo_horizontal.png"
    from PIL import Image as PImg
    lw, lh = PImg.open(logo).size
    story.append(Image(str(logo), width=17 * mm * lw / lh, height=17 * mm, hAlign="LEFT"))
    story.append(Spacer(1, 9 * mm))
    story.append(Paragraph(f"Waste-Heat Recovery at {esc(site.site_name)}:<br/>Pre-Feasibility Study", S["title"]))
    story.append(Spacer(1, 5 * mm))
    meta = Table([[
        [Paragraph("PREPARED FOR", S["k"]), Paragraph(esc(prepared_for), S["v"])],
        [Paragraph("FROM", S["k"]), Paragraph("HeatHarvest", S["v"])],
        [Paragraph("DATE", S["k"]), Paragraph(f"{d.day} {d.strftime('%B %Y')}", S["v"])],
    ]], colWidths=[TEXT_W / 3] * 3)
    meta.setStyle(TableStyle([("LINEABOVE", (0, 0), (-1, 0), 0.6, RULE), ("LINEBELOW", (0, 0), (-1, 0), 0.6, RULE),
                              ("LEFTPADDING", (0, 0), (-1, -1), 0), ("TOPPADDING", (0, 0), (-1, -1), 2.6 * mm),
                              ("BOTTOMPADDING", (0, 0), (-1, -1), 2.6 * mm), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story.append(meta)
    story.append(Spacer(1, 7 * mm))

    if draft:
        story.append(Paragraph("Draft for internal review. Not yet approved for release to the client.", S["cap"]))
        story.append(Spacer(1, 3 * mm))

    base = res.scenarios[1] if res.scenarios else None
    sector = SECTOR_LABELS.get(site.sector, "Industrial")
    story.append(Paragraph(
        f"This study estimates how much electricity {esc(site.company)} could generate from waste heat at "
        f"{esc(site.site_name)} ({esc(site.city)}) using an Organic Rankine Cycle (ORC) unit, what the plant would "
        f"cost and how quickly it would pay back. It uses the site data you provided, Saudi climate data for "
        f"{esc(site.city)} and the HeatHarvest Insight engine. Figures are pre-feasibility estimates and are given "
        f"as a range where it matters.", S["lead"]))

    # Summary
    story.append(Paragraph(f"<font name='Inter-SemiBold'>Our assessment.</font> {esc(res.verdict_text)}", S["lead"]))
    if res.feasible and base:
        lo, hi = res.scenarios[0], res.scenarios[2]
        rows = [
            [_p("Net electrical output", "tdb"), _p(kw_text(lo.net_power_kw)), _p(kw_text(base.net_power_kw), "tdb"), _p(kw_text(hi.net_power_kw))],
            [_p("Electricity per year", "tdb"), _p(f"{lo.energy_mwh / 1000:,.1f} GWh"), _p(f"{base.energy_mwh / 1000:,.1f} GWh", "tdb"), _p(f"{hi.energy_mwh / 1000:,.1f} GWh")],
            [_p("Value of electricity per year", "tdb"), _p(sar_m(lo.revenue_sar)), _p(sar_m(base.revenue_sar), "tdb"), _p(sar_m(hi.revenue_sar))],
            [_p("Installed investment", "tdb"), _p(sar_m(lo.capex_sar)), _p(sar_m(base.capex_sar), "tdb"), _p(sar_m(hi.capex_sar))],
            [_p("Simple payback", "tdb"), _p(f"{lo.payback_years} years" if lo.payback_years else "Over 30 years"),
             _p(f"{base.payback_years} years" if base.payback_years else "Over 30 years", "tdb"),
             _p(f"{hi.payback_years} years" if hi.payback_years else "Over 30 years")],
            [_p("Net present value", "tdb"), _p(sar_m(lo.npv_sar)), _p(sar_m(base.npv_sar), "tdb"), _p(sar_m(hi.npv_sar))],
            [_p("CO<sub>2</sub> avoided per year", "tdb"), _p(f"{res.co2_t_per_year * 0.85:,.0f} t"), _p(f"{res.co2_t_per_year:,.0f} t", "tdb"), _p(f"{res.co2_t_per_year * 1.08:,.0f} t")],
        ]
        story.append(KeepTogether([_table(rows, [58 * mm, (TEXT_W - 58 * mm) / 3] + [(TEXT_W - 58 * mm) / 3] * 2,
                                          header=["Result", "Cautious", "Expected", "Favourable"])]))
        story.append(Spacer(1, 2 * mm))
        story.append(Paragraph("Cautious: 15% less power and 35% higher cost. Favourable: 8% more power and 20% lower cost.", S["cap"]))
    story.append(Spacer(1, 6 * mm))

    # A. Heat sources
    rows = []
    for i, s in enumerate(res.sources, 1):
        rows.append([_p(f"{i:02d}", "num"),
                     _p(f"<font name='Inter-SemiBold'>{esc(s['name'])}</font><br/>{s['mass_flow_kg_s']:,.1f} kg/s at {s['temp_in_c']:.0f} °C, "
                        f"cooled to no lower than {s['min_outlet_c']:.0f} °C. Dust: {s['dust']}."),
                     _p(f"{s['heat_kw'] / 1000:,.1f} MW of heat", "tdg")])
    story.append(KeepTogether([SectionBand("A", "Heat sources", TEXT_W), _table(rows, [12 * mm, 112 * mm, TEXT_W - 124 * mm],
                                                                                    header=["No.", "Source", "Recoverable heat"])]))
    story.append(Spacer(1, 2 * mm))
    story.append(Paragraph(f"Total heat available above the outlet limits: {res.heat_available_kw / 1000:,.1f} MW. "
                           f"Plant running hours: {site.operating_hours:,.0f} per year. Sector: {esc(sector)}.", S["cap"]))
    story.append(Spacer(1, 6 * mm))

    if res.feasible:
        # B. Plant
        def row(i, title, text, why):
            return [_p(f"{i:02d}", "num"), _p(f"<font name='Inter-SemiBold'>{title}</font><br/>{text}"), _p(why, "tdg")]
        area_text = f"About {res.footprint_m2_low:,.0f}–{res.footprint_m2_high:,.0f} m², mostly for the air-cooled condensers."
        if site.available_area_m2:
            area_text += f" You indicated {site.available_area_m2:,.0f} m² available" + (", which looks sufficient." if res.space_ok else ", which looks tight.")
        rows = [
            row(1, "Configuration", esc(res.configuration) + ".", "How heat reaches the ORC unit."),
            row(2, "Working fluid", f"{esc(res.fluid_label)}, evaporating at {res.evaporating_c:.0f} °C and condensing at {res.condensing_c:.0f} °C.",
                "Chosen for the heat-source temperature to maximise net output."),
            row(3, "Heat carrier temperatures", f"Supply {res.carrier_supply_c:.0f} °C, return {res.carrier_return_c:.0f} °C. "
                f"{res.heat_recovered_kw / 1000:,.1f} MW of heat recovered.", "Set by the pinch limits of the exchangers."),
            row(4, "Power", f"Gross {kw_text(res.gross_power_kw)}, own consumption {kw_text(res.parasitic_kw)} (pumps and condenser fans), "
                f"net {kw_text(res.net_power_kw)} at {res.design_ambient_c:.0f} °C. Cycle efficiency {res.cycle_efficiency:.1%}.",
                "Net is what the site can use."),
            row(5, "Summer performance", f"{kw_text(res.summer_net_power_kw)} in the hottest month ({res.summer_ambient_c:.0f} °C average).",
                "Air-cooled condensers lose output in the heat."),
            row(6, "Units and space", f"{res.units} ORC unit{'s' if res.units > 1 else ''}. {area_text}", "Space is often the main constraint on site."),
        ]
        story.append(KeepTogether([SectionBand("B", "Recommended plant", TEXT_W),
                                   _table(rows, [12 * mm, 112 * mm, TEXT_W - 124 * mm], header=["No.", "Item", "Note"])]))
        story.append(Spacer(1, 6 * mm))

        # C. Year
        img = Image(_chart_monthly(res), width=TEXT_W, height=TEXT_W * 2.4 / 7.0)
        story.append(KeepTogether([SectionBand("C", "Output through the year", TEXT_W), Spacer(1, 3 * mm), img,
                                   Paragraph(f"Net power by month at {esc(site.city)}'s average temperatures. Annual electricity "
                                             f"{res.annual_energy_mwh / 1000:,.1f} GWh, a capacity factor of {res.capacity_factor:.0%}.", S["cap"])]))
        story.append(Spacer(1, 6 * mm))

        # D. Economics
        rows = [[_p(k), _p(sar_m(v), "tdb")] for k, v in res.capex_breakdown_sar.items()]
        rows.append([_p("Total installed investment (expected case)", "tdb"), _p(sar_m(base.capex_sar), "tdb")])
        cash = Image(_chart_cash(res), width=TEXT_W, height=TEXT_W * 2.3 / 7.0)
        econ_rows = [
            [_p("Value of electricity", "tdb"), _p(f"{res.value_sar_per_kwh:.3f} SAR/kWh")],
            [_p("Operation and maintenance", "tdb"), _p(f"{sar_m(base.opex_sar)} per year")],
            [_p("Internal rate of return", "tdb"), _p(f"{base.irr:.1%}" if base.irr is not None else "Not reached")],
            [_p("Cost of electricity produced", "tdb"), _p(f"{base.lcoe_sar_kwh:.3f} SAR/kWh" if base.lcoe_sar_kwh else "–")],
        ]
        story.append(KeepTogether([SectionBand("D", "Investment and returns", TEXT_W),
                                   _table(rows, [TEXT_W * 0.65, TEXT_W * 0.35], header=["Investment item", "Amount"])]))
        story.append(Spacer(1, 3 * mm))
        story.append(KeepTogether([_table(econ_rows, [TEXT_W * 0.65, TEXT_W * 0.35], header=["Expected case", "Value"]),
                                   Spacer(1, 3 * mm), cash,
                                   Paragraph("Cumulative cash position of the expected case, after investment and operating costs.", S["cap"])]))
        story.append(Spacer(1, 6 * mm))

    # E. Assumptions
    rows = [[_p(esc(k), "tdb"), _p(esc(v))] for k, v in res.assumptions]
    story.append(KeepTogether([SectionBand("E" if res.feasible else "B", "Assumptions", TEXT_W),
                               _table(rows[:1], [62 * mm, TEXT_W - 62 * mm], header=["Assumption", "Value"])]))
    story.append(_table(rows[1:], [62 * mm, TEXT_W - 62 * mm]))
    story.append(Spacer(1, 6 * mm))

    # F. Notes and the data that would firm up the result
    notes = list(res.warnings) + [
        "Measured gas flow, temperature and composition (including dust and sulphur) for each heat source.",
        "A site plan showing where the heat-recovery units, the ORC unit and the air-cooled condensers could go.",
        "The site's electricity tariff or the cost of its own generation, and its running pattern through the year.",
        "Supplier performance data and a budget quotation, which replace the indicative cost curve used here.",
    ]
    rows = [[_p(f"{i:02d}", "num"), _p(esc(n))] for i, n in enumerate(notes, 1)]
    story.append(KeepTogether([SectionBand("F" if res.feasible else "C", "Notes, and what would firm up these results", TEXT_W),
                               _table(rows[:2], [12 * mm, TEXT_W - 12 * mm])]))
    if len(rows) > 2:
        story.append(_table(rows[2:], [12 * mm, TEXT_W - 12 * mm]))

    closing = [Spacer(1, 7 * mm),
               Paragraph("We would be glad to take this to the next stage with you, starting with a site visit and the measurements above.", S["lead"]),
               Spacer(1, 4 * mm), Paragraph("Kind regards,", S["body"]), Spacer(1, 2 * mm),
               Paragraph(esc(signatory[0]), S["sig"]),
               Paragraph(f"HeatHarvest<br/>{esc(signatory[1])}<br/>{esc(signatory[2])}", S["contact"])]
    if reviewer:
        closing += [Spacer(1, 4 * mm), Paragraph(f"Reviewed by {esc(reviewer)}. Prepared with HeatHarvest Insight {esc(res.engine_version)}.", S["cap"])]
    story.append(KeepTogether(closing))

    doc.build(story, onFirstPage=_on_page, onLaterPages=_on_page)
    return buf.getvalue()
