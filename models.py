from datetime import datetime, date
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from extensions import db


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(120), unique=True, nullable=False)  # email / login id
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="tenant")
    # For admin/tenant, which PG they “belong” to (superadmin has None)
    pg_id = db.Column(db.Integer, db.ForeignKey("pg.id"), nullable=True)

    def set_password(self, password: str):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)


class PG(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    location = db.Column(db.String(255))
    latitude = db.Column(db.Float)
    longitude = db.Column(db.Float)
    total_rooms = db.Column(db.Integer, default=0)

    rooms = db.relationship("Room", backref="pg", lazy=True)
    admins = db.relationship("User", backref="pg_admin", lazy=True)


class Room(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.String(50), nullable=False)
    price = db.Column(db.Float, nullable=False)
    sharing = db.Column(db.Integer, default=1)
    ac_type = db.Column(db.String(20), default="non-ac")
    image_url = db.Column(db.String(255))
    available = db.Column(db.Boolean, default=True)
    pg_id = db.Column(db.Integer, db.ForeignKey("pg.id"), nullable=False)

    bookings = db.relationship("Booking", backref="room", lazy=True)


class Booking(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    tenant_name = db.Column(db.String(255), nullable=False)
    tenant_phone = db.Column(db.String(50), nullable=False)
    tenant_email = db.Column(db.String(120))
    tenant_aadhar = db.Column(db.String(50))
    id_proof = db.Column(db.String(255))

    room_id = db.Column(db.Integer, db.ForeignKey("room.id"), nullable=False)
    booking_date = db.Column(db.DateTime, default=datetime.utcnow)
    move_in_date = db.Column(db.Date)

    amount = db.Column(db.Float, nullable=True)  # base monthly / booking amount
    payment_status = db.Column(db.String(20), default="pending")  # pending/paid/received
    kyc_status = db.Column(db.String(20), default="pending")
    booking_status = db.Column(
        db.String(20),
        default="kyc_pending",
    )  # requested/approved/confirmed/completed/declined/checked_out

    checkout_date = db.Column(db.Date)

    # optional
    payment_method = db.Column(db.String(50))
    kyc_verified_by = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    kyc_verified_at = db.Column(db.DateTime)

    services = db.relationship("BookingService", backref="booking", lazy=True)


class ServiceType(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    category = db.Column(db.String(50), nullable=False)
    price = db.Column(db.Float, nullable=False)
    active = db.Column(db.Boolean, default=True)


class BookingService(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    booking_id = db.Column(db.Integer, db.ForeignKey("booking.id"), nullable=False)
    service_type_id = db.Column(db.Integer, db.ForeignKey("service_type.id"), nullable=False)
    quantity = db.Column(db.Integer, default=1)
    total_price = db.Column(db.Float, nullable=False)

    service_type = db.relationship("ServiceType")


class Attendance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    booking_id = db.Column(db.Integer, db.ForeignKey("booking.id"), nullable=False)
    date = db.Column(db.Date, default=date.today)
    status = db.Column(db.String(20), default="present")

    booking = db.relationship("Booking")
