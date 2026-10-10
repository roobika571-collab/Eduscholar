import os
import sqlite3
from werkzeug.security import generate_password_hash

DATABASE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'instance')
DATABASE_PATH = os.path.join(DATABASE_DIR, 'eduscholar.db')

def get_db():
    """Returns a new database connection with row factory configured."""
    os.makedirs(DATABASE_DIR, exist_ok=True)
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def init_db():
    """Initializes the database schema and seeds initial data."""
    os.makedirs(DATABASE_DIR, exist_ok=True)
    conn = get_db()
    cursor = conn.cursor()

    # 1. Users Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        full_name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'student', -- 'student' or 'admin'
        phone TEXT,
        institution TEXT,
        major TEXT,
        gpa REAL,
        education_level TEXT,
        bio TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # 2. Scholarships Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS scholarships (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        organization TEXT NOT NULL,
        description TEXT NOT NULL,
        eligibility TEXT NOT NULL,
        amount REAL NOT NULL,
        deadline DATE NOT NULL,
        category TEXT NOT NULL,
        slots INTEGER DEFAULT 1,
        status TEXT NOT NULL DEFAULT 'active', -- 'active' or 'inactive'
        created_by INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (created_by) REFERENCES users (id)
    );
    """)

    # 3. Applications Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS applications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        scholarship_id INTEGER NOT NULL,
        gpa REAL NOT NULL,
        academic_level TEXT NOT NULL,
        essay TEXT NOT NULL,
        document_path TEXT,
        document_name TEXT,
        status TEXT NOT NULL DEFAULT 'Submitted', -- 'Submitted', 'Under Review', 'Approved', 'Rejected'
        admin_notes TEXT,
        reviewed_by INTEGER,
        reviewed_at TIMESTAMP,
        submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
        FOREIGN KEY (scholarship_id) REFERENCES scholarships (id) ON DELETE CASCADE,
        FOREIGN KEY (reviewed_by) REFERENCES users (id),
        UNIQUE (user_id, scholarship_id)
    );
    """)

    # 4. Audit Logs Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS audit_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        action TEXT NOT NULL,
        target_type TEXT NOT NULL,
        target_id INTEGER,
        details TEXT,
        ip_address TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users (id)
    );
    """)

    # Indices for performance
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_apps_user ON applications(user_id);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_apps_scholarship ON applications(scholarship_id);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_apps_status ON applications(status);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_logs(created_at);")

    # Seed Admin User if not exists
    cursor.execute("SELECT id FROM users WHERE email = ?", ('admin@eduscholar.org',))
    admin_row = cursor.fetchone()
    admin_id = None
    if not admin_row:
        admin_pass_hash = generate_password_hash("Admin@12345")
        cursor.execute("""
        INSERT INTO users (full_name, email, password_hash, role, phone, institution, education_level)
        VALUES (?, ?, ?, 'admin', ?, ?, ?)
        """, (
            'EduScholar Administrator',
            'admin@eduscholar.org',
            admin_pass_hash,
            '+1 (555) 019-2834',
            'EduScholar Global Foundation',
            'Postgraduate'
        ))
        admin_id = cursor.lastrowid
        # Log the creation
        cursor.execute("""
        INSERT INTO audit_logs (user_id, action, target_type, target_id, details, ip_address)
        VALUES (?, 'INITIALIZE_ADMIN', 'user', ?, 'Default system administrator provisioned', '127.0.0.1')
        """, (admin_id, admin_id))
    else:
        admin_id = admin_row['id']

    # Seed Sample Scholarships if empty
    cursor.execute("SELECT COUNT(*) as count FROM scholarships")
    if cursor.fetchone()['count'] == 0:
        sample_scholarships = [
            (
                "Global STEM Innovation Fellowship",
                "EduScholar Global Foundation",
                "Designed to support promising students pursuing cutting-edge degrees in Science, Technology, Engineering, or Mathematics. Recipients receive financial assistance and mentorship with leading tech researchers.",
                "Minimum GPA of 3.5. Enrolled in an undergraduate or graduate STEM degree program. Demonstrated project or research portfolio.",
                10000.00,
                "2026-12-15",
                "STEM",
                5,
                "active",
                admin_id
            ),
            (
                "Women in Tech Leadership Award",
                "Apex Computing Institute",
                "Empowering female identifying leaders in computer science, software engineering, and artificial intelligence to break barriers and drive innovation.",
                "Minimum GPA of 3.2. Identifying as a female student enrolled in a Computer Science or related engineering degree.",
                7500.00,
                "2026-11-30",
                "Women in Tech",
                8,
                "active",
                admin_id
            ),
            (
                "First-Generation Academic Opportunity Grant",
                "Horizon Education Trust",
                "Dedicated financial support for first-generation university students who have shown resilience, academic dedication, and community leadership.",
                "First-generation college student. Demonstrated financial need. Enrolled full-time in accredited university with GPA >= 3.0.",
                5000.00,
                "2026-12-01",
                "Need-Based",
                12,
                "active",
                admin_id
            ),
            (
                "Future Healthcare Pioneers Scholarship",
                "BioMed Health Alliance",
                "Supporting future physicians, nurses, biomedical engineers, and public health champions dedicated to underserved community care.",
                "Enrolled in Pre-Med, Nursing, Biology, Public Health, or Biomedical Sciences. Minimum GPA of 3.4.",
                12000.00,
                "2027-01-20",
                "Healthcare",
                4,
                "active",
                admin_id
            ),
            (
                "Creative Arts & Digital Media Fellowship",
                "Kalliope Arts Foundation",
                "Recognizing visionary storytellers, digital artists, animators, and media creators who push the boundaries of contemporary cultural expression.",
                "Portfolio submission required. Enrolled in Fine Arts, Digital Media, Animation, Graphic Design, or Creative Writing. GPA >= 3.0.",
                4500.00,
                "2026-11-15",
                "Arts & Humanities",
                6,
                "active",
                admin_id
            ),
            (
                "Sustainable Energy & Climate Scholars",
                "Green Earth Future Initiative",
                "Funding students dedicated to developing climate solutions, renewable energy technologies, and environmental policy research.",
                "Enrolled in Environmental Science, Energy Engineering, Sustainability, or Earth Sciences. GPA >= 3.3.",
                8500.00,
                "2026-12-28",
                "STEM",
                5,
                "active",
                admin_id
            )
        ]

        for s in sample_scholarships:
            cursor.execute("""
            INSERT INTO scholarships (title, organization, description, eligibility, amount, deadline, category, slots, status, created_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, s)

        cursor.execute("""
        INSERT INTO audit_logs (user_id, action, target_type, target_id, details, ip_address)
        VALUES (?, 'SEED_SCHOLARSHIPS', 'scholarship', 0, 'Seeded 6 initial official scholarship programs', '127.0.0.1')
        """, (admin_id,))

    conn.commit()
    conn.close()

def log_audit(user_id, action, target_type, target_id, details, ip_address='127.0.0.1'):
    """Helper function to record an audit log entry."""
    try:
        conn = get_db()
        conn.execute("""
        INSERT INTO audit_logs (user_id, action, target_type, target_id, details, ip_address)
        VALUES (?, ?, ?, ?, ?, ?)
        """, (user_id, action, target_type, target_id, details, ip_address))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[Audit Log Error] Failed to log audit: {e}")
