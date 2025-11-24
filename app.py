from flask import Flask, render_template, request, jsonify, session, Response, redirect
import pandas as pd
import numpy as np
from openpyxl import load_workbook
import os
import smtplib
from email.mime.text import MIMEText
import random
import secrets
from datetime import datetime, timedelta
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail, Email, To, Content
import sqlite3
from flask import g
import traceback

# Initialize Flask app FIRST
app = Flask(__name__)

# Manual environment variable loading (bypass Flask's dotenv)
def load_environment_variables():
    """Manually load environment variables from .env file"""
    try:
        if os.path.exists('.env'):
            with open('.env', 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#'):
                        if '=' in line:
                            key, value = line.split('=', 1)
                            os.environ[key] = value
                            print(f"Loaded: {key}")
            print("✅ Environment variables loaded successfully")
        else:
            print("⚠️  No .env file found, using defaults")
    except Exception as e:
        print(f"❌ Error loading .env: {e}")

# Load environment variables manually
load_environment_variables()

# Set configuration
app.secret_key = os.environ.get('SESSION_SECRET', 'dev-local-secret-key-12345')
# Set session to be permanent and set lifetime
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=24)

print(f"🌐 Environment: {os.environ.get('FLASK_ENV', 'development')}")
print(f"🔐 Secret key: {'Set' if app.secret_key else 'Not set'}")

# Global variables to store data
cities_by_tier = {}
avg_costs = {}
plan_ranges = {}
otp_storage = {}

# SendGrid Configuration
SENDGRID_CONFIG = {
    'api_key': os.environ.get('SENDGRID_API_KEY', ''),
    'from_email': os.environ.get('SENDGRID_FROM_EMAIL', 'dhruv@talenttrail.ai'),
    'from_name': os.environ.get('SENDGRID_FROM_NAME', 'GCC Setup Cost Calculator')
}

# ============================================================================
# VISITS TRACKER FUNCTIONS
# ============================================================================

def get_db():
    """Get SQLite database connection"""
    if 'db' not in g:
        g.db = sqlite3.connect('visits.db')
        g.db.row_factory = sqlite3.Row
    return g.db

def close_db(e=None):
    """Close database connection"""
    db = g.pop('db', None)
    if db is not None:
        db.close()

def init_db():
    """Initialize the database with required tables"""
    db = get_db()
    
    try:
        # Check if tables exist
        tables = db.execute("SELECT name FROM sqlite_master WHERE type='table' AND (name='user_visits' OR name='user_stats')").fetchall()
        
        if len(tables) < 2:
            print("🔄 Creating missing database tables...")
            # Create user_visits table
            db.execute('''
                CREATE TABLE IF NOT EXISTS user_visits (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    headcount INTEGER,
                    city TEXT,
                    tier TEXT,
                    plan TEXT,
                    real_estate BOOLEAN,
                    it_infra BOOLEAN,
                    enabling BOOLEAN,
                    technology BOOLEAN,
                    total_cost REAL,
                    visit_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Create user_stats table for summary data
            db.execute('''
                CREATE TABLE IF NOT EXISTS user_stats (
                    user_id TEXT PRIMARY KEY,
                    visit_count INTEGER DEFAULT 1,
                    first_visit TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_visit TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    total_calculations INTEGER DEFAULT 1
                )
            ''')
            
            db.commit()
            print("✅ Database tables created successfully")
        else:
            print("✅ Database tables already exist")
            
    except Exception as e:
        print(f"❌ Error initializing database: {e}")
        db.rollback()

def log_visit(user_data):
    """Log a user visit and update statistics"""
    if not user_data.get('user_id'):
        print("❌ log_visit: No user_id provided")
        return None
    
    db = get_db()
    
    try:
        print(f"📊 Logging visit for user: {user_data['user_id']}")
        print(f"📊 Visit data: {user_data}")
        
        # Insert the visit details
        cursor = db.execute('''
            INSERT INTO user_visits 
            (user_id, headcount, city, tier, plan, real_estate, it_infra, enabling, technology, total_cost)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            user_data['user_id'],
            user_data.get('headcount'),
            user_data.get('city'),
            user_data.get('tier'),
            user_data.get('plan'),
            user_data.get('real_estate', False),
            user_data.get('it_infra', False),
            user_data.get('enabling', False),
            user_data.get('technology', False),
            user_data.get('total_cost')
        ))
        
        visit_id = cursor.lastrowid
        print(f"✅ Visit record created with ID: {visit_id}")
        
        # Update or insert user statistics
        result = db.execute('''
            INSERT INTO user_stats (user_id, visit_count, total_calculations, last_visit)
            VALUES (?, 1, 1, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id) 
            DO UPDATE SET 
                visit_count = visit_count + 1,
                total_calculations = total_calculations + 1,
                last_visit = CURRENT_TIMESTAMP
        ''', (user_data['user_id'],))
        
        db.commit()
        print(f"✅ User stats updated for: {user_data['user_id']}")
        return visit_id
        
    except Exception as e:
        db.rollback()
        print(f"❌ Error logging visit for {user_data['user_id']}: {e}")
        print(f"❌ Full traceback: {traceback.format_exc()}")
        return None

def get_visit_stats():
    """Get comprehensive visit statistics"""
    db = get_db()
    
    try:
        # Basic counts
        stats = db.execute('''
            SELECT 
                COUNT(DISTINCT user_id) as unique_users,
                COUNT(*) as total_visits,
                COUNT(DISTINCT user_id) as total_users,
                SUM(CASE WHEN user_id IS NOT NULL AND user_id != '' THEN 1 ELSE 0 END) as visits_with_id
            FROM user_visits
        ''').fetchone()
        
        # Recent visits (last 50)
        recent_visits = db.execute('''
            SELECT user_id, headcount, city, plan, total_cost, visit_time
            FROM user_visits 
            WHERE user_id IS NOT NULL AND user_id != ''
            ORDER BY visit_time DESC 
            LIMIT 50
        ''').fetchall()
        
        # User ranking by visit count
        user_ranking = db.execute('''
            SELECT user_id, visit_count, first_visit, last_visit, total_calculations
            FROM user_stats 
            ORDER BY visit_count DESC, last_visit DESC
        ''').fetchall()
        
        # Popular configurations
        popular_cities = db.execute('''
            SELECT city, COUNT(*) as count
            FROM user_visits 
            WHERE city IS NOT NULL
            GROUP BY city 
            ORDER BY count DESC 
            LIMIT 10
        ''').fetchall()
        
        popular_plans = db.execute('''
            SELECT plan, COUNT(*) as count
            FROM user_visits 
            WHERE plan IS NOT NULL
            GROUP BY plan 
            ORDER BY count DESC
        ''').fetchall()
        
        return {
            'unique_users': stats['unique_users'],
            'total_visits': stats['total_visits'],
            'total_users': stats['total_users'],
            'visits_with_id': stats['visits_with_id'],
            'recent_visits': recent_visits,
            'user_ranking': user_ranking,
            'popular_cities': popular_cities,
            'popular_plans': popular_plans
        }
    except Exception as e:
        print(f"❌ Error getting visit stats: {e}")
        return {
            'unique_users': 0,
            'total_visits': 0,
            'total_users': 0,
            'visits_with_id': 0,
            'recent_visits': [],
            'user_ranking': [],
            'popular_cities': [],
            'popular_plans': []
        }

def get_user_details(user_id):
    """Get detailed history for a specific user"""
    db = get_db()
    
    try:
        user_info = db.execute('''
            SELECT * FROM user_stats WHERE user_id = ?
        ''', (user_id,)).fetchone()
        
        user_visits = db.execute('''
            SELECT * FROM user_visits 
            WHERE user_id = ? 
            ORDER BY visit_time DESC
        ''', (user_id,)).fetchall()
        
        return {
            'user_info': user_info,
            'user_visits': user_visits
        }
    except Exception as e:
        print(f"❌ Error getting user details for {user_id}: {e}")
        return {
            'user_info': None,
            'user_visits': []
        }

def export_data(format='json'):
    """Export all visit data"""
    import json
    
    db = get_db()
    
    try:
        visits = db.execute('''
            SELECT * FROM user_visits ORDER BY visit_time DESC
        ''').fetchall()
        
        stats = db.execute('''
            SELECT * FROM user_stats ORDER BY visit_count DESC
        ''').fetchall()
        
        data = {
            'visits': [dict(row) for row in visits],
            'stats': [dict(row) for row in stats],
            'export_time': datetime.now().isoformat()
        }
        
        if format == 'json':
            return json.dumps(data, indent=2, default=str)
        else:
            return data
    except Exception as e:
        print(f"❌ Error exporting data: {e}")
        return json.dumps({'error': str(e)}, indent=2)

# ============================================================================
# DATABASE INITIALIZATION - UPDATED FOR FLASK 3.0+
# ============================================================================

def initialize_database():
    """Initialize database on app startup"""
    with app.app_context():
        init_db()
        print("✅ Database initialized successfully")

@app.teardown_appcontext
def close_database(error):
    """Close database connection on teardown"""
    close_db()

# ============================================================================
# EMAIL AND OTP FUNCTIONS
# ============================================================================

def send_email_sendgrid(to_email, subject, body):
    """Send email using SendGrid API with detailed debugging"""
    try:
        # Check if SendGrid is configured
        if not SENDGRID_CONFIG['api_key']:
            print("❌ SendGrid not configured - please set SENDGRID_API_KEY")
            return False
        
        print(f"🔧 SendGrid Debug Info:")
        print(f"   API Key: {SENDGRID_CONFIG['api_key'][:10]}...")
        print(f"   From: {SENDGRID_CONFIG['from_email']}")
        print(f"   To: {to_email}")
        print(f"   Subject: {subject}")
        
        message = Mail(
            from_email=Email(SENDGRID_CONFIG['from_email'], SENDGRID_CONFIG['from_name']),
            to_emails=To(to_email),
            subject=subject,
            plain_text_content=Content("text/plain", body)
        )
        
        sg = SendGridAPIClient(SENDGRID_CONFIG['api_key'])
        response = sg.send(message)
        
        print(f"📨 SendGrid Response Status: {response.status_code}")
        
        if response.status_code in [200, 202]:
            print(f"✅ Email sent successfully to {to_email} via SendGrid")
            return True
        else:
            print(f"❌ SendGrid API error: {response.status_code}")
            print(f"❌ Response body: {response.body}")
            
            # Check for specific error codes
            if response.status_code == 403:
                print("🔒 Permission denied - check sender verification")
            elif response.status_code == 401:
                print("🔒 Unauthorized - check API key permissions")
            elif response.status_code == 400:
                print("📧 Bad request - check email format or content")
            elif response.status_code == 413:
                print("📧 Payload too large - reduce email content")
            elif response.status_code == 429:
                print("⏰ Rate limit exceeded - wait before sending more emails")
                
            return False
            
    except Exception as e:
        print(f"❌ SendGrid error: {str(e)}")
        print(f"❌ Full error traceback: {traceback.format_exc()}")
        return False

def send_email_smtp(to_email, subject, body):
    """Send email using SMTP with better error handling"""
    try:
        # SMTP configuration with fallbacks
        SMTP_CONFIG = {
            'server': os.environ.get('SMTP_SERVER', 'smtp.sendgrid.net'),
            'port': int(os.environ.get('SMTP_PORT', 587)),
            'username': os.environ.get('SMTP_USERNAME', 'apikey'),
            'password': os.environ.get('SMTP_PASSWORD', SENDGRID_CONFIG['api_key']),
            'from_name': 'GCC Setup Cost Calculator',
            'from_email': os.environ.get('FROM_EMAIL', 'dhruv@talenttrail.ai')
        }
        
        # Check if email is configured
        if not SMTP_CONFIG['username'] or not SMTP_CONFIG['password']:
            print("SMTP not configured - running in demo mode")
            return True  # Return True for demo mode
        
        msg = MIMEText(body)
        msg['Subject'] = subject
        msg['From'] = f"{SMTP_CONFIG['from_name']} <{SMTP_CONFIG['from_email']}>"
        msg['To'] = to_email
        
        print(f"🔧 SMTP Debug: Connecting to {SMTP_CONFIG['server']}:{SMTP_CONFIG['port']}")
        
        with smtplib.SMTP(SMTP_CONFIG['server'], SMTP_CONFIG['port']) as server:
            server.starttls()
            server.login(SMTP_CONFIG['username'], SMTP_CONFIG['password'])
            server.send_message(msg)
        
        print(f"✅ Email sent successfully to {to_email} via SMTP")
        return True
        
    except Exception as e:
        print(f"❌ SMTP error: {e}")
        return False

def send_email(to_email, subject, body):
    """Send email using SendGrid (primary) with SMTP fallback"""
    # Use SendGrid first
    print("🚀 Attempting to send email via SendGrid...")
    success = send_email_sendgrid(to_email, subject, body)
    
    if success:
        return True
    else:
        print("🔄 SendGrid failed, falling back to SMTP...")
        return send_email_smtp(to_email, subject, body)

def generate_otp():
    """Generate a 6-digit OTP"""
    return str(random.randint(100000, 999999))

def is_email_verified(email):
    """Check if email is already verified in session"""
    verified_emails = session.get('verified_emails', {})
    
    if email in verified_emails:
        # Check if verification is still valid (24 hours)
        verified_at = datetime.fromisoformat(verified_emails[email]['verified_at'])
        if datetime.now() - verified_at < timedelta(hours=24):
            return True
        else:
            # Remove expired verification
            del verified_emails[email]
            session['verified_emails'] = verified_emails
            return False
    return False

def add_verified_email(email, organization):
    """Add email to verified emails list in session"""
    verified_emails = session.get('verified_emails', {})
    verified_emails[email] = {
        'organization': organization,
        'verified_at': datetime.now().isoformat()
    }
    session['verified_emails'] = verified_emails
    session.modified = True

# ============================================================================
# DATA LOADING AND CALCULATION FUNCTIONS
# ============================================================================

def load_data():
    """Load data from Excel file and prepare for use"""
    global cities_by_tier, avg_costs, plan_ranges
    
    try:
        # Load the Excel file
        file_path = 'GCC Calculator.xlsx'
        if not os.path.exists(file_path):
            print(f"Error: File {file_path} not found")
            return False
        
        # Load Real Estate data
        real_estate_df = pd.read_excel(file_path, sheet_name='Real_Estate')
        
        # Load IT Infrastructure data
        it_infra_df = pd.read_excel(file_path, sheet_name='IT_Infra')
        
        # Load Plans data
        plans_df = pd.read_excel(file_path, sheet_name='Plans')
        
        # Load Lookup Helper for city lists
        lookup_df = pd.read_excel(file_path, sheet_name='Lookup_Helper')
        
        # Prepare cities by tier
        cities_by_tier.clear()
        cities_by_tier['Tier 1'] = lookup_df['Tier 1'].dropna().tolist()
        cities_by_tier['Tier 2'] = lookup_df['Tier 2'].dropna().tolist()
        cities_by_tier['Tier 3'] = lookup_df['Tier 3'].dropna().tolist()
        
        # Calculate average costs by tier
        avg_costs.clear()
        for tier in ['Tier 1', 'Tier 2', 'Tier 3']:
            tier_cities = cities_by_tier[tier]
            
            # Real estate average
            real_estate_avg = real_estate_df[
                real_estate_df['City'].isin(tier_cities)
            ]['Cost_INR_PM'].mean()
            
            # IT infrastructure average
            it_infra_avg = it_infra_df[
                it_infra_df['City'].isin(tier_cities)
            ]['Cost_INR_PM'].mean()
            
            avg_costs[tier] = {
                'real_estate': float(real_estate_avg) if not pd.isna(real_estate_avg) else 0,
                'it_infra': float(it_infra_avg) if not pd.isna(it_infra_avg) else 0
            }
        
        # Prepare plan ranges
        plan_ranges.clear()
        plan_ranges['Basic'] = {
            'min': float(plans_df['Enab_Basic'].min() + plans_df['Tech_Basic'].min()),
            'max': float(plans_df['Enab_Basic'].max() + plans_df['Tech_Basic'].max())
        }
        plan_ranges['Premium'] = {
            'min': float(plans_df['Enab_Premium'].min() + plans_df['Tech_Premium'].min()),
            'max': float(plans_df['Enab_Premium'].max() + plans_df['Tech_Premium'].max())
        }
        plan_ranges['Advance'] = {
            'min': float(plans_df['Enab_Advance'].min() + plans_df['Tech_Advance'].min()),
            'max': float(plans_df['Enab_Advance'].max() + plans_df['Tech_Advance'].max())
        }
        
        print("✅ Data loaded successfully")
        return True
        
    except Exception as e:
        print(f"❌ Error loading data: {str(e)}")
        return False

def get_plan_details_by_headcount(plan, headcount):
    """Get plan details based on plan and headcount range"""
    # Get headcount range
    if headcount <= 50:
        headcount_range = '0-50'
    elif headcount <= 100:
        headcount_range = '51-100'
    elif headcount <= 250:
        headcount_range = '101-250'
    elif headcount <= 500:
        headcount_range = '251-500'
    else:
        headcount_range = '501-1000'
    
    # Plan details configuration
    plan_details_by_headcount = {
        'Basic': {
            '0-50': {
                'name': 'Basic Plan',
                'description': 'Essential GCC setup with core functionality',
                'real_estate': 'Managed Workspace',
                'it_infra': 'Hardware, Networking, Security solutions, Cloud, IT Support, Collaboration tools, Data-centre, Disaster-recovery backups, Compliance & audits, End-user peripherals, cybersecurity (SIEM/DLP), Biometric attendance/access',
                'enabling_functions': 'HR/Admin , Finance , IT Support ',
                'technology': 'Zoho People , Zoho Recruit , Zoho Books Std , Google Workspace/Slack '
            },
            '51-100': {
                'name': 'Basic Plan',
                'description': 'Essential GCC setup with core functionality',
                'real_estate': 'Managed Workspace',
                'it_infra': 'Hardware, Networking, Security solutions, Cloud, IT Support, Collaboration tools, Data-centre, Disaster-recovery backups, Compliance & audits, End-user peripherals, cybersecurity (SIEM/DLP), Biometric attendance/access',
                'enabling_functions': 'HR , Finance , Admin , IT Helpdesk ',
                'technology': 'Keka (HR+Payroll ₹7,500), QuickBooks Advanced (₹6,500), Slack/Workspace (₹3,000)'
            },
            '101-250': {
                'name': 'Basic Plan',
                'description': 'Essential GCC setup with core functionality',
                'real_estate': 'Managed Workspace',
                'it_infra': 'Hardware, Networking, Security solutions, Cloud, IT Support, Collaboration tools, Data-centre, Disaster-recovery backups, Compliance & audits, End-user peripherals, cybersecurity (SIEM/DLP), Biometric attendance/access',
                'enabling_functions': 'HR , Finance , Admin , IT ',
                'technology': 'Darwinbox , Zoho Books Pro , Slack/Workspace '
            },
            '251-500': {
                'name': 'Basic Plan',
                'description': 'Essential GCC setup with core functionality',
                'real_estate': 'Managed Workspace',
                'it_infra': 'Hardware, Networking, Security solutions, Cloud, IT Support, Collaboration tools, Data-centre, Disaster-recovery backups, Compliance & audits, End-user peripherals, cybersecurity (SIEM/DLP), Biometric attendance/access',
                'enabling_functions': 'HRBP + Ops , Finance , Admin , IT ',
                'technology': 'Darwinbox , NetSuite ERP , Slack '
            },
            '501-1000': {
                'name': 'Basic Plan',
                'description': 'Essential GCC setup with core functionality',
                'real_estate': 'Managed Workspace',
                'it_infra': 'Hardware, Networking, Security solutions, Cloud, IT Support, Collaboration tools, Data-centre, Disaster-recovery backups, Compliance & audits, End-user peripherals, cybersecurity (SIEM/DLP), Biometric attendance/access',
                'enabling_functions': 'Full Enabling COEs with Mid Mgmt layers (HR, Finance, Admin, IT) ',
                'technology': 'SAP SuccessFactors , SAP B1/Oracle ERP , Slack '
            }
        },
        'Premium': {
            '0-50': {
                'name': 'Premium Plan',
                'description': 'Enhanced GCC setup with additional features',
                'real_estate': 'Managed Workspace',
                'it_infra': 'Hardware, Networking, Security solutions, Cloud/SaaS, IT Support & AMC, Collaboration tools, Data-centre/Colocation, Disaster-recovery backups, Compliance & audits, End-user peripherals, Advanced cybersecurity (SIEM/DLP), Biometric attendance/access',
                'enabling_functions': 'Marketing , Legal , Finance/Vendor Mgmt ',
                'technology': 'Zoho People , Zoho Recruit , Zoho Books Std , Zoho Campaigns , Zoho Contracts , Slack/Workspace '
            },
            '51-100': {
                'name': 'Premium Plan',
                'description': 'Enhanced GCC setup with additional features',
                'real_estate': 'Managed Workspace',
                'it_infra': 'Hardware, Networking, Security solutions, Cloud/SaaS, IT Support & AMC, Collaboration tools, Data-centre/Colocation, Disaster-recovery backups, Compliance & audits, End-user peripherals, Advanced cybersecurity (SIEM/DLP), Biometric attendance/access',
                'enabling_functions': 'Marketing , Legal , Finance/Vendor Mgmt , Other ',
                'technology': 'Keka , QuickBooks Adv , HubSpot Starter , Zoho Contracts , Slack/Workspace '
            },
            '101-250': {
                'name': 'Premium Plan',
                'description': 'Enhanced GCC setup with additional features',
                'real_estate': 'Managed Workspace',
                'it_infra': 'Hardware, Networking, Security solutions, Cloud/SaaS, IT Support & AMC, Collaboration tools, Data-centre/Colocation, Disaster-recovery backups, Compliance & audits, End-user peripherals, Advanced cybersecurity (SIEM/DLP), Biometric attendance/access',
                'enabling_functions': 'Marketing , Legal , Finance/Vendor Mgmt , Other ',
                'technology': 'Darwinbox , Zoho Books Pro , HubSpot Pro , DocuSign CLM , Slack '
            },
            '251-500': {
                'name': 'Premium Plan',
                'description': 'Enhanced GCC setup with additional features',
                'real_estate': 'Managed Workspace',
                'it_infra': 'Hardware, Networking, Security solutions, Cloud/SaaS, IT Support & AMC, Collaboration tools, Data-centre/Colocation, Disaster-recovery backups, Compliance & audits, End-user peripherals, Advanced cybersecurity (SIEM/DLP), Biometric attendance/access',
                'enabling_functions': 'Marketing , Legal , Finance/Vendor Mgmt , Other ',
                'technology': 'Darwinbox , NetSuite ERP , HubSpot Pro , DocuSign CLM , Slack '
            },
            '501-1000': {
                'name': 'Premium Plan',
                'description': 'Enhanced GCC setup with additional features',
                'real_estate': 'Managed Workspace',
                'it_infra': 'Hardware, Networking, Security solutions, Cloud/SaaS, IT Support & AMC, Collaboration tools, Data-centre/Colocation, Disaster-recovery backups, Compliance & audits, End-user peripherals, Advanced cybersecurity (SIEM/DLP), Biometric attendance/access',
                'enabling_functions': 'Marketing , Legal , Finance/Vendor Mgmt , Other ',
                'technology': 'SAP SuccessFactors , SAP B1/Oracle ERP , Salesforce Marketing Cloud , DocuSign CLM , Slack '
            }
        },
        'Advance': {
            '0-50': {
                'name': 'Advance Plan',
                'description': 'Comprehensive GCC setup with full customization',
                'real_estate': 'Managed Workspace',
                'it_infra': 'Hardware, Networking, Security solutions, Cloud/SaaS, IT Support & AMC, Collaboration tools, Data-centre/Colocation, Disaster-recovery backups, Compliance & audits, End-user peripherals, Advanced cybersecurity (SIEM/DLP), Biometric attendance/access',
                'enabling_functions': 'Marketing , Legal , Finance , Vendor Mgmt ',
                'technology': 'Keka , QuickBooks Adv , HubSpot Starter , DocuSign CLM , Slack + Notion '
            },
            '51-100': {
                'name': 'Advance Plan',
                'description': 'Comprehensive GCC setup with full customization',
                'real_estate': 'Managed Workspace',
                'it_infra': 'Hardware, Networking, Security solutions, Cloud/SaaS, IT Support & AMC, Collaboration tools, Data-centre/Colocation, Disaster-recovery backups, Compliance & audits, End-user peripherals, Advanced cybersecurity (SIEM/DLP), Biometric attendance/access',
                'enabling_functions': 'Marketing , Legal , Finance/Vendor Mgmt , Other ',
                'technology': 'Darwinbox , QuickBooks Adv , HubSpot Pro , DocuSign CLM , Slack + Notion '
            },
            '101-250': {
                'name': 'Advance Plan',
                'description': 'Comprehensive GCC setup with full customization',
                'real_estate': 'Managed Workspace',
                'it_infra': 'Hardware, Networking, Security solutions, Cloud/SaaS, IT Support & AMC, Collaboration tools, Data-centre/Colocation, Disaster-recovery backups, Compliance & audits, End-user peripherals, Advanced cybersecurity (SIEM/DLP), Biometric attendance/access',
                'enabling_functions': 'Marketing , Legal , Finance/Vendor Mgmt , Other ',
                'technology': 'Darwinbox, NetSuite ERP , Marketo Pro , DocuSign CLM , Slack + Notion '
            },
            '251-500': {
                'name': 'Advance Plan',
                'description': 'Comprehensive GCC setup with full customization',
                'real_estate': 'Managed Workspace',
                'it_infra': 'Hardware, Networking, Security solutions, Cloud/SaaS, IT Support & AMC, Collaboration tools, Data-centre/Colocation, Disaster-recovery backups, Compliance & audits, End-user peripherals, Advanced cybersecurity (SIEM/DLP), Biometric attendance/access',
                'enabling_functions': 'Marketing , Legal , Finance/Vendor Mgmt , Other ',
                'technology': 'SAP SuccessFactors , SAP B1 ERP , Marketo Pro , Agiloft CLM , Slack Grid + Notion '
            },
            '501-1000': {
                'name': 'Advance Plan',
                'description': 'Comprehensive GCC setup with full customization',
                'real_estate': 'Managed Workspace',
                'it_infra': 'Hardware, Networking, Security solutions, Cloud/SaaS, IT Support & AMC, Collaboration tools, Data-centre/Colocation, Disaster-recovery backups, Compliance & audits, End-user peripherals, Advanced cybersecurity (SIEM/DLP), Biometric attendance/access',
                'enabling_functions': 'Marketing , Legal , Finance/Vendor Mgmt , Other ',
                'technology': 'SAP SuccessFactors , Oracle ERP Cloud , Salesforce Marketing Cloud , Agiloft CLM , Slack Grid + Notion '
            }
        }
    }
    
    return plan_details_by_headcount.get(plan, {}).get(headcount_range, {})

def convert_to_serializable(obj):
    """Convert numpy/pandas types to Python native types for JSON serialization"""
    if isinstance(obj, (np.integer, np.int64)):
        return int(obj)
    elif isinstance(obj, (np.floating, np.float64)):
        return float(obj)
    elif isinstance(obj, pd.Series):
        return obj.tolist()
    elif isinstance(obj, pd.DataFrame):
        return obj.to_dict()
    elif isinstance(obj, dict):
        return {key: convert_to_serializable(value) for key, value in obj.items()}
    elif isinstance(obj, list):
        return [convert_to_serializable(item) for item in obj]
    else:
        return obj

def get_cost_for_city(city, component):
    """Get cost for a specific city and component"""
    try:
        file_path = 'GCC Calculator.xlsx'
        
        if component == 'real_estate':
            df = pd.read_excel(file_path, sheet_name='Real_Estate')
            cost_col = 'Cost_INR_PM'
        elif component == 'it_infra':
            df = pd.read_excel(file_path, sheet_name='IT_Infra')
            cost_col = 'Cost_INR_PM'
        else:
            return 0
        
        city_data = df[df['City'] == city]
        if not city_data.empty:
            cost = city_data[cost_col].iloc[0]
            return float(cost) if not pd.isna(cost) else 0
        else:
            # Return average for tier if city not found
            tier = None
            for t, cities in cities_by_tier.items():
                if city in cities:
                    tier = t
                    break
            
            if tier and tier in avg_costs:
                if component == 'real_estate':
                    return avg_costs[tier]['real_estate']
                else:
                    return avg_costs[tier]['it_infra']
            else:
                return 0
                
    except Exception as e:
        print(f"Error getting cost for {city}, {component}: {str(e)}")
        return 0

def get_plan_costs(headcount, plan):
    """Get enabling functions and technology costs for a plan and headcount"""
    try:
        file_path = 'GCC Calculator.xlsx'
        plans_df = pd.read_excel(file_path, sheet_name='Plans')
        
        # Find the appropriate headcount range
        headcount_ranges = [
            (0, 50), (51, 100), (101, 250), (251, 500), (501, 1000)
        ]
        
        selected_range = None
        for min_hc, max_hc in headcount_ranges:
            if min_hc <= headcount <= max_hc:
                selected_range = (min_hc, max_hc)
                break
        
        if not selected_range:
            # Use the highest range if headcount exceeds 1000
            selected_range = (501, 1000)
        
        # Find the row with matching headcount range
        mask = (plans_df['MinHC'] == selected_range[0]) & (plans_df['MaxHC'] == selected_range[1])
        plan_data = plans_df[mask]
        
        if plan_data.empty:
            return 0, 0
        
        if plan == 'Basic':
            enab_cost = plan_data['Enab_Basic'].iloc[0]
            tech_cost = plan_data['Tech_Basic'].iloc[0]
        elif plan == 'Premium':
            enab_cost = plan_data['Enab_Premium'].iloc[0]
            tech_cost = plan_data['Tech_Premium'].iloc[0]
        elif plan == 'Advance':
            enab_cost = plan_data['Enab_Advance'].iloc[0]
            tech_cost = plan_data['Tech_Advance'].iloc[0]
        else:
            return 0, 0
        
        return float(enab_cost) if not pd.isna(enab_cost) else 0, float(tech_cost) if not pd.isna(tech_cost) else 0
        
    except Exception as e:
        print(f"Error getting plan costs: {str(e)}")
        return 0, 0

# ============================================================================
# FLASK ROUTES
# ============================================================================

# Test SendGrid Route
@app.route('/test-sendgrid')
def test_sendgrid():
    """Test SendGrid email functionality"""
    test_email = "dhruv@talenttrail.ai"
    subject = "🎉 SendGrid Test - GCC Calculator"
    body = """
    Congratulations! Your SendGrid integration is working perfectly.
    
    This email was sent via SendGrid from your GCC Setup Cost Calculator.
    
    ✅ Email: dhruv@talenttrail.ai
    ✅ Status: Verified
    ✅ Mode: Production
    
    You can now send OTP verification emails to your users.
    
    Best regards,
    GCC Calculator Team
    Talenttrail AI
    """
    
    print("=" * 50)
    print("🧪 SENDGRID EMAIL TEST")
    print("=" * 50)
    
    success = send_email(test_email, subject, body)
    
    if success:
        return jsonify({
            "status": "success", 
            "message": "Test email sent successfully!",
            "method": "SendGrid",
            "from": SENDGRID_CONFIG['from_email'],
            "to": test_email
        })
    else:
        return jsonify({
            "status": "error", 
            "message": "Failed to send test email.",
            "method": "SendGrid + SMTP Fallback"
        })

# Debug SendGrid Configuration
@app.route('/debug-sendgrid')
def debug_sendgrid():
    return jsonify({
        "api_key_set": bool(SENDGRID_CONFIG['api_key']),
        "api_key_prefix": SENDGRID_CONFIG['api_key'][:10] + "..." if SENDGRID_CONFIG['api_key'] else "Not set",
        "from_email": SENDGRID_CONFIG['from_email'],
        "from_name": SENDGRID_CONFIG['from_name'],
        "environment": os.environ.get('FLASK_ENV', 'development')
    })

# OTP Verification Routes
@app.route('/api/send-otp', methods=['POST'])
def send_otp():
    try:
        data = request.get_json()
        email = data.get('email', '').lower().strip()
        organization = data.get('organization', '').strip()
        
        if not email or not organization:
            return jsonify({'error': 'Email and organization name are required'}), 400
        
        # Check if email is already verified
        if is_email_verified(email):
            return jsonify({
                'already_verified': True,
                'message': 'Email is already verified. Proceeding to calculation...'
            })
        
        # Generate OTP
        otp = generate_otp()
        otp_id = secrets.token_urlsafe(16)
        
        # Store OTP with timestamp and organization info
        otp_storage[otp_id] = {
            'email': email,
            'otp': otp,
            'organization': organization,
            'created_at': datetime.now(),
            'attempts': 0
        }
        
        # Always print OTP to console for development
        print(f" OTP for {email} ({organization}): {otp}")
        
        # Send email using SendGrid with SMTP fallback
        subject = " Your GCC Calculator Verification Code"
        body = f"""
        Hello,

        Your verification code for the GCC Setup Cost Calculator is:

         {otp}

        This code will expire in 10 minutes.

        Organization: {organization}
        Email: {email}

        Need help? Contact support at support@gatewai.io

        Best regards,
        GCC Setup Cost Calculator Team
        GatewAI
        """
        
        email_sent = send_email(email, subject, body)
        
        if email_sent:
            # Store OTP ID in session for verification
            session['otp_id'] = otp_id
            session['pending_email'] = email
            
            return jsonify({
                'success': True,
                'message': 'OTP sent successfully to your email'
            })
        else:
            # Even if email fails, we allow continuation with console OTP
            session['otp_id'] = otp_id
            session['pending_email'] = email
            return jsonify({
                'success': True,
                'message': 'OTP generated (check console for development)',
                'demo_otp': otp  # Include OTP in response for development
            })
            
    except Exception as e:
        print(f"OTP sending error: {e}")
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/api/verify-otp', methods=['POST'])
def verify_otp():
    try:
        data = request.get_json()
        email = data.get('email', '').lower().strip()
        otp = data.get('otp', '').strip()
        
        if not email or not otp:
            return jsonify({'error': 'Email and OTP are required'}), 400
        
        otp_id = session.get('otp_id')
        if not otp_id or otp_id not in otp_storage:
            return jsonify({'verified': False, 'error': 'OTP session expired'})
        
        otp_data = otp_storage[otp_id]
        
        # Check if OTP has expired (10 minutes)
        if datetime.now() - otp_data['created_at'] > timedelta(minutes=10):
            del otp_storage[otp_id]
            return jsonify({'verified': False, 'error': 'OTP expired'})
        
        # Check attempts
        if otp_data['attempts'] >= 3:
            del otp_storage[otp_id]
            return jsonify({'verified': False, 'error': 'Too many attempts'})
        
        # Verify OTP
        otp_data['attempts'] += 1
        
        if otp_data['email'] != email:
            return jsonify({'verified': False, 'error': 'Email mismatch'})
        
        if otp_data['otp'] == otp:
            # OTP verified successfully
            # Add to verified emails list
            add_verified_email(email, otp_data['organization'])
            
            # Clean up OTP storage and session
            del otp_storage[otp_id]
            session.pop('otp_id', None)
            session.pop('pending_email', None)
            
            return jsonify({
                'verified': True,
                'message': 'Email verified successfully'
            })
        else:
            remaining_attempts = 3 - otp_data['attempts']
            return jsonify({
                'verified': False, 
                'error': f'Invalid OTP. {remaining_attempts} attempts remaining.'
            })
            
    except Exception as e:
        print(f"OTP verification error: {e}")
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/api/check-verification', methods=['POST'])
def check_verification():
    """Check if email is already verified"""
    try:
        data = request.get_json()
        email = data.get('email', '').lower().strip()
        
        if not email:
            return jsonify({'error': 'Email is required'}), 400
        
        if is_email_verified(email):
            verified_emails = session.get('verified_emails', {})
            organization = verified_emails[email]['organization']
            return jsonify({
                'verified': True,
                'organization': organization,
                'message': 'Email is already verified'
            })
        else:
            return jsonify({
                'verified': False,
                'message': 'Email verification required'
            })
            
    except Exception as e:
        print(f"Verification check error: {e}")
        return jsonify({'error': 'Internal server error'}), 500

# Updated calculate route to use verified email as user_id
@app.route('/calculate', methods=['POST'])
def calculate():
    """Calculate costs based on user input"""
    try:
        # Get the email from session (if any)
        pending_email = session.get('pending_email')
        
        # Check if we have a pending verification that was just completed
        if pending_email and is_email_verified(pending_email):
            verified_email = pending_email
            verified_emails = session.get('verified_emails', {})
            organization = verified_emails[verified_email]['organization']
            user_id = verified_email  # Use verified email as user ID for tracking
        else:
            # For direct form submission without OTP, we don't require verification
            # This maintains backward compatibility
            verified_email = None
            organization = None
            user_id = None  # No user ID if not verified

        # Get form data
        headcount = int(request.form.get('headcount', 100))
        tier = request.form.get('tier', 'Tier 1')
        city = request.form.get('city', 'Bengaluru')
        plan = request.form.get('plan', 'Basic')
        
        # DEBUG: Print user_id to console
        print(f"🔍 DEBUG - User ID from verified email: '{user_id}'")
        print(f"🔍 DEBUG - Form data: headcount={headcount}, city={city}, plan={plan}")
        
        # Component toggles
        real_estate_toggle = request.form.get('real_estate') == 'on'
        it_infra_toggle = request.form.get('it_infra') == 'on'
        enabling_toggle = request.form.get('enabling') == 'on'
        technology_toggle = request.form.get('technology') == 'on'
        
        # Calculate costs
        total_cost = 0
        cost_breakdown = {}
        
        # Real Estate Cost
        if real_estate_toggle:
            real_estate_cost_per_seat = get_cost_for_city(city, 'real_estate')
            total_real_estate_cost = real_estate_cost_per_seat * headcount
            total_cost += total_real_estate_cost
            cost_breakdown['real_estate'] = total_real_estate_cost
        else:
            total_real_estate_cost = 0
        
        # IT Infrastructure Cost
        if it_infra_toggle:
            it_infra_cost_per_seat = get_cost_for_city(city, 'it_infra')
            total_it_infra_cost = it_infra_cost_per_seat * headcount
            total_cost += total_it_infra_cost
            cost_breakdown['it_infra'] = total_it_infra_cost
        else:
            total_it_infra_cost = 0
        
        # Enabling Functions Cost
        if enabling_toggle:
            enab_cost, _ = get_plan_costs(headcount, plan)
            total_cost += enab_cost
            cost_breakdown['enabling'] = enab_cost
        else:
            enab_cost = 0
        
        # Technology Cost
        if technology_toggle:
            _, tech_cost = get_plan_costs(headcount, plan)
            total_cost += tech_cost
            cost_breakdown['technology'] = tech_cost
        else:
            tech_cost = 0
        
        # Calculate hourly cost per head in USD
        hours_per_month = 120
        usd_to_inr = 85
        hourly_cost_per_head_usd = (total_cost / headcount / hours_per_month / usd_to_inr) if headcount > 0 else 0
        
        # Get plan details based on headcount
        plan_details = get_plan_details_by_headcount(plan, headcount)
        
        # Prepare results
        results = {
            'headcount': int(headcount),
            'tier': str(tier),
            'city': str(city),
            'plan': str(plan),
            'total_cost': float(total_cost),
            'hourly_cost_per_head_usd': float(hourly_cost_per_head_usd),
            'total_real_estate_cost': float(total_real_estate_cost),
            'total_it_infra_cost': float(total_it_infra_cost),
            'enab_cost': float(enab_cost),
            'tech_cost': float(tech_cost),
            'real_estate_toggle': bool(real_estate_toggle),
            'it_infra_toggle': bool(it_infra_toggle),
            'enabling_toggle': bool(enabling_toggle),
            'technology_toggle': bool(technology_toggle),
            'plan_details': plan_details,
            'verified_email': verified_email,
            'organization': organization
        }
        
        # Log the visit if user_id is provided (from verified email)
        if user_id:
            print(f"📝 Attempting to log visit for user: {user_id}")
            visit_data = {
                'user_id': user_id,
                'headcount': headcount,
                'city': city,
                'tier': tier,
                'plan': plan,
                'real_estate': real_estate_toggle,
                'it_infra': it_infra_toggle,
                'enabling': enabling_toggle,
                'technology': technology_toggle,
                'total_cost': total_cost
            }
            visit_id = log_visit(visit_data)
            if visit_id:
                print(f"✅ Successfully logged visit ID: {visit_id} for user: {user_id}")
            else:
                print(f"❌ Failed to log visit for user: {user_id}")
        else:
            print("⚠️ No verified email (user_id), skipping visit logging")
        
        return render_template('results.html', 
                             results=results, 
                             cities_by_tier=convert_to_serializable(cities_by_tier))
        
    except Exception as e:
        print(f"Error in calculate route: {str(e)}")
        return f"Error calculating costs: {str(e)}", 500

# ============================================================================
# ADMIN ROUTES FOR VISITS TRACKER
# ============================================================================

@app.route('/admin/stats')
def admin_stats():
    """Admin page to view statistics"""
    stats = get_visit_stats()
    return render_template('admin_stats.html', stats=stats)

@app.route('/admin/user/<user_id>')
def user_details(user_id):
    """Detailed view for a specific user"""
    user_data = get_user_details(user_id)
    return render_template('user_details.html', user_data=user_data, user_id=user_id)

@app.route('/admin/export')
def export_visits():
    """Export all data as JSON"""
    data = export_data('json')
    return Response(
        data,
        mimetype="application/json",
        headers={"Content-disposition": "attachment; filename=visits_export.json"}
    )

@app.route('/admin')
def admin_home():
    return redirect('/admin/stats')

# ============================================================================
# DEBUG ROUTES
# ============================================================================

@app.route('/admin/debug-db')
def debug_database():
    """Debug route to check database contents"""
    db = get_db()
    
    try:
        # Check user_visits table
        visits = db.execute('SELECT * FROM user_visits ORDER BY visit_time DESC').fetchall()
        visits_data = [dict(row) for row in visits]
        
        # Check user_stats table
        stats = db.execute('SELECT * FROM user_stats ORDER BY last_visit DESC').fetchall()
        stats_data = [dict(row) for row in stats]
        
        return jsonify({
            'user_visits_count': len(visits_data),
            'user_stats_count': len(stats_data),
            'user_visits': visits_data,
            'user_stats': stats_data
        })
    except Exception as e:
        return jsonify({
            'error': str(e),
            'traceback': traceback.format_exc()
        })

# ============================================================================
# EXISTING ROUTES
# ============================================================================

@app.route('/')
def index():
    """Main page"""
    tiers = list(cities_by_tier.keys())
    return render_template('index.html', 
                         tiers=tiers,
                         cities_by_tier=convert_to_serializable(cities_by_tier),
                         avg_costs=convert_to_serializable(avg_costs),
                         plan_ranges=convert_to_serializable(plan_ranges))

@app.route('/api/cities/<tier>')
def get_cities_by_tier(tier):
    """API endpoint to get cities by tier"""
    cities = cities_by_tier.get(tier, [])
    return jsonify(convert_to_serializable(cities))

@app.route('/api/plan_details')
def get_plan_details():
    """API endpoint to get plan details for specific plan and headcount"""
    plan = request.args.get('plan', 'Basic')
    headcount = int(request.args.get('headcount', 100))
    
    plan_details = get_plan_details_by_headcount(plan, headcount)
    return jsonify(convert_to_serializable(plan_details))

if __name__ == '__main__':
    # Load data on startup
    if load_data():
        # Initialize database
        initialize_database()
        
        print("🚀 Starting GCC Cost Calculator...")
        print("✅ OTP Verification: Active (24-hour memory)")
        print("✅ SendGrid Integration: Active")
        print("✅ SMTP Fallback: Active")
        print("✅ Visits Tracker: Active")
        print("📍 Server: http://localhost:5000")
        print("📍 Test SendGrid: http://localhost:5000/test-sendgrid")
        print("📍 Debug Info: http://localhost:5000/debug-sendgrid")
        print("📍 Admin Dashboard: http://localhost:5000/admin/stats")
        print("📍 Database Debug: http://localhost:5000/admin/debug-db")
        # Disable Flask's built-in dotenv loading
        app.run(debug=True, host='0.0.0.0', port=5000, load_dotenv=False)
    else:
        print("❌ Failed to load data. Please check the Excel file.")