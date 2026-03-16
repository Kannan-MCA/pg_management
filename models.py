from datetime import datetime, date

from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

from extensions import db


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)  # use email/phone
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), default="tenant")  # admin / tenant

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class PG(db.Model):
    __table_args__ = {"extend_existing": True}
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    location = db.Column(db.String(500))
    latitude = db.Column(db.Float)
    longitude = db.Column(db.Float)
    total_rooms = db.Column(db.Integer, default=0)


class Room(db.Model):
    __table_args__ = {"extend_existing": True}
    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.String(20), nullable=False)
    price = db.Column(db.Float, nullable=False)
    sharing = db.Column(db.Integer, nullable=False, default=1)
    ac_type = db.Column(db.String(20), default="non-ac")
    image_url = db.Column(db.String(500))
    available = db.Column(db.Boolean, default=True)
    pg_id = db.Column(db.Integer, db.ForeignKey("pg.id"), nullable=False)

    pg = db.relationship("PG", backref="rooms")


class Booking(db.Model):
    __table_args__ = {"extend_existing": True}

    id = db.Column(db.Integer, primary_key=True)

    # Tenant details
    tenant_name = db.Column(db.String(100), nullable=False)
    tenant_phone = db.Column(db.String(15), nullable=False)
    tenant_email = db.Column(db.String(120))
    tenant_aadhar = db.Column(db.String(20))
    id_proof = db.Column(db.String(500))  # stored file path / URL

    # Room relation
    room_id = db.Column(db.Integer, db.ForeignKey("room.id"), nullable=False)
    room = db.relationship("Room", backref="bookings")

    # Dates
    booking_date = db.Column(db.DateTime, default=datetime.utcnow)
    move_in_date = db.Column(db.Date)  # keep this as the only move-in field

    # Overall booking status
    # possible: initiated, kyc_pending, kyc_verified, payment_pending,
    # approved, declined, completed, cancelled
    booking_status = db.Column(db.String(20), default="kyc_pending")

    # Payment fields (single definition)
    amount = db.Column(db.Float, default=0.0)
    payment_status = db.Column(db.String(20), default="pending")  # pending/paid/failed/received
    payment_method = db.Column(db.String(20))  # cash/upi/card

    # KYC fields (single definition)
    kyc_status = db.Column(db.String(20), default="pending")  # pending/verified/rejected
    kyc_verified_by = db.Column(db.Integer, db.ForeignKey("user.id"))
    kyc_verified_at = db.Column(db.DateTime)

    kyc_verifier = db.relationship("User", foreign_keys=[kyc_verified_by])
    # tenant_id = db.Column(db.Integer, db.ForeignKey("user.id"))  # optional link to user


class ServiceType(db.Model):
    """
    Laundry/Food service catalog.
    """
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)      # "Laundry", "Breakfast", etc.
    category = db.Column(db.String(20), nullable=False)  # "laundry", "food"
    price = db.Column(db.Float, nullable=False)
    active = db.Column(db.Boolean, default=True)


class BookingService(db.Model):
    """
    Selected add-on services per booking.
    """
    id = db.Column(db.Integer, primary_key=True)
    booking_id = db.Column(db.Integer, db.ForeignKey("booking.id"), nullable=False)
    service_type_id = db.Column(db.Integer, db.ForeignKey("service_type.id"), nullable=False)
    quantity = db.Column(db.Integer, default=1)
    total_price = db.Column(db.Float, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    booking = db.relationship("Booking", backref="services")
    service_type = db.relationship("ServiceType")


class Attendance(db.Model):
    """
    Daily attendance per booking (tenant).
    """
    id = db.Column(db.Integer, primary_key=True)
    booking_id = db.Column(db.Integer, db.ForeignKey("booking.id"), nullable=False)
    date = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(10), nullable=False, default="present")  # present/absent
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    booking = db.relationship("Booking", backref="attendance")
