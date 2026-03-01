import os
from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, current_user, logout_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, date
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config['SECRET_KEY'] = 'pg-management-2026'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///pg_management.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# IMAGE UPLOAD CONFIG
UPLOAD_FOLDER = 'static/uploads/rooms'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'pdf'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

# Create upload folders
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs('static/uploads/id_proofs', exist_ok=True)

db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'admin_login'

# UPLOAD HELPER FUNCTION
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# 🔥 LOCATION SEARCH FUNCTION
def search_pgs(query):
    """Search PGs by location name, PG name, or coordinates"""
    if not query or len(query) < 2:
        return PG.query.all()
    
    # Search in location, name, latitude, longitude fields
    pgs = PG.query.filter(
        (PG.location.ilike(f'%{query}%')) |
        (PG.name.ilike(f'%{query}%')) |
        (PG.latitude.cast(db.String).ilike(f'%{query}%')) |
        (PG.longitude.cast(db.String).ilike(f'%{query}%'))
    ).order_by(PG.name).all()
    
    return pgs

# Models
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), default='tenant')
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class PG(db.Model):
    __table_args__ = {'extend_existing': True}
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    location = db.Column(db.String(500))
    latitude = db.Column(db.Float)
    longitude = db.Column(db.Float)
    total_rooms = db.Column(db.Integer, default=0)

class Room(db.Model):
    __table_args__ = {'extend_existing': True}
    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.String(20), nullable=False)
    price = db.Column(db.Float, nullable=False)
    sharing = db.Column(db.Integer, nullable=False, default=1)
    ac_type = db.Column(db.String(20), default='non-ac')
    image_url = db.Column(db.String(500))
    available = db.Column(db.Boolean, default=True)
    pg_id = db.Column(db.Integer, db.ForeignKey('pg.id'), nullable=False)
    
    pg = db.relationship('PG', backref='rooms')

class Booking(db.Model):
    __table_args__ = {'extend_existing': True}
    id = db.Column(db.Integer, primary_key=True)
    tenant_name = db.Column(db.String(100), nullable=False)
    tenant_phone = db.Column(db.String(15), nullable=False)
    tenant_email = db.Column(db.String(120))
    tenant_aadhar = db.Column(db.String(20))
    id_proof = db.Column(db.String(500))
    room_id = db.Column(db.Integer, db.ForeignKey('room.id'), nullable=False)
    booking_date = db.Column(db.DateTime, default=datetime.utcnow)
    move_in_date = db.Column(db.Date)
    booking_status = db.Column(db.String(20), default='confirmed')
    room = db.relationship('Room', backref='bookings')

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Routes
@app.route('/create_admin')
def create_admin():
    admin = User(username='admin', role='admin')
    admin.set_password('admin123')
    db.session.add(admin)
    db.session.commit()
    return '✅ Admin created: admin/admin123 (run ONCE)'

@app.route('/')
@app.route('/pgs')
def pgs():
    # 🔥 LOCATION SEARCH SUPPORT
    search_query = request.args.get('search', '').strip()
    pgs = search_pgs(search_query) if search_query else PG.query.all()
    return render_template('pgs.html', pgs=pgs, search_query=search_query)

@app.route('/pg/<int:pg_id>')
def rooms(pg_id):
    pg = PG.query.get_or_404(pg_id)
    rooms = Room.query.filter_by(pg_id=pg_id, available=True).all()
    return render_template('rooms.html', pg=pg, rooms=rooms)

@app.route('/book/<int:room_id>', methods=['GET', 'POST'])
def book_room(room_id):
    room = Room.query.get_or_404(room_id)
    if not room.available:
        flash('Room is no longer available!', 'danger')
        return redirect(url_for('rooms', pg_id=room.pg_id))
    
    if request.method == 'POST':
        tenant_name = request.form.get('tenant_name', '').strip()
        tenant_phone = request.form.get('tenant_phone', '').strip()
        tenant_email = request.form.get('tenant_email', '').strip()
        tenant_aadhar = request.form.get('tenant_aadhar', '').strip()
        
        id_proof_filename = None
        if 'id_proof' in request.files:
            file = request.files['id_proof']
            if file and file.filename and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                id_proof_filename = f"id_{tenant_phone}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{filename}"
                file.save(os.path.join('static/uploads/id_proofs/', id_proof_filename))
        
        if not tenant_name or not tenant_phone:
            flash('Please fill name and phone number!', 'danger')
            pg = PG.query.get(room.pg_id)
            return render_template('booking/form.html', room=room, pg=pg)
        
        booking = Booking(
            tenant_name=tenant_name,
            tenant_phone=tenant_phone,
            tenant_email=tenant_email,
            tenant_aadhar=tenant_aadhar,
            id_proof=id_proof_filename,
            room_id=room_id
        )
        db.session.add(booking)
        db.session.flush()
        room.available = False
        db.session.commit()
        
        flash(f'✅ Booking confirmed! ID: BK{booking.id:04d}', 'success')
        return redirect(url_for('booking_receipt', booking_id=booking.id))
    
    pg = PG.query.get(room.pg_id)
    return render_template('booking/form.html', room=room, pg=pg)

@app.route('/booking/receipt/<int:booking_id>')
def booking_receipt(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    room = Room.query.get(booking.room_id)
    pg = PG.query.get(room.pg_id)
    return render_template('booking/receipt.html', booking=booking, room=room, pg=pg)

# Admin Routes
@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if current_user.is_authenticated and current_user.role == 'admin':
        return redirect('/admin/dashboard')
    
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form['username']).first()
        if user and user.check_password(request.form['password']) and user.role == 'admin':
            login_user(user)
            return redirect('/admin/dashboard')
        flash('Invalid credentials', 'error')
    return render_template('admin/login.html')

@app.route('/admin/logout')
@login_required
def admin_logout():
    logout_user()
    flash('Logged out successfully!')
    return redirect('/admin/login')

@app.route('/admin/dashboard')
@login_required
def admin_dashboard():
    if current_user.role != 'admin':
        flash('Admin access only')
        return redirect('/admin/login')
    
    stats = {
        'total_pgs': PG.query.count(),
        'total_rooms': Room.query.count(),
        'available_rooms': Room.query.filter_by(available=True).count(),
        'total_bookings': Booking.query.count()
    }
    return render_template('admin/dashboard.html', stats=stats)

@app.route('/admin/pgs')
@login_required
def admin_pgs():
    if current_user.role != 'admin':
        return redirect('/admin/login')
    
    pgs = PG.query.all()
    for pg in pgs:
        pg.room_count = Room.query.filter_by(pg_id=pg.id).count()
    
    return render_template('admin/pgs.html', pgs=pgs)

@app.route('/admin/add_pg', methods=['GET', 'POST'])
@login_required
def admin_add_pg():
    if current_user.role != 'admin':
        return redirect('/admin/login')
    
    if request.method == 'POST':
        name = request.form['name']
        location = request.form.get('location', '').strip()
        lat = request.form.get('latitude')
        lng = request.form.get('longitude')
        total_rooms = int(request.form['total_rooms'])
        
        new_pg = PG(
            name=name,
            location=location or f'Lat:{lat}, Lng:{lng}' if lat and lng else 'Location TBD',
            latitude=float(lat) if lat else None,
            longitude=float(lng) if lng else None,
            total_rooms=total_rooms
        )
        db.session.add(new_pg)
        db.session.commit()
        flash(f'✅ PG "{name}" added with GPS location!', 'success')
        return redirect(url_for('admin_pgs'))
    
    return render_template('admin/add_pg.html')

@app.route('/admin/pgs/<int:pg_id>/delete', methods=['POST'])
@login_required
def delete_pg(pg_id):
    if current_user.role != 'admin':
        return redirect('/admin/login')
    
    pg = PG.query.get_or_404(pg_id)
    db.session.delete(pg)
    db.session.commit()
    flash('PG deleted successfully!')
    return redirect('/admin/pgs')

@app.route('/admin/rooms/<int:pg_id>', methods=['GET', 'POST'])
@login_required
def admin_rooms(pg_id):
    if current_user.role != 'admin':
        return redirect('/admin/login')
    
    pg = PG.query.get_or_404(pg_id)
    
    if request.method == 'POST':
        number = request.form['number']
        price = float(request.form['price'])
        sharing = int(request.form['sharing'])
        ac_type = request.form['ac_type']
        
        image_filename = None
        if 'image' in request.files:
            file = request.files['image']
            if file and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                image_filename = f"room_{number}_{filename}"
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], image_filename))
        
        room = Room(
            number=number,
            price=price,
            sharing=sharing,
            ac_type=ac_type,
            image_url=image_filename,
            available=True,
            pg_id=pg_id
        )
        db.session.add(room)
        db.session.commit()
        flash('Room added successfully with image!', 'success')
    
    rooms = Room.query.filter_by(pg_id=pg_id).order_by(Room.number).all()
    return render_template('admin/rooms.html', pg=pg, rooms=rooms)

@app.route('/admin/add_room', methods=['GET', 'POST'])
@login_required
def admin_add_room():
    if current_user.role != 'admin':
        return redirect('/admin/login')
    
    if request.method == 'POST':
        number = request.form['number']
        price = float(request.form['price'])
        sharing = int(request.form['sharing'])
        ac_type = request.form['ac_type']
        pg_id = int(request.form['pg_id'])
        
        image_filename = None
        if 'image' in request.files:
            file = request.files['image']
            if file and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                image_filename = f"room_{number}_{filename}"
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], image_filename))
        
        new_room = Room(
            number=number,
            price=price,
            sharing=sharing,
            ac_type=ac_type,
            image_url=image_filename,
            available=True,
            pg_id=pg_id
        )
        db.session.add(new_room)
        db.session.commit()
        flash('Room added successfully!', 'success')
        return redirect(url_for('admin_rooms', pg_id=pg_id))
    
    pgs = PG.query.all()
    return render_template('admin/add_room.html', pgs=pgs)

@app.route('/admin/bookings')
@login_required
def admin_bookings():
    if current_user.role != 'admin':
        return redirect('/admin/login')
    
    bookings = Booking.query.all()
    return render_template('admin/bookings.html', bookings=bookings)

@app.route('/admin/rooms')
@login_required
def admin_all_rooms():
    if current_user.role != 'admin':
        return redirect('/admin/login')
    
    pgs = PG.query.all()
    for pg in pgs:
        pg.room_count = Room.query.filter_by(pg_id=pg.id).count()
        pg.rooms_list = Room.query.filter_by(pg_id=pg.id).order_by(Room.number).all()
    
    return render_template('admin/all_rooms.html', pgs=pgs)

@app.route('/admin/rooms/<int:pg_id>/<int:room_id>/toggle', methods=['POST'])
@login_required
def toggle_room_status(pg_id, room_id):
    if current_user.role != 'admin':
        return redirect('/admin/login')
    
    room = Room.query.get_or_404(room_id)
    room.available = not room.available
    db.session.commit()
    flash(f'Room {room.number} status updated!')
    return redirect(f'/admin/rooms/{pg_id}')

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True, port=5000)
