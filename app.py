from flask import Flask, render_template, request, jsonify, session, Response, redirect
import pandas as pd
import numpy as np
from openpyxl import load_workbook
import os
import sqlite3
from flask import g
import traceback
import secrets
from datetime import datetime

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

print(f"🌐 Environment: {os.environ.get('FLASK_ENV', 'development')}")
print(f"🔐 Secret key: {'Set' if app.secret_key else 'Not set'}")

# Global variables to store data
cities_by_tier = {}
avg_costs = {}
plan_ranges = {}

# ============================================================================
# VISITS TRACKER FUNCTIONS (SIMPLIFIED)
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
        print("🔄 Creating database tables...")
        # Create user_visits table (simplified)
        db.execute('''
            CREATE TABLE IF NOT EXISTS user_visits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
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
        
        db.commit()
        print("✅ Database tables created successfully")
            
    except Exception as e:
        print(f"❌ Error initializing database: {e}")
        db.rollback()

def log_visit(session_id, user_data):
    """Log a user visit anonymously"""
    db = get_db()
    
    try:
        cursor = db.execute('''
            INSERT INTO user_visits 
            (session_id, headcount, city, tier, plan, real_estate, it_infra, enabling, technology, total_cost)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            session_id,
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
        db.commit()
        print(f"✅ Visit logged with ID: {visit_id}")
        return visit_id
        
    except Exception as e:
        db.rollback()
        print(f"❌ Error logging visit: {e}")
        return None

def get_visit_stats():
    """Get basic visit statistics"""
    db = get_db()
    
    try:
        stats = db.execute('''
            SELECT 
                COUNT(DISTINCT session_id) as unique_sessions,
                COUNT(*) as total_visits
            FROM user_visits
        ''').fetchone()
        
        return {
            'unique_sessions': stats['unique_sessions'],
            'total_visits': stats['total_visits']
        }
    except Exception as e:
        print(f"❌ Error getting visit stats: {e}")
        return {
            'unique_sessions': 0,
            'total_visits': 0
        }

# ============================================================================
# DATABASE INITIALIZATION
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
    
    # Plan details configuration (simplified)
    plan_details_by_headcount = {
        'Basic': {
            '0-50': {'name': 'Basic Plan', 'description': 'Essential GCC setup with core functionality'},
            '51-100': {'name': 'Basic Plan', 'description': 'Essential GCC setup with core functionality'},
            '101-250': {'name': 'Basic Plan', 'description': 'Essential GCC setup with core functionality'},
            '251-500': {'name': 'Basic Plan', 'description': 'Essential GCC setup with core functionality'},
            '501-1000': {'name': 'Basic Plan', 'description': 'Essential GCC setup with core functionality'}
        },
        'Premium': {
            '0-50': {'name': 'Premium Plan', 'description': 'Enhanced GCC setup with additional features'},
            '51-100': {'name': 'Premium Plan', 'description': 'Enhanced GCC setup with additional features'},
            '101-250': {'name': 'Premium Plan', 'description': 'Enhanced GCC setup with additional features'},
            '251-500': {'name': 'Premium Plan', 'description': 'Enhanced GCC setup with additional features'},
            '501-1000': {'name': 'Premium Plan', 'description': 'Enhanced GCC setup with additional features'}
        },
        'Advance': {
            '0-50': {'name': 'Advance Plan', 'description': 'Comprehensive GCC setup with full customization'},
            '51-100': {'name': 'Advance Plan', 'description': 'Comprehensive GCC setup with full customization'},
            '101-250': {'name': 'Advance Plan', 'description': 'Comprehensive GCC setup with full customization'},
            '251-500': {'name': 'Advance Plan', 'description': 'Comprehensive GCC setup with full customization'},
            '501-1000': {'name': 'Advance Plan', 'description': 'Comprehensive GCC setup with full customization'}
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
# FLASK ROUTES (NO AUTHENTICATION)
# ============================================================================

@app.route('/calculate', methods=['POST'])
def calculate():
    """Calculate costs based on user input - NO AUTHENTICATION REQUIRED"""
    try:
        # Get form data
        headcount = int(request.form.get('headcount', 100))
        tier = request.form.get('tier', 'Tier 1')
        city = request.form.get('city', 'Bengaluru')
        plan = request.form.get('plan', 'Basic')
        
        # Component toggles
        real_estate_toggle = request.form.get('real_estate') == 'on'
        it_infra_toggle = request.form.get('it_infra') == 'on'
        enabling_toggle = request.form.get('enabling') == 'on'
        technology_toggle = request.form.get('technology') == 'on'
        
        # Calculate costs
        total_cost = 0
        
        # Real Estate Cost
        if real_estate_toggle:
            real_estate_cost_per_seat = get_cost_for_city(city, 'real_estate')
            total_real_estate_cost = real_estate_cost_per_seat * headcount
            total_cost += total_real_estate_cost
        else:
            total_real_estate_cost = 0
        
        # IT Infrastructure Cost
        if it_infra_toggle:
            it_infra_cost_per_seat = get_cost_for_city(city, 'it_infra')
            total_it_infra_cost = it_infra_cost_per_seat * headcount
            total_cost += total_it_infra_cost
        else:
            total_it_infra_cost = 0
        
        # Enabling Functions Cost
        if enabling_toggle:
            enab_cost, _ = get_plan_costs(headcount, plan)
            total_cost += enab_cost
        else:
            enab_cost = 0
        
        # Technology Cost
        if technology_toggle:
            _, tech_cost = get_plan_costs(headcount, plan)
            total_cost += tech_cost
        else:
            tech_cost = 0
        
        # Calculate hourly cost per head in USD
        hours_per_month = 120
        usd_to_inr = 85
        hourly_cost_per_head_usd = (total_cost / headcount / hours_per_month / usd_to_inr) if headcount > 0 else 0
        
        # Get plan details based on headcount
        plan_details = get_plan_details_by_headcount(plan, headcount)
        
        # Generate or get session ID for anonymous tracking
        if 'session_id' not in session:
            session['session_id'] = f"session_{secrets.token_urlsafe(12)}"
        
        # Log the visit (anonymous)
        log_visit(session['session_id'], {
            'headcount': headcount,
            'city': city,
            'tier': tier,
            'plan': plan,
            'real_estate': real_estate_toggle,
            'it_infra': it_infra_toggle,
            'enabling': enabling_toggle,
            'technology': technology_toggle,
            'total_cost': total_cost
        })
        
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
            'plan_details': plan_details
        }
        
        return render_template('results.html', 
                             results=results, 
                             cities_by_tier=convert_to_serializable(cities_by_tier))
        
    except Exception as e:
        print(f"Error in calculate route: {str(e)}")
        print(traceback.format_exc())
        return f"Error calculating costs: {str(e)}", 500

# ============================================================================
# SIMPLE ADMIN ROUTES
# ============================================================================

@app.route('/admin/stats')
def admin_stats():
    """Simple admin page to view statistics"""
    stats = get_visit_stats()
    return jsonify(stats)

# ============================================================================
# MAIN ROUTES
# ============================================================================

@app.route('/')
def index():
    """Main page - NO AUTHENTICATION POPUP"""
    tiers = list(cities_by_tier.keys())
    return render_template('index.html', 
                         tiers=tiers,
                         cities_by_tier=convert_to_serializable(cities_by_tier),
                         avg_costs=convert_to_serializable(avg_costs),
                         plan_ranges=convert_to_serializable(plan_ranges))

@app.route('/api/cities/<tier>')
def get_cities_by_tier_route(tier):
    """API endpoint to get cities by tier"""
    cities = cities_by_tier.get(tier, [])
    return jsonify(convert_to_serializable(cities))

@app.route('/api/plan_details')
def get_plan_details_route():
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
        print("✅ Authentication: DISABLED")
        print("✅ Visits Tracker: Active (Anonymous)")
        print("📍 Server: http://localhost:5000")
        print("📍 Admin Stats: http://localhost:5000/admin/stats")
        # Disable Flask's built-in dotenv loading
        app.run(debug=True, host='0.0.0.0', port=5000, load_dotenv=False)
    else:
        print("❌ Failed to load data. Please check the Excel file.")