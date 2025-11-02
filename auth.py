from flask import Blueprint, request, redirect, render_template, url_for, flash
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from models import db, User 

auth_bp = Blueprint('auth', __name__, template_folder='templates')

@auth_bp.route('/signup', methods=['GET', 'POST'])
def signup():
    # If already logged in, redirect to dashboard
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
        
    if request.method == 'POST':
        try:
            username = request.form.get('username')
            password = request.form.get('password')
            role = request.form.get('role', 'user')

            if not username or not password:
                flash('Username and password are required.', 'error') # Added category
                return redirect(url_for('auth.signup'))

            if User.query.filter_by(username=username).first():
                flash('Username already exists.', 'error') # Added category
                return redirect(url_for('auth.signup'))

            hashed_pw = generate_password_hash(password)
            new_user = User(username=username, password=hashed_pw, role=role)
            db.session.add(new_user)
            db.session.commit()

            flash('Signup successful. Please log in.', 'success') # Added category
            return redirect(url_for('auth.login'))
        except Exception:
            flash('An error occurred during signup.', 'error') # Added category
            return render_template('signup.html') # Fixed internal error handling

    return render_template('signup.html')

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    # If already logged in, redirect to dashboard
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        if not username or not password:
            flash('Both fields are required.', 'error') # Added category
            return redirect(url_for('auth.login'))

        user = User.query.filter_by(username=username).first()

        if user and check_password_hash(user.password, password):
            login_user(user)
            flash(f'Welcome back, {user.username}!', 'success') # Added category
            return redirect(url_for('dashboard')) # Redirect to dashboard URL
        else:
            flash('Invalid credentials.', 'error') # Added category
            return redirect(url_for('auth.login'))

    return render_template('login.html')

@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Logged out successfully.', 'success') # Added category
    return redirect(url_for('auth.login')) # Fixed redirect to the login page

@auth_bp.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        username = request.form.get('username')
        user = User.query.filter_by(username=username).first()
        
        if user:
            # Username is validated. Redirect to the password reset page.
            flash('Username validated. Please enter your new password.', 'info')
            # Pass the username via a query parameter (pretending to be a secure token link)
            return redirect(url_for('auth.reset_password', username=username))
        else:
            # Use generic message for security, but direct to the form for error state
            flash('Username not found.', 'error')
            return redirect(url_for('auth.forgot_password'))
    
    return render_template('forgot_password.html')

# --- NEW ROUTE: Handles password reset form submission ---
@auth_bp.route('/reset_password', methods=['GET', 'POST'])
def reset_password():
    # Get username from query args (GET) or hidden form data (POST)
    username = request.args.get('username') or request.form.get('username')

    if request.method == 'POST':
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')

        user = User.query.filter_by(username=username).first()

        if not user:
            flash('User validation failed. Please try the forgot password link again.', 'error')
            return redirect(url_for('auth.forgot_password'))

        if not new_password or new_password != confirm_password:
            flash('Passwords do not match or field is empty.', 'error')
            # Re-render the form, passing username back to keep context
            return render_template('reset_password.html', username=username)

        # Update and hash the new password securely
        user.password = generate_password_hash(new_password)
        db.session.commit()

        flash('Password successfully reset. Please log in with your new password.', 'success')
        return redirect(url_for('auth.login'))

    # GET request handler: checks if username context is available
    if not username:
        flash('Please enter your username first.', 'error')
        return redirect(url_for('auth.forgot_password'))
        
    return render_template('reset_password.html', username=username)


@auth_bp.route('/dashboard')
@login_required
def dashboard():
    role_templates = {
        'admin': 'admin_dashboard.html',
        'family': 'family_dashboard.html',
        'user': 'user_dashboard.html'
    }
    role = current_user.role.strip().lower()
    template = role_templates.get(role, 'user_dashboard.html')
    return render_template(template, username=current_user.username)
