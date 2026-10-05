# EcoPulse Feature Roadmap

## Overview
This document provides a structured implementation guide for adding new features to EcoPulse without disrupting existing functionality. All features are designed to integrate seamlessly with the current Flask application.

---

## 🎯 PHASE 1: USER EXPERIENCE FEATURES

### 1.1 Interactive Dashboard
**Status:** Enhancement to existing dashboard  
**Integration Points:** Current dashboard at `/dashboard` route

#### What to Add:
```python
# Add to User model
class User(UserMixin, db.Model):
    # Existing fields...
    dashboard_widgets = db.relationship('DashboardWidget', 
                                       back_populates='user',
                                       cascade='all, delete-orphan')
    chart_preferences = db.Column(db.JSON, default={
        'show_hourly': True,
        'show_daily': True,
        'show_weekly': True,
        'comparison_enabled': True
    })
```

#### New Models Needed:
```python
class DashboardWidget(db.Model):
    __tablename__ = 'dashboard_widgets'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    widget_type = db.Column(db.String(50))  # 'energy_usage', 'savings', 'comparison'
    position = db.Column(db.Integer)
    enabled = db.Column(db.Boolean, default=True)
    user = db.relationship('User', back_populates='dashboard_widgets')
```

#### Frontend Components:
- Real-time chart updates using Chart.js or Plotly
- WebSocket integration for live data (optional)
- Comparison widget: Current day vs last week/month
- Savings calculator display

#### New Routes:
```
GET  /api/dashboard/charts/hourly
GET  /api/dashboard/charts/daily
GET  /api/dashboard/charts/weekly
GET  /api/dashboard/savings
POST /api/dashboard/widgets/reorder
```

---

### 1.2 Personalized Tips (AI-driven Suggestions)
**Status:** New feature  
**Dependencies:** Energy usage patterns

#### New Models:
```python
class EnergyTip(db.Model):
    __tablename__ = 'energy_tips'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    title = db.Column(db.String(200))
    description = db.Column(db.Text)
    potential_savings = db.Column(db.Float)  # Percentage
    category = db.Column(db.String(50))  # 'laundry', 'heating', 'appliances'
    generated_at = db.Column(db.DateTime, default=datetime.utcnow)
    dismissed = db.Column(db.Boolean, default=False)
    user = db.relationship('User')
```

#### Logic Module (`modules/tip_engine.py`):
```python
class TipEngine:
    """
    AI-driven suggestion engine
    Analyzes patterns and generates contextual tips
    """
    
    @staticmethod
    def analyze_usage_patterns(user_id):
        # Identify peak usage times
        # Find expensive operations
        # Generate suggestions
        pass
    
    @staticmethod
    def get_time_based_tip(hour, usage_level):
        # Example: "Run laundry at 9 PM to save 15% energy"
        pass
    
    @staticmethod
    def calculate_potential_savings(tip_id):
        pass
```

#### New Routes:
```
GET  /api/tips/personalized
GET  /api/tips/today
POST /api/tips/{id}/dismiss
GET  /api/tips/savings-estimate
```

---

### 1.3 Mobile Responsiveness
**Status:** CSS/Layout enhancement  
**Integration:** Update existing templates

#### What to Add:
```css
/* Add to base.css */
@media (max-width: 768px) {
    /* Mobile-specific styles */
    .dashboard-grid {
        grid-template-columns: 1fr;  /* Single column on mobile */
    }
    .chart-container {
        height: 300px;  /* Reduce height */
    }
    .navigation {
        display: flex;
        flex-direction: column;  /* Stack menu items */
    }
}

/* Touch-friendly buttons and controls */
button, a.btn {
    min-height: 44px;  /* Apple's HIG standard */
    min-width: 44px;
    padding: 12px;
}
```

#### Framework Update:
- Add Bootstrap 5 (if not present) with mobile-first approach
- Update templates with responsive breakpoints
- Add viewport meta tag to base template

---

### 1.4 Gamification
**Status:** New feature  
**Integration Points:** User model, dashboard

#### New Models:
```python
class UserBadge(db.Model):
    __tablename__ = 'user_badges'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    badge_type = db.Column(db.String(50))
    earned_at = db.Column(db.DateTime, default=datetime.utcnow)
    user = db.relationship('User')

class UserPoints(db.Model):
    __tablename__ = 'user_points'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), unique=True)
    total_points = db.Column(db.Integer, default=0)
    points_this_month = db.Column(db.Integer, default=0)
    last_updated = db.Column(db.DateTime, default=datetime.utcnow)
    user = db.relationship('User')
```

#### Badge System:
```python
BADGE_CRITERIA = {
    'eco_warrior': {'condition': 'total_savings > 100', 'icon': '🌍'},
    'energy_saver': {'condition': 'monthly_reduction > 20%', 'icon': '⚡'},
    'night_owl': {'condition': 'off_peak_usage > 60%', 'icon': '🌙'},
    'solar_champion': {'condition': 'solar_usage > 80%', 'icon': '☀️'},
    'consistency_king': {'condition': 'consecutive_days_below_target > 30', 'icon': '👑'},
}

POINT_RULES = {
    'daily_below_target': 10,
    'weekly_improvement': 25,
    'tip_implemented': 15,
    'data_shared': 20,
    'milestone_reached': 50,
}
```

#### New Routes:
```
GET  /api/gamification/badges
GET  /api/gamification/points
GET  /api/gamification/leaderboard
POST /api/gamification/claim-points
```

---

### 1.5 Community Sharing
**Status:** New feature  
**Integration Points:** User accounts, readings

#### New Models:
```python
class HouseholdGroup(db.Model):
    __tablename__ = 'household_groups'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))
    region = db.Column(db.String(50))  # For neighborhood comparison
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    members = db.relationship('User', secondary='group_members')

class GroupComparison(db.Model):
    __tablename__ = 'group_comparisons'
    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey('household_groups.id'))
    period = db.Column(db.String(20))  # 'daily', 'weekly', 'monthly'
    comparison_data = db.Column(db.JSON)  # Anonymized comparison data
    generated_at = db.Column(db.DateTime, default=datetime.utcnow)
```

#### Sharing Features:
```python
class CommunitySharing:
    @staticmethod
    def get_regional_average(region, period):
        """Get anonymous regional energy usage average"""
        pass
    
    @staticmethod
    def get_household_comparison(user_id, group_id):
        """Compare household to similar households"""
        pass
    
    @staticmethod
    def generate_share_report(user_id):
        """Create shareable consumption report"""
        pass
```

#### New Routes:
```
GET  /api/community/groups
POST /api/community/groups/join
GET  /api/community/comparison/{region}
GET  /api/community/rankings
POST /api/community/share-report
```

---

## ⚙️ PHASE 2: TECHNICAL FEATURES

### 2.1 IoT Integration
**Status:** New feature  
**Integration:** Device management already exists

#### Extend Existing `CustomerDevice` Model:
```python
class CustomerDevice(db.Model):
    # Existing fields...
    device_type = db.Column(db.String(50))  # 'smart_plug', 'meter', 'solar_panel'
    api_key = db.Column(db.String(200))  # For device authentication
    connection_status = db.Column(db.String(20), default='disconnected')
    last_sync = db.Column(db.DateTime)
    raw_data = db.relationship('IoTData', back_populates='device')

class IoTData(db.Model):
    __tablename__ = 'iot_data'
    id = db.Column(db.Integer, primary_key=True)
    device_id = db.Column(db.Integer, db.ForeignKey('customer_devices.id'))
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    value = db.Column(db.Float)  # Energy reading
    unit = db.Column(db.String(10))  # 'kWh', 'W'
    device = db.relationship('CustomerDevice', back_populates='raw_data')
```

#### New Module (`modules/iot_handler.py`):
```python
class IoTHandler:
    """
    Handles connections and data ingestion from smart devices
    Supports various device types and protocols
    """
    
    @staticmethod
    def register_device(user_id, device_type, api_key):
        pass
    
    @staticmethod
    def ingest_live_data(device_id, data_payload):
        """Process live data from IoT devices"""
        pass
    
    @staticmethod
    def verify_device_connection(device_id):
        pass
    
    @staticmethod
    def get_device_status(device_id):
        pass

# Support for common platforms:
IoT_PLATFORMS = {
    'smart_plugs': ['TP-Link', 'Philips Hue', 'Shelly'],
    'meters': ['Schneider Electric', 'Siemens'],
    'solar': ['SMA', 'Fronius', 'Tesla Powerwall'],
}
```

#### New Routes:
```
POST /api/iot/register-device
POST /api/iot/sync-data
GET  /api/iot/device-status/{device_id}
GET  /api/iot/live-readings/{device_id}
DELETE /api/iot/device/{device_id}
```

---

### 2.2 Forecasting & Alerts
**Status:** New feature  
**Dependencies:** Historical usage data

#### New Models:
```python
class UsageForecast(db.Model):
    __tablename__ = 'usage_forecasts'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    forecast_date = db.Column(db.Date)
    predicted_usage = db.Column(db.Float)
    confidence_level = db.Column(db.Float)  # 0-100%
    risk_alert = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class AlertRule(db.Model):
    __tablename__ = 'alert_rules'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    rule_type = db.Column(db.String(50))  # 'threshold', 'anomaly', 'forecast'
    threshold_value = db.Column(db.Float)
    alert_method = db.Column(db.String(20))  # 'email', 'sms', 'push'
    enabled = db.Column(db.Boolean, default=True)
```

#### Forecasting Module (`modules/forecasting.py`):
```python
from sklearn.linear_model import LinearRegression
from sklearn.preprocessing import StandardScaler

class ForecastingEngine:
    """
    Predicts future energy usage based on historical patterns
    """
    
    @staticmethod
    def predict_daily_usage(user_id, days_ahead=7):
        """Predict next 7 days of usage"""
        pass
    
    @staticmethod
    def detect_anomaly(user_id):
        """Identify unusual consumption patterns"""
        pass
    
    @staticmethod
    def send_alert(user_id, alert_type, message):
        """Trigger alerts for high-usage predictions"""
        pass
    
    @staticmethod
    def calculate_bill_spike_probability(user_id):
        """Estimate probability of bill spike"""
        pass
```

#### Alert System:
```python
ALERT_TYPES = {
    'high_usage': 'Predicted high usage on {date}',
    'bill_spike': 'Bill may spike by {percentage}% this month',
    'anomaly': 'Unusual consumption detected',
    'maintenance': 'Solar panel efficiency dropped',
    'threshold': 'Usage exceeded threshold by {amount} kWh',
}
```

#### New Routes:
```
GET  /api/forecast/weekly
GET  /api/forecast/bill-estimate
GET  /api/forecast/anomalies
POST /api/alerts/rules
GET  /api/alerts/active
DELETE /api/alerts/rules/{id}

---

## 🌐 PHASE 3: ECOSYSTEM & TRUST FEATURES

### 3.1 Security & Privacy
**Status:** Planned
**Goal:** End-to-end encryption, comprehensive audit logs, and examiner validation flows for tariff changes.

#### What to Add:
- End-to-end encryption for sensitive data at-rest and in-transit (TLS + field-level encryption for tariffs and finance records)
- AuditLog model to record user actions (who, what, when, ip, changes)
- Examiner validation workflow for tariff publication (draft -> examiner_review -> approved)
- Routes:
```
GET  /api/audit/logs
POST /api/tariffs/{id}/submit-for-review
POST /api/tariffs/{id}/approve  # examiner only
```

---

### 3.2 Customer Support
**Status:** Planned
**Goal:** Integrate live chat support, searchable FAQs, and a ticketing system for escalations.

#### What to Add:
- Live chat backend (socket-based or third-party integration)
- FAQ model and searchable UI
- Ticket model and triage workflow (status, priority, assignee)
- Routes:
```
GET  /support/faqs
POST /support/tickets
GET  /support/tickets/{id}
POST /support/tickets/{id}/assign
```

---

### 3.3 Partnerships & Integrations
**Status:** Planned
**Goal:** Offer stable APIs and onboarding flows for schools, businesses, and NGOs to integrate with EcoPulse.

#### What to Add:
- Public API keys and partner management dashboard
- API endpoints for bulk user sync, impact reporting, and authentication (OAuth2/client credentials)
- Partner sandbox mode and docs
- Routes:
```
POST /api/partners/register
GET  /api/partners/{id}/usage
POST /api/partners/{id}/webhook
```

---

### 3.4 Sustainability Impact Tracker
**Status:** Planned
**Goal:** Display CO₂ saved, renewable energy consumed, and community impact counters with source attribution.

#### What to Add:
- Extend `ImpactCounter` to include `co2_saved`, `renewable_kwh`, `community_projects` counters
- UI widgets for CO₂ and renewable breakdown (daily/weekly/monthly)
- Attribution metadata for counter updates (source: device/partner/manual)
- Routes:
```
GET  /api/impact/summary
POST /api/impact/update
```

---

## 🔗 PHASE 4: CROSS-SYSTEM ENHANCEMENTS

### 4.1 Unified Analytics Dashboard
**Status:** Planned
**Goal:** Combine customer usage, admin updates, and examiner finance reports into a single analytics view.

#### What to Add:
- Aggregation layer to join customer usage, finance, and admin events
- Role-aware dashboard views and export (CSV/PDF)
- Routes:
```
GET /api/analytics/unified
```

---

### 4.2 Centralized Notifications Center
**Status:** Planned
**Goal:** One hub for system-wide alerts (tariff changes, feature updates, finance approvals).

#### What to Add:
- Notification model with channels (in-app, email, SMS, webhook)
- User subscription preferences and global notification rules
- Routes:
```
GET  /api/notifications
POST /api/notifications/send
POST /api/notifications/preferences
```

---

### 4.3 Smart Search & Filter Engine
**Status:** Planned
**Goal:** Fast cross-system search to find customers, transactions, or reports.

#### What to Add:
- Full-text search index (e.g., PostgreSQL tsvector or external search like Elasticsearch / Meilisearch)
- Filter facets for roles, dates, amounts, and status
- Routes:
```
GET /api/search?q=...&type=customers
```

---

### 4.4 Audit Logs & Transparency
**Status:** Planned
**Goal:** Track every system action (tariff updates, finance approvals, customer registrations) with queryable logs.

#### What to Add:
- `AuditLog` model and secure access controls
- Immutable storage option (append-only, backed by write-once logs or signed entries)
- Admin/examiner views for export and filtering
- Routes:
```
GET /api/audit/logs?entity=tariff&action=approve
```

---

*These phases focus on privacy, partnerships, and cross-system visibility required for scaling EcoPulse.*
```

---

### 2.3 Data Export (CSV/Excel)
**Status:** New feature  
**Integration:** Existing reports system

#### New Module (`modules/export_handler.py`):
```python
import csv
import pandas as pd
from io import StringIO, BytesIO

class DataExporter:
    """
    Generate exportable reports in multiple formats
    """
    
    @staticmethod
    def export_to_csv(user_id, start_date, end_date):
        """Export energy readings to CSV"""
        pass
    
    @staticmethod
    def export_to_excel(user_id, start_date, end_date, include_charts=True):
        """Export comprehensive Excel report with charts"""
        pass
    
    @staticmethod
    def generate_audit_report(user_id, period='monthly'):
        """Create compliance/audit report"""
        pass
    
    @staticmethod
    def export_cost_analysis(user_id, start_date, end_date):
        """Financial breakdowns and cost comparisons"""
        pass
```

#### Export Templates:
```
Required Columns:
- Date/Time
- Energy Usage (kWh)
- Cost (Ksh)
- Energy Source (KPLC/Solar)
- Temperature (if available)
- Notes

Optional:
- Comparison to previous period
- Savings amount
- Device-level breakdown
```

#### New Routes:
```
GET  /api/export/csv?start_date=&end_date=
GET  /api/export/excel?start_date=&end_date=
GET  /api/export/audit-report
POST /api/export/schedule-email
```

---

### 2.4 Secure Accounts (Enhanced Security)
**Status:** Enhancement to existing system  
**Current Base:** Flask-Login, password hashing

#### Extend User Model:
```python
class User(UserMixin, db.Model):
    # Existing fields...
    
    # Security enhancements
    two_factor_enabled = db.Column(db.Boolean, default=False)
    two_factor_method = db.Column(db.String(20))  # 'email', 'sms', 'authenticator'
    backup_codes = db.Column(db.JSON)  # For 2FA recovery
    login_attempts = db.Column(db.Integer, default=0)
    locked_until = db.Column(db.DateTime, nullable=True)
    privacy_settings = db.Column(db.JSON, default={
        'share_data': False,
        'show_in_rankings': False,
        'allow_comparisons': False,
    })
    data_encryption_key = db.Column(db.String(200))  # For sensitive data
    last_login = db.Column(db.DateTime)
    last_password_change = db.Column(db.DateTime)
```

#### Security Module (`modules/security.py`):
```python
from cryptography.fernet import Fernet
import pyotp
import secrets

class SecurityManager:
    """
    Handles security operations for user accounts
    """
    
    @staticmethod
    def enable_two_factor(user_id, method='email'):
        """Enable 2FA"""
        pass
    
    @staticmethod
    def verify_otp(user_id, otp_code):
        """Verify one-time password"""
        pass
    
    @staticmethod
    def encrypt_sensitive_data(data, encryption_key):
        """Encrypt data like meter numbers"""
        pass
    
    @staticmethod
    def enforce_password_policy(password):
        """Validate password strength"""
        pass
    
    @staticmethod
    def generate_backup_codes(user_id):
        """Generate 2FA backup codes"""
        pass
    
    @staticmethod
    def manage_access(user_id, role_name):
        """Role-based access control"""
        pass

# Access levels
ROLES = {
    'customer': ['view_own_data', 'modify_settings'],
    'auditor': ['view_all_data', 'generate_reports'],
    'admin': ['full_access'],
    'staff': ['approve_readings', 'manage_users'],
}
```

#### New Routes:
```
POST /api/security/2fa/enable
POST /api/security/2fa/verify
POST /api/security/2fa/backup-codes
POST /api/security/change-password
POST /api/security/privacy-settings
GET  /api/security/login-history
```

---

### 2.5 Payment & Subscription (Monetization)
**Status:** New feature  
**Integration:** Integrate with existing Subscription model

#### Extend Subscription Model:
```python
class Subscription(db.Model):
    # Existing fields...
    
    # Enhanced monetization
    tier = db.Column(db.String(20))  # 'free', 'basic', 'pro', 'enterprise'
    monthly_price = db.Column(db.Float)
    trial_ends = db.Column(db.DateTime)
    auto_renew = db.Column(db.Boolean, default=True)
    payment_method = db.Column(db.String(50))  # 'mpesa', 'card', 'bank'
    next_billing_date = db.Column(db.DateTime)
    features = db.Column(db.JSON)  # Available features for tier
    usage_limit = db.Column(db.Integer)  # Data points/month

class PaymentTransaction(db.Model):
    __tablename__ = 'payment_transactions'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    amount = db.Column(db.Float)
    currency = db.Column(db.String(10))
    payment_method = db.Column(db.String(50))
    transaction_id = db.Column(db.String(100), unique=True)
    status = db.Column(db.String(20))  # 'pending', 'completed', 'failed'
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
```

#### Subscription Tiers:
```python
SUBSCRIPTION_TIERS = {
    'free': {
        'price': 0,
        'features': [
            'basic_dashboard',
            'manual_readings',
            'weekly_summary_email',
        ],
        'monthly_data_points': 1000,
    },
    'basic': {
        'price': 299,  # Ksh
        'features': [
            'all_free_features',
            'real_time_charts',
            'daily_tips',
            'csv_export',
        ],
        'monthly_data_points': 10000,
    },
    'pro': {
        'price': 799,
        'features': [
            'all_basic_features',
            'advanced_analytics',
            'forecasting',
            'community_sharing',
            'custom_alerts',
            'excel_export',
            'priority_support',
        ],
        'monthly_data_points': 50000,
    },
    'enterprise': {
        'price': 2999,
        'features': [
            'all_pro_features',
            'api_access',
            'dedicated_support',
            'custom_integrations',
            'iot_integration',
            'bulk_user_management',
        ],
        'monthly_data_points': 'unlimited',
    },
}
```

#### Payment Module (`modules/payment_handler.py`):
```python
class PaymentHandler:
    """
    Handles payment processing and subscription management
    """
    
    @staticmethod
    def process_payment(user_id, amount, payment_method):
        """Process payment via M-Pesa, card, etc."""
        pass
    
    @staticmethod
    def upgrade_subscription(user_id, tier):
        """Upgrade user to new tier"""
        pass
    
    @staticmethod
    def renew_subscription(user_id):
        """Handle subscription renewal"""
        pass
    
    @staticmethod
    def check_feature_access(user_id, feature_name):
        """Verify if user has access to feature"""
        pass
    
    @staticmethod
    def generate_invoice(user_id, transaction_id):
        """Create invoice for payment"""
        pass

# Integration with payment gateways
PAYMENT_PROVIDERS = {
    'mpesa': {
        'api_key': 'YOUR_MPESA_KEY',
        'shortcode': 'YOUR_SHORTCODE',
    },
    'stripe': {
        'public_key': 'YOUR_STRIPE_KEY',
        'secret_key': 'YOUR_STRIPE_SECRET',
    },
    'paypal': {
        'client_id': 'YOUR_PAYPAL_ID',
    },
}
```

#### New Routes:
```
GET  /api/billing/subscription
POST /api/billing/upgrade
POST /api/billing/process-payment
GET  /api/billing/invoices
POST /api/billing/cancel-subscription
GET  /api/billing/usage
```

---

## 📊 IMPLEMENTATION CHECKLIST

### Phase 1: UX (Weeks 1-4)
- [ ] Dashboard widgets system
- [ ] Real-time chart library integration
- [ ] Mobile CSS framework
- [ ] Tip engine algorithm
- [ ] Gamification database and badges
- [ ] Community sharing backend

### Phase 2: Technical (Weeks 5-10)
- [ ] IoT device registration
- [ ] Data ingestion pipeline
- [ ] Forecasting ML model
- [ ] Alert system
- [ ] Export functionality
- [ ] Security enhancements (2FA, encryption)

### Phase 3: Monetization (Weeks 11-12)
- [ ] Payment gateway integration
- [ ] Subscription tier system
- [ ] Invoice generation
- [ ] Feature access control

---

## 📁 NEW FILE STRUCTURE

```
ecopulse_app.py (main app with new models)
modules/
  ├── tip_engine.py          (Personalized tips)
  ├── iot_handler.py         (IoT integration)
  ├── forecasting.py         (Predictions & alerts)
  ├── export_handler.py      (CSV/Excel export)
  ├── security.py            (Enhanced security)
  ├── payment_handler.py     (Payments & subscriptions)
  └── gamification.py        (Badges & points)
templates/
  ├── dashboard_enhanced.html (Real-time charts)
  ├── tips.html              (Personalized tips)
  ├── gamification.html      (Badges & leaderboard)
  └── community.html         (Sharing & comparisons)
static/
  ├── css/
  │   ├── mobile.css         (Mobile responsiveness)
  │   └── dashboard.css      (Dashboard enhancements)
  ├── js/
  │   ├── charts.js          (Real-time charting)
  │   └── gamification.js    (Badge animations)
```

---

## 🔌 DEPENDENCIES TO ADD

```
# Charts & Visualization
plotly>=5.0.0
chart.js>=3.0

# Machine Learning (Forecasting)
scikit-learn>=1.0
pandas>=1.3

# IoT Support
paho-mqtt>=1.6  (for MQTT devices)
requests>=2.28

# Security
python-dotenv>=0.19
pyotp>=2.6  (for 2FA)
cryptography>=37.0

# Export
openpyxl>=3.7  (Excel export)
xlsxwriter>=3.0

# Payments
stripe>=2.60  (if using Stripe)
python-mpesa>=0.1  (if using M-Pesa)
```

---

## ✅ MINIMAL CODE CHANGES TO EXISTING FILES

The beauty of this plan: **Most features can be added via new modules and routes without modifying the core `ecopulse_app.py`**

Only add to existing file:
1. New model definitions (at the end)
2. New API routes (they don't interfere with existing routes)
3. Update `requirements.txt`

---

## 🚀 INTEGRATION EXAMPLE

Once all models are defined, integration is simple:

```python
# In ecopulse_app.py routes section, add:

@app.route('/api/dashboard/tips', methods=['GET'])
@login_required
def get_personalized_tips():
    from modules.tip_engine import TipEngine
    tips = TipEngine.analyze_usage_patterns(current_user.id)
    return jsonify(tips)

@app.route('/api/gamification/badges', methods=['GET'])
@login_required
def get_user_badges():
    badges = UserBadge.query.filter_by(user_id=current_user.id).all()
    return jsonify([b.to_dict() for b in badges])

# ... More routes as needed
```

---

## 📝 NOTES

- All features respect existing user roles and permissions
- Database migrations can be handled incrementally
- Feature flags can wrap new features for gradual rollout
- Each module is independent and can be tested separately
- Backward compatible with current database schema

**Ready to implement? Start with Phase 1 for immediate UX wins!**
