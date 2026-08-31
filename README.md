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
