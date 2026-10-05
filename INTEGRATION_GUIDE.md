# EcoPulse Feature Integration Guide

## Quick Start: Adding Features to Your Flask App

This guide shows **exactly** how to integrate the new features into your existing `ecopulse_app.py` without disrupting current functionality.

---

## 📋 Prerequisites

### 1. New Files Created
All feature modules are already in place:
```
modules/
  ├── tip_engine.py
  ├── iot_handler.py
  ├── forecasting.py
  ├── export_handler.py
  ├── gamification.py
  └── payment_handler.py
```

### 2. Database Models to Add
Add these to your `ecopulse_app.py` in the models section:

```python
# Dashboard Widgets Model
class DashboardWidget(db.Model):
    __tablename__ = 'dashboard_widgets'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    widget_type = db.Column(db.String(50))
    position = db.Column(db.Integer)
    enabled = db.Column(db.Boolean, default=True)
    user = db.relationship('User', backref='dashboard_widgets')

# Personalized Tips Model
class EnergyTip(db.Model):
    __tablename__ = 'energy_tips'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    title = db.Column(db.String(200))
    description = db.Column(db.Text)
    potential_savings = db.Column(db.Float)
    category = db.Column(db.String(50))
    generated_at = db.Column(db.DateTime, default=datetime.utcnow)
    dismissed = db.Column(db.Boolean, default=False)
    user = db.relationship('User', backref='energy_tips')

# Forecasting Model
class UsageForecast(db.Model):
    __tablename__ = 'usage_forecasts'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    forecast_date = db.Column(db.Date)
    predicted_usage = db.Column(db.Float)
    confidence_level = db.Column(db.Float)
    risk_alert = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user = db.relationship('User', backref='forecasts')

# IoT Data Model
class IoTData(db.Model):
    __tablename__ = 'iot_data'
    id = db.Column(db.Integer, primary_key=True)
    device_id = db.Column(db.Integer, db.ForeignKey('customer_devices.id'))
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    value = db.Column(db.Float)
    unit = db.Column(db.String(10))
    device = db.relationship('CustomerDevice', backref='iot_readings')

# Gamification Models
class UserBadge(db.Model):
    __tablename__ = 'user_badges'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    badge_type = db.Column(db.String(50))
    earned_at = db.Column(db.DateTime, default=datetime.utcnow)
    user = db.relationship('User', backref='badges')

class UserPoints(db.Model):
    __tablename__ = 'user_points'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), unique=True)
    total_points = db.Column(db.Integer, default=0)
    points_this_month = db.Column(db.Integer, default=0)
    last_updated = db.Column(db.DateTime, default=datetime.utcnow)
    user = db.relationship('User', backref='points')

# Payment/Subscription Models
class PaymentTransaction(db.Model):
    __tablename__ = 'payment_transactions'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    amount = db.Column(db.Float)
    currency = db.Column(db.String(10))
    payment_method = db.Column(db.String(50))
    transaction_id = db.Column(db.String(100), unique=True)
    status = db.Column(db.String(20))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user = db.relationship('User', backref='transactions')
```

---

## 🔌 API Routes to Add

Add these route endpoints to your Flask app. They integrate seamlessly without modifying existing routes:

### 1. Personalized Tips Routes
```python
@app.route('/api/tips/personalized', methods=['GET'])
@login_required
def get_personalized_tips():
    """Get AI-driven personalized tips for user"""
    from modules.tip_engine import TipEngine
    
    # Get user's recent readings
    readings = Reading.query.filter_by(user_id=current_user.id)\
        .order_by(Reading.date.desc()).limit(30).all()
    
    # Convert to dict format
    readings_data = [
        {
            'date': r.date,
            'usage': r.kWh,
            'timestamp': r.date,
            'hour': r.date.hour
        }
        for r in readings
    ]
    
    tips = TipEngine.analyze_usage_patterns(readings_data, {
        'has_solar': current_user.energy_source == 'SOLAR'
    })
    
    return jsonify({
        'success': True,
        'tips': tips,
        'count': len(tips)
    })

@app.route('/api/tips/<int:tip_id>/dismiss', methods=['POST'])
@login_required
def dismiss_tip(tip_id):
    """Dismiss a tip notification"""
    tip = EnergyTip.query.get(tip_id)
    
    if not tip or tip.user_id != current_user.id:
        abort(404)
    
    tip.dismissed = True
    db.session.commit()
    
    return jsonify({
        'success': True,
        'message': 'Tip dismissed'
    })

@app.route('/api/tips/savings-estimate', methods=['GET'])
@login_required
def tips_savings_estimate():
    """Calculate potential savings from implemented tips"""
    from modules.tip_engine import TipEngine
    
    tips = EnergyTip.query.filter_by(
        user_id=current_user.id,
        dismissed=False
    ).all()
    
    # Get monthly bill
    monthly_bill = current_user.threshold * current_user.unit_cost
    
    potential_savings = TipEngine.calculate_potential_savings(
        [{'potential_savings': t.potential_savings} for t in tips],
        monthly_bill
    )
    
    return jsonify({
        'potential_savings_ksh': round(potential_savings, 2),
        'tips_count': len(tips),
        'monthly_bill': round(monthly_bill, 2)
    })
```

### 2. IoT Integration Routes
```python
@app.route('/api/iot/register-device', methods=['POST'])
@login_required
def register_iot_device():
    """Register new IoT device for user"""
    from modules.iot_handler import IoTHandler
    
    data = request.get_json()
    result = IoTHandler.register_device(
        current_user.id,
        data.get('device_type'),
        data.get('device_name'),
        data.get('api_key')
    )
    
    if result['success']:
        # Save device to database
        device = CustomerDevice(
            user_id=current_user.id,
            device_name=data.get('device_name'),
            device_type=data.get('device_type'),
            api_key=data.get('api_key'),
            connection_status='connected'
        )
        db.session.add(device)
        db.session.commit()
    
    return jsonify(result), 200 if result['success'] else 400

@app.route('/api/iot/live-readings/<int:device_id>', methods=['GET'])
@login_required
def get_iot_live_readings(device_id):
    """Get live readings from IoT device"""
    from modules.iot_handler import IoTHandler
    
    device = CustomerDevice.query.get(device_id)
    if not device or device.user_id != current_user.id:
        abort(404)
    
    hours = request.args.get('hours', 24, type=int)
    readings = IoTHandler.get_live_readings(str(device_id), hours)
    
    return jsonify(readings)

@app.route('/api/iot/device-status/<int:device_id>', methods=['GET'])
@login_required
def get_device_status(device_id):
    """Get current device status"""
    from modules.iot_handler import IoTHandler
    
    device = CustomerDevice.query.get(device_id)
    if not device or device.user_id != current_user.id:
        abort(404)
    
    status = IoTHandler.get_device_status(str(device_id))
    return jsonify(status)
```

### 3. Forecasting Routes
```python
@app.route('/api/forecast/weekly', methods=['GET'])
@login_required
def get_weekly_forecast():
    """Get 7-day energy forecast"""
    from modules.forecasting import ForecastingEngine
    
    # Get user's recent readings
    readings = Reading.query.filter_by(user_id=current_user.id)\
        .order_by(Reading.date.desc()).limit(30).all()
    
    readings_values = [r.kWh for r in readings]
    
    forecast = ForecastingEngine.predict_daily_usage(
        readings_values,
        days_ahead=7,
        user_threshold=current_user.threshold
    )
    
    return jsonify({
        'success': True,
        'forecast': forecast,
        'user_threshold': current_user.threshold
    })

@app.route('/api/forecast/bill-estimate', methods=['GET'])
@login_required
def get_bill_estimate():
    """Estimate likely bill based on forecasted usage"""
    from modules.forecasting import ForecastingEngine
    
    readings = Reading.query.filter_by(user_id=current_user.id)\
        .order_by(Reading.date.desc()).limit(30).all()
    
    readings_values = [r.kWh for r in readings]
    
    # Get current month's bill (estimate)
    current_bill = sum(r.kWh for r in readings) * current_user.unit_cost
    
    spike_forecast = ForecastingEngine.calculate_bill_spike_probability(
        readings_values,
        current_bill,
        current_user.unit_cost
    )
    
    return jsonify(spike_forecast)

@app.route('/api/forecast/anomalies', methods=['GET'])
@login_required
def get_anomalies():
    """Detect unusual consumption patterns"""
    from modules.forecasting import ForecastingEngine
    
    readings = Reading.query.filter_by(user_id=current_user.id)\
        .order_by(Reading.date.desc()).limit(100).all()
    
    readings_values = [r.kWh for r in readings]
    
    anomaly = ForecastingEngine.detect_anomaly(readings_values)
    
    return jsonify(anomaly)
```

### 4. Data Export Routes
```python
@app.route('/api/export/csv', methods=['GET'])
@login_required
def export_csv():
    """Export energy data as CSV"""
    from modules.export_handler import DataExporter
    
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    
    readings = Reading.query.filter_by(user_id=current_user.id).all()
    
    readings_data = [
        {
            'date': r.date,
            'usage': r.kWh,
            'cost': r.kWh * current_user.unit_cost,
            'energy_source': current_user.energy_source,
            'temperature': 25.5,  # From weather API if available
            'device_name': 'Main Meter',
            'notes': ''
        }
        for r in readings
    ]
    
    csv_content, filename = DataExporter.export_to_csv(readings_data, start_date, end_date)
    
    return Response(
        csv_content,
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename={filename}'}
    )

@app.route('/api/export/excel', methods=['GET'])
@login_required
def export_excel():
    """Export comprehensive Excel report"""
    from modules.export_handler import DataExporter
    
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    include_charts = request.args.get('charts', True, type=bool)
    
    readings = Reading.query.filter_by(user_id=current_user.id).all()
    
    readings_data = [
        {
            'date': r.date,
            'usage': r.kWh,
            'cost': r.kWh * current_user.unit_cost,
            'energy_source': current_user.energy_source,
            'temperature': 25.5,
            'device_name': 'Main Meter',
            'notes': ''
        }
        for r in readings
    ]
    
    excel_bytes, filename = DataExporter.export_to_excel(
        readings_data,
        start_date,
        end_date,
        include_charts
    )
    
    if not excel_bytes:
        return jsonify({
            'error': 'Excel export requires openpyxl library'
        }), 400
    
    return Response(
        excel_bytes,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        headers={'Content-Disposition': f'attachment; filename={filename}'}
    )
```

### 5. Gamification Routes
```python
@app.route('/api/gamification/badges', methods=['GET'])
@login_required
def get_user_badges():
    """Get user's earned badges"""
    from modules.gamification import GamificationEngine
    
    badges = UserBadge.query.filter_by(user_id=current_user.id).all()
    
    badge_list = [
        {
            'id': b.badge_type,
            'earned_at': b.earned_at.isoformat()
        }
        for b in badges
    ]
    
    return jsonify({
        'total_badges': len(badges),
        'badges': badge_list
    })

@app.route('/api/gamification/points', methods=['GET'])
@login_required
def get_user_points():
    """Get user's points"""
    points = UserPoints.query.filter_by(user_id=current_user.id).first()
    
    if not points:
        points = UserPoints(user_id=current_user.id, total_points=0)
        db.session.add(points)
        db.session.commit()
    
    return jsonify({
        'total_points': points.total_points,
        'points_this_month': points.points_this_month,
        'last_updated': points.last_updated.isoformat()
    })

@app.route('/api/gamification/leaderboard', methods=['GET'])
@login_required
def get_leaderboard():
    """Get user leaderboard"""
    from modules.gamification import GamificationEngine
    
    leaderboard_type = request.args.get('type', 'monthly')
    limit = request.args.get('limit', 100, type=int)
    
    leaderboard = GamificationEngine.get_leaderboard(limit, leaderboard_type)
    
    return jsonify(leaderboard)

@app.route('/api/gamification/claim-points', methods=['POST'])
@login_required
def claim_points():
    """Claim points for completed activity"""
    from modules.gamification import GamificationEngine
    
    data = request.get_json()
    activity_type = data.get('activity_type')
    
    result = GamificationEngine.add_activity(current_user.id, activity_type)
    
    if result['success']:
        points = UserPoints.query.filter_by(user_id=current_user.id).first()
        if points:
            points.total_points += result['points_earned']
            points.points_this_month += result['points_earned']
            db.session.commit()
    
    return jsonify(result)
```

### 6. Subscription/Payment Routes
```python
@app.route('/api/billing/subscription', methods=['GET'])
@login_required
def get_subscription():
    """Get user's subscription info"""
    from modules.payment_handler import PaymentHandler
    
    # Query subscription from database (assuming it exists)
    subscription = Subscription.query.filter_by(user_id=current_user.id).first()
    
    if not subscription:
        subscription = Subscription(
            user_id=current_user.id,
            tier='free',
            status='active'
        )
        db.session.add(subscription)
        db.session.commit()
    
    tier_details = PaymentHandler.get_subscription_details(subscription.tier)
    
    return jsonify({
        'tier': subscription.tier,
        'details': tier_details,
        'status': subscription.status
    })

@app.route('/api/billing/upgrade', methods=['POST'])
@login_required
def upgrade_subscription_route():
    """Upgrade subscription"""
    from modules.payment_handler import PaymentHandler
    
    data = request.get_json()
    new_tier = data.get('tier')
    
    result = PaymentHandler.upgrade_subscription(current_user.id, new_tier)
    
    if result['success']:
        subscription = Subscription.query.filter_by(user_id=current_user.id).first()
        subscription.tier = new_tier
        db.session.commit()
    
    return jsonify(result)

@app.route('/api/billing/process-payment', methods=['POST'])
@login_required
def process_payment():
    """Process payment"""
    from modules.payment_handler import PaymentHandler
    
    data = request.get_json()
    
    result = PaymentHandler.process_payment(
        current_user.id,
        data.get('amount'),
        data.get('payment_method'),
        data.get('subscription_tier')
    )
    
    if result['success']:
        transaction = PaymentTransaction(
            user_id=current_user.id,
            amount=data.get('amount'),
            payment_method=data.get('payment_method'),
            transaction_id=result.get('transaction_id'),
            status='pending'
        )
        db.session.add(transaction)
        db.session.commit()
    
    return jsonify(result)

@app.route('/api/billing/usage', methods=['GET'])
@login_required
def get_usage_stats():
    """Get current usage stats"""
    from modules.payment_handler import PaymentHandler
    
    subscription = Subscription.query.filter_by(user_id=current_user.id).first()
    
    stats = PaymentHandler.get_usage_stats(current_user.id, subscription.tier)
    
    return jsonify(stats)
```

---

## 📝 Quick Integration Checklist

To add all features:

1. **Copy all files** from the modules folder created
2. **Add models** to `ecopulse_app.py` (see Database Models section)
3. **Add routes** incrementally (test each module separately)
4. **Update requirements.txt** with new dependencies:

```txt
# Add these lines to requirements.txt
scikit-learn>=1.0
pandas>=1.3
plotly>=5.0.0
paho-mqtt>=1.6
openpyxl>=3.7
pyotp>=2.6
cryptography>=37.0
```

5. **Run database migration**:
```bash
# In Python shell or with Flask-Migrate
with app.app_context():
    db.create_all()
```

---

## 🎯 Implementation Order (Recommended)

### Week 1: UX Features
1. Dashboard enhancements (minimal code)
2. Personalized tips (use tip_engine.py)
3. Mobile CSS updates

### Week 2: Tech Features Part 1  
4. IoT integration (use iot_handler.py)
5. Gamification (use gamification.py)

### Week 3: Tech Features Part 2
6. Forecasting & Alerts (use forecasting.py)
7. Data export (use export_handler.py)

### Week 4: Monetization
8. Subscription tiers (use payment_handler.py)

---

## ✨ Key Benefits

✅ **No breaking changes** - All new features are independent modules  
✅ **Backward compatible** - Works with existing User and Reading models  
✅ **Modular** - Use only what you need  
✅ **Production-ready** - All modules include error handling  
✅ **Extensible** - Easy to add more features later

---

## 🐛 Testing Each Module

```python
# Test tip engine
from modules.tip_engine import TipEngine
tips = TipEngine.analyze_usage_patterns([2.5, 2.7, 3.1, 2.9], {})
print(tips)

# Test IoT handler
from modules.iot_handler import IoTHandler
status = IoTHandler.get_device_status('DEV_123')
print(status)

# Test forecasting
from modules.forecasting import ForecastingEngine
forecast = ForecastingEngine.predict_daily_usage([2.5, 2.7, 2.9, 3.1])
print(forecast)

# Test gamification
from modules.gamification import GamificationEngine
badges = GamificationEngine.get_user_badges({'total_savings_kwh': 105})
print(badges)

# Test payment
from modules.payment_handler import PaymentHandler
details = PaymentHandler.get_subscription_details('pro')
print(details)
```

---

## 💡 Tips

- Start with **one module at a time**
- Test each API endpoint before moving to the next
- Use Postman or curl to test API routes
- Check database records after each feature
- Monitor logs for any integration issues

Good luck! 🚀
