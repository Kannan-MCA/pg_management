from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from flask_login import login_required, current_user
from models import db, PG, Room, User, Booking
from datetime import datetime

admin_bp = Blueprint('admin', __name__, template_folder='templates', 
                    static_folder='../../static', url_prefix='/admin')

@login_required
@admin_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('admin.dashboard'))
    
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form['username']).first()
        if user and user.check_password(request.form['password']) and user.role == 'admin':
            from flask_login import login_user
            login_user(user)
            return redirect(url_for('admin.dashboard'))
        flash('Invalid credentials')
    
    return render_template('login.html')

@admin_bp.route('/dashboard')
@login_required
def dashboard():
    if current_user.role != 'admin':
        abort(403)
    
    stats = {
        'total_pgs': PG.query.count(),
        'total_rooms': Room.query.count(),
        'available_rooms': Room.query.filter_by(available=True).count(),
        'pending_bookings': Booking.query.filter_by(status='pending').count()
    }
    
    return render_template('dashboard.html', stats=stats)

@admin_bp.route('/pgs', methods=['GET', 'POST'])
@login_required
def manage_pgs():
    if current_user.role != 'admin':
        abort(403)
    
    if request.method == 'POST':
        pg = PG(
            name=request.form['name'],
            location=request.form['location'],
            description=request.form.get('description', ''),
            total_rooms=int(request.form.get('total_rooms', 0))
        )
        db.session.add(pg)
        db.session.commit()
        flash('PG created successfully!')
    
    pgs = PG.query.all()
    return render_template('pgs.html', pgs=pgs)

@admin_bp.route('/pgs/<int:pg_id>/delete', methods=['POST'])
@login_required
def delete_pg(pg_id):
    if current_user.role != 'admin':
        abort(403)
    pg = PG.query.get_or_404(pg_id)
    db.session.delete(pg)
    db.session.commit()
    flash('PG deleted!')
    return redirect(url_for('admin.manage_pgs'))

@admin_bp.route('/pgs/<int:pg_id>/rooms', methods=['GET', 'POST'])
@login_required
def manage_rooms(pg_id):
    if current_user.role != 'admin':
        abort(403)
    
    pg = PG.query.get_or_404(pg_id)
    
    if request.method == 'POST':
        room = Room(
            number=request.form['number'],
            capacity=int(request.form.get('capacity', 1)),
            price=float(request.form['price']),
            pg_id=pg_id
        )
        db.session.add(room)
        pg.total_rooms += 1
        db.session.commit()
        flash('Room created!')
    
    rooms = pg.rooms.all()
    return render_template('rooms.html', pg=pg, rooms=rooms)
