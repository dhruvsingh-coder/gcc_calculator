import sqlite3
import datetime
from flask import g
import json

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

def log_visit(user_data):
    """Log a user visit and update statistics"""
    if not user_data.get('user_id'):
        return None
    
    db = get_db()
    
    try:
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
        
        # Update or insert user statistics
        db.execute('''
            INSERT INTO user_stats (user_id, visit_count, total_calculations, last_visit)
            VALUES (?, 1, 1, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id) 
            DO UPDATE SET 
                visit_count = visit_count + 1,
                total_calculations = total_calculations + 1,
                last_visit = CURRENT_TIMESTAMP
        ''', (user_data['user_id'],))
        
        db.commit()
        return visit_id
        
    except Exception as e:
        db.rollback()
        print(f"Error logging visit: {e}")
        return None

def get_visit_stats():
    """Get comprehensive visit statistics"""
    db = get_db()
    
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

def get_user_details(user_id):
    """Get detailed history for a specific user"""
    db = get_db()
    
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

def export_data(format='json'):
    """Export all visit data"""
    db = get_db()
    
    visits = db.execute('''
        SELECT * FROM user_visits ORDER BY visit_time DESC
    ''').fetchall()
    
    stats = db.execute('''
        SELECT * FROM user_stats ORDER BY visit_count DESC
    ''').fetchall()
    
    data = {
        'visits': [dict(row) for row in visits],
        'stats': [dict(row) for row in stats],
        'export_time': datetime.datetime.now().isoformat()
    }
    
    if format == 'json':
        return json.dumps(data, indent=2, default=str)
    else:
        return data