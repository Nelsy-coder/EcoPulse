from flask import Flask, render_template_string, request, send_file, redirect, url_for, session, jsonify, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
import matplotlib
import secrets
import string
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

# Configure matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from datetime import UTC, datetime, timedelta
import io
import base64
import heapq
import math
import json
from collections import deque
from zoneinfo import ZoneInfo

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-change-this-in-production'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///ecopulse.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

APP_TIMEZONE = ZoneInfo('Africa/Nairobi')
PHONE_COUNTRY_CODES = [
    {'code': '+254', 'label': 'Kenya (+254)'},
    {'code': '+255', 'label': 'Tanzania (+255)'},
    {'code': '+256', 'label': 'Uganda (+256)'},
    {'code': '+250', 'label': 'Rwanda (+250)'},
    {'code': '+257', 'label': 'Burundi (+257)'},
    {'code': '+251', 'label': 'Ethiopia (+251)'},
    {'code': '+211', 'label': 'South Sudan (+211)'},
    {'code': '+234', 'label': 'Nigeria (+234)'},
    {'code': '+27', 'label': 'South Africa (+27)'},
    {'code': '+1', 'label': 'USA/Canada (+1)'}
]

# Load SMTP settings from smtp.env if it exists
env_path = os.path.join(os.path.dirname(__file__), 'smtp.env')
if os.path.exists(env_path):
    with open(env_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#'):
                parts = line.split('=', 1)
                if len(parts) == 2:
                    key, val = parts[0].strip(), parts[1].strip()
                    # Strip quotes if they exist around the value
                    if len(val) >= 2 and val.startswith(('"', "'")) and val.endswith(('"', "'")):
                        val = val[1:-1]
                    # Also strip spaces from passwords
                    if key == 'ECOULSE_SMTP_PASSWORD':
                        val = ''.join(val.split())
                    os.environ[key] = val

app.config['SMTP_HOST'] = os.environ.get('ECOULSE_SMTP_HOST', '').strip()
app.config['SMTP_PORT'] = int(os.environ.get('ECOULSE_SMTP_PORT', '587'))
app.config['SMTP_USERNAME'] = os.environ.get('ECOULSE_SMTP_USERNAME', '').strip()
app.config['SMTP_PASSWORD'] = os.environ.get('ECOULSE_SMTP_PASSWORD', '').strip()
app.config['SMTP_FROM'] = os.environ.get('ECOULSE_SMTP_FROM', '').strip()
app.config['SMTP_USE_TLS'] = os.environ.get('ECOULSE_SMTP_USE_TLS', 'true').strip().lower() in (
    '1', 'true', 'yes', 'y', 'on'
)

db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'


# ===================== DATABASE MODELS =====================

class User(UserMixin, db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(120), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='customer')
    employee_id = db.Column(db.String(20), unique=True, nullable=True)
    department = db.Column(db.String(50), nullable=True)
    threshold = db.Column(db.Float, default=600)
    currency = db.Column(db.String(10), default='Ksh')
    unit_cost = db.Column(db.Float, default=0.12)
    alert_email = db.Column(db.Boolean, default=True)
    meter_number = db.Column(db.String(11), unique=True, nullable=True)
    phone_number = db.Column('phone', db.String(20), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships - specify foreign keys explicitly
    readings = db.relationship('Reading',
                               foreign_keys='Reading.user_id',
                               back_populates='user',
                               lazy=True,
                               cascade='all, delete-orphan')

    reviewed_readings = db.relationship('Reading',
                                        foreign_keys='Reading.reviewed_by',
                                        back_populates='reviewer',
                                        lazy=True)

    approved_readings = db.relationship('Reading',
                                        foreign_keys='Reading.approved_by',
                                        back_populates='approver',
                                        lazy=True)

    settings = db.relationship('UserSettings',
                               foreign_keys='UserSettings.user_id',
                               back_populates='user',
                               uselist=False,
                               cascade='all, delete-orphan')

    logs = db.relationship('SystemLog',
                           foreign_keys='SystemLog.user_id',
                           back_populates='user',
                           lazy=True)

    sent_reports = db.relationship('Report',
                                   foreign_keys='Report.sent_by',
                                   back_populates='sender',
                                   lazy=True)

    received_reports = db.relationship('Report',
                                       foreign_keys='Report.sent_to',
                                       back_populates='recipient',
                                       lazy=True)

    financial_records = db.relationship('FinancialRecord',
                                        foreign_keys='FinancialRecord.user_id',
                                        back_populates='user',
                                        lazy=True)

    consumption_reviews = db.relationship('ConsumptionReview',
                                          foreign_keys='ConsumptionReview.examiner_id',
                                          back_populates='examiner',
                                          lazy=True)

    approved_reviews = db.relationship('ConsumptionReview',
                                       foreign_keys='ConsumptionReview.approved_by',
                                       back_populates='approver',
                                       lazy=True)

    customer_submissions = db.relationship('CustomerSubmission',
                                           foreign_keys='CustomerSubmission.customer_id',
                                           back_populates='customer',
                                           lazy=True)

    devices = db.relationship('CustomerDevice',
                              foreign_keys='CustomerDevice.user_id',
                              back_populates='user',
                              lazy=True,
                              cascade='all, delete-orphan')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def generate_employee_id(self):
        prefix = 'ADM' if self.role == 'admin' else 'EXM'
        random_digits = ''.join(secrets.choice(string.digits) for _ in range(6))
        return f"{prefix}{random_digits}"


class Reading(db.Model):
    __tablename__ = 'readings'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    date = db.Column(db.String(100), nullable=False)
    kwh = db.Column(db.Float, nullable=False)
    cost = db.Column(db.Float, nullable=True, default=0.0)
    is_reviewed = db.Column(db.Boolean, default=False)
    reviewed_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    reviewed_at = db.Column(db.DateTime, nullable=True)
    review_notes = db.Column(db.Text, nullable=True)
    is_approved = db.Column(db.Boolean, default=False)
    approved_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    approved_at = db.Column(db.DateTime, nullable=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships - specify foreign keys explicitly
    user = db.relationship('User', foreign_keys=[user_id], back_populates='readings')
    reviewer = db.relationship('User', foreign_keys=[reviewed_by], back_populates='reviewed_readings')
    approver = db.relationship('User', foreign_keys=[approved_by], back_populates='approved_readings')

    def calculate_cost(self, unit_cost):
        self.cost = self.kwh * unit_cost
        return self.cost


class UserSettings(db.Model):
    __tablename__ = 'user_settings'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, unique=True)
    alert_threshold = db.Column(db.Float, default=600)
    alert_frequency = db.Column(db.String(20), default='immediate')
    co2_per_kwh = db.Column(db.Float, default=0.385)
    allow_overage = db.Column(db.Boolean, default=False)
    auto_shutdown_enabled = db.Column(db.Boolean, default=True)
    shutdown_delay_minutes = db.Column(db.Integer, default=5)
    last_threshold_alert_at = db.Column(db.DateTime, nullable=True)
    scheduled_shutdown_at = db.Column(db.DateTime, nullable=True)

    # NEW FIELDS FOR THRESHOLD NOTIFICATIONS
    last_80_percent_notification = db.Column(db.DateTime, nullable=True)
    last_90_percent_notification = db.Column(db.DateTime, nullable=True)
    last_95_percent_notification = db.Column(db.DateTime, nullable=True)
    last_100_percent_notification = db.Column(db.DateTime, nullable=True)
    notification_80_sent = db.Column(db.Boolean, default=False)
    notification_90_sent = db.Column(db.Boolean, default=False)
    notification_95_sent = db.Column(db.Boolean, default=False)
    notification_100_sent = db.Column(db.Boolean, default=False)
    last_consumption_check = db.Column(db.Float, default=0)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    user = db.relationship('User', foreign_keys=[user_id], back_populates='settings')


class SystemLog(db.Model):
    __tablename__ = 'system_logs'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    action = db.Column(db.String(200), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    ip_address = db.Column(db.String(50), nullable=True)

    # Relationships
    user = db.relationship('User', foreign_keys=[user_id], back_populates='logs')


class Report(db.Model):
    __tablename__ = 'reports'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=False)
    report_type = db.Column(db.String(50), nullable=False)
    sent_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    sent_to = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    pdf_path = db.Column(db.String(500), nullable=True)
    chart_data = db.Column(db.Text, nullable=True)

    # Relationships
    sender = db.relationship('User', foreign_keys=[sent_by], back_populates='sent_reports')
    recipient = db.relationship('User', foreign_keys=[sent_to], back_populates='received_reports')


class FinancialRecord(db.Model):
    __tablename__ = 'financial_records'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    period = db.Column(db.String(50), nullable=False)
    total_consumption = db.Column(db.Float, default=0)
    total_cost = db.Column(db.Float, default=0)
    total_paid = db.Column(db.Float, default=0)
    balance = db.Column(db.Float, default=0)
    due_date = db.Column(db.DateTime, nullable=True)
    payment_status = db.Column(db.String(20), default='pending')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    user = db.relationship('User', foreign_keys=[user_id], back_populates='financial_records')


class ConsumptionReview(db.Model):
    __tablename__ = 'consumption_reviews'

    id = db.Column(db.Integer, primary_key=True)
    examiner_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    period = db.Column(db.String(50), nullable=False)
    total_consumption = db.Column(db.Float, default=0)
    total_customers = db.Column(db.Integer, default=0)
    average_consumption = db.Column(db.Float, default=0)
    peak_consumption = db.Column(db.Float, default=0)
    notes = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), default='pending_review')
    reviewed_at = db.Column(db.DateTime, nullable=True)
    approved_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    approved_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    examiner = db.relationship('User', foreign_keys=[examiner_id], back_populates='consumption_reviews')
    approver = db.relationship('User', foreign_keys=[approved_by], back_populates='approved_reviews')


class CustomerSubmission(db.Model):
    __tablename__ = 'customer_submissions'

    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    period = db.Column(db.String(50), nullable=False)
    total_consumption = db.Column(db.Float, default=0)
    total_cost = db.Column(db.Float, default=0)
    average_daily = db.Column(db.Float, default=0)
    readings_count = db.Column(db.Integer, default=0)
    notes = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), default='pending')  # pending, reviewed, approved, rejected
    admin_notes = db.Column(db.Text, nullable=True)
    reviewed_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    reviewed_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    customer = db.relationship('User', foreign_keys=[customer_id], back_populates='customer_submissions')
    reviewer = db.relationship('User', foreign_keys=[reviewed_by])


class ContactMessage(db.Model):
    __tablename__ = 'contact_messages'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(255), nullable=False)
    subject = db.Column(db.String(255), nullable=False)
    message = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class CustomerDevice(db.Model):
    __tablename__ = 'customer_devices'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    category = db.Column(db.String(80), nullable=False, default='Appliance')
    watts = db.Column(db.Float, nullable=False, default=0)
    hours_per_day = db.Column(db.Float, nullable=False, default=0)
    quantity = db.Column(db.Integer, nullable=False, default=1)
    notes = db.Column(db.String(255), nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = db.relationship('User', foreign_keys=[user_id], back_populates='devices')


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


# ===================== ROLE-BASED ACCESS CONTROL =====================

def role_required(*roles):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                return redirect(url_for('login'))
            if current_user.role not in roles:
                return render_template_string(error_page,
                                              error="Access Denied: You don't have permission to access this page.")
            return f(*args, **kwargs)

        return decorated_function

    return decorator


def admin_required(f):
    return role_required('admin')(f)


def examiner_required(f):
    return role_required('examiner')(f)


# ===================== UTILITY FUNCTIONS =====================

def log_system_action(user_id, action):
    try:
        log = SystemLog(user_id=user_id, action=action, ip_address=request.remote_addr)
        db.session.add(log)
        db.session.commit()
    except:
        db.session.rollback()


def get_user_readings(user_id, days=None, start_date=None, end_date=None):
    query = Reading.query.filter_by(user_id=user_id).order_by(Reading.created_at.desc())
    if start_date and end_date:
        try:
            start = datetime.strptime(start_date, '%Y-%m-%d')
            end = datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1)
            query = query.filter(Reading.created_at >= start, Reading.created_at <= end)
        except:
            pass
    elif days:
        start = datetime.utcnow() - timedelta(days=days)
        query = query.filter(Reading.created_at >= start)
    return query.all()


def calculate_co2_emissions(kwh, co2_per_kwh=0.385):
    return kwh * co2_per_kwh


def utc_now():
    return datetime.now(UTC)


def to_local_time(dt):
    if not dt:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(APP_TIMEZONE)


def local_now():
    return datetime.now(APP_TIMEZONE)


def luhn_checksum_digit(number):
    total = 0
    reverse_digits = list(map(int, reversed(number)))
    for index, digit in enumerate(reverse_digits, start=1):
        if index % 2 == 1:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return str((10 - (total % 10)) % 10)


def generate_valid_meter_number():
    while True:
        base = '41' + ''.join(secrets.choice(string.digits) for _ in range(8))
        meter_number = f"{base}{luhn_checksum_digit(base)}"
        if not User.query.filter_by(meter_number=meter_number).first():
            return meter_number


def is_valid_meter_number(value):
    meter_number = ''.join(ch for ch in (value or '') if ch.isdigit())
    if len(meter_number) != 11:
        return False
    return meter_number[-1] == luhn_checksum_digit(meter_number[:-1])


def ensure_customer_meter_number(user, commit=False):
    changed = False
    if user and user.role == 'customer' and not user.meter_number:
        user.meter_number = generate_valid_meter_number()
        changed = True
    if user and user.role == 'customer' and not user.phone_number:
        user.phone_number = '+2547000000000'
        changed = True
    if changed and commit:
        db.session.commit()
    return user.meter_number if user else None


def split_phone_number(phone_number):
    phone = (phone_number or '').strip()
    for item in PHONE_COUNTRY_CODES:
        code = item['code']
        if phone.startswith(code):
            local_number = ''.join(ch for ch in phone[len(code):] if ch.isdigit())
            return code, local_number
    digits = ''.join(ch for ch in phone if ch.isdigit())
    return '+254', digits[-10:] if digits else '7000000000'


def normalize_phone_number(country_code, phone_number):
    code = (country_code or '+254').strip()
    valid_codes = {item['code'] for item in PHONE_COUNTRY_CODES}
    if code not in valid_codes:
        return None, 'Select a valid country code.'

    digits = ''.join(ch for ch in (phone_number or '') if ch.isdigit())
    if len(digits) != 10:
        return None, 'Phone number must contain exactly 10 digits.'
    return f"{code}{digits}", None


def parse_local_datetime_input(value):
    if not value:
        return datetime.utcnow()
    local_dt = datetime.fromisoformat(value)
    if local_dt.tzinfo is None:
        local_dt = local_dt.replace(tzinfo=APP_TIMEZONE)
    return local_dt.astimezone(UTC).replace(tzinfo=None)


@app.template_filter('local_datetime')
def local_datetime_filter(dt, fmt='%Y-%m-%d %H:%M'):
    local_dt = to_local_time(dt)
    return local_dt.strftime(fmt) if local_dt else ''


@app.template_filter('local_datetime_input')
def local_datetime_input_filter(dt):
    local_dt = to_local_time(dt)
    return local_dt.strftime('%Y-%m-%dT%H:%M') if local_dt else ''


def get_or_create_user_settings(user):
    settings = UserSettings.query.filter_by(user_id=user.id).first()
    if not settings:
        settings = UserSettings(
            user_id=user.id,
            alert_threshold=user.threshold,
        )
        db.session.add(settings)
        db.session.commit()
    ensure_customer_meter_number(user, commit=True)
    return settings


def calculate_reading_cost(user, settings, kwh):
    base_cost = kwh * user.unit_cost
    overage_units = max(0, kwh - user.threshold)
    overage_charge = 0

    if overage_units > 0 and settings.allow_overage:
        overage_charge = overage_units * user.unit_cost * 0.15

    return round(base_cost + overage_charge, 2), round(overage_charge, 2)


def get_latest_kplc_tariff_notice():
    report = Report.query.filter_by(report_type='kplc_tariff').order_by(Report.created_at.desc()).first()
    if not report:
        return None
    payload = {}
    if report.chart_data:
        try:
            payload = json.loads(report.chart_data)
        except json.JSONDecodeError:
            payload = {}
    payload['created_at'] = report.created_at
    payload['content'] = report.content
    payload['title'] = report.title
    return payload


def get_active_unit_cost():
    latest_notice = get_latest_kplc_tariff_notice()
    if latest_notice and latest_notice.get('cost_per_unit') is not None:
        return float(latest_notice['cost_per_unit'])
    admin_user = User.query.filter_by(role='admin').first()
    if admin_user and admin_user.unit_cost is not None:
        return float(admin_user.unit_cost)
    customer = User.query.filter_by(role='customer').first()
    return float(customer.unit_cost) if customer and customer.unit_cost is not None else 0.12


def send_sms_notification(phone_number, message):
    phone = (phone_number or '').strip()
    if not phone:
        return False, 'Customer phone number is not configured.'
    print(f"SMS notification queued for {phone}: {message}")
    return True, None


def get_default_device_profiles():
    return [
        {'name': 'Air Conditioner', 'category': 'Home Appliance', 'watts': 1800.0, 'hours_per_day': 6.0, 'quantity': 1, 'notes': 'High impact cooling load'},
        {'name': 'Water Heater', 'category': 'Home Appliance', 'watts': 3500.0, 'hours_per_day': 1.5, 'quantity': 1, 'notes': 'High impact heating load'},
        {'name': 'Refrigerator', 'category': 'Home Appliance', 'watts': 250.0, 'hours_per_day': 12.0, 'quantity': 1, 'notes': 'Continuous background load'},
        {'name': 'Washing Machine', 'category': 'Home Appliance', 'watts': 850.0, 'hours_per_day': 1.0, 'quantity': 1, 'notes': 'Run only on full loads'},
        {'name': 'Desktop Computers', 'category': 'Office Appliance', 'watts': 120.0, 'hours_per_day': 8.0, 'quantity': 3, 'notes': 'Office equipment baseline'}
    ]


def calculate_device_monthly_kwh(watts, hours_per_day, quantity=1):
    watts = max(float(watts or 0), 0)
    hours_per_day = max(float(hours_per_day or 0), 0)
    quantity = max(int(quantity or 1), 1)
    return round((watts * hours_per_day * quantity * 30) / 1000, 2)


def build_customer_device_prediction(user, devices, current_total_kwh):
    source_devices = []
    using_defaults = not bool(devices)

    if devices:
        for item in devices:
            monthly_kwh = calculate_device_monthly_kwh(item.watts, item.hours_per_day, item.quantity)
            source_devices.append({
                'id': item.id,
                'name': item.name,
                'category': item.category,
                'watts': round(item.watts, 2),
                'hours_per_day': round(item.hours_per_day, 2),
                'quantity': item.quantity,
                'notes': item.notes,
                'monthly_kwh': monthly_kwh,
                'daily_kwh': round(monthly_kwh / 30, 2)
            })
    else:
        for index, item in enumerate(get_default_device_profiles(), start=1):
            monthly_kwh = calculate_device_monthly_kwh(item['watts'], item['hours_per_day'], item['quantity'])
            source_devices.append({
                'id': index,
                'name': item['name'],
                'category': item['category'],
                'watts': round(item['watts'], 2),
                'hours_per_day': round(item['hours_per_day'], 2),
                'quantity': item['quantity'],
                'notes': item['notes'],
                'monthly_kwh': monthly_kwh,
                'daily_kwh': round(monthly_kwh / 30, 2)
            })

    source_devices.sort(key=lambda item: item['monthly_kwh'], reverse=True)
    projected_total = round(sum(item['monthly_kwh'] for item in source_devices), 2)
    top_device = source_devices[0] if source_devices else None
    threshold = max(float(user.threshold or 0), 1.0)
    projected_utilization = round((projected_total / threshold) * 100, 1)
    current_utilization = round((float(current_total_kwh or 0) / threshold) * 100, 1)

    if projected_utilization >= 100:
        recommendation = 'Projected device demand is above your threshold. Reduce the top device runtime or recharge.'
    elif projected_utilization >= 85:
        recommendation = 'Projected demand is close to the threshold. Monitor the top device and shift usage off-peak.'
    else:
        recommendation = 'Projected demand is within threshold. Keep monitoring the heaviest device for sudden changes.'

    return {
        'devices': source_devices,
        'top_device': top_device,
        'projected_total': projected_total,
        'projected_utilization': projected_utilization,
        'current_utilization': current_utilization,
        'using_defaults': using_defaults,
        'recommendation': recommendation
    }


def send_customer_contact_test(user, simulated_total_kwh):
    threshold = float(user.threshold or 0)
    simulated_total_kwh = round(float(simulated_total_kwh or threshold), 2)
    message = (
        f"EcoPulse test notification for {user.username}. "
        f"Usage check: {simulated_total_kwh:.2f} kWh against threshold {threshold:.2f} kWh."
    )
    delivery_notes = []

    if getattr(user, 'alert_email', False) and getattr(user, 'email', None):
        html_body = (
            f"<h2>EcoPulse Threshold Notification Test</h2>"
            f"<p>Dear {user.username},</p>"
            f"<p>This is a test of your registered threshold notification channel.</p>"
            f"<p><strong>Usage:</strong> {simulated_total_kwh:.2f} kWh</p>"
            f"<p><strong>Threshold:</strong> {threshold:.2f} kWh</p>"
        )
        ok, err = send_email_notification(user.email, 'EcoPulse Threshold Notification Test', html_body, message)
        delivery_notes.append('Email sent' if ok else f'Email failed: {err}')
    else:
        delivery_notes.append('Email unavailable')

    if getattr(user, 'phone_number', None):
        ok, err = send_sms_notification(user.phone_number, message)
        delivery_notes.append('SMS queued' if ok else f'SMS failed: {err}')
    else:
        delivery_notes.append('SMS unavailable')

    return delivery_notes


def check_and_send_threshold_notifications(user, current_total_kwh, user_settings):
    """Check consumption levels and send notifications at 80%, 90%, 95%, 100%"""
    threshold = user.threshold
    if threshold <= 0:
        return

    percentage = (current_total_kwh / threshold) * 100
    notifications_sent = []

    # Define notification levels
    levels = [
        (80, '80_percent', '⚠️ 80% Threshold Alert',
         f"You have reached 80% of your monthly threshold. Current usage: {current_total_kwh:.2f} kWh out of {threshold} kWh. {threshold - current_total_kwh:.2f} kWh remaining."),

        (90, '90_percent', '⚠️ 90% Threshold Alert - High Usage',
         f"URGENT: You have reached 90% of your monthly threshold! Current usage: {current_total_kwh:.2f} kWh out of {threshold} kWh. Only {threshold - current_total_kwh:.2f} kWh remaining! Please reduce consumption or recharge."),

        (95, '95_percent', '🔴 95% Threshold Alert - Critical',
         f"CRITICAL: You have reached 95% of your monthly threshold! Current usage: {current_total_kwh:.2f} kWh out of {threshold} kWh. Only {threshold - current_total_kwh:.2f} kWh left! Immediate action required."),

        (100, '100_percent', '🔴 THRESHOLD EXCEEDED - Service Alert',
         f"ALERT: You have exceeded your monthly threshold! Current usage: {current_total_kwh:.2f} kWh. Threshold: {threshold} kWh. Exceeded by: {current_total_kwh - threshold:.2f} kWh. Please recharge immediately to avoid service interruption.")
    ]

    for level_value, level_key, title, message in levels:
        if percentage >= level_value:
            # Check if notification already sent for this level
            notification_flag = getattr(user_settings, f'notification_{level_key}_sent', False)

            if not notification_flag:
                # Mark as sent
                setattr(user_settings, f'notification_{level_key}_sent', True)
                setattr(user_settings, f'last_{level_key}_notification', datetime.utcnow())

                # Create report
                report = Report(
                    title=title,
                    content=f"<p><strong>{title}</strong></p><p>{message}</p><p><strong>Recommendation:</strong> {'Consider recharging your account.' if level_value >= 90 else 'Monitor your usage closely.'}</p>",
                    report_type='threshold_alert',
                    sent_by=user.id,
                    sent_to=user.id
                )
                db.session.add(report)

                # Send email if enabled
                if getattr(user, 'alert_email', False) and getattr(user, 'email', None):
                    html_body = f"""
                    <h2>{title}</h2>
                    <p>Dear {user.username},</p>
                    <p>{message}</p>
                    <hr>
                    <p><strong>Quick Actions:</strong></p>
                    <ul>
                        <li><a href="{url_for('dashboard', _external=True)}">View Dashboard</a></li>
                        <li><a href="{url_for('recharge_energy', _external=True)}">Recharge Now</a></li>
                    </ul>
                    """
                    send_email_notification(user.email, title, html_body)

                if getattr(user, 'phone_number', None):
                    send_sms_notification(user.phone_number, message)

                notifications_sent.append(level_key)

                # Flash message for immediate feedback
                if level_value >= 90:
                    flash(f"{title} - {message}", 'warning')

    if notifications_sent:
        db.session.commit()

    return notifications_sent


def create_sensor_alert_report(customer, reading, exceeded_by, user_settings):
    admin = User.query.filter_by(role='admin').first()
    if not admin:
        return None

    payload = {
        'customer_id': customer.id,
        'customer': customer.username,
        'meter_number': customer.meter_number,
        'reading_id': reading.id,
        'reading_period': reading.date,
        'reading_kwh': round(reading.kwh, 2),
        'threshold': round(customer.threshold, 2),
        'exceeded_by': round(exceeded_by, 2),
        'sensor_name': 'KPLC Smart Threshold Sensor',
        'sensor_status': 'critical' if exceeded_by >= customer.threshold * 0.2 else 'warning',
        'scheduled_shutdown_at': user_settings.scheduled_shutdown_at.isoformat() if user_settings.scheduled_shutdown_at else None
    }
    report = Report(
        title=f"Sensor Alert - {customer.username} exceeded threshold",
        content=(
            f"<p><strong>Customer:</strong> {customer.username}</p>"
            f"<p><strong>Meter:</strong> {customer.meter_number}</p>"
            f"<p><strong>Reading:</strong> {reading.kwh:.2f} kWh for {reading.date}</p>"
            f"<p><strong>Threshold:</strong> {customer.threshold:.2f} kWh</p>"
            f"<p><strong>Exceeded by:</strong> {exceeded_by:.2f} kWh</p>"
        ),
        report_type='sensor_alert',
        sent_by=customer.id,
        sent_to=admin.id,
        chart_data=json.dumps(payload)
    )
    db.session.add(report)
    return report


def build_prediction_payload(years_back=10, years_forward=10):
    years_back = max(1, min(int(years_back), 10))
    years_forward = max(1, min(int(years_forward), 10))
    current_year = datetime.utcnow().year
    readings = Reading.query.all()
    yearly_totals = {}

    for reading in readings:
        year = reading.timestamp.year if reading.timestamp else reading.created_at.year
        yearly_totals[year] = yearly_totals.get(year, 0) + reading.kwh

    if not yearly_totals:
        baseline = 4800.0
        yearly_totals[current_year] = baseline

    known_years = sorted(yearly_totals.keys())
    known_values = np.array([yearly_totals[year] for year in known_years], dtype=float)

    if len(known_years) > 1:
        coefficients = np.polyfit(np.array(known_years, dtype=float), known_values, 1)
        slope = float(coefficients[0])
        intercept = float(coefficients[1])
    else:
        slope = known_values[0] * 0.03
        intercept = float(known_values[0] - slope * known_years[0])

    timeline = []
    start_year = current_year - years_back
    end_year = current_year + years_forward
    actual_total = yearly_totals.get(current_year, max(known_values[-1], 1))

    for year in range(start_year, end_year + 1):
        if year in yearly_totals:
            value = yearly_totals[year]
            series_type = 'actual'
        else:
            value = max(0.0, slope * year + intercept)
            series_type = 'projected' if year > current_year else 'backcast'

        timeline.append({
            'year': year,
            'value': round(float(value), 2),
            'type': series_type
        })

    projected = [item['value'] for item in timeline if item['year'] > current_year]
    previous = [item['value'] for item in timeline if item['year'] < current_year]
    next_average = sum(projected) / len(projected) if projected else actual_total
    previous_average = sum(previous) / len(previous) if previous else actual_total
    growth_rate = ((next_average - actual_total) / actual_total * 100) if actual_total else 0

    fig = plt.figure(figsize=(12, 5))
    ax = plt.subplot(1, 1, 1)
    x_years = [item['year'] for item in timeline]
    y_values = [item['value'] for item in timeline]
    colors = ['#0f766e' if item['type'] == 'actual' else '#f59e0b' if item['type'] == 'backcast' else '#2563eb'
              for item in timeline]

    ax.bar(x_years, y_values, color=colors, alpha=0.85)
    ax.axvline(current_year + 0.5, color='#1f2937', linestyle='--', linewidth=1.5)
    ax.set_title(f'{years_back}-Year Backcast and {years_forward}-Year Forecast', fontweight='bold')
    ax.set_xlabel('Year')
    ax.set_ylabel('Estimated Consumption (kWh)')
    ax.grid(True, alpha=0.25, axis='y')

    img_bytes = io.BytesIO()
    plt.tight_layout()
    plt.savefig(img_bytes, format='png', dpi=110, bbox_inches='tight')
    img_bytes.seek(0)
    plt.close(fig)

    return {
        'timeline': timeline,
        'chart': base64.b64encode(img_bytes.getvalue()).decode(),
        'summary': {
            'current_year': current_year,
            'current_total': round(actual_total, 2),
            'previous_average': round(previous_average, 2),
            'next_average': round(next_average, 2),
            'growth_rate': round(growth_rate, 2),
            'years_back': years_back,
            'years_forward': years_forward
        }
    }


def build_customer_meter_status(readings, user, user_settings, customer_invoices):
    latest = max(readings, key=lambda item: item.timestamp or item.created_at) if readings else None
    latest_kwh = latest.kwh if latest else 0
    threshold = max(user.threshold or 0, 1)
    utilization = min(160, round((latest_kwh / threshold) * 100, 1)) if latest else 0
    open_balance = sum(max(0, invoice.balance or 0) for invoice in customer_invoices)
    verification_ratio = 0
    if readings:
        verified_count = len([reading for reading in readings if reading.is_reviewed or reading.is_approved])
        verification_ratio = round((verified_count / len(readings)) * 100, 1)
    state = 'Stable'
    if latest and latest_kwh > threshold:
        state = 'Alert'
    elif latest and latest_kwh > threshold * 0.85:
        state = 'Watch'

    return {
        'title': 'Home Smart Meter',
        'status': state,
        'reading_value': f"{latest_kwh:.1f} kWh",
        'reading_label': 'Latest household reading',
        'ring_value': utilization,
        'ring_label': 'Threshold usage',
        'support_value': f"{verification_ratio:.0f}%",
        'support_label': 'Verified readings',
        'detail_primary': f"Open balance: {user.currency} {open_balance:.2f}",
        'detail_secondary': 'Protection mode active' if not user_settings.allow_overage else 'Overage billing active'
    }


def build_examiner_meter_status(consumption_stats, pending_readings, reviewed_readings):
    total_readings = max(consumption_stats.get('total_readings', 0), 1)
    review_ratio = round((consumption_stats.get('reviewed_count', 0) / total_readings) * 100, 1)
    state = 'Clear'
    if len(pending_readings) > 10:
        state = 'Busy'
    if len(pending_readings) > 25:
        state = 'Critical'

    return {
        'title': 'Examiner Smart Meter',
        'status': state,
        'reading_value': f"{consumption_stats.get('total_consumption', 0):.0f} kWh",
        'reading_label': 'Observed network load',
        'ring_value': review_ratio,
        'ring_label': 'Review completion',
        'support_value': f"{len(reviewed_readings)}",
        'support_label': 'Ready for admin',
        'detail_primary': f"Pending queue: {len(pending_readings)} reading(s)",
        'detail_secondary': f"Active customers monitored: {consumption_stats.get('total_customers', 0)}"
    }


def build_admin_meter_status(financial, pending_reviews, financial_records):
    payment_rate = round(financial.get('payment_rate', 0), 1)
    portfolio_size = len(financial_records)
    state = 'Stable'
    if financial.get('total_outstanding', 0) > financial.get('total_collected', 0):
        state = 'Attention'
    if len(pending_reviews) > 10:
        state = 'Busy'

    return {
        'title': 'Admin Smart Meter',
        'status': state,
        'reading_value': f"Ksh {financial.get('total_revenue', 0):,.0f}",
        'reading_label': 'Portfolio throughput',
        'ring_value': payment_rate,
        'ring_label': 'Collection rate',
        'support_value': f"{len(pending_reviews)}",
        'support_label': 'Awaiting approval',
        'detail_primary': f"Outstanding: Ksh {financial.get('total_outstanding', 0):,.2f}",
        'detail_secondary': f"Tracked customer records: {portfolio_size}"
    }


def build_yearly_consumption_series():
    yearly_totals = {}
    for reading in Reading.query.all():
        year = reading.timestamp.year if reading.timestamp else reading.created_at.year
        yearly_totals[year] = yearly_totals.get(year, 0.0) + reading.kwh
    return yearly_totals


def evaluate_forecast_model(yearly_totals):
    if len(yearly_totals) < 2:
        return {
            'model_name': 'Linear regression trend model',
            'years_evaluated': 0,
            'mae': None,
            'rmse': None,
            'mape': None,
            'predictions': []
        }

    sorted_years = sorted(yearly_totals.keys())
    predictions = []

    for index in range(1, len(sorted_years)):
        train_years = np.array(sorted_years[:index], dtype=float)
        train_values = np.array([yearly_totals[year] for year in sorted_years[:index]], dtype=float)
        target_year = sorted_years[index]
        actual_value = float(yearly_totals[target_year])

        if len(train_years) > 1:
            slope, intercept = np.polyfit(train_years, train_values, 1)
            predicted_value = float(slope * target_year + intercept)
        else:
            predicted_value = float(train_values[0])

        error = predicted_value - actual_value
        abs_pct = abs(error) / actual_value * 100 if actual_value else 0.0
        predictions.append({
            'year': target_year,
            'actual': round(actual_value, 2),
            'predicted': round(predicted_value, 2),
            'absolute_error': round(abs(error), 2),
            'absolute_percentage_error': round(abs_pct, 2)
        })

    mae = sum(item['absolute_error'] for item in predictions) / len(predictions)
    rmse = math.sqrt(
        sum((item['predicted'] - item['actual']) ** 2 for item in predictions) / len(predictions)
    )
    mape = sum(item['absolute_percentage_error'] for item in predictions) / len(predictions)

    return {
        'model_name': 'Linear regression trend model',
        'years_evaluated': len(predictions),
        'mae': round(mae, 2),
        'rmse': round(rmse, 2),
        'mape': round(mape, 2),
        'predictions': predictions
    }


def infer_customer_priority(customer, latest_reading, latest_invoice):
    excess = max(0.0, latest_reading.kwh - customer.threshold) if latest_reading else 0.0
    balance = latest_invoice.balance if latest_invoice else 0.0
    due_date = None
    if latest_invoice and latest_invoice.due_date:
        due_date = (
            latest_invoice.due_date.date()
            if isinstance(latest_invoice.due_date, datetime)
            else latest_invoice.due_date
        )
    overdue = bool(due_date and due_date < datetime.utcnow().date())
    settings = UserSettings.query.filter_by(user_id=customer.id).first()
    protect_mode = bool(settings and not settings.allow_overage)

    fired_rules = []
    risk = 'Low'
    advice = 'Maintain current monitoring and continue monthly submissions.'

    if excess > 0:
        fired_rules.append('R1: Over-threshold usage indicates intervention is needed.')
        risk = 'Medium'
        advice = 'Send efficiency guidance and review the latest meter reading.'
    if excess > customer.threshold * 0.15:
        fired_rules.append('R2: Large threshold breach elevates customer risk.')
        risk = 'High'
        advice = 'Schedule an energy audit and verify abnormal appliance demand.'
    if overdue or balance > 0:
        fired_rules.append('R3: Outstanding balance requires billing follow-up.')
        if risk == 'Low':
            risk = 'Medium'
        advice = 'Pair usage advice with invoice follow-up and payment reminders.'
    if protect_mode and excess > 0:
        fired_rules.append('R4: Protect mode with overuse needs immediate action.')
        risk = 'Critical'
        advice = 'Escalate immediately and review shutdown or alert handling.'

    return {
        'customer': customer.username,
        'latest_period': latest_reading.date if latest_reading else 'No readings',
        'latest_kwh': round(latest_reading.kwh, 2) if latest_reading else 0.0,
        'threshold': round(customer.threshold, 2),
        'excess_kwh': round(excess, 2),
        'balance': round(balance, 2),
        'risk': risk,
        'advice': advice,
        'fired_rules': fired_rules or ['R0: No critical condition triggered.']
    }


def build_reasoning_snapshot():
    customers = User.query.filter_by(role='customer').all()
    snapshot = []

    for customer in customers:
        latest_reading = Reading.query.filter_by(user_id=customer.id) \
            .order_by(Reading.timestamp.desc(), Reading.created_at.desc()) \
            .first()
        latest_invoice = FinancialRecord.query.filter_by(user_id=customer.id) \
            .order_by(FinancialRecord.created_at.desc()) \
            .first()
        if latest_reading or latest_invoice:
            snapshot.append(infer_customer_priority(customer, latest_reading, latest_invoice))

    if not snapshot:
        snapshot.append({
            'customer': 'Sample customer',
            'latest_period': 'No readings',
            'latest_kwh': 720.0,
            'threshold': 600.0,
            'excess_kwh': 120.0,
            'balance': 0.0,
            'risk': 'High',
            'advice': 'Schedule an audit and review abnormal appliance demand.',
            'fired_rules': [
                'R1: Over-threshold usage indicates intervention is needed.',
                'R2: Large threshold breach elevates customer risk.'
            ]
        })

    risk_order = {'Critical': 0, 'High': 1, 'Medium': 2, 'Low': 3}
    snapshot.sort(key=lambda item: (risk_order.get(item['risk'], 9), -item['excess_kwh'], -item['balance']))
    return snapshot


def build_search_case():
    reasoning_snapshot = build_reasoning_snapshot()
    candidate = next((item for item in reasoning_snapshot if item['excess_kwh'] > 0), reasoning_snapshot[0])
    excess = max(candidate['excess_kwh'], 120.0 if candidate['excess_kwh'] <= 0 else candidate['excess_kwh'])
    return {
        'customer': candidate['customer'],
        'start_excess': int(math.ceil(excess)),
        'target_excess': 0
    }


def get_search_actions():
    return [
        {'name': 'Send efficiency tips', 'reduction': 35, 'cost': 1},
        {'name': 'Off-peak scheduling advice', 'reduction': 45, 'cost': 2},
        {'name': 'Remote audit', 'reduction': 60, 'cost': 3},
        {'name': 'Protect-mode tuning', 'reduction': 80, 'cost': 4},
        {'name': 'Technician inspection', 'reduction': 110, 'cost': 5}
    ]


def run_bfs_search(start_excess, actions):
    queue = deque([(start_excess, [], 0)])
    visited = {start_excess}
    explored = 0

    while queue:
        state, path, cost = queue.popleft()
        explored += 1
        if state <= 0:
            return {'path': path, 'cost': cost, 'explored': explored}

        for action in actions:
            next_state = max(0, state - action['reduction'])
            if next_state not in visited:
                visited.add(next_state)
                queue.append((next_state, path + [action], cost + action['cost']))

    return {'path': [], 'cost': 0, 'explored': explored}


def run_astar_search(start_excess, actions):
    max_reduction = max(action['reduction'] for action in actions)

    def heuristic(state):
        return math.ceil(state / max_reduction) if state > 0 else 0

    frontier = [(heuristic(start_excess), 0, start_excess, [])]
    best_cost = {start_excess: 0}
    explored = 0

    while frontier:
        _, cost, state, path = heapq.heappop(frontier)
        explored += 1
        if state <= 0:
            return {'path': path, 'cost': cost, 'explored': explored}

        for action in actions:
            next_state = max(0, state - action['reduction'])
            next_cost = cost + action['cost']
            if next_cost < best_cost.get(next_state, float('inf')):
                best_cost[next_state] = next_cost
                priority = next_cost + heuristic(next_state)
                heapq.heappush(frontier, (priority, next_cost, next_state, path + [action]))

    return {'path': [], 'cost': 0, 'explored': explored}


def build_search_report():
    case = build_search_case()
    actions = get_search_actions()
    bfs_result = run_bfs_search(case['start_excess'], actions)
    astar_result = run_astar_search(case['start_excess'], actions)

    return {
        'problem': case,
        'actions': actions,
        'bfs': bfs_result,
        'astar': astar_result,
        'comparison': [
            {
                'algorithm': 'BFS',
                'path_length': len(bfs_result['path']),
                'solution_cost': bfs_result['cost'],
                'states_explored': bfs_result['explored'],
                'solution': ' -> '.join(action['name'] for action in bfs_result['path']) or 'No solution'
            },
            {
                'algorithm': 'A*',
                'path_length': len(astar_result['path']),
                'solution_cost': astar_result['cost'],
                'states_explored': astar_result['explored'],
                'solution': ' -> '.join(action['name'] for action in astar_result['path']) or 'No solution'
            }
        ]
    }


def generate_ai_comparison_chart(search_report, forecast_eval):
    fig = plt.figure(figsize=(12, 5))

    ax1 = plt.subplot(1, 2, 1)
    algorithms = [item['algorithm'] for item in search_report['comparison']]
    explored = [item['states_explored'] for item in search_report['comparison']]
    ax1.bar(algorithms, explored, color=['#0f766e', '#1d4ed8'])
    ax1.set_title('Search Efficiency')
    ax1.set_ylabel('States Explored')

    ax2 = plt.subplot(1, 2, 2)
    if forecast_eval['predictions']:
        years = [item['year'] for item in forecast_eval['predictions']]
        actual = [item['actual'] for item in forecast_eval['predictions']]
        predicted = [item['predicted'] for item in forecast_eval['predictions']]
        ax2.plot(years, actual, marker='o', linewidth=2, label='Actual', color='#111827')
        ax2.plot(years, predicted, marker='s', linewidth=2, label='Predicted', color='#f59e0b')
        ax2.set_title('Forecast Evaluation')
        ax2.set_xlabel('Year')
        ax2.set_ylabel('kWh')
        ax2.legend()
        ax2.grid(True, alpha=0.25)
    else:
        ax2.text(0.5, 0.5, 'Not enough yearly data for\nforecast evaluation', ha='center', va='center')
        ax2.set_axis_off()

    img_bytes = io.BytesIO()
    plt.tight_layout()
    plt.savefig(img_bytes, format='png', dpi=110, bbox_inches='tight')
    img_bytes.seek(0)
    plt.close(fig)
    return base64.b64encode(img_bytes.getvalue()).decode()


def build_ai_course_report():
    yearly_totals = build_yearly_consumption_series()
    forecast_eval = evaluate_forecast_model(yearly_totals)
    reasoning_snapshot = build_reasoning_snapshot()
    search_report = build_search_report()
    visualization = generate_ai_comparison_chart(search_report, forecast_eval)

    return {
        'problem_statement': (
            'EcoPulse needs an intelligent way to identify risky energy-consumption cases and choose efficient actions '
            'that bring customers back toward threshold-compliant usage.'
        ),
        'agent': {
            'name': 'EcoPulse Energy Response Agent',
            'type': 'Goal-based, model-based agent',
            'justification': (
                'The agent keeps an internal view of customer usage, thresholds, balances, and forecast trends, '
                'then plans actions that minimize excess consumption while preserving operational efficiency.'
            ),
            'peas': {
                'Performance': 'Reduce threshold violations, minimize explored states, improve forecast accuracy, and prioritize correct risk alerts.',
                'Environment': 'Energy dashboard with customer readings, invoices, thresholds, and operational review workflows.',
                'Actuators': 'Send alerts, recommend audits, adjust protect-mode actions, generate invoices, and trigger staff follow-up.',
                'Sensors': 'Meter readings, threshold settings, timestamps, invoice balances, review status, and yearly consumption totals.'
            }
        },
        'search': search_report,
        'reasoning': reasoning_snapshot,
        'ml': forecast_eval,
        'visualization': visualization
    }


def answer_public_assistant(question):
    prompt = (question or '').strip().lower()
    if not prompt:
        return "Ask about services, billing workflow, account setup, thresholds, reports, support, privacy, or AI forecasting."

    responses = {
        'service': "EcoPulse offers smart monitoring, consumption analytics, billing support, AI forecasting, and threshold alerts for homes and businesses.",
        'career': "EcoPulse is hiring IoT engineers, data analysts, and sustainability consultants, and it also offers internship opportunities for students interested in green tech.",
        'about': "EcoPulse is an energy management platform for customers, examiners, and admins. It tracks readings, estimates costs, and highlights efficiency opportunities.",
        'news': "EcoPulse news covers product launches, green energy partnerships, industry insights, and practical energy-saving tips.",
        'workflow': "Customers register, add readings, and submit summaries. Examiners review readings and compile reports. Admins approve reviews, manage finances, and send summaries back to customers.",
        'device': "EcoPulse supports IoT device integration for appliances, sensors, and meters so users can monitor energy use more effectively.",
        'community': "EcoPulse community features focus on shared sustainability tips, user stories, and practical guidance for reducing waste.",
        'contact': "You can reach EcoPulse through the contact page, email `support@ecopulse.local`, or the map section on the homepage.",
        'threshold': "Customers can set a threshold in Settings. If overage is allowed, extra units are billed with an overage charge. If overage is off, alerts are raised and an auto-shutdown can be scheduled after 5 minutes.",
        'login': "Customers use the public login page. Staff sign in through the hidden staff login route `/staff/login`.",
        'register': "Public registration creates customer accounts only. Admin and examiner accounts are generated automatically for testing.",
        'ai': "EcoPulse AI provides a public assistant on the homepage and 10-year backcast/forecast charts on the admin and examiner dashboards.",
        'privacy': "Privacy and terms are available from the footer. They explain data usage, consent, system monitoring, and billing records.",
        'map': "The homepage includes an embedded map in the contact section to help customers find the EcoPulse office."
    }

    for keyword, response in responses.items():
        if keyword in prompt:
            return response

    return "I can help with EcoPulse services, customer registration, billing workflow, threshold alerts, support contacts, privacy, and AI forecasting."


def answer_staff_assistant(question, role, prediction=None):
    prompt = (question or '').strip().lower()
    prediction = prediction or build_prediction_payload()
    summary = prediction['summary']
    readings = Reading.query.all()
    customers = User.query.filter_by(role='customer').all()
    financial_records = FinancialRecord.query.all()
    pending_reviews = Reading.query.filter_by(is_reviewed=False).count()
    outstanding = sum(record.balance for record in financial_records if record.balance > 0)
    total_customers = len([customer for customer in customers if customer.readings])

    if not prompt:
        return (
            f"I can help with {role} forecasting, invoice guidance, efficiency suggestions, "
            "risk spotting, and customer advice."
        )

    if any(keyword in prompt for keyword in ['future', 'forecast', 'predict', 'prediction']):
        return (
            f"The current forecast projects an average of {summary['next_average']:.2f} kWh over the next 10 years, "
            f"compared with a current total of {summary['current_total']:.2f} kWh and a growth rate of "
            f"{summary['growth_rate']:.2f}%. "
            f"Advice: prioritize customers with rising usage, review threshold exceptions, and watch seasonal spikes."
        )

    if any(keyword in prompt for keyword in ['suggest', 'suggestion', 'improve', 'efficiency', 'save']):
        if pending_reviews > 0:
            return (
                f"There are {pending_reviews} pending readings waiting for review. "
                "Suggestion: clear pending reviews first, then focus on customers with high consumption and unpaid balances "
                "to improve both efficiency and response time."
            )
        return (
            f"Usage is currently spread across {total_customers} active customers. "
            "Suggestion: compare high-usage customers against thresholds, encourage device audits, and issue targeted advice "
            "for off-peak consumption and appliance optimization."
        )

    if any(keyword in prompt for keyword in ['advice', 'recommend', 'risk', 'issue']):
        if role == 'admin':
            return (
                f"Outstanding customer balances currently total {outstanding:.2f}. "
                "Advice: follow up on overdue invoices, approve only well-supported examiner reviews, and use the forecast trend "
                "to plan revenue, support capacity, and customer communication."
            )
        return (
            f"System-wide consumption is {sum(reading.kwh for reading in readings):.2f} kWh across reviewed and pending records. "
            "Advice: investigate abnormal usage swings, annotate reviews with corrective actions, and send invoices promptly to keep customers informed."
        )

    if any(keyword in prompt for keyword in ['invoice', 'billing', 'customer']):
        return (
            "You can create invoices from the examiner dashboard for individual customers. "
            "Use the latest consumption totals, set a due date, and keep the balance aligned with the issued amount so the customer dashboard updates immediately."
        )

    return (
        f"Current forecast growth is {summary['growth_rate']:.2f}% with {pending_reviews} pending reviews and "
        f"{outstanding:.2f} in outstanding balances. "
        "Use that as the baseline for planning, customer follow-up, and efficiency advice."
    )


def generate_role_test_credentials(role):
    return f"{role}_demo", f"{role.capitalize()}!EcoPulse2026"


def ensure_test_user(role, email, department=None):
    username, password = generate_role_test_credentials(role)
    user = User.query.filter_by(username=username).first()
    if user:
        settings = get_or_create_user_settings(user)
        ensure_customer_meter_number(user, commit=True)
        return user, password, settings

    user = User(
        username=username,
        email=email,
        role=role,
        department=department
    )
    user.set_password(password)
    if role in ['admin', 'examiner']:
        user.employee_id = user.generate_employee_id()
    else:
        user.meter_number = generate_valid_meter_number()
        user.phone_number = '+2547000000000'
    db.session.add(user)
    db.session.flush()
    settings = UserSettings(user_id=user.id, alert_threshold=user.threshold)
    db.session.add(settings)
    db.session.commit()
    return user, password, settings


def send_email_notification(to_email, subject, html_body, text_body=None):
    """
    Send a real email using SMTP.
    Returns: (success: bool, error_message: str | None)
    """
    try:
        smtp_host = app.config.get('SMTP_HOST', '')
        smtp_from = app.config.get('SMTP_FROM', '')
        if not smtp_host or not smtp_from:
            return False, "SMTP is not configured (missing SMTP_HOST or SMTP_FROM)."

        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = smtp_from
        msg['To'] = to_email

        # Include plain text fallback too.
        plain = text_body if text_body is not None else "Please view this email in an HTML-capable client."
        msg.attach(MIMEText(plain, 'plain', 'utf-8'))
        msg.attach(MIMEText(html_body, 'html', 'utf-8'))

        server = smtplib.SMTP(smtp_host, app.config.get('SMTP_PORT', 587), timeout=20)
        try:
            if app.config.get('SMTP_USE_TLS', True):
                server.starttls()

            smtp_username = app.config.get('SMTP_USERNAME', '')
            smtp_password = app.config.get('SMTP_PASSWORD', '')
            if smtp_username and smtp_password:
                server.login(smtp_username, smtp_password)

            server.sendmail(smtp_from, [to_email], msg.as_string())
        finally:
            server.quit()

        return True, None
    except Exception as e:
        return False, str(e)


def generate_consumption_chart(user_id):
    """Generate consumption chart for customer view"""
    try:
        readings = Reading.query.filter_by(user_id=user_id).order_by(Reading.created_at).all()
        user = User.query.get(user_id)
        if not readings or not user:
            return None

        # Prepare data
        dates = [r.date for r in readings[-12:]]
        values = [r.kwh for r in readings[-12:]]

        if not dates:
            return None

        fig = plt.figure(figsize=(14, 10))

        # Main consumption chart
        ax1 = plt.subplot(2, 2, 1)
        colors = ['#00b894' if v <= user.threshold else '#ff6b6b' for v in values]
        bars = ax1.bar(range(len(dates)), values, color=colors, edgecolor='black', linewidth=1.5)
        ax1.set_xlabel("Period", fontsize=12)
        ax1.set_ylabel("Consumption (kWh)", fontsize=12)
        ax1.set_title(f"Energy Consumption - {user.username}", fontsize=14, fontweight='bold')
        ax1.set_xticks(range(len(dates)))
        ax1.set_xticklabels(dates, rotation=45, ha='right')
        ax1.axhline(y=user.threshold, color="#ff6b6b", linestyle="--", linewidth=2,
                    label=f"Threshold: {user.threshold} kWh")
        ax1.legend()
        ax1.grid(True, alpha=0.3)

        for bar, v in zip(bars, values):
            height = bar.get_height()
            ax1.text(bar.get_x() + bar.get_width() / 2., height + 5, f'{v:.0f}',
                     ha='center', va='bottom', fontsize=9)

        # Trend line
        ax2 = plt.subplot(2, 2, 2)
        ax2.plot(range(len(dates)), values, marker='o', linewidth=2, color='#667eea', markersize=8)
        ax2.fill_between(range(len(dates)), values, alpha=0.3, color='#667eea')
        ax2.set_xlabel("Period", fontsize=12)
        ax2.set_ylabel("Consumption (kWh)", fontsize=12)
        ax2.set_title("Consumption Trend", fontsize=14, fontweight='bold')
        ax2.set_xticks(range(len(dates)))
        ax2.set_xticklabels(dates, rotation=45, ha='right')
        ax2.grid(True, alpha=0.3)

        # Cost analysis
        ax3 = plt.subplot(2, 2, 3)
        costs = [v * user.unit_cost for v in values]
        ax3.plot(range(len(dates)), costs, marker='s', linewidth=2, color='#00b894', markersize=8)
        ax3.fill_between(range(len(dates)), costs, alpha=0.3, color='#00b894')
        ax3.set_xlabel("Period", fontsize=12)
        ax3.set_ylabel(f"Cost ({user.currency})", fontsize=12)
        ax3.set_title("Cost Analysis", fontsize=14, fontweight='bold')
        ax3.set_xticks(range(len(dates)))
        ax3.set_xticklabels(dates, rotation=45, ha='right')
        ax3.grid(True, alpha=0.3)

        # CO2 emissions
        ax4 = plt.subplot(2, 2, 4)
        co2 = [v * 0.385 for v in values]
        ax4.bar(range(len(dates)), co2, color='#95a5a6', edgecolor='black', alpha=0.7)
        ax4.set_xlabel("Period", fontsize=12)
        ax4.set_ylabel("CO2 (kg)", fontsize=12)
        ax4.set_title("Carbon Footprint", fontsize=14, fontweight='bold')
        ax4.set_xticks(range(len(dates)))
        ax4.set_xticklabels(dates, rotation=45, ha='right')
        ax4.grid(True, alpha=0.3)

        plt.tight_layout()

        img_bytes = io.BytesIO()
        plt.savefig(img_bytes, format='png', dpi=100, bbox_inches='tight')
        img_bytes.seek(0)
        plt.close()

        img_base64 = base64.b64encode(img_bytes.getvalue()).decode()
        return img_base64

    except Exception as e:
        print(f"Chart error: {e}")
        plt.close('all')
        return None


def generate_examiner_consumption_report():
    """Generate consumption report for examiner showing all customers' consumption"""
    try:
        users = User.query.filter_by(role='customer').all()
        readings = Reading.query.all()

        if not readings:
            return {
                'chart': None,
                'summary': {
                    'total_customers': len(users),
                    'total_readings': 0,
                    'total_consumption': 0,
                    'average_consumption': 0,
                    'peak_consumption': 0,
                    'total_revenue': 0,
                    'total_co2': 0
                }
            }

        fig = plt.figure(figsize=(18, 12))

        # 1. Consumption by customer (bar chart)
        ax1 = plt.subplot(3, 3, 1)
        customer_consumption = {}
        for user in users:
            user_readings = Reading.query.filter_by(user_id=user.id).all()
            if user_readings:
                customer_consumption[user.username] = sum(r.kwh for r in user_readings)

        if customer_consumption:
            customers = list(customer_consumption.keys())
            consumption = list(customer_consumption.values())
            colors = plt.cm.viridis(np.linspace(0, 1, len(customers)))
            ax1.bar(range(len(customers)), consumption, color=colors)
            ax1.set_xlabel("Customers", fontsize=10)
            ax1.set_ylabel("Consumption (kWh)", fontsize=10)
            ax1.set_title("Customer Consumption Distribution", fontsize=12, fontweight='bold')
            ax1.set_xticks(range(len(customers)))
            ax1.set_xticklabels(customers, rotation=45, ha='right')
            ax1.grid(True, alpha=0.3)
        else:
            ax1.text(0.5, 0.5, 'No consumption data', ha='center', va='center', transform=ax1.transAxes)

        # 2. Monthly consumption trend
        ax2 = plt.subplot(3, 3, 2)
        monthly_data = {}
        for reading in readings:
            month_key = reading.created_at.strftime('%Y-%m')
            if month_key not in monthly_data:
                monthly_data[month_key] = 0
            monthly_data[month_key] += reading.kwh

        months = sorted(monthly_data.keys())
        monthly_totals = [monthly_data[m] for m in months]

        if months:
            ax2.plot(range(len(months)), monthly_totals, marker='o', linewidth=2, color='#ff6b6b')
            ax2.fill_between(range(len(months)), monthly_totals, alpha=0.3, color='#ff6b6b')
            ax2.set_xlabel("Month", fontsize=10)
            ax2.set_ylabel("Total Consumption (kWh)", fontsize=10)
            ax2.set_title("Monthly Consumption Trend", fontsize=12, fontweight='bold')
            ax2.set_xticks(range(len(months)))
            ax2.set_xticklabels(months, rotation=45, ha='right')
            ax2.grid(True, alpha=0.3)
        else:
            ax2.text(0.5, 0.5, 'No monthly data', ha='center', va='center', transform=ax2.transAxes)

        # 3. Peak consumption hours
        ax3 = plt.subplot(3, 3, 3)
        hour_data = [0] * 24
        for reading in readings:
            hour = reading.timestamp.hour
            hour_data[hour] += reading.kwh

        hours = list(range(24))
        ax3.bar(hours, hour_data, color='#9b59b6', edgecolor='black', alpha=0.7)
        ax3.set_xlabel("Hour of Day", fontsize=10)
        ax3.set_ylabel("Consumption (kWh)", fontsize=10)
        ax3.set_title("Peak Consumption Hours", fontsize=12, fontweight='bold')
        ax3.set_xticks(range(0, 24, 3))
        ax3.grid(True, alpha=0.3)

        # 4. Customer efficiency rating
        ax4 = plt.subplot(3, 3, 4)
        efficient = 0
        average = 0
        inefficient = 0

        for user in users:
            user_readings = Reading.query.filter_by(user_id=user.id).all()
            if user_readings:
                avg_consumption = sum(r.kwh for r in user_readings) / len(user_readings)
                if avg_consumption < user.threshold * 0.7:
                    efficient += 1
                elif avg_consumption < user.threshold:
                    average += 1
                else:
                    inefficient += 1

        efficiency_data = [efficient, average, inefficient]
        efficiency_labels = ['Efficient', 'Average', 'Inefficient']
        colors_efficiency = ['#00b894', '#f39c12', '#ff6b6b']
        ax4.pie(efficiency_data, labels=efficiency_labels, autopct='%1.1f%%', colors=colors_efficiency, startangle=90)
        ax4.set_title("Customer Efficiency Distribution", fontsize=12, fontweight='bold')

        # 5. Cost analysis by customer
        ax5 = plt.subplot(3, 3, 5)
        customer_costs = {}
        for user in users:
            user_readings = Reading.query.filter_by(user_id=user.id).all()
            if user_readings:
                customer_costs[user.username] = sum(r.kwh * user.unit_cost for r in user_readings)

        if customer_costs:
            top_customers = dict(sorted(customer_costs.items(), key=lambda x: x[1], reverse=True)[:5])
            ax5.barh(list(top_customers.keys()), list(top_customers.values()), color='#00b894')
            ax5.set_xlabel("Cost", fontsize=10)
            ax5.set_title("Top 5 Customers by Cost", fontsize=12, fontweight='bold')
            ax5.grid(True, alpha=0.3)
        else:
            ax5.text(0.5, 0.5, 'No cost data', ha='center', va='center', transform=ax5.transAxes)

        # 6. CO2 emissions by customer
        ax6 = plt.subplot(3, 3, 6)
        customer_co2 = {}
        for user in users:
            user_readings = Reading.query.filter_by(user_id=user.id).all()
            if user_readings:
                customer_co2[user.username] = sum(r.kwh * 0.385 for r in user_readings)

        if customer_co2:
            top_co2 = dict(sorted(customer_co2.items(), key=lambda x: x[1], reverse=True)[:5])
            ax6.bar(range(len(top_co2)), list(top_co2.values()), color='#95a5a6')
            ax6.set_xlabel("Customers", fontsize=10)
            ax6.set_ylabel("CO2 (kg)", fontsize=10)
            ax6.set_title("Top 5 Customers by CO2", fontsize=12, fontweight='bold')
            ax6.set_xticks(range(len(top_co2)))
            ax6.set_xticklabels(list(top_co2.keys()), rotation=45, ha='right')
            ax6.grid(True, alpha=0.3)
        else:
            ax6.text(0.5, 0.5, 'No CO2 data', ha='center', va='center', transform=ax6.transAxes)

        # 7. Readings per customer
        ax7 = plt.subplot(3, 3, 7)
        readings_count = {}
        for user in users:
            count = Reading.query.filter_by(user_id=user.id).count()
            if count > 0:
                readings_count[user.username] = count

        if readings_count:
            ax7.bar(range(len(readings_count)), list(readings_count.values()), color='#3498db')
            ax7.set_xlabel("Customers", fontsize=10)
            ax7.set_ylabel("Number of Readings", fontsize=10)
            ax7.set_title("Readings per Customer", fontsize=12, fontweight='bold')
            ax7.set_xticks(range(len(readings_count)))
            ax7.set_xticklabels(list(readings_count.keys()), rotation=45, ha='right')
            ax7.grid(True, alpha=0.3)
        else:
            ax7.text(0.5, 0.5, 'No readings data', ha='center', va='center', transform=ax7.transAxes)

        # 8. Consumption vs Threshold
        ax8 = plt.subplot(3, 3, 8)
        above_threshold = 0
        below_threshold = 0

        for reading in readings:
            user = User.query.get(reading.user_id)
            if user:
                if reading.kwh > user.threshold:
                    above_threshold += 1
                else:
                    below_threshold += 1

        ax8.pie([above_threshold, below_threshold], labels=['Above Threshold', 'Below Threshold'],
                autopct='%1.1f%%', colors=['#ff6b6b', '#00b894'], startangle=90)
        ax8.set_title("Readings vs Threshold", fontsize=12, fontweight='bold')

        # 9. Summary statistics
        ax9 = plt.subplot(3, 3, 9)
        total_consumption = sum(r.kwh for r in readings)
        total_customers = len([u for u in users if u.readings])
        avg_consumption = total_consumption / total_customers if total_customers > 0 else 0
        peak_consumption = max(monthly_totals) if monthly_totals else 0

        summary_data = ['Total\nConsumption', 'Avg per\nCustomer', 'Peak\nMonthly']
        summary_values = [total_consumption, avg_consumption, peak_consumption]
        ax9.bar(summary_data, summary_values, color=['#3498db', '#00b894', '#ff6b6b'])
        ax9.set_ylabel("kWh", fontsize=10)
        ax9.set_title("Key Metrics", fontsize=12, fontweight='bold')

        for i, v in enumerate(summary_values):
            ax9.text(i, v + 5, f'{v:.0f}', ha='center', va='bottom', fontsize=9)

        plt.tight_layout()

        img_bytes = io.BytesIO()
        plt.savefig(img_bytes, format='png', dpi=100, bbox_inches='tight')
        img_bytes.seek(0)
        plt.close()

        img_base64 = base64.b64encode(img_bytes.getvalue()).decode()

        # Calculate summary statistics
        total_consumption = sum(r.kwh for r in readings)
        total_customers = len([u for u in users if u.readings])
        avg_consumption = total_consumption / total_customers if total_customers > 0 else 0
        peak_consumption = max(monthly_totals) if monthly_totals else 0
        total_revenue = sum(r.kwh * User.query.get(r.user_id).unit_cost for r in readings)
        total_co2 = sum(r.kwh * 0.385 for r in readings)

        summary = {
            'total_customers': total_customers,
            'total_readings': len(readings),
            'total_consumption': total_consumption,
            'average_consumption': avg_consumption,
            'peak_consumption': peak_consumption,
            'total_revenue': total_revenue,
            'total_co2': total_co2,
            'efficient_customers': efficient,
            'inefficient_customers': inefficient,
            'above_threshold_count': above_threshold,
            'below_threshold_count': below_threshold
        }

        return {
            'chart': img_base64,
            'summary': summary
        }

    except Exception as e:
        print(f"Examiner report error: {e}")
        plt.close('all')
        return {
            'chart': None,
            'summary': {
                'total_customers': 0,
                'total_readings': 0,
                'total_consumption': 0,
                'average_consumption': 0,
                'peak_consumption': 0,
                'total_revenue': 0,
                'total_co2': 0,
                'efficient_customers': 0,
                'inefficient_customers': 0,
                'above_threshold_count': 0,
                'below_threshold_count': 0
            }
        }


def generate_examiner_report():
    """Generate comprehensive system report for examiner"""
    try:
        users = User.query.all()
        readings = Reading.query.all()

        if not readings:
            return {
                'chart': None,
                'summary': {
                    'total_users': len(users),
                    'total_readings': 0,
                    'total_consumption': 0,
                    'total_revenue': 0,
                    'total_co2': 0,
                    'avg_consumption_per_user': 0,
                    'peak_month': 'N/A',
                    'efficient_users': 0,
                    'inefficient_users': 0
                }
            }

        fig = plt.figure(figsize=(16, 12))

        # 1. Total consumption by user
        ax1 = plt.subplot(3, 3, 1)
        user_consumption = {}
        for user in users:
            user_readings = Reading.query.filter_by(user_id=user.id).all()
            if user_readings:
                user_consumption[user.username] = sum(r.kwh for r in user_readings)

        if user_consumption:
            usernames = list(user_consumption.keys())
            totals = list(user_consumption.values())
            colors = plt.cm.Set3(np.linspace(0, 1, len(usernames)))
            ax1.pie(totals, labels=usernames, autopct='%1.1f%%', colors=colors, startangle=90)
            ax1.set_title("Consumption Distribution by User", fontsize=12, fontweight='bold')
        else:
            ax1.text(0.5, 0.5, 'No data', ha='center', va='center', transform=ax1.transAxes)

        # 2. Monthly trends
        ax2 = plt.subplot(3, 3, 2)
        monthly_data = {}
        for reading in readings:
            month_key = reading.created_at.strftime('%Y-%m')
            if month_key not in monthly_data:
                monthly_data[month_key] = 0
            monthly_data[month_key] += reading.kwh

        months = sorted(monthly_data.keys())
        monthly_totals = [monthly_data[m] for m in months]

        if months:
            ax2.plot(range(len(months)), monthly_totals, marker='o', linewidth=2, color='#ff6b6b')
            ax2.fill_between(range(len(months)), monthly_totals, alpha=0.3, color='#ff6b6b')
            ax2.set_xlabel("Month", fontsize=10)
            ax2.set_ylabel("Total Consumption (kWh)", fontsize=10)
            ax2.set_title("System-wide Monthly Trends", fontsize=12, fontweight='bold')
            ax2.set_xticks(range(len(months)))
            ax2.set_xticklabels(months, rotation=45, ha='right')
            ax2.grid(True, alpha=0.3)
        else:
            ax2.text(0.5, 0.5, 'No data', ha='center', va='center', transform=ax2.transAxes)

        # 3. Revenue analysis
        ax3 = plt.subplot(3, 3, 3)
        revenue_data = {}
        for reading in readings:
            user = User.query.get(reading.user_id)
            if user:
                month_key = reading.created_at.strftime('%Y-%m')
                cost = reading.kwh * user.unit_cost
                if month_key not in revenue_data:
                    revenue_data[month_key] = 0
                revenue_data[month_key] += cost

        if revenue_data:
            rev_months = sorted(revenue_data.keys())
            revenues = [revenue_data[m] for m in rev_months]
            ax3.bar(range(len(rev_months)), revenues, color='#00b894', edgecolor='black')
            ax3.set_xlabel("Month", fontsize=10)
            ax3.set_ylabel("Revenue", fontsize=10)
            ax3.set_title("Monthly Revenue", fontsize=12, fontweight='bold')
            ax3.set_xticks(range(len(rev_months)))
            ax3.set_xticklabels(rev_months, rotation=45, ha='right')
            ax3.grid(True, alpha=0.3)
        else:
            ax3.text(0.5, 0.5, 'No data', ha='center', va='center', transform=ax3.transAxes)

        # 4. User statistics
        ax4 = plt.subplot(3, 3, 4)
        roles = ['admin', 'examiner', 'customer']
        role_counts = [User.query.filter_by(role=r).count() for r in roles]
        ax4.bar(roles, role_counts, color=['#ff6b6b', '#f39c12', '#00b894'])
        ax4.set_xlabel("User Role", fontsize=10)
        ax4.set_ylabel("Count", fontsize=10)
        ax4.set_title("User Distribution", fontsize=12, fontweight='bold')
        ax4.grid(True, alpha=0.3)

        # 5. Peak usage times
        ax5 = plt.subplot(3, 3, 5)
        hour_data = [0] * 24
        for reading in readings:
            hour = reading.timestamp.hour
            hour_data[hour] += reading.kwh

        hours = list(range(24))
        ax5.bar(hours, hour_data, color='#9b59b6', edgecolor='black', alpha=0.7)
        ax5.set_xlabel("Hour of Day", fontsize=10)
        ax5.set_ylabel("Consumption (kWh)", fontsize=10)
        ax5.set_title("Peak Usage Hours", fontsize=12, fontweight='bold')
        ax5.set_xticks(range(0, 24, 3))
        ax5.grid(True, alpha=0.3)

        # 6. CO2 emissions
        ax6 = plt.subplot(3, 3, 6)
        co2_data = {}
        for reading in readings:
            month_key = reading.created_at.strftime('%Y-%m')
            if month_key not in co2_data:
                co2_data[month_key] = 0
            co2_data[month_key] += reading.kwh * 0.385

        if co2_data:
            co2_months = sorted(co2_data.keys())
            co2_values = [co2_data[m] for m in co2_months]
            ax6.fill_between(range(len(co2_months)), co2_values, alpha=0.5, color='#95a5a6')
            ax6.plot(range(len(co2_months)), co2_values, linewidth=2, color='#2c3e50')
            ax6.set_xlabel("Month", fontsize=10)
            ax6.set_ylabel("CO2 (kg)", fontsize=10)
            ax6.set_title("Carbon Footprint Trend", fontsize=12, fontweight='bold')
            ax6.set_xticks(range(len(co2_months)))
            ax6.set_xticklabels(co2_months, rotation=45, ha='right')
            ax6.grid(True, alpha=0.3)
        else:
            ax6.text(0.5, 0.5, 'No data', ha='center', va='center', transform=ax6.transAxes)

        # 7. Financial summary
        ax7 = plt.subplot(3, 3, 7)
        payment_status = ['paid', 'pending', 'overdue']
        status_counts = []
        for status in payment_status:
            count = FinancialRecord.query.filter_by(payment_status=status).count()
            status_counts.append(count)

        if sum(status_counts) > 0:
            ax7.pie(status_counts, labels=payment_status, autopct='%1.1f%%',
                    colors=['#00b894', '#f39c12', '#ff6b6b'], startangle=90)
            ax7.set_title("Payment Status Distribution", fontsize=12, fontweight='bold')
        else:
            ax7.text(0.5, 0.5, 'No payment data', ha='center', va='center', transform=ax7.transAxes)

        # 8. Efficiency ratings
        ax8 = plt.subplot(3, 3, 8)
        efficient_users = 0
        average_users = 0
        inefficient_users = 0

        for user in users:
            user_readings = Reading.query.filter_by(user_id=user.id).all()
            if user_readings:
                avg_consumption = sum(r.kwh for r in user_readings) / len(user_readings)
                if avg_consumption < user.threshold * 0.7:
                    efficient_users += 1
                elif avg_consumption < user.threshold:
                    average_users += 1
                else:
                    inefficient_users += 1

        efficiency_data = [efficient_users, average_users, inefficient_users]
        efficiency_labels = ['Efficient', 'Average', 'Inefficient']
        colors_efficiency = ['#00b894', '#f39c12', '#ff6b6b']
        ax8.bar(efficiency_labels, efficiency_data, color=colors_efficiency)
        ax8.set_xlabel("Efficiency Level", fontsize=10)
        ax8.set_ylabel("Number of Users", fontsize=10)
        ax8.set_title("User Efficiency Distribution", fontsize=12, fontweight='bold')
        ax8.grid(True, alpha=0.3)

        # 9. System health
        ax9 = plt.subplot(3, 3, 9)
        total_readings = len(readings)
        active_users = len([u for u in users if u.readings])
        system_metrics = [active_users, total_readings, len(users)]
        metric_labels = ['Active Users', 'Total Readings', 'Total Users']
        ax9.barh(metric_labels, system_metrics, color='#3498db')
        ax9.set_xlabel("Count", fontsize=10)
        ax9.set_title("System Health Metrics", fontsize=12, fontweight='bold')

        plt.tight_layout()

        img_bytes = io.BytesIO()
        plt.savefig(img_bytes, format='png', dpi=100, bbox_inches='tight')
        img_bytes.seek(0)
        plt.close()

        img_base64 = base64.b64encode(img_bytes.getvalue()).decode()

        summary = {
            'total_users': len(users),
            'total_readings': total_readings,
            'total_consumption': sum(r.kwh for r in readings),
            'total_revenue': sum(r.kwh * User.query.get(r.user_id).unit_cost for r in readings),
            'total_co2': sum(r.kwh * 0.385 for r in readings),
            'avg_consumption_per_user': sum(r.kwh for r in readings) / len(users) if users else 0,
            'peak_month': max(monthly_data.items(), key=lambda x: x[1])[0] if monthly_data else 'N/A',
            'efficient_users': efficient_users,
            'inefficient_users': inefficient_users
        }

        return {
            'chart': img_base64,
            'summary': summary
        }

    except Exception as e:
        print(f"Report generation error: {e}")
        plt.close('all')
        return {
            'chart': None,
            'summary': {
                'total_users': User.query.count(),
                'total_readings': 0,
                'total_consumption': 0,
                'total_revenue': 0,
                'total_co2': 0,
                'avg_consumption_per_user': 0,
                'peak_month': 'N/A',
                'efficient_users': 0,
                'inefficient_users': 0
            }
        }


def generate_financial_report():
    """Generate financial report for admin"""
    try:
        users = User.query.all()
        readings = Reading.query.all()
        financial_records = FinancialRecord.query.all()

        total_revenue = sum(r.kwh * User.query.get(r.user_id).unit_cost for r in readings) if readings else 0
        total_outstanding = sum(r.balance for r in financial_records if r.balance > 0) if financial_records else 0
        total_collected = total_revenue - total_outstanding

        if not readings or not users:
            return {
                'chart': None,
                'total_revenue': 0,
                'total_outstanding': 0,
                'total_collected': 0,
                'payment_rate': 0
            }

        fig = plt.figure(figsize=(15, 10))

        # 1. Revenue by user
        ax1 = plt.subplot(2, 3, 1)
        user_revenue = {}
        for user in users:
            user_readings = Reading.query.filter_by(user_id=user.id).all()
            if user_readings:
                user_revenue[user.username] = sum(r.kwh * user.unit_cost for r in user_readings)

        if user_revenue:
            top_users = dict(sorted(user_revenue.items(), key=lambda x: x[1], reverse=True)[:5])
            ax1.bar(range(len(top_users)), list(top_users.values()), color='#00b894')
            ax1.set_xlabel("Top 5 Users", fontsize=10)
            ax1.set_ylabel("Revenue", fontsize=10)
            ax1.set_title("Top Revenue Generating Users", fontsize=12, fontweight='bold')
            ax1.set_xticks(range(len(top_users)))
            ax1.set_xticklabels(list(top_users.keys()), rotation=45, ha='right')
            ax1.grid(True, alpha=0.3)
        else:
            ax1.text(0.5, 0.5, 'No revenue data', ha='center', va='center', transform=ax1.transAxes)

        # 2. Monthly revenue trend
        ax2 = plt.subplot(2, 3, 2)
        monthly_revenue = {}
        for reading in readings:
            user = User.query.get(reading.user_id)
            if user:
                month_key = reading.created_at.strftime('%Y-%m')
                cost = reading.kwh * user.unit_cost
                if month_key not in monthly_revenue:
                    monthly_revenue[month_key] = 0
                monthly_revenue[month_key] += cost

        if monthly_revenue:
            months = sorted(monthly_revenue.keys())
            revenues = [monthly_revenue[m] for m in months]
            ax2.plot(range(len(months)), revenues, marker='o', linewidth=2, color='#ff6b6b')
            ax2.fill_between(range(len(months)), revenues, alpha=0.3, color='#ff6b6b')
            ax2.set_xlabel("Month", fontsize=10)
            ax2.set_ylabel("Revenue", fontsize=10)
            ax2.set_title("Monthly Revenue Trend", fontsize=12, fontweight='bold')
            ax2.set_xticks(range(len(months)))
            ax2.set_xticklabels(months, rotation=45, ha='right')
            ax2.grid(True, alpha=0.3)
        else:
            ax2.text(0.5, 0.5, 'No monthly data', ha='center', va='center', transform=ax2.transAxes)

        # 3. Payment status
        ax3 = plt.subplot(2, 3, 3)
        status_counts = {
            'paid': FinancialRecord.query.filter_by(payment_status='paid').count(),
            'pending': FinancialRecord.query.filter_by(payment_status='pending').count(),
            'overdue': FinancialRecord.query.filter_by(payment_status='overdue').count()
        }

        if sum(status_counts.values()) > 0:
            ax3.pie(status_counts.values(), labels=status_counts.keys(), autopct='%1.1f%%',
                    colors=['#00b894', '#f39c12', '#ff6b6b'], startangle=90)
            ax3.set_title("Payment Status Distribution", fontsize=12, fontweight='bold')
        else:
            ax3.text(0.5, 0.5, 'No payment data', ha='center', va='center', transform=ax3.transAxes)

        # 4. Outstanding balances
        ax4 = plt.subplot(2, 3, 4)
        users_with_balance = []
        balances = []
        for record in financial_records:
            if record.balance > 0:
                user = User.query.get(record.user_id)
                if user:
                    users_with_balance.append(user.username)
                    balances.append(record.balance)

        if users_with_balance:
            ax4.barh(users_with_balance[:5], balances[:5], color='#e74c3c')
            ax4.set_xlabel("Balance", fontsize=10)
            ax4.set_title("Top Outstanding Balances", fontsize=12, fontweight='bold')
            ax4.grid(True, alpha=0.3)
        else:
            ax4.text(0.5, 0.5, 'No outstanding balances', ha='center', va='center', transform=ax4.transAxes)

        # 5. Revenue vs Consumption
        ax5 = plt.subplot(2, 3, 5)
        has_data = False
        for user in users[:5]:
            user_readings = Reading.query.filter_by(user_id=user.id).all()
            if user_readings:
                months_data = {}
                for reading in user_readings:
                    month_key = reading.created_at.strftime('%Y-%m')
                    if month_key not in months_data:
                        months_data[month_key] = {'kwh': 0, 'cost': 0}
                    months_data[month_key]['kwh'] += reading.kwh
                    months_data[month_key]['cost'] += reading.kwh * user.unit_cost

                months = sorted(months_data.keys())[-6:]
                if months:
                    costs = [months_data[m]['cost'] for m in months]
                    ax5.plot(range(len(months)), costs, marker='o', label=user.username)
                    has_data = True

        if has_data:
            ax5.set_xlabel("Months", fontsize=10)
            ax5.set_ylabel("Revenue", fontsize=10)
            ax5.set_title("User Revenue Comparison", fontsize=12, fontweight='bold')
            ax5.legend(bbox_to_anchor=(1.05, 1), loc='upper left')
            ax5.grid(True, alpha=0.3)
        else:
            ax5.text(0.5, 0.5, 'No comparison data', ha='center', va='center', transform=ax5.transAxes)

        # 6. Financial summary
        ax6 = plt.subplot(2, 3, 6)
        summary_data = ['Collected', 'Outstanding', 'Total Revenue']
        summary_values = [total_collected, total_outstanding, total_revenue]
        colors_summary = ['#00b894', '#ff6b6b', '#3498db']

        if total_revenue > 0:
            ax6.bar(summary_data, summary_values, color=colors_summary)
            ax6.set_xlabel("Category", fontsize=10)
            ax6.set_ylabel("Amount", fontsize=10)
            ax6.set_title("Financial Summary", fontsize=12, fontweight='bold')
            ax6.grid(True, alpha=0.3)

            for i, v in enumerate(summary_values):
                ax6.text(i, v + 5, f'{v:.0f}', ha='center', va='bottom', fontsize=9)
        else:
            ax6.text(0.5, 0.5, 'No financial data', ha='center', va='center', transform=ax6.transAxes)

        plt.tight_layout()

        img_bytes = io.BytesIO()
        plt.savefig(img_bytes, format='png', dpi=100, bbox_inches='tight')
        img_bytes.seek(0)
        plt.close()

        img_base64 = base64.b64encode(img_bytes.getvalue()).decode()

        return {
            'chart': img_base64,
            'total_revenue': total_revenue,
            'total_outstanding': total_outstanding,
            'total_collected': total_collected,
            'payment_rate': (total_collected / total_revenue * 100) if total_revenue > 0 else 0
        }

    except Exception as e:
        print(f"Financial report error: {e}")
        plt.close('all')
        return {
            'chart': None,
            'total_revenue': 0,
            'total_outstanding': 0,
            'total_collected': 0,
            'payment_rate': 0
        }


def send_report_to_customers(admin_id):
    """Send consumption summary to all customers"""
    customers = User.query.filter_by(role='customer').all()
    count = 0

    for customer in customers:
        customer_readings = Reading.query.filter_by(user_id=customer.id).all()
        if customer_readings:
            total_consumption = sum(r.kwh for r in customer_readings)
            total_cost = sum(r.kwh * customer.unit_cost for r in customer_readings)

            # Calculate if readings are approved
            approved_readings = [r for r in customer_readings if r.is_approved]
            pending_readings = [r for r in customer_readings if not r.is_approved]

            report_content = f"""
            <h2>Energy Consumption Summary - {datetime.utcnow().strftime('%B %Y')}</h2>
            <p>Dear {customer.username},</p>
            <p>Here's your energy consumption summary:</p>
            <ul>
                <li><strong>Total Consumption:</strong> {total_consumption:.2f} kWh</li>
                <li><strong>Total Cost:</strong> {customer.currency} {total_cost:.2f}</li>
                <li><strong>Average Monthly:</strong> {total_consumption / len(customer_readings):.2f} kWh</li>
                <li><strong>Approved Readings:</strong> {len(approved_readings)}</li>
                <li><strong>Pending Review:</strong> {len(pending_readings)}</li>
            </ul>

            <h3>Detailed Breakdown:</h3>
            <table border="1" cellpadding="5" style="border-collapse: collapse;">
                <tr>
                    <th>Period</th>
                    <th>Consumption (kWh)</th>
                    <th>Cost</th>
                    <th>Status</th>
                </tr>
            """

            for reading in customer_readings[-6:]:  # Last 6 readings
                status = " Approved" if reading.is_approved else "⏳ Pending Review"
                report_content += f"""
                <tr>
                    <td>{reading.date}</td>
                    <td>{reading.kwh:.2f}</td>
                    <td>{customer.currency} {(reading.kwh * customer.unit_cost):.2f}</td>
                    <td>{status}</td>
                </tr>
                """

            report_content += """
            </table>

            <p><strong>Next Steps:</strong></p>
            <ul>
                <li>Please review your consumption data</li>
                <li>Ensure timely payment to avoid service interruption</li>
                <li>Contact support for any discrepancies</li>
            </ul>

            <p>Thank you for being an EcoPulse customer!</p>
            """

            report = Report(
                title=f"Consumption Summary - {datetime.utcnow().strftime('%B %Y')}",
                content=report_content,
                report_type='consumption_summary',
                sent_by=admin_id,
                sent_to=customer.id
            )
            db.session.add(report)
            count += 1

            # Real email notification (SMTP) for customers who opt in.
            if getattr(customer, 'alert_email', False) and getattr(customer, 'email', None):
                subject = f"EcoPulse Consumption Summary - {datetime.utcnow().strftime('%B %Y')}"
                ok, err = send_email_notification(customer.email, subject, report_content)
                if not ok:
                    print(f"Consumption email failed for {customer.email}: {err}")
                else:
                    print(f"Consumption email sent to {customer.email}")

    db.session.commit()
    return count


def update_database_schema():
    """Check and update database schema if needed"""
    try:
        from sqlalchemy import inspect
        inspector = inspect(db.engine)

        if 'users' in inspector.get_table_names():
            user_columns = [col['name'] for col in inspector.get_columns('users')]
            user_required = {
                'meter_number': 'VARCHAR(11)'
            }
            for col_name, col_type in user_required.items():
                if col_name not in user_columns:
                    with db.engine.connect() as conn:
                        conn.execute(db.text(f"ALTER TABLE users ADD COLUMN {col_name} {col_type}"))
                        conn.commit()
            if 'phone' not in user_columns:
                with db.engine.connect() as conn:
                    conn.execute(db.text("ALTER TABLE users ADD COLUMN phone VARCHAR(20)"))
                    conn.commit()

        # Check if readings table exists and has required columns
        if 'readings' in inspector.get_table_names():
            columns = [col['name'] for col in inspector.get_columns('readings')]

            # Add missing columns if they don't exist
            required_columns = {
                'cost': 'FLOAT DEFAULT 0',
                'is_reviewed': 'BOOLEAN DEFAULT 0',
                'reviewed_by': 'INTEGER',
                'reviewed_at': 'DATETIME',
                'review_notes': 'TEXT',
                'is_approved': 'BOOLEAN DEFAULT 0',
                'approved_by': 'INTEGER',
                'approved_at': 'DATETIME'
            }

            for col_name, col_type in required_columns.items():
                if col_name not in columns:
                    print(f" Adding missing '{col_name}' column to readings table...")
                    with db.engine.connect() as conn:
                        conn.execute(db.text(f"ALTER TABLE readings ADD COLUMN {col_name} {col_type}"))
                        conn.commit()
                    print(f" '{col_name}' column added successfully!")

        # Check if consumption_reviews table exists
        if 'consumption_reviews' not in inspector.get_table_names():
            print(" Creating consumption_reviews table...")
            # Table will be created by SQLAlchemy when we run db.create_all()

        # Check if customer_submissions table exists
        if 'customer_submissions' not in inspector.get_table_names():
            print(" Creating customer_submissions table...")
            # Table will be created by SQLAlchemy when we run db.create_all()

        if 'contact_messages' not in inspector.get_table_names():
            print(" Creating contact_messages table...")
            # Table will be created by SQLAlchemy when we run db.create_all()

        if 'user_settings' in inspector.get_table_names():
            settings_columns = [col['name'] for col in inspector.get_columns('user_settings')]
            settings_required = {
                'allow_overage': 'BOOLEAN DEFAULT 0',
                'auto_shutdown_enabled': 'BOOLEAN DEFAULT 1',
                'shutdown_delay_minutes': 'INTEGER DEFAULT 5',
                'last_threshold_alert_at': 'DATETIME',
                'scheduled_shutdown_at': 'DATETIME'
            }
            for col_name, col_type in settings_required.items():
                if col_name not in settings_columns:
                    with db.engine.connect() as conn:
                        conn.execute(db.text(f"ALTER TABLE user_settings ADD COLUMN {col_name} {col_type}"))
                        conn.commit()

    except Exception as e:
        print(f"Note: Schema check - {e}")


# ===================== NEW CUSTOMER SUBMISSION ROUTES =====================

@app.route('/submit_to_admin', methods=['POST'])
@login_required
def submit_to_admin():
    """Allow customer to submit their consumption summary to admin for verification"""
    if current_user.role != 'customer':
        return jsonify({'success': False, 'message': 'Only customers can submit'})

    # Get customer's readings
    readings = Reading.query.filter_by(user_id=current_user.id).all()

    if not readings:
        return jsonify({'success': False, 'message': 'No readings to submit'})

    # Calculate statistics
    total_consumption = sum(r.kwh for r in readings)
    total_cost = sum(r.kwh * current_user.unit_cost for r in readings)
    avg_daily = total_consumption / len(readings) if readings else 0

    # Check if there's already a pending submission
    existing = CustomerSubmission.query.filter_by(
        customer_id=current_user.id,
        status='pending'
    ).first()

    if existing:
        return jsonify({'success': False, 'message': 'You already have a pending submission'})

    # Create submission
    submission = CustomerSubmission(
        customer_id=current_user.id,
        period=datetime.utcnow().strftime('%Y-%m'),
        total_consumption=total_consumption,
        total_cost=total_cost,
        average_daily=avg_daily,
        readings_count=len(readings),
        notes=f"Submitted for verification - {len(readings)} readings",
        status='pending'
    )

    db.session.add(submission)
    db.session.commit()

    # Create a report for admin
    admin = User.query.filter_by(role='admin').first()
    if admin:
        report_content = f"""
        <h2>Customer Consumption Submission - {current_user.username}</h2>
        <p><strong>Customer:</strong> {current_user.username}</p>
        <p><strong>Email:</strong> {current_user.email}</p>
        <p><strong>Period:</strong> {submission.period}</p>
        <p><strong>Total Consumption:</strong> {total_consumption:.2f} kWh</p>
        <p><strong>Total Cost:</strong> {current_user.currency} {total_cost:.2f}</p>
        <p><strong>Average Daily:</strong> {avg_daily:.2f} kWh</p>
        <p><strong>Number of Readings:</strong> {len(readings)}</p>

        <h3>Detailed Readings:</h3>
        <table border="1" cellpadding="5" style="border-collapse: collapse;">
            <tr>
                <th>Period</th>
                <th>Consumption (kWh)</th>
                <th>Cost</th>
                <th>Status</th>
            </tr>
        """

        for reading in readings:
            status = " Approved" if reading.is_approved else "⏳ Pending" if not reading.is_reviewed else "📝 Reviewed"
            report_content += f"""
            <tr>
                <td>{reading.date}</td>
                <td>{reading.kwh:.2f}</td>
                <td>{current_user.currency} {(reading.kwh * current_user.unit_cost):.2f}</td>
                <td>{status}</td>
            </tr>
            """

        report_content += """
        </table>

        <p>Please review this submission and verify the consumption data.</p>
        """

        report = Report(
            title=f"Customer Submission - {current_user.username} - {submission.period}",
            content=report_content,
            report_type='customer_submission',
            sent_by=current_user.id,
            sent_to=admin.id
        )
        db.session.add(report)
        db.session.commit()

    log_system_action(current_user.id, f"Submitted consumption summary to admin")

    return jsonify({
        'success': True,
        'message': 'Submission sent to admin successfully!'
    })


@app.route('/admin_submissions')
@login_required
@admin_required
def admin_submissions():
    """View all customer submissions"""
    submissions = CustomerSubmission.query.order_by(CustomerSubmission.created_at.desc()).all()

    # Create a simple HTML page for submissions
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Customer Submissions - Admin</title>
        <link rel="icon" type="image/svg+xml" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Crect width='64' height='64' rx='16' fill='%23062f2f'/%3E%3Cpath d='M35 6 18 34h11l-4 24 21-31H34z' fill='%23f59e0b'/%3E%3C/svg%3E">
        <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css">
        <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.0/font/bootstrap-icons.css">
        <style>
            body {
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                min-height: 100vh;
                padding: 20px;
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            }
            .container {
                background: linear-gradient(180deg, rgba(248,255,253,0.96) 0%, rgba(236,253,245,0.94) 100%);
                border: 1px solid rgba(255,255,255,0.45);
                backdrop-filter: blur(10px);
                border-radius: 15px;
                padding: 30px;
                margin-top: 30px;
                box-shadow: 0 10px 30px rgba(0,0,0,0.2);
            }
            .status-pending { background-color: #f39c12; color: white; padding: 5px 10px; border-radius: 20px; }
            .status-reviewed { background-color: #3498db; color: white; padding: 5px 10px; border-radius: 20px; }
            .status-approved { background-color: #00b894; color: white; padding: 5px 10px; border-radius: 20px; }
            .status-rejected { background-color: #ff6b6b; color: white; padding: 5px 10px; border-radius: 20px; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1 class="mb-4"><i class="bi bi-people"></i> Customer Submissions</h1>
            <a href="/admin_financial" class="btn btn-primary mb-3">Back to Dashboard</a>

            <div class="table-responsive">
                <table class="table table-hover">
                    <thead>
                        <tr>
                            <th>ID</th>
                            <th>Customer</th>
                            <th>Period</th>
                            <th>Total Consumption</th>
                            <th>Total Cost</th>
                            <th>Readings</th>
                            <th>Status</th>
                            <th>Submitted</th>
                            <th>Actions</th>
                        </tr>
                    </thead>
                    <tbody>
    """

    for sub in submissions:
        status_class = f"status-{sub.status}"
        html += f"""
        <tr>
            <td>{sub.id}</td>
            <td>{sub.customer.username}</td>
            <td>{sub.period}</td>
            <td>{sub.total_consumption:.2f} kWh</td>
            <td>Ksh {sub.total_cost:.2f}</td>
            <td>{sub.readings_count}</td>
            <td><span class="{status_class}">{sub.status}</span></td>
            <td>{sub.created_at.strftime('%Y-%m-%d %H:%M')}</td>
            <td>
                <button class="btn btn-sm btn-success" onclick="approveSubmission({sub.id})">Approve</button>
                <button class="btn btn-sm btn-warning" onclick="reviewSubmission({sub.id})">Review</button>
                <button class="btn btn-sm btn-danger" onclick="rejectSubmission({sub.id})">Reject</button>
            </td>
        </tr>
        """

    html += """
                    </tbody>
                </table>
            </div>
        </div>

        <script>
            function approveSubmission(id) {
                fetch('/approve_submission/' + id, {method: 'POST'})
                    .then(r => r.json())
                    .then(d => { alert(d.message); location.reload(); });
            }
            function reviewSubmission(id) {
                fetch('/review_submission/' + id, {method: 'POST'})
                    .then(r => r.json())
                    .then(d => { alert(d.message); location.reload(); });
            }
            function rejectSubmission(id) {
                fetch('/reject_submission/' + id, {method: 'POST'})
                    .then(r => r.json())
                    .then(d => { alert(d.message); location.reload(); });
            }
        </script>
        <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script>
    </body>
    </html>
    """

    return html


@app.route('/approve_submission/<int:submission_id>', methods=['POST'])
@login_required
@admin_required
def approve_submission(submission_id):
    """Approve a customer submission"""
    submission = CustomerSubmission.query.get(submission_id)
    if submission:
        submission.status = 'approved'
        submission.reviewed_by = current_user.id
        submission.reviewed_at = datetime.utcnow()
        submission.admin_notes = "Approved by admin"

        # Mark customer's readings as approved
        readings = Reading.query.filter_by(user_id=submission.customer_id).all()
        for reading in readings:
            reading.is_approved = True
            reading.approved_by = current_user.id
            reading.approved_at = datetime.utcnow()

        db.session.commit()

        # Notify customer
        report = Report(
            title=f"Submission Approved - {submission.period}",
            content=f"Dear {submission.customer.username}, your consumption submission has been approved.",
            report_type='submission_response',
            sent_by=current_user.id,
            sent_to=submission.customer_id
        )
        db.session.add(report)
        db.session.commit()

        log_system_action(current_user.id, f"Approved customer submission ID: {submission_id}")
        return jsonify({'message': 'Submission approved successfully!'})

    return jsonify({'message': 'Submission not found'})


@app.route('/review_submission/<int:submission_id>', methods=['POST'])
@login_required
@admin_required
def review_submission(submission_id):
    """Mark a customer submission as reviewed"""
    submission = CustomerSubmission.query.get(submission_id)
    if submission:
        submission.status = 'reviewed'
        submission.reviewed_by = current_user.id
        submission.reviewed_at = datetime.utcnow()
        db.session.commit()

        log_system_action(current_user.id, f"Reviewed customer submission ID: {submission_id}")
        return jsonify({'message': 'Submission marked as reviewed!'})

    return jsonify({'message': 'Submission not found'})


@app.route('/reject_submission/<int:submission_id>', methods=['POST'])
@login_required
@admin_required
def reject_submission(submission_id):
    """Reject a customer submission"""
    submission = CustomerSubmission.query.get(submission_id)
    if submission:
        submission.status = 'rejected'
        submission.reviewed_by = current_user.id
        submission.reviewed_at = datetime.utcnow()
        submission.admin_notes = "Rejected - Please review your readings"
        db.session.commit()

        # Notify customer
        report = Report(
            title=f"Submission Rejected - {submission.period}",
            content=f"Dear {submission.customer.username}, your consumption submission needs review. Please check your readings.",
            report_type='submission_response',
            sent_by=current_user.id,
            sent_to=submission.customer_id
        )
        db.session.add(report)
        db.session.commit()

        log_system_action(current_user.id, f"Rejected customer submission ID: {submission_id}")
        return jsonify({'message': 'Submission rejected!'})

    return jsonify({'message': 'Submission not found'})


# ===================== TEMPLATES =====================

login_page = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Customer Login - EcoPulse</title>
    <link rel="icon" type="image/svg+xml" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Crect width='64' height='64' rx='16' fill='%23062f2f'/%3E%3Cpath d='M35 6 18 34h11l-4 24 21-31H34z' fill='%23f59e0b'/%3E%3C/svg%3E">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.0/font/bootstrap-icons.css">
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;700&family=Source+Sans+3:wght@400;600&display=swap" rel="stylesheet">
    <style>
        :root{--ink:#052e2b;--teal:#0f766e;--sun:#f59e0b;--mist:#ecfdf5;--card:rgba(255,255,255,.92)}
        body{min-height:100vh;display:flex;align-items:center;justify-content:center;background:radial-gradient(circle at top left,rgba(245,158,11,.22),transparent 26%),radial-gradient(circle at bottom right,rgba(16,185,129,.28),transparent 26%),linear-gradient(145deg,#041b1b,#0b3c38 48%,#166534);font-family:'Source Sans 3',sans-serif;padding:24px}
        .auth-shell{max-width:1080px;width:100%;margin:auto;background:var(--card);border:1px solid rgba(255,255,255,.2);border-radius:32px;overflow:hidden;box-shadow:0 30px 80px rgba(0,0,0,.32);backdrop-filter:blur(12px)}
        .auth-hero{background:linear-gradient(160deg,#052e2b,#0f766e 60%,#34d399);color:white;padding:56px;min-height:100%;position:relative;overflow:hidden}
        .auth-hero:before,.auth-hero:after{content:'';position:absolute;border-radius:999px;background:rgba(255,255,255,.08)}
        .auth-hero:before{width:220px;height:220px;top:-80px;right:-60px}
        .auth-hero:after{width:160px;height:160px;bottom:-50px;left:-40px}
        .auth-hero>*{position:relative;z-index:1}
        .auth-card{padding:56px;background:linear-gradient(180deg,#ffffff,#f8fffd)}
        .accent-chip{display:inline-flex;align-items:center;gap:10px;padding:9px 16px;border-radius:999px;background:rgba(255,255,255,.14);border:1px solid rgba(255,255,255,.14);margin-bottom:24px;font-weight:600}
        h1,h2{font-family:'Space Grotesk',sans-serif}
        .auth-list{display:grid;gap:14px;margin-top:28px}
        .auth-list div{padding:14px 16px;border-radius:18px;background:rgba(255,255,255,.1);border:1px solid rgba(255,255,255,.1)}
        .form-control{border-radius:16px;padding:.9rem 1rem;border:1px solid #d9e7e2}
        .form-control:focus{border-color:#0f766e;box-shadow:0 0 0 .2rem rgba(15,118,110,.14)}
        .btn-dark{background:linear-gradient(135deg,#052e2b,#0f766e);border:none;border-radius:16px;padding:.9rem 1rem;font-weight:700}
        .btn-link{color:#0f766e}
        .helper-band{margin-top:24px;padding:16px 18px;border-radius:18px;background:#f0fdf9;border:1px solid rgba(15,118,110,.14)}
        @media (max-width:991.98px){.auth-hero,.auth-card{padding:40px}}
        @media (max-width:767.98px){body{padding:16px}.auth-shell{border-radius:24px}.auth-hero,.auth-card{padding:28px}.btn-dark{width:100%}}
    </style>
</head>
<body>
    <div class="auth-shell row g-0">
        <div class="col-lg-6 auth-hero d-flex flex-column justify-content-center">
            <div class="accent-chip"><i class="bi bi-lightning-charge-fill"></i> EcoPulse Customer Access</div>
            <h1 class="display-5 fw-bold">Monitor usage, costs, and alerts from one place.</h1>
            <p class="lead mt-3">Customer login is public. Staff access exists separately and is intentionally not shown on the homepage navigation.</p>
            <div class="auth-list">
                <div><strong>Usage visibility</strong><br><span class="small">Track readings, thresholds, and estimated billing in one workspace.</span></div>
                <div><strong>Faster follow-up</strong><br><span class="small">See alerts, reports, and support actions without switching systems.</span></div>
            </div>
        </div>
        <div class="col-lg-6 auth-card">
            <a href="{{ url_for('index') }}" class="btn btn-link px-0 text-decoration-none"><i class="bi bi-arrow-left"></i> Back to home</a>
            <h2 class="fw-bold mt-3">Customer Login</h2>
            <p class="text-muted">Sign in with your customer account.</p>
            {% if error %}<div class="alert alert-danger">{{ error }}</div>{% endif %}
            {% with messages = get_flashed_messages(with_categories=true) %}{% for category, msg in messages %}<div class="alert alert-{{ 'warning' if category == 'warning' else 'info' }}">{{ msg }}</div>{% endfor %}{% endwith %}
            <form method="POST" class="mt-4">
                <div class="mb-3"><label class="form-label">Username</label><input type="text" name="username" class="form-control form-control-lg" required></div>
                <div class="mb-3"><label class="form-label">KPLC Meter Number</label><input type="text" name="meter_number" maxlength="11" class="form-control form-control-lg" placeholder="Enter your 11-digit meter number" required></div>
                <div class="mb-3"><label class="form-label">Password</label><input type="password" name="password" class="form-control form-control-lg" required></div>
                <button type="submit" class="btn btn-lg btn-dark w-100">Login</button>
            </form>
            <div class="helper-band"><span class="text-muted">Need an account?</span> <a href="{{ url_for('register') }}" class="text-decoration-none fw-semibold">Register as a customer</a><div class="small text-muted mt-2">Customer login now requires the autogenerated KPLC meter number together with username and password.</div></div>
        </div>
    </div>
</body>
</html>
"""

staff_login_page = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Staff Login - EcoPulse</title>
    <link rel="icon" type="image/svg+xml" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Crect width='64' height='64' rx='16' fill='%23062f2f'/%3E%3Cpath d='M35 6 18 34h11l-4 24 21-31H34z' fill='%23f59e0b'/%3E%3C/svg%3E">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.0/font/bootstrap-icons.css">
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;700&family=Source+Sans+3:wght@400;600&display=swap" rel="stylesheet">
    <style>:root{--navy:#111827;--slate:#1f2937;--ember:#9a3412;--amber:#f59e0b}body{background:radial-gradient(circle at top right,rgba(245,158,11,.22),transparent 24%),linear-gradient(160deg,#111827,#1f2937 52%,#7c2d12);min-height:100vh;display:flex;align-items:center;justify-content:center;font-family:'Source Sans 3',sans-serif;padding:24px}.panel{max-width:980px;width:100%;margin:auto;background:rgba(255,255,255,.94);border:1px solid rgba(255,255,255,.18);border-radius:30px;overflow:hidden;box-shadow:0 30px 80px rgba(0,0,0,.35)}.staff-hero{background:linear-gradient(155deg,#0f172a,#1f2937 58%,#b45309);color:#fff;padding:48px}.staff-card{padding:48px;background:linear-gradient(180deg,#ffffff,#fffaf5)}h1,h2{font-family:'Space Grotesk',sans-serif}.token{display:inline-flex;align-items:center;gap:10px;background:rgba(255,255,255,.1);border:1px solid rgba(255,255,255,.1);padding:8px 14px;border-radius:999px;margin-bottom:22px}.form-control,.form-select{border-radius:16px;padding:.85rem 1rem;border:1px solid #e5e7eb}.form-control:focus,.form-select:focus{border-color:#92400e;box-shadow:0 0 0 .2rem rgba(146,64,14,.14)}.btn-dark{background:linear-gradient(135deg,#111827,#7c2d12);border:none;border-radius:16px;padding:.9rem 1rem;font-weight:700}.mini-grid{display:grid;gap:14px;margin-top:24px}.mini-grid div{padding:14px 16px;border-radius:18px;background:rgba(255,255,255,.08)}@media (max-width:991.98px){.staff-hero,.staff-card{padding:34px}}@media (max-width:767.98px){body{padding:16px}.panel{border-radius:24px}.staff-hero,.staff-card{padding:26px}}</style>
</head>
<body>
    <div class="panel row g-0">
        <div class="col-lg-5 staff-hero d-flex flex-column justify-content-center">
            <div class="token"><i class="bi bi-shield-lock-fill"></i> Operational Access</div>
            <h1 class="fw-bold">Secure staff sign-in for admin and examiner workflows.</h1>
            <p class="mt-3 mb-0">Use this route for internal approvals, system-wide analysis, and finance operations.</p>
            <div class="mini-grid">
                <div><strong>Admin</strong><br><span class="small">Financial controls, approvals, and customer summaries.</span></div>
                <div><strong>Examiner</strong><br><span class="small">Reading reviews, reports, and forecast-driven guidance.</span></div>
            </div>
        </div>
        <div class="col-lg-7 staff-card">
            <h2 class="fw-bold">Staff Login</h2>
            <p class="text-muted">Hidden operational entry point for admin and examiner roles.</p>
            {% if error %}<div class="alert alert-danger">{{ error }}</div>{% endif %}
            <form method="POST">
                <div class="mb-3"><label class="form-label">Username</label><input type="text" name="username" class="form-control" required></div>
                <div class="mb-3"><label class="form-label">Password</label><input type="password" name="password" class="form-control" required></div>
                <div class="mb-4"><label class="form-label">Role</label><select name="role" class="form-select" required><option value="">Select role</option><option value="admin">Admin</option><option value="examiner">Examiner</option></select></div>
                <button type="submit" class="btn btn-dark w-100">Sign In</button>
            </form>
        </div>
    </div>
</body>
</html>
"""

register_page = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Register - EcoPulse</title>
    <link rel="icon" type="image/svg+xml" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Crect width='64' height='64' rx='16' fill='%23062f2f'/%3E%3Cpath d='M35 6 18 34h11l-4 24 21-31H34z' fill='%23f59e0b'/%3E%3C/svg%3E">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.0/font/bootstrap-icons.css">
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;700&family=Source+Sans+3:wght@400;600&display=swap" rel="stylesheet">
    <style>:root{--forest:#062f2f;--teal:#0f766e;--amber:#f59e0b}body{background:radial-gradient(circle at top left,rgba(245,158,11,.24),transparent 24%),radial-gradient(circle at bottom right,rgba(52,211,153,.22),transparent 24%),linear-gradient(145deg,#0f172a,#0f766e 62%,#0b3b36);min-height:100vh;display:flex;align-items:center;justify-content:center;font-family:'Source Sans 3',sans-serif;padding:24px}.panel{max-width:1080px;width:100%;margin:auto;background:rgba(255,255,255,.94);border:1px solid rgba(255,255,255,.16);border-radius:32px;overflow:hidden;box-shadow:0 28px 80px rgba(0,0,0,.3)}.register-hero{background:linear-gradient(155deg,#062f2f,#0f766e 58%,#34d399);color:#fff;padding:52px}.register-card{padding:52px;background:linear-gradient(180deg,#ffffff,#f8fffd)}h1,h2{font-family:'Space Grotesk',sans-serif}.hero-points{display:grid;gap:14px;margin-top:26px}.hero-points div{padding:14px 16px;border-radius:18px;background:rgba(255,255,255,.1)}.form-control{border-radius:16px;padding:.88rem 1rem;border:1px solid #dbe7e5}.form-control:focus{border-color:#0f766e;box-shadow:0 0 0 .2rem rgba(15,118,110,.14)}.btn-dark{background:linear-gradient(135deg,#062f2f,#0f766e);border:none;border-radius:16px;padding:.95rem 1rem;font-weight:700}.back-link{color:#0f766e}.helper-box{margin-top:18px;padding:16px 18px;border-radius:18px;background:#f0fdf9;border:1px solid rgba(15,118,110,.14)}@media (max-width:991.98px){.register-hero,.register-card{padding:34px}}@media (max-width:767.98px){body{padding:16px}.panel{border-radius:24px}.register-hero,.register-card{padding:26px}}</style>
</head>
<body>
    <div class="panel row g-0">
        <div class="col-lg-5 register-hero d-flex flex-column justify-content-center">
            <span class="badge text-bg-light text-dark mb-3">Customer Onboarding</span>
            <h1 class="fw-bold">Create your EcoPulse account and start tracking energy with clarity.</h1>
            <p class="mt-3 mb-0">Registration gives customers access to readings, billing summaries, threshold settings, and support workflows.</p>
            <div class="hero-points">
                <div><strong>Monitor usage</strong><br><span class="small">Store readings and review consumption trends over time.</span></div>
                <div><strong>Manage thresholds</strong><br><span class="small">Choose how EcoPulse behaves when your usage goes above target.</span></div>
            </div>
        </div>
        <div class="col-lg-7 register-card">
            <a href="{{ url_for('index') }}" class="btn btn-link px-0 text-decoration-none back-link"><i class="bi bi-arrow-left"></i> Back to home</a>
            <h2 class="fw-bold mt-2">Customer Registration</h2>
            <p class="text-muted">Create a customer account to start tracking consumption and billing summaries.</p>
            {% if error %}<div class="alert alert-danger">{{ error }}</div>{% endif %}
            <form method="POST" class="row g-3">
                <div class="col-md-6"><label class="form-label">Username</label><input type="text" name="username" class="form-control" required></div>
                <div class="col-md-6"><label class="form-label">Email</label><input type="email" name="email" class="form-control" required></div>
                <div class="col-md-6"><label class="form-label">KPLC Meter Number</label><input type="text" name="meter_number" maxlength="11" value="{{ generated_meter or '' }}" class="form-control" required></div>
                <div class="col-md-3"><label class="form-label">Country Code</label><select name="country_code" class="form-control" required>{% for item in phone_country_codes %}<option value="{{ item.code }}" {% if item.code == selected_country_code %}selected{% endif %}>{{ item.label }}</option>{% endfor %}</select></div>
                <div class="col-md-3"><label class="form-label">Phone Number</label><input type="text" name="phone_number" maxlength="10" value="{{ phone_number or '7000000000' }}" class="form-control" placeholder="10 digits" required></div>
                <div class="col-md-6"><label class="form-label">Password</label><input type="password" name="password" class="form-control" required></div>
                <div class="col-md-6"><label class="form-label">Confirm Password</label><input type="password" name="confirm_password" class="form-control" required></div>
                <div class="col-12"><button type="submit" class="btn btn-dark w-100 btn-lg">Create Customer Account</button></div>
            </form>
            <div class="helper-box"><span class="text-muted">Already registered?</span> <a href="{{ url_for('login') }}" class="text-decoration-none fw-semibold">Log in here</a><div class="small text-muted mt-2">A valid 11-digit test meter number is generated automatically and can be changed if needed.</div></div>
        </div>
    </div>
</body>
</html>
"""

dashboard_template = """<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>EcoPulse Dashboard</title><link rel="icon" type="image/svg+xml" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Crect width='64' height='64' rx='16' fill='%23062f2f'/%3E%3Cpath d='M35 6 18 34h11l-4 24 21-31H34z' fill='%23f59e0b'/%3E%3C/svg%3E"><link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css"><link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.0/font/bootstrap-icons.css"><style>*{margin:0;padding:0;box-sizing:border-box}body{background:linear-gradient(135deg, #667eea 0%, #764ba2 100%);min-height:100vh;font-family:'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;padding-top:80px;padding-bottom:30px}.navbar{background:linear-gradient(135deg, #667eea 0%, #764ba2 100%);box-shadow:0 5px 20px rgba(0,0,0,0.2)}.navbar-brand{font-weight:700;font-size:1.5rem}.header-section{text-align:center;margin-bottom:40px;color:white}.header-section h1{font-size:3rem;font-weight:700;margin-bottom:10px;text-shadow:2px 2px 4px rgba(0,0,0,0.3)}.role-badge{display:inline-block;padding:5px 15px;border-radius:20px;font-size:0.9rem;font-weight:600;margin-top:10px}.role-customer{background-color:#00b894;color:white}.role-admin{background-color:#ff6b6b;color:white}.role-examiner{background-color:#ff9800;color:white}.card{border:none;border-radius:15px;box-shadow:0 10px 30px rgba(0,0,0,0.2);margin-bottom:30px;transition:transform 0.3s ease, box-shadow 0.3s ease}.card:hover{transform:translateY(-5px);box-shadow:0 15px 40px rgba(0,0,0,0.3)}.card-header{border-radius:15px 15px 0 0;padding:20px;font-weight:600;font-size:1.2rem;display:flex;align-items:center;gap:10px;color:white}.card-header.bg-primary{background:linear-gradient(135deg, #667eea 0%, #764ba2 100%) !important}.card-header.bg-info{background:linear-gradient(135deg, #00d4ff 0%, #0099ff 100%) !important}.card-header.bg-warning{background:linear-gradient(135deg, #ffc107 0%, #ff9800 100%) !important}.card-header.bg-success{background:linear-gradient(135deg, #00b894 0%, #00cec9 100%) !important}.card-header.bg-secondary{background:linear-gradient(135deg, #6c757d 0%, #495057 100%) !important}.card-body{padding:30px}.stats-grid{display:grid;grid-template-columns:repeat(auto-fit, minmax(250px, 1fr));gap:20px;margin-bottom:30px}.stat-card{background:white;padding:20px;border-radius:10px;box-shadow:0 5px 15px rgba(0,0,0,0.1);text-align:center}.stat-value{font-size:2.5rem;font-weight:700;color:#667eea}.stat-label{color:#666;font-size:0.9rem;margin-top:10px}.stat-icon{font-size:2rem;margin-bottom:10px;color:#667eea}.form-control,.form-select{border-radius:8px;border:2px solid #e0e0e0;padding:12px 15px}.form-control:focus,.form-select:focus{border-color:#667eea;box-shadow:0 0 0 0.2rem rgba(102,126,234,0.25)}.btn{border-radius:8px;padding:10px 20px;font-weight:600;transition:all 0.3s ease}.btn-success{background:linear-gradient(135deg, #00b894 0%, #00cec9 100%);border:none;color:white}.btn-success:hover{background:linear-gradient(135deg, #00a884 0%, #00beb9 100%)}.btn-primary{background:linear-gradient(135deg, #667eea 0%, #764ba2 100%);border:none;color:white}.btn-warning{background:linear-gradient(135deg, #ffc107 0%, #ff9800 100%);border:none;color:white}.btn-danger{background:linear-gradient(135deg, #ff6b6b 0%, #ee5a6f 100%);border:none;color:white}.btn-sm{padding:5px 10px;font-size:0.875rem}.alert{border-radius:10px;border:none;margin-bottom:20px}.table{color:#333}.table thead{background:#f5f5f5;font-weight:600}.table tbody tr:hover{background-color:#f9f9f9}.no-data{text-align:center;padding:30px;color:#999;font-style:italic}.img-fluid{border-radius:10px;box-shadow:0 5px 15px rgba(0,0,0,0.1);max-width:100%;height:auto}.employee-info{background:rgba(255,255,255,0.1);padding:10px;border-radius:10px;margin-top:10px;color:white;font-size:0.9rem}.employee-info i{margin-right:5px}@media (max-width:768px){body{padding-top:100px}.header-section h1{font-size:2rem}.stats-grid{grid-template-columns:1fr}}</style></head><body><nav class="navbar navbar-expand-lg navbar-dark fixed-top"><div class="container"><a class="navbar-brand" href="{{ url_for('dashboard') }}"><i class="bi bi-lightning-fill"></i> EcoPulse</a><button class="navbar-toggler" type="button" data-bs-toggle="collapse" data-bs-target="#navbarNav"><span class="navbar-toggler-icon"></span></button><div class="collapse navbar-collapse" id="navbarNav"><ul class="navbar-nav ms-auto"><li class="nav-item"><a class="nav-link" href="{{ url_for('dashboard') }}"><i class="bi bi-house"></i> Dashboard</a></li><li class="nav-item"><a class="nav-link" href="{{ url_for('settings') }}"><i class="bi bi-gear"></i> Settings</a></li>{% if current_user.role == 'admin' %}<li class="nav-item"><a class="nav-link" href="{{ url_for('admin_financial') }}"><i class="bi bi-cash-stack"></i> Financial</a></li>{% endif %}{% if current_user.role == 'examiner' %}<li class="nav-item"><a class="nav-link" href="{{ url_for('examiner_dashboard') }}"><i class="bi bi-clipboard-data"></i> Examiner</a></li>{% endif %}<li class="nav-item dropdown"><a class="nav-link dropdown-toggle" href="#" id="navbarDropdown" role="button" data-bs-toggle="dropdown"><i class="bi bi-person-circle"></i> {{ current_user.username }}</a><ul class="dropdown-menu dropdown-menu-end"><li><a class="dropdown-item" href="{{ url_for('logout') }}"><i class="bi bi-box-arrow-right"></i> Logout</a></li></ul></li></ul></div></div></nav><div class="container"><div class="header-section"><h1><i class="bi bi-lightning-fill"></i> EcoPulse</h1><p>Welcome, {{ current_user.username }}!</p>{% if current_user.role == 'admin' %}<span class="role-badge role-admin"><i class="bi bi-shield-fill"></i> Administrator</span>{% elif current_user.role == 'examiner' %}<span class="role-badge role-examiner"><i class="bi bi-eye-fill"></i> Examiner</span>{% else %}<span class="role-badge role-customer"><i class="bi bi-person-fill"></i> Customer</span>{% endif %}{% if current_user.employee_id %}<div class="employee-info"><i class="bi bi-building"></i> Employee ID: {{ current_user.employee_id }} | <i class="bi bi-diagram-3"></i> {{ current_user.department or 'General' }}</div>{% endif %}</div>{% if message %}<div class="alert alert-success"><i class="bi bi-check-circle"></i> {{ message }}</div>{% endif %}{% if analytics %}<div class="stats-grid"><div class="stat-card"><div class="stat-icon"><i class="bi bi-lightning-charge"></i></div><div class="stat-label">Total</div><div class="stat-value">{{ analytics.total_kwh }}</div><small>kWh</small></div><div class="stat-card"><div class="stat-icon"><i class="bi bi-graph-up"></i></div><div class="stat-label">Average</div><div class="stat-value">{{ analytics.avg_kwh }}</div><small>kWh</small></div><div class="stat-card"><div class="stat-icon"><i class="bi bi-cash-coin"></i></div><div class="stat-label">Total Cost</div><div class="stat-value">{{ analytics.currency }} {{ analytics.total_cost }}</div><small>Est.</small></div><div class="stat-card"><div class="stat-icon"><i class="bi bi-cloud"></i></div><div class="stat-label">CO2</div><div class="stat-value">{{ analytics.total_co2 }}</div><small>kg</small></div></div>{% endif %}<div class="card"><div class="card-header bg-primary"><i class="bi bi-plus-circle"></i> Add Reading</div><div class="card-body"><form method="POST" action="{{ url_for('add_reading') }}"><div class="row"><div class="col-md-4 mb-3"><label class="form-label">Month</label><input type="text" name="date" class="form-control" placeholder="e.g. January" required></div><div class="col-md-4 mb-3"><label class="form-label">kWh</label><input type="number" name="kwh" class="form-control" placeholder="e.g. 520" step="0.01" required></div><div class="col-md-4 mb-3"><label class="form-label">Timestamp</label><input type="datetime-local" name="timestamp" class="form-control" required></div></div><button type="submit" class="btn btn-success"><i class="bi bi-check-circle"></i> Submit</button></form></div></div><div class="row mb-4"><div class="col-md-6"><div class="card"><div class="card-header bg-info"><i class="bi bi-funnel"></i> Filter</div><div class="card-body"><form method="GET" action="{{ url_for('dashboard') }}" class="row g-3"><div class="col-md-4"><label class="form-label">Start</label><input type="date" name="start_date" class="form-control"></div><div class="col-md-4"><label class="form-label">End</label><input type="date" name="end_date" class="form-control"></div><div class="col-md-4"><label class="form-label">Days</label><select name="days" class="form-select"><option value="">All</option><option value="7">7 days</option><option value="30">30 days</option><option value="90">90 days</option></select></div><div class="col-md-12 mt-2"><button type="submit" class="btn btn-primary w-100">Filter</button></div></form></div></div></div><div class="col-md-6"><div class="card"><div class="card-header bg-warning"><i class="bi bi-send"></i> Submit to Admin</div><div class="card-body text-center"><p>Submit your consumption summary to admin for verification and comparison</p><button class="btn btn-warning w-100" onclick="submitToAdmin()"><i class="bi bi-send"></i> Submit My Consumption</button></div></div></div></div><div class="card"><div class="card-header bg-warning"><i class="bi bi-bar-chart"></i> Consumption Analysis</div><div class="card-body">{% if chart %}<img src="data:image/png;base64,{{ chart }}" class="img-fluid" alt="Consumption Chart">{% else %}<p class="no-data">No chart available. Add some readings to see visualization.</p>{% endif %}</div></div><div class="card"><div class="card-header bg-secondary"><i class="bi bi-table"></i> Readings</div><div class="card-body">{% if readings %}<div class="table-responsive"><table class="table table-hover"><thead><tr><th>Period</th><th>kWh</th><th>Cost</th><th>CO2</th><th>Status</th><th>Timestamp</th><th>Actions</th></tr></thead><tbody>{% for reading in readings %}<tr><td><strong>{{ reading.date }}</strong></td><td><span class="badge {% if reading.kwh > current_user.threshold %}bg-danger{% else %}bg-success{% endif %}">{{ reading.kwh }}</span></td><td>{{ "%.2f"|format(reading.kwh * current_user.unit_cost) }}</td><td>{{ "%.2f"|format(reading.kwh * 0.385) }}</td><td>{% if reading.is_approved %}<span class="badge bg-success">Approved</span>{% elif reading.is_reviewed %}<span class="badge bg-info">Reviewed</span>{% else %}<span class="badge bg-warning">Pending</span>{% endif %}</td><td><small>{{ reading.timestamp.strftime('%Y-%m-%d %H:%M') }}</small></td><td><button class="btn btn-warning btn-sm" data-bs-toggle="modal" data-bs-target="#editModal{{ reading.id }}"><i class="bi bi-pencil"></i></button><form method="POST" action="{{ url_for('delete_reading', reading_id=reading.id) }}" style="display: inline;" onsubmit="return confirm('Delete?');"><button type="submit" class="btn btn-danger btn-sm"><i class="bi bi-trash"></i></button></form></td></tr><div class="modal fade" id="editModal{{ reading.id }}" tabindex="-1"><div class="modal-dialog"><div class="modal-content"><div class="modal-header"><h5 class="modal-title">Edit</h5><button type="button" class="btn-close" data-bs-dismiss="modal"></button></div><form method="POST" action="{{ url_for('update_reading', reading_id=reading.id) }}"><div class="modal-body"><div class="mb-3"><label class="form-label">Period</label><input type="text" name="date" class="form-control" value="{{ reading.date }}" required></div><div class="mb-3"><label class="form-label">kWh</label><input type="number" name="kwh" class="form-control" value="{{ reading.kwh }}" step="0.01" required></div><div class="mb-3"><label class="form-label">Timestamp</label><input type="datetime-local" name="timestamp" class="form-control" value="{{ reading.timestamp.strftime('%Y-%m-%dT%H:%M') }}" required></div></div><div class="modal-footer"><button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancel</button><button type="submit" class="btn btn-success">Update</button></div></form></div></div></div>{% endfor %}</tbody></table></div>{% else %}<p class="no-data">No readings yet. Add your first reading above.</p>{% endif %}</div></div><div class="card"><div class="card-header bg-success"><i class="bi bi-download"></i> Export</div><div class="card-body"><div class="row g-3"><div class="col-md-6"><a href="{{ url_for('export_csv') }}" class="btn btn-success w-100"><i class="bi bi-file-earmark-spreadsheet"></i> CSV</a></div><div class="col-md-6"><a href="{{ url_for('export_pdf') }}" class="btn btn-danger w-100"><i class="bi bi-file-pdf"></i> PDF</a></div></div></div></div>{% if reports %}<div class="card"><div class="card-header bg-info"><i class="bi bi-envelope"></i> Recent Reports</div><div class="card-body"><div class="list-group">{% for report in reports %}<a href="#" class="list-group-item list-group-item-action"><div class="d-flex w-100 justify-content-between"><h6 class="mb-1">{{ report.title }}</h6><small>{{ report.created_at.strftime('%Y-%m-%d') }}</small></div><p class="mb-1">{{ report.content|safe }}</p></a>{% endfor %}</div></div></div>{% endif %}</div><script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script><script>const now=new Date();now.setMinutes(now.getMinutes()-now.getTimezoneOffset());const ts=document.querySelector('input[name="timestamp"]');if(ts)ts.value=now.toISOString().slice(0,16);function submitToAdmin(){fetch('/submit_to_admin',{method:'POST'}).then(r=>r.json()).then(d=>{alert(d.message);if(d.success){location.reload();}});}</script></body></html>"""

settings_template = """<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>Settings - EcoPulse</title><link rel="icon" type="image/svg+xml" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Crect width='64' height='64' rx='16' fill='%23062f2f'/%3E%3Cpath d='M35 6 18 34h11l-4 24 21-31H34z' fill='%23f59e0b'/%3E%3C/svg%3E"><link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css"><link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.0/font/bootstrap-icons.css"><style>body{background:linear-gradient(135deg, #667eea 0%, #764ba2 100%);min-height:100vh;font-family:'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;padding-top:80px;padding-bottom:30px}.navbar{background:linear-gradient(135deg, #667eea 0%, #764ba2 100%);box-shadow:0 5px 20px rgba(0,0,0,0.2)}.container{max-width:800px}.card{border:none;border-radius:15px;box-shadow:0 10px 30px rgba(0,0,0,0.2);margin-bottom:30px}.card-header{background:linear-gradient(135deg, #667eea 0%, #764ba2 100%);color:white;border-radius:15px 15px 0 0;padding:20px;font-weight:600;font-size:1.2rem}.card-body{padding:30px}.form-control,.form-select{border-radius:8px;border:2px solid #e0e0e0;padding:12px 15px}.form-control:focus,.form-select:focus{border-color:#667eea;box-shadow:0 0 0 0.2rem rgba(102,126,234,0.25)}.btn{border-radius:8px;padding:10px 20px;font-weight:600}.btn-primary{background:linear-gradient(135deg, #667eea 0%, #764ba2 100%);border:none;color:white}.btn-secondary{background:linear-gradient(135deg, #a4a4a4 0%, #797979 100%);border:none;color:white}.form-label{font-weight:600;color:#333}.settings-section{margin-bottom:30px;padding-bottom:30px;border-bottom:2px solid #e0e0e0}.settings-section:last-child{border-bottom:none}.settings-title{font-size:1.3rem;font-weight:700;color:#333;margin-bottom:20px;display:flex;align-items:center;gap:10px}.info-badge{background:#e8f4f8;border-left:4px solid #667eea;padding:15px;border-radius:10px;margin-bottom:20px}.switch-container{display:flex;align-items:center;justify-content:space-between;padding:15px;background:#f8f9fa;border-radius:10px;margin-bottom:15px}.switch-label{font-weight:600;color:#333}.switch-description{font-size:0.85rem;color:#666;margin-top:5px}.overage-rate{background:linear-gradient(135deg, #00b894 0%, #00cec9 100%);color:white;padding:10px 15px;border-radius:10px;margin-top:10px}.overage-rate small{color:rgba(255,255,255,0.9)}</style></head><body><nav class="navbar navbar-expand-lg navbar-dark fixed-top"><div class="container"><a class="navbar-brand" href="{{ url_for('dashboard') }}"><i class="bi bi-lightning-fill"></i> EcoPulse</a><div class="navbar-nav ms-auto"><a class="nav-link" href="{{ url_for('dashboard') }}"><i class="bi bi-arrow-left"></i> Back</a></div></div></nav><div class="container"><div class="card"><div class="card-header"><i class="bi bi-gear"></i> Settings</div><div class="card-body">{% if message %}<div class="alert alert-success"><i class="bi bi-check-circle"></i> {{ message }}</div>{% endif %}<form method="POST"><div class="settings-section"><div class="settings-title"><i class="bi bi-speedometer2"></i> Threshold Settings</div><div class="row"><div class="col-md-12 mb-3"><label class="form-label">Monthly Threshold (kWh)</label><input type="number" name="threshold" class="form-control" value="{{ current_user.threshold }}" step="10" required><small class="text-muted">Set your monthly energy consumption limit. You'll be notified when approaching this limit.</small></div></div></div><div class="settings-section"><div class="settings-title"><i class="bi bi-shield-check"></i> Auto-Switch Protection Mode</div><div class="info-badge"><i class="bi bi-info-circle-fill"></i> <strong>How it works:</strong> When your consumption exceeds the threshold, you can choose how EcoPulse responds.</div><div class="switch-container"><div><div class="switch-label"><i class="bi bi-arrow-repeat"></i> Enable Auto-Switch to Overage Mode</div><div class="switch-description">When enabled, exceeding threshold automatically switches to overage billing (extra charges apply). When disabled, protect mode activates with alerts and possible shutdown.</div></div><div class="form-check form-switch"><input class="form-check-input" type="checkbox" name="allow_overage" id="allowOverage" style="width: 3em; height: 1.5em;" {% if user_settings.allow_overage %}checked{% endif %} onchange="updateOverageInfo()"></div></div>{% if user_settings.allow_overage %}<div class="overage-rate" id="overageInfo"><i class="bi bi-cash-stack"></i> <strong>Overage Mode Active</strong><br><small>When you exceed your {{ current_user.threshold }} kWh threshold, extra usage will be billed at <strong>{{ current_user.unit_cost * 0.15 }} Ksh extra per kWh</strong> (15% surcharge).</small></div>{% else %}<div class="overage-rate" id="overageInfo" style="background: linear-gradient(135deg, #ff6b6b 0%, #ee5a6f 100%);"><i class="bi bi-shield-lock-fill"></i> <strong>Protect Mode Active</strong><br><small>When you exceed your {{ current_user.threshold }} kWh threshold, EcoPulse will send alerts and schedule automatic shutdown reminders. No extra charges will be applied.</small></div>{% endif %}</div><div class="settings-section"><div class="settings-title"><i class="bi bi-power"></i> Automatic Shutdown Settings</div><div class="switch-container"><div><div class="switch-label"><i class="bi bi-clock-history"></i> Enable Automatic Shutdown Reminders</div><div class="switch-description">When protect mode is active and threshold is exceeded, automatically schedule shutdown reminders.</div></div><div class="form-check form-switch"><input class="form-check-input" type="checkbox" name="auto_shutdown_enabled" id="autoShutdown" style="width: 3em; height: 1.5em;" {% if user_settings.auto_shutdown_enabled %}checked{% endif %}></div></div><div class="row mt-3"><div class="col-md-12"><label class="form-label">Shutdown Delay (minutes)</label><input type="number" name="shutdown_delay_minutes" class="form-control" value="{{ user_settings.shutdown_delay_minutes or 5 }}" min="1" max="60"><small class="text-muted">Minutes after threshold exceedance before shutdown reminder is sent (only in protect mode).</small></div></div></div><div class="settings-section"><div class="settings-title"><i class="bi bi-cash-coin"></i> Cost Settings</div><div class="row"><div class="col-md-6 mb-3"><label class="form-label">Currency</label><select name="currency" class="form-select"><option value="USD" {% if current_user.currency == 'USD' %}selected{% endif %}>USD</option><option value="EUR" {% if current_user.currency == 'EUR' %}selected{% endif %}>EUR</option><option value="GBP" {% if current_user.currency == 'GBP' %}selected{% endif %}>GBP</option><option value="INR" {% if current_user.currency == 'INR' %}selected{% endif %}>INR</option><option value="Ksh" {% if current_user.currency == 'Ksh' %}selected{% endif %}>Ksh</option></select></div><div class="col-md-6 mb-3"><label class="form-label">Base Cost/kWh</label><input type="number" name="unit_cost" class="form-control" value="{{ current_user.unit_cost }}" step="0.01" required><small class="text-muted">Base rate per kilowatt-hour</small></div></div></div><div class="settings-section"><div class="settings-title"><i class="bi bi-bell"></i> Notification Settings</div><div class="mb-3"><div class="form-check form-switch"><input class="form-check-input" type="checkbox" name="alert_email" id="alertEmail" {% if current_user.alert_email %}checked{% endif %}><label class="form-check-label" for="alertEmail">Email Alerts</label></div><small class="text-muted">Receive email notifications when your consumption approaches or exceeds threshold.</small></div></div>{% if current_user.role in ['admin', 'examiner'] %}<div class="settings-section"><div class="settings-title"><i class="bi bi-building"></i> Employee Information</div><div class="row"><div class="col-md-6 mb-3"><label class="form-label">Employee ID</label><input type="text" class="form-control" value="{{ current_user.employee_id or 'Not assigned' }}" readonly></div><div class="col-md-6 mb-3"><label class="form-label">Department</label><input type="text" class="form-control" value="{{ current_user.department or 'Not specified' }}" readonly></div></div></div>{% endif %}<div class="d-flex gap-3"><button type="submit" class="btn btn-primary"><i class="bi bi-check-circle"></i> Save Settings</button><a href="{{ url_for('dashboard') }}" class="btn btn-secondary"><i class="bi bi-x-circle"></i> Cancel</a></div></form></div></div></div><script>function updateOverageInfo(){const checkbox=document.getElementById('allowOverage');const overageInfo=document.getElementById('overageInfo');const threshold={{ current_user.threshold }};const surcharge={{ current_user.unit_cost * 0.15 }};if(checkbox.checked){overageInfo.style.background='linear-gradient(135deg, #00b894 0%, #00cec9 100%)';overageInfo.innerHTML='<i class="bi bi-cash-stack"></i> <strong>Overage Mode Active</strong><br><small>When you exceed your '+threshold+' kWh threshold, extra usage will be billed at <strong>'+surcharge.toFixed(2)+' Ksh extra per kWh</strong> (15% surcharge).</small>';}else{overageInfo.style.background='linear-gradient(135deg, #ff6b6b 0%, #ee5a6f 100%)';overageInfo.innerHTML='<i class="bi bi-shield-lock-fill"></i> <strong>Protect Mode Active</strong><br><small>When you exceed your '+threshold+' kWh threshold, EcoPulse will send alerts and schedule automatic shutdown reminders. No extra charges will be applied.</small>';}}</script><script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script></body></html>"""

examiner_template = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=yes, viewport-fit=cover">
    <title>Examiner Dashboard - EcoPulse</title>
    <link rel="icon" type="image/svg+xml" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Crect width='64' height='64' rx='16' fill='%23062f2f'/%3E%3Cpath d='M35 6 18 34h11l-4 24 21-31H34z' fill='%23f59e0b'/%3E%3C/svg%3E">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.0/font/bootstrap-icons.css">
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        /* Mobile Responsive Styles - Works on all devices */
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            padding-top: 70px;
            padding-bottom: 30px;
            overflow-x: hidden;
        }

        /* Responsive Navbar */
        .navbar {
            background: linear-gradient(135deg, #f39c12 0%, #e67e22 100%);
            box-shadow: 0 5px 20px rgba(0,0,0,0.2);
            padding: 10px 16px;
        }

        .navbar-brand {
            font-size: 1.1rem;
            font-weight: 700;
        }

        .navbar-toggler {
            border: none;
            padding: 6px 10px;
        }

        .navbar-toggler:focus {
            box-shadow: none;
        }

        .navbar-nav .nav-link {
            padding: 8px 12px;
            font-size: 0.9rem;
        }

        /* Responsive Cards */
        .card {
            border: none;
            border-radius: 15px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.2);
            margin-bottom: 20px;
        }

        .card-header {
            background: linear-gradient(135deg, #f39c12 0%, #e67e22 100%);
            color: white;
            border-radius: 15px 15px 0 0;
            padding: 15px 20px;
            font-weight: 600;
            font-size: 1rem;
        }

        .card-header i {
            font-size: 1.1rem;
        }

        .card-body {
            padding: 20px;
        }

        /* Responsive Stats Grid */
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 15px;
            margin-bottom: 20px;
        }

        .stat-card {
            background: white;
            padding: 15px;
            border-radius: 12px;
            box-shadow: 0 5px 15px rgba(0,0,0,0.1);
            text-align: center;
        }

        .stat-value {
            font-size: 1.5rem;
            font-weight: 700;
            color: #f39c12;
        }

        .stat-label {
            font-size: 0.75rem;
            color: #666;
            margin-top: 5px;
        }

        .stat-icon i {
            font-size: 1.5rem;
        }

        /* Responsive Row */
        .row {
            margin-left: -10px;
            margin-right: -10px;
        }

        .row > [class*="col-"] {
            padding-left: 10px;
            padding-right: 10px;
        }

        /* Responsive Tables */
        .table-responsive {
            border-radius: 12px;
            overflow-x: auto;
            -webkit-overflow-scrolling: touch;
        }

        .table {
            min-width: 600px;
        }

        .table th, .table td {
            padding: 10px;
            font-size: 0.85rem;
            white-space: nowrap;
        }

        /* Responsive Forms */
        .form-control, .form-select {
            border-radius: 10px;
            padding: 10px 12px;
            font-size: 0.9rem;
        }

        /* Responsive Buttons */
        .btn {
            border-radius: 10px;
            padding: 10px 16px;
            font-weight: 600;
            font-size: 0.85rem;
            width: 100%;
            margin-bottom: 8px;
        }

        .btn-sm {
            padding: 6px 12px;
            font-size: 0.75rem;
        }

        /* Responsive Charts */
        .chart-container {
            position: relative;
            height: 250px;
            width: 100%;
            margin-bottom: 20px;
        }

        canvas {
            max-width: 100%;
            height: auto;
        }

        /* AI Assistant Responsive */
        .assistant-scroll {
            max-height: 300px;
            overflow-y: auto;
            background: #f8fafc;
            border-radius: 16px;
            padding: 15px;
            border: 1px solid rgba(15,23,42,.08);
        }

        .assistant-message-user {
            background: #667eea;
            color: white;
            padding: 8px 12px;
            border-radius: 18px;
            margin-bottom: 10px;
            text-align: right;
            font-size: 0.85rem;
        }

        .assistant-message-bot {
            background: #e2e8f0;
            color: #1e293b;
            padding: 8px 12px;
            border-radius: 18px;
            margin-bottom: 10px;
            font-size: 0.85rem;
        }

        /* Responsive Metric Box */
        .metric-box {
            background: linear-gradient(135deg, #00b894 0%, #00cec9 100%);
            color: white;
            padding: 12px;
            border-radius: 10px;
            text-align: center;
            margin-bottom: 12px;
        }

        .metric-value {
            font-size: 1.3rem;
            font-weight: 700;
        }

        .metric-label {
            font-size: 0.7rem;
            opacity: 0.9;
        }

        /* Tariff Badge */
        .tariff-badge {
            background: #ff6b6b;
            color: white;
            padding: 10px;
            border-radius: 10px;
            text-align: center;
            margin-bottom: 15px;
            font-size: 0.85rem;
        }

        /* Status Badges */
        .badge {
            padding: 4px 8px;
            font-size: 0.7rem;
            border-radius: 20px;
        }

        /* Modal Responsive */
        .modal-dialog {
            margin: 10px;
        }

        .modal-content {
            border-radius: 15px;
        }

        .modal-body {
            padding: 15px;
        }

        /* Header Section */
        .header-section {
            text-align: center;
            margin-bottom: 20px;
        }

        .header-section h1 {
            font-size: 1.5rem;
            font-weight: 700;
        }

        .header-section p {
            font-size: 0.85rem;
        }

        /* Alert Responsive */
        .alert {
            padding: 10px 15px;
            font-size: 0.85rem;
            border-radius: 10px;
        }

        /* Small screens (phones) */
        @media (max-width: 576px) {
            body {
                padding-top: 60px;
                padding-left: 10px;
                padding-right: 10px;
            }

            .navbar-brand {
                font-size: 1rem;
            }

            .card-header {
                padding: 12px 15px;
                font-size: 0.9rem;
            }

            .card-body {
                padding: 15px;
            }

            .stats-grid {
                grid-template-columns: repeat(2, 1fr);
                gap: 10px;
            }

            .stat-card {
                padding: 10px;
            }

            .stat-value {
                font-size: 1.2rem;
            }

            .stat-label {
                font-size: 0.65rem;
            }

            .btn {
                padding: 8px 12px;
                font-size: 0.8rem;
            }

            .header-section h1 {
                font-size: 1.3rem;
            }

            .chart-container {
                height: 200px;
            }

            .metric-value {
                font-size: 1.1rem;
            }

            .table th, .table td {
                padding: 8px;
                font-size: 0.75rem;
            }
        }

        /* Medium screens (tablets) */
        @media (min-width: 577px) and (max-width: 768px) {
            .stats-grid {
                grid-template-columns: repeat(3, 1fr);
            }

            .btn {
                width: auto;
                min-width: 120px;
            }

            .chart-container {
                height: 280px;
            }
        }

        /* Large screens (desktops) */
        @media (min-width: 769px) {
            .stats-grid {
                grid-template-columns: repeat(4, 1fr);
            }

            .btn {
                width: auto;
            }

            .chart-container {
                height: 350px;
            }

            .card-header {
                font-size: 1.1rem;
            }

            .stat-value {
                font-size: 1.8rem;
            }
        }

        /* Touch-friendly adjustments */
        @media (hover: none) and (pointer: coarse) {
            .btn, .nav-link, .clickable {
                min-height: 44px;
            }

            input, select, textarea {
                font-size: 16px;
            }
        }

        /* Loading spinner */
        .spinner-border-sm {
            width: 1rem;
            height: 1rem;
        }

        /* Custom scrollbar */
        ::-webkit-scrollbar {
            width: 6px;
            height: 6px;
        }

        ::-webkit-scrollbar-track {
            background: #f1f1f1;
            border-radius: 10px;
        }

        ::-webkit-scrollbar-thumb {
            background: #f39c12;
            border-radius: 10px;
        }

        /* Utility classes */
        .text-truncate-mobile {
            white-space: normal;
            word-break: break-word;
        }

        @media (max-width: 576px) {
            .text-truncate-mobile {
                white-space: nowrap;
                overflow: hidden;
                text-overflow: ellipsis;
            }
        }
    </style>
</head>
<body>
    <nav class="navbar navbar-expand-lg navbar-dark fixed-top">
        <div class="container-fluid px-2 px-sm-3 px-md-4">
            <a class="navbar-brand" href="{{ url_for('examiner_dashboard') }}">
                <i class="bi bi-clipboard-data"></i> <span class="d-none d-sm-inline">EcoPulse Examiner</span>
                <span class="d-inline d-sm-none">Examiner</span>
            </a>
            <button class="navbar-toggler" type="button" data-bs-toggle="collapse" data-bs-target="#examinerNav">
                <span class="navbar-toggler-icon"></span>
            </button>
            <div class="collapse navbar-collapse" id="examinerNav">
                <div class="navbar-nav ms-auto">
                    <a class="nav-link" href="{{ url_for('dashboard') }}">
                        <i class="bi bi-house"></i> <span class="d-none d-sm-inline">Dashboard</span>
                    </a>
                    <a class="nav-link" href="{{ url_for('ai_analysis') }}">
                        <i class="bi bi-robot"></i> <span class="d-none d-sm-inline">AI Analysis</span>
                    </a>
                    <a class="nav-link" href="{{ url_for('logout') }}">
                        <i class="bi bi-box-arrow-right"></i> <span class="d-none d-sm-inline">Logout</span>
                    </a>
                </div>
            </div>
        </div>
    </nav>

    <div class="container-fluid px-2 px-sm-3 px-md-4">
        <div class="header-section">
            <h1><i class="bi bi-graph-up"></i> Examiner Dashboard</h1>
            <p>Review approved customer consumption, send invoices, and manage financial reporting</p>
        </div>

        {% with messages = get_flashed_messages(with_categories=true) %}
            {% for category, msg in messages %}
                <div class="alert alert-{{ 'warning' if category == 'warning' else 'info' }} alert-dismissible fade show">
                    <i class="bi bi-info-circle"></i> {{ msg }}
                    <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
                </div>
            {% endfor %}
        {% endwith %}

        <!-- Current Tariff Display -->
        <div class="tariff-badge">
            <i class="bi bi-tag"></i> <strong>Current KPLC Tariff:</strong> 
            {% if current_tariff %}
                Ksh {{ "%.2f"|format(current_tariff.cost_per_unit) }} per unit 
                (Effective: {{ current_tariff.effective_date }})
            {% else %}
                Ksh {{ "%.2f"|format(default_unit_cost) }} per unit
            {% endif %}
        </div>

        <!-- Summary Stats -->
        <div class="stats-grid">
            <div class="stat-card">
                <div class="stat-icon"><i class="bi bi-people"></i></div>
                <div class="stat-value">{{ consumption_stats.total_customers }}</div>
                <div class="stat-label">Active Customers</div>
            </div>
            <div class="stat-card">
                <div class="stat-icon"><i class="bi bi-lightning"></i></div>
                <div class="stat-value">{{ "%.0f"|format(consumption_stats.total_consumption) }}</div>
                <div class="stat-label">Total kWh</div>
            </div>
            <div class="stat-card">
                <div class="stat-icon"><i class="bi bi-cash"></i></div>
                <div class="stat-value">Ksh {{ "%.0f"|format(consumption_stats.total_revenue) }}</div>
                <div class="stat-label">Total Revenue</div>
            </div>
            <div class="stat-card">
                <div class="stat-icon"><i class="bi bi-cloud"></i></div>
                <div class="stat-value">{{ "%.0f"|format(consumption_stats.total_co2) }}</div>
                <div class="stat-label">CO2 (kg)</div>
            </div>
        </div>

        <!-- Reading Stats Summary -->
        <div class="row g-2 mb-4">
            <div class="col-6 col-md-3">
                <div class="card bg-light">
                    <div class="card-body text-center p-2 p-md-3">
                        <h6 class="mb-1">Approved Customers</h6>
                        <h4 class="text-success mb-0">{{ consumption_stats.approved_customers }}</h4>
                    </div>
                </div>
            </div>
            <div class="col-6 col-md-3">
                <div class="card bg-light">
                    <div class="card-body text-center p-2 p-md-3">
                        <h6 class="mb-1">Pending Invoices</h6>
                        <h4 class="text-warning mb-0">{{ consumption_stats.pending_invoices }}</h4>
                    </div>
                </div>
            </div>
            <div class="col-6 col-md-3">
                <div class="card bg-light">
                    <div class="card-body text-center p-2 p-md-3">
                        <h6 class="mb-1">Total Paid</h6>
                        <h4 class="text-success mb-0">Ksh {{ "%.0f"|format(consumption_stats.total_collected) }}</h4>
                    </div>
                </div>
            </div>
            <div class="col-6 col-md-3">
                <div class="card bg-light">
                    <div class="card-body text-center p-2 p-md-3">
                        <h6 class="mb-1">Outstanding</h6>
                        <h4 class="text-danger mb-0">Ksh {{ "%.0f"|format(consumption_stats.total_outstanding) }}</h4>
                    </div>
                </div>
            </div>
        </div>

        <!-- Main Action Buttons -->
        <div class="row g-2 mb-4">
            <div class="col-12 col-md-4">
                <div class="card">
                    <div class="card-header">
                        <i class="bi bi-envelope"></i> Send Invoices
                    </div>
                    <div class="card-body">
                        <p class="small">Send invoices to customers with approved consumption</p>
                        <form method="POST" action="{{ url_for('examiner_send_invoice') }}">
                            <div class="mb-2">
                                <select class="form-select form-select-sm" name="customer_id" required>
                                    <option value="">Select Customer</option>
                                    {% for customer in approved_customers %}
                                        <option value="{{ customer.id }}">{{ customer.username }} - {{ "%.0f"|format(customer.approved_consumption) }} kWh</option>
                                    {% endfor %}
                                </select>
                            </div>
                            <div class="mb-2">
                                <input type="text" class="form-control form-control-sm" name="period" placeholder="Period (e.g., March 2026)" required>
                            </div>
                            <div class="mb-2">
                                <input type="number" class="form-control form-control-sm" name="total_consumption" id="invoiceConsumption" placeholder="Total Consumption (kWh)" step="0.01" required>
                            </div>
                            <div class="mb-2">
                                <input type="number" class="form-control form-control-sm" name="total_cost" id="invoiceCost" placeholder="Total Cost" step="0.01" required>
                            </div>
                            <div class="mb-2">
                                <input type="date" class="form-control form-control-sm" name="due_date" placeholder="Due Date">
                            </div>
                            <div class="mb-2">
                                <textarea class="form-control form-control-sm" name="notes" rows="2" placeholder="Additional notes"></textarea>
                            </div>
                            <button type="submit" class="btn btn-warning btn-sm w-100">
                                <i class="bi bi-send"></i> Send Invoice
                            </button>
                        </form>
                        <small class="text-muted d-block mt-2">Current tariff: {% if current_tariff %}Ksh {{ "%.2f"|format(current_tariff.cost_per_unit) }}{% else %}Ksh {{ "%.2f"|format(default_unit_cost) }}{% endif %} per unit</small>
                    </div>
                </div>
            </div>

            <div class="col-12 col-md-4">
                <div class="card">
                    <div class="card-header">
                        <i class="bi bi-file-text"></i> Send Financial Report
                    </div>
                    <div class="card-body text-center">
                        <p class="small">Generate and send income report to admin</p>
                        <button class="btn btn-primary btn-sm w-100 mb-2" onclick="sendFinancialReport()">
                            <i class="bi bi-graph-up"></i> Send Income Report
                        </button>
                        <small class="text-muted">Report includes: Revenue, Collections, Outstanding payments</small>
                    </div>
                </div>
            </div>

            <div class="col-12 col-md-4">
                <div class="card">
                    <div class="card-header">
                        <i class="bi bi-download"></i> Export
                    </div>
                    <div class="card-body text-center">
                        <p class="small">Export financial data</p>
                        <a href="{{ url_for('export_financial_csv') }}" class="btn btn-success btn-sm w-100 mb-2">
                            <i class="bi bi-file-earmark-spreadsheet"></i> Export CSV
                        </a>
                        <a href="{{ url_for('export_financial_pdf') }}" class="btn btn-danger btn-sm w-100">
                            <i class="bi bi-file-pdf"></i> Export PDF
                        </a>
                    </div>
                </div>
            </div>
        </div>

        <!-- AI Assistant Section -->
        <div class="card mb-4">
            <div class="card-header">
                <i class="bi bi-robot"></i> AI Financial Assistant
            </div>
            <div class="card-body">
                <div class="row g-3">
                    <div class="col-12 col-md-6">
                        <h6><i class="bi bi-chat-dots"></i> Ask AI Assistant</h6>
                        <div id="assistantMessages" class="assistant-scroll mb-3">
                            <div class="assistant-message-bot">
                                <strong>AI Assistant:</strong> Hello! I can help you with:
                                <ul class="mb-0 mt-2 ps-3">
                                    <li>Revenue predictions and forecasting</li>
                                    <li>Customer payment behavior analysis</li>
                                    <li>Financial advice and recommendations</li>
                                    <li>Income improvement strategies</li>
                                </ul>
                            </div>
                        </div>
                        <div class="input-group">
                            <input type="text" id="assistantInput" class="form-control form-control-sm" placeholder="e.g., Predict revenue for next quarter">
                            <button class="btn btn-warning btn-sm" onclick="askAssistant()">Ask</button>
                        </div>
                    </div>
                    <div class="col-12 col-md-6">
                        <h6><i class="bi bi-graph-up"></i> 10-Year Forecast</h6>
                        <div class="row g-2 mb-2">
                            <div class="col-6">
                                <label class="small">Past Years</label>
                                <input type="number" id="pastYears" class="form-control form-control-sm" value="10" min="1" max="10">
                            </div>
                            <div class="col-6">
                                <label class="small">Future Years</label>
                                <input type="number" id="futureYears" class="form-control form-control-sm" value="10" min="1" max="10">
                            </div>
                        </div>
                        <button class="btn btn-info btn-sm w-100 mb-2" onclick="generateForecast()">
                            <i class="bi bi-bar-chart-steps"></i> Generate Forecast
                        </button>
                        <div id="forecastSummary" class="small text-muted"></div>
                        <div class="chart-container">
                            <canvas id="forecastChart"></canvas>
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <!-- Financial Charts Section -->
        <div class="card mb-4">
            <div class="card-header">
                <i class="bi bi-pie-chart"></i> Financial Analytics
            </div>
            <div class="card-body">
                <div class="row g-3">
                    <div class="col-12 col-md-6">
                        <h6><i class="bi bi-bar-chart"></i> Revenue by Customer</h6>
                        <div class="chart-container">
                            <canvas id="revenueChart"></canvas>
                        </div>
                    </div>
                    <div class="col-12 col-md-6">
                        <h6><i class="bi bi-pie-chart-fill"></i> Payment Status</h6>
                        <div class="chart-container">
                            <canvas id="paymentChart"></canvas>
                        </div>
                    </div>
                </div>
                <div class="row mt-3">
                    <div class="col-12">
                        <h6><i class="bi bi-graph-up"></i> Revenue Trend (Last 12 Months)</h6>
                        <div class="chart-container">
                            <canvas id="revenueTrendChart"></canvas>
                        </div>
                    </div>
                </div>
            </div>
        </div>

        {% if consumption_report and consumption_report.chart %}
        <div class="card mb-4">
            <div class="card-header">
                <i class="bi bi-bar-chart"></i> Customer Consumption Analysis
            </div>
            <div class="card-body">
                <img src="data:image/png;base64,{{ consumption_report.chart }}" class="img-fluid rounded-3 w-100" alt="Consumption Report">
                <div class="row g-2 mt-3">
                    <div class="col-4">
                        <div class="card bg-light">
                            <div class="card-body text-center p-2">
                                <small>Efficient</small>
                                <h5 class="text-success mb-0">{{ consumption_report.summary.efficient_customers }}</h5>
                            </div>
                        </div>
                    </div>
                    <div class="col-4">
                        <div class="card bg-light">
                            <div class="card-body text-center p-2">
                                <small>Above Threshold</small>
                                <h5 class="text-danger mb-0">{{ consumption_report.summary.above_threshold_count }}</h5>
                            </div>
                        </div>
                    </div>
                    <div class="col-4">
                        <div class="card bg-light">
                            <div class="card-body text-center p-2">
                                <small>Below Threshold</small>
                                <h5 class="text-success mb-0">{{ consumption_report.summary.below_threshold_count }}</h5>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
        {% endif %}

        <!-- Invoices Sent -->
        <div class="card mb-4">
            <div class="card-header">
                <i class="bi bi-receipt"></i> Sent Invoices
            </div>
            <div class="card-body p-0">
                <div class="table-responsive">
                    <table class="table table-hover mb-0">
                        <thead class="table-light">
                            <tr>
                                <th>Customer</th>
                                <th>Period</th>
                                <th>Total</th>
                                <th>Status</th>
                                <th>Actions</th>
                            </tr>
                        </thead>
                        <tbody>
                            {% for invoice in sent_invoices %}
                            <tr>
                                <td>{{ invoice.user.username|truncate(15) }}</td>
                                <td>{{ invoice.period|truncate(12) }}</td>
                                <td>Ksh {{ "%.0f"|format(invoice.total_cost) }}</td>
                                <td>
                                    <span class="badge {% if invoice.payment_status == 'paid' %}bg-success{% elif invoice.payment_status == 'pending' %}bg-warning{% else %}bg-danger{% endif %}">
                                        {{ invoice.payment_status }}
                                    </span>
                                 </td>
                                <td>
                                    <button class="btn btn-sm btn-info" onclick="sendReminder({{ invoice.id }})" title="Send Reminder">
                                        <i class="bi bi-envelope"></i>
                                    </button>
                                 </td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>

        <!-- Financial Reports Sent to Admin -->
        <div class="card mb-4">
            <div class="card-header">
                <i class="bi bi-file-earmark-text"></i> Financial Reports to Admin
            </div>
            <div class="card-body p-0">
                <div class="table-responsive">
                    <table class="table table-hover mb-0">
                        <thead class="table-light">
                            <tr>
                                <th>Date</th>
                                <th>Title</th>
                                <th>Actions</th>
                            </tr>
                        </thead>
                        <tbody>
                            {% for report in financial_reports %}
                            <tr>
                                <td>{{ report.created_at.strftime('%Y-%m-%d') }}</td>
                                <td>{{ report.title|truncate(30) }}</td>
                                <td>
                                    <button class="btn btn-sm btn-primary" onclick="viewReport({{ report.id }})">
                                        <i class="bi bi-eye"></i> View
                                    </button>
                                 </td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    </div>

    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script>
    <script>
        let forecastChart = null;

        function sendFinancialReport() {
            fetch('/examiner/send_financial_report', { method: 'POST' })
                .then(response => response.json())
                .then(data => {
                    alert(data.message);
                    if (data.success) location.reload();
                });
        }

        function sendReminder(invoiceId) {
            fetch('/examiner/send_payment_reminder/' + invoiceId, { method: 'POST' })
                .then(response => response.json())
                .then(data => alert(data.message));
        }

        function viewReport(reportId) {
            window.open('/view_report/' + reportId, '_blank');
        }

        async function askAssistant() {
            const input = document.getElementById('assistantInput');
            const messages = document.getElementById('assistantMessages');
            const question = input.value.trim();
            if (!question) return;

            messages.insertAdjacentHTML('beforeend', `<div class="assistant-message-user"><strong>You:</strong> ${question}</div>`);
            input.value = '';

            const pastYears = document.getElementById('pastYears').value;
            const futureYears = document.getElementById('futureYears').value;

            const response = await fetch('/examiner/ai_assistant', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ question, past_years: pastYears, future_years: futureYears })
            });
            const data = await response.json();
            messages.insertAdjacentHTML('beforeend', `<div class="assistant-message-bot"><strong>AI Assistant:</strong> ${data.answer}</div>`);
            messages.scrollTop = messages.scrollHeight;
        }

        async function generateForecast() {
            const pastYears = document.getElementById('pastYears').value;
            const futureYears = document.getElementById('futureYears').value;

            const response = await fetch('/examiner/forecast', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ past_years: pastYears, future_years: futureYears })
            });
            const data = await response.json();

            document.getElementById('forecastSummary').innerHTML = `
                <strong>Current Year:</strong> ${data.summary.current_year} |
                <strong>Current Total:</strong> ${data.summary.current_total.toFixed(0)} kWh |
                <strong>Growth Rate:</strong> ${data.summary.growth_rate.toFixed(2)}%
            `;

            if (forecastChart) forecastChart.destroy();
            const ctx = document.getElementById('forecastChart').getContext('2d');
            forecastChart = new Chart(ctx, {
                type: 'line',
                data: {
                    labels: data.timeline.map(t => t.year),
                    datasets: [{
                        label: 'Consumption (kWh)',
                        data: data.timeline.map(t => t.value),
                        borderColor: '#f39c12',
                        backgroundColor: 'rgba(243, 156, 18, 0.1)',
                        fill: true,
                        tension: 0.4
                    }]
                },
                options: { responsive: true, maintainAspectRatio: true }
            });
        }

        // Initialize Charts
        document.addEventListener('DOMContentLoaded', function() {
            generateForecast();

            // Revenue Chart
            const revenueCtx = document.getElementById('revenueChart').getContext('2d');
            new Chart(revenueCtx, {
                type: 'bar',
                data: {
                    labels: {{ revenue_labels|tojson }},
                    datasets: [{
                        label: 'Revenue (Ksh)',
                        data: {{ revenue_data|tojson }},
                        backgroundColor: '#f39c12',
                        borderRadius: 8
                    }]
                },
                options: { responsive: true, maintainAspectRatio: true }
            });

            // Payment Chart
            const paymentCtx = document.getElementById('paymentChart').getContext('2d');
            new Chart(paymentCtx, {
                type: 'pie',
                data: {
                    labels: ['Paid', 'Pending', 'Overdue'],
                    datasets: [{
                        data: [{{ paid_count }}, {{ pending_count }}, {{ overdue_count }}],
                        backgroundColor: ['#00b894', '#f39c12', '#ff6b6b']
                    }]
                },
                options: { responsive: true, maintainAspectRatio: true }
            });

            // Revenue Trend Chart
            const trendCtx = document.getElementById('revenueTrendChart').getContext('2d');
            new Chart(trendCtx, {
                type: 'line',
                data: {
                    labels: {{ trend_labels|tojson }},
                    datasets: [{
                        label: 'Monthly Revenue (Ksh)',
                        data: {{ trend_data|tojson }},
                        borderColor: '#00b894',
                        backgroundColor: 'rgba(0, 184, 148, 0.1)',
                        fill: true,
                        tension: 0.4
                    }]
                },
                options: { responsive: true, maintainAspectRatio: true }
            });
        });

        // Auto-calculate cost based on consumption
        const tariffRate = {% if current_tariff %}{{ current_tariff.cost_per_unit }}{% else %}{{ default_unit_cost }}{% endif %};
        document.addEventListener('input', function(e) {
            if (e.target && e.target.id === 'invoiceConsumption') {
                const consumption = parseFloat(e.target.value) || 0;
                const cost = consumption * tariffRate;
                document.getElementById('invoiceCost').value = cost.toFixed(2);
            }
        });
    </script>
</body>
</html>
"""

admin_financial_template = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Financial Management - EcoPulse Admin</title>
    <link rel="icon" type="image/svg+xml" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Crect width='64' height='64' rx='16' fill='%23062f2f'/%3E%3Cpath d='M35 6 18 34h11l-4 24 21-31H34z' fill='%23f59e0b'/%3E%3C/svg%3E">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.0/font/bootstrap-icons.css">
    <style>
        body {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            padding-top: 80px;
            padding-bottom: 30px;
        }
        .navbar {
            background: linear-gradient(135deg, #ff6b6b 0%, #ee5a6f 100%);
            box-shadow: 0 5px 20px rgba(0,0,0,0.2);
        }
        .card {
            border: none;
            border-radius: 15px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.2);
            margin-bottom: 30px;
        }
        .card-header {
            background: linear-gradient(135deg, #ff6b6b 0%, #ee5a6f 100%);
            color: white;
            border-radius: 15px 15px 0 0;
            padding: 20px;
            font-weight: 600;
            font-size: 1.2rem;
        }
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }
        .stat-card {
            background: white;
            padding: 20px;
            border-radius: 10px;
            box-shadow: 0 5px 15px rgba(0,0,0,0.1);
            text-align: center;
        }
        .stat-value {
            font-size: 2rem;
            font-weight: 700;
            color: #ff6b6b;
        }
        .btn-danger {
            background: linear-gradient(135deg, #ff6b6b 0%, #ee5a6f 100%);
            border: none;
        }
        .btn-success {
            background: linear-gradient(135deg, #00b894 0%, #00cec9 100%);
            border: none;
        }
        .btn-warning {
            background: linear-gradient(135deg, #f39c12 0%, #e67e22 100%);
            border: none;
            color: white;
        }
        .btn-info {
            background: linear-gradient(135deg, #3498db 0%, #2980b9 100%);
            border: none;
            color: white;
        }
        .financial-chart {
            max-width: 100%;
            border-radius: 10px;
            box-shadow: 0 5px 15px rgba(0,0,0,0.2);
        }
        .status-paid {
            background-color: #00b894;
            color: white;
            padding: 5px 10px;
            border-radius: 20px;
        }
        .status-pending {
            background-color: #f39c12;
            color: white;
            padding: 5px 10px;
            border-radius: 20px;
        }
        .status-overdue {
            background-color: #ff7b6b;
            color: white;
            padding: 5px 10px;
            border-radius: 20px;
        }
        .status-badge {
            padding: 5px 10px;
            border-radius: 20px;
            font-size: 0.8rem;
            font-weight: 600;
        }
        .status-pending-admin {
            background-color: #f39c12;
            color: white;
        }
        .status-approved {
            background-color: #00b894;
            color: white;
        }
    </style>
</head>
<body>
    <nav class="navbar navbar-expand-lg navbar-dark fixed-top">
        <div class="container">
            <a class="navbar-brand" href="{{ url_for('admin_financial') }}">
                <i class="bi bi-cash-stack"></i> EcoPulse Financial Admin
            </a>
            <div class="navbar-nav ms-auto">
                <a class="nav-link" href="{{ url_for('dashboard') }}">
                    <i class="bi bi-house"></i> Dashboard
                </a>
                <a class="nav-link" href="{{ url_for('admin_submissions') }}">
                    <i class="bi bi-people"></i> Submissions
                </a>
                <a class="nav-link" href="{{ url_for('logout') }}">
                    <i class="bi bi-box-arrow-right"></i> Logout
                </a>
            </div>
        </div>
    </nav>

    <div class="container">
        <div class="header-section text-center text-white mb-4">
            <h1><i class="bi bi-calculator"></i> Financial Management</h1>
            <p>Approve examiner reports and send consumption summaries to customers</p>
        </div>

        {% if message %}
        <div class="alert alert-success">{{ message }}</div>
        {% endif %}

        <!-- Financial Stats -->
        <div class="stats-grid">
            <div class="stat-card">
                <div class="stat-icon"><i class="bi bi-cash-stack fs-1 text-danger"></i></div>
                <div class="stat-value">Ksh {{ "%.2f"|format(financial.total_revenue) }}</div>
                <div class="stat-label">Total Revenue</div>
            </div>
            <div class="stat-card">
                <div class="stat-icon"><i class="bi bi-exclamation-triangle fs-1 text-danger"></i></div>
                <div class="stat-value">Ksh {{ "%.2f"|format(financial.total_outstanding) }}</div>
                <div class="stat-label">Outstanding</div>
            </div>
            <div class="stat-card">
                <div class="stat-icon"><i class="bi bi-check-circle fs-1 text-danger"></i></div>
                <div class="stat-value">Ksh {{ "%.2f"|format(financial.total_collected) }}</div>
                <div class="stat-label">Collected</div>
            </div>
            <div class="stat-card">
                <div class="stat-icon"><i class="bi bi-percent fs-1 text-danger"></i></div>
                <div class="stat-value">{{ "%.1f"|format(financial.payment_rate) }}%</div>
                <div class="stat-label">Payment Rate</div>
            </div>
        </div>

        <div class="row">
            <div class="col-md-8">
                <!-- Financial Chart -->
                <div class="card">
                    <div class="card-header">
                        <i class="bi bi-graph-up"></i> Financial Overview
                    </div>
                    <div class="card-body">
                        {% if financial.chart %}
                        <img src="data:image/png;base64,{{ financial.chart }}" class="img-fluid financial-chart" alt="Financial Chart">
                        {% else %}
                        <div class="alert alert-info text-center">
                            <i class="bi bi-info-circle"></i> No financial data available yet. Add some readings to see charts.
                        </div>
                        {% endif %}
                    </div>
                </div>
            </div>

            <div class="col-md-4">
                <!-- Quick Actions -->
                <div class="card">
                    <div class="card-header">
                        <i class="bi bi-envelope-paper"></i> Send Customer Summaries
                    </div>
                    <div class="card-body">
                        <p>Generate and send monthly consumption summaries to all customers</p>
                        <form method="POST" action="{{ url_for('send_customer_summaries') }}">
                            <button type="submit" class="btn btn-danger w-100 mb-3">
                                <i class="bi bi-send"></i> Send to All Customers
                            </button>
                        </form>
                        <hr>
                        <h6>Recent Reports from Examiner</h6>
                        <div class="list-group" style="max-height: 300px; overflow-y: auto;">
                            {% for report in examiner_reports %}
                            <a href="#" class="list-group-item list-group-item-action">
                                <div class="d-flex w-100 justify-content-between">
                                    <h6 class="mb-1">{{ report.title }}</h6>
                                    <small>{{ report.created_at.strftime('%d/%m/%Y') }}</small>
                                </div>
                                <p class="mb-1">From: Examiner</p>
                            </a>
                            {% endfor %}
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <!-- Pending Examiner Reviews -->
        <div class="card">
            <div class="card-header">
                <i class="bi bi-clipboard-check"></i> Pending Examiner Reviews
            </div>
            <div class="card-body">
                {% if pending_reviews %}
                <div class="table-responsive">
                    <table class="table table-hover">
                        <thead>
                            <tr>
                                <th>Period</th>
                                <th>Examiner</th>
                                <th>Total Customers</th>
                                <th>Total Consumption</th>
                                <th>Average Consumption</th>
                                <th>Peak Consumption</th>
                                <th>Notes</th>
                                <th>Actions</th>
                            </tr>
                        </thead>
                        <tbody>
                            {% for review in pending_reviews %}
                            <tr>
                                <td>{{ review.period }}</td>
                                <td>{{ review.examiner.username }}</td>
                                <td>{{ review.total_customers }}</td>
                                <td>{{ "%.0f"|format(review.total_consumption) }} kWh</td>
                                <td>{{ "%.0f"|format(review.average_consumption) }} kWh</td>
                                <td>{{ "%.0f"|format(review.peak_consumption) }} kWh</td>
                                <td><small>{{ review.notes or 'No notes' }}</small></td>
                                <td>
                                    <button class="btn btn-sm btn-success" onclick="approveReview({{ review.id }})">
                                        <i class="bi bi-check-circle"></i> Approve
                                    </button>
                                    <button class="btn btn-sm btn-danger" onclick="rejectReview({{ review.id }})">
                                        <i class="bi bi-x-circle"></i> Reject
                                    </button>
                                </td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
                {% else %}
                <p class="text-center text-muted">No pending reviews from examiner.</p>
                {% endif %}
            </div>
        </div>

        <!-- Customer Financial Status -->
        <div class="card">
            <div class="card-header">
                <i class="bi bi-people"></i> Customer Financial Status
            </div>
            <div class="card-body">
                <div class="table-responsive">
                    <table class="table table-hover">
                        <thead>
                            <tr>
                                <th>Customer</th>
                                <th>Period</th>
                                <th>Consumption (kWh)</th>
                                <th>Total Cost</th>
                                <th>Paid</th>
                                <th>Balance</th>
                                <th>Due Date</th>
                                <th>Status</th>
                                <th>Actions</th>
                            </tr>
                        </thead>
                        <tbody>
                            {% for record in financial_records %}
                            <tr>
                                <td>{{ record.user.username }}</td>
                                <td>{{ record.period }}</td>
                                <td>{{ "%.2f"|format(record.total_consumption) }}</td>
                                <td>Ksh {{ "%.2f"|format(record.total_cost) }}</td>
                                <td>Ksh {{ "%.2f"|format(record.total_paid) }}</td>
                                <td>Ksh {{ "%.2f"|format(record.balance) }}</td>
                                <td>{{ record.due_date.strftime('%Y-%m-%d') if record.due_date else 'N/A' }}</td>
                                <td>
                                    <span class="badge {% if record.payment_status == 'paid' %}bg-success{% elif record.payment_status == 'pending' %}bg-warning{% else %}bg-danger{% endif %}">
                                        {{ record.payment_status }}
                                    </span>
                                </td>
                                <td>
                                    <button class="btn btn-sm btn-success" onclick="markAsPaid({{ record.id }})">
                                        <i class="bi bi-check"></i>
                                    </button>
                                    <button class="btn btn-sm btn-danger" onclick="sendReminder({{ record.id }})">
                                        <i class="bi bi-envelope"></i>
                                    </button>
                                </td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    </div>

    <script>
        function markAsPaid(recordId) {
            fetch('/mark_as_paid/' + recordId, {
                method: 'POST'
            }).then(response => response.json())
              .then(data => {
                  alert(data.message);
                  location.reload();
              });
        }

        function sendReminder(recordId) {
            fetch('/send_payment_reminder/' + recordId, {
                method: 'POST'
            }).then(response => response.json())
              .then(data => {
                  alert(data.message);
              });
        }

        function approveReview(reviewId) {
            fetch('/approve_review/' + reviewId, {
                method: 'POST'
            }).then(response => response.json())
              .then(data => {
                  alert(data.message);
                  location.reload();
              });
        }

        function rejectReview(reviewId) {
            fetch('/reject_review/' + reviewId, {
                method: 'POST'
            }).then(response => response.json())
              .then(data => {
                  alert(data.message);
                  location.reload();
              });
        }
    </script>
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
"""

PUBLIC_FOOTER_LINKS = [
    ('Home', 'index'),
    ('Services', 'services'),
    ('Careers', 'careers'),
    ('News', 'news'),
    ('FAQs', 'faqs'),
    ('About Us', 'about'),
    ('Workflow', 'how_it_works'),
    ('Pricing', 'pricing'),
    ('Get in Touch', 'contact'),
    ('Privacy Policy', 'privacy_policy'),
    ('Terms of Service', 'terms_of_service')
]

PUBLIC_SERVICES = [
    {'title': 'Smart Home Monitoring', 'text': 'Track and optimize household energy use with live visibility into appliances, sensors, and daily consumption patterns.', 'icon': 'bi-house-gear'},
    {'title': 'Business Energy Optimization', 'text': 'Reduce operational costs with IoT-driven insights, threshold alerts, and business-grade analytics across facilities.', 'icon': 'bi-buildings'},
    {'title': 'IoT Device Integration', 'text': 'Connect appliances, smart meters, and environmental sensors into one streamlined energy management workflow.', 'icon': 'bi-cpu'},
    {'title': 'Analytics & Reporting', 'text': 'Use dashboards to review usage, savings, efficiency trends, and sustainability impact in one place.', 'icon': 'bi-bar-chart-line'}
]

PUBLIC_ABOUT = [
    {'title': 'Mission', 'text': 'To empower smarter energy use for a sustainable future.'},
    {'title': 'Vision', 'text': 'Every home and business running on efficient, eco-friendly energy.'},
    {'title': 'Our Story', 'text': 'EcoPulse was founded to bridge IoT technology with sustainability goals, helping people turn energy data into practical action.'},
    {'title': 'Meet the Team', 'text': 'Our founders and key leaders bring together expertise in IoT engineering, analytics, energy systems, and sustainable operations.'}
]

PUBLIC_WORKFLOW = [
    {'title': '1. Customer Records Usage', 'text': 'Customers register, log in, add readings, adjust thresholds, and submit summaries when ready.'},
    {'title': '2. Examiner Reviews Patterns', 'text': 'Examiners review pending readings, analyze system-wide activity, and prepare reports.'},
    {'title': '3. Admin Approves Actions', 'text': 'Admins review examiner output, manage financial records, and close the loop with customer summaries.'}
]

PUBLIC_PRIVACY = [
    {'title': 'Data Collected', 'text': 'EcoPulse stores account details, meter readings, threshold settings, payment records, and staff review activity.'},
    {'title': 'Why It Is Used', 'text': 'The data is used to calculate billing, show dashboards, trigger alerts, and support customer service.'},
    {'title': 'Access Control', 'text': 'Customers see their own information while admins and examiners access only the role-specific records needed for operations.'}
]

PUBLIC_TERMS = [
    {'title': 'Customer Use', 'text': 'Customers are responsible for submitting accurate readings and reviewing billing summaries sent through the platform.'},
    {'title': 'Staff Use', 'text': 'Admins and examiners must use staff accounts only for operational reviews, approvals, and reporting.'},
    {'title': 'Service Behavior', 'text': 'Threshold settings, overage options, and auto-shutdown reminders are advisory workflow tools within the application.'}
]

PUBLIC_PRICING = [
    {'title': 'Starter', 'text': 'For households starting with digital monitoring. Includes customer dashboard, threshold controls, alerts, and exports.', 'price': 'Ksh 0 demo'},
    {'title': 'Operations', 'text': 'For teams handling examiner review workflows, report generation, and operational analysis.', 'price': 'Ksh 7,500 / month'},
    {'title': 'Enterprise', 'text': 'For full admin finance controls, custom reporting, workflow support, and deployment planning.', 'price': 'Custom pricing'}
]

PUBLIC_CAREERS = [
    {'title': 'IoT Engineers', 'text': 'Build connected monitoring systems, device integrations, and automation workflows that help users reduce waste.'},
    {'title': 'Data Analysts', 'text': 'Transform energy data into actionable dashboards, efficiency reports, and sustainability insights.'},
    {'title': 'Sustainability Consultants', 'text': 'Guide households and businesses on practical strategies for lower energy costs and reduced carbon footprints.'},
    {'title': 'Internship Programs', 'text': 'Students passionate about green tech can join hands-on internships focused on IoT, analytics, and product innovation.'},
    {'title': 'Culture', 'text': 'EcoPulse values innovation, sustainability, teamwork, and practical solutions that create measurable environmental impact.'}
]

PUBLIC_NEWS = [
    {'title': 'Product Launches', 'text': 'Follow the latest EcoPulse releases across smart monitoring, automation, and energy intelligence.'},
    {'title': 'Green Energy Partnerships', 'text': 'Read about collaborations with energy providers, clean-tech firms, and sustainability-focused organizations.'},
    {'title': 'Industry Insights', 'text': 'Stay informed on how IoT, smart grids, and sustainability trends are changing energy management.'},
    {'title': 'Energy-Saving Tips', 'text': 'Browse practical blog-style advice on reducing electricity bills and improving home or business efficiency.'}
]

PUBLIC_FAQS = [
    {'title': 'How does EcoPulse predict future energy use?', 'text': 'EcoPulse analyzes recorded consumption trends and builds backcast and forecast views to help staff plan ahead.'},
    {'title': 'How are invoices delivered to customers?', 'text': 'Invoices are created as financial records inside the platform and can also trigger report notifications and payment reminders.'},
    {'title': 'Can businesses use EcoPulse for multiple devices?', 'text': 'Yes. EcoPulse is designed to support connected sensors, appliances, and meters for business-grade visibility.'},
    {'title': 'What support is available?', 'text': 'Customers can use FAQs, troubleshooting guidance, support contact forms, and role-based staff workflows for follow-up.'},
    {'title': 'How does threshold protection work?', 'text': 'When usage crosses a threshold, EcoPulse either applies overage billing or raises alerts and schedules a shutdown reminder depending on account settings.'}
]

PUBLIC_HOME_HIGHLIGHTS = [
    'Real-time energy monitoring',
    'Automated efficiency suggestions',
    'Business-grade analytics',
    'Sustainable living made simple'
]

PUBLIC_HOME_STATS = [
    {'value': '24/7', 'label': 'Live monitoring for homes and teams'},
    {'value': 'AI', 'label': 'Guided efficiency suggestions'},
    {'value': '1', 'label': 'Unified dashboard for energy workflows'}
]

home_page_template = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>EcoPulse</title>
    <link rel="icon" type="image/svg+xml" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Crect width='64' height='64' rx='16' fill='%23062f2f'/%3E%3Cpath d='M35 6 18 34h11l-4 24 21-31H34z' fill='%23f59e0b'/%3E%3C/svg%3E">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.0/font/bootstrap-icons.css">
    <style>
        :root { --forest:#062f2f; --teal:#0f766e; --amber:#f59e0b; --ink:#0f172a; --sand:#fff7ed; }
        * { box-sizing:border-box; }
        body { margin:0; background:
            radial-gradient(circle at top left, rgba(16,185,129,.18), transparent 24%),
            radial-gradient(circle at bottom right, rgba(245,158,11,.14), transparent 20%),
            linear-gradient(180deg, #e8f3f1 0%, #f6fbfa 30%, #eef4ff 62%, #f7efe2 100%);
            color: #111827; overflow-x:hidden; }
        .navbar { backdrop-filter: blur(14px); background: rgba(6,47,47,0.88); box-shadow:0 14px 30px rgba(6,47,47,.18); }
        .hero { padding: 132px 0 96px; min-height: 88vh; display:flex; align-items:center; background:
            linear-gradient(rgba(6,47,47,.42), rgba(6,47,47,.18)),
            url('https://images.unsplash.com/photo-1473341304170-971dccb5ac1e?auto=format&fit=crop&w=1800&q=80') center center/cover no-repeat,
            linear-gradient(135deg, #062f2f, #0f766e 60%, #d97706);
            color: white; position:relative; }
        .hero:before { content:''; position:absolute; inset:0; background:linear-gradient(110deg, rgba(6,47,47,.86), rgba(6,47,47,.48) 44%, rgba(6,47,47,.12) 72%, rgba(217,119,6,.24)); }
        .hero > .container { position:relative; z-index:1; }
        .section-card, .assistant-card { border: 0; border-radius: 28px; box-shadow: 0 20px 50px rgba(15,23,42,0.12); overflow:hidden; }
        .section-card { background:rgba(255,255,255,.9); backdrop-filter:blur(10px); }
        .assistant-card { background:linear-gradient(180deg, rgba(255,255,255,.96), rgba(240,253,250,.96)); }
        .metric-tile { background: rgba(255,255,255,0.14); border:1px solid rgba(255,255,255,.16); border-radius: 18px; padding: 18px; backdrop-filter:blur(10px); }
        .showcase-image { width: 100%; border-radius: 24px; min-height: 340px; object-fit: cover; box-shadow: 0 28px 48px rgba(0,0,0,0.24); }
        .map-frame { border: 0; width: 100%; min-height: 340px; border-radius: 24px; box-shadow:0 20px 45px rgba(15,23,42,.12); }
        .highlight-band { background:linear-gradient(135deg, rgba(6,47,47,.96), rgba(15,118,110,.92)); color:#fff; }
        .tone-soft { background:linear-gradient(180deg, rgba(255,255,255,.72), rgba(255,247,237,.9)); }
        .feature-poster { position:relative; min-height:300px; border-radius:28px; overflow:hidden; color:#fff; box-shadow:0 24px 60px rgba(15,23,42,.16); }
        .feature-poster img { position:absolute; inset:0; width:100%; height:100%; object-fit:cover; }
        .feature-poster:after { content:''; position:absolute; inset:0; background:linear-gradient(180deg, rgba(6,47,47,.18), rgba(6,47,47,.84)); }
        .feature-poster .content { position:relative; z-index:1; padding:28px; display:flex; flex-direction:column; justify-content:flex-end; min-height:300px; }
        footer { background: #041b1b; color: #d7ece8; }
        .assistant-scroll { max-height: 260px; overflow-y: auto; background: #f8fafc; border-radius: 16px; padding: 16px; border:1px solid rgba(15,23,42,.08); }
        @media (max-width:767.98px) {
            .hero { padding: 108px 0 64px; min-height:auto; }
            .container { padding-left:18px; padding-right:18px; }
            .section-card, .assistant-card, .feature-poster { border-radius:22px; }
        }
    </style>
</head>
<body>
    <nav class="navbar navbar-expand-lg navbar-dark fixed-top">
        <div class="container">
            <a class="navbar-brand fw-bold" href="{{ url_for('index') }}"><i class="bi bi-lightning-charge-fill"></i> EcoPulse</a>
            <button class="navbar-toggler" type="button" data-bs-toggle="collapse" data-bs-target="#navMenu"><span class="navbar-toggler-icon"></span></button>
            <div class="collapse navbar-collapse" id="navMenu">
                <ul class="navbar-nav ms-auto align-items-lg-center gap-lg-2">
                    <li class="nav-item"><a class="nav-link" href="{{ url_for('index') }}">Home</a></li>
                    <li class="nav-item"><a class="nav-link" href="{{ url_for('services') }}">Services</a></li>
                    <li class="nav-item"><a class="nav-link" href="{{ url_for('careers') }}">Careers</a></li>
                    <li class="nav-item"><a class="nav-link" href="{{ url_for('about') }}">About</a></li>
                    <li class="nav-item"><a class="nav-link" href="{{ url_for('news') }}">News</a></li>
                    <li class="nav-item"><a class="nav-link" href="{{ url_for('how_it_works') }}">Workflow</a></li>
                    <li class="nav-item"><a class="nav-link" href="{{ url_for('contact') }}">Get in Touch</a></li>
                    <li class="nav-item"><a class="nav-link" href="{{ url_for('pricing') }}">Pricing</a></li>
                    <li class="nav-item"><a class="btn btn-outline-light ms-lg-2" href="{{ url_for('login') }}">Customer Login</a></li>
                    <li class="nav-item"><a class="btn btn-warning ms-lg-2" href="{{ url_for('register') }}">Register</a></li>
                </ul>
            </div>
        </div>
    </nav>
    <section class="hero">
        <div class="container">
            <div class="row align-items-center g-5">
                <div class="col-lg-7 col-xl-6">
                    <span class="badge text-bg-light text-dark mb-3">Smarter Energy, Greener Future</span>
                    <h1 class="display-4 fw-bold">Smarter energy management for homes and businesses.</h1>
                    <p class="lead mt-3">EcoPulse helps homes and businesses cut energy costs and reduce carbon footprints with smart IoT solutions.</p>
                    <div class="d-flex flex-wrap gap-3 mt-4">
                        <a href="{{ url_for('register') }}" class="btn btn-warning btn-lg">Get Started</a>
                        <a href="{{ url_for('about') }}" class="btn btn-outline-light btn-lg">Learn More</a>
                    </div>
                    <div class="row g-3 mt-4">
                        {% for highlight in PUBLIC_HOME_HIGHLIGHTS %}
                        <div class="col-sm-6"><div class="metric-tile"><div class="fw-semibold">{{ highlight }}</div></div></div>
                        {% endfor %}
                    </div>
                </div>
            </div>
        </div>
    </section>
    <section class="py-5">
        <div class="container">
            <div class="section-card card p-4 p-lg-5 mb-4 highlight-band">
                <div class="row g-4 align-items-center">
                    <div class="col-lg-6">
                        <span class="badge text-bg-light text-dark mb-3">Home Overview</span>
                        <h2 class="fw-bold">A cleaner, smarter way to manage energy from one place.</h2>
                        <p class="mb-0" style="color:rgba(255,255,255,.86)">EcoPulse brings smart-home visibility, billing workflows, efficiency guidance, and support tools into one platform for customers and staff.</p>
                    </div>
                    <div class="col-lg-6">
                        <div class="row g-3">
                            {% for stat in PUBLIC_HOME_STATS %}
                            <div class="col-sm-4"><div class="border rounded-4 p-3 h-100 text-center" style="background:rgba(255,255,255,.12);border-color:rgba(255,255,255,.18)!important"><div class="fs-3 fw-bold text-warning">{{ stat.value }}</div><div class="small" style="color:rgba(255,255,255,.82)">{{ stat.label }}</div></div></div>
                            {% endfor %}
                        </div>
                    </div>
                </div>
            </div>
            <div class="row g-4">
                {% for item in PUBLIC_SERVICES %}
                <div class="col-md-6 col-xl-3"><div class="section-card card p-4 h-100"><div class="fs-1 text-warning"><i class="bi {{ item.icon }}"></i></div><h4 class="mt-3">{{ item.title }}</h4><p class="text-muted mb-0">{{ item.text }}</p></div></div>
                {% endfor %}
            </div>
        </div>
    </section>
    <section class="py-4">
        <div class="container">
            <div class="row g-4">
                <div class="col-lg-4"><div class="section-card card p-4 h-100 tone-soft"><h3 class="fw-bold">Explore Features</h3><p class="text-muted">Real-time energy monitoring, automated efficiency suggestions, business-grade analytics, and sustainable living made simple.</p></div></div>
                <div class="col-lg-4"><div class="section-card card p-4 h-100" style="background:linear-gradient(145deg,#fff,#f0fdf9)"><h3 class="fw-bold">Careers</h3><p class="text-muted">Join a mission-driven team building IoT products, analytics workflows, and sustainability tools.</p><a href="{{ url_for('careers') }}" class="btn btn-outline-dark mt-2">Apply Now</a></div></div>
                <div class="col-lg-4"><div class="section-card card p-4 h-100" style="background:linear-gradient(145deg,#fff,#eff6ff)"><h3 class="fw-bold">News</h3><p class="text-muted">Read the latest EcoPulse launches, partnerships, and practical insights on IoT and sustainability.</p><a href="{{ url_for('news') }}" class="btn btn-outline-dark mt-2">Read Updates</a></div></div>
            </div>
        </div>
    </section>
    <section class="py-4">
        <div class="container">
            <div class="section-card card p-4">
                <div class="row g-4 align-items-start">
                    <div class="col-lg-4">
                        <span class="badge text-bg-warning mb-3">About EcoPulse</span>
                        <h3 class="fw-bold">Built to connect IoT and sustainability.</h3>
                        <p class="text-muted mb-0">EcoPulse helps homes and businesses make better energy decisions with practical monitoring, forecasting, and operational support.</p>
                    </div>
                    <div class="col-lg-8">
                        <div class="row g-3">
                            {% for item in PUBLIC_ABOUT %}
                            <div class="col-md-6"><div class="border rounded-4 p-4 h-100"><h5>{{ item.title }}</h5><p class="text-muted mb-0">{{ item.text }}</p></div></div>
                            {% endfor %}
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </section>
    <section class="py-4">
        <div class="container">
            <div class="row g-4">
                <div class="col-lg-6">
                    <div class="section-card card p-4 h-100">
                        <span class="badge text-bg-light border mb-3">Careers</span>
                        <h3 class="fw-bold">Join Our Mission</h3>
                        <p class="text-muted">Innovation, sustainability, and teamwork define how EcoPulse builds products and serves customers.</p>
                        <div class="row g-3">
                            {% for item in PUBLIC_CAREERS[:4] %}
                            <div class="col-md-6"><div class="border rounded-4 p-3 h-100"><h6 class="fw-bold mb-2">{{ item.title }}</h6><p class="text-muted mb-0">{{ item.text }}</p></div></div>
                            {% endfor %}
                        </div>
                        <a href="{{ url_for('careers') }}" class="btn btn-dark mt-3">Apply Now</a>
                    </div>
                </div>
                <div class="col-lg-6">
                    <div class="section-card card p-4 h-100">
                        <span class="badge text-bg-light border mb-3">News</span>
                        <h3 class="fw-bold">Stay Updated</h3>
                        <div class="row g-3">
                            {% for item in PUBLIC_NEWS %}
                            <div class="col-12"><div class="border rounded-4 p-3"><h6 class="fw-bold mb-2">{{ item.title }}</h6><p class="text-muted mb-0">{{ item.text }}</p></div></div>
                            {% endfor %}
                        </div>
                        <a href="{{ url_for('news') }}" class="btn btn-outline-dark mt-3">View All News</a>
                    </div>
                </div>
            </div>
        </div>
    </section>
    <section class="py-4">
        <div class="container">
            <div class="row g-4 align-items-stretch">
                <div class="col-lg-7">
                    <div class="assistant-card card p-4 h-100">
                        <h3 class="fw-bold mb-1"><i class="bi bi-robot"></i> EcoPulse AI Assistant</h3>
                        <p class="text-muted mb-0">Ask about services, thresholds, workflow, support, privacy, or forecasting.</p>
                        <div id="assistantMessages" class="assistant-scroll mt-4"><div class="mb-3"><strong>EcoPulse AI:</strong> Ask me anything about how EcoPulse works.</div></div>
                        <div class="input-group mt-3"><input id="assistantInput" type="text" class="form-control form-control-lg" placeholder="How does threshold protection work?"><button id="assistantSend" class="btn btn-dark">Ask</button></div>
                    </div>
                </div>
                <div class="col-lg-5">
                    <div class="section-card card p-4 h-100">
                        <h3 class="fw-bold">How it works</h3>
                        {% for item in PUBLIC_WORKFLOW %}
                        <div class="mt-3"><h5>{{ item.title }}</h5><p class="text-muted mb-0">{{ item.text }}</p></div>
                        {% endfor %}
                    </div>
                </div>
            </div>
        </div>
    </section>
    <section class="py-4">
        <div class="container">
            <div class="section-card card p-4">
                <div class="row g-4 align-items-center">
                    <div class="col-lg-5">
                        <h3 class="fw-bold">Why EcoPulse</h3>
                        <p class="text-muted mb-3">EcoPulse turns energy data into clear actions for households, businesses, and operational teams.</p>
                        <div class="mb-3"><strong>Track usage clearly</strong><p class="text-muted mb-0">Monitor consumption trends, costs, and sustainability impact without technical clutter.</p></div>
                        <div class="mb-3"><strong>Act faster</strong><p class="text-muted mb-0">Use alerts, reporting, and efficiency suggestions to make better day-to-day energy decisions.</p></div>
                        <div><strong>Scale confidently</strong><p class="text-muted mb-0">Support smart homes, connected business operations, and greener long-term planning from one platform.</p></div>
                    </div>
                    <div class="col-lg-7">
                        <div class="border rounded-4 p-4 bg-dark text-light">
                            <div class="d-flex justify-content-between"><span>EcoPulse Highlights</span><span class="text-warning">Live platform</span></div>
                            <hr>
                            <div class="row g-3">
                                <div class="col-sm-4"><div class="p-3 rounded-3" style="background:#0f172a;"><small>Monitoring</small><div class="fs-4 fw-bold">Realtime</div></div></div>
                                <div class="col-sm-4"><div class="p-3 rounded-3" style="background:#0f172a;"><small>Insights</small><div class="fs-4 fw-bold">Smart</div></div></div>
                                <div class="col-sm-4"><div class="p-3 rounded-3" style="background:#0f172a;"><small>Savings</small><div class="fs-4 fw-bold">Visible</div></div></div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </section>
    <section class="py-4">
        <div class="container">
            <div class="row g-4">
                <div class="col-lg-7">
                    <div class="section-card card p-4 h-100">
                        <span class="badge text-bg-success mb-3">Dashboard</span>
                        <h3 class="fw-bold">Everything users need in one energy dashboard.</h3>
                        <div class="row g-3 mt-1">
                            <div class="col-md-6"><div class="border rounded-4 p-3 h-100"><h6 class="fw-bold">Analytics</h6><p class="text-muted mb-0">Interactive charts show usage trends, estimated costs, and long-term efficiency patterns.</p></div></div>
                            <div class="col-md-6"><div class="border rounded-4 p-3 h-100"><h6 class="fw-bold">Devices</h6><p class="text-muted mb-0">Manage connected IoT devices, sensors, and meters from one organized workspace.</p></div></div>
                            <div class="col-md-6"><div class="border rounded-4 p-3 h-100"><h6 class="fw-bold">Support</h6><p class="text-muted mb-0">Access troubleshooting help, support channels, and guided next steps when issues appear.</p></div></div>
                            <div class="col-md-6"><div class="border rounded-4 p-3 h-100"><h6 class="fw-bold">Community</h6><p class="text-muted mb-0">Learn from shared stories, sustainability tips, and customer experiences.</p></div></div>
                        </div>
                    </div>
                </div>
                <div class="col-lg-5">
                    <div class="section-card card p-4 h-100">
                        <span class="badge text-bg-light border mb-3">FAQs</span>
                        <h3 class="fw-bold">Common Questions</h3>
                        {% for item in PUBLIC_FAQS[:4] %}
                        <div class="border rounded-4 p-3 mb-3">
                            <h6 class="fw-bold mb-2">{{ item.title }}</h6>
                            <p class="text-muted mb-0">{{ item.text }}</p>
                        </div>
                        {% endfor %}
                        <a href="{{ url_for('faqs') }}" class="btn btn-outline-dark">View All FAQs</a>
                    </div>
                </div>
            </div>
        </div>
    </section>
    <section class="py-5">
        <div class="container">
            <div class="row g-4 align-items-center">
                <div class="col-lg-6"><div class="section-card card p-4"><h3 class="fw-bold">Get in touch</h3><p class="text-muted">Visit the office, send a note, or use the contact page for support and partnership requests.</p><p class="mb-2"><i class="bi bi-geo-alt-fill text-warning me-2"></i>EcoPulse Centre, Kisii Town, Kenya</p><p class="mb-2"><i class="bi bi-envelope-fill text-warning me-2"></i>support@ecopulse.local</p><p class="mb-0"><i class="bi bi-telephone-fill text-warning me-2"></i>+254 700 123 456</p></div></div>
                <div class="col-lg-6"><iframe class="map-frame" loading="lazy" src="https://www.google.com/maps?q=Kisii%20Town%20Kenya&z=13&output=embed"></iframe></div>
            </div>
        </div>
    </section>
    <section class="py-5">
        <div class="container">
            <div class="row g-4">
                <div class="col-lg-4">
                    <div class="feature-poster">
                        <img src="https://images.unsplash.com/photo-1558002038-1055907df827?auto=format&fit=crop&w=1200&q=80" alt="Smart home monitoring">
                        <div class="content">
                            <span class="badge text-bg-warning text-dark mb-3">Smart Home Monitoring</span>
                            <h3 class="fw-bold">Room-by-room visibility for daily household energy clarity.</h3>
                            <p class="mb-0">Live readings, protection mode cues, and trend summaries are easier to understand on mobile and desktop.</p>
                        </div>
                    </div>
                </div>
                <div class="col-lg-4">
                    <div class="feature-poster">
                        <img src="https://images.unsplash.com/photo-1518770660439-4636190af475?auto=format&fit=crop&w=1200&q=80" alt="IoT device integration">
                        <div class="content">
                            <span class="badge text-bg-light text-dark mb-3">IoT Device Integration</span>
                            <h3 class="fw-bold">Connect smart sensors, meters, and appliances in one flow.</h3>
                            <p class="mb-0">EcoPulse keeps device data, review workflows, and alerts synchronized without changing your current records.</p>
                        </div>
                    </div>
                </div>
                <div class="col-lg-4">
                    <div class="feature-poster">
                        <img src="https://images.unsplash.com/photo-1486406146926-c627a92ad1ab?auto=format&fit=crop&w=1200&q=80" alt="Business energy optimization">
                        <div class="content">
                            <span class="badge text-bg-success mb-3">Business Energy Optimization</span>
                            <h3 class="fw-bold">Operational forecasting and financial oversight in one place.</h3>
                            <p class="mb-0">Customer, examiner, and admin views now carry distinct visual cues while preserving the existing information hierarchy.</p>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </section>
    <footer class="py-5 mt-4">
        <div class="container">
            <div class="row g-4">
                <div class="col-lg-4"><h4 class="fw-bold"><i class="bi bi-lightning-charge-fill"></i> EcoPulse</h4><p class="mb-0">Customer-centric energy monitoring with role-based operational workflows and AI-assisted forecasting.</p></div>
                <div class="col-sm-6 col-lg-4"><h6 class="text-uppercase">Quick Links</h6><ul class="list-unstyled">{% for label, endpoint in footer_links %}<li class="mb-2"><a class="text-decoration-none text-light" href="{{ url_for(endpoint) }}">{{ label }}</a></li>{% endfor %}</ul></div>
                <div class="col-sm-6 col-lg-4"><h6 class="text-uppercase">Contact</h6><p class="mb-1">support@ecopulse.local</p><p class="mb-1">+254 700 123 456</p><p class="mb-2">Kisii Town, Kenya</p><a class="text-decoration-none text-light d-block" href="{{ url_for('staff_login') }}">Admin / Examiner Login</a></div>
            </div>
            <div class="d-flex justify-content-between align-items-center border-top border-secondary pt-3 mt-4 flex-wrap gap-2"><small>&copy;2026 EcoPulse. All rights reserved.</small><small>Committed to a green future</small></div>
        </div>
    </footer>
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script>
    <script>
        const assistantInput = document.getElementById('assistantInput');
        const assistantMessages = document.getElementById('assistantMessages');
        async function sendAssistantQuestion() {
            const message = assistantInput.value.trim();
            if (!message) return;
            assistantMessages.insertAdjacentHTML('beforeend', `<div class="mb-2"><strong>You:</strong> ${message}</div>`);
            assistantInput.value = '';
            const response = await fetch('{{ url_for("public_assistant") }}', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({message})});
            const data = await response.json();
            assistantMessages.insertAdjacentHTML('beforeend', `<div class="mb-3"><strong>EcoPulse AI:</strong> ${data.answer}</div>`);
            assistantMessages.scrollTop = assistantMessages.scrollHeight;
        }
        document.getElementById('assistantSend').addEventListener('click', sendAssistantQuestion);
        assistantInput.addEventListener('keydown', (event) => { if (event.key === 'Enter') { event.preventDefault(); sendAssistantQuestion(); }});
    </script>
</body>
</html>
"""

RECHARGE_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Recharge Energy - EcoPulse</title>
    <link rel="icon" type="image/svg+xml" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Crect width='64' height='64' rx='16' fill='%23062f2f'/%3E%3Cpath d='M35 6 18 34h11l-4 24 21-31H34z' fill='%23f59e0b'/%3E%3C/svg%3E">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.0/font/bootstrap-icons.css">
    <style>
        body{background:linear-gradient(135deg, #667eea 0%, #764ba2 100%);min-height:100vh;padding-top:80px;font-family:'Segoe UI', Tahoma, Geneva, Verdana, sans-serif}
        .card{border:none;border-radius:15px;box-shadow:0 10px 30px rgba(0,0,0,0.2);margin-bottom:30px}
        .card-header{background:linear-gradient(135deg, #00b894 0%, #00cec9 100%);color:white;border-radius:15px 15px 0 0;padding:20px;font-weight:600}
        .usage-bar{height:30px;background:#e0e0e0;border-radius:15px;overflow:hidden;margin:20px 0}
        .usage-fill{height:100%;background:linear-gradient(90deg, #00b894, #fdcb6e, #ff6b6b);border-radius:15px;transition:width 0.5s ease}
        .btn-recharge{background:linear-gradient(135deg, #00b894 0%, #00cec9 100%);border:none;color:white;padding:12px 30px;font-weight:600;border-radius:10px}
    </style>
</head>
<body>
    <div class="container">
        <div class="row justify-content-center">
            <div class="col-md-8">
                <div class="card">
                    <div class="card-header">
                        <i class="bi bi-lightning-charge"></i> Recharge Energy
                    </div>
                    <div class="card-body">
                        <div class="alert alert-info">
                            <h5><i class="bi bi-speedometer2"></i> Current Consumption Status</h5>
                            <p><strong>Used:</strong> {{ "%.2f"|format(current_total) }} kWh / {{ threshold }} kWh ({{ "%.1f"|format(percentage) }}%)</p>
                            <p><strong>Remaining:</strong> {{ "%.2f"|format(remaining) }} kWh</p>
                        </div>
                        <div class="usage-bar">
                            <div class="usage-fill" style="width: {{ percentage }}%"></div>
                        </div>
                        <form method="POST" onsubmit="return validateRecharge()">
                            <div class="mb-3">
                                <label class="form-label">Units to Recharge (kWh)</label>
                                <input type="number" name="recharge_units" id="rechargeUnits" class="form-control" step="10" min="10" required>
                                <small class="text-muted">Minimum recharge: 10 kWh</small>
                            </div>
                            <div class="mb-3">
                                <label class="form-label">Payment Method</label>
                                <select name="payment_method" id="paymentMethod" class="form-select" required onchange="togglePhoneField()">
                                    <option value="">Select payment method</option>
                                    <option value="mpesa">📱 M-Pesa</option>
                                    <option value="card">💳 Card</option>
                                    <option value="bank_transfer">🏦 Bank Transfer</option>
                                </select>
                            </div>
                            <div class="mb-3" id="phoneField" style="display:none;">
                                <label class="form-label">M-Pesa Phone Number</label>
                                <input type="tel" name="phone_number" id="phoneNumber" class="form-control" maxlength="10" placeholder="0712345678">
                                <small class="text-muted">Enter 10-digit M-Pesa phone number</small>
                            </div>
                            <div class="mb-3">
                                <label class="form-label">Transaction Reference</label>
                                <input type="text" name="reference" id="reference" class="form-control" maxlength="10" minlength="10" required placeholder="ABC123XYZ7">
                                <small class="text-muted">Exactly 10 alphanumeric characters</small>
                            </div>
                            <div class="mb-3">
                                <label class="form-label">Estimated Cost</label>
                                <input type="text" class="form-control" id="costDisplay" readonly value="{{ currency }} 0.00">
                            </div>
                            <button type="submit" class="btn btn-recharge w-100">Recharge Now</button>
                        </form>
                        <hr>
                        <div class="text-center">
                            <a href="{{ url_for('dashboard') }}" class="btn btn-outline-secondary">Back to Dashboard</a>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>
    <script>
        const unitCost = {{ unit_cost }};
        const currency = '{{ currency }}';
        document.getElementById('rechargeUnits').addEventListener('input', function() {
            const units = parseFloat(this.value) || 0;
            document.getElementById('costDisplay').value = `${currency} ${(units * unitCost).toFixed(2)}`;
        });
        function togglePhoneField() {
            const method = document.getElementById('paymentMethod').value;
            const phoneField = document.getElementById('phoneField');
            if (method === 'mpesa') {
                phoneField.style.display = 'block';
                document.getElementById('phoneNumber').required = true;
            } else {
                phoneField.style.display = 'none';
                document.getElementById('phoneNumber').required = false;
            }
        }
        function validateRecharge() {
            const units = document.getElementById('rechargeUnits').value;
            const reference = document.getElementById('reference').value;
            const method = document.getElementById('paymentMethod').value;
            const phone = document.getElementById('phoneNumber').value;
            if (!units || units < 10) { alert('Please enter valid units (minimum 10 kWh)'); return false; }
            if (!reference || reference.length !== 10 || !/^[a-zA-Z0-9]+$/.test(reference)) { alert('Reference must be exactly 10 alphanumeric characters'); return false; }
            if (!method) { alert('Please select a payment method'); return false; }
            if (method === 'mpesa' && (!phone || phone.length !== 10 || !/^\\d{10}$/.test(phone))) { alert('Please enter a valid 10-digit M-Pesa phone number'); return false; }
            return confirm(`Confirm recharge of ${units} kWh for ${currency} ${(units * unitCost).toFixed(2)}?`);
        }
    </script>
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
"""

public_content_template = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ page_title }}</title>
    <link rel="icon" type="image/svg+xml" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Crect width='64' height='64' rx='16' fill='%23062f2f'/%3E%3Cpath d='M35 6 18 34h11l-4 24 21-31H34z' fill='%23f59e0b'/%3E%3C/svg%3E">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.0/font/bootstrap-icons.css">
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;700&family=Source+Sans+3:wght@400;600&display=swap" rel="stylesheet">
    <style>:root{--forest:#062f2f;--teal:#0f766e;--amber:#f59e0b;--ink:#0f172a}body{margin:0;background:radial-gradient(circle at top left,rgba(16,185,129,.16),transparent 20%),radial-gradient(circle at bottom right,rgba(245,158,11,.12),transparent 18%),linear-gradient(180deg,#edf6f4 0,#f8fafc 40%,#f6efe4 100%);font-family:'Source Sans 3',sans-serif;color:var(--ink);overflow-x:hidden}h1,h2,h3,h4,h5,.navbar-brand{font-family:'Space Grotesk',sans-serif}.navbar{backdrop-filter:blur(14px);background:rgba(6,47,47,.9)!important;box-shadow:0 10px 30px rgba(6,47,47,.16)}.nav-link{font-weight:600}.hero{position:relative;overflow:hidden;background:linear-gradient(rgba(6,47,47,.58),rgba(6,47,47,.22)),url('https://images.unsplash.com/photo-1509391366360-2e959784a276?auto=format&fit=crop&w=1600&q=80') center/cover,linear-gradient(145deg,#062f2f,#0f766e 58%,#d97706);color:white;padding:128px 0 72px}.hero:after{content:'';position:absolute;right:-80px;top:-80px;width:260px;height:260px;border-radius:999px;background:rgba(255,255,255,.08)}.hero .lead{color:rgba(255,255,255,.86)}.glass-chip{display:inline-flex;align-items:center;gap:10px;padding:9px 16px;border-radius:999px;background:rgba(255,255,255,.12);border:1px solid rgba(255,255,255,.12);margin-bottom:16px}.content-card{border:1px solid rgba(15,23,42,.08);border-radius:28px;box-shadow:0 20px 52px rgba(15,23,42,.08);background:rgba(255,255,255,.92);backdrop-filter:blur(10px)}.feature-icon{width:56px;height:56px;border-radius:18px;display:inline-flex;align-items:center;justify-content:center;background:linear-gradient(135deg,#ecfeff,#fef3c7);color:#0f766e;font-size:1.3rem;margin-bottom:16px}.hero-panel{background:rgba(255,255,255,.1);border:1px solid rgba(255,255,255,.12);border-radius:24px;padding:20px}.footer-grid a{color:#d7ece8;text-decoration:none}.footer-grid a:hover{color:#fff}.footer-note{color:#a7c9c1}.btn-outline-light,.btn-outline-dark{font-weight:600;border-radius:14px}.content-card:nth-child(odd){background:linear-gradient(180deg,rgba(255,255,255,.94),rgba(240,253,250,.96))}.content-card:nth-child(even){background:linear-gradient(180deg,rgba(255,255,255,.94),rgba(255,247,237,.96))}@media (max-width:991.98px){.navbar-nav{padding-top:12px;gap:6px}.hero{padding:112px 0 58px}}@media (max-width:767.98px){.hero{padding:104px 0 48px}.content-card{border-radius:22px}.container{padding-left:18px;padding-right:18px}}</style>
</head>
<body>
    <nav class="navbar navbar-expand-lg navbar-dark fixed-top"><div class="container"><a class="navbar-brand fw-bold" href="{{ url_for('index') }}"><i class="bi bi-lightning-charge-fill"></i> EcoPulse</a><button class="navbar-toggler" type="button" data-bs-toggle="collapse" data-bs-target="#publicNav"><span class="navbar-toggler-icon"></span></button><div class="collapse navbar-collapse" id="publicNav"><div class="navbar-nav ms-auto align-items-lg-center gap-lg-2"><a class="nav-link" href="{{ url_for('index') }}">Home</a><a class="nav-link" href="{{ url_for('services') }}">Services</a><a class="nav-link" href="{{ url_for('careers') }}">Careers</a><a class="nav-link" href="{{ url_for('about') }}">About</a><a class="nav-link" href="{{ url_for('news') }}">News</a><a class="nav-link" href="{{ url_for('login') }}">Customer Login</a><a class="btn btn-outline-light ms-lg-2" href="{{ url_for('register') }}">Register</a><a class="nav-link ms-lg-2" href="{{ url_for('staff_login') }}">Admin / Examiner Login</a></div></div></div></nav>
    <section class="hero"><div class="container"><div class="row align-items-end g-4"><div class="col-lg-8"><div class="glass-chip"><i class="bi bi-stars"></i> {{ page_name }}</div><h1 class="display-5 fw-bold">{{ hero_title }}</h1><p class="lead col-lg-10">{{ hero_text }}</p></div><div class="col-lg-4"><div class="hero-panel"><div class="small text-uppercase mb-2">EcoPulse Focus</div><div class="fw-semibold">Energy visibility, workflow clarity, and practical sustainability action.</div></div></div></div></div></section>
    <section class="py-5"><div class="container"><div class="row g-4">{% for section in sections %}<div class="col-md-6"><div class="card content-card p-4 p-lg-5 h-100"><div class="feature-icon"><i class="bi bi-lightning"></i></div><h4>{{ section.title }}</h4><p class="text-muted mb-0">{{ section.text }}</p></div></div>{% endfor %}</div></div></section>
    <footer class="py-5" style="background:#041b1b;color:#d7ece8"><div class="container"><div class="row g-4 align-items-start"><div class="col-md-5"><h5 class="mb-3">EcoPulse</h5><p class="mb-0 footer-note">Energy monitoring, workflow visibility, and responsive customer support.</p></div><div class="col-md-7"><div class="footer-grid d-flex flex-wrap gap-3 justify-content-md-end">{% for label, endpoint in footer_links %}<a href="{{ url_for(endpoint) }}">{{ label }}</a>{% endfor %}</div></div></div><div class="d-flex justify-content-between align-items-center border-top border-secondary pt-3 mt-4 flex-wrap gap-2"><small>&copy; 2026 EcoPulse. All rights reserved.</small><small class="footer-note">Committed to a green future</small></div></div></footer>
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
"""

contact_page_template = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Contact EcoPulse</title>
    <link rel="icon" type="image/svg+xml" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Crect width='64' height='64' rx='16' fill='%23062f2f'/%3E%3Cpath d='M35 6 18 34h11l-4 24 21-31H34z' fill='%23f59e0b'/%3E%3C/svg%3E">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.0/font/bootstrap-icons.css">
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;700&family=Source+Sans+3:wght@400;600&display=swap" rel="stylesheet">
    <style>:root{--forest:#062f2f;--teal:#0f766e;--amber:#f59e0b}body{background:radial-gradient(circle at top,#f7fffc 0,#f8fafc 36%,#eef6f4 100%);font-family:'Source Sans 3',sans-serif;color:#0f172a}.navbar{backdrop-filter:blur(14px);background:rgba(6,47,47,.9)!important;box-shadow:0 10px 30px rgba(6,47,47,.16)}h1,h2,h3,.navbar-brand{font-family:'Space Grotesk',sans-serif}.hero{background:radial-gradient(circle at top left,rgba(255,255,255,.14),transparent 24%),linear-gradient(145deg,#062f2f,#0f766e 60%,#d97706);color:white;padding:126px 0 64px}.hero p{color:rgba(255,255,255,.85)}.card{border:1px solid rgba(15,23,42,.08);border-radius:26px;box-shadow:0 20px 52px rgba(15,23,42,.08);background:rgba(255,255,255,.96)}.detail-row{display:flex;gap:14px;align-items:flex-start;padding:14px 0;border-bottom:1px solid #eef2f7}.detail-row:last-child{border-bottom:0}.detail-icon{width:42px;height:42px;border-radius:14px;display:inline-flex;align-items:center;justify-content:center;background:linear-gradient(135deg,#ecfeff,#fef3c7);color:#0f766e}.form-control,textarea{border-radius:16px;padding:.88rem 1rem;border:1px solid #dce7e5}.form-control:focus,textarea:focus{border-color:#0f766e;box-shadow:0 0 0 .2rem rgba(15,118,110,.14)}.btn-dark{background:linear-gradient(135deg,#062f2f,#0f766e);border:none;border-radius:16px;padding:.9rem 1.1rem;font-weight:700}.map-frame{min-height:380px;border:0;border-radius:26px;box-shadow:0 20px 52px rgba(15,23,42,.1)}.footer-note{color:#6b7280}@media (max-width:767.98px){.hero{padding:108px 0 52px}.card,.map-frame{border-radius:22px}}</style>
</head>
<body>
    <nav class="navbar navbar-expand-lg navbar-dark fixed-top"><div class="container"><a class="navbar-brand fw-bold" href="{{ url_for('index') }}"><i class="bi bi-lightning-charge-fill"></i> EcoPulse</a><button class="navbar-toggler" type="button" data-bs-toggle="collapse" data-bs-target="#contactNav"><span class="navbar-toggler-icon"></span></button><div class="collapse navbar-collapse" id="contactNav"><div class="navbar-nav ms-auto align-items-lg-center gap-lg-2"><a class="nav-link" href="{{ url_for('index') }}">Home</a><a class="nav-link" href="{{ url_for('login') }}">Customer Login</a><a class="btn btn-outline-light ms-lg-2" href="{{ url_for('register') }}">Register</a><a class="nav-link ms-lg-2" href="{{ url_for('staff_login') }}">Admin / Examiner Login</a></div></div></div></nav>
    <section class="hero"><div class="container"><div class="row g-4 align-items-end"><div class="col-lg-8"><span class="badge text-bg-light text-dark mb-3">Contact</span><h1 class="display-5 fw-bold">Get in touch with EcoPulse</h1><p class="lead">Use the contact information below for customer support, deployments, and partnership discussions.</p></div><div class="col-lg-4"><div class="card p-4 text-dark"><div class="small text-uppercase text-muted mb-2">Support Promise</div><div class="fw-semibold">We respond with practical guidance for billing, thresholds, workflows, and platform questions.</div></div></div></div></div></section>
    <section class="py-5"><div class="container"><div class="row g-4"><div class="col-lg-5"><div class="card p-4 p-lg-5 h-100"><h3 class="mb-4">Contact details</h3><div class="detail-row"><div class="detail-icon"><i class="bi bi-envelope"></i></div><div><strong>Email</strong><div class="text-muted">support@ecopulse.local</div></div></div><div class="detail-row"><div class="detail-icon"><i class="bi bi-telephone"></i></div><div><strong>Phone</strong><div class="text-muted">+254 700 123 456</div></div></div><div class="detail-row"><div class="detail-icon"><i class="bi bi-geo-alt"></i></div><div><strong>Office</strong><div class="text-muted">EcoPulse Centre, Kisii Town, Kenya</div></div></div><div class="detail-row"><div class="detail-icon"><i class="bi bi-clock"></i></div><div><strong>Hours</strong><div class="text-muted">Monday to Saturday, 8:00 AM to 6:00 PM</div></div></div>{% if contact_success %}<div class="alert alert-info mt-4 mb-0">{{ contact_success }}</div>{% endif %}</div></div><div class="col-lg-7"><div class="card p-4 p-lg-5 mb-4"><h3>Send a message</h3><form method="POST" class="row g-3 mt-1"><div class="col-md-6"><label class="form-label">Name</label><input class="form-control" name="name" required></div><div class="col-md-6"><label class="form-label">Email</label><input class="form-control" type="email" name="email" required></div><div class="col-12"><label class="form-label">Subject</label><input class="form-control" name="subject" required></div><div class="col-12"><label class="form-label">Message</label><textarea class="form-control" name="message" rows="5" required></textarea></div><div class="col-12"><button class="btn btn-dark" type="submit">Send Message</button></div></form></div><iframe class="w-100 map-frame" loading="lazy" src="https://www.google.com/maps?q=Kisii%20Town%20Kenya&z=13&output=embed"></iframe></div></div><div class="d-flex justify-content-between align-items-center border-top pt-3 mt-4 flex-wrap gap-2"><small>&copy; 2026 EcoPulse. All rights reserved.</small><small class="footer-note">Committed to a green future</small></div></div></section>
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
"""

customer_dashboard_template_v2 = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Customer Dashboard - EcoPulse</title>
    <link rel="icon" type="image/svg+xml" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Crect width='64' height='64' rx='16' fill='%23062f2f'/%3E%3Cpath d='M35 6 18 34h11l-4 24 21-31H34z' fill='%23f59e0b'/%3E%3C/svg%3E">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.0/font/bootstrap-icons.css">
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        :root{--dash-ink:#062f2f;--dash-accent:#0f766e;--dash-soft:#ecfdf5;--dash-border:rgba(15,23,42,0.08);--dash-glow:rgba(52,211,153,.24)}
        body{margin:0;background:radial-gradient(circle at top left,rgba(52,211,153,.18),transparent 22%),radial-gradient(circle at bottom right,rgba(245,158,11,.12),transparent 20%),linear-gradient(180deg,#edf8f4 0,#f5fbf9 36%,#eef7ff 100%);padding-top:86px;color:#102a2a;overflow-x:hidden}
        .navbar{background:rgba(6,47,47,.94);backdrop-filter:blur(10px);box-shadow:0 10px 30px rgba(6,47,47,.18)}
        .card{border:1px solid var(--dash-border);border-radius:24px;box-shadow:0 18px 42px rgba(15,23,42,0.08);background:rgba(255,255,255,.95);transition:transform 0.3s ease, box-shadow 0.3s ease}
        .card:hover{transform:translateY(-5px);box-shadow:0 25px 50px rgba(15,23,42,0.12)}

        .hero-strip {
            background: linear-gradient(120deg, rgba(6,47,47,0.85), rgba(15,118,110,0.75));
            color: white;
            border-radius: 28px;
            padding: 32px;
            box-shadow: 0 24px 60px rgba(6,47,47,.22);
            position: relative;
            overflow: hidden;
            z-index: 1;
        }
        .hero-strip::before {
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background-image: url('https://images.unsplash.com/photo-1497436072909-60f360e1d4b1?auto=format&fit=crop&w=1600&q=80');
            background-size: cover;
            background-position: center;
            opacity: 0.35;
            z-index: -1;
            transform: scaleX(-1);
        }
        .hero-strip::after {
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: linear-gradient(120deg, rgba(6,47,47,0.6), rgba(15,118,110,0.5));
            z-index: -1;
        }

        /* Appliance List Styles */
        .appliance-card {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
        }
        .appliance-item {
            background: rgba(255,255,255,0.15);
            border-radius: 12px;
            padding: 12px;
            margin-bottom: 10px;
            transition: all 0.3s ease;
        }
        .appliance-item:hover {
            background: rgba(255,255,255,0.25);
            transform: translateX(5px);
        }
        .appliance-name {
            font-weight: 600;
            font-size: 1rem;
        }
        .appliance-watts {
            font-size: 0.8rem;
            opacity: 0.9;
        }
        .suggestion-badge {
            background: #ff6b6b;
            color: white;
            padding: 5px 10px;
            border-radius: 20px;
            font-size: 0.7rem;
            font-weight: 600;
        }
        .warning-appliance {
            border-left: 4px solid #ff6b6b;
        }
        .safe-appliance {
            border-left: 4px solid #00b894;
        }
        .prediction-card {
            background: linear-gradient(135deg, #0f172a 0%, #134e4a 100%);
            color: white;
        }
        .device-mini-card {
            border: 1px solid rgba(15, 23, 42, 0.08);
            border-radius: 18px;
            background: #fff;
            padding: 16px;
        }
        .device-action-row {
            display: flex;
            gap: 10px;
            flex-wrap: wrap;
        }
        .device-action-row .btn {
            flex: 1 1 140px;
        }
        .device-form-shell {
            border: 1px solid rgba(255, 255, 255, 0.18);
            border-radius: 18px;
            padding: 18px;
            background: rgba(255, 255, 255, 0.12);
        }

        .consumption-section { width: 100%; margin: 0; padding: 0; }
        .consumption-card { width: 100%; margin-bottom: 30px; }
        .chart-container { position: relative; height: 400px; width: 100%; margin-bottom: 30px; }
        .chart-row { display: flex; flex-wrap: wrap; gap: 30px; margin-bottom: 30px; }
        .chart-col { flex: 1; min-width: 300px; background: white; border-radius: 20px; padding: 20px; box-shadow: 0 5px 20px rgba(0,0,0,0.08); }
        .chart-col canvas { max-height: 350px; width: 100% !important; }
        .stats-summary { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; border-radius: 20px; padding: 25px; margin-bottom: 30px; }
        .stats-summary h4 { margin-bottom: 20px; font-weight: 700; }
        .stats-grid-custom { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px; }
        .stat-item { text-align: center; padding: 15px; background: rgba(255,255,255,0.15); border-radius: 15px; backdrop-filter: blur(10px); }
        .stat-value { font-size: 2rem; font-weight: 700; }
        .stat-label { font-size: 0.85rem; opacity: 0.9; margin-top: 5px; }
        .table-responsive{border-radius:18px}
        .table thead th{background:#f8fafc;color:#334155;border-bottom:0;white-space:nowrap}
        .btn{border-radius:14px;padding:.7rem 1rem;font-weight:600}
        .btn-sm{border-radius:12px}
        .btn-dark{background:linear-gradient(135deg,#062f2f,#0f766e);border:none}
        .btn-outline-dark{border-color:#0f766e;color:#0f766e}
        .btn-outline-dark:hover{background:#0f766e;border-color:#0f766e}
        .form-control,.form-select{border-radius:14px;padding:.78rem .95rem;border:1px solid #dbe5e7}
        .form-control:focus,.form-select:focus{border-color:#0f766e;box-shadow:0 0 0 .2rem rgba(15,118,110,.12)}
        .metric-card h3{font-size:clamp(1.35rem,2vw,1.9rem)}
        .section-head{display:flex;justify-content:space-between;align-items:center;gap:1rem;flex-wrap:wrap}
        .surface{background:linear-gradient(180deg,#ffffff,#f8fffd)}
        .compact-note{background:var(--dash-soft);border:1px solid rgba(15,118,110,.12);border-radius:18px}
        .smart-meter{background:linear-gradient(145deg,#052f2c,#0f766e 62%,#34d399);color:#fff;overflow:hidden;position:relative}
        .smart-meter:after{content:'';position:absolute;right:-36px;top:-36px;width:140px;height:140px;border-radius:50%;background:rgba(255,255,255,.08)}
        .meter-ring{width:118px;height:118px;border-radius:50%;display:grid;place-items:center;background:conic-gradient(#f59e0b 0 calc(var(--meter-value) * 1%),rgba(255,255,255,.15) 0);padding:10px;box-shadow:0 0 0 10px rgba(255,255,255,.05)}
        .meter-ring span{width:100%;height:100%;border-radius:50%;display:grid;place-items:center;background:#062f2f;font-weight:700;font-size:1.1rem}
        .meter-chip{display:inline-flex;align-items:center;gap:8px;padding:8px 12px;border-radius:999px;background:rgba(255,255,255,.12);border:1px solid rgba(255,255,255,.16)}
        .accent-panel{background:linear-gradient(180deg,#fff,#f0fdf9)}
        .story-card{background:linear-gradient(180deg,#fff,#effcf6)}
        .warm-card{background:linear-gradient(180deg,#fff,#fff7ed)}

        @media (max-width:991.98px){
            body{padding-top:78px}
            .hero-strip{padding:24px}
            .chart-row{flex-direction:column}
            .chart-col{min-width:100%}
            .chart-container{height:300px}
            .section-head .btn,.section-head .btn-group,.section-head form{width:100%}
            .section-head .btn{justify-content:center}
        }
        @media (max-width:767.98px){
            body{padding-top:74px}
            .container{padding-left:16px;padding-right:16px}
            .card{border-radius:20px}
            .hero-strip{border-radius:24px;padding:22px}
            .chart-container{height:250px}
            .stats-grid-custom{grid-template-columns:1fr}
            .btn,.btn-sm{width:100%}
            .meter-ring{margin:auto}
        }
    </style>
</head>
<body>
    <nav class="navbar navbar-expand-lg navbar-dark fixed-top">
        <div class="container">
            <a class="navbar-brand fw-bold" href="{{ url_for('dashboard') }}"><i class="bi bi-lightning-charge-fill"></i> EcoPulse</a>
            <button class="navbar-toggler" type="button" data-bs-toggle="collapse" data-bs-target="#dashNav">
                <span class="navbar-toggler-icon"></span>
            </button>
            <div class="collapse navbar-collapse" id="dashNav">
                <ul class="navbar-nav ms-auto">
                    <li class="nav-item"><a class="nav-link" href="{{ url_for('ai_analysis') }}"><i class="bi bi-robot"></i> AI Analysis</a></li>
                    <li class="nav-item"><a class="nav-link" href="{{ url_for('settings') }}"><i class="bi bi-gear"></i> Settings</a></li>
                    <li class="nav-item"><a class="nav-link" href="{{ url_for('logout') }}"><i class="bi bi-box-arrow-right"></i> Logout</a></li>
                </ul>
            </div>
        </div>
    </nav>

    <div class="container pb-5">
        <!-- Hero Section with backward layered image -->
        <div class="hero-strip mb-4">
            <div class="row g-3 align-items-center">
                <div class="col-lg-8">
                    <h1 class="h2 fw-bold mb-2">Welcome back, {{ current_user.username }}</h1>
                    <p class="mb-0">Track readings, monitor appliance energy consumption, get smart recommendations, and view AI prediction of energy consumption.</p>
                </div>
                <div class="col-lg-4 text-lg-end">
                    <span class="badge text-bg-light text-dark"><i class="bi bi-speedometer2"></i> Threshold {{ current_user.threshold }} kWh</span>
                    <span class="badge text-bg-light text-dark"><i class="bi bi-qr-code"></i> Meter {{ current_user.meter_number }}</span>
                    <span class="badge text-bg-warning"><i class="bi bi-shield-check"></i> {{ 'Overage enabled' if user_settings.allow_overage else 'Protect mode' }}</span>
                    {% if current_tariff %}<span class="badge text-bg-info text-dark"><i class="bi bi-tag"></i> KPLC Ksh {{ "%.2f"|format(current_tariff.cost_per_unit) }}/unit</span>{% endif %}
                    {% if device_prediction.top_device %}<span class="badge text-bg-success"><i class="bi bi-cpu"></i> Predicted top device: {{ device_prediction.top_device.name }}</span>{% endif %}
                    <a href="{{ url_for('ai_analysis') }}" class="btn btn-sm btn-light mt-2"><i class="bi bi-graph-up"></i> Course AI View</a>
                </div>
            </div>
        </div>

        <!-- Threshold Usage Bar -->
        <div class="row mb-3">
            <div class="col-12">
                {% set current_total = analytics.total_kwh if analytics else 0 %}
                {% set percentage = (current_total / current_user.threshold * 100) if current_user.threshold > 0 else 0 %}
                {% set remaining = current_user.threshold - current_total if current_user.threshold > current_total else 0 %}

                <div class="card p-3">
                    <div class="d-flex justify-content-between align-items-center mb-2">
                        <strong><i class="bi bi-speedometer2"></i> Monthly Threshold Usage</strong>
                        <strong class="{% if percentage >= 100 %}text-danger{% elif percentage >= 90 %}text-warning{% else %}text-success{% endif %}">
                            {{ "%.1f"|format(percentage) }}% ({{ "%.0f"|format(current_total) }} / {{ current_user.threshold }} kWh)
                        </strong>
                    </div>
                    <div class="progress mb-2" style="height: 25px;">
                        <div class="progress-bar {% if percentage >= 100 %}bg-danger{% elif percentage >= 95 %}bg-danger{% elif percentage >= 90 %}bg-warning{% elif percentage >= 80 %}bg-warning{% else %}bg-success{% endif %}" 
                             role="progressbar" 
                             style="width: {{ percentage }}%" 
                             aria-valuenow="{{ percentage }}" 
                             aria-valuemin="0" 
                             aria-valuemax="100">
                            {{ "%.1f"|format(percentage) }}%
                        </div>
                    </div>
                    <div class="d-flex justify-content-between align-items-center">
                        <div>
                            {% if remaining > 0 %}
                                <small class="text-muted"><i class="bi bi-battery-half"></i> {{ "%.2f"|format(remaining) }} kWh remaining</small>
                            {% else %}
                                <small class="text-danger"><i class="bi bi-exclamation-triangle"></i> Exceeded by {{ "%.2f"|format(current_total - current_user.threshold) }} kWh</small>
                            {% endif %}
                        </div>
                        <div>
                            {% if percentage >= 80 %}
                                <a href="{{ url_for('recharge_energy') }}" class="btn btn-danger btn-sm">
                                    <i class="bi bi-lightning-charge"></i> RECHARGE NOW
                                </a>
                            {% else %}
                                <a href="{{ url_for('recharge_energy') }}" class="btn btn-outline-success btn-sm">
                                    <i class="bi bi-plus-circle"></i> Recharge Energy
                                </a>
                            {% endif %}
                        </div>
                    </div>
                </div>
            </div>
        </div>

        {% with messages = get_flashed_messages(with_categories=true) %}
            {% for category, msg in messages %}
                <div class="alert alert-{{ 'warning' if category == 'warning' else 'info' }} alert-dismissible fade show" role="alert">
                    <i class="bi bi-info-circle-fill"></i> {{ msg }}
                    <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
                </div>
            {% endfor %}
        {% endwith %}

        <!-- Smart Meter Card -->
        <div class="card smart-meter p-4 mb-4">
            <div class="row g-4 align-items-center">
                <div class="col-lg-7">
                    <div class="d-flex flex-wrap gap-2 mb-3">
                        <span class="meter-chip"><i class="bi bi-house-door-fill"></i> {{ smart_meter.title }}</span>
                        <span class="meter-chip"><i class="bi bi-patch-check-fill"></i> {{ smart_meter.status }}</span>
                    </div>
                    <h3 class="fw-bold mb-2">{{ smart_meter.reading_value }}</h3>
                    <p class="mb-3" style="color:rgba(255,255,255,.82)">{{ smart_meter.reading_label }}</p>
                    <div class="row g-3">
                        <div class="col-sm-6">
                            <div class="p-3 rounded-4" style="background:rgba(255,255,255,.1)">
                                <small class="d-block" style="color:rgba(255,255,255,.7)"><i class="bi bi-check-circle"></i> Verification</small>
                                <strong>{{ smart_meter.support_value }}</strong>
                                <div class="small" style="color:rgba(255,255,255,.72)">{{ smart_meter.support_label }}</div>
                            </div>
                        </div>
                        <div class="col-sm-6">
                            <div class="p-3 rounded-4" style="background:rgba(255,255,255,.1)">
                                <small class="d-block" style="color:rgba(255,255,255,.7)"><i class="bi bi-graph-up"></i> Status</small>
                                <strong>{{ smart_meter.detail_primary }}</strong>
                                <div class="small" style="color:rgba(255,255,255,.72)">{{ smart_meter.detail_secondary }}</div>
                            </div>
                        </div>
                    </div>
                </div>
                <div class="col-lg-5 text-center text-lg-end">
                    <div class="meter-ring ms-lg-auto" style="--meter-value: {{ smart_meter.ring_value }};">
                        <span>{{ smart_meter.ring_value }}%</span>
                    </div>
                    <div class="mt-3 small" style="color:rgba(255,255,255,.8)">{{ smart_meter.ring_label }}</div>
                </div>
            </div>
        </div>

        <!-- Stats Cards -->
        <div class="row g-4 mb-4">
            <div class="col-md-3">
                <div class="card surface metric-card p-4 h-100 text-center">
                    <i class="bi bi-lightning-charge fs-1 text-primary"></i>
                    <small class="text-muted mt-2">Total kWh</small>
                    <h3 class="fw-bold mb-0">{{ analytics.total_kwh if analytics else 0 }}</h3>
                </div>
            </div>
            <div class="col-md-3">
                <div class="card surface metric-card p-4 h-100 text-center">
                    <i class="bi bi-bar-chart-line fs-1 text-success"></i>
                    <small class="text-muted mt-2">Average</small>
                    <h3 class="fw-bold mb-0">{{ analytics.avg_kwh if analytics else 0 }}</h3>
                </div>
            </div>
            <div class="col-md-3">
                <div class="card surface metric-card p-4 h-100 text-center">
                    <i class="bi bi-cash-coin fs-1 text-warning"></i>
                    <small class="text-muted mt-2">Estimated Cost</small>
                    <h3 class="fw-bold mb-0">{{ analytics.currency if analytics else current_user.currency }} {{ analytics.total_cost if analytics else 0 }}</h3>
                </div>
            </div>
            <div class="col-md-3">
                <div class="card surface metric-card p-4 h-100 text-center">
                    <i class="bi bi-cloud fs-1 text-info"></i>
                    <small class="text-muted mt-2">CO2 Emissions</small>
                    <h3 class="fw-bold mb-0">{{ analytics.total_co2 if analytics else 0 }} kg</h3>
                </div>
            </div>
        </div>

        <!-- Add Reading and Threshold Behavior -->
        <div class="row g-4 mb-4">
            <div class="col-lg-8">
                <div class="card p-4 h-100">
                    <div class="section-head mb-3">
                        <h3 class="h5 fw-bold mb-0"><i class="bi bi-plus-circle"></i> Add Reading</h3>
                        <a href="{{ url_for('settings') }}" class="btn btn-sm btn-outline-dark"><i class="bi bi-sliders2"></i> Threshold Settings</a>
                    </div>
                    <form method="POST" action="{{ url_for('add_reading') }}" class="row g-3">
                        <div class="col-md-4">
                            <label class="form-label"><i class="bi bi-calendar"></i> Period</label>
                            <input type="text" name="date" class="form-control" placeholder="e.g. March 2026" required>
                        </div>
                        <div class="col-md-4">
                            <label class="form-label"><i class="bi bi-lightning"></i> kWh</label>
                            <input type="number" name="kwh" step="0.01" class="form-control" placeholder="Enter consumption" required>
                        </div>
                        <div class="col-md-4">
                            <label class="form-label"><i class="bi bi-clock"></i> Timestamp</label>
                            <input type="datetime-local" name="timestamp" class="form-control" value="{{ now|local_datetime_input }}" required>
                        </div>
                        <div class="col-12">
                            <button type="submit" class="btn btn-dark w-100"><i class="bi bi-save"></i> Save Reading</button>
                        </div>
                    </form>
                </div>
            </div>
            <div class="col-lg-4">
                <div class="card surface p-4 h-100">
                    <h3 class="h5 fw-bold"><i class="bi bi-shield-shaded"></i> Threshold Behavior</h3>
                    <p class="text-muted">If overage is enabled, usage continues and extra units are billed with a surcharge. If protect mode is active, EcoPulse raises alerts and can schedule a shutdown reminder.</p>
                    {% if threshold_state %}
                        <div class="alert {{ 'alert-info' if threshold_state.allow_overage else 'alert-warning' }}">
                            <i class="bi bi-exclamation-triangle-fill"></i>
                            Latest reading: {{ threshold_state.latest_kwh }} kWh against {{ threshold_state.threshold }} kWh.
                            {% if threshold_state.allow_overage %} Extra charge applied: {{ current_user.currency }} {{ "%.2f"|format(threshold_state.overage_charge) }}.
                            {% elif threshold_state.scheduled_shutdown_at %} Auto shutdown scheduled for {{ threshold_state.scheduled_shutdown_at|local_datetime }}.
                            {% endif %}
                        </div>
                    {% else %}
                        <div class="alert alert-success mb-0 compact-note">
                            <i class="bi bi-check-circle-fill"></i> No threshold breach is active right now.
                        </div>
                    {% endif %}
                </div>
            </div>
        </div>

        <div class="row g-4 mb-4">
            <div class="col-lg-8">
                <div class="card prediction-card p-4 h-100">
                    <div class="section-head mb-3">
                        <h3 class="h5 fw-bold mb-0"><i class="bi bi-stars"></i> AI Energy Consumption Prediction</h3>
                        <span class="badge text-bg-light text-dark">{{ 'Using your saved devices' if customer_devices else 'Using estimated appliance profiles' }}</span>
                    </div>
                    <div class="row g-3 mb-3">
                        <div class="col-md-4">
                            <div class="p-3 rounded-4" style="background:rgba(255,255,255,.12)">
                                <small class="d-block" style="color:rgba(255,255,255,.72)">Projected device load</small>
                                <strong class="fs-4">{{ "%.2f"|format(device_prediction.projected_total) }} kWh/month</strong>
                            </div>
                        </div>
                        <div class="col-md-4">
                            <div class="p-3 rounded-4" style="background:rgba(255,255,255,.12)">
                                <small class="d-block" style="color:rgba(255,255,255,.72)">Projected threshold usage</small>
                                <strong class="fs-4">{{ "%.1f"|format(device_prediction.projected_utilization) }}%</strong>
                            </div>
                        </div>
                        <div class="col-md-4">
                            <div class="p-3 rounded-4" style="background:rgba(255,255,255,.12)">
                                <small class="d-block" style="color:rgba(255,255,255,.72)">Current recorded usage</small>
                                <strong class="fs-4">{{ "%.1f"|format(device_prediction.current_utilization) }}%</strong>
                            </div>
                        </div>
                    </div>
                    {% if device_prediction.top_device %}
                    <div class="alert alert-light mb-0">
                        <strong>Predicted highest-consuming device:</strong> {{ device_prediction.top_device.name }}
                        at {{ "%.2f"|format(device_prediction.top_device.monthly_kwh) }} kWh/month.
                        <div class="small mt-2">{{ device_prediction.recommendation }}</div>
                    </div>
                    {% endif %}
                </div>
            </div>
            <div class="col-lg-4">
                <div class="card surface p-4 h-100">
                    <h3 class="h5 fw-bold"><i class="bi bi-bell"></i> Notification Test</h3>
                    <p class="text-muted">Use your registered email and phone number to test threshold notifications on the customer page.</p>
                    <div class="small mb-3">
                        <div><strong>Email:</strong> {{ current_user.email }}</div>
                        <div><strong>Phone:</strong> {{ current_user.phone_number or 'Not set' }}</div>
                    </div>
                    <form method="POST" action="{{ url_for('test_customer_notifications') }}" class="row g-3">
                        <div class="col-12">
                            <label class="form-label">Simulated usage (kWh)</label>
                            <input type="number" name="simulated_total_kwh" step="0.01" min="1" value="{{ current_user.threshold }}" class="form-control">
                        </div>
                        <div class="col-12">
                            <button type="submit" class="btn btn-outline-dark w-100"><i class="bi bi-send-check"></i> Send Test Notification</button>
                        </div>
                    </form>
                    <div class="alert alert-info mt-3 mb-0 small">
                        Automatic email and SMS notifications now trigger when your recorded consumption reaches the configured threshold levels.
                    </div>
                </div>
            </div>
        </div>

        <!-- APPLIANCE ENERGY MONITORING SECTION -->
        <div class="card appliance-card mb-4">
            <div class="card-header">
                <i class="bi bi-cpu"></i> Smart Appliance Energy Monitor
            </div>
            <div class="card-body">
                <div class="row">
                    <div class="col-12 mb-3">
                        <div class="alert alert-info">
                            <i class="bi bi-info-circle"></i> <strong>Energy Saving Tips:</strong> The table below shows estimated energy consumption of common appliances. When your usage is high, focus on reducing appliances marked with <span class="suggestion-badge">⚠️ High Impact</span>.
                        </div>
                    </div>
                </div>

                <div class="device-form-shell mb-4" id="device-manager">
                    <div class="d-flex justify-content-between align-items-center flex-wrap gap-2 mb-3">
                        <h6 class="mb-0"><i class="bi bi-hdd-network"></i> Devices and Appliances</h6>
                        <div class="device-action-row">
                            <a href="#device-add-form" class="btn btn-light btn-sm"><i class="bi bi-plus-circle"></i> Add</a>
                            <a href="#device-list" class="btn btn-outline-light btn-sm"><i class="bi bi-pencil-square"></i> Manage</a>
                            <a href="#device-list" class="btn btn-outline-danger btn-sm"><i class="bi bi-trash"></i> Remove</a>
                        </div>
                    </div>
                    <div class="row g-4">
                        <div class="col-lg-5">
                            <form method="POST" action="{{ url_for('add_customer_device') }}" id="device-add-form" class="row g-3">
                                <div class="col-12">
                                    <label class="form-label">Device name</label>
                                    <input type="text" name="name" class="form-control" placeholder="e.g. Air Conditioner" required>
                                </div>
                                <div class="col-md-6">
                                    <label class="form-label">Category</label>
                                    <input type="text" name="category" class="form-control" value="Appliance" required>
                                </div>
                                <div class="col-md-6">
                                    <label class="form-label">Quantity</label>
                                    <input type="number" name="quantity" class="form-control" min="1" value="1" required>
                                </div>
                                <div class="col-md-6">
                                    <label class="form-label">Power (W)</label>
                                    <input type="number" name="watts" class="form-control" min="1" step="0.01" required>
                                </div>
                                <div class="col-md-6">
                                    <label class="form-label">Hours/day</label>
                                    <input type="number" name="hours_per_day" class="form-control" min="0.1" step="0.1" required>
                                </div>
                                <div class="col-12">
                                    <label class="form-label">Notes</label>
                                    <input type="text" name="notes" class="form-control" placeholder="Optional">
                                </div>
                                <div class="col-12">
                                    <button type="submit" class="btn btn-light w-100"><i class="bi bi-plus-circle"></i> Add Device</button>
                                </div>
                            </form>
                        </div>
                        <div class="col-lg-7" id="device-list">
                            {% if customer_devices %}
                                <div class="row g-3">
                                    {% for device in device_prediction.devices %}
                                    <div class="col-12">
                                        <div class="device-mini-card">
                                            <div class="d-flex justify-content-between align-items-start gap-3 mb-3">
                                                <div>
                                                    <div class="fw-bold">{{ device.name }}</div>
                                                    <small class="text-muted">{{ device.category }}{% if device.notes %} | {{ device.notes }}{% endif %}</small>
                                                </div>
                                                <span class="badge {% if loop.first %}bg-danger{% else %}bg-secondary{% endif %}">
                                                    {{ "%.2f"|format(device.monthly_kwh) }} kWh/mo
                                                </span>
                                            </div>
                                            <form method="POST" action="{{ url_for('update_customer_device', device_id=device.id) }}" class="row g-2">
                                                <div class="col-md-4"><input type="text" name="name" class="form-control form-control-sm" value="{{ device.name }}" required></div>
                                                <div class="col-md-2"><input type="number" name="quantity" class="form-control form-control-sm" min="1" value="{{ device.quantity }}" required></div>
                                                <div class="col-md-2"><input type="number" name="watts" class="form-control form-control-sm" min="1" step="0.01" value="{{ device.watts }}" required></div>
                                                <div class="col-md-2"><input type="number" name="hours_per_day" class="form-control form-control-sm" min="0.1" step="0.1" value="{{ device.hours_per_day }}" required></div>
                                                <div class="col-md-2"><input type="text" name="category" class="form-control form-control-sm" value="{{ device.category }}" required></div>
                                                <div class="col-12"><input type="text" name="notes" class="form-control form-control-sm" value="{{ device.notes or '' }}" placeholder="Notes"></div>
                                                <div class="col-12"><button type="submit" class="btn btn-outline-dark btn-sm w-100"><i class="bi bi-pencil-square"></i> Manage</button></div>
                                            </form>
                                            <form method="POST" action="{{ url_for('delete_customer_device', device_id=device.id) }}" class="mt-2">
                                                <button type="submit" class="btn btn-outline-danger btn-sm w-100"><i class="bi bi-trash"></i> Remove</button>
                                            </form>
                                        </div>
                                    </div>
                                    {% endfor %}
                                </div>
                            {% else %}
                                <div class="alert alert-light mb-0">
                                    No saved customer devices yet. Add one to get a more accurate prediction of which device consumes the most energy.
                                </div>
                            {% endif %}
                        </div>
                    </div>
                </div>

                <!-- Energy Saving Suggestions when threshold is high -->
                {% if percentage >= 80 %}
                <div class="alert alert-warning mb-3">
                    <i class="bi bi-exclamation-triangle-fill"></i> <strong>Energy Saving Recommendations:</strong>
                    <ul class="mb-0 mt-2">
                        {% if percentage >= 100 %}
                            <li>🔴 <strong>CRITICAL:</strong> You have exceeded your threshold by {{ "%.2f"|format(current_total - current_user.threshold) }} kWh!</li>
                            <li>💡 Immediately switch off: Air Conditioner, Water Heater, Electric Oven</li>
                            <li>💡 Reduce usage of: Washing Machine, Dryer, Dishwasher</li>
                        {% elif percentage >= 90 %}
                            <li>⚠️ You have reached {{ "%.0f"|format(percentage) }}% of your threshold!</li>
                            <li>💡 Consider reducing: Air Conditioner usage, limiting oven use, shorter showers (water heater)</li>
                        {% elif percentage >= 80 %}
                            <li>📊 You have reached {{ "%.0f"|format(percentage) }}% of your threshold. Start monitoring high-consumption appliances.</li>
                            <li>💡 Tips: Run dishwasher and washing machine only when full, use energy-saving modes</li>
                        {% endif %}
                    </ul>
                </div>
                {% endif %}

                <!-- Home Appliances Table -->
                <h6 class="mb-3"><i class="bi bi-house"></i> Home Appliances & Estimated Energy Consumption</h6>
                <div class="table-responsive">
                    <table class="table table-dark table-hover">
                        <thead>
                            <tr>
                                <th>Appliance</th>
                                <th>Power (Watts)</th>
                                <th>Daily Use (Hours)</th>
                                <th>Daily kWh</th>
                                <th>Monthly kWh</th>
                                <th>Impact Level</th>
                            </tr>
                        </thead>
                        <tbody>
                            <tr class="{% if percentage >= 85 %}table-danger{% endif %}">
                                <td><i class="bi bi-snow"></i> Air Conditioner (1.5 ton)</td>
                                <td>1500-2000 W</td>
                                <td>5-8 hrs</td>
                                <td>7.5-16 kWh</td>
                                <td>225-480 kWh</td>
                                <td><span class="suggestion-badge">⚠️ High Impact</span></td>
                            </tr>
                            <tr class="{% if percentage >= 85 %}table-danger{% endif %}">
                                <td><i class="bi bi-droplet"></i> Water Heater</td>
                                <td>3000-4500 W</td>
                                <td>1-2 hrs</td>
                                <td>3-9 kWh</td>
                                <td>90-270 kWh</td>
                                <td><span class="suggestion-badge">⚠️ High Impact</span></td>
                            </tr>
                            <tr class="{% if percentage >= 85 %}table-danger{% endif %}">
                                <td><i class="bi bi-thermometer-half"></i> Electric Oven/Stove</td>
                                <td>2000-5000 W</td>
                                <td>1-2 hrs</td>
                                <td>2-10 kWh</td>
                                <td>60-300 kWh</td>
                                <td><span class="suggestion-badge">⚠️ High Impact</span></td>
                            </tr>
                            <tr>
                                <td><i class="bi bi-tsunami"></i> Washing Machine</td>
                                <td>500-1000 W</td>
                                <td>1-2 hrs</td>
                                <td>0.5-2 kWh</td>
                                <td>15-60 kWh</td>
                                <td><span class="badge bg-warning">Medium</span></td>
                            </tr>
                            <tr>
                                <td><i class="bi bi-brightness-high"></i> Dryer</td>
                                <td>2000-4000 W</td>
                                <td>1-2 hrs</td>
                                <td>2-8 kWh</td>
                                <td>60-240 kWh</td>
                                <td><span class="badge bg-warning">Medium-High</span></td>
                            </tr>
                            <tr>
                                <td><i class="bi bi-fridge"></i> Refrigerator</td>
                                <td>100-800 W</td>
                                <td>24 hrs</td>
                                <td>2.4-5 kWh</td>
                                <td>72-150 kWh</td>
                                <td><span class="badge bg-warning">Medium</span></td>
                            </tr>
                            <tr>
                                <td><i class="bi bi-tv"></i> TV (LED 55")</td>
                                <td>60-150 W</td>
                                <td>4-6 hrs</td>
                                <td>0.24-0.9 kWh</td>
                                <td>7-27 kWh</td>
                                <td><span class="badge bg-success">Low</span></td>
                            </tr>
                            <tr>
                                <td><i class="bi bi-laptop"></i> Laptop</td>
                                <td>30-100 W</td>
                                <td>4-6 hrs</td>
                                <td>0.12-0.6 kWh</td>
                                <td>3.6-18 kWh</td>
                                <td><span class="badge bg-success">Low</span></td>
                            </tr>
                            <tr>
                                <td><i class="bi bi-lightbulb"></i> LED Lights (10 bulbs)</td>
                                <td>50-100 W</td>
                                <td>5-8 hrs</td>
                                <td>0.25-0.8 kWh</td>
                                <td>7.5-24 kWh</td>
                                <td><span class="badge bg-success">Low</span></td>
                            </tr>
                            <tr>
                                <td><i class="bi bi-dish"></i> Dishwasher</td>
                                <td>1200-2400 W</td>
                                <td>1-2 hrs</td>
                                <td>1.2-4.8 kWh</td>
                                <td>36-144 kWh</td>
                                <td><span class="badge bg-warning">Medium</span></td>
                            </tr>
                        </tbody>
                    </table>
                </div>

                <!-- Business Appliances Table -->
                <h6 class="mb-3 mt-4"><i class="bi bi-building"></i> Business/Office Appliances</h6>
                <div class="table-responsive">
                    <table class="table table-dark table-hover">
                        <thead>
                            <tr>
                                <th>Appliance</th>
                                <th>Power (Watts)</th>
                                <th>Daily Use (Hours)</th>
                                <th>Daily kWh</th>
                                <th>Monthly kWh</th>
                                <th>Impact Level</th>
                            </tr>
                        </thead>
                        <tbody>
                            <tr>
                                <td><i class="bi bi-server"></i> Server Room (2 servers)</td>
                                <td>600-1200 W</td>
                                <td>24 hrs</td>
                                <td>14.4-28.8 kWh</td>
                                <td>432-864 kWh</td>
                                <td><span class="suggestion-badge">⚠️ High Impact</span></td>
                            </tr>
                            <tr>
                                <td><i class="bi bi-printer"></i> Commercial Printer</td>
                                <td>300-1000 W</td>
                                <td>4-6 hrs</td>
                                <td>1.2-6 kWh</td>
                                <td>36-180 kWh</td>
                                <td><span class="badge bg-warning">Medium</span></td>
                            </tr>
                            <tr>
                                <td><i class="bi bi-display"></i> Desktop Computers (10 units)</td>
                                <td>500-1500 W</td>
                                <td>8 hrs</td>
                                <td>4-12 kWh</td>
                                <td>120-360 kWh</td>
                                <td><span class="badge bg-warning">Medium-High</span></td>
                            </tr>
                            <tr>
                                <td><i class="bi bi-cup-straw"></i> Coffee Machine</td>
                                <td>800-1500 W</td>
                                <td>2-4 hrs</td>
                                <td>1.6-6 kWh</td>
                                <td>48-180 kWh</td>
                                <td><span class="badge bg-warning">Medium</span></td>
                            </tr>
                            <tr>
                                <td><i class="bi bi-fan"></i> Ceiling Fans (5 units)</td>
                                 средњим75-150 W</td>
                                <td>8-10 hrs</td>
                                <td>0.6-1.5 kWh</td>
                                <td>18-45 kWh</td>
                                <td><span class="badge bg-success">Low</span></td>
                            </tr>
                        </tbody>
                    </table>
                </div>

                <!-- Savings Tips based on usage -->
                <div class="row mt-3">
                    <div class="col-md-6">
                        <div class="alert alert-success">
                            <i class="bi bi-lightbulb"></i> <strong>Quick Savings Tips:</strong>
                            <ul class="mb-0 mt-2">
                                <li>Set AC to 24°C (saves 10-15% energy)</li>
                                <li>Use cold water for washing clothes</li>
                                <li>Unplug devices when not in use</li>
                                <li>Use energy-saving mode on all appliances</li>
                            </ul>
                        </div>
                    </div>
                    <div class="col-md-6">
                        <div class="alert alert-info">
                            <i class="bi bi-calculator"></i> <strong>Estimated Savings:</strong>
                            <ul class="mb-0 mt-2">
                                {% if percentage >= 80 %}
                                    <li>Reducing AC by 2 hours daily: Save ~90 kWh/month</li>
                                    <li>Using cold water wash: Save ~30 kWh/month</li>
                                    <li>Total potential savings: <strong>{{ "%.0f"|format(remaining) }} kWh</strong> to reach threshold</li>
                                {% else %}
                                    <li>You're on track! Maintain good habits</li>
                                    <li>Consider solar water heater for long-term savings</li>
                                {% endif %}
                            </ul>
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <!-- FULL WIDTH CONSUMPTION ANALYSIS SECTION -->
        <div class="consumption-section mb-4">
            <div class="card consumption-card p-4">
                <div class="section-head mb-4">
                    <h3 class="h4 fw-bold mb-0"><i class="bi bi-graph-up"></i> Detailed Consumption Analysis</h3>
                    <button class="btn btn-outline-dark" onclick="submitToAdmin()"><i class="bi bi-send"></i> Submit Summary to Admin</button>
                </div>

                <div class="stats-summary mb-4">
                    <h4><i class="bi bi-pie-chart"></i> Your Energy Profile</h4>
                    <div class="stats-grid-custom">
                        <div class="stat-item">
                            <div class="stat-value">{{ analytics.total_kwh if analytics else 0 }}</div>
                            <div class="stat-label">Total kWh Consumed</div>
                        </div>
                        <div class="stat-item">
                            <div class="stat-value">{{ analytics.total_cost if analytics else 0 }}</div>
                            <div class="stat-label">Total Cost ({{ analytics.currency if analytics else current_user.currency }})</div>
                        </div>
                        <div class="stat-item">
                            <div class="stat-value">{{ analytics.total_co2 if analytics else 0 }}</div>
                            <div class="stat-label">CO2 Emissions (kg)</div>
                        </div>
                        <div class="stat-item">
                            <div class="stat-value">{{ ((analytics.total_kwh / current_user.threshold * 100) if analytics and current_user.threshold else 0)|round(1) }}%</div>
                            <div class="stat-label">Threshold Usage</div>
                        </div>
                    </div>
                </div>

                {% if readings %}
                    <div class="chart-container">
                        <canvas id="mainConsumptionChart"></canvas>
                    </div>
                    <div class="chart-row">
                        <div class="chart-col">
                            <h5 class="text-center mb-3"><i class="bi bi-pie-chart-fill"></i> Consumption Distribution</h5>
                            <canvas id="pieChart"></canvas>
                        </div>
                        <div class="chart-col">
                            <h5 class="text-center mb-3"><i class="bi bi-bar-chart-steps"></i> Monthly Trend</h5>
                            <canvas id="trendChart"></canvas>
                        </div>
                        <div class="chart-col">
                            <h5 class="text-center mb-3"><i class="bi bi-speedometer2"></i> Efficiency Score</h5>
                            <canvas id="efficiencyGauge"></canvas>
                        </div>
                    </div>
                    <div class="chart-row">
                        <div class="chart-col">
                            <h5 class="text-center mb-3"><i class="bi bi-cash-stack"></i> Cost Analysis</h5>
                            <canvas id="costChart"></canvas>
                        </div>
                        <div class="chart-col">
                            <h5 class="text-center mb-3"><i class="bi bi-tree"></i> Environmental Impact</h5>
                            <canvas id="environmentChart"></canvas>
                        </div>
                        <div class="chart-col">
                            <h5 class="text-center mb-3"><i class="bi bi-arrow-repeat"></i> Consumption vs Threshold</h5>
                            <canvas id="thresholdComparisonChart"></canvas>
                        </div>
                    </div>
                {% else %}
                    <div class="text-center py-5 text-muted">
                        <i class="bi bi-bar-chart-line fs-1"></i>
                        <p class="mt-3 mb-0">Add readings to generate comprehensive consumption analysis charts.</p>
                    </div>
                {% endif %}
            </div>
        </div>

        <!-- Reports Section -->
        <div class="row g-4 mb-4">
            <div class="col-lg-12">
                <div class="card surface p-4 h-100">
                    <h3 class="h5 fw-bold"><i class="bi bi-envelope"></i> Recent Reports & Alerts</h3>
                    <div class="row">
                        <div class="col-md-6">
                            <h6 class="fw-bold mt-2">System Reports</h6>
                            {% if reports %}
                                {% for report in reports %}
                                    <div class="border rounded-4 p-3 mb-3 bg-light-subtle">
                                        <div class="fw-semibold">{{ report.title }}</div>
                                        <small class="text-muted">{{ report.created_at.strftime('%Y-%m-%d') }}</small>
                                        <div class="small mt-2">{{ report.content|safe }}</div>
                                    </div>
                                {% endfor %}
                            {% else %}
                                <p class="text-muted mb-0">No reports have been sent to your account yet.</p>
                            {% endif %}
                        </div>
                        <div class="col-md-6">
                            <h6 class="fw-bold mt-2">Examiner Alerts</h6>
                            {% if customer_alerts %}
                                {% for item in customer_alerts %}
                                    <div class="border rounded-4 p-3 mb-3 bg-white">
                                        <div class="fw-semibold">{{ item.title }}</div>
                                        <small class="text-muted">{{ item.created_at.strftime('%Y-%m-%d %H:%M') }}</small>
                                        <div class="small mt-2">{{ item.content|safe }}</div>
                                    </div>
                                {% endfor %}
                            {% else %}
                                <p class="text-muted mb-0">No examiner advisories or billing alerts yet.</p>
                            {% endif %}
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <!-- Invoices Section -->
        <div class="card p-4 mb-4">
            <div class="section-head mb-3">
                <h3 class="h5 fw-bold mb-0"><i class="bi bi-receipt"></i> Invoices</h3>
                <span class="text-muted small">{{ customer_invoices|length }} record(s)</span>
            </div>
            {% if customer_invoices %}
                <div class="table-responsive">
                    <table class="table align-middle table-hover">
                        <thead class="table-light">
                            <tr>
                                <th><i class="bi bi-calendar"></i> Period</th>
                                <th><i class="bi bi-lightning"></i> Consumption</th>
                                <th><i class="bi bi-cash"></i> Total</th>
                                <th><i class="bi bi-check-circle"></i> Paid</th>
                                <th><i class="bi bi-wallet"></i> Balance</th>
                                <th><i class="bi bi-calendar-event"></i> Due Date</th>
                                <th><i class="bi bi-tag"></i> Status</th>
                            </tr>
                        </thead>
                        <tbody>
                            {% for invoice in customer_invoices %}
                            <tr>
                                <td>{{ invoice.period }}</td>
                                <td>{{ "%.2f"|format(invoice.total_consumption) }} kWh</td>
                                <td>{{ current_user.currency }} {{ "%.2f"|format(invoice.total_cost) }}</td>
                                <td>{{ current_user.currency }} {{ "%.2f"|format(invoice.total_paid) }}</td>
                                <td>{{ current_user.currency }} {{ "%.2f"|format(invoice.balance) }}</td>
                                <td>{{ invoice.due_date.strftime('%Y-%m-%d') if invoice.due_date else 'N/A' }}</td>
                                <td><span class="badge {% if invoice.payment_status == 'paid' %}bg-success{% elif invoice.payment_status == 'pending' %}bg-warning{% else %}bg-danger{% endif %}">{{ invoice.payment_status }}</span></td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
            {% else %}
                <div class="text-center py-4 text-muted">
                    <i class="bi bi-receipt fs-1"></i>
                    <p class="mt-2 mb-0">No invoices are available for your account yet.</p>
                </div>
            {% endif %}
        </div>

        <!-- Payment Section -->
        <div class="card p-4 mb-4">
            <div class="section-head mb-3">
                <h3 class="h5 fw-bold mb-0"><i class="bi bi-credit-card"></i> Make Payment</h3>
                <span class="text-muted small">{{ payable_invoices|length }} unpaid invoice(s)</span>
            </div>
            {% if payable_invoices %}
                <div class="row g-4">
                    {% for invoice in payable_invoices %}
                        <div class="col-lg-6">
                            <div class="border rounded-4 p-4 h-100 surface">
                                <div class="d-flex justify-content-between align-items-start gap-3 mb-3">
                                    <div>
                                        <div class="fw-semibold fs-5">{{ invoice.period }}</div>
                                        <small class="text-muted">{{ "%.2f"|format(invoice.total_consumption) }} kWh billed</small>
                                    </div>
                                    <span class="badge {% if invoice.payment_status == 'overdue' %}bg-danger{% else %}bg-warning{% endif %} fs-6">{{ invoice.payment_status|upper }}</span>
                                </div>
                                <div class="row g-3 mb-3">
                                    <div class="col-4 text-center"><small class="text-muted d-block">Total</small><strong class="fs-5">{{ current_user.currency }} {{ "%.2f"|format(invoice.total_cost) }}</strong></div>
                                    <div class="col-4 text-center"><small class="text-muted d-block">Paid</small><strong class="fs-5">{{ current_user.currency }} {{ "%.2f"|format(invoice.total_paid) }}</strong></div>
                                    <div class="col-4 text-center"><small class="text-muted d-block">Balance</small><strong class="fs-5 text-warning">{{ current_user.currency }} {{ "%.2f"|format(invoice.balance) }}</strong></div>
                                </div>
                                <form method="POST" action="{{ url_for('customer_make_payment', record_id=invoice.id) }}" class="row g-3" onsubmit="return validatePayment({{ invoice.id }})">
                                    <div class="col-md-6">
                                        <label class="form-label">Payment Method</label>
                                        <select class="form-select" name="payment_method" required>
                                            <option value="">Select method</option>
                                            <option value="mpesa">📱 M-Pesa</option>
                                            <option value="card">💳 Card</option>
                                            <option value="bank_transfer">🏦 Bank Transfer</option>
                                        </select>
                                    </div>
                                    <div class="col-md-6">
                                        <label class="form-label">Phone Number (10 digits)</label>
                                        <input class="form-control" type="tel" name="payment_phone" id="payment_phone_{{ invoice.id }}" maxlength="10" pattern="\\d{10}" placeholder="0712345678" required>
                                    </div>
                                    <div class="col-md-6">
                                        <label class="form-label">Reference (10 chars)</label>
                                        <input class="form-control" type="text" name="payment_reference" id="payment_reference_{{ invoice.id }}" maxlength="10" minlength="10" placeholder="ABC123XYZ7" required>
                                    </div>
                                    <div class="col-md-6">
                                        <label class="form-label">Payment Amount</label>
                                        <input class="form-control" type="number" min="0.01" max="{{ '%.2f'|format(invoice.balance) }}" step="0.01" name="payment_amount" value="{{ '%.2f'|format(invoice.balance) }}" required>
                                    </div>
                                    <div class="col-12">
                                        <button class="btn btn-dark w-100" type="submit">Pay Now</button>
                                    </div>
                                </form>
                            </div>
                        </div>
                    {% endfor %}
                </div>
            {% else %}
                <div class="text-center py-4 text-muted">
                    <i class="bi bi-check-circle-fill fs-1 text-success"></i>
                    <p class="mt-2 mb-0">You have no outstanding invoice balance right now.</p>
                </div>
            {% endif %}
        </div>

        <!-- Analytics, Devices, Support, Community -->
        <div class="row g-4 mb-4">
            <div class="col-lg-6"><div class="card p-4 h-100 accent-panel"><h3 class="h5 fw-bold"><i class="bi bi-graph-up"></i> Analytics</h3><p class="text-muted">Interactive trends help you understand your usage patterns.</p><ul class="mb-0"><li>Energy usage trends from your readings</li><li>Cost and CO2 visibility</li><li>Export-ready data</li></ul></div></div>
            <div class="col-lg-6"><div class="card p-4 h-100 warm-card"><h3 class="h5 fw-bold"><i class="bi bi-cpu"></i> Devices</h3><p class="text-muted">Manage connected IoT devices.</p><div class="row g-3"><div class="col-sm-4"><div class="border rounded-4 p-3 bg-white text-center"><small>Connected Sensors</small><strong class="fs-4">{{ readings|length if readings else 0 }}</strong></div></div><div class="col-sm-4"><div class="border rounded-4 p-3 bg-white text-center"><small>Meter Number</small><strong>{{ current_user.meter_number }}</strong></div></div><div class="col-sm-4"><div class="border rounded-4 p-3 bg-white text-center"><small>KPLC Cost</small><strong>{% if current_tariff %}Ksh {{ "%.2f"|format(current_tariff.cost_per_unit) }}{% else %}Ksh {{ "%.2f"|format(current_user.unit_cost) }}{% endif %}</strong></div></div></div><div class="device-action-row mt-3"><a class="btn btn-outline-dark btn-sm" href="#device-add-form"><i class="bi bi-plus-circle"></i> Add</a><a class="btn btn-outline-dark btn-sm" href="#device-list"><i class="bi bi-pencil-square"></i> Manage</a><a class="btn btn-outline-danger btn-sm" href="#device-list"><i class="bi bi-trash"></i> Remove</a></div></div></div>
        </div>
        <div class="row g-4 mb-4">
            <div class="col-lg-6"><div class="card p-4 h-100 story-card"><h3 class="h5 fw-bold"><i class="bi bi-headset"></i> Support</h3><p class="text-muted">Find help with billing, thresholds, exports, and setup.</p><div class="d-flex gap-2 flex-wrap"><a class="btn btn-outline-dark" href="{{ url_for('contact') }}">Contact Support</a><a class="btn btn-outline-secondary" href="{{ url_for('faqs') }}">View FAQs</a></div></div></div>
            <div class="col-lg-6"><div class="card p-4 h-100" style="background:linear-gradient(180deg,#fff,#eef4ff)"><h3 class="h5 fw-bold"><i class="bi bi-people"></i> Community</h3><p class="text-muted">Learn from user stories and sustainability tips.</p></div></div>
        </div>

        <!-- Readings Table -->
        <div class="card p-4">
            <div class="section-head mb-3">
                <h3 class="h5 fw-bold mb-0"><i class="bi bi-table"></i> Your Readings</h3>
                <div class="d-flex gap-2 flex-wrap"><a class="btn btn-outline-success btn-sm" href="{{ url_for('export_csv') }}">CSV</a><a class="btn btn-outline-danger btn-sm" href="{{ url_for('export_pdf') }}">PDF</a></div>
            </div>
            {% if readings %}
                <div class="table-responsive">
                    <table class="table align-middle table-hover">
                        <thead class="table-light"><tr><th>Period</th><th>kWh</th><th>Cost</th><th>Status</th><th>Timestamp</th><th>Actions</th></tr></thead>
                        <tbody>
                            {% for reading in readings %}
                            <tr>
                                <td>{{ reading.date }}</td>
                                <td>{{ reading.kwh }}</td>
                                <td>{{ current_user.currency }} {{ "%.2f"|format(reading.cost or 0) }}</td>
                                <td>{% if reading.is_approved %}<span class="badge bg-success">Approved</span>{% elif reading.is_reviewed %}<span class="badge bg-info">Reviewed</span>{% else %}<span class="badge bg-warning">Pending</span>{% endif %}</td>
                                <td>{{ reading.timestamp|local_datetime }}</td>
                                <td><button class="btn btn-sm btn-outline-dark" data-bs-toggle="modal" data-bs-target="#editModal{{ reading.id }}">Edit</button><form method="POST" action="{{ url_for('delete_reading', reading_id=reading.id) }}" class="d-inline" onsubmit="return confirm('Delete?');"><button class="btn btn-sm btn-outline-danger">Delete</button></form></td>
                            </tr>
                            <div class="modal fade" id="editModal{{ reading.id }}" tabindex="-1"><div class="modal-dialog"><div class="modal-content"><form method="POST" action="{{ url_for('update_reading', reading_id=reading.id) }}"><div class="modal-header"><h5 class="modal-title">Edit Reading</h5><button type="button" class="btn-close" data-bs-dismiss="modal"></button></div><div class="modal-body"><div class="mb-3"><label class="form-label">Period</label><input class="form-control" name="date" value="{{ reading.date }}" required></div><div class="mb-3"><label class="form-label">kWh</label><input class="form-control" type="number" step="0.01" name="kwh" value="{{ reading.kwh }}" required></div><div class="mb-3"><label class="form-label">Timestamp</label><input class="form-control" type="datetime-local" name="timestamp" value="{{ reading.timestamp|local_datetime_input }}" required></div></div><div class="modal-footer"><button type="submit" class="btn btn-dark">Save changes</button></div></form></div></div></div>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
            {% else %}
                <div class="text-center py-5 text-muted"><i class="bi bi-inbox fs-1"></i><p class="mt-3 mb-0">No readings recorded yet.</p></div>
            {% endif %}
        </div>
    </div>

    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script>
    <script>
        function submitToAdmin() { fetch('{{ url_for("submit_to_admin") }}', { method: 'POST' }).then(r => r.json()).then(d => { alert(d.message); if (d.success) location.reload(); }); }
        function validatePayment(recordId) {
            const phone = document.getElementById('payment_phone_' + recordId).value;
            const reference = document.getElementById('payment_reference_' + recordId).value;
            if (!phone || phone.length !== 10 || !/^\\d{10}$/.test(phone)) { alert('Phone number must be exactly 10 digits'); return false; }
            if (!reference || reference.length !== 10) { alert('Reference number must be exactly 10 characters'); return false; }
            const hasLetters = /[a-zA-Z]/.test(reference); const hasNumbers = /\\d/.test(reference);
            if (!hasLetters || !hasNumbers) { alert('Reference must contain both letters and numbers'); return false; }
            if (!/^[a-zA-Z0-9]+$/.test(reference)) { alert('Reference can only contain letters and numbers'); return false; }
            return true;
        }
        {% if readings %}
        document.addEventListener('DOMContentLoaded', function() {
            const readingDates = {{ readings|map(attribute='date')|list|tojson }};
            const readingValues = {{ readings|map(attribute='kwh')|list|tojson }};
            const readingCosts = {{ readings|map(attribute='cost')|list|tojson }};
            const threshold = {{ current_user.threshold }};
            new Chart(document.getElementById('mainConsumptionChart'), { type: 'bar', data: { labels: readingDates, datasets: [{ label: 'Energy Consumption (kWh)', data: readingValues, backgroundColor: readingValues.map(v => v > threshold ? '#ff6b6b' : '#00b894'), borderRadius: 8 }] }, options: { responsive: true, maintainAspectRatio: true } });
            const above = readingValues.filter(v => v > threshold).length, below = readingValues.filter(v => v <= threshold).length;
            new Chart(document.getElementById('pieChart'), { type: 'pie', data: { labels: ['Above Threshold', 'Below Threshold'], datasets: [{ data: [above, below], backgroundColor: ['#ff6b6b', '#00b894'] }] }, options: { responsive: true } });
            new Chart(document.getElementById('trendChart'), { type: 'line', data: { labels: readingDates, datasets: [{ label: 'Actual', data: readingValues, borderColor: '#0984e3', fill: true }, { label: 'Threshold', data: Array(readingValues.length).fill(threshold), borderColor: '#ff6b6b', borderDash: [5,5], fill: false }] }, options: { responsive: true } });
            const efficiency = Math.max(0, Math.min(100, ((threshold - (readingValues[readingValues.length-1]||0))/threshold*100)));
            new Chart(document.getElementById('efficiencyGauge'), { type: 'doughnut', data: { labels: ['Efficiency', 'Remaining'], datasets: [{ data: [efficiency, 100-efficiency], backgroundColor: ['#00b894', '#dfe6e9'], cutout: '70%' }] }, options: { responsive: true } });
            new Chart(document.getElementById('costChart'), { type: 'bar', data: { labels: readingDates, datasets: [{ label: 'Cost', data: readingCosts, backgroundColor: '#fdcb6e' }] }, options: { responsive: true } });
            new Chart(document.getElementById('environmentChart'), { type: 'line', data: { labels: readingDates, datasets: [{ label: 'CO2 (kg)', data: readingValues.map(v => v*0.385), borderColor: '#00b894', fill: true }] }, options: { responsive: true } });
            new Chart(document.getElementById('thresholdComparisonChart'), { type: 'radar', data: { labels: readingDates.slice(-6), datasets: [{ label: 'Usage', data: readingValues.slice(-6), borderColor: '#ff6b6b' }, { label: 'Threshold', data: Array(readingValues.slice(-6).length).fill(threshold), borderColor: '#00b894' }] }, options: { responsive: true } });
        });
        {% endif %}
    </script>
</body>
</html>
"""

admin_financial_template_v2 = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Admin Dashboard - EcoPulse</title>
    <link rel="icon" type="image/svg+xml" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Crect width='64' height='64' rx='16' fill='%23062f2f'/%3E%3Cpath d='M35 6 18 34h11l-4 24 21-31H34z' fill='%23f59e0b'/%3E%3C/svg%3E">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css">
    <style>body{margin:0;background:radial-gradient(circle at top left,rgba(59,130,246,.12),transparent 22%),radial-gradient(circle at bottom right,rgba(16,185,129,.08),transparent 18%),linear-gradient(180deg,#edf3ff 0,#f8fafc 36%,#eef6ff 100%);padding-top:86px;overflow-x:hidden}.navbar{background:rgba(31,41,55,.94);backdrop-filter:blur(10px);box-shadow:0 10px 30px rgba(15,23,42,.18)}.card{border:1px solid rgba(15,23,42,.08);border-radius:24px;box-shadow:0 18px 42px rgba(15,23,42,0.08);background:rgba(255,255,255,.96)}.assistant-scroll{max-height:220px;overflow-y:auto;background:#f8fafc;border-radius:16px;padding:16px;border:1px solid rgba(15,23,42,.08)}.btn{border-radius:14px;font-weight:600}.btn-dark{background:linear-gradient(135deg,#0f172a,#334155);border:none}.btn-outline-dark:hover{background:#1f2937;border-color:#1f2937}.table-responsive{border-radius:18px}.table thead th{background:#f8fafc;white-space:nowrap}.toolbar{display:flex;gap:.75rem;flex-wrap:wrap}.toolbar>*{flex:0 0 auto}.hero-surface{background:linear-gradient(135deg,rgba(15,23,42,.92),rgba(51,65,85,.84)),url('https://images.unsplash.com/photo-1451187580459-43490279c0fa?auto=format&fit=crop&w=1600&q=80') center/cover;color:#fff;border-radius:28px;padding:30px;box-shadow:0 24px 56px rgba(15,23,42,.2)}.smart-meter{background:linear-gradient(145deg,#0f172a,#1e3a8a 62%,#38bdf8);color:#fff;position:relative;overflow:hidden}.smart-meter:after{content:'';position:absolute;right:-38px;top:-38px;width:150px;height:150px;border-radius:50%;background:rgba(255,255,255,.08)}.meter-ring{width:118px;height:118px;border-radius:50%;display:grid;place-items:center;background:conic-gradient(#86efac 0 calc(var(--meter-value) * 1%),rgba(255,255,255,.18) 0);padding:10px}.meter-ring span{width:100%;height:100%;border-radius:50%;display:grid;place-items:center;background:#0f172a;font-weight:700}.meter-chip{display:inline-flex;align-items:center;gap:8px;padding:8px 12px;border-radius:999px;background:rgba(255,255,255,.12);border:1px solid rgba(255,255,255,.16)}.cool-card{background:linear-gradient(180deg,#fff,#eef4ff)}.mint-card{background:linear-gradient(180deg,#fff,#f0fdf9)}@media (max-width:991.98px){.toolbar>*{width:100%}}@media (max-width:767.98px){body{padding-top:74px}.container{padding-left:16px;padding-right:16px}.card,.hero-surface{border-radius:20px}.btn,.btn-sm{width:100%}.table td,.table th{font-size:.92rem}.meter-ring{margin:auto}}</style>
</head>
<body>
    <nav class="navbar navbar-expand-lg navbar-dark fixed-top"><div class="container"><a class="navbar-brand fw-bold" href="{{ url_for('admin_financial') }}">EcoPulse Admin</a><button class="navbar-toggler" type="button" data-bs-toggle="collapse" data-bs-target="#adminNav"><span class="navbar-toggler-icon"></span></button><div class="collapse navbar-collapse" id="adminNav"><div class="navbar-nav ms-auto"><a class="nav-link" href="{{ url_for('ai_analysis') }}">AI Analysis</a><a class="nav-link" href="{{ url_for('logout') }}">Logout</a></div></div></div></nav>
    <div class="container pb-5">
        <div class="hero-surface mb-4"><div class="d-flex flex-column flex-lg-row justify-content-between align-items-lg-end"><div><h1 class="fw-bold">Admin Dashboard</h1><p class="mb-0" style="color:rgba(255,255,255,.82)">Approve examiner output, review financial records, and monitor 10-year system forecasts.</p></div><div class="mt-3 mt-lg-0 toolbar"><a class="btn btn-outline-light" href="{{ url_for('ai_analysis') }}">AI Analysis</a><form method="POST" action="{{ url_for('send_customer_summaries') }}"><button class="btn btn-dark">Send Customer Summaries</button></form></div></div></div>
        {% with messages = get_flashed_messages(with_categories=true) %}{% for category, msg in messages %}<div class="alert alert-{{ 'warning' if category == 'warning' else 'info' }}">{{ msg }}</div>{% endfor %}{% endwith %}
        <div class="card smart-meter p-4 mb-4"><div class="row g-4 align-items-center"><div class="col-lg-7"><div class="d-flex flex-wrap gap-2 mb-3"><span class="meter-chip"><i class="bi bi-building-check"></i> {{ smart_meter.title }}</span><span class="meter-chip"><i class="bi bi-shield-fill-check"></i> {{ smart_meter.status }}</span></div><h3 class="fw-bold mb-2">{{ smart_meter.reading_value }}</h3><p class="mb-3" style="color:rgba(255,255,255,.82)">{{ smart_meter.reading_label }}</p><div class="row g-3"><div class="col-sm-6"><div class="p-3 rounded-4" style="background:rgba(255,255,255,.1)"><small class="d-block" style="color:rgba(255,255,255,.7)">Verification</small><strong>{{ smart_meter.support_value }}</strong><div class="small" style="color:rgba(255,255,255,.72)">{{ smart_meter.support_label }}</div></div></div><div class="col-sm-6"><div class="p-3 rounded-4" style="background:rgba(255,255,255,.1)"><small class="d-block" style="color:rgba(255,255,255,.7)">Finance</small><strong>{{ smart_meter.detail_primary }}</strong><div class="small" style="color:rgba(255,255,255,.72)">{{ smart_meter.detail_secondary }}</div></div></div></div></div><div class="col-lg-5 text-center text-lg-end"><div class="meter-ring ms-lg-auto" style="--meter-value: {{ smart_meter.ring_value }};"><span>{{ smart_meter.ring_value }}%</span></div><div class="mt-3 small" style="color:rgba(255,255,255,.8)">{{ smart_meter.ring_label }}</div></div></div></div>
        <div class="row g-4 mb-4"><div class="col-md-3"><div class="card p-4"><small class="text-muted">Revenue</small><h3 class="fw-bold mb-0">Ksh {{ "%.2f"|format(financial.total_revenue) }}</h3></div></div><div class="col-md-3"><div class="card p-4"><small class="text-muted">Outstanding</small><h3 class="fw-bold mb-0">Ksh {{ "%.2f"|format(financial.total_outstanding) }}</h3></div></div><div class="col-md-3"><div class="card p-4"><small class="text-muted">Collected</small><h3 class="fw-bold mb-0">Ksh {{ "%.2f"|format(financial.total_collected) }}</h3></div></div><div class="col-md-3"><div class="card p-4"><small class="text-muted">Payment Rate</small><h3 class="fw-bold mb-0">{{ "%.1f"|format(financial.payment_rate) }}%</h3></div></div></div>
        <div class="row g-4 mb-4"><div class="col-lg-8"><div class="card p-4 h-100 cool-card"><h3 class="h5 fw-bold">10-Year Backcast and Forecast</h3><img src="data:image/png;base64,{{ prediction_payload.chart }}" class="img-fluid rounded-4" alt="Prediction chart"></div></div><div class="col-lg-4"><div class="card p-4 h-100 mint-card"><h3 class="h5 fw-bold">Forecast Summary</h3><p class="mb-2"><strong>Current year:</strong> {{ prediction_payload.summary.current_year }}</p><p class="mb-2"><strong>Current total:</strong> {{ "%.2f"|format(prediction_payload.summary.current_total) }} kWh</p><p class="mb-2"><strong>Previous average:</strong> {{ "%.2f"|format(prediction_payload.summary.previous_average) }} kWh</p><p class="mb-2"><strong>Next average:</strong> {{ "%.2f"|format(prediction_payload.summary.next_average) }} kWh</p><p class="mb-0"><strong>Growth rate:</strong> {{ "%.2f"|format(prediction_payload.summary.growth_rate) }}%</p></div></div></div>
        <div class="card p-4 mb-4"><h3 class="h5 fw-bold">Admin AI Forecast Assistant</h3><p class="text-muted">Enter an earlier range and a future range, up to 10 years each, to generate a graph and receive planning advice.</p><div class="row g-3"><div class="col-md-6"><label class="form-label">Earlier Years</label><input id="adminYearsBack" type="number" min="1" max="10" value="10" class="form-control"></div><div class="col-md-6"><label class="form-label">Next Years</label><input id="adminYearsForward" type="number" min="1" max="10" value="10" class="form-control"></div></div><div id="adminAssistantMessages" class="assistant-scroll mt-3"><div class="mb-2"><strong>EcoPulse AI:</strong> Ask about future demand, outstanding balances, or operational advice.</div></div><div class="input-group mt-3"><input id="adminAssistantInput" type="text" class="form-control" placeholder="What should I focus on for the selected forecast years?"><button id="adminAssistantSend" class="btn btn-dark" type="button">Generate</button></div><div id="adminAssistantSummary" class="small text-muted mt-3"></div><img id="adminAssistantChart" class="img-fluid rounded-4 mt-3 d-none" alt="Admin AI forecast chart"></div>
        <div class="row g-4 mb-4"><div class="col-lg-5"><div class="card p-4 h-100"><h3 class="h5 fw-bold">KPLC Tariff Notifications</h3><p class="text-muted">Receive and publish KPLC cost-per-unit or token notices here so billing stays aligned across the system.</p><div class="border rounded-4 p-3 bg-light mb-3"><small class="text-muted d-block">Current Published Tariff</small><strong>{% if current_tariff %}Ksh {{ "%.2f"|format(current_tariff.cost_per_unit) }} / unit{% else %}Ksh 0.12 / unit{% endif %}</strong><div class="small text-muted">{% if current_tariff %}Effective {{ current_tariff.effective_date }} | {{ current_tariff.notice_reference }}{% else %}No KPLC update published yet{% endif %}</div></div><form method="POST" action="{{ url_for('update_kplc_tariff') }}" class="row g-3"><div class="col-md-6"><label class="form-label">Cost / Unit</label><input class="form-control" type="number" step="0.01" min="0.01" name="cost_per_unit" value="{% if current_tariff %}{{ '%.2f'|format(current_tariff.cost_per_unit) }}{% else %}0.12{% endif %}" required></div><div class="col-md-6"><label class="form-label">Effective Date</label><input class="form-control" type="date" name="effective_date"></div><div class="col-12"><label class="form-label">Notice Reference</label><input class="form-control" name="notice_reference" placeholder="e.g. KPLC Tariff Circular April 2026" required></div><div class="col-12"><label class="form-label">Notice Message</label><textarea class="form-control" name="notice_message" rows="3" placeholder="Short note from KPLC about the tariff update"></textarea></div><div class="col-12"><button class="btn btn-dark" type="submit">Publish Tariff Update</button></div></form>{% if kplc_notifications %}<hr><div class="table-responsive"><table class="table align-middle"><thead><tr><th>Notice</th><th>Published</th></tr></thead><tbody>{% for item in kplc_notifications %}<tr><td><div class="fw-semibold">{{ item.title }}</div><div class="small">{{ item.content|safe }}</div></td><td>{{ item.created_at.strftime('%Y-%m-%d %H:%M') }}</td></tr>{% endfor %}</tbody></table></div>{% endif %}</div></div><div class="col-lg-7"><div class="card p-4 h-100"><h3 class="h5 fw-bold">Threshold Sensor Alerts</h3><p class="text-muted">These alerts are raised automatically when a customer exceeds the configured threshold.</p>{% if sensor_alerts %}{% for alert in sensor_alerts %}<div class="border rounded-4 p-3 mb-3 bg-light-subtle"><div class="fw-semibold">{{ alert.title }}</div><small class="text-muted">{{ alert.created_at.strftime('%Y-%m-%d %H:%M') }}</small><div class="small mt-2">{{ alert.content|safe }}</div></div>{% endfor %}{% else %}<p class="text-muted mb-0">No sensor alerts have been raised yet.</p>{% endif %}</div></div></div>
        <div class="card p-4 mb-4"><h3 class="h5 fw-bold">Pending Examiner Reviews</h3>{% if pending_reviews %}<div class="table-responsive"><table class="table align-middle"><thead><tr><th>Period</th><th>Examiner</th><th>Total Consumption</th><th>Customers</th><th>Actions</th></tr></thead><tbody>{% for review in pending_reviews %}<tr><td>{{ review.period }}</td><td>{{ review.examiner.username }}</td><td>{{ "%.2f"|format(review.total_consumption) }} kWh</td><td>{{ review.total_customers }}</td><td><button class="btn btn-sm btn-outline-success" onclick="approveReview({{ review.id }})">Approve</button> <button class="btn btn-sm btn-outline-danger" onclick="rejectReview({{ review.id }})">Reject</button></td></tr>{% endfor %}</tbody></table></div>{% else %}<p class="text-muted mb-0">No pending examiner reviews.</p>{% endif %}</div>
        <div class="card p-4 mb-4"><div class="d-flex justify-content-between align-items-center mb-3"><h3 class="h5 fw-bold mb-0">Contact Messages</h3><a class="btn btn-sm btn-outline-dark" href="{{ url_for('admin_contact_messages') }}">View All</a></div>{% if contact_messages %}<div class="table-responsive"><table class="table align-middle"><thead><tr><th>Name</th><th>Email</th><th>Subject</th><th>Received</th></tr></thead><tbody>{% for item in contact_messages %}<tr><td>{{ item.name }}</td><td>{{ item.email }}</td><td>{{ item.subject }}</td><td>{{ item.created_at.strftime('%Y-%m-%d %H:%M') }}</td></tr>{% endfor %}</tbody></table></div>{% else %}<p class="text-muted mb-0">No contact messages have been submitted yet.</p>{% endif %}</div>
        <div class="card p-4 mb-4"><h3 class="h5 fw-bold">Financial Records</h3>{% if financial_records %}<div class="table-responsive"><table class="table align-middle"><thead><tr><th>Customer</th><th>Period</th><th>Total Cost</th><th>Paid</th><th>Balance</th><th>Status</th><th>Actions</th></tr></thead><tbody>{% for record in financial_records %}<tr><td>{{ record.user.username }}</td><td>{{ record.period }}</td><td>{{ "%.2f"|format(record.total_cost) }}</td><td>{{ "%.2f"|format(record.total_paid) }}</td><td>{{ "%.2f"|format(record.balance) }}</td><td class="text-capitalize">{{ record.payment_status }}</td><td><button class="btn btn-sm btn-outline-success" onclick="markPaid({{ record.id }})">Mark Paid</button> <button class="btn btn-sm btn-outline-dark" onclick="sendReminder({{ record.id }})">Reminder</button></td></tr>{% endfor %}</tbody></table></div>{% else %}<p class="text-muted mb-0">No financial records available.</p>{% endif %}</div>
        <div class="card p-4"><h3 class="h5 fw-bold">Prediction Timeline</h3><div class="table-responsive"><table class="table align-middle"><thead><tr><th>Year</th><th>kWh</th><th>Type</th></tr></thead><tbody>{% for item in prediction_payload.timeline %}<tr><td>{{ item.year }}</td><td>{{ "%.2f"|format(item.value) }}</td><td class="text-capitalize">{{ item.type }}</td></tr>{% endfor %}</tbody></table></div></div>
    </div>
    <script>
        function callEndpoint(url){fetch(url,{method:'POST'}).then(response=>response.json()).then(data=>{alert(data.message);location.reload();});}
        function approveReview(id){callEndpoint(`/approve_review/${id}`);}
        function rejectReview(id){callEndpoint(`/reject_review/${id}`);}
        function markPaid(id){callEndpoint(`/mark_as_paid/${id}`);}
        function sendReminder(id){callEndpoint(`/send_payment_reminder/${id}`);}
        async function askAdminAssistant(){const input=document.getElementById('adminAssistantInput');const messages=document.getElementById('adminAssistantMessages');const yearsBack=Math.min(10,Math.max(1,parseInt(document.getElementById('adminYearsBack').value||'10',10)));const yearsForward=Math.min(10,Math.max(1,parseInt(document.getElementById('adminYearsForward').value||'10',10)));const message=input.value.trim()||'Give me ideas and advice for this selected forecast range.';messages.insertAdjacentHTML('beforeend',`<div class="mb-2"><strong>You:</strong> ${message} (${yearsBack} back, ${yearsForward} forward)</div>`);input.value='';const response=await fetch('{{ url_for("staff_assistant") }}',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message,years_back:yearsBack,years_forward:yearsForward})});const data=await response.json();messages.insertAdjacentHTML('beforeend',`<div class="mb-3"><strong>EcoPulse AI:</strong> ${data.answer}</div>`);messages.scrollTop=messages.scrollHeight;document.getElementById('adminAssistantSummary').textContent=`Current year: ${data.summary.current_year} | Previous avg: ${data.summary.previous_average} kWh | Next avg: ${data.summary.next_average} kWh | Growth: ${data.summary.growth_rate}%`;const chart=document.getElementById('adminAssistantChart');chart.src=`data:image/png;base64,${data.chart}`;chart.classList.remove('d-none');}
        document.getElementById('adminAssistantSend').addEventListener('click',askAdminAssistant);
        document.getElementById('adminAssistantInput').addEventListener('keydown',event=>{if(event.key==='Enter'){event.preventDefault();askAdminAssistant();}});
    </script>
</body>
</html>
"""

admin_contact_messages_template = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Admin Contact Messages - EcoPulse</title>
    <link rel="icon" type="image/svg+xml" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Crect width='64' height='64' rx='16' fill='%23062f2f'/%3E%3Cpath d='M35 6 18 34h11l-4 24 21-31H34z' fill='%23f59e0b'/%3E%3C/svg%3E">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.0/font/bootstrap-icons.css">
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;700&family=Source+Sans+3:wght@400;600&display=swap" rel="stylesheet">
    <style>body{background:radial-gradient(circle at top,#eef2ff 0,#f8fafc 35%,#ffffff 100%);padding-top:86px;font-family:'Source Sans 3',sans-serif}.navbar{background:rgba(31,41,55,.94);backdrop-filter:blur(10px);box-shadow:0 10px 30px rgba(15,23,42,.18)}.navbar-brand,h1,h2,h3{font-family:'Space Grotesk',sans-serif}.card{border:1px solid rgba(15,23,42,.08);border-radius:26px;box-shadow:0 20px 52px rgba(15,23,42,.08);background:rgba(255,255,255,.96)}.table-responsive{border-radius:20px}.table thead th{background:#f8fafc;white-space:nowrap}.hero-note{background:linear-gradient(135deg,#0f172a,#334155);color:#fff;border-radius:24px;padding:26px;box-shadow:0 22px 56px rgba(15,23,42,.18)}@media (max-width:767.98px){body{padding-top:74px}.card,.hero-note{border-radius:22px}}</style>
</head>
<body>
    <nav class="navbar navbar-expand-lg navbar-dark fixed-top"><div class="container"><a class="navbar-brand fw-bold" href="{{ url_for('admin_financial') }}"><i class="bi bi-envelope-paper"></i> EcoPulse Admin</a><button class="navbar-toggler" type="button" data-bs-toggle="collapse" data-bs-target="#contactAdminNav"><span class="navbar-toggler-icon"></span></button><div class="collapse navbar-collapse" id="contactAdminNav"><div class="navbar-nav ms-auto"><a class="nav-link" href="{{ url_for('admin_financial') }}">Dashboard</a><a class="nav-link" href="{{ url_for('logout') }}">Logout</a></div></div></div></nav>
    <div class="container pb-5">
        <div class="hero-note mb-4"><div class="small text-uppercase mb-2">Admin Inbox</div><h1 class="fw-bold mb-2">Contact Messages</h1><p class="mb-0">Messages submitted from the public Get in Touch page.</p></div>
        <div class="card p-4">
            {% if messages %}
            <div class="table-responsive">
                <table class="table align-middle">
                    <thead><tr><th>Name</th><th>Email</th><th>Subject</th><th>Message</th><th>Received</th></tr></thead>
                    <tbody>
                    {% for item in messages %}
                    <tr>
                        <td>{{ item.name }}</td>
                        <td>{{ item.email }}</td>
                        <td>{{ item.subject }}</td>
                        <td style="min-width:320px;">{{ item.message }}</td>
                        <td>{{ item.created_at.strftime('%Y-%m-%d %H:%M') }}</td>
                    </tr>
                    {% endfor %}
                    </tbody>
                </table>
            </div>
            {% else %}
            <p class="text-muted mb-0">No contact messages available.</p>
            {% endif %}
        </div>
    </div>
</body>
</html>
"""

ai_course_template = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AI Analysis - EcoPulse</title>
    <link rel="icon" type="image/svg+xml" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Crect width='64' height='64' rx='16' fill='%23062f2f'/%3E%3Cpath d='M35 6 18 34h11l-4 24 21-31H34z' fill='%23f59e0b'/%3E%3C/svg%3E">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css">
    <style>:root{--ai-navy:#0f172a;--ai-teal:#0f766e;--ai-mist:#eff6ff;--ai-border:rgba(15,23,42,.08)}body{background:radial-gradient(circle at top,#eff6ff 0,#f5f7fb 32%,#ffffff 100%);padding-top:86px}.navbar{background:rgba(15,23,42,.94);backdrop-filter:blur(10px);box-shadow:0 10px 30px rgba(15,23,42,.18)}.card{border:1px solid var(--ai-border);border-radius:24px;box-shadow:0 18px 42px rgba(15,23,42,0.08);background:rgba(255,255,255,.96)}.hero{background:linear-gradient(135deg,#0f172a,#0f766e 68%,#38bdf8);color:#fff;border-radius:30px;padding:34px;box-shadow:0 28px 64px rgba(15,23,42,.22)}.hero-title{font-size:clamp(1.6rem,3vw,2.5rem)}.hero-subtitle{max-width:760px;color:rgba(255,255,255,.84)}.code-chip{display:inline-flex;align-items:center;background:rgba(255,255,255,.16);border:1px solid rgba(255,255,255,.18);color:#fff;border-radius:999px;padding:8px 14px;font-size:.9rem;margin:0 8px 8px 0;backdrop-filter:blur(8px)}.rule-list{padding-left:18px;margin-bottom:0}.table td,.table th{vertical-align:middle}.table thead th{background:#f8fafc;white-space:nowrap}.table-responsive{border-radius:18px}.stat-tile{background:linear-gradient(180deg,#ffffff,#f8fbff);border:1px solid rgba(59,130,246,.12);border-radius:20px;padding:1rem}.stat-tile .value{font-size:1.6rem;font-weight:700;color:var(--ai-navy)}.section-head{display:flex;justify-content:space-between;align-items:flex-end;gap:1rem;flex-wrap:wrap}.risk-chip{display:inline-block;padding:.35rem .7rem;border-radius:999px;font-weight:600;font-size:.85rem}.risk-Low{background:#dcfce7;color:#166534}.risk-Medium{background:#fef3c7;color:#92400e}.risk-High{background:#fee2e2;color:#991b1b}.risk-Critical{background:#fecaca;color:#7f1d1d}.muted-panel{background:var(--ai-mist);border:1px solid rgba(59,130,246,.12);border-radius:18px}.insight-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:1rem}.nav-link{font-weight:500}.img-fluid{box-shadow:0 18px 42px rgba(15,23,42,.12)}@media (max-width:991.98px){.insight-grid{grid-template-columns:1fr}.section-head>*{width:100%}}@media (max-width:767.98px){body{padding-top:74px}.container{padding-left:16px;padding-right:16px}.hero{padding:24px;border-radius:24px}.card{border-radius:20px}.table td,.table th{font-size:.92rem}}</style>
</head>
<body>
    <nav class="navbar navbar-expand-lg navbar-dark fixed-top"><div class="container"><a class="navbar-brand fw-bold" href="{{ back_url }}">EcoPulse AI</a><button class="navbar-toggler" type="button" data-bs-toggle="collapse" data-bs-target="#aiNav"><span class="navbar-toggler-icon"></span></button><div class="collapse navbar-collapse" id="aiNav"><div class="navbar-nav ms-auto"><a class="nav-link" href="{{ back_url }}">Dashboard</a><a class="nav-link" href="{{ url_for('logout') }}">Logout</a></div></div></div></nav>
    <div class="container pb-5">
        <div class="hero mb-4"><h1 class="hero-title fw-bold mb-2">AI Problem Definition and System Evaluation</h1><p class="hero-subtitle mb-3">{{ report.problem_statement }}</p><span class="code-chip">{{ report.agent.name }}</span><span class="code-chip">{{ report.agent.type }}</span></div>
        <div class="insight-grid mb-4"><div class="stat-tile"><div class="small text-muted mb-1">Search Winner</div><div class="value">{{ report.search.comparison[1].algorithm }}</div><div class="small text-muted">Fewer explored states for the current case.</div></div><div class="stat-tile"><div class="small text-muted mb-1">Forecast Years</div><div class="value">{{ report.ml.years_evaluated }}</div><div class="small text-muted">Years used to evaluate the regression model.</div></div><div class="stat-tile"><div class="small text-muted mb-1">Top Risk Case</div><div class="value">{{ report.reasoning[0].risk }}</div><div class="small text-muted">{{ report.reasoning[0].customer }}</div></div></div>
        <div class="row g-4 mb-4"><div class="col-lg-6"><div class="card p-4 h-100"><h2 class="h5 fw-bold">PEAS Framework</h2><table class="table mb-0"><tbody><tr><th>Performance</th><td>{{ report.agent.peas.Performance }}</td></tr><tr><th>Environment</th><td>{{ report.agent.peas.Environment }}</td></tr><tr><th>Actuators</th><td>{{ report.agent.peas.Actuators }}</td></tr><tr><th>Sensors</th><td>{{ report.agent.peas.Sensors }}</td></tr></tbody></table></div></div><div class="col-lg-6"><div class="card p-4 h-100"><h2 class="h5 fw-bold">Agent Design</h2><p class="mb-2"><strong>Type:</strong> {{ report.agent.type }}</p><p class="mb-3">{{ report.agent.justification }}</p><div class="small muted-panel p-3">This section adds the explicit agent definition required by the course while leaving the existing EcoPulse workflows unchanged.</div></div></div></div>
        <div class="card p-4 mb-4"><div class="section-head mb-3"><h2 class="h5 fw-bold mb-0">Search-Based Solution</h2><span class="text-muted">Case: {{ report.search.problem.customer }} needs {{ report.search.problem.start_excess }} kWh of excess reduced</span></div><div class="table-responsive"><table class="table align-middle"><thead><tr><th>Algorithm</th><th>Path Length</th><th>Solution Cost</th><th>States Explored</th><th>Recommended Sequence</th></tr></thead><tbody>{% for row in report.search.comparison %}<tr><td><strong>{{ row.algorithm }}</strong></td><td>{{ row.path_length }}</td><td>{{ row.solution_cost }}</td><td>{{ row.states_explored }}</td><td>{{ row.solution }}</td></tr>{% endfor %}</tbody></table></div><p class="text-muted mb-0">BFS is the uninformed baseline. A* uses a heuristic based on the largest possible kWh reduction per action, so it reaches the goal with fewer explored states.</p></div>
        <div class="card p-4 mb-4"><h2 class="h5 fw-bold">Knowledge Representation and Reasoning</h2><div class="table-responsive"><table class="table align-middle"><thead><tr><th>Customer</th><th>Latest Period</th><th>Latest kWh</th><th>Threshold</th><th>Excess</th><th>Balance</th><th>Risk</th><th>Advice</th><th>Rules Fired</th></tr></thead><tbody>{% for item in report.reasoning %}<tr><td>{{ item.customer }}</td><td>{{ item.latest_period }}</td><td>{{ "%.2f"|format(item.latest_kwh) }}</td><td>{{ "%.2f"|format(item.threshold) }}</td><td>{{ "%.2f"|format(item.excess_kwh) }}</td><td>{{ "%.2f"|format(item.balance) }}</td><td><span class="risk-chip risk-{{ item.risk }}">{{ item.risk }}</span></td><td>{{ item.advice }}</td><td><ul class="rule-list">{% for rule in item.fired_rules %}<li>{{ rule }}</li>{% endfor %}</ul></td></tr>{% endfor %}</tbody></table></div></div>
        <div class="row g-4 mb-4"><div class="col-lg-6"><div class="card p-4 h-100"><h2 class="h5 fw-bold">Machine Learning Component</h2><p class="mb-2"><strong>Model:</strong> {{ report.ml.model_name }}</p><p class="mb-2"><strong>Evaluation years:</strong> {{ report.ml.years_evaluated }}</p>{% if report.ml.years_evaluated > 0 %}<p class="mb-2"><strong>MAE:</strong> {{ "%.2f"|format(report.ml.mae) }} kWh</p><p class="mb-2"><strong>RMSE:</strong> {{ "%.2f"|format(report.ml.rmse) }} kWh</p><p class="mb-0"><strong>MAPE:</strong> {{ "%.2f"|format(report.ml.mape) }}%</p>{% else %}<p class="mb-0 text-muted">Not enough yearly history is available yet to compute accuracy metrics. The regression forecast still runs for visualization and planning.</p>{% endif %}</div></div><div class="col-lg-6"><div class="card p-4 h-100"><h2 class="h5 fw-bold">Visualization</h2><img src="data:image/png;base64,{{ report.visualization }}" class="img-fluid rounded-4" alt="AI analysis comparison chart"></div></div></div>
        <div class="card p-4"><h2 class="h5 fw-bold">Forecast Evaluation Table</h2>{% if report.ml.predictions %}<div class="table-responsive"><table class="table align-middle"><thead><tr><th>Year</th><th>Actual</th><th>Predicted</th><th>Absolute Error</th><th>Absolute % Error</th></tr></thead><tbody>{% for item in report.ml.predictions %}<tr><td>{{ item.year }}</td><td>{{ "%.2f"|format(item.actual) }}</td><td>{{ "%.2f"|format(item.predicted) }}</td><td>{{ "%.2f"|format(item.absolute_error) }}</td><td>{{ "%.2f"|format(item.absolute_percentage_error) }}%</td></tr>{% endfor %}</tbody></table></div>{% else %}<p class="text-muted mb-0">Add readings across more than one year to generate a historical prediction accuracy table.</p>{% endif %}</div>
    </div>
</body>
</html>
"""

error_page = """<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>Error - EcoPulse</title><link rel="icon" type="image/svg+xml" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Crect width='64' height='64' rx='16' fill='%23062f2f'/%3E%3Cpath d='M35 6 18 34h11l-4 24 21-31H34z' fill='%23f59e0b'/%3E%3C/svg%3E"><link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css"><link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.0/font/bootstrap-icons.css"><link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin><link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;700&family=Source+Sans+3:wght@400;600&display=swap" rel="stylesheet"><style>body{background:radial-gradient(circle at top,rgba(245,158,11,.18),transparent 24%),linear-gradient(145deg,#0f172a,#1f2937 58%,#7c2d12);min-height:100vh;display:flex;align-items:center;justify-content:center;font-family:'Source Sans 3',sans-serif;padding:20px}.error-container{max-width:560px;width:100%}.card{border:1px solid rgba(255,255,255,.12);border-radius:28px;box-shadow:0 24px 72px rgba(0,0,0,0.34);overflow:hidden;background:rgba(255,255,255,.95)}.card-header{background:linear-gradient(135deg,#7f1d1d,#dc2626 70%,#f59e0b);color:white;padding:34px;text-align:center}.card-header h2{font-family:'Space Grotesk',sans-serif;margin:0}.card-body{padding:42px;text-align:center}.btn-primary{background:linear-gradient(135deg,#0f172a,#334155);border:none;border-radius:16px;padding:.85rem 1.1rem;font-weight:700}</style></head><body><div class="error-container"><div class="card"><div class="card-header"><h2><i class="bi bi-exclamation-triangle"></i> Access Denied</h2></div><div class="card-body"><p class="lead mb-4">{{ error }}</p><a href="{{ url_for('dashboard') }}" class="btn btn-primary">Go to Dashboard</a></div></div></div></body></html>"""


# ===================== ROUTES =====================

@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return render_template_string(home_page_template,
                                  footer_links=PUBLIC_FOOTER_LINKS,
                                  PUBLIC_SERVICES=PUBLIC_SERVICES,
                                  PUBLIC_WORKFLOW=PUBLIC_WORKFLOW,
                                  PUBLIC_HOME_HIGHLIGHTS=PUBLIC_HOME_HIGHLIGHTS,
                                  PUBLIC_HOME_STATS=PUBLIC_HOME_STATS,
                                  PUBLIC_ABOUT=PUBLIC_ABOUT,
                                  PUBLIC_CAREERS=PUBLIC_CAREERS,
                                  PUBLIC_NEWS=PUBLIC_NEWS,
                                  PUBLIC_FAQS=PUBLIC_FAQS)


@app.route('/services')
def services():
    return render_template_string(public_content_template,
                                  page_title='Services',
                                  page_name='Services',
                                  hero_title='IoT energy solutions for homes and businesses',
                                  hero_text='Explore EcoPulse services for smart monitoring, optimization, device integration, and reporting.',
                                  sections=PUBLIC_SERVICES,
                                  footer_links=PUBLIC_FOOTER_LINKS)


@app.route('/careers')
def careers():
    return render_template_string(public_content_template,
                                  page_title='Careers at EcoPulse',
                                  page_name='Careers',
                                  hero_title='Join our mission',
                                  hero_text='We are building a greener future with IoT, analytics, and sustainability-focused teamwork.',
                                  sections=PUBLIC_CAREERS,
                                  footer_links=PUBLIC_FOOTER_LINKS)


@app.route('/about')
def about():
    return render_template_string(public_content_template,
                                  page_title='About EcoPulse',
                                  page_name='About Us',
                                  hero_title='Who we are',
                                  hero_text='EcoPulse combines IoT technology and sustainability goals to empower smarter energy use.',
                                  sections=PUBLIC_ABOUT,
                                  footer_links=PUBLIC_FOOTER_LINKS)


@app.route('/news')
def news():
    return render_template_string(public_content_template,
                                  page_title='EcoPulse News',
                                  page_name='News',
                                  hero_title='Stay updated',
                                  hero_text='Follow product launches, partnerships, industry insights, and practical energy-saving stories from EcoPulse.',
                                  sections=PUBLIC_NEWS,
                                  footer_links=PUBLIC_FOOTER_LINKS)


@app.route('/faqs')
def faqs():
    return render_template_string(public_content_template,
                                  page_title='EcoPulse FAQs',
                                  page_name='FAQs',
                                  hero_title='Frequently asked questions',
                                  hero_text='Find quick answers about forecasting, invoices, connected devices, thresholds, and support.',
                                  sections=PUBLIC_FAQS,
                                  footer_links=PUBLIC_FOOTER_LINKS)


@app.route('/how-it-works')
def how_it_works():
    return render_template_string(public_content_template,
                                  page_title='How EcoPulse Works',
                                  page_name='Workflow',
                                  hero_title='How the EcoPulse workflow moves from meter to decision',
                                  hero_text='The platform keeps customer reporting, examiner review, and admin approvals aligned.',
                                  sections=PUBLIC_WORKFLOW,
                                  footer_links=PUBLIC_FOOTER_LINKS)


@app.route('/contact', methods=['GET', 'POST'])
def contact():
    contact_success = None
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip()
        subject = request.form.get('subject', '').strip()
        message = request.form.get('message', '').strip()
        if name and email and subject and message:
            db.session.add(ContactMessage(
                name=name,
                email=email,
                subject=subject,
                message=message
            ))
            db.session.commit()
            contact_success = "Your message has been received and saved. EcoPulse support will follow up."
        else:
            contact_success = "Fill in all contact fields before sending your message."
    return render_template_string(contact_page_template,
                                  footer_links=PUBLIC_FOOTER_LINKS,
                                  contact_success=contact_success)


@app.route('/pricing')
def pricing():
    return render_template_string(public_content_template,
                                  page_title='EcoPulse Pricing',
                                  page_name='Pricing',
                                  hero_title='Plans built for households and energy operations teams',
                                  hero_text='Choose the setup that fits customer monitoring, examiner workflows, and admin reporting.',
                                  sections=[{'title': item['title'], 'text': f"{item['price']} - {item['text']}"} for item in PUBLIC_PRICING],
                                  footer_links=PUBLIC_FOOTER_LINKS)


@app.route('/privacy-policy')
def privacy_policy():
    return render_template_string(public_content_template,
                                  page_title='Privacy Policy',
                                  page_name='Privacy Policy',
                                  hero_title='How EcoPulse uses and protects data',
                                  hero_text='This policy covers customer information, metering records, staff access, and communication preferences.',
                                  sections=PUBLIC_PRIVACY,
                                  footer_links=PUBLIC_FOOTER_LINKS)


@app.route('/examiner/send_financial_report', methods=['POST'])
@login_required
@examiner_required
def examiner_send_financial_report():
    """Send financial report to admin with income rate and customer payments"""
    # Calculate financial statistics
    financial_records = FinancialRecord.query.all()
    total_revenue = sum(r.total_cost for r in financial_records)
    total_collected = sum(r.total_paid for r in financial_records)
    total_outstanding = sum(r.balance for r in financial_records)
    payment_rate = (total_collected / total_revenue * 100) if total_revenue > 0 else 0

    # Count customers by payment status
    paid_customers = len([r for r in financial_records if r.payment_status == 'paid'])
    pending_customers = len([r for r in financial_records if r.payment_status == 'pending'])
    overdue_customers = len([r for r in financial_records if r.payment_status == 'overdue'])

    report_content = f"""
    <h2>Monthly Financial Report</h2>
    <p><strong>Report Date:</strong> {datetime.utcnow().strftime('%Y-%m-%d %H:%M')}</p>

    <h3>Income Summary</h3>
    <ul>
        <li><strong>Total Revenue:</strong> Ksh {total_revenue:,.2f}</li>
        <li><strong>Total Collected:</strong> Ksh {total_collected:,.2f}</li>
        <li><strong>Total Outstanding:</strong> Ksh {total_outstanding:,.2f}</li>
        <li><strong>Payment Rate:</strong> {payment_rate:.1f}%</li>
    </ul>

    <h3>Customer Payment Status</h3>
    <ul>
        <li><strong>Paid Customers:</strong> {paid_customers}</li>
        <li><strong>Pending Customers:</strong> {pending_customers}</li>
        <li><strong>Overdue Customers:</strong> {overdue_customers}</li>
    </ul>

    <h3>Recommendations</h3>
    <ul>
        <li>Follow up with {overdue_customers} customers with overdue payments</li>
        <li>Send reminders to {pending_customers} customers with pending invoices</li>
        <li>Current collection rate is {payment_rate:.1f}%</li>
    </ul>
    """

    admin = User.query.filter_by(role='admin').first()
    if admin:
        report = Report(
            title=f"Financial Report - {datetime.utcnow().strftime('%B %Y')}",
            content=report_content,
            report_type='financial_report',
            sent_by=current_user.id,
            sent_to=admin.id,
            chart_data=json.dumps({
                'total_revenue': total_revenue,
                'total_collected': total_collected,
                'total_outstanding': total_outstanding,
                'payment_rate': payment_rate
            })
        )
        db.session.add(report)
        db.session.commit()
        log_system_action(current_user.id, f"Sent financial report to admin")
        return jsonify({'success': True, 'message': 'Financial report sent to admin successfully!'})

    return jsonify({'success': False, 'message': 'Admin not found'})


@app.route('/examiner/ai_assistant', methods=['POST'])
@login_required
@examiner_required
def examiner_ai_assistant():
    """AI assistant for financial advice and predictions"""
    data = request.get_json()
    question = data.get('question', '').lower()
    past_years = int(data.get('past_years', 10))
    future_years = int(data.get('future_years', 10))

    # Get financial data
    financial_records = FinancialRecord.query.all()
    total_revenue = sum(r.total_cost for r in financial_records)
    total_collected = sum(r.total_paid for r in financial_records)
    total_outstanding = sum(r.balance for r in financial_records)
    payment_rate = (total_collected / total_revenue * 100) if total_revenue > 0 else 0

    # Get prediction
    prediction = build_prediction_payload(years_back=past_years, years_forward=future_years)

    # Generate response based on question type
    if 'predict' in question or 'forecast' in question or 'future' in question:
        answer = f"""Based on the {past_years}-year historical data and {future_years}-year forecast:

📊 Current annual consumption: {prediction['summary']['current_total']:.0f} kWh
📈 Projected growth rate: {prediction['summary']['growth_rate']:.2f}%
💰 Estimated future revenue: Ksh {(prediction['summary']['next_average'] * 0.12):,.0f} (based on current tariff)

Recommendation: {'Increase collection efforts' if payment_rate < 70 else 'Maintain current strategy'}"""

    elif 'collection' in question or 'payment' in question:
        answer = f"""💳 Payment Analysis:
• Collection Rate: {payment_rate:.1f}%
• Outstanding Amount: Ksh {total_outstanding:,.2f}
• Total Collected: Ksh {total_collected:,.2f}

Recommendations:
1. Send reminders to customers with pending invoices
2. Offer payment plans for overdue accounts
3. Consider early payment discounts"""

    elif 'improve' in question or 'increase' in question or 'revenue' in question:
        answer = f"""📈 Revenue Improvement Strategies:

Current Revenue: Ksh {total_revenue:,.2f}
Collection Rate: {payment_rate:.1f}%

Recommended Actions:
1. Reduce threshold for high-usage customers
2. Implement tiered pricing for excess consumption
3. Send timely invoices (within 3 days of approval)
4. Offer incentives for on-time payments

Projected revenue increase with implementation: 15-25%"""

    elif 'trend' in question:
        answer = f"""📊 Current Financial Trends:
• Payment collection is {'above' if payment_rate > 70 else 'below'} target
• Outstanding balance represents {(total_outstanding / total_revenue * 100) if total_revenue > 0 else 0:.1f}% of revenue
• Revenue growth rate: {prediction['summary']['growth_rate']:.2f}%

Focus on: {'Reducing outstanding balances' if total_outstanding > total_collected / 2 else 'Maintaining collection efficiency'}"""

    else:
        answer = f"""📋 Financial Summary:

💰 Total Revenue: Ksh {total_revenue:,.2f}
💵 Collected: Ksh {total_collected:,.2f}
⚠️ Outstanding: Ksh {total_outstanding:,.2f}
📊 Collection Rate: {payment_rate:.1f}%
📈 Growth Rate: {prediction['summary']['growth_rate']:.2f}%

Ask me about: predictions, collections, improvements, or trends for more specific advice."""

    return jsonify({'answer': answer})


@app.route('/examiner/forecast', methods=['POST'])
@login_required
@examiner_required
def examiner_forecast():
    """Generate forecast for examiner"""
    data = request.get_json()
    past_years = int(data.get('past_years', 10))
    future_years = int(data.get('future_years', 10))
    prediction = build_prediction_payload(years_back=past_years, years_forward=future_years)
    return jsonify(prediction)


@app.route('/examiner/send_payment_reminder/<int:invoice_id>', methods=['POST'])
@login_required
@examiner_required
def examiner_send_payment_reminder(invoice_id):
    """Send payment reminder to customer"""
    invoice = FinancialRecord.query.get(invoice_id)
    if invoice and invoice.user:
        message = f"""
        Dear {invoice.user.username},

        This is a payment reminder for your invoice period {invoice.period}.
        Outstanding Balance: {invoice.user.currency} {invoice.balance:.2f}
        Due Date: {invoice.due_date.strftime('%Y-%m-%d') if invoice.due_date else 'N/A'}

        Please make your payment to avoid service interruption.
        """

        report = Report(
            title=f"Payment Reminder - {invoice.period}",
            content=message,
            report_type='payment_reminder',
            sent_by=current_user.id,
            sent_to=invoice.user.id
        )
        db.session.add(report)

        if getattr(invoice.user, 'alert_email', False) and getattr(invoice.user, 'email', None):
            send_email_notification(invoice.user.email, f"Payment Reminder - {invoice.period}", message)

        db.session.commit()
        return jsonify({'message': 'Reminder sent successfully!'})
    return jsonify({'message': 'Invoice not found'})


@app.route('/export_financial_csv')
@login_required
@examiner_required
def export_financial_csv():
    """Export financial data as CSV"""
    financial_records = FinancialRecord.query.all()
    if not financial_records:
        return "No financial data", 404

    output = "Customer,Period,Consumption (kWh),Total Cost,Paid,Balance,Due Date,Status\n"
    for record in financial_records:
        output += f"{record.user.username},{record.period},{record.total_consumption:.2f},{record.total_cost:.2f},{record.total_paid:.2f},{record.balance:.2f},{record.due_date.strftime('%Y-%m-%d') if record.due_date else 'N/A'},{record.payment_status}\n"

    return send_file(
        io.BytesIO(output.encode()),
        mimetype="text/csv",
        as_attachment=True,
        download_name=f"financial_report_{datetime.utcnow().strftime('%Y%m%d')}.csv"
    )


@app.route('/export_financial_pdf')
@login_required
@examiner_required
def export_financial_pdf():
    """Export financial data as PDF"""
    try:
        from reportlab.lib.pagesizes import landscape, A4
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib import colors
        import io as io_lib

        financial_records = FinancialRecord.query.all()
        if not financial_records:
            return "No financial data", 404

        buffer = io_lib.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=landscape(A4))
        styles = getSampleStyleSheet()
        elements = []

        # Title
        title_style = ParagraphStyle('CustomTitle', parent=styles['Title'], fontSize=16, spaceAfter=30)
        elements.append(Paragraph(f"EcoPulse Financial Report - {datetime.utcnow().strftime('%B %Y')}", title_style))
        elements.append(Spacer(1, 20))

        # Summary
        total_revenue = sum(r.total_cost for r in financial_records)
        total_collected = sum(r.total_paid for r in financial_records)
        total_outstanding = sum(r.balance for r in financial_records)

        summary_data = [
            ["Metric", "Amount (Ksh)"],
            ["Total Revenue", f"{total_revenue:,.2f}"],
            ["Total Collected", f"{total_collected:,.2f}"],
            ["Total Outstanding", f"{total_outstanding:,.2f}"],
            ["Collection Rate", f"{(total_collected / total_revenue * 100) if total_revenue > 0 else 0:.1f}%"]
        ]

        summary_table = Table(summary_data)
        summary_table.setStyle(TableStyle([
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke)
        ]))
        elements.append(summary_table)
        elements.append(Spacer(1, 20))

        # Detailed records table
        data = [["Customer", "Period", "Consumption", "Total Cost", "Paid", "Balance", "Status"]]
        for r in financial_records:
            data.append([
                r.user.username,
                r.period,
                f"{r.total_consumption:.2f} kWh",
                f"Ksh {r.total_cost:.2f}",
                f"Ksh {r.total_paid:.2f}",
                f"Ksh {r.balance:.2f}",
                r.payment_status
            ])

        table = Table(data, repeatRows=1)
        table.setStyle(TableStyle([
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('FONTSIZE', (0, 0), (-1, -1), 9)
        ]))
        elements.append(table)

        doc.build(elements)
        buffer.seek(0)

        return send_file(
            buffer,
            as_attachment=True,
            download_name=f"financial_report_{datetime.utcnow().strftime('%Y%m%d')}.pdf",
            mimetype="application/pdf"
        )
    except Exception as e:
        return f"Error generating PDF: {str(e)}"


@app.route('/recharge-energy', methods=['GET', 'POST'])
@login_required
def recharge_energy():
    """Allow customers to recharge/buy additional energy units"""
    if current_user.role != 'customer':
        flash('Only customers can recharge energy.', 'warning')
        return redirect(url_for('dashboard'))

    user_settings = get_or_create_user_settings(current_user)
    readings = Reading.query.filter_by(user_id=current_user.id).all()
    current_total = sum(r.kwh for r in readings)
    threshold = current_user.threshold
    remaining = max(0, threshold - current_total)
    percentage = (current_total / threshold * 100) if threshold > 0 else 0

    if request.method == 'POST':
        recharge_units = float(request.form.get('recharge_units', 0))
        payment_method = request.form.get('payment_method')
        phone_number = request.form.get('phone_number', '')
        reference = request.form.get('reference', '')

        if recharge_units <= 0:
            flash('Please enter a valid number of units to recharge.', 'warning')
            return redirect(url_for('recharge_energy'))

        unit_cost = get_active_unit_cost()
        total_cost = recharge_units * unit_cost

        if payment_method == 'mpesa' and (not phone_number or len(phone_number) != 10):
            flash('Please enter a valid 10-digit phone number for M-Pesa payment.', 'warning')
            return redirect(url_for('recharge_energy'))

        if not reference or len(reference) != 10:
            flash('Reference number must be exactly 10 characters.', 'warning')
            return redirect(url_for('recharge_energy'))

        # Create recharge record
        recharge_record = FinancialRecord(
            user_id=current_user.id,
            period=f"Recharge-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
            total_consumption=0,
            total_cost=total_cost,
            total_paid=total_cost,
            balance=0,
            due_date=datetime.utcnow() + timedelta(days=365),
            payment_status='paid'
        )
        db.session.add(recharge_record)

        # Reset notification flags
        user_settings.notification_80_sent = False
        user_settings.notification_90_sent = False
        user_settings.notification_95_sent = False
        user_settings.notification_100_sent = False

        db.session.commit()

        confirmation_msg = f"""
        <h3>Recharge Successful!</h3>
        <p>You have successfully purchased <strong>{recharge_units} kWh</strong> of energy.</p>
        <p><strong>Payment Details:</strong><br>
        Method: {payment_method.upper()}<br>
        Amount: {current_user.currency} {total_cost:.2f}<br>
        Reference: {reference}</p>
        <p>Your current consumption: {current_total:.2f} kWh / {threshold} kWh ({percentage:.1f}%)</p>
        """

        report = Report(
            title=f"Energy Recharge - {recharge_units} kWh",
            content=confirmation_msg,
            report_type='recharge',
            sent_by=current_user.id,
            sent_to=current_user.id
        )
        db.session.add(report)
        db.session.commit()

        flash(f'Successfully recharged {recharge_units} kWh! Total cost: {current_user.currency} {total_cost:.2f}',
              'success')
        return redirect(url_for('dashboard'))

    # GET request - show recharge form
    return render_template_string(RECHARGE_TEMPLATE,
                                  current_total=current_total,
                                  threshold=threshold,
                                  remaining=remaining,
                                  percentage=percentage,
                                  unit_cost=get_active_unit_cost(),
                                  currency=current_user.currency)

@app.route('/view_report/<int:report_id>')
@login_required
def view_report(report_id):
    """View report details"""
    report = Report.query.get(report_id)
    if report:
        return f"<html><body><h1>{report.title}</h1><div>{report.content}</div></body></html>"
    return "Report not found", 404

@app.route('/terms-of-service')
def terms_of_service():
    return render_template_string(public_content_template,
                                  page_title='Terms of Service',
                                  page_name='Terms of Service',
                                  hero_title='Operational terms for using EcoPulse',
                                  hero_text='These terms explain acceptable use, billing expectations, and role-based system access.',
                                  sections=PUBLIC_TERMS,
                                  footer_links=PUBLIC_FOOTER_LINKS)


@app.route('/api/public-assistant', methods=['POST'])
def public_assistant():
    data = request.get_json(silent=True) or {}
    answer = answer_public_assistant(data.get('message'))
    return jsonify({'answer': answer})


@app.route('/api/staff-assistant', methods=['POST'])
@login_required
def staff_assistant():
    if current_user.role not in ['admin', 'examiner']:
        return jsonify({'answer': 'This assistant is only available to staff users.'}), 403

    data = request.get_json(silent=True) or {}
    years_back = max(1, min(int(data.get('years_back', 10) or 10), 10))
    years_forward = max(1, min(int(data.get('years_forward', 10) or 10), 10))
    prediction = build_prediction_payload(years_back=years_back, years_forward=years_forward)
    answer = answer_staff_assistant(data.get('message'), current_user.role, prediction=prediction)
    return jsonify({
        'answer': answer,
        'chart': prediction['chart'],
        'summary': prediction['summary'],
        'timeline': prediction['timeline']
    })


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        email = (request.form.get('email') or '').strip()
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        meter_number = ''.join(ch for ch in (request.form.get('meter_number') or '') if ch.isdigit())
        country_code = (request.form.get('country_code') or '+254').strip()
        phone_number = (request.form.get('phone_number') or '').strip()
        role = 'customer'
        department = None

        if not username or not email or not password:
            return render_template_string(register_page,
                                          error='All fields required',
                                          generated_meter=meter_number or generate_valid_meter_number(),
                                          phone_number=phone_number,
                                          selected_country_code=country_code,
                                          phone_country_codes=PHONE_COUNTRY_CODES)
        if password != confirm_password:
            return render_template_string(register_page,
                                          error='Passwords do not match',
                                          generated_meter=meter_number or generate_valid_meter_number(),
                                          phone_number=phone_number,
                                          selected_country_code=country_code,
                                          phone_country_codes=PHONE_COUNTRY_CODES)
        if User.query.filter_by(username=username).first():
            return render_template_string(register_page,
                                          error='Username exists',
                                          generated_meter=meter_number or generate_valid_meter_number(),
                                          phone_number=phone_number,
                                          selected_country_code=country_code,
                                          phone_country_codes=PHONE_COUNTRY_CODES)
        if User.query.filter_by(email=email).first():
            return render_template_string(register_page,
                                          error='Email registered',
                                          generated_meter=meter_number or generate_valid_meter_number(),
                                          phone_number=phone_number,
                                          selected_country_code=country_code,
                                          phone_country_codes=PHONE_COUNTRY_CODES)
        if not meter_number:
            meter_number = generate_valid_meter_number()
        if not is_valid_meter_number(meter_number):
            return render_template_string(register_page,
                                          error='Meter number must be a valid 11-digit KPLC meter number',
                                          generated_meter=meter_number,
                                          phone_number=phone_number,
                                          selected_country_code=country_code,
                                          phone_country_codes=PHONE_COUNTRY_CODES)
        if User.query.filter_by(meter_number=meter_number).first():
            return render_template_string(register_page,
                                          error='Meter number already exists',
                                          generated_meter=generate_valid_meter_number(),
                                          phone_number=phone_number,
                                          selected_country_code=country_code,
                                          phone_country_codes=PHONE_COUNTRY_CODES)

        normalized_phone, phone_error = normalize_phone_number(country_code, phone_number)
        if phone_error:
            return render_template_string(register_page,
                                          error=phone_error,
                                          generated_meter=meter_number,
                                          phone_number=phone_number,
                                          selected_country_code=country_code,
                                          phone_country_codes=PHONE_COUNTRY_CODES)

        user = User(username=username, email=email, role=role, department=department)
        user.set_password(password)
        user.meter_number = meter_number
        user.phone_number = normalized_phone

        db.session.add(user)
        db.session.flush()
        settings = UserSettings(user_id=user.id, alert_threshold=user.threshold)
        db.session.add(settings)

        db.session.commit()

        log_system_action(user.id, f"User registered as {role}")
        flash(f"Registration successful. Your autogenerated KPLC meter number is {user.meter_number}. Use it when logging in.", 'info')

        return redirect(url_for('login'))
    return render_template_string(register_page,
                                  generated_meter=generate_valid_meter_number(),
                                  phone_number='7000000000',
                                  selected_country_code='+254',
                                  phone_country_codes=PHONE_COUNTRY_CODES)


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        password = request.form.get('password')
        meter_number = ''.join(ch for ch in (request.form.get('meter_number') or '') if ch.isdigit())
        user = User.query.filter_by(username=username, role='customer').first()

        if not meter_number:
            return render_template_string(login_page, error='Enter your KPLC meter number')

        if user and user.check_password(password) and user.meter_number == meter_number:
            login_user(user)
            log_system_action(user.id, "Customer logged in")
            return redirect(url_for('dashboard'))

        return render_template_string(login_page, error='Invalid username, password, or meter number')
    return render_template_string(login_page)


@app.route('/staff/login', methods=['GET', 'POST'])
def staff_login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        selected_role = request.form.get('role')

        if selected_role not in ['admin', 'examiner']:
            return render_template_string(staff_login_page, error='Select a valid staff role')

        user = User.query.filter_by(username=username, role=selected_role).first()
        if user and user.check_password(password):
            login_user(user)
            log_system_action(user.id, f"{selected_role.capitalize()} logged in")
            return redirect(url_for('dashboard'))

        return render_template_string(staff_login_page, error='Invalid credentials')

    return render_template_string(staff_login_page)


@app.route('/logout')
@login_required
def logout():
    """User logout route"""
    log_system_action(current_user.id, "User logged out")
    logout_user()
    return redirect(url_for('login'))


@app.route('/dashboard')
@login_required
def dashboard():
    if current_user.role == 'examiner':
        return redirect(url_for('examiner_dashboard'))
    elif current_user.role == 'admin':
        return redirect(url_for('admin_financial'))

    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    days = request.args.get('days', type=int)
    user_settings = get_or_create_user_settings(current_user)
    ensure_customer_meter_number(current_user, commit=True)
    readings = get_user_readings(current_user.id, days=days, start_date=start_date, end_date=end_date)
    analytics = None
    if readings:
        total_kwh = sum(r.kwh for r in readings)
        avg_kwh = total_kwh / len(readings) if readings else 0
        total_cost = sum(r.kwh * current_user.unit_cost for r in readings)
        total_co2 = total_kwh * 0.385

        analytics = {
            'total_kwh': round(total_kwh, 2),
            'avg_kwh': round(avg_kwh, 2),
            'total_cost': round(total_cost, 2),
            'total_co2': round(total_co2, 2),
            'currency': current_user.currency
        }

    chart = generate_consumption_chart(current_user.id)
    reports = Report.query.filter_by(sent_to=current_user.id).order_by(Report.created_at.desc()).limit(5).all()
    customer_invoices = FinancialRecord.query.filter_by(user_id=current_user.id) \
        .order_by(FinancialRecord.created_at.desc()) \
        .all()
    payable_invoices = [invoice for invoice in customer_invoices if (invoice.balance or 0) > 0]
    pending_submission = CustomerSubmission.query.filter_by(customer_id=current_user.id, status='pending').first()
    current_tariff = get_latest_kplc_tariff_notice()
    customer_alerts = Report.query.filter(
        Report.sent_to == current_user.id,
        Report.report_type.in_(['invoice', 'energy_advisory'])
    ).order_by(Report.created_at.desc()).limit(5).all()
    customer_devices = CustomerDevice.query.filter_by(user_id=current_user.id).order_by(CustomerDevice.created_at.desc()).all()
    threshold_state = None

    if readings:
        latest = max(readings, key=lambda item: item.timestamp or item.created_at)
        if latest.kwh > current_user.threshold:
            threshold_state = {
                'latest_kwh': latest.kwh,
                'threshold': current_user.threshold,
                'allow_overage': user_settings.allow_overage,
                'scheduled_shutdown_at': user_settings.scheduled_shutdown_at,
                'overage_charge': max(0, latest.cost - (latest.kwh * current_user.unit_cost))
            }
    smart_meter = build_customer_meter_status(readings, current_user, user_settings, customer_invoices)
    device_prediction = build_customer_device_prediction(
        current_user,
        customer_devices,
        analytics['total_kwh'] if analytics else 0.0
    )

    return render_template_string(customer_dashboard_template_v2,
                                  readings=readings,
                                  analytics=analytics,
                                  chart=chart,
                                  reports=reports,
                                  customer_invoices=customer_invoices,
                                  payable_invoices=payable_invoices,
                                  pending_submission=pending_submission,
                                  current_tariff=current_tariff,
                                  customer_alerts=customer_alerts,
                                  user_settings=user_settings,
                                  threshold_state=threshold_state,
                                  smart_meter=smart_meter,
                                  customer_devices=customer_devices,
                                  device_prediction=device_prediction,
                                  now=local_now(),
                                  footer_links=PUBLIC_FOOTER_LINKS)


@app.route('/examiner_dashboard')
@login_required
@examiner_required
def examiner_dashboard():
    customers = User.query.filter_by(role='customer').all()
    readings = Reading.query.all()
    financial_records = FinancialRecord.query.all()

    # Get approved customers (those with approved readings)
    approved_customers = []
    for customer in customers:
        approved_readings = Reading.query.filter_by(user_id=customer.id, is_approved=True).all()
        if approved_readings:
            approved_consumption = sum(r.kwh for r in approved_readings)
            customer.approved_consumption = approved_consumption
            approved_customers.append(customer)

    total_customers = len([c for c in customers if c.readings])
    total_consumption = sum(r.kwh for r in readings)
    total_revenue = sum(r.kwh * User.query.get(r.user_id).unit_cost for r in readings)
    total_co2 = sum(r.kwh * 0.385 for r in readings)

    # Financial stats
    total_collected = sum(r.total_paid for r in financial_records)
    total_outstanding = sum(r.balance for r in financial_records)
    pending_invoices = len([r for r in financial_records if r.payment_status == 'pending'])
    approved_customers_count = len(approved_customers)

    consumption_stats = {
        'total_customers': total_customers,
        'total_consumption': total_consumption,
        'total_revenue': total_revenue,
        'total_co2': total_co2,
        'total_readings': len(readings),
        'reviewed_count': len([r for r in readings if r.is_reviewed]),
        'pending_count': len([r for r in readings if not r.is_reviewed]),
        'approved_count': len([r for r in readings if r.is_approved]),
        'approved_customers': approved_customers_count,
        'pending_invoices': pending_invoices,
        'total_collected': total_collected,
        'total_outstanding': total_outstanding
    }

    # Chart data
    revenue_labels = []
    revenue_data = []
    for customer in approved_customers[:10]:
        revenue_labels.append(customer.username)
        customer_revenue = sum(
            r.kwh * customer.unit_cost for r in Reading.query.filter_by(user_id=customer.id, is_approved=True).all())
        revenue_data.append(customer_revenue)

    # Payment status counts
    paid_count = len([r for r in financial_records if r.payment_status == 'paid'])
    pending_count = len([r for r in financial_records if r.payment_status == 'pending'])
    overdue_count = len([r for r in financial_records if r.payment_status == 'overdue'])

    # Monthly trend data (last 12 months)
    trend_labels = []
    trend_data = []
    for i in range(11, -1, -1):
        month_date = datetime.utcnow() - timedelta(days=30 * i)
        month_str = month_date.strftime('%b %Y')
        trend_labels.append(month_str)
        month_records = FinancialRecord.query.filter(
            FinancialRecord.created_at >= month_date.replace(day=1),
            FinancialRecord.created_at < (month_date.replace(day=1) + timedelta(days=32)).replace(day=1)
        ).all()
        month_revenue = sum(r.total_cost for r in month_records)
        trend_data.append(month_revenue)

    pending_readings = Reading.query.filter_by(is_reviewed=False).all()
    pending_count = len(pending_readings)
    reviewed_readings = Reading.query.filter_by(is_reviewed=True, is_approved=False).all()
    all_readings = Reading.query.order_by(Reading.created_at.desc()).limit(20).all()
    sent_invoices = FinancialRecord.query.order_by(FinancialRecord.created_at.desc()).limit(20).all()
    financial_reports = Report.query.filter_by(report_type='financial_report', sent_by=current_user.id).order_by(
        Report.created_at.desc()).limit(10).all()
    prediction_payload = build_prediction_payload()
    consumption_report = None
    current_tariff = get_latest_kplc_tariff_notice()
    default_unit_cost = get_active_unit_cost()

    return render_template_string(examiner_template,
                                  consumption_stats=consumption_stats,
                                  pending_readings=pending_readings,
                                  pending_count=pending_count,
                                  reviewed_readings=reviewed_readings,
                                  all_readings=all_readings,
                                  customers=customers,
                                  approved_customers=approved_customers,
                                  sent_invoices=sent_invoices,
                                  financial_reports=financial_reports,
                                  consumption_report=consumption_report,
                                  prediction_payload=prediction_payload,
                                  current_tariff=current_tariff,
                                  default_unit_cost=default_unit_cost,
                                  revenue_labels=revenue_labels,
                                  revenue_data=revenue_data,
                                  paid_count=paid_count,
                                  overdue_count=overdue_count,
                                  trend_labels=trend_labels,
                                  trend_data=trend_data)


@app.route('/view_consumption_report', methods=['POST'])
@login_required
@examiner_required
def view_consumption_report():
    consumption_report = generate_examiner_consumption_report()
    customers = User.query.filter_by(role='customer').all()
    readings = Reading.query.all()

    consumption_stats = {
        'total_customers': len([c for c in customers if c.readings]),
        'total_consumption': sum(r.kwh for r in readings),
        'total_revenue': sum(r.kwh * User.query.get(r.user_id).unit_cost for r in readings),
        'total_co2': sum(r.kwh * 0.385 for r in readings),
        'total_readings': len(readings),
        'reviewed_count': len([r for r in readings if r.is_reviewed]),
        'pending_count': len([r for r in readings if not r.is_reviewed]),
        'approved_count': len([r for r in readings if r.is_approved])
    }

    pending_readings = Reading.query.filter_by(is_reviewed=False).all()
    pending_count = len(pending_readings)
    reviewed_readings = Reading.query.filter_by(is_reviewed=True, is_approved=False).all()
    all_readings = Reading.query.order_by(Reading.created_at.desc()).limit(20).all()
    review_history = ConsumptionReview.query.filter_by(examiner_id=current_user.id) \
        .order_by(ConsumptionReview.created_at.desc()) \
        .limit(10).all()
    examiner_invoices = FinancialRecord.query.order_by(FinancialRecord.created_at.desc()).limit(15).all()
    prediction_payload = build_prediction_payload()
    smart_meter = build_examiner_meter_status(consumption_stats, pending_readings, reviewed_readings)
    current_tariff = get_latest_kplc_tariff_notice()

    # Use the existing examiner_template (not examiner_template_v2)
    return render_template_string(examiner_template,
                                  consumption_stats=consumption_stats,
                                  pending_readings=pending_readings,
                                  pending_count=pending_count,
                                  reviewed_readings=reviewed_readings,
                                  all_readings=all_readings,
                                  customers=customers,
                                  review_history=review_history,
                                  consumption_report=consumption_report,
                                  examiner_invoices=examiner_invoices,
                                  prediction_payload=prediction_payload,
                                  smart_meter=smart_meter,
                                  current_tariff=current_tariff)


@app.route('/examiner/send-invoice', methods=['POST'])
@login_required
@examiner_required
def examiner_send_invoice():
    customer_id = request.form.get('customer_id', type=int)
    period = (request.form.get('period') or '').strip()
    total_consumption = request.form.get('total_consumption', type=float)
    total_cost = request.form.get('total_cost', type=float)
    due_date_raw = (request.form.get('due_date') or '').strip()
    notes = (request.form.get('notes') or '').strip()

    customer = User.query.filter_by(id=customer_id, role='customer').first()
    if not customer or not period or total_consumption is None or total_cost is None:
        flash('Fill in the customer, period, consumption, and total cost before sending an invoice.', 'warning')
        return redirect(url_for('examiner_dashboard'))

    due_date = datetime.fromisoformat(due_date_raw) if due_date_raw else (datetime.utcnow() + timedelta(days=30))
    record = FinancialRecord.query.filter_by(user_id=customer.id, period=period).first()

    if not record:
        record = FinancialRecord(
            user_id=customer.id,
            period=period,
            total_paid=0
        )
        db.session.add(record)

    record.total_consumption = total_consumption
    record.total_cost = total_cost
    record.due_date = due_date
    record.balance = max(total_cost - (record.total_paid or 0), 0)
    record.payment_status = 'paid' if record.balance <= 0 else 'pending'

    invoice_message = (
        f"Invoice for {period}: {customer.currency} {total_cost:.2f}. "
        f"Due date: {due_date.strftime('%Y-%m-%d')}. "
        f"{notes if notes else 'Review your dashboard for the full invoice details.'}"
    )

    db.session.add(Report(
        title=f"Invoice Issued - {period}",
        content=invoice_message,
        report_type='invoice',
        sent_by=current_user.id,
        sent_to=customer.id
    ))
    db.session.commit()

    if getattr(customer, 'alert_email', False) and getattr(customer, 'email', None):
        send_email_notification(
            customer.email,
            f"EcoPulse Invoice - {period}",
            f"<p>Dear {customer.username},</p><p>{invoice_message}</p>"
        )

    log_system_action(current_user.id, f"Examiner sent invoice to customer ID {customer.id} for {period}")
    flash('Invoice sent to the selected customer successfully.', 'info')
    return redirect(url_for('examiner_dashboard'))


@app.route('/examiner/send-energy-alert', methods=['POST'])
@login_required
@examiner_required
def examiner_send_energy_alert():
    customer_id = request.form.get('customer_id', type=int)
    message = (request.form.get('message') or '').strip()
    send_email = 'send_email' in request.form
    send_sms = 'send_sms' in request.form
    customer = User.query.filter_by(id=customer_id, role='customer').first()

    if not customer or not message:
        flash('Select a customer and enter an advisory message before sending the alert.', 'warning')
        return redirect(url_for('examiner_dashboard'))

    delivery_notes = []
    if send_email and getattr(customer, 'alert_email', False) and getattr(customer, 'email', None):
        ok, err = send_email_notification(
            customer.email,
            'EcoPulse Energy Advisory',
            f"<p>Dear {customer.username},</p><p>{message}</p><p>Please minimize or switch off high-consumption appliances where possible.</p>"
        )
        delivery_notes.append('Email sent' if ok else f'Email failed: {err}')
    elif send_email:
        delivery_notes.append('Email unavailable')

    if send_sms:
        ok, err = send_sms_notification(customer.phone_number, message)
        delivery_notes.append('SMS queued' if ok else f'SMS failed: {err}')

    if not send_email and not send_sms:
        delivery_notes.append('Dashboard alert only')

    db.session.add(Report(
        title=f"Energy Advisory - {customer.username}",
        content=(
            f"<p><strong>Message:</strong> {message}</p>"
            f"<p><strong>Delivery:</strong> {', '.join(delivery_notes)}</p>"
            f"<p><strong>Meter:</strong> {customer.meter_number}</p>"
        ),
        report_type='energy_advisory',
        sent_by=current_user.id,
        sent_to=customer.id,
        chart_data=json.dumps({
            'customer_id': customer.id,
            'meter_number': customer.meter_number,
            'delivery_notes': delivery_notes
        })
    ))
    db.session.commit()

    log_system_action(current_user.id, f"Sent energy advisory to customer ID {customer.id}")
    flash('Energy advisory sent to the selected customer.', 'info')
    return redirect(url_for('examiner_dashboard'))


@app.route('/review_reading/<int:reading_id>', methods=['POST'])
@login_required
@examiner_required
def review_reading(reading_id):
    """Review a single reading"""
    reading = Reading.query.get(reading_id)
    if reading:
        decision = request.form.get('decision')
        notes = request.form.get('notes')

        reading.is_reviewed = True
        reading.reviewed_by = current_user.id
        reading.reviewed_at = datetime.utcnow()
        reading.review_notes = notes

        if decision == 'approve':
            # Mark as reviewed and ready for admin
            reading.is_approved = False
        else:
            # Reject - needs correction
            reading.is_approved = False

        db.session.commit()

        log_system_action(current_user.id, f"Reviewed reading ID: {reading_id} - {decision}")

    return redirect(url_for('examiner_dashboard'))


@app.route('/send_review_to_admin', methods=['POST'])
@login_required
@examiner_required
def send_review_to_admin():
    """Send consolidated review to admin - includes all readings"""
    # Get all readings (both reviewed and unreviewed)
    all_readings = Reading.query.all()

    if not all_readings:
        return jsonify({'success': False, 'message': 'No readings available to send'})

    # Calculate statistics for all readings
    customers = User.query.filter_by(role='customer').all()
    total_customers = len([c for c in customers if c.readings])
    total_consumption = sum(r.kwh for r in all_readings)
    avg_consumption = total_consumption / total_customers if total_customers > 0 else 0
    peak_consumption = max([r.kwh for r in all_readings]) if all_readings else 0

    # Count readings by status
    reviewed_count = len([r for r in all_readings if r.is_reviewed])
    pending_count = len([r for r in all_readings if not r.is_reviewed])
    approved_count = len([r for r in all_readings if r.is_approved])

    # Create a comprehensive review
    notes = f"""Consumption Review Report - {datetime.utcnow().strftime('%B %Y')}

Summary:
- Total Readings: {len(all_readings)}
- Reviewed Readings: {reviewed_count}
- Pending Review: {pending_count}
- Approved Readings: {approved_count}
- Total Customers: {total_customers}
- Total Consumption: {total_consumption:.2f} kWh
- Average Consumption: {avg_consumption:.2f} kWh
- Peak Consumption: {peak_consumption:.2f} kWh

Please review and approve this consumption report.
"""

    review = ConsumptionReview(
        examiner_id=current_user.id,
        period=datetime.utcnow().strftime('%Y-%m'),
        total_consumption=total_consumption,
        total_customers=total_customers,
        average_consumption=avg_consumption,
        peak_consumption=peak_consumption,
        notes=notes,
        status='pending_review'
    )
    db.session.add(review)
    db.session.commit()

    log_system_action(current_user.id, f"Sent consumption review to admin with {len(all_readings)} readings")

    return jsonify({
        'success': True,
        'message': f'Review sent to admin successfully! ({len(all_readings)} readings, {reviewed_count} reviewed, {pending_count} pending)'
    })


@app.route('/admin_financial')
@login_required
@admin_required
def admin_financial():
    financial = generate_financial_report()
    if financial is None:
        financial = {
            'chart': None,
            'total_revenue': 0,
            'total_outstanding': 0,
            'total_collected': 0,
            'payment_rate': 0
        }

    financial_records = FinancialRecord.query.all()
    if not financial_records:
        financial_records = []
    pending_reviews = ConsumptionReview.query.filter_by(status='pending_review').all()
    examiner_reports = Report.query.filter_by(report_type='system_analysis') \
        .order_by(Report.created_at.desc()) \
        .limit(5) \
        .all()
    if not examiner_reports:
        examiner_reports = []
    prediction_payload = build_prediction_payload()
    contact_messages = ContactMessage.query.order_by(ContactMessage.created_at.desc()).limit(10).all()
    smart_meter = build_admin_meter_status(financial, pending_reviews, financial_records)
    kplc_notifications = Report.query.filter_by(report_type='kplc_tariff').order_by(Report.created_at.desc()).limit(5).all()
    sensor_alerts = Report.query.filter_by(report_type='sensor_alert').order_by(Report.created_at.desc()).limit(10).all()
    current_tariff = get_latest_kplc_tariff_notice()

    return render_template_string(admin_financial_template_v2,
                                  financial=financial,
                                  financial_records=financial_records,
                                  examiner_reports=examiner_reports,
                                  pending_reviews=pending_reviews,
                                  prediction_payload=prediction_payload,
                                  contact_messages=contact_messages,
                                  smart_meter=smart_meter,
                                  kplc_notifications=kplc_notifications,
                                  sensor_alerts=sensor_alerts,
                                  current_tariff=current_tariff)


@app.route('/admin/contact-messages')
@login_required
@admin_required
def admin_contact_messages():
    messages = ContactMessage.query.order_by(ContactMessage.created_at.desc()).all()
    return render_template_string(admin_contact_messages_template, messages=messages)


@app.route('/admin/update-kplc-tariff', methods=['POST'])
@login_required
@admin_required
def update_kplc_tariff():
    try:
        cost_per_unit = float(request.form.get('cost_per_unit', '0'))
    except (TypeError, ValueError):
        flash('Enter a valid KPLC cost per unit.', 'warning')
        return redirect(url_for('admin_financial'))

    effective_date_raw = (request.form.get('effective_date') or '').strip()
    notice_reference = (request.form.get('notice_reference') or 'KPLC Tariff Notice').strip()
    notice_message = (request.form.get('notice_message') or '').strip()
    if cost_per_unit <= 0:
        flash('KPLC cost per unit must be greater than zero.', 'warning')
        return redirect(url_for('admin_financial'))

    effective_date = datetime.fromisoformat(effective_date_raw) if effective_date_raw else utc_now()
    users = User.query.filter(User.role.in_(['admin', 'examiner', 'customer'])).all()
    for user in users:
        user.unit_cost = cost_per_unit

    payload = {
        'cost_per_unit': round(cost_per_unit, 2),
        'effective_date': effective_date.strftime('%Y-%m-%d'),
        'notice_reference': notice_reference
    }
    db.session.add(Report(
        title=f"KPLC Tariff Update - {effective_date.strftime('%Y-%m-%d')}",
        content=(
            f"<p><strong>Reference:</strong> {notice_reference}</p>"
            f"<p><strong>Cost per unit/token:</strong> Ksh {cost_per_unit:.2f}</p>"
            f"<p><strong>Effective date:</strong> {effective_date.strftime('%Y-%m-%d')}</p>"
            f"<p>{notice_message or 'Tariff updated from KPLC notice for billing clarity.'}</p>"
        ),
        report_type='kplc_tariff',
        sent_by=current_user.id,
        sent_to=None,
        chart_data=json.dumps(payload)
    ))
    db.session.commit()

    log_system_action(current_user.id, f"Updated KPLC tariff to Ksh {cost_per_unit:.2f}")
    flash('KPLC tariff updated. Customers and examiners now see the latest cost per unit.', 'info')
    return redirect(url_for('admin_financial'))


@app.route('/ai-analysis')
@login_required
def ai_analysis():
    report = build_ai_course_report()
    if current_user.role == 'admin':
        back_url = url_for('admin_financial')
    elif current_user.role == 'examiner':
        back_url = url_for('examiner_dashboard')
    else:
        back_url = url_for('dashboard')
    return render_template_string(ai_course_template, report=report, back_url=back_url)


@app.route('/approve_review/<int:review_id>', methods=['POST'])
@login_required
@admin_required
def approve_review(review_id):
    """Approve a consumption review"""
    review = ConsumptionReview.query.get(review_id)
    if review:
        review.status = 'approved'
        review.approved_by = current_user.id
        review.approved_at = datetime.utcnow()

        # Mark all readings as approved
        readings = Reading.query.all()
        for reading in readings:
            reading.is_approved = True
            reading.approved_by = current_user.id
            reading.approved_at = datetime.utcnow()

        db.session.commit()

        log_system_action(current_user.id, f"Approved consumption review ID: {review_id}")
        return jsonify({'message': 'Review approved successfully!'})

    return jsonify({'message': 'Review not found'})


@app.route('/reject_review/<int:review_id>', methods=['POST'])
@login_required
@admin_required
def reject_review(review_id):
    """Reject a consumption review"""
    review = ConsumptionReview.query.get(review_id)
    if review:
        review.status = 'rejected'
        db.session.commit()

        log_system_action(current_user.id, f"Rejected consumption review ID: {review_id}")
        return jsonify({'message': 'Review rejected. Please ask examiner to revise.'})

    return jsonify({'message': 'Review not found'})


@app.route('/send_customer_summaries', methods=['POST'])
@login_required
@admin_required
def send_customer_summaries():
    """Send consumption summaries to all customers"""
    customers_sent = send_report_to_customers(current_user.id)

    # Update financial records
    customers = User.query.filter_by(role='customer').all()
    for customer in customers:
        readings = Reading.query.filter_by(user_id=customer.id).all()
        if readings:
            total_kwh = sum(r.kwh for r in readings)
            total_cost = sum(r.kwh * customer.unit_cost for r in readings)

            # Create or update financial record
            period = datetime.utcnow().strftime('%Y-%m')
            record = FinancialRecord.query.filter_by(user_id=customer.id, period=period).first()

            if not record:
                record = FinancialRecord(
                    user_id=customer.id,
                    period=period,
                    total_consumption=total_kwh,
                    total_cost=total_cost,
                    balance=total_cost,
                    due_date=datetime.utcnow() + timedelta(days=30),
                    payment_status='pending'
                )
                db.session.add(record)
            else:
                record.total_consumption = total_kwh
                record.total_cost = total_cost
                record.balance = total_cost - record.total_paid

            db.session.commit()

    return redirect(url_for('admin_financial'))


@app.route('/add_reading', methods=['POST'])
@login_required
def add_reading():
    date = request.form.get('date')
    kwh = request.form.get('kwh')
    timestamp_str = request.form.get('timestamp')

    try:
        kwh = float(kwh)
        ensure_customer_meter_number(current_user)
        timestamp = parse_local_datetime_input(timestamp_str)
        user_settings = get_or_create_user_settings(current_user)
        current_user.unit_cost = get_active_unit_cost()
        cost, overage_charge = calculate_reading_cost(current_user, user_settings, kwh)
        current_total_kwh = sum(reading.kwh for reading in Reading.query.filter_by(user_id=current_user.id).all()) + kwh

        reading = Reading(
            user_id=current_user.id,
            date=date,
            kwh=kwh,
            cost=cost,
            timestamp=timestamp,
            is_reviewed=False,
            is_approved=False
        )
        db.session.add(reading)
        message = f"Added reading: {kwh} kWh for {date}"

        if kwh > current_user.threshold:
            exceeded_by = kwh - current_user.threshold
            user_settings.last_threshold_alert_at = datetime.utcnow()
            if user_settings.allow_overage:
                user_settings.scheduled_shutdown_at = None
                message += f" with an overage charge of {current_user.currency} {overage_charge:.2f}"
                flash("Threshold exceeded. Overage mode is enabled, so service continues and extra charges apply.", 'info')
            else:
                if user_settings.auto_shutdown_enabled:
                    user_settings.scheduled_shutdown_at = datetime.utcnow() + timedelta(
                        minutes=user_settings.shutdown_delay_minutes
                    )
                    flash(
                        f"Threshold exceeded. Alerts were raised and automatic shutdown is scheduled in {user_settings.shutdown_delay_minutes} minutes.",
                        'warning'
                    )
                else:
                    flash("Threshold exceeded. Alerts were raised for manual intervention.", 'warning')
            create_sensor_alert_report(current_user, reading, exceeded_by, user_settings)
        else:
            user_settings.scheduled_shutdown_at = None

        triggered_notifications = check_and_send_threshold_notifications(current_user, current_total_kwh, user_settings)
        if triggered_notifications:
            message += f" and triggered notifications for {', '.join(triggered_notifications)}"

        db.session.commit()
        log_system_action(current_user.id, message)

    except Exception as e:
        print(f"Error adding reading: {e}")
        db.session.rollback()

    return redirect(url_for('dashboard'))


@app.route('/update_reading/<int:reading_id>', methods=['POST'])
@login_required
def update_reading(reading_id):
    """Update an existing reading"""
    reading = Reading.query.filter_by(id=reading_id, user_id=current_user.id).first()
    if reading:
        reading.date = request.form.get('date')
        reading.kwh = float(request.form.get('kwh'))
        current_user.unit_cost = get_active_unit_cost()
        reading.cost = reading.kwh * current_user.unit_cost
        reading.timestamp = parse_local_datetime_input(request.form.get('timestamp'))
        reading.is_reviewed = False  # Reset review status
        reading.is_approved = False
        db.session.commit()
        log_system_action(current_user.id, f"Updated reading ID: {reading_id}")
    return redirect(url_for('dashboard'))


@app.route('/delete_reading/<int:reading_id>', methods=['POST'])
@login_required
def delete_reading(reading_id):
    """Delete a reading"""
    reading = Reading.query.filter_by(id=reading_id, user_id=current_user.id).first()
    if reading:
        db.session.delete(reading)
        db.session.commit()
        log_system_action(current_user.id, f"Deleted reading ID: {reading_id}")
    return redirect(url_for('dashboard'))


@app.route('/customer_devices/add', methods=['POST'])
@login_required
def add_customer_device():
    if current_user.role != 'customer':
        flash('Only customers can add devices.', 'warning')
        return redirect(url_for('dashboard'))

    name = (request.form.get('name') or '').strip()
    category = (request.form.get('category') or 'Appliance').strip()
    notes = (request.form.get('notes') or '').strip()

    try:
        watts = float(request.form.get('watts') or 0)
        hours_per_day = float(request.form.get('hours_per_day') or 0)
        quantity = int(request.form.get('quantity') or 1)
    except ValueError:
        flash('Enter valid device values before adding.', 'warning')
        return redirect(url_for('dashboard'))

    if not name or watts <= 0 or hours_per_day <= 0 or quantity <= 0:
        flash('Device name, watts, hours, and quantity are required.', 'warning')
        return redirect(url_for('dashboard'))

    db.session.add(CustomerDevice(
        user_id=current_user.id,
        name=name,
        category=category or 'Appliance',
        watts=watts,
        hours_per_day=hours_per_day,
        quantity=quantity,
        notes=notes or None
    ))
    db.session.commit()
    log_system_action(current_user.id, f"Added customer device {name}")
    flash('Device added to your customer page.', 'info')
    return redirect(url_for('dashboard'))


@app.route('/customer_devices/<int:device_id>/update', methods=['POST'])
@login_required
def update_customer_device(device_id):
    device = CustomerDevice.query.filter_by(id=device_id, user_id=current_user.id).first()
    if not device:
        flash('Device not found.', 'warning')
        return redirect(url_for('dashboard'))

    try:
        device.name = (request.form.get('name') or device.name).strip()
        device.category = (request.form.get('category') or device.category).strip() or 'Appliance'
        device.watts = float(request.form.get('watts') or device.watts)
        device.hours_per_day = float(request.form.get('hours_per_day') or device.hours_per_day)
        device.quantity = int(request.form.get('quantity') or device.quantity)
        device.notes = (request.form.get('notes') or '').strip() or None
    except ValueError:
        flash('Enter valid values before managing the device.', 'warning')
        return redirect(url_for('dashboard'))

    db.session.commit()
    log_system_action(current_user.id, f"Updated customer device ID {device_id}")
    flash('Device updated successfully.', 'info')
    return redirect(url_for('dashboard'))


@app.route('/customer_devices/<int:device_id>/delete', methods=['POST'])
@login_required
def delete_customer_device(device_id):
    device = CustomerDevice.query.filter_by(id=device_id, user_id=current_user.id).first()
    if not device:
        flash('Device not found.', 'warning')
        return redirect(url_for('dashboard'))

    db.session.delete(device)
    db.session.commit()
    log_system_action(current_user.id, f"Deleted customer device ID {device_id}")
    flash('Device removed from your customer page.', 'info')
    return redirect(url_for('dashboard'))


@app.route('/customer_notifications/test', methods=['POST'])
@login_required
def test_customer_notifications():
    if current_user.role != 'customer':
        flash('Only customers can test notifications.', 'warning')
        return redirect(url_for('dashboard'))

    simulated_total = request.form.get('simulated_total_kwh', type=float)
    if simulated_total is None:
        simulated_total = max(float(current_user.threshold or 0), 1.0)

    delivery_notes = send_customer_contact_test(current_user, simulated_total)
    log_system_action(current_user.id, 'Triggered customer notification test')
    flash('Notification test: ' + ', '.join(delivery_notes), 'info')
    return redirect(url_for('dashboard'))


@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    user_settings = get_or_create_user_settings(current_user)
    message = None
    selected_country_code, phone_number_local = split_phone_number(current_user.phone_number)

    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        email = (request.form.get('email') or '').strip()
        department = (request.form.get('department') or '').strip()

        if not username or not email:
            flash('Username and email are required.', 'warning')
            return redirect(url_for('settings'))

        existing_username = User.query.filter(User.username == username, User.id != current_user.id).first()
        if existing_username:
            flash('That username is already in use.', 'warning')
            return redirect(url_for('settings'))

        existing_email = User.query.filter(User.email == email, User.id != current_user.id).first()
        if existing_email:
            flash('That email is already registered.', 'warning')
            return redirect(url_for('settings'))

        current_user.username = username
        current_user.email = email

        if current_user.role in ['admin', 'examiner']:
            current_user.department = department or None

        current_user.threshold = float(request.form.get('threshold', current_user.threshold))
        current_user.currency = request.form.get('currency', current_user.currency)
        current_user.alert_email = 'alert_email' in request.form

        if current_user.role == 'customer':
            meter_number = ''.join(ch for ch in (request.form.get('meter_number') or '') if ch.isdigit())
            country_code = (request.form.get('country_code') or selected_country_code).strip()
            phone_number = (request.form.get('phone_number') or '').strip()

            if meter_number:
                if not is_valid_meter_number(meter_number):
                    flash('Meter number must be 11 digits and pass validation.', 'warning')
                    return redirect(url_for('settings'))
                existing_meter = User.query.filter(User.meter_number == meter_number,
                                                   User.id != current_user.id).first()
                if existing_meter:
                    flash('That meter number is already assigned to another customer.', 'warning')
                    return redirect(url_for('settings'))
                current_user.meter_number = meter_number
            else:
                ensure_customer_meter_number(current_user)

            normalized_phone, phone_error = normalize_phone_number(country_code, phone_number)
            if not phone_error:
                current_user.phone_number = normalized_phone

        current_user.unit_cost = get_active_unit_cost()
        user_settings.alert_threshold = current_user.threshold
        user_settings.allow_overage = 'allow_overage' in request.form
        user_settings.auto_shutdown_enabled = 'auto_shutdown_enabled' in request.form
        user_settings.shutdown_delay_minutes = int(request.form.get('shutdown_delay_minutes') or 5)

        db.session.commit()
        message = "Settings updated successfully!"
        log_system_action(current_user.id, "Updated settings")
        flash(message, 'success')
        return redirect(url_for('settings'))

    # Use the existing settings_template (not settings_template_v2)
    return render_template_string(settings_template,
                                  user_settings=user_settings,
                                  message=message,
                                  current_tariff=get_latest_kplc_tariff_notice(),
                                  phone_country_codes=PHONE_COUNTRY_CODES,
                                  selected_country_code=selected_country_code,
                                  phone_number_local=phone_number_local)
@app.route('/mark_as_paid/<int:record_id>', methods=['POST'])
@login_required
@admin_required
def mark_as_paid(record_id):
    """Mark a financial record as paid"""
    record = FinancialRecord.query.get(record_id)
    if record:
        record.payment_status = 'paid'
        record.total_paid = record.total_cost
        record.balance = 0
        db.session.commit()
        return jsonify({'message': 'Marked as paid successfully'})
    return jsonify({'message': 'Record not found'})


@app.route('/customer/pay/<int:record_id>', methods=['POST'])
@login_required
def customer_make_payment(record_id):
    if current_user.role != 'customer':
        flash('Only customer accounts can make invoice payments from this page.', 'warning')
        return redirect(url_for('dashboard'))

    record = FinancialRecord.query.filter_by(id=record_id, user_id=current_user.id).first()
    if not record:
        flash('Invoice not found for your account.', 'warning')
        return redirect(url_for('dashboard'))

    try:
        payment_amount = float(request.form.get('payment_amount', '0'))
    except (TypeError, ValueError):
        flash('Enter a valid payment amount.', 'warning')
        return redirect(url_for('dashboard'))

    payment_method = (request.form.get('payment_method') or '').strip()
    payment_reference = (request.form.get('payment_reference') or '').strip()
    payment_method_labels = {
        'mpesa': 'M-Pesa',
        'card': 'Card',
        'bank_transfer': 'Bank Transfer',
        'wallet': 'EcoPulse Wallet'
    }
    if payment_method not in payment_method_labels:
        flash('Select a valid payment method.', 'warning')
        return redirect(url_for('dashboard'))

    outstanding_balance = max(record.balance or 0, 0)
    if payment_amount <= 0:
        flash('Payment amount must be greater than zero.', 'warning')
        return redirect(url_for('dashboard'))
    if outstanding_balance <= 0:
        flash('This invoice is already fully paid.', 'info')
        return redirect(url_for('dashboard'))
    if payment_amount > outstanding_balance:
        flash('Payment amount cannot be more than the remaining balance.', 'warning')
        return redirect(url_for('dashboard'))

    record.total_paid = round((record.total_paid or 0) + payment_amount, 2)
    record.balance = round(max(record.total_cost - record.total_paid, 0), 2)
    record.payment_status = 'paid' if record.balance <= 0 else 'pending'
    db.session.commit()

    log_system_action(
        current_user.id,
        f"Customer payment recorded for {record.period} via {payment_method_labels[payment_method]}: "
        f"{current_user.currency} {payment_amount:.2f}"
        + (f" (ref: {payment_reference})" if payment_reference else "")
    )
    flash(
        f'Payment of {current_user.currency} {payment_amount:.2f} via {payment_method_labels[payment_method]} recorded for {record.period}.',
        'info'
    )
    return redirect(url_for('dashboard'))


@app.route('/send_payment_reminder/<int:record_id>', methods=['POST'])
@login_required
@admin_required
def send_payment_reminder(record_id):
    """Send payment reminder to customer"""
    record = FinancialRecord.query.get(record_id)
    if record and record.user:
        if getattr(record.user, 'alert_email', False) and getattr(record.user, 'email', None):
            subject = "EcoPulse Payment Reminder"
            html_body = f"""
            <h2>Payment Reminder</h2>
            <p>Dear {record.user.username},</p>
            <p>This is a reminder that your balance is <strong>{record.balance:.2f} {record.user.currency}</strong>.</p>
            <p>Please make your payment to avoid service interruption.</p>
            """
            ok, err = send_email_notification(record.user.email, subject, html_body)
            if ok:
                print(f"Payment reminder email sent to {record.user.email} for Ksh {record.balance}")
                return jsonify({'message': 'Reminder sent successfully'})
            return jsonify({'message': f'Error sending reminder email: {err}'})

        return jsonify({'message': 'Customer email alerts are disabled'})

    return jsonify({'message': 'Error sending reminder'})


@app.route('/view_review/<int:review_id>')
@login_required
def view_review(review_id):
    """View review details"""
    review = ConsumptionReview.query.get(review_id)
    if review:
        return f"<html><body><h1>Review Details</h1><pre>{review}</pre></body></html>"
    return "Review not found", 404


@app.route('/export_csv')
@login_required
def export_csv():
    """Export readings as CSV"""
    readings = Reading.query.filter_by(user_id=current_user.id).all()
    if not readings:
        return "No data", 404

    output = "Month,kWh,Cost,CO2,Status,Timestamp\n"
    for reading in readings:
        co2 = reading.kwh * 0.385
        status = "Approved" if reading.is_approved else "Pending" if not reading.is_reviewed else "Reviewed"
        output += f"{reading.date},{reading.kwh},{reading.cost:.2f},{co2:.2f},{status},{reading.timestamp}\n"

    log_system_action(current_user.id, "Exported data to CSV")

    return send_file(
        io.BytesIO(output.encode()),
        mimetype="text/csv",
        as_attachment=True,
        download_name=f"ecopulse_{current_user.username}.csv"
    )


@app.route('/export_pdf')
@login_required
def export_pdf():
    """Export readings as PDF"""
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib import colors
        import io as io_lib

        readings = Reading.query.filter_by(user_id=current_user.id).all()
        if not readings:
            return "No data", 404

        buffer = io_lib.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=letter)

        styles = getSampleStyleSheet()
        elements = []

        elements.append(Paragraph(f"EcoPulse Energy Report - {current_user.username}", styles['Title']))
        elements.append(Spacer(1, 20))

        # Summary
        total_kwh = sum(r.kwh for r in readings)
        total_cost = sum(r.kwh * current_user.unit_cost for r in readings)
        approved_count = len([r for r in readings if r.is_approved])
        pending_count = len([r for r in readings if not r.is_reviewed])

        summary_data = [
            ["Metric", "Value"],
            ["Total Consumption", f"{total_kwh:.2f} kWh"],
            ["Total Cost", f"{current_user.currency} {total_cost:.2f}"],
            ["Approved Readings", str(approved_count)],
            ["Pending Review", str(pending_count)],
            ["Number of Readings", str(len(readings))]
        ]

        summary_table = Table(summary_data)
        summary_table.setStyle(TableStyle([
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey)
        ]))
        elements.append(summary_table)
        elements.append(Spacer(1, 20))

        # Readings table
        data = [["Period", "kWh", f"Cost ({current_user.currency})", "CO2", "Status", "Timestamp"]]
        for r in readings:
            co2 = r.kwh * 0.385
            status = "Approved" if r.is_approved else "Pending" if not r.is_reviewed else "Reviewed"
            data.append([
                r.date,
                f"{r.kwh:.2f}",
                f"{r.cost:.2f}",
                f"{co2:.2f}",
                status,
                r.timestamp.strftime("%Y-%m-%d")
            ])

        table = Table(data)
        table.setStyle(TableStyle([
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke)
        ]))

        elements.append(table)
        doc.build(elements)
        buffer.seek(0)

        return send_file(
            buffer,
            as_attachment=True,
            download_name=f"ecopulse_report_{current_user.username}.pdf",
            mimetype="application/pdf"
        )

    except Exception as e:
        return f"Error generating PDF: {str(e)}"


def update_database_schema():
    """Check and update database schema if needed"""
    try:
        from sqlalchemy import inspect
        inspector = inspect(db.engine)

        # Check if readings table exists and has required columns
        if 'readings' in inspector.get_table_names():
            columns = [col['name'] for col in inspector.get_columns('readings')]

            # Add missing columns if they don't exist
            required_columns = {
                'cost': 'FLOAT DEFAULT 0',
                'is_reviewed': 'BOOLEAN DEFAULT 0',
                'reviewed_by': 'INTEGER',
                'reviewed_at': 'DATETIME',
                'review_notes': 'TEXT',
                'is_approved': 'BOOLEAN DEFAULT 0',
                'approved_by': 'INTEGER',
                'approved_at': 'DATETIME'
            }

            for col_name, col_type in required_columns.items():
                if col_name not in columns:
                    print(f" Adding missing '{col_name}' column to readings table...")
                    with db.engine.connect() as conn:
                        conn.execute(db.text(f"ALTER TABLE readings ADD COLUMN {col_name} {col_type}"))
                        conn.commit()
                    print(f" '{col_name}' column added successfully!")

        # Check if consumption_reviews table exists
        if 'consumption_reviews' not in inspector.get_table_names():
            print(" Creating consumption_reviews table...")
            # Table will be created by SQLAlchemy when we run db.create_all()

        # Check if customer_submissions table exists
        if 'customer_submissions' not in inspector.get_table_names():
            print(" Creating customer_submissions table...")
            # Table will be created by SQLAlchemy when we run db.create_all()

        if 'user_settings' in inspector.get_table_names():
            settings_columns = [col['name'] for col in inspector.get_columns('user_settings')]
            settings_required = {
                'allow_overage': 'BOOLEAN DEFAULT 0',
                'auto_shutdown_enabled': 'BOOLEAN DEFAULT 1',
                'shutdown_delay_minutes': 'INTEGER DEFAULT 5',
                'last_threshold_alert_at': 'DATETIME',
                'scheduled_shutdown_at': 'DATETIME'
            }
            for col_name, col_type in settings_required.items():
                if col_name not in settings_columns:
                    with db.engine.connect() as conn:
                        conn.execute(db.text(f"ALTER TABLE user_settings ADD COLUMN {col_name} {col_type}"))
                        conn.commit()

    except Exception as e:
        print(f"Note: Schema check - {e}")


if __name__ == '__main__':
    with app.app_context():
        # Create tables if they don't exist
        db.create_all()
        print(" Database tables created/verified")

        # Update schema if needed
        update_database_schema()

        admin, admin_password, _ = ensure_test_user('admin', 'admin.demo@ecopulse.local', 'Administration')
        examiner, examiner_password, _ = ensure_test_user('examiner', 'examiner.demo@ecopulse.local', 'Audit')
        customer, customer_password, customer_settings = ensure_test_user('customer', 'customer.demo@ecopulse.local')

        customer.threshold = customer.threshold or 600
        customer_settings.alert_threshold = customer.threshold
        for existing_customer in User.query.filter_by(role='customer').all():
            ensure_customer_meter_number(existing_customer)
            existing_customer.unit_cost = get_active_unit_cost()
        db.session.commit()

        if not Reading.query.filter_by(user_id=customer.id).first():
            now_utc = utc_now()
            sample_readings = [
                ('January 2025', 450, now_utc - timedelta(days=420), True, True),
                ('April 2025', 520, now_utc - timedelta(days=330), True, True),
                ('July 2025', 480, now_utc - timedelta(days=240), True, False),
                ('October 2025', 610, now_utc - timedelta(days=150), False, False),
                ('January 2026', 550, now_utc - timedelta(days=60), False, False),
                ('March 2026', 580, now_utc, False, False),
            ]
            for label, kwh, ts, reviewed, approved in sample_readings:
                cost, _ = calculate_reading_cost(customer, customer_settings, kwh)
                db.session.add(Reading(
                    user_id=customer.id,
                    date=label,
                    kwh=kwh,
                    cost=cost,
                    timestamp=ts,
                    is_reviewed=reviewed,
                    is_approved=approved
                ))
            db.session.commit()
            print(" Sample customer readings created")

        # Create sample financial records if none exist
        if not FinancialRecord.query.first():
            customers = User.query.filter_by(role='customer').all()
            for customer in customers:
                readings = Reading.query.filter_by(user_id=customer.id).all()
                if readings:
                    total_kwh = sum(r.kwh for r in readings)
                    total_cost = sum(r.kwh * customer.unit_cost for r in readings)

                    record = FinancialRecord(
                        user_id=customer.id,
                        period=datetime.utcnow().strftime('%Y-%m'),
                        total_consumption=total_kwh,
                        total_cost=total_cost,
                        total_paid=total_cost * 0.9,
                        balance=total_cost * 0.4,
                        due_date=datetime.utcnow() + timedelta(days=15),
                        payment_status='pending'
                    )
                    db.session.add(record)
            db.session.commit()
            print(" Sample financial records created")

        admin_username = admin.username
        examiner_username = examiner.username
        customer_username = customer.username
        customer_meter_number = customer.meter_number

    print("\n" + "=" * 70)
    print(" EcoPulse Energy Dashboard with Customer Submissions")
    print("=" * 70)
    print("\n New Features:")
    print("   • Customers can submit their consumption summary to admin")
    print("   • Admin can approve/review/reject customer submissions")
    print("   • Examiner can send reports regardless of review status")
    print("   • Complete workflow from customer to admin")
    print("\n Workflow:")
    print("   1. Customer adds readings")
    print("   2. Customer can submit summary to admin for verification")
    print("   3. Examiner reviews readings and sends reports to admin")
    print("   4. Admin approves/reviews/rejects submissions")
    print("   5. Admin sends approved summaries to customers")
    print("\n Test Logins:")
    print(f"   Staff login route: /staff/login")
    print(f"   Admin:    username: {admin_username},    password: {admin_password}")
    print(f"   Examiner: username: {examiner_username}, password: {examiner_password}")
    print(f"   Customer: username: {customer_username}, meter: {customer_meter_number}, password: {customer_password}")
    print("\n Access the application at: http://localhost:5000")
    print("\n" + "=" * 70 + "\n")

    app.run(debug=True, host='0.0.0.0', port=5000)
