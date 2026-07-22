import os
from flask import Flask, render_template, request, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from datetime import datetime, date, timedelta

app = Flask(__name__)

# --- SECURE CONFIGURATION FOR PRODUCTION ---
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'default-dev-key-change-in-prod')

# Handle Render's Postgres URL compatibility fix
db_url = os.environ.get('DATABASE_URL', 'sqlite:///leveling_together.db')
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# AVATAR UPLOAD CONFIG
app.config['UPLOAD_FOLDER'] = os.path.join('static', 'avatars')
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'auth'

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# --- Database Models ---
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    display_name = db.Column(db.String(50), default="")
    bio = db.Column(db.String(150), default="")
    avatar_url = db.Column(db.String(200), default="https://via.placeholder.com/100")
    location = db.Column(db.String(100), default="")
    points = db.Column(db.Integer, default=0)

class FollowRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    requester_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    target_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    status = db.Column(db.String(20), default='pending')

class Task(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    description = db.Column(db.String(200), nullable=False)
    is_completed = db.Column(db.Boolean, default=False)
    date_assigned = db.Column(db.Date, nullable=False) 
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

class DailyLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date_logged = db.Column(db.Date, default=date.today)
    rating = db.Column(db.Integer, nullable=False)
    journal = db.Column(db.Text, nullable=True) 
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

# NEW: Activity Feed Model
class Activity(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    message = db.Column(db.String(200), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

# --- Helper Function ---
def calculate_stats(user_id):
    logs = DailyLog.query.filter_by(user_id=user_id).order_by(DailyLog.date_logged.desc()).all()
    if not logs: return 0, 0, 0, 0
    days_logged = len(logs)
    avg_rating = round(sum(log.rating for log in logs) / days_logged, 1)

    max_streak, temp_streak, expected_date = 0, 0, date.today()
    for log in logs:
        if log.date_logged == expected_date:
            temp_streak += 1; expected_date -= timedelta(days=1)
        elif log.date_logged == expected_date - timedelta(days=1): 
            if temp_streak == 0: expected_date -= timedelta(days=1)
            temp_streak += 1; expected_date -= timedelta(days=1)
        else:
            max_streak = max(max_streak, temp_streak)
            temp_streak = 1; expected_date = log.date_logged - timedelta(days=1)
            
    max_streak = max(max_streak, temp_streak)
    current_streak = temp_streak if logs[0].date_logged >= date.today() - timedelta(days=1) else 0
    return days_logged, avg_rating, current_streak, max_streak

# --- Routes ---
@app.route('/')
def index():
    if current_user.is_authenticated: return redirect(url_for('dashboard'))
    return render_template('index.html')

@app.route('/auth', methods=['GET', 'POST'])
def auth():
    error = None 
    if request.method == 'POST':
        action = request.form.get('action')
        login_id = request.form.get('email') 
        password = request.form.get('password')
        
        if action == 'register':
            username = request.form.get('username')
            if User.query.filter((User.email == login_id) | (User.username == username)).first():
                error = "Email or Username already exists."
            else:
                new_user = User(email=login_id, username=username, password_hash=generate_password_hash(password), display_name=username)
                db.session.add(new_user)
                db.session.commit()
                # Log join activity
                db.session.add(Activity(user_id=new_user.id, message="joined Leveling Together! 🎉"))
                db.session.commit()
                login_user(new_user)
                return redirect(url_for('settings'))
                
        elif action == 'login':
            user = User.query.filter((User.email == login_id) | (User.username == login_id)).first()
            if user and check_password_hash(user.password_hash, password):
                login_user(user)
                return redirect(url_for('dashboard'))
            error = "Invalid credentials. Please try again."
    return render_template('auth.html', error=error)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.route('/dashboard')
@login_required
def dashboard():
    today_str = date.today().strftime('%Y-%m-%d')
    tasks = Task.query.filter(Task.user_id == current_user.id, Task.date_assigned == date.today()).all()
    today_log = DailyLog.query.filter_by(user_id=current_user.id, date_logged=date.today()).first()
    all_logs = DailyLog.query.filter_by(user_id=current_user.id).order_by(DailyLog.date_logged.asc()).all()
    
    days_logged, avg_rating, current_streak, max_streak = calculate_stats(current_user.id)
    level = (current_user.points // 50) + 1
    points_progress = current_user.points % 50
    
    ratings = [log.rating for log in all_logs]
    log_dates = [log.date_logged.strftime('%Y-%m-%d') for log in all_logs]
    
    # DYNAMIC BADGES LOGIC
    badges_earned = {
        'first_step': days_logged >= 1,
        'week_warrior': max_streak >= 7,
        'monthly_master': max_streak >= 30,
        'perfect_ten': 10 in ratings,
        'reflector': sum(1 for log in all_logs if log.journal) >= 10,
        'century_club': current_user.points >= 100
    }
    
    return render_template('dashboard.html', user=current_user, tasks=tasks, log=today_log, today=today_str,
                           days_logged=days_logged, avg_rating=avg_rating, current_streak=current_streak, 
                           max_streak=max_streak, level=level, points_progress=points_progress, 
                           ratings=ratings, log_dates=log_dates, badges_earned=badges_earned)

# NEW: The Social Feed
@app.route('/feed')
@login_required
def social_feed():
    # Find friends who approved you
    approved_reqs = FollowRequest.query.filter_by(requester_id=current_user.id, status='approved').all()
    friend_ids = [req.target_id for req in approved_reqs]
    friend_ids.append(current_user.id) # Include yourself in the feed
    
    # Join Activities with User data
    activities = db.session.query(Activity, User).join(User).filter(Activity.user_id.in_(friend_ids)).order_by(Activity.timestamp.desc()).limit(50).all()
    
    return render_template('feed.html', activities=activities, level=(current_user.points // 50) + 1)

@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    if request.method == 'POST':
        current_user.display_name = request.form.get('display_name')
        current_user.bio = request.form.get('bio')
        current_user.location = request.form.get('location')
        
        # AVATAR UPLOAD LOGIC
        avatar_file = request.files.get('avatar_file')
        if avatar_file and avatar_file.filename:
            # Secure the filename and save it
            filename = secure_filename(f"user_{current_user.id}_{avatar_file.filename}")
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            avatar_file.save(filepath)
            # Update DB with the new path
            current_user.avatar_url = url_for('static', filename=f'avatars/{filename}')
        
        db.session.commit()
        return redirect(url_for('dashboard'))
        
    pending_requests = FollowRequest.query.filter_by(target_id=current_user.id, status='pending').all()
    requesters = [User.query.get(req.requester_id) for req in pending_requests]
    request_data = zip(pending_requests, requesters)
    return render_template('settings.html', user=current_user, request_data=request_data)

@app.route('/handle_request/<int:req_id>/<action>')
@login_required
def handle_request(req_id, action):
    req = FollowRequest.query.get(req_id)
    if req and req.target_id == current_user.id:
        req.status = 'approved' if action == 'approve' else 'declined'
        db.session.commit()
    return redirect(url_for('settings'))

@app.route('/discover')
@login_required
def discover():
    users = User.query.filter(User.id != current_user.id).all()
    return render_template('discover.html', users=users)

@app.route('/u/<username>')
@login_required
def public_profile(username):
    if username == current_user.username: return redirect(url_for('dashboard'))
    target_user = User.query.filter_by(username=username).first_or_404()
    req = FollowRequest.query.filter_by(requester_id=current_user.id, target_id=target_user.id).first()
    access_status = req.status if req else 'none'
    
    days_logged, avg_rating, current_streak, max_streak = 0, 0, 0, 0
    ratings, log_dates, level = [], [], (target_user.points // 50) + 1
    
    if access_status == 'approved':
        days_logged, avg_rating, current_streak, max_streak = calculate_stats(target_user.id)
        all_logs = DailyLog.query.filter_by(user_id=target_user.id).order_by(DailyLog.date_logged.asc()).all()
        ratings = [log.rating for log in all_logs]
        log_dates = [log.date_logged.strftime('%Y-%m-%d') for log in all_logs]
        
    return render_template('public_profile.html', target=target_user, status=access_status, level=level,
                           days_logged=days_logged, avg_rating=avg_rating, current_streak=current_streak, 
                           max_streak=max_streak, ratings=ratings, log_dates=log_dates)

@app.route('/request_access/<username>')
@login_required
def request_access(username):
    target = User.query.filter_by(username=username).first_or_404()
    existing_req = FollowRequest.query.filter_by(requester_id=current_user.id, target_id=target.id).first()
    if not existing_req:
        db.session.add(FollowRequest(requester_id=current_user.id, target_id=target.id))
        db.session.commit()
    return redirect(url_for('public_profile', username=username))

@app.route('/save_day', methods=['POST'])
@login_required
def save_day():
    rating = request.form.get('rating', type=int)
    journal = request.form.get('journal')
    if not rating: return redirect(url_for('dashboard'))
    
    old_level = (current_user.points // 50) + 1
    
    today_log = DailyLog.query.filter_by(user_id=current_user.id, date_logged=date.today()).first()
    if today_log:
        today_log.rating, today_log.journal = rating, journal
    else:
        db.session.add(DailyLog(rating=rating, journal=journal, user_id=current_user.id))
        current_user.points += 10
        # Post Activity to Feed
        db.session.add(Activity(user_id=current_user.id, message=f"logged their day with a rating of {rating}/10! 📝"))
        
        # Check Level Up
        new_level = (current_user.points // 50) + 1
        if new_level > old_level:
            db.session.add(Activity(user_id=current_user.id, message=f"leveled up to Level {new_level}! 🚀"))
            
    db.session.commit()
    return redirect(url_for('dashboard'))

@app.route('/add_task', methods=['POST'])
@login_required
def add_task():
    desc = request.form.get('description')
    if desc:
        db.session.add(Task(description=desc, date_assigned=date.today(), user_id=current_user.id))
        db.session.commit()
    return redirect(url_for('dashboard'))

@app.route('/toggle_task/<int:task_id>')
@login_required
def toggle_task(task_id):
    task = Task.query.get(task_id)
    if task and task.user_id == current_user.id:
        task.is_completed = not task.is_completed
        db.session.commit()
    return redirect(url_for('dashboard'))

if __name__ == '__main__':
    with app.app_context():
        db.drop_all() # Reset required for Activity table addition
        db.create_all()
    app.run(debug=True)