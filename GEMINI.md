# BEMS 2.0 (Biomedical Equipment Management System)

## Project Overview
BEMS 2.0 is a Flask-based application designed for managing biomedical equipment, departments, maintenance tasks, and repairs.

## Tech Stack
- **Backend:** Flask
- **Database:** SQLite with Flask-SQLAlchemy
- **Data Processing:** Pandas, openpyxl (Excel), CSV
- **Reports:** ReportLab (PDF generation)
- **Scheduling:** `schedule` library for automated maintenance tasks
- **Deployment:** Waitress (WSGI server)

## Architecture
- `app.py`: Contains the core application logic, database models, and route definitions.
- `templates/`: HTML templates using Jinja2.
- `static/`: Static assets (CSS, JS, images).
- `backups/`: Stores database backups.
- `uploads/`: Directory for processed equipment lists.
- `wsgi.py`: Entry point for production WSGI servers.

## Conventions & Standards
- **Database Models:** All models should be defined in `app.py` using Flask-SQLAlchemy.
- **Dates:** Dates and timestamps are primarily stored as strings (`db.String(50)`) formatted as `%Y-%m-%d %H:%M:%S`.
- **Authentication:** Use the custom `@login_required` decorator for protected routes.
- **Error Handling:** Use Flask's `flash` message system for user feedback.
- **File Handling:** Secure filenames using `werkzeug.utils.secure_filename` before saving to `uploads/`.

## Development Workflow
- **Dependencies:** Managed via `req.txt`.
- **Environment:** Use a virtual environment.
- **Database Initialization:** The database (`bems.db`) is initialized automatically on app startup if it doesn't exist.
- **Running Locally:** `python app.py` runs the development server.
- **Production:** Use `waitress-serve` as configured in `wsgi.py`.
