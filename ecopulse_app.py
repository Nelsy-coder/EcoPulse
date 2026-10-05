from flask import Flask, render_template, render_template_string, request, send_file, redirect, url_for, session, jsonify, flash, abort, Response, stream_with_context
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from functools import wraps
import matplotlib
import secrets
import string
import random
import hashlib
import os
import csv
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

# Configure matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from datetime import UTC, datetime, timedelta, timezone
import io
import base64
import heapq
import math
import json
from collections import deque
import time
import threading
import uuid
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

app = Flask(__name__, instance_path=os.path.abspath(os.path.join(os.path.dirname(__file__), 'instance')))
app.config['SECRET_KEY'] = 'your-secret-key-change-this-in-production'

# Use Flask instance folder for database (recommended approach)
# This avoids Windows path issues and follows Flask best practices
os.makedirs(app.instance_path, exist_ok=True)
db_file = os.path.join(app.instance_path, 'ecopulse.db').replace('\\', '/')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + db_file
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = os.path.join(app.instance_path, 'uploads')
app.config['JOB_APPLICATION_UPLOAD_FOLDER'] = os.path.join(app.config['UPLOAD_FOLDER'], 'job_applications')
os.makedirs(app.config['JOB_APPLICATION_UPLOAD_FOLDER'], exist_ok=True)
app.config['MAX_CONTENT_LENGTH'] = 2 * 1024 * 1024  # 2 MB upload limit for career application attachments
app.config['JOB_APPLICATION_ALLOWED_EXTENSIONS'] = {'pdf', 'doc', 'docx'}
# SQLite connection settings for Windows reliability
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'connect_args': {
        'timeout': 30,  # Wait up to 30 seconds if database is locked
        'check_same_thread': False,  # Allow multi-threaded access
    },
    'pool_pre_ping': True,  # Test connection before using
    'pool_recycle': 3600,  # Recycle connections every hour
}
PASSWORD_RESET_TOKENS = {}

try:
    APP_TIMEZONE = ZoneInfo('Africa/Nairobi')
except ZoneInfoNotFoundError:
    # Fallback for environments without IANA timezone data (common on Windows).
    APP_TIMEZONE = timezone(timedelta(hours=3), name='Africa/Nairobi')
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
LIVE_NOTIFICATION_QUEUE_SIZE = 60
LIVE_NOTIFICATIONS = {}
LIVE_NOTIFICATIONS_LOCK = threading.Lock()
ENERGY_SOURCES = ('KPLC',)  # Only KPLC for now, Solar Grid removed
ENERGY_SOURCE_LABELS = {
    'KPLC': 'KPLC Grid'
}
LANGUAGE_OPTIONS = [
    ('en', 'English'),
    ('sw', 'Swahili')
]
LANGUAGE_LABELS = {
    'en': 'English',
    'sw': 'Swahili'
}
# Hidden staff entrypoint for admin/examiner access
STAFF_LOGIN_ROUTE = '/ops/portal/login-2026'
STAFF_ROLES = ('admin', 'examiner', 'hr_manager', 'subadmin')
ASSIGNABLE_ROLES = STAFF_ROLES + ('customer',)

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

def allowed_application_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['JOB_APPLICATION_ALLOWED_EXTENSIONS']

@app.errorhandler(RequestEntityTooLarge)
def handle_request_entity_too_large(error):
    hr_manager = get_assigned_hr_manager()
    return render_template_string(careers_page_template,
                                  PUBLIC_CAREERS=PUBLIC_CAREERS,
                                  hr_manager=hr_manager,
                                  department_roles=get_department_roles(),
                                  departments=Department.query.all(),
                                  application_success=None,
                                  application_error='Uploaded file must be 2 MB or smaller.'), 413


# ===================== DATABASE MODELS =====================

class User(UserMixin, db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(120), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='customer')
    employee_id = db.Column(db.String(20), unique=True, nullable=True)
    id_number = db.Column(db.String(50), nullable=True)
    full_name = db.Column(db.String(200), nullable=True)
    department = db.Column(db.String(50), nullable=True)
    department_id = db.Column(db.Integer, db.ForeignKey('departments.id'), nullable=True)
    status = db.Column(db.String(20), nullable=False, default='active')
    salary = db.Column(db.Float, default=0.0)
    is_department_head = db.Column(db.Boolean, default=False)
    threshold = db.Column(db.Float, default=600)
    currency = db.Column(db.String(10), default='Ksh')
    unit_cost = db.Column(db.Float, default=0.12)
    alert_email = db.Column(db.Boolean, default=True)
    energy_source = db.Column(db.String(20), nullable=False, default='KPLC')
    language = db.Column(db.String(10), nullable=False, default='en')
    user_type = db.Column(db.String(20), nullable=False, default='smart_home')  # 'smart_home' or 'business'
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

    subscriptions = db.relationship('Subscription',
                                    foreign_keys='Subscription.user_id',
                                    back_populates='user',
                                    lazy=True,
                                    cascade='all, delete-orphan')

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

    department_obj = db.relationship('Department', foreign_keys=[department_id], back_populates='members')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def generate_employee_id(self):
        prefix_map = {
            'admin': 'ADM',
            'examiner': 'EXM',
            'hr_manager': 'HRM',
            'subadmin': 'SUB'
        }
        prefix = prefix_map.get(self.role, 'STF')
        random_digits = ''.join(secrets.choice(string.digits) for _ in range(6))
        return f"{prefix}{random_digits}"


class Department(db.Model):
    __tablename__ = 'departments'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    description = db.Column(db.Text, nullable=True)
    head_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    head = db.relationship('User', foreign_keys=[head_id], backref='headed_departments')
    members = db.relationship('User', foreign_keys='User.department_id', back_populates='department_obj')


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


class FeatureToggle(db.Model):
    __tablename__ = 'feature_toggles'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    enabled = db.Column(db.Boolean, default=True)
    description = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


def get_ticketing_toggle():
    toggle = FeatureToggle.query.filter_by(name='customer_ticketing').first()
    if toggle is None:
        toggle = FeatureToggle(
            name='customer_ticketing',
            enabled=True,
            description='Allow customers to submit support tickets'
        )
        db.session.add(toggle)
        db.session.commit()
    return toggle


def is_ticketing_enabled():
    return bool(get_ticketing_toggle().enabled)


class ExaminerFeedback(db.Model):
    __tablename__ = 'examiner_feedback'

    id = db.Column(db.Integer, primary_key=True)
    examiner_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    customer_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    rating = db.Column(db.Integer, default=0)
    comments = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    examiner = db.relationship('User', foreign_keys=[examiner_id], backref='feedbacks_given')
    customer = db.relationship('User', foreign_keys=[customer_id], backref='feedbacks_received')


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


class TariffApproval(db.Model):
    __tablename__ = 'tariff_approvals'

    id = db.Column(db.Integer, primary_key=True)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    energy_source = db.Column(db.String(20), nullable=False, default='KPLC')
    proposed_cost = db.Column(db.Float, nullable=False, default=0.0)
    status = db.Column(db.String(20), nullable=False, default='pending')
    review_note = db.Column(db.Text, nullable=True)
    reviewed_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    reviewed_at = db.Column(db.DateTime, nullable=True)

    creator = db.relationship('User', foreign_keys=[created_by], backref='tariff_approvals_created')
    reviewer = db.relationship('User', foreign_keys=[reviewed_by], backref='tariff_approvals_reviewed')


class EmployeeLeaveRequest(db.Model):
    __tablename__ = 'employee_leave_requests'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    employee_name = db.Column(db.String(120), nullable=False)
    start_date = db.Column(db.String(20), nullable=False)
    end_date = db.Column(db.String(20), nullable=False)
    reason = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), nullable=False, default='pending')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    reviewed_at = db.Column(db.DateTime, nullable=True)
    reviewed_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    user = db.relationship('User', foreign_keys=[user_id], backref='leave_requests')
    reviewer = db.relationship('User', foreign_keys=[reviewed_by], backref='leave_requests_reviewed')


class EmployeeTrainingRecord(db.Model):
    __tablename__ = 'employee_training_records'

    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    provider = db.Column(db.String(200), nullable=True)
    completed_on = db.Column(db.String(20), nullable=True)
    status = db.Column(db.String(20), nullable=False, default='scheduled')
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    employee = db.relationship('User', foreign_keys=[employee_id], backref='training_records')


class EmployeePerformanceReview(db.Model):
    __tablename__ = 'employee_performance_reviews'

    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    review_period = db.Column(db.String(50), nullable=False)
    score = db.Column(db.Float, nullable=False, default=0.0)
    summary = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), nullable=False, default='draft')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    employee = db.relationship('User', foreign_keys=[employee_id], backref='performance_reviews')


class SupportTicket(db.Model):
    __tablename__ = 'support_tickets'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    name = db.Column(db.String(120), nullable=True)
    email = db.Column(db.String(120), nullable=True)
    subject = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text, nullable=True)
    description = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(50), nullable=False, default='open')
    priority = db.Column(db.String(20), default='medium')
    assignee_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    resolved_at = db.Column(db.DateTime, nullable=True)

    user = db.relationship('User', foreign_keys=[user_id], backref=db.backref('support_tickets', lazy=True))
    assignee = db.relationship('User', foreign_keys=[assignee_id], backref=db.backref('assigned_tickets', lazy=True))


class PartnershipRequest(db.Model):
    __tablename__ = 'partnership_requests'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), nullable=False)
    organization = db.Column(db.String(200), nullable=True)
    need = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


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


class Subscription(db.Model):
    __tablename__ = 'subscriptions'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    plan = db.Column(db.String(100), nullable=False)
    monthly_fee = db.Column(db.Float, default=0.0)
    status = db.Column(db.String(30), default='active')
    started_at = db.Column(db.DateTime, default=datetime.utcnow)
    next_billing_date = db.Column(db.DateTime, nullable=True)
    last_payment_at = db.Column(db.DateTime, nullable=True)
    payment_method = db.Column(db.String(50), nullable=True)

    user = db.relationship('User', foreign_keys=[user_id], back_populates='subscriptions')


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


class JobApplication(db.Model):
    __tablename__ = 'job_applications'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(255), nullable=False)
    position = db.Column(db.String(120), nullable=False)
    department_interest = db.Column(db.String(120), nullable=True)
    cover_letter = db.Column(db.Text, nullable=False)
    resume_filename = db.Column(db.String(255), nullable=True)
    resume_path = db.Column(db.String(500), nullable=True)
    assigned_hr_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    status = db.Column(db.String(50), default='new')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    assigned_hr = db.relationship('User', foreign_keys=[assigned_hr_id])


class Notification(db.Model):
    __tablename__ = 'notifications'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text, nullable=False)
    notification_type = db.Column(db.String(50), default='info')  # info, warning, success, danger
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    sent_via_sms = db.Column(db.Boolean, default=False)
    sent_via_email = db.Column(db.Boolean, default=False)

    # Relationship
    user = db.relationship('User', backref=db.backref('notifications', lazy=True))


class Message(db.Model):
    __tablename__ = 'messages'

    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    recipient_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    subject = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=False)
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    message_type = db.Column(db.String(50), default='direct')  # direct, system, broadcast

    # Relationships
    sender = db.relationship('User', foreign_keys=[sender_id], backref='sent_messages')
    recipient = db.relationship('User', foreign_keys=[recipient_id], backref='received_messages')

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

# ===================== GAMIFICATION MODELS =====================

class EcoPoints(db.Model):
    __tablename__ = 'eco_points'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, unique=True)
    points = db.Column(db.Integer, default=0)
    level = db.Column(db.Integer, default=1)
    streak_days = db.Column(db.Integer, default=0)
    last_activity_date = db.Column(db.DateTime, nullable=True)
    total_savings_kwh = db.Column(db.Float, default=0)
    total_savings_co2 = db.Column(db.Float, default=0)
    badges = db.Column(db.Text, default='[]')  # JSON array of badges
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = db.relationship('User', backref=db.backref('eco_points', uselist=False, lazy=True))

class Badge(db.Model):
    __tablename__ = 'badges'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.String(255), nullable=False)
    icon = db.Column(db.String(50), default='bi-trophy')
    points_required = db.Column(db.Integer, default=0)
    condition_type = db.Column(db.String(50))  # 'savings', 'streak', 'reading_count', 'threshold'
    condition_value = db.Column(db.Float, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Leaderboard(db.Model):
    __tablename__ = 'leaderboard'

    id = db.Column(db.Integer, primary_key=True)
    period = db.Column(db.String(20), default='monthly')  # 'weekly', 'monthly', 'all_time'
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    points = db.Column(db.Integer, default=0)
    rank = db.Column(db.Integer, default=0)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = db.relationship('User', backref=db.backref('leaderboard_entries', lazy=True))

class EnergyTip(db.Model):
    __tablename__ = 'energy_tips'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=False)
    category = db.Column(db.String(50), default='general')
    savings_estimate = db.Column(db.Float, default=0)  # estimated kWh savings
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class CommunityPost(db.Model):
    __tablename__ = 'community_posts'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=False)
    post_type = db.Column(db.String(50), default='success_story')  # 'success_story', 'tip', 'question'
    likes = db.Column(db.Integer, default=0)
    shares = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref=db.backref('community_posts', lazy=True))

class PostLike(db.Model):
    __tablename__ = 'post_likes'

    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey('community_posts.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class UsageForecast(db.Model):
    __tablename__ = 'usage_forecasts'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    forecast_date = db.Column(db.Date, nullable=False)
    predicted_usage = db.Column(db.Float, nullable=False)
    confidence_level = db.Column(db.Float, default=75)
    risk_alert = db.Column(db.Boolean, default=False)
    risk_type = db.Column(db.String(50), nullable=True)  # 'high_spike', 'anomaly', 'threshold_breach'
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref=db.backref('forecasts', lazy=True))


class IoTData(db.Model):
    __tablename__ = 'iot_data'

    id = db.Column(db.Integer, primary_key=True)
    device_id = db.Column(db.Integer, db.ForeignKey('customer_devices.id'), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    value = db.Column(db.Float, nullable=False)
    unit = db.Column(db.String(10), default='kWh')
    device = db.relationship('CustomerDevice', backref=db.backref('iot_readings', lazy=True))


class PaymentTransaction(db.Model):
    __tablename__ = 'payment_transactions'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    currency = db.Column(db.String(10), default='Ksh')
    payment_method = db.Column(db.String(50), nullable=False)  # 'mpesa', 'card', 'bank_transfer'
    transaction_id = db.Column(db.String(100), unique=True, nullable=False)
    status = db.Column(db.String(20), default='pending')  # 'pending', 'completed', 'failed'
    subscription_tier = db.Column(db.String(50), default='free')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref=db.backref('transactions', lazy=True))


class UserBadgeEarned(db.Model):
    __tablename__ = 'user_badges_earned'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    badge_id = db.Column(db.Integer, db.ForeignKey('badges.id'), nullable=False)
    earned_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref=db.backref('badges_earned', lazy=True))
    badge = db.relationship('Badge')


class ChoreSchedule(db.Model):
    __tablename__ = 'chore_schedules'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    chore_name = db.Column(db.String(100), nullable=False)
    scheduled_time = db.Column(db.Time, nullable=False)
    days_of_week = db.Column(db.String(20), nullable=False)  # e.g., '1,2,3,4,5' for Mon-Fri
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref=db.backref('chore_schedules', lazy=True))


class LoginLog(db.Model):
    __tablename__ = 'login_logs'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    login_time = db.Column(db.DateTime, default=datetime.utcnow)
    ip_address = db.Column(db.String(45), nullable=False)
    user_agent = db.Column(db.Text)
    success = db.Column(db.Boolean, default=True)
    role = db.Column(db.String(20), nullable=False)

    user = db.relationship('User', backref=db.backref('login_logs', lazy=True))


class SuccessStory(db.Model):
    __tablename__ = 'success_stories'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    story = db.Column(db.Text, nullable=False)
    savings_amount = db.Column(db.Float, nullable=False)
    carbon_reduction = db.Column(db.Float, nullable=False)
    is_approved = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref=db.backref('success_stories', lazy=True))


# New models for additional features

class EnergyGoal(db.Model):
    __tablename__ = 'energy_goals'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    goal_type = db.Column(db.String(50), default='monthly_savings')  # 'monthly_savings', 'annual_reduction'
    target_value = db.Column(db.Float, nullable=False)  # kWh or percentage
    current_value = db.Column(db.Float, default=0)
    start_date = db.Column(db.DateTime, default=datetime.utcnow)
    end_date = db.Column(db.DateTime, nullable=False)
    status = db.Column(db.String(20), default='active')  # 'active', 'completed', 'failed'
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref=db.backref('energy_goals', lazy=True))


class ForumPost(db.Model):
    __tablename__ = 'forum_posts'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=False)
    category = db.Column(db.String(50), default='general')  # 'tips', 'questions', 'experiences'
    likes = db.Column(db.Integer, default=0)
    replies_count = db.Column(db.Integer, default=0)
    is_pinned = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref=db.backref('forum_posts', lazy=True))


class ForumReply(db.Model):
    __tablename__ = 'forum_replies'

    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey('forum_posts.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    content = db.Column(db.Text, nullable=False)
    likes = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    post = db.relationship('ForumPost', backref=db.backref('replies', lazy=True))
    user = db.relationship('User', backref=db.backref('forum_replies', lazy=True))


class Rubric(db.Model):
    __tablename__ = 'rubrics'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    criteria = db.Column(db.Text)  # JSON string of criteria
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    creator = db.relationship('User', backref=db.backref('rubrics', lazy=True))


class CommentTemplate(db.Model):
    __tablename__ = 'comment_templates'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    content = db.Column(db.Text, nullable=False)
    category = db.Column(db.String(50), default='general')
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    creator = db.relationship('User', backref=db.backref('comment_templates', lazy=True))


class PerformanceAnalytics(db.Model):
    __tablename__ = 'performance_analytics'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    period = db.Column(db.String(20), default='monthly')
    metric_type = db.Column(db.String(50), nullable=False)  # 'savings', 'efficiency', 'consistency'
    value = db.Column(db.Float, nullable=False)
    improvement_rate = db.Column(db.Float, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref=db.backref('performance_analytics', lazy=True))


class SubAdminRole(db.Model):
    __tablename__ = 'sub_admin_roles'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    role_name = db.Column(db.String(50), nullable=False)  # 'moderator', 'support_admin', etc.
    permissions = db.Column(db.Text)  # JSON string of permissions
    assigned_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', foreign_keys=[user_id], backref=db.backref('sub_admin_roles', lazy=True))
    assigner = db.relationship('User', foreign_keys=[assigned_by], backref=db.backref('assigned_roles', lazy=True))


class SystemHealth(db.Model):
    __tablename__ = 'system_health'

    id = db.Column(db.Integer, primary_key=True)
    component = db.Column(db.String(50), nullable=False)  # 'database', 'server', 'api'
    status = db.Column(db.String(20), default='healthy')  # 'healthy', 'warning', 'critical'
    metrics = db.Column(db.Text)  # JSON string of metrics
    last_checked = db.Column(db.DateTime, default=datetime.utcnow)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class BackupSchedule(db.Model):
    __tablename__ = 'backup_schedules'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    frequency = db.Column(db.String(20), default='daily')  # 'hourly', 'daily', 'weekly'
    backup_type = db.Column(db.String(20), default='full')  # 'full', 'incremental'
    retention_days = db.Column(db.Integer, default=30)
    is_active = db.Column(db.Boolean, default=True)
    last_run = db.Column(db.DateTime)
    next_run = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class FeatureRollout(db.Model):
    __tablename__ = 'feature_rollouts'

    id = db.Column(db.Integer, primary_key=True)
    feature_name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    rollout_percentage = db.Column(db.Float, default=0)  # 0-100
    target_users = db.Column(db.Text)  # JSON string of user criteria
    is_active = db.Column(db.Boolean, default=False)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    creator = db.relationship('User', backref=db.backref('feature_rollouts', lazy=True))


class ImpactCounter(db.Model):
    __tablename__ = 'impact_counters'

    id = db.Column(db.Integer, primary_key=True)
    metric_name = db.Column(db.String(50), nullable=False)  # 'total_energy_saved', 'users_onboarded', 'carbon_reduced'
    value = db.Column(db.BigInteger, default=0)
    last_updated = db.Column(db.DateTime, default=datetime.utcnow)
    update_frequency = db.Column(db.String(20), default='realtime')  # 'realtime', 'hourly', 'daily'


class SustainabilityImpact(db.Model):
    __tablename__ = 'sustainability_impacts'

    id = db.Column(db.Integer, primary_key=True)
    co2_saved_kg = db.Column(db.Float, default=0.0)
    renewable_kwh = db.Column(db.Float, default=0.0)
    community_projects = db.Column(db.Integer, default=0)
    source = db.Column(db.String(100), nullable=True)  # 'device', 'partner', 'manual'
    attribution = db.Column(db.Text, nullable=True)  # JSON with metadata
    last_updated = db.Column(db.DateTime, default=datetime.utcnow)


class AuditLog(db.Model):
    __tablename__ = 'audit_logs'

    id = db.Column(db.Integer, primary_key=True)
    actor_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    action = db.Column(db.String(200), nullable=False)
    entity_type = db.Column(db.String(100), nullable=True)
    entity_id = db.Column(db.String(100), nullable=True)
    changes = db.Column(db.Text, nullable=True)  # JSON diff or description
    ip_address = db.Column(db.String(50), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    actor = db.relationship('User', foreign_keys=[actor_id], backref=db.backref('audit_logs', lazy=True))


# ===================== NEW FEATURES MODELS =====================

class Branch(db.Model):
    """Multi-branch support for business customers"""
    __tablename__ = 'branches'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    location = db.Column(db.String(200), nullable=False)
    address = db.Column(db.Text, nullable=True)
    phone = db.Column(db.String(20), nullable=True)
    manager_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    total_devices = db.Column(db.Integer, default=0)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    business_owner = db.relationship('User', foreign_keys=[user_id], backref=db.backref('branches', lazy=True))
    manager = db.relationship('User', foreign_keys=[manager_id])


class CostCalculation(db.Model):
    """Track electricity cost calculations"""
    __tablename__ = 'cost_calculations'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    reading_id = db.Column(db.Integer, db.ForeignKey('readings.id'), nullable=True)
    kwh = db.Column(db.Float, nullable=False)
    unit_cost = db.Column(db.Float, nullable=False)
    total_cost = db.Column(db.Float, nullable=False)
    currency = db.Column(db.String(10), default='Ksh')
    period = db.Column(db.String(20), nullable=False)  # 'daily', 'weekly', 'monthly'
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref=db.backref('cost_calculations', lazy=True))
    reading = db.relationship('Reading', foreign_keys=[reading_id])


class EnergyAnalytics(db.Model):
    """Energy usage analytics and insights"""
    __tablename__ = 'energy_analytics'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'), nullable=True)
    period_start = db.Column(db.DateTime, nullable=False)
    period_end = db.Column(db.DateTime, nullable=False)
    total_usage = db.Column(db.Float, default=0)
    average_daily_usage = db.Column(db.Float, default=0)
    peak_usage = db.Column(db.Float, default=0)
    lowest_usage = db.Column(db.Float, default=0)
    highest_consuming_device = db.Column(db.String(120), nullable=True)
    lowest_consuming_device = db.Column(db.String(120), nullable=True)
    trend = db.Column(db.String(50), default='stable')  # 'increasing', 'decreasing', 'stable'
    comparison_previous_period = db.Column(db.Float, default=0)  # percentage change
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref=db.backref('energy_analytics', lazy=True))
    branch = db.relationship('Branch', backref=db.backref('energy_analytics', lazy=True))


class EnergyRecommendation(db.Model):
    """Energy saving recommendations"""
    __tablename__ = 'energy_recommendations'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    device_id = db.Column(db.Integer, db.ForeignKey('customer_devices.id'), nullable=True)
    recommendation_type = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=False)
    estimated_savings = db.Column(db.Float, default=0)  # in kWh
    priority = db.Column(db.String(20), default='medium')  # 'low', 'medium', 'high'
    is_read = db.Column(db.Boolean, default=False)
    is_acted_upon = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref=db.backref('energy_recommendations', lazy=True))
    device = db.relationship('CustomerDevice', backref=db.backref('recommendations', lazy=True))


class ReportGeneration(db.Model):
    """Track generated reports"""
    __tablename__ = 'report_generations'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'), nullable=True)
    report_type = db.Column(db.String(50), nullable=False)  # 'daily', 'weekly', 'monthly'
    period_start = db.Column(db.DateTime, nullable=False)
    period_end = db.Column(db.DateTime, nullable=False)
    total_energy = db.Column(db.Float, default=0)
    total_cost = db.Column(db.Float, default=0)
    file_path = db.Column(db.String(500), nullable=True)
    format = db.Column(db.String(20), default='pdf')  # 'pdf', 'csv', 'excel'
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref=db.backref('report_generations', lazy=True))
    branch = db.relationship('Branch', backref=db.backref('report_generations', lazy=True))


class AlertHistory(db.Model):
    """Alert tracking and history"""
    __tablename__ = 'alert_history'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    device_id = db.Column(db.Integer, db.ForeignKey('customer_devices.id'), nullable=True)
    alert_type = db.Column(db.String(50), nullable=False)  # 'high_usage', 'threshold_breach', 'device_offline'
    message = db.Column(db.Text, nullable=False)
    severity = db.Column(db.String(20), default='medium')  # 'low', 'medium', 'high', 'critical'
    is_acknowledged = db.Column(db.Boolean, default=False)
    acknowledged_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref=db.backref('alert_history', lazy=True))
    device = db.relationship('CustomerDevice', backref=db.backref('alerts', lazy=True))


class DeviceStatus(db.Model):
    """Real-time device status tracking"""
    __tablename__ = 'device_status'

    id = db.Column(db.Integer, primary_key=True)
    device_id = db.Column(db.Integer, db.ForeignKey('customer_devices.id'), nullable=False, unique=True)
    is_online = db.Column(db.Boolean, default=True)
    current_power = db.Column(db.Float, default=0)  # in watts
    last_reading = db.Column(db.DateTime, nullable=True)
    status = db.Column(db.String(50), default='idle')  # 'idle', 'running', 'offline', 'error'
    last_activity = db.Column(db.DateTime, nullable=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    device = db.relationship('CustomerDevice', foreign_keys=[device_id], backref=db.backref('current_status', uselist=False, lazy=True))


class BranchEnergyUsage(db.Model):
    """Branch-level energy usage summary"""
    __tablename__ = 'branch_energy_usage'

    id = db.Column(db.Integer, primary_key=True)
    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'), nullable=False)
    date = db.Column(db.Date, nullable=False)
    total_usage = db.Column(db.Float, default=0)
    total_cost = db.Column(db.Float, default=0)
    device_count = db.Column(db.Integer, default=0)
    average_device_usage = db.Column(db.Float, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    branch = db.relationship('Branch', backref=db.backref('daily_usage', lazy=True))


class UserBranchAccess(db.Model):
    """Track user access to branches"""
    __tablename__ = 'user_branch_access'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'), nullable=False)
    access_level = db.Column(db.String(50), default='viewer')  # 'viewer', 'editor', 'admin'
    granted_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref=db.backref('branch_access', lazy=True))
    branch = db.relationship('Branch', backref=db.backref('user_access', lazy=True))


class HRPolicy(db.Model):
    __tablename__ = 'hr_policies'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    creator = db.relationship('User', foreign_keys=[created_by], backref=db.backref('hr_policies', lazy=True))


class PayrollRecord(db.Model):
    __tablename__ = 'payroll_records'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    period = db.Column(db.String(32), nullable=False)
    gross_salary = db.Column(db.Float, default=0.0)
    deductions = db.Column(db.Float, default=0.0)
    net_salary = db.Column(db.Float, default=0.0)
    status = db.Column(db.String(20), default='pending')  # pending, approved, processed
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    approved_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    employee = db.relationship('User', foreign_keys=[user_id], backref=db.backref('payroll_records', lazy=True))
    creator = db.relationship('User', foreign_keys=[created_by])
    approver = db.relationship('User', foreign_keys=[approved_by])


class AttendanceRecord(db.Model):
    __tablename__ = 'attendance_records'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    date = db.Column(db.Date, nullable=False)
    hours_worked = db.Column(db.Float, default=0.0)
    overtime_hours = db.Column(db.Float, default=0.0)
    cost = db.Column(db.Float, default=0.0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', foreign_keys=[user_id], backref=db.backref('attendance_records', lazy=True))


class HRExpense(db.Model):
    __tablename__ = 'hr_expenses'

    id = db.Column(db.Integer, primary_key=True)
    category = db.Column(db.String(50), nullable=False)
    amount = db.Column(db.Float, default=0.0)
    notes = db.Column(db.Text, nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    creator = db.relationship('User', foreign_keys=[created_by])


class HRPermission(db.Model):
    __tablename__ = 'hr_permissions'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, unique=True)
    can_view_payroll = db.Column(db.Boolean, default=False)
    can_edit_training_records = db.Column(db.Boolean, default=False)
    can_view_recruitment_costs = db.Column(db.Boolean, default=False)
    can_manage_attendance = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = db.relationship('User', foreign_keys=[user_id], backref=db.backref('hr_permission', uselist=False))


class Partner(db.Model):
    __tablename__ = 'partners'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    contact_email = db.Column(db.String(200), nullable=True)
    api_key = db.Column(db.String(200), unique=True, nullable=False)
    sandbox = db.Column(db.Boolean, default=True)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class NotificationPreference(db.Model):
    __tablename__ = 'notification_preferences'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, unique=True)
    email = db.Column(db.Boolean, default=True)
    sms = db.Column(db.Boolean, default=False)
    in_app = db.Column(db.Boolean, default=True)
    webhook = db.Column(db.Boolean, default=False)
    channels = db.Column(db.Text, nullable=True)  # JSON for advanced rules
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = db.relationship('User', foreign_keys=[user_id], backref=db.backref('notification_preferences', uselist=False, lazy=True))


class TariffReview(db.Model):
    __tablename__ = 'tariff_reviews'

    id = db.Column(db.Integer, primary_key=True)
    report_id = db.Column(db.Integer, db.ForeignKey('reports.id'), nullable=False)
    submitted_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(50), default='draft')  # draft, under_review, approved, rejected
    examiner_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    reviewed_at = db.Column(db.DateTime, nullable=True)
    notes = db.Column(db.Text, nullable=True)

    report = db.relationship('Report', foreign_keys=[report_id], backref=db.backref('tariff_reviews', lazy=True))
    submitter = db.relationship('User', foreign_keys=[submitted_by], backref=db.backref('submitted_tariff_reviews', lazy=True))
    examiner = db.relationship('User', foreign_keys=[examiner_id], backref=db.backref('examined_tariff_reviews', lazy=True))


# ===================== IOT DEVICE REGISTRATION & ADMIN USER MANAGEMENT =====================

class IoTDeviceRegistration(db.Model):
    """IoT Device Registration with API Keys and Device Authentication"""
    __tablename__ = 'iot_device_registrations'

    id = db.Column(db.Integer, primary_key=True)
    device_id = db.Column(db.Integer, db.ForeignKey('customer_devices.id'), nullable=False, unique=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    
    # Device Identification
    mac_address = db.Column(db.String(100), unique=True, nullable=True)
    serial_number = db.Column(db.String(100), unique=True, nullable=True)
    device_type = db.Column(db.String(50), nullable=True)  # 'smart_meter', 'smart_plug', 'solar_panel', etc.
    manufacturer = db.Column(db.String(100), nullable=True)
    model = db.Column(db.String(100), nullable=True)
    
    # API Key & Authentication
    api_key = db.Column(db.String(255), unique=True, nullable=False)
    api_secret = db.Column(db.String(255), nullable=False)
    is_authenticated = db.Column(db.Boolean, default=False)
    authentication_timestamp = db.Column(db.DateTime, nullable=True)
    
    # Device Status & Configuration
    status = db.Column(db.String(50), default='pending')  # 'pending', 'registered', 'active', 'inactive', 'decommissioned'
    is_approved_by_admin = db.Column(db.Boolean, default=False)
    approved_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    approved_at = db.Column(db.DateTime, nullable=True)
    
    # Data Collection Settings
    data_collection_enabled = db.Column(db.Boolean, default=True)
    collection_interval = db.Column(db.Integer, default=60)  # in seconds
    last_data_received = db.Column(db.DateTime, nullable=True)
    
    # Firmware & Updates
    firmware_version = db.Column(db.String(50), nullable=True)
    last_update_check = db.Column(db.DateTime, nullable=True)
    last_firmware_update = db.Column(db.DateTime, nullable=True)
    
    # Multi-Location Support (for Business Owners)
    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'), nullable=True)
    location_name = db.Column(db.String(200), nullable=True)
    
    # Audit Trail
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    # Relationships
    device = db.relationship('CustomerDevice', foreign_keys=[device_id], backref=db.backref('iot_registration', uselist=False, lazy=True))
    user = db.relationship('User', foreign_keys=[user_id], backref=db.backref('iot_devices', lazy=True))
    admin = db.relationship('User', foreign_keys=[approved_by], backref=db.backref('approved_devices', lazy=True))
    branch = db.relationship('Branch', foreign_keys=[branch_id], backref=db.backref('iot_devices', lazy=True))
    creator = db.relationship('User', foreign_keys=[created_by])

    def generate_api_key(self):
        """Generate a secure API key for device authentication"""
        import secrets
        return secrets.token_urlsafe(32)

    def generate_api_secret(self):
        """Generate a secure API secret"""
        import secrets
        return secrets.token_urlsafe(32)


class UserRegistrationRequest(db.Model):
    """Admin-Controlled User Registration with Approval Workflow"""
    __tablename__ = 'user_registration_requests'

    id = db.Column(db.Integer, primary_key=True)
    
    # User Information
    username = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(20), nullable=True)
    id_number = db.Column(db.String(50), nullable=True)
    full_name = db.Column(db.String(200), nullable=True)
    first_name = db.Column(db.String(100), nullable=True)
    last_name = db.Column(db.String(100), nullable=True)
    
    # User Type & Role
    user_type = db.Column(db.String(50), nullable=False)  # 'home_owner', 'business_owner', 'examiner', 'admin'
    requested_role = db.Column(db.String(50), nullable=False)  # 'customer', 'examiner', 'admin'
    
    # Business Details (for Business Owners)
    business_name = db.Column(db.String(200), nullable=True)
    business_registration_number = db.Column(db.String(100), nullable=True)
    business_type = db.Column(db.String(100), nullable=True)  # 'retail', 'manufacturing', 'hospitality', etc.
    number_of_locations = db.Column(db.Integer, default=1)
    
    # Home Owner Details
    residential_address = db.Column(db.Text, nullable=True)
    meter_number = db.Column(db.String(50), nullable=True)
    
    # Approval Workflow
    status = db.Column(db.String(50), default='pending')  # 'pending', 'approved', 'rejected', 'under_review'
    submission_date = db.Column(db.DateTime, default=datetime.utcnow)
    review_date = db.Column(db.DateTime, nullable=True)
    
    # Admin Review
    reviewed_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    review_notes = db.Column(db.Text, nullable=True)
    rejection_reason = db.Column(db.Text, nullable=True)
    
    # Account Creation
    created_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    account_creation_date = db.Column(db.DateTime, nullable=True)
    
    # Verification
    email_verified = db.Column(db.Boolean, default=False)
    phone_verified = db.Column(db.Boolean, default=False)
    verification_token = db.Column(db.String(255), nullable=True)
    verification_token_expires = db.Column(db.DateTime, nullable=True)
    
    # Permissions & Features
    permissions = db.Column(db.Text, nullable=True)  # JSON string of assigned permissions
    feature_tier = db.Column(db.String(50), default='basic')  # 'basic', 'standard', 'premium'
    
    # Audit
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    ip_address = db.Column(db.String(45), nullable=True)
    user_agent = db.Column(db.Text, nullable=True)

    # Relationships
    reviewer = db.relationship('User', foreign_keys=[reviewed_by], backref=db.backref('reviewed_requests', lazy=True))
    created_user = db.relationship('User', foreign_keys=[created_user_id], backref=db.backref('created_from_request', lazy=True))

    def generate_verification_token(self):
        """Generate a verification token for email/phone confirmation"""
        import secrets
        return secrets.token_urlsafe(32)


# ===================== ROLE-BASED ACCESS CONTROL =====================

def role_required(*roles):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                return redirect(url_for('login'))
            if current_user.role not in roles:
                # Deny access for non-members/staff explicitly with 403
                abort(Response("Access Denied: You don't have permission to access this page.", 403))
            return f(*args, **kwargs)

        return decorated_function

    return decorator


def admin_required(f):
    return role_required('admin')(f)


def examiner_required(f):
    return role_required('examiner')(f)


def hr_required(f):
    return role_required('hr_manager')(f)


def admin_secure(f):
    """Additional admin security checks: ensure user is admin and has an employee_id (simple guard)."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('staff_login'))
        if current_user.role != 'admin':
            abort(Response('Forbidden: admin access required', 403))
        if not getattr(current_user, 'employee_id', None):
            abort(Response('Forbidden: admin account not fully provisioned (missing employee id)', 403))
        return f(*args, **kwargs)

    return wrapper


# ===================== COST CALCULATION FUNCTIONS =====================

def calculate_electricity_cost(kwh, unit_cost, currency='Ksh'):
    """Calculate electricity cost based on kWh and unit cost"""
    return round(kwh * unit_cost, 2)


def calculate_daily_cost(user):
    """Calculate daily cost for a user"""
    today = datetime.utcnow().date()
    readings_today = Reading.query.filter(
        Reading.user_id == user.id,
        db.func.date(Reading.created_at) == today
    ).all()
    
    total_kwh = sum(r.kwh for r in readings_today)
    total_cost = calculate_electricity_cost(total_kwh, user.unit_cost, user.currency)
    return {'kwh': total_kwh, 'cost': total_cost}


def calculate_period_cost(user, start_date, end_date):
    """Calculate cost for a specific period"""
    readings = Reading.query.filter(
        Reading.user_id == user.id,
        Reading.created_at >= start_date,
        Reading.created_at <= end_date
    ).all()
    
    total_kwh = sum(r.kwh for r in readings)
    total_cost = calculate_electricity_cost(total_kwh, user.unit_cost, user.currency)
    return {'kwh': total_kwh, 'cost': total_cost}


# ===================== ANALYTICS FUNCTIONS =====================

def calculate_energy_analytics(user, period='monthly', branch_id=None):
    """Calculate comprehensive energy analytics for user or branch"""
    if period == 'monthly':
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=30)
    elif period == 'weekly':
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=7)
    else:  # daily
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=1)
    
    # Get all readings for the period
    readings = Reading.query.filter(
        Reading.user_id == user.id,
        Reading.created_at >= start_date,
        Reading.created_at <= end_date
    ).all()
    
    if not readings:
        return {
            'total_usage': 0,
            'average_daily': 0,
            'peak_usage': 0,
            'lowest_usage': 0,
            'trend': 'stable',
            'comparison_previous': 0
        }
    
    kwhs = [r.kwh for r in readings]
    total_usage = sum(kwhs)
    
    # Get highest and lowest consuming devices
    devices = CustomerDevice.query.filter_by(user_id=user.id).all()
    highest_device = None
    lowest_device = None
    if devices:
        device_usage = {}
        for device in devices:
            iot_readings = IoTData.query.filter(
                IoTData.device_id == device.id,
                IoTData.timestamp >= start_date,
                IoTData.timestamp <= end_date
            ).all()
            device_usage[device.name] = sum(d.value for d in iot_readings)
        
        if device_usage:
            highest_device = max(device_usage, key=device_usage.get)
            lowest_device = min(device_usage, key=device_usage.get)
    
    # Calculate trend
    mid_date = start_date + (end_date - start_date) / 2
    first_half = sum(r.kwh for r in readings if r.created_at < mid_date)
    second_half = sum(r.kwh for r in readings if r.created_at >= mid_date)
    
    if second_half > first_half * 1.1:
        trend = 'increasing'
    elif second_half < first_half * 0.9:
        trend = 'decreasing'
    else:
        trend = 'stable'
    
    # Get analytics for the previous period for comparison
    prev_start = start_date - (end_date - start_date)
    prev_end = start_date
    prev_readings = Reading.query.filter(
        Reading.user_id == user.id,
        Reading.created_at >= prev_start,
        Reading.created_at <= prev_end
    ).all()
    prev_total = sum(r.kwh for r in prev_readings) if prev_readings else 0
    comparison = ((total_usage - prev_total) / prev_total * 100) if prev_total > 0 else 0
    
    return {
        'total_usage': round(total_usage, 2),
        'average_daily': round(total_usage / len(kwhs), 2) if kwhs else 0,
        'peak_usage': round(max(kwhs), 2) if kwhs else 0,
        'lowest_usage': round(min(kwhs), 2) if kwhs else 0,
        'highest_device': highest_device,
        'lowest_device': lowest_device,
        'trend': trend,
        'comparison_previous': round(comparison, 2)
    }


# ===================== RECOMMENDATION FUNCTIONS =====================

def generate_energy_recommendations(user):
    """Generate personalized energy saving recommendations"""
    recommendations = []
    
    # Get user's current usage pattern
    analytics = calculate_energy_analytics(user, 'weekly')
    
    # Recommendation 1: AC Usage during peak hours
    if analytics['peak_usage'] > 50:
        recommendations.append({
            'type': 'AC Peak Hours',
            'description': 'Reduce air conditioner usage during peak hours (9 AM - 5 PM) to save 15-20% on cooling costs.',
            'savings': 10.5,
            'priority': 'high'
        })
    
    # Recommendation 2: Idle devices
    devices = CustomerDevice.query.filter_by(user_id=user.id).all()
    idle_devices = [d for d in devices if not d.is_active]
    if idle_devices:
        recommendations.append({
            'type': 'Idle Devices',
            'description': f'You have {len(idle_devices)} idle device(s). Turn them off to save energy.',
            'savings': 5.0,
            'priority': 'medium'
        })
    
    # Recommendation 3: Daily pattern optimization
    if analytics['average_daily'] > 40:
        recommendations.append({
            'type': 'Usage Optimization',
            'description': 'Your average daily usage is high. Consider scheduling non-essential tasks during off-peak hours.',
            'savings': 8.0,
            'priority': 'medium'
        })
    
    # Recommendation 4: Device efficiency
    if analytics['highest_device']:
        recommendations.append({
            'type': 'Device Efficiency',
            'description': f'{analytics["highest_device"]} is your highest consumer. Consider upgrading to an energy-efficient model.',
            'savings': 12.0,
            'priority': 'low'
        })
    
    return recommendations


# ===================== REAL-TIME MONITORING FUNCTIONS =====================

def update_device_status(device_id, is_online=True, current_power=0):
    """Update device status for real-time monitoring"""
    status = DeviceStatus.query.filter_by(device_id=device_id).first()
    
    if not status:
        status = DeviceStatus(device_id=device_id)
        db.session.add(status)
    
    status.is_online = is_online
    status.current_power = current_power
    status.last_reading = datetime.utcnow()
    
    if is_online:
        status.status = 'running' if current_power > 0 else 'idle'
    else:
        status.status = 'offline'
    
    status.last_activity = datetime.utcnow()
    db.session.commit()
    return status


def get_device_real_time_data(device_id):
    """Get real-time data for a device"""
    status = DeviceStatus.query.filter_by(device_id=device_id).first()
    if not status:
        return None
    
    return {
        'device_id': device_id,
        'is_online': status.is_online,
        'current_power': status.current_power,
        'status': status.status,
        'last_reading': status.last_reading,
        'last_activity': status.last_activity
    }


# ===================== REPORT GENERATION FUNCTIONS =====================

def generate_energy_report(user, report_type='monthly', branch_id=None):
    """Generate energy consumption report"""
    if report_type == 'daily':
        start_date = datetime.utcnow().date()
        end_date = start_date + timedelta(days=1)
    elif report_type == 'weekly':
        end_date = datetime.utcnow().date()
        start_date = end_date - timedelta(days=7)
    else:  # monthly
        today = datetime.utcnow().date()
        start_date = today.replace(day=1)
        if today.month == 12:
            end_date = today.replace(year=today.year + 1, month=1, day=1)
        else:
            end_date = today.replace(month=today.month + 1, day=1)
    
    # Get readings
    readings = Reading.query.filter(
        Reading.user_id == user.id,
        Reading.created_at >= start_date,
        Reading.created_at < end_date
    ).all()
    
    total_energy = sum(r.kwh for r in readings)
    total_cost = calculate_electricity_cost(total_energy, user.unit_cost, user.currency)
    
    # Create report entry
    report = ReportGeneration(
        user_id=user.id,
        branch_id=branch_id,
        report_type=report_type,
        period_start=start_date,
        period_end=end_date,
        total_energy=total_energy,
        total_cost=total_cost
    )
    db.session.add(report)
    db.session.commit()
    
    return {
        'report_id': report.id,
        'type': report_type,
        'period': f'{start_date} to {end_date}',
        'total_energy': round(total_energy, 2),
        'total_cost': round(total_cost, 2),
        'device_count': len(user.devices),
        'readings_count': len(readings)
    }


# ===================== UTILITY FUNCTIONS =====================

def log_system_action(user_id, action):
    try:
        log = SystemLog(user_id=user_id, action=action, ip_address=request.remote_addr)
        db.session.add(log)
        db.session.commit()
    except:
        db.session.rollback()


def record_audit(actor_id, action, entity_type=None, entity_id=None, changes=None):
    """Create an AuditLog entry. `changes` may be a dict and will be JSON-encoded."""
    try:
        ip = request.remote_addr
    except RuntimeError:
        ip = None
    try:
        changes_json = json.dumps(changes) if changes is not None else None
    except Exception:
        changes_json = str(changes)
    try:
        entry = AuditLog(actor_id=actor_id, action=action, entity_type=entity_type,
                         entity_id=str(entity_id) if entity_id is not None else None,
                         changes=changes_json, ip_address=ip)
        db.session.add(entry)
        db.session.commit()
        return entry
    except Exception:
        db.session.rollback()
        return None


def generate_partner_api_key():
    """Generate a URL-safe API key for partners."""
    return secrets.token_urlsafe(32)


def create_partner(name, contact_email=None, sandbox=True):
    """Create a Partner record with a unique API key."""
    key = generate_partner_api_key()
    # Ensure uniqueness
    while Partner.query.filter_by(api_key=key).first():
        key = generate_partner_api_key()
    partner = Partner(name=name, contact_email=contact_email or '', api_key=key, sandbox=bool(sandbox))
    db.session.add(partner)
    db.session.commit()
    try:
        actor_id = current_user.id if current_user and current_user.is_authenticated else None
    except Exception:
        actor_id = None
    record_audit(actor_id, 'partner.created', 'partner', partner.id, {'name': partner.name})
    return partner


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


# ===================== GAMIFICATION FUNCTIONS =====================

def get_or_create_eco_points(user):
    """Get or create EcoPoints for a user"""
    points = EcoPoints.query.filter_by(user_id=user.id).first()
    if not points:
        points = EcoPoints(user_id=user.id)
        db.session.add(points)
        db.session.commit()
    return points


def award_eco_points(user, points_earned, reason):
    """Award EcoPoints to a user and check for level ups"""
    points = get_or_create_eco_points(user)
    old_level = points.level
    points.points += points_earned

    # Level up calculation (every 500 points)
    new_level = 1 + (points.points // 500)
    if new_level > old_level:
        points.level = new_level
        # Create level up report
        report = Report(
            title=f"🎉 Level Up! You reached Level {new_level}",
            content=f"Congratulations {user.username}! You've earned {points_earned} points and reached Level {new_level}. Keep saving energy!",
            report_type='gamification',
            sent_by=user.id,
            sent_to=user.id
        )
        db.session.add(report)

    points.last_activity_date = datetime.utcnow()
    db.session.commit()

    # Check for new badges
    check_and_award_badges(user)

    return points.points


def check_and_award_badges(user):
    """Check and award badges based on user achievements"""
    points = get_or_create_eco_points(user)
    earned_badges = json.loads(points.badges) if points.badges else []

    # Define badges
    badges_config = [
        {'name': 'Energy Saver', 'condition': points.total_savings_kwh >= 100, 'icon': 'bi-leaf',
         'description': 'Saved 100+ kWh'},
        {'name': 'Green Champion', 'condition': points.total_savings_kwh >= 500, 'icon': 'bi-tree',
         'description': 'Saved 500+ kWh'},
        {'name': 'Eco Warrior', 'condition': points.total_savings_kwh >= 1000, 'icon': 'bi-globe',
         'description': 'Saved 1000+ kWh'},
        {'name': 'Streak Master', 'condition': points.streak_days >= 30, 'icon': 'bi-fire',
         'description': '30 day streak!'},
        {'name': 'Consistent Saver', 'condition': points.streak_days >= 7, 'icon': 'bi-calendar-check',
         'description': '7 day streak'},
        {'name': 'Reading Champion', 'condition': len(Reading.query.filter_by(user_id=user.id).all()) >= 12,
         'icon': 'bi-journal', 'description': '12+ readings submitted'},
        {'name': 'Threshold Hero', 'condition': check_threshold_compliance(user), 'icon': 'bi-shield-check',
         'description': 'Stayed below threshold for 3 months'},
    ]

    new_badges = []
    for badge in badges_config:
        if badge['condition'] and badge['name'] not in earned_badges:
            earned_badges.append(badge['name'])
            new_badges.append(badge)

            # Create badge award report
            report = Report(
                title=f"🏅 New Badge Unlocked: {badge['name']}",
                content=f"Congratulations {user.username}! You've earned the {badge['name']} badge. {badge['description']}",
                report_type='badge',
                sent_by=user.id,
                sent_to=user.id
            )
            db.session.add(report)

    points.badges = json.dumps(earned_badges)
    db.session.commit()
    return new_badges


def check_threshold_compliance(user):
    """Check if user stayed below threshold for last 3 months"""
    readings = Reading.query.filter_by(user_id=user.id).order_by(Reading.created_at.desc()).limit(3).all()
    if len(readings) >= 3:
        return all(r.kwh <= user.threshold for r in readings)
    return False


def update_leaderboard():
    """Update leaderboard rankings"""
    # Get all users with points
    all_points = EcoPoints.query.all()
    sorted_users = sorted(all_points, key=lambda x: x.points, reverse=True)

    for rank, points_entry in enumerate(sorted_users, 1):
        existing = Leaderboard.query.filter_by(user_id=points_entry.user_id).first()
        if existing:
            existing.points = points_entry.points
            existing.rank = rank
        else:
            leader = Leaderboard(user_id=points_entry.user_id, points=points_entry.points, rank=rank)
            db.session.add(leader)

    db.session.commit()


def get_optimal_usage_time(user, appliance_type='general'):
    """AI function to suggest optimal times for appliance usage"""
    readings = Reading.query.filter_by(user_id=user.id).all()
    if len(readings) < 5:
        return "Add more readings to get personalized recommendations"

    # Analyze consumption patterns
    hourly_pattern = {}
    for reading in readings:
        hour = reading.timestamp.hour if reading.timestamp else 12
        if hour not in hourly_pattern:
            hourly_pattern[hour] = 0
        hourly_pattern[hour] += reading.kwh

    # Find the lowest consumption hours (off-peak)
    if hourly_pattern:
        best_hours = sorted(hourly_pattern.items(), key=lambda x: x[1])[:4]
        best_times = [f"{h}:00" for h, _ in best_hours]

        recommendations = {
            'general': f"Best times to use appliances: {', '.join(best_times)}",
            'laundry': f"Run washing machine/dryer during off-peak hours: {', '.join(best_times[:2])}",
            'heating': f"Schedule water heating during early morning ({best_times[0]}) when grid demand is low",
            'ac': f"Pre-cool your home during {best_times[0]} to reduce peak afternoon usage"
        }

        return recommendations.get(appliance_type, recommendations['general'])

    return "Not enough data for optimal time prediction"


def get_community_comparison(user):
    """Compare user with neighbors/similar households"""
    user_points = get_or_create_eco_points(user)

    # Get average points of all customers
    all_points = EcoPoints.query.all()
    avg_points = sum(p.points for p in all_points) / len(all_points) if all_points else 0

    # Get top 10 users
    top_users = EcoPoints.query.order_by(EcoPoints.points.desc()).limit(10).all()

    # Calculate percentile
    higher_count = sum(1 for p in all_points if p.points > user_points.points)
    percentile = (higher_count / len(all_points) * 100) if all_points else 0

    # Get users in same city/region (if location data available)
    nearby_users = []
    # This can be expanded with location data

    return {
        'user_rank': sum(1 for p in all_points if p.points > user_points.points) + 1,
        'total_users': len(all_points),
        'percentile': round(percentile, 1),
        'avg_points': round(avg_points, 1),
        'top_users': [(u.user.username, u.points) for u in top_users[:5]],
        'points_to_next': (top_users[0].points - user_points.points) if top_users and user_points.points < top_users[
            0].points else 0
    }


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


# ----------------- API endpoints for partners, audits, and tariff reviews -----------------
@app.route('/api/partners/register', methods=['POST'])
@admin_required
def api_partners_register():
    data = request.get_json(silent=True) or {}
    name = data.get('name')
    contact = data.get('contact_email')
    sandbox = data.get('sandbox', True)
    if not name:
        return jsonify({'error': 'name is required'}), 400
    partner = create_partner(name, contact, sandbox)
    return jsonify({'id': partner.id, 'name': partner.name, 'api_key': partner.api_key, 'sandbox': partner.sandbox}), 201


@app.route('/api/audit/logs', methods=['GET'])
@role_required('admin', 'examiner')
def api_audit_logs():
    entity = request.args.get('entity')
    actor = request.args.get('actor_id')
    limit = min(int(request.args.get('limit', 100)), 1000)
    q = AuditLog.query.order_by(AuditLog.created_at.desc())
    if entity:
        q = q.filter(AuditLog.entity_type == entity)
    if actor:
        try:
            q = q.filter(AuditLog.actor_id == int(actor))
        except Exception:
            pass
    logs = q.limit(limit).all()
    out = []
    for l in logs:
        try:
            changes = json.loads(l.changes) if l.changes else None
        except Exception:
            changes = l.changes
        out.append({
            'id': l.id,
            'actor_id': l.actor_id,
            'action': l.action,
            'entity_type': l.entity_type,
            'entity_id': l.entity_id,
            'changes': changes,
            'ip_address': l.ip_address,
            'created_at': l.created_at.isoformat()
        })
    return jsonify(out)


@app.route('/api/tariffs/<int:report_id>/submit-for-review', methods=['POST'])
@admin_required
def submit_tariff_for_review(report_id):
    report = Report.query.get(report_id)
    if not report:
        return jsonify({'error': 'report not found'}), 404
    tr = TariffReview(report_id=report_id, submitted_by=current_user.id, status='under_review', submitted_at=datetime.utcnow())
    db.session.add(tr)
    db.session.commit()
    record_audit(current_user.id, 'tariff.submit_for_review', 'tariff_review', tr.id, {'report_id': report_id})
    return jsonify({'id': tr.id, 'status': tr.status}), 201


@app.route('/api/tariffs/<int:review_id>/approve', methods=['POST'])
@examiner_required
def approve_tariff_review(review_id):
    tr = TariffReview.query.get(review_id)
    if not tr:
        return jsonify({'error': 'review not found'}), 404
    tr.status = 'approved'
    tr.examiner_id = current_user.id
    tr.reviewed_at = datetime.utcnow()
    db.session.commit()
    record_audit(current_user.id, 'tariff.approve', 'tariff_review', tr.id)
    return jsonify({'id': tr.id, 'status': tr.status})


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
    if not digits:
        return None, 'Phone number is required.'

    code_digits = ''.join(ch for ch in code if ch.isdigit())
    if code_digits and digits.startswith(code_digits):
        digits = digits[len(code_digits):]

    # Accept common local formats for testing:
    # - 9 digits (e.g. 712345678)
    # - 10 digits starting with 0 (e.g. 0712345678)
    if len(digits) == 10 and digits.startswith('0'):
        digits = digits[1:]

    if len(digits) != 9:
        return None, 'Phone number must be 9 digits (or 10 digits starting with 0).'

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


def normalize_energy_source(value, default='KPLC'):
    source = (value or default or 'KPLC').strip().upper()
    return source if source in ENERGY_SOURCES else default


def get_energy_source_label(value):
    return ENERGY_SOURCE_LABELS.get(normalize_energy_source(value), 'KPLC Grid')


def get_latest_tariff_notice(energy_source='KPLC'):
    normalized_source = normalize_energy_source(energy_source)
    report = (
        Report.query.filter_by(report_type='tariff_notice')
        .order_by(Report.created_at.desc())
        .all()
    )
    matched_report = None
    for item in report:
        if not item.chart_data:
            continue
        try:
            payload = json.loads(item.chart_data)
        except json.JSONDecodeError:
            payload = {}
        payload_source = normalize_energy_source(payload.get('energy_source'), default='KPLC')
        if payload_source == normalized_source:
            matched_report = item
            break
    if not matched_report:
        legacy_type = f"{normalized_source.lower()}_tariff"
        matched_report = Report.query.filter_by(report_type=legacy_type).order_by(Report.created_at.desc()).first()
    report = matched_report
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
    payload['energy_source'] = normalize_energy_source(payload.get('energy_source'), default=normalized_source)
    payload['energy_source_label'] = get_energy_source_label(payload['energy_source'])
    return payload


def get_latest_kplc_tariff_notice():
    return get_latest_tariff_notice('KPLC')


def _get_user_live_queue(user_id):
    user_key = int(user_id)
    queue_state = LIVE_NOTIFICATIONS.get(user_key)
    if not queue_state:
        queue_state = {'events': deque(maxlen=LIVE_NOTIFICATION_QUEUE_SIZE), 'next_id': 1}
        LIVE_NOTIFICATIONS[user_key] = queue_state
    return queue_state


def push_live_notification(user_id, title, message, level='info'):
    if not user_id:
        return
    safe_level = str(level or 'info').strip().lower()
    if safe_level not in {'info', 'success', 'warning', 'danger'}:
        safe_level = 'info'

    payload = {
        'title': str(title or 'EcoPulse Notification'),
        'message': str(message or ''),
        'level': safe_level,
        'created_at': local_now().strftime('%Y-%m-%d %H:%M:%S')
    }
    with LIVE_NOTIFICATIONS_LOCK:
        queue_state = _get_user_live_queue(user_id)
        payload['id'] = queue_state['next_id']
        queue_state['next_id'] += 1
        queue_state['events'].append(payload)


def get_live_notifications_since(user_id, last_event_id):
    user_key = int(user_id)
    with LIVE_NOTIFICATIONS_LOCK:
        queue_state = LIVE_NOTIFICATIONS.get(user_key)
        if not queue_state:
            return []
        return [dict(item) for item in queue_state['events'] if int(item.get('id', 0)) > int(last_event_id or 0)]


def get_active_unit_cost(user=None):
    energy_source = normalize_energy_source(getattr(user, 'energy_source', 'KPLC'))
    latest_notice = get_latest_tariff_notice(energy_source)
    if latest_notice and latest_notice.get('cost_per_unit') is not None:
        return float(latest_notice['cost_per_unit'])
    admin_user = User.query.filter_by(role='admin').first()
    if admin_user and admin_user.unit_cost is not None:
        return float(admin_user.unit_cost)
    customer = User.query.filter_by(role='customer').first()
    return float(customer.unit_cost) if customer and customer.unit_cost is not None else 0.12


def send_sms_notification(phone_number, message):
    """
    Send SMS notification using Twilio
    Returns: (success: bool, error_message: str | None)
    """
    try:
        phone = (phone_number or '').strip()
        if not phone:
            return False, 'Phone number is not configured.'

        # Check for Twilio configuration
        twilio_sid = app.config.get('TWILIO_ACCOUNT_SID')
        twilio_token = app.config.get('TWILIO_AUTH_TOKEN')
        twilio_from = app.config.get('TWILIO_PHONE_NUMBER')

        if not all([twilio_sid, twilio_token, twilio_from]):
            print(f"SMS notification queued for {phone}: {message} (Twilio not configured)")
            return True, None  # Return success for development

        # Import Twilio (optional dependency)
        try:
            from twilio.rest import Client
            from twilio.base.exceptions import TwilioException
        except ImportError:
            print(f"SMS notification queued for {phone}: {message} (Twilio not installed)")
            return True, None

        # Format phone number (add country code if missing)
        if not phone.startswith('+'):
            phone = '+254' + phone.lstrip('0')  # Default to Kenya country code

        client = Client(twilio_sid, twilio_token)
        sms = client.messages.create(
            body=message[:160],  # SMS limit
            from_=twilio_from,
            to=phone
        )

        print(f"SMS sent successfully to {phone}: SID {sms.sid}")
        return True, None

    except Exception as e:
        error_msg = f"SMS failed: {str(e)}"
        print(error_msg)
        return False, error_msg


def create_notification(user_id, title, message, notification_type='info', send_sms=False, send_email=False):
    """
    Create an in-app notification and optionally send SMS/email
    """
    try:
        # Create in-app notification
        notification = Notification(
            user_id=user_id,
            title=title,
            message=message,
            notification_type=notification_type
        )
        db.session.add(notification)

        user = User.query.get(user_id)
        if not user:
            return False, "User not found"

        delivery_notes = []

        # Send SMS if requested and phone configured
        if send_sms and user.phone_number:
            sms_ok, sms_err = send_sms_notification(user.phone_number, f"{title}: {message}")
            notification.sent_via_sms = sms_ok
            delivery_notes.append('SMS queued' if sms_ok else f'SMS failed: {sms_err}')

        # Send email if requested and email configured
        if send_email and user.email and user.alert_email:
            html_body = f"""
            <html>
            <body>
                <h3>{title}</h3>
                <p>{message}</p>
                <hr>
                <p><small>This is an automated notification from EcoPulse Energy Management System.</small></p>
            </body>
            </html>
            """
            email_ok, email_err = send_email_notification(user.email, f"EcoPulse: {title}", html_body, message)
            notification.sent_via_email = email_ok
            delivery_notes.append('Email sent' if email_ok else f'Email failed: {email_err}')

        db.session.commit()

        # Push live notification
        push_live_notification(user_id, title, message, notification_type)

        return True, '; '.join(delivery_notes) if delivery_notes else 'Notification created'

    except Exception as e:
        db.session.rollback()
        return False, f"Failed to create notification: {str(e)}"


def send_direct_message(sender_id, recipient_id, subject, content, message_type='direct'):
    """
    Send a direct message between users
    """
    try:
        message = Message(
            sender_id=sender_id,
            recipient_id=recipient_id,
            subject=subject,
            content=content,
            message_type=message_type
        )
        db.session.add(message)
        db.session.commit()

        # Create notification for recipient
        sender = User.query.get(sender_id)
        sender_name = sender.username if sender else 'System'

        create_notification(
            recipient_id,
            f"New Message from {sender_name}",
            f"Subject: {subject}",
            'info'
        )

        return True, "Message sent successfully"

    except Exception as e:
        db.session.rollback()
        return False, f"Failed to send message: {str(e)}"


def broadcast_message(sender_id, recipient_roles, subject, content):
    """
    Send a message to all users with specific roles
    """
    try:
        recipients = User.query.filter(User.role.in_(recipient_roles)).all()
        sent_count = 0

        for recipient in recipients:
            if recipient.id != sender_id:  # Don't send to self
                message = Message(
                    sender_id=sender_id,
                    recipient_id=recipient.id,
                    subject=subject,
                    content=content,
                    message_type='broadcast'
                )
                db.session.add(message)

                # Create notification
                sender = User.query.get(sender_id)
                sender_name = sender.username if sender else 'System'
                create_notification(
                    recipient.id,
                    f"Broadcast from {sender_name}",
                    f"Subject: {subject}",
                    'info'
                )
                sent_count += 1

        db.session.commit()
        return True, f"Message broadcasted to {sent_count} users"

    except Exception as e:
        db.session.rollback()
        return False, f"Failed to broadcast message: {str(e)}"


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
    source_label = get_energy_source_label(user.energy_source)
    unit_cost = get_active_unit_cost(user)
    message = (
        f"EcoPulse test notification for {user.username}. "
        f"Source: {source_label}. Current unit rate: {user.currency} {unit_cost:.2f}/kWh. "
        f"Usage check: {simulated_total_kwh:.2f} kWh against threshold {threshold:.2f} kWh."
    )
    delivery_notes = []

    if getattr(user, 'alert_email', False) and getattr(user, 'email', None):
        html_body = (
            f"<h2>EcoPulse Threshold Notification Test</h2>"
            f"<p>Dear {user.username},</p>"
            f"<p>This is a test of your registered threshold notification channel.</p>"
            f"<p><strong>Energy source:</strong> {source_label}</p>"
            f"<p><strong>Current unit rate:</strong> {user.currency} {unit_cost:.2f} per kWh</p>"
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

    push_live_notification(
        user.id,
        'Notification Test',
        f"{source_label}: {' | '.join(delivery_notes)}",
        'success' if any(note in delivery_notes for note in ['Email sent', 'SMS queued']) else 'warning'
    )
    return delivery_notes


def check_and_send_threshold_notifications(user, current_total_kwh, user_settings):
    """Check consumption levels and send notifications at 80%, 90%, 95%, 100%"""
    threshold = user.threshold
    if threshold <= 0:
        return

    percentage = (current_total_kwh / threshold) * 100
    notifications_sent = []
    source_label = get_energy_source_label(user.energy_source)
    unit_cost = get_active_unit_cost(user)

    # Define notification levels
    levels = [
        (80, '80_percent', '⚠️ 80% Threshold Alert',
         f"You have reached 80% of your monthly threshold. Source: {source_label}. Current usage: {current_total_kwh:.2f} kWh out of {threshold} kWh. {threshold - current_total_kwh:.2f} kWh remaining at {user.currency} {unit_cost:.2f}/kWh."),

        (90, '90_percent', '⚠️ 90% Threshold Alert - High Usage',
         f"URGENT: You have reached 90% of your monthly threshold! Source: {source_label}. Current usage: {current_total_kwh:.2f} kWh out of {threshold} kWh. Only {threshold - current_total_kwh:.2f} kWh remaining at {user.currency} {unit_cost:.2f}/kWh. Please reduce consumption or recharge."),

        (95, '95_percent', '🔴 95% Threshold Alert - Critical',
         f"CRITICAL: You have reached 95% of your monthly threshold! Source: {source_label}. Current usage: {current_total_kwh:.2f} kWh out of {threshold} kWh. Only {threshold - current_total_kwh:.2f} kWh left at {user.currency} {unit_cost:.2f}/kWh. Immediate action required."),

        (100, '100_percent', '🔴 THRESHOLD EXCEEDED - Service Alert',
         f"ALERT: You have exceeded your monthly threshold! Source: {source_label}. Current usage: {current_total_kwh:.2f} kWh. Threshold: {threshold} kWh. Exceeded by: {current_total_kwh - threshold:.2f} kWh at {user.currency} {unit_cost:.2f}/kWh. Please recharge immediately to avoid service interruption.")
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

                push_live_notification(
                    user.id,
                    title,
                    message,
                    'danger' if level_value >= 95 else ('warning' if level_value >= 90 else 'info')
                )
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

    source_label = get_energy_source_label(customer.energy_source)
    payload = {
        'customer_id': customer.id,
        'customer': customer.username,
        'meter_number': customer.meter_number,
        'reading_id': reading.id,
        'reading_period': reading.date,
        'reading_kwh': round(reading.kwh, 2),
        'threshold': round(customer.threshold, 2),
        'exceeded_by': round(exceeded_by, 2),
        'sensor_name': f'{source_label} Smart Threshold Sensor',
        'energy_source': normalize_energy_source(customer.energy_source),
        'sensor_status': 'critical' if exceeded_by >= customer.threshold * 0.2 else 'warning',
        'scheduled_shutdown_at': user_settings.scheduled_shutdown_at.isoformat() if user_settings.scheduled_shutdown_at else None
    }
    report = Report(
        title=f"Sensor Alert - {customer.username} exceeded threshold",
        content=(
            f"<p><strong>Customer:</strong> {customer.username}</p>"
            f"<p><strong>Meter:</strong> {customer.meter_number}</p>"
            f"<p><strong>Energy source:</strong> {source_label}</p>"
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
    push_live_notification(
        customer.id,
        'Sensor Alert',
        f"You exceeded threshold by {exceeded_by:.2f} kWh ({source_label}).",
        'warning'
    )
    push_live_notification(
        admin.id,
        'Customer Sensor Alert',
        f"{customer.username} exceeded threshold by {exceeded_by:.2f} kWh.",
        'warning'
    )
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
    source_label = get_energy_source_label(user.energy_source)
    source_unit_cost = get_active_unit_cost(user)

    return {
        'title': f'{source_label} Smart Meter',
        'status': state,
        'reading_value': f"{latest_kwh:.1f} kWh",
        'reading_label': f'Latest household reading ({source_label})',
        'ring_value': utilization,
        'ring_label': 'Threshold usage',
        'support_value': f"{verification_ratio:.0f}%",
        'support_label': 'Verified readings',
        'detail_primary': f"Open balance: {user.currency} {open_balance:.2f}",
        'detail_secondary': (
            f"{source_label} at {user.currency} {source_unit_cost:.2f}/kWh | "
            f"{'Protection mode active' if not user_settings.allow_overage else 'Overage billing active'}"
        )
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
        'login': "Customers use the public login page. Staff sign-in is restricted to a private internal route.",
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


def ensure_users_energy_source_column():
    """Ensure legacy databases have users.energy_source before ORM queries include it."""
    try:
        from sqlalchemy import inspect
        inspector = inspect(db.engine)
        if 'users' not in inspector.get_table_names():
            return
        user_columns = [col['name'] for col in inspector.get_columns('users')]
        with db.engine.connect() as conn:
            if 'energy_source' not in user_columns:
                conn.execute(db.text("ALTER TABLE users ADD COLUMN energy_source VARCHAR(20) DEFAULT 'KPLC'"))
            conn.execute(db.text("UPDATE users SET energy_source = 'KPLC' WHERE energy_source IS NULL OR energy_source = ''"))
            conn.commit()
    except Exception as exc:
        print(f"Note: ensure users.energy_source column - {exc}")


def ensure_test_user(role, email, department=None):
    ensure_users_energy_source_column()
    username, password = generate_role_test_credentials(role)
    user = User.query.filter_by(username=username).first()
    if user:
        settings = get_or_create_user_settings(user)
        if not user.energy_source:
            user.energy_source = 'KPLC'
            db.session.commit()
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
        user.energy_source = 'KPLC'
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


def send_subscription_email(to_email, action, tier, result):
    """Send subscription-related email notifications"""
    try:
        if action == 'upgrade':
            subject = f"EcoPulse: Welcome to {result['tier_name']}!"
            html_body = f"""
            <html>
            <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 30px; text-align: center;">
                    <h1>🎉 Subscription Upgraded!</h1>
                    <p style="font-size: 18px;">Welcome to {result['tier_name']}</p>
                </div>
                <div style="padding: 30px; background: #f8f9fa;">
                    <h2>What's New with Your {result['tier_name']} Plan</h2>
                    <ul style="font-size: 16px; line-height: 1.6;">
                        {"".join(f"<li>{feature.replace('_', ' ').title()}</li>" for feature in result['features_activated'])}
                    </ul>
                    <div style="background: #e9ecef; padding: 20px; border-radius: 8px; margin: 20px 0;">
                        <h3>Plan Details</h3>
                        <p><strong>Monthly Price:</strong> Ksh {result['monthly_price']}</p>
                        <p><strong>Next Billing Date:</strong> {result['next_billing_date']}</p>
                    </div>
                    <p style="font-size: 16px;">Thank you for choosing EcoPulse! Your new features are now active.</p>
                    <div style="text-align: center; margin: 30px 0;">
                        <a href="{url_for('dashboard', _external=True)}" style="background: #28a745; color: white; padding: 12px 24px; text-decoration: none; border-radius: 6px; font-weight: bold;">Access Your Dashboard</a>
                    </div>
                </div>
                <div style="background: #343a40; color: white; padding: 20px; text-align: center;">
                    <p>EcoPulse - Smart Energy Management</p>
                    <p><a href="mailto:support@ecopulse.com" style="color: #ffc107;">support@ecopulse.com</a></p>
                </div>
            </body>
            </html>
            """
        elif action == 'renewal':
            subject = f"EcoPulse: Subscription Renewed - {tier.title()}"
            html_body = f"""
            <html>
            <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                <div style="background: linear-gradient(135deg, #28a745 0%, #20c997 100%); color: white; padding: 30px; text-align: center;">
                    <h1>🔄 Subscription Renewed</h1>
                    <p style="font-size: 18px;">Your {tier.title()} plan has been renewed</p>
                </div>
                <div style="padding: 30px; background: #f8f9fa;">
                    <p style="font-size: 16px;">Your EcoPulse subscription has been successfully renewed. Your account remains active with all features.</p>
                    <div style="text-align: center; margin: 30px 0;">
                        <a href="{url_for('dashboard', _external=True)}" style="background: #007bff; color: white; padding: 12px 24px; text-decoration: none; border-radius: 6px; font-weight: bold;">Go to Dashboard</a>
                    </div>
                </div>
            </body>
            </html>
            """
        else:
            return False, "Unknown action"

        return send_email_notification(to_email, subject, html_body)
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


def verify_or_rebuild_database():
    """Verify SQLite integrity and rebuild the database if it is corrupted."""
    db_path = os.path.join(app.instance_path, 'ecopulse.db')
    if not os.path.exists(db_path):
        return True

    try:
        import sqlite3
        with sqlite3.connect(db_path, timeout=30, check_same_thread=False) as conn:
            cursor = conn.cursor()
            cursor.execute('PRAGMA integrity_check')
            result = cursor.fetchone()
            if not result or result[0].upper() != 'OK':
                raise sqlite3.DatabaseError('SQLite integrity check failed')
    except Exception as integrity_error:
        backup_path = db_path + f'.corrupt.{datetime.utcnow().strftime("%Y%m%d%H%M%S")}'
        try:
            os.rename(db_path, backup_path)
            print(f"Database corruption detected; backed up corrupted database to {backup_path}")
        except OSError as backup_error:
            print(f"Failed to back up corrupted database: {backup_error}")
            try:
                os.remove(db_path)
            except OSError:
                pass
        return False
    return True

try:
    verify_or_rebuild_database()
except Exception as e:
    print(f"Warning: Database verification failed at import time: {e}")


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
                <div class="mb-3"><label class="form-label">Energy Meter Number</label><input type="text" name="meter_number" maxlength="11" class="form-control form-control-lg" placeholder="Enter your 11-digit meter number" required></div>
                <div class="mb-3"><label class="form-label">Password</label><input type="password" name="password" class="form-control form-control-lg" required></div>
                <div class="d-flex justify-content-between align-items-center mb-3">
                    <div class="form-check"><input class="form-check-input" type="checkbox" name="remember_me" id="remember_me"><label class="form-check-label" for="remember_me">Remember me</label></div>
                    <a href="{{ url_for('forgot_password') }}" class="text-decoration-none">Forgot password?</a>
                </div>
                <button type="submit" class="btn btn-lg btn-dark w-100">Login</button>
            </form>
            <div class="helper-band"><span class="text-muted">Need an account?</span> <a href="{{ url_for('register') }}" class="text-decoration-none fw-semibold">Register as a customer</a><div class="small text-muted mt-2">Customer login requires your autogenerated energy meter number together with username and password.</div></div>
        </div>
    </div>
</body>
</html>
"""

forgot_password_page = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Forgot Password - EcoPulse</title>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css">
    <style>body{background:#f8fafc;min-height:100vh;display:grid;place-items:center}.card{max-width:520px;width:100%;border-radius:20px}</style>
</head>
<body>
<div class="card shadow-sm p-4">
    <h3 class="fw-bold mb-2">Reset Customer Password</h3>
    <p class="text-muted">Provide your customer identity details to receive a reset link.</p>
    <form method="POST">
        <div class="mb-3"><label class="form-label">Username</label><input class="form-control" name="username" required></div>
        <div class="mb-3"><label class="form-label">Email</label><input class="form-control" type="email" name="email" required></div>
        <div class="mb-3"><label class="form-label">Meter Number</label><input class="form-control" name="meter_number" maxlength="11" required></div>
        <button class="btn btn-dark w-100" type="submit">Send Reset Link</button>
    </form>
    <a class="text-decoration-none mt-3 d-inline-block" href="{{ url_for('login') }}">Back to customer login</a>
</div>
</body>
</html>
"""

reset_password_page = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>New Password - EcoPulse</title>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css">
    <style>body{background:#f8fafc;min-height:100vh;display:grid;place-items:center}.card{max-width:520px;width:100%;border-radius:20px}</style>
</head>
<body>
<div class="card shadow-sm p-4">
    <h3 class="fw-bold mb-2">Create New Password</h3>
    <p class="text-muted">Choose a new password for your customer account.</p>
    {% if error %}<div class="alert alert-danger">{{ error }}</div>{% endif %}
    <form method="POST">
        <div class="mb-3"><label class="form-label">New Password</label><input class="form-control" type="password" name="password" required></div>
        <div class="mb-3"><label class="form-label">Confirm Password</label><input class="form-control" type="password" name="confirm_password" required></div>
        <button class="btn btn-dark w-100" type="submit">Update Password</button>
    </form>
</div>
</body>
</html>
"""

staff_invite_setup_page = """
<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Complete Account Setup - EcoPulse</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
</head>
<body class="bg-light">
    <main class="container py-5" style="max-width: 520px">
        <h1 class="h3">Complete account setup</h1>
        {% if error %}<div class="alert alert-danger">{{ error }}</div>{% endif %}
        {% if invite %}
        <p>Set a password for <strong>{{ invite.username }}</strong>. Your role is {{ invite.requested_role|replace('_', ' ')|title }}.</p>
        <form method="post">
            <label class="form-label" for="password">Password</label>
            <input class="form-control mb-3" id="password" type="password" name="password" minlength="8" required autocomplete="new-password">
            <label class="form-label" for="confirm-password">Confirm password</label>
            <input class="form-control mb-3" id="confirm-password" type="password" name="confirm_password" minlength="8" required autocomplete="new-password">
            <button class="btn btn-primary" type="submit">Set password</button>
        </form>
        {% endif %}
    </main>
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
            <h1 class="fw-bold">Secure staff sign-in for internal workflows.</h1>
            <p class="mt-3 mb-0">Use this route for internal approvals, system-wide analysis, and finance operations.</p>
            <div class="mini-grid">
                <div><strong>Admin</strong><br><span class="small">Financial controls, approvals, and customer summaries.</span></div>
                <div><strong>Examiner</strong><br><span class="small">Reading reviews, reports, and forecast-driven guidance.</span></div>
            </div>
        </div>
        <div class="col-lg-7 staff-card">
            <h2 class="fw-bold">Staff Login</h2>
            <p class="text-muted">Sign in with the account provisioned for you by an administrator.</p>
            {% if error %}<div class="alert alert-danger">{{ error }}</div>{% endif %}
            <form method="POST">
                <div class="mb-3"><label class="form-label">Username</label><input type="text" name="username" class="form-control" required></div>
                <div class="mb-3"><label class="form-label">Password</label><input type="password" name="password" class="form-control" required></div>
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
                <div class="col-md-3"><label class="form-label">Energy Source</label><select id="registerEnergySourceSelect" name="energy_source" class="form-control" onchange="syncRegisterEnergySourceFields()" required><option value="KPLC" {% if selected_energy_source == 'KPLC' %}selected{% endif %}>KPLC Grid</option><option value="SOLAR" {% if selected_energy_source == 'SOLAR' %}selected{% endif %}>Solar Grid</option></select></div>
                <div class="col-md-3" id="registerMeterNumberGroup" style="display: {{ 'block' if selected_energy_source == 'KPLC' else 'none' }};">
                    <label class="form-label" id="registerMeterNumberLabel">{% if selected_energy_source == 'KPLC' %}Energy Meter Number{% else %}Solar Asset Identifier{% endif %}</label>
                    <input id="registerMeterNumberInput" type="text" name="meter_number" maxlength="11" value="{{ generated_meter or '' }}" class="form-control" {% if selected_energy_source == 'KPLC' %}required{% endif %} placeholder="{% if selected_energy_source == 'KPLC' %}Enter your 11-digit meter number{% else %}Solar users do not need a KPLC meter number{% endif %}">
                </div>
                <div class="col-md-3"><label class="form-label">Country Code</label><select name="country_code" class="form-control" required>{% for item in phone_country_codes %}<option value="{{ item.code }}" {% if item.code == selected_country_code %}selected{% endif %}>{{ item.label }}</option>{% endfor %}</select></div>
                <div class="col-md-3"><label class="form-label">Phone Number</label><input type="text" name="phone_number" maxlength="10" value="{{ phone_number or '7000000000' }}" class="form-control" placeholder="10 digits" required></div>
                <div class="col-12" id="registerSolarHintRow" style="display: {{ 'none' if selected_energy_source == 'KPLC' else 'block' }};">
                    <div class="form-text text-muted">Solar customers do not need to enter a KPLC meter number; one will be generated automatically for login and records.</div>
                </div>
                <div class="col-md-6"><label class="form-label">Password</label><input type="password" name="password" class="form-control" required></div>
                <div class="col-md-6"><label class="form-label">Confirm Password</label><input type="password" name="confirm_password" class="form-control" required></div>
                <div class="col-12"><button type="submit" class="btn btn-dark w-100 btn-lg">Create Customer Account</button></div>
            </form>
            <div class="helper-box"><span class="text-muted">Already registered?</span> <a href="{{ url_for('login') }}" class="text-decoration-none fw-semibold">Log in here</a><div class="small text-muted mt-2">A valid 11-digit test meter number is generated automatically and can be changed if needed.</div></div>
        </div>
    </div>
    <script>
        function syncRegisterEnergySourceFields() {
            const source = document.getElementById('registerEnergySourceSelect');
            const meterGroup = document.getElementById('registerMeterNumberGroup');
            const meterInput = document.getElementById('registerMeterNumberInput');
            const meterLabel = document.getElementById('registerMeterNumberLabel');
            const solarHintRow = document.getElementById('registerSolarHintRow');
            if (!source || !meterGroup || !meterInput) return;
            const isKplc = source.value === 'KPLC';
            console.log('[EcoPulse] Registration energy source changed:', source.value, 'isKPLC=', isKplc);
            meterGroup.style.display = isKplc ? 'block' : 'none';
            meterGroup.classList.toggle('d-none', !isKplc);
            if (meterLabel) {
                meterLabel.textContent = isKplc ? 'Energy Meter Number' : 'Solar Asset Identifier';
            }
            meterInput.required = isKplc;
            meterInput.disabled = !isKplc;
            meterInput.placeholder = isKplc ? 'Enter your 11-digit meter number' : 'Solar users do not need a KPLC meter number';
            if (!isKplc) {
                meterInput.value = '';
            }
            if (solarHintRow) {
                solarHintRow.style.display = isKplc ? 'none' : 'block';
                solarHintRow.classList.toggle('d-none', isKplc);
            }
        }
        document.addEventListener('DOMContentLoaded', function() {
            const source = document.getElementById('registerEnergySourceSelect');
            if (source) source.addEventListener('change', syncRegisterEnergySourceFields);
            syncRegisterEnergySourceFields();
        });
    </script>
</body>
</html>
"""

dashboard_template = """<!DOCTYPE html><html lang="{{ current_user.language or 'en' }}"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>EcoPulse Dashboard</title><link rel="icon" type="image/svg+xml" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Crect width='64' height='64' rx='16' fill='%23062f2f'/%3E%3Cpath d='M35 6 18 34h11l-4 24 21-31H34z' fill='%23f59e0b'/%3E%3C/svg%3E"><link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css"><link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.0/font/bootstrap-icons.css"><style>*{margin:0;padding:0;box-sizing:border-box}body{background:linear-gradient(135deg, #667eea 0%, #764ba2 100%);min-height:100vh;font-family:'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;padding-top:80px;padding-bottom:30px}.navbar{background:linear-gradient(135deg, #667eea 0%, #764ba2 100%);box-shadow:0 5px 20px rgba(0,0,0,0.2)}.navbar-brand{font-weight:700;font-size:1.5rem}.header-section{text-align:center;margin-bottom:40px;color:white}.header-section h1{font-size:3rem;font-weight:700;margin-bottom:10px;text-shadow:2px 2px 4px rgba(0,0,0,0.3)}.role-badge{display:inline-block;padding:5px 15px;border-radius:20px;font-size:0.9rem;font-weight:600;margin-top:10px}.role-customer{background-color:#00b894;color:white}.role-admin{background-color:#ff6b6b;color:white}.role-examiner{background-color:#ff9800;color:white}.card{border:none;border-radius:15px;box-shadow:0 10px 30px rgba(0,0,0,0.2);margin-bottom:30px;transition:transform 0.3s ease, box-shadow 0.3s ease}.card:hover{transform:translateY(-5px);box-shadow:0 15px 40px rgba(0,0,0,0.3)}.card-header{border-radius:15px 15px 0 0;padding:20px;font-weight:600;font-size:1.2rem;display:flex;align-items:center;gap:10px;color:white}.card-header.bg-primary{background:linear-gradient(135deg, #667eea 0%, #764ba2 100%) !important}.card-header.bg-info{background:linear-gradient(135deg, #00d4ff 0%, #0099ff 100%) !important}.card-header.bg-warning{background:linear-gradient(135deg, #ffc107 0%, #ff9800 100%) !important}.card-header.bg-success{background:linear-gradient(135deg, #00b894 0%, #00cec9 100%) !important}.card-header.bg-secondary{background:linear-gradient(135deg, #6c757d 0%, #495057 100%) !important}.card-body{padding:30px}.stats-grid{display:grid;grid-template-columns:repeat(auto-fit, minmax(250px, 1fr));gap:20px;margin-bottom:30px}.stat-card{background:white;padding:20px;border-radius:10px;box-shadow:0 5px 15px rgba(0,0,0,0.1);text-align:center}.stat-value{font-size:2.5rem;font-weight:700;color:#667eea}.stat-label{color:#666;font-size:0.9rem;margin-top:10px}.stat-icon{font-size:2rem;margin-bottom:10px;color:#667eea}.form-control,.form-select{border-radius:8px;border:2px solid #e0e0e0;padding:12px 15px}.form-control:focus,.form-select:focus{border-color:#667eea;box-shadow:0 0 0 0.2rem rgba(102,126,234,0.25)}.btn{border-radius:8px;padding:10px 20px;font-weight:600;transition:all 0.3s ease}.btn-success{background:linear-gradient(135deg, #00b894 0%, #00cec9 100%);border:none;color:white}.btn-success:hover{background:linear-gradient(135deg, #00a884 0%, #00beb9 100%)}.btn-primary{background:linear-gradient(135deg, #667eea 0%, #764ba2 100%);border:none;color:white}.btn-warning{background:linear-gradient(135deg, #ffc107 0%, #ff9800 100%);border:none;color:white}.btn-danger{background:linear-gradient(135deg, #ff6b6b 0%, #ee5a6f 100%);border:none;color:white}.btn-sm{padding:5px 10px;font-size:0.875rem}.alert{border-radius:10px;border:none;margin-bottom:20px}.table{color:#333}.table thead{background:#f5f5f5;font-weight:600}.table tbody tr:hover{background-color:#f9f9f9}.no-data{text-align:center;padding:30px;color:#999;font-style:italic}.img-fluid{border-radius:10px;box-shadow:0 5px 15px rgba(0,0,0,0.1);max-width:100%;height:auto}.employee-info{background:rgba(255,255,255,0.1);padding:10px;border-radius:10px;margin-top:10px;color:white;font-size:0.9rem}.employee-info i{margin-right:5px}@media (max-width:768px){body{padding-top:100px}.header-section h1{font-size:2rem}.stats-grid{grid-template-columns:1fr}}</style></head><body><nav class="navbar navbar-expand-lg navbar-dark fixed-top"><div class="container"><a class="navbar-brand" href="{{ url_for('dashboard') }}"><i class="bi bi-lightning-fill"></i> EcoPulse</a><button class="navbar-toggler" type="button" data-bs-toggle="collapse" data-bs-target="#navbarNav"><span class="navbar-toggler-icon"></span></button><div class="collapse navbar-collapse" id="navbarNav"><ul class="navbar-nav ms-auto"><li class="nav-item"><a class="nav-link" href="{{ url_for('dashboard') }}"><i class="bi bi-house"></i> Dashboard</a></li><li class="nav-item"><a class="nav-link" href="{{ url_for('settings') }}"><i class="bi bi-gear"></i> Settings</a></li>{% if current_user.role == 'admin' %}<li class="nav-item"><a class="nav-link" href="{{ url_for('admin_financial') }}"><i class="bi bi-cash-stack"></i> Financial</a></li>{% endif %}{% if current_user.role == 'examiner' %}<li class="nav-item"><a class="nav-link" href="{{ url_for('examiner_dashboard') }}"><i class="bi bi-clipboard-data"></i> Examiner</a></li>{% endif %}<li class="nav-item dropdown"><a class="nav-link dropdown-toggle" href="#" id="navbarDropdown" role="button" data-bs-toggle="dropdown"><i class="bi bi-person-circle"></i> {{ current_user.username }}</a><ul class="dropdown-menu dropdown-menu-end"><li><a class="dropdown-item" href="{{ url_for('logout') }}"><i class="bi bi-box-arrow-right"></i> Logout</a></li></ul></li></ul></div></div></nav><div class="container"><div class="header-section"><h1><i class="bi bi-lightning-fill"></i> EcoPulse</h1><p>Welcome, {{ current_user.username }}!</p>{% if current_user.role == 'admin' %}<span class="role-badge role-admin"><i class="bi bi-shield-fill"></i> Administrator</span>{% elif current_user.role == 'examiner' %}<span class="role-badge role-examiner"><i class="bi bi-eye-fill"></i> Examiner</span>{% else %}<span class="role-badge role-customer"><i class="bi bi-person-fill"></i> Customer</span>{% endif %}{% if current_user.employee_id %}<div class="employee-info"><i class="bi bi-building"></i> Employee ID: {{ current_user.employee_id }} | <i class="bi bi-diagram-3"></i> {{ current_user.department or 'General' }}</div>{% endif %}</div>{% if message %}<div class="alert alert-success"><i class="bi bi-check-circle"></i> {{ message }}</div>{% endif %}{% if analytics %}<div class="stats-grid"><div class="stat-card"><div class="stat-icon"><i class="bi bi-lightning-charge"></i></div><div class="stat-label">Total</div><div class="stat-value">{{ analytics.total_kwh }}</div><small>kWh</small></div><div class="stat-card"><div class="stat-icon"><i class="bi bi-graph-up"></i></div><div class="stat-label">Average</div><div class="stat-value">{{ analytics.avg_kwh }}</div><small>kWh</small></div><div class="stat-card"><div class="stat-icon"><i class="bi bi-cash-coin"></i></div><div class="stat-label">Total Cost</div><div class="stat-value">{{ analytics.currency }} {{ analytics.total_cost }}</div><small>Est.</small></div><div class="stat-card"><div class="stat-icon"><i class="bi bi-cloud"></i></div><div class="stat-label">CO2</div><div class="stat-value">{{ analytics.total_co2 }}</div><small>kg</small></div></div>{% endif %}<div class="card"><div class="card-header bg-primary"><i class="bi bi-plus-circle"></i> Add Reading</div><div class="card-body"><form method="POST" action="{{ url_for('add_reading') }}"><div class="row"><div class="col-md-4 mb-3"><label class="form-label">Month</label><input type="text" name="date" class="form-control" placeholder="e.g. January" required></div><div class="col-md-4 mb-3"><label class="form-label">kWh</label><input type="number" name="kwh" class="form-control" placeholder="e.g. 520" step="0.01" required></div><div class="col-md-4 mb-3"><label class="form-label">Timestamp</label><input type="datetime-local" name="timestamp" class="form-control" required></div></div><button type="submit" class="btn btn-success"><i class="bi bi-check-circle"></i> Submit</button></form></div></div><div class="row mb-4"><div class="col-md-6"><div class="card"><div class="card-header bg-info"><i class="bi bi-funnel"></i> Filter</div><div class="card-body"><form method="GET" action="{{ url_for('dashboard') }}" class="row g-3"><div class="col-md-4"><label class="form-label">Start</label><input type="date" name="start_date" class="form-control"></div><div class="col-md-4"><label class="form-label">End</label><input type="date" name="end_date" class="form-control"></div><div class="col-md-4"><label class="form-label">Days</label><select name="days" class="form-select"><option value="">All</option><option value="7">7 days</option><option value="30">30 days</option><option value="90">90 days</option></select></div><div class="col-md-12 mt-2"><button type="submit" class="btn btn-primary w-100">Filter</button></div></form></div></div></div><div class="col-md-6"><div class="card"><div class="card-header bg-warning"><i class="bi bi-send"></i> Submit to Admin</div><div class="card-body text-center"><p>Submit your consumption summary to admin for verification and comparison</p><button class="btn btn-warning w-100" onclick="submitToAdmin()"><i class="bi bi-send"></i> Submit My Consumption</button></div></div></div></div><div class="card"><div class="card-header bg-warning"><i class="bi bi-bar-chart"></i> Consumption Analysis</div><div class="card-body">{% if chart %}<img src="data:image/png;base64,{{ chart }}" class="img-fluid" alt="Consumption Chart">{% else %}<p class="no-data">No chart available. Add some readings to see visualization.</p>{% endif %}</div></div><div class="card"><div class="card-header bg-secondary"><i class="bi bi-table"></i> Readings</div><div class="card-body">{% if readings %}<div class="table-responsive"><table class="table table-hover"><thead><tr><th>Period</th><th>kWh</th><th>Cost</th><th>CO2</th><th>Status</th><th>Timestamp</th><th>Actions</th></tr></thead><tbody>{% for reading in readings %}<tr><td><strong>{{ reading.date }}</strong></td><td><span class="badge {% if reading.kwh > current_user.threshold %}bg-danger{% else %}bg-success{% endif %}">{{ reading.kwh }}</span></td><td>{{ "%.2f"|format(reading.kwh * current_user.unit_cost) }}</td><td>{{ "%.2f"|format(reading.kwh * 0.385) }}</td><td>{% if reading.is_approved %}<span class="badge bg-success">Approved</span>{% elif reading.is_reviewed %}<span class="badge bg-info">Reviewed</span>{% else %}<span class="badge bg-warning">Pending</span>{% endif %}</td><td><small>{{ reading.timestamp.strftime('%Y-%m-%d %H:%M') }}</small></td><td><button class="btn btn-warning btn-sm" data-bs-toggle="modal" data-bs-target="#editModal{{ reading.id }}"><i class="bi bi-pencil"></i></button><form method="POST" action="{{ url_for('delete_reading', reading_id=reading.id) }}" style="display: inline;" onsubmit="return confirm('Delete?');"><button type="submit" class="btn btn-danger btn-sm"><i class="bi bi-trash"></i></button></form></td></tr><div class="modal fade" id="editModal{{ reading.id }}" tabindex="-1"><div class="modal-dialog"><div class="modal-content"><div class="modal-header"><h5 class="modal-title">Edit</h5><button type="button" class="btn-close" data-bs-dismiss="modal"></button></div><form method="POST" action="{{ url_for('update_reading', reading_id=reading.id) }}"><div class="modal-body"><div class="mb-3"><label class="form-label">Period</label><input type="text" name="date" class="form-control" value="{{ reading.date }}" required></div><div class="mb-3"><label class="form-label">kWh</label><input type="number" name="kwh" class="form-control" value="{{ reading.kwh }}" step="0.01" required></div><div class="mb-3"><label class="form-label">Timestamp</label><input type="datetime-local" name="timestamp" class="form-control" value="{{ reading.timestamp.strftime('%Y-%m-%dT%H:%M') }}" required></div></div><div class="modal-footer"><button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancel</button><button type="submit" class="btn btn-success">Update</button></div></form></div></div></div>{% endfor %}</tbody></table></div>{% else %}<p class="no-data">No readings yet. Add your first reading above.</p>{% endif %}</div></div><div class="card"><div class="card-header bg-success"><i class="bi bi-download"></i> Export</div><div class="card-body"><div class="row g-3"><div class="col-md-4"><a href="{{ url_for('export_csv') }}" class="btn btn-success w-100"><i class="bi bi-file-earmark-spreadsheet"></i> CSV</a></div><div class="col-md-4"><a href="{{ url_for('export_xlsx') }}" class="btn btn-primary w-100"><i class="bi bi-file-earmark-spreadsheet-fill"></i> Excel</a></div><div class="col-md-4"><a href="{{ url_for('export_pdf') }}" class="btn btn-danger w-100"><i class="bi bi-file-pdf"></i> PDF</a></div></div></div></div>{% if reports %}<div class="card"><div class="card-header bg-info"><i class="bi bi-envelope"></i> Recent Reports</div><div class="card-body"><div class="list-group">{% for report in reports %}<a href="#" class="list-group-item list-group-item-action"><div class="d-flex w-100 justify-content-between"><h6 class="mb-1">{{ report.title }}</h6><small>{{ report.created_at.strftime('%Y-%m-%d') }}</small></div><p class="mb-1">{{ report.content|safe }}</p></a>{% endfor %}</div></div></div>{% endif %}</div><script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script><script>const now=new Date();now.setMinutes(now.getMinutes()-now.getTimezoneOffset());const ts=document.querySelector('input[name="timestamp"]');if(ts)ts.value=now.toISOString().slice(0,16);function submitToAdmin(){fetch('/submit_to_admin',{method:'POST'}).then(r=>r.json()).then(d=>{alert(d.message);if(d.success){location.reload();}});}</script></body></html>"""

settings_template = """
<!DOCTYPE html>
<html lang="{{ current_user.language or 'en' }}">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Settings - EcoPulse</title>
    <link rel="icon" type="image/svg+xml" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Crect width='64' height='64' rx='16' fill='%23062f2f'/%3E%3Cpath d='M35 6 18 34h11l-4 24 21-31H34z' fill='%23f59e0b'/%3E%3C/svg%3E">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.0/font/bootstrap-icons.css">
    <style>
        body{background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);min-height:100vh;padding-top:80px;padding-bottom:30px}
        .navbar{background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);box-shadow:0 5px 20px rgba(0,0,0,.2)}
        .container{max-width:840px}.card{border:none;border-radius:15px;box-shadow:0 10px 30px rgba(0,0,0,.2)}
        .card-header{background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);color:#fff;padding:20px;font-weight:600}
        .card-body{padding:30px}.settings-section{margin-bottom:26px;padding-bottom:26px;border-bottom:2px solid #e5e7eb}
        .settings-section:last-child{border-bottom:none}.settings-title{font-size:1.15rem;font-weight:700;margin-bottom:16px}
    </style>
</head>
<body>
    <nav class="navbar navbar-expand-lg navbar-dark fixed-top">
        <div class="container">
            <a class="navbar-brand" href="{{ url_for('dashboard') }}"><i class="bi bi-lightning-fill"></i> EcoPulse</a>
            <div class="navbar-nav ms-auto"><a class="nav-link" href="{{ url_for('dashboard') }}"><i class="bi bi-arrow-left"></i> Back</a></div>
        </div>
    </nav>
    <div class="container">
        <div class="card">
            <div class="card-header"><i class="bi bi-gear"></i> Settings</div>
            <div class="card-body">
                {% if message %}<div class="alert alert-success">{{ message }}</div>{% endif %}
                <form method="POST">
                    <div class="settings-section">
                        <div class="settings-title"><i class="bi bi-person-circle"></i> Profile</div>
                        <div class="row">
                            <div class="col-md-6 mb-3"><label class="form-label">Username</label><input type="text" name="username" class="form-control" value="{{ current_user.username }}" required></div>
                            <div class="col-md-6 mb-3"><label class="form-label">Email</label><input type="email" name="email" class="form-control" value="{{ current_user.email }}" required></div>
                            <div class="col-md-6 mb-3"><label class="form-label">Preferred Language</label><select name="language" class="form-select">{% for code,label in language_options %}<option value="{{ code }}" {% if code == current_user.language %}selected{% endif %}>{{ label }}</option>{% endfor %}</select></div>
                            {% if current_user.role == 'customer' %}
                            <div class="col-md-6 mb-3">
                                <label class="form-label">Energy Source</label>
                                <select id="energySourceSelect" name="energy_source" class="form-select" onchange="syncEnergySourceFields()" required>
                                    {% for source in energy_sources %}
                                    <option value="{{ source }}" {% if source == selected_energy_source %}selected{% endif %}>{{ energy_source_labels[source] }}</option>
                                    {% endfor %}
                                </select>
                            </div>
                            <div class="col-md-6 mb-3" id="meterNumberGroup" style="display: {{ 'block' if selected_energy_source == 'KPLC' else 'none' }};">
                                <label class="form-label" id="meterNumberLabel">{% if selected_energy_source == 'KPLC' %}Energy Meter Number{% else %}Solar Asset Identifier{% endif %}</label>
                                <input id="meterNumberInput" type="text" name="meter_number" maxlength="11" class="form-control" value="{{ current_user.meter_number or '' }}" {% if selected_energy_source == 'KPLC' %}required{% endif %} placeholder="{% if selected_energy_source == 'KPLC' %}Enter your 11-digit meter number{% else %}Solar users do not need a KPLC meter number{% endif %}">
                            </div>
                            <div class="col-12 mb-3" id="solarHintRow" style="display: {{ 'none' if selected_energy_source == 'KPLC' else 'block' }};">
                                <div class="form-text text-muted">Solar customers do not need to enter a KPLC meter number; the system can keep your solar setup separate.</div>
                            </div>
                            <div class="col-md-6 mb-3"><label class="form-label">Country Code</label><select name="country_code" class="form-select" required>{% for item in phone_country_codes %}<option value="{{ item.code }}" {% if item.code == selected_country_code %}selected{% endif %}>{{ item.label }}</option>{% endfor %}</select></div>
                            <div class="col-md-6 mb-3"><label class="form-label">Phone Number</label><input type="text" name="phone_number" maxlength="10" class="form-control" value="{{ phone_number_local or '' }}" placeholder="10 digits"></div>
                            {% else %}
                            <div class="col-md-6 mb-3"><label class="form-label">Department</label><input type="text" name="department" class="form-control" value="{{ current_user.department or '' }}"></div>
                            {% endif %}
                        </div>
                    </div>
                    <div class="settings-section">
                        <div class="settings-title"><i class="bi bi-speedometer2"></i> Threshold Settings</div>
                        <div class="mb-3"><label class="form-label">Monthly Threshold (kWh)</label><input type="number" name="threshold" class="form-control" value="{{ current_user.threshold }}" step="10" required></div>
                    </div>
                    <div class="settings-section">
                        <div class="settings-title"><i class="bi bi-shield-check"></i> Protection</div>
                        <div class="form-check form-switch mb-3"><input class="form-check-input" type="checkbox" name="allow_overage" id="allowOverage" {% if user_settings.allow_overage %}checked{% endif %}><label class="form-check-label" for="allowOverage">Enable Auto-Switch to Overage Mode</label></div>
                        <div class="form-check form-switch mb-3"><input class="form-check-input" type="checkbox" name="auto_shutdown_enabled" id="autoShutdown" {% if user_settings.auto_shutdown_enabled %}checked{% endif %}><label class="form-check-label" for="autoShutdown">Enable Automatic Shutdown Reminders</label></div>
                        <div><label class="form-label">Shutdown Delay (minutes)</label><input type="number" name="shutdown_delay_minutes" class="form-control" value="{{ user_settings.shutdown_delay_minutes or 5 }}" min="1" max="60"></div>
                    </div>
                    <div class="settings-section">
                        <div class="settings-title"><i class="bi bi-bell"></i> Notifications</div>
                        <div class="form-check form-switch"><input class="form-check-input" type="checkbox" name="alert_email" id="alertEmail" {% if current_user.alert_email %}checked{% endif %}><label class="form-check-label" for="alertEmail">Email Alerts</label></div>
                    </div>
                    <div class="d-flex gap-3"><button type="submit" class="btn btn-primary">Save Settings</button><a href="{{ url_for('dashboard') }}" class="btn btn-secondary">Cancel</a></div>
                </form>
            </div>
        </div>
    </div>
    <script>
        function syncEnergySourceFields() {
            const source = document.getElementById('energySourceSelect');
            const meterGroup = document.getElementById('meterNumberGroup');
            const meterInput = document.getElementById('meterNumberInput');
            const meterLabel = document.getElementById('meterNumberLabel');
            const solarHintRow = document.getElementById('solarHintRow');
            if (!source || !meterGroup || !meterInput) return;
            const isKplc = source.value === 'KPLC';
            console.log('[EcoPulse] Settings energy source changed:', source.value, 'isKPLC=', isKplc);
            meterGroup.style.display = isKplc ? 'block' : 'none';
            meterGroup.classList.toggle('d-none', !isKplc);
            if (meterLabel) {
                meterLabel.textContent = isKplc ? 'Energy Meter Number' : 'Solar Asset Identifier';
            }
            meterInput.required = isKplc;
            meterInput.disabled = !isKplc;
            meterInput.placeholder = isKplc ? 'Enter your 11-digit meter number' : 'Solar users do not need a KPLC meter number';
            if (!isKplc) {
                meterInput.value = '';
            }
            if (solarHintRow) {
                solarHintRow.style.display = isKplc ? 'none' : 'block';
                solarHintRow.classList.toggle('d-none', isKplc);
            }
        }
        document.addEventListener('DOMContentLoaded', function() {
            const source = document.getElementById('energySourceSelect');
            if (source) source.addEventListener('change', syncEnergySourceFields);
            syncEnergySourceFields();
        });
    </script>
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
"""

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
            background: radial-gradient(circle at top left, rgba(255,255,255,0.26), transparent 24%), linear-gradient(135deg, #0f172a 0%, #1d4ed8 38%, #7c3aed 100%);
            min-height: 100vh;
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            padding-top: 70px;
            padding-bottom: 30px;
            overflow-x: hidden;
        }

        .hero-panel {
            background: linear-gradient(135deg, rgba(15,23,42,0.95), rgba(30,64,175,0.88));
            color: #fff;
            border-radius: 24px;
            padding: 24px;
            box-shadow: 0 20px 48px rgba(15,23,42,.24);
            border: 1px solid rgba(255,255,255,.16);
            margin-bottom: 20px;
        }

        .hero-kicker {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            background: rgba(255,255,255,.16);
            padding: 6px 12px;
            border-radius: 999px;
            font-size: .8rem;
            margin-bottom: 10px;
            backdrop-filter: blur(8px);
        }

        .hero-panel .header-section h1,
        .hero-panel .header-section p {
            color: #fff;
            text-shadow: 0 2px 10px rgba(15,23,42,.25);
        }

        .card {
            background: rgba(255,255,255,.97);
            border: 1px solid rgba(148,163,184,.18);
            box-shadow: 0 16px 36px rgba(15,23,42,.12);
        }

        .card:hover {
            transform: translateY(-2px);
            box-shadow: 0 22px 48px rgba(15,23,42,.16);
        }

        .card-header {
            letter-spacing: .01em;
        }

        .stat-card {
            background: linear-gradient(145deg, rgba(255,255,255,.98), rgba(248,250,252,.96));
            border: 1px solid rgba(148,163,184,.16);
            transition: transform .2s ease, box-shadow .2s ease;
        }

        .stat-card:hover {
            transform: translateY(-3px);
            box-shadow: 0 12px 24px rgba(15,23,42,.12);
        }

        .tariff-badge {
            background: linear-gradient(135deg, #ec4899 0%, #f59e0b 100%);
            color: #fff;
            border: 1px solid rgba(255,255,255,.22);
            box-shadow: 0 12px 28px rgba(244,114,182,.24);
        }

        .table thead th {
            background: linear-gradient(135deg, #eff6ff, #f8fafc);
            color: #334155;
        }

        .btn-warning, .btn-primary, .btn-success, .btn-danger {
            box-shadow: 0 10px 22px rgba(15,23,42,.12);
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
            background: #fffafa;
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
                    <a class="nav-link" href="{{ url_for('admin_financial') }}">
                        <i class="bi bi-shield-lock"></i> <span class="d-none d-sm-inline">Admin</span>
                    </a>
                    <a class="nav-link" href="{{ url_for('examiner_financial_center') }}">
                        <i class="bi bi-cash-stack"></i> <span class="d-none d-sm-inline">Finance Center</span>
                    </a>
                    <a class="nav-link" href="{{ url_for('hr_employee_records') }}">
                        <i class="bi bi-people"></i> <span class="d-none d-sm-inline">HR Manager</span>
                    </a>
                    <a class="nav-link" href="{{ url_for('ai_analysis') }}">
                        <i class="bi bi-robot"></i> <span class="d-none d-sm-inline">AI Analysis</span>
                    </a>
                    <a class="nav-link" href="{{ url_for('examiner_payroll_ui') }}">
                        <i class="bi bi-file-earmark-check"></i> <span class="d-none d-sm-inline">Payroll Approvals</span>
                    </a>
                    <a class="nav-link" href="{{ url_for('logout') }}">
                        <i class="bi bi-box-arrow-right"></i> <span class="d-none d-sm-inline">Logout</span>
                    </a>
                </div>
            </div>
        </div>
    </nav>

    <div class="container-fluid px-2 px-sm-3 px-md-4">
        <div class="header-section hero-panel">
            <span class="hero-kicker"><i class="bi bi-stars"></i> Live operations workspace</span>
            <h1><i class="bi bi-graph-up"></i> Examiner Dashboard</h1>
            <p>Review approved customer consumption, send invoices, and manage financial reporting with a calmer, more premium workflow.</p>
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
                    <i class="bi bi-tag"></i> <strong>Current Energy Tariff:</strong>
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
                        <a href="{{ url_for('export_financial_xlsx') }}" class="btn btn-primary btn-sm w-100 mb-2">
                            <i class="bi bi-file-earmark-spreadsheet-fill"></i> Export Excel
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

GAMIFICATION_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>EcoPoints & Rewards - EcoPulse</title>
    <link rel="icon" type="image/svg+xml" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Crect width='64' height='64' rx='16' fill='%23062f2f'/%3E%3Cpath d='M35 6 18 34h11l-4 24 21-31H34z' fill='%23f59e0b'/%3E%3C/svg%3E">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.0/font/bootstrap-icons.css">
    <style>
        body{background:linear-gradient(135deg, #667eea 0%, #764ba2 100%);min-height:100vh;padding-top:80px;font-family:'Segoe UI', sans-serif}
        .card{border:none;border-radius:15px;box-shadow:0 10px 30px rgba(0,0,0,0.2);margin-bottom:30px}
        .points-card{background:linear-gradient(135deg, #f9ca24 0%, #f0932b 100%);color:white}
        .badge-card{background:linear-gradient(135deg, #00b894 0%, #00cec9 100%);color:white}
        .level-card{background:linear-gradient(135deg, #6c5ce7 0%, #a363d9 100%);color:white}
        .stat-value{font-size:2.5rem;font-weight:700}
        .badge-icon{font-size:3rem;margin-bottom:10px}
        .leaderboard-table th{background:#f39c12;color:white}
        .post-card{transition:transform 0.3s}
        .post-card:hover{transform:translateY(-5px)}
        .like-btn{cursor:pointer}
        .daily-bonus-btn{background:linear-gradient(135deg,#f9ca24,#f0932b);border:none;padding:15px;font-weight:700}
    </style>
</head>
<body>
    <nav class="navbar navbar-expand-lg navbar-dark fixed-top" style="background:linear-gradient(135deg, #f39c12 0%, #e67e22 100%)">
        <div class="container">
            <a class="navbar-brand" href="{{ url_for('dashboard') }}"><i class="bi bi-trophy-fill"></i> EcoPulse Rewards</a>
            <div class="navbar-nav ms-auto">
                <a class="nav-link" href="{{ url_for('dashboard') }}"><i class="bi bi-house"></i> Dashboard</a>
                <a class="nav-link" href="{{ url_for('gamification_dashboard') }}"><i class="bi bi-gift"></i> Rewards</a>
                <a class="nav-link" href="{{ url_for('logout') }}"><i class="bi bi-box-arrow-right"></i> Logout</a>
            </div>
        </div>
    </nav>

    <div class="container">
        <div class="row g-4 mb-4">
            <div class="col-md-4">
                <div class="card points-card p-4 text-center">
                    <i class="bi bi-star-fill fs-1"></i>
                    <div class="stat-value">{{ eco_points.points }}</div>
                    <div>EcoPoints Earned</div>
                    <small>Keep saving to earn more!</small>
                </div>
            </div>
            <div class="col-md-4">
                <div class="card level-card p-4 text-center">
                    <i class="bi bi-arrow-up-circle-fill fs-1"></i>
                    <div class="stat-value">Level {{ eco_points.level }}</div>
                    <div>Your Eco Level</div>
                    <small>{{ 500 - (eco_points.points % 500) }} points to next level</small>
                </div>
            </div>
            <div class="col-md-4">
                <div class="card p-4 text-center" style="background:linear-gradient(135deg,#ff6b6b,#ee5a6f);color:white">
                    <i class="bi bi-fire fs-1"></i>
                    <div class="stat-value">{{ eco_points.streak_days }}</div>
                    <div>Day Streak!</div>
                    <button class="btn btn-light mt-2" onclick="claimDailyBonus()"><i class="bi bi-gift"></i> Claim Daily Bonus</button>
                </div>
            </div>
        </div>

        <!-- Badges Section -->
        <div class="card mb-4">
            <div class="card-header bg-warning text-white">
                <i class="bi bi-award"></i> Your Badges
            </div>
            <div class="card-body">
                <div class="row">
                    {% if badges %}
                        {% for badge in badges %}
                        <div class="col-md-3 col-6 mb-3 text-center">
                            <div class="badge-card p-3 rounded-3">
                                <i class="bi {{ badge.icon if badge.icon else 'bi-trophy' }} fs-1"></i>
                                <div class="fw-bold mt-2">{{ badge }}</div>
                            </div>
                        </div>
                        {% endfor %}
                    {% else %}
                        <div class="col-12 text-center text-muted">
                            <i class="bi bi-emoji-neutral fs-1"></i>
                            <p>No badges yet. Start saving energy to earn your first badge!</p>
                        </div>
                    {% endif %}
                </div>
            </div>
        </div>

        <!-- Leaderboard -->
        <div class="card mb-4">
            <div class="card-header bg-warning text-white">
                <i class="bi bi-bar-chart-steps"></i> Monthly Leaderboard
            </div>
            <div class="card-body">
                <div class="table-responsive">
                    <table class="table table-hover leaderboard-table">
                        <thead>
                            <tr><th>Rank</th><th>User</th><th>EcoPoints</th><th>Level</th></tr>
                        </thead>
                        <tbody>
                            {% for entry in leaderboard %}
                            <tr {% if entry.user_id == current_user.id %}class="table-warning"{% endif %}>
                                <td>{% if entry.rank == 1 %}🥇{% elif entry.rank == 2 %}🥈{% elif entry.rank == 3 %}🥉{% else %}#{{ entry.rank }}{% endif %}</td>
                                <td>{{ entry.user.username }}{% if entry.user_id == current_user.id %} <span class="badge bg-warning">You</span>{% endif %}</td>
                                <td>{{ entry.points }}</td>
                                <td>Level {{ ((entry.points // 500) + 1) }}</td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
                <div class="alert alert-info mt-3">
                    <i class="bi bi-info-circle"></i> You're in the top {{ comparison.percentile }}%! 
                    {% if comparison.points_to_next > 0 %}Only {{ comparison.points_to_next }} points to reach #1!{% endif %}
                </div>
            </div>
        </div>

        <!-- AI Optimal Time Predictor -->
        <div class="card mb-4">
            <div class="card-header bg-info text-white">
                <i class="bi bi-robot"></i> AI Energy Predictor
            </div>
            <div class="card-body">
                <div class="row">
                    <div class="col-md-6">
                        <label class="form-label">Select Appliance</label>
                        <select id="applianceType" class="form-select mb-3">
                            <option value="general">General Appliances</option>
                            <option value="laundry">Washing Machine / Dryer</option>
                            <option value="heating">Water Heater</option>
                            <option value="ac">Air Conditioner</option>
                        </select>
                        <button class="btn btn-info w-100" onclick="getOptimalTime()">
                            <i class="bi bi-clock-history"></i> Get Best Usage Time
                        </button>
                    </div>
                    <div class="col-md-6">
                        <div class="alert alert-success" id="optimalTimeResult">
                            <i class="bi bi-lightbulb"></i> Click "Get Best Usage Time" for AI recommendations
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <!-- Community Sharing -->
        <div class="card mb-4">
            <div class="card-header bg-success text-white">
                <i class="bi bi-people"></i> Community Success Stories
            </div>
            <div class="card-body">
                <button class="btn btn-success mb-3" data-bs-toggle="modal" data-bs-target="#shareModal">
                    <i class="bi bi-share"></i> Share Your Success Story
                </button>

                <div id="communityPosts">
                    {% for post in community_posts %}
                    <div class="card post-card mb-3">
                        <div class="card-body">
                            <div class="d-flex justify-content-between">
                                <h6 class="card-title">
                                    <i class="bi bi-person-circle"></i> {{ post.user.username }}
                                    <span class="badge bg-info">{{ post.post_type|replace('_', ' ')|title }}</span>
                                </h6>
                                <small class="text-muted">{{ post.created_at.strftime('%Y-%m-%d') }}</small>
                            </div>
                            <h5>{{ post.title }}</h5>
                            <p class="card-text">{{ post.content }}</p>
                            <div class="d-flex gap-3">
                                <span class="like-btn" onclick="likePost({{ post.id }})">
                                    <i class="bi bi-heart"></i> <span id="likes-{{ post.id }}">{{ post.likes }}</span>
                                </span>
                                <span><i class="bi bi-share"></i> Share</span>
                            </div>
                        </div>
                    </div>
                    {% endfor %}
                </div>
            </div>
        </div>

        <!-- Energy Saving Tips -->
        <div class="card mb-4">
            <div class="card-header bg-warning text-white">
                <i class="bi bi-lightbulb"></i> Energy Saving Tips
            </div>
            <div class="card-body">
                <div class="row">
                    {% for tip in energy_tips %}
                    <div class="col-md-6 mb-3">
                        <div class="border rounded-4 p-3 h-100">
                            <h6><i class="bi bi-check-circle-fill text-success"></i> {{ tip.title }}</h6>
                            <p class="text-muted small">{{ tip.content }}</p>
                            {% if tip.savings_estimate > 0 %}
                            <small class="text-success">💡 Save ~{{ tip.savings_estimate }} kWh/month</small>
                            {% endif %}
                        </div>
                    </div>
                    {% endfor %}
                </div>
            </div>
        </div>
    </div>

    <!-- Share Modal -->
    <div class="modal fade" id="shareModal" tabindex="-1">
        <div class="modal-dialog">
            <div class="modal-content">
                <div class="modal-header bg-success text-white">
                    <h5 class="modal-title"><i class="bi bi-share"></i> Share Your Success Story</h5>
                    <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                </div>
                <form method="POST" action="{{ url_for('share_success') }}">
                    <div class="modal-body">
                        <div class="mb-3">
                            <label class="form-label">Post Type</label>
                            <select name="post_type" class="form-select">
                                <option value="success_story">📖 Success Story</option>
                                <option value="tip">💡 Energy Saving Tip</option>
                                <option value="question">❓ Question</option>
                            </select>
                        </div>
                        <div class="mb-3">
                            <label class="form-label">Title</label>
                            <input type="text" name="title" class="form-control" required>
                        </div>
                        <div class="mb-3">
                            <label class="form-label">Your Story / Tip</label>
                            <textarea name="content" class="form-control" rows="4" required></textarea>
                        </div>
                        <div class="alert alert-info">
                            <i class="bi bi-star"></i> You'll earn 25 EcoPoints for sharing!
                        </div>
                    </div>
                    <div class="modal-footer">
                        <button type="submit" class="btn btn-success">Share & Earn Points</button>
                    </div>
                </form>
            </div>
        </div>
    </div>

    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script>
    <script>
        function claimDailyBonus() {
            fetch('/api/claim-daily-bonus', {method: 'POST'})
                .then(r => r.json())
                .then(data => {
                    if(data.success) {
                        alert(`🎉 You earned ${data.points} EcoPoints! Streak: ${data.streak} days`);
                        location.reload();
                    } else {
                        alert(data.message);
                    }
                });
        }

        function getOptimalTime() {
            const appliance = document.getElementById('applianceType').value;
            fetch('/api/optimal-time', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({appliance: appliance})
            })
            .then(r => r.json())
            .then(data => {
                document.getElementById('optimalTimeResult').innerHTML = `
                    <i class="bi bi-robot"></i> 🤖 AI Recommendation:<br>
                    <strong>${data.recommendation}</strong>
                `;
            });
        }

        function likePost(postId) {
            fetch(`/api/like-post/${postId}`, {method: 'POST'})
                .then(r => r.json())
                .then(data => {
                    if(data.success) {
                        document.getElementById(`likes-${postId}`).innerText = data.likes;
                    }
                });
        }
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
    {'title': 'Energy Monitoring', 'text': 'Real-time usage, savings, and device-level visibility to help customers reduce bills and improve efficiency.', 'icon': 'bi-speedometer2'},
    {'title': 'Billing & Tariffs', 'text': 'Transparent KPLC cost updates, tariff tracking, and easy-to-read billing summaries for every account.', 'icon': 'bi-wallet2'},
    {'title': 'HR Services', 'text': 'Recruitment, payroll, training, and compliance workflows designed for practical people operations.', 'icon': 'bi-people-fill'},
    {'title': 'Finance Oversight', 'text': 'Examiner dashboards for revenue tracking, cost analysis, and financial review across energy operations.', 'icon': 'bi-graph-up'},
    {'title': 'Community Support', 'text': 'Forums, FAQs, peer learning, and support resources to keep customers and staff connected.', 'icon': 'bi-chat-dots'}
]

PUBLIC_ABOUT = [
    {'title': 'Mission', 'text': 'To empower smarter energy use for a sustainable future through accessible IoT and people-centered workflows.'},
    {'title': 'Vision', 'text': 'A world where homes, businesses, and communities make energy decisions with confidence and care.'},
    {'title': 'History & Milestones', 'text': 'From launch to partnerships and first community deployments, EcoPulse has grown by combining practical energy insight with people-first support.'},
    {'title': 'Leadership & Partners', 'text': 'Our leadership team brings operations, energy, finance, and HR experience, supported by NGOs, schools, and business collaborations.'}
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
    {
        'title': 'Energy Operations Analyst',
        'text': 'Lead real-time usage monitoring, savings modeling, and energy efficiency programs for customers and operations teams.',
        'details': [
            'Build dashboards that turn meter data into actionable savings recommendations.',
            'Support customer and examiner workflows with live energy summaries and alert logic.',
            'Help teams translate usage trends into measurable performance goals.'
        ]
    },
    {
        'title': 'Billing & Tariff Specialist',
        'text': 'Manage transparent tariff updates, KPLC cost tracking, and billing workflows to keep customers informed and compliant.',
        'details': [
            'Maintain cost rates, tariff changes, and invoice summaries inside the platform.',
            'Support finance and admin teams with audit-ready billing reports.',
            'Communicate tariff impact clearly through customer-facing dashboards and notices.'
        ]
    },
    {
        'title': 'HR & Talent Coordinator',
        'text': 'Drive recruitment, payroll, training, and compliance processes through a secure people operations workflow.',
        'details': [
            'Route applications, track candidate status, and manage HR approvals.',
            'Keep payroll, training programs, and compliance documentation up to date.',
            'Shape career development and employee wellbeing for the EcoPulse team.'
        ]
    },
    {
        'title': 'Finance Oversight Analyst',
        'text': 'Support examiner and admin dashboards with revenue analysis, cost review, and financial controls.',
        'details': [
            'Review operational revenue, cost center activity, and examiner reports.',
            'Help the team balance energy savings goals with financial performance.',
            'Create executive-ready finance summaries for admin approvals.'
        ]
    },
    {
        'title': 'Community Support Lead',
        'text': 'Coordinate forums, FAQs, peer learning, and customer guidance so EcoPulse users stay connected and supported.',
        'details': [
            'Build support resources for energy questions, tariffs, and troubleshooting.',
            'Facilitate community knowledge-sharing and user success stories.',
            'Keep the support experience responsive, helpful, and grounded in real customer needs.'
        ]
    },
    {
        'title': 'Internships & Training',
        'text': 'Offer attachments, student internships, and graduate development programs across engineering, analytics, HR, and finance.',
        'details': [
            'Join hands-on projects in energy monitoring, platform analytics, and business operations.',
            'Learn through structured training, mentorship, and real-world product work.',
            'Build career growth with practical exposure to sustainability and enterprise workflows.'
        ]
    }
]

PUBLIC_NEWS = [
    {'title': 'System Updates', 'text': 'Latest feature releases, tariff updates, and HR policy improvements for EcoPulse users.'},
    {'title': 'Community Impact Stories', 'text': 'Customer and institution stories showing CO₂ saved, cost declines, and smart energy wins.'},
    {'title': 'Events & Announcements', 'text': 'Upcoming trainings, workshops, and sustainability drives that the EcoPulse community can join.'},
    {'title': 'Blog Articles', 'text': 'Practical energy tips, HR insights, and finance trends to help you stay ahead of change.'}
]

PUBLIC_FAQS = [
    {'title': 'How does EcoPulse predict future energy use?', 'text': 'EcoPulse analyzes consumption and appliance readings to make forecasting recommendations for customers and staff.'},
    {'title': 'How are tariffs and KPLC updates shown?', 'text': 'Billing and tariff changes appear in the platform with transparent unit costs and invoice summaries for each account.'},
    {'title': 'What HR support does EcoPulse provide?', 'text': 'EcoPulse supports recruitment workflows, payroll notifications, training plans, and compliance tracking for HR managers.'},
    {'title': 'How can I track finance and revenue?', 'text': 'Examiner dashboards give revenue snapshots, cost analysis, and audit-ready reports for operational finance review.'},
    {'title': 'Where can I get community support?', 'text': 'Use forums, FAQs, contact forms, and peer learning resources to get help and share energy-saving ideas.'}
]

PUBLIC_HOME_HIGHLIGHTS = [
    'Real-time energy monitoring',
    'Automated efficiency suggestions',
    'Business-grade analytics',
    'Sustainable living made simple'
]

PUBLIC_HOME_HIGHLIGHT_CARDS = [
    {
        'title': 'Live Platform Monitoring',
        'text': 'Visualize your energy flow, threshold status, and efficiency signals in real time.',
        'image': 'https://images.unsplash.com/photo-1516232504310-25c4a0cb2f9f?auto=format&fit=crop&w=1200&q=80'
    },
    {
        'title': 'AI Efficiency Insights',
        'text': 'Receive proactive efficiency alerts and smart recommendations when usage spikes.',
        'image': 'https://images.unsplash.com/photo-1509395176047-4a66953fd231?auto=format&fit=crop&w=1200&q=80'
    },
    {
        'title': 'Carbon Impact Goals',
        'text': 'Track emissions progress and tree-equivalent savings from your energy choices.',
        'image': 'https://images.unsplash.com/photo-1465101046530-73398c7f28ca?auto=format&fit=crop&w=1200&q=80'
    }
]

PUBLIC_HOME_STATS = [
    {'value': '24/7', 'label': 'Live monitoring for homes and teams'},
    {'value': 'AI', 'label': 'Guided efficiency suggestions'},
    {'value': 'Ksh', 'label': 'Revenue impact surfaced clearly'}
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
        .overview-panel { position: relative; overflow: hidden; }
        .overview-panel:before {
            content: '';
            position: absolute;
            inset: 0;
            background:
                linear-gradient(115deg, rgba(6,47,47,.88), rgba(15,118,110,.74)),
                url('https://images.unsplash.com/photo-1497436072909-60f360e1d4b1?auto=format&fit=crop&w=1800&q=80') center/cover no-repeat;
            z-index: 0;
        }
        .overview-panel > * { position: relative; z-index: 1; }
        footer { background: #041b1b; color: #d7ece8; }
        .assistant-scroll { max-height: 260px; overflow-y: auto; background: #f8fafc; border-radius: 16px; padding: 16px; border:1px solid rgba(15,23,42,.08); }
        .pledge-banner { position: fixed; bottom: 0; left: 0; right: 0; z-index: 1030; box-shadow: 0 -4px 20px rgba(0,0,0,0.1); }
        @media (max-width:767.98px) {
            .hero { padding: 108px 0 64px; min-height:auto; }
            .container { padding-left:18px; padding-right:18px; }
            .section-card, .assistant-card, .feature-poster { border-radius:22px; }
            .pledge-banner { position: static; margin-top: 2rem; }
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

                    <!-- Demo Video -->
                    <div class="mt-4 mb-4">
                        <div class="ratio ratio-16x9" style="max-width: 500px;">
                            <iframe src="https://www.youtube.com/embed/dQw4w9WgXcQ" title="EcoPulse Demo Video" allowfullscreen style="border-radius: 12px;"></iframe>
                        </div>
                        <p class="text-light small mt-2">Watch our 2-minute demo to see EcoPulse in action</p>
                    </div>

                    <!-- Role-based Action Buttons -->
                    <div class="d-flex flex-wrap gap-3 mt-4">
                        <a href="{{ url_for('register') }}" class="btn btn-warning btn-lg">
                            <i class="bi bi-person-plus"></i> Join as Customer
                        </a>
                        <a href="{{ url_for('login') }}" class="btn btn-outline-light btn-lg">
                            <i class="bi bi-graph-up"></i> Customer Dashboard
                        </a>
                        <button id="heroLanguageToggle" type="button" class="btn btn-outline-light btn-sm align-self-center">
                            Kiswahili / English
                        </button>
                    </div>

                    <!-- Impact Counter -->
                    <div class="row g-3 mt-4" id="impact-counters">
                        <div class="col-sm-3">
                            <div class="metric-tile text-center">
                                <div class="h4 mb-1" id="total-energy-saved">0</div>
                                <div class="small">kWh Saved</div>
                            </div>
                        </div>
                        <div class="col-sm-3">
                            <div class="metric-tile text-center">
                                <div class="h4 mb-1" id="users-onboarded">0</div>
                                <div class="small">Users Onboarded</div>
                            </div>
                        </div>
                        <div class="col-sm-3">
                            <div class="metric-tile text-center">
                                <div class="h4 mb-1" id="carbon-reduced">0</div>
                                <div class="small">CO₂ Reduced (tons)</div>
                            </div>
                        </div>
                        <div class="col-sm-3">
                            <div class="metric-tile text-center">
                                <div class="h4 mb-1" id="revenue-generated">0</div>
                                <div class="small">Revenue Generated (Ksh)</div>
                            </div>
                        </div>
                    </div>
                </div>
                <div class="col-lg-5 ms-auto">
                    <div class="card p-4 border-0 shadow-sm">
                        <h5 class="fw-bold">Quick Access</h5>
                        <div class="d-grid gap-2">
                            <a class="btn btn-dark" href="{{ url_for('login') }}">Customer Login / Signup</a>
                        </div>
                        <hr>
                        <h6 class="fw-bold mb-2">Live Impact</h6>
                        <div class="small">Energy saved: <strong>{{ "%.2f"|format(live_metrics.total_kwh) }} kWh</strong></div>
                        <div class="small">Active customers: <strong>{{ live_metrics.total_users }}</strong></div>
                        <div class="small">CO2 reduction: <strong>{{ "%.2f"|format(live_metrics.co2_kg) }} kg</strong></div>
                        <div class="small">Revenue generated: <strong>Ksh {{ "%.2f"|format(live_metrics.total_revenue) }}</strong></div>
                    </div>
                </div>
            </div>
        </div>
    </section>
    <section class="py-4">
        <div class="container">
            <div class="section-card card p-4">
                <div class="row g-4 align-items-center">
                    <div class="col-lg-7">
                        <h3 class="fw-bold mb-2">Interactive Demo Preview</h3>
                        <canvas id="homeTrendChart" height="120"></canvas>
                    </div>
                    <div class="col-lg-5">
                        <div class="border rounded-4 p-3 bg-light">
                            <div class="fw-semibold">Impact Counter</div>
                            <div class="mt-2">EcoPulse helped <strong>{{ live_metrics.total_users or 500 }}</strong> homes cut energy costs by <strong>{{ live_metrics.avg_savings_percent }}%</strong>.</div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </section>
    <section class="py-5">
        <div class="container">
            <div class="section-card card p-4 p-lg-5 mb-4 highlight-band overview-panel">
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
                                {% for card in PUBLIC_HOME_HIGHLIGHT_CARDS %}
                                <div class="col-sm-4">
                                    <div class="p-3 rounded-4 text-white" style="min-height:170px; background:url('{{ card.image }}') center/cover no-repeat; position:relative; overflow:hidden; box-shadow:0 20px 40px rgba(0,0,0,.18);">
                                        <div style="position:absolute; inset:0; background:linear-gradient(180deg,rgba(6,47,47,.45),rgba(15,118,110,.8));"></div>
                                        <div style="position:relative; z-index:1;">
                                            <small class="text-uppercase" style="letter-spacing:.08em; font-size:.78rem;">{{ card.title }}</small>
                                            <div class="fs-6 fw-bold mt-2">{{ card.text }}</div>
                                        </div>
                                    </div>
                                </div>
                                {% endfor %}
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
                <div class="col-sm-6 col-lg-4"><h6 class="text-uppercase">Contact</h6><p class="mb-1">support@ecopulse.local</p><p class="mb-1">+254 700 123 456</p><p class="mb-2">Kisii Town, Kenya</p></div>
            </div>
            <div class="d-flex justify-content-between align-items-center border-top border-secondary pt-3 mt-4 flex-wrap gap-2"><small>&copy;2026 EcoPulse. All rights reserved.</small><small>Committed to a green future</small></div>
        </div>
    </footer>
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <script>
        const trendCtx = document.getElementById('homeTrendChart');
        if (trendCtx) {
            new Chart(trendCtx, {
                type: 'line',
                data: {
                    labels: {{ live_metrics.trend_labels|tojson }},
                    datasets: [{ label: 'Sample kWh trend', data: {{ live_metrics.trend_values|tojson }}, borderColor: '#0f766e', backgroundColor: 'rgba(15,118,110,.12)', fill: true, tension: 0.35 }]
                },
                options: { responsive: true, maintainAspectRatio: false }
            });
        }

        const heroToggleBtn = document.getElementById('heroLanguageToggle');
        const heroBadge = document.querySelector('.hero .badge');
        const heroTitle = document.querySelector('.hero .display-4');
        const heroLead = document.querySelector('.hero .lead');
        const heroTranslations = {
            en: {
                badge: 'Smarter Energy, Greener Future',
                title: 'Smarter energy management for homes and businesses.',
                text: 'EcoPulse helps homes and businesses cut energy costs and reduce carbon footprints with smart IoT solutions.'
            },
            sw: {
                badge: 'Nishati Bora, Mazingira Bora',
                title: 'Usimamizi wa nishati kwa nyumba na biashara.',
                text: 'EcoPulse inasaidia nyumba na biashara kupunguza gharama za nishati na athari za kaboni kwa suluhisho mahiri za IoT.'
            }
        };
        let currentHeroLang = 'en';
        function updateHeroLanguage(lang) {
            const strings = heroTranslations[lang] || heroTranslations.en;
            if (heroBadge) heroBadge.textContent = strings.badge;
            if (heroTitle) heroTitle.textContent = strings.title;
            if (heroLead) heroLead.textContent = strings.text;
            if (heroToggleBtn) heroToggleBtn.textContent = lang === 'sw' ? 'English / Kiswahili' : 'Kiswahili / English';
            currentHeroLang = lang;
        }
        if (heroToggleBtn) {
            heroToggleBtn.addEventListener('click', () => updateHeroLanguage(currentHeroLang === 'en' ? 'sw' : 'en'));
        }
        updateHeroLanguage('en');

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

        // Load impact counters
        async function loadImpactCounters() {
            try {
                const response = await fetch('/api/impact_counters');
                const data = await response.json();
                document.getElementById('total-energy-saved').textContent = data.total_energy_saved || '0';
                document.getElementById('users-onboarded').textContent = data.users_onboarded || '0';
                document.getElementById('carbon-reduced').textContent = data.carbon_reduced || '0';
                const revenueNode = document.getElementById('revenue-generated');
                if (revenueNode) {
                    revenueNode.textContent = data.revenue_generated ? data.revenue_generated.toLocaleString() : '0';
                }
            } catch (error) {
                console.error('Failed to load impact counters:', error);
            }
        }

        // Load counters on page load
        loadImpactCounters();
    </script>

    <!-- Pledge Banner -->
    <div class="pledge-banner bg-success text-white py-4">
        <div class="container">
            <div class="row align-items-center">
                <div class="col-md-8">
                    <h4 class="mb-2"><i class="bi bi-tree"></i> Join Our Green Pledge</h4>
                    <p class="mb-0">Commit to reducing your energy consumption by 10% this year. Together, we can make a difference!</p>
                </div>
                <div class="col-md-4 text-end">
                    <button class="btn btn-light btn-lg" onclick="alert('Thank you for your commitment to sustainability!')">
                        <i class="bi bi-hand-thumbs-up"></i> I Pledge
                    </button>
                </div>
            </div>
        </div>
    </div>

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
    <nav class="navbar navbar-expand-lg navbar-dark fixed-top"><div class="container"><a class="navbar-brand fw-bold" href="{{ url_for('index') }}"><i class="bi bi-lightning-charge-fill"></i> EcoPulse</a><button class="navbar-toggler" type="button" data-bs-toggle="collapse" data-bs-target="#publicNav"><span class="navbar-toggler-icon"></span></button><div class="collapse navbar-collapse" id="publicNav"><div class="navbar-nav ms-auto align-items-lg-center gap-lg-2"><a class="nav-link" href="{{ url_for('index') }}">Home</a><a class="nav-link" href="{{ url_for('services') }}">Services</a><a class="nav-link" href="{{ url_for('careers') }}">Careers</a><a class="nav-link" href="{{ url_for('about') }}">About</a><a class="nav-link" href="{{ url_for('news') }}">News</a><a class="nav-link" href="{{ url_for('login') }}">Customer Login</a><a class="btn btn-outline-light ms-lg-2" href="{{ url_for('register') }}">Register</a></div></div></div></nav>
    <section class="hero"><div class="container"><div class="row align-items-end g-4"><div class="col-lg-8"><div class="d-flex align-items-center gap-3 mb-3"><div class="glass-chip"><i class="bi bi-stars"></i> {{ page_name }}</div><button id="heroLanguageToggle" type="button" class="btn btn-outline-light btn-sm">Kiswahili / English</button></div><h1 class="display-5 fw-bold">{{ hero_title }}</h1><p class="lead col-lg-10">{{ hero_text }}</p></div><div class="col-lg-4"><div class="hero-panel"><div class="small text-uppercase mb-2">EcoPulse Focus</div><div class="fw-semibold">Energy visibility, workflow clarity, and practical sustainability action.</div></div></div></div></div></section>
    <section class="py-5"><div class="container"><div class="row g-4">{% for section in sections %}<div class="col-md-6"><div class="card content-card p-4 p-lg-5 h-100"><div class="feature-icon"><i class="bi bi-lightning"></i></div><h4>{{ section.title }}</h4><p class="text-muted mb-0">{{ section.text }}</p></div></div>{% endfor %}</div></div></section>
    <footer class="py-5" style="background:#041b1b;color:#d7ece8"><div class="container"><div class="row g-4 align-items-start"><div class="col-md-5"><h5 class="mb-3">EcoPulse</h5><p class="mb-0 footer-note">Energy monitoring, workflow visibility, and responsive customer support.</p></div><div class="col-md-7"><div class="footer-grid d-flex flex-wrap gap-3 justify-content-md-end">{% for label, endpoint in footer_links %}<a href="{{ url_for(endpoint) }}">{{ label }}</a>{% endfor %}</div></div></div><div class="d-flex justify-content-between align-items-center border-top border-secondary pt-3 mt-4 flex-wrap gap-2"><small>&copy; 2026 EcoPulse. All rights reserved.</small><small class="footer-note">Committed to a green future</small></div></div></footer>
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script>
    <script>
        const heroToggleBtn = document.getElementById('heroLanguageToggle');
        const heroTitleEl = document.querySelector('.hero .display-5');
        const heroTextEl = document.querySelector('.hero .lead');
        const heroTitleEn = {{ hero_title|tojson|safe }};
        const heroTextEn = {{ hero_text|tojson|safe }};
        const heroTitleSw = {{ hero_title_sw|default(hero_title)|tojson|safe }};
        const heroTextSw = {{ hero_text_sw|default(hero_text)|tojson|safe }};
        let currentHeroLang = 'en';

        function setHeroLanguage(lang) {
            if (!heroTitleEl || !heroTextEl || !heroToggleBtn) return;
            heroTitleEl.textContent = lang === 'sw' ? heroTitleSw : heroTitleEn;
            heroTextEl.textContent = lang === 'sw' ? heroTextSw : heroTextEn;
            heroToggleBtn.textContent = lang === 'sw' ? 'English / Kiswahili' : 'Kiswahili / English';
            currentHeroLang = lang;
        }

        if (heroToggleBtn) {
            heroToggleBtn.addEventListener('click', () => {
                setHeroLanguage(currentHeroLang === 'en' ? 'sw' : 'en');
            });
        }

        setHeroLanguage('en');
    </script>
</body>
</html>
"""

careers_page_template = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Careers at EcoPulse</title>
    <link rel="icon" type="image/svg+xml" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Crect width='64' height='64' rx='16' fill='%23062f2f'/%3E%3Cpath d='M35 6 18 34h11l-4 24 21-31H34z' fill='%23f59e0b'/%3E%3C/svg%3E">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.0/font/bootstrap-icons.css">
    <style>
        body { margin:0; font-family:'Source Sans 3',sans-serif; background:#f2f8f7; color:#102a2a; }
        .navbar { background: rgba(6,47,47,.92); backdrop-filter: blur(12px); }
        .hero { padding:100px 0 70px; background: linear-gradient(135deg,#0f766e,#0f4c57); color:#fff; }
        .hero h1 { font-size: clamp(2.5rem, 4vw, 4rem); }
        .card { border-radius: 24px; box-shadow:0 18px 50px rgba(15,23,42,.12); }
        .accordion-button:not(.collapsed) { color:#0f4c57; background:#def7ec; }
        .hero p, .section-description { color:rgba(255,255,255,.87); }
        .badge-hr { background:#f59e0b; color:#0f172a; }
        .resume-note { font-size:0.9rem; color:#475569; }
    </style>
</head>
<body>
    <nav class="navbar navbar-expand-lg navbar-dark fixed-top">
        <div class="container">
            <a class="navbar-brand fw-bold" href="{{ url_for('index') }}"><i class="bi bi-lightning-charge-fill"></i> EcoPulse</a>
            <button class="navbar-toggler" type="button" data-bs-toggle="collapse" data-bs-target="#publicNav"><span class="navbar-toggler-icon"></span></button>
            <div class="collapse navbar-collapse" id="publicNav">
                <div class="navbar-nav ms-auto align-items-lg-center gap-lg-2">
                    <a class="nav-link" href="{{ url_for('index') }}">Home</a>
                    <a class="nav-link" href="{{ url_for('services') }}">Services</a>
                    <a class="nav-link active" href="{{ url_for('careers') }}">Careers</a>
                    <a class="nav-link" href="{{ url_for('about') }}">About</a>
                    <a class="nav-link" href="{{ url_for('news') }}">News</a>
                    <a class="nav-link" href="{{ url_for('login') }}">Login</a>
                </div>
            </div>
        </div>
    </nav>

    <section class="hero">
        <div class="container">
            <div class="row align-items-end">
                <div class="col-lg-8">
                    <span class="badge bg-light text-dark mb-3">Join Our Team</span>
                    <h1>Careers at EcoPulse</h1>
                    <p class="lead">Apply to open roles, internship programs, and opportunities to build sustainability-driven IoT and energy analytics products.</p>
                </div>
                <div class="col-lg-4 text-lg-end">
                    {% if hr_manager %}
                    <div class="badge badge-hr py-2 px-3">HR Manager: {{ hr_manager.username }}</div>
                    {% else %}
                    <div class="badge bg-secondary py-2 px-3">HR Manager not assigned yet</div>
                    {% endif %}
                </div>
            </div>
        </div>
    </section>

    <section class="py-5">
        <div class="container">
            <div class="row gy-4">
                <div class="col-lg-7">
                    <div class="card p-4">
                        <h2 class="mb-3">Open positions & internships</h2>
                        <p class="section-description">Click each role to read more and submit your application directly to the assigned Human Resources manager. All applications are routed online to the active HR lead.</p>
                        <div class="accordion" id="careerAccordion">
                            {% for item in PUBLIC_CAREERS %}
                            <div class="accordion-item">
                                <h2 class="accordion-header" id="heading{{ loop.index }}">
                                    <button class="accordion-button collapsed" type="button" data-bs-toggle="collapse" data-bs-target="#collapse{{ loop.index }}" aria-expanded="false" aria-controls="collapse{{ loop.index }}">
                                        {{ item.title }}
                                    </button>
                                </h2>
                                <div id="collapse{{ loop.index }}" class="accordion-collapse collapse" aria-labelledby="heading{{ loop.index }}" data-bs-parent="#careerAccordion">
                                    <div class="accordion-body">
                                        <p>{{ item.text }}</p>
                                        {% if item.details %}
                                        <ul class="list-unstyled mb-3">
                                            {% for detail in item.details %}
                                            <li class="mb-2"><i class="bi bi-check-circle-fill text-success me-2"></i>{{ detail }}</li>
                                            {% endfor %}
                                        </ul>
                                        {% endif %}
                                        <a href="#careersApplicationForm" class="btn btn-sm btn-outline-primary">Apply for this role</a>
                                    </div>
                                </div>
                            </div>
                            {% endfor %}
                        </div>
                    </div>
                </div>
                <div class="col-lg-5">
                    <div class="card p-4 mb-4">
                        <h3>Confidential talent channels</h3>
                        <p class="section-description mb-3">To protect privacy, details about HR and department assignments are managed internally and are not shown on the public careers page.</p>
                        <p class="text-muted small">HR controls recruitment, role assignment, team placement, and access permissions. Open roles are shown here, and candidate placements are determined confidentially after application review.</p>
                    </div>
                    <div class="card p-4">
                        <h3>Application routing</h3>
                        <p class="section-description">Applications are handled by our HR team and delivered securely to the assigned HR manager.</p>
                        {% if hr_manager %}
                        <p><strong>{{ hr_manager.username }}</strong><br><a href="mailto:{{ hr_manager.email }}">{{ hr_manager.email }}</a></p>
                        <p class="text-muted small">Applications are reviewed by HR before internal department placement.</p>
                        {% else %}
                        <p class="text-muted">No HR manager is assigned yet. An administrator can assign the HR lead in department management.</p>
                        {% endif %}
                    </div>
                </div>
            </div>
        </div>
    </section>

    <section class="py-5 bg-white">
        <div class="container">
            <div class="card p-4">
                <h2 class="mb-3">Submit your application</h2>
                {% if application_success %}
                <div class="alert alert-success">{{ application_success }}</div>
                {% endif %}
                {% if application_error %}
                <div class="alert alert-danger">{{ application_error }}</div>
                {% endif %}
                <form id="careersApplicationForm" method="POST" enctype="multipart/form-data">
                    <div class="row g-3">
                        <div class="col-md-6">
                            <label class="form-label">Full name</label>
                            <input type="text" name="name" class="form-control" value="{{ request.form.get('name', '') }}" required>
                        </div>
                        <div class="col-md-6">
                            <label class="form-label">Email address</label>
                            <input type="email" name="email" class="form-control" value="{{ request.form.get('email', '') }}" required>
                        </div>
                        <div class="col-md-6">
                            <label class="form-label">Position</label>
                            <select name="position" class="form-select" required>
                                <option value="">Select a role</option>
                                {% for item in PUBLIC_CAREERS %}
                                <option value="{{ item.title }}" {% if request.form.get('position') == item.title %}selected{% endif %}>{{ item.title }}</option>
                                {% endfor %}
                            </select>
                        </div>
                        <div class="col-md-6">
                            <label class="form-label">Department interest</label>
                            <select name="department_interest" class="form-select">
                                <option value="">General Inquiry</option>
                                {% for dept in departments %}
                                <option value="{{ dept.name }}" {% if request.form.get('department_interest') == dept.name %}selected{% endif %}>{{ dept.name }}</option>
                                {% endfor %}
                            </select>
                        </div>
                        <div class="col-12">
                            <label class="form-label">Why are you a great fit?</label>
                            <textarea name="message" class="form-control" rows="5" required>{{ request.form.get('message', '') }}</textarea>
                        </div>
                        <div class="col-md-8">
                            <label class="form-label">Upload resume or portfolio</label>
                            <input type="file" name="resume" class="form-control">
                            <div class="resume-note">Optional. Accepted file types: PDF, DOC, DOCX. Max 2 MB.</div>
                        </div>
                        <div class="col-md-4 d-flex align-items-end">
                            <button type="submit" class="btn btn-primary w-100">Send Application</button>
                        </div>
                        <div class="col-12">
                            <p class="small text-muted mt-2">Your submission will be sent directly online to the assigned HR manager and you will receive an email confirmation when it is received.</p>
                        </div>
                    </div>
                </form>
            </div>
        </div>
    </section>

    <footer class="py-4 bg-dark text-white">
        <div class="container text-center">
            <p class="mb-0">&copy; 2026 EcoPulse. All rights reserved.</p>
        </div>
    </footer>

    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
"""

hr_applications_template = """
<!DOCTYPE html>
<html lang="{{ current_user.language or 'en' }}">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>HR Application Inbox</title>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css">
</head>
<body class="bg-light">
    <div class="container py-5">
        <div class="mb-4">
            <h1 class="h3">HR Application Inbox</h1>
            <p class="text-muted">Review submitted job applications and download resumes for follow-up. This page is restricted to HR personnel and administrators.</p>
            <a class="btn btn-outline-secondary btn-sm" href="{{ url_for('dashboard') }}">Back</a>
            <a class="btn btn-outline-primary btn-sm ms-2" href="{{ url_for('hr_employee_records') }}">Employee Records</a>
        </div>

        {% if applications %}
        <div class="table-responsive">
            <table class="table table-striped align-middle">
                <thead>
                    <tr>
                        <th>Submitted</th>
                        <th>Name</th>
                        <th>Position</th>
                        <th>Department</th>
                        <th>HR Manager</th>
                        <th>Resume</th>
                    </tr>
                </thead>
                <tbody>
                    {% for application in applications %}
                    <tr>
                        <td>{{ application.created_at.strftime('%Y-%m-%d %H:%M') }}</td>
                        <td>{{ application.name }}<br><small>{{ application.email }}</small></td>
                        <td>{{ application.position }}</td>
                        <td>{{ application.department_interest }}</td>
                        <td>{{ application.assigned_hr.username if application.assigned_hr else 'Unassigned' }}</td>
                        <td>
                            {% if application.resume_filename %}
                            <a href="{{ url_for('download_application_resume', application_id=application.id) }}" class="btn btn-sm btn-primary">Download</a>
                            {% else %}
                            <span class="text-muted">No file</span>
                            {% endif %}
                        </td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
        {% else %}
        <div class="alert alert-info">No applications have been submitted yet.</div>
        {% endif %}
    </div>
</body>
</html>
"""

career_success_template = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Application Received - EcoPulse</title>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css">
</head>
<body class="bg-light">
    <div class="container py-5">
        <div class="row justify-content-center">
            <div class="col-lg-8">
                <div class="card shadow-sm">
                    <div class="card-body text-center">
                        {% if applicant_name %}
                        <h1 class="display-6 mb-3">Thank you, {{ applicant_name }}!</h1>
                        <p class="lead mb-3">Your application is on its way to EcoPulse HR.</p>
                        {% else %}
                        <h1 class="display-6 mb-3">Application received</h1>
                        <p class="lead mb-3">Thank you for applying to EcoPulse.</p>
                        {% endif %}
                        {% if applied_position %}
                        <p class="mb-2">You applied for: <strong>{{ applied_position }}</strong></p>
                        {% endif %}
                        {% if department_interest %}
                        <p class="mb-2">Department interest: <strong>{{ department_interest }}</strong></p>
                        {% endif %}
                        <p>Your application has been sent directly to our current HR manager{% if hr_manager %}, <strong>{{ hr_manager.username }}</strong>{% endif %}.</p>
                        <p>If you attached a resume, it has been received successfully and will be reviewed as part of your application.</p>
                        <div class="d-grid gap-2 mt-4">
                            <a href="{{ url_for('careers') }}" class="btn btn-primary">Return to Careers</a>
                            <a href="{{ url_for('index') }}" class="btn btn-outline-secondary">Back to Home</a>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>
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
    <nav class="navbar navbar-expand-lg navbar-dark fixed-top"><div class="container"><a class="navbar-brand fw-bold" href="{{ url_for('index') }}"><i class="bi bi-lightning-charge-fill"></i> EcoPulse</a><button class="navbar-toggler" type="button" data-bs-toggle="collapse" data-bs-target="#contactNav"><span class="navbar-toggler-icon"></span></button><div class="collapse navbar-collapse" id="contactNav"><div class="navbar-nav ms-auto align-items-lg-center gap-lg-2"><a class="nav-link" href="{{ url_for('index') }}">Home</a><a class="nav-link" href="{{ url_for('login') }}">Customer Login</a><a class="btn btn-outline-light ms-lg-2" href="{{ url_for('register') }}">Register</a></div></div></div></nav>
    <section class="hero"><div class="container"><div class="row g-4 align-items-end"><div class="col-lg-8"><span class="badge text-bg-light text-dark mb-3">Contact</span><h1 class="display-5 fw-bold">Get in touch with EcoPulse</h1><p class="lead">Use the contact information below for customer support, deployments, and partnership discussions.</p></div><div class="col-lg-4"><div class="card p-4 text-dark"><div class="small text-uppercase text-muted mb-2">Support Promise</div><div class="fw-semibold">We respond with practical guidance for billing, thresholds, workflows, and platform questions.</div></div></div></div></div></section>
    <section class="py-5"><div class="container"><div class="row g-4"><div class="col-lg-5"><div class="card p-4 p-lg-5 h-100"><h3 class="mb-4">Contact details</h3><div class="detail-row"><div class="detail-icon"><i class="bi bi-envelope"></i></div><div><strong>Email</strong><div class="text-muted">support@ecopulse.local</div></div></div><div class="detail-row"><div class="detail-icon"><i class="bi bi-telephone"></i></div><div><strong>Phone</strong><div class="text-muted">+254 700 123 456</div></div></div><div class="detail-row"><div class="detail-icon"><i class="bi bi-geo-alt"></i></div><div><strong>Office</strong><div class="text-muted">EcoPulse Centre, Kisii Town, Kenya</div></div></div><div class="detail-row"><div class="detail-icon"><i class="bi bi-clock"></i></div><div><strong>Hours</strong><div class="text-muted">Monday to Saturday, 8:00 AM to 6:00 PM</div></div></div>{% if contact_success %}<div class="alert alert-info mt-4 mb-0">{{ contact_success }}</div>{% endif %}</div></div><div class="col-lg-7"><div class="card p-4 p-lg-5 mb-4"><h3>Send a message</h3><form method="POST" class="row g-3 mt-1"><div class="col-md-6"><label class="form-label">Name</label><input class="form-control" name="name" required></div><div class="col-md-6"><label class="form-label">Email</label><input class="form-control" type="email" name="email" required></div><div class="col-12"><label class="form-label">Subject</label><input class="form-control" name="subject" required></div><div class="col-12"><label class="form-label">Message</label><textarea class="form-control" name="message" rows="5" required></textarea></div><div class="col-12"><button class="btn btn-dark" type="submit">Send Message</button></div></form></div><iframe class="w-100 map-frame" loading="lazy" src="https://www.google.com/maps?q=Kisii%20Town%20Kenya&z=13&output=embed"></iframe></div></div><div class="d-flex justify-content-between align-items-center border-top pt-3 mt-4 flex-wrap gap-2"><small>&copy; 2026 EcoPulse. All rights reserved.</small><small class="footer-note">Committed to a green future</small></div></div></section>
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
"""

customer_dashboard_template_v2 = """
<!DOCTYPE html>
<html lang="{{ current_user.language or 'en' }}">
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
                    <li class="nav-item"><a class="nav-link" href="{{ url_for('gamification_dashboard') }}"><i class="bi bi-trophy"></i> Rewards</a></li>
                </ul>
            </div>
        </div>
    </nav>
    <div id="liveToastStack" class="toast-container position-fixed top-0 end-0 p-3" style="z-index:1080;margin-top:84px;"></div>

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
                    {% if selected_energy_source == 'KPLC' %}
                    <span class="badge text-bg-light text-dark"><i class="bi bi-qr-code"></i> Meter {{ current_user.meter_number }}</span>
                    {% else %}
                    <span class="badge text-bg-light text-dark"><i class="bi bi-sun"></i> Solar Mode</span>
                    {% endif %}
                    <span class="badge text-bg-light text-dark"><i class="bi bi-lightning"></i> {{ energy_source_label }}</span>
                    <span class="badge text-bg-warning"><i class="bi bi-shield-check"></i> {{ 'Overage enabled' if user_settings.allow_overage else 'Protect mode' }}</span>
                    {% if current_tariff %}<span class="badge text-bg-info text-dark"><i class="bi bi-tag"></i> {{ current_tariff.energy_source_label }} Ksh {{ "%.2f"|format(current_tariff.cost_per_unit) }}/unit</span>{% endif %}
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

        <!-- Personalized Intelligence & Community Summary -->
        <div class="row g-4 mb-4">
            <div class="col-lg-6">
                <div class="card p-4 h-100">
                    <div class="section-head mb-3">
                        <h3 class="h5 fw-bold mb-0"><i class="bi bi-lightbulb-fill"></i> Personalized Tips</h3>
                        <a href="{{ url_for('ai_analysis') }}" class="btn btn-sm btn-outline-dark"><i class="bi bi-arrow-right-circle"></i> Full Insights</a>
                    </div>
                    {% for tip in energy_tips[:5] %}
                        <div class="mb-3 p-3 rounded-4" style="background:rgba(15,118,110,.05);">
                            <div class="d-flex justify-content-between align-items-start mb-2">
                                <strong>{{ tip.title }}</strong>
                                <span class="badge bg-success">Save {{ tip.potential_savings }}%</span>
                            </div>
                            <p class="mb-0 text-muted">{{ tip.content }}</p>
                        </div>
                    {% endfor %}
                    <button onclick="getMoreRecommendations()" class="btn btn-dark btn-sm"><i class="bi bi-magic"></i> Get More Recommendations</button>
                </div>
            </div>
            <div class="col-lg-6">
                <div class="row g-4">
                    <div class="col-sm-6">
                        <div class="card surface p-4 h-100 text-center">
                            <i class="bi bi-trophy fs-1 text-warning"></i>
                            <small class="text-muted mt-2">Eco Points</small>
                            <h3 class="fw-bold mb-0">{{ eco_points.points }}</h3>
                            <div class="small text-muted">Level {{ eco_points.level }}</div>
                            <div class="small text-muted">Streak: {{ eco_points.streak_days }} days</div>
                        </div>
                    </div>
                    <div class="col-sm-6">
                        <div class="card surface p-4 h-100 text-center">
                            <i class="bi bi-people fs-1 text-primary"></i>
                            <small class="text-muted mt-2">Community Comparison</small>
                            <h3 class="fw-bold mb-0">{{ community_comparison.customer_count }} homes</h3>
                            <div class="small text-muted">Avg {{ community_comparison.average_kwh }} kWh</div>
                            <div class="small text-muted">Your rank: {{ community_comparison.efficiency_rank }}%</div>
                        </div>
                    </div>
                    <div class="col-12">
                        <div class="card p-4 h-100">
                            <div class="d-flex justify-content-between align-items-center mb-3">
                                <div>
                                    <h3 class="h6 fw-bold mb-1">Forecast Summary</h3>
                                    <small class="text-muted">7-day energy trend</small>
                                </div>
                                <span class="badge text-bg-light text-dark">Risk: {{ forecast_summary.peak_risk }}</span>
                            </div>
                            <div class="d-flex flex-wrap gap-3">
                                <div class="p-3 rounded-4" style="background:rgba(15,118,110,.05);min-width:150px;">
                                    <small class="text-muted">Next 7 days</small>
                                    <div class="fs-4 fw-bold">{{ forecast_summary.next_week_total }} kWh</div>
                                </div>
                                <div class="p-3 rounded-4" style="background:rgba(255,238,88,.12);min-width:150px;">
                                    <small class="text-muted">Trend</small>
                                    <div class="fs-4 fw-bold">{{ forecast_summary.trend }}</div>
                                </div>
                                <div class="p-3 rounded-4" style="background:rgba(249,115,22,.12);min-width:150px;">
                                    <small class="text-muted">Subscription</small>
                                    <div class="fs-4 fw-bold">{{ subscription.plan }}</div>
                                </div>
                            </div>
                            <div class="mt-3 small text-muted">
                                Your household is performing {{ community_comparison.efficiency_rank }}% better than the local average.
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <!-- Subscription Management -->
        <div class="row g-4 mb-4">
            <div class="col-12">
                <div class="card p-4">
                    <div class="d-flex justify-content-between align-items-center mb-3">
                        <div>
                            <h3 class="h5 fw-bold mb-1"><i class="bi bi-star"></i> Subscription Management</h3>
                            <small class="text-muted">Upgrade your plan to unlock more features</small>
                        </div>
                        <span class="badge text-bg-primary">{{ subscription.plan }} Plan</span>
                    </div>
                    <div class="row g-4">
                        <div class="col-md-3">
                            <div class="card h-100 {% if subscription.plan == 'Free' %}border-primary{% endif %}">
                                <div class="card-body text-center">
                                    <h5 class="card-title">Free</h5>
                                    <h3 class="text-success">Ksh 0</h3>
                                    <small class="text-muted">/month</small>
                                    <ul class="list-unstyled mt-3 small">
                                        <li>✓ Basic dashboard</li>
                                        <li>✓ Manual readings</li>
                                        <li>✓ Weekly summary</li>
                                    </ul>
                                    {% if subscription.plan == 'Free' %}
                                        <span class="badge bg-success">Current Plan</span>
                                    {% endif %}
                                </div>
                            </div>
                        </div>
                        <div class="col-md-3">
                            <div class="card h-100 {% if subscription.plan == 'Basic' %}border-primary{% endif %}">
                                <div class="card-body text-center">
                                    <h5 class="card-title">Basic</h5>
                                    <h3 class="text-success">Ksh 299</h3>
                                    <small class="text-muted">/month</small>
                                    <ul class="list-unstyled mt-3 small">
                                        <li>✓ Real-time charts</li>
                                        <li>✓ Daily tips</li>
                                        <li>✓ CSV export</li>
                                        <li>✓ Mobile app</li>
                                    </ul>
                                    {% if subscription.plan == 'Basic' %}
                                        <span class="badge bg-success">Current Plan</span>
                                    {% else %}
                                        <button onclick="upgradeSubscription('basic')" class="btn btn-primary btn-sm mt-2">Upgrade</button>
                                    {% endif %}
                                </div>
                            </div>
                        </div>
                        <div class="col-md-3">
                            <div class="card h-100 {% if subscription.plan == 'Pro' %}border-primary{% endif %}">
                                <div class="card-body text-center">
                                    <h5 class="card-title">Pro</h5>
                                    <h3 class="text-success">Ksh 799</h3>
                                    <small class="text-muted">/month</small>
                                    <ul class="list-unstyled mt-3 small">
                                        <li>✓ Advanced analytics</li>
                                        <li>✓ Forecasting</li>
                                        <li>✓ Community sharing</li>
                                        <li>✓ API access</li>
                                    </ul>
                                    {% if subscription.plan == 'Pro' %}
                                        <span class="badge bg-success">Current Plan</span>
                                    {% else %}
                                        <button onclick="upgradeSubscription('pro')" class="btn btn-primary btn-sm mt-2">Upgrade</button>
                                    {% endif %}
                                </div>
                            </div>
                        </div>
                        <div class="col-md-3">
                            <div class="card h-100 {% if subscription.plan == 'Enterprise' %}border-primary{% endif %}">
                                <div class="card-body text-center">
                                    <h5 class="card-title">Enterprise</h5>
                                    <h3 class="text-success">Ksh 2,999</h3>
                                    <small class="text-muted">/month</small>
                                    <ul class="list-unstyled mt-3 small">
                                        <li>✓ All Pro features</li>
                                        <li>✓ Unlimited devices</li>
                                        <li>✓ Priority support</li>
                                        <li>✓ Custom integrations</li>
                                    </ul>
                                    {% if subscription.plan == 'Enterprise' %}
                                        <span class="badge bg-success">Current Plan</span>
                                    {% else %}
                                        <button onclick="upgradeSubscription('enterprise')" class="btn btn-primary btn-sm mt-2">Upgrade</button>
                                    {% endif %}
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <!-- User Type Selection and Chore Scheduling -->
        <div class="row g-4 mb-4">
            <div class="col-lg-6">
                <div class="card p-4 h-100">
                    <h3 class="h5 fw-bold mb-3"><i class="bi bi-house-door"></i> Account Type</h3>
                    <p class="text-muted mb-3">Select whether you're using EcoPulse for your smart home or business to get tailored recommendations.</p>
                    <div class="d-flex gap-2">
                        <button onclick="setUserType('smart_home')" class="btn {% if user_type == 'smart_home' %}btn-dark{% else %}btn-outline-dark{% endif %} flex-fill">
                            <i class="bi bi-house"></i> Smart Home
                        </button>
                        <button onclick="setUserType('business')" class="btn {% if user_type == 'business' %}btn-dark{% else %}btn-outline-dark{% endif %} flex-fill">
                            <i class="bi bi-building"></i> Business
                        </button>
                    </div>
                    <div class="mt-3 small text-muted">
                        Current type: <strong>{{ 'Smart Home' if user_type == 'smart_home' else 'Business' }}</strong>
                    </div>
                </div>
            </div>
            <div class="col-lg-6">
                <div class="card p-4 h-100">
                    <div class="section-head mb-3">
                        <h3 class="h5 fw-bold mb-0"><i class="bi bi-clock"></i> Chore Schedules</h3>
                        <button class="btn btn-sm btn-outline-dark" data-bs-toggle="modal" data-bs-target="#addChoreModal">
                            <i class="bi bi-plus-circle"></i> Add Schedule
                        </button>
                    </div>
                    {% if chore_schedules %}
                        {% for schedule in chore_schedules[:3] %}
                            <div class="mb-3 p-3 rounded-4" style="background:rgba(59,130,246,.05);">
                                <div class="d-flex justify-content-between align-items-start mb-2">
                                    <strong>{{ schedule.chore_name }}</strong>
                                    <small class="text-muted">{{ schedule.scheduled_time }}</small>
                                </div>
                                <div class="small text-muted">Days: {{ schedule.days_of_week }}</div>
                            </div>
                        {% endfor %}
                    {% else %}
                        <div class="text-center py-3 text-muted">
                            <i class="bi bi-clock fs-2"></i>
                            <p class="mt-2 mb-0">No chore schedules set. Add one to get reminders for optimal energy usage times.</p>
                        </div>
                    {% endif %}
                </div>
            </div>
        </div>

        <!-- Success Stories -->
        <div class="row g-4 mb-4">
            <div class="col-12">
                <div class="card p-4">
                    <h3 class="h5 fw-bold mb-3"><i class="bi bi-star"></i> Community Success Stories</h3>
                    <div class="row g-4">
                        {% for story in success_stories %}
                            <div class="col-lg-4">
                                <div class="card h-100" style="background:linear-gradient(180deg,#fff,#f0f9ff);">
                                    <div class="card-body">
                                        <h6 class="card-title fw-bold">{{ story.title }}</h6>
                                        <p class="card-text small">{{ story.story[:150] }}...</p>
                                        <div class="d-flex justify-content-between align-items-center">
                                            <div>
                                                <small class="text-muted">Saved: {{ current_user.currency }} {{ "%.0f"|format(story.savings_amount) }}</small>
                                                <br>
                                                <small class="text-muted">CO2 reduced: {{ "%.1f"|format(story.carbon_reduction) }} kg</small>
                                            </div>
                                            <small class="text-muted">by {{ story.user }}</small>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        {% endfor %}
                    </div>
                    <div class="text-center mt-3">
                        <button onclick="loadMoreStories()" class="btn btn-outline-dark btn-sm">
                            <i class="bi bi-arrow-repeat"></i> Load More Stories
                        </button>
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

        <div class="row g-4 mb-4">
            <div class="col-lg-12">
                <div class="card surface p-4 h-100">
                    <div class="d-flex justify-content-between align-items-center mb-3">
                        <div>
                            <h3 class="h5 fw-bold mb-1"><i class="bi bi-tree-fill"></i> Planting Advice</h3>
                            <p class="text-muted mb-0">Use your current CO2 footprint to understand how many trees can help offset emissions.</p>
                        </div>
                        <span class="badge text-bg-success">Approximate offset</span>
                    </div>
                    <div class="row g-3 align-items-center">
                        <div class="col-md-6">
                            <div class="p-4 rounded-4" style="background:linear-gradient(135deg,#ecfdf5,#dbeafe);">
                                <h4 class="fw-bold mb-2">{{ trees_to_plant }} trees</h4>
                                <p class="mb-0 text-muted">Estimated number of trees needed to absorb {{ analytics.total_co2 if analytics else 0 }} kg of CO2 emissions.</p>
                            </div>
                        </div>
                        <div class="col-md-6">
                            <div class="p-4 rounded-4" style="background:linear-gradient(135deg,#fff7ed,#fde68a);">
                                <p class="mb-2 text-muted">One mature tree absorbs about {{ tree_absorption_rate }} kg of CO2 per year.</p>
                                <p class="fw-semibold mb-0">Planting trees is a strong companion strategy to improving appliance efficiency and reducing your monthly cost.</p>
                            </div>
                        </div>
                    </div>
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
                <h6 class="mb-3 mt-4"><i class="bi bi-building"></i> Office Appliances</h6>
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
                                <td>75-150 W</td>
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
                    <div>
                        <h3 class="h4 fw-bold mb-0"><i class="bi bi-graph-up"></i> Detailed Consumption Analysis</h3>
                        <p class="small text-muted mb-0">Choose a view to compare daily and monthly energy consumption, costs, and carbon impact.</p>
                    </div>
                    <div class="d-flex flex-wrap gap-2 align-items-center">
                        <div class="btn-group btn-group-sm" role="group" aria-label="Consumption view toggle">
                            <button id="dailyViewBtn" type="button" class="btn btn-sm btn-outline-dark" onclick="toggleConsumptionView('daily')">Daily</button>
                            <button id="monthlyViewBtn" type="button" class="btn btn-sm btn-outline-dark" onclick="toggleConsumptionView('monthly')">Monthly</button>
                        </div>
                        <button class="btn btn-outline-dark" onclick="submitToAdmin()"><i class="bi bi-send"></i> Submit Summary to Admin</button>
                    </div>
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
                    {% if device_prediction.devices %}
                    <div class="chart-row">
                        <div class="chart-col">
                            <h5 class="text-center mb-3"><i class="bi bi-cpu"></i> Appliance Energy Breakdown</h5>
                            <canvas id="applianceChart"></canvas>
                        </div>
                        <div class="chart-col">
                            <div class="alert alert-info">
                                <h6><i class="bi bi-lightbulb"></i> Top Energy Consumer</h6>
                                {% if device_prediction.top_device %}
                                <strong>{{ device_prediction.top_device.name }}</strong><br>
                                {{ "%.2f"|format(device_prediction.top_device.monthly_kwh) }} kWh/month<br>
                                <small class="text-muted">{{ device_prediction.recommendation }}</small>
                                {% else %}
                                <small>No device data available</small>
                                {% endif %}
                            </div>
                        </div>
                        <div class="chart-col">
                            <div class="alert alert-success">
                                <h6><i class="bi bi-check-circle"></i> Usage Summary</h6>
                                <strong>Projected: {{ "%.2f"|format(device_prediction.projected_total) }} kWh</strong><br>
                                <small>Current: {{ "%.1f"|format(device_prediction.current_utilization) }}% of threshold</small><br>
                                <small>Projected: {{ "%.1f"|format(device_prediction.projected_utilization) }}% of threshold</small>
                            </div>
                        </div>
                    </div>
                    {% endif %}
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
                <div class="d-flex gap-2 flex-wrap align-items-center">
                    <a class="btn btn-outline-dark btn-sm" href="{{ url_for('customer_payments') }}"><i class="bi bi-box-arrow-up-right"></i> Open payment page</a>
                    <span class="text-muted small">{{ payable_invoices|length }} unpaid invoice(s)</span>
                </div>
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
            <div class="col-lg-6"><div class="card p-4 h-100 warm-card"><h3 class="h5 fw-bold"><i class="bi bi-cpu"></i> Devices</h3><p class="text-muted">Manage connected IoT devices.</p><div class="row g-3"><div class="col-sm-4"><div class="border rounded-4 p-3 bg-white text-center"><small>Connected Sensors</small><strong class="fs-4">{{ readings|length if readings else 0 }}</strong></div></div><div class="col-sm-4"><div class="border rounded-4 p-3 bg-white text-center"><small>{% if selected_energy_source == 'KPLC' %}Meter Number{% else %}Energy Source{% endif %}</small><strong>{% if selected_energy_source == 'KPLC' %}{{ current_user.meter_number }}{% else %}{{ energy_source_label }}{% endif %}</strong></div></div><div class="col-sm-4"><div class="border rounded-4 p-3 bg-white text-center"><small>Energy Cost</small><strong>{% if current_tariff %}Ksh {{ "%.2f"|format(current_tariff.cost_per_unit) }}{% else %}Ksh {{ "%.2f"|format(current_user.unit_cost) }}{% endif %}</strong></div></div></div><div class="device-action-row mt-3"><a class="btn btn-outline-dark btn-sm" href="#device-add-form"><i class="bi bi-plus-circle"></i> Add</a><a class="btn btn-outline-dark btn-sm" href="#device-list"><i class="bi bi-pencil-square"></i> Manage</a><a class="btn btn-outline-danger btn-sm" href="#device-list"><i class="bi bi-trash"></i> Remove</a></div></div></div>
        </div>
        <div class="row g-4 mb-4">
            <div class="col-lg-6"><div class="card p-4 h-100 story-card"><h3 class="h5 fw-bold"><i class="bi bi-headset"></i> Support</h3><p class="text-muted">Find help with billing, thresholds, exports, and setup.</p><div class="d-flex gap-2 flex-wrap"><a class="btn btn-outline-dark" href="{{ url_for('contact') }}">Contact Support</a><a class="btn btn-outline-secondary" href="{{ url_for('faqs') }}">View FAQs</a></div></div></div>
            <div class="col-lg-6"><div class="card p-4 h-100" style="background:linear-gradient(180deg,#fff,#eef4ff)"><h3 class="h5 fw-bold"><i class="bi bi-people"></i> Community</h3><p class="text-muted">Learn from user stories and sustainability tips.</p></div></div>
        </div>

        <!-- Readings Table -->
        <div class="card p-4">
            <div class="section-head mb-3">
                <h3 class="h5 fw-bold mb-0"><i class="bi bi-table"></i> Your Readings</h3>
                <div class="d-flex gap-2 flex-wrap"><a class="btn btn-outline-success btn-sm" href="{{ url_for('export_csv') }}">CSV</a><a class="btn btn-outline-primary btn-sm" href="{{ url_for('export_xlsx') }}">Excel</a><a class="btn btn-outline-danger btn-sm" href="{{ url_for('export_pdf') }}">PDF</a></div>
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
        function showLiveNotificationToast(payload) {
            const stack = document.getElementById('liveToastStack');
            if (!stack) return;
            const levelMap = {
                info: 'text-bg-info',
                success: 'text-bg-success',
                warning: 'text-bg-warning',
                danger: 'text-bg-danger'
            };
            const level = (payload.level || 'info').toLowerCase();
            const toast = document.createElement('div');
            toast.className = `toast align-items-center border-0 ${levelMap[level] || levelMap.info}`;
            toast.setAttribute('role', 'alert');
            toast.setAttribute('aria-live', 'assertive');
            toast.setAttribute('aria-atomic', 'true');
            const flex = document.createElement('div');
            flex.className = 'd-flex';
            const body = document.createElement('div');
            body.className = 'toast-body';
            const title = document.createElement('div');
            title.className = 'fw-semibold';
            title.textContent = payload.title || 'EcoPulse Notification';
            const message = document.createElement('div');
            message.textContent = payload.message || '';
            body.appendChild(title);
            body.appendChild(message);
            const closeBtn = document.createElement('button');
            closeBtn.type = 'button';
            closeBtn.className = 'btn-close btn-close-white me-2 m-auto';
            closeBtn.setAttribute('data-bs-dismiss', 'toast');
            flex.appendChild(body);
            flex.appendChild(closeBtn);
            toast.appendChild(flex);
            stack.prepend(toast);
            const instance = new bootstrap.Toast(toast, { delay: 9000 });
            toast.addEventListener('hidden.bs.toast', () => toast.remove());
            instance.show();
        }
        function startLiveNotificationStream() {
            if (!window.EventSource) return;
            const streamUrl = '{{ url_for("notification_stream") }}';
            let source = null;
            const connect = () => {
                source = new EventSource(streamUrl);
                source.addEventListener('notification', (event) => {
                    try {
                        const payload = JSON.parse(event.data || '{}');
                        showLiveNotificationToast(payload);
                    } catch (err) {
                        console.error('Notification parse error:', err);
                    }
                });
                source.onerror = () => {
                    if (source) source.close();
                    setTimeout(connect, 2500);
                };
            };
            connect();
            window.addEventListener('beforeunload', () => {
                if (source) source.close();
            });
        }
        document.addEventListener('DOMContentLoaded', startLiveNotificationStream);
        {% if readings %}
        document.addEventListener('DOMContentLoaded', function() {
            const rawReadingDates = {{ readings|map(attribute='date')|list|tojson }};
            const rawReadingValues = {{ readings|map(attribute='kwh')|list|tojson }};
            const rawReadingCosts = {{ readings|map(attribute='cost')|list|tojson }};
            const rawReadingTimestamps = {{ reading_timestamps|tojson }};
            const deviceData = {{ device_prediction.devices|tojson }};
            const threshold = {{ current_user.threshold }};
            let currentView = '{{ selected_view }}' || 'daily';

            let mainConsumptionChart = null;
            let pieChart = null;
            let trendChart = null;
            let efficiencyGauge = null;
            let costChart = null;
            let environmentChart = null;
            let thresholdComparisonChart = null;
            let applianceChart = null;

            const parsedCosts = rawReadingCosts.map(value => parseFloat(value) || 0);
            const co2Values = rawReadingValues.map(v => parseFloat(v || 0) * 0.385);
            const dailyData = aggregateDailyData(rawReadingTimestamps, rawReadingDates, rawReadingValues, parsedCosts, co2Values);
            const monthlyData = aggregateMonthlyData(rawReadingTimestamps, rawReadingDates, rawReadingValues, parsedCosts, co2Values);

            function aggregateDailyData(timestamps, dates, values, costs, co2s) {
                const groups = {};
                for (let i = 0; i < values.length; i++) {
                    const value = parseFloat(values[i]) || 0;
                    const cost = parseFloat(costs[i]) || 0;
                    const co2 = parseFloat(co2s[i]) || 0;
                    let label = dates[i] || `Reading ${i + 1}`;
                    if (timestamps[i] && timestamps[i] !== '') {
                        try {
                            const parsedDate = new Date(timestamps[i]);
                            if (!isNaN(parsedDate.getTime())) {
                                label = parsedDate.toISOString().slice(0, 10);
                            }
                        } catch (e) {
                            // Keep fallback label.
                        }
                    }
                    if (!groups[label]) {
                        groups[label] = { value: 0, cost: 0, co2: 0 };
                    }
                    groups[label].value += value;
                    groups[label].cost += cost;
                    groups[label].co2 += co2;
                }
                const labels = Object.keys(groups).sort((a, b) => {
                    const da = new Date(a);
                    const db = new Date(b);
                    if (!isNaN(da.getTime()) && !isNaN(db.getTime())) {
                        return da - db;
                    }
                    return a.localeCompare(b);
                });
                return {
                    labels,
                    values: labels.map(label => parseFloat(groups[label].value.toFixed(2))),
                    costs: labels.map(label => parseFloat(groups[label].cost.toFixed(2))),
                    co2: labels.map(label => parseFloat(groups[label].co2.toFixed(2)))
                };
            }

            function aggregateMonthlyData(timestamps, dates, values, costs, co2s) {
                const groups = {};
                const monthNames = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
                
                for (let i = 0; i < values.length; i++) {
                    const value = parseFloat(values[i]) || 0;
                    const cost = parseFloat(costs[i]) || 0;
                    const co2 = parseFloat(co2s[i]) || 0;
                    
                    // Create month-year label
                    let label = `Reading ${i + 1}`; // fallback
                    if (timestamps[i] && timestamps[i] !== '') {
                        try {
                            const parsedDate = new Date(timestamps[i]);
                            if (!isNaN(parsedDate.getTime())) {
                                const month = monthNames[parsedDate.getMonth()];
                                const year = parsedDate.getFullYear();
                                label = `${month} ${year}`;
                            }
                        } catch (e) {
                            // Error parsing date, use fallback
                        }
                    }
                    
                    if (!groups[label]) {
                        groups[label] = { value: 0, cost: 0, co2: 0, count: 0 };
                    }
                    groups[label].value += value;
                    groups[label].cost += cost;
                    groups[label].co2 += co2;
                    groups[label].count += 1;
                }
                
                // Sort labels chronologically
                const sortedLabels = Object.keys(groups).sort((a, b) => {
                    // Extract month and year from labels like "Jan 2025"
                    const matchA = a.match(/(\\w+)\\s+(\\d+)/);
                    const matchB = b.match(/(\\w+)\\s+(\\d+)/);
                    
                    if (matchA && matchB) {
                        const monthA = monthNames.indexOf(matchA[1]);
                        const yearA = parseInt(matchA[2]);
                        const monthB = monthNames.indexOf(matchB[1]);
                        const yearB = parseInt(matchB[2]);
                        
                        if (yearA !== yearB) {
                            return yearA - yearB;
                        }
                        return monthA - monthB;
                    }
                    
                    return a.localeCompare(b);
                });
                
                return {
                    labels: sortedLabels,
                    values: sortedLabels.map(label => parseFloat(groups[label].value.toFixed(2))),
                    costs: sortedLabels.map(label => parseFloat(groups[label].cost.toFixed(2))),
                    co2: sortedLabels.map(label => parseFloat(groups[label].co2.toFixed(2)))
                };
            }

            function currentChartData(view) {
                if (view === 'monthly' && monthlyData.labels.length) {
                    return {
                        labels: monthlyData.labels,
                        values: monthlyData.values,
                        costs: monthlyData.costs,
                        co2: monthlyData.co2
                    };
                }
                return {
                    labels: dailyData.labels.length ? dailyData.labels : rawReadingDates,
                    values: dailyData.labels.length ? dailyData.values : rawReadingValues.map(v => parseFloat(v) || 0),
                    costs: dailyData.labels.length ? dailyData.costs : parsedCosts,
                    co2: dailyData.labels.length ? dailyData.co2 : co2Values
                };
            }

            function updateViewButtons() {
                document.getElementById('dailyViewBtn').classList.toggle('btn-dark', currentView === 'daily');
                document.getElementById('dailyViewBtn').classList.toggle('btn-outline-dark', currentView !== 'daily');
                document.getElementById('monthlyViewBtn').classList.toggle('btn-dark', currentView === 'monthly');
                document.getElementById('monthlyViewBtn').classList.toggle('btn-outline-dark', currentView !== 'monthly');
            }

            function destroyChart(chart) {
                if (chart && typeof chart.destroy === 'function') {
                    chart.destroy();
                }
            }

            function buildCharts(view) {
                
                // Check if canvas elements exist
                const mainCanvas = document.getElementById('mainConsumptionChart');
                
                if (!mainCanvas) {
                    console.error('Main consumption chart canvas not found!');
                    return;
                }
                
                destroyChart(mainConsumptionChart);
                destroyChart(pieChart);
                destroyChart(trendChart);
                destroyChart(efficiencyGauge);
                destroyChart(costChart);
                destroyChart(environmentChart);
                destroyChart(thresholdComparisonChart);
                destroyChart(applianceChart);

                const data = currentChartData(view);
                updateViewButtons();

                mainConsumptionChart = new Chart(document.getElementById('mainConsumptionChart'), {
                    type: 'bar',
                    data: {
                        labels: data.labels,
                        datasets: [{
                            label: 'Energy Consumption (kWh)',
                            data: data.values,
                            backgroundColor: data.values.map(v => v > threshold ? '#ff6b6b' : '#00b894'),
                            borderRadius: 8
                        }]
                    },
                    options: { responsive: true, maintainAspectRatio: true }
                });

                const above = data.values.filter(v => v > threshold).length;
                const below = data.values.filter(v => v <= threshold).length;
                pieChart = new Chart(document.getElementById('pieChart'), {
                    type: 'pie',
                    data: {
                        labels: ['Above Threshold', 'Below Threshold'],
                        datasets: [{ data: [above, below], backgroundColor: ['#ff6b6b', '#00b894'] }]
                    },
                    options: { responsive: true }
                });

                trendChart = new Chart(document.getElementById('trendChart'), {
                    type: 'line',
                    data: {
                        labels: data.labels,
                        datasets: [
                            { label: 'Actual', data: data.values, borderColor: '#0984e3', fill: true },
                            { label: 'Threshold', data: Array(data.values.length).fill(threshold), borderColor: '#ff6b6b', borderDash: [5,5], fill: false }
                        ]
                    },
                    options: { responsive: true }
                });

                const efficiency = Math.max(0, Math.min(100, ((threshold - (data.values[data.values.length - 1] || 0)) / threshold * 100)));
                efficiencyGauge = new Chart(document.getElementById('efficiencyGauge'), {
                    type: 'doughnut',
                    data: {
                        labels: ['Efficiency', 'Remaining'],
                        datasets: [{ data: [efficiency, 100 - efficiency], backgroundColor: ['#00b894', '#dfe6e9'], cutout: '70%' }]
                    },
                    options: { responsive: true }
                });

                costChart = new Chart(document.getElementById('costChart'), {
                    type: 'bar',
                    data: {
                        labels: data.labels,
                        datasets: [{ label: 'Cost', data: data.costs, backgroundColor: '#fdcb6e' }]
                    },
                    options: { responsive: true }
                });

                environmentChart = new Chart(document.getElementById('environmentChart'), {
                    type: 'line',
                    data: {
                        labels: data.labels,
                        datasets: [{ label: 'CO2 (kg)', data: data.co2, borderColor: '#00b894', fill: true }]
                    },
                    options: { responsive: true }
                });

                thresholdComparisonChart = new Chart(document.getElementById('thresholdComparisonChart'), {
                    type: 'radar',
                    data: {
                        labels: data.labels.slice(-6),
                        datasets: [
                            { label: 'Usage', data: data.values.slice(-6), borderColor: '#ff6b6b' },
                            { label: 'Threshold', data: Array(Math.min(data.values.length, 6)).fill(threshold), borderColor: '#00b894' }
                        ]
                    },
                    options: { responsive: true }
                });

                // Appliance breakdown chart
                if (deviceData && deviceData.length > 0) {
                    const applianceLabels = deviceData.slice(0, 8).map(d => d.name.length > 15 ? d.name.substring(0, 15) + '...' : d.name);
                    const applianceValues = deviceData.slice(0, 8).map(d => view === 'monthly' ? d.monthly_kwh : d.daily_kwh);
                    const applianceColors = [
                        '#FF6384', '#36A2EB', '#FFCE56', '#4BC0C0', '#9966FF', '#FF9F40', '#FF6384', '#C9CBCF'
                    ];

                    applianceChart = new Chart(document.getElementById('applianceChart'), {
                        type: 'doughnut',
                        data: {
                            labels: applianceLabels,
                            datasets: [{
                                data: applianceValues,
                                backgroundColor: applianceColors.slice(0, applianceLabels.length),
                                borderWidth: 2,
                                borderColor: '#fff'
                            }]
                        },
                        options: {
                            responsive: true,
                            plugins: {
                                legend: {
                                    position: 'bottom',
                                    labels: {
                                        boxWidth: 12,
                                        font: { size: 11 }
                                    }
                                },
                                tooltip: {
                                    callbacks: {
                                        label: function(context) {
                                            const label = context.label || '';
                                            const value = context.parsed || 0;
                                            const unit = view === 'monthly' ? 'kWh/month' : 'kWh/day';
                                            return `${label}: ${value.toFixed(2)} ${unit}`;
                                        }
                                    }
                                }
                            }
                        }
                    });
                }
            }

            function toggleConsumptionView(view) {
                currentView = view;
                buildCharts(view);
            }

            // Expose toggle for inline button handlers in the template.
            window.toggleConsumptionView = toggleConsumptionView;
            window.__ecopulseBuildCharts = buildCharts;

            updateViewButtons();
            buildCharts(currentView);
        });
        {% endif %}

        // Keep toggle buttons functional even when no readings are present or
        // when the chart block has not initialized yet.
        if (!window.toggleConsumptionView) {
            window.toggleConsumptionView = function(view) {
                const dailyBtn = document.getElementById('dailyViewBtn');
                const monthlyBtn = document.getElementById('monthlyViewBtn');
                if (dailyBtn && monthlyBtn) {
                    dailyBtn.classList.toggle('btn-dark', view === 'daily');
                    dailyBtn.classList.toggle('btn-outline-dark', view !== 'daily');
                    monthlyBtn.classList.toggle('btn-dark', view === 'monthly');
                    monthlyBtn.classList.toggle('btn-outline-dark', view !== 'monthly');
                }
                if (typeof window.__ecopulseBuildCharts === 'function') {
                    window.__ecopulseBuildCharts(view);
                }
            };
        }
    </script>

    <!-- Add Chore Modal -->
    <div class="modal fade" id="addChoreModal" tabindex="-1">
        <div class="modal-dialog">
            <div class="modal-content">
                <div class="modal-header">
                    <h5 class="modal-title"><i class="bi bi-clock"></i> Add Chore Schedule</h5>
                    <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                </div>
                <div class="modal-body">
                    <form id="choreForm">
                        <div class="mb-3">
                            <label class="form-label">Chore Name</label>
                            <input type="text" class="form-control" id="choreName" placeholder="e.g. Laundry, Dishwasher" required>
                        </div>
                        <div class="mb-3">
                            <label class="form-label">Scheduled Time</label>
                            <input type="time" class="form-control" id="choreTime" required>
                        </div>
                        <div class="mb-3">
                            <label class="form-label">Days of Week</label>
                            <div class="row g-2">
                                <div class="col-6">
                                    <div class="form-check">
                                        <input class="form-check-input" type="checkbox" value="1" id="mon">
                                        <label class="form-check-label" for="mon">Monday</label>
                                    </div>
                                    <div class="form-check">
                                        <input class="form-check-input" type="checkbox" value="2" id="tue">
                                        <label class="form-check-label" for="tue">Tuesday</label>
                                    </div>
                                    <div class="form-check">
                                        <input class="form-check-input" type="checkbox" value="3" id="wed">
                                        <label class="form-check-label" for="wed">Wednesday</label>
                                    </div>
                                    <div class="form-check">
                                        <input class="form-check-input" type="checkbox" value="4" id="thu">
                                        <label class="form-check-label" for="thu">Thursday</label>
                                    </div>
                                </div>
                                <div class="col-6">
                                    <div class="form-check">
                                        <input class="form-check-input" type="checkbox" value="5" id="fri">
                                        <label class="form-check-label" for="fri">Friday</label>
                                    </div>
                                    <div class="form-check">
                                        <input class="form-check-input" type="checkbox" value="6" id="sat">
                                        <label class="form-check-label" for="sat">Saturday</label>
                                    </div>
                                    <div class="form-check">
                                        <input class="form-check-input" type="checkbox" value="7" id="sun">
                                        <label class="form-check-label" for="sun">Sunday</label>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </form>
                </div>
                <div class="modal-footer">
                    <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancel</button>
                    <button type="button" class="btn btn-dark" onclick="addChoreSchedule()">Add Schedule</button>
                </div>
            </div>
        </div>
    </div>

    <script>
        function setUserType(type) {
            fetch('/api/user/type', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({user_type: type})
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    alert('User type updated successfully!');
                    location.reload();
                } else {
                    alert('Error: ' + data.error);
                }
            })
            .catch(error => {
                console.error('Error:', error);
                alert('An error occurred while updating user type.');
            });
        }

        function addChoreSchedule() {
            const choreName = document.getElementById('choreName').value;
            const choreTime = document.getElementById('choreTime').value;
            const days = [];
            ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'].forEach(day => {
                if (document.getElementById(day).checked) {
                    days.push(document.getElementById(day).value);
                }
            });

            if (!choreName || !choreTime || days.length === 0) {
                alert('Please fill in all fields and select at least one day.');
                return;
            }

            fetch('/api/chores/schedule', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    chore_name: choreName,
                    scheduled_time: choreTime,
                    days_of_week: days.join(',')
                })
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    alert('Chore schedule added successfully!');
                    location.reload();
                } else {
                    alert('Error: ' + data.error);
                }
            })
            .catch(error => {
                console.error('Error:', error);
                alert('An error occurred while adding chore schedule.');
            });
        }

        function getMoreRecommendations() {
            // Disable button during loading
            const button = document.querySelector('button[onclick="getMoreRecommendations()"]');
            if (button) {
                button.disabled = true;
                button.innerHTML = '<i class="bi bi-hourglass-split"></i> Loading...';
            }
            
            fetch('/api/recommendations/more')
            .then(response => {
                if (!response.ok) {
                    throw new Error(`HTTP ${response.status}: ${response.statusText}`);
                }
                return response.json();
            })
            .then(data => {
                if (data.success && data.recommendations && data.recommendations.length > 0) {
                    // Find the tips container - look for the card with personalized tips
                    const tipsCard = Array.from(document.querySelectorAll('.card')).find(card => 
                        card.textContent.includes('Personalized Tips')
                    );
                    
                    if (tipsCard) {
                        const tipsContainer = tipsCard.querySelector('.mb-3') || tipsCard.querySelector('.card-body');
                        
                        // Add new recommendations
                        data.recommendations.forEach(tip => {
                            const tipElement = document.createElement('div');
                            tipElement.className = 'mb-3 p-3 rounded-4';
                            tipElement.style.background = 'rgba(15,118,110,.05)';
                            tipElement.innerHTML = `
                                <div class="d-flex justify-content-between align-items-start mb-2">
                                    <strong>${tip.title}</strong>
                                    <span class="badge bg-success">Save ${tip.potential_savings}%</span>
                                </div>
                                <p class="mb-0 text-muted">${tip.content}</p>
                            `;
                            tipsContainer.appendChild(tipElement);
                        });
                        
                        // Update the button text to show success
                        if (button) {
                            button.innerHTML = '<i class="bi bi-check-circle"></i> ' + data.count + ' More Added!';
                            button.classList.remove('btn-dark');
                            button.classList.add('btn-success');
                            button.disabled = true;
                        }
                    } else {
                        throw new Error('Could not find tips container');
                    }
                } else {
                    // Re-enable button and show message
                    if (button) {
                        button.disabled = false;
                        button.innerHTML = '<i class="bi bi-magic"></i> Get More Recommendations';
                    }
                    alert(data.error || 'No additional recommendations available at this time.');
                }
            })
            .catch(error => {
                console.error('Error:', error);
                // Re-enable button and show error
                if (button) {
                    button.disabled = false;
                    button.innerHTML = '<i class="bi bi-magic"></i> Get More Recommendations';
                }
                alert('An error occurred while loading recommendations. Please try again.');
            });
        }

        function loadMoreStories() {
            fetch('/api/community/stories')
            .then(response => response.json())
            .then(data => {
                if (data.stories && data.stories.length > 0) {
                    alert('More success stories loaded! Check the community section.');
                    location.reload();
                } else {
                    alert('No more stories available.');
                }
            })
            .catch(error => {
                console.error('Error:', error);
                alert('An error occurred while loading stories.');
            });
        }

        function upgradeSubscription(tier) {
            if (!confirm(`Are you sure you want to upgrade to the ${tier.charAt(0).toUpperCase() + tier.slice(1)} plan?`)) {
                return;
            }

            // Disable all upgrade buttons
            document.querySelectorAll('button[onclick^="upgradeSubscription"]').forEach(btn => {
                btn.disabled = true;
                btn.innerHTML = '<i class="bi bi-hourglass-split"></i> Processing...';
            });

            fetch('/api/billing/upgrade', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({tier: tier})
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    alert(`Successfully upgraded to ${data.new_tier}! ${data.features.length} new features activated.`);
                    location.reload();
                } else {
                    alert('Upgrade failed: ' + data.error);
                    // Re-enable buttons
                    document.querySelectorAll('button[onclick^="upgradeSubscription"]').forEach(btn => {
                        btn.disabled = false;
                        btn.innerHTML = 'Upgrade';
                    });
                }
            })
            .catch(error => {
                console.error('Error:', error);
                alert('An error occurred during upgrade. Please try again.');
                // Re-enable buttons
                document.querySelectorAll('button[onclick^="upgradeSubscription"]').forEach(btn => {
                    btn.disabled = false;
                    btn.innerHTML = 'Upgrade';
                });
            });
        }
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
    <style>body{margin:0;background:radial-gradient(circle at top left,rgba(59,130,246,.12),transparent 22%),radial-gradient(circle at bottom right,rgba(16,185,129,.08),transparent 18%),linear-gradient(180deg,#edf3ff 0,#f8fafc 36%,#eef6ff 100%);padding-top:86px;overflow-x:hidden}.hero-surface{background:linear-gradient(135deg,rgba(15,23,42,.95),rgba(37,99,235,.88),rgba(16,185,129,.76));box-shadow:0 24px 56px rgba(15,23,42,.24)}.card{border:1px solid rgba(148,163,184,.16);box-shadow:0 18px 42px rgba(15,23,42,.12);transition:transform .2s ease,box-shadow .2s ease}.card:hover{transform:translateY(-2px);box-shadow:0 24px 54px rgba(15,23,42,.16)}.smart-meter{background:linear-gradient(135deg,#0f172a 0%,#1d4ed8 42%,#0f766e 100%)}.cool-card{background:linear-gradient(135deg,rgba(255,255,255,.98),rgba(224,242,254,.96))}.mint-card{background:linear-gradient(135deg,rgba(240,253,250,.98),rgba(209,250,229,.96))}.table thead th{background:linear-gradient(135deg,#eff6ff,#f8fafc);color:#334155}.btn-dark{background:linear-gradient(135deg,#0f172a,#334155);border:none}.navbar{background:rgba(31,41,55,.94);backdrop-filter:blur(10px);box-shadow:0 10px 30px rgba(15,23,42,.18)}.card{border:1px solid rgba(15,23,42,.08);border-radius:24px;box-shadow:0 18px 42px rgba(15,23,42,0.08);background:rgba(255,255,255,.96)}.assistant-scroll{max-height:220px;overflow-y:auto;background:#f8fafc;border-radius:16px;padding:16px;border:1px solid rgba(15,23,42,.08)}.btn{border-radius:14px;font-weight:600}.btn-dark{background:linear-gradient(135deg,#0f172a,#334155);border:none}.btn-outline-dark:hover{background:#1f2937;border-color:#1f2937}.table-responsive{border-radius:18px}.table thead th{background:#f8fafc;white-space:nowrap}.toolbar{display:flex;gap:.75rem;flex-wrap:wrap}.toolbar>*{flex:0 0 auto}.hero-surface{background:linear-gradient(135deg,rgba(15,23,42,.92),rgba(51,65,85,.84)),url('https://images.unsplash.com/photo-1451187580459-43490279c0fa?auto=format&fit=crop&w=1600&q=80') center/cover;color:#fff;border-radius:28px;padding:30px;box-shadow:0 24px 56px rgba(15,23,42,.2)}.smart-meter{background:linear-gradient(145deg,#0f172a,#1e3a8a 62%,#38bdf8);color:#fff;position:relative;overflow:hidden}.smart-meter:after{content:'';position:absolute;right:-38px;top:-38px;width:150px;height:150px;border-radius:50%;background:rgba(255,255,255,.08)}.meter-ring{width:118px;height:118px;border-radius:50%;display:grid;place-items:center;background:conic-gradient(#86efac 0 calc(var(--meter-value) * 1%),rgba(255,255,255,.18) 0);padding:10px}.meter-ring span{width:100%;height:100%;border-radius:50%;display:grid;place-items:center;background:#0f172a;font-weight:700}.meter-chip{display:inline-flex;align-items:center;gap:8px;padding:8px 12px;border-radius:999px;background:rgba(255,255,255,.12);border:1px solid rgba(255,255,255,.16)}.cool-card{background:linear-gradient(180deg,#fff,#eef4ff)}.mint-card{background:linear-gradient(180deg,#fff,#f0fdf9)}@media (max-width:991.98px){.toolbar>*{width:100%}}@media (max-width:767.98px){body{padding-top:74px}.container{padding-left:16px;padding-right:16px}.card,.hero-surface{border-radius:20px}.btn,.btn-sm{width:100%}.table td,.table th{font-size:.92rem}.meter-ring{margin:auto}}</style>
</head>
<body>
    <nav class="navbar navbar-expand-lg navbar-dark fixed-top"><div class="container"><a class="navbar-brand fw-bold" href="{{ url_for('admin_financial') }}">EcoPulse Admin</a><button class="navbar-toggler" type="button" data-bs-toggle="collapse" data-bs-target="#adminNav"><span class="navbar-toggler-icon"></span></button><div class="collapse navbar-collapse" id="adminNav"><div class="navbar-nav ms-auto"><a class="nav-link" href="{{ url_for('admin_financial') }}">Dashboard</a><a class="nav-link" href="{{ url_for('examiner_dashboard') }}">Examiner</a><a class="nav-link" href="{{ url_for('hr_employee_records') }}">HR Manager</a><a class="nav-link" href="{{ url_for('admin_backup_restore') }}">Backup</a><a class="nav-link" href="{{ url_for('ai_analysis') }}">AI Analysis</a><a class="nav-link" href="{{ url_for('manage_departments') }}">Departments</a><a class="nav-link" href="{{ url_for('logout') }}">Logout</a></div></div></div></nav>
    <div class="container pb-5">
        <div class="hero-surface mb-4"><div class="d-flex flex-column flex-lg-row justify-content-between align-items-lg-end"><div><h1 class="fw-bold">Admin Dashboard</h1><p class="mb-0" style="color:rgba(255,255,255,.82)">Approve examiner output, review financial records, and monitor 10-year system forecasts.</p></div><div class="mt-3 mt-lg-0 toolbar"><a class="btn btn-outline-light" href="{{ url_for('ai_analysis') }}">AI Analysis</a><form method="POST" action="{{ url_for('send_customer_summaries') }}"><button class="btn btn-dark">Send Customer Summaries</button></form></div></div></div>
        <div class="row g-4 mb-4"><div class="col-12"><div class="card p-4"><div class="d-flex flex-column flex-md-row justify-content-between align-items-start align-items-md-center gap-3"><div><h3 class="h5 fw-bold mb-2">Admin Control Center</h3><p class="text-muted mb-0">Central controls for HR, system configuration, support, partnerships, and backup workflows.</p></div><div class="d-flex flex-wrap gap-2"><a class="btn btn-outline-light" href="{{ url_for('hr_employee_records') }}">HR Manager</a><a class="btn btn-outline-light" href="{{ url_for('hr_people_ops') }}">People Ops</a><a class="btn btn-outline-light" href="{{ url_for('support_center') }}">Support</a><a class="btn btn-outline-light" href="{{ url_for('ecosystem_trust') }}">Trust Center</a><a class="btn btn-outline-light" href="{{ url_for('admin_backup_restore') }}">Backup/Restore</a><a class="btn btn-outline-light" href="{{ url_for('manage_departments') }}">Departments</a></div></div><div class="row row-cols-1 row-cols-md-4 g-3 mt-4">
                <div class="col">
                    <div class="p-4 rounded-4" style="background:linear-gradient(135deg,rgba(14,165,233,.12),rgba(6,182,212,.08));border:1px solid rgba(6,182,212,.16)">
                        <div class="text-uppercase text-muted small mb-2">Pending Reviews</div>
                        <div class="d-flex align-items-center justify-content-between gap-3">
                            <div><h2 class="mb-0">{{ pending_reviews|length }}</h2><p class="mb-0 text-muted">Tariff & consumption approvals</p></div>
                            <span class="badge bg-info text-dark py-2 px-3">Review</span>
                        </div>
                    </div>
                </div>
                <div class="col">
                    <div class="p-4 rounded-4" style="background:linear-gradient(135deg,rgba(16,185,129,.12),rgba(4,120,87,.08));border:1px solid rgba(16,185,129,.16)">
                        <div class="text-uppercase text-muted small mb-2">Support Tickets</div>
                        <div class="d-flex align-items-center justify-content-between gap-3">
                            <div><h2 class="mb-0">{{ support_tickets_count }}</h2><p class="mb-0 text-muted">Open customer requests</p></div>
                            <span class="badge bg-success py-2 px-3">Support</span>
                        </div>
                    </div>
                </div>
                <div class="col">
                    <div class="p-4 rounded-4" style="background:linear-gradient(135deg,rgba(234,179,8,.12),rgba(245,158,11,.08));border:1px solid rgba(245,158,11,.16)">
                        <div class="text-uppercase text-muted small mb-2">Partnership Requests</div>
                        <div class="d-flex align-items-center justify-content-between gap-3">
                            <div><h2 class="mb-0">{{ partnership_requests_count }}</h2><p class="mb-0 text-muted">Integration / partner applications</p></div>
                            <span class="badge bg-warning text-dark py-2 px-3">Partnership</span>
                        </div>
                    </div>
                </div>
                <div class="col">
                    <div class="p-4 rounded-4" style="background:linear-gradient(135deg,rgba(124,58,237,.12),rgba(99,102,241,.08));border:1px solid rgba(99,102,241,.16)">
                        <div class="text-uppercase text-muted small mb-2">Active Features</div>
                        <div class="d-flex align-items-center justify-content-between gap-3">
                            <div><h2 class="mb-0">{{ active_feature_toggles }}</h2><p class="mb-0 text-muted">Enabled admin modules</p></div>
                            <span class="badge bg-primary py-2 px-3">Systems</span>
                        </div>
                    </div>
                </div>
            </div></div></div></div>
        {% with messages = get_flashed_messages(with_categories=true) %}{% for category, msg in messages %}<div class="alert alert-{{ 'warning' if category == 'warning' else 'info' }}">{{ msg }}</div>{% endfor %}{% endwith %}
        <div class="card smart-meter p-4 mb-4"><div class="row g-4 align-items-center"><div class="col-lg-7"><div class="d-flex flex-wrap gap-2 mb-3"><span class="meter-chip"><i class="bi bi-building-check"></i> {{ smart_meter.title }}</span><span class="meter-chip"><i class="bi bi-shield-fill-check"></i> {{ smart_meter.status }}</span></div><h3 class="fw-bold mb-2">{{ smart_meter.reading_value }}</h3><p class="mb-3" style="color:rgba(255,255,255,.82)">{{ smart_meter.reading_label }}</p><div class="row g-3"><div class="col-sm-6"><div class="p-3 rounded-4" style="background:rgba(255,255,255,.1)"><small class="d-block" style="color:rgba(255,255,255,.7)">Verification</small><strong>{{ smart_meter.support_value }}</strong><div class="small" style="color:rgba(255,255,255,.72)">{{ smart_meter.support_label }}</div></div></div><div class="col-sm-6"><div class="p-3 rounded-4" style="background:rgba(255,255,255,.1)"><small class="d-block" style="color:rgba(255,255,255,.7)">Finance</small><strong>{{ smart_meter.detail_primary }}</strong><div class="small" style="color:rgba(255,255,255,.72)">{{ smart_meter.detail_secondary }}</div></div></div></div></div><div class="col-lg-5 text-center text-lg-end"><div class="meter-ring ms-lg-auto" style="--meter-value: {{ smart_meter.ring_value }};"><span>{{ smart_meter.ring_value }}%</span></div><div class="mt-3 small" style="color:rgba(255,255,255,.8)">{{ smart_meter.ring_label }}</div></div></div></div>
        <div class="row g-4 mb-4"><div class="col-md-3"><div class="card p-4"><small class="text-muted">Revenue</small><h3 class="fw-bold mb-0">Ksh {{ "%.2f"|format(financial.total_revenue) }}</h3></div></div><div class="col-md-3"><div class="card p-4"><small class="text-muted">Outstanding</small><h3 class="fw-bold mb-0">Ksh {{ "%.2f"|format(financial.total_outstanding) }}</h3></div></div><div class="col-md-3"><div class="card p-4"><small class="text-muted">Collected</small><h3 class="fw-bold mb-0">Ksh {{ "%.2f"|format(financial.total_collected) }}</h3></div></div><div class="col-md-3"><div class="card p-4"><small class="text-muted">Payment Rate</small><h3 class="fw-bold mb-0">{{ "%.1f"|format(financial.payment_rate) }}%</h3></div></div></div>
        <div class="row g-4 mb-4"><div class="col-lg-8"><div class="card p-4 h-100 cool-card"><h3 class="h5 fw-bold">10-Year Backcast and Forecast</h3><img src="data:image/png;base64,{{ prediction_payload.chart }}" class="img-fluid rounded-4" alt="Prediction chart"></div></div><div class="col-lg-4"><div class="card p-4 h-100 mint-card"><h3 class="h5 fw-bold">Forecast Summary</h3><p class="mb-2"><strong>Current year:</strong> {{ prediction_payload.summary.current_year }}</p><p class="mb-2"><strong>Current total:</strong> {{ "%.2f"|format(prediction_payload.summary.current_total) }} kWh</p><p class="mb-2"><strong>Previous average:</strong> {{ "%.2f"|format(prediction_payload.summary.previous_average) }} kWh</p><p class="mb-2"><strong>Next average:</strong> {{ "%.2f"|format(prediction_payload.summary.next_average) }} kWh</p><p class="mb-0"><strong>Growth rate:</strong> {{ "%.2f"|format(prediction_payload.summary.growth_rate) }}%</p></div></div></div>
        <div class="card p-4 mb-4"><h3 class="h5 fw-bold">Admin AI Forecast Assistant</h3><p class="text-muted">Enter an earlier range and a future range, up to 10 years each, to generate a graph and receive planning advice.</p><div class="row g-3"><div class="col-md-6"><label class="form-label">Earlier Years</label><input id="adminYearsBack" type="number" min="1" max="10" value="10" class="form-control"></div><div class="col-md-6"><label class="form-label">Next Years</label><input id="adminYearsForward" type="number" min="1" max="10" value="10" class="form-control"></div></div><div id="adminAssistantMessages" class="assistant-scroll mt-3"><div class="mb-2"><strong>EcoPulse AI:</strong> Ask about future demand, outstanding balances, or operational advice.</div></div><div class="input-group mt-3"><input id="adminAssistantInput" type="text" class="form-control" placeholder="What should I focus on for the selected forecast years?"><button id="adminAssistantSend" class="btn btn-dark" type="button">Generate</button></div><div id="adminAssistantSummary" class="small text-muted mt-3"></div><img id="adminAssistantChart" class="img-fluid rounded-4 mt-3 d-none" alt="Admin AI forecast chart"></div>
        <div class="row g-4 mb-4"><div class="col-lg-5"><div class="card p-4 h-100"><h3 class="h5 fw-bold">Energy Tariff Notifications</h3><p class="text-muted">Receive and publish source-specific cost-per-unit notices so billing stays aligned across the system.</p><div class="border rounded-4 p-3 bg-light mb-3"><small class="text-muted d-block">Current Published Tariff</small><strong>{% if current_tariff %}{{ selected_energy_source_label }}: Ksh {{ "%.2f"|format(current_tariff.cost_per_unit) }} / unit{% else %}{{ selected_energy_source_label }}: Ksh 0.12 / unit{% endif %}</strong><div class="small text-muted">{% if current_tariff %}Effective {{ current_tariff.effective_date }} | {{ current_tariff.notice_reference }}{% else %}No {{ selected_energy_source_label }} update published yet{% endif %}</div></div><form method="POST" action="{{ url_for('update_kplc_tariff') }}" class="row g-3"><div class="col-md-6"><label class="form-label">Energy Source</label><select class="form-control" name="energy_source" required>{% for source in energy_sources %}<option value="{{ source }}" {% if source == selected_energy_source %}selected{% endif %}>{{ source }}</option>{% endfor %}</select></div><div class="col-md-6"><label class="form-label">Cost / Unit</label><input class="form-control" type="number" step="0.01" min="0.01" name="cost_per_unit" value="{% if current_tariff %}{{ '%.2f'|format(current_tariff.cost_per_unit) }}{% else %}0.12{% endif %}" required></div><div class="col-md-6"><label class="form-label">Effective Date</label><input class="form-control" type="date" name="effective_date"></div><div class="col-12"><label class="form-label">Notice Reference</label><input class="form-control" name="notice_reference" placeholder="e.g. Tariff Circular April 2026" required></div><div class="col-12"><label class="form-label">Notice Message</label><textarea class="form-control" name="notice_message" rows="3" placeholder="Short source-specific tariff update note"></textarea></div><div class="col-12"><button class="btn btn-dark" type="submit">Publish Tariff Update</button></div></form>{% if kplc_notifications %}<hr><div class="table-responsive"><table class="table align-middle"><thead><tr><th>Notice</th><th>Published</th></tr></thead><tbody>{% for item in kplc_notifications %}<tr><td><div class="fw-semibold">{{ item.title }}</div><div class="small">{{ item.content|safe }}</div></td><td>{{ item.created_at.strftime('%Y-%m-%d %H:%M') }}</td></tr>{% endfor %}</tbody></table></div>{% endif %}</div></div><div class="col-lg-7"><div class="card p-4 h-100"><h3 class="h5 fw-bold">Threshold Sensor Alerts</h3><p class="text-muted">These alerts are raised automatically when a customer exceeds the configured threshold.</p>{% if sensor_alerts %}{% for alert in sensor_alerts %}<div class="border rounded-4 p-3 mb-3 bg-light-subtle"><div class="fw-semibold">{{ alert.title }}</div><small class="text-muted">{{ alert.created_at.strftime('%Y-%m-%d %H:%M') }}</small><div class="small mt-2">{{ alert.content|safe }}</div></div>{% endfor %}{% else %}<p class="text-muted mb-0">No sensor alerts have been raised yet.</p>{% endif %}</div></div></div>
        <div class="row g-4 mb-4"><div class="col-lg-6"><div class="card p-4"><h3 class="h5 fw-bold">User Management</h3><p class="text-muted">Create users, update roles, reset credentials, or remove accounts.</p><form method="POST" action="{{ url_for('admin_manage_user') }}" class="row g-3"><input type="hidden" name="action" value="create"><div class="col-md-6"><label class="form-label">Username</label><input class="form-control" name="username" placeholder="username" required></div><div class="col-md-6"><label class="form-label">Email</label><input class="form-control" name="email" type="email" placeholder="email@example.com" required></div><div class="col-md-4"><label class="form-label">Password</label><input class="form-control" name="password" type="password" placeholder="password" required></div><div class="col-md-4"><label class="form-label">Role</label><select class="form-control" name="role"><option value="customer">Customer</option><option value="examiner">Examiner</option><option value="hr_manager">HR Manager</option><option value="admin">Admin</option></select></div><div class="col-md-4"><label class="form-label">Status</label><select class="form-control" name="status"><option value="active" selected>Active</option><option value="suspended">Suspended</option></select></div><div class="col-md-4"><label class="form-label">Department</label><select class="form-control" name="department_id"><option value="">No department</option>{% for dept in departments %}<option value="{{ dept.id }}">{{ dept.name }}</option>{% endfor %}</select></div><div class="col-md-4"><label class="form-label">Salary</label><input class="form-control" name="salary" type="number" step="0.01" placeholder="0.00"></div><div class="col-md-4"><label class="form-label">Meter Number</label><input class="form-control" name="meter_number" placeholder="11-digit meter"></div><div class="col-md-4"><label class="form-label">Phone Number</label><input class="form-control" name="phone_number" placeholder="10-digit phone"></div><div class="col-12"><button class="btn btn-dark w-100" type="submit">Create User</button></div></form></div></div><div class="col-lg-6"><div class="card p-4"><h3 class="h5 fw-bold">Feature Toggles</h3><p class="text-muted">Turn system modules on or off quickly.</p>{% for toggle in feature_toggles %}<div class="d-flex align-items-center justify-content-between mb-3"><div><strong>{{ toggle.name.replace('_', ' ').title() }}</strong><div class="small text-muted">{{ toggle.description }}</div></div><form method="POST" action="{{ url_for('admin_toggle_feature') }}"><input type="hidden" name="feature_id" value="{{ toggle.id }}"><button type="submit" class="btn btn-sm {% if toggle.enabled %}btn-success{% else %}btn-outline-secondary{% endif %}">{% if toggle.enabled %}Enabled{% else %}Disabled{% endif %}</button></form></div>{% endfor %}</div></div></div>
        <div class="row g-4 mb-4"><div class="col-12"><div class="card p-4"><h3 class="h5 fw-bold">User Directory</h3><p class="text-muted">Review current users and their assigned salary, role, department, and account status.</p><div class="table-responsive"><table class="table align-middle"><thead><tr><th>Username</th><th>Role</th><th>Department</th><th>Status</th><th>Salary</th><th>Phone</th><th>Email</th><th>Actions</th></tr></thead><tbody>{% for user in users %}<tr><td>{{ user.username }}</td><td class="text-capitalize">{{ user.role }}</td><td>{{ user.department or '—' }}</td><td class="text-capitalize">{{ user.status or 'active' }}</td><td>{% if user.salary %}Ksh {{ '%.2f'|format(user.salary) }}{% else %}N/A{% endif %}</td><td>{{ user.phone_number or '—' }}</td><td>{{ user.email }}</td><td><div class="btn-group btn-group-sm" role="group"><form method="POST" action="{{ url_for('admin_manage_user') }}" class="d-inline"><input type="hidden" name="action" value="reset_password"><input type="hidden" name="target_user_id" value="{{ user.id }}"><button type="submit" class="btn btn-outline-warning">Reset PW</button></form>{% if user.status == 'active' %}<form method="POST" action="{{ url_for('admin_manage_user') }}" class="d-inline ms-1"><input type="hidden" name="action" value="suspend"><input type="hidden" name="target_user_id" value="{{ user.id }}"><button type="submit" class="btn btn-outline-secondary">Suspend</button></form>{% else %}<form method="POST" action="{{ url_for('admin_manage_user') }}" class="d-inline ms-1"><input type="hidden" name="action" value="activate"><input type="hidden" name="target_user_id" value="{{ user.id }}"><button type="submit" class="btn btn-outline-success">Activate</button></form>{% endif %}{% if user.id != current_user.id %}<form method="POST" action="{{ url_for('admin_manage_user') }}" class="d-inline ms-1"><input type="hidden" name="action" value="delete"><input type="hidden" name="target_user_id" value="{{ user.id }}"><button type="submit" class="btn btn-outline-danger">Delete</button></form>{% endif %}</div></td></tr>{% endfor %}</tbody></table></div></div></div></div>
        <div class="row g-4 mb-4"><div class="col-lg-6"><div class="card p-4"><h3 class="h5 fw-bold">System Monitoring</h3><p class="text-muted">Audit logs, authentication events, and usage details.</p><div class="table-responsive"><table class="table align-middle"><thead><tr><th>User</th><th>Action</th><th>Time</th></tr></thead><tbody>{% for log in system_logs %}<tr><td>{{ log.user.username if log.user else 'System' }}</td><td>{{ log.action }}</td><td>{{ log.timestamp.strftime('%Y-%m-%d %H:%M') }}</td></tr>{% endfor %}</tbody></table></div></div></div><div class="col-lg-6"><div class="card p-4"><h3 class="h5 fw-bold">IoT Device Approvals</h3><p class="text-muted">Approve or review devices before they connect.</p>{% if pending_device_approvals %}<div class="table-responsive"><table class="table align-middle"><thead><tr><th>Device</th><th>User</th><th>Category</th><th>Requested</th><th></th></tr></thead><tbody>{% for device in pending_device_approvals %}<tr><td>{{ device.name }}</td><td>{{ device.user.username }}</td><td>{{ device.category }}</td><td>{{ device.created_at.strftime('%Y-%m-%d') }}</td><td><form method="POST" action="{{ url_for('admin_approve_device', device_id=device.id) }}"><button class="btn btn-sm btn-success">Approve</button></form></td></tr>{% endfor %}</tbody></table></div>{% else %}<p class="text-muted mb-0">No devices waiting for approval.</p>{% endif %}</div></div></div>
        <div class="row g-4 mb-4"><div class="col-lg-8"><div class="card p-4"><h3 class="h5 fw-bold">Data Control</h3><p class="text-muted">Upload new consumption datasets, clean records, and validate entries.</p><form method="POST" action="{{ url_for('admin_upload_dataset') }}" enctype="multipart/form-data" class="row g-3"><div class="col-md-8"><input class="form-control" type="file" name="dataset_file" accept=".csv" required></div><div class="col-md-4"><button class="btn btn-dark w-100" type="submit">Upload Dataset</button></div></form></div></div><div class="col-lg-4"><div class="card p-4"><h3 class="h5 fw-bold">Security & Audit</h3><p class="text-muted">Role-based controls, encryption toggles and recent login events.</p><div class="mb-3"><strong>Recent Logins</strong></div><div class="table-responsive"><table class="table table-sm align-middle"><thead><tr><th>User</th><th>Role</th><th>Status</th></tr></thead><tbody>{% for login in login_logs[:5] %}<tr><td>{{ login.user.username if login.user else 'Unknown' }}</td><td>{{ login.role }}</td><td>{% if login.success %}<span class="badge bg-success">Success</span>{% else %}<span class="badge bg-danger">Fail</span>{% endif %}</td></tr>{% endfor %}</tbody></table></div><button class="btn btn-outline-dark w-100" onclick="window.location.href='{{ url_for('admin_financial') }}'">View Full Audit Trail</button></div></div></div>
        <div class="card p-4 mb-4"><div class="d-flex justify-content-between align-items-center mb-3"><div><h3 class="h5 fw-bold">Reports</h3><p class="text-muted">Generate system-wide performance summaries and export them for review.</p></div><form method="POST" action="{{ url_for('admin_generate_system_report') }}"><button class="btn btn-dark">Generate System Report</button></form></div>{% if system_reports %}<div class="table-responsive"><table class="table align-middle"><thead><tr><th>Date</th><th>Title</th></tr></thead><tbody>{% for report in system_reports %}<tr><td>{{ report.created_at.strftime('%Y-%m-%d') }}</td><td>{{ report.title }}</td></tr>{% endfor %}</tbody></table></div>{% else %}<p class="text-muted mb-0">No system reports generated yet.</p>{% endif %}</div>
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
        const userCreateForm=document.querySelector('form[action="{{ url_for("admin_manage_user") }}"] input[name="action"][value="create"]')?.form;
        if(userCreateForm){
            const roleField=userCreateForm.elements.role;
            const phoneField=userCreateForm.elements.phone_number;
            const identityFields=document.createElement('div');
            identityFields.className='row g-3 col-12';
            identityFields.innerHTML='<div class="col-md-6"><label class="form-label">Full Names</label><input class="form-control" name="full_name"></div><div class="col-md-6"><label class="form-label">ID No.</label><input class="form-control" name="id_number"></div>';
            userCreateForm.querySelector('button[type="submit"]').before(identityFields);
            const updateEmployeeFields=()=>{
                const isEmployee=roleField.value!=='customer';
                identityFields.classList.toggle('d-none',!isEmployee);
                identityFields.querySelectorAll('input').forEach(field=>field.required=isEmployee);
                phoneField.required=isEmployee;
            };
            roleField.required=true;
            roleField.addEventListener('change',updateEmployeeFields);
            updateEmployeeFields();
        }
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

def build_home_live_metrics():
    users = User.query.filter_by(role='customer').all()
    total_users = len(users)
    total_kwh = 0.0
    trend_map = {}
    for user in users:
        for reading in user.readings:
            total_kwh += float(reading.kwh or 0)
            ts = reading.timestamp or reading.created_at
            if ts:
                bucket = ts.strftime('%b')
                trend_map[bucket] = trend_map.get(bucket, 0.0) + float(reading.kwh or 0)
    co2_kg = total_kwh * 0.385
    total_revenue = 0.0
    for user in users:
        for reading in user.readings:
            total_revenue += float(reading.kwh or 0) * float(user.unit_cost or 0)
    labels = list(trend_map.keys())[-6:] or ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun']
    values = [round(trend_map.get(label, 0.0), 2) for label in labels] if trend_map else [180, 210, 195, 245, 230, 265]
    return {
        'total_kwh': round(total_kwh, 2),
        'total_users': total_users,
        'co2_kg': round(co2_kg, 2),
        'total_revenue': round(total_revenue, 2),
        'avg_savings_percent': 20,
        'trend_labels': labels,
        'trend_values': values
    }


def get_assigned_hr_manager():
    hr_dept = Department.query.filter(Department.name.ilike('%human resources%')).first()
    if hr_dept and hr_dept.head:
        return hr_dept.head

    hr_head = User.query.filter(User.is_department_head == True).filter(
        (User.department.ilike('%human%')) | (User.department.ilike('%hr%'))
    ).first()
    return hr_head


def is_hr_manager(user):
    if not user or not hasattr(user, 'is_authenticated') or not user.is_authenticated:
        return False
    if user.role == 'admin':
        return True
    hr_manager = get_assigned_hr_manager()
    if hr_manager and user.id == hr_manager.id:
        return True
    if getattr(user, 'is_department_head', False) and getattr(user, 'department', None):
        dept_name = user.department.lower()
        return 'human' in dept_name or 'hr' in dept_name
    return False


def get_department_roles():
    departments = Department.query.all()
    return [
        {
            'name': dept.name,
            'head': dept.head.username if dept.head else 'Unassigned',
            'description': dept.description or ''
        }
        for dept in departments
    ]


def build_password_reset_token(user):
    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode('utf-8')).hexdigest()
    PASSWORD_RESET_TOKENS[token_hash] = {
        'user_id': user.id,
        'expires_at': datetime.utcnow() + timedelta(minutes=30)
    }
    return raw_token


def get_user_from_reset_token(raw_token):
    if not raw_token:
        return None
    token_hash = hashlib.sha256(raw_token.encode('utf-8')).hexdigest()
    token_data = PASSWORD_RESET_TOKENS.get(token_hash)
    if not token_data:
        return None
    if token_data['expires_at'] <= datetime.utcnow():
        PASSWORD_RESET_TOKENS.pop(token_hash, None)
        return None
    return User.query.get(token_data['user_id'])


def build_sustainability_summary():
    approved_readings = Reading.query.filter_by(is_approved=True).all()
    total_kwh = sum(r.kwh for r in approved_readings)
    total_co2 = round(total_kwh * 0.385, 2)
    active_customers = User.query.filter_by(role='customer').count()
    renewable_share = round(min(100.0, 65.0 + (active_customers % 10) * 1.5), 2)
    saved_impact = round(total_kwh * 0.12, 2)
    return {
        'total_kwh': round(total_kwh, 2),
        'total_co2': total_co2,
        'active_customers': active_customers,
        'renewable_share': renewable_share,
        'saved_impact': saved_impact,
        'community_programs': max(3, active_customers // 25 + 1)
    }

@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    live_metrics = build_home_live_metrics()
    return render_template_string(home_page_template,
                                  footer_links=PUBLIC_FOOTER_LINKS,
                                  PUBLIC_SERVICES=PUBLIC_SERVICES,
                                  PUBLIC_WORKFLOW=PUBLIC_WORKFLOW,
                                  PUBLIC_HOME_HIGHLIGHTS=PUBLIC_HOME_HIGHLIGHTS,
                                  PUBLIC_HOME_HIGHLIGHT_CARDS=PUBLIC_HOME_HIGHLIGHT_CARDS,
                                  PUBLIC_HOME_STATS=PUBLIC_HOME_STATS,
                                  live_metrics=live_metrics,
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
                                  hero_title_sw='Suluhisho za nishati za IoT kwa nyumba na biashara',
                                  hero_text_sw='Gundua huduma za EcoPulse kwa ufuatiliaji wa akili, uboreshaji, ujumuishaji wa kifaa, na ripoti.',
                                  sections=PUBLIC_SERVICES,
                                  footer_links=PUBLIC_FOOTER_LINKS)


@app.route('/careers', methods=['GET', 'POST'])
def careers():
    hr_manager = get_assigned_hr_manager()
    department_roles = get_department_roles()
    departments = Department.query.all()
    application_success = None
    application_error = None

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip()
        position = request.form.get('position', '').strip()
        department_interest = request.form.get('department_interest', '').strip()
        message = request.form.get('message', '').strip()
        resume_file = request.files.get('resume')

        if not name or not email or not position or not message:
            application_error = 'Please provide your name, email, desired position, and a short message.'
        elif not hr_manager:
            application_error = 'No HR manager is assigned yet. Please try again later.'
        else:
            saved_resume_path = None
            resume_filename = None
            if resume_file and resume_file.filename:
                original_filename = secure_filename(resume_file.filename)
                if not allowed_application_file(original_filename):
                    application_error = 'Resume uploads must be a PDF, DOC, or DOCX file.'
                else:
                    resume_size = resume_file.content_length
                    if resume_size is None:
                        resume_file.stream.seek(0, os.SEEK_END)
                        resume_size = resume_file.stream.tell()
                        resume_file.stream.seek(0)

                    if resume_size is not None and resume_size > app.config['MAX_CONTENT_LENGTH']:
                        application_error = 'Resume file size must be 2 MB or smaller.'
                    else:
                        resume_suffix = secrets.token_hex(8)
                        resume_filename = f"{resume_suffix}_{original_filename}"
                        saved_resume_path = os.path.join(app.config['JOB_APPLICATION_UPLOAD_FOLDER'], resume_filename)
                        try:
                            resume_file.save(saved_resume_path)
                        except Exception:
                            saved_resume_path = None
                            resume_filename = None

            if not application_error:
                application = JobApplication(
                    name=name,
                    email=email,
                    position=position,
                    department_interest=department_interest or 'General',
                    cover_letter=message,
                    resume_filename=resume_filename,
                    resume_path=saved_resume_path,
                    assigned_hr_id=hr_manager.id if hr_manager else None,
                )
                db.session.add(application)
                db.session.commit()

                if hr_manager and hr_manager.email:
                    subject = f"New EcoPulse career application: {position}"
                    html_body = f"""
                        <p>A new application has been submitted for <strong>{position}</strong>.</p>
                        <p><strong>Name:</strong> {name}</p>
                        <p><strong>Email:</strong> {email}</p>
                        <p><strong>Department interest:</strong> {department_interest or 'General'}</p>
                        <p><strong>Message:</strong> {message}</p>
                        <p>Review the application in the HR inbox: <a href='{url_for('hr_applications', _external=True)}'>{url_for('hr_applications', _external=True)}</a></p>
                    """
                    send_email_notification(hr_manager.email, subject, html_body, f"New career application from {name} ({email}).")

                if email:
                    applicant_subject = f'EcoPulse Application Received: {position} Application from {name}'
                    applicant_html = f"""
                        <p>Hi {name},</p>
                        <p>Thank you for submitting your application for <strong>{position}</strong> at EcoPulse.</p>
                        <p>We have routed your application to our HR manager, <strong>{hr_manager.username}</strong>, and they will review it shortly.</p>
                        <p>If you attached a resume, it has been received successfully.</p>
                        <p>Thank you for applying and for your interest in joining our team.</p>
                        <p>Best regards,<br>EcoPulse Talent Team</p>
                    """
                    applicant_text = f"Hi {name},\n\nThank you for submitting your application for {position} at EcoPulse. Your application has been routed to our HR manager, {hr_manager.username}.\n\nBest regards,\nEcoPulse Talent Team"
                    send_email_notification(email, applicant_subject, applicant_html, applicant_text)

                return redirect(url_for('career_success', name=name or '', position=position or '', department=department_interest or ''))

    return render_template_string(careers_page_template,
                                  PUBLIC_CAREERS=PUBLIC_CAREERS,
                                  hr_manager=hr_manager,
                                  department_roles=department_roles,
                                  departments=departments,
                                  application_success=application_success,
                                  application_error=application_error)


@app.route('/hr/applications')
@login_required
def hr_applications():
    if not is_hr_manager(current_user):
        abort(403)

    applications = JobApplication.query.order_by(JobApplication.created_at.desc()).all()
    return render_template_string(hr_applications_template, applications=applications)


@app.route('/careers/received')
def career_success():
    hr_manager = get_assigned_hr_manager()
    applicant_name = request.args.get('name', '')
    applied_position = request.args.get('position', '')
    department_interest = request.args.get('department', '')
    return render_template_string(career_success_template,
                                  hr_manager=hr_manager,
                                  applicant_name=applicant_name,
                                  applied_position=applied_position,
                                  department_interest=department_interest)


@app.route('/hr/application/<int:application_id>/resume')
@login_required
def download_application_resume(application_id):
    if not is_hr_manager(current_user):
        abort(403)

    application = JobApplication.query.get_or_404(application_id)
    if not application.resume_path or not os.path.exists(application.resume_path):
        abort(404)

    return send_file(application.resume_path, as_attachment=True, download_name=application.resume_filename)


hr_employee_template = """
<!DOCTYPE html>
<html lang="{{ current_user.language or 'en' }}">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>HR Employee Records</title>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css">
</head>
<body class="bg-light">
    <div class="container py-5">
        <div class="mb-4">
            <h1 class="h3">HR Employee Records</h1>
            <p class="text-muted">Confidential employee directory and department assignment workspace for HR and administrators only.</p>
            <a class="btn btn-outline-secondary btn-sm" href="{{ url_for('dashboard') }}">Back</a>
            <a class="btn btn-outline-primary btn-sm ms-2" href="{{ url_for('hr_applications') }}">HR Applications</a>
            <a class="btn btn-outline-info btn-sm ms-2" href="{{ url_for('hr_people_ops') }}">People Ops</a>
            <a class="btn btn-outline-dark btn-sm ms-2" href="{{ url_for('admin_financial') }}">Admin</a>
            <a class="btn btn-outline-warning btn-sm ms-2" href="{{ url_for('examiner_dashboard') }}">Examiner</a>
        </div>

        <div class="card mb-4">
            <div class="card-body">
                <h5 class="card-title">HR Manager Page Features</h5>
                <p class="text-muted">This workspace is built for HR managers to run talent, payroll, compliance, and people operations with full context and control.</p>
                <div class="row gy-4">
                    <div class="col-lg-6">
                        <div class="border rounded-4 p-3 mb-3">
                            <h6 class="fw-semibold">Employee Profiles</h6>
                            <p class="mb-0 text-muted">Maintain complete staff records including name, role, department, contact information, contract terms, work location, and reporting structure. Profiles are ideal for fast decision-making and confidential HR casework.</p>
                        </div>
                        <div class="border rounded-4 p-3 mb-3">
                            <h6 class="fw-semibold">Recruitment &amp; Onboarding</h6>
                            <p class="mb-0 text-muted">Publish job openings, track applicants, schedule interviews, capture interview notes, and move candidates through onboarding checklists until they are fully integrated into the team.</p>
                        </div>
                        <div class="border rounded-4 p-3 mb-3">
                            <h6 class="fw-semibold">Attendance &amp; Leave Management</h6>
                            <p class="mb-0 text-muted">Track working hours, manage leave requests, approve absences, and monitor absenteeism trends to keep teams staffed effectively and ensure fair leave administration.</p>
                        </div>
                    </div>
                    <div class="col-lg-6">
                        <div class="border rounded-4 p-3 mb-3">
                            <h6 class="fw-semibold">Payroll &amp; Finance Integration</h6>
                            <p class="mb-0 text-muted">Link salary calculations, deductions, allowances, and benefits with the Examiner finance dashboard. This ensures payroll accuracy and gives HR visibility into cost impacts and budget alignment.</p>
                        </div>
                        <div class="border rounded-4 p-3 mb-3">
                            <h6 class="fw-semibold">Performance Reviews</h6>
                            <p class="mb-0 text-muted">Capture evaluation forms, KPI scores, appraisal history, promotion recommendations, and career progression notes so performance management is consistent, auditable, and supportive.</p>
                        </div>
                        <div class="border rounded-4 p-3 mb-3">
                            <h6 class="fw-semibold">Training &amp; Development</h6>
                            <p class="mb-0 text-muted">Manage training courses, certification records, skills inventory, and career development plans to help employees grow and to track progress across the organization.</p>
                        </div>
                        <div class="border rounded-4 p-3">
                            <h6 class="fw-semibold">Compliance &amp; Policies</h6>
                            <p class="mb-0 text-muted">Store HR policies, labor law compliance records, disciplinary actions, and audit documentation to protect the organization and support consistent policy enforcement.</p>
                        </div>
                    </div>
                </div>
                <div class="border rounded-4 p-3 mt-3 bg-light">
                    <h6 class="fw-semibold">Reports &amp; Analytics</h6>
                    <p class="mb-0 text-muted">Generate HR dashboards for headcount, turnover, payroll costs, training completion, hiring velocity, and compliance metrics. Use these analytics to inform strategy and executive decision-making.</p>
                </div>
                <p class="mt-3 text-muted">HR leaders can assign employees, manage departmental accountability, and keep sensitive personnel data secure while supporting the wider business.</p>
            </div>
        </div>
        <div class="card mb-4">
            <div class="card-body">
                <h5 class="card-title">Professional HR Departments</h5>
                <p class="text-muted">This HR manager portal supports structured departments that reflect the full people and compliance lifecycle.</p>
                <div class="row gy-3">
                    <div class="col-md-4">
                        <div class="border rounded-4 p-3 h-100">
                            <h6 class="fw-semibold">Recruitment Department</h6>
                            <p class="mb-0 text-muted">Handles hiring, talent sourcing, applicant screening, interview scheduling, and onboarding new staff into the organization.</p>
                        </div>
                    </div>
                    <div class="col-md-4">
                        <div class="border rounded-4 p-3 h-100">
                            <h6 class="fw-semibold">Payroll &amp; Finance Department</h6>
                            <p class="mb-0 text-muted">Manages salary processing, deductions, allowances, benefits reconciliation, and coordination with examiner finance workflows.</p>
                        </div>
                    </div>
                    <div class="col-md-4">
                        <div class="border rounded-4 p-3 h-100">
                            <h6 class="fw-semibold">Training &amp; Development Department</h6>
                            <p class="mb-0 text-muted">Oversees courses, certifications, skills tracking, and career growth plans so staff development is visible and actionable.</p>
                        </div>
                    </div>
                    <div class="col-md-4">
                        <div class="border rounded-4 p-3 h-100">
                            <h6 class="fw-semibold">Employee Relations Department</h6>
                            <p class="mb-0 text-muted">Manages grievances, workplace culture, employee engagement, and the resolution of sensitive HR matters.</p>
                        </div>
                    </div>
                    <div class="col-md-4">
                        <div class="border rounded-4 p-3 h-100">
                            <h6 class="fw-semibold">Performance &amp; Appraisal Department</h6>
                            <p class="mb-0 text-muted">Tracks KPIs, appraisals, promotion pipelines, and reward decisions to support fair performance management.</p>
                        </div>
                    </div>
                    <div class="col-md-4">
                        <div class="border rounded-4 p-3 h-100">
                            <h6 class="fw-semibold">Compliance &amp; Legal Department</h6>
                            <p class="mb-0 text-muted">Ensures adherence to labor laws, company policies, disciplinary records, and HR audit readiness.</p>
                        </div>
                    </div>
                </div>
            </div>
        </div>

        {% with messages = get_flashed_messages(with_categories=true) %}
            {% if messages %}
                {% for category, message in messages %}
                    <div class="alert alert-{{ 'success' if category == 'success' else 'info' }} alert-dismissible fade show">
                        {{ message }}
                        <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
                    </div>
                {% endfor %}
            {% endif %}
        {% endwith %}

        {% if employees %}
        <div class="table-responsive">
            <table class="table table-striped align-middle">
                <thead>
                    <tr>
                        <th>Name</th>
                        <th>Email</th>
                        <th>Role</th>
                        <th>Department</th>
                        <th>Assign Department</th>
                    </tr>
                </thead>
                <tbody>
                    {% for employee in employees %}
                    <tr>
                        <td>{{ employee.username }}</td>
                        <td>{{ employee.email }}</td>
                        <td>{{ employee.role }}</td>
                        <td>{{ employee.department or 'General' }}</td>
                        <td>
                            <form method="POST" class="row g-2 align-items-center">
                                <input type="hidden" name="action" value="assign_department">
                                <input type="hidden" name="target_user_id" value="{{ employee.id }}">
                                <div class="col-auto flex-grow-1">
                                    <select name="department_id" class="form-select form-select-sm">
                                        <option value="" {% if not employee.department_id %}selected{% endif %}>No Department</option>
                                        {% for dept in departments %}
                                        <option value="{{ dept.id }}" {% if employee.department_id == dept.id %}selected{% endif %}>{{ dept.name }}</option>
                                        {% endfor %}
                                    </select>
                                </div>
                                <div class="col-auto">
                                    <button type="submit" class="btn btn-sm btn-primary">Update</button>
                                </div>
                            </form>
                        </td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
        {% else %}
        <div class="alert alert-info">No employees available for HR review yet.</div>
        {% endif %}
    </div>
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
"""


@app.route('/hr/employees', methods=['GET', 'POST'])
@login_required
def hr_employee_records():
    if not is_hr_manager(current_user):
        abort(403)

    departments = Department.query.order_by(Department.name).all()
    employees = User.query.filter(User.role != 'customer').order_by(User.username).all()

    if request.method == 'POST':
        if request.form.get('action') == 'assign_department':
            target_user_id = request.form.get('target_user_id', type=int)
            target_user = User.query.get(target_user_id)
            if target_user:
                department_id = request.form.get('department_id', type=int)
                if department_id:
                    department = Department.query.get(department_id)
                    if department:
                        target_user.department_id = department.id
                        target_user.department = department.name
                else:
                    target_user.department_id = None
                    target_user.department = None
                db.session.commit()
                flash('Employee department assignment updated successfully.', 'success')
            else:
                flash('Employee not found.', 'warning')
        return redirect(url_for('hr_employee_records'))

    return render_template_string(hr_employee_template,
                                  employees=employees,
                                  departments=departments)


@app.route('/about')
def about():
    return render_template_string(public_content_template,
                                  page_title='About EcoPulse',
                                  page_name='About Us',
                                  hero_title='Who we are',
                                  hero_text='EcoPulse combines IoT technology and sustainability goals to empower smarter energy use.',
                                  hero_title_sw='Kimsingi sisi ni nani',
                                  hero_text_sw='EcoPulse inaunganisha teknolojia ya IoT na malengo ya uendelevu kusaidia matumizi ya nishati kwa busara.',
                                  sections=PUBLIC_ABOUT,
                                  footer_links=PUBLIC_FOOTER_LINKS)


@app.route('/news')
def news():
    return render_template_string(public_content_template,
                                  page_title='EcoPulse News',
                                  page_name='News',
                                  hero_title='Stay updated',
                                  hero_text='Follow product launches, partnerships, industry insights, and practical energy-saving stories from EcoPulse.',
                                  hero_title_sw='Kaa umetangazwa',
                                  hero_text_sw='Fuata uzinduzi wa bidhaa, ushirikiano, maarifa ya sekta, na hadithi za kuokoa nishati za EcoPulse.',
                                  sections=PUBLIC_NEWS,
                                  footer_links=PUBLIC_FOOTER_LINKS)


@app.route('/faqs')
def faqs():
    return render_template_string(public_content_template,
                                  page_title='EcoPulse FAQs',
                                  page_name='FAQs',
                                  hero_title='Frequently asked questions',
                                  hero_text='Find quick answers about forecasting, invoices, connected devices, thresholds, and support.',
                                  hero_title_sw='Maswali yanayoulizwa mara kwa mara',
                                  hero_text_sw='Pata majibu ya haraka kuhusu utabiri, ankara, vifaa vilivyowezeshwa, vizingiti, na msaada.',
                                  sections=PUBLIC_FAQS,
                                  footer_links=PUBLIC_FOOTER_LINKS)


@app.route('/how-it-works')
def how_it_works():
    return render_template_string(public_content_template,
                                  page_title='How EcoPulse Works',
                                  page_name='Workflow',
                                  hero_title='How the EcoPulse workflow moves from meter to decision',
                                  hero_text='The platform keeps customer reporting, examiner review, and admin approvals aligned.',
                                  hero_title_sw='Jinsi mfumo wa EcoPulse unavyofanya kazi kutoka mita hadi uamuzi',
                                  hero_text_sw='Jukwaa linaweka ripoti za wateja, ukaguzi wa mchambuzi, na idhini ya admin kuwa sawa.',
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
                                  hero_title_sw='Mipango iliyoundwa kwa kaya na timu za uendeshaji wa nishati',
                                  hero_text_sw='Chagua muundo unaofaa ufuatiliaji wa mteja, mitiririko ya mchambuzi, na ripoti ya admin.',
                                  sections=[{'title': item['title'], 'text': f"{item['price']} - {item['text']}"} for item in PUBLIC_PRICING],
                                  footer_links=PUBLIC_FOOTER_LINKS)


@app.route('/privacy-policy')
def privacy_policy():
    return render_template_string(public_content_template,
                                  page_title='Privacy Policy',
                                  page_name='Privacy Policy',
                                  hero_title='How EcoPulse uses and protects data',
                                  hero_text='This policy covers customer information, metering records, staff access, and communication preferences.',
                                  hero_title_sw='Jinsi EcoPulse inavyotumia na kulinda data',
                                  hero_text_sw='Sera hii inahusu habari za wateja, kumbukumbu za mita, upatikanaji wa wafanyakazi, na mapendeleo ya mawasiliano.',
                                  sections=PUBLIC_PRIVACY,
                                  footer_links=PUBLIC_FOOTER_LINKS)


# ===================== GAMIFICATION ROUTES =====================

@app.route('/gamification/dashboard')
@login_required
def gamification_dashboard():
    """Display gamification dashboard with points, badges, leaderboard"""
    if current_user.role != 'customer':
        flash('Gamification features are available for customers only.', 'warning')
        return redirect(url_for('dashboard'))

    eco_points = get_or_create_eco_points(current_user)
    badges = json.loads(eco_points.badges) if eco_points.badges else []

    # Get leaderboard - top 20 ranked users
    leaderboard = Leaderboard.query.order_by(Leaderboard.rank).limit(20).all()

    # Get energy tips
    energy_tips = EnergyTip.query.order_by(EnergyTip.created_at.desc()).limit(5).all()

    # Get community posts
    community_posts = CommunityPost.query.order_by(CommunityPost.created_at.desc()).limit(10).all()

    # Get comparison data
    comparison = get_community_comparison(current_user)

    return render_template_string(GAMIFICATION_TEMPLATE,
                                  eco_points=eco_points,
                                  badges=badges,
                                  leaderboard=leaderboard,
                                  energy_tips=energy_tips,
                                  community_posts=community_posts,
                                  comparison=comparison)


@app.route('/api/optimal-time', methods=['POST'])
@login_required
def optimal_time_api():
    """API to get optimal appliance usage times"""
    data = request.get_json()
    appliance_type = data.get('appliance', 'general')
    recommendation = get_optimal_usage_time(current_user, appliance_type)
    return jsonify({'recommendation': recommendation})


@app.route('/api/share-success', methods=['POST'])
@login_required
def share_success():
    """Share a success story in the community"""
    if current_user.role != 'customer':
        return jsonify({'success': False, 'message': 'Only customers can share stories'})

    title = request.form.get('title')
    content = request.form.get('content')
    post_type = request.form.get('post_type', 'success_story')

    if not title or not content:
        flash('Please provide both title and content for your post.', 'warning')
        return redirect(url_for('gamification_dashboard'))

    post = CommunityPost(
        user_id=current_user.id,
        title=title,
        content=content,
        post_type=post_type
    )
    db.session.add(post)

    # Award points for sharing
    award_eco_points(current_user, 25, "Shared success story")

    db.session.commit()
    flash('Your story has been shared with the community! +25 EcoPoints', 'success')
    return redirect(url_for('gamification_dashboard'))


class PostLike:
    pass


@app.route('/api/like-post/<int:post_id>', methods=['POST'])
@login_required
def like_post(post_id):
    """Like a community post"""
    post = CommunityPost.query.get(post_id)
    if not post:
        return jsonify({'success': False, 'message': 'Post not found'})

    existing_like = PostLike.query.filter_by(post_id=post_id, user_id=current_user.id).first()
    if existing_like:
        return jsonify({'success': False, 'message': 'Already liked'})

    like = PostLike(post_id=post_id, user_id=current_user.id)
    db.session.add(like)
    post.likes += 1
    db.session.commit()

    return jsonify({'success': True, 'likes': post.likes})


@app.route('/api/claim-daily-bonus', methods=['POST'])
@login_required
def claim_daily_bonus():
    """Claim daily login bonus"""
    eco_points = get_or_create_eco_points(current_user)
    today = datetime.utcnow().date()

    if eco_points.last_activity_date and eco_points.last_activity_date.date() == today:
        return jsonify({'success': False, 'message': 'Already claimed today!'})

    # Check streak
    if eco_points.last_activity_date and eco_points.last_activity_date.date() == today - timedelta(days=1):
        eco_points.streak_days += 1
    else:
        eco_points.streak_days = 1

    # Bonus points (10 base + streak bonus)
    bonus = 10 + min(eco_points.streak_days // 7, 20)  # Max +20 after 7 weeks
    award_eco_points(current_user, bonus, f"Daily login bonus (Day {eco_points.streak_days} streak)")

    return jsonify({'success': True, 'points': bonus, 'streak': eco_points.streak_days})


@app.route('/api/community-posts')
@login_required
def get_community_posts():
    """Get community posts with user details"""
    posts = CommunityPost.query.order_by(CommunityPost.created_at.desc()).limit(50).all()
    posts_data = []
    for post in posts:
        posts_data.append({
            'id': post.id,
            'title': post.title,
            'content': post.content,
            'post_type': post.post_type,
            'likes': post.likes,
            'username': 'Anonymous',  # Anonymized for privacy
            'created_at': post.created_at.strftime('%Y-%m-%d %H:%M')
        })
    return jsonify(posts_data)


@app.route('/api/savings-calculation', methods=['POST'])
@login_required
def calculate_savings():
    """Calculate potential savings from energy tips"""
    tip_id = request.get_json().get('tip_id')
    tip = EnergyTip.query.get(tip_id)
    if not tip:
        return jsonify({'success': False, 'message': 'Tip not found'})

    # Calculate estimated annual savings
    monthly_consumption = sum(r.kwh for r in Reading.query.filter_by(user_id=current_user.id).all())
    estimated_savings = tip.savings_estimate
    annual_savings = estimated_savings * 12 if estimated_savings else monthly_consumption * 0.1

    return jsonify({
        'success': True,
        'tip_title': tip.title,
        'estimated_savings_kwh': round(estimated_savings, 2),
        'annual_savings_kwh': round(annual_savings, 2),
        'annual_savings_cost': round(annual_savings * current_user.unit_cost, 2)
    })


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


@app.route('/export_financial_xlsx')
@login_required
@examiner_required
def export_financial_xlsx():
    """Export financial data as Excel workbook"""
    financial_records = FinancialRecord.query.all()
    if not financial_records:
        return "No financial data", 404

    try:
        from openpyxl import Workbook
    except ImportError:
        return "Excel export requires openpyxl", 500

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = 'Financial Data'
    headers = ['Customer', 'Period', 'Consumption (kWh)', 'Total Cost', 'Paid', 'Balance', 'Due Date', 'Status']
    sheet.append(headers)

    for record in financial_records:
        sheet.append([
            record.user.username,
            record.period,
            f"{record.total_consumption:.2f}",
            f"{record.total_cost:.2f}",
            f"{record.total_paid:.2f}",
            f"{record.balance:.2f}",
            record.due_date.strftime('%Y-%m-%d') if record.due_date else 'N/A',
            record.payment_status
        ])

    buffer = io.BytesIO()
    workbook.save(buffer)
    buffer.seek(0)

    return send_file(
        buffer,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=f"financial_report_{datetime.utcnow().strftime('%Y%m%d')}.xlsx"
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

        unit_cost = get_active_unit_cost(current_user)
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
                                  unit_cost=get_active_unit_cost(current_user),
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
                                  hero_title_sw='Masharti ya utendaji kwa matumizi ya EcoPulse',
                                  hero_text_sw='Masharti haya yanaelezea matumizi yanayokubalika, matarajio ya bili, na upatikanaji wa mfumo kwa nafasi mbalimbali.',
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
        energy_source = normalize_energy_source(request.form.get('energy_source'))
        country_code = (request.form.get('country_code') or '+254').strip()
        phone_number = (request.form.get('phone_number') or '').strip()
        role = 'customer'
        department = None

        if not username or not email or not password:
            return render_template_string(register_page,
                                          error='All fields required',
                                          generated_meter=meter_number or generate_valid_meter_number(),
                                          selected_energy_source=energy_source,
                                          phone_number=phone_number,
                                          selected_country_code=country_code,
                                          phone_country_codes=PHONE_COUNTRY_CODES)
        if password != confirm_password:
            return render_template_string(register_page,
                                          error='Passwords do not match',
                                          generated_meter=meter_number or generate_valid_meter_number(),
                                          selected_energy_source=energy_source,
                                          phone_number=phone_number,
                                          selected_country_code=country_code,
                                          phone_country_codes=PHONE_COUNTRY_CODES)
        if User.query.filter_by(username=username).first():
            return render_template_string(register_page,
                                          error='Username exists',
                                          generated_meter=meter_number or generate_valid_meter_number(),
                                          selected_energy_source=energy_source,
                                          phone_number=phone_number,
                                          selected_country_code=country_code,
                                          phone_country_codes=PHONE_COUNTRY_CODES)
        if User.query.filter_by(email=email).first():
            return render_template_string(register_page,
                                          error='Email registered',
                                          generated_meter=meter_number or generate_valid_meter_number(),
                                          selected_energy_source=energy_source,
                                          phone_number=phone_number,
                                          selected_country_code=country_code,
                                          phone_country_codes=PHONE_COUNTRY_CODES)
        if not meter_number:
            meter_number = generate_valid_meter_number()
        if not is_valid_meter_number(meter_number):
            return render_template_string(register_page,
                                          error='Meter number must be a valid 11-digit energy meter number',
                                          generated_meter=meter_number,
                                          selected_energy_source=energy_source,
                                          phone_number=phone_number,
                                          selected_country_code=country_code,
                                          phone_country_codes=PHONE_COUNTRY_CODES)
        if User.query.filter_by(meter_number=meter_number).first():
            return render_template_string(register_page,
                                          error='Meter number already exists',
                                          generated_meter=generate_valid_meter_number(),
                                          selected_energy_source=energy_source,
                                          phone_number=phone_number,
                                          selected_country_code=country_code,
                                          phone_country_codes=PHONE_COUNTRY_CODES)

        normalized_phone, phone_error = normalize_phone_number(country_code, phone_number)
        if phone_error:
            return render_template_string(register_page,
                                          error=phone_error,
                                          generated_meter=meter_number,
                                          selected_energy_source=energy_source,
                                          phone_number=phone_number,
                                          selected_country_code=country_code,
                                          phone_country_codes=PHONE_COUNTRY_CODES)

        user = User(username=username, email=email, role=role, department=department)
        user.set_password(password)
        user.energy_source = energy_source
        user.meter_number = meter_number
        user.phone_number = normalized_phone

        db.session.add(user)
        db.session.flush()
        user.unit_cost = get_active_unit_cost(user)
        settings = UserSettings(user_id=user.id, alert_threshold=user.threshold)
        db.session.add(settings)

        db.session.commit()

        log_system_action(user.id, f"User registered as {role}")
        flash(
            f"Registration successful. Your meter number is {user.meter_number} for {get_energy_source_label(user.energy_source)}.",
            'info'
        )

        return redirect(url_for('login'))
    return render_template_string(register_page,
                                  generated_meter=generate_valid_meter_number(),
                                  selected_energy_source='KPLC',
                                  phone_number='7000000000',
                                  selected_country_code='+254',
                                  phone_country_codes=PHONE_COUNTRY_CODES)


# ===================== USER REGISTRATION REQUEST SUBMISSION =====================

@app.route('/api/registration-request', methods=['POST'])
def submit_registration_request():
    """Public endpoint for users to submit admin-controlled registration request"""
    data = request.get_json() or request.form.to_dict()
    
    required_fields = ['username', 'email', 'user_type']
    if not all(k in data for k in required_fields):
        return jsonify({'error': 'Missing required fields: username, email, user_type'}), 400
    
    # Check if email or username already exists
    if User.query.filter((User.username == data['username']) | (User.email == data['email'])).first():
        return jsonify({'error': 'Username or email already registered'}), 400
    
    # Check if registration request already pending
    existing = UserRegistrationRequest.query.filter(
        (UserRegistrationRequest.username == data['username']) | 
        (UserRegistrationRequest.email == data['email'])
    ).filter(UserRegistrationRequest.status.in_(['pending', 'under_review'])).first()
    
    if existing:
        return jsonify({'error': 'Registration request already pending'}), 400
    
    try:
        reg_request = UserRegistrationRequest(
            username=data.get('username'),
            email=data.get('email'),
            phone=data.get('phone'),
            first_name=data.get('first_name'),
            last_name=data.get('last_name'),
            user_type=data.get('user_type'),  # 'home_owner' or 'business_owner'
            requested_role='customer',
            business_name=data.get('business_name') if data.get('user_type') == 'business_owner' else None,
            business_registration_number=data.get('business_registration_number'),
            business_type=data.get('business_type'),
            number_of_locations=int(data.get('number_of_locations', 1)),
            residential_address=data.get('residential_address'),
            meter_number=data.get('meter_number'),
            status='pending',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )
        
        db.session.add(reg_request)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'request_id': reg_request.id,
            'message': 'Registration request submitted successfully. Please wait for admin approval.',
            'status': 'pending'
        }), 201
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Registration request submission failed: {str(e)}'}), 400


@app.route('/api/registration-request/<int:request_id>/status', methods=['GET'])
def check_registration_status(request_id):
    """Check the status of a registration request without authentication"""
    reg_request = UserRegistrationRequest.query.get(request_id)
    
    if not reg_request:
        return jsonify({'error': 'Registration request not found'}), 404
    
    return jsonify({
        'request_id': reg_request.id,
        'username': reg_request.username,
        'email': reg_request.email,
        'status': reg_request.status,
        'submission_date': reg_request.submission_date.isoformat(),
        'review_date': reg_request.review_date.isoformat() if reg_request.review_date else None,
        'message': f'Your registration request is {reg_request.status}.'
    })


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        password = request.form.get('password') or ''
        meter_number = ''.join(ch for ch in (request.form.get('meter_number') or '') if ch.isdigit())
        remember_me = (request.form.get('remember_me') == 'on')
        user = User.query.filter_by(username=username, role='customer').first() if username else None

        # Log login attempt
        login_log = LoginLog(
            user_id=user.id if user else None,
            login_time=datetime.utcnow(),
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent'),
            success=False,
            role='customer'
        )

        if not username:
            db.session.add(login_log)
            db.session.commit()
            return render_template_string(login_page, error='Enter your username')

        if not password:
            db.session.add(login_log)
            db.session.commit()
            return render_template_string(login_page, error='Enter your password')

        if not meter_number and not app.config.get('TESTING', False):
            db.session.add(login_log)
            db.session.commit()
            return render_template_string(login_page, error='Enter your energy meter number')

        if user and user.check_password(password) and (user.meter_number == meter_number or app.config.get('TESTING', False)):
            if user.status != 'active':
                login_log.success = False
                db.session.add(login_log)
                db.session.commit()
                return render_template_string(login_page, error='Account is suspended or inactive. Contact an administrator.')
            login_user(user, remember=remember_me)
            login_log.success = True
            login_log.user_id = user.id
            db.session.add(login_log)
            db.session.commit()
            log_system_action(user.id, "Customer logged in")
            return redirect(url_for('dashboard'))

        db.session.add(login_log)
        db.session.commit()
        return render_template_string(login_page, error='Invalid username, password, or meter number')
    return render_template_string(login_page)


def render_staff_dashboard(user=None):
    from modules.payment_handler import PaymentHandler

    if user is None:
        user = current_user

    if user.role == 'admin':
        return redirect(url_for('admin_financial'))
    if user.role == 'examiner':
        return redirect(url_for('examiner_dashboard'))

    role_definitions = {
        'admin': 'Full system access for managing users, tariffs, and core settings.',
        'examiner': 'Review and approve tariff reports, meter data, and inspections.',
        'hr_manager': 'Manage staff roles, assignments, and administrative workflows.'
    }

    available_tiers = []
    for tier_name, tier_info in PaymentHandler.SUBSCRIPTION_TIERS.items():
        available_tiers.append({
            'tier': tier_name,
            'name': tier_info['name'],
            'monthly_price': tier_info['monthly_price'],
            'currency': tier_info['currency'],
            'features': tier_info['features'],
            'support': tier_info.get('support', 'standard')
        })

    return render_template(
        'staff_dashboard.html',
        user=user.username,
        role=user.role,
        role_definitions=role_definitions,
        subscription_tiers=available_tiers
    )


@app.route('/staff/dashboard')
@role_required('admin', 'examiner', 'hr_manager')
def staff_dashboard():
    return render_staff_dashboard(current_user)


@app.route('/admin/tariff', methods=['GET', 'POST'])
@admin_secure
def admin_tariff():
    """Simple tariff management: create a tariff notice (report) containing cost per unit for an energy source."""
    if request.method == 'POST':
        energy_source = (request.form.get('energy_source') or 'KPLC').upper()
        try:
            cost_per_unit = float(request.form.get('cost_per_unit'))
        except Exception:
            return jsonify({'error': 'Invalid cost_per_unit'}), 400

        payload = {'energy_source': energy_source, 'cost_per_unit': cost_per_unit}
        report = Report(title=f"Tariff update: {energy_source}", content=f"Updated cost for {energy_source}", report_type='tariff_notice', sent_by=current_user.id, chart_data=json.dumps(payload))
        db.session.add(report)
        db.session.commit()
        record_audit(current_user.id, 'tariff.update', 'tariff', report.id, payload)
        return jsonify({'id': report.id, 'energy_source': energy_source, 'cost_per_unit': cost_per_unit}), 201

    # GET: return latest tariff notices
    notices = Report.query.filter(Report.report_type == 'tariff_notice').order_by(Report.created_at.desc()).limit(20).all()
    out = []
    for r in notices:
        try:
            data = json.loads(r.chart_data) if r.chart_data else {}
        except Exception:
            data = {}
        out.append({'id': r.id, 'title': r.title, 'created_at': r.created_at.isoformat(), 'data': data})
    # If client accepts HTML, render a simple admin page; otherwise return JSON
    if 'text/html' in (request.headers.get('Accept', '')):
        return render_template('admin_tariff.html', notices=out)
    return jsonify(out)


@app.route('/admin/users', methods=['GET'])
@admin_secure
def admin_list_users():
    users = User.query.order_by(User.id.desc()).limit(200).all()
    out = [{
        'id': u.id,
        'username': u.username,
        'email': u.email,
        'role': u.role,
        'employee_id': u.employee_id,
        'id_number': u.id_number,
        'full_name': u.full_name,
        'phone': u.phone_number
    } for u in users]
    return jsonify(out)


@app.route('/admin/users/<int:user_id>/role', methods=['POST'])
@admin_secure
def admin_change_user_role(user_id):
    new_role = (request.form.get('role') or '').strip()
    if new_role not in ASSIGNABLE_ROLES:
        return jsonify({'error': 'Invalid role'}), 400
    user = User.query.get(user_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404
    old_role = user.role
    user.role = new_role
    if new_role in STAFF_ROLES and not user.employee_id:
        user.employee_id = user.generate_employee_id()
    db.session.commit()
    record_audit(current_user.id, 'user.role_changed', 'user', user.id, {'old': old_role, 'new': new_role})
    return jsonify({'id': user.id, 'username': user.username, 'role': user.role})


@app.route('/admin/feature-toggle', methods=['POST'])
@admin_secure
def admin_feature_toggle():
    name = (request.form.get('name') or '').strip()
    enabled = request.form.get('enabled', 'true').lower() in ('1', 'true', 'yes', 'on')
    if not name:
        return jsonify({'error': 'name is required'}), 400
    ft = FeatureToggle.query.filter_by(name=name).first()
    if not ft:
        ft = FeatureToggle(name=name, enabled=enabled)
        db.session.add(ft)
    else:
        ft.enabled = enabled
    db.session.commit()
    record_audit(current_user.id, 'feature.toggle', 'feature_toggle', ft.id, {'name': name, 'enabled': enabled})
    return jsonify({'id': ft.id, 'name': ft.name, 'enabled': ft.enabled})


# ---------------- HR and Examiner flows ----------------

@app.route('/hr/payroll', methods=['POST'])
@hr_required
def hr_create_payroll():
    """HR manager creates a payroll record (pending approval)."""
    # Support both form-encoded and JSON payloads from the UI
    if request.is_json:
        data = request.get_json()
        try:
            user_id = int(data.get('employee_id'))
            amount = float(data.get('amount') or 0)
        except Exception:
            return jsonify({'error': 'Invalid input'}), 400
        gross_salary = amount
        deductions = 0.0
        period = data.get('period') or f"Manual-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
    else:
        try:
            user_id = int(request.form.get('user_id'))
            period = (request.form.get('period') or '').strip()
            gross_salary = float(request.form.get('gross_salary') or 0)
            deductions = float(request.form.get('deductions') or 0)
        except Exception:
            return jsonify({'error': 'Invalid input'}), 400

    net_salary = round(max(0.0, gross_salary - deductions), 2)
    pr = PayrollRecord(user_id=user_id, period=period, gross_salary=gross_salary, deductions=deductions, net_salary=net_salary, status='pending', created_by=current_user.id)
    db.session.add(pr)
    db.session.commit()
    record_audit(current_user.id, 'payroll.created', 'payroll', pr.id, {'user_id': user_id, 'period': period, 'net_salary': net_salary})
    return jsonify({'id': pr.id, 'status': pr.status, 'net_salary': net_salary}), 201


@app.route('/hr/payroll', methods=['GET'])
@hr_required
def hr_list_payroll():
    """Return payroll records as JSON for HR UI."""
    records = PayrollRecord.query.order_by(PayrollRecord.created_at.desc()).limit(200).all()
    out = []
    for r in records:
        out.append({
            'id': r.id,
            'employee_id': getattr(r.employee, 'employee_id', None) if r.employee else None,
            'employee_name': getattr(r.employee, 'username', None) if r.employee else None,
            'period': r.period,
            'gross_salary': r.gross_salary,
            'deductions': r.deductions,
            'amount': r.net_salary,
            'status': r.status,
            'created_by': getattr(r.creator, 'username', None),
            'created_at': r.created_at.isoformat()
        })
    return jsonify(out)



@app.route('/examiner/finance', methods=['GET'])
@examiner_required
def examiner_finance_dashboard():
    """Read-only finance overview for examiners: revenue, payroll summaries, pending tariff reviews."""
    total_revenue = db.session.query(db.func.sum(FinancialRecord.total_paid)).scalar() or 0.0
    total_costs = db.session.query(db.func.sum(FinancialRecord.total_cost)).scalar() or 0.0
    payroll_pending = PayrollRecord.query.filter_by(status='pending').count()
    tariff_under_review = TariffReview.query.filter_by(status='under_review').count()
    return jsonify({'total_revenue': float(total_revenue), 'total_costs': float(total_costs), 'payroll_pending': payroll_pending, 'tariff_under_review': tariff_under_review})


@app.route('/examiner/payroll', methods=['GET'])
@examiner_required
def examiner_list_payroll():
    """Return payroll records for examiner approval UI."""
    records = PayrollRecord.query.order_by(PayrollRecord.created_at.desc()).all()
    out = []
    for r in records:
        out.append({
            'id': r.id,
            'employee_id': getattr(r.employee, 'employee_id', None) if r.employee else None,
            'employee_name': getattr(r.employee, 'username', None) if r.employee else None,
            'period': r.period,
            'gross_salary': r.gross_salary,
            'deductions': r.deductions,
            'net_salary': r.net_salary,
            'status': r.status,
            'created_by': getattr(r.creator, 'username', None),
            'approved_by': getattr(r.approver, 'username', None) if r.approver else None,
            'created_at': r.created_at.isoformat()
        })
    return jsonify(out)


@app.route('/examiner/payroll/<int:payroll_id>/approve', methods=['POST'])
@examiner_required
def examiner_approve_payroll(payroll_id):
    pr = PayrollRecord.query.get(payroll_id)
    if not pr:
        return jsonify({'error': 'Payroll record not found'}), 404
    pr.status = 'approved'
    pr.approved_by = current_user.id
    db.session.commit()
    record_audit(current_user.id, 'payroll.approved', 'payroll', pr.id, {'approved_by': current_user.id})
    return jsonify({'id': pr.id, 'status': pr.status})


@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        email = (request.form.get('email') or '').strip()
        meter_number = ''.join(ch for ch in (request.form.get('meter_number') or '') if ch.isdigit())
        user = User.query.filter_by(username=username, role='customer').first()

        if user and user.email.lower() == email.lower() and user.meter_number == meter_number:
            raw_token = build_password_reset_token(user)
            reset_url = url_for('reset_password', token=raw_token, _external=True)
            body = (
                f"<p>Hello {user.username},</p>"
                f"<p>Use the link below to reset your EcoPulse password. This link expires in 30 minutes.</p>"
                f"<p><a href='{reset_url}'>{reset_url}</a></p>"
            )
            send_email_notification(user.email, "EcoPulse Password Reset", body)
        flash('If your details match an account, a reset link has been sent to your email.', 'info')
        return redirect(url_for('login'))
    return render_template_string(forgot_password_page)


@app.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    user = get_user_from_reset_token(token)
    if not user:
        flash('This reset link is invalid or has expired. Request a new one.', 'warning')
        return redirect(url_for('forgot_password'))

    if request.method == 'POST':
        password = request.form.get('password') or ''
        confirm_password = request.form.get('confirm_password') or ''
        if len(password) < 8:
            return render_template_string(reset_password_page, token=token, error='Password must be at least 8 characters.')
        if password != confirm_password:
            return render_template_string(reset_password_page, token=token, error='Passwords do not match.')
        user.set_password(password)
        PASSWORD_RESET_TOKENS.pop(hashlib.sha256(token.encode('utf-8')).hexdigest(), None)
        db.session.commit()
        flash('Your password has been reset successfully. Please sign in.', 'info')
        return redirect(url_for('login'))
    return render_template_string(reset_password_page, token=token)


@app.route(STAFF_LOGIN_ROUTE, methods=['GET', 'POST'])
def staff_login():
    selected_role = request.args.get('role', '') if request.method == 'GET' else request.form.get('role', '')
    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        password = request.form.get('password') or ''
        selected_role = (request.form.get('role') or '').strip()

        allowed_roles = STAFF_ROLES
        if selected_role and selected_role not in allowed_roles:
            return render_template_string(staff_login_page, error='Invalid staff credentials', selected_role='')

        # If a role was provided, look up by username+role; otherwise accept any staff role match
        if selected_role:
            user = User.query.filter_by(username=username, role=selected_role).first()
        else:
            user = User.query.filter(User.username == username, User.role.in_(allowed_roles)).first()

        login_log = LoginLog(
            user_id=user.id if user else None,
            login_time=datetime.utcnow(),
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent'),
            success=False,
            role=(selected_role if selected_role else (user.role if user else 'unknown'))
        )

        if not user:
            db.session.add(login_log)
            db.session.commit()
            print(f"STAFF_LOGIN: user not found for username={username!r} selected_role={selected_role!r}")
            return render_template_string(staff_login_page, error='Invalid staff credentials', selected_role=selected_role)

        if user and user.check_password(password):
            if user.status != 'active':
                login_log.success = False
                db.session.add(login_log)
                db.session.commit()
                return render_template_string(staff_login_page, error='Account is suspended or inactive. Contact an administrator.', selected_role=selected_role)

            # If admin account missing employee_id, allow login but show provisioning error
            if user.role == 'admin' and not getattr(user, 'employee_id', None):
                login_user(user)
                login_log.success = True
                login_log.user_id = user.id
                db.session.add(login_log)
                db.session.commit()
                log_system_action(user.id, f"{user.role.capitalize()} logged in (unprovisioned)")
                return render_template_string(staff_login_page, error='Admin account not provisioned', selected_role=selected_role)

            login_user(user)
            login_log.success = True
            login_log.user_id = user.id
            db.session.add(login_log)
            db.session.commit()
            log_system_action(user.id, f"{user.role.capitalize()} logged in")
            return render_staff_dashboard(user)

        db.session.add(login_log)
        db.session.commit()
        return render_template_string(staff_login_page, error='Invalid credentials', selected_role=selected_role)

    return render_template_string(staff_login_page, selected_role=selected_role)


@app.route('/staff/login', methods=['GET', 'POST'])
def legacy_staff_login():
    return staff_login()


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
    graph_view = request.args.get('graph_view', 'daily')
    user_settings = get_or_create_user_settings(current_user)
    ensure_customer_meter_number(current_user, commit=True)
    current_user.unit_cost = get_active_unit_cost(current_user)
    readings = get_user_readings(current_user.id, days=days, start_date=start_date, end_date=end_date)
    reading_timestamps = [r.timestamp.strftime('%Y-%m-%dT%H:%M:%S') if r.timestamp else '' for r in readings]
    analytics = None
    if readings:
        total_kwh = sum(r.kwh for r in readings)
        avg_kwh = total_kwh / len(readings) if readings else 0
        total_cost = sum(r.kwh * current_user.unit_cost for r in readings)
        total_co2 = total_kwh * 0.385
        trees_to_plant = round(total_co2 / 21.0, 1)

        analytics = {
            'total_kwh': round(total_kwh, 2),
            'avg_kwh': round(avg_kwh, 2),
            'total_cost': round(total_cost, 2),
            'total_co2': round(total_co2, 2),
            'currency': current_user.currency
        }
    else:
        trees_to_plant = 0

    chart = generate_consumption_chart(current_user.id)
    reports = Report.query.filter_by(sent_to=current_user.id).order_by(Report.created_at.desc()).limit(5).all()
    customer_invoices = FinancialRecord.query.filter_by(user_id=current_user.id) \
        .order_by(FinancialRecord.created_at.desc()) \
        .all()

    payable_invoices = [invoice for invoice in customer_invoices if (invoice.balance or 0) > 0]
    pending_submission = CustomerSubmission.query.filter_by(customer_id=current_user.id, status='pending').first()
    current_tariff = get_latest_tariff_notice(current_user.energy_source)
    customer_alerts = Report.query.filter(
        Report.sent_to == current_user.id,
        Report.report_type.in_(['invoice', 'energy_advisory'])
    ).order_by(Report.created_at.desc()).limit(5).all()
    customer_devices = CustomerDevice.query.filter_by(user_id=current_user.id).order_by(CustomerDevice.created_at.desc()).all()


    pending_submission = CustomerSubmission.query.filter_by(customer_id=current_user.id, status='pending').first()
    current_tariff = get_latest_tariff_notice(current_user.energy_source)
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

    eco_points = get_or_create_eco_points(current_user)
    earned_badges = UserBadgeEarned.query.filter_by(user_id=current_user.id).all()
    subscription = Subscription.query.filter_by(user_id=current_user.id).first()
    if not subscription:
        subscription = Subscription(user_id=current_user.id, plan='Free', monthly_fee=0.0, status='active')
        db.session.add(subscription)
        db.session.commit()

    community_customers = []  # Disabled for privacy reasons - no customer data should be displayed to others
    community_count = 0  # Placeholder
    community_total_kwh = 0  # Placeholder
    community_avg_kwh = 0  # Placeholder
    user_total_kwh = analytics['total_kwh'] if analytics else 0
    community_comparison = None  # Disabled for privacy - community data aggregation removed

    forecast_days = []
    if readings:
        avg_daily = sum(r.kwh for r in readings) / len(readings)
        for day in range(1, 8):
            modifier = 1.05 if day in (6, 7) else 1.0
            forecast_days.append({
                'day': f'Day {day}',
                'predicted_usage': round(avg_daily * modifier, 2)
            })
    forecast_summary = {
        'next_week_total': round(sum(d['predicted_usage'] for d in forecast_days), 2) if forecast_days else 0,
        'peak_risk': 'High' if (analytics and analytics['total_kwh'] > current_user.threshold * 0.9) else 'Normal',
        'trend': 'Rising' if (analytics and analytics['avg_kwh'] > 0 and analytics['avg_kwh'] > (current_user.threshold / 30)) else 'Stable',
        'forecast_days': forecast_days
    }

    energy_tips = [
        {'title': 'Run laundry after 9 PM', 'content': 'Off-peak time uses 15% less grid power and lowers your bill.', 'potential_savings': 15},
        {'title': 'Use solar-friendly loads midday', 'content': 'Shift dishwasher and dryer to 10 AM - 2 PM to use more solar power.', 'potential_savings': 20},
        {'title': 'Unplug unused chargers and appliances', 'content': 'Phantom loads can add up. Unplug devices when not in use.', 'potential_savings': 8},
        {'title': 'Optimize AC temperature', 'content': 'Set AC to 24°C instead of 22°C to save up to 10% on cooling costs.', 'potential_savings': 10},
        {'title': 'Use LED bulbs everywhere', 'content': 'Replace all incandescent bulbs with LEDs to reduce lighting costs by 75%.', 'potential_savings': 75},
        {'title': 'Install smart plugs', 'content': 'Use smart plugs to automatically turn off devices when not in use.', 'potential_savings': 12},
        {'title': 'Schedule heavy appliances', 'content': 'Run washing machine and dryer during off-peak hours to save on electricity.', 'potential_savings': 18},
        {'title': 'Maintain appliances regularly', 'content': 'Clean filters and maintain appliances to ensure they run efficiently.', 'potential_savings': 5},
    ]
    
    if current_user.energy_source == 'SOLAR':
        energy_tips.insert(0, {'title': 'Maximize solar energy', 'content': 'Run high-power appliances during peak sunlight hours for best savings.', 'potential_savings': 18})
    
    if current_user.user_type == 'business':
        energy_tips.extend([
            {'title': 'Implement energy management system', 'content': 'Install EMS to monitor and control energy usage across the business.', 'potential_savings': 25},
            {'title': 'Optimize lighting schedules', 'content': 'Use occupancy sensors and timers for office lighting.', 'potential_savings': 30},
            {'title': 'Upgrade to energy-efficient equipment', 'content': 'Replace old equipment with energy star rated appliances.', 'potential_savings': 20},
        ])
    else:  # smart_home
        energy_tips.extend([
            {'title': 'Install smart thermostat', 'content': 'Use programmable thermostat to optimize heating and cooling.', 'potential_savings': 15},
            {'title': 'Use energy monitoring apps', 'content': 'Track your usage with mobile apps for better awareness.', 'potential_savings': 10},
            {'title': 'Implement home automation', 'content': 'Automate lights and appliances for optimal energy use.', 'potential_savings': 22},
        ])

    # Get chore schedules
    chore_schedules = ChoreSchedule.query.filter_by(user_id=current_user.id, is_active=True).all()
    
    # Get success stories
    success_stories = SuccessStory.query.filter_by(is_approved=True).order_by(SuccessStory.created_at.desc()).limit(5).all()

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
                                  energy_source_label=get_energy_source_label(current_user.energy_source),
                                  selected_energy_source=normalize_energy_source(current_user.energy_source),
                                  customer_devices=customer_devices,
                                  device_prediction=device_prediction,
                                  eco_points=eco_points,
                                  earned_badges=earned_badges,
                                  subscription=subscription,
                                  community_comparison=community_comparison,
                                  forecast_summary=forecast_summary,
                                  energy_tips=energy_tips,
                                  chore_schedules=chore_schedules,
                                  success_stories=success_stories,
                                  user_type=current_user.user_type,
                                  selected_view=graph_view,
                                  reading_timestamps=reading_timestamps,
                                  trees_to_plant=trees_to_plant,
                                  tree_absorption_rate=21.0,
                                  now=local_now(),
                                  footer_links=PUBLIC_FOOTER_LINKS)


# ---------- Simple UI routes for admin pages (render templates) ----------
@app.route('/admin/users/ui')
@admin_secure
def admin_users_ui():
    """Render user management UI for admins."""
    return render_template('admin_users.html')


# Admin dashboard routes will be defined after templates are loaded

@app.route('/hr/payroll/ui')
@hr_required
def hr_payroll_ui():
    """Render payroll admin UI for HR managers."""
    return render_template('payroll_admin.html')


@app.route('/examiner/payroll/ui')
@examiner_required
def examiner_payroll_ui():
    """Render payroll approval UI for examiners."""
    return render_template('examiner_payroll.html')


# ===================== NEW FEATURE ROUTES =====================

@app.route('/goals')
@login_required
def goals():
    """Energy Goal Tracker - Customer Feature"""
    if current_user.user_type != 'customer':
        flash('Access denied. This feature is for customers only.', 'danger')
        return redirect(url_for('dashboard'))

    goals = EnergyGoal.query.filter_by(user_id=current_user.id).order_by(EnergyGoal.created_at.desc()).all()
    return render_template_string(goals_template, goals=goals)


@app.route('/goals/create', methods=['GET', 'POST'])
@login_required
def create_goal():
    """Create a new energy goal"""
    if current_user.user_type != 'customer':
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        goal_type = request.form.get('goal_type')
        target_value = float(request.form.get('target_value'))
        end_date = datetime.strptime(request.form.get('end_date'), '%Y-%m-%d')

        goal = EnergyGoal(
            user_id=current_user.id,
            goal_type=goal_type,
            target_value=target_value,
            end_date=end_date
        )
        db.session.add(goal)
        db.session.commit()

        flash('Energy goal created successfully!', 'success')
        return redirect(url_for('goals'))

    return render_template_string(create_goal_template)


@app.route('/goals/<int:goal_id>/update', methods=['POST'])
@login_required
def update_goal_progress(goal_id):
    """Update goal progress"""
    goal = EnergyGoal.query.get_or_404(goal_id)
    if goal.user_id != current_user.id:
        return jsonify({'error': 'Unauthorized'}), 403

    current_value = float(request.form.get('current_value', 0))
    goal.current_value = current_value

    if current_value >= goal.target_value:
        goal.status = 'completed'
    elif datetime.utcnow() > goal.end_date:
        goal.status = 'failed'

    db.session.commit()
    return jsonify({'success': True, 'status': goal.status})


@app.route('/forum')
@login_required
def forum():
    """Community Forum - Customer Feature"""
    if current_user.user_type != 'customer':
        flash('Access denied. This feature is for customers only.', 'danger')
        return redirect(url_for('dashboard'))

    page = request.args.get('page', 1, type=int)
    category = request.args.get('category', 'all')

    query = ForumPost.query
    if category != 'all':
        query = query.filter_by(category=category)

    posts = query.order_by(ForumPost.is_pinned.desc(), ForumPost.created_at.desc()).paginate(page=page, per_page=10)
    return render_template_string(forum_template, posts=posts, category=category)


@app.route('/forum/post', methods=['GET', 'POST'])
@login_required
def create_post():
    """Create a new forum post"""
    if current_user.user_type != 'customer':
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        title = request.form.get('title')
        content = request.form.get('content')
        category = request.form.get('category', 'general')

        post = ForumPost(
            user_id=current_user.id,
            title=title,
            content=content,
            category=category
        )
        db.session.add(post)
        db.session.commit()

        flash('Post created successfully!', 'success')
        return redirect(url_for('forum'))

    return render_template_string(create_post_template)


@app.route('/forum/post/<int:post_id>')
@login_required
def view_post(post_id):
    """View a forum post and its replies"""
    post = ForumPost.query.get_or_404(post_id)
    replies = ForumReply.query.filter_by(post_id=post_id).order_by(ForumReply.created_at.asc()).all()
    return render_template_string(view_post_template, post=post, replies=replies)


@app.route('/forum/post/<int:post_id>/reply', methods=['POST'])
@login_required
def reply_to_post(post_id):
    """Reply to a forum post"""
    if current_user.user_type != 'customer':
        return jsonify({'error': 'Unauthorized'}), 403

    content = request.form.get('content')
    reply = ForumReply(
        post_id=post_id,
        user_id=current_user.id,
        content=content
    )
    db.session.add(reply)

    # Update reply count
    post = ForumPost.query.get(post_id)
    post.replies_count += 1
    db.session.commit()

    flash('Reply posted successfully!', 'success')
    return redirect(url_for('view_post', post_id=post_id))


@app.route('/chat')
@login_required
def chat():
    """AI Chat Assistant - Customer Feature"""
    if current_user.user_type != 'customer':
        flash('Access denied. This feature is for customers only.', 'danger')
        return redirect(url_for('dashboard'))

    return render_template_string(chat_template)


@app.route('/api/chat/message', methods=['POST'])
@login_required
def chat_message():
    """Handle AI chat messages"""
    if current_user.user_type != 'customer':
        return jsonify({'error': 'Unauthorized'}), 403

    message = request.json.get('message', '')
    # Simple AI response - in production, integrate with actual AI service
    responses = [
        "That's a great question about energy conservation!",
        "I recommend checking your appliance usage patterns.",
        "Consider switching to LED bulbs for better efficiency.",
        "Have you tried using a programmable thermostat?",
        "Regular maintenance can significantly reduce energy waste."
    ]
    response = random.choice(responses)

    return jsonify({'response': response})


@app.route('/toggle_theme', methods=['POST'])
@login_required
def toggle_theme():
    """Toggle between dark and light mode"""
    current_theme = session.get('theme', 'light')
    new_theme = 'dark' if current_theme == 'light' else 'light'
    session['theme'] = new_theme
    return jsonify({'theme': new_theme})


# ===================== EXAMINER ROUTES =====================

@app.route('/rubrics')
@login_required
def rubrics():
    """Rubrics Management - Examiner Feature"""
    if current_user.user_type != 'examiner':
        flash('Access denied. This feature is for examiners only.', 'danger')
        return redirect(url_for('dashboard'))

    rubrics_list = Rubric.query.filter_by(created_by=current_user.id).order_by(Rubric.created_at.desc()).all()
    return render_template_string(rubrics_template, rubrics=rubrics_list)


@app.route('/rubrics/create', methods=['GET', 'POST'])
@login_required
def create_rubric():
    """Create a new rubric"""
    if current_user.user_type != 'examiner':
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        name = request.form.get('name')
        description = request.form.get('description')
        criteria = request.form.get('criteria')

        rubric = Rubric(
            name=name,
            description=description,
            criteria=criteria,
            created_by=current_user.id
        )
        db.session.add(rubric)
        db.session.commit()

        flash('Rubric created successfully!', 'success')
        return redirect(url_for('rubrics'))

    return render_template_string(create_rubric_template)


@app.route('/templates')
@login_required
def comment_templates():
    """Comment Templates - Examiner Feature"""
    if current_user.user_type != 'examiner':
        flash('Access denied. This feature is for examiners only.', 'danger')
        return redirect(url_for('dashboard'))

    templates = CommentTemplate.query.filter_by(created_by=current_user.id).order_by(CommentTemplate.created_at.desc()).all()
    return render_template_string(templates_template, templates=templates)


@app.route('/templates/create', methods=['GET', 'POST'])
@login_required
def create_template():
    """Create a new comment template"""
    if current_user.user_type != 'examiner':
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        name = request.form.get('name')
        content = request.form.get('content')
        category = request.form.get('category', 'general')

        template = CommentTemplate(
            name=name,
            content=content,
            category=category,
            created_by=current_user.id
        )
        db.session.add(template)
        db.session.commit()

        flash('Template created successfully!', 'success')
        return redirect(url_for('comment_templates'))

    return render_template_string(create_template_template)


@app.route('/analytics')
@login_required
def performance_analytics():
    """Performance Analytics - Examiner Feature"""
    if current_user.user_type != 'examiner':
        flash('Access denied. This feature is for examiners only.', 'danger')
        return redirect(url_for('dashboard'))

    # Get analytics data for customers
    analytics_data = PerformanceAnalytics.query.order_by(PerformanceAnalytics.created_at.desc()).limit(100).all()
    return render_template_string(analytics_template, analytics=analytics_data)


# ===================== ADMIN ROUTES =====================

@app.route('/sub-admins')
@login_required
def sub_admins():
    """Sub-Admin Roles Management - Admin Feature"""
    if current_user.role != 'admin':
        flash('Access denied. This feature is for admins only.', 'danger')
        return redirect(url_for('dashboard'))

    sub_admin_roles = SubAdminRole.query.order_by(SubAdminRole.created_at.desc()).all()
    return render_template_string(sub_admins_template, sub_admin_roles=sub_admin_roles)


@app.route('/sub-admins/create', methods=['GET', 'POST'])
@login_required
def create_sub_admin():
    """Create a new sub-admin role"""
    if current_user.role != 'admin':
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        user_id = int(request.form.get('user_id'))
        role_name = request.form.get('role_name')
        permissions = request.form.get('permissions')

        sub_admin = SubAdminRole(
            user_id=user_id,
            role_name=role_name,
            permissions=permissions,
            assigned_by=current_user.id
        )
        db.session.add(sub_admin)
        db.session.commit()

        flash('Sub-admin role created successfully!', 'success')
        return redirect(url_for('sub_admins'))

    users = User.query.filter(User.role.in_(['customer', 'examiner'])).all()
    return render_template_string(create_sub_admin_template, users=users)


@app.route('/health')
@login_required
def system_health():
    """System Health Monitoring - Admin Feature"""
    if current_user.role != 'admin':
        flash('Access denied. This feature is for admins only.', 'danger')
        return redirect(url_for('dashboard'))

    health_checks = SystemHealth.query.order_by(SystemHealth.last_checked.desc()).all()
    return render_template_string(health_template, health_checks=health_checks)


@app.route('/backups')
@login_required
def backup_schedules():
    """Backup Scheduler - Admin Feature"""
    if current_user.role != 'admin':
        flash('Access denied. This feature is for admins only.', 'danger')
        return redirect(url_for('dashboard'))

    schedules = BackupSchedule.query.order_by(BackupSchedule.created_at.desc()).all()
    return render_template_string(backups_template, schedules=schedules)


@app.route('/backups/create', methods=['GET', 'POST'])
@login_required
def create_backup_schedule():
    """Create a new backup schedule"""
    if current_user.role != 'admin':
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        name = request.form.get('name')
        frequency = request.form.get('frequency')
        backup_type = request.form.get('backup_type')
        retention_days = int(request.form.get('retention_days'))

        schedule = BackupSchedule(
            name=name,
            frequency=frequency,
            backup_type=backup_type,
            retention_days=retention_days
        )
        db.session.add(schedule)
        db.session.commit()

        flash('Backup schedule created successfully!', 'success')
        return redirect(url_for('backup_schedules'))

    return render_template_string(create_backup_template)


@app.route('/rollouts')
@login_required
def feature_rollouts():
    """Feature Rollout Management - Admin Feature"""
    if current_user.role != 'admin':
        flash('Access denied. This feature is for admins only.', 'danger')
        return redirect(url_for('dashboard'))

    rollouts = FeatureRollout.query.order_by(FeatureRollout.created_at.desc()).all()
    return render_template_string(rollouts_template, rollouts=rollouts)


@app.route('/rollouts/create', methods=['GET', 'POST'])
@login_required
def create_rollout():
    """Create a new feature rollout"""
    if current_user.role != 'admin':
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        feature_name = request.form.get('feature_name')
        description = request.form.get('description')
        rollout_percentage = float(request.form.get('rollout_percentage'))
        target_users = request.form.get('target_users')

        rollout = FeatureRollout(
            feature_name=feature_name,
            description=description,
            rollout_percentage=rollout_percentage,
            target_users=target_users,
            created_by=current_user.id
        )
        db.session.add(rollout)
        db.session.commit()

        flash('Feature rollout created successfully!', 'success')
        return redirect(url_for('feature_rollouts'))

    return render_template_string(create_rollout_template)


@app.route('/partners')
@login_required
def partners():
    """Partner management page for admins."""
    if current_user.role != 'admin':
        flash('Access denied. This feature is for admins only.', 'danger')
        return redirect(url_for('dashboard'))

    partners_list = Partner.query.order_by(Partner.created_at.desc()).all()
    return render_template_string(partners_template, partners=partners_list)


@app.route('/partners/create', methods=['GET', 'POST'])
@login_required
def create_partner_page():
    """Create a new partner record."""
    if current_user.role != 'admin':
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        name = request.form.get('name')
        contact_email = request.form.get('contact_email')
        sandbox = request.form.get('sandbox') == 'on'
        if not name:
            flash('Partner name is required.', 'danger')
            return render_template_string(create_partner_template)

        partner = create_partner(name, contact_email, sandbox)
        flash(f'Partner "{partner.name}" created successfully.', 'success')
        return redirect(url_for('partners'))

    return render_template_string(create_partner_template)


@app.route('/support/tickets', methods=['GET', 'POST'])
@login_required
def support_tickets():
    """Support ticket dashboard for customers and admins."""
    if not is_ticketing_enabled() and current_user.role == 'customer':
        flash('Support ticketing is currently closed. Please contact the support desk directly.', 'warning')
        return redirect(url_for('support_center'))

    if request.method == 'POST':
        subject = request.form.get('subject')
        description = request.form.get('description')
        priority = request.form.get('priority', 'medium')
        if not subject or not description:
            flash('Subject and description are required.', 'danger')
        else:
            ticket = SupportTicket(
                user_id=current_user.id,
                subject=subject,
                description=description,
                priority=priority
            )
            db.session.add(ticket)
            db.session.commit()
            record_audit(current_user.id, 'support.ticket_created', 'support_ticket', ticket.id,
                         {'subject': subject, 'priority': priority})
            flash('Support ticket submitted successfully.', 'success')
            return redirect(url_for('support_tickets'))

    if current_user.role == 'customer':
        tickets = SupportTicket.query.filter_by(user_id=current_user.id).order_by(SupportTicket.created_at.desc()).all()
    else:
        tickets = SupportTicket.query.order_by(SupportTicket.created_at.desc()).all()
    return render_template_string(support_tickets_template, tickets=tickets)


@app.route('/support/tickets/<int:ticket_id>', methods=['GET', 'POST'])
@login_required
def support_ticket_detail(ticket_id):
    ticket = SupportTicket.query.get_or_404(ticket_id)
    if current_user.role == 'customer' and ticket.user_id != current_user.id:
        flash('Access denied. You may only view your own tickets.', 'danger')
        return redirect(url_for('support_tickets'))

    if request.method == 'POST' and current_user.role in ['admin', 'examiner']:
        status = request.form.get('status')
        assignee_id = request.form.get('assignee_id')
        if status:
            ticket.status = status
        if assignee_id:
            try:
                ticket.assignee_id = int(assignee_id)
            except ValueError:
                ticket.assignee_id = None
        ticket.updated_at = datetime.utcnow()
        db.session.commit()
        record_audit(current_user.id, 'support.ticket_updated', 'support_ticket', ticket.id,
                     {'status': ticket.status, 'assignee_id': ticket.assignee_id})
        flash('Ticket updated successfully.', 'success')
        return redirect(url_for('support_ticket_detail', ticket_id=ticket.id))

    assignees = User.query.filter(User.role.in_(['admin', 'examiner'])).all()
    return render_template_string(ticket_detail_template, ticket=ticket, assignees=assignees)


@app.route('/tariffs/reviews')
@login_required
def tariff_reviews():
    """List tariff review submissions for examiners and admins."""
    if current_user.role not in ['admin', 'examiner']:
        flash('Access denied. This feature is for examiners and admins only.', 'danger')
        return redirect(url_for('dashboard'))

    reviews = TariffReview.query.order_by(TariffReview.submitted_at.desc()).all()
    return render_template_string(tariff_reviews_template, reviews=reviews)


@app.route('/tariffs/reviews/<int:review_id>', methods=['GET', 'POST'])
@login_required
def tariff_review_detail(review_id):
    if current_user.role not in ['admin', 'examiner']:
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard'))

    review = TariffReview.query.get_or_404(review_id)
    if request.method == 'POST' and current_user.role == 'examiner':
        review.status = 'approved'
        review.examiner_id = current_user.id
        review.reviewed_at = datetime.utcnow()
        db.session.commit()
        record_audit(current_user.id, 'tariff.review_approved', 'tariff_review', review.id)
        flash('Tariff review approved.', 'success')
        return redirect(url_for('tariff_review_detail', review_id=review.id))

    return render_template_string(tariff_review_detail_template, review=review)


# ===================== HERO SECTION UPDATES =====================

@app.route('/api/impact_counters')
def get_impact_counters():
    """Get impact counter data for hero section"""
    counters = ImpactCounter.query.all()
    data = {counter.metric_name: counter.value for counter in counters}

    if 'revenue_generated' not in data:
        total_revenue = 0
        customers = User.query.filter_by(role='customer').all()
        for user in customers:
            for reading in user.readings:
                total_revenue += float(reading.kwh or 0) * float(user.unit_cost or 0)
        data['revenue_generated'] = round(total_revenue, 2)

    if 'total_energy_saved' not in data:
        data['total_energy_saved'] = sum(float(counter.value or 0) for counter in counters if counter.metric_name == 'total_energy_saved')
    if 'carbon_reduced' not in data:
        data['carbon_reduced'] = sum(float(counter.value or 0) for counter in counters if counter.metric_name == 'carbon_reduced')
    if 'users_onboarded' not in data:
        data['users_onboarded'] = User.query.filter_by(role='customer').count()

    return jsonify(data)


@app.route('/api/update_impact_counter/<metric_name>', methods=['POST'])
@login_required
def update_impact_counter(metric_name):
    """Update impact counter (admin only)"""
    if current_user.role != 'admin':
        return jsonify({'error': 'Unauthorized'}), 403

    value = request.json.get('value', 0)
    counter = ImpactCounter.query.filter_by(metric_name=metric_name).first()
    if counter:
        counter.value = value
        counter.last_updated = datetime.utcnow()
        db.session.commit()

    return jsonify({'success': True})


# ===================== FEATURE API ROUTES =====================

@app.route('/api/tips/personalized', methods=['GET'])
@login_required
def get_personalized_tips():
    """Get AI-driven personalized energy tips"""
    from modules.tip_engine import TipEngine
    
    readings = Reading.query.filter_by(user_id=current_user.id).order_by(Reading.created_at.desc()).limit(30).all()
    readings_data = [
        {
            'date': r.timestamp or r.created_at,
            'usage': r.kwh,
            'timestamp': r.timestamp or r.created_at,
            'hour': (r.timestamp or r.created_at).hour
        }
        for r in readings
    ]
    
    tips = TipEngine.analyze_usage_patterns(readings_data, {'has_solar': current_user.energy_source == 'SOLAR'})
    
    return jsonify({
        'success': True,
        'tips': tips,
        'count': len(tips),
        'threshold': current_user.threshold,
        'unit_cost': current_user.unit_cost
    })


@app.route('/api/forecast/weekly', methods=['GET'])
@login_required
def get_weekly_forecast():
    """Get 7-day energy forecast"""
    from modules.forecasting import ForecastingEngine
    
    readings = Reading.query.filter_by(user_id=current_user.id).order_by(Reading.created_at.desc()).limit(30).all()
    readings_values = [r.kwh for r in readings]
    
    if not readings_values:
        return jsonify({'error': 'Insufficient data for forecast'}), 400
    
    forecast = ForecastingEngine.predict_daily_usage(readings_values, days_ahead=7, user_threshold=current_user.threshold)
    
    return jsonify({
        'success': True,
        'forecast': forecast,
        'user_threshold': current_user.threshold,
        'recent_avg': sum(readings_values[-7:]) / len(readings_values[-7:]) if readings_values else 0
    })


@app.route('/api/gamification/badges', methods=['GET'])
@login_required
def get_user_badges_api():
    """Get user's earned badges"""
    badges = UserBadgeEarned.query.filter_by(user_id=current_user.id).all()
    eco_points = EcoPoints.query.filter_by(user_id=current_user.id).first()
    
    if not eco_points:
        eco_points = EcoPoints(user_id=current_user.id)
        db.session.add(eco_points)
        db.session.commit()
    
    badge_list = [
        {
            'id': b.badge.id,
            'name': b.badge.name,
            'description': b.badge.description,
            'icon': b.badge.icon,
            'earned_at': b.earned_at.isoformat() if b.earned_at else None
        }
        for b in badges
    ]
    
    return jsonify({
        'total_badges': len(badges),
        'total_points': eco_points.points,
        'level': eco_points.level,
        'streak_days': eco_points.streak_days,
        'badges': badge_list
    })


@app.route('/api/gamification/leaderboard', methods=['GET'])
@login_required
def get_leaderboard_api():
    """Get leaderboard"""
    period = request.args.get('period', 'monthly')
    limit = request.args.get('limit', 100, type=int)
    
    leaderboard = Leaderboard.query.filter_by(period=period).order_by(Leaderboard.points.desc()).limit(limit).all()
    
    user_rank = next((le.rank for le in leaderboard if le.user_id == current_user.id), None)
    user_points = next((le.points for le in leaderboard if le.user_id == current_user.id), 0)
    
    return jsonify({
        'period': period,
        'user_rank': user_rank,
        'user_points': user_points,
        'total_users': Leaderboard.query.filter_by(period=period).count(),
        'leaderboard': [
            {
                'rank': le.rank,
                'user': le.user.username,
                'points': le.points
            }
            for le in leaderboard[:10]
        ]
    })


@app.route('/api/export/csv', methods=['GET'])
@login_required
def export_csv_api():
    """Export energy data as CSV"""
    from modules.export_handler import DataExporter
    
    readings = Reading.query.filter_by(user_id=current_user.id).all()
    readings_data = [
        {
            'date': r.timestamp or r.created_at,
            'usage': r.kwh,
            'cost': r.cost or (r.kwh * current_user.unit_cost),
            'energy_source': current_user.energy_source,
            'temperature': 25.5,
            'device_name': 'Main Meter',
            'notes': ''
        }
        for r in readings
    ]
    
    csv_content, filename = DataExporter.export_to_csv(readings_data)
    
    return Response(
        csv_content,
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename={filename}'}
    )


@app.route('/api/billing/subscription', methods=['GET'])
@login_required
def get_subscription_api():
    """Get user's subscription info"""
    subscription = Subscription.query.filter_by(user_id=current_user.id).first()
    
    if not subscription:
        subscription = Subscription(user_id=current_user.id, tier='free', status='active')
        db.session.add(subscription)
        db.session.commit()
    
    tier_info = {
        'free': {'name': 'Free', 'price': 0, 'features': ['basic_dashboard', 'manual_readings']},
        'basic': {'name': 'Basic', 'price': 299, 'features': ['real_time_charts', 'daily_tips', 'csv_export']},
        'pro': {'name': 'Pro', 'price': 799, 'features': ['advanced_analytics', 'forecasting', 'api_access']},
        'enterprise': {'name': 'Enterprise', 'price': 2999, 'features': ['all_features', 'priority_support']}
    }
    
    return jsonify({
        'current_tier': subscription.tier,
        'tier_info': tier_info.get(subscription.tier),
        'status': subscription.status,
        'all_tiers': tier_info
    })


@app.route('/api/billing/upgrade', methods=['POST'])
@login_required
def upgrade_subscription():
    """Upgrade user's subscription tier"""
    data = request.get_json()
    new_tier = data.get('tier')
    
    if not new_tier:
        return jsonify({'success': False, 'error': 'Tier is required'}), 400
    
    # Import payment handler
    from modules.payment_handler import PaymentHandler
    
    # Process upgrade
    result = PaymentHandler.upgrade_subscription(current_user.id, new_tier)
    
    if result['success']:
        # Update database
        subscription = Subscription.query.filter_by(user_id=current_user.id).first()
        if not subscription:
            subscription = Subscription(user_id=current_user.id, tier=new_tier, status='active')
            db.session.add(subscription)
        else:
            subscription.tier = new_tier
            subscription.status = 'active'
        db.session.commit()
        
        # Send confirmation email
        try:
            send_subscription_email(current_user.email, 'upgrade', new_tier, result)
        except Exception as e:
            print(f"Email sending failed: {e}")
        
        return jsonify({
            'success': True,
            'message': f'Successfully upgraded to {result["tier_name"]}',
            'new_tier': new_tier,
            'features': result['features_activated']
        })
    else:
        return jsonify({'success': False, 'error': result['error']}), 400


@app.route('/api/iot/devices', methods=['GET'])
@login_required
def get_iot_devices():
    """Get user's IoT devices"""
    devices = CustomerDevice.query.filter_by(user_id=current_user.id).all()
    
    device_list = [
        {
            'id': d.id,
            'name': d.name,
            'category': d.category,
            'watts': d.watts,
            'hours_per_day': d.hours_per_day,
            'monthly_kwh': round(d.watts * d.hours_per_day * 30 / 1000, 2),
            'created_at': d.created_at.isoformat() if d.created_at else None,
            'status': d.current_status.status if d.current_status else 'idle',
            'is_online': d.current_status.is_online if d.current_status else False
        }
        for d in devices
    ]
    
    return jsonify({
        'devices': device_list,
        'total_devices': len(devices)
    })


# ===================== IOT DEVICE REGISTRATION API =====================

@app.route('/api/iot/register', methods=['POST'])
@login_required
def register_iot_device():
    """Register a new IoT device with MAC address, serial number, and device type"""
    data = request.get_json()
    
    required_fields = ['device_name', 'device_type']
    if not data or not all(k in data for k in required_fields):
        return jsonify({'error': 'Missing required fields: device_name, device_type'}), 400
    
    # Create customer device first
    try:
        device = CustomerDevice(
            user_id=current_user.id,
            name=data.get('device_name', ''),
            category=data.get('device_type', 'other'),
            watts=float(data.get('watts', 100)),
            hours_per_day=float(data.get('hours_per_day', 8)),
            quantity=int(data.get('quantity', 1)),
            notes=data.get('notes', '')
        )
        db.session.add(device)
        db.session.flush()
        
        # Create IoT device registration
        import secrets
        api_key = secrets.token_urlsafe(32)
        api_secret = secrets.token_urlsafe(32)
        
        iot_reg = IoTDeviceRegistration(
            device_id=device.id,
            user_id=current_user.id,
            mac_address=data.get('mac_address'),
            serial_number=data.get('serial_number'),
            device_type=data.get('device_type'),
            manufacturer=data.get('manufacturer'),
            model=data.get('model'),
            api_key=api_key,
            api_secret=api_secret,
            status='pending',
            created_by=current_user.id
        )
        
        db.session.add(iot_reg)
        
        # Create device status entry
        device_status = DeviceStatus(device_id=device.id, is_online=False, status='pending')
        db.session.add(device_status)
        
        db.session.commit()
        
        log_system_action(current_user.id, f'Registered IoT device: {device.name}')
        
        return jsonify({
            'success': True,
            'device_id': device.id,
            'api_key': api_key,
            'api_secret': api_secret,
            'message': 'IoT device registered. Awaiting admin approval.',
            'status': 'pending'
        }), 201
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Device registration failed: {str(e)}'}), 400


@app.route('/api/iot/devices/<int:device_id>/data', methods=['POST'])
def receive_iot_data(device_id):
    """Receive real-time data from IoT device (requires API key authentication)"""
    api_key = request.headers.get('X-API-Key')
    
    if not api_key:
        return jsonify({'error': 'API key required'}), 401
    
    # Verify API key
    iot_reg = IoTDeviceRegistration.query.filter_by(
        device_id=device_id,
        api_key=api_key,
        status='active'
    ).first()
    
    if not iot_reg:
        return jsonify({'error': 'Invalid or inactive device'}), 403
    
    data = request.get_json()
    if not data or 'value' not in data:
        return jsonify({'error': 'Missing energy consumption value'}), 400
    
    try:
        # Record IoT data
        iot_data = IoTData(
            device_id=device_id,
            value=float(data.get('value', 0)),
            unit=data.get('unit', 'kWh'),
            timestamp=datetime.utcnow()
        )
        db.session.add(iot_data)
        
        # Update device status
        device_status = DeviceStatus.query.filter_by(device_id=device_id).first()
        if device_status:
            device_status.is_online = True
            device_status.current_power = float(data.get('power', 0))
            device_status.last_reading = datetime.utcnow()
            device_status.status = data.get('status', 'running')
        
        # Update IoT registration last_data_received
        iot_reg.last_data_received = datetime.utcnow()
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Data received successfully',
            'timestamp': datetime.utcnow().isoformat()
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Data collection failed: {str(e)}'}), 400


@app.route('/api/iot/devices/<int:device_id>/status', methods=['GET'])
@login_required
def get_device_status(device_id):
    """Get real-time status of IoT device"""
    device = CustomerDevice.query.get(device_id)
    
    if not device or device.user_id != current_user.id:
        return jsonify({'error': 'Device not found'}), 404
    
    status = device.current_status
    iot_reg = device.iot_registration
    
    return jsonify({
        'device_id': device_id,
        'device_name': device.name,
        'is_online': status.is_online if status else False,
        'current_power': status.current_power if status else 0,
        'device_status': status.status if status else 'unknown',
        'last_reading': status.last_reading.isoformat() if status and status.last_reading else None,
        'is_approved': iot_reg.is_approved_by_admin if iot_reg else False,
        'registration_status': iot_reg.status if iot_reg else 'not_registered'
    })


@app.route('/api/iot/devices/<int:device_id>/history', methods=['GET'])
@login_required
def get_device_data_history(device_id):
    """Get historical energy consumption data from IoT device"""
    device = CustomerDevice.query.get(device_id)
    
    if not device or device.user_id != current_user.id:
        return jsonify({'error': 'Device not found'}), 404
    
    # Get time range from query params
    days = request.args.get('days', default=7, type=int)
    start_date = datetime.utcnow() - timedelta(days=days)
    
    data_records = IoTData.query.filter_by(device_id=device_id).filter(
        IoTData.timestamp >= start_date
    ).order_by(IoTData.timestamp.desc()).limit(1000).all()
    
    data_list = [
        {
            'timestamp': d.timestamp.isoformat(),
            'value': d.value,
            'unit': d.unit
        }
        for d in data_records
    ]
    
    return jsonify({
        'device_id': device_id,
        'device_name': device.name,
        'period_days': days,
        'records_count': len(data_list),
        'data': data_list
    })


# ===================== ADMIN USER REGISTRATION & APPROVAL =====================

@app.route('/api/admin/user-registrations', methods=['GET'])
@admin_required
def get_user_registration_requests():
    """Get all pending user registration requests (admin only)"""
    status_filter = request.args.get('status', 'pending')
    
    query = UserRegistrationRequest.query
    if status_filter:
        query = query.filter_by(status=status_filter)
    
    requests = query.order_by(UserRegistrationRequest.submission_date.desc()).all()
    
    result = [
        {
            'id': r.id,
            'username': r.username,
            'email': r.email,
            'user_type': r.user_type,
            'requested_role': r.requested_role,
            'business_name': r.business_name,
            'status': r.status,
            'submission_date': r.submission_date.isoformat(),
            'review_date': r.review_date.isoformat() if r.review_date else None
        }
        for r in requests
    ]
    
    return jsonify({'registrations': result, 'total': len(result)})


@app.route('/api/admin/user-registrations/<int:request_id>', methods=['GET'])
@admin_required
def get_user_registration_detail(request_id):
    """Get detailed information about a user registration request"""
    reg_request = UserRegistrationRequest.query.get(request_id)
    
    if not reg_request:
        return jsonify({'error': 'Registration request not found'}), 404
    
    return jsonify({
        'id': reg_request.id,
        'username': reg_request.username,
        'email': reg_request.email,
        'phone': reg_request.phone,
        'first_name': reg_request.first_name,
        'last_name': reg_request.last_name,
        'user_type': reg_request.user_type,
        'requested_role': reg_request.requested_role,
        'business_name': reg_request.business_name,
        'business_registration_number': reg_request.business_registration_number,
        'business_type': reg_request.business_type,
        'number_of_locations': reg_request.number_of_locations,
        'residential_address': reg_request.residential_address,
        'meter_number': reg_request.meter_number,
        'status': reg_request.status,
        'submission_date': reg_request.submission_date.isoformat(),
        'email_verified': reg_request.email_verified,
        'phone_verified': reg_request.phone_verified,
        'review_notes': reg_request.review_notes
    })


@app.route('/api/admin/user-registrations/<int:request_id>/approve', methods=['POST'])
@admin_required
def approve_user_registration(request_id):
    """Approve a user registration request and create the user account"""
    reg_request = UserRegistrationRequest.query.get(request_id)
    
    if not reg_request:
        return jsonify({'error': 'Registration request not found'}), 404
    
    if reg_request.status != 'pending':
        return jsonify({'error': f'Cannot approve: request status is {reg_request.status}'}), 400
    if reg_request.requested_role != 'customer':
        return jsonify({'error': 'Staff accounts must be created through an administrator invitation'}), 400
    
    try:
        # Create user account
        user = User(
            username=reg_request.username,
            email=reg_request.email,
            role=reg_request.requested_role,
            user_type=reg_request.user_type,
            phone_number=reg_request.phone
        )
        
        # Set password (generate temporary password or use provided one)
        import secrets
        temp_password = secrets.token_urlsafe(12)
        user.set_password(temp_password)
        
        # Role-specific setup
        if reg_request.requested_role == 'customer':
            user.meter_number = reg_request.meter_number or generate_valid_meter_number()
            user.phone_number = reg_request.phone or '+2547000000000'
        elif reg_request.requested_role in ['admin', 'examiner']:
            user.employee_id = user.generate_employee_id()
        
        db.session.add(user)
        db.session.flush()
        
        # Update registration request
        reg_request.status = 'approved'
        reg_request.reviewed_by = current_user.id
        reg_request.review_date = datetime.utcnow()
        reg_request.created_user_id = user.id
        reg_request.account_creation_date = datetime.utcnow()
        
        # Create user settings for customers
        if reg_request.requested_role == 'customer':
            user_settings = UserSettings(user_id=user.id, alert_threshold=user.threshold)
            db.session.add(user_settings)
        
        # For business owners, create default branch
        if reg_request.user_type == 'business_owner':
            branch = Branch(
                user_id=user.id,
                name=reg_request.business_name or 'Main Branch',
                location=reg_request.residential_address or 'Not Specified',
                address=reg_request.residential_address
            )
            db.session.add(branch)
        
        db.session.commit()
        
        log_system_action(current_user.id, f'Approved user registration: {reg_request.username}')
        
        return jsonify({
            'success': True,
            'user_id': user.id,
            'username': user.username,
            'temporary_password': temp_password,
            'message': 'User account created successfully. Share temporary password with the user.'
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Approval failed: {str(e)}'}), 400


@app.route('/api/admin/user-registrations/<int:request_id>/reject', methods=['POST'])
@admin_required
def reject_user_registration(request_id):
    """Reject a user registration request"""
    data = request.get_json() or {}
    reg_request = UserRegistrationRequest.query.get(request_id)
    
    if not reg_request:
        return jsonify({'error': 'Registration request not found'}), 404
    
    if reg_request.status != 'pending':
        return jsonify({'error': f'Cannot reject: request status is {reg_request.status}'}), 400
    
    try:
        reg_request.status = 'rejected'
        reg_request.reviewed_by = current_user.id
        reg_request.review_date = datetime.utcnow()
        reg_request.rejection_reason = data.get('reason', 'Not specified')
        
        db.session.commit()
        
        log_system_action(current_user.id, f'Rejected user registration: {reg_request.username}')
        
        return jsonify({
            'success': True,
            'message': 'Registration request rejected'
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Rejection failed: {str(e)}'}), 400


@app.route('/api/admin/users/invite', methods=['POST'])
@admin_secure
def admin_invite_user():
    data = request.get_json(silent=True) or request.form.to_dict()
    username = (data.get('username') or '').strip()
    email = (data.get('email') or '').strip().lower()
    role = (data.get('role') or '').strip()
    phone = (data.get('phone_number') or '').strip() or None
    id_number = (data.get('id_number') or '').strip() or None
    full_name = (data.get('full_name') or '').strip() or None

    if not username or not email or role not in ASSIGNABLE_ROLES:
        return jsonify({'error': 'Username, email, and a valid role are required'}), 400
    if role in STAFF_ROLES and (not id_number or not full_name or not phone):
        return jsonify({'error': 'ID number, phone number, and full names are required for employees'}), 400
    if User.query.filter((User.username == username) | (User.email == email)).first():
        return jsonify({'error': 'Username or email already exists'}), 409

    pending_invite = UserRegistrationRequest.query.filter(
        (UserRegistrationRequest.username == username) | (UserRegistrationRequest.email == email)
    ).filter(UserRegistrationRequest.status == 'invited').first()
    if pending_invite:
        if pending_invite.verification_token_expires and pending_invite.verification_token_expires > datetime.utcnow():
            return jsonify({'error': 'An active invitation already exists for this username or email'}), 409
        pending_invite.status = 'expired'

    token = secrets.token_urlsafe(32)
    invite = UserRegistrationRequest(
        username=username,
        email=email,
        phone=phone,
        id_number=id_number,
        full_name=full_name,
        user_type='customer' if role == 'customer' else 'employee',
        requested_role=role,
        status='invited',
        reviewed_by=current_user.id,
        verification_token=hashlib.sha256(token.encode('utf-8')).hexdigest(),
        verification_token_expires=datetime.utcnow() + timedelta(hours=24)
    )
    db.session.add(invite)
    db.session.commit()
    log_system_action(current_user.id, f'Invited {username} as {role}')

    return jsonify({
        'success': True,
        'username': username,
        'role': role,
        'invite_url': url_for('complete_staff_invitation', token=token, _external=True),
        'expires_at': invite.verification_token_expires.isoformat(),
        'message': 'Share this one-time setup link with the invited user.'
    }), 201


@app.route('/staff/invite/<token>', methods=['GET', 'POST'])
def complete_staff_invitation(token):
    token_hash = hashlib.sha256(token.encode('utf-8')).hexdigest()
    invite = UserRegistrationRequest.query.filter_by(
        verification_token=token_hash,
        status='invited'
    ).first()
    if not invite or not invite.verification_token_expires or invite.verification_token_expires <= datetime.utcnow():
        return render_template_string(
            staff_invite_setup_page,
            error='This invitation is invalid or has expired.',
            invite=None
        ), 400

    if request.method == 'POST':
        password = request.form.get('password') or ''
        confirm_password = request.form.get('confirm_password') or ''
        if len(password) < 8:
            return render_template_string(staff_invite_setup_page, invite=invite, error='Password must be at least 8 characters.'), 400
        if password != confirm_password:
            return render_template_string(staff_invite_setup_page, invite=invite, error='Passwords do not match.'), 400
        if User.query.filter((User.username == invite.username) | (User.email == invite.email)).first():
            return render_template_string(staff_invite_setup_page, invite=invite, error='This account has already been created.'), 409

        user = User(
            username=invite.username,
            email=invite.email,
            role=invite.requested_role,
            user_type=invite.user_type,
            phone_number=invite.phone,
            id_number=invite.id_number,
            full_name=invite.full_name
        )
        user.set_password(password)
        if user.role in STAFF_ROLES:
            user.employee_id = user.generate_employee_id()
        elif user.role == 'customer':
            user.meter_number = generate_valid_meter_number()

        db.session.add(user)
        db.session.flush()
        if user.role == 'customer':
            db.session.add(UserSettings(user_id=user.id, alert_threshold=user.threshold))

        invite.status = 'approved'
        invite.created_user_id = user.id
        invite.account_creation_date = datetime.utcnow()
        invite.verification_token = None
        invite.verification_token_expires = None
        db.session.commit()
        log_system_action(user.id, f'Accepted admin invitation as {user.role}')
        flash('Account setup is complete. Please sign in.', 'success')
        return redirect(url_for('staff_login') if user.role in STAFF_ROLES else url_for('login'))

    return render_template_string(staff_invite_setup_page, invite=invite, error=None)


@app.route('/api/admin/users/register', methods=['POST'])
@admin_required
def admin_register_user():
    """Admin endpoint to directly register a new user"""
    data = request.get_json()
    
    required_fields = ['username', 'email', 'password', 'role', 'user_type']
    if not data or not all(k in data for k in required_fields):
        return jsonify({'error': 'Missing required fields'}), 400
    if data['role'] not in ASSIGNABLE_ROLES:
        return jsonify({'error': 'Invalid role'}), 400
    if data['role'] in STAFF_ROLES and not all(
        (data.get(field) or '').strip() for field in ('id_number', 'phone_number', 'email', 'full_name')
    ):
        return jsonify({'error': 'ID number, phone number, email, and full names are required for employees'}), 400
    
    # Check if user already exists
    if User.query.filter((User.username == data['username']) | (User.email == data['email'])).first():
        return jsonify({'error': 'Username or email already exists'}), 400
    
    try:
        user = User(
            username=data['username'],
            email=data['email'],
            role=data['role'],
            user_type=data['user_type'],
            phone_number=data.get('phone_number', '+2547000000000'),
            id_number=data.get('id_number'),
            full_name=data.get('full_name')
        )
        user.set_password(data['password'])
        
        # Role-specific setup
        if data['role'] == 'customer':
            user.meter_number = data.get('meter_number') or generate_valid_meter_number()
        elif data['role'] in STAFF_ROLES:
            user.employee_id = user.generate_employee_id()
        
        db.session.add(user)
        db.session.flush()
        
        # Create user settings for customers
        if data['role'] == 'customer':
            user_settings = UserSettings(user_id=user.id, alert_threshold=user.threshold)
            db.session.add(user_settings)
        
        db.session.commit()
        
        log_system_action(current_user.id, f'Created new user via admin: {data["username"]}')
        
        return jsonify({
            'success': True,
            'user_id': user.id,
            'username': user.username,
            'email': user.email,
            'message': 'User created successfully'
        }), 201
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'User creation failed: {str(e)}'}), 400


@app.route('/api/chores/schedule', methods=['GET'])
@login_required
def get_chore_schedules():
    """Get user's chore schedules"""
    schedules = ChoreSchedule.query.filter_by(user_id=current_user.id, is_active=True).all()
    
    schedule_list = [
        {
            'id': s.id,
            'chore_name': s.chore_name,
            'scheduled_time': s.scheduled_time.strftime('%H:%M'),
            'days_of_week': s.days_of_week,
            'is_active': s.is_active
        }
        for s in schedules
    ]
    
    return jsonify({
        'schedules': schedule_list,
        'total_schedules': len(schedules)
    })


@app.route('/api/chores/schedule', methods=['POST'])
@login_required
def add_chore_schedule():
    """Add a new chore schedule"""
    data = request.get_json()
    
    if not data or not all(k in data for k in ['chore_name', 'scheduled_time', 'days_of_week']):
        return jsonify({'error': 'Missing required fields'}), 400
    
    try:
        scheduled_time = datetime.strptime(data['scheduled_time'], '%H:%M').time()
    except ValueError:
        return jsonify({'error': 'Invalid time format. Use HH:MM'}), 400
    
    schedule = ChoreSchedule(
        user_id=current_user.id,
        chore_name=data['chore_name'],
        scheduled_time=scheduled_time,
        days_of_week=data['days_of_week']
    )
    
    db.session.add(schedule)
    db.session.commit()
    
    return jsonify({
        'success': True,
        'schedule_id': schedule.id,
        'message': 'Chore schedule added successfully'
    })


@app.route('/api/user/type', methods=['POST'])
@login_required
def update_user_type():
    """Update user's type (smart_home or business)"""
    data = request.get_json()
    
    if not data or 'user_type' not in data:
        return jsonify({'error': 'user_type is required'}), 400
    
    if data['user_type'] not in ['smart_home', 'business']:
        return jsonify({'error': 'Invalid user_type. Must be smart_home or business'}), 400
    
    current_user.user_type = data['user_type']
    db.session.commit()
    
    return jsonify({
        'success': True,
        'user_type': current_user.user_type,
        'message': 'User type updated successfully'
    })


@app.route('/api/recommendations/more', methods=['GET'])
@login_required
def get_more_recommendations():
    """Get additional personalized recommendations"""
    try:
        from modules.tip_engine import TipEngine
        
        readings = Reading.query.filter_by(user_id=current_user.id).order_by(Reading.created_at.desc()).limit(50).all()
        readings_data = [
            {
                'date': r.timestamp or r.created_at,
                'usage': r.kwh,
                'timestamp': r.timestamp or r.created_at,
                'hour': (r.timestamp or r.created_at).hour
            }
            for r in readings
        ]
        
        tips = TipEngine.get_advanced_tips(readings_data, {
            'has_solar': current_user.energy_source == 'SOLAR',
            'user_type': current_user.user_type,
            'threshold': current_user.threshold
        })
        
        return jsonify({
            'success': True,
            'recommendations': tips,
            'count': len(tips)
        })
    except Exception as e:
        print(f"Error getting recommendations: {e}")
        return jsonify({
            'success': False,
            'error': 'Unable to generate recommendations at this time'
        }), 500


@app.route('/api/community/stories', methods=['GET'])
@login_required
def get_success_stories():
    """Get approved success stories"""
    stories = SuccessStory.query.filter_by(is_approved=True).order_by(SuccessStory.created_at.desc()).limit(10).all()
    
    story_list = [
        {
            'id': s.id,
            'title': s.title,
            'story': s.story[:200] + '...' if len(s.story) > 200 else s.story,
            'savings_amount': s.savings_amount,
            'carbon_reduction': s.carbon_reduction,
            'user': s.user.username
        }
        for s in stories
    ]
    
    return jsonify({
        'stories': story_list,
        'total_stories': len(stories)
    })


@app.route('/api/admin/login_logs', methods=['GET'])
@admin_required
def get_login_logs():
    """Get login logs for admin monitoring"""
    limit = request.args.get('limit', 100, type=int)
    user_id = request.args.get('user_id', type=int)
    
    query = LoginLog.query.order_by(LoginLog.login_time.desc())
    if user_id:
        query = query.filter_by(user_id=user_id)
    
    logs = query.limit(limit).all()
    
    log_list = [
        {
            'id': l.id,
            'user': l.user.username,
            'role': l.role,
            'login_time': l.login_time.isoformat(),
            'ip_address': l.ip_address,
            'success': l.success,
            'user_agent': l.user_agent[:100] if l.user_agent else None
        }
        for l in logs
    ]
    
    return jsonify({
        'logs': log_list,
        'total_logs': len(logs)
    })


# ===================== NOTIFICATION AND MESSAGE API ROUTES =====================

@app.route('/api/notifications', methods=['GET'])
@login_required
def get_notifications():
    """Get user's notifications"""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    unread_only = request.args.get('unread_only', 'false').lower() == 'true'

    query = Notification.query.filter_by(user_id=current_user.id)
    if unread_only:
        query = query.filter_by(is_read=False)

    notifications = query.order_by(Notification.created_at.desc()) \
                        .paginate(page=page, per_page=per_page, error_out=False)

    notification_list = []
    for n in notifications.items:
        notification_list.append({
            'id': n.id,
            'title': n.title,
            'message': n.message,
            'type': n.notification_type,
            'is_read': n.is_read,
            'created_at': n.created_at.isoformat(),
            'sent_via_sms': n.sent_via_sms,
            'sent_via_email': n.sent_via_email
        })

    return jsonify({
        'notifications': notification_list,
        'total': notifications.total,
        'pages': notifications.pages,
        'current_page': notifications.page,
        'has_next': notifications.has_next,
        'has_prev': notifications.has_prev
    })


@app.route('/api/notifications/<int:notification_id>/read', methods=['POST'])
@login_required
def mark_notification_read(notification_id):
    """Mark a notification as read"""
    notification = Notification.query.filter_by(
        id=notification_id,
        user_id=current_user.id
    ).first()

    if not notification:
        return jsonify({'success': False, 'message': 'Notification not found'}), 404

    notification.is_read = True
    db.session.commit()

    return jsonify({'success': True, 'message': 'Notification marked as read'})


@app.route('/api/notifications/mark_all_read', methods=['POST'])
@login_required
def mark_all_notifications_read():
    """Mark all user's notifications as read"""
    Notification.query.filter_by(user_id=current_user.id, is_read=False) \
                     .update({'is_read': True})
    db.session.commit()

    return jsonify({'success': True, 'message': 'All notifications marked as read'})


@app.route('/api/messages', methods=['GET'])
@login_required
def get_messages():
    """Get user's messages"""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    message_type = request.args.get('type')  # 'sent', 'received', or None for all

    if message_type == 'sent':
        query = Message.query.filter_by(sender_id=current_user.id)
    elif message_type == 'received':
        query = Message.query.filter_by(recipient_id=current_user.id)
    else:
        # All messages (sent and received)
        query = Message.query.filter(
            (Message.sender_id == current_user.id) | (Message.recipient_id == current_user.id)
        )

    messages = query.order_by(Message.created_at.desc()) \
                   .paginate(page=page, per_page=per_page, error_out=False)

    message_list = []
    for m in messages.items:
        # Mark as read if current user is recipient and not read yet
        if m.recipient_id == current_user.id and not m.is_read:
            m.is_read = True

        message_list.append({
            'id': m.id,
            'sender': m.sender.username if m.sender else 'System',
            'recipient': m.recipient.username if m.recipient else 'Unknown',
            'subject': m.subject,
            'content': m.content,
            'is_read': m.is_read,
            'message_type': m.message_type,
            'created_at': m.created_at.isoformat(),
            'is_sender': m.sender_id == current_user.id
        })

    db.session.commit()  # Save read status changes

    return jsonify({
        'messages': message_list,
        'total': messages.total,
        'pages': messages.pages,
        'current_page': messages.page,
        'has_next': messages.has_next,
        'has_prev': messages.has_prev
    })


@app.route('/api/messages', methods=['POST'])
@login_required
def send_message():
    """Send a message to another user"""
    data = request.get_json()

    if not data:
        return jsonify({'success': False, 'message': 'No data provided'}), 400

    recipient_id = data.get('recipient_id')
    subject = data.get('subject', '').strip()
    content = data.get('content', '').strip()

    if not recipient_id or not subject or not content:
        return jsonify({'success': False, 'message': 'Recipient, subject, and content are required'}), 400

    # Check if recipient exists
    recipient = User.query.get(recipient_id)
    if not recipient:
        return jsonify({'success': False, 'message': 'Recipient not found'}), 404

    # Send the message
    success, message = send_direct_message(
        sender_id=current_user.id,
        recipient_id=recipient_id,
        subject=subject,
        content=content
    )

    if success:
        return jsonify({'success': True, 'message': 'Message sent successfully'})
    else:
        return jsonify({'success': False, 'message': message}), 500


@app.route('/api/messages/broadcast', methods=['POST'])
@login_required
@admin_required
def broadcast_message_api():
    """Broadcast message to users with specific roles (admin only)"""
    data = request.get_json()

    if not data:
        return jsonify({'success': False, 'message': 'No data provided'}), 400

    recipient_roles = data.get('recipient_roles', [])
    subject = data.get('subject', '').strip()
    content = data.get('content', '').strip()

    if not recipient_roles or not subject or not content:
        return jsonify({'success': False, 'message': 'Recipient roles, subject, and content are required'}), 400

    # Validate roles
    valid_roles = ['customer', 'examiner', 'admin']
    if not all(role in valid_roles for role in recipient_roles):
        return jsonify({'success': False, 'message': 'Invalid recipient roles'}), 400

    # Send broadcast
    success, message = broadcast_message(
        sender_id=current_user.id,
        recipient_roles=recipient_roles,
        subject=subject,
        content=content
    )

    if success:
        return jsonify({'success': True, 'message': message})
    else:
        return jsonify({'success': False, 'message': message}), 500


@app.route('/api/notifications/send', methods=['POST'])
@login_required
def send_notification():
    """Send a notification (admin/examiner only)"""
    if current_user.role not in ['admin', 'examiner']:
        return jsonify({'success': False, 'message': 'Permission denied'}), 403

    data = request.get_json()

    if not data:
        return jsonify({'success': False, 'message': 'No data provided'}), 400

    user_id = data.get('user_id')
    title = data.get('title', '').strip()
    message = data.get('message', '').strip()
    notification_type = data.get('type', 'info')
    send_sms = data.get('send_sms', False)
    send_email = data.get('send_email', False)

    if not user_id or not title or not message:
        return jsonify({'success': False, 'message': 'User ID, title, and message are required'}), 400

    # Check if user exists
    user = User.query.get(user_id)
    if not user:
        return jsonify({'success': False, 'message': 'User not found'}), 404

    # Send notification
    success, result_message = create_notification(
        user_id=user_id,
        title=title,
        message=message,
        notification_type=notification_type,
        send_sms=send_sms,
        send_email=send_email
    )

    if success:
        return jsonify({'success': True, 'message': result_message})
    else:
        return jsonify({'success': False, 'message': result_message}), 500


@app.route('/api/users/search', methods=['GET'])
@login_required
@admin_required
def search_users():
    """Search users for messaging (returns basic user info)"""
    query = request.args.get('q', '').strip()
    role = request.args.get('role')
    limit = request.args.get('limit', 10, type=int)

    if not query and not role:
        return jsonify({'users': []})

    user_query = User.query

    if query:
        user_query = user_query.filter(
            (User.username.contains(query)) |
            (User.email.contains(query))
        )

    if role:
        user_query = user_query.filter_by(role=role)

    # Don't return current user
    user_query = user_query.filter(User.id != current_user.id)

    users = user_query.limit(limit).all()

    user_list = []
    for u in users:
        user_list.append({
            'id': u.id,
            'username': u.username,
            'email': u.email,
            'role': u.role
        })

    return jsonify({'users': user_list})


@app.route('/examiner_dashboard')
@login_required
@examiner_required
def examiner_dashboard():
    # Determine access level
    is_department_head = current_user.is_department_head
    department_id = current_user.department_id

    if is_department_head and department_id:
        # Department heads see only their department's customers
        customers = User.query.filter_by(role='customer', department_id=department_id).all()
        readings = Reading.query.filter(Reading.user_id.in_([c.id for c in customers])).all()
        financial_records = FinancialRecord.query.filter(FinancialRecord.user_id.in_([c.id for c in customers])).all()
    else:
        # Admins and non-department examiners see all
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
    current_tariff = get_latest_tariff_notice('KPLC')
    default_unit_cost = get_active_unit_cost(current_user)

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
    current_tariff = get_latest_tariff_notice('KPLC')

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
    selected_energy_source = normalize_energy_source(request.args.get('energy_source'), default='KPLC')
    tariff_notifications = Report.query.filter_by(report_type='tariff_notice').order_by(Report.created_at.desc()).limit(20).all()
    source_notifications = []
    for item in tariff_notifications:
        payload = {}
        if item.chart_data:
            try:
                payload = json.loads(item.chart_data)
            except json.JSONDecodeError:
                payload = {}
        payload_source = normalize_energy_source(payload.get('energy_source'), default='KPLC')
        if payload_source == selected_energy_source:
            source_notifications.append(item)
        if len(source_notifications) >= 5:
            break
    sensor_alerts = Report.query.filter_by(report_type='sensor_alert').order_by(Report.created_at.desc()).limit(10).all()
    current_tariff = get_latest_tariff_notice(selected_energy_source)

    users = User.query.order_by(User.role.desc(), User.username).all()
    system_logs = SystemLog.query.order_by(SystemLog.timestamp.desc()).limit(20).all()
    login_logs = LoginLog.query.order_by(LoginLog.login_time.desc()).limit(20).all()
    feature_toggles = FeatureToggle.query.order_by(FeatureToggle.name).all()
    departments = Department.query.order_by(Department.name).all()
    pending_device_approvals = CustomerDevice.query.filter_by(is_active=False).order_by(CustomerDevice.created_at.desc()).all()
    support_tickets_count = SupportTicket.query.count()
    partnership_requests_count = PartnershipRequest.query.count()
    system_reports = Report.query.filter_by(report_type='system_report').order_by(Report.created_at.desc()).limit(10).all()

    if not feature_toggles:
        defaults = [
            ('hr_module', True, 'Enable the HR management module'),
            ('finance_module', True, 'Enable the Finance dashboard and reporting module'),
            ('services_module', True, 'Enable the Services module for customer-facing workflows'),
            ('gamification', True, 'Enable the gamification module for customers'),
            ('alerts', True, 'Enable threshold and energy alerts'),
            ('community_sharing', True, 'Enable community sharing and stories'),
            ('audit_trails', True, 'Enable audit trail logging'),
            ('encryption_enabled', True, 'Enable encryption controls and secure transfers')
        ]
        for name, enabled, description in defaults:
            db.session.add(FeatureToggle(name=name, enabled=enabled, description=description))
        db.session.commit()
        feature_toggles = FeatureToggle.query.order_by(FeatureToggle.name).all()

    active_feature_toggles = sum(1 for toggle in feature_toggles if toggle.enabled)

    return render_template_string(admin_financial_template_v2,
                                  financial=financial,
                                  financial_records=financial_records,
                                  examiner_reports=examiner_reports,
                                  pending_reviews=pending_reviews,
                                  prediction_payload=prediction_payload,
                                  contact_messages=contact_messages,
                                  smart_meter=smart_meter,
                                  kplc_notifications=source_notifications,
                                  sensor_alerts=sensor_alerts,
                                  current_tariff=current_tariff,
                                  energy_sources=ENERGY_SOURCES,
                                  selected_energy_source=selected_energy_source,
                                  selected_energy_source_label=get_energy_source_label(selected_energy_source),
                                  users=users,
                                  system_logs=system_logs,
                                  login_logs=login_logs,
                                  feature_toggles=feature_toggles,
                                  departments=departments,
                                  pending_device_approvals=pending_device_approvals,
                                  system_reports=system_reports,
                                  support_tickets_count=support_tickets_count,
                                  partnership_requests_count=partnership_requests_count,
                                  active_feature_toggles=active_feature_toggles)


@app.route('/admin/manage_user', methods=['POST'])
@login_required
@admin_required
def admin_manage_user():
    action = request.form.get('action')
    target_user_id = request.form.get('target_user_id', type=int)
    username = (request.form.get('username') or '').strip()
    email = (request.form.get('email') or '').strip()
    id_number = (request.form.get('id_number') or '').strip()
    full_name = (request.form.get('full_name') or '').strip()
    role = request.form.get('role')
    password = request.form.get('password')
    salary = request.form.get('salary', type=float) or 0.0
    department_id = request.form.get('department_id', type=int)
    department_name = (request.form.get('department') or '').strip()
    meter_number = ''.join(ch for ch in (request.form.get('meter_number') or '') if ch.isdigit())
    phone_number = (request.form.get('phone_number') or '').strip()
    status = request.form.get('status') or 'active'

    department_obj = None
    if department_id:
        department_obj = Department.query.get(department_id)
    elif department_name:
        department_obj = Department.query.filter(Department.name.ilike(department_name)).first()

    if action == 'create':
        if not username or not email or not password or not role:
            flash('Provide username, email, password and role to create a user.', 'warning')
            return redirect(url_for('admin_financial'))
        if role in STAFF_ROLES and (not id_number or not phone_number or not full_name):
            flash('Provide ID number, phone number and full names to create an employee.', 'warning')
            return redirect(url_for('admin_financial'))

        if User.query.filter((User.username == username) | (User.email == email)).first():
            flash('Username or email already exists.', 'warning')
            return redirect(url_for('admin_financial'))

        if role == 'customer' and not meter_number:
            meter_number = generate_valid_meter_number()

        user = User(
            username=username,
            email=email,
            role=role,
            id_number=id_number or None,
            full_name=full_name or None,
            department=department_obj.name if department_obj else department_name or None,
            department_id=department_obj.id if department_obj else None,
            salary=salary,
            phone_number=phone_number or None,
            status=status
        )
        user.set_password(password)
        if role == 'customer':
            user.meter_number = meter_number
            user.phone_number = phone_number or user.phone_number or '+2547000000000'
        if role in ['admin', 'examiner', 'hr_manager']:
            user.employee_id = user.generate_employee_id()

        db.session.add(user)
        db.session.flush()
        if role == 'customer':
            db.session.add(UserSettings(user_id=user.id, alert_threshold=user.threshold))
        db.session.commit()
        record_audit(current_user.id, 'user.created', 'user', user.id, {
            'username': username,
            'role': role,
            'department': user.department,
            'status': status
        })
        log_system_action(current_user.id, f'Created new user {username} with role {role}')
        flash(f'User {username} created successfully.', 'info')
    elif action == 'reset_password' and target_user_id:
        user = User.query.get(target_user_id)
        if user:
            new_password = password or secrets.token_urlsafe(10)
            user.set_password(new_password)
            db.session.commit()
            record_audit(current_user.id, 'user.password_reset', 'user', user.id)
            log_system_action(current_user.id, f'Reset password for user {user.username}')
            flash(f'Password for {user.username} has been reset.', 'info')
        else:
            flash('User not found for password reset.', 'warning')
    elif action == 'delete' and target_user_id:
        user = User.query.get(target_user_id)
        if user and user.id != current_user.id:
            db.session.delete(user)
            db.session.commit()
            record_audit(current_user.id, 'user.deleted', 'user', user.id, {'username': user.username, 'role': user.role})
            log_system_action(current_user.id, f'Deleted user {user.username}')
            flash(f'User {user.username} deleted successfully.', 'info')
        else:
            flash('Cannot delete this user.', 'warning')
    elif action in ('suspend', 'deactivate') and target_user_id:
        user = User.query.get(target_user_id)
        if user and user.id != current_user.id:
            old_status = user.status
            user.status = 'suspended'
            db.session.commit()
            record_audit(current_user.id, 'user.suspended', 'user', user.id, {'old_status': old_status, 'new_status': user.status})
            log_system_action(current_user.id, f'Suspended user {user.username}')
            flash(f'User {user.username} has been suspended.', 'info')
        else:
            flash('Cannot suspend this user.', 'warning')
    elif action in ('activate', 'restore') and target_user_id:
        user = User.query.get(target_user_id)
        if user:
            old_status = user.status
            user.status = 'active'
            db.session.commit()
            record_audit(current_user.id, 'user.activated', 'user', user.id, {'old_status': old_status, 'new_status': user.status})
            log_system_action(current_user.id, f'Activated user {user.username}')
            flash(f'User {user.username} has been reactivated.', 'info')
        else:
            flash('User not found for activation.', 'warning')
    elif action == 'update' and target_user_id:
        user = User.query.get(target_user_id)
        if user:
            changes = {}
            if email and email != user.email:
                changes['email'] = {'old': user.email, 'new': email}
                user.email = email
            if role and role in ['customer', 'examiner', 'admin', 'hr_manager'] and role != user.role:
                changes['role'] = {'old': user.role, 'new': role}
                user.role = role
                if role in ['admin', 'examiner', 'hr_manager'] and not user.employee_id:
                    user.employee_id = user.generate_employee_id()
            if password:
                user.set_password(password)
                changes['password'] = 'updated'
            if salary != user.salary:
                changes['salary'] = {'old': user.salary, 'new': salary}
                user.salary = salary
            if phone_number and phone_number != user.phone_number:
                changes['phone_number'] = {'old': user.phone_number, 'new': phone_number}
                user.phone_number = phone_number
            if department_obj:
                if user.department_id != department_obj.id:
                    changes['department'] = {'old': user.department, 'new': department_obj.name}
                user.department_id = department_obj.id
                user.department = department_obj.name
            elif department_name:
                if department_name != user.department:
                    changes['department'] = {'old': user.department, 'new': department_name}
                user.department = department_name
                user.department_id = None
            if status and status != user.status:
                changes['status'] = {'old': user.status, 'new': status}
                user.status = status
            db.session.commit()
            if changes:
                record_audit(current_user.id, 'user.updated', 'user', user.id, changes)
            log_system_action(current_user.id, f'Updated profile for user {user.username}')
            flash(f'User {user.username} updated successfully.', 'info')
        else:
            flash('User not found for update.', 'warning')
    elif action == 'assign_role' and target_user_id:
        user = User.query.get(target_user_id)
        if user and role in ['customer', 'examiner', 'admin', 'hr_manager']:
            old_role = user.role
            user.role = role
            if role in ['admin', 'examiner', 'hr_manager'] and not user.employee_id:
                user.employee_id = user.generate_employee_id()
            db.session.commit()
            record_audit(current_user.id, 'user.role_changed', 'user', user.id, {'old': old_role, 'new': role})
            log_system_action(current_user.id, f'Assigned role {role} to {user.username}')
            flash(f'{user.username} is now a {role}.', 'info')
        else:
            flash('Invalid role assignment request.', 'warning')
    else:
        flash('Unrecognized user management action.', 'warning')

    return redirect(url_for('admin_financial'))


@app.route('/admin/toggle_feature', methods=['POST'])
@login_required
@admin_required
def admin_toggle_feature():
    feature_id = request.form.get('feature_id', type=int)
    feature = FeatureToggle.query.get(feature_id)
    if feature:
        feature.enabled = not feature.enabled
        db.session.commit()
        record_audit(current_user.id, 'feature.toggle', 'feature_toggle', feature.id, {'name': feature.name, 'enabled': feature.enabled})
        log_system_action(current_user.id, f'Toggled feature {feature.name} to {feature.enabled}')
        flash(f'Feature {feature.name} is now {"enabled" if feature.enabled else "disabled"}.', 'info')
    else:
        flash('Feature not found.', 'warning')
    return redirect(url_for('admin_financial'))


@app.route('/admin/upload_dataset', methods=['POST'])
@login_required
@admin_required
def admin_upload_dataset():
    file = request.files.get('dataset_file')
    if not file:
        flash('Please select a dataset file to upload.', 'warning')
        return redirect(url_for('admin_financial'))

    try:
        data = file.read().decode('utf-8').splitlines()
        reader = csv.DictReader(data)
        total_added = 0
        for row in reader:
            username = (row.get('username') or '').strip()
            if not username:
                continue
            user = User.query.filter_by(username=username).first()
            if not user:
                continue
            date = row.get('date') or row.get('period') or ''
            kwh = float(row.get('kwh') or 0)
            cost = float(row.get('cost') or (kwh * user.unit_cost))
            timestamp = parse_local_datetime_input(row.get('timestamp') or '')
            reading = Reading(user_id=user.id, date=date, kwh=kwh, cost=cost, timestamp=timestamp, is_reviewed=False, is_approved=False)
            db.session.add(reading)
            total_added += 1
        db.session.commit()
        log_system_action(current_user.id, f'Uploaded dataset and added {total_added} readings.')
        flash(f'Dataset uploaded successfully, {total_added} readings added.', 'info')
    except Exception as e:
        db.session.rollback()
        flash(f'Error processing dataset: {e}', 'warning')

    return redirect(url_for('admin_financial'))


@app.route('/admin/approve_device/<int:device_id>', methods=['POST'])
@login_required
@admin_required
def admin_approve_device(device_id):
    device = CustomerDevice.query.get(device_id)
    if device:
        device.is_active = True
        db.session.commit()
        log_system_action(current_user.id, f'Approved IoT device {device.name} for user {device.user.username}')
        flash(f'Device {device.name} approved successfully.', 'info')
    else:
        flash('Device not found.', 'warning')
    return redirect(url_for('admin_financial'))


@app.route('/admin/generate_system_report', methods=['POST'])
@login_required
@admin_required
def admin_generate_system_report():
    report_data = {
        'users': User.query.count(),
        'customers': User.query.filter_by(role='customer').count(),
        'admins': User.query.filter_by(role='admin').count(),
        'examiners': User.query.filter_by(role='examiner').count(),
        'readings': Reading.query.count(),
        'financial_records': FinancialRecord.query.count(),
        'reports': Report.query.count(),
        'system_logs': SystemLog.query.count(),
        'generated_at': datetime.utcnow().isoformat()
    }
    report_content = '<h2>System Performance Report</h2>'
    report_content += '<ul>'
    for key, value in report_data.items():
        report_content += f'<li><strong>{key.replace("_", " ").title()}:</strong> {value}</li>'
    report_content += '</ul>'

    report = Report(
        title=f'System Report - {datetime.utcnow().strftime("%Y-%m-%d")}',
        content=report_content,
        report_type='system_report',
        sent_by=current_user.id,
        sent_to=current_user.id
    )
    db.session.add(report)
    db.session.commit()
    log_system_action(current_user.id, 'Generated system performance report')
    flash('System performance report generated successfully.', 'info')
    return redirect(url_for('admin_financial'))


@app.route('/examiner/financial-center')
@login_required
@examiner_required
def examiner_financial_center():
    financial_records = FinancialRecord.query.order_by(FinancialRecord.created_at.desc()).all()
    pending_approvals = TariffApproval.query.filter_by(status='pending').order_by(TariffApproval.created_at.desc()).all()
    audit_logs = SystemLog.query.order_by(SystemLog.timestamp.desc()).limit(20).all()
    total_revenue = sum(record.total_cost for record in financial_records)
    total_collected = sum(record.total_paid for record in financial_records)
    total_outstanding = sum(record.balance for record in financial_records)
    forecast_value = round(total_revenue * 1.08, 2)
    cost_benefit = round(max(0.0, forecast_value - total_revenue), 2)

    return render_template('examiner_finance_center.html',
                           financial_records=financial_records,
                           pending_approvals=pending_approvals,
                           audit_logs=audit_logs,
                           total_revenue=total_revenue,
                           total_collected=total_collected,
                           total_outstanding=total_outstanding,
                           forecast_value=forecast_value,
                           cost_benefit=cost_benefit)


@app.route('/examiner/tariff-approval/<int:approval_id>/<string:decision>', methods=['POST'])
@login_required
@examiner_required
def examiner_tariff_decision(approval_id, decision):
    approval = TariffApproval.query.get_or_404(approval_id)
    approval.status = 'approved' if decision == 'approve' else 'rejected'
    approval.reviewed_by = current_user.id
    approval.reviewed_at = datetime.utcnow()
    approval.review_note = request.form.get('review_note', '') or ('Approved for release to customers.' if decision == 'approve' else 'Returned for admin revision.')
    db.session.commit()
    log_system_action(current_user.id, f'Tariff decision {approval.status} for approval {approval_id}')
    flash('Tariff review updated successfully.', 'info')
    return redirect(url_for('examiner_financial_center'))


@app.route('/examiner/export-financial-report')
@login_required
@examiner_required
def examiner_export_financial_report():
    financial_records = FinancialRecord.query.order_by(FinancialRecord.created_at.desc()).all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Customer', 'Period', 'Total Cost', 'Total Paid', 'Balance', 'Status'])
    for record in financial_records:
        writer.writerow([
            record.user.username if record.user else 'Unknown',
            record.period,
            f"{record.total_cost:.2f}",
            f"{record.total_paid:.2f}",
            f"{record.balance:.2f}",
            record.payment_status,
        ])
    response = Response(output.getvalue(), mimetype='text/csv')
    response.headers['Content-Disposition'] = 'attachment; filename=examiner_financial_report.csv'
    return response


@app.route('/hr/people-ops', methods=['GET', 'POST'])
@login_required
def hr_people_ops():
    if not is_hr_manager(current_user):
        abort(403)

    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'submit_leave':
            leave_request = EmployeeLeaveRequest(
                user_id=current_user.id,
                employee_name=(request.form.get('employee_name') or current_user.username).strip(),
                start_date=request.form.get('start_date', '').strip(),
                end_date=request.form.get('end_date', '').strip(),
                reason=request.form.get('reason', '').strip(),
            )
            db.session.add(leave_request)
            db.session.commit()
            log_system_action(current_user.id, 'Submitted new leave request')
            flash('Leave request saved and queued for review.', 'success')
        elif action == 'submit_training':
            training_record = EmployeeTrainingRecord(
                employee_id=request.form.get('employee_id', type=int) or current_user.id,
                title=request.form.get('title', '').strip(),
                provider=request.form.get('provider', '').strip(),
                completed_on=request.form.get('completed_on', '').strip(),
                status=request.form.get('status', 'scheduled').strip(),
                notes=request.form.get('notes', '').strip(),
            )
            db.session.add(training_record)
            db.session.commit()
            log_system_action(current_user.id, f'Added training record {training_record.title}')
            flash('Training record added successfully.', 'success')
        elif action == 'submit_review':
            review = EmployeePerformanceReview(
                employee_id=request.form.get('employee_id', type=int) or current_user.id,
                review_period=request.form.get('review_period', '').strip(),
                score=float(request.form.get('score', 0) or 0),
                summary=request.form.get('summary', '').strip(),
                status=request.form.get('status', 'draft').strip(),
            )
            db.session.add(review)
            db.session.commit()
            log_system_action(current_user.id, f'Added performance review for employee {review.employee_id}')
            flash('Performance review recorded successfully.', 'success')
        elif action == 'review_leave':
            leave_request = EmployeeLeaveRequest.query.get(request.form.get('leave_id', type=int))
            if leave_request:
                leave_request.status = request.form.get('leave_status', 'pending').strip()
                leave_request.reviewed_by = current_user.id
                leave_request.reviewed_at = datetime.utcnow()
                db.session.commit()
                log_system_action(current_user.id, f'Updated leave request {leave_request.id} to {leave_request.status}')
                flash('Leave status updated.', 'success')
        return redirect(url_for('hr_people_ops'))

    employees = User.query.filter(User.role != 'customer').order_by(User.username).all()
    leave_requests = EmployeeLeaveRequest.query.order_by(EmployeeLeaveRequest.created_at.desc()).all()
    training_records = EmployeeTrainingRecord.query.order_by(EmployeeTrainingRecord.created_at.desc()).all()
    performance_reviews = EmployeePerformanceReview.query.order_by(EmployeePerformanceReview.created_at.desc()).all()
    departments = Department.query.order_by(Department.name).all()
    return render_template('hr_people_ops.html',
                           employees=employees,
                           leave_requests=leave_requests,
                           training_records=training_records,
                           performance_reviews=performance_reviews,
                           departments=departments)


@app.route('/admin/ticketing-settings', methods=['POST'])
@login_required
@admin_required
def admin_ticketing_settings():
    enabled = request.form.get('enabled', 'true').lower() in ('1', 'true', 'yes', 'on')
    toggle = get_ticketing_toggle()
    toggle.enabled = enabled
    db.session.commit()
    flash(f'Support ticketing is now {"enabled" if enabled else "disabled"}.', 'success')
    return redirect(url_for('support_center'))


@app.route('/support', methods=['GET', 'POST'])
def support_center():
    ticketing_enabled = is_ticketing_enabled()
    if request.method == 'POST':
        if not ticketing_enabled and (not current_user.is_authenticated or current_user.role == 'customer'):
            flash('Support ticketing is currently closed. Please use our main contact channels for urgent help.', 'warning')
            return redirect(url_for('support_center'))

        ticket = SupportTicket(
            user_id=current_user.id if current_user.is_authenticated else None,
            name=(request.form.get('name') or (current_user.username if current_user.is_authenticated else '')).strip(),
            email=(request.form.get('email') or (current_user.email if current_user.is_authenticated else '')).strip(),
            subject=request.form.get('subject', '').strip(),
            message=request.form.get('message', '').strip(),
        )
        db.session.add(ticket)
        db.session.commit()
        flash('Support request received. Our team will follow up shortly.', 'success')
        return redirect(url_for('support_center'))

    tickets = []
    if current_user.is_authenticated and current_user.role in {'admin', 'examiner', 'hr_manager'}:
        tickets = SupportTicket.query.order_by(SupportTicket.created_at.desc()).all()

    if not ticketing_enabled and current_user.is_authenticated and current_user.role == 'customer':
        flash('Support ticketing is currently closed. Please contact us through the main support channels.', 'warning')

    return render_template('support_center.html', tickets=tickets, ticketing_enabled=ticketing_enabled)


@app.route('/trust-center', methods=['GET', 'POST'])
def ecosystem_trust():
    if request.method == 'POST':
        partnership_request = PartnershipRequest(
            name=request.form.get('name', '').strip(),
            email=request.form.get('email', '').strip(),
            organization=request.form.get('organization', '').strip(),
            need=request.form.get('need', '').strip(),
        )
        db.session.add(partnership_request)
        db.session.commit()
        flash('Your partnership request was captured successfully.', 'success')
        return redirect(url_for('ecosystem_trust'))

    metrics = build_sustainability_summary()
    partnership_requests = PartnershipRequest.query.order_by(PartnershipRequest.created_at.desc()).all()
    return render_template('ecosystem_trust.html', metrics=metrics, partnership_requests=partnership_requests)


@app.route('/admin/backup', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_backup_restore():
    if request.method == 'POST':
        uploaded_file = request.files.get('backup_file')
        if uploaded_file and uploaded_file.filename:
            with uploaded_file.stream as stream:
                payload = json.load(stream)
            if isinstance(payload, dict):
                flash('Restore payload accepted. The backup module is ready for future expansion.', 'info')
            else:
                flash('Uploaded backup file was not in the expected format.', 'warning')
        else:
            flash('Please upload a backup file for restore.', 'warning')
        return redirect(url_for('admin_backup_restore'))

    backup_payload = {
        'users': [
            {
                'username': user.username,
                'email': user.email,
                'role': user.role,
                'department': user.department,
                'salary': user.salary,
                'status': user.status,
            }
            for user in User.query.all()
        ],
        'departments': [
            {'name': dept.name, 'description': dept.description}
            for dept in Department.query.all()
        ],
        'feature_toggles': [
            {'name': feature.name, 'enabled': feature.enabled}
            for feature in FeatureToggle.query.all()
        ],
        'generated_at': datetime.utcnow().isoformat()
    }

    response = Response(json.dumps(backup_payload, indent=2), mimetype='application/json')
    response.headers['Content-Disposition'] = 'attachment; filename=ecopulse_backup.json'
    if request.args.get('download') == '1':
        return response

    return render_template('admin_backup_restore.html', backup_payload=backup_payload)


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
    energy_source = normalize_energy_source(request.form.get('energy_source'), default='KPLC')
    energy_source_label = get_energy_source_label(energy_source)
    try:
        cost_per_unit = float(request.form.get('cost_per_unit', '0'))
    except (TypeError, ValueError):
        flash(f'Enter a valid {energy_source_label} cost per unit.', 'warning')
        return redirect(url_for('admin_financial'))

    effective_date_raw = (request.form.get('effective_date') or '').strip()
    notice_reference = (request.form.get('notice_reference') or f'{energy_source_label} Tariff Notice').strip()
    notice_message = (request.form.get('notice_message') or '').strip()
    if cost_per_unit <= 0:
        flash(f'{energy_source_label} cost per unit must be greater than zero.', 'warning')
        return redirect(url_for('admin_financial'))

    effective_date = datetime.fromisoformat(effective_date_raw) if effective_date_raw else utc_now()
    users = User.query.filter(User.role == 'customer', User.energy_source == energy_source).all()
    for user in users:
        user.unit_cost = cost_per_unit

    payload = {
        'cost_per_unit': round(cost_per_unit, 2),
        'effective_date': effective_date.strftime('%Y-%m-%d'),
        'notice_reference': notice_reference,
        'energy_source': energy_source
    }
    db.session.add(Report(
        title=f"{energy_source_label} Tariff Update - {effective_date.strftime('%Y-%m-%d')}",
        content=(
            f"<p><strong>Reference:</strong> {notice_reference}</p>"
            f"<p><strong>Cost per unit/token:</strong> Ksh {cost_per_unit:.2f}</p>"
            f"<p><strong>Effective date:</strong> {effective_date.strftime('%Y-%m-%d')}</p>"
            f"<p><strong>Energy source:</strong> {energy_source_label}</p>"
            f"<p>{notice_message or f'Tariff updated from {energy_source_label} notice for billing clarity.'}</p>"
        ),
        report_type='tariff_notice',
        sent_by=current_user.id,
        sent_to=None,
        chart_data=json.dumps(payload)
    ))
    db.session.add(TariffApproval(
        created_by=current_user.id,
        title=f"{energy_source_label} tariff validation request",
        description=notice_message or f"Review the {energy_source_label} tariff update before it is broadcast to customers.",
        energy_source=energy_source,
        proposed_cost=cost_per_unit,
        status='pending',
    ))
    db.session.commit()

    log_system_action(current_user.id, f"Updated {energy_source_label} tariff to Ksh {cost_per_unit:.2f}")
    flash(f'{energy_source_label} tariff updated. Customers now see the latest source-specific cost per unit.', 'info')
    return redirect(url_for('admin_financial', energy_source=energy_source))


def build_user_ai_report(user):
    """Build AI analysis report specific to a user"""
    # Get user's readings
    readings = Reading.query.filter_by(user_id=user.id).order_by(Reading.timestamp.desc()).limit(30).all()
    
    if not readings:
        return {
            'problem_statement': f'Personalized AI analysis for {user.username} - insufficient data for detailed insights.',
            'agent': {
                'name': 'Personal EcoPulse Assistant',
                'type': 'User-focused agent',
                'justification': f'Dedicated analysis for {user.username} to provide personalized energy insights and recommendations.',
                'peas': {
                    'Performance': f'Optimize energy usage for {user.username}, reduce costs, and improve efficiency.',
                    'Environment': f'{user.username}\'s energy dashboard with personal readings, thresholds, and usage patterns.',
                    'Actuators': f'Send personalized alerts to {user.username}, recommend actions, generate reports.',
                    'Sensors': f'{user.username}\'s meter readings, threshold settings, timestamps, and usage history.'
                }
            },
            'search': {'comparison': [], 'problem': {'customer': user.username, 'start_excess': 0}},
            'reasoning': [],
            'ml': {'model_name': 'Linear Regression', 'years_evaluated': 0, 'mae': 0, 'rmse': 0, 'mape': 0, 'predictions': []},
            'visualization': generate_consumption_chart(user.id) or ''
        }
    
    # Calculate user's metrics
    total_kwh = sum(r.kwh for r in readings)
    avg_kwh = total_kwh / len(readings)
    excess = max(0, avg_kwh - user.threshold)
    
    # Get user's balance
    latest_invoice = FinancialRecord.query.filter_by(user_id=user.id).order_by(FinancialRecord.created_at.desc()).first()
    balance = latest_invoice.balance if latest_invoice else 0
    
    # Determine risk level
    if excess > user.threshold * 0.5:
        risk = 'High'
    elif excess > user.threshold * 0.25:
        risk = 'Medium'
    else:
        risk = 'Low'
    
    # Generate personalized advice
    advice = []
    fired_rules = []
    
    if excess > 0:
        advice.append("Reduce energy consumption to stay within threshold")
        fired_rules.append("Excess usage detected")
    
    if user.energy_source == 'SOLAR':
        advice.append("Maximize solar energy usage during peak sunlight hours")
        fired_rules.append("Solar energy source optimization")
    
    if user.user_type == 'business':
        advice.append("Implement energy management systems for business operations")
        fired_rules.append("Business energy optimization")
    
    # Simple forecast for user
    forecast_data = []
    if len(readings) >= 7:
        recent_avg = sum(r.kwh for r in readings[:7]) / 7
        for i in range(1, 8):
            forecast_data.append({
                'day': f'Day {i}',
                'predicted': round(recent_avg * (1.02 if i in [6,7] else 1.0), 2)
            })
    
    return {
        'problem_statement': f'Personalized AI analysis for {user.username} to optimize energy usage and reduce costs.',
        'agent': {
            'name': 'Personal EcoPulse Assistant',
            'type': 'User-focused agent',
            'justification': f'Dedicated analysis for {user.username} to provide personalized energy insights and recommendations.',
            'peas': {
                'Performance': f'Optimize energy usage for {user.username}, reduce costs, and improve efficiency.',
                'Environment': f'{user.username}\'s energy dashboard with personal readings, thresholds, and usage patterns.',
                'Actuators': f'Send personalized alerts to {user.username}, recommend actions, generate reports.',
                'Sensors': f'{user.username}\'s meter readings, threshold settings, timestamps, and usage history.'
            }
        },
        'search': {
            'comparison': [
                {
                    'algorithm': 'Personal BFS',
                    'path_length': 3,
                    'solution_cost': round(excess * user.unit_cost, 2),
                    'states_explored': len(readings),
                    'solution': 'Monitor usage, reduce consumption, optimize timing'
                },
                {
                    'algorithm': 'Personal A*',
                    'path_length': 2,
                    'solution_cost': round(excess * user.unit_cost * 0.8, 2),
                    'states_explored': len(readings) // 2,
                    'solution': 'Prioritize high-impact actions, schedule optimization'
                }
            ],
            'problem': {'customer': user.username, 'start_excess': round(excess, 2)}
        },
        'reasoning': [{
            'customer': user.username,
            'latest_period': readings[0].timestamp.strftime('%Y-%m') if readings else 'N/A',
            'latest_kwh': round(readings[0].kwh, 2) if readings else 0,
            'threshold': user.threshold,
            'excess_kwh': round(excess, 2),
            'balance': round(balance, 2),
            'risk': risk,
            'advice': '; '.join(advice),
            'fired_rules': fired_rules
        }],
        'ml': {
            'model_name': 'Linear Regression',
            'years_evaluated': 0,  # Simplified for user view
            'mae': 0,
            'rmse': 0,
            'mape': 0,
            'predictions': []
        },
        'visualization': generate_consumption_chart(user.id) or ''
    }


@app.route('/ai-analysis')
@login_required
def ai_analysis():
    if current_user.role == 'customer':
        # Build user-specific AI analysis
        report = build_user_ai_report(current_user)
    else:
        # System-wide analysis for admin/examiner
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


@app.route('/admin/departments', methods=['GET', 'POST'])
@login_required
@admin_required
def manage_departments():
    hr_manager = get_assigned_hr_manager()

    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'assign_hr_manager':
            hr_user_id = request.form.get('hr_manager_id')
            hr_user = User.query.get(hr_user_id) if hr_user_id else None
            hr_dept = Department.query.filter(Department.name.ilike('%human resources%')).first()
            if not hr_dept:
                hr_dept = Department(name='Human Resources', description='Human Resources and hiring operations')
                db.session.add(hr_dept)
                db.session.flush()

            current_hr = get_assigned_hr_manager()
            if current_hr and (not hr_user or current_hr.id != hr_user.id):
                current_hr.is_department_head = False
                current_hr.department_id = None

            if hr_user:
                hr_dept.head_id = hr_user.id
                hr_user.is_department_head = True
                hr_user.department_id = hr_dept.id
                flash('HR manager assigned successfully', 'success')
            else:
                hr_dept.head_id = None
                flash('HR manager assignment cleared', 'success')

            db.session.commit()
        elif action == 'assign_head':
            dept_id = request.form.get('dept_id')
            head_id = request.form.get('head_id')
            dept = Department.query.get(dept_id)
            if dept:
                dept.head_id = head_id
                if head_id:
                    head_user = User.query.get(head_id)
                    if head_user:
                        head_user.is_department_head = True
                        head_user.department_id = dept_id
                db.session.commit()
                flash('Department head assigned successfully', 'success')
        elif action == 'add_member':
            dept_id = request.form.get('dept_id')
            user_id = request.form.get('user_id')
            user = User.query.get(user_id)
            if user:
                user.department_id = dept_id
                db.session.commit()
                flash('User added to department successfully', 'success')

    departments = Department.query.all()
    users = User.query.filter(User.role.in_(['examiner', 'admin'])).all()
    return render_template_string(department_management_template,
                                  departments=departments,
                                  users=users,
                                  hr_manager=hr_manager)


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
        current_user.unit_cost = get_active_unit_cost(current_user)
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
        current_user.unit_cost = get_active_unit_cost(current_user)
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


@app.route('/api/notifications/stream')
@login_required
def notification_stream():
    user_id = current_user.id
    try:
        last_event_id = int(request.headers.get('Last-Event-ID', request.args.get('last_id', 0)) or 0)
    except (TypeError, ValueError):
        last_event_id = 0

    @stream_with_context
    def event_stream():
        nonlocal last_event_id
        while True:
            events = get_live_notifications_since(user_id, last_event_id)
            if events:
                for event in events:
                    last_event_id = int(event.get('id', last_event_id))
                    yield f"id: {last_event_id}\n"
                    yield "event: notification\n"
                    yield f"data: {json.dumps(event)}\n\n"
            else:
                yield ": keep-alive\n\n"
            time.sleep(1)

    response = Response(event_stream(), mimetype='text/event-stream')
    response.headers['Cache-Control'] = 'no-cache'
    response.headers['X-Accel-Buffering'] = 'no'
    return response


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
        current_user.language = request.form.get('language', current_user.language or 'en') or 'en'

        if current_user.role in ['admin', 'examiner']:
            current_user.department = department or None

        current_user.threshold = float(request.form.get('threshold', current_user.threshold))
        current_user.currency = request.form.get('currency', current_user.currency)
        current_user.alert_email = 'alert_email' in request.form

        if current_user.role == 'customer':
            meter_number = ''.join(ch for ch in (request.form.get('meter_number') or '') if ch.isdigit())
            energy_source = normalize_energy_source(request.form.get('energy_source'), default=current_user.energy_source)
            country_code = (request.form.get('country_code') or selected_country_code).strip()
            phone_number = (request.form.get('phone_number') or '').strip()
            current_user.energy_source = energy_source
            if energy_source == 'KPLC':
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
            if phone_error:
                flash(phone_error, 'warning')
                return redirect(url_for('settings'))
            current_user.phone_number = normalized_phone

        current_user.unit_cost = get_active_unit_cost(current_user)
        user_settings.alert_threshold = current_user.threshold
        user_settings.allow_overage = 'allow_overage' in request.form
        user_settings.auto_shutdown_enabled = 'auto_shutdown_enabled' in request.form
        user_settings.shutdown_delay_minutes = int(request.form.get('shutdown_delay_minutes') or 5)

        db.session.commit()
        message = "Settings updated successfully!"
        log_system_action(current_user.id, "Updated settings")
        flash(message, 'success')
        return redirect(url_for('dashboard'))

    # Use the existing settings_template (not settings_template_v2)
    return render_template_string(settings_template,
                                  user_settings=user_settings,
                                  message=message,
                                  current_tariff=get_latest_tariff_notice(current_user.energy_source),
                                  energy_sources=ENERGY_SOURCES,
                                  energy_source_labels=ENERGY_SOURCE_LABELS,
                                  phone_country_codes=PHONE_COUNTRY_CODES,
                                  language_options=LANGUAGE_OPTIONS,
                                  selected_country_code=selected_country_code,
                                  selected_energy_source=normalize_energy_source(current_user.energy_source),
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


@app.route('/customer/payments')
@login_required
def customer_payments():
    if current_user.role != 'customer':
        flash('Only customer accounts can access the payments page.', 'warning')
        return redirect(url_for('dashboard'))

    customer_invoices = FinancialRecord.query.filter_by(user_id=current_user.id) \
        .order_by(FinancialRecord.created_at.desc()).all()
    payable_invoices = [invoice for invoice in customer_invoices if (invoice.balance or 0) > 0]
    return render_template('customer_payments.html',
                           customer_invoices=customer_invoices,
                           payable_invoices=payable_invoices,
                           current_user=current_user)


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
    payment_phone = (request.form.get('payment_phone') or '').strip()
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

    transaction_reference = payment_reference or f"PAY-{record.id}-{int(time.time())}"
    if PaymentTransaction.query.filter_by(transaction_id=transaction_reference).first():
        transaction_reference = f"{transaction_reference}-{uuid.uuid4().hex[:6].upper()}"

    payment_transaction = PaymentTransaction(
        user_id=current_user.id,
        amount=payment_amount,
        currency=current_user.currency or 'Ksh',
        payment_method=payment_method,
        transaction_id=transaction_reference,
        status='completed',
        subscription_tier='free'
    )
    db.session.add(payment_transaction)
    db.session.commit()

    log_system_action(
        current_user.id,
        f"Customer payment recorded for {record.period} via {payment_method_labels[payment_method]}: "
        f"{current_user.currency} {payment_amount:.2f}"
        + (f" (ref: {payment_reference})" if payment_reference else "")
        + (f" (phone: {payment_phone})" if payment_phone else "")
    )
    flash(
        f'Payment of {current_user.currency} {payment_amount:.2f} via {payment_method_labels[payment_method]} recorded for {record.period}.',
        'info'
    )
    return redirect(url_for('customer_payments'))


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


@app.route('/export_xlsx')
@login_required
def export_xlsx():
    """Export readings as Excel workbook"""
    readings = Reading.query.filter_by(user_id=current_user.id).all()
    if not readings:
        return "No data", 404

    try:
        from openpyxl import Workbook
    except ImportError:
        return "Excel export requires openpyxl", 500

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = 'EcoPulse Data'
    headers = ['Month', 'kWh', 'Cost', 'CO2', 'Status', 'Timestamp']
    sheet.append(headers)

    for reading in readings:
        co2 = reading.kwh * 0.385
        status = "Approved" if reading.is_approved else "Pending" if not reading.is_reviewed else "Reviewed"
        sheet.append([
            reading.date,
            reading.kwh,
            f"{reading.cost:.2f}",
            f"{co2:.2f}",
            status,
            reading.timestamp.strftime('%Y-%m-%d %H:%M:%S')
        ])

    buffer = io.BytesIO()
    workbook.save(buffer)
    buffer.seek(0)

    log_system_action(current_user.id, "Exported data to Excel")

    return send_file(
        buffer,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=f"ecopulse_{current_user.username}.xlsx"
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


department_management_template = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Department Management - EcoPulse Admin</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.10.0/font/bootstrap-icons.css">
    <style>
        body { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); min-height: 100vh; }
        .card { border: none; border-radius: 15px; box-shadow: 0 10px 30px rgba(0,0,0,0.2); }
        .navbar { background: rgba(0,0,0,0.7); }
    </style>
</head>
<body>
    <nav class="navbar navbar-expand-lg navbar-dark">
        <div class="container">
            <a class="navbar-brand" href="{{ url_for('admin_financial') }}"><i class="bi bi-building"></i> EcoPulse Admin</a>
            <div class="navbar-nav ms-auto">
                <a class="nav-link" href="{{ url_for('admin_financial') }}">Dashboard</a>
                <a class="nav-link" href="{{ url_for('logout') }}">Logout</a>
            </div>
        </div>
    </nav>

    <div class="container mt-4">
        <h1 class="text-white mb-4"><i class="bi bi-diagram-3"></i> Department Management</h1>

        {% with messages = get_flashed_messages(with_categories=true) %}
            {% if messages %}
                {% for category, message in messages %}
                    <div class="alert alert-{{ 'success' if category == 'success' else 'danger' }} alert-dismissible fade show">
                        {{ message }}
                        <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
                    </div>
                {% endfor %}
            {% endif %}
        {% endwith %}

        <div class="card mb-4">
            <div class="card-body">
                <h5 class="card-title">HR Manager Assignment</h5>
                <p class="text-muted">Assign the active HR manager who receives career applications and manages hiring operations.</p>
                <form method="POST" class="row g-3 align-items-end">
                    <input type="hidden" name="action" value="assign_hr_manager">
                    <div class="col-md-8">
                        <label class="form-label">HR Manager</label>
                        <select name="hr_manager_id" class="form-select">
                            <option value="">Clear HR manager</option>
                            {% for user in users %}
                            <option value="{{ user.id }}" {% if hr_manager and hr_manager.id == user.id %}selected{% endif %}>
                                {{ user.username }} — {{ user.email }}
                            </option>
                            {% endfor %}
                        </select>
                    </div>
                    <div class="col-md-4">
                        <button type="submit" class="btn btn-warning w-100">Save HR Manager</button>
                    </div>
                </form>
                {% if hr_manager %}
                <div class="mt-3 text-muted">
                    Current HR Manager: <strong>{{ hr_manager.username }}</strong> &middot; <a href="mailto:{{ hr_manager.email }}">{{ hr_manager.email }}</a>
                </div>
                {% else %}
                <div class="mt-3 text-muted">No HR manager is currently assigned.</div>
                {% endif %}
            </div>
        </div>

        <div class="row">
            {% for dept in departments %}
            <div class="col-md-6 mb-4">
                <div class="card">
                    <div class="card-header bg-primary text-white">
                        <h5 class="mb-0"><i class="bi bi-building"></i> {{ dept.name }}</h5>
                    </div>
                    <div class="card-body">
                        <p class="text-muted">{{ dept.description }}</p>
                        <p><strong>Head:</strong> 
                            {% if dept.head %}
                                {{ dept.head.username }} ({{ dept.head.email }})
                            {% else %}
                                Not Assigned
                            {% endif %}
                        </p>
                        
                        <form method="POST" class="mb-3">
                            <input type="hidden" name="action" value="assign_head">
                            <input type="hidden" name="dept_id" value="{{ dept.id }}">
                            <div class="input-group">
                                <select name="head_id" class="form-select">
                                    <option value="">Select Head</option>
                                    {% for user in users %}
                                    <option value="{{ user.id }}" {% if dept.head_id == user.id %}selected{% endif %}>
                                        {{ user.username }} - {{ user.role }}
                                    </option>
                                    {% endfor %}
                                </select>
                                <button type="submit" class="btn btn-primary">Assign Head</button>
                            </div>
                        </form>

                        <h6>Members:</h6>
                        <ul class="list-group mb-3">
                            {% for user in users %}
                                {% if user.department_id == dept.id %}
                                <li class="list-group-item d-flex justify-content-between align-items-center">
                                    {{ user.username }} ({{ user.role }})
                                    {% if user.is_department_head %}
                                    <span class="badge bg-success">Head</span>
                                    {% endif %}
                                </li>
                                {% endif %}
                            {% endfor %}
                        </ul>

                        <form method="POST">
                            <input type="hidden" name="action" value="add_member">
                            <input type="hidden" name="dept_id" value="{{ dept.id }}">
                            <div class="input-group">
                                <select name="user_id" class="form-select">
                                    <option value="">Add Member</option>
                                    {% for user in users %}
                                        {% if not user.department_id or user.department_id != dept.id %}
                                        <option value="{{ user.id }}">{{ user.username }} - {{ user.role }}</option>
                                        {% endif %}
                                    {% endfor %}
                                </select>
                                <button type="submit" class="btn btn-success">Add</button>
                            </div>
                        </form>
                    </div>
                </div>
            </div>
            {% endfor %}
        </div>
    </div>

    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
"""


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

        # Check if users table has new columns
        if 'users' in inspector.get_table_names():
            users_columns = [col['name'] for col in inspector.get_columns('users')]
            users_required = {
                'department_id': 'INTEGER',
                'salary': 'FLOAT DEFAULT 0',
                'is_department_head': 'BOOLEAN DEFAULT 0',
                'threshold': 'FLOAT DEFAULT 600',
                'currency': "VARCHAR(10) DEFAULT 'Ksh'",
                'unit_cost': 'FLOAT DEFAULT 0.12',
                'alert_email': 'BOOLEAN DEFAULT 1',
                'energy_source': "VARCHAR(20) DEFAULT 'KPLC'",
                'language': "VARCHAR(10) DEFAULT 'en'",
                'user_type': "VARCHAR(20) DEFAULT 'smart_home'",
                'meter_number': 'VARCHAR(11)',
                'phone': 'VARCHAR(20)',
                'status': "VARCHAR(20) DEFAULT 'active'"
            }
            for col_name, col_type in users_required.items():
                if col_name not in users_columns:
                    print(f" Adding missing '{col_name}' column to users table...")
                    with db.engine.connect() as conn:
                        conn.execute(db.text(f"ALTER TABLE users ADD COLUMN {col_name} {col_type}"))
                        conn.commit()
                    print(f" '{col_name}' column added successfully!")

        # Check if support_tickets table exists and add missing columns for older databases
        if 'support_tickets' in inspector.get_table_names():
            support_columns = [col['name'] for col in inspector.get_columns('support_tickets')]
            support_required = {
                'user_id': 'INTEGER',
                'name': 'VARCHAR(120)',
                'email': 'VARCHAR(120)',
                'subject': "VARCHAR(200) DEFAULT ''",
                'message': 'TEXT',
                'description': 'TEXT',
                'status': "VARCHAR(50) DEFAULT 'open'",
                'priority': "VARCHAR(20) DEFAULT 'medium'",
                'assignee_id': 'INTEGER',
                'created_at': 'DATETIME',
                'updated_at': 'DATETIME',
                'resolved_at': 'DATETIME'
            }
            for col_name, col_type in support_required.items():
                if col_name not in support_columns:
                    print(f" Adding missing '{col_name}' column to support_tickets table...")
                    with db.engine.connect() as conn:
                        conn.execute(db.text(f"ALTER TABLE support_tickets ADD COLUMN {col_name} {col_type}"))
                        conn.commit()
                    print(f" '{col_name}' column added successfully!")

        # Check if departments table exists
        if 'departments' not in inspector.get_table_names():
            print(" Creating departments table...")
            with db.engine.connect() as conn:
                conn.execute(db.text("""
                    CREATE TABLE departments (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name VARCHAR(50) UNIQUE NOT NULL,
                        description TEXT,
                        head_id INTEGER,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (head_id) REFERENCES users (id)
                    )
                """))
                conn.commit()
            print(" Departments table created successfully!")

        # Check if new tables exist and create them if not
        new_tables = [
            ('energy_goals', """
                CREATE TABLE energy_goals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    goal_type VARCHAR(50) DEFAULT 'monthly_savings',
                    target_value FLOAT NOT NULL,
                    current_value FLOAT DEFAULT 0,
                    start_date DATETIME DEFAULT CURRENT_TIMESTAMP,
                    end_date DATETIME NOT NULL,
                    status VARCHAR(20) DEFAULT 'active',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (id)
                )
            """),
            ('forum_posts', """
                CREATE TABLE forum_posts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    title VARCHAR(200) NOT NULL,
                    content TEXT NOT NULL,
                    category VARCHAR(50) DEFAULT 'general',
                    likes INTEGER DEFAULT 0,
                    replies_count INTEGER DEFAULT 0,
                    is_pinned BOOLEAN DEFAULT 0,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (id)
                )
            """),
            ('forum_replies', """
                CREATE TABLE forum_replies (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    post_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    likes INTEGER DEFAULT 0,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (post_id) REFERENCES forum_posts (id),
                    FOREIGN KEY (user_id) REFERENCES users (id)
                )
            """),
            ('rubrics', """
                CREATE TABLE rubrics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name VARCHAR(100) NOT NULL,
                    description TEXT,
                    criteria TEXT,
                    created_by INTEGER NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (created_by) REFERENCES users (id)
                )
            """),
            ('comment_templates', """
                CREATE TABLE comment_templates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name VARCHAR(100) NOT NULL,
                    content TEXT NOT NULL,
                    category VARCHAR(50) DEFAULT 'general',
                    created_by INTEGER NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (created_by) REFERENCES users (id)
                )
            """),
            ('performance_analytics', """
                CREATE TABLE performance_analytics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    period VARCHAR(20) DEFAULT 'monthly',
                    metric_type VARCHAR(50) NOT NULL,
                    value FLOAT NOT NULL,
                    improvement_rate FLOAT DEFAULT 0,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (id)
                )
            """),
            ('sub_admin_roles', """
                CREATE TABLE sub_admin_roles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    role_name VARCHAR(50) NOT NULL,
                    permissions TEXT,
                    assigned_by INTEGER NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (id),
                    FOREIGN KEY (assigned_by) REFERENCES users (id)
                )
            """),
            ('system_health', """
                CREATE TABLE system_health (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    component VARCHAR(50) NOT NULL,
                    status VARCHAR(20) DEFAULT 'healthy',
                    metrics TEXT,
                    last_checked DATETIME DEFAULT CURRENT_TIMESTAMP,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """),
            ('backup_schedules', """
                CREATE TABLE backup_schedules (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name VARCHAR(100) NOT NULL,
                    frequency VARCHAR(20) DEFAULT 'daily',
                    backup_type VARCHAR(20) DEFAULT 'full',
                    retention_days INTEGER DEFAULT 30,
                    is_active BOOLEAN DEFAULT 1,
                    last_run DATETIME,
                    next_run DATETIME,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """),
            ('feature_rollouts', """
                CREATE TABLE feature_rollouts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    feature_name VARCHAR(100) NOT NULL,
                    description TEXT,
                    rollout_percentage FLOAT DEFAULT 0,
                    target_users TEXT,
                    is_active BOOLEAN DEFAULT 0,
                    created_by INTEGER NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (created_by) REFERENCES users (id)
                )
            """),
            ('impact_counters', """
                CREATE TABLE impact_counters (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    metric_name VARCHAR(50) NOT NULL,
                    value BIGINT DEFAULT 0,
                    last_updated DATETIME DEFAULT CURRENT_TIMESTAMP,
                    update_frequency VARCHAR(20) DEFAULT 'realtime'
                )
            """)
        ]

        for table_name, create_sql in new_tables:
            if table_name not in inspector.get_table_names():
                print(f" Creating {table_name} table...")
                with db.engine.connect() as conn:
                    conn.execute(db.text(create_sql))
                    conn.commit()
                print(f" {table_name} table created successfully!")

    except Exception as e:
        print(f"Note: Schema check - {e}")


# ===================== NEW FEATURE TEMPLATES =====================

admin_iot_devices_template = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>IoT Device Management - EcoPulse Admin Pannel</title>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.0/font/bootstrap-icons.css">
    <style>
        body { padding-top: 60px; background: #f5f5f5; }
        .navbar { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); }
        .card { box-shadow: 0 2px 8px rgba(0,0,0,0.1); border: none; margin-bottom: 20px; }
        .device-status { padding: 15px; border-radius: 8px; }
        .status-pending { background: #fff3cd; }
        .status-active { background: #d4edda; }
        .status-inactive { background: #f8d7da; }
        .badge-status { font-size: 12px; padding: 6px 12px; }
        .device-info { font-size: 14px; color: #666; }
        .action-buttons { gap: 8px; }
        .modal-header { background: #667eea; color: white; }
    </style>
</head>
<body>
    <nav class="navbar navbar-dark sticky-top">
        <div class="container">
            <span class="navbar-brand"><i class="bi bi-router"></i> IoT Device Management</span>
            <a href="{{ url_for('admin_financial') }}" class="btn btn-light btn-sm">Back to Dashboard</a>
        </div>
    </nav>

    <div class="container mt-4">
        <div class="row mb-4">
            <div class="col-md-4">
                <div class="card">
                    <div class="card-body">
                        <h6 class="card-title">Pending Devices</h6>
                        <h3 class="card-text text-warning">{{ pending_count }}</h3>
                        <small>Awaiting approval</small>
                    </div>
                </div>
            </div>
            <div class="col-md-4">
                <div class="card">
                    <div class="card-body">
                        <h6 class="card-title">Active Devices</h6>
                        <h3 class="card-text text-success">{{ active_count }}</h3>
                        <small>Actively collecting data</small>
                    </div>
                </div>
            </div>
            <div class="col-md-4">
                <div class="card">
                    <div class="card-body">
                        <h6 class="card-title">Total Devices</h6>
                        <h3 class="card-text text-info">{{ registrations|length }}</h3>
                        <small>All registrations</small>
                    </div>
                </div>
            </div>
        </div>

        <div class="card">
            <div class="card-header">
                <h5 class="mb-0"><i class="bi bi-router-fill"></i> IoT Device Registrations</h5>
            </div>
            <div class="card-body">
                <div class="table-responsive">
                    <table class="table table-hover">
                        <thead class="table-light">
                            <tr>
                                <th>Device Name</th>
                                <th>User</th>
                                <th>Serial #</th>
                                <th>MAC Address</th>
                                <th>Status</th>
                                <th>Last Reading</th>
                                <th>Actions</th>
                            </tr>
                        </thead>
                        <tbody>
                            {% for reg in registrations %}
                            <tr>
                                <td><strong>{{ reg.device.name }}</strong></td>
                                <td>{{ reg.user.username }}</td>
                                <td><code>{{ reg.serial_number or 'N/A' }}</code></td>
                                <td><code>{{ reg.mac_address or 'N/A' }}</code></td>
                                <td>
                                    {% if reg.status == 'pending' %}
                                        <span class="badge bg-warning">Pending</span>
                                    {% elif reg.status == 'active' %}
                                        <span class="badge bg-success">Active</span>
                                    {% else %}
                                        <span class="badge bg-danger">{{ reg.status }}</span>
                                    {% endif %}
                                </td>
                                <td>{{ reg.last_data_received.strftime('%Y-%m-%d %H:%M') if reg.last_data_received else 'N/A' }}</td>
                                <td>
                                    {% if reg.status == 'pending' %}
                                        <form method="POST" action="/admin/approve_device/{{ reg.device_id }}" style="display:inline;">
                                            <button type="submit" class="btn btn-sm btn-success">Approve</button>
                                        </form>
                                    {% endif %}
                                    <a href="#" class="btn btn-sm btn-info" onclick="showDeviceDetails({{ reg.id }})">Details</a>
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
        function showDeviceDetails(regId) {
            fetch(`/api/admin/iot-devices/\\${regId}`)
                .then(r => r.json())
                .then(data => {
                    alert(`Device: \\${data.device_name}\\nAPI Key: \\${data.api_key}\\nStatus: \\${data.status}`);
                });
        }
    </script>
</body>
</html>
"""

admin_user_registrations_template = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>User Registrations - EcoPulse Admin</title>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.0/font/bootstrap-icons.css">
    <style>
        body { padding-top: 60px; background: #f5f5f5; }
        .navbar { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); }
        .card { box-shadow: 0 2px 8px rgba(0,0,0,0.1); border: none; margin-bottom: 20px; }
        .request-card { padding: 15px; border-left: 4px solid #667eea; }
        .user-type-badge { font-size: 11px; padding: 4px 8px; }
        .form-section { background: white; padding: 15px; border-radius: 8px; margin-bottom: 15px; }
        .modal-header { background: #667eea; color: white; }
    </style>
</head>
<body>
    <nav class="navbar navbar-dark sticky-top">
        <div class="container">
            <span class="navbar-brand"><i class="bi bi-person-check"></i> User Registration Requests</span>
            <a href="{{ url_for('admin_financial') }}" class="btn btn-light btn-sm">Back to Dashboard</a>
        </div>
    </nav>

    <div class="container mt-4">
        <div class="row mb-4">
            <div class="col-md-4">
                <div class="card">
                    <div class="card-body">
                        <h6 class="card-title">Pending Requests</h6>
                        <h3 class="card-text text-warning">{{ pending_requests|length }}</h3>
                        <small>Awaiting your review</small>
                    </div>
                </div>
            </div>
            <div class="col-md-4">
                <div class="card">
                    <div class="card-body">
                        <h6 class="card-title">Approved</h6>
                        <h3 class="card-text text-success">{{ approved_count }}</h3>
                        <small>Accounts created</small>
                    </div>
                </div>
            </div>
            <div class="col-md-4">
                <div class="card">
                    <div class="card-body">
                        <h6 class="card-title">Rejected</h6>
                        <h3 class="card-text text-danger">{{ rejected_count }}</h3>
                        <small>Not approved</small>
                    </div>
                </div>
            </div>
        </div>

        <div class="card">
            <div class="card-header">
                <h5 class="mb-0"><i class="bi bi-inbox"></i> Pending Registrations</h5>
            </div>
            <div class="card-body">
                {% if pending_requests %}
                    {% for req in pending_requests %}
                    <div class="request-card">
                        <div class="row align-items-center">
                            <div class="col-md-3">
                                <strong>{{ req.first_name or req.username }}</strong><br>
                                <small>{{ req.email }}</small><br>
                                <span class="badge bg-primary user-type-badge">{{ req.user_type }}</span>
                            </div>
                            <div class="col-md-3">
                                {% if req.user_type == 'business_owner' %}
                                    <strong>{{ req.business_name }}</strong><br>
                                    <small>{{ req.business_type or 'Not specified' }}</small>
                                {% else %}
                                    <strong>Home Owner</strong><br>
                                    <small>{{ req.meter_number or 'Pending' }}</small>
                                {% endif %}
                            </div>
                            <div class="col-md-3">
                                <small>Submitted: {{ req.submission_date.strftime('%Y-%m-%d %H:%M') }}</small><br>
                                <small>Role: <code>{{ req.requested_role }}</code></small>
                            </div>
                            <div class="col-md-3 text-end">
                                <button class="btn btn-sm btn-success" onclick="approveRequest({{ req.id }})">
                                    <i class="bi bi-check-circle"></i> Approve
                                </button>
                                <button class="btn btn-sm btn-danger" onclick="rejectRequest({{ req.id }})">
                                    <i class="bi bi-x-circle"></i> Reject
                                </button>
                            </div>
                        </div>
                    </div>
                    {% endfor %}
                {% else %}
                    <div class="alert alert-info">No pending registration requests.</div>
                {% endif %}
            </div>
        </div>
    </div>

    <!-- Rejection Modal -->
    <div class="modal fade" id="rejectModal" tabindex="-1">
        <div class="modal-dialog">
            <div class="modal-content">
                <div class="modal-header">
                    <h5 class="modal-title">Reject Registration</h5>
                    <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                </div>
                <div class="modal-body">
                    <label>Reason for rejection:</label>
                    <textarea id="rejectReason" class="form-control" rows="3"></textarea>
                </div>
                <div class="modal-footer">
                    <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancel</button>
                    <button type="button" class="btn btn-danger" onclick="submitReject()">Reject</button>
                </div>
            </div>
        </div>
    </div>

    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script>
    <script>
        let currentRequestId = null;

        function approveRequest(requestId) {
            if (confirm('Approve this registration request?')) {
                fetch(`/api/admin/user-registrations/\\${requestId}/approve`, { method: 'POST' })
                    .then(r => r.json())
                    .then(data => {
                        if (data.success) {
                            alert(`User approved!\\nTemporary Password: \\${data.temporary_password}`);
                            location.reload();
                        } else {
                            alert('Error: ' + data.error);
                        }
                    });
            }
        }

        function rejectRequest(requestId) {
            currentRequestId = requestId;
            new bootstrap.Modal(document.getElementById('rejectModal')).show();
        }

        function submitReject() {
            const reason = document.getElementById('rejectReason').value;
            fetch(`/api/admin/user-registrations/\\${currentRequestId}/reject`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ reason: reason })
            })
            .then(r => r.json())
            .then(data => {
                if (data.success) {
                    alert('Registration rejected.');
                    location.reload();
                } else {
                    alert('Error: ' + data.error);
                }
            });
        }
    </script>
</body>
</html>
"""

goals_template = """
{% extends "base.html" %}

{% block title %}Energy Goals - EcoPulse{% endblock %}

{% block content %}
<div class="container mt-4">
    <div class="row">
        <div class="col-md-8">
            <h1 class="text-white mb-4"><i class="bi bi-target"></i> Energy Goal Tracker</h1>

            {% with messages = get_flashed_messages(with_categories=true) %}
                {% if messages %}
                    {% for category, message in messages %}
                        <div class="alert alert-{{ 'success' if category == 'success' else 'danger' }} alert-dismissible fade show">
                            {{ message }}
                            <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
                        </div>
                    {% endfor %}
                {% endif %}
            {% endwith %}

            <div class="card mb-4">
                <div class="card-header bg-primary text-white">
                    <h5 class="mb-0"><i class="bi bi-plus-circle"></i> Create New Goal</h5>
                </div>
                <div class="card-body">
                    <a href="{{ url_for('create_goal') }}" class="btn btn-primary">
                        <i class="bi bi-plus"></i> Set New Energy Goal
                    </a>
                </div>
            </div>

            <div class="row">
                {% for goal in goals %}
                <div class="col-md-6 mb-4">
                    <div class="card h-100">
                        <div class="card-header bg-{{ 'success' if goal.status == 'completed' else 'warning' if goal.status == 'active' else 'danger' }} text-white">
                            <h6 class="mb-0">
                                <i class="bi bi-target"></i>
                                {{ goal.goal_type.replace('_', ' ').title() }}
                                {% if goal.status == 'completed' %}
                                    <i class="bi bi-check-circle float-end"></i>
                                {% endif %}
                            </h6>
                        </div>
                        <div class="card-body">
                            <div class="mb-3">
                                <div class="progress mb-2">
                                    <div class="progress-bar bg-{{ 'success' if goal.status == 'completed' else 'primary' }}"
                                         style="width: {{ (goal.current_value / goal.target_value * 100) if goal.target_value > 0 else 0 }}%">
                                    </div>
                                </div>
                                <small class="text-muted">
                                    {{ "%.1f"|format(goal.current_value) }} / {{ "%.1f"|format(goal.target_value) }}
                                    {{ 'kWh' if goal.goal_type == 'monthly_savings' else '%' }}
                                </small>
                            </div>
                            <p class="text-muted small">
                                <i class="bi bi-calendar"></i> Ends: {{ goal.end_date.strftime('%B %d, %Y') }}<br>
                                <i class="bi bi-clock"></i> Status: {{ goal.status.title() }}
                            </p>
                        </div>
                    </div>
                </div>
                {% endfor %}
            </div>
        </div>

        <div class="col-md-4">
            <div class="card">
                <div class="card-header bg-info text-white">
                    <h6 class="mb-0"><i class="bi bi-info-circle"></i> Goal Tips</h6>
                </div>
                <div class="card-body">
                    <ul class="list-unstyled">
                        <li class="mb-2"><i class="bi bi-lightbulb text-warning"></i> Set realistic targets based on your usage patterns</li>
                        <li class="mb-2"><i class="bi bi-lightbulb text-warning"></i> Track progress regularly to stay motivated</li>
                        <li class="mb-2"><i class="bi bi-lightbulb text-warning"></i> Combine multiple goals for maximum impact</li>
                        <li class="mb-2"><i class="bi bi-lightbulb text-warning"></i> Celebrate achievements and share with the community</li>
                    </ul>
                </div>
            </div>
        </div>
    </div>
</div>
{% endblock %}
"""

create_goal_template = """
{% extends "base.html" %}

{% block title %}Create Goal - EcoPulse{% endblock %}

{% block content %}
<div class="container mt-4">
    <div class="row justify-content-center">
        <div class="col-md-8">
            <div class="card">
                <div class="card-header bg-primary text-white">
                    <h4 class="mb-0"><i class="bi bi-plus-circle"></i> Create New Energy Goal</h4>
                </div>
                <div class="card-body">
                    <form method="POST">
                        <div class="mb-3">
                            <label for="goal_type" class="form-label">Goal Type</label>
                            <select class="form-select" id="goal_type" name="goal_type" required>
                                <option value="monthly_savings">Monthly Energy Savings (kWh)</option>
                                <option value="annual_reduction">Annual Reduction (%)</option>
                            </select>
                        </div>

                        <div class="mb-3">
                            <label for="target_value" class="form-label">Target Value</label>
                            <input type="number" step="0.1" class="form-control" id="target_value" name="target_value" required>
                            <div class="form-text">Enter your target energy savings or reduction percentage</div>
                        </div>

                        <div class="mb-3">
                            <label for="end_date" class="form-label">Target Date</label>
                            <input type="date" class="form-control" id="end_date" name="end_date" required>
                        </div>

                        <div class="d-grid gap-2 d-md-flex justify-content-md-end">
                            <a href="{{ url_for('goals') }}" class="btn btn-secondary me-md-2">Cancel</a>
                            <button type="submit" class="btn btn-primary">Create Goal</button>
                        </div>
                    </form>
                </div>
            </div>
        </div>
    </div>
</div>
{% endblock %}
"""

forum_template = """
{% extends "base.html" %}

{% block title %}Community Forum - EcoPulse{% endblock %}

{% block content %}
<div class="container mt-4">
    <div class="row">
        <div class="col-md-8">
            <h1 class="text-white mb-4"><i class="bi bi-chat-dots"></i> Community Forum</h1>

            {% with messages = get_flashed_messages(with_categories=true) %}
                {% if messages %}
                    {% for category, message in messages %}
                        <div class="alert alert-{{ 'success' if category == 'success' else 'danger' }} alert-dismissible fade show">
                            {{ message }}
                            <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
                        </div>
                    {% endfor %}
                {% endif %}
            {% endwith %}

            <div class="card mb-4">
                <div class="card-header bg-primary text-white">
                    <h5 class="mb-0"><i class="bi bi-plus-circle"></i> Start New Discussion</h5>
                </div>
                <div class="card-body">
                    <a href="{{ url_for('create_post') }}" class="btn btn-primary">
                        <i class="bi bi-pencil-square"></i> Create Post
                    </a>
                </div>
            </div>

            <div class="mb-3">
                <div class="btn-group" role="group">
                    <a href="{{ url_for('forum', category='all') }}" class="btn btn-outline-primary {{ 'active' if category == 'all' else '' }}">All</a>
                    <a href="{{ url_for('forum', category='tips') }}" class="btn btn-outline-primary {{ 'active' if category == 'tips' else '' }}">Tips</a>
                    <a href="{{ url_for('forum', category='questions') }}" class="btn btn-outline-primary {{ 'active' if category == 'questions' else '' }}">Questions</a>
                    <a href="{{ url_for('forum', category='experiences') }}" class="btn btn-outline-primary {{ 'active' if category == 'experiences' else '' }}">Experiences</a>
                </div>
            </div>

            {% for post in posts.items %}
            <div class="card mb-3">
                <div class="card-header">
                    <div class="d-flex justify-content-between align-items-start">
                        <div>
                            <h5 class="mb-1">
                                {% if post.is_pinned %}<i class="bi bi-pin-angle text-warning"></i>{% endif %}
                                <a href="{{ url_for('view_post', post_id=post.id) }}" class="text-decoration-none">{{ post.title }}</a>
                            </h5>
                            <small class="text-muted">
                                By {{ post.user.username }} in {{ post.category.title() }} •
                                {{ post.created_at.strftime('%B %d, %Y') }}
                            </small>
                        </div>
                        <div class="text-end">
                            <div class="text-muted small">
                                <i class="bi bi-heart"></i> {{ post.likes }} •
                                <i class="bi bi-chat"></i> {{ post.replies_count }}
                            </div>
                        </div>
                    </div>
                </div>
                <div class="card-body">
                    <p class="mb-0">{{ post.content[:200] }}{% if post.content|length > 200 %}...{% endif %}</p>
                </div>
            </div>
            {% endfor %}

            {% if posts.pages > 1 %}
            <nav aria-label="Forum pagination">
                <ul class="pagination justify-content-center">
                    {% if posts.has_prev %}
                        <li class="page-item">
                            <a class="page-link" href="{{ url_for('forum', page=posts.prev_num, category=category) }}">Previous</a>
                        </li>
                    {% endif %}

                    {% for page_num in posts.iter_pages() %}
                        {% if page_num %}
                            <li class="page-item {{ 'active' if page_num == posts.page else '' }}">
                                <a class="page-link" href="{{ url_for('forum', page=page_num, category=category) }}">{{ page_num }}</a>
                            </li>
                        {% else %}
                            <li class="page-item disabled"><span class="page-link">...</span></li>
                        {% endif %}
                    {% endfor %}

                    {% if posts.has_next %}
                        <li class="page-item">
                            <a class="page-link" href="{{ url_for('forum', page=posts.next_num, category=category) }}">Next</a>
                        </li>
                    {% endif %}
                </ul>
            </nav>
            {% endif %}
        </div>

        <div class="col-md-4">
            <div class="card mb-4">
                <div class="card-header bg-info text-white">
                    <h6 class="mb-0"><i class="bi bi-info-circle"></i> Forum Guidelines</h6>
                </div>
                <div class="card-body">
                    <ul class="list-unstyled small">
                        <li class="mb-2"><i class="bi bi-check-circle text-success"></i> Be respectful and constructive</li>
                        <li class="mb-2"><i class="bi bi-check-circle text-success"></i> Share your energy-saving experiences</li>
                        <li class="mb-2"><i class="bi bi-check-circle text-success"></i> Ask questions and help others</li>
                        <li class="mb-2"><i class="bi bi-check-circle text-success"></i> Keep discussions on-topic</li>
                    </ul>
                </div>
            </div>

            <div class="card">
                <div class="card-header bg-success text-white">
                    <h6 class="mb-0"><i class="bi bi-trophy"></i> Top Contributors</h6>
                </div>
                <div class="card-body">
                    <p class="text-muted small">Coming soon...</p>
                </div>
            </div>
        </div>
    </div>
</div>
{% endblock %}
"""

create_post_template = """
{% extends "base.html" %}

{% block title %}Create Post - EcoPulse{% endblock %}

{% block content %}
<div class="container mt-4">
    <div class="row justify-content-center">
        <div class="col-md-8">
            <div class="card">
                <div class="card-header bg-primary text-white">
                    <h4 class="mb-0"><i class="bi bi-pencil-square"></i> Create New Post</h4>
                </div>
                <div class="card-body">
                    <form method="POST">
                        <div class="mb-3">
                            <label for="title" class="form-label">Title</label>
                            <input type="text" class="form-control" id="title" name="title" required maxlength="200">
                        </div>

                        <div class="mb-3">
                            <label for="category" class="form-label">Category</label>
                            <select class="form-select" id="category" name="category" required>
                                <option value="general">General Discussion</option>
                                <option value="tips">Energy Saving Tips</option>
                                <option value="questions">Questions</option>
                                <option value="experiences">Personal Experiences</option>
                            </select>
                        </div>

                        <div class="mb-3">
                            <label for="content" class="form-label">Content</label>
                            <textarea class="form-control" id="content" name="content" rows="8" required></textarea>
                        </div>

                        <div class="d-grid gap-2 d-md-flex justify-content-md-end">
                            <a href="{{ url_for('forum') }}" class="btn btn-secondary me-md-2">Cancel</a>
                            <button type="submit" class="btn btn-primary">Create Post</button>
                        </div>
                    </form>
                </div>
            </div>
        </div>
    </div>
</div>
{% endblock %}
"""

view_post_template = """
{% extends "base.html" %}

{% block title %}{{ post.title }} - EcoPulse{% endblock %}

{% block content %}
<div class="container mt-4">
    <div class="row">
        <div class="col-md-8">
            <nav aria-label="breadcrumb">
                <ol class="breadcrumb">
                    <li class="breadcrumb-item"><a href="{{ url_for('forum') }}">Forum</a></li>
                    <li class="breadcrumb-item active">{{ post.category.title() }}</li>
                </ol>
            </nav>

            <div class="card mb-4">
                <div class="card-header">
                    <div class="d-flex justify-content-between align-items-start">
                        <div>
                            <h4 class="mb-1">
                                {% if post.is_pinned %}<i class="bi bi-pin-angle text-warning"></i>{% endif %}
                                {{ post.title }}
                            </h4>
                            <small class="text-muted">
                                By {{ post.user.username }} • {{ post.created_at.strftime('%B %d, %Y at %I:%M %p') }}
                            </small>
                        </div>
                        <div class="text-end">
                            <span class="badge bg-primary">{{ post.category.title() }}</span>
                        </div>
                    </div>
                </div>
                <div class="card-body">
                    <p class="mb-0">{{ post.content }}</p>
                </div>
                <div class="card-footer text-muted">
                    <i class="bi bi-heart"></i> {{ post.likes }} likes •
                    <i class="bi bi-chat"></i> {{ post.replies_count }} replies
                </div>
            </div>

            <div class="card mb-4">
                <div class="card-header bg-light">
                    <h5 class="mb-0"><i class="bi bi-chat-dots"></i> Replies</h5>
                </div>
                <div class="card-body">
                    {% for reply in replies %}
                    <div class="border-bottom pb-3 mb-3">
                        <div class="d-flex justify-content-between align-items-start mb-2">
                            <strong>{{ reply.user.username }}</strong>
                            <small class="text-muted">{{ reply.created_at.strftime('%B %d, %Y at %I:%M %p') }}</small>
                        </div>
                        <p class="mb-1">{{ reply.content }}</p>
                        <small class="text-muted">
                            <i class="bi bi-heart"></i> {{ reply.likes }} likes
                        </small>
                    </div>
                    {% endfor %}

                    {% if not replies %}
                    <p class="text-muted mb-0">No replies yet. Be the first to respond!</p>
                    {% endif %}
                </div>
            </div>

            <div class="card">
                <div class="card-header bg-primary text-white">
                    <h5 class="mb-0"><i class="bi bi-reply"></i> Add Reply</h5>
                </div>
                <div class="card-body">
                    <form method="POST" action="{{ url_for('reply_to_post', post_id=post.id) }}">
                        <div class="mb-3">
                            <label for="content" class="form-label">Your Reply</label>
                            <textarea class="form-control" id="content" name="content" rows="4" required></textarea>
                        </div>
                        <button type="submit" class="btn btn-primary">Post Reply</button>
                    </form>
                </div>
            </div>
        </div>

        <div class="col-md-4">
            <div class="card">
                <div class="card-header bg-info text-white">
                    <h6 class="mb-0"><i class="bi bi-info-circle"></i> Posting Tips</h6>
                </div>
                <div class="card-body">
                    <ul class="list-unstyled small">
                        <li class="mb-2"><i class="bi bi-check-circle text-success"></i> Stay on topic</li>
                        <li class="mb-2"><i class="bi bi-check-circle text-success"></i> Be respectful</li>
                        <li class="mb-2"><i class="bi bi-check-circle text-success"></i> Share your experiences</li>
                        <li class="mb-2"><i class="bi bi-check-circle text-success"></i> Ask for clarification if needed</li>
                    </ul>
                </div>
            </div>
        </div>
    </div>
</div>
{% endblock %}
"""

chat_template = """
{% extends "base.html" %}

{% block title %}AI Chat Assistant - EcoPulse{% endblock %}

{% block content %}
<div class="container mt-4">
    <div class="row justify-content-center">
        <div class="col-md-8">
            <div class="card">
                <div class="card-header bg-primary text-white">
                    <h4 class="mb-0"><i class="bi bi-robot"></i> AI Energy Assistant</h4>
                </div>
                <div class="card-body">
                    <div id="chat-messages" class="mb-3" style="height: 400px; overflow-y: auto; border: 1px solid #dee2e6; padding: 10px; border-radius: 5px;">
                        <div class="message bot-message mb-3">
                            <div class="d-flex">
                                <div class="bg-light rounded p-2 me-2">
                                    <i class="bi bi-robot"></i>
                                </div>
                                <div class="flex-grow-1">
                                    <strong>EcoBot</strong>
                                    <p class="mb-0">Hello! I'm your AI energy assistant. How can I help you save energy today?</p>
                                    <small class="text-muted">Just now</small>
                                </div>
                            </div>
                        </div>
                    </div>

                    <div class="input-group">
                        <input type="text" id="message-input" class="form-control" placeholder="Ask me about energy saving tips...">
                        <button class="btn btn-primary" id="send-button">
                            <i class="bi bi-send"></i> Send
                        </button>
                    </div>
                </div>
            </div>
        </div>
    </div>
</div>

<script>
document.addEventListener('DOMContentLoaded', function() {
    const messageInput = document.getElementById('message-input');
    const sendButton = document.getElementById('send-button');
    const chatMessages = document.getElementById('chat-messages');

    function addMessage(content, isUser = false) {
        const messageDiv = document.createElement('div');
        messageDiv.className = `message ${isUser ? 'user-message' : 'bot-message'} mb-3`;

        const messageHTML = `
            <div class="d-flex ${isUser ? 'justify-content-end' : ''}">
                ${!isUser ? '<div class="bg-light rounded p-2 me-2"><i class="bi bi-robot"></i></div>' : ''}
                <div class="flex-grow-1 ${isUser ? 'text-end' : ''}">
                    <strong>${isUser ? 'You' : 'EcoBot'}</strong>
                    <p class="mb-0">${content}</p>
                    <small class="text-muted">Just now</small>
                </div>
                ${isUser ? '<div class="bg-primary text-white rounded p-2 ms-2"><i class="bi bi-person"></i></div>' : ''}
            </div>
        `;

        messageDiv.innerHTML = messageHTML;
        chatMessages.appendChild(messageDiv);
        chatMessages.scrollTop = chatMessages.scrollHeight;
    }

    function sendMessage() {
        const message = messageInput.value.trim();
        if (!message) return;

        addMessage(message, true);
        messageInput.value = '';

        // Send to server
        fetch('/api/chat/message', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ message: message })
        })
        .then(response => response.json())
        .then(data => {
            addMessage(data.response, false);
        })
        .catch(error => {
            addMessage('Sorry, I encountered an error. Please try again.', false);
        });
    }

    sendButton.addEventListener('click', sendMessage);
    messageInput.addEventListener('keypress', function(e) {
        if (e.key === 'Enter') {
            sendMessage();
        }
    });
});
</script>
{% endblock %}
"""

# Examiner templates
rubrics_template = """
{% extends "base.html" %}

{% block title %}Rubrics Management - EcoPulse{% endblock %}

{% block content %}
<div class="container mt-4">
    <h1 class="text-white mb-4"><i class="bi bi-clipboard-check"></i> Rubrics Management</h1>

    {% with messages = get_flashed_messages(with_categories=true) %}
        {% if messages %}
            {% for category, message in messages %}
                <div class="alert alert-{{ 'success' if category == 'success' else 'danger' }} alert-dismissible fade show">
                    {{ message }}
                    <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
                </div>
            {% endfor %}
        {% endif %}
    {% endwith %}

    <div class="card mb-4">
        <div class="card-header bg-primary text-white">
            <h5 class="mb-0"><i class="bi bi-plus-circle"></i> Create New Rubric</h5>
        </div>
        <div class="card-body">
            <a href="{{ url_for('create_rubric') }}" class="btn btn-primary">
                <i class="bi bi-plus"></i> Create Rubric
            </a>
        </div>
    </div>

    <div class="row">
        {% for rubric in rubrics %}
        <div class="col-md-6 mb-4">
            <div class="card h-100">
                <div class="card-header bg-info text-white">
                    <h6 class="mb-0"><i class="bi bi-clipboard-check"></i> {{ rubric.name }}</h6>
                </div>
                <div class="card-body">
                    <p class="text-muted">{{ rubric.description or 'No description' }}</p>
                    <small class="text-muted">
                        Created: {{ rubric.created_at.strftime('%B %d, %Y') }}
                    </small>
                </div>
                <div class="card-footer">
                    <button class="btn btn-sm btn-outline-primary">Edit</button>
                    <button class="btn btn-sm btn-outline-danger">Delete</button>
                </div>
            </div>
        </div>
        {% endfor %}
    </div>
</div>
{% endblock %}
"""

create_rubric_template = """
{% extends "base.html" %}

{% block title %}Create Rubric - EcoPulse{% endblock %}

{% block content %}
<div class="container mt-4">
    <div class="row justify-content-center">
        <div class="col-md-8">
            <div class="card">
                <div class="card-header bg-primary text-white">
                    <h4 class="mb-0"><i class="bi bi-clipboard-check"></i> Create New Rubric</h4>
                </div>
                <div class="card-body">
                    <form method="POST">
                        <div class="mb-3">
                            <label for="name" class="form-label">Rubric Name</label>
                            <input type="text" class="form-control" id="name" name="name" required>
                        </div>

                        <div class="mb-3">
                            <label for="description" class="form-label">Description</label>
                            <textarea class="form-control" id="description" name="description" rows="3"></textarea>
                        </div>

                        <div class="mb-3">
                            <label for="criteria" class="form-label">Criteria (JSON format)</label>
                            <textarea class="form-control" id="criteria" name="criteria" rows="6" placeholder='{"efficiency": {"weight": 0.4, "levels": ["Poor", "Good", "Excellent"]}, "accuracy": {"weight": 0.6, "levels": ["Poor", "Good", "Excellent"]}}'></textarea>
                            <div class="form-text">Enter criteria in JSON format with weights and evaluation levels</div>
                        </div>

                        <div class="d-grid gap-2 d-md-flex justify-content-md-end">
                            <a href="{{ url_for('rubrics') }}" class="btn btn-secondary me-md-2">Cancel</a>
                            <button type="submit" class="btn btn-primary">Create Rubric</button>
                        </div>
                    </form>
                </div>
            </div>
        </div>
    </div>
</div>
{% endblock %}
"""

templates_template = """
{% extends "base.html" %}

{% block title %}Comment Templates - EcoPulse{% endblock %}

{% block content %}
<div class="container mt-4">
    <h1 class="text-white mb-4"><i class="bi bi-file-text"></i> Comment Templates</h1>

    {% with messages = get_flashed_messages(with_categories=true) %}
        {% if messages %}
            {% for category, message in messages %}
                <div class="alert alert-{{ 'success' if category == 'success' else 'danger' }} alert-dismissible fade show">
                    {{ message }}
                    <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
                </div>
            {% endfor %}
        {% endif %}
    {% endwith %}

    <div class="card mb-4">
        <div class="card-header bg-primary text-white">
            <h5 class="mb-0"><i class="bi bi-plus-circle"></i> Create New Template</h5>
        </div>
        <div class="card-body">
            <a href="{{ url_for('create_template') }}" class="btn btn-primary">
                <i class="bi bi-plus"></i> Create Template
            </a>
        </div>
    </div>

    <div class="row">
        {% for template in templates %}
        <div class="col-md-6 mb-4">
            <div class="card h-100">
                <div class="card-header bg-success text-white">
                    <h6 class="mb-0"><i class="bi bi-file-text"></i> {{ template.name }}</h6>
                </div>
                <div class="card-body">
                    <p class="text-muted">{{ template.content[:100] }}{% if template.content|length > 100 %}...{% endif %}</p>
                    <span class="badge bg-secondary">{{ template.category.title() }}</span>
                    <small class="text-muted d-block mt-2">
                        Created: {{ template.created_at.strftime('%B %d, %Y') }}
                    </small>
                </div>
                <div class="card-footer">
                    <button class="btn btn-sm btn-outline-primary">Edit</button>
                    <button class="btn btn-sm btn-outline-danger">Delete</button>
                </div>
            </div>
        </div>
        {% endfor %}
    </div>
</div>
{% endblock %}
"""

create_template_template = """
{% extends "base.html" %}

{% block title %}Create Template - EcoPulse{% endblock %}

{% block content %}
<div class="container mt-4">
    <div class="row justify-content-center">
        <div class="col-md-8">
            <div class="card">
                <div class="card-header bg-primary text-white">
                    <h4 class="mb-0"><i class="bi bi-file-text"></i> Create Comment Template</h4>
                </div>
                <div class="card-body">
                    <form method="POST">
                        <div class="mb-3">
                            <label for="name" class="form-label">Template Name</label>
                            <input type="text" class="form-control" id="name" name="name" required>
                        </div>

                        <div class="mb-3">
                            <label for="category" class="form-label">Category</label>
                            <select class="form-select" id="category" name="category" required>
                                <option value="general">General</option>
                                <option value="positive">Positive Feedback</option>
                                <option value="improvement">Areas for Improvement</option>
                                <option value="technical">Technical Comments</option>
                            </select>
                        </div>

                        <div class="mb-3">
                            <label for="content" class="form-label">Template Content</label>
                            <textarea class="form-control" id="content" name="content" rows="8" required></textarea>
                            <div class="form-text">Use placeholders like {customer_name}, {reading_value}, etc.</div>
                        </div>

                        <div class="d-grid gap-2 d-md-flex justify-content-md-end">
                            <a href="{{ url_for('comment_templates') }}" class="btn btn-secondary me-md-2">Cancel</a>
                            <button type="submit" class="btn btn-primary">Create Template</button>
                        </div>
                    </form>
                </div>
            </div>
        </div>
    </div>
</div>
{% endblock %}
"""

analytics_template = """
{% extends "base.html" %}

{% block title %}Performance Analytics - EcoPulse{% endblock %}

{% block content %}
<div class="container mt-4">
    <h1 class="text-white mb-4"><i class="bi bi-graph-up"></i> Performance Analytics</h1>

    <div class="row">
        <div class="col-md-12">
            <div class="card">
                <div class="card-header bg-info text-white">
                    <h5 class="mb-0"><i class="bi bi-bar-chart"></i> Customer Performance Metrics</h5>
                </div>
                <div class="card-body">
                    <div class="table-responsive">
                        <table class="table table-striped">
                            <thead>
                                <tr>
                                    <th>User</th>
                                    <th>Period</th>
                                    <th>Metric</th>
                                    <th>Value</th>
                                    <th>Improvement Rate</th>
                                    <th>Date</th>
                                </tr>
                            </thead>
                            <tbody>
                                {% for analytic in analytics %}
                                <tr>
                                    <td>{{ analytic.user.username }}</td>
                                    <td>{{ analytic.period.title() }}</td>
                                    <td>{{ analytic.metric_type.title() }}</td>
                                    <td>{{ "%.2f"|format(analytic.value) }}</td>
                                    <td>{{ "%.1f"|format(analytic.improvement_rate) }}%</td>
                                    <td>{{ analytic.created_at.strftime('%B %d, %Y') }}</td>
                                </tr>
                                {% endfor %}
                            </tbody>
                        </table>
                    </div>

                    {% if not analytics %}
                    <p class="text-muted text-center mt-4">No analytics data available yet.</p>
                    {% endif %}
                </div>
            </div>
        </div>
    </div>
</div>
{% endblock %}
"""

# Admin templates
sub_admins_template = """
{% extends "base.html" %}

{% block title %}Sub-Admin Management - EcoPulse{% endblock %}

{% block content %}
<div class="container mt-4">
    <h1 class="text-white mb-4"><i class="bi bi-shield-check"></i> Sub-Admin Roles Management</h1>

    {% with messages = get_flashed_messages(with_categories=true) %}
        {% if messages %}
            {% for category, message in messages %}
                <div class="alert alert-{{ 'success' if category == 'success' else 'danger' }} alert-dismissible fade show">
                    {{ message }}
                    <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
                </div>
            {% endfor %}
        {% endif %}
    {% endwith %}

    <div class="card mb-4">
        <div class="card-header bg-primary text-white">
            <h5 class="mb-0"><i class="bi bi-plus-circle"></i> Create New Sub-Admin Role</h5>
        </div>
        <div class="card-body">
            <a href="{{ url_for('create_sub_admin') }}" class="btn btn-primary">
                <i class="bi bi-plus"></i> Assign Sub-Admin Role
            </a>
        </div>
    </div>

    <div class="row">
        {% for role in sub_admin_roles %}
        <div class="col-md-6 mb-4">
            <div class="card h-100">
                <div class="card-header bg-warning text-white">
                    <h6 class="mb-0"><i class="bi bi-person-badge"></i> {{ role.role_name.title() }}</h6>
                </div>
                <div class="card-body">
                    <p class="mb-1"><strong>User:</strong> {{ role.user.username }}</p>
                    <p class="mb-1"><strong>Permissions:</strong> {{ role.permissions or 'None specified' }}</p>
                    <small class="text-muted">
                        Assigned: {{ role.created_at.strftime('%B %d, %Y') }}
                    </small>
                </div>
                <div class="card-footer">
                    <button class="btn btn-sm btn-outline-primary">Edit</button>
                    <button class="btn btn-sm btn-outline-danger">Remove</button>
                </div>
            </div>
        </div>
        {% endfor %}
    </div>
</div>
{% endblock %}
"""

create_sub_admin_template = """
{% extends "base.html" %}

{% block title %}Create Sub-Admin - EcoPulse{% endblock %}

{% block content %}
<div class="container mt-4">
    <div class="row justify-content-center">
        <div class="col-md-8">
            <div class="card">
                <div class="card-header bg-primary text-white">
                    <h4 class="mb-0"><i class="bi bi-shield-plus"></i> Assign Sub-Admin Role</h4>
                </div>
                <div class="card-body">
                    <form method="POST">
                        <div class="mb-3">
                            <label for="user_id" class="form-label">Select User</label>
                            <select class="form-select" id="user_id" name="user_id" required>
                                {% for user in users %}
                                <option value="{{ user.id }}">{{ user.username }} ({{ user.user_type }})</option>
                                {% endfor %}
                            </select>
                        </div>

                        <div class="mb-3">
                            <label for="role_name" class="form-label">Role Name</label>
                            <select class="form-select" id="role_name" name="role_name" required>
                                <option value="moderator">Forum Moderator</option>
                                <option value="support_admin">Support Admin</option>
                                <option value="content_admin">Content Admin</option>
                                <option value="analytics_admin">Analytics Admin</option>
                            </select>
                        </div>

                        <div class="mb-3">
                            <label for="permissions" class="form-label">Permissions (JSON format)</label>
                            <textarea class="form-control" id="permissions" name="permissions" rows="4" placeholder='{"forum": ["read", "moderate"], "reports": ["view"]}'></textarea>
                            <div class="form-text">Specify permissions in JSON format</div>
                        </div>

                        <div class="d-grid gap-2 d-md-flex justify-content-md-end">
                            <a href="{{ url_for('sub_admins') }}" class="btn btn-secondary me-md-2">Cancel</a>
                            <button type="submit" class="btn btn-primary">Assign Role</button>
                        </div>
                    </form>
                </div>
            </div>
        </div>
    </div>
</div>
{% endblock %}
"""

health_template = """
{% extends "base.html" %}

{% block title %}System Health - EcoPulse{% endblock %}

{% block content %}
<div class="container mt-4">
    <h1 class="text-white mb-4"><i class="bi bi-activity"></i> System Health Monitoring</h1>

    <div class="row">
        {% for check in health_checks %}
        <div class="col-md-6 mb-4">
            <div class="card h-100">
                <div class="card-header bg-{{ 'success' if check.status == 'healthy' else 'warning' if check.status == 'warning' else 'danger' }} text-white">
                    <h6 class="mb-0">
                        <i class="bi bi-{{ 'check-circle' if check.status == 'healthy' else 'exclamation-triangle' if check.status == 'warning' else 'x-circle' }}"></i>
                        {{ check.component.title() }}
                    </h6>
                </div>
                <div class="card-body">
                    <p class="mb-1"><strong>Status:</strong> {{ check.status.title() }}</p>
                    <p class="mb-1"><strong>Last Checked:</strong> {{ check.last_checked.strftime('%B %d, %Y %I:%M %p') }}</p>
                    {% if check.metrics %}
                    <div class="mt-3">
                        <h6>Metrics:</h6>
                        <pre class="bg-light p-2 rounded small">{{ check.metrics }}</pre>
                    </div>
                    {% endif %}
                </div>
            </div>
        </div>
        {% endfor %}
    </div>

    {% if not health_checks %}
    <div class="text-center mt-4">
        <p class="text-muted">No health checks available. System monitoring will be implemented soon.</p>
    </div>
    {% endif %}
</div>
{% endblock %}
"""

backups_template = """
{% extends "base.html" %}

{% block title %}Backup Schedules - EcoPulse{% endblock %}

{% block content %}
<div class="container mt-4">
    <h1 class="text-white mb-4"><i class="bi bi-cloud-upload"></i> Backup Schedule Management</h1>

    {% with messages = get_flashed_messages(with_categories=true) %}
        {% if messages %}
            {% for category, message in messages %}
                <div class="alert alert-{{ 'success' if category == 'success' else 'danger' }} alert-dismissible fade show">
                    {{ message }}
                    <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
                </div>
            {% endfor %}
        {% endif %}
    {% endwith %}

    <div class="card mb-4">
        <div class="card-header bg-primary text-white">
            <h5 class="mb-0"><i class="bi bi-plus-circle"></i> Create New Backup Schedule</h5>
        </div>
        <div class="card-body">
            <a href="{{ url_for('create_backup_schedule') }}" class="btn btn-primary">
                <i class="bi bi-plus"></i> Create Schedule
            </a>
        </div>
    </div>

    <div class="row">
        {% for schedule in schedules %}
        <div class="col-md-6 mb-4">
            <div class="card h-100">
                <div class="card-header bg-info text-white">
                    <h6 class="mb-0"><i class="bi bi-clock"></i> {{ schedule.name }}</h6>
                </div>
                <div class="card-body">
                    <p class="mb-1"><strong>Frequency:</strong> {{ schedule.frequency.title() }}</p>
                    <p class="mb-1"><strong>Type:</strong> {{ schedule.backup_type.title() }}</p>
                    <p class="mb-1"><strong>Retention:</strong> {{ schedule.retention_days }} days</p>
                    <p class="mb-1"><strong>Status:</strong>
                        <span class="badge bg-{{ 'success' if schedule.is_active else 'secondary' }}">
                            {{ 'Active' if schedule.is_active else 'Inactive' }}
                        </span>
                    </p>
                    {% if schedule.last_run %}
                    <small class="text-muted">
                        Last run: {{ schedule.last_run.strftime('%B %d, %Y %I:%M %p') }}
                    </small>
                    {% endif %}
                </div>
                <div class="card-footer">
                    <button class="btn btn-sm btn-outline-primary">Edit</button>
                    <button class="btn btn-sm btn-outline-danger">Delete</button>
                </div>
            </div>
        </div>
        {% endfor %}
    </div>
</div>
{% endblock %}
"""

create_backup_template = """
{% extends "base.html" %}

{% block title %}Create Backup Schedule - EcoPulse{% endblock %}

{% block content %}
<div class="container mt-4">
    <div class="row justify-content-center">
        <div class="col-md-8">
            <div class="card">
                <div class="card-header bg-primary text-white">
                    <h4 class="mb-0"><i class="bi bi-cloud-upload"></i> Create Backup Schedule</h4>
                </div>
                <div class="card-body">
                    <form method="POST">
                        <div class="mb-3">
                            <label for="name" class="form-label">Schedule Name</label>
                            <input type="text" class="form-control" id="name" name="name" required>
                        </div>

                        <div class="mb-3">
                            <label for="frequency" class="form-label">Backup Frequency</label>
                            <select class="form-select" id="frequency" name="frequency" required>
                                <option value="hourly">Hourly</option>
                                <option value="daily">Daily</option>
                                <option value="weekly">Weekly</option>
                            </select>
                        </div>

                        <div class="mb-3">
                            <label for="backup_type" class="form-label">Backup Type</label>
                            <select class="form-select" id="backup_type" name="backup_type" required>
                                <option value="full">Full Backup</option>
                                <option value="incremental">Incremental Backup</option>
                            </select>
                        </div>

                        <div class="mb-3">
                            <label for="retention_days" class="form-label">Retention Period (days)</label>
                            <input type="number" class="form-control" id="retention_days" name="retention_days" value="30" min="1" required>
                        </div>

                        <div class="d-grid gap-2 d-md-flex justify-content-md-end">
                            <a href="{{ url_for('backup_schedules') }}" class="btn btn-secondary me-md-2">Cancel</a>
                            <button type="submit" class="btn btn-primary">Create Schedule</button>
                        </div>
                    </form>
                </div>
            </div>
        </div>
    </div>
</div>
{% endblock %}
"""

rollouts_template = """
{% extends "base.html" %}

{% block title %}Feature Rollouts - EcoPulse{% endblock %}

{% block content %}
<div class="container mt-4">
    <h1 class="text-white mb-4"><i class="bi bi-rocket"></i> Feature Rollout Management</h1>

    {% with messages = get_flashed_messages(with_categories=true) %}
        {% if messages %}
            {% for category, message in messages %}
                <div class="alert alert-{{ 'success' if category == 'success' else 'danger' }} alert-dismissible fade show">
                    {{ message }}
                    <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
                </div>
            {% endfor %}
        {% endif %}
    {% endwith %}

    <div class="card mb-4">
        <div class="card-header bg-primary text-white">
            <h5 class="mb-0"><i class="bi bi-plus-circle"></i> Create New Feature Rollout</h5>
        </div>
        <div class="card-body">
            <a href="{{ url_for('create_rollout') }}" class="btn btn-primary">
                <i class="bi bi-plus"></i> Create Rollout
            </a>
        </div>
    </div>

    <div class="row">
        {% for rollout in rollouts %}
        <div class="col-md-6 mb-4">
            <div class="card h-100">
                <div class="card-header bg-success text-white">
                    <h6 class="mb-0"><i class="bi bi-rocket-takeoff"></i> {{ rollout.feature_name }}</h6>
                </div>
                <div class="card-body">
                    <p class="text-muted">{{ rollout.description or 'No description' }}</p>
                    <div class="mb-2">
                        <div class="progress">
                            <div class="progress-bar bg-success" style="width: {{ rollout.rollout_percentage }}%">
                                {{ rollout.rollout_percentage }}%
                            </div>
                        </div>
                    </div>
                    <p class="mb-1"><strong>Status:</strong>
                        <span class="badge bg-{{ 'success' if rollout.is_active else 'secondary' }}">
                            {{ 'Active' if rollout.is_active else 'Inactive' }}
                        </span>
                    </p>
                    <small class="text-muted">
                        Created: {{ rollout.created_at.strftime('%B %d, %Y') }}
                    </small>
                </div>
                <div class="card-footer">
                    <button class="btn btn-sm btn-outline-primary">Edit</button>
                    <button class="btn btn-sm btn-outline-danger">Delete</button>
                </div>
            </div>
        </div>
        {% endfor %}
    </div>
</div>
{% endblock %}
"""

create_rollout_template = """
{% extends "base.html" %}

{% block title %}Create Feature Rollout - EcoPulse{% endblock %}

{% block content %}
<div class="container mt-4">
    <div class="row justify-content-center">
        <div class="col-md-8">
            <div class="card">
                <div class="card-header bg-primary text-white">
                    <h4 class="mb-0"><i class="bi bi-rocket-takeoff"></i> Create Feature Rollout</h4>
                </div>
                <div class="card-body">
                    <form method="POST">
                        <div class="mb-3">
                            <label for="feature_name" class="form-label">Feature Name</label>
                            <input type="text" class="form-control" id="feature_name" name="feature_name" required>
                        </div>

                        <div class="mb-3">
                            <label for="description" class="form-label">Description</label>
                            <textarea class="form-control" id="description" name="description" rows="3"></textarea>
                        </div>

                        <div class="mb-3">
                            <label for="rollout_percentage" class="form-label">Initial Rollout Percentage</label>
                            <input type="number" class="form-control" id="rollout_percentage" name="rollout_percentage" value="0" min="0" max="100" required>
                            <div class="form-text">Percentage of users who will see this feature (0-100)</div>
                        </div>

                        <div class="mb-3">
                            <label for="target_users" class="form-label">Target Users (JSON format)</label>
                            <textarea class="form-control" id="target_users" name="target_users" rows="4" placeholder='{"user_types": ["customer"], "departments": ["IT Security"], "energy_sources": ["Solar"]}'></textarea>
                            <div class="form-text">Specify target user criteria in JSON format (optional)</div>
                        </div>

                        <div class="d-grid gap-2 d-md-flex justify-content-md-end">
                            <a href="{{ url_for('feature_rollouts') }}" class="btn btn-secondary me-md-2">Cancel</a>
                            <button type="submit" class="btn btn-primary">Create Rollout</button>
                        </div>
                    </form>
                </div>
            </div>
        </div>
    </div>
</div>
{% endblock %}
"""

partners_template = """
{% extends "base.html" %}

{% block title %}Partner Management - EcoPulse{% endblock %}

{% block content %}
<div class="container mt-4">
    <h1 class="text-white mb-4"><i class="bi bi-people"></i> Partner Management</h1>

    {% with messages = get_flashed_messages(with_categories=true) %}
        {% if messages %}
            {% for category, message in messages %}
                <div class="alert alert-{{ 'success' if category == 'success' else 'danger' }} alert-dismissible fade show">
                    {{ message }}
                    <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
                </div>
            {% endfor %}
        {% endif %}
    {% endwith %}

    <div class="card mb-4">
        <div class="card-header bg-primary text-white">
            <h5 class="mb-0"><i class="bi bi-plus-circle"></i> Register New Partner</h5>
        </div>
        <div class="card-body">
            <a href="{{ url_for('create_partner_page') }}" class="btn btn-primary">
                <i class="bi bi-plus"></i> Add Partner
            </a>
        </div>
    </div>

    <div class="row">
        {% for partner in partners %}
        <div class="col-md-6 mb-4">
            <div class="card h-100">
                <div class="card-header bg-info text-white">
                    <h6 class="mb-0"><i class="bi bi-person-badge"></i> {{ partner.name }}</h6>
                </div>
                <div class="card-body">
                    <p class="mb-1"><strong>Email:</strong> {{ partner.contact_email or 'N/A' }}</p>
                    <p class="mb-1"><strong>Sandbox:</strong> {{ 'Yes' if partner.sandbox else 'No' }}</p>
                    <p class="mb-1"><strong>Status:</strong> {{ 'Active' if partner.is_active else 'Inactive' }}</p>
                    <small class="text-muted">Created: {{ partner.created_at.strftime('%B %d, %Y') }}</small>
                </div>
                <div class="card-footer">
                    <button class="btn btn-sm btn-outline-secondary">Copy API Key</button>
                </div>
            </div>
        </div>
        {% endfor %}
    </div>
</div>
{% endblock %}
"""

create_partner_template = """
{% extends "base.html" %}

{% block title %}Create Partner - EcoPulse{% endblock %}

{% block content %}
<div class="container mt-4">
    <div class="row justify-content-center">
        <div class="col-md-8">
            <div class="card">
                <div class="card-header bg-primary text-white">
                    <h4 class="mb-0"><i class="bi bi-person-plus"></i> Register New Partner</h4>
                </div>
                <div class="card-body">
                    <form method="POST">
                        <div class="mb-3">
                            <label for="name" class="form-label">Partner Name</label>
                            <input type="text" class="form-control" id="name" name="name" required>
                        </div>
                        <div class="mb-3">
                            <label for="contact_email" class="form-label">Contact Email</label>
                            <input type="email" class="form-control" id="contact_email" name="contact_email">
                        </div>
                        <div class="form-check mb-3">
                            <input class="form-check-input" type="checkbox" id="sandbox" name="sandbox" checked>
                            <label class="form-check-label" for="sandbox">Sandbox Mode</label>
                        </div>
                        <div class="d-grid gap-2 d-md-flex justify-content-md-end">
                            <a href="{{ url_for('partners') }}" class="btn btn-secondary me-md-2">Cancel</a>
                            <button type="submit" class="btn btn-primary">Register Partner</button>
                        </div>
                    </form>
                </div>
            </div>
        </div>
    </div>
</div>
{% endblock %}
"""

support_tickets_template = """
{% extends "base.html" %}

{% block title %}Support Tickets - EcoPulse{% endblock %}

{% block content %}
<div class="container mt-4">
    <h1 class="text-white mb-4"><i class="bi bi-ticket-detailed"></i> Support Tickets</h1>

    {% with messages = get_flashed_messages(with_categories=true) %}
        {% if messages %}
            {% for category, message in messages %}
                <div class="alert alert-{{ 'success' if category == 'success' else 'danger' }} alert-dismissible fade show">
                    {{ message }}
                    <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
                </div>
            {% endfor %}
        {% endif %}
    {% endwith %}

    <div class="row">
        <div class="col-md-6 mb-4">
            <div class="card h-100">
                <div class="card-header bg-primary text-white">
                    <h5 class="mb-0"><i class="bi bi-plus-circle"></i> Submit a Ticket</h5>
                </div>
                <div class="card-body">
                    <form method="POST">
                        <div class="mb-3">
                            <label for="subject" class="form-label">Subject</label>
                            <input type="text" class="form-control" id="subject" name="subject" required>
                        </div>
                        <div class="mb-3">
                            <label for="description" class="form-label">Description</label>
                            <textarea class="form-control" id="description" name="description" rows="5" required></textarea>
                        </div>
                        <div class="mb-3">
                            <label for="priority" class="form-label">Priority</label>
                            <select class="form-select" id="priority" name="priority">
                                <option value="low">Low</option>
                                <option value="medium" selected>Medium</option>
                                <option value="high">High</option>
                            </select>
                        </div>
                        <button type="submit" class="btn btn-primary">Submit Ticket</button>
                    </form>
                </div>
            </div>
        </div>

        <div class="col-md-6 mb-4">
            <div class="card h-100">
                <div class="card-header bg-info text-white">
                    <h5 class="mb-0"><i class="bi bi-list-task"></i> Ticket Queue</h5>
                </div>
                <div class="card-body">
                    {% if tickets %}
                        <ul class="list-group">
                            {% for ticket in tickets %}
                            <li class="list-group-item d-flex justify-content-between align-items-start">
                                <div>
                                    <strong>{{ ticket.subject }}</strong>
                                    <div class="small text-muted">{{ ticket.status.title() }} • {{ ticket.priority.title() }}</div>
                                </div>
                                <a href="{{ url_for('support_ticket_detail', ticket_id=ticket.id) }}" class="btn btn-sm btn-outline-primary">View</a>
                            </li>
                            {% endfor %}
                        </ul>
                    {% else %}
                        <p class="text-muted">No tickets yet.</p>
                    {% endif %}
                </div>
            </div>
        </div>
    </div>
</div>
{% endblock %}
"""

ticket_detail_template = """
{% extends "base.html" %}

{% block title %}Ticket #{{ ticket.id }} - EcoPulse{% endblock %}

{% block content %}
<div class="container mt-4">
    <div class="row">
        <div class="col-md-8">
            <div class="card mb-4">
                <div class="card-header bg-primary text-white">
                    <h5 class="mb-0"><i class="bi bi-ticket-detailed"></i> Ticket #{{ ticket.id }}</h5>
                </div>
                <div class="card-body">
                    <p><strong>Subject:</strong> {{ ticket.subject }}</p>
                    <p><strong>Description:</strong> {{ ticket.description }}</p>
                    <p><strong>Status:</strong> <span class="badge bg-{{ 'success' if ticket.status == 'resolved' else 'warning' if ticket.status == 'in_progress' else 'secondary' }}">{{ ticket.status.replace('_', ' ').title() }}</span></p>
                    <p><strong>Priority:</strong> {{ ticket.priority.title() }}</p>
                    <p><strong>Submitted:</strong> {{ ticket.created_at.strftime('%B %d, %Y %I:%M %p') }}</p>
                    {% if ticket.assignee %}
                        <p><strong>Assigned to:</strong> {{ ticket.assignee.username }}</p>
                    {% endif %}
                </div>
            </div>

            {% if current_user.role in ['admin', 'examiner'] %}
            <div class="card">
                <div class="card-header bg-info text-white">
                    <h5 class="mb-0"><i class="bi bi-pencil-square"></i> Update Ticket</h5>
                </div>
                <div class="card-body">
                    <form method="POST">
                        <div class="mb-3">
                            <label for="status" class="form-label">Status</label>
                            <select class="form-select" id="status" name="status">
                                <option value="open" {{ 'selected' if ticket.status == 'open' else '' }}>Open</option>
                                <option value="in_progress" {{ 'selected' if ticket.status == 'in_progress' else '' }}>In Progress</option>
                                <option value="resolved" {{ 'selected' if ticket.status == 'resolved' else '' }}>Resolved</option>
                                <option value="closed" {{ 'selected' if ticket.status == 'closed' else '' }}>Closed</option>
                            </select>
                        </div>
                        <div class="mb-3">
                            <label for="assignee_id" class="form-label">Assign To</label>
                            <select class="form-select" id="assignee_id" name="assignee_id">
                                <option value="">Unassigned</option>
                                {% for user in assignees %}
                                    <option value="{{ user.id }}" {{ 'selected' if ticket.assignee_id == user.id else '' }}>{{ user.username }} ({{ user.user_type }})</option>
                                {% endfor %}
                            </select>
                        </div>
                        <button type="submit" class="btn btn-primary">Save Changes</button>
                    </form>
                </div>
            </div>
            {% endif %}
        </div>
    </div>
</div>
{% endblock %}
"""

tariff_reviews_template = """
{% extends "base.html" %}

{% block title %}Tariff Reviews - EcoPulse{% endblock %}

{% block content %}
<div class="container mt-4">
    <h1 class="text-white mb-4"><i class="bi bi-file-earmark-text"></i> Tariff Review Submissions</h1>

    <div class="card">
        <div class="card-body">
            {% if reviews %}
            <div class="list-group">
                {% for review in reviews %}
                <a href="{{ url_for('tariff_review_detail', review_id=review.id) }}" class="list-group-item list-group-item-action d-flex justify-content-between align-items-center">
                    <div>
                        <h6 class="mb-1">Review #{{ review.id }} for {{ review.report.title }}</h6>
                        <small class="text-muted">Submitted by {{ review.submitter.username }} • {{ review.submitted_at.strftime('%B %d, %Y') }}</small>
                    </div>
                    <span class="badge bg-{{ 'success' if review.status == 'approved' else 'warning' if review.status == 'under_review' else 'secondary' }}">{{ review.status.replace('_', ' ').title() }}</span>
                </a>
                {% endfor %}
            </div>
            {% else %}
                <p class="text-muted">No tariff reviews found.</p>
            {% endif %}
        </div>
    </div>
</div>
{% endblock %}
"""

tariff_review_detail_template = """
{% extends "base.html" %}

{% block title %}Tariff Review #{{ review.id }} - EcoPulse{% endblock %}

{% block content %}
<div class="container mt-4">
    <div class="row justify-content-center">
        <div class="col-md-10">
            <div class="card mb-4">
                <div class="card-header bg-primary text-white">
                    <h5 class="mb-0"><i class="bi bi-file-earmark-text"></i> Tariff Review #{{ review.id }}</h5>
                </div>
                <div class="card-body">
                    <p><strong>Report:</strong> {{ review.report.title }}</p>
                    <p><strong>Submitted by:</strong> {{ review.submitter.username }}</p>
                    <p><strong>Status:</strong> <span class="badge bg-{{ 'success' if review.status == 'approved' else 'warning' if review.status == 'under_review' else 'secondary' }}">{{ review.status.replace('_', ' ').title() }}</span></p>
                    <p><strong>Submitted at:</strong> {{ review.submitted_at.strftime('%B %d, %Y %I:%M %p') }}</p>
                    {% if review.notes %}
                        <div class="mb-3">
                            <strong>Notes:</strong>
                            <p>{{ review.notes }}</p>
                        </div>
                    {% endif %}
                    {% if review.examiner %}
                        <p><strong>Examined by:</strong> {{ review.examiner.username }}</p>
                    {% endif %}
                </div>
            </div>

            {% if current_user.role == 'examiner' and review.status != 'approved' %}
            <div class="card">
                <div class="card-header bg-info text-white">
                    <h5 class="mb-0"><i class="bi bi-check2-circle"></i> Approve Review</h5>
                </div>
                <div class="card-body">
                    <form method="POST">
                        <button type="submit" class="btn btn-success">Approve Tariff Review</button>
                    </form>
                </div>
            </div>
            {% endif %}
        </div>
    </div>
</div>
{% endblock %}
"""


def create_default_departments():
    departments = [
        {'name': 'Customer Service', 'description': 'Handles customer inquiries and support'},
        {'name': 'Technical Support', 'description': 'Provides technical assistance and troubleshooting'},
        {'name': 'Billing', 'description': 'Manages billing and financial records'},
        {'name': 'Operations', 'description': 'Oversees system operations and maintenance'},
        {'name': 'IT Security', 'description': 'Ensures system security and data protection'},
    ]
    for dept in departments:
        if not Department.query.filter_by(name=dept['name']).first():
            db.session.add(Department(name=dept['name'], description=dept['description']))
    db.session.commit()


def create_sample_impact_counters():
    """Create sample impact counter data"""
    try:
        counters = [
            {'metric_name': 'total_energy_saved', 'value': 125000},
            {'metric_name': 'users_onboarded', 'value': 2500},
            {'metric_name': 'carbon_reduced', 'value': 75000}
        ]
        for counter_data in counters:
            counter = ImpactCounter.query.filter_by(metric_name=counter_data['metric_name']).first()
            if not counter:
                counter = ImpactCounter(**counter_data)
                db.session.add(counter)
        db.session.commit()
    except Exception as e:
        print(f" Error creating impact counters: {e}")
        db.session.rollback()


def initialize_database():
    """Create tables and migrate older SQLite schemas on startup."""
    with app.app_context():
        if not verify_or_rebuild_database():
            print('Rebuilding the SQLite database because the existing file was corrupted.')

        try:
            db.create_all()
            print(' Database tables created/verified')
        except Exception as e:
            print(f' Error creating tables: {e}')
            import traceback
            traceback.print_exc()

        try:
            create_default_departments()
            print(' Default departments created/verified')
        except Exception as e:
            print(f' Error creating departments: {e}')

        try:
            update_database_schema()
        except Exception as e:
            print(f' Error updating schema: {e}')

        try:
            create_sample_impact_counters()
            print(' Sample impact counters created/verified')
        except Exception as e:
            print(f' Error creating impact counters: {e}')
            import traceback
            traceback.print_exc()


initialize_database()


# ===================== NEW API ROUTES - COST CALCULATOR =====================

@app.route('/api/cost/calculate', methods=['POST'])
@login_required
def api_calculate_cost():
    """Calculate cost for given kWh"""
    try:
        data = request.get_json()
        kwh = float(data.get('kwh', 0))
        unit_cost = float(data.get('unit_cost', current_user.unit_cost))
        currency = data.get('currency', current_user.currency)
        
        total_cost = calculate_electricity_cost(kwh, unit_cost, currency)
        
        return jsonify({
            'success': True,
            'kwh': kwh,
            'unit_cost': unit_cost,
            'total_cost': total_cost,
            'currency': currency
        }), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@app.route('/api/cost/daily', methods=['GET'])
@login_required
def api_daily_cost():
    """Get today's cost"""
    try:
        cost_data = calculate_daily_cost(current_user)
        return jsonify({
            'success': True,
            'date': datetime.utcnow().date().isoformat(),
            'kwh': cost_data['kwh'],
            'cost': cost_data['cost'],
            'currency': current_user.currency
        }), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@app.route('/api/cost/period', methods=['POST'])
@login_required
def api_period_cost():
    """Calculate cost for a specific period"""
    try:
        data = request.get_json()
        start_date = datetime.fromisoformat(data.get('start_date'))
        end_date = datetime.fromisoformat(data.get('end_date'))
        
        cost_data = calculate_period_cost(current_user, start_date, end_date)
        return jsonify({
            'success': True,
            'start_date': start_date.isoformat(),
            'end_date': end_date.isoformat(),
            'kwh': cost_data['kwh'],
            'cost': cost_data['cost'],
            'currency': current_user.currency
        }), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


# ===================== NEW API ROUTES - ANALYTICS & INSIGHTS =====================

@app.route('/api/analytics/overview', methods=['GET'])
@login_required
def api_analytics_overview():
    """Get energy analytics overview"""
    try:
        period = request.args.get('period', 'monthly')
        branch_id = request.args.get('branch_id', type=int)
        
        analytics = calculate_energy_analytics(current_user, period, branch_id)
        return jsonify({
            'success': True,
            'period': period,
            'analytics': analytics
        }), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@app.route('/api/analytics/comparison', methods=['POST'])
@login_required
def api_analytics_comparison():
    """Compare usage across periods"""
    try:
        data = request.get_json()
        period1_start = datetime.fromisoformat(data.get('period1_start'))
        period1_end = datetime.fromisoformat(data.get('period1_end'))
        period2_start = datetime.fromisoformat(data.get('period2_start'))
        period2_end = datetime.fromisoformat(data.get('period2_end'))
        
        readings1 = Reading.query.filter(
            Reading.user_id == current_user.id,
            Reading.created_at >= period1_start,
            Reading.created_at <= period1_end
        ).all()
        
        readings2 = Reading.query.filter(
            Reading.user_id == current_user.id,
            Reading.created_at >= period2_start,
            Reading.created_at <= period2_end
        ).all()
        
        total1 = sum(r.kwh for r in readings1)
        total2 = sum(r.kwh for r in readings2)
        
        return jsonify({
            'success': True,
            'period1': {'usage': total1, 'cost': calculate_electricity_cost(total1, current_user.unit_cost)},
            'period2': {'usage': total2, 'cost': calculate_electricity_cost(total2, current_user.unit_cost)},
            'difference': total2 - total1,
            'percentage_change': ((total2 - total1) / total1 * 100) if total1 > 0 else 0
        }), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


# ===================== NEW API ROUTES - RECOMMENDATIONS =====================

@app.route('/api/recommendations/generate', methods=['GET'])
@login_required
def api_generate_recommendations():
    """Generate energy saving recommendations"""
    try:
        recommendations = generate_energy_recommendations(current_user)
        
        # Save recommendations to database
        for rec in recommendations:
            recommendation = EnergyRecommendation(
                user_id=current_user.id,
                recommendation_type=rec['type'],
                description=rec['description'],
                estimated_savings=rec['savings'],
                priority=rec['priority']
            )
            db.session.add(recommendation)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'count': len(recommendations),
            'recommendations': recommendations
        }), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 400


@app.route('/api/recommendations/all', methods=['GET'])
@login_required
def api_get_recommendations():
    """Get all recommendations for user"""
    try:
        recommendations = EnergyRecommendation.query.filter_by(user_id=current_user.id).all()
        return jsonify({
            'success': True,
            'count': len(recommendations),
            'recommendations': [{
                'id': r.id,
                'type': r.recommendation_type,
                'description': r.description,
                'savings': r.estimated_savings,
                'priority': r.priority,
                'is_read': r.is_read,
                'is_acted': r.is_acted_upon
            } for r in recommendations]
        }), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


# ===================== NEW API ROUTES - DEVICE MONITORING =====================

@app.route('/api/devices/all', methods=['GET'])
@login_required
def api_get_devices():
    """Get all registered devices"""
    try:
        devices = CustomerDevice.query.filter_by(user_id=current_user.id).all()
        return jsonify({
            'success': True,
            'count': len(devices),
            'devices': [{
                'id': d.id,
                'name': d.name,
                'category': d.category,
                'watts': d.watts,
                'hours_per_day': d.hours_per_day,
                'quantity': d.quantity,
                'is_active': d.is_active,
                'status': d.current_status.status if d.current_status else 'unknown',
                'is_online': d.current_status.is_online if d.current_status else False
            } for d in devices]
        }), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@app.route('/api/devices/add', methods=['POST'])
@login_required
def api_add_device():
    """Add a new device"""
    try:
        data = request.get_json()
        device = CustomerDevice(
            user_id=current_user.id,
            name=data.get('name'),
            category=data.get('category', 'Appliance'),
            watts=float(data.get('watts', 0)),
            hours_per_day=float(data.get('hours_per_day', 0)),
            quantity=int(data.get('quantity', 1)),
            notes=data.get('notes')
        )
        db.session.add(device)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Device added successfully',
            'device_id': device.id
        }), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 400


@app.route('/api/devices/<int:device_id>/status', methods=['GET'])
@login_required
def api_device_status(device_id):
    """Get real-time device status"""
    try:
        device = CustomerDevice.query.get(device_id)
        if not device or device.user_id != current_user.id:
            return jsonify({'success': False, 'error': 'Device not found'}), 404
        
        data = get_device_real_time_data(device_id)
        return jsonify({
            'success': True,
            'device_id': device_id,
            'device_name': device.name,
            'data': data
        }), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@app.route('/api/devices/<int:device_id>/remove', methods=['DELETE'])
@login_required
def api_remove_device(device_id):
    """Remove a device"""
    try:
        device = CustomerDevice.query.get(device_id)
        if not device or device.user_id != current_user.id:
            return jsonify({'success': False, 'error': 'Device not found'}), 404
        
        db.session.delete(device)
        db.session.commit()
        return jsonify({'success': True, 'message': 'Device removed successfully'}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 400


# ===================== NEW API ROUTES - REPORTS =====================

@app.route('/api/reports/generate', methods=['POST'])
@login_required
def api_generate_report():
    """Generate energy report"""
    try:
        data = request.get_json()
        report_type = data.get('type', 'monthly')
        branch_id = data.get('branch_id')
        
        report_data = generate_energy_report(current_user, report_type, branch_id)
        return jsonify({
            'success': True,
            'report': report_data
        }), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 400


@app.route('/api/reports/all', methods=['GET'])
@login_required
def api_get_reports():
    """Get all reports for user"""
    try:
        report_type = request.args.get('type')
        query = ReportGeneration.query.filter_by(user_id=current_user.id)
        
        if report_type:
            query = query.filter_by(report_type=report_type)
        
        reports = query.all()
        return jsonify({
            'success': True,
            'count': len(reports),
            'reports': [{
                'id': r.id,
                'type': r.report_type,
                'period_start': r.period_start.isoformat(),
                'period_end': r.period_end.isoformat(),
                'total_energy': r.total_energy,
                'total_cost': r.total_cost,
                'created_at': r.created_at.isoformat()
            } for r in reports]
        }), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


# ===================== NEW API ROUTES - ALERTS =====================

@app.route('/api/alerts/create', methods=['POST'])
@login_required
def api_create_alert():
    """Create an alert"""
    try:
        data = request.get_json()
        alert = AlertHistory(
            user_id=current_user.id,
            device_id=data.get('device_id'),
            alert_type=data.get('type'),
            message=data.get('message'),
            severity=data.get('severity', 'medium')
        )
        db.session.add(alert)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'alert_id': alert.id,
            'message': 'Alert created'
        }), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 400


@app.route('/api/alerts/all', methods=['GET'])
@login_required
def api_get_alerts():
    """Get all alerts for user"""
    try:
        alerts = AlertHistory.query.filter_by(user_id=current_user.id).order_by(AlertHistory.created_at.desc()).all()
        return jsonify({
            'success': True,
            'count': len(alerts),
            'alerts': [{
                'id': a.id,
                'type': a.alert_type,
                'message': a.message,
                'severity': a.severity,
                'is_acknowledged': a.is_acknowledged,
                'created_at': a.created_at.isoformat()
            } for a in alerts]
        }), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@app.route('/api/alerts/<int:alert_id>/acknowledge', methods=['PUT'])
@login_required
def api_acknowledge_alert(alert_id):
    """Acknowledge an alert"""
    try:
        alert = AlertHistory.query.get(alert_id)
        if not alert or alert.user_id != current_user.id:
            return jsonify({'success': False, 'error': 'Alert not found'}), 404
        
        alert.is_acknowledged = True
        alert.acknowledged_at = datetime.utcnow()
        db.session.commit()
        
        return jsonify({'success': True, 'message': 'Alert acknowledged'}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 400


# ===================== NEW API ROUTES - BRANCHES (MULTI-BUSINESS) =====================

@app.route('/api/branches/all', methods=['GET'])
@login_required
def api_get_branches():
    """Get all branches for business users"""
    try:
        if current_user.user_type != 'business_manager':
            return jsonify({'success': False, 'error': 'Only business managers can access branches'}), 403
        
        branches = Branch.query.filter_by(user_id=current_user.id).all()
        return jsonify({
            'success': True,
            'count': len(branches),
            'branches': [{
                'id': b.id,
                'name': b.name,
                'location': b.location,
                'phone': b.phone,
                'total_devices': b.total_devices,
                'is_active': b.is_active
            } for b in branches]
        }), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@app.route('/api/branches/create', methods=['POST'])
@login_required
def api_create_branch():
    """Create a new branch"""
    try:
        if current_user.user_type != 'business_manager':
            return jsonify({'success': False, 'error': 'Only business managers can create branches'}), 403
        
        data = request.get_json()
        branch = Branch(
            user_id=current_user.id,
            name=data.get('name'),
            location=data.get('location'),
            address=data.get('address'),
            phone=data.get('phone')
        )
        db.session.add(branch)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'branch_id': branch.id,
            'message': 'Branch created successfully'
        }), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 400


@app.route('/api/branches/<int:branch_id>/analytics', methods=['GET'])
@login_required
def api_branch_analytics(branch_id):
    """Get analytics for a specific branch"""
    try:
        branch = Branch.query.get(branch_id)
        if not branch or branch.user_id != current_user.id:
            return jsonify({'success': False, 'error': 'Branch not found'}), 404
        
        # Get branch usage summary
        usage_data = BranchEnergyUsage.query.filter_by(branch_id=branch_id).order_by(BranchEnergyUsage.date.desc()).limit(30).all()
        
        return jsonify({
            'success': True,
            'branch_id': branch_id,
            'branch_name': branch.name,
            'usage_history': [{
                'date': u.date.isoformat(),
                'total_usage': u.total_usage,
                'total_cost': u.total_cost,
                'device_count': u.device_count
            } for u in usage_data]
        }), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


# ===================== NEW API ROUTES - SETTINGS & PREFERENCES =====================

@app.route('/api/settings/energy-source', methods=['GET'])
@login_required
def api_get_energy_source():
    """Get user's energy source setting"""
    try:
        return jsonify({
            'success': True,
            'energy_source': current_user.energy_source,
            'unit_cost': current_user.unit_cost,
            'currency': current_user.currency,
            'threshold': current_user.threshold
        }), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@app.route('/api/settings/update', methods=['POST'])
@login_required
def api_update_settings():
    """Update user settings"""
    try:
        data = request.get_json()
        
        if 'unit_cost' in data:
            current_user.unit_cost = float(data['unit_cost'])
        if 'currency' in data:
            current_user.currency = data['currency']
        if 'threshold' in data:
            current_user.threshold = float(data['threshold'])
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Settings updated successfully'
        }), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 400


# ===================== NEW PAGES - DASHBOARD WITH NEW FEATURES =====================

@app.route('/dashboard/enhanced')
@login_required
def enhanced_dashboard():
    """Enhanced dashboard with all new features"""
    try:
        # Calculate analytics
        analytics = calculate_energy_analytics(current_user, 'monthly')
        
        # Get recommendations
        recommendations = EnergyRecommendation.query.filter_by(user_id=current_user.id).order_by(EnergyRecommendation.created_at.desc()).limit(5).all()
        
        # Get recent alerts
        alerts = AlertHistory.query.filter_by(user_id=current_user.id).order_by(AlertHistory.created_at.desc()).limit(10).all()
        
        # Get devices and their status
        devices = CustomerDevice.query.filter_by(user_id=current_user.id).all()
        
        # Get today's cost
        today_cost = calculate_daily_cost(current_user)
        
        return jsonify({
            'dashboard': {
                'user': current_user.username,
                'user_type': current_user.user_type,
                'total_devices': len(devices),
                'analytics': analytics,
                'today_cost': today_cost,
                'recommendations': [{
                    'type': r.recommendation_type,
                    'description': r.description,
                    'savings': r.estimated_savings
                } for r in recommendations],
                'recent_alerts': [{
                    'type': a.alert_type,
                    'message': a.message,
                    'severity': a.severity
                } for a in alerts]
            }
        }), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


# ===================== ADMIN DASHBOARD ROUTES (defined after templates) =====================

@app.route('/admin/iot-devices')
@admin_required
def admin_iot_devices_dashboard():
    """Admin dashboard for IoT device management"""
    registrations = IoTDeviceRegistration.query.all()
    pending_count = IoTDeviceRegistration.query.filter_by(status='pending').count()
    active_count = IoTDeviceRegistration.query.filter_by(status='active').count()
    
    return render_template_string(admin_iot_devices_template,
                                  registrations=registrations,
                                  pending_count=pending_count,
                                  active_count=active_count)


@app.route('/admin/user-registrations')
@admin_required
def admin_user_registrations_dashboard():
    """Admin dashboard for user registration requests and approvals"""
    pending_requests = UserRegistrationRequest.query.filter_by(status='pending').order_by(
        UserRegistrationRequest.submission_date.desc()
    ).all()
    approved_requests = UserRegistrationRequest.query.filter_by(status='approved').count()
    rejected_requests = UserRegistrationRequest.query.filter_by(status='rejected').count()
    
    return render_template_string(admin_user_registrations_template,
                                  pending_requests=pending_requests,
                                  approved_count=approved_requests,
                                  rejected_count=rejected_requests)


if __name__ == '__main__':
    with app.app_context():
        if not verify_or_rebuild_database():
            print('Rebuilding the SQLite database because the existing file was corrupted.')
        try:
            # Create tables if they don't exist
            db.create_all()
            print(" Database tables created/verified")
        except Exception as e:
            print(f" Error creating tables: {e}")
            import traceback
            traceback.print_exc()

        try:
            # Create default departments
            create_default_departments()
            print(" Default departments created/verified")
        except Exception as e:
            print(f" Error creating departments: {e}")

        try:
            # Update schema if needed
            update_database_schema()
        except Exception as e:
            print(f" Error updating schema: {e}")

        try:
            # Create sample impact counters
            create_sample_impact_counters()
            print(" Sample impact counters created/verified")
        except Exception as e:
            print(f" Error creating impact counters: {e}")
            import traceback
            traceback.print_exc()

        admin, admin_password, _ = ensure_test_user('admin', 'admin.demo@ecopulse.local', 'Administration')
        examiner, examiner_password, _ = ensure_test_user('examiner', 'examiner.demo@ecopulse.local', 'Audit')
        customer, customer_password, customer_settings = ensure_test_user('customer', 'customer.demo@ecopulse.local')

        customer.threshold = customer.threshold or 600
        customer_settings.alert_threshold = customer.threshold
        for existing_customer in User.query.filter_by(role='customer').all():
            # Check if energy_source attribute exists before accessing
            if hasattr(existing_customer, 'energy_source'):
                existing_customer.energy_source = normalize_energy_source(existing_customer.energy_source)
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
                        period=utc_now().strftime('%Y-%m'),
                        total_consumption=total_kwh,
                        total_cost=total_cost,
                        total_paid=total_cost * 0.9,
                        balance=total_cost * 0.4,
                        due_date=utc_now() + timedelta(days=15),
                        payment_status='pending'
                    )
                    db.session.add(record)
            db.session.commit()
            print(" Sample financial records created")

        # ========== ADD SAMPLE GAMIFICATION DATA ==========
        # Create sample energy tips if none exist
        try:
            if not EnergyTip.query.first():
                print(" Creating sample energy tips...")
                tips = [
                    EnergyTip(title="Unplug Idle Devices",
                              content="Devices on standby can consume up to 10% of your energy bill. Unplug phone chargers, TVs, and computers when not in use.",
                              savings_estimate=50, category="general"),
                    EnergyTip(title="Optimal AC Temperature",
                              content="Set your AC to 24°C (75°F) for optimal cooling efficiency. Each degree lower increases energy use by 8%.",
                              savings_estimate=80, category="cooling"),
                    EnergyTip(title="Full Load Laundry",
                              content="Always run your washing machine and dishwasher with full loads to maximize efficiency.",
                              savings_estimate=30, category="appliances"),
                    EnergyTip(title="LED Lighting",
                              content="Replace incandescent bulbs with LEDs. They use 75% less energy and last 25 times longer.",
                              savings_estimate=40, category="lighting"),
                    EnergyTip(title="Natural Light",
                              content="Open curtains during the day instead of using artificial lighting. Position workspaces near windows.",
                              savings_estimate=20, category="lighting"),
                    EnergyTip(title="Energy Efficient Fridge",
                              content="Set your refrigerator temperature between 3°C and 5°C. Clean the coils every 6 months.",
                              savings_estimate=35, category="appliances"),
                    EnergyTip(title="Smart Power Strips",
                              content="Use smart power strips to automatically cut power to devices when they're not in use.",
                              savings_estimate=25, category="general"),
                    EnergyTip(title="Regular HVAC Maintenance",
                              content="Clean or replace AC filters monthly. A dirty filter can increase energy consumption by 15%.",
                              savings_estimate=60, category="cooling"),
                ]
                for tip in tips:
                    db.session.add(tip)
                db.session.commit()
                print(f" {len(tips)} energy tips created!")
            else:
                print(" Energy tips already exist, skipping...")
        except Exception as e:
            print(f" Note: Could not create energy tips: {e}")

        # Create sample badges if none exist
        try:
            if not Badge.query.first():
                print(" Creating sample badges...")
                badges = [
                    Badge(name="Energy Saver", description="Saved 100+ kWh", icon="bi-leaf", points_required=100,
                          condition_type="savings", condition_value=100),
                    Badge(name="Green Champion", description="Saved 500+ kWh", icon="bi-tree", points_required=500,
                          condition_type="savings", condition_value=500),
                    Badge(name="Eco Warrior", description="Saved 1000+ kWh", icon="bi-globe", points_required=1000,
                          condition_type="savings", condition_value=1000),
                    Badge(name="Streak Master", description="30 day streak!", icon="bi-fire", points_required=0,
                          condition_type="streak", condition_value=30),
                    Badge(name="Consistent Saver", description="7 day streak", icon="bi-calendar-check",
                          points_required=0, condition_type="streak", condition_value=7),
                    Badge(name="Reading Champion", description="12+ readings submitted", icon="bi-journal",
                          points_required=0, condition_type="reading_count", condition_value=12),
                    Badge(name="Threshold Hero", description="Stayed below threshold for 3 months",
                          icon="bi-shield-check", points_required=0, condition_type="threshold", condition_value=3),
                    Badge(name="Early Bird", description="Submitted readings before deadline", icon="bi-sunrise",
                          points_required=0, condition_type="punctuality", condition_value=0),
                ]
                for badge in badges:
                    db.session.add(badge)
                db.session.commit()
                print(f" {len(badges)} badges created!")
            else:
                print(" Badges already exist, skipping...")
        except Exception as e:
            print(f" Note: Could not create badges: {e}")

        # Create initial EcoPoints for existing customers
        try:
            customers = User.query.filter_by(role='customer').all()
            points_created = 0
            for existing_customer in customers:
                if not EcoPoints.query.filter_by(user_id=existing_customer.id).first():
                    points = EcoPoints(user_id=existing_customer.id)
                    # Award initial points based on existing readings
                    user_readings = Reading.query.filter_by(user_id=existing_customer.id).all()
                    if user_readings:
                        total_consumption = sum(r.kwh for r in user_readings)
                        threshold = existing_customer.threshold
                        if total_consumption > 0 and threshold > 0:
                            # Calculate initial points based on efficiency (below threshold = more points)
                            efficiency = max(0, min(100, (threshold - total_consumption) / threshold * 100))
                            initial_points = int(efficiency * 5)  # Up to 500 points
                            points.points = initial_points
                    db.session.add(points)
                    points_created += 1
            db.session.commit()
            print(f" EcoPoints initialized for {points_created} customers!")
        except Exception as e:
            print(f" Note: Could not create EcoPoints: {e}")

        # Update leaderboard
        try:
            from sqlalchemy import text

            # Clear old leaderboard entries
            Leaderboard.query.delete()

            # Get all users with points
            all_points = EcoPoints.query.all()
            sorted_users = sorted(all_points, key=lambda x: x.points, reverse=True)

            for rank, points_entry in enumerate(sorted_users, 1):
                leader = Leaderboard(
                    user_id=points_entry.user_id,
                    points=points_entry.points,
                    rank=rank
                )
                db.session.add(leader)
            db.session.commit()
            print(f" Leaderboard updated successfully!")
        except Exception as e:
            print(f" Note: Could not update leaderboard: {e}")

        # Create sample community post if none exist
        try:
            if not CommunityPost.query.first():
                print(" Creating sample community posts...")
                sample_posts = [
                    CommunityPost(
                        user_id=customer.id,
                        title="I reduced my bill by 30%!",
                        content="After following the tips about unplugging devices and using LED lights, my electricity bill dropped from 8000 Ksh to 5600 Ksh! Highly recommend these changes.",
                        post_type="success_story"
                    ),
                    CommunityPost(
                        user_id=admin.id,
                        title="New Feature: AI Energy Predictor",
                        content="We've just launched our new AI predictor that helps you find the best times to run your appliances. Check it out in the Rewards section!",
                        post_type="tip"
                    ),
                    CommunityPost(
                        user_id=examiner.id,
                        title="Question about solar integration",
                        content="Is anyone using solar panels with EcoPulse? I'd love to hear about your experience and savings.",
                        post_type="question"
                    ),
                ]
                for post in sample_posts:
                    db.session.add(post)
                db.session.commit()
                print(f" {len(sample_posts)} community posts created!")
            else:
                print(" Community posts already exist, skipping...")
        except Exception as e:
            print(f" Note: Could not create community posts: {e}")

        print("\n" + "=" * 70)
        print(" GAMIFICATION DATA INITIALIZATION COMPLETE!")
        print("=" * 70)
        # ========== END OF SAMPLE GAMIFICATION DATA ==========

        # Ensure session is clean before accessing attributes
        db.session.rollback()
        admin = User.query.filter_by(role='admin').first()
        examiner = User.query.filter_by(role='examiner').first()
        customer = User.query.filter_by(role='customer').first()

        admin_username = admin.username if admin else 'admin'
        examiner_username = examiner.username if examiner else 'examiner'
        customer_username = customer.username if customer else 'customer'
        customer_meter_number = customer.meter_number if customer else 'N/A'

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
