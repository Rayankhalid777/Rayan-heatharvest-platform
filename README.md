# HeatHarvest platform

The full HeatHarvest system: the public website, a server that does the engineering calculations, the study generator, and a team dashboard.

## How it works

1. **Visitor uses the estimator** on the home page. The server calculates the quick estimate.
2. **Visitor sends site data** through the study form (`/study.html`): company, city, industry, each hot exhaust stream (flow, temperature, dust), running hours, the value of energy, available space.
3. **The server runs the full study straight away** with the HeatHarvest Insight engine and saves it as a draft. The client gets a confirmation email; the team gets a notification.
4. **An engineer reviews it in the dashboard** (`/admin`): checks the result and the warnings, corrects any inputs and recalculates if needed, opens the draft PDF, then approves it.
5. **The approved study is emailed to the client** as a branded PDF, from the dashboard. Everything is recorded in the request's activity log.

Contact-form messages from the home page also arrive in the dashboard under Inquiries.

## What the engine calculates

Per site, in `app/engine/`:

- **Heat available** from each stream, down to its lowest allowed outlet temperature (acid dew point, raw-mill drying needs; typical values by industry when the client leaves it empty).
- **Plant configuration:** direct exchange for a single clean stream up to 380 °C; otherwise a thermal-oil loop collecting heat from all streams.
- **ORC cycle with real fluid properties** (CoolProp): isopentane, cyclopentane, siloxane MM and toluene are each tried over a range of evaporating temperatures, with a recuperator, pinch limits on every exchanger, and an air-cooled condenser 15 K above ambient. The best net output wins.
- **Own consumption:** feed pump, condenser fans, oil pump, extra exhaust fan power.
- **Saudi climate:** output is recalculated for each month at the city's mean temperature, giving the summer loss and the annual energy.
- **Limits:** 0.5 MWe smallest unit, 20 MWe largest single unit, plot area needed against the area available.
- **Economics:** investment (indicative cost curve with a breakdown), O&M, value of electricity or of gas saved at a chosen price, NPV, IRR, payback, cost of electricity, CO₂, each for a cautious, expected and favourable case.
- **Verdict:** recommended, promising, not economic, too small or too cold. It never recommends a project with a negative NPV.

Checked against Saudi Arabia's first cement ORC plant (about 10,000 t/d clinker, 13 MW, about 80 GWh a year): the engine gives about 10.6–10.9 MWe and 80–82 GWh a year for similar inputs.

### Values to replace when supplier data arrives

| What | Where |
| --- | --- |
| Installed cost curve and its breakdown | `app/engine/economics.py` (`CAPEX_REF_USD_PER_KW`, `CAPEX_SCALE_EXP`, `CAPEX_SHARES_*`) |
| Turbine, pump and generator efficiencies | `app/engine/cycle.py` |
| Condenser approach, pinch limits, fan and pump power, plot area per MWe | top of `app/engine/study.py` |
| Climate data (approximate monthly means; replace with station data) | `app/engine/climate.py` |

Change the version number in `app/engine/study.py` (`ENGINE_VERSION`) when you change the engine, so each study records which version produced it.

## Put it online on Render

The site needs a server, so it runs on Render instead of a static host. Render's Starter web service plus a small database costs roughly USD 7–25 a month; check Render's current prices.

1. Create a free GitHub account if you do not have one, create a private repository, and upload this whole folder to it.
2. Create a Render account (render.com) and connect GitHub.
3. In Render choose **New → Blueprint**, pick the repository. Render reads `render.yaml` and creates the web service and the PostgreSQL database.
4. When asked, fill in:
   - `SITE_URL`: your address, for example `https://www.heatharvest.sa`
   - `ADMIN_EMAIL`, `ADMIN_PASSWORD`, `ADMIN_NAME`: the first team account (password of at least 10 characters)
   - the email settings (below), or leave them empty for now
5. Wait for the first deploy, then open `https://<your-service>.onrender.com/admin` and sign in. Add the rest of the team under **Team**.

### Connect your domain

In Render: the web service → **Settings → Custom Domains → Add**. Enter your domain and `www.` version, then add the DNS records Render shows at your domain registrar. Render issues the HTTPS certificate automatically. Then set `SITE_URL` to the new address and replace `https://www.heatharvest.example/` in `site/index.html` (4 places), `site/robots.txt` and `site/sitemap.xml`.

### Email

Studies and notifications are sent through any SMTP mail service. Once you have the domain, the simplest is a mailbox on it (Google Workspace, Microsoft 365 or Zoho Mail), for example `studies@yourdomain`. Enter its SMTP settings on Render: `SMTP_HOST`, `SMTP_PORT` (587), `SMTP_USER`, `SMTP_PASSWORD`, `MAIL_FROM`, and `TEAM_NOTIFY_EMAIL` for the address that should hear about new requests.

Until email is set up, everything else works: requests arrive in the dashboard, and you download the PDF and send it yourself, then click **mark as sent**.

## Run it on a computer

```
pip install -r requirements-dev.txt
cp .env.example .env        # then edit the values; DATABASE_URL can stay empty
export $(grep -v '^#' .env | xargs)
uvicorn app.main:app --reload
```

Open http://localhost:8000 for the website and http://localhost:8000/admin for the dashboard. Run the tests with `pytest`.

## Before launch

- Confirm with the team: the team list and the Ministry of Energy grant line on the home page; the promise to send studies "within a few days".
- Check the default electricity value (0.18 SAR/kWh) against the current SEC industrial tariff.
- The study PDF is signed by Prof. Awad Alquaity by default; change `SIGNATORY_*` on Render if needed.
- A privacy statement covering the site data clients send is advisable.
