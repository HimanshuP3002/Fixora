# Fixora

Fixora is a Django-based civic operations and issue management platform built for hackathons, smart governance demos, and operational dashboards. It combines a modern Tailwind-powered UI with MongoDB-backed business data, role-aware workflows, AI review tooling, reporting, notifications, and admin-driven system settings.

## Highlights

- Modern Django project structure with a custom dashboard UI
- Tailwind CSS integration with reusable layouts and components
- MongoDB-backed DAO/service layer for operational data
- Role-based experiences for simple users, authority users, moderators, editors, and super admins
- AI review queue with approve, correct, reject, and export flows
- Report analytics, performance, and overview pages
- Notification center with read, bulk update, and delete actions
- Settings center with Mongo-backed configuration and logo upload
- Allauth integration for authentication scaffolding

## Tech Stack

- Python
- Django 6
- MongoDB Atlas with `pymongo`
- SQLite for Django default/local data
- Tailwind CSS via `django-tailwind`
- `django-allauth`
- `django-browser-reload`
- Alpine.js-style frontend behavior embedded in templates

## Project Structure

```text
Fixora/
├── core/                 # Django project settings, urls, ASGI/WSGI
├── main/                 # Main app: views, Mongo DAO logic, business flows
├── design/               # Tailwind app
├── templates/            # Shared layouts and page templates
├── static/               # Project static assets
├── media/                # Uploaded files (created at runtime)
├── manage.py
└── requirements.txt
```

## Core Modules

- `core/settings.py`
  Project settings, allauth, static/media config, and Mongo connection config.

- `main/views.py`
  Function-based views, dashboard pages, settings APIs, notification views, and AI review endpoints.

- `main/models.py`
  Django model stubs where needed plus MongoDB DAO-style operational classes such as:
  - `CivilOperation`
  - `UserOperation`
  - `NotificationOperation`
  - `AIReviewOperation`
  - `SystemSettingsDAO`

- `templates/`
  Shared layouts, auth pages, dashboards, reports, settings, notifications, and legal pages.

## Features

### Authentication

- Login and registration pages
- Django allauth integration
- role/session-aware navigation

### Issue Management

- report issues
- issue overview and detail flows
- issue management dashboards
- map view and user issue tracking

### Reports

- report creation
- reports overview
- reports analytics
- reports performance

### AI Review

- AI review queue
- approve/correct/reject endpoints
- export approved training data

### Notifications

- user notifications
- admin/system notification views
- unread counts
- mark-as-read and delete flows

### Settings

- Mongo-backed system settings
- maintenance mode
- festival theme settings
- AI system settings
- logo upload support

## Roles

The app is structured to support multiple roles:

- `Simple User`
- `Authority`
- `Editor`
- `Moderator`
- `Super Admin`
- `Admin User`

Views and notification flows are designed around role-based access checks and session-driven navigation.

## Local Setup

### 1. Clone the repository

```bash
git clone https://github.com/HimanshuP3002/Fixora.git
cd Fixora
```

### 2. Create and activate a virtual environment

Windows PowerShell:

```powershell
python -m venv .env
.env\Scripts\activate

# Linux
#source venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure MongoDB connection

Fixora reads Mongo configuration from `core/settings.py` and environment variables.

Recommended environment variables:

```powershell
$env:MONGO_DB_USER="your_username"
$env:MONGO_DB_PASSWORD="your_password"
$env:MONGO_CLUSTER="cluster0.va3thzm.mongodb.net"
```

Or provide a full URI:

```powershell
$env:MONGO_URI="mongodb+srv://username:password@cluster.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"
```

### 5. Run migrations

```bash
python manage.py migrate
```

### 6. Start the development server

```bash
python manage.py runserver
```

## Tailwind Setup

Install Tailwind dependencies:

```bash
python manage.py tailwind install
```

Start Tailwind watcher:

```bash
python manage.py tailwind start
```

If you use standalone Tailwind mode or a custom setup, align it with your local environment first.

## Static and Media

Configured in `core/settings.py`:

- `STATIC_URL = 'static/'`
- `STATICFILES_DIRS = [BASE_DIR / 'static']`
- `STATIC_ROOT = BASE_DIR / 'static' / 'staticfiles'`
- `MEDIA_URL = 'media/'`
- `MEDIA_ROOT = BASE_DIR / 'media'`

In development, media files are served through `core/urls.py` when `DEBUG = True`.

## Important Routes

Some notable application routes:

- `/login/`
- `/register/`
- `/report_issues/`
- `/my_issues/`
- `/map_view/`
- `/notification/`
- `/fetch_issue_admin/`
- `/reports/`
- `/ai-review/`
- `/settings/`

API routes:

- `/api/ai-review/queue/`
- `/api/ai-review/approve/`
- `/api/ai-review/correct/`
- `/api/ai-review/reject/`
- `/api/ai-review/export/`
- `/api/settings/`
- `/api/settings/update/`
- `/api/settings/reset/`

## Environment Notes

- The project currently mixes Django ORM and MongoDB-backed DAO logic.
- Business data is primarily handled through MongoDB service classes.
- Some authentication/session behavior is custom and role-aware.
- Browser reload and allauth are configured for local development.

## Development Tips

- Use `python -m py_compile main\models.py` and `python -m py_compile main\views.py` for quick syntax checks.
- Keep Mongo credentials out of source code in production.
- Prefer environment variables for database secrets.
- If Tailwind or Django commands fail, verify the virtual environment is active.

## Security Notes

Before deploying:

- move secrets out of `settings.py`
- disable `DEBUG`
- set proper `ALLOWED_HOSTS`
- replace any hardcoded credentials
- use production-grade media/static handling

## Current Status

Fixora is currently structured as a strong prototype / hackathon-grade platform with:

- polished frontend direction
- Mongo-backed operational services
- admin and AI review tooling
- room for production hardening and cleanup

## License

Add your project license here.
