# Hall Seat Management System

A Django-based seat allocation and management system for university halls.

## Prerequisites

- Python 3.12+
- PostgreSQL 14+
- Node.js 18+ (for Tailwind CSS)
- pip

## Installation

### 1. Clone & setup Python environment

```bash
git clone <repo-url>
cd hallseatmanagement

python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # Linux/Mac

pip install -r requirements.txt
```

### 2. Environment variables

Copy `.env.example` to `.env` and update values:

```bash
cp .env.example .env
```

Key variables:

| Variable | Default | Production | Description |
|----------|---------|------------|-------------|
| `POSTGRES_DB` | `hallseatmanagment` | `hallseatmanagment` | Database name |
| `POSTGRES_USER` | `postgres` | `postgres` | Database user |
| `POSTGRES_PASSWORD` | `1232` | _(set via env)_ | Database password |
| `POSTGRES_HOST` | `localhost` | `host.docker.internal` | Database host |
| `POSTGRES_PORT` | `5432` | `5432` | Database port |
| `BASE_PATH` | _(empty)_ | `sam` | URL sub-path prefix |

> **Production note:** In Docker, PostgreSQL runs in a separate container. Use `host.docker.internal` as `POSTGRES_HOST` so Django connects to the DB via the Docker network.

### BASE_PATH

`BASE_PATH` sets a URL prefix for the entire application. When set to `sam`, all routes are served under `/sam/`:

| Route | Without BASE_PATH | With BASE_PATH=sam |
|-------|-------------------|---------------------|
| Dashboard | `/` | `/sam/` |
| Login | `/accounts/login/` | `/sam/accounts/login/` |
| Admin | `/admin/` | `/sam/admin/` |
| Manage panel | `/manage/` | `/sam/manage/` |
| Allocations | `/allocations/` | `/sam/allocations/` |

This is used when the app is deployed behind a reverse proxy (Traefik) at a sub-path, e.g. `https://proto.cu.ac.bd/sam/`.

### 3. Database setup

Create the PostgreSQL database:

```sql
CREATE DATABASE hallseatmanagment;
```

### 4. Install frontend dependencies

```bash
npm install
```

## Migrations

### Run all migrations

```bash
python manage.py migrate
```

### Run migrations for a specific app

```bash
python manage.py migrate hsm
python manage.py migrate accounts
python manage.py migrate allocations
python manage.py migrate adminpanel
python manage.py migrate halls
python manage.py migrate students
python manage.py migrate slips
python manage.py migrate dashboard
```

### Show migration status

```bash
python manage.py showmigrations
```

### Roll back to a specific migration

Revert a single app to a previous migration state:

```bash
python manage.py migrate <app_name> <migration_name>
```

Examples:

```bash
# Roll back accounts app to its initial migration
python manage.py migrate accounts 0001_initial

# Roll back allocations to before the last migration
python manage.py migrate allocations 0004_previous_migration_name

# Roll back everything to a clean state (nuclear option)
python manage.py migrate hsm zero
```

> **Reference:** [How to Revert a Migration in Django - FreeCodeCamp](https://www.freecodecamp.org/news/how-to-revert-a-migration-in-django/)

### Create new migrations after model changes

```bash
python manage.py makemigrations
python manage.py migrate
```

## Tailwind CSS

The project uses Tailwind CSS 3.x compiled locally (no CDN).

### Build for production

```bash
npx tailwindcss -i static/css/input.css -o static/css/dist.css --minify
```

### Watch mode during development

```bash
npx tailwindcss -i static/css/input.css -o static/css/dist.css --watch
```

After building, collect static files:

```bash
python manage.py collectstatic --noinput
```

## Running the development server

```bash
python manage.py runserver
```

Access at: `http://127.0.0.1:8000/`

| URL | Description |
|-----|-------------|
| `/` | Dashboard |
| `/admin/` | Django admin (superuser only) |
| `/manage/` | Custom admin panel |
| `/allocations/` | Seat allocation |
| `/slips/` | Hall slips |
| `/accounts/login/` | Login |

## Create superuser

```bash
python manage.py createsuperuser
```

## Seed data

Seed commands are idempotent and ordered — halls must exist before managers can be created.

### Required order

```bash
python manage.py migrate              # one squashed 0001_initial per app
python manage.py seed_hall            # 1. halls + demo blocks/floors/rooms/seats
python manage.py seed_reasons         # 2. seat-release reasons (allocations)
python manage.py seed_admin           # 3. Admin group + demo admins (optional)
python manage.py seed_managers        # 4. hall managers — requires halls!
# students are now imported from CSV in production; seed_students was removed
```

### 1. `seed_hall` — halls only (with confirmation)

```bash
python manage.py seed_hall                 # prompts: "Type yes to confirm"
python manage.py seed_hall --no-input      # skip prompt (automation)
python manage.py seed_hall --clear         # drop only (wipe)
python manage.py seed_hall --clear --no-input
```

- Source: `halls/management/commands/seed_hall.py:1` (`HALL_DATA` — 17 CU halls).
- Creates **only `Hall` rows** (no blocks/floors/rooms/seats — per latest spec). Previous demo structure removed.
- **Destructive + confirmed:** both `seed` and `--clear` prompt `Type "yes" to confirm [y/N]:` via `_confirm()` (`seed_hall.py:55`); use `--no-input`/`-y`/`--yes` to bypass (`seed_hall.py:27`). `_wipe_demo_data()` (`seed_hall.py:72`) deletes all existing `Hall` and dependent `Slip`/`SlipItem` (PROTECT), `SeatAssignment/Log/Maintenance`, `HallAllocation`, `Seat`/`Room`/`Floor`/`Block` before (re)creating.
- `--clear` (`seed_hall.py:24`) = reverse/drop: wipes all hall-associated data and exits (e.g. `python manage.py seed_hall --clear` → `Seed hall data wiped/cleared (reverse) …`). Same wipe is used before seeding, so re-running `seed_hall` is a reset.
- Re-run to reset hall layout; next step is `seed_managers`.

### 2. `seed_reasons` — seat release reasons

```bash
python manage.py seed_reasons
```

- Source: `allocations/management/commands/seed_reasons.py:5` (`REASONS` — 6 Bengali reasons, idempotent `update_or_create` ordered by `sort_order`).
- Replaces the old `allocations/migrations/0003_seed_release_reasons.py` data migration. Run after every fresh `migrate`.

### 3. `seed_admin` — Admin group + demo admins

```bash
python manage.py seed_admin
python manage.py seed_admin --count 1 --password 'MyPass@123'
```

- Source: `accounts/management/commands/seed_admin.py:1`.
- Creates/updates the `Admin` group (full CRUD on halls/students/allocations without superuser) and demo users (`forkan.ict@cu.ac.bd`, `shimul.ict@cu.ac.bd`, `tonmoy.ict@cu.ac.bd`, `sayedurrchowdhury@cu.ac.bd`). Default ` --count 2` creates first two; re-run with `--count 4` to create all 4 sample admins. Default password `SamAdmin@202609`, `is_staff=True`, `managed_hall=None` (global).
- Options: `--count 1|2|3|4`, `--password <str>`, `--clear` to drop. Superusers remain separate (`createsuperuser`). First run creates 2, second run with `--count 4` creates remaining.

### 4. `seed_managers` — hall managers (depends on halls)

> **What the error means:** `seed_managers` reads `halls_hall`. The message
> `No halls with codes found. Run 'python manage.py seed_hall' first or pass '--halls <code1> <code2> ...'.` (`accounts/management/commands/seed_managers.py:92`) means the DB has no `Hall` rows (fresh DB or after wipe). Fix: run `seed_hall` first, or pass explicit codes that already exist. The second error `Hall with code "X" does not exist. Run seed_hall first.` (`seed_managers.py:99`) means the specific code you passed wasn't found.

```bash
# auto — uses first two hall codes from DB (requires seed_hall)
python manage.py seed_managers

# explicit — pass hall codes (code + hall_type is unique). Case-insensitive,
# so upper or lower both work; codes are normalized via code__iexact
# Email is derived from the hall code: HALAFR -> hallafr@cu.ac.bd
# Duplicates get numeric suffix: HALAFR HALAFR HALKHZ -> hallafr@cu.ac.bd, hallafr1@cu.ac.bd, halkhz@cu.ac.bd
python manage.py seed_managers --halls HALAFR HALAFR HALKHZ
python manage.py seed_managers --halls halafr halafr halkhz   # same (lower-case)
python manage.py seed_managers --halls HALALA HALSJL --password 'MyPass@123'
python manage.py seed_managers --halls HALALA HALSJL --phone '+8801670502283'

# typical fresh bootstrap
python manage.py seed_hall                                      # creates 17 CU halls; sample codes: HALALA, HALAFR, HALSJL, ...
python manage.py seed_managers --halls HALALA HALSNR           # -> halala@cu.ac.bd, halsnr@cu.ac.bd
python manage.py seed_managers --halls halala halafr halsur    # lower-case also works
```

- Source: `accounts/management/commands/seed_managers.py:1`.
- For each hall code: email = `<hall_code_lower>@cu.ac.bd` (`HALAFR` → `hallafr@cu.ac.bd`); duplicate codes get suffix (`HALAFR HALAFR` → `hallafr@cu.ac.bd`, `hallafr1@cu.ac.bd`, next `hallafr2@cu.ac.bd` …) (`seed_managers.py:60`). Full name `Hall Manager <CODE>`, `managed_hall` FK set. Default password `SamHallManager@202609`, default phone `+8801670502283` (`seed_managers.py:8`), domain `@cu.ac.bd` (case-insensitive lookup `seed_managers.py:97`). Phone is unique in `accounts_user.phone`; if the default is already taken, a sequential variant is auto-generated (`+88016705022831`, …) to satisfy the DB constraint.
- Options: `--halls <code ...>` (default: first 2 codes in DB, any case, duplicates allowed), `--password <str>`, `--phone <str>`, `--clear` to drop previous managers. Uses `update_or_create` — safe to re-run. Sample hall codes from `seed_hall` (`halls/management/commands/seed_hall.py:9`): `HALALA`, `HALAFR`, `HALSJL`, `HALSMT`, `HALSUH`, `HALSNR`, `HALRAB`, `HALPRT`, `HALKHZ`, `HALBIJ`, `HALFRD`, `HALATS`, `HALFAZ`, `HALSUR`, `HALRCH`.
- `python manage.py seed_managers --clear` clears previous demo managers (users with `managed_hall` set) before re-seeding — run this first if you have old `manager.*@cu.ac.bd` data.
- After seeding, log in as `hallafr@cu.ac.bd` / `SamHallManager@202609` (or `hallafr1@cu.ac.bd`, `halkhz@cu.ac.bd`, …).

### Students

`students/management/commands/seed_students.py` was removed. Populate `students_student` via CSV import in production instead of code seed.

## Docker deployment

```bash
docker compose up -d --build
```

Production `.env` values for Docker:

```
POSTGRES_HOST=host.docker.internal
BASE_PATH=sam
```

Services:

- **app** - Django + Gunicorn (port 8000)
- **db** - PostgreSQL 16
- **traefik** - Reverse proxy with Let's Encrypt

## Project structure

```
hallseatmanagement/
├── hsm/                  # Project settings, urls, wsgi
├── accounts/             # Custom user model, auth backends
├── halls/                # Hall data models
├── allocations/          # Seat allocation logic
├── dashboard/            # Home dashboard
├── students/             # Student data
├── adminpanel/           # Custom admin panel (/manage/)
├── slips/                # Hall slip generation
├── templates/            # Global templates
├── static/               # Static assets (CSS, fonts, images, JS)
│   ├── css/
│   │   ├── dist.css          # Compiled Tailwind output
│   │   ├── input.css         # Tailwind source
│   │   └── inter-font.css    # Inter font-face
│   ├── fonts/inter/          # Inter font files
│   ├── images/               # Logo, etc.
│   └── js/                   # JavaScript
├── manage.py
├── requirements.txt
├── tailwind.config.js
├── Dockerfile
└── docker-compose.yml
```
