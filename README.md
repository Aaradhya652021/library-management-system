# Library Management System (LMS)

A Flask web application for running a library: manage the book catalogue and members, issue and return books, track reading progress, and get personalised book recommendations from a hybrid machine-learning model.

## Features

- **Two role-based areas** — librarians/admins and members have separate logins, with hashed passwords, CSRF protection and hardened session cookies.
- **Catalogue & member management** — add, edit and remove books and members, with copy-level availability tracking.
- **Loans & fines** — 14-day loan period, overdue tracking and automatic fines of ₹5 per day on return.
- **Member dashboard** — current loans, borrowing history and a reading-progress badge that advances from *Newcomer* to *Scholar*.
- **Ratings & feedback** — members rate and comment on books; admins see rating consensus and feedback panels.
- **Hybrid recommendations** — content similarity + SVD collaborative filtering + a popularity prior, served lazily from a pretrained model (no full N×N similarity matrix built at request time).
- **User segmentation** — KMeans clusters over synthetic feedback, with segment exploration pages for admins.
- **Optional public sharing** — run behind a Waitress server and expose a temporary HTTPS URL through a Cloudflare quick tunnel.

## Tech stack

| Layer | Technologies |
| --- | --- |
| Backend | Python 3.10+, Flask 3, Flask-WTF, Werkzeug |
| Database | MySQL 8, `mysql-connector-python` |
| ML | pandas, numpy, scipy, scikit-learn, joblib |
| Serving | Waitress, Cloudflare tunnel (optional) |
| Tests | pytest |

## Project layout

```
app.py                     Flask app, routes, admin/member dashboards
auth_utils.py              Login and role guards
db.py                      MySQL connection helper
recs.py                    Recommendation, feedback and segment routes
recommender.py             Lazy hybrid recommender service
progress.py                Reading-level/progress calculations
schema.sql                 Base MySQL schema (structure only)
migrations/                Idempotent migration for feedback/segment tables
Machine_Learning/          Pretrained model, book catalog and research notebook
scripts/                   Migration, demo seeding, admin password and public-run helpers
templates/, static/        Jinja templates and CSS
tests/                     pytest suite for recommender and progress logic
PUBLIC_HOSTING.md          Guide for the Cloudflare tunnel setup
```

## Getting started

### 1. Clone and install dependencies

```powershell
git clone https://github.com/<your-username>/library-management-system.git
cd library-management-system
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### 2. Configure the database

Create an empty MySQL database and copy the environment template:

```powershell
# In MySQL: CREATE DATABASE library_management_system CHARACTER SET utf8mb4;
Copy-Item .env.example .env
```

Edit `.env` with your MySQL credentials and a random `SECRET_KEY`. Credentials are loaded only from the environment/`.env`; there is no hard-coded password fallback.

Load the base schema and then the idempotent ML migration:

```powershell
# From a PowerShell prompt with mysql on PATH, or use MySQL Workbench:
mysql -u root -p library_management_system < schema.sql

.\.venv\Scripts\python.exe scripts\migrate.py
.\.venv\Scripts\python.exe init_admin.py
```

`init_admin.py` creates the default `admin` / `admin@123` account. **Change this password before exposing the app:**

```powershell
.\.venv\Scripts\python.exe scripts\set_admin_password.py
```

### 3. Run locally

```powershell
.\.venv\Scripts\python.exe app.py
```

Open <http://127.0.0.1:5000/>. The app opens Chrome automatically in development mode.

### 4. Optional demo data

```powershell
.\.venv\Scripts\python.exe scripts\seed_demo.py --yes
```

This adds isolated demo members, books, issues and ratings so recommendations and dashboard charts have data. Demo members use `demo.*@example.com` addresses and the password `demo1234`. Remove them later with `--remove`.

### 5. Run the tests

```powershell
.\.venv\Scripts\python.exe -m pytest
```

## Public access

`start_public.bat` (or `python scripts/run_public.py`) serves the app with Waitress and creates a temporary `https://<random>.trycloudflare.com` URL. The URL is printed and written to `public_url.txt`. It changes on every restart, and the computer must stay online. The `tools/cloudflared.exe` binary is **not** included in this repository — download it from [Cloudflare](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/) and place it there, or set `CLOUDFLARED_PATH`. See [PUBLIC_HOSTING.md](PUBLIC_HOSTING.md) for details.

## Notes on committed files

`.env`, `backup_before_ml.sql` (a dump containing real data), `public_url.txt`, the generated demo manifest, logs and `tools/cloudflared.exe` are deliberately gitignored. Only the data-free `schema.sql` and the pretrained model/catalog files needed by the recommender are versioned.
