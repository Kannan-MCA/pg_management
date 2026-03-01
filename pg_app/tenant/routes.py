from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from flask_login import login_required, current_user
# ✅ FIXED: Absolute import from root
import models
from models import db, PG, Room, User
from flask_login import login_user

admin_bp = Blueprint('admin', __name__, template_folder='templates')

@login_required
@admin_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('admin.dashboard'))
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form['username']).first()
        if user and user.check_password(request.form['password']) and user.role == 'admin':
            login_user(user)
            return redirect(url_for('admin.dashboard'))
        flash('Invalid credentials', 'error')
    return render_template('login.html')

@admin_bp.route('/dashboard')
@login_required
def dashboard():
    if current_user.role != 'admin': abort(403)
    stats = {
        'total_pgs': PG.query.count(),
        'total_rooms': Room.query.count()
    }
    return render_template('dashboard.html', stats=stats)

@admin_bp.route('/pgs', methods=['GET', 'POST'])
@login_required
def manage_pgs():
    if current_user.role != 'admin': abort(403)
    if request.method == 'POST':
        pg = PG(name=request.form['name'], location=request.form['location'])
        db.session.add(pg)
        db.session.commit()
        flash('PG created!')
    pgs = PG.query.all()
    return render_template('pgs.html', pgs=pgs)

@admin_bp.route('/pgs/<int:pg_id>/delete', methods=['POST'])
@login_required
def delete_pg(pg_id):
    if current_user.role != 'admin': abort(403)
    pg = PG.query.get_or_404(pg_id)
    db.session.delete(pg)
    db.session.commit()
    flash('PG deleted!')
    return redirect(url_for('admin.manage_pgs'))
