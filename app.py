import os
import secrets
from datetime import datetime
from functools import wraps
from flask import (
    Flask, render_template, request, redirect, url_for,
    session, flash, abort, send_from_directory, jsonify
)
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
import database

# Initialize Flask application
app = Flask(__name__)

# Configuration
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY') or secrets.token_hex(32)
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16 MB max upload
app.config['ALLOWED_EXTENSIONS'] = {'pdf', 'png', 'jpg', 'jpeg', 'docx', 'doc'}
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

# Ensure required directories exist and initialize database
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
with app.app_context():
    database.init_db()

# ==============================================================================
# Helper Functions & Decorators
# ==============================================================================

def allowed_file(filename):
    """Check if uploaded file has an allowed extension."""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

def get_client_ip():
    """Retrieve client IP address safely."""
    if request.headers.get('X-Forwarded-For'):
        return request.headers.get('X-Forwarded-For').split(',')[0].strip()
    return request.remote_addr or '127.0.0.1'

def generate_csrf_token():
    """Generate or retrieve the session CSRF token."""
    if 'csrf_token' not in session:
        session['csrf_token'] = secrets.token_hex(32)
    return session['csrf_token']

@app.context_processor
def inject_global_template_data():
    """Inject CSRF token and current logged-in user into all templates."""
    current_user = None
    if 'user_id' in session:
        conn = database.get_db()
        current_user = conn.execute(
            "SELECT id, full_name, email, role, phone, institution, major, gpa, education_level FROM users WHERE id = ?",
            (session['user_id'],)
        ).fetchone()
        conn.close()
    return {
        'csrf_token': generate_csrf_token,
        'current_user': current_user,
        'now': datetime.now()
    }

@app.before_request
def csrf_protect():
    """CSRF protection for state-changing HTTP methods."""
    if request.method in ('POST', 'PUT', 'DELETE', 'PATCH'):
        # Allow if matching token in form or header
        token = request.form.get('csrf_token') or request.headers.get('X-CSRFToken') or request.headers.get('X-CSRF-Token')
        session_token = session.get('csrf_token')
        if not session_token or not token or not secrets.compare_digest(session_token, token):
            if request.is_json:
                return jsonify({'error': 'Invalid or missing CSRF token'}), 403
            flash('Security token invalid or expired. Please try again.', 'error')
            return redirect(request.referrer or url_for('landing'))

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in to access this page.', 'warning')
            return redirect(url_for('login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function

def student_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in as a student to access this page.', 'warning')
            return redirect(url_for('login', next=request.url))
        if session.get('role') != 'student':
            flash('This section is reserved for students.', 'warning')
            return redirect(url_for('admin_dashboard'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Administrator authentication required.', 'warning')
            return redirect(url_for('admin_login', next=request.url))
        if session.get('role') != 'admin':
            flash('Access denied. Administrator privileges required.', 'error')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated_function

# ==============================================================================
# Public & Authentication Routes
# ==============================================================================

@app.route('/')
def landing():
    """Page 1: Landing Page with scholarship highlights and system metrics."""
    conn = database.get_db()
    
    # Active featured scholarships
    featured_scholarships = conn.execute("""
        SELECT * FROM scholarships 
        WHERE status = 'active' 
        ORDER BY deadline ASC LIMIT 3
    """).fetchall()
    
    # Aggregated metrics for credibility
    total_scholarships = conn.execute("SELECT COUNT(*) FROM scholarships WHERE status = 'active'").fetchone()[0]
    total_funding = conn.execute("SELECT COALESCE(SUM(amount * slots), 0) FROM scholarships WHERE status = 'active'").fetchone()[0]
    total_applications = conn.execute("SELECT COUNT(*) FROM applications").fetchone()[0]
    total_awarded = conn.execute("SELECT COUNT(*) FROM applications WHERE status = 'Approved'").fetchone()[0]
    
    conn.close()
    return render_template(
        'index.html',
        featured_scholarships=featured_scholarships,
        stats={
            'total_scholarships': total_scholarships,
            'total_funding': f"${total_funding:,.0f}",
            'total_applications': total_applications,
            'total_awarded': total_awarded
        }
    )

@app.route('/register', methods=['GET', 'POST'])
def register():
    """Page 2: Student Registration Page."""
    if 'user_id' in session:
        return redirect(url_for('dashboard') if session.get('role') == 'student' else url_for('admin_dashboard'))

    if request.method == 'POST':
        full_name = request.form.get('full_name', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')
        phone = request.form.get('phone', '').strip()
        institution = request.form.get('institution', '').strip()
        major = request.form.get('major', '').strip()
        education_level = request.form.get('education_level', '').strip()
        gpa_str = request.form.get('gpa', '').strip()

        # Validation
        if not full_name or not email or not password:
            flash('Please fill in all required fields.', 'error')
            return render_template('register.html')
        
        if '@' not in email or '.' not in email:
            flash('Please enter a valid email address.', 'error')
            return render_template('register.html')

        if len(password) < 6:
            flash('Password must be at least 6 characters long.', 'error')
            return render_template('register.html')

        if password != confirm_password:
            flash('Passwords do not match.', 'error')
            return render_template('register.html')

        gpa = None
        if gpa_str:
            try:
                gpa = float(gpa_str)
                if not (0.0 <= gpa <= 4.0):
                    flash('GPA must be between 0.00 and 4.00.', 'error')
                    return render_template('register.html')
            except ValueError:
                flash('Please enter a valid numeric GPA.', 'error')
                return render_template('register.html')

        conn = database.get_db()
        existing_user = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
        if existing_user:
            conn.close()
            flash('An account with this email already exists. Please log in.', 'error')
            return render_template('register.html')

        # Insert new student user
        password_hash = generate_password_hash(password)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO users (full_name, email, password_hash, role, phone, institution, major, gpa, education_level)
            VALUES (?, ?, ?, 'student', ?, ?, ?, ?, ?)
        """, (full_name, email, password_hash, phone, institution, major, gpa, education_level))
        new_user_id = cursor.lastrowid
        conn.commit()
        conn.close()

        # Record audit log
        database.log_audit(new_user_id, 'STUDENT_REGISTER', 'user', new_user_id, f'Registered new student account: {email}', get_client_ip())

        # Establish session
        session['user_id'] = new_user_id
        session['role'] = 'student'
        session['user_name'] = full_name
        session['email'] = email

        flash(f'Welcome to EduScholar, {full_name}! Your account has been created.', 'success')
        return redirect(url_for('dashboard'))

    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    """Page 3: Student Login Page."""
    if 'user_id' in session:
        return redirect(url_for('dashboard') if session.get('role') == 'student' else url_for('admin_dashboard'))

    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')

        if not email or not password:
            flash('Please enter both email and password.', 'error')
            return render_template('login.html')

        conn = database.get_db()
        user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        conn.close()

        if user and check_password_hash(user['password_hash'], password):
            session['user_id'] = user['id']
            session['role'] = user['role']
            session['user_name'] = user['full_name']
            session['email'] = user['email']

            database.log_audit(user['id'], 'USER_LOGIN', 'auth', user['id'], f'User logged in ({user["role"]})', get_client_ip())
            flash(f'Welcome back, {user["full_name"]}!', 'success')

            if user['role'] == 'admin':
                return redirect(url_for('admin_dashboard'))
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid email or password. Please try again.', 'error')
            return render_template('login.html')

    return render_template('login.html')

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    """Page 9: Admin Login Page."""
    if 'user_id' in session and session.get('role') == 'admin':
        return redirect(url_for('admin_dashboard'))

    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')

        if not email or not password:
            flash('Please enter administrator credentials.', 'error')
            return render_template('admin/login.html')

        conn = database.get_db()
        user = conn.execute("SELECT * FROM users WHERE email = ? AND role = 'admin'", (email,)).fetchone()
        conn.close()

        if user and check_password_hash(user['password_hash'], password):
            session['user_id'] = user['id']
            session['role'] = 'admin'
            session['user_name'] = user['full_name']
            session['email'] = user['email']

            database.log_audit(user['id'], 'ADMIN_LOGIN', 'auth', user['id'], 'Administrator signed in to management portal', get_client_ip())
            flash('Authenticated as Administrator.', 'success')
            return redirect(url_for('admin_dashboard'))
        else:
            flash('Invalid administrator credentials or unauthorized account.', 'error')
            return render_template('admin/login.html')

    return render_template('admin/login.html')

@app.route('/logout')
def logout():
    """Log out current user and clear session."""
    user_id = session.get('user_id')
    if user_id:
        database.log_audit(user_id, 'USER_LOGOUT', 'auth', user_id, 'User logged out', get_client_ip())
    session.clear()
    flash('You have been logged out successfully.', 'info')
    return redirect(url_for('login'))

# ==============================================================================
# Scholarship Catalog & Discovery
# ==============================================================================

@app.route('/scholarships')
def scholarship_list():
    """Page 5: Scholarship Listing and Search Page."""
    query = request.args.get('q', '').strip()
    category = request.args.get('category', '').strip()
    sort_by = request.args.get('sort', 'deadline')

    conn = database.get_db()
    sql = "SELECT * FROM scholarships WHERE status = 'active'"
    params = []

    if query:
        sql += " AND (title LIKE ? OR description LIKE ? OR organization LIKE ?)"
        like_q = f"%{query}%"
        params.extend([like_q, like_q, like_q])

    if category and category != 'All':
        sql += " AND category = ?"
        params.append(category)

    if sort_by == 'amount_desc':
        sql += " ORDER BY amount DESC"
    elif sort_by == 'amount_asc':
        sql += " ORDER BY amount ASC"
    elif sort_by == 'newest':
        sql += " ORDER BY created_at DESC"
    else:
        sql += " ORDER BY deadline ASC"

    scholarships = conn.execute(sql, params).fetchall()

    # Get distinct categories for filter buttons
    categories = [row['category'] for row in conn.execute(
        "SELECT DISTINCT category FROM scholarships WHERE status = 'active' ORDER BY category"
    ).fetchall()]

    # If student is logged in, find which scholarships they've already applied for
    applied_ids = []
    if 'user_id' in session and session.get('role') == 'student':
        applied_rows = conn.execute(
            "SELECT scholarship_id FROM applications WHERE user_id = ?",
            (session['user_id'],)
        ).fetchall()
        applied_ids = [row['scholarship_id'] for row in applied_rows]

    conn.close()

    return render_template(
        'scholarships.html',
        scholarships=scholarships,
        categories=categories,
        selected_category=category,
        query=query,
        sort_by=sort_by,
        applied_ids=applied_ids
    )

@app.route('/scholarships/<int:scholarship_id>')
def scholarship_detail(scholarship_id):
    """View individual scholarship details."""
    conn = database.get_db()
    scholarship = conn.execute("SELECT * FROM scholarships WHERE id = ?", (scholarship_id,)).fetchone()
    
    if not scholarship:
        conn.close()
        flash('Scholarship not found.', 'error')
        return redirect(url_for('scholarship_list'))

    # Check if current student applied
    has_applied = False
    application = None
    if 'user_id' in session and session.get('role') == 'student':
        application = conn.execute(
            "SELECT * FROM applications WHERE user_id = ? AND scholarship_id = ?",
            (session['user_id'], scholarship_id)
        ).fetchone()
        has_applied = application is not None

    conn.close()
    return render_template('scholarship_detail.html', scholarship=scholarship, has_applied=has_applied, application=application)

# ==============================================================================
# Student Portal Routes
# ==============================================================================

@app.route('/dashboard')
@student_required
def dashboard():
    """Page 4: Student Dashboard."""
    user_id = session['user_id']
    conn = database.get_db()

    user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()

    # Metric counts
    total_applied = conn.execute("SELECT COUNT(*) FROM applications WHERE user_id = ?", (user_id,)).fetchone()[0]
    under_review = conn.execute("SELECT COUNT(*) FROM applications WHERE user_id = ? AND status IN ('Submitted', 'Under Review')", (user_id,)).fetchone()[0]
    approved = conn.execute("SELECT COUNT(*) FROM applications WHERE user_id = ? AND status = 'Approved'", (user_id,)).fetchone()[0]
    rejected = conn.execute("SELECT COUNT(*) FROM applications WHERE user_id = ? AND status = 'Rejected'", (user_id,)).fetchone()[0]

    # Recent applications with scholarship details
    recent_applications = conn.execute("""
        SELECT a.*, s.title as scholarship_title, s.organization, s.amount, s.deadline
        FROM applications a
        JOIN scholarships s ON a.scholarship_id = s.id
        WHERE a.user_id = ?
        ORDER BY a.submitted_at DESC
        LIMIT 5
    """, (user_id,)).fetchall()

    # Recommended scholarships student hasn't applied for yet
    recommended_scholarships = conn.execute("""
        SELECT * FROM scholarships
        WHERE status = 'active'
        AND id NOT IN (SELECT scholarship_id FROM applications WHERE user_id = ?)
        ORDER BY deadline ASC
        LIMIT 3
    """, (user_id,)).fetchall()

    conn.close()

    return render_template(
        'dashboard.html',
        user=user,
        stats={
            'total_applied': total_applied,
            'under_review': under_review,
            'approved': approved,
            'rejected': rejected
        },
        recent_applications=recent_applications,
        recommended_scholarships=recommended_scholarships
    )

@app.route('/apply/<int:scholarship_id>', methods=['GET', 'POST'])
@student_required
def apply_scholarship(scholarship_id):
    """Page 6: Scholarship Application Form."""
    user_id = session['user_id']
    conn = database.get_db()

    scholarship = conn.execute("SELECT * FROM scholarships WHERE id = ? AND status = 'active'", (scholarship_id,)).fetchone()
    if not scholarship:
        conn.close()
        flash('This scholarship is either not found or currently closed to applications.', 'error')
        return redirect(url_for('scholarship_list'))

    # Check if student already applied
    existing_app = conn.execute(
        "SELECT id FROM applications WHERE user_id = ? AND scholarship_id = ?",
        (user_id, scholarship_id)
    ).fetchone()
    if existing_app:
        conn.close()
        flash('You have already submitted an application for this scholarship.', 'info')
        return redirect(url_for('my_applications'))

    user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()

    if request.method == 'POST':
        gpa_str = request.form.get('gpa', '').strip()
        academic_level = request.form.get('academic_level', '').strip()
        essay = request.form.get('essay', '').strip()

        # Validation
        if not gpa_str or not academic_level or not essay:
            conn.close()
            flash('Please complete all required fields.', 'error')
            return render_template('apply.html', scholarship=scholarship, user=user)

        try:
            gpa = float(gpa_str)
            if not (0.0 <= gpa <= 4.0):
                conn.close()
                flash('GPA must be between 0.00 and 4.00.', 'error')
                return render_template('apply.html', scholarship=scholarship, user=user)
        except ValueError:
            conn.close()
            flash('Please enter a valid numeric GPA.', 'error')
            return render_template('apply.html', scholarship=scholarship, user=user)

        if len(essay.split()) < 25:
            conn.close()
            flash('Your statement of purpose must be at least 25 words.', 'error')
            return render_template('apply.html', scholarship=scholarship, user=user)

        # File upload handling
        file = request.files.get('document')
        if not file or file.filename == '':
            conn.close()
            flash('Please upload your supporting academic transcript or document.', 'error')
            return render_template('apply.html', scholarship=scholarship, user=user)

        if not allowed_file(file.filename):
            conn.close()
            flash('Invalid file format. Allowed formats: PDF, PNG, JPG, JPEG, DOC, DOCX.', 'error')
            return render_template('apply.html', scholarship=scholarship, user=user)

        # Secure file saving
        original_filename = secure_filename(file.filename)
        timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
        random_token = secrets.token_hex(4)
        stored_filename = f"user_{user_id}_sch_{scholarship_id}_{timestamp}_{random_token}_{original_filename}"
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], stored_filename)
        file.save(file_path)

        # Save to database
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO applications (user_id, scholarship_id, gpa, academic_level, essay, document_path, document_name, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'Submitted')
        """, (user_id, scholarship_id, gpa, academic_level, essay, stored_filename, original_filename))
        app_id = cursor.lastrowid
        conn.commit()
        conn.close()

        # Log audit
        database.log_audit(
            user_id,
            'SUBMIT_APPLICATION',
            'application',
            app_id,
            f'Submitted application for "{scholarship["title"]}" (${scholarship["amount"]:,.0f})',
            get_client_ip()
        )

        flash(f'Application successfully submitted for {scholarship["title"]}!', 'success')
        return redirect(url_for('my_applications'))

    conn.close()
    return render_template('apply.html', scholarship=scholarship, user=user)

@app.route('/my-applications')
@student_required
def my_applications():
    """Page 7: My Applications and History Page."""
    user_id = session['user_id']
    conn = database.get_db()

    applications = conn.execute("""
        SELECT a.*, s.title as scholarship_title, s.organization, s.amount, s.deadline, s.category
        FROM applications a
        JOIN scholarships s ON a.scholarship_id = s.id
        WHERE a.user_id = ?
        ORDER BY a.submitted_at DESC
    """, (user_id,)).fetchall()

    conn.close()
    return render_template('my_applications.html', applications=applications)

@app.route('/profile', methods=['GET', 'POST'])
@student_required
def profile():
    """Page 8: Student Profile Management Page."""
    user_id = session['user_id']
    conn = database.get_db()

    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'update_details':
            full_name = request.form.get('full_name', '').strip()
            phone = request.form.get('phone', '').strip()
            institution = request.form.get('institution', '').strip()
            major = request.form.get('major', '').strip()
            education_level = request.form.get('education_level', '').strip()
            bio = request.form.get('bio', '').strip()
            gpa_str = request.form.get('gpa', '').strip()

            if not full_name:
                flash('Full name cannot be empty.', 'error')
                return redirect(url_for('profile'))

            gpa = None
            if gpa_str:
                try:
                    gpa = float(gpa_str)
                    if not (0.0 <= gpa <= 4.0):
                        flash('GPA must be between 0.00 and 4.00.', 'error')
                        return redirect(url_for('profile'))
                except ValueError:
                    flash('Invalid GPA value.', 'error')
                    return redirect(url_for('profile'))

            conn.execute("""
                UPDATE users
                SET full_name = ?, phone = ?, institution = ?, major = ?, gpa = ?, education_level = ?, bio = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (full_name, phone, institution, major, gpa, education_level, bio, user_id))
            conn.commit()

            session['user_name'] = full_name
            database.log_audit(user_id, 'UPDATE_PROFILE', 'user', user_id, 'Updated profile details', get_client_ip())
            flash('Profile updated successfully!', 'success')

        elif action == 'change_password':
            current_password = request.form.get('current_password', '')
            new_password = request.form.get('new_password', '')
            confirm_new_password = request.form.get('confirm_new_password', '')

            user = conn.execute("SELECT password_hash FROM users WHERE id = ?", (user_id,)).fetchone()
            if not check_password_hash(user['password_hash'], current_password):
                flash('Current password incorrect.', 'error')
                return redirect(url_for('profile'))

            if len(new_password) < 6:
                flash('New password must be at least 6 characters.', 'error')
                return redirect(url_for('profile'))

            if new_password != confirm_new_password:
                flash('New passwords do not match.', 'error')
                return redirect(url_for('profile'))

            new_hash = generate_password_hash(new_password)
            conn.execute("UPDATE users SET password_hash = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (new_hash, user_id))
            conn.commit()

            database.log_audit(user_id, 'CHANGE_PASSWORD', 'user', user_id, 'Changed password', get_client_ip())
            flash('Password changed successfully!', 'success')

        return redirect(url_for('profile'))

    user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    # Calculate profile completion percentage
    fields = [user['full_name'], user['email'], user['phone'], user['institution'], user['major'], user['gpa'], user['education_level'], user['bio']]
    completed = sum(1 for f in fields if f is not None and str(f).strip() != '')
    completion_rate = int((completed / len(fields)) * 100)

    conn.close()
    return render_template('profile.html', user=user, completion_rate=completion_rate)

@app.route('/download-doc/<int:application_id>')
@login_required
def download_document(application_id):
    """Secure document download endpoint with strict ownership verification."""
    conn = database.get_db()
    app_record = conn.execute("SELECT * FROM applications WHERE id = ?", (application_id,)).fetchone()
    conn.close()

    if not app_record or not app_record['document_path']:
        flash('Document not found.', 'error')
        return redirect(request.referrer or url_for('dashboard'))

    # Security: Ensure only the student owner or an admin can access the document
    if session.get('role') != 'admin' and app_record['user_id'] != session.get('user_id'):
        flash('Access denied. You cannot view documents from other applicants.', 'error')
        return redirect(url_for('dashboard'))

    return send_from_directory(
        app.config['UPLOAD_FOLDER'],
        app_record['document_path'],
        as_attachment=True,
        download_name=app_record['document_name'] or 'application_document.pdf'
    )

# ==============================================================================
# Administrator Portal Routes
# ==============================================================================

@app.route('/admin/dashboard')
@admin_required
def admin_dashboard():
    """Page 10: Admin Dashboard."""
    conn = database.get_db()

    total_applicants = conn.execute("SELECT COUNT(*) FROM users WHERE role = 'student'").fetchone()[0]
    total_applications = conn.execute("SELECT COUNT(*) FROM applications").fetchone()[0]
    pending_review = conn.execute("SELECT COUNT(*) FROM applications WHERE status IN ('Submitted', 'Under Review')").fetchone()[0]
    approved_count = conn.execute("SELECT COUNT(*) FROM applications WHERE status = 'Approved'").fetchone()[0]
    rejected_count = conn.execute("SELECT COUNT(*) FROM applications WHERE status = 'Rejected'").fetchone()[0]
    active_scholarships = conn.execute("SELECT COUNT(*) FROM scholarships WHERE status = 'active'").fetchone()[0]
    
    # Funds awarded
    funds_awarded = conn.execute("""
        SELECT COALESCE(SUM(s.amount), 0)
        FROM applications a
        JOIN scholarships s ON a.scholarship_id = s.id
        WHERE a.status = 'Approved'
    """).fetchone()[0]

    # Recent applications
    recent_applications = conn.execute("""
        SELECT a.*, u.full_name as applicant_name, u.email as applicant_email, s.title as scholarship_title, s.amount
        FROM applications a
        JOIN users u ON a.user_id = u.id
        JOIN scholarships s ON a.scholarship_id = s.id
        ORDER BY a.submitted_at DESC
        LIMIT 6
    """).fetchall()

    # Recent audit logs
    recent_audit_logs = conn.execute("""
        SELECT l.*, u.full_name as user_name, u.email as user_email
        FROM audit_logs l
        LEFT JOIN users u ON l.user_id = u.id
        ORDER BY l.created_at DESC
        LIMIT 6
    """).fetchall()

    conn.close()

    return render_template(
        'admin/dashboard.html',
        stats={
            'total_applicants': total_applicants,
            'total_applications': total_applications,
            'pending_review': pending_review,
            'approved_count': approved_count,
            'rejected_count': rejected_count,
            'active_scholarships': active_scholarships,
            'funds_awarded': f"${funds_awarded:,.0f}"
        },
        recent_applications=recent_applications,
        recent_audit_logs=recent_audit_logs
    )

@app.route('/admin/applications')
@admin_required
def admin_applications():
    """Page 11: Application Management and Review Page."""
    status_filter = request.args.get('status', 'all')
    scholarship_id = request.args.get('scholarship_id', '')
    search = request.args.get('search', '').strip()

    conn = database.get_db()
    sql = """
        SELECT a.*, u.full_name as applicant_name, u.email as applicant_email, u.institution,
               s.title as scholarship_title, s.amount as scholarship_amount, s.category
        FROM applications a
        JOIN users u ON a.user_id = u.id
        JOIN scholarships s ON a.scholarship_id = s.id
        WHERE 1=1
    """
    params = []

    if status_filter and status_filter != 'all':
        sql += " AND a.status = ?"
        params.append(status_filter)

    if scholarship_id:
        sql += " AND a.scholarship_id = ?"
        params.append(scholarship_id)

    if search:
        sql += " AND (u.full_name LIKE ? OR u.email LIKE ? OR s.title LIKE ?)"
        like_term = f"%{search}%"
        params.extend([like_term, like_term, like_term])

    sql += " ORDER BY a.submitted_at DESC"
    applications = conn.execute(sql, params).fetchall()

    # Get scholarships list for filter dropdown
    scholarships = conn.execute("SELECT id, title FROM scholarships ORDER BY title").fetchall()
    conn.close()

    return render_template(
        'admin/applications.html',
        applications=applications,
        scholarships=scholarships,
        status_filter=status_filter,
        scholarship_id=scholarship_id,
        search=search
    )

@app.route('/admin/applications/<int:app_id>')
@admin_required
def admin_application_detail(app_id):
    """View individual application details for administrative review."""
    conn = database.get_db()
    application = conn.execute("""
        SELECT a.*, 
               u.full_name as applicant_name, u.email as applicant_email, u.phone as applicant_phone,
               u.institution as applicant_institution, u.major as applicant_major, u.bio as applicant_bio,
               s.title as scholarship_title, s.organization, s.amount, s.deadline, s.eligibility,
               r.full_name as reviewer_name
        FROM applications a
        JOIN users u ON a.user_id = u.id
        JOIN scholarships s ON a.scholarship_id = s.id
        LEFT JOIN users r ON a.reviewed_by = r.id
        WHERE a.id = ?
    """, (app_id,)).fetchone()
    conn.close()

    if not application:
        flash('Application not found.', 'error')
        return redirect(url_for('admin_applications'))

    return render_template('admin/application_detail.html', app=application)

@app.route('/admin/applications/<int:app_id>/status', methods=['POST'])
@admin_required
def admin_update_application_status(app_id):
    """Admin updates an application's status with reviewer notes and logs audit."""
    new_status = request.form.get('status')
    admin_notes = request.form.get('admin_notes', '').strip()

    valid_statuses = ['Submitted', 'Under Review', 'Approved', 'Rejected']
    if new_status not in valid_statuses:
        flash('Invalid status selection.', 'error')
        return redirect(url_for('admin_applications'))

    conn = database.get_db()
    current_app = conn.execute("""
        SELECT a.*, u.full_name as applicant_name, s.title as scholarship_title
        FROM applications a
        JOIN users u ON a.user_id = u.id
        JOIN scholarships s ON a.scholarship_id = s.id
        WHERE a.id = ?
    """, (app_id,)).fetchone()

    if not current_app:
        conn.close()
        flash('Application not found.', 'error')
        return redirect(url_for('admin_applications'))

    old_status = current_app['status']
    reviewer_id = session['user_id']

    conn.execute("""
        UPDATE applications
        SET status = ?, admin_notes = ?, reviewed_by = ?, reviewed_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (new_status, admin_notes, reviewer_id, app_id))
    conn.commit()
    conn.close()

    # Log administrative audit
    database.log_audit(
        reviewer_id,
        'UPDATE_APPLICATION_STATUS',
        'application',
        app_id,
        f'Changed application #{app_id} ({current_app["applicant_name"]} - {current_app["scholarship_title"]}) status from "{old_status}" to "{new_status}". Notes: "{admin_notes}"',
        get_client_ip()
    )

    flash(f'Application #{app_id} status updated to {new_status}.', 'success')
    return redirect(request.referrer or url_for('admin_applications'))

@app.route('/admin/scholarships')
@admin_required
def admin_scholarships():
    """Page 12: Scholarship Management Page (Create, Edit, Toggle)."""
    conn = database.get_db()
    scholarships = conn.execute("""
        SELECT s.*, 
               COUNT(a.id) as total_applicants,
               SUM(CASE WHEN a.status = 'Approved' THEN 1 ELSE 0 END) as approved_count
        FROM scholarships s
        LEFT JOIN applications a ON s.id = a.scholarship_id
        GROUP BY s.id
        ORDER BY s.created_at DESC
    """).fetchall()
    conn.close()
    return render_template('admin/scholarships.html', scholarships=scholarships)

@app.route('/admin/scholarships/create', methods=['POST'])
@admin_required
def admin_create_scholarship():
    """Create a new scholarship."""
    title = request.form.get('title', '').strip()
    organization = request.form.get('organization', '').strip()
    description = request.form.get('description', '').strip()
    eligibility = request.form.get('eligibility', '').strip()
    amount_str = request.form.get('amount', '').strip()
    deadline = request.form.get('deadline', '').strip()
    category = request.form.get('category', '').strip()
    slots_str = request.form.get('slots', '1').strip()
    status = request.form.get('status', 'active')

    if not title or not organization or not description or not eligibility or not amount_str or not deadline:
        flash('Please fill in all required scholarship fields.', 'error')
        return redirect(url_for('admin_scholarships'))

    try:
        amount = float(amount_str)
        slots = int(slots_str) if slots_str else 1
    except ValueError:
        flash('Amount and slots must be valid numbers.', 'error')
        return redirect(url_for('admin_scholarships'))

    admin_id = session['user_id']
    conn = database.get_db()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO scholarships (title, organization, description, eligibility, amount, deadline, category, slots, status, created_by)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (title, organization, description, eligibility, amount, deadline, category, slots, status, admin_id))
    new_sch_id = cursor.lastrowid
    conn.commit()
    conn.close()

    database.log_audit(
        admin_id,
        'CREATE_SCHOLARSHIP',
        'scholarship',
        new_sch_id,
        f'Created new scholarship: "{title}" (${amount:,.0f}, Category: {category})',
        get_client_ip()
    )

    flash(f'Scholarship "{title}" created successfully!', 'success')
    return redirect(url_for('admin_scholarships'))

@app.route('/admin/scholarships/<int:scholarship_id>/edit', methods=['POST'])
@admin_required
def admin_edit_scholarship(scholarship_id):
    """Edit existing scholarship details."""
    title = request.form.get('title', '').strip()
    organization = request.form.get('organization', '').strip()
    description = request.form.get('description', '').strip()
    eligibility = request.form.get('eligibility', '').strip()
    amount_str = request.form.get('amount', '').strip()
    deadline = request.form.get('deadline', '').strip()
    category = request.form.get('category', '').strip()
    slots_str = request.form.get('slots', '1').strip()
    status = request.form.get('status', 'active')

    try:
        amount = float(amount_str)
        slots = int(slots_str)
    except ValueError:
        flash('Amount and slots must be valid numbers.', 'error')
        return redirect(url_for('admin_scholarships'))

    conn = database.get_db()
    conn.execute("""
        UPDATE scholarships
        SET title = ?, organization = ?, description = ?, eligibility = ?, amount = ?, deadline = ?, category = ?, slots = ?, status = ?, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (title, organization, description, eligibility, amount, deadline, category, slots, status, scholarship_id))
    conn.commit()
    conn.close()

    admin_id = session['user_id']
    database.log_audit(
        admin_id,
        'EDIT_SCHOLARSHIP',
        'scholarship',
        scholarship_id,
        f'Updated scholarship #{scholarship_id}: "{title}"',
        get_client_ip()
    )

    flash(f'Scholarship #{scholarship_id} updated successfully.', 'success')
    return redirect(url_for('admin_scholarships'))

@app.route('/admin/scholarships/<int:scholarship_id>/toggle-status', methods=['POST'])
@admin_required
def admin_toggle_scholarship_status(scholarship_id):
    """Toggle scholarship active/inactive status."""
    conn = database.get_db()
    scholarship = conn.execute("SELECT status, title FROM scholarships WHERE id = ?", (scholarship_id,)).fetchone()
    
    if not scholarship:
        conn.close()
        flash('Scholarship not found.', 'error')
        return redirect(url_for('admin_scholarships'))

    new_status = 'inactive' if scholarship['status'] == 'active' else 'active'
    conn.execute("UPDATE scholarships SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (new_status, scholarship_id))
    conn.commit()
    conn.close()

    admin_id = session['user_id']
    database.log_audit(
        admin_id,
        'TOGGLE_SCHOLARSHIP_STATUS',
        'scholarship',
        scholarship_id,
        f'Toggled status for "{scholarship["title"]}" to {new_status}',
        get_client_ip()
    )

    flash(f'Scholarship status changed to {new_status}.', 'success')
    return redirect(url_for('admin_scholarships'))

@app.route('/admin/audit-logs')
@admin_required
def admin_audit_logs():
    """Audit logs viewer for administrative compliance."""
    conn = database.get_db()
    logs = conn.execute("""
        SELECT l.*, u.full_name as user_name, u.email as user_email, u.role as user_role
        FROM audit_logs l
        LEFT JOIN users u ON l.user_id = u.id
        ORDER BY l.created_at DESC
        LIMIT 100
    """).fetchall()
    conn.close()
    return render_template('admin/audit_logs.html', logs=logs)

# ==============================================================================
# REST API Endpoints
# ==============================================================================

@app.route('/api/scholarships')
def api_scholarships():
    """REST endpoint returning active scholarships."""
    conn = database.get_db()
    rows = conn.execute("SELECT id, title, organization, amount, deadline, category, slots FROM scholarships WHERE status = 'active' ORDER BY deadline ASC").fetchall()
    conn.close()
    return jsonify([dict(row) for row in rows])

@app.route('/api/applications/<int:app_id>')
@admin_required
def api_application_detail(app_id):
    """REST endpoint returning single application details for modal view."""
    conn = database.get_db()
    app_data = conn.execute("""
        SELECT a.*, u.full_name, u.email, u.institution, u.major, s.title as scholarship_title, s.amount
        FROM applications a
        JOIN users u ON a.user_id = u.id
        JOIN scholarships s ON a.scholarship_id = s.id
        WHERE a.id = ?
    """, (app_id,)).fetchone()
    conn.close()
    if not app_data:
        return jsonify({'error': 'Not found'}), 404
    return jsonify(dict(app_data))

# ==============================================================================
# Error Handlers
# ==============================================================================

@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404

@app.errorhandler(403)
def access_forbidden(e):
    return render_template('403.html'), 403

@app.errorhandler(500)
def internal_server_error(e):
    return render_template('500.html'), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
