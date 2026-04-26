from flask import Flask, render_template, request, redirect, session, send_file, make_response, jsonify, flash
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
import webbrowser
import os
import bcrypt
from functools import wraps
import pandas as pd
from werkzeug.utils import secure_filename
import csv
from io import StringIO, BytesIO
import shutil
import glob
import schedule
import threading
import time

# ===== APP CONFIGURATION =====
app = Flask(__name__)
app.secret_key = "your-secret-key-change-this-in-production"

# Force database to be in main project folder
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
db_path = os.path.join(BASE_DIR, 'bems.db')
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['PERMANENT_SESSION_LIFETIME'] = 28800

# Upload configuration
UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'csv', 'xlsx', 'xls'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

# Create folders
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs('backups', exist_ok=True)

db = SQLAlchemy(app)

# ===== DATABASE MODELS =====

class Department(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    description = db.Column(db.String(200))
    created_at = db.Column(db.String(50), default=lambda: datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    equipments = db.relationship('Equipment', backref='department_obj', lazy=True)

class Equipment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))
    model_no = db.Column(db.String(100))
    company = db.Column(db.String(100))
    serial_no = db.Column(db.String(100))
    quantity = db.Column(db.Integer, default=1)
    department_id = db.Column(db.Integer, db.ForeignKey('department.id'))
    department_name = db.Column(db.String(100))
    status = db.Column(db.String(50))
    install_date = db.Column(db.String(50))
    warranty_date = db.Column(db.String(50))
    last_service = db.Column(db.String(50))
    created_at = db.Column(db.String(50), default=lambda: datetime.now().strftime('%Y-%m-%d %H:%M:%S'))

class Repair(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    equipment_id = db.Column(db.Integer, db.ForeignKey('equipment.id'))
    repair_date = db.Column(db.String(50))
    description = db.Column(db.String(200))
    cost = db.Column(db.Float, default=0)
    technician = db.Column(db.String(100))
    created_at = db.Column(db.String(50), default=lambda: datetime.now().strftime('%Y-%m-%d %H:%M:%S'))

class Task(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200))
    description = db.Column(db.String(500))
    date = db.Column(db.String(50))
    due_date = db.Column(db.String(50))
    priority = db.Column(db.String(20), default='medium')
    status = db.Column(db.String(50), default='pending')
    category = db.Column(db.String(50), default='general')
    equipment_id = db.Column(db.Integer, db.ForeignKey('equipment.id'), nullable=True)
    created_by = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.String(50), default=lambda: datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    completed_at = db.Column(db.String(50), nullable=True)
    notes = db.Column(db.String(500))

class PreventiveMaintenance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    equipment_id = db.Column(db.Integer, db.ForeignKey('equipment.id'), nullable=True)
    equipment_name = db.Column(db.String(100))
    title = db.Column(db.String(200))
    description = db.Column(db.String(500))
    frequency = db.Column(db.String(50))
    interval_days = db.Column(db.Integer)
    last_performed = db.Column(db.String(50))
    next_due = db.Column(db.String(50))
    status = db.Column(db.String(50), default='active')
    assigned_to = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.String(50), default=lambda: datetime.now().strftime('%Y-%m-%d %H:%M:%S'))

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=True)
    password_hash = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(50), default='biomed')
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.String(50), default=lambda: datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    last_login = db.Column(db.String(50))
    
    def set_password(self, password):
        salt = bcrypt.gensalt()
        self.password_hash = bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')
    
    def check_password(self, password):
        try:
            return bcrypt.checkpw(password.encode('utf-8'), self.password_hash.encode('utf-8'))
        except Exception:
            return False

# ===== DECORATORS =====

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            return redirect('/login')
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            return redirect('/login')
        if session.get('role') != 'admin':
            return "Access Denied. Admin privileges required.", 403
        return f(*args, **kwargs)
    return decorated_function

# ===== AUTO-CREATE ADMIN AND DEPARTMENTS =====

def create_default_data():
    with app.app_context():
        if User.query.count() == 0:
            print("=" * 50)
            print("🔧 Creating default admin user...")
            admin = User(username='admin', email='admin@bems.local', role='admin', is_active=True)
            admin.set_password('admin123')
            db.session.add(admin)
            db.session.commit()
            print("✅ Admin user created: admin / admin123")
        
        if Department.query.count() == 0:
            print("🔧 Creating default departments...")
            default_depts = [
                ('ICU', 'Intensive Care Unit'),
                ('Emergency', 'Emergency Department'),
                ('Radiology', 'Medical Imaging Department'),
                ('Operation Theater', 'Surgical Suite'),
                ('General Ward', 'General Patient Ward'),
                ('Laboratory', 'Clinical Laboratory'),
                ('Cardiology', 'Heart Care Department'),
                ('Neurology', 'Brain and Nervous System Department'),
                ('Orthopedics', 'Bone and Joint Department'),
                ('Pharmacy', 'Medication and Supplies')
            ]
            for dept_name, dept_desc in default_depts:
                dept = Department(name=dept_name, description=dept_desc)
                db.session.add(dept)
            db.session.commit()
            print(f"✅ Created {len(default_depts)} default departments")
        print("=" * 50)

# ===== BACKUP SYSTEM =====

BACKUP_FOLDER = 'backups'

def create_backup():
    try:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_filename = f"bems_backup_{timestamp}.db"
        backup_path = os.path.join(BACKUP_FOLDER, backup_filename)
        if os.path.exists('bems.db'):
            shutil.copy2('bems.db', backup_path)
            return backup_filename
        return None
    except Exception as e:
        print(f"Backup failed: {e}")
        return None

def cleanup_old_backups(days_to_keep=30):
    try:
        cutoff_date = datetime.now() - timedelta(days=days_to_keep)
        for backup_file in glob.glob(os.path.join(BACKUP_FOLDER, 'bems_backup_*.db')):
            filename = os.path.basename(backup_file)
            timestamp_str = filename.replace('bems_backup_', '').replace('.db', '')
            backup_date = datetime.strptime(timestamp_str, '%Y%m%d_%H%M%S')
            if backup_date < cutoff_date:
                os.remove(backup_file)
    except Exception:
        pass

def run_scheduled_backups():
    schedule.every().day.at("02:00").do(create_backup)
    schedule.every().sunday.at("03:00").do(cleanup_old_backups)
    while True:
        schedule.run_pending()
        time.sleep(60)

backup_thread = threading.Thread(target=run_scheduled_backups, daemon=True)
backup_thread.start()

# ===== HELPER FUNCTIONS =====

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def map_columns(df_columns):
    column_mappings = {
        'name': ['name', 'equipment name', 'device name', 'item name', 'title'],
        'model_no': ['model', 'model no', 'model number', 'model_no', 'model #'],
        'company': ['company', 'manufacturer', 'brand', 'vendor', 'make'],
        'serial_no': ['serial', 'serial no', 'serial number', 'serial_no', 'sn', 's/n'],
        'quantity': ['quantity', 'qty', 'number', 'count', 'units'],
        'department': ['department', 'dept', 'location', 'unit', 'ward', 'section'],
        'status': ['status', 'condition', 'state', 'working status'],
        'install_date': ['install date', 'installation date', 'date installed', 'install_date'],
        'warranty_date': ['warranty', 'warranty date', 'warranty expiry', 'warranty_date'],
        'last_service': ['last service', 'last maintenance', 'service date', 'last_service']
    }
    mapped = {}
    used_columns = set()
    for field, variations in column_mappings.items():
        found = False
        for col in df_columns:
            if col.lower() in variations and col not in used_columns:
                mapped[field] = col
                used_columns.add(col)
                found = True
                break
        if not found:
            mapped[field] = None
    return mapped

# ===== ROUTES =====

@app.route('/')
@login_required
def index():
    today = datetime.now().strftime('%Y-%m-%d')
    
    # Equipment stats
    total_equipment_count = Equipment.query.count()
    total_quantity = db.session.query(db.func.sum(Equipment.quantity)).scalar() or 0
    under_repair = Equipment.query.filter_by(status="Under Repair").count()
    departments = Department.query.count()
    
    # Task stats
    pending_tasks = Task.query.filter_by(status='pending').count()
    tasks_today = Task.query.filter_by(date=today, status='pending').count()
    
    # PM stats
    pms_due = PreventiveMaintenance.query.filter(
        PreventiveMaintenance.next_due <= today,
        PreventiveMaintenance.status == 'active'
    ).count()
    pending_notifications = tasks_today + pms_due
    
    # Recent items
    recent_equipment = Equipment.query.order_by(Equipment.id.desc()).limit(5).all()
    recent_tasks = Task.query.order_by(Task.id.desc()).limit(5).all()
    upcoming_pms = PreventiveMaintenance.query.filter(
        PreventiveMaintenance.next_due > today,
        PreventiveMaintenance.status == 'active'
    ).order_by(PreventiveMaintenance.next_due).limit(5).all()
    
    # Department stats
    department_stats = []
    for dept in Department.query.all():
        count = Equipment.query.filter_by(department_id=dept.id).count()
        if count > 0:
            department_stats.append({'id': dept.id, 'name': dept.name, 'count': count})
    department_stats = sorted(department_stats, key=lambda x: x['count'], reverse=True)[:6]
    
    return render_template('index.html', 
                         total_equipment_count=total_equipment_count,
                         total_quantity=total_quantity,
                         under_repair=under_repair,
                         departments_count=departments,
                         pending_tasks=pending_tasks,
                         tasks_today=tasks_today,
                         pms_due=pms_due,
                         pending_notifications=pending_notifications,
                         recent_equipment=recent_equipment,
                         recent_tasks=recent_tasks,
                         upcoming_pms=upcoming_pms,
                         department_stats=department_stats,
                         datetime=datetime)

login_attempts = {}

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        
        ip = request.remote_addr
        if ip in login_attempts and login_attempts[ip] >= 5:
            return render_template('login.html', error="Too many login attempts. Try again later.")
        
        user = User.query.filter_by(username=username, is_active=True).first()
        
        if user and user.check_password(password):
            session.clear()
            session['user'] = user.username
            session['role'] = user.role
            session['user_id'] = user.id
            session.permanent = True
            user.last_login = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            db.session.commit()
            if ip in login_attempts:
                del login_attempts[ip]
            return redirect('/')
        else:
            login_attempts[ip] = login_attempts.get(ip, 0) + 1
            return render_template('login.html', error="Invalid username or password")
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/login')

@app.route('/settings')
@login_required
def settings():
    db_size_mb = 0
    if os.path.exists('bems.db'):
        db_size_mb = os.path.getsize('bems.db') / (1024 * 1024)
    
    last_backup = None
    backups = sorted(glob.glob(os.path.join('backups', 'bems_backup_*.db')), reverse=True)
    if backups:
        last_backup_filename = os.path.basename(backups[0])
        try:
            timestamp_str = last_backup_filename.replace('bems_backup_', '').replace('.db', '')
            last_backup = datetime.strptime(timestamp_str, '%Y%m%d_%H%M%S').strftime('%Y-%m-%d %H:%M:%S')
        except:
            last_backup = last_backup_filename
    
    total_equipment = Equipment.query.count()
    total_users = User.query.count()
    total_backups = len(backups)
    storage_path = os.path.abspath(os.path.dirname(__file__))
    
    return render_template('settings.html', 
                         db_size_mb=round(db_size_mb, 2),
                         last_backup=last_backup,
                         total_equipment=total_equipment,
                         total_users=total_users,
                         total_backups=total_backups,
                         storage_path=storage_path)

@app.route('/equipment_list')
@login_required
def equipment_list():
    search = request.args.get('search', '')
    department = request.args.get('department', '')
    status_filter = request.args.get('status', '')
    
    query = Equipment.query
    
    if search:
        query = query.filter(
            (Equipment.name.contains(search)) |
            (Equipment.model_no.contains(search)) |
            (Equipment.company.contains(search)) |
            (Equipment.serial_no.contains(search))
        )
    
    if department:
        query = query.filter_by(department_name=department)
    
    if status_filter:
        query = query.filter_by(status=status_filter)
    
    equipments = query.all()
    departments = [d.name for d in Department.query.all()]
    
    return render_template('equipment_list.html', 
                         equipments=equipments, 
                         departments=departments,
                         search=search,
                         department=department,
                         status_filter=status_filter)

@app.route('/add', methods=['GET', 'POST'])
@login_required
def add_equipment():
    if request.method == 'POST':
        name = request.form.get('name')
        model_no = request.form.get('model_no')
        company = request.form.get('company')
        serial_no = request.form.get('serial_no')
        quantity = request.form.get('quantity', 1)
        department_id = request.form.get('department_id')
        new_department = request.form.get('new_department')
        status = request.form.get('status')
        install_date = request.form.get('install_date')
        warranty_date = request.form.get('warranty_date')
        last_service = request.form.get('last_service')
        
        try:
            quantity = int(quantity) if quantity else 1
        except ValueError:
            quantity = 1
        
        department_obj = None
        department_name = None
        
        if new_department:
            existing = Department.query.filter_by(name=new_department).first()
            if existing:
                department_obj = existing
                department_name = existing.name
            else:
                new_dept = Department(name=new_department)
                db.session.add(new_dept)
                db.session.commit()
                department_obj = new_dept
                department_name = new_dept.name
        elif department_id:
            department_obj = Department.query.get(department_id)
            if department_obj:
                department_name = department_obj.name
        
        new_eq = Equipment(
            name=name, model_no=model_no, company=company, serial_no=serial_no,
            quantity=quantity, department_id=department_obj.id if department_obj else None,
            department_name=department_name, status=status, install_date=install_date,
            warranty_date=warranty_date, last_service=last_service
        )
        
        db.session.add(new_eq)
        db.session.commit()
        return redirect('/equipment_list')
    
    departments = Department.query.all()
    return render_template('add_equipment.html', departments=departments)

@app.route('/equipment/<int:id>')
@login_required
def equipment_detail(id):
    eq = Equipment.query.get(id)
    repairs = Repair.query.filter_by(equipment_id=id).all()
    return render_template('equipment_detail.html', eq=eq, repairs=repairs, datetime=datetime)

@app.route('/add_repair/<int:id>', methods=['POST'])
@login_required
def add_repair(id):
    repair_date = request.form.get('repair_date')
    description = request.form.get('description')
    cost = request.form.get('cost', 0)
    technician = request.form.get('technician')
    
    new_repair = Repair(equipment_id=id, repair_date=repair_date, 
                        description=description, cost=float(cost) if cost else 0,
                        technician=technician)
    db.session.add(new_repair)
    db.session.commit()
    
    eq = Equipment.query.get(id)
    if eq:
        eq.status = "Under Repair"
        db.session.commit()
    
    return redirect(f'/equipment/{id}')

@app.route('/edit_repair/<int:id>', methods=['POST'])
@login_required
def edit_repair(id):
    repair = Repair.query.get(id)
    if repair:
        repair.repair_date = request.form.get('repair_date')
        repair.description = request.form.get('description')
        repair.technician = request.form.get('technician')
        try:
            repair.cost = float(request.form.get('cost', 0))
        except:
            repair.cost = 0
        db.session.commit()
    return redirect(request.referrer or f'/equipment/{repair.equipment_id}')

@app.route('/delete_repair/<int:id>', methods=['POST'])
@login_required
def delete_repair(id):
    repair = Repair.query.get(id)
    equipment_id = repair.equipment_id if repair else None
    if repair:
        db.session.delete(repair)
        db.session.commit()
    return redirect(request.referrer or f'/equipment/{equipment_id}')

@app.route('/equipment/<int:id>/delete')
@login_required
def delete_equipment(id):
    if session.get('role') != 'admin':
        return "Access Denied", 403
    
    eq = Equipment.query.get(id)
    if eq:
        Repair.query.filter_by(equipment_id=id).delete()
        Task.query.filter_by(equipment_id=id).delete()
        PreventiveMaintenance.query.filter_by(equipment_id=id).delete()
        db.session.delete(eq)
        db.session.commit()
    
    return redirect('/equipment_list')

@app.route('/edit/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_equipment(id):
    eq = Equipment.query.get(id)
    
    if request.method == 'POST':
        eq.name = request.form.get('name')
        eq.model_no = request.form.get('model_no')
        eq.company = request.form.get('company')
        eq.serial_no = request.form.get('serial_no')
        
        quantity = request.form.get('quantity', 1)
        try:
            eq.quantity = int(quantity)
        except:
            eq.quantity = 1
        
        department_id = request.form.get('department_id')
        if department_id:
            dept = Department.query.get(department_id)
            if dept:
                eq.department_id = dept.id
                eq.department_name = dept.name
        
        eq.status = request.form.get('status')
        eq.install_date = request.form.get('install_date')
        eq.warranty_date = request.form.get('warranty_date')
        eq.last_service = request.form.get('last_service')
        
        db.session.commit()
        return redirect('/equipment_list')
    
    departments = Department.query.all()
    return render_template('edit_equipment.html', eq=eq, departments=departments, datetime=datetime)

@app.route('/tasks')
@login_required
def tasks():
    today = datetime.now().strftime('%Y-%m-%d')
    tomorrow = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')
    
    today_tasks = Task.query.filter_by(date=today, status='pending').order_by(Task.priority.desc()).all()
    tomorrow_tasks = Task.query.filter_by(date=tomorrow, status='pending').all()
    pending_tasks = Task.query.filter_by(status='pending').order_by(Task.date).all()
    completed_tasks = Task.query.filter_by(status='done').order_by(Task.completed_at.desc()).limit(50).all()
    overdue_tasks = Task.query.filter(Task.date < today, Task.status == 'pending').all()
    equipments = Equipment.query.all()
    
    return render_template('tasks.html', 
                         today_tasks=today_tasks,
                         tomorrow_tasks=tomorrow_tasks,
                         pending_tasks=pending_tasks,
                         completed_tasks=completed_tasks,
                         overdue_tasks=overdue_tasks,
                         equipments=equipments,
                         datetime=datetime)

@app.route('/tasks/add', methods=['POST'])
@login_required
def add_task():
    title = request.form.get('title')
    description = request.form.get('description')
    date = request.form.get('date')
    priority = request.form.get('priority', 'medium')
    category = request.form.get('category', 'general')
    equipment_id = request.form.get('equipment_id')
    notes = request.form.get('notes')
    
    new_task = Task(title=title, description=description, date=date, due_date=date,
                    priority=priority, category=category, equipment_id=equipment_id if equipment_id else None,
                    created_by=session.get('user_id'), notes=notes, status='pending')
    db.session.add(new_task)
    db.session.commit()
    return redirect('/tasks')

@app.route('/tasks/<int:id>/complete')
@login_required
def complete_task(id):
    task = Task.query.get(id)
    if task:
        task.status = 'done'
        task.completed_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        db.session.commit()
    return redirect(request.referrer or '/tasks')

@app.route('/tasks/<int:id>/delete')
@login_required
def delete_task(id):
    task = Task.query.get(id)
    if task:
        db.session.delete(task)
        db.session.commit()
    return redirect(request.referrer or '/tasks')

@app.route('/tasks/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def edit_task(id):
    task = Task.query.get(id)
    if request.method == 'POST':
        task.title = request.form.get('title')
        task.description = request.form.get('description')
        task.date = request.form.get('date')
        task.priority = request.form.get('priority')
        task.category = request.form.get('category')
        task.status = request.form.get('status')
        task.notes = request.form.get('notes')
        
        equipment_id = request.form.get('equipment_id')
        task.equipment_id = equipment_id if equipment_id else None
        
        db.session.commit()
        return redirect('/tasks')
    
    equipments = Equipment.query.all()
    return render_template('edit_task.html', task=task, equipments=equipments, datetime=datetime)

@app.route('/pm')
@login_required
def pm_scheduler():
    active_pms = PreventiveMaintenance.query.filter_by(status='active').all()
    today = datetime.now().strftime('%Y-%m-%d')
    due_pms = [pm for pm in active_pms if pm.next_due and pm.next_due <= today]
    upcoming_pms = [pm for pm in active_pms if pm.next_due and pm.next_due > today]
    equipments = Equipment.query.all()
    completed_pms_count = PreventiveMaintenance.query.filter_by(status='completed').count()
    
    return render_template('pm_scheduler.html', 
                         active_pms=active_pms, 
                         due_pms=due_pms,
                         upcoming_pms=upcoming_pms, 
                         equipments=equipments, 
                         today=today,
                         completed_pms_count=completed_pms_count)

@app.route('/pm/add', methods=['POST'])
@login_required
def add_pm():
    equipment_id = request.form.get('equipment_id')
    title = request.form.get('title')
    description = request.form.get('description')
    frequency = request.form.get('frequency')
    interval_days = request.form.get('interval_days')
    
    today = datetime.now()
    if frequency == 'daily': next_due = today + timedelta(days=1)
    elif frequency == 'weekly': next_due = today + timedelta(weeks=1)
    elif frequency == 'monthly': next_due = today + timedelta(days=30)
    elif frequency == 'quarterly': next_due = today + timedelta(days=90)
    elif frequency == 'yearly': next_due = today + timedelta(days=365)
    else: next_due = today + timedelta(days=int(interval_days or 30))
    
    equipment = Equipment.query.get(equipment_id) if equipment_id else None
    new_pm = PreventiveMaintenance(
        equipment_id=equipment_id if equipment_id else None,
        equipment_name=equipment.name if equipment else 'General',
        title=title, description=description, frequency=frequency,
        interval_days=int(interval_days) if interval_days else None,
        next_due=next_due.strftime('%Y-%m-%d'), status='active',
        assigned_to=session.get('user_id'))
    db.session.add(new_pm)
    db.session.commit()
    return redirect('/pm')

@app.route('/pm/<int:id>/perform')
@login_required
def perform_pm(id):
    pm = PreventiveMaintenance.query.get(id)
    if pm:
        pm.last_performed = datetime.now().strftime('%Y-%m-%d')
        last_date = datetime.strptime(pm.last_performed, '%Y-%m-%d')
        
        if pm.frequency == 'daily': next_date = last_date + timedelta(days=1)
        elif pm.frequency == 'weekly': next_date = last_date + timedelta(weeks=1)
        elif pm.frequency == 'monthly': next_date = last_date + timedelta(days=30)
        elif pm.frequency == 'quarterly': next_date = last_date + timedelta(days=90)
        elif pm.frequency == 'yearly': next_date = last_date + timedelta(days=365)
        else: next_date = last_date + timedelta(days=pm.interval_days or 30)
        
        pm.next_due = next_date.strftime('%Y-%m-%d')
        
        task = Task(title=f"PM: {pm.title}",
                    description=f"Preventive maintenance performed on {pm.equipment_name}",
                    date=pm.last_performed, category='pm', status='done',
                    equipment_id=pm.equipment_id)
        db.session.add(task)
        db.session.commit()
    return redirect('/pm')

@app.route('/pm/<int:id>/delete')
@login_required
def delete_pm(id):
    pm = PreventiveMaintenance.query.get(id)
    if pm:
        db.session.delete(pm)
        db.session.commit()
    return redirect('/pm')

@app.route('/departments')
@login_required
def departments():
    departments = Department.query.all()
    total_equipment = Equipment.query.count()
    under_repair = Equipment.query.filter_by(status="Under Repair").count()
    return render_template('departments.html', 
                         departments=departments,
                         total_equipment=total_equipment,
                         under_repair=under_repair)

@app.route('/departments/add', methods=['POST'])
@login_required
def add_department():
    name = request.form.get('name')
    description = request.form.get('description')
    existing = Department.query.filter_by(name=name).first()
    if existing:
        return redirect('/departments')
    new_dept = Department(name=name, description=description)
    db.session.add(new_dept)
    db.session.commit()
    return redirect('/departments')

@app.route('/departments/<int:id>/equipment')
@login_required
def department_equipment(id):
    department = Department.query.get(id)
    search = request.args.get('search', '')
    status_filter = request.args.get('status', '')
    
    query = Equipment.query.filter_by(department_id=id)
    
    if search:
        query = query.filter(
            (Equipment.name.contains(search)) |
            (Equipment.model_no.contains(search)) |
            (Equipment.company.contains(search)) |
            (Equipment.serial_no.contains(search))
        )
    
    if status_filter:
        query = query.filter_by(status=status_filter)
    
    equipments = query.all()
    today = datetime.now().strftime('%Y-%m-%d')
    
    return render_template('department_equipment.html', 
                         department=department, 
                         equipments=equipments,
                         search=search,
                         status_filter=status_filter,
                         today=today)

@app.route('/departments/<int:id>/delete')
@admin_required
def delete_department(id):
    department = Department.query.get(id)
    if department:
        Equipment.query.filter_by(department_id=id).update({'department_id': None, 'department_name': 'Unassigned'})
        db.session.delete(department)
        db.session.commit()
    return redirect('/departments')

@app.route('/export/department/<int:id>')
@login_required
def export_department(id):
    department = Department.query.get(id)
    search = request.args.get('search', '')
    status_filter = request.args.get('status', '')
    
    query = Equipment.query.filter_by(department_id=id)
    
    if search:
        query = query.filter(
            (Equipment.name.contains(search)) |
            (Equipment.model_no.contains(search)) |
            (Equipment.company.contains(search)) |
            (Equipment.serial_no.contains(search))
        )
    
    if status_filter:
        query = query.filter_by(status=status_filter)
    
    equipments = query.all()
    
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(['ID', 'Name', 'Model No', 'Company', 'Serial No', 'Quantity', 'Status', 'Install Date', 'Warranty Date', 'Last Service'])
    
    for eq in equipments:
        writer.writerow([
            eq.id, eq.name or '', eq.model_no or '', eq.company or '',
            eq.serial_no or '', eq.quantity or 1, eq.status or '',
            eq.install_date or '', eq.warranty_date or '', eq.last_service or ''
        ])
    
    output.seek(0)
    response = make_response(output.getvalue())
    response.headers['Content-Type'] = 'text/csv'
    response.headers['Content-Disposition'] = f'attachment; filename={department.name}_equipment_{datetime.now().strftime("%Y%m%d")}.csv'
    
    return response

@app.route('/users')
@admin_required
def user_management():
    users = User.query.all()
    return render_template('users.html', users=users)

@app.route('/users/add', methods=['POST'])
@admin_required
def add_user():
    username = request.form.get('username')
    email = request.form.get('email')
    password = request.form.get('password')
    role = request.form.get('role')
    
    existing = User.query.filter_by(username=username).first()
    if existing:
        flash('Username already exists')
        return redirect('/users')
    
    new_user = User(username=username, email=email, role=role)
    new_user.set_password(password)
    db.session.add(new_user)
    db.session.commit()
    return redirect('/users')

@app.route('/users/<int:id>/toggle')
@admin_required
def toggle_user(id):
    user = User.query.get(id)
    if user and user.id != session.get('user_id'):
        user.is_active = not user.is_active
        db.session.commit()
    return redirect('/users')

@app.route('/users/<int:id>/reset-password')
@admin_required
def reset_user_password(id):
    user = User.query.get(id)
    if user:
        new_password = request.args.get('password', 'temp123')
        user.set_password(new_password)
        db.session.commit()
    return redirect('/users')

@app.route('/users/<int:id>/delete')
@admin_required
def delete_user(id):
    user = User.query.get(id)
    if user and user.id != session.get('user_id') and user.role != 'admin':
        db.session.delete(user)
        db.session.commit()
    return redirect('/users')

@app.route('/users/admin-reset-password', methods=['POST'])
@admin_required
def admin_reset_password():
    user_id = request.form.get('user_id')
    new_password = request.form.get('new_password')
    
    user = User.query.get(user_id)
    if user:
        user.set_password(new_password)
        db.session.commit()
    
    return redirect('/users')

@app.route('/export/csv')
@login_required
def export_csv():
    equipments = Equipment.query.all()
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(['ID', 'Name', 'Model No', 'Company', 'Serial No', 'Quantity', 'Department', 'Status', 'Install Date', 'Warranty Date', 'Last Service'])
    for eq in equipments:
        writer.writerow([eq.id, eq.name or '', eq.model_no or '', eq.company or '',
                        eq.serial_no or '', eq.quantity or 1, eq.department_name or '',
                        eq.status or '', eq.install_date or '', eq.warranty_date or '',
                        eq.last_service or ''])
    output.seek(0)
    response = make_response(output.getvalue())
    response.headers['Content-Type'] = 'text/csv'
    response.headers['Content-Disposition'] = f'attachment; filename=equipment_export_{datetime.now().strftime("%Y%m%d")}.csv'
    return response

@app.route('/export/excel')
@login_required
def export_excel():
    equipments = Equipment.query.all()
    data = []
    for eq in equipments:
        data.append({'ID': eq.id, 'Name': eq.name or '', 'Model No': eq.model_no or '',
                     'Company': eq.company or '', 'Serial No': eq.serial_no or '',
                     'Quantity': eq.quantity or 1, 'Department': eq.department_name or '',
                     'Status': eq.status or '', 'Install Date': eq.install_date or '',
                     'Warranty Date': eq.warranty_date or '', 'Last Service': eq.last_service or ''})
    df = pd.DataFrame(data)
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name='Equipment', index=False)
        worksheet = writer.sheets['Equipment']
        for column in worksheet.columns:
            max_length = 0
            column_letter = column[0].column_letter
            for cell in column:
                try:
                    if len(str(cell.value)) > max_length:
                        max_length = len(str(cell.value))
                except:
                    pass
            adjusted_width = min(max_length + 2, 50)
            worksheet.column_dimensions[column_letter].width = adjusted_width
    output.seek(0)
    return send_file(output, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                     as_attachment=True, download_name=f'equipment_export_{datetime.now().strftime("%Y%m%d")}.xlsx')

@app.route('/export/pdf/equipment')
@login_required
def export_equipment_pdf():
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import landscape, letter
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Spacer, Paragraph
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    
    equipments = Equipment.query.all()
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(letter))
    elements = []
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('CustomTitle', parent=styles['Heading1'], fontSize=24,
                                  textColor=colors.HexColor('#0f172a'), alignment=1)
    title = Paragraph("Biomedical Equipment Management System", title_style)
    elements.append(title)
    elements.append(Spacer(1, 12))
    subtitle = Paragraph(f"Equipment Inventory Report - Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}", styles['Normal'])
    elements.append(subtitle)
    elements.append(Spacer(1, 24))
    data = [['ID', 'Name', 'Model', 'Company', 'Serial', 'Qty', 'Department', 'Status']]
    for eq in equipments:
        data.append([str(eq.id), eq.name or '-', eq.model_no or '-', eq.company or '-',
                     eq.serial_no or '-', str(eq.quantity or 1), eq.department_name or '-', eq.status or '-'])
    table = Table(data)
    table.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#22c55e')),
                                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                                ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#cbd5e1'))]))
    elements.append(table)
    doc.build(elements)
    buffer.seek(0)
    return send_file(buffer, as_attachment=True, download_name=f'equipment_report_{datetime.now().strftime("%Y%m%d")}.pdf', mimetype='application/pdf')

@app.route('/export/pdf/repair/<int:equipment_id>')
@login_required
def export_repair_pdf(equipment_id):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Spacer, Paragraph
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    
    eq = Equipment.query.get(equipment_id)
    repairs = Repair.query.filter_by(equipment_id=equipment_id).all()
    
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    elements = []
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('CustomTitle', parent=styles['Heading1'], fontSize=20,
                                  textColor=colors.HexColor('#0f172a'), alignment=1)
    title = Paragraph(f"Repair History Report", title_style)
    elements.append(title)
    elements.append(Spacer(1, 12))
    
    equip_info = Paragraph(f"<b>Equipment:</b> {eq.name} | <b>Model:</b> {eq.model_no or '-'} | <b>Serial:</b> {eq.serial_no or '-'} | <b>Quantity:</b> {eq.quantity or 1}", styles['Normal'])
    elements.append(equip_info)
    elements.append(Spacer(1, 24))
    
    data = [['Date', 'Description', 'Cost', 'Technician']]
    for r in repairs:
        data.append([r.repair_date or '-', r.description or '-', f"${r.cost:.2f}" if r.cost else '-', r.technician or '-'])
    
    if len(data) == 1:
        data.append(['No repair records found', '', '', ''])
    
    table = Table(data)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#22c55e')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#cbd5e1')),
    ]))
    
    elements.append(table)
    doc.build(elements)
    buffer.seek(0)
    
    return send_file(buffer, as_attachment=True, download_name=f'repair_report_{eq.name}_{datetime.now().strftime("%Y%m%d")}.pdf', mimetype='application/pdf')

@app.route('/import', methods=['GET', 'POST'])
@login_required
def import_data():
    if request.method == 'POST':
        if 'file' not in request.files:
            return render_template('import_export.html', error="No file selected")
        file = request.files['file']
        if file.filename == '':
            return render_template('import_export.html', error="No file selected")
        if not allowed_file(file.filename):
            return render_template('import_export.html', error="File type not allowed")
        try:
            filename = secure_filename(file.filename)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)
            ext = filename.rsplit('.', 1)[1].lower()
            if ext == 'csv':
                df = pd.read_csv(filepath)
            else:
                df = pd.read_excel(filepath)
            os.remove(filepath)
            
            column_map = map_columns(df.columns)
            if not column_map.get('name'):
                return render_template('import_export.html', error="Could not find equipment name column", available_columns=list(df.columns))
            
            imported_count = 0
            skipped_count = 0
            errors = []
            warnings = []
            
            for index, row in df.iterrows():
                try:
                    row_num = index + 2
                    name = str(row[column_map['name']]) if column_map['name'] and pd.notna(row[column_map['name']]) else ''
                    
                    if not name or name == 'nan':
                        warnings.append(f"Row {row_num}: Skipped - empty equipment name")
                        skipped_count += 1
                        continue
                    
                    def get_value(field, default=''):
                        col = column_map.get(field)
                        if col and col in df.columns and pd.notna(row[col]):
                            return str(row[col])
                        return default
                    
                    department_name = get_value('department')
                    department_obj = None
                    if department_name:
                        existing_dept = Department.query.filter_by(name=department_name).first()
                        if existing_dept:
                            department_obj = existing_dept
                        else:
                            new_dept = Department(name=department_name)
                            db.session.add(new_dept)
                            db.session.commit()
                            department_obj = new_dept
                    
                    quantity = get_value('quantity', '1')
                    try:
                        quantity = int(float(quantity)) if quantity else 1
                    except:
                        quantity = 1
                    
                    new_eq = Equipment(
                        name=name,
                        model_no=get_value('model_no'),
                        company=get_value('company'),
                        serial_no=get_value('serial_no'),
                        quantity=quantity,
                        department_id=department_obj.id if department_obj else None,
                        department_name=department_name,
                        status=get_value('status', 'Working'),
                        install_date=get_value('install_date'),
                        warranty_date=get_value('warranty_date'),
                        last_service=get_value('last_service')
                    )
                    
                    db.session.add(new_eq)
                    imported_count += 1
                    
                except Exception as e:
                    skipped_count += 1
                    errors.append(f"Row {row_num}: {str(e)}")
            
            db.session.commit()
            
            message = f"Successfully imported {imported_count} equipment items."
            if skipped_count > 0:
                message += f" Skipped {skipped_count} items due to errors."
            
            return render_template('import_export.html', success=message, errors=errors, warnings=warnings, imported_count=imported_count, skipped_count=skipped_count)
            
        except Exception as e:
            return render_template('import_export.html', error=f"Error reading file: {str(e)}")
    
    return render_template('import_export.html')

@app.route('/backup/manual')
@admin_required
def manual_backup():
    create_backup()
    return redirect('/backup/manage')

@app.route('/backup/download/<filename>')
@admin_required
def download_backup(filename):
    if '..' in filename or '/' in filename:
        return "Invalid filename", 400
    filepath = os.path.join(BACKUP_FOLDER, filename)
    if not os.path.exists(filepath):
        return "Backup file not found", 404
    return send_file(filepath, as_attachment=True, download_name=filename, mimetype='application/x-sqlite3')

@app.route('/backup/restore/<filename>')
@admin_required
def restore_backup(filename):
    if '..' in filename or '/' in filename:
        return "Invalid filename", 400
    backup_path = os.path.join(BACKUP_FOLDER, filename)
    if not os.path.exists(backup_path):
        return "Backup file not found", 404
    try:
        create_backup()
        db.session.remove()
        db.engine.dispose()
        shutil.copy2(backup_path, 'bems.db')
        with app.app_context():
            db.create_all()
        return "<h1>✅ Database Restored Successfully!</h1><p>Redirecting...</p><script>setTimeout(function(){ window.location.href='/'; }, 3000);</script>"
    except Exception as e:
        return f"Restore failed: {str(e)}", 500

@app.route('/backup/delete/<filename>')
@admin_required
def delete_backup(filename):
    if '..' in filename or '/' in filename:
        return "Invalid filename", 400
    filepath = os.path.join(BACKUP_FOLDER, filename)
    if os.path.exists(filepath):
        os.remove(filepath)
    return redirect('/backup/manage')

@app.route('/backup/manage')
@admin_required
def manage_backups():
    backups = []
    for backup_file in sorted(glob.glob(os.path.join(BACKUP_FOLDER, 'bems_backup_*.db')), reverse=True):
        filename = os.path.basename(backup_file)
        try:
            timestamp_str = filename.replace('bems_backup_', '').replace('.db', '')
            backup_date = datetime.strptime(timestamp_str, '%Y%m%d_%H%M%S')
            formatted_date = backup_date.strftime('%Y-%m-%d %H:%M:%S')
        except:
            formatted_date = "Unknown"
        size_bytes = os.path.getsize(backup_file)
        size_mb = size_bytes / (1024 * 1024)
        backups.append({'filename': filename, 'date': formatted_date, 'size_mb': round(size_mb, 2)})
    db_size_mb = 0
    if os.path.exists('bems.db'):
        db_size_mb = os.path.getsize('bems.db') / (1024 * 1024)
    return render_template('backup_manage.html', backups=backups, db_size_mb=round(db_size_mb, 2))

# ===== RUN APP =====

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        create_default_data()
    if os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        webbrowser.open("http://127.0.0.1:5000")
    app.run(debug=True, host='0.0.0.0', port=5000)