import os
from datetime import datetime, date
from calendar import monthrange

from sqlalchemy import func
from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    flash,
)
from flask_login import (
    LoginManager,
    login_user,
    login_required,
    current_user,
    logout_user,
)
from werkzeug.utils import secure_filename

from config import DevelopmentConfig, Config
from extensions import db
from models import (
    User,
    PG,
    Room,
    Booking,
    ServiceType,
    BookingService,
    Attendance,
)

app = Flask(__name__)
app.config.from_object(DevelopmentConfig)

db.init_app(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"  # unified login view

# folder paths
UPLOAD_FOLDER = app.config["UPLOAD_FOLDER"]
ID_PROOF_FOLDER = app.config["ID_PROOF_FOLDER"]
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(ID_PROOF_FOLDER, exist_ok=True)


def allowed_file(filename: str) -> bool:
    return Config.allowed_file(filename)


def search_pgs(query):
    if not query or len(query) < 2:
        return PG.query.all()

    return (
        PG.query.filter(
            (PG.location.ilike(f"%{query}%"))
            | (PG.name.ilike(f"%{query}%"))
            | (PG.latitude.cast(db.String).ilike(f"%{query}%"))
            | (PG.longitude.cast(db.String).ilike(f"%{query}%"))
        )
        .order_by(PG.name)
        .all()
    )


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


# ---- Utility: compute booking revenue including services ----
def compute_booking_total(booking: Booking) -> float:
    base = booking.amount or (booking.room.price if booking.room else 0.0)
    addons = sum(s.total_price for s in booking.services)
    return base + addons


# ---- Initial admin + service seeding ----
@app.route("/init_seed")
def init_seed():
    if not User.query.filter_by(username="admin").first():
        admin = User(username="admin", role="admin")
        admin.set_password("admin123")
        db.session.add(admin)

    defaults = [
        ("Laundry", "laundry", 30.0),
        ("Breakfast", "food", 50.0),
        ("Lunch", "food", 80.0),
        ("Dinner", "food", 80.0),
    ]
    for name, cat, price in defaults:
        if not ServiceType.query.filter_by(name=name, category=cat).first():
            db.session.add(ServiceType(name=name, category=cat, price=price))

    db.session.commit()
    return "Seeded admin and basic services."


@app.route("/init_tenant")
def init_tenant():
    # example tenant user; username should match tenant_email used in bookings
    email = "tenant1@example.com"
    user = User.query.filter_by(username=email).first()
    if not user:
        user = User(username=email, role="tenant")
        user.set_password("tenant123")
        db.session.add(user)
        db.session.commit()
        return f"Tenant user created: {email} / tenant123"
    return "Tenant user already exists"


# ---- Public / tenant-facing routes ----
@app.route("/")
@app.route("/pgs")
def pgs():
    search_query = request.args.get("search", "").strip()
    pgs = search_pgs(search_query) if search_query else PG.query.all()
    return render_template("pgs.html", pgs=pgs, search_query=search_query)


@app.route("/pg/<int:pg_id>")
def rooms(pg_id):
    pg = PG.query.get_or_404(pg_id)

    min_price = request.args.get("min_price")
    max_price = request.args.get("max_price")
    sharing = request.args.get("sharing")
    ac_type = request.args.get("ac_type")

    q = Room.query.filter_by(pg_id=pg_id, available=True)

    if min_price:
        q = q.filter(Room.price >= float(min_price))
    if max_price:
        q = q.filter(Room.price <= float(max_price))
    if sharing:
        q = q.filter(Room.sharing == int(sharing))
    if ac_type:
        q = q.filter(Room.ac_type == ac_type)

    rooms = q.order_by(Room.price).all()
    return render_template("rooms.html", pg=pg, rooms=rooms)


@app.route("/book/<int:room_id>", methods=["GET", "POST"])
def book_room(room_id):
    room = Room.query.get_or_404(room_id)
    if not room.available:
        flash("Room is no longer available!", "danger")
        return redirect(url_for("rooms", pg_id=room.pg_id))

    if request.method == "POST":
        tenant_name = request.form.get("tenant_name", "").strip()
        tenant_phone = request.form.get("tenant_phone", "").strip()
        tenant_email = request.form.get("tenant_email", "").strip()
        tenant_aadhar = request.form.get("tenant_aadhar", "").strip()
        move_in_date_str = request.form.get("move_in_date")

        amount = float(request.form.get("amount") or room.price)

        move_in_date = (
            datetime.strptime(move_in_date_str, "%Y-%m-%d").date()
            if move_in_date_str
            else None
        )

        id_proof_filename = None
        if "id_proof" in request.files:
            file = request.files["id_proof"]
            if file and file.filename and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                id_proof_filename = (
                    f"id_{tenant_phone}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{filename}"
                )
                file.save(os.path.join(ID_PROOF_FOLDER, id_proof_filename))

        if not tenant_name or not tenant_phone:
            flash("Please fill name and phone number!", "danger")
            pg = PG.query.get(room.pg_id)
            return render_template("booking/form.html", room=room, pg=pg)

        booking = Booking(
            tenant_name=tenant_name,
            tenant_phone=tenant_phone,
            tenant_email=tenant_email,
            tenant_aadhar=tenant_aadhar,
            id_proof=id_proof_filename,
            room_id=room_id,
            move_in_date=move_in_date,
            amount=amount,
            payment_status="pending",
            kyc_status="pending",
            booking_status="kyc_pending",
        )
        db.session.add(booking)
        db.session.flush()
        room.available = False
        db.session.commit()

        flash(f"✅ Booking confirmed! ID: BK{booking.id:04d}", "success")
        return redirect(url_for("booking_receipt", booking_id=booking.id))

    pg = PG.query.get(room.pg_id)
    return render_template("booking/form.html", room=room, pg=pg)


@app.route("/booking/receipt/<int:booking_id>")
def booking_receipt(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    room = booking.room
    pg = room.pg
    total = compute_booking_total(booking)
    return render_template(
        "booking/receipt.html",
        booking=booking,
        room=room,
        pg=pg,
        total=total,
    )


# ---- Unified login / logout ----
@app.route("/login", methods=["GET", "POST"])
def login():
    # already logged in: send to correct dashboard
    if current_user.is_authenticated:
        if current_user.role == "admin":
            return redirect("/admin/dashboard")
        if current_user.role == "tenant":
            return redirect("/tenant/dashboard")

    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            login_user(user)
            if user.role == "admin":
                return redirect("/admin/dashboard")
            else:
                return redirect("/tenant/dashboard")

        flash("Invalid credentials", "error")

    return render_template("login.html")


# optional alias to keep old URL working
@app.route("/admin/login", methods=["GET", "POST"])
def admin_login_alias():
    return redirect(url_for("login"))


@app.route("/admin/logout")
@login_required
def admin_logout():
    logout_user()
    flash("Logged out successfully!")
    return redirect("/login")


# ---- Tenant dashboard & services & billing ----
@app.route("/tenant/dashboard")
@login_required
def tenant_dashboard():
    if current_user.role != "tenant":
        flash("Tenant access only")
        return redirect("/admin/dashboard")

    bookings = Booking.query.filter_by(tenant_email=current_user.username).all()
    return render_template("tenant/dashboard.html", bookings=bookings)


@app.route("/tenant/booking/<int:booking_id>/services", methods=["GET", "POST"])
@login_required
def tenant_services(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    if current_user.role != "tenant":
        flash("Tenant access only")
        return redirect("/")

    services = ServiceType.query.filter_by(active=True).all()

    if request.method == "POST":
        for s in services:
            qty_str = request.form.get(f"service_{s.id}")
            if qty_str:
                qty = int(qty_str)
                if qty > 0:
                    total_price = qty * s.price
                    db.session.add(
                        BookingService(
                            booking_id=booking.id,
                            service_type_id=s.id,
                            quantity=qty,
                            total_price=total_price,
                        )
                    )
        db.session.commit()
        flash("Services added to your booking.", "success")
        return redirect(url_for("tenant_dashboard"))

    return render_template("tenant/services.html", booking=booking, services=services)


@app.route("/tenant/billing")
@login_required
def tenant_billing():
    if current_user.role != "tenant":
        flash("Tenant access only")
        return redirect("/login")

    # get latest booking for this tenant using tenant_email
    booking = (
        Booking.query
        .filter_by(tenant_email=current_user.username)
        .order_by(Booking.id.desc())
        .first_or_404()
    )

    # nights: if you later add check_in/check_out, replace this logic
    nights = 1
    if getattr(booking, "check_in", None) and getattr(booking, "check_out", None):
        try:
            nights = (booking.check_out.date() - booking.check_in.date()).days or 1
        except Exception:
            nights = 1

    # room rate from your Room model
    room_rate = booking.room.price
    room_total = nights * room_rate

    # services added for this booking
    service_items = []
    for s in booking.services:
        service_items.append({
            "name": s.service_type.name,
            "unit_price": s.service_type.price,
            "quantity": s.quantity,
            "total": s.total_price,
        })

    subtotal = room_total + sum(i["total"] for i in service_items)
    tax_percent = 12
    tax_amount = subtotal * tax_percent / 100
    total_payable = subtotal + tax_amount

    amount_received = total_payable if booking.payment_status == "paid" else 0
    balance = total_payable - amount_received

    billing = {
        "invoice_no": f"INV-{booking.id:04d}",
        "date": booking.booking_date or datetime.utcnow(),
        "booking": booking,
        "guest": {
            "name": booking.tenant_name,
            "address": "",  # fill later if you add address field
            "phone": booking.tenant_phone,
            "email": booking.tenant_email,
        },
        "nights": nights,
        "room_rate": room_rate,
        "room_total": room_total,
        "service_items": service_items,
        "other_items": [],
        "subtotal": subtotal,
        "tax_percent": tax_percent,
        "tax_amount": tax_amount,
        "discount_amount": 0,
        "total_payable": total_payable,
        "amount_received": amount_received,
        "balance": balance,
        "payment_method": getattr(booking, "payment_method", "Cash"),
        "remarks": "",
        "is_paid": booking.payment_status == "paid",
    }

    hotel = {
        "name": "Your PG Name",
        "address": "Full address here",
        "phone": "9876543210",
        "email": "info@example.com",
    }

    return render_template(
        "tenant/billing.html",
        billing=billing,
        hotel=hotel,
    )


# ---- Admin dashboard & bookings ----
@app.route("/admin/dashboard")
@login_required
def admin_dashboard():
    if current_user.role != "admin":
        flash("Admin access only")
        return redirect("/login")

    stats = {
        "total_pgs": PG.query.count(),
        "total_rooms": Room.query.count(),
        "available_rooms": Room.query.filter_by(available=True).count(),
        "total_bookings": Booking.query.count(),
        "paid_bookings": Booking.query.filter_by(payment_status="paid").count(),
    }

    paid_bookings = Booking.query.filter_by(payment_status="paid").all()
    total_revenue = sum(compute_booking_total(b) for b in paid_bookings)

    return render_template(
        "admin/dashboard.html",
        stats=stats,
        total_revenue=total_revenue,
    )


@app.route("/admin/bookings")
@login_required
def admin_bookings():
    if current_user.role != "admin":
        return redirect("/login")

    status = request.args.get("status")
    q_id = request.args.get("booking_id", "").strip()

    q = Booking.query
    if status:
        q = q.filter_by(payment_status=status)

    if q_id:
        try:
            bid = int(q_id)
            q = q.filter(Booking.id == bid)
        except ValueError:
            q = q.filter(False)

    bookings = q.order_by(Booking.booking_date.desc()).all()
    return render_template(
        "admin/bookings.html",
        bookings=bookings,
        booking_id=q_id,
    )


@app.route("/admin/bookings/<int:booking_id>/mark_paid", methods=["POST"])
@login_required
def admin_mark_paid(booking_id):
    if current_user.role != "admin":
        return redirect("/login")

    booking = Booking.query.get_or_404(booking_id)
    booking.payment_status = "paid"
    booking.payment_method = request.form.get("method", "cash")

    if booking.kyc_status == "verified":
        booking.booking_status = "confirmed"

    db.session.commit()
    flash("Booking marked as paid.", "success")
    return redirect(url_for("admin_bookings"))


@app.route("/admin/bookings/<int:booking_id>/kyc", methods=["POST"])
@login_required
def admin_kyc_update(booking_id):
    if current_user.role != "admin":
        return redirect("/login")

    booking = Booking.query.get_or_404(booking_id)
    new_status = request.form.get("kyc_status", "pending")
    booking.kyc_status = new_status
    booking.kyc_verified_by = current_user.id
    booking.kyc_verified_at = datetime.utcnow()

    if booking.kyc_status == "verified":
        booking.booking_status = "kyc_verified"
        if booking.payment_status == "paid":
            booking.booking_status = "completed"

    db.session.commit()
    flash("KYC status updated.", "success")
    return redirect(url_for("admin_bookings"))


@app.route("/admin/bookings/<int:booking_id>/checkout", methods=["POST"])
@login_required
def admin_checkout_booking(booking_id):
    if current_user.role != "admin":
        return redirect("/login")

    booking = Booking.query.get_or_404(booking_id)
    booking.checkout_date = date.today()
    booking.booking_status = "checked_out"
    if booking.room:
        booking.room.available = True

    db.session.commit()
    flash("Guest checked out and room freed.", "success")
    return redirect(url_for("admin_bookings"))


@app.route("/admin/bookings/<int:booking_id>/approve", methods=["POST"])
@login_required
def admin_approve_booking(booking_id):
    if current_user.role != "admin":
        return redirect("/login")

    booking = Booking.query.get_or_404(booking_id)
    booking.booking_status = "approved"
    db.session.commit()
    flash("Booking approved.", "success")
    return redirect(url_for("admin_bookings"))


@app.route("/admin/bookings/<int:booking_id>/decline", methods=["POST"])
@login_required
def admin_decline_booking(booking_id):
    if current_user.role != "admin":
        return redirect("/login")

    booking = Booking.query.get_or_404(booking_id)
    booking.booking_status = "declined"
    if booking.room:
        booking.room.available = True
    db.session.commit()
    flash("Booking declined.", "warning")
    return redirect(url_for("admin_bookings"))


@app.route("/admin/bookings/<int:booking_id>/complete", methods=["POST"])
@login_required
def admin_complete_booking(booking_id):
    if current_user.role != "admin":
        return redirect("/login")

    booking = Booking.query.get_or_404(booking_id)
    if booking.kyc_status == "verified" and booking.payment_status in ("paid", "received"):
        booking.booking_status = "completed"
        db.session.commit()
        flash("Booking marked as completed.", "success")
    else:
        flash(
            "Ensure KYC is verified and payment is paid/received before completing.",
            "error",
        )
    return redirect(url_for("admin_bookings"))


@app.route("/admin/bookings/<int:booking_id>")
@login_required
def admin_booking_detail(booking_id):
    if current_user.role != "admin":
        return redirect("/login")
    booking = Booking.query.get_or_404(booking_id)
    return render_template("admin/booking_detail.html", booking=booking)


# ---- Reports ----
@app.route("/admin/reports/revenue")
@login_required
def admin_revenue_report():
    if current_user.role != "admin":
        return redirect("/login")

    from_date_str = request.args.get("from")
    to_date_str = request.args.get("to")

    q = Booking.query.filter_by(payment_status="paid")
    if from_date_str:
        from_date = datetime.strptime(from_date_str, "%Y-%m-%d")
        q = q.filter(Booking.booking_date >= from_date)
    if to_date_str:
        to_date = datetime.strptime(to_date_str, "%Y-%m-%d")
        q = q.filter(Booking.booking_date <= to_date)

    bookings = q.order_by(Booking.booking_date.desc()).all()
    total_revenue = sum(compute_booking_total(b) for b in bookings)

    return render_template(
        "admin/revenue_report.html",
        bookings=bookings,
        total_revenue=total_revenue,
        from_date=from_date_str,
        to_date=to_date_str,
    )


@app.route("/admin/reports/strength")
@login_required
def admin_strength_report():
    if current_user.role != "admin":
        return redirect("/login")

    rows = (
        db.session.query(
            PG.id,
            PG.name,
            func.count(Booking.id).label("strength"),
        )
        .join(Room, Room.pg_id == PG.id)
        .join(Booking, Booking.room_id == Room.id)
        .filter(
            Booking.booking_status.in_(
                ["approved", "confirmed", "completed"]
            )
        )
        .group_by(PG.id, PG.name)
        .all()
    )
    total_strength = sum(r.strength for r in rows)

    return render_template(
        "admin/strength_report.html",
        rows=rows,
        total_strength=total_strength,
    )


@app.route("/admin/attendance", methods=["GET", "POST"])
@login_required
def admin_attendance():
    if current_user.role != "admin":
        return redirect("/login")

    today = date.today()

    # bookings eligible for marking today
    bookings = (
        Booking.query.filter(
            Booking.booking_status.in_(["approved", "confirmed", "completed"])
        )
        .order_by(Booking.id.desc())
        .all()
    )

    if request.method == "POST":
        for b in bookings:
            value = request.form.get(f"booking_{b.id}")  # "present" or None
            status = "present" if value == "present" else "absent"

            existing = Attendance.query.filter_by(
                booking_id=b.id, date=today
            ).first()

            if existing:
                existing.status = status
            else:
                db.session.add(
                    Attendance(booking_id=b.id, date=today, status=status)
                )
        db.session.commit()
        flash("Attendance saved for today.", "success")
        return redirect(url_for("admin_attendance"))

    # map for today's checkboxes
    today_map = {
        a.booking_id: a.status
        for a in Attendance.query.filter_by(date=today).all()
    }

    # simple attendance report (all records with booking + PG info)
    records = (
        Attendance.query
        .join(Booking)
        .join(Room)
        .join(PG)
        .order_by(Attendance.date.desc(), Booking.id.desc())
        .all()
    )

    return render_template(
        "admin/attendance.html",
        bookings=bookings,
        today=today,
        today_map=today_map,
        records=records,
    )


# ---- Admin PG management ----
@app.route("/admin/pgs", methods=["GET"])
@login_required
def admin_pgs():
    if current_user.role != "admin":
        flash("Admin access only")
        return redirect("/login")

    pgs = PG.query.order_by(PG.id.desc()).all()
    return render_template("admin/pg_form.html", pgs=pgs, pg=None, mode="create")


@app.route("/admin/pgs/new", methods=["POST"])
@login_required
def admin_create_pg():
    if current_user.role != "admin":
        flash("Admin access only")
        return redirect("/login")

    name = request.form.get("name", "").strip()
    location = request.form.get("location", "").strip()
    latitude = request.form.get("latitude")
    longitude = request.form.get("longitude")

    if not name:
        flash("Name is required", "danger")
        return redirect(url_for("admin_pgs"))

    pg = PG(
        name=name,
        location=location or None,
        latitude=float(latitude) if latitude else None,
        longitude=float(longitude) if longitude else None,
    )
    db.session.add(pg)
    db.session.commit()
    flash("PG created successfully", "success")
    return redirect(url_for("admin_pgs"))


@app.route("/admin/pgs/<int:pg_id>/edit", methods=["GET", "POST"])
@login_required
def admin_edit_pg(pg_id):
    if current_user.role != "admin":
        flash("Admin access only")
        return redirect("/login")

    pg = PG.query.get_or_404(pg_id)

    if request.method == "POST":
        pg.name = request.form.get("name", "").strip()
        pg.location = request.form.get("location", "").strip() or None
        latitude = request.form.get("latitude")
        longitude = request.form.get("longitude")
        pg.latitude = float(latitude) if latitude else None
        pg.longitude = float(longitude) if longitude else None

        db.session.commit()
        flash("PG updated successfully", "success")
        return redirect(url_for("admin_pgs"))

    pgs = PG.query.order_by(PG.id.desc()).all()
    return render_template("admin/pg_form.html", pgs=pgs, pg=pg, mode="edit")


@app.route("/admin/pgs/<int:pg_id>/delete", methods=["POST"])
@login_required
def admin_delete_pg(pg_id):
    if current_user.role != "admin":
        flash("Admin access only")
        return redirect("/login")

    pg = PG.query.get_or_404(pg_id)

    if pg.rooms:
        flash("Cannot delete PG with existing rooms.", "danger")
        return redirect(url_for("admin_pgs"))

    db.session.delete(pg)
    db.session.commit()
    flash("PG deleted successfully", "success")
    return redirect(url_for("admin_pgs"))


# ---- Admin: Room management using room_form.html ----
@app.route("/admin/pgs/<int:pg_id>/rooms/new", methods=["GET", "POST"])
@login_required
def admin_create_room(pg_id):
    if current_user.role != "admin":
        flash("Admin access only")
        return redirect("/login")

    pg = PG.query.get_or_404(pg_id)
    rooms = Room.query.filter_by(pg_id=pg.id).order_by(Room.number).all()

    if request.method == "POST":
        number = request.form.get("number", "").strip()
        price = request.form.get("price")
        sharing = request.form.get("sharing") or 1
        ac_type = request.form.get("ac_type", "non-ac")

        if not number or not price:
            flash("Room number and price are required", "danger")
            return render_template(
                "admin/room_form.html", pg=pg, rooms=rooms, room=None
            )

        filename = None
        file = request.files.get("image")
        if file and file.filename:
            filename = secure_filename(file.filename)
            file.save(os.path.join(UPLOAD_FOLDER, filename))

        room = Room(
            number=number,
            price=float(price),
            sharing=int(sharing),
            ac_type=ac_type,
            image_url=filename,
            available=True,
            pg_id=pg.id,
        )
        db.session.add(room)
        pg.total_rooms = (pg.total_rooms or 0) + 1
        db.session.commit()
        flash("Room created successfully", "success")
        return redirect(url_for("admin_create_room", pg_id=pg.id))

    return render_template("admin/room_form.html", pg=pg, rooms=rooms, room=None)


@app.route("/admin/rooms/<int:room_id>/edit", methods=["GET", "POST"])
@login_required
def admin_edit_room(room_id):
    if current_user.role != "admin":
        flash("Admin access only")
        return redirect("/login")

    room = Room.query.get_or_404(room_id)
    pg = room.pg
    rooms = Room.query.filter_by(pg_id=pg.id).order_by(Room.number).all()

    if request.method == "POST":
        room.number = request.form.get("number", "").strip()
        room.price = float(request.form.get("price"))
        room.sharing = int(request.form.get("sharing") or 1)
        room.ac_type = request.form.get("ac_type", "non-ac")

        file = request.files.get("image")
        if file and file.filename:
            filename = secure_filename(file.filename)
            file.save(os.path.join(UPLOAD_FOLDER, filename))
            room.image_url = filename

        db.session.commit()
        flash("Room updated successfully", "success")
        return redirect(url_for("admin_create_room", pg_id=pg.id))

    return render_template("admin/room_form.html", pg=pg, rooms=rooms, room=room)


@app.route("/admin/rooms/<int:room_id>/delete", methods=["POST"])
@login_required
def admin_delete_room(room_id):
    if current_user.role != "admin":
        flash("Admin access only")
        return redirect("/login")

    room = Room.query.get_or_404(room_id)
    pg_id = room.pg_id

    db.session.delete(room)
    pg = PG.query.get(pg_id)
    if pg and pg.total_rooms:
        pg.total_rooms = max(pg.total_rooms - 1, 0)

    db.session.commit()
    flash("Room deleted successfully", "success")
    return redirect(url_for("admin_create_room", pg_id=pg_id))


if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(debug=True, port=5000)
