"""Server checks: public API, login, review flow, PDF."""
import os
import re

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_heatharvest.db")
os.environ.setdefault("ADMIN_EMAIL", "admin@test.local")
os.environ.setdefault("ADMIN_PASSWORD", "a-long-test-password")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

STUDY = {"contact": {"name": "Eng. Test", "email": "eng@client.example"}, "consent": True,
         "site": {"company": "Client Co", "site_name": "Line 1", "city": "Dammam", "sector": "glass",
                  "heat_sources": [{"name": "Furnace flue", "mass_flow_kg_s": 45, "temp_in_c": 450, "dust": "medium"}]}}


@pytest.fixture(scope="module")
def client():
    if os.path.exists("test_heatharvest.db"):
        os.remove("test_heatharvest.db")
    with TestClient(app) as c:
        yield c
    os.remove("test_heatharvest.db")


def login(c):
    tok = re.search(r'name="csrf" value="([^"]+)"', c.get("/admin/login").text).group(1)
    r = c.post("/admin/login", data={"email": "admin@test.local", "password": "a-long-test-password", "csrf": tok}, follow_redirects=False)
    assert r.status_code == 303


def test_site_pages(client):
    assert client.get("/").status_code == 200
    assert client.get("/study.html").status_code == 200
    assert client.get("/no-such-page").status_code == 404


def test_dashboard_needs_login(client):
    assert client.get("/admin", follow_redirects=False).status_code == 303
    assert client.get("/admin/requests/1/study.pdf", follow_redirects=False).status_code == 303


def test_wrong_password(client):
    tok = re.search(r'name="csrf" value="([^"]+)"', client.get("/admin/login").text).group(1)
    r = client.post("/admin/login", data={"email": "admin@test.local", "password": "wrong", "csrf": tok})
    assert "do not match" in r.text


def test_study_flow(client):
    r = client.post("/api/study-requests", json=STUDY)
    assert r.status_code == 200 and r.json()["ok"]
    rid = r.json()["id"]
    login(client)
    page = client.get(f"/admin/requests/{rid}").text
    assert "Client Co" in page
    tok = re.search(r'name="csrf" value="([^"]+)"', page).group(1)
    draft = client.get(f"/admin/requests/{rid}/study.pdf")
    assert draft.status_code == 200 and draft.content[:4] == b"%PDF"
    assert client.post(f"/admin/requests/{rid}/approve", data={"csrf": tok}, follow_redirects=False).status_code == 303
    assert "Approved by" in client.get(f"/admin/requests/{rid}").text
    assert client.post(f"/admin/requests/{rid}/approve", data={"csrf": "forged"}).status_code == 400


def test_bad_study_is_rejected(client):
    bad = dict(STUDY, site=dict(STUDY["site"], city="Nowhere"))
    r = client.post("/api/study-requests", json=bad)
    assert r.status_code == 422 and r.json()["errors"]


def test_inquiry(client):
    assert client.post("/api/inquiries", json={"name": "A", "email": "a@b.co", "message": "Hi"}).json()["ok"]
    assert client.post("/api/inquiries", json={"name": "A", "email": "not-an-email"}).status_code == 422
