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

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-change-this-in-production'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///ecopulse.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

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


def get_or_create_user_settings(user):
    settings = UserSettings.query.filter_by(user_id=user.id).first()
    if not settings:
        settings = UserSettings(
            user_id=user.id,
            alert_threshold=user.threshold,
        )
        db.session.add(settings)
        db.session.commit()
    return settings


def calculate_reading_cost(user, settings, kwh):
    base_cost = kwh * user.unit_cost
    overage_units = max(0, kwh - user.threshold)
    overage_charge = 0

    if overage_units > 0 and settings.allow_overage:
        overage_charge = overage_units * user.unit_cost * 0.15

    return round(base_cost + overage_charge, 2), round(overage_charge, 2)


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
                background: white;
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
    <style>
        body { background: linear-gradient(135deg, #072f2f, #0f766e 55%, #d97706); min-height: 100vh; display: flex; align-items: center; justify-content: center; }
        .auth-shell { max-width: 980px; width: 100%; margin: 24px; background: rgba(255,255,255,0.98); border-radius: 28px; overflow: hidden; box-shadow: 0 24px 60px rgba(0,0,0,0.28); }
        .auth-hero { background: linear-gradient(155deg, #052e2b, #0f766e); color: white; padding: 48px; min-height: 100%; }
        .auth-card { padding: 48px; }
        .accent-chip { display: inline-flex; align-items: center; gap: 10px; padding: 8px 14px; border-radius: 999px; background: rgba(255,255,255,0.12); margin-bottom: 20px; }
    </style>
</head>
<body>
    <div class="auth-shell row g-0">
        <div class="col-lg-6 auth-hero d-flex flex-column justify-content-center">
            <div class="accent-chip"><i class="bi bi-lightning-charge-fill"></i> EcoPulse Customer Access</div>
            <h1 class="display-5 fw-bold">Monitor usage, costs, and alerts from one place.</h1>
            <p class="lead mt-3">Customer login is public. Staff access exists separately and is intentionally not shown on the homepage navigation.</p>
        </div>
        <div class="col-lg-6 auth-card">
            <a href="{{ url_for('index') }}" class="btn btn-link px-0 text-decoration-none"><i class="bi bi-arrow-left"></i> Back to home</a>
            <h2 class="fw-bold mt-3">Customer Login</h2>
            <p class="text-muted">Sign in with your customer account.</p>
            {% if error %}<div class="alert alert-danger">{{ error }}</div>{% endif %}
            <form method="POST" class="mt-4">
                <div class="mb-3"><label class="form-label">Username</label><input type="text" name="username" class="form-control form-control-lg" required></div>
                <div class="mb-3"><label class="form-label">Password</label><input type="password" name="password" class="form-control form-control-lg" required></div>
                <button type="submit" class="btn btn-lg btn-dark w-100">Login</button>
            </form>
            <div class="mt-4"><span class="text-muted">Need an account?</span> <a href="{{ url_for('register') }}" class="text-decoration-none">Register as a customer</a></div>
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
    <style>body{background:linear-gradient(160deg,#111827,#1f2937 55%,#7c2d12);min-height:100vh;display:flex;align-items:center;justify-content:center}.panel{max-width:520px;width:100%;margin:24px;background:white;border-radius:24px;padding:36px;box-shadow:0 24px 60px rgba(0,0,0,0.35)}</style>
</head>
<body>
    <div class="panel">
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
    <style>body{background:linear-gradient(145deg,#0f172a,#0f766e);min-height:100vh;display:flex;align-items:center;justify-content:center}.panel{max-width:620px;width:100%;margin:24px;background:white;border-radius:28px;padding:40px;box-shadow:0 24px 60px rgba(0,0,0,0.28)}</style>
</head>
<body>
    <div class="panel">
        <a href="{{ url_for('index') }}" class="btn btn-link px-0 text-decoration-none">Back to home</a>
        <h2 class="fw-bold mt-2">Customer Registration</h2>
        <p class="text-muted">Create a customer account to start tracking consumption and billing summaries.</p>
        {% if error %}<div class="alert alert-danger">{{ error }}</div>{% endif %}
        <form method="POST" class="row g-3">
            <div class="col-md-6"><label class="form-label">Username</label><input type="text" name="username" class="form-control" required></div>
            <div class="col-md-6"><label class="form-label">Email</label><input type="email" name="email" class="form-control" required></div>
            <div class="col-md-6"><label class="form-label">Password</label><input type="password" name="password" class="form-control" required></div>
            <div class="col-md-6"><label class="form-label">Confirm Password</label><input type="password" name="confirm_password" class="form-control" required></div>
            <div class="col-12"><button type="submit" class="btn btn-dark w-100 btn-lg">Create Customer Account</button></div>
        </form>
        <div class="mt-3"><span class="text-muted">Already registered?</span> <a href="{{ url_for('login') }}" class="text-decoration-none">Log in here</a></div>
    </div>
</body>
</html>
"""

dashboard_template = """<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>EcoPulse Dashboard</title><link rel="icon" type="image/svg+xml" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Crect width='64' height='64' rx='16' fill='%23062f2f'/%3E%3Cpath d='M35 6 18 34h11l-4 24 21-31H34z' fill='%23f59e0b'/%3E%3C/svg%3E"><link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css"><link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.0/font/bootstrap-icons.css"><style>*{margin:0;padding:0;box-sizing:border-box}body{background:linear-gradient(135deg, #667eea 0%, #764ba2 100%);min-height:100vh;font-family:'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;padding-top:80px;padding-bottom:30px}.navbar{background:linear-gradient(135deg, #667eea 0%, #764ba2 100%);box-shadow:0 5px 20px rgba(0,0,0,0.2)}.navbar-brand{font-weight:700;font-size:1.5rem}.header-section{text-align:center;margin-bottom:40px;color:white}.header-section h1{font-size:3rem;font-weight:700;margin-bottom:10px;text-shadow:2px 2px 4px rgba(0,0,0,0.3)}.role-badge{display:inline-block;padding:5px 15px;border-radius:20px;font-size:0.9rem;font-weight:600;margin-top:10px}.role-customer{background-color:#00b894;color:white}.role-admin{background-color:#ff6b6b;color:white}.role-examiner{background-color:#ff9800;color:white}.card{border:none;border-radius:15px;box-shadow:0 10px 30px rgba(0,0,0,0.2);margin-bottom:30px;transition:transform 0.3s ease, box-shadow 0.3s ease}.card:hover{transform:translateY(-5px);box-shadow:0 15px 40px rgba(0,0,0,0.3)}.card-header{border-radius:15px 15px 0 0;padding:20px;font-weight:600;font-size:1.2rem;display:flex;align-items:center;gap:10px;color:white}.card-header.bg-primary{background:linear-gradient(135deg, #667eea 0%, #764ba2 100%) !important}.card-header.bg-info{background:linear-gradient(135deg, #00d4ff 0%, #0099ff 100%) !important}.card-header.bg-warning{background:linear-gradient(135deg, #ffc107 0%, #ff9800 100%) !important}.card-header.bg-success{background:linear-gradient(135deg, #00b894 0%, #00cec9 100%) !important}.card-header.bg-secondary{background:linear-gradient(135deg, #6c757d 0%, #495057 100%) !important}.card-body{padding:30px}.stats-grid{display:grid;grid-template-columns:repeat(auto-fit, minmax(250px, 1fr));gap:20px;margin-bottom:30px}.stat-card{background:white;padding:20px;border-radius:10px;box-shadow:0 5px 15px rgba(0,0,0,0.1);text-align:center}.stat-value{font-size:2.5rem;font-weight:700;color:#667eea}.stat-label{color:#666;font-size:0.9rem;margin-top:10px}.stat-icon{font-size:2rem;margin-bottom:10px;color:#667eea}.form-control,.form-select{border-radius:8px;border:2px solid #e0e0e0;padding:12px 15px}.form-control:focus,.form-select:focus{border-color:#667eea;box-shadow:0 0 0 0.2rem rgba(102,126,234,0.25)}.btn{border-radius:8px;padding:10px 20px;font-weight:600;transition:all 0.3s ease}.btn-success{background:linear-gradient(135deg, #00b894 0%, #00cec9 100%);border:none;color:white}.btn-success:hover{background:linear-gradient(135deg, #00a884 0%, #00beb9 100%)}.btn-primary{background:linear-gradient(135deg, #667eea 0%, #764ba2 100%);border:none;color:white}.btn-warning{background:linear-gradient(135deg, #ffc107 0%, #ff9800 100%);border:none;color:white}.btn-danger{background:linear-gradient(135deg, #ff6b6b 0%, #ee5a6f 100%);border:none;color:white}.btn-sm{padding:5px 10px;font-size:0.875rem}.alert{border-radius:10px;border:none;margin-bottom:20px}.table{color:#333}.table thead{background:#f5f5f5;font-weight:600}.table tbody tr:hover{background-color:#f9f9f9}.no-data{text-align:center;padding:30px;color:#999;font-style:italic}.img-fluid{border-radius:10px;box-shadow:0 5px 15px rgba(0,0,0,0.1);max-width:100%;height:auto}.employee-info{background:rgba(255,255,255,0.1);padding:10px;border-radius:10px;margin-top:10px;color:white;font-size:0.9rem}.employee-info i{margin-right:5px}@media (max-width:768px){body{padding-top:100px}.header-section h1{font-size:2rem}.stats-grid{grid-template-columns:1fr}}</style></head><body><nav class="navbar navbar-expand-lg navbar-dark fixed-top"><div class="container"><a class="navbar-brand" href="{{ url_for('dashboard') }}"><i class="bi bi-lightning-fill"></i> EcoPulse</a><button class="navbar-toggler" type="button" data-bs-toggle="collapse" data-bs-target="#navbarNav"><span class="navbar-toggler-icon"></span></button><div class="collapse navbar-collapse" id="navbarNav"><ul class="navbar-nav ms-auto"><li class="nav-item"><a class="nav-link" href="{{ url_for('dashboard') }}"><i class="bi bi-house"></i> Dashboard</a></li><li class="nav-item"><a class="nav-link" href="{{ url_for('settings') }}"><i class="bi bi-gear"></i> Settings</a></li>{% if current_user.role == 'admin' %}<li class="nav-item"><a class="nav-link" href="{{ url_for('admin_financial') }}"><i class="bi bi-cash-stack"></i> Financial</a></li>{% endif %}{% if current_user.role == 'examiner' %}<li class="nav-item"><a class="nav-link" href="{{ url_for('examiner_dashboard') }}"><i class="bi bi-clipboard-data"></i> Examiner</a></li>{% endif %}<li class="nav-item dropdown"><a class="nav-link dropdown-toggle" href="#" id="navbarDropdown" role="button" data-bs-toggle="dropdown"><i class="bi bi-person-circle"></i> {{ current_user.username }}</a><ul class="dropdown-menu dropdown-menu-end"><li><a class="dropdown-item" href="{{ url_for('logout') }}"><i class="bi bi-box-arrow-right"></i> Logout</a></li></ul></li></ul></div></div></nav><div class="container"><div class="header-section"><h1><i class="bi bi-lightning-fill"></i> EcoPulse</h1><p>Welcome, {{ current_user.username }}!</p>{% if current_user.role == 'admin' %}<span class="role-badge role-admin"><i class="bi bi-shield-fill"></i> Administrator</span>{% elif current_user.role == 'examiner' %}<span class="role-badge role-examiner"><i class="bi bi-eye-fill"></i> Examiner</span>{% else %}<span class="role-badge role-customer"><i class="bi bi-person-fill"></i> Customer</span>{% endif %}{% if current_user.employee_id %}<div class="employee-info"><i class="bi bi-building"></i> Employee ID: {{ current_user.employee_id }} | <i class="bi bi-diagram-3"></i> {{ current_user.department or 'General' }}</div>{% endif %}</div>{% if message %}<div class="alert alert-success"><i class="bi bi-check-circle"></i> {{ message }}</div>{% endif %}{% if analytics %}<div class="stats-grid"><div class="stat-card"><div class="stat-icon"><i class="bi bi-lightning-charge"></i></div><div class="stat-label">Total</div><div class="stat-value">{{ analytics.total_kwh }}</div><small>kWh</small></div><div class="stat-card"><div class="stat-icon"><i class="bi bi-graph-up"></i></div><div class="stat-label">Average</div><div class="stat-value">{{ analytics.avg_kwh }}</div><small>kWh</small></div><div class="stat-card"><div class="stat-icon"><i class="bi bi-cash-coin"></i></div><div class="stat-label">Total Cost</div><div class="stat-value">{{ analytics.currency }} {{ analytics.total_cost }}</div><small>Est.</small></div><div class="stat-card"><div class="stat-icon"><i class="bi bi-cloud"></i></div><div class="stat-label">CO2</div><div class="stat-value">{{ analytics.total_co2 }}</div><small>kg</small></div></div>{% endif %}<div class="card"><div class="card-header bg-primary"><i class="bi bi-plus-circle"></i> Add Reading</div><div class="card-body"><form method="POST" action="{{ url_for('add_reading') }}"><div class="row"><div class="col-md-4 mb-3"><label class="form-label">Month</label><input type="text" name="date" class="form-control" placeholder="e.g. January" required></div><div class="col-md-4 mb-3"><label class="form-label">kWh</label><input type="number" name="kwh" class="form-control" placeholder="e.g. 520" step="0.01" required></div><div class="col-md-4 mb-3"><label class="form-label">Timestamp</label><input type="datetime-local" name="timestamp" class="form-control" required></div></div><button type="submit" class="btn btn-success"><i class="bi bi-check-circle"></i> Submit</button></form></div></div><div class="row mb-4"><div class="col-md-6"><div class="card"><div class="card-header bg-info"><i class="bi bi-funnel"></i> Filter</div><div class="card-body"><form method="GET" action="{{ url_for('dashboard') }}" class="row g-3"><div class="col-md-4"><label class="form-label">Start</label><input type="date" name="start_date" class="form-control"></div><div class="col-md-4"><label class="form-label">End</label><input type="date" name="end_date" class="form-control"></div><div class="col-md-4"><label class="form-label">Days</label><select name="days" class="form-select"><option value="">All</option><option value="7">7 days</option><option value="30">30 days</option><option value="90">90 days</option></select></div><div class="col-md-12 mt-2"><button type="submit" class="btn btn-primary w-100">Filter</button></div></form></div></div></div><div class="col-md-6"><div class="card"><div class="card-header bg-warning"><i class="bi bi-send"></i> Submit to Admin</div><div class="card-body text-center"><p>Submit your consumption summary to admin for verification and comparison</p><button class="btn btn-warning w-100" onclick="submitToAdmin()"><i class="bi bi-send"></i> Submit My Consumption</button></div></div></div></div><div class="card"><div class="card-header bg-warning"><i class="bi bi-bar-chart"></i> Consumption Analysis</div><div class="card-body">{% if chart %}<img src="data:image/png;base64,{{ chart }}" class="img-fluid" alt="Consumption Chart">{% else %}<p class="no-data">No chart available. Add some readings to see visualization.</p>{% endif %}</div></div><div class="card"><div class="card-header bg-secondary"><i class="bi bi-table"></i> Readings</div><div class="card-body">{% if readings %}<div class="table-responsive"><table class="table table-hover"><thead><tr><th>Period</th><th>kWh</th><th>Cost</th><th>CO2</th><th>Status</th><th>Timestamp</th><th>Actions</th></tr></thead><tbody>{% for reading in readings %}<tr><td><strong>{{ reading.date }}</strong></td><td><span class="badge {% if reading.kwh > current_user.threshold %}bg-danger{% else %}bg-success{% endif %}">{{ reading.kwh }}</span></td><td>{{ "%.2f"|format(reading.kwh * current_user.unit_cost) }}</td><td>{{ "%.2f"|format(reading.kwh * 0.385) }}</td><td>{% if reading.is_approved %}<span class="badge bg-success">Approved</span>{% elif reading.is_reviewed %}<span class="badge bg-info">Reviewed</span>{% else %}<span class="badge bg-warning">Pending</span>{% endif %}</td><td><small>{{ reading.timestamp.strftime('%Y-%m-%d %H:%M') }}</small></td><td><button class="btn btn-warning btn-sm" data-bs-toggle="modal" data-bs-target="#editModal{{ reading.id }}"><i class="bi bi-pencil"></i></button><form method="POST" action="{{ url_for('delete_reading', reading_id=reading.id) }}" style="display: inline;" onsubmit="return confirm('Delete?');"><button type="submit" class="btn btn-danger btn-sm"><i class="bi bi-trash"></i></button></form></td></tr><div class="modal fade" id="editModal{{ reading.id }}" tabindex="-1"><div class="modal-dialog"><div class="modal-content"><div class="modal-header"><h5 class="modal-title">Edit</h5><button type="button" class="btn-close" data-bs-dismiss="modal"></button></div><form method="POST" action="{{ url_for('update_reading', reading_id=reading.id) }}"><div class="modal-body"><div class="mb-3"><label class="form-label">Period</label><input type="text" name="date" class="form-control" value="{{ reading.date }}" required></div><div class="mb-3"><label class="form-label">kWh</label><input type="number" name="kwh" class="form-control" value="{{ reading.kwh }}" step="0.01" required></div><div class="mb-3"><label class="form-label">Timestamp</label><input type="datetime-local" name="timestamp" class="form-control" value="{{ reading.timestamp.strftime('%Y-%m-%dT%H:%M') }}" required></div></div><div class="modal-footer"><button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancel</button><button type="submit" class="btn btn-success">Update</button></div></form></div></div></div>{% endfor %}</tbody></table></div>{% else %}<p class="no-data">No readings yet. Add your first reading above.</p>{% endif %}</div></div><div class="card"><div class="card-header bg-success"><i class="bi bi-download"></i> Export</div><div class="card-body"><div class="row g-3"><div class="col-md-6"><a href="{{ url_for('export_csv') }}" class="btn btn-success w-100"><i class="bi bi-file-earmark-spreadsheet"></i> CSV</a></div><div class="col-md-6"><a href="{{ url_for('export_pdf') }}" class="btn btn-danger w-100"><i class="bi bi-file-pdf"></i> PDF</a></div></div></div></div>{% if reports %}<div class="card"><div class="card-header bg-info"><i class="bi bi-envelope"></i> Recent Reports</div><div class="card-body"><div class="list-group">{% for report in reports %}<a href="#" class="list-group-item list-group-item-action"><div class="d-flex w-100 justify-content-between"><h6 class="mb-1">{{ report.title }}</h6><small>{{ report.created_at.strftime('%Y-%m-%d') }}</small></div><p class="mb-1">{{ report.content|safe }}</p></a>{% endfor %}</div></div></div>{% endif %}</div><script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script><script>const now=new Date();now.setMinutes(now.getMinutes()-now.getTimezoneOffset());const ts=document.querySelector('input[name="timestamp"]');if(ts)ts.value=now.toISOString().slice(0,16);function submitToAdmin(){fetch('/submit_to_admin',{method:'POST'}).then(r=>r.json()).then(d=>{alert(d.message);if(d.success){location.reload();}});}</script></body></html>"""

settings_template = """<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>Settings - EcoPulse</title><link rel="icon" type="image/svg+xml" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Crect width='64' height='64' rx='16' fill='%23062f2f'/%3E%3Cpath d='M35 6 18 34h11l-4 24 21-31H34z' fill='%23f59e0b'/%3E%3C/svg%3E"><link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css"><link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.0/font/bootstrap-icons.css"><style>body{background:linear-gradient(135deg, #667eea 0%, #764ba2 100%);min-height:100vh;font-family:'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;padding-top:80px;padding-bottom:30px}.navbar{background:linear-gradient(135deg, #667eea 0%, #764ba2 100%);box-shadow:0 5px 20px rgba(0,0,0,0.2)}.container{max-width:800px}.card{border:none;border-radius:15px;box-shadow:0 10px 30px rgba(0,0,0,0.2);margin-bottom:30px}.card-header{background:linear-gradient(135deg, #667eea 0%, #764ba2 100%);color:white;border-radius:15px 15px 0 0;padding:20px;font-weight:600;font-size:1.2rem}.card-body{padding:30px}.form-control,.form-select{border-radius:8px;border:2px solid #e0e0e0;padding:12px 15px}.form-control:focus,.form-select:focus{border-color:#667eea;box-shadow:0 0 0 0.2rem rgba(102,126,234,0.25)}.btn{border-radius:8px;padding:10px 20px;font-weight:600}.btn-primary{background:linear-gradient(135deg, #667eea 0%, #764ba2 100%);border:none;color:white}.btn-secondary{background:linear-gradient(135deg, #a4a4a4 0%, #797979 100%);border:none;color:white}.form-label{font-weight:600;color:#333}.settings-section{margin-bottom:30px;padding-bottom:30px;border-bottom:2px solid #e0e0e0}.settings-section:last-child{border-bottom:none}.settings-title{font-size:1.3rem;font-weight:700;color:#333;margin-bottom:20px;display:flex;align-items:center;gap:10px}</style></head><body><nav class="navbar navbar-expand-lg navbar-dark fixed-top"><div class="container"><a class="navbar-brand" href="{{ url_for('dashboard') }}"><i class="bi bi-lightning-fill"></i> EcoPulse</a><div class="navbar-nav ms-auto"><a class="nav-link" href="{{ url_for('dashboard') }}"><i class="bi bi-arrow-left"></i> Back</a></div></div></nav><div class="container"><div class="card"><div class="card-header"><i class="bi bi-gear"></i> Settings</div><div class="card-body">{% if message %}<div class="alert alert-success"><i class="bi bi-check-circle"></i> {{ message }}</div>{% endif %}<form method="POST"><div class="settings-section"><div class="settings-title"><i class="bi bi-speedometer2"></i> Threshold</div><div class="row"><div class="col-md-6 mb-3"><label class="form-label">Monthly (kWh)</label><input type="number" name="threshold" class="form-control" value="{{ current_user.threshold }}" step="10" required></div></div></div><div class="settings-section"><div class="settings-title"><i class="bi bi-cash-coin"></i> Cost</div><div class="row"><div class="col-md-6 mb-3"><label class="form-label">Currency</label><select name="currency" class="form-select"><option value="USD" {% if current_user.currency == 'USD' %}selected{% endif %}>USD</option><option value="EUR" {% if current_user.currency == 'EUR' %}selected{% endif %}>EUR</option><option value="GBP" {% if current_user.currency == 'GBP' %}selected{% endif %}>GBP</option><option value="INR" {% if current_user.currency == 'INR' %}selected{% endif %}>INR</option><option value="Ksh" {% if current_user.currency == 'Ksh' %}selected{% endif %}>Ksh</option></select></div><div class="col-md-6 mb-3"><label class="form-label">Cost/kWh</label><input type="number" name="unit_cost" class="form-control" value="{{ current_user.unit_cost }}" step="0.01" required></div></div></div><div class="settings-section"><div class="settings-title"><i class="bi bi-bell"></i> Alerts</div><div class="mb-3"><div class="form-check form-switch"><input class="form-check-input" type="checkbox" name="alert_email" id="alertEmail" {% if current_user.alert_email %}checked{% endif %}><label class="form-check-label" for="alertEmail">Email Alerts</label></div></div></div>{% if current_user.role in ['admin', 'examiner'] %}<div class="settings-section"><div class="settings-title"><i class="bi bi-building"></i> Employee Information</div><div class="row"><div class="col-md-6 mb-3"><label class="form-label">Employee ID</label><input type="text" class="form-control" value="{{ current_user.employee_id or 'Not assigned' }}" readonly></div><div class="col-md-6 mb-3"><label class="form-label">Department</label><input type="text" class="form-control" value="{{ current_user.department or 'Not specified' }}" readonly></div></div></div>{% endif %}<div class="d-flex gap-3"><button type="submit" class="btn btn-primary"><i class="bi bi-check-circle"></i> Save</button><a href="{{ url_for('dashboard') }}" class="btn btn-secondary"><i class="bi bi-x-circle"></i> Cancel</a></div></form></div></div></div><script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script></body></html>"""

examiner_template = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Examiner Dashboard - EcoPulse</title>
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
            background: linear-gradient(135deg, #f39c12 0%, #e67e22 100%);
            box-shadow: 0 5px 20px rgba(0,0,0,0.2);
        }
        .card {
            border: none;
            border-radius: 15px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.2);
            margin-bottom: 30px;
        }
        .card-header {
            background: linear-gradient(135deg, #f39c12 0%, #e67e22 100%);
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
            color: #f39c12;
        }
        .btn-warning {
            background: linear-gradient(135deg, #f39c12 0%, #e67e22 100%);
            border: none;
            color: white;
        }
        .btn-success {
            background: linear-gradient(135deg, #00b894 0%, #00cec9 100%);
            border: none;
            color: white;
        }
        .btn-info {
            background: linear-gradient(135deg, #3498db 0%, #2980b9 100%);
            border: none;
            color: white;
        }
        .btn-primary {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            border: none;
            color: white;
        }
        .report-preview {
            max-width: 100%;
            border-radius: 10px;
            box-shadow: 0 5px 15px rgba(0,0,0,0.2);
        }
        .status-badge {
            padding: 5px 10px;
            border-radius: 20px;
            font-size: 0.8rem;
            font-weight: 600;
        }
        .status-pending {
            background-color: #f39c12;
            color: white;
        }
        .status-reviewed {
            background-color: #3498db;
            color: white;
        }
        .status-approved {
            background-color: #00b894;
            color: white;
        }
        .status-rejected {
            background-color: #ff6b6b;
            color: white;
        }
    </style>
</head>
<body>
    <nav class="navbar navbar-expand-lg navbar-dark fixed-top">
        <div class="container">
            <a class="navbar-brand" href="{{ url_for('examiner_dashboard') }}">
                <i class="bi bi-clipboard-data"></i> EcoPulse Examiner
            </a>
            <div class="navbar-nav ms-auto">
                <a class="nav-link" href="{{ url_for('dashboard') }}">
                    <i class="bi bi-house"></i> Dashboard
                </a>
                <a class="nav-link" href="{{ url_for('logout') }}">
                    <i class="bi bi-box-arrow-right"></i> Logout
                </a>
            </div>
        </div>
    </nav>

    <div class="container">
        <div class="header-section text-center text-white mb-4">
            <h1><i class="bi bi-graph-up"></i> Examiner Dashboard</h1>
            <p>Review customer consumption and prepare reports for admin approval</p>
        </div>

        {% if message %}
        <div class="alert alert-success">{{ message }}</div>
        {% endif %}

        <!-- Summary Stats -->
        <div class="stats-grid">
            <div class="stat-card">
                <div class="stat-icon"><i class="bi bi-people fs-1 text-warning"></i></div>
                <div class="stat-value">{{ consumption_stats.total_customers }}</div>
                <div class="stat-label">Active Customers</div>
            </div>
            <div class="stat-card">
                <div class="stat-icon"><i class="bi bi-lightning fs-1 text-warning"></i></div>
                <div class="stat-value">{{ "%.0f"|format(consumption_stats.total_consumption) }}</div>
                <div class="stat-label">Total kWh</div>
            </div>
            <div class="stat-card">
                <div class="stat-icon"><i class="bi bi-cash fs-1 text-warning"></i></div>
                <div class="stat-value">Ksh {{ "%.0f"|format(consumption_stats.total_revenue) }}</div>
                <div class="stat-label">Est. Revenue</div>
            </div>
            <div class="stat-card">
                <div class="stat-icon"><i class="bi bi-cloud fs-1 text-warning"></i></div>
                <div class="stat-value">{{ "%.0f"|format(consumption_stats.total_co2) }}</div>
                <div class="stat-label">CO2 (kg)</div>
            </div>
        </div>

        <!-- Reading Stats Summary -->
        <div class="row mb-4">
            <div class="col-md-3">
                <div class="card bg-light">
                    <div class="card-body text-center">
                        <h5>Total Readings</h5>
                        <h3>{{ consumption_stats.total_readings }}</h3>
                    </div>
                </div>
            </div>
            <div class="col-md-3">
                <div class="card bg-light">
                    <div class="card-body text-center">
                        <h5>Reviewed</h5>
                        <h3 class="text-info">{{ consumption_stats.reviewed_count }}</h3>
                    </div>
                </div>
            </div>
            <div class="col-md-3">
                <div class="card bg-light">
                    <div class="card-body text-center">
                        <h5>Pending</h5>
                        <h3 class="text-warning">{{ consumption_stats.pending_count }}</h3>
                    </div>
                </div>
            </div>
            <div class="col-md-3">
                <div class="card bg-light">
                    <div class="card-body text-center">
                        <h5>Approved</h5>
                        <h3 class="text-success">{{ consumption_stats.approved_count }}</h3>
                    </div>
                </div>
            </div>
        </div>

        <!-- Main Action Buttons -->
        <div class="row mb-4">
            <div class="col-md-3">
                <div class="card">
                    <div class="card-header">
                        <i class="bi bi-bar-chart"></i> View Report
                    </div>
                    <div class="card-body text-center">
                        <p>Generate detailed consumption analysis</p>
                        <form method="POST" action="{{ url_for('view_consumption_report') }}">
                            <button type="submit" class="btn btn-info w-100">
                                <i class="bi bi-graph-up"></i> View Report
                            </button>
                        </form>
                    </div>
                </div>
            </div>

            <div class="col-md-3">
                <div class="card">
                    <div class="card-header">
                        <i class="bi bi-check-circle"></i> Review
                    </div>
                    <div class="card-body text-center">
                        <p>Review pending readings</p>
                        <a href="#pendingReadings" class="btn btn-warning w-100">
                            <i class="bi bi-eye"></i> Review ({{ pending_count }})
                        </a>
                    </div>
                </div>
            </div>

            <div class="col-md-3">
                <div class="card">
                    <div class="card-header">
                        <i class="bi bi-send"></i> Send to Admin
                    </div>
                    <div class="card-body text-center">
                        <p>Send all readings to admin</p>
                        <button class="btn btn-primary w-100" onclick="sendToAdmin()">
                            <i class="bi bi-send"></i> Send Report
                        </button>
                        <small class="text-muted">{{ consumption_stats.total_readings }} total readings</small>
                    </div>
                </div>
            </div>

            <div class="col-md-3">
                <div class="card">
                    <div class="card-header">
                        <i class="bi bi-download"></i> Export
                    </div>
                    <div class="card-body text-center">
                        <p>Export consumption data</p>
                        <a href="{{ url_for('export_csv') }}" class="btn btn-success w-100 mb-2">
                            <i class="bi bi-file-earmark-spreadsheet"></i> CSV
                        </a>
                        <a href="{{ url_for('export_pdf') }}" class="btn btn-danger w-100">
                            <i class="bi bi-file-pdf"></i> PDF
                        </a>
                    </div>
                </div>
            </div>
        </div>

        {% if consumption_report and consumption_report.chart %}
        <!-- Consumption Analysis Chart -->
        <div class="card">
            <div class="card-header">
                <i class="bi bi-bar-chart"></i> Customer Consumption Analysis
            </div>
            <div class="card-body">
                <img src="data:image/png;base64,{{ consumption_report.chart }}" class="img-fluid report-preview" alt="Consumption Report">

                <div class="row mt-4">
                    <div class="col-md-3">
                        <div class="card bg-light">
                            <div class="card-body text-center">
                                <h5>Total Customers</h5>
                                <h3>{{ consumption_report.summary.total_customers }}</h3>
                            </div>
                        </div>
                    </div>
                    <div class="col-md-3">
                        <div class="card bg-light">
                            <div class="card-body text-center">
                                <h5>Total Consumption</h5>
                                <h3>{{ "%.0f"|format(consumption_report.summary.total_consumption) }} kWh</h3>
                            </div>
                        </div>
                    </div>
                    <div class="col-md-3">
                        <div class="card bg-light">
                            <div class="card-body text-center">
                                <h5>Average per Customer</h5>
                                <h3>{{ "%.0f"|format(consumption_report.summary.average_consumption) }} kWh</h3>
                            </div>
                        </div>
                    </div>
                    <div class="col-md-3">
                        <div class="card bg-light">
                            <div class="card-body text-center">
                                <h5>Peak Consumption</h5>
                                <h3>{{ "%.0f"|format(consumption_report.summary.peak_consumption) }} kWh</h3>
                            </div>
                        </div>
                    </div>
                </div>

                <div class="row mt-3">
                    <div class="col-md-4">
                        <div class="card bg-light">
                            <div class="card-body text-center">
                                <h6>Efficient Customers</h6>
                                <h4 class="text-success">{{ consumption_report.summary.efficient_customers }}</h4>
                            </div>
                        </div>
                    </div>
                    <div class="col-md-4">
                        <div class="card bg-light">
                            <div class="card-body text-center">
                                <h6>Above Threshold</h6>
                                <h4 class="text-danger">{{ consumption_report.summary.above_threshold_count }}</h4>
                            </div>
                        </div>
                    </div>
                    <div class="col-md-4">
                        <div class="card bg-light">
                            <div class="card-body text-center">
                                <h6>Below Threshold</h6>
                                <h4 class="text-success">{{ consumption_report.summary.below_threshold_count }}</h4>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
        {% endif %}

        <!-- Pending Readings for Review -->
        <div class="card" id="pendingReadings">
            <div class="card-header">
                <i class="bi bi-clock-history"></i> Pending Readings for Review
            </div>
            <div class="card-body">
                {% if pending_readings %}
                <div class="table-responsive">
                    <table class="table table-hover">
                        <thead>
                            <tr>
                                <th>Customer</th>
                                <th>Period</th>
                                <th>kWh</th>
                                <th>Cost</th>
                                <th>Submitted</th>
                                <th>Actions</th>
                            </tr>
                        </thead>
                        <tbody>
                            {% for reading in pending_readings %}
                            <tr>
                                <td>{{ reading.user.username }}</td>
                                <td>{{ reading.date }}</td>
                                <td><span class="badge {% if reading.kwh > reading.user.threshold %}bg-danger{% else %}bg-success{% endif %}">{{ reading.kwh }}</span></td>
                                <td>Ksh {{ "%.2f"|format(reading.kwh * reading.user.unit_cost) }}</td>
                                <td><small>{{ reading.timestamp.strftime('%Y-%m-%d %H:%M') }}</small></td>
                                <td>
                                    <button class="btn btn-sm btn-info" onclick="reviewReading({{ reading.id }})">
                                        <i class="bi bi-eye"></i> Review
                                    </button>
                                </td>
                            </tr>

                            <!-- Review Modal -->
                            <div class="modal fade" id="reviewModal{{ reading.id }}" tabindex="-1">
                                <div class="modal-dialog">
                                    <div class="modal-content">
                                        <div class="modal-header">
                                            <h5 class="modal-title">Review Reading - {{ reading.user.username }}</h5>
                                            <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                                        </div>
                                        <form method="POST" action="{{ url_for('review_reading', reading_id=reading.id) }}">
                                            <div class="modal-body">
                                                <div class="mb-3">
                                                    <label class="form-label">Period</label>
                                                    <input type="text" class="form-control" value="{{ reading.date }}" readonly>
                                                </div>
                                                <div class="mb-3">
                                                    <label class="form-label">Consumption (kWh)</label>
                                                    <input type="number" class="form-control" value="{{ reading.kwh }}" readonly>
                                                </div>
                                                <div class="mb-3">
                                                    <label class="form-label">Calculated Cost</label>
                                                    <input type="text" class="form-control" value="Ksh {{ "%.2f"|format(reading.kwh * reading.user.unit_cost) }}" readonly>
                                                </div>
                                                <div class="mb-3">
                                                    <label class="form-label">Review Notes</label>
                                                    <textarea name="notes" class="form-control" rows="3" placeholder="Add your review notes..."></textarea>
                                                </div>
                                                <div class="mb-3">
                                                    <label class="form-label">Review Decision</label>
                                                    <div class="form-check">
                                                        <input class="form-check-input" type="radio" name="decision" value="approve" id="approve{{ reading.id }}" checked>
                                                        <label class="form-check-label" for="approve{{ reading.id }}">
                                                            <span class="text-success">✓ Approve - Ready for admin</span>
                                                        </label>
                                                    </div>
                                                    <div class="form-check">
                                                        <input class="form-check-input" type="radio" name="decision" value="reject" id="reject{{ reading.id }}">
                                                        <label class="form-check-label" for="reject{{ reading.id }}">
                                                            <span class="text-danger">✗ Reject - Needs correction</span>
                                                        </label>
                                                    </div>
                                                </div>
                                            </div>
                                            <div class="modal-footer">
                                                <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancel</button>
                                                <button type="submit" class="btn btn-primary">Submit Review</button>
                                            </div>
                                        </form>
                                    </div>
                                </div>
                            </div>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
                {% else %}
                <p class="text-center text-muted">No pending readings to review.</p>
                {% endif %}
            </div>
        </div>

        <!-- Reviewed Readings -->
        <div class="card">
            <div class="card-header">
                <i class="bi bi-check-circle"></i> Reviewed Readings
            </div>
            <div class="card-body">
                {% if reviewed_readings %}
                <div class="table-responsive">
                    <table class="table table-hover">
                        <thead>
                            <tr>
                                <th>Customer</th>
                                <th>Period</th>
                                <th>kWh</th>
                                <th>Review Notes</th>
                                <th>Reviewed At</th>
                                <th>Status</th>
                            </tr>
                        </thead>
                        <tbody>
                            {% for reading in reviewed_readings %}
                            <tr>
                                <td>{{ reading.user.username }}</td>
                                <td>{{ reading.date }}</td>
                                <td>{{ reading.kwh }}</td>
                                <td><small>{{ reading.review_notes or 'No notes' }}</small></td>
                                <td><small>{{ reading.reviewed_at.strftime('%Y-%m-%d %H:%M') if reading.reviewed_at }}</small></td>
                                <td>
                                    {% if reading.is_approved %}
                                        <span class="status-badge status-approved">Approved by Admin</span>
                                    {% else %}
                                        <span class="status-badge status-reviewed">Reviewed</span>
                                    {% endif %}
                                </td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
                {% else %}
                <p class="text-center text-muted">No reviewed readings yet.</p>
                {% endif %}
            </div>
        </div>

        <!-- All Readings -->
        <div class="card">
            <div class="card-header">
                <i class="bi bi-table"></i> All Readings
            </div>
            <div class="card-body">
                {% if all_readings %}
                <div class="table-responsive">
                    <table class="table table-hover">
                        <thead>
                            <tr>
                                <th>Customer</th>
                                <th>Period</th>
                                <th>kWh</th>
                                <th>Cost</th>
                                <th>Status</th>
                                <th>Reviewed By</th>
                                <th>Notes</th>
                                <th>Timestamp</th>
                            </tr>
                        </thead>
                        <tbody>
                            {% for reading in all_readings %}
                            <tr>
                                <td>{{ reading.user.username }}</td>
                                <td>{{ reading.date }}</td>
                                <td><span class="badge {% if reading.kwh > reading.user.threshold %}bg-danger{% else %}bg-success{% endif %}">{{ reading.kwh }}</span></td>
                                <td>Ksh {{ "%.2f"|format(reading.kwh * reading.user.unit_cost) }}</td>
                                <td>
                                    {% if reading.is_approved %}
                                        <span class="badge bg-success">Approved</span>
                                    {% elif reading.is_reviewed %}
                                        <span class="badge bg-info">Reviewed</span>
                                    {% else %}
                                        <span class="badge bg-warning">Pending</span>
                                    {% endif %}
                                </td>
                                <td>
                                    {% if reading.reviewer %}
                                        {{ reading.reviewer.username }}
                                    {% else %}
                                        -
                                    {% endif %}
                                </td>
                                <td><small>{{ reading.review_notes or '-' }}</small></td>
                                <td><small>{{ reading.timestamp.strftime('%Y-%m-%d %H:%M') }}</small></td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
                {% else %}
                <p class="text-center text-muted">No readings available.</p>
                {% endif %}
            </div>
        </div>

        <!-- Report History -->
        <div class="card">
            <div class="card-header">
                <i class="bi bi-clock-history"></i> Report History
            </div>
            <div class="card-body">
                <div class="table-responsive">
                    <table class="table table-hover">
                        <thead>
                            <tr>
                                <th>Date</th>
                                <th>Report Type</th>
                                <th>Total Customers</th>
                                <th>Total Consumption</th>
                                <th>Status</th>
                                <th>Actions</th>
                            </tr>
                        </thead>
                        <tbody>
                            {% for review in review_history %}
                            <tr>
                                <td>{{ review.created_at.strftime('%Y-%m-%d %H:%M') }}</td>
                                <td>Consumption Review</td>
                                <td>{{ review.total_customers }}</td>
                                <td>{{ "%.0f"|format(review.total_consumption) }} kWh</td>
                                <td>
                                    {% if review.status == 'approved' %}
                                        <span class="badge bg-success">Approved</span>
                                    {% elif review.status == 'pending_review' %}
                                        <span class="badge bg-warning">Pending Admin</span>
                                    {% else %}
                                        <span class="badge bg-info">Reviewed</span>
                                    {% endif %}
                                </td>
                                <td>
                                    <button class="btn btn-sm btn-info" onclick="viewDetails({{ review.id }})">
                                        <i class="bi bi-eye"></i>
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
        function reviewReading(readingId) {
            $('#reviewModal' + readingId).modal('show');
        }

        function sendToAdmin() {
            fetch('/send_review_to_admin', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                }
            })
            .then(response => response.json())
            .then(data => {
                alert(data.message);
                if (data.success) {
                    location.reload();
                }
            });
        }

        function viewDetails(reviewId) {
            window.open('/view_review/' + reviewId, '_blank');
        }
    </script>
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script>
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
            background-color: #ff6b6b;
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
        body { background: linear-gradient(180deg, #f3f7f6 0%, #ffffff 100%); color: #111827; }
        .navbar { backdrop-filter: blur(14px); background: rgba(6,47,47,0.88); }
        .hero { padding: 120px 0 72px; background: radial-gradient(circle at top left, rgba(15,118,110,0.18), transparent 40%), linear-gradient(135deg, #062f2f, #0f766e 60%, #d97706); color: white; }
        .section-card, .assistant-card { border: 0; border-radius: 24px; box-shadow: 0 20px 50px rgba(15,23,42,0.12); }
        .metric-tile { background: rgba(255,255,255,0.12); border-radius: 18px; padding: 18px; }
        .showcase-image { width: 100%; border-radius: 24px; min-height: 340px; object-fit: cover; box-shadow: 0 28px 48px rgba(0,0,0,0.24); }
        .map-frame { border: 0; width: 100%; min-height: 340px; border-radius: 24px; }
        footer { background: #041b1b; color: #d7ece8; }
        .assistant-scroll { max-height: 260px; overflow-y: auto; background: #f8fafc; border-radius: 16px; padding: 16px; }
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
                <div class="col-lg-6">
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
                <div class="col-lg-6"><img class="showcase-image" src="https://images.unsplash.com/photo-1513694203232-719a280e022f?auto=format&fit=crop&w=1200&q=80" alt="Smart home interior with connected technology"></div>
            </div>
        </div>
    </section>
    <section class="py-5">
        <div class="container">
            <div class="section-card card p-4 p-lg-5 mb-4">
                <div class="row g-4 align-items-center">
                    <div class="col-lg-6">
                        <span class="badge text-bg-success mb-3">Home Overview</span>
                        <h2 class="fw-bold">A cleaner, smarter way to manage energy from one place.</h2>
                        <p class="text-muted mb-0">EcoPulse brings smart-home visibility, billing workflows, efficiency guidance, and support tools into one platform for customers and staff.</p>
                    </div>
                    <div class="col-lg-6">
                        <div class="row g-3">
                            {% for stat in PUBLIC_HOME_STATS %}
                            <div class="col-sm-4"><div class="border rounded-4 p-3 h-100 text-center"><div class="fs-3 fw-bold text-success">{{ stat.value }}</div><div class="small text-muted">{{ stat.label }}</div></div></div>
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
                <div class="col-lg-4"><div class="section-card card p-4 h-100"><h3 class="fw-bold">Explore Features</h3><p class="text-muted">Real-time energy monitoring, automated efficiency suggestions, business-grade analytics, and sustainable living made simple.</p></div></div>
                <div class="col-lg-4"><div class="section-card card p-4 h-100"><h3 class="fw-bold">Careers</h3><p class="text-muted">Join a mission-driven team building IoT products, analytics workflows, and sustainability tools.</p><a href="{{ url_for('careers') }}" class="btn btn-outline-dark mt-2">Apply Now</a></div></div>
                <div class="col-lg-4"><div class="section-card card p-4 h-100"><h3 class="fw-bold">News</h3><p class="text-muted">Read the latest EcoPulse launches, partnerships, and practical insights on IoT and sustainability.</p><a href="{{ url_for('news') }}" class="btn btn-outline-dark mt-2">Read Updates</a></div></div>
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

public_content_template = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ page_title }}</title>
    <link rel="icon" type="image/svg+xml" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Crect width='64' height='64' rx='16' fill='%23062f2f'/%3E%3Cpath d='M35 6 18 34h11l-4 24 21-31H34z' fill='%23f59e0b'/%3E%3C/svg%3E">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css">
    <style>body{background:#f8fafc}.hero{background:linear-gradient(145deg,#062f2f,#0f766e 60%,#d97706);color:white;padding:110px 0 60px}.content-card{border:0;border-radius:24px;box-shadow:0 18px 42px rgba(15,23,42,0.08)}footer{background:#041b1b;color:#d7ece8}</style>
</head>
<body>
    <nav class="navbar navbar-expand-lg navbar-dark fixed-top" style="background:#062f2f;"><div class="container"><a class="navbar-brand fw-bold" href="{{ url_for('index') }}">EcoPulse</a><div class="navbar-nav ms-auto"><a class="nav-link" href="{{ url_for('index') }}">Home</a><a class="nav-link" href="{{ url_for('services') }}">Services</a><a class="nav-link" href="{{ url_for('careers') }}">Careers</a><a class="nav-link" href="{{ url_for('about') }}">About</a><a class="nav-link" href="{{ url_for('news') }}">News</a><a class="nav-link" href="{{ url_for('login') }}">Customer Login</a><a class="nav-link" href="{{ url_for('register') }}">Register</a><a class="nav-link" href="{{ url_for('staff_login') }}">Admin / Examiner Login</a></div></div></nav>
    <section class="hero"><div class="container"><span class="badge text-bg-light text-dark mb-3">{{ page_name }}</span><h1 class="display-5 fw-bold">{{ hero_title }}</h1><p class="lead col-lg-8">{{ hero_text }}</p></div></section>
    <section class="py-5"><div class="container"><div class="row g-4">{% for section in sections %}<div class="col-md-6"><div class="card content-card p-4 h-100"><h4>{{ section.title }}</h4><p class="text-muted mb-0">{{ section.text }}</p></div></div>{% endfor %}</div></div></section>
    <footer class="py-5"><div class="container"><div class="row"><div class="col-md-6"><h5>EcoPulse</h5><p class="mb-0">Energy monitoring, workflow visibility, and responsive customer support.</p></div><div class="col-md-6"><div class="d-flex flex-wrap gap-3 justify-content-md-end">{% for label, endpoint in footer_links %}<a class="text-decoration-none text-light" href="{{ url_for(endpoint) }}">{{ label }}</a>{% endfor %}</div></div></div><div class="d-flex justify-content-between align-items-center border-top border-secondary pt-3 mt-4 flex-wrap gap-2"><small>©2026 EcoPulse. All rights reserved.</small><small>Committed to a green future</small></div></div></footer>
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
    <style>body{background:linear-gradient(180deg,#f8fafc,#eef6f4)}.hero{background:linear-gradient(145deg,#062f2f,#0f766e 60%,#d97706);color:white;padding:110px 0 60px}.card{border:0;border-radius:24px;box-shadow:0 18px 42px rgba(15,23,42,0.08)}</style>
</head>
<body>
    <nav class="navbar navbar-expand-lg navbar-dark fixed-top" style="background:#062f2f;"><div class="container"><a class="navbar-brand fw-bold" href="{{ url_for('index') }}">EcoPulse</a><div class="navbar-nav ms-auto"><a class="nav-link" href="{{ url_for('index') }}">Home</a><a class="nav-link" href="{{ url_for('login') }}">Customer Login</a><a class="nav-link" href="{{ url_for('register') }}">Register</a><a class="nav-link" href="{{ url_for('staff_login') }}">Admin / Examiner Login</a></div></div></nav>
    <section class="hero"><div class="container"><h1 class="display-5 fw-bold">Get in touch with EcoPulse</h1><p class="lead">Use the contact information below for customer support, deployments, and partnership discussions.</p></div></section>
    <section class="py-5"><div class="container"><div class="row g-4"><div class="col-lg-5"><div class="card p-4 h-100"><h3>Contact details</h3><p><strong>Email:</strong> support@ecopulse.local</p><p><strong>Phone:</strong> +254 700 123 456</p><p><strong>Office:</strong> EcoPulse Centre, Kisii Town, Kenya</p><p><strong>Hours:</strong> Monday to Saturday, 8:00 AM to 6:00 PM</p>{% if contact_success %}<div class="alert alert-info mt-3 mb-0">{{ contact_success }}</div>{% endif %}</div></div><div class="col-lg-7"><div class="card p-4 mb-4"><h3>Send a message</h3><form method="POST" class="row g-3"><div class="col-md-6"><label class="form-label">Name</label><input class="form-control" name="name" required></div><div class="col-md-6"><label class="form-label">Email</label><input class="form-control" type="email" name="email" required></div><div class="col-12"><label class="form-label">Subject</label><input class="form-control" name="subject" required></div><div class="col-12"><label class="form-label">Message</label><textarea class="form-control" name="message" rows="5" required></textarea></div><div class="col-12"><button class="btn btn-dark" type="submit">Send Message</button></div></form></div><iframe class="w-100" style="min-height:380px;border:0;border-radius:24px;" loading="lazy" src="https://www.google.com/maps?q=Kisii%20Town%20Kenya&z=13&output=embed"></iframe></div></div><div class="d-flex justify-content-between align-items-center border-top pt-3 mt-4 flex-wrap gap-2"><small>©2026 EcoPulse. All rights reserved.</small><small>Committed to a green future</small></div></div></section>
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
    <style>body{background:linear-gradient(180deg,#eff6f3,#ffffff);padding-top:86px}.navbar{background:#062f2f}.card{border:0;border-radius:24px;box-shadow:0 18px 42px rgba(15,23,42,0.08)}.hero-strip{background:linear-gradient(135deg,#062f2f,#0f766e);color:white;border-radius:28px;padding:28px}</style>
</head>
<body>
    <nav class="navbar navbar-expand-lg navbar-dark fixed-top"><div class="container"><a class="navbar-brand fw-bold" href="{{ url_for('dashboard') }}">EcoPulse</a><button class="navbar-toggler" type="button" data-bs-toggle="collapse" data-bs-target="#dashNav"><span class="navbar-toggler-icon"></span></button><div class="collapse navbar-collapse" id="dashNav"><ul class="navbar-nav ms-auto"><li class="nav-item"><a class="nav-link" href="{{ url_for('settings') }}">Settings</a></li><li class="nav-item"><a class="nav-link" href="{{ url_for('logout') }}">Logout</a></li></ul></div></div></nav>
    <div class="container pb-5">
        <div class="hero-strip mb-4"><div class="row g-3 align-items-center"><div class="col-lg-8"><h1 class="h2 fw-bold mb-2">Welcome back, {{ current_user.username }}</h1><p class="mb-0">Track readings, manage threshold behavior, and review reports from EcoPulse operations.</p></div><div class="col-lg-4 text-lg-end"><span class="badge text-bg-light text-dark">Threshold {{ current_user.threshold }} kWh</span> <span class="badge text-bg-warning">{{ 'Overage enabled' if user_settings.allow_overage else 'Protect mode' }}</span></div></div></div>
        {% with messages = get_flashed_messages(with_categories=true) %}{% for category, msg in messages %}<div class="alert alert-{{ 'warning' if category == 'warning' else 'info' }}">{{ msg }}</div>{% endfor %}{% endwith %}
        <div class="row g-4 mb-4"><div class="col-md-3"><div class="card p-4 h-100"><small class="text-muted">Total kWh</small><h3 class="fw-bold mb-0">{{ analytics.total_kwh if analytics else 0 }}</h3></div></div><div class="col-md-3"><div class="card p-4 h-100"><small class="text-muted">Average</small><h3 class="fw-bold mb-0">{{ analytics.avg_kwh if analytics else 0 }}</h3></div></div><div class="col-md-3"><div class="card p-4 h-100"><small class="text-muted">Estimated Cost</small><h3 class="fw-bold mb-0">{{ analytics.currency if analytics else current_user.currency }} {{ analytics.total_cost if analytics else 0 }}</h3></div></div><div class="col-md-3"><div class="card p-4 h-100"><small class="text-muted">CO2</small><h3 class="fw-bold mb-0">{{ analytics.total_co2 if analytics else 0 }} kg</h3></div></div></div>
        <div class="row g-4 mb-4"><div class="col-lg-8"><div class="card p-4 h-100"><div class="d-flex justify-content-between align-items-center mb-3"><h3 class="h5 fw-bold mb-0">Add Reading</h3><a href="{{ url_for('settings') }}" class="btn btn-sm btn-outline-dark">Threshold Settings</a></div><form method="POST" action="{{ url_for('add_reading') }}" class="row g-3"><div class="col-md-4"><label class="form-label">Period</label><input type="text" name="date" class="form-control" placeholder="e.g. March 2026" required></div><div class="col-md-4"><label class="form-label">kWh</label><input type="number" name="kwh" step="0.01" class="form-control" required></div><div class="col-md-4"><label class="form-label">Timestamp</label><input type="datetime-local" name="timestamp" class="form-control" value="{{ now.strftime('%Y-%m-%dT%H:%M') }}" required></div><div class="col-12"><button type="submit" class="btn btn-dark">Save Reading</button></div></form></div></div><div class="col-lg-4"><div class="card p-4 h-100"><h3 class="h5 fw-bold">Threshold Behavior</h3><p class="text-muted">If overage is enabled, usage continues and extra units are billed with a surcharge. If protect mode is active, EcoPulse raises alerts and can schedule a shutdown reminder.</p>{% if threshold_state %}<div class="alert {{ 'alert-info' if threshold_state.allow_overage else 'alert-warning' }}">Latest reading: {{ threshold_state.latest_kwh }} kWh against {{ threshold_state.threshold }} kWh.{% if threshold_state.allow_overage %} Extra charge applied: {{ current_user.currency }} {{ "%.2f"|format(threshold_state.overage_charge) }}.{% elif threshold_state.scheduled_shutdown_at %} Auto shutdown scheduled for {{ threshold_state.scheduled_shutdown_at.strftime('%Y-%m-%d %H:%M') }}.{% endif %}</div>{% else %}<div class="alert alert-success mb-0">No threshold breach is active right now.</div>{% endif %}</div></div></div>
        <div class="row g-4 mb-4"><div class="col-lg-8"><div class="card p-4 h-100"><div class="d-flex justify-content-between align-items-center mb-3"><h3 class="h5 fw-bold mb-0">Consumption Analysis</h3><button class="btn btn-outline-dark" onclick="submitToAdmin()">Submit Summary to Admin</button></div>{% if chart %}<img src="data:image/png;base64,{{ chart }}" class="img-fluid rounded-4" alt="Consumption chart">{% else %}<p class="text-muted mb-0">Add readings to generate the customer analysis chart.</p>{% endif %}</div></div><div class="col-lg-4"><div class="card p-4 h-100"><h3 class="h5 fw-bold">Recent Reports</h3>{% if reports %}{% for report in reports %}<div class="border rounded-4 p-3 mb-3"><div class="fw-semibold">{{ report.title }}</div><small class="text-muted">{{ report.created_at.strftime('%Y-%m-%d') }}</small><div class="small mt-2">{{ report.content|safe }}</div></div>{% endfor %}{% else %}<p class="text-muted mb-0">No reports have been sent to your account yet.</p>{% endif %}</div></div></div>
        <div class="card p-4 mb-4"><div class="d-flex justify-content-between align-items-center mb-3"><h3 class="h5 fw-bold mb-0">Invoices</h3><span class="text-muted small">{{ customer_invoices|length }} record(s)</span></div>{% if customer_invoices %}<div class="table-responsive"><table class="table align-middle"><thead><tr><th>Period</th><th>Consumption</th><th>Total</th><th>Paid</th><th>Balance</th><th>Due Date</th><th>Status</th></tr></thead><tbody>{% for invoice in customer_invoices %}<tr><td>{{ invoice.period }}</td><td>{{ "%.2f"|format(invoice.total_consumption) }} kWh</td><td>{{ current_user.currency }} {{ "%.2f"|format(invoice.total_cost) }}</td><td>{{ current_user.currency }} {{ "%.2f"|format(invoice.total_paid) }}</td><td>{{ current_user.currency }} {{ "%.2f"|format(invoice.balance) }}</td><td>{{ invoice.due_date.strftime('%Y-%m-%d') if invoice.due_date else 'N/A' }}</td><td><span class="badge {% if invoice.payment_status == 'paid' %}text-bg-success{% elif invoice.payment_status == 'pending' %}text-bg-warning{% else %}text-bg-danger{% endif %} text-capitalize">{{ invoice.payment_status }}</span></td></tr>{% endfor %}</tbody></table></div>{% else %}<p class="text-muted mb-0">No invoices are available for your account yet.</p>{% endif %}</div>
        <div class="row g-4 mb-4"><div class="col-lg-6"><div class="card p-4 h-100"><h3 class="h5 fw-bold">Analytics</h3><p class="text-muted">Interactive trends help you understand how your usage changes over time and where savings opportunities are available.</p><ul class="mb-0"><li>Energy usage trends from your submitted readings</li><li>Estimated cost and CO2 visibility</li><li>Export-ready data for deeper review</li></ul></div></div><div class="col-lg-6"><div class="card p-4 h-100"><h3 class="h5 fw-bold">Devices</h3><p class="text-muted">Manage connected IoT devices and monitoring points from one place as your setup grows.</p><div class="row g-3"><div class="col-sm-6"><div class="border rounded-4 p-3 h-100"><small class="text-muted d-block">Connected Sensors</small><strong>{{ readings|length if readings else 0 }}</strong></div></div><div class="col-sm-6"><div class="border rounded-4 p-3 h-100"><small class="text-muted d-block">Protection Mode</small><strong>{{ 'Enabled' if not user_settings.allow_overage else 'Overage Billing' }}</strong></div></div></div></div></div></div>
        <div class="row g-4 mb-4"><div class="col-lg-6"><div class="card p-4 h-100"><h3 class="h5 fw-bold">Support</h3><p class="text-muted">Find help quickly with guidance for billing, thresholds, exports, and account setup.</p><ul class="mb-3"><li>FAQs for common customer questions</li><li>Troubleshooting guides for readings and alerts</li><li>Live support through the contact page and staff follow-up</li></ul><div class="d-flex gap-2 flex-wrap"><a class="btn btn-outline-dark" href="{{ url_for('contact') }}">Contact Support</a><a class="btn btn-outline-secondary" href="{{ url_for('faqs') }}">View FAQs</a></div></div></div><div class="col-lg-6"><div class="card p-4 h-100"><h3 class="h5 fw-bold">Community</h3><p class="text-muted">Learn from user stories, shared sustainability tips, and practical ideas for cutting waste.</p><ul class="mb-0"><li>User stories from homes and businesses</li><li>Shared efficiency tips and sustainability habits</li><li>Community-inspired improvements to monitoring routines</li></ul></div></div></div>
        <div class="card p-4"><div class="d-flex justify-content-between align-items-center mb-3"><h3 class="h5 fw-bold mb-0">Your Readings</h3><div class="d-flex gap-2"><a class="btn btn-outline-success btn-sm" href="{{ url_for('export_csv') }}">CSV</a><a class="btn btn-outline-danger btn-sm" href="{{ url_for('export_pdf') }}">PDF</a></div></div>{% if readings %}<div class="table-responsive"><table class="table align-middle"><thead><tr><th>Period</th><th>kWh</th><th>Cost</th><th>Status</th><th>Timestamp</th><th>Actions</th></tr></thead><tbody>{% for reading in readings %}<tr><td>{{ reading.date }}</td><td>{{ reading.kwh }}</td><td>{{ current_user.currency }} {{ "%.2f"|format(reading.cost or 0) }}</td><td>{% if reading.is_approved %}<span class="badge text-bg-success">Approved</span>{% elif reading.is_reviewed %}<span class="badge text-bg-info">Reviewed</span>{% else %}<span class="badge text-bg-warning">Pending</span>{% endif %}</td><td>{{ reading.timestamp.strftime('%Y-%m-%d %H:%M') }}</td><td><button class="btn btn-sm btn-outline-dark" data-bs-toggle="modal" data-bs-target="#editModal{{ reading.id }}">Edit</button> <form method="POST" action="{{ url_for('delete_reading', reading_id=reading.id) }}" class="d-inline" onsubmit="return confirm('Delete this reading?');"><button class="btn btn-sm btn-outline-danger">Delete</button></form></td></tr><div class="modal fade" id="editModal{{ reading.id }}" tabindex="-1"><div class="modal-dialog"><div class="modal-content"><form method="POST" action="{{ url_for('update_reading', reading_id=reading.id) }}"><div class="modal-header"><h5 class="modal-title">Edit Reading</h5><button type="button" class="btn-close" data-bs-dismiss="modal"></button></div><div class="modal-body"><div class="mb-3"><label class="form-label">Period</label><input class="form-control" name="date" value="{{ reading.date }}" required></div><div class="mb-3"><label class="form-label">kWh</label><input class="form-control" type="number" step="0.01" name="kwh" value="{{ reading.kwh }}" required></div><div class="mb-3"><label class="form-label">Timestamp</label><input class="form-control" type="datetime-local" name="timestamp" value="{{ reading.timestamp.strftime('%Y-%m-%dT%H:%M') }}" required></div></div><div class="modal-footer"><button type="submit" class="btn btn-dark">Save changes</button></div></form></div></div></div>{% endfor %}</tbody></table></div>{% else %}<p class="text-muted mb-0">No readings recorded yet.</p>{% endif %}</div>
    </div>
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script>
    <script>function submitToAdmin(){fetch('{{ url_for("submit_to_admin") }}',{method:'POST'}).then(response=>response.json()).then(data=>{alert(data.message);if(data.success)location.reload();});}</script>
</body>
</html>
"""

settings_template_v2 = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Settings - EcoPulse</title>
    <link rel="icon" type="image/svg+xml" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Crect width='64' height='64' rx='16' fill='%23062f2f'/%3E%3Cpath d='M35 6 18 34h11l-4 24 21-31H34z' fill='%23f59e0b'/%3E%3C/svg%3E">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css">
    <style>body{background:linear-gradient(180deg,#f8fafc,#eef6f4);padding-top:86px}.navbar{background:#062f2f}.card{border:0;border-radius:24px;box-shadow:0 18px 42px rgba(15,23,42,0.08)}</style>
</head>
<body>
    <nav class="navbar navbar-expand-lg navbar-dark fixed-top"><div class="container"><a class="navbar-brand" href="{{ url_for('dashboard') }}">EcoPulse</a><a class="btn btn-outline-light ms-auto" href="{{ url_for('dashboard') }}">Back</a></div></nav>
    <div class="container"><div class="card p-4"><h2 class="fw-bold">Customer Settings</h2><p class="text-muted">Set your threshold, choose overage behavior, and define how EcoPulse reacts when consumption passes the threshold.</p>{% if message %}<div class="alert alert-success">{{ message }}</div>{% endif %}<form method="POST" class="row g-4"><div class="col-md-4"><label class="form-label">Threshold (kWh)</label><input class="form-control" type="number" step="1" name="threshold" value="{{ current_user.threshold }}" required></div><div class="col-md-4"><label class="form-label">Currency</label><input class="form-control" name="currency" value="{{ current_user.currency }}" required></div><div class="col-md-4"><label class="form-label">Unit Cost</label><input class="form-control" type="number" step="0.01" name="unit_cost" value="{{ current_user.unit_cost }}" required></div><div class="col-12"><hr></div><div class="col-md-6"><div class="form-check form-switch fs-5"><input class="form-check-input" type="checkbox" name="allow_overage" id="allowOverage" {% if user_settings.allow_overage %}checked{% endif %}><label class="form-check-label" for="allowOverage">Allow over-threshold usage and bill extra charges</label></div><small class="text-muted">When enabled, service continues after the threshold and EcoPulse adds an overage surcharge.</small></div><div class="col-md-6"><div class="form-check form-switch fs-5"><input class="form-check-input" type="checkbox" name="auto_shutdown_enabled" id="autoShutdown" {% if user_settings.auto_shutdown_enabled %}checked{% endif %}><label class="form-check-label" for="autoShutdown">Automatic shutdown reminder when protect mode is active</label></div><small class="text-muted">When overage is off, EcoPulse sends alerts and schedules a 5-minute shutdown reminder.</small></div><div class="col-md-4"><label class="form-label">Shutdown Delay (minutes)</label><input class="form-control" type="number" min="1" name="shutdown_delay_minutes" value="{{ user_settings.shutdown_delay_minutes or 5 }}"></div><div class="col-md-4 d-flex align-items-end"><div class="form-check form-switch"><input class="form-check-input" type="checkbox" name="alert_email" id="alertEmail" {% if current_user.alert_email %}checked{% endif %}><label class="form-check-label" for="alertEmail">Email alerts</label></div></div><div class="col-12"><button class="btn btn-dark btn-lg" type="submit">Save Settings</button></div></form></div></div>
</body>
</html>
"""

examiner_template_v2 = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Examiner Dashboard - EcoPulse</title>
    <link rel="icon" type="image/svg+xml" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Crect width='64' height='64' rx='16' fill='%23062f2f'/%3E%3Cpath d='M35 6 18 34h11l-4 24 21-31H34z' fill='%23f59e0b'/%3E%3C/svg%3E">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css">
    <style>body{background:#fff8f0;padding-top:86px}.navbar{background:#92400e}.card{border:0;border-radius:24px;box-shadow:0 18px 42px rgba(15,23,42,0.08)}.assistant-scroll{max-height:220px;overflow-y:auto;background:#fff7ed;border-radius:16px;padding:16px}</style>
</head>
<body>
    <nav class="navbar navbar-expand-lg navbar-dark fixed-top"><div class="container"><a class="navbar-brand fw-bold" href="{{ url_for('examiner_dashboard') }}">EcoPulse Examiner</a><div class="navbar-nav ms-auto"><a class="nav-link" href="{{ url_for('logout') }}">Logout</a></div></div></nav>
    <div class="container pb-5">
        <div class="d-flex flex-column flex-lg-row justify-content-between align-items-lg-end mb-4"><div><h1 class="fw-bold">Examiner Dashboard</h1><p class="text-muted mb-0">Review readings, generate reports, and monitor the system-wide 10-year backcast and forecast.</p></div><div class="mt-3 mt-lg-0 d-flex gap-2"><form method="POST" action="{{ url_for('view_consumption_report') }}"><button class="btn btn-dark">Generate Report</button></form><button class="btn btn-outline-dark" onclick="sendToAdmin()">Send to Admin</button></div></div>
        {% with messages = get_flashed_messages(with_categories=true) %}{% for category, msg in messages %}<div class="alert alert-{{ 'warning' if category == 'warning' else 'info' }}">{{ msg }}</div>{% endfor %}{% endwith %}
        <div class="row g-4 mb-4"><div class="col-md-3"><div class="card p-4"><small class="text-muted">Active Customers</small><h3 class="fw-bold mb-0">{{ consumption_stats.total_customers }}</h3></div></div><div class="col-md-3"><div class="card p-4"><small class="text-muted">Total Consumption</small><h3 class="fw-bold mb-0">{{ "%.0f"|format(consumption_stats.total_consumption) }} kWh</h3></div></div><div class="col-md-3"><div class="card p-4"><small class="text-muted">Pending Reviews</small><h3 class="fw-bold mb-0">{{ consumption_stats.pending_count }}</h3></div></div><div class="col-md-3"><div class="card p-4"><small class="text-muted">Estimated Revenue</small><h3 class="fw-bold mb-0">Ksh {{ "%.0f"|format(consumption_stats.total_revenue) }}</h3></div></div></div>
        <div class="row g-4 mb-4"><div class="col-lg-8"><div class="card p-4 h-100"><h3 class="h5 fw-bold">10-Year Backcast and Forecast</h3><p class="text-muted">This view estimates previous and future annual consumption from the available system readings.</p><img src="data:image/png;base64,{{ prediction_payload.chart }}" class="img-fluid rounded-4" alt="Prediction chart"></div></div><div class="col-lg-4"><div class="card p-4 h-100"><h3 class="h5 fw-bold">Prediction Summary</h3><p class="mb-2"><strong>Current year:</strong> {{ prediction_payload.summary.current_year }}</p><p class="mb-2"><strong>Current total:</strong> {{ "%.2f"|format(prediction_payload.summary.current_total) }} kWh</p><p class="mb-2"><strong>Previous 10-year avg:</strong> {{ "%.2f"|format(prediction_payload.summary.previous_average) }} kWh</p><p class="mb-2"><strong>Next 10-year avg:</strong> {{ "%.2f"|format(prediction_payload.summary.next_average) }} kWh</p><p class="mb-0"><strong>Growth rate:</strong> {{ "%.2f"|format(prediction_payload.summary.growth_rate) }}%</p></div></div></div>
        <div class="row g-4 mb-4"><div class="col-lg-6"><div class="card p-4 h-100"><h3 class="h5 fw-bold">Examiner AI Forecast Assistant</h3><p class="text-muted">Enter an earlier range and a future range, up to 10 years each, to generate a graph and get review ideas.</p><div class="row g-3"><div class="col-md-6"><label class="form-label">Earlier Years</label><input id="examinerYearsBack" type="number" min="1" max="10" value="10" class="form-control"></div><div class="col-md-6"><label class="form-label">Next Years</label><input id="examinerYearsForward" type="number" min="1" max="10" value="10" class="form-control"></div></div><div id="examinerAssistantMessages" class="assistant-scroll mt-3"><div class="mb-2"><strong>EcoPulse AI:</strong> Ask about forecast risk, efficiency suggestions, or invoice advice.</div></div><div class="input-group mt-3"><input id="examinerAssistantInput" type="text" class="form-control" placeholder="What does the forecast suggest for the selected years?"><button id="examinerAssistantSend" class="btn btn-dark" type="button">Generate</button></div><div id="examinerAssistantSummary" class="small text-muted mt-3"></div><img id="examinerAssistantChart" class="img-fluid rounded-4 mt-3 d-none" alt="Examiner AI forecast chart"></div></div><div class="col-lg-6"><div class="card p-4 h-100"><h3 class="h5 fw-bold">Send Invoice to Customer</h3><form method="POST" action="{{ url_for('examiner_send_invoice') }}" class="row g-3"><div class="col-md-6"><label class="form-label">Customer</label><select class="form-select" name="customer_id" required><option value="">Select customer</option>{% for customer in customers %}<option value="{{ customer.id }}">{{ customer.username }}</option>{% endfor %}</select></div><div class="col-md-6"><label class="form-label">Period</label><input class="form-control" name="period" placeholder="e.g. 2026-03" required></div><div class="col-md-6"><label class="form-label">Consumption (kWh)</label><input class="form-control" type="number" step="0.01" name="total_consumption" required></div><div class="col-md-6"><label class="form-label">Total Cost</label><input class="form-control" type="number" step="0.01" name="total_cost" required></div><div class="col-md-6"><label class="form-label">Due Date</label><input class="form-control" type="date" name="due_date"></div><div class="col-md-6"><label class="form-label">Notes</label><input class="form-control" name="notes" placeholder="Optional invoice note"></div><div class="col-12"><button class="btn btn-dark" type="submit">Send Invoice</button></div></form></div></div></div>
        {% if consumption_report and consumption_report.chart %}<div class="card p-4 mb-4"><h3 class="h5 fw-bold">Detailed Consumption Analysis</h3><img src="data:image/png;base64,{{ consumption_report.chart }}" class="img-fluid rounded-4" alt="Examiner report"></div>{% endif %}
        <div class="card p-4 mb-4"><h3 class="h5 fw-bold">Pending Readings</h3>{% if pending_readings %}<div class="table-responsive"><table class="table align-middle"><thead><tr><th>Customer</th><th>Period</th><th>kWh</th><th>Cost</th><th>Submitted</th><th>Action</th></tr></thead><tbody>{% for reading in pending_readings %}<tr><td>{{ reading.user.username }}</td><td>{{ reading.date }}</td><td>{{ reading.kwh }}</td><td>Ksh {{ "%.2f"|format(reading.kwh * reading.user.unit_cost) }}</td><td>{{ reading.timestamp.strftime('%Y-%m-%d %H:%M') }}</td><td><button class="btn btn-sm btn-outline-dark" data-bs-toggle="modal" data-bs-target="#reviewModal{{ reading.id }}">Review</button></td></tr><div class="modal fade" id="reviewModal{{ reading.id }}" tabindex="-1"><div class="modal-dialog"><div class="modal-content"><form method="POST" action="{{ url_for('review_reading', reading_id=reading.id) }}"><div class="modal-header"><h5 class="modal-title">Review {{ reading.user.username }}</h5><button type="button" class="btn-close" data-bs-dismiss="modal"></button></div><div class="modal-body"><textarea class="form-control mb-3" name="notes" rows="4" placeholder="Review notes"></textarea><select class="form-select" name="decision"><option value="approve">Approve for admin review</option><option value="reject">Reject and request correction</option></select></div><div class="modal-footer"><button type="submit" class="btn btn-dark">Submit Review</button></div></form></div></div></div>{% endfor %}</tbody></table></div>{% else %}<p class="text-muted mb-0">No pending readings.</p>{% endif %}</div>
        <div class="card p-4 mb-4"><div class="d-flex justify-content-between align-items-center mb-3"><h3 class="h5 fw-bold mb-0">Customer Invoices</h3><span class="text-muted small">{{ examiner_invoices|length }} record(s)</span></div>{% if examiner_invoices %}<div class="table-responsive"><table class="table align-middle"><thead><tr><th>Customer</th><th>Period</th><th>Total</th><th>Paid</th><th>Balance</th><th>Due Date</th><th>Status</th></tr></thead><tbody>{% for invoice in examiner_invoices %}<tr><td>{{ invoice.user.username }}</td><td>{{ invoice.period }}</td><td>{{ invoice.user.currency }} {{ "%.2f"|format(invoice.total_cost) }}</td><td>{{ invoice.user.currency }} {{ "%.2f"|format(invoice.total_paid) }}</td><td>{{ invoice.user.currency }} {{ "%.2f"|format(invoice.balance) }}</td><td>{{ invoice.due_date.strftime('%Y-%m-%d') if invoice.due_date else 'N/A' }}</td><td><span class="badge {% if invoice.payment_status == 'paid' %}text-bg-success{% elif invoice.payment_status == 'pending' %}text-bg-warning{% else %}text-bg-danger{% endif %} text-capitalize">{{ invoice.payment_status }}</span></td></tr>{% endfor %}</tbody></table></div>{% else %}<p class="text-muted mb-0">No invoices have been generated yet.</p>{% endif %}</div>
        <div class="card p-4"><h3 class="h5 fw-bold">Prediction Timeline</h3><div class="table-responsive"><table class="table align-middle"><thead><tr><th>Year</th><th>kWh</th><th>Type</th></tr></thead><tbody>{% for item in prediction_payload.timeline %}<tr><td>{{ item.year }}</td><td>{{ "%.2f"|format(item.value) }}</td><td class="text-capitalize">{{ item.type }}</td></tr>{% endfor %}</tbody></table></div></div>
    </div>
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script>
    <script>function sendToAdmin(){fetch('{{ url_for("send_review_to_admin") }}',{method:'POST'}).then(response=>response.json()).then(data=>{alert(data.message);if(data.success)location.reload();});}async function askExaminerAssistant(){const input=document.getElementById('examinerAssistantInput');const messages=document.getElementById('examinerAssistantMessages');const yearsBack=Math.min(10,Math.max(1,parseInt(document.getElementById('examinerYearsBack').value||'10',10)));const yearsForward=Math.min(10,Math.max(1,parseInt(document.getElementById('examinerYearsForward').value||'10',10)));const message=input.value.trim()||'Give me ideas and advice for this selected forecast range.';messages.insertAdjacentHTML('beforeend',`<div class="mb-2"><strong>You:</strong> ${message} (${yearsBack} back, ${yearsForward} forward)</div>`);input.value='';const response=await fetch('{{ url_for("staff_assistant") }}',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message,years_back:yearsBack,years_forward:yearsForward})});const data=await response.json();messages.insertAdjacentHTML('beforeend',`<div class="mb-3"><strong>EcoPulse AI:</strong> ${data.answer}</div>`);messages.scrollTop=messages.scrollHeight;document.getElementById('examinerAssistantSummary').textContent=`Current year: ${data.summary.current_year} | Previous avg: ${data.summary.previous_average} kWh | Next avg: ${data.summary.next_average} kWh | Growth: ${data.summary.growth_rate}%`;const chart=document.getElementById('examinerAssistantChart');chart.src=`data:image/png;base64,${data.chart}`;chart.classList.remove('d-none');}document.getElementById('examinerAssistantSend').addEventListener('click',askExaminerAssistant);document.getElementById('examinerAssistantInput').addEventListener('keydown',event=>{if(event.key==='Enter'){event.preventDefault();askExaminerAssistant();}});</script>
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
    <style>body{background:#f8fafc;padding-top:86px}.navbar{background:#1f2937}.card{border:0;border-radius:24px;box-shadow:0 18px 42px rgba(15,23,42,0.08)}.assistant-scroll{max-height:220px;overflow-y:auto;background:#f8fafc;border-radius:16px;padding:16px}</style>
</head>
<body>
    <nav class="navbar navbar-expand-lg navbar-dark fixed-top"><div class="container"><a class="navbar-brand fw-bold" href="{{ url_for('admin_financial') }}">EcoPulse Admin</a><div class="navbar-nav ms-auto"><a class="nav-link" href="{{ url_for('logout') }}">Logout</a></div></div></nav>
    <div class="container pb-5">
        <div class="d-flex flex-column flex-lg-row justify-content-between align-items-lg-end mb-4"><div><h1 class="fw-bold">Admin Dashboard</h1><p class="text-muted mb-0">Approve examiner output, review financial records, and monitor 10-year system forecasts.</p></div><form method="POST" action="{{ url_for('send_customer_summaries') }}" class="mt-3 mt-lg-0"><button class="btn btn-dark">Send Customer Summaries</button></form></div>
        {% with messages = get_flashed_messages(with_categories=true) %}{% for category, msg in messages %}<div class="alert alert-{{ 'warning' if category == 'warning' else 'info' }}">{{ msg }}</div>{% endfor %}{% endwith %}
        <div class="row g-4 mb-4"><div class="col-md-3"><div class="card p-4"><small class="text-muted">Revenue</small><h3 class="fw-bold mb-0">Ksh {{ "%.2f"|format(financial.total_revenue) }}</h3></div></div><div class="col-md-3"><div class="card p-4"><small class="text-muted">Outstanding</small><h3 class="fw-bold mb-0">Ksh {{ "%.2f"|format(financial.total_outstanding) }}</h3></div></div><div class="col-md-3"><div class="card p-4"><small class="text-muted">Collected</small><h3 class="fw-bold mb-0">Ksh {{ "%.2f"|format(financial.total_collected) }}</h3></div></div><div class="col-md-3"><div class="card p-4"><small class="text-muted">Payment Rate</small><h3 class="fw-bold mb-0">{{ "%.1f"|format(financial.payment_rate) }}%</h3></div></div></div>
        <div class="row g-4 mb-4"><div class="col-lg-8"><div class="card p-4 h-100"><h3 class="h5 fw-bold">10-Year Backcast and Forecast</h3><img src="data:image/png;base64,{{ prediction_payload.chart }}" class="img-fluid rounded-4" alt="Prediction chart"></div></div><div class="col-lg-4"><div class="card p-4 h-100"><h3 class="h5 fw-bold">Forecast Summary</h3><p class="mb-2"><strong>Current year:</strong> {{ prediction_payload.summary.current_year }}</p><p class="mb-2"><strong>Current total:</strong> {{ "%.2f"|format(prediction_payload.summary.current_total) }} kWh</p><p class="mb-2"><strong>Previous average:</strong> {{ "%.2f"|format(prediction_payload.summary.previous_average) }} kWh</p><p class="mb-2"><strong>Next average:</strong> {{ "%.2f"|format(prediction_payload.summary.next_average) }} kWh</p><p class="mb-0"><strong>Growth rate:</strong> {{ "%.2f"|format(prediction_payload.summary.growth_rate) }}%</p></div></div></div>
        <div class="card p-4 mb-4"><h3 class="h5 fw-bold">Admin AI Forecast Assistant</h3><p class="text-muted">Enter an earlier range and a future range, up to 10 years each, to generate a graph and receive planning advice.</p><div class="row g-3"><div class="col-md-6"><label class="form-label">Earlier Years</label><input id="adminYearsBack" type="number" min="1" max="10" value="10" class="form-control"></div><div class="col-md-6"><label class="form-label">Next Years</label><input id="adminYearsForward" type="number" min="1" max="10" value="10" class="form-control"></div></div><div id="adminAssistantMessages" class="assistant-scroll mt-3"><div class="mb-2"><strong>EcoPulse AI:</strong> Ask about future demand, outstanding balances, or operational advice.</div></div><div class="input-group mt-3"><input id="adminAssistantInput" type="text" class="form-control" placeholder="What should I focus on for the selected forecast years?"><button id="adminAssistantSend" class="btn btn-dark" type="button">Generate</button></div><div id="adminAssistantSummary" class="small text-muted mt-3"></div><img id="adminAssistantChart" class="img-fluid rounded-4 mt-3 d-none" alt="Admin AI forecast chart"></div>
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
    <style>body{background:#f8fafc;padding-top:86px}.navbar{background:#1f2937}.card{border:0;border-radius:24px;box-shadow:0 18px 42px rgba(15,23,42,0.08)}</style>
</head>
<body>
    <nav class="navbar navbar-expand-lg navbar-dark fixed-top"><div class="container"><a class="navbar-brand fw-bold" href="{{ url_for('admin_financial') }}">EcoPulse Admin</a><div class="navbar-nav ms-auto"><a class="nav-link" href="{{ url_for('admin_financial') }}">Dashboard</a><a class="nav-link" href="{{ url_for('logout') }}">Logout</a></div></div></nav>
    <div class="container pb-5">
        <div class="d-flex justify-content-between align-items-end mb-4"><div><h1 class="fw-bold">Contact Messages</h1><p class="text-muted mb-0">Messages submitted from the public Get in Touch page.</p></div></div>
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

error_page = """<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>Error - EcoPulse</title><link rel="icon" type="image/svg+xml" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Crect width='64' height='64' rx='16' fill='%23062f2f'/%3E%3Cpath d='M35 6 18 34h11l-4 24 21-31H34z' fill='%23f59e0b'/%3E%3C/svg%3E"><link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css"><link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.0/font/bootstrap-icons.css"><style>body{background:linear-gradient(135deg, #667eea 0%, #764ba2 100%);min-height:100vh;display:flex;align-items:center;justify-content:center;font-family:'Segoe UI', Tahoma, Geneva, Verdana, sans-serif}.error-container{max-width:500px;padding:20px}.card{border:none;border-radius:15px;box-shadow:0 10px 40px rgba(0,0,0,0.3)}.card-header{background:linear-gradient(135deg, #ff6b6b 0%, #ee5a6f 100%);color:white;border-radius:15px 15px 0 0;padding:30px;text-align:center}</style></head><body><div class="error-container"><div class="card"><div class="card-header"><h2><i class="bi bi-exclamation-triangle"></i> Access Denied</h2></div><div class="card-body p-5 text-center"><p class="lead">{{ error }}</p><a href="{{ url_for('dashboard') }}" class="btn btn-primary mt-3">Go to Dashboard</a></div></div></div></body></html>"""


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
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        role = 'customer'
        department = None

        if not username or not email or not password:
            return render_template_string(register_page, error='All fields required')
        if password != confirm_password:
            return render_template_string(register_page, error='Passwords do not match')
        if User.query.filter_by(username=username).first():
            return render_template_string(register_page, error='Username exists')
        if User.query.filter_by(email=email).first():
            return render_template_string(register_page, error='Email registered')

        user = User(username=username, email=email, role=role, department=department)
        user.set_password(password)

        db.session.add(user)
        db.session.flush()
        settings = UserSettings(user_id=user.id, alert_threshold=user.threshold)
        db.session.add(settings)

        db.session.commit()

        log_system_action(user.id, f"User registered as {role}")

        return redirect(url_for('login'))
    return render_template_string(register_page)


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username, role='customer').first()

        if user and user.check_password(password):
            login_user(user)
            log_system_action(user.id, "Customer logged in")
            return redirect(url_for('dashboard'))

        return render_template_string(login_page, error='Invalid credentials')
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
    pending_submission = CustomerSubmission.query.filter_by(customer_id=current_user.id, status='pending').first()
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

    return render_template_string(customer_dashboard_template_v2,
                                  readings=readings,
                                  analytics=analytics,
                                  chart=chart,
                                  reports=reports,
                                  customer_invoices=customer_invoices,
                                  pending_submission=pending_submission,
                                  user_settings=user_settings,
                                  threshold_state=threshold_state,
                                  now=datetime.utcnow(),
                                  footer_links=PUBLIC_FOOTER_LINKS)


@app.route('/examiner_dashboard')
@login_required
@examiner_required
def examiner_dashboard():
    customers = User.query.filter_by(role='customer').all()
    readings = Reading.query.all()
    total_customers = len([c for c in customers if c.readings])
    total_consumption = sum(r.kwh for r in readings)
    total_revenue = sum(r.kwh * User.query.get(r.user_id).unit_cost for r in readings)
    total_co2 = sum(r.kwh * 0.385 for r in readings)

    consumption_stats = {
        'total_customers': total_customers,
        'total_consumption': total_consumption,
        'total_revenue': total_revenue,
        'total_co2': total_co2,
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

    return render_template_string(examiner_template_v2,
                                  consumption_stats=consumption_stats,
                                  pending_readings=pending_readings,
                                  pending_count=pending_count,
                                  reviewed_readings=reviewed_readings,
                                  all_readings=all_readings,
                                  customers=customers,
                                  review_history=review_history,
                                  consumption_report=None,
                                  examiner_invoices=examiner_invoices,
                                  prediction_payload=prediction_payload)


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

    return render_template_string(examiner_template_v2,
                                  consumption_stats=consumption_stats,
                                  pending_readings=pending_readings,
                                  pending_count=pending_count,
                                  reviewed_readings=reviewed_readings,
                                  all_readings=all_readings,
                                  customers=customers,
                                  review_history=review_history,
                                  consumption_report=consumption_report,
                                  examiner_invoices=examiner_invoices,
                                  prediction_payload=prediction_payload)


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

    return render_template_string(admin_financial_template_v2,
                                  financial=financial,
                                  financial_records=financial_records,
                                  examiner_reports=examiner_reports,
                                  pending_reviews=pending_reviews,
                                  prediction_payload=prediction_payload,
                                  contact_messages=contact_messages)


@app.route('/admin/contact-messages')
@login_required
@admin_required
def admin_contact_messages():
    messages = ContactMessage.query.order_by(ContactMessage.created_at.desc()).all()
    return render_template_string(admin_contact_messages_template, messages=messages)


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
        timestamp = datetime.fromisoformat(timestamp_str) if timestamp_str else datetime.utcnow()
        user_settings = get_or_create_user_settings(current_user)
        cost, overage_charge = calculate_reading_cost(current_user, user_settings, kwh)

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

            if getattr(current_user, 'alert_email', False) and getattr(current_user, 'email', None):
                subject = "EcoPulse Energy Threshold Alert"
                html_body = f"""
                <h2>Energy Threshold Exceeded</h2>
                <p>Dear {current_user.username},</p>
                <p>Your latest reading for <strong>{date}</strong> is <strong>{kwh:.2f} kWh</strong>.</p>
                <p>This exceeds your configured threshold of <strong>{current_user.threshold:.2f} kWh</strong>.</p>
                <p>{'Overage mode is enabled, so billing continues with extra charges.' if user_settings.allow_overage else 'Protect mode is enabled, so EcoPulse has scheduled an automatic shutdown reminder.'}</p>
                """
                ok, err = send_email_notification(current_user.email, subject, html_body)
                if not ok:
                    print(f"Email alert failed: {err}")
        else:
            user_settings.scheduled_shutdown_at = None

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
        reading.cost = reading.kwh * current_user.unit_cost
        reading.timestamp = datetime.fromisoformat(request.form.get('timestamp'))
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


@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    user_settings = get_or_create_user_settings(current_user)
    message = None

    if request.method == 'POST':
        current_user.threshold = float(request.form.get('threshold'))
        current_user.currency = request.form.get('currency')
        current_user.unit_cost = float(request.form.get('unit_cost'))
        current_user.alert_email = 'alert_email' in request.form
        user_settings.alert_threshold = current_user.threshold
        user_settings.allow_overage = 'allow_overage' in request.form
        user_settings.auto_shutdown_enabled = 'auto_shutdown_enabled' in request.form
        user_settings.shutdown_delay_minutes = int(request.form.get('shutdown_delay_minutes') or 5)
        db.session.commit()
        message = "Settings updated."
        log_system_action(current_user.id, "Updated settings")

    return render_template_string(settings_template_v2, user_settings=user_settings, message=message)


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
    print(f"   Customer: username: {customer_username}, password: {customer_password}")
    print("\n Access the application at: http://localhost:5000")
    print("\n" + "=" * 70 + "\n")

    app.run(debug=True, host='0.0.0.0', port=5000)
