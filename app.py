import os
from datetime import datetime, date
from functools import wraps

from flask import (
    Flask, render_template, request, redirect,
    url_for, flash, abort
)
from flask_login import (
    LoginManager, login_user, login_required,
    current_user, logout_user
)
from werkzeug.utils import secure_filename
from sqlalchemy import func

from config import DevelopmentConfig, Config
from extensions import db
from models import (
    User, PG, Room, Booking,
    ServiceType, BookingService,
    Attendance
)

app = Flask(__name__)
app.config.from_object(DevelopmentConfig)

db.init_app(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"

UPLOAD_FOLDER = app.config["UPLOAD_FOLDER"]
ID_PROOF_FOLDER = app.config["ID_PROOF_FOLDER"]
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(ID_PROOF_FOLDER, exist_ok=True)


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


def allowed_file(filename: str) -> bool:
    return Config.allowed_file(filename)


def roles_required(*roles):
    def decorator(view):
        @wraps(view)
        @login_required
        def wrapped(*args, **kwargs):
            if current_user.role not in roles:
                abort(403)
            return view(*args, **kwargs)
        return wrapped
    return decorator


def search_pgs(query):
    if not query or len(query) < 2:
        return PG.query.all()
    return (
        PG.query.filter(
            (PG.location.ilike(f"%{query}%"))
            | (PG.name.ilike(f"%{query}%"))
        )
        .order_by(PG.name)
        .all()
    )


def compute_booking_total(booking: Booking) -> float:
    base = booking.amount or (booking.room.price if booking.room else 0.0)
    addons = sum(s.total_price for s in booking.services)
    return base + addons


# ---------- Seed superadmin & sample ----------
@app.route("/init_superadmin")
def init_superadmin():
    if not User.query.filter_by(username="superadmin@example.com").first():
        u = User(username="superadmin@example.com", role="superadmin")
        u.set_password("superadmin123")
        db.session.add(u)
        db.session.commit()
        return "Superadmin created: superadmin@example.com / superadmin123"
    return "Superadmin already exists"


# ---------- Guest / public pages ----------
@app.route("/")
def home():
    search_query = request.args.get("search", "").strip()
    pgs = search_pgs(search_query) if search_query else PG.query.all()
    return render_template("guest/home.html", pgs=pgs, search_query=search_query)


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
    return render_template("guest/rooms.html", pg=pg, rooms=rooms)


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
            if move_in_date_str else None
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
            return render_template("guest/booking_form.html", room=room, pg=pg)

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
            booking_status="requested",
        )
        db.session.add(booking)
        db.session.flush()
        room.available = False
        db.session.commit()

        flash(f"Booking request submitted! ID: BK{booking.id:04d}", "success")
        return redirect(url_for("booking_receipt", booking_id=booking.id))

    pg = PG.query.get(room.pg_id)
    return render_template("guest/booking_form.html", room=room, pg=pg)


@app.route("/booking/receipt/<int:booking_id>")
def booking_receipt(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    room = booking.room
    pg = room.pg
    total = compute_booking_total(booking)
    return render_template(
        "guest/booking_receipt.html",
        booking=booking,
        room=room,
        pg=pg,
        total=total,
    )


# ---------- Auth ----------
@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        if current_user.role == "superadmin":
            return redirect("/superadmin/dashboard")
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
            if user.role == "superadmin":
                return redirect("/superadmin/dashboard")
            if user.role == "admin":
                return redirect("/admin/dashboard")
            return redirect("/tenant/dashboard")

        flash("Invalid credentials", "danger")

    return render_template("auth/login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Logged out successfully!", "success")
    return redirect(url_for("home"))


# ---------- Superadmin: global PG & stats ----------
@app.route("/superadmin/dashboard")
@roles_required("superadmin")
def superadmin_dashboard():
    stats = {
        "total_pgs": PG.query.count(),
        "total_rooms": Room.query.count(),
        "total_bookings": Booking.query.count(),
        "paid_bookings": Booking.query.filter_by(payment_status="paid").count(),
    }
    paid = Booking.query.filter_by(payment_status="paid").all()
    total_revenue = sum(compute_booking_total(b) for b in paid)
    return render_template(
        "superadmin/dashboard.html",
        stats=stats,
        total_revenue=total_revenue,
    )


@app.route("/superadmin/pgs", methods=["GET", "POST"])
@roles_required("superadmin")
def superadmin_pgs():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        location = request.form.get("location", "").strip()
        if not name:
            flash("Name is required", "danger")
            return redirect(url_for("superadmin_pgs"))
        pg = PG(name=name, location=location or None)
        db.session.add(pg)
        db.session.commit()
        flash("PG created", "success")
        return redirect(url_for("superadmin_pgs"))

    pgs = PG.query.order_by(PG.id.desc()).all()
    return render_template("superadmin/pgs.html", pgs=pgs)


@app.route("/superadmin/pgs/<int:pg_id>/assign_admin", methods=["POST"])
@roles_required("superadmin")
def superadmin_assign_admin(pg_id):
    pg = PG.query.get_or_404(pg_id)
    email = request.form.get("admin_email")
    password = request.form.get("admin_password") or "Admin@" + str(pg.id)

    user = User.query.filter_by(username=email).first()
    if user:
        user.role = "admin"
        user.pg_id = pg.id
    else:
        user = User(username=email, role="admin", pg_id=pg.id)
        user.set_password(password)
        db.session.add(user)
    db.session.commit()
    flash(f"Admin assigned to PG {pg.name}", "success")
    return redirect(url_for("superadmin_pgs"))


# ---------- Admin: scoped dashboard / bookings / attendance ----------
def admin_scoped_bookings():
    q = Booking.query
    if current_user.role == "admin":
        q = q.join(Room).filter(Room.pg_id == current_user.pg_id)
    return q


@app.route("/admin/dashboard")
@roles_required("admin", "superadmin")
def admin_dashboard():
    if current_user.role == "admin":
        pg_id = current_user.pg_id
        total_rooms = Room.query.filter_by(pg_id=pg_id).count()
        available_rooms = Room.query.filter_by(pg_id=pg_id, available=True).count()
        total_bookings = (
            Booking.query.join(Room).filter(Room.pg_id == pg_id).count()
        )
        total_pgs = 1
        paid_bookings = (
            Booking.query.join(Room)
            .filter(Room.pg_id == pg_id, Booking.payment_status == "paid")
            .count()
        )
        paid = (
            Booking.query.join(Room)
            .filter(Room.pg_id == pg_id, Booking.payment_status == "paid")
            .all()
        )
    else:  # superadmin viewing admin dashboard as global view
        total_pgs = PG.query.count()
        total_rooms = Room.query.count()
        available_rooms = Room.query.filter_by(available=True).count()
        total_bookings = Booking.query.count()
        paid_bookings = Booking.query.filter_by(payment_status="paid").count()
        paid = Booking.query.filter_by(payment_status="paid").all()

    stats = {
        "total_pgs": total_pgs,
        "total_rooms": total_rooms,
        "available_rooms": available_rooms,
        "total_bookings": total_bookings,
        "paid_bookings": paid_bookings,
    }
    total_revenue = sum(compute_booking_total(b) for b in paid)

    return render_template(
        "admin/dashboard.html",
        stats=stats,
        total_revenue=total_revenue,
    )


@app.route("/admin/bookings")
@roles_required("admin", "superadmin")
def admin_bookings():
    status = request.args.get("status")
    q_id = request.args.get("booking_id", "").strip()

    q = admin_scoped_bookings()
    if status:
        q = q.filter(Booking.payment_status == status)
    if q_id:
        try:
            q = q.filter(Booking.id == int(q_id))
        except ValueError:
            q = q.filter(False)

    bookings = q.order_by(Booking.booking_date.desc()).all()
    return render_template("admin/bookings.html", bookings=bookings, booking_id=q_id)


def ensure_tenant_account_for_booking(booking: Booking):
    if not booking.tenant_email:
        return
    user = User.query.filter_by(username=booking.tenant_email).first()
    if user:
        user.role = "tenant"
        user.pg_id = booking.room.pg_id
    else:
        temp_password = "Tenant@" + str(booking.id)
        user = User(
            username=booking.tenant_email,
            role="tenant",
            pg_id=booking.room.pg_id,
        )
        user.set_password(temp_password)
        db.session.add(user)
        # TODO: send credentials via mail/SMS
    db.session.flush()


@app.route("/admin/bookings/<int:booking_id>/approve", methods=["POST"])
@roles_required("admin", "superadmin")
def admin_approve_booking(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    if current_user.role == "admin" and booking.room.pg_id != current_user.pg_id:
        abort(403)
    booking.booking_status = "approved"
    ensure_tenant_account_for_booking(booking)
    db.session.commit()
    flash("Booking approved and tenant account created/updated.", "success")
    return redirect(url_for("admin_bookings"))


@app.route("/admin/bookings/<int:booking_id>/mark_paid", methods=["POST"])
@roles_required("admin", "superadmin")
def admin_mark_paid(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    if current_user.role == "admin" and booking.room.pg_id != current_user.pg_id:
        abort(403)
    booking.payment_status = "paid"
    booking.payment_method = request.form.get("method", "cash")
    db.session.commit()
    flash("Booking marked as paid.", "success")
    return redirect(url_for("admin_bookings"))


@app.route("/admin/bookings/<int:booking_id>/checkout", methods=["POST"])
@roles_required("admin", "superadmin")
def admin_checkout_booking(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    if current_user.role == "admin" and booking.room.pg_id != current_user.pg_id:
        abort(403)
    booking.checkout_date = date.today()
    booking.booking_status = "checked_out"
    if booking.room:
        booking.room.available = True
    db.session.commit()
    flash("Guest checked out and room freed.", "success")
    return redirect(url_for("admin_bookings"))


# Attendance (mark + report same page)
@app.route("/admin/attendance", methods=["GET", "POST"])
@roles_required("admin", "superadmin")
def admin_attendance():
    today = date.today()

    bookings = (
        admin_scoped_bookings()
        .filter(
            Booking.booking_status.in_(["approved", "confirmed", "completed"])
        )
        .order_by(Booking.id.desc())
        .all()
    )

    if request.method == "POST":
        for b in bookings:
            value = request.form.get(f"booking_{b.id}")
            status = "present" if value == "present" else "absent"
            existing = Attendance.query.filter_by(
                booking_id=b.id, date=today
            ).first()
            if existing:
                existing.status = status
            else:
                db.session.add(Attendance(booking_id=b.id, date=today, status=status))
        db.session.commit()
        flash("Attendance saved for today.", "success")
        return redirect(url_for("admin_attendance"))

    today_map = {
        a.booking_id: a.status
        for a in Attendance.query.filter_by(date=today).all()
    }

    records = (
        Attendance.query.join(Booking).join(Room)
        .filter(Room.pg_id == current_user.pg_id if current_user.role == "admin" else True)
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


# Strength & revenue reports (already mostly done)
@app.route("/admin/reports/strength")
@roles_required("admin", "superadmin")
def admin_strength_report():
    q = (
        db.session.query(
            PG.id, PG.name, func.count(Booking.id).label("strength")
        )
        .join(Room, Room.pg_id == PG.id)
        .join(Booking, Booking.room_id == Room.id)
        .filter(
            Booking.booking_status.in_(["approved", "confirmed", "completed"])
        )
    )
    if current_user.role == "admin":
        q = q.filter(PG.id == current_user.pg_id)

    rows = q.group_by(PG.id, PG.name).all()
    total_strength = sum(r.strength for r in rows)

    return render_template(
        "admin/strength.html",
        rows=rows,
        total_strength=total_strength,
    )


@app.route("/admin/reports/revenue")
@roles_required("admin", "superadmin")
def admin_revenue_report():
    from_date_str = request.args.get("from")
    to_date_str = request.args.get("to")

    q = Booking.query.filter_by(payment_status="paid")
    if current_user.role == "admin":
        q = q.join(Room).filter(Room.pg_id == current_user.pg_id)

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


# ---------- Tenant ----------
@app.route("/tenant/dashboard")
@roles_required("tenant")
def tenant_dashboard():
    bookings = Booking.query.filter_by(tenant_email=current_user.username).all()
    return render_template("tenant/dashboard.html", bookings=bookings)


@app.route("/tenant/billing")
@roles_required("tenant")
def tenant_billing():
    booking = (
        Booking.query
        .filter_by(tenant_email=current_user.username)
        .order_by(Booking.id.desc())
        .first_or_404()
    )

    nights = 1
    room_rate = booking.room.price
    room_total = nights * room_rate

    service_items = [
        {
            "name": s.service_type.name,
            "unit_price": s.service_type.price,
            "quantity": s.quantity,
            "total": s.total_price,
        }
        for s in booking.services
    ]

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
            "address": "",
            "phone": booking.tenant_phone,
            "email": booking.tenant_email,
        },
        "nights": nights,
        "room_rate": room_rate,
        "room_total": room_total,
        "service_items": service_items,
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
        "name": booking.room.pg.name,
        "address": booking.room.pg.location or "",
        "phone": "",
        "email": "",
    }

    return render_template("tenant/billing.html", billing=billing, hotel=hotel)


@app.route("/tenant/booking/<int:booking_id>/services", methods=["GET", "POST"])
@roles_required("tenant")
def tenant_services(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    if booking.tenant_email != current_user.username:
        abort(403)

    services = ServiceType.query.filter_by(active=True).all()

    if request.method == "POST":
        for s in services:
            qty_str = request.form.get(f"service_{s.id}")
            if qty_str:
                qty = int(qty_str)
                if qty > 0:
                    db.session.add(
                        BookingService(
                            booking_id=booking.id,
                            service_type_id=s.id,
                            quantity=qty,
                            total_price=qty * s.price,
                        )
                    )
        db.session.commit()
        flash("Services updated for your booking.", "success")
        return redirect(url_for("tenant_dashboard"))

    return render_template("tenant/services.html", booking=booking, services=services)
@app.route("/admin/pg/<int:pg_id>/rooms", methods=["GET", "POST"])
@roles_required("admin", "superadmin")
def admin_pg_rooms(pg_id):
    pg = PG.query.get_or_404(pg_id)

    # if normal admin, ensure they own this PG
    if current_user.role == "admin" and current_user.pg_id != pg.id:
        abort(403)

    if request.method == "POST":
        number = request.form.get("number", "").strip()
        price = float(request.form.get("price") or 0)
        sharing = int(request.form.get("sharing") or 1)
        ac_type = request.form.get("ac_type") or "non-ac"

        if not number or price <= 0:
            flash("Room number and price are required.", "danger")
        else:
            room = Room(
                number=number,
                price=price,
                sharing=sharing,
                ac_type=ac_type,
                pg_id=pg.id,
                available=True,
            )
            db.session.add(room)
            pg.total_rooms = (pg.total_rooms or 0) + 1
            db.session.commit()
            flash("Room added to PG.", "success")
        return redirect(url_for("admin_pg_rooms", pg_id=pg.id))

    rooms = Room.query.filter_by(pg_id=pg.id).order_by(Room.number).all()
    return render_template("admin/pg_rooms.html", pg=pg, rooms=rooms)


if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(debug=True, port=5000)
