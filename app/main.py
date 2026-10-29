"""HeatHarvest web server: public website, public API and the team dashboard."""
from __future__ import annotations

import json
import logging
import re
from contextlib import asynccontextmanager
from datetime import date

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, EmailStr, Field, ValidationError
from sqlalchemy import func, select
from starlette.middleware.sessions import SessionMiddleware

from . import config, mailer
from .db import Event, Inquiry, SessionLocal, StudyRequest, User, init_db, now
from .engine import ENGINE_VERSION, SiteInput, run_study
from .engine.climate import CITIES
from .engine.models import SECTOR_LABELS, StudyResult
from .engine.quick import QuickInput, quick_estimate
from .report.pdf import build_study_pdf
from .security import RateLimiter, csrf_ok, csrf_token, hash_password, verify_password

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("heatharvest")

@asynccontextmanager
async def lifespan(_app):
    startup()
    yield


app = FastAPI(title="HeatHarvest", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=config.SECRET_KEY, session_cookie="hh_session",
                   max_age=12 * 3600, same_site="lax", https_only=config.PRODUCTION)
templates = Jinja2Templates(directory=str(config.BASE_DIR / "app" / "templates"))
app.mount("/admin-static", StaticFiles(directory=str(config.BASE_DIR / "app" / "admin_static")), name="admin-static")

public_limit = RateLimiter(limit=12, window=3600)
quick_limit = RateLimiter(limit=600, window=3600)
login_limit = RateLimiter(limit=10, window=900)

STATUS_LABELS = {
    "received": "Received",
    "draft": "Draft ready for review",
    "approved": "Approved",
    "sent": "Sent to client",
    "declined": "Declined",
    "error": "Needs attention",
}


@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    if request.url.path.startswith("/admin"):
        resp.headers["Cache-Control"] = "no-store"
    return resp


def startup() -> None:
    init_db()
    if config.ADMIN_EMAIL and config.ADMIN_PASSWORD:
        with SessionLocal() as db:
            if not db.scalar(select(User).where(User.email == config.ADMIN_EMAIL.lower())):
                db.add(User(email=config.ADMIN_EMAIL.lower(), name=config.ADMIN_NAME,
                            password_hash=hash_password(config.ADMIN_PASSWORD)))
                db.commit()
                log.info("Created first team account for %s", config.ADMIN_EMAIL)


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    return fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "unknown")


def add_event(db, req: StudyRequest, actor: str, text: str) -> None:
    db.add(Event(request_id=req.id, actor=actor, text=text))


def compute(db, req: StudyRequest, actor: str) -> None:
    try:
        site = SiteInput(**req.input_json)
        res = run_study(site)
        req.result_json = res.model_dump()
        req.status = "draft"
        req.error = ""
        req.approved_at = None
        add_event(db, req, actor, f"Study calculated (engine {ENGINE_VERSION}): {res.net_power_kw / 1000:.2f} MWe, verdict {res.verdict}.")
    except Exception as e:  # noqa: BLE001 - keep the request and show the error to the team
        log.exception("Study calculation failed for request %s", req.id)
        req.status = "error"
        req.error = str(e)[:2000]
        add_event(db, req, actor, "Calculation failed. See the error on this page.")


# ---------------------------------------------------------------- public API

@app.get("/healthz")
def healthz():
    return {"ok": True, "engine": ENGINE_VERSION}


@app.get("/api/meta")
def meta():
    return {"cities": list(CITIES), "sectors": SECTOR_LABELS, "engine": ENGINE_VERSION}


@app.post("/api/quick-estimate")
def api_quick(q: QuickInput, request: Request):
    if not quick_limit.allow(client_ip(request)):
        raise HTTPException(429, "Too many requests. Try again later.")
    return quick_estimate(q)


class InquiryIn(BaseModel):
    role: str = Field("", max_length=80)
    name: str = Field(..., min_length=1, max_length=200)
    email: EmailStr
    company: str = Field("", max_length=300)
    message: str = Field("", max_length=5000)
    estimate: str = Field("", max_length=1000)
    bot_field: str = Field("", alias="bot-field")

    model_config = {"populate_by_name": True}


@app.post("/api/inquiries")
def api_inquiry(body: InquiryIn, request: Request):
    if body.bot_field:
        return {"ok": True}
    if not public_limit.allow("inq:" + client_ip(request)):
        raise HTTPException(429, "Too many messages from this connection. Try again in an hour or email us.")
    with SessionLocal() as db:
        inq = Inquiry(role=body.role, name=body.name.strip(), email=str(body.email), company=body.company.strip(),
                      message=body.message.strip(), estimate=body.estimate.strip())
        db.add(inq)
        db.commit()
        mailer.notify_team(f"New website inquiry from {inq.name}",
                           f"{inq.name} <{inq.email}>\nRole: {inq.role}\nCompany and site: {inq.company}\n\n{inq.message}\n\n"
                           f"Estimate: {inq.estimate}\n\nOpen the dashboard: {config.SITE_URL}/admin/inquiries")
    return {"ok": True}


class ContactIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    email: EmailStr
    phone: str = Field("", max_length=80)
    role: str = Field("", max_length=120)


class StudyRequestIn(BaseModel):
    contact: ContactIn
    site: SiteInput
    consent: bool
    website: str = ""  # honeypot


@app.post("/api/study-requests")
async def api_study_request(request: Request):
    try:
        raw = await request.json()
        body = StudyRequestIn(**raw)
    except ValidationError as e:
        msgs = []
        for err in e.errors():
            loc = " › ".join(str(x) for x in err["loc"])
            msgs.append(f"{loc}: {err['msg'].replace('Value error, ', '')}")
        return JSONResponse({"ok": False, "errors": msgs[:8]}, status_code=422)
    except (ValueError, json.JSONDecodeError):
        return JSONResponse({"ok": False, "errors": ["The form data could not be read."]}, status_code=400)
    if body.website:
        return {"ok": True, "id": 0}
    if not body.consent:
        return JSONResponse({"ok": False, "errors": ["Please confirm we may use this data to prepare your study."]}, status_code=422)
    if not public_limit.allow("study:" + client_ip(request)):
        raise HTTPException(429, "Too many requests from this connection. Try again in an hour or email us.")
    with SessionLocal() as db:
        req = StudyRequest(contact_name=body.contact.name.strip(), contact_email=str(body.contact.email),
                           contact_phone=body.contact.phone.strip(), contact_role=body.contact.role.strip(),
                           company=body.site.company.strip(), site_name=body.site.site_name.strip(),
                           input_json=body.site.model_dump(), status="received")
        db.add(req)
        db.flush()
        add_event(db, req, "website", "Request received from the website.")
        compute(db, req, "system")
        db.commit()
        rid = req.id
        mailer.notify_team(f"New study request #{rid}: {req.company}, {req.site_name}",
                           f"{req.contact_name} <{req.contact_email}> {req.contact_phone}\n"
                           f"Draft study status: {STATUS_LABELS.get(req.status)}\n\n"
                           f"Review it here: {config.SITE_URL}/admin/requests/{rid}")
        mailer.send(req.contact_email, "We have received your site data",
                    f"Dear {req.contact_name},\n\nThank you for sending the data for {req.site_name}. "
                    f"Our engineers are preparing your detailed waste-heat recovery study and will send it to you "
                    f"within a few days. If we need anything else, we will write to you.\n\nKind regards,\n"
                    f"HeatHarvest\n{config.SIGNATORY_EMAIL}", reply_to=config.SIGNATORY_EMAIL)
    return {"ok": True, "id": rid}


# ---------------------------------------------------------------- team dashboard

class NotLoggedIn(Exception):
    pass


@app.exception_handler(NotLoggedIn)
async def _not_logged_in(request: Request, exc: NotLoggedIn):
    return RedirectResponse("/admin/login", status_code=303)


def current_user(request: Request) -> User:
    uid = request.session.get("uid")
    if not uid:
        raise NotLoggedIn()
    with SessionLocal() as db:
        u = db.get(User, uid)
    if not u:
        request.session.clear()
        raise NotLoggedIn()
    return u


def render(request: Request, name: str, **ctx):
    ctx.update(request=request, csrf=csrf_token(request.session), STATUS_LABELS=STATUS_LABELS,
               SECTOR_LABELS=SECTOR_LABELS, mail_ok=mailer.configured())
    return templates.TemplateResponse(request, name, ctx)


def check_csrf(request: Request, token: str):
    if not csrf_ok(request.session, token):
        raise HTTPException(400, "This form has expired. Go back, reload the page and try again.")


@app.get("/admin/login", response_class=HTMLResponse)
def login_page(request: Request):
    return render(request, "login.html", error=None)


@app.post("/admin/login")
def login(request: Request, email: str = Form(...), password: str = Form(...), csrf: str = Form("")):
    check_csrf(request, csrf)
    if not login_limit.allow(client_ip(request)):
        return render(request, "login.html", error="Too many attempts. Wait 15 minutes and try again.")
    with SessionLocal() as db:
        u = db.scalar(select(User).where(User.email == email.strip().lower()))
    if not u or not verify_password(password, u.password_hash):
        return render(request, "login.html", error="That email and password do not match a team account.")
    request.session.clear()
    request.session["uid"] = u.id
    return RedirectResponse("/admin", status_code=303)


@app.post("/admin/logout")
def logout(request: Request, csrf: str = Form("")):
    check_csrf(request, csrf)
    request.session.clear()
    return RedirectResponse("/admin/login", status_code=303)


@app.get("/admin", response_class=HTMLResponse)
def dashboard(request: Request, status: str = "", user: User = Depends(current_user)):
    with SessionLocal() as db:
        q = select(StudyRequest).order_by(StudyRequest.created_at.desc())
        if status:
            q = q.where(StudyRequest.status == status)
        reqs = db.scalars(q.limit(300)).all()
        counts = dict(db.execute(select(StudyRequest.status, func.count()).group_by(StudyRequest.status)).all())
        new_inq = db.scalar(select(func.count()).select_from(Inquiry).where(Inquiry.status == "new")) or 0
    return render(request, "dashboard.html", user=user, reqs=reqs, counts=counts, status=status, new_inq=new_inq)


def _get_req(db, rid: int) -> StudyRequest:
    req = db.get(StudyRequest, rid)
    if not req:
        raise HTTPException(404, "No study request with that number.")
    return req


@app.get("/admin/requests/{rid}", response_class=HTMLResponse)
def request_detail(request: Request, rid: int, user: User = Depends(current_user)):
    with SessionLocal() as db:
        req = _get_req(db, rid)
        events = list(req.events)
    res = StudyResult(**req.result_json) if req.result_json else None
    return render(request, "request.html", user=user, req=req, res=res, events=events,
                  input_text=json.dumps(req.input_json, indent=2, ensure_ascii=False), flash=request.session.pop("flash", None))


def _flash(request: Request, text: str):
    request.session["flash"] = text


@app.post("/admin/requests/{rid}/rerun")
def rerun(request: Request, rid: int, input_json: str = Form(...), csrf: str = Form(""), user: User = Depends(current_user)):
    check_csrf(request, csrf)
    try:
        data = json.loads(input_json)
        SiteInput(**data)
    except (json.JSONDecodeError, ValidationError) as e:
        _flash(request, f"The inputs were not saved: {str(e)[:600]}")
        return RedirectResponse(f"/admin/requests/{rid}", status_code=303)
    with SessionLocal() as db:
        req = _get_req(db, rid)
        changed = data != req.input_json
        req.input_json = data
        if changed:
            add_event(db, req, user.name, "Inputs edited.")
        compute(db, req, user.name)
        req.reviewer = ""
        db.commit()
    _flash(request, "Study recalculated. Review it, then approve it.")
    return RedirectResponse(f"/admin/requests/{rid}", status_code=303)


@app.post("/admin/requests/{rid}/approve")
def approve(request: Request, rid: int, csrf: str = Form(""), user: User = Depends(current_user)):
    check_csrf(request, csrf)
    with SessionLocal() as db:
        req = _get_req(db, rid)
        if req.status not in ("draft", "approved") or not req.result_json:
            raise HTTPException(400, "Only a calculated draft can be approved.")
        req.status, req.reviewer, req.approved_at = "approved", user.name, now()
        add_event(db, req, user.name, "Study approved for release.")
        db.commit()
    _flash(request, "Approved. You can now send it to the client.")
    return RedirectResponse(f"/admin/requests/{rid}", status_code=303)


def _pdf_for(req: StudyRequest) -> bytes:
    site = SiteInput(**req.input_json)
    res = StudyResult(**req.result_json)
    final = req.status in ("approved", "sent")
    return build_study_pdf(site, res, prepared_for=req.company, reviewer=req.reviewer if final else None,
                           signatory=(config.SIGNATORY_NAME, config.SIGNATORY_EMAIL, config.SIGNATORY_PHONE),
                           study_date=(req.approved_at.date() if req.approved_at else date.today()), draft=not final)


def _pdf_name(req: StudyRequest) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", f"{req.company}_{req.site_name}").strip("_")[:80]
    return f"HeatHarvest_Study_{slug}.pdf"


@app.get("/admin/requests/{rid}/study.pdf")
def study_pdf(rid: int, request: Request, user: User = Depends(current_user)):
    with SessionLocal() as db:
        req = _get_req(db, rid)
        if not req.result_json:
            raise HTTPException(400, "This request has no calculated study yet.")
        pdf = _pdf_for(req)
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{_pdf_name(req)}"'})


@app.post("/admin/requests/{rid}/send")
def send_study(request: Request, rid: int, message: str = Form(...), csrf: str = Form(""), user: User = Depends(current_user)):
    check_csrf(request, csrf)
    with SessionLocal() as db:
        req = _get_req(db, rid)
        if req.status not in ("approved", "sent"):
            raise HTTPException(400, "Approve the study before sending it.")
        pdf = _pdf_for(req)
        ok = mailer.send(req.contact_email, f"Your waste-heat recovery study: {req.site_name}", message,
                         attachment=(_pdf_name(req), pdf), reply_to=config.SIGNATORY_EMAIL)
        if ok:
            req.status, req.sent_at = "sent", now()
            add_event(db, req, user.name, f"Study emailed to {req.contact_email}.")
            _flash(request, f"Sent to {req.contact_email}.")
        else:
            add_event(db, req, user.name, "Email could not be sent.")
            _flash(request, "The email could not be sent. Check the email settings, or download the PDF and send it yourself, then mark it as sent.")
        db.commit()
    return RedirectResponse(f"/admin/requests/{rid}", status_code=303)


@app.post("/admin/requests/{rid}/status")
def set_status(request: Request, rid: int, action: str = Form(...), csrf: str = Form(""), user: User = Depends(current_user)):
    check_csrf(request, csrf)
    with SessionLocal() as db:
        req = _get_req(db, rid)
        if action == "mark_sent" and req.status in ("approved", "sent"):
            req.status, req.sent_at = "sent", now()
            add_event(db, req, user.name, "Marked as sent outside the dashboard.")
        elif action == "decline":
            req.status = "declined"
            add_event(db, req, user.name, "Request declined.")
        elif action == "reopen":
            req.status = "draft" if req.result_json else "received"
            add_event(db, req, user.name, "Request reopened.")
        else:
            raise HTTPException(400, "That action is not available for this request.")
        db.commit()
    return RedirectResponse(f"/admin/requests/{rid}", status_code=303)


@app.post("/admin/requests/{rid}/notes")
def save_notes(request: Request, rid: int, internal_notes: str = Form(""), csrf: str = Form(""), user: User = Depends(current_user)):
    check_csrf(request, csrf)
    with SessionLocal() as db:
        req = _get_req(db, rid)
        req.internal_notes = internal_notes[:10000]
        db.commit()
    _flash(request, "Notes saved.")
    return RedirectResponse(f"/admin/requests/{rid}", status_code=303)


@app.get("/admin/new", response_class=HTMLResponse)
def new_request_page(request: Request, user: User = Depends(current_user)):
    example = {
        "company": "", "site_name": "", "city": "Riyadh", "sector": "cement",
        "heat_sources": [{"name": "Preheater exhaust", "mass_flow_kg_s": 120, "temp_in_c": 330, "min_outlet_c": 210, "dust": "high"}],
        "operating_hours": 7800, "electricity_value_sar_kwh": 0.18, "value_basis": "electricity",
    }
    return render(request, "new.html", user=user, example=json.dumps(example, indent=2), error=None)


@app.post("/admin/new")
def new_request(request: Request, contact_name: str = Form(...), contact_email: str = Form(...), input_json: str = Form(...),
                csrf: str = Form(""), user: User = Depends(current_user)):
    check_csrf(request, csrf)
    try:
        data = json.loads(input_json)
        site = SiteInput(**data)
    except (json.JSONDecodeError, ValidationError) as e:
        return render(request, "new.html", user=user, example=input_json, error=str(e)[:800])
    with SessionLocal() as db:
        req = StudyRequest(contact_name=contact_name.strip(), contact_email=contact_email.strip(), company=site.company,
                           site_name=site.site_name, input_json=site.model_dump(), status="received")
        db.add(req)
        db.flush()
        add_event(db, req, user.name, "Request entered by the team.")
        compute(db, req, user.name)
        db.commit()
        rid = req.id
    return RedirectResponse(f"/admin/requests/{rid}", status_code=303)


@app.get("/admin/inquiries", response_class=HTMLResponse)
def inquiries(request: Request, user: User = Depends(current_user)):
    with SessionLocal() as db:
        items = db.scalars(select(Inquiry).order_by(Inquiry.created_at.desc()).limit(500)).all()
    return render(request, "inquiries.html", user=user, items=items)


@app.post("/admin/inquiries/{iid}")
def inquiry_status(request: Request, iid: int, status: str = Form(...), csrf: str = Form(""), user: User = Depends(current_user)):
    check_csrf(request, csrf)
    if status not in ("new", "handled"):
        raise HTTPException(400, "Unknown status.")
    with SessionLocal() as db:
        inq = db.get(Inquiry, iid)
        if inq:
            inq.status = status
            db.commit()
    return RedirectResponse("/admin/inquiries", status_code=303)


@app.get("/admin/team", response_class=HTMLResponse)
def team(request: Request, user: User = Depends(current_user)):
    with SessionLocal() as db:
        users = db.scalars(select(User).order_by(User.created_at)).all()
    return render(request, "team.html", user=user, users=users, flash=request.session.pop("flash", None))


@app.post("/admin/team")
def add_member(request: Request, name: str = Form(...), email: str = Form(...), password: str = Form(...),
               csrf: str = Form(""), user: User = Depends(current_user)):
    check_csrf(request, csrf)
    email = email.strip().lower()
    if len(password) < 10:
        _flash(request, "Use a password of at least 10 characters.")
        return RedirectResponse("/admin/team", status_code=303)
    with SessionLocal() as db:
        if db.scalar(select(User).where(User.email == email)):
            _flash(request, "A team account with that email already exists.")
        else:
            db.add(User(email=email, name=name.strip(), password_hash=hash_password(password)))
            db.commit()
            _flash(request, f"Added {name.strip()}. Share the password with them privately.")
    return RedirectResponse("/admin/team", status_code=303)


@app.post("/admin/password")
def change_password(request: Request, current: str = Form(...), new: str = Form(...), csrf: str = Form(""),
                    user: User = Depends(current_user)):
    check_csrf(request, csrf)
    with SessionLocal() as db:
        u = db.get(User, user.id)
        if not verify_password(current, u.password_hash):
            _flash(request, "Your current password was not correct.")
        elif len(new) < 10:
            _flash(request, "Use a new password of at least 10 characters.")
        else:
            u.password_hash = hash_password(new)
            db.commit()
            _flash(request, "Password changed.")
    return RedirectResponse("/admin/team", status_code=303)


# ---------------------------------------------------------------- website (mounted last)
app.mount("/", StaticFiles(directory=str(config.SITE_DIR), html=True), name="site")
