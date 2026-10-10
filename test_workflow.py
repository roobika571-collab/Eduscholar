import os
import io
import unittest
from app import app
import database

class TestEduScholarWorkflow(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False
        self.client = app.test_client()
        # Ensure database is initialized
        database.init_db()

    def test_01_landing_page(self):
        """Test landing page renders with active scholarships and metrics."""
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'EduScholar', response.data)
        self.assertIn(b'Direct Scholarships', response.data)

    def test_02_student_registration_and_login(self):
        """Test student registration and session establishment."""
        email = 'alex.rivera@stanford.edu'
        # Clean up if existing from previous run
        conn = database.get_db()
        conn.execute("DELETE FROM users WHERE email = ?", (email,))
        conn.commit()
        conn.close()

        # Step 1: Register
        with self.client:
            # First fetch register page to initialize csrf token in session
            resp = self.client.get('/register')
            csrf = self.client.get('/register').headers.get('Set-Cookie')

            # We can get csrf token from session
            with self.client.session_transaction() as sess:
                token = sess.get('csrf_token')

            reg_data = {
                'csrf_token': token,
                'full_name': 'Alex Rivera',
                'email': email,
                'password': 'Password@123',
                'confirm_password': 'Password@123',
                'phone': '+1 (555) 345-6789',
                'institution': 'Stanford University',
                'major': 'Computer Science',
                'education_level': 'Undergraduate',
                'gpa': '3.92'
            }
            res = self.client.post('/register', data=reg_data, follow_redirects=True)
            self.assertEqual(res.status_code, 200)
            self.assertIn(b'Welcome to EduScholar, Alex Rivera!', res.data)

            # Step 2: Verify in DB
            conn = database.get_db()
            user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
            self.assertIsNotNone(user)
            self.assertEqual(user['role'], 'student')
            self.assertEqual(user['full_name'], 'Alex Rivera')
            conn.close()

            # Logout
            self.client.get('/logout', follow_redirects=True)

            # Step 3: Log back in
            with self.client.session_transaction() as sess:
                token = sess.get('csrf_token')

            login_res = self.client.post('/login', data={
                'csrf_token': token,
                'email': email,
                'password': 'Password@123'
            }, follow_redirects=True)
            self.assertEqual(login_res.status_code, 200)
            self.assertIn(b'Welcome back, Alex Rivera!', login_res.data)

    def test_03_application_submission(self):
        """Test application submission with file upload."""
        with self.client:
            # Login as Alex
            self.client.get('/login')
            with self.client.session_transaction() as sess:
                token = sess.get('csrf_token')

            self.client.post('/login', data={
                'csrf_token': token,
                'email': 'alex.rivera@stanford.edu',
                'password': 'Password@123'
            }, follow_redirects=True)

            # Find active scholarship
            conn = database.get_db()
            sch = conn.execute("SELECT id, title FROM scholarships WHERE status = 'active' LIMIT 1").fetchone()
            sch_id = sch['id']
            conn.close()

            # Get token
            with self.client.session_transaction() as sess:
                token = sess.get('csrf_token')

            # Prepare fake PDF file
            fake_pdf = (io.BytesIO(b"%PDF-1.4 Official Transcript Content for Alex Rivera"), 'transcript.pdf')

            app_data = {
                'csrf_token': token,
                'gpa': '3.92',
                'academic_level': 'Undergraduate',
                'essay': 'I am deeply committed to applying machine learning techniques to environmental data analysis. Throughout my academic career at Stanford University, I have focused on solving real-world challenges.',
                'document': fake_pdf
            }

            res = self.client.post(f'/apply/{sch_id}', data=app_data, content_type='multipart/form-data', follow_redirects=True)
            self.assertEqual(res.status_code, 200)
            self.assertIn(b'Application successfully submitted', res.data)

            # Verify in DB
            conn = database.get_db()
            app_record = conn.execute("""
                SELECT a.*, u.email 
                FROM applications a 
                JOIN users u ON a.user_id = u.id 
                WHERE u.email = ? AND a.scholarship_id = ?
            """, ('alex.rivera@stanford.edu', sch_id)).fetchone()
            self.assertIsNotNone(app_record)
            self.assertEqual(app_record['status'], 'Submitted')
            conn.close()

    def test_04_admin_review_and_status_update(self):
        """Test administrative review, approval, and audit logging."""
        with self.client:
            # Login as Admin
            self.client.get('/admin/login')
            with self.client.session_transaction() as sess:
                token = sess.get('csrf_token')

            admin_res = self.client.post('/admin/login', data={
                'csrf_token': token,
                'email': 'admin@eduscholar.org',
                'password': 'Admin@12345'
            }, follow_redirects=True)
            self.assertEqual(admin_res.status_code, 200)
            self.assertIn(b'Operations Overview', admin_res.data)

            # Find Alex's application
            conn = database.get_db()
            app_record = conn.execute("""
                SELECT a.id FROM applications a
                JOIN users u ON a.user_id = u.id
                WHERE u.email = 'alex.rivera@stanford.edu'
            """).fetchone()
            app_id = app_record['id']
            conn.close()

            # Review and update to 'Approved'
            with self.client.session_transaction() as sess:
                token = sess.get('csrf_token')

            update_res = self.client.post(f'/admin/applications/{app_id}/status', data={
                'csrf_token': token,
                'status': 'Approved',
                'admin_notes': 'Outstanding academic record and exemplary essay. Fully approved for endowment award.'
            }, follow_redirects=True)
            self.assertEqual(update_res.status_code, 200)

            # Check DB updated
            conn = database.get_db()
            updated_app = conn.execute("SELECT * FROM applications WHERE id = ?", (app_id,)).fetchone()
            self.assertEqual(updated_app['status'], 'Approved')
            self.assertIn('Fully approved', updated_app['admin_notes'])

            # Verify Audit Log
            log_entry = conn.execute("""
                SELECT * FROM audit_logs 
                WHERE action = 'UPDATE_APPLICATION_STATUS' AND target_id = ?
                ORDER BY created_at DESC LIMIT 1
            """, (app_id,)).fetchone()
            self.assertIsNotNone(log_entry)
            self.assertIn('Approved', log_entry['details'])
            conn.close()

    def test_05_admin_scholarship_management(self):
        """Test admin creating and toggling a scholarship."""
        with self.client:
            # Login as Admin
            self.client.get('/admin/login')
            with self.client.session_transaction() as sess:
                token = sess.get('csrf_token')

            self.client.post('/admin/login', data={
                'csrf_token': token,
                'email': 'admin@eduscholar.org',
                'password': 'Admin@12345'
            }, follow_redirects=True)

            with self.client.session_transaction() as sess:
                token = sess.get('csrf_token')

            # Create scholarship
            new_sch_data = {
                'csrf_token': token,
                'title': 'Quantum Computing Future Minds Grant',
                'organization': 'Quantum Innovations Lab',
                'description': 'Encouraging undergraduate students researching quantum simulation and quantum algorithms.',
                'eligibility': 'GPA >= 3.7. Enrolled in Physics or Computer Science.',
                'amount': '15000',
                'deadline': '2026-12-31',
                'category': 'STEM',
                'slots': '3',
                'status': 'active'
            }
            res = self.client.post('/admin/scholarships/create', data=new_sch_data, follow_redirects=True)
            self.assertEqual(res.status_code, 200)

            conn = database.get_db()
            created_sch = conn.execute("SELECT * FROM scholarships WHERE title = ?", ('Quantum Computing Future Minds Grant',)).fetchone()
            self.assertIsNotNone(created_sch)
            self.assertEqual(created_sch['amount'], 15000.0)

            # Toggle status
            with self.client.session_transaction() as sess:
                token = sess.get('csrf_token')

            self.client.post(f'/admin/scholarships/{created_sch["id"]}/toggle-status', data={'csrf_token': token}, follow_redirects=True)
            toggled_sch = conn.execute("SELECT status FROM scholarships WHERE id = ?", (created_sch['id'],)).fetchone()
            self.assertEqual(toggled_sch['status'], 'inactive')
            conn.close()

    def test_06_security_role_enforcement(self):
        """Verify student cannot access admin routes."""
        with self.client:
            # Login as student
            self.client.get('/login')
            with self.client.session_transaction() as sess:
                token = sess.get('csrf_token')

            self.client.post('/login', data={
                'csrf_token': token,
                'email': 'alex.rivera@stanford.edu',
                'password': 'Password@123'
            }, follow_redirects=True)

            # Attempt to access admin dashboard
            res = self.client.get('/admin/dashboard', follow_redirects=False)
            # Should redirect to student dashboard with error
            self.assertEqual(res.status_code, 302)
            self.assertIn('/dashboard', res.headers['Location'])

if __name__ == '__main__':
    unittest.main()
