# EcoPulse - Comprehensive Features Implementation

**Last Updated:** June 2026  
**Status:** All Features Implemented ✅

## Table of Contents
1. [Overview](#overview)
2. [Cost Calculator](#cost-calculator)
3. [Analytics & Insights](#analytics--insights)
4. [Energy Saving Recommendations](#energy-saving-recommendations)
5. [Real-Time Monitoring](#real-time-monitoring)
6. [Device Monitoring Panel](#device-monitoring-panel)
7. [Multi-Branch Monitoring](#multi-branch-monitoring)
8. [Energy Consumption Reports](#energy-consumption-reports)
9. [Device Management](#device-management)
10. [User Roles](#user-roles)
11. [Database Architecture](#database-architecture)
12. [API Endpoints](#api-endpoints)
13. [System Architecture](#system-architecture)

---

## Overview

EcoPulse has been upgraded with comprehensive energy management features including:
- **Intelligent Cost Calculation** - Real-time electricity cost estimation
- **Advanced Analytics** - Consumption patterns and trends
- **AI-Powered Recommendations** - Personalized energy-saving suggestions
- **Real-Time Monitoring** - Live device tracking via IoT
- **Multi-Branch Support** - For business customers
- **Professional Reports** - Daily, weekly, monthly reports
- **Role-Based Access** - Home Owner, Business Manager, System Administrator

---

## Cost Calculator

### Features
- Calculate electricity cost from kWh consumption
- Support for multiple currencies (Ksh, USD, etc.)
- Period-based calculations (daily, weekly, monthly)
- Integration with actual consumption data

### Database Model
```python
class CostCalculation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    kwh = db.Column(db.Float)
    unit_cost = db.Column(db.Float)
    total_cost = db.Column(db.Float)
    currency = db.Column(db.String(10), default='Ksh')
    period = db.Column(db.String(20))  # 'daily', 'weekly', 'monthly'
```

### Usage Examples

#### Calculate Cost from kWh
```bash
POST /api/cost/calculate
Content-Type: application/json

{
    "kwh": 150,
    "unit_cost": 0.12,
    "currency": "Ksh"
}

Response:
{
    "success": true,
    "kwh": 150,
    "unit_cost": 0.12,
    "total_cost": 18.00,
    "currency": "Ksh"
}
```

#### Get Today's Cost
```bash
GET /api/cost/daily

Response:
{
    "success": true,
    "date": "2026-06-01",
    "kwh": 45.5,
    "cost": 5.46,
    "currency": "Ksh"
}
```

#### Calculate Period Cost
```bash
POST /api/cost/period
Content-Type: application/json

{
    "start_date": "2026-06-01T00:00:00",
    "end_date": "2026-06-30T23:59:59"
}

Response:
{
    "success": true,
    "start_date": "2026-06-01T00:00:00",
    "end_date": "2026-06-30T23:59:59",
    "kwh": 1250.75,
    "cost": 150.09,
    "currency": "Ksh"
}
```

### Utility Functions
```python
def calculate_electricity_cost(kwh, unit_cost, currency='Ksh'):
    """Calculate total cost = kwh × unit_cost"""
    return round(kwh * unit_cost, 2)

def calculate_daily_cost(user):
    """Get today's consumption and cost"""
    
def calculate_period_cost(user, start_date, end_date):
    """Get consumption and cost for a date range"""
```

---

## Analytics & Insights

### Features
- Track highest and lowest consuming devices
- Monitor energy trends (increasing/decreasing/stable)
- Compare usage across periods
- Average daily consumption calculation
- Peak and lowest usage identification
- Percentage change comparison with previous periods

### Database Model
```python
class EnergyAnalytics(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'), nullable=True)
    period_start = db.Column(db.DateTime)
    period_end = db.Column(db.DateTime)
    total_usage = db.Column(db.Float, default=0)
    average_daily_usage = db.Column(db.Float, default=0)
    peak_usage = db.Column(db.Float, default=0)
    lowest_usage = db.Column(db.Float, default=0)
    highest_consuming_device = db.Column(db.String(120))
    lowest_consuming_device = db.Column(db.String(120))
    trend = db.Column(db.String(50), default='stable')  # 'increasing', 'decreasing'
    comparison_previous_period = db.Column(db.Float, default=0)  # percentage
```

### Usage Examples

#### Get Analytics Overview
```bash
GET /api/analytics/overview?period=monthly

Response:
{
    "success": true,
    "period": "monthly",
    "analytics": {
        "total_usage": 1250.75,
        "average_daily": 41.69,
        "peak_usage": 85.3,
        "lowest_usage": 15.2,
        "highest_device": "Air Conditioner",
        "lowest_device": "LED Lights",
        "trend": "increasing",
        "comparison_previous": 12.5  # 12.5% increase
    }
}
```

#### Compare Two Periods
```bash
POST /api/analytics/comparison
Content-Type: application/json

{
    "period1_start": "2026-05-01T00:00:00",
    "period1_end": "2026-05-31T23:59:59",
    "period2_start": "2026-06-01T00:00:00",
    "period2_end": "2026-06-30T23:59:59"
}

Response:
{
    "success": true,
    "period1": {
        "usage": 1200,
        "cost": 144.00
    },
    "period2": {
        "usage": 1350,
        "cost": 162.00
    },
    "difference": 150,
    "percentage_change": 12.5
}
```

---

## Energy Saving Recommendations

### Features
- AI-powered personalized recommendations
- Priority levels (high, medium, low)
- Estimated savings in kWh
- Recommendation tracking (read, acted upon)
- Device-specific recommendations

### Database Model
```python
class EnergyRecommendation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    device_id = db.Column(db.Integer, db.ForeignKey('customer_devices.id'))
    recommendation_type = db.Column(db.String(100))
    description = db.Column(db.Text)
    estimated_savings = db.Column(db.Float, default=0)  # in kWh
    priority = db.Column(db.String(20), default='medium')
    is_read = db.Column(db.Boolean, default=False)
    is_acted_upon = db.Column(db.Boolean, default=False)
```

### Recommendation Types

1. **AC Peak Hours Reduction**
   - Description: Reduce AC usage during peak hours (9 AM - 5 PM)
   - Estimated Savings: 15-20%
   - Trigger: Peak usage > 50 kWh

2. **Idle Devices Shutdown**
   - Description: Turn off idle/inactive devices
   - Estimated Savings: 5-10%
   - Trigger: Multiple inactive devices detected

3. **Usage Optimization**
   - Description: Schedule non-essential tasks during off-peak hours
   - Estimated Savings: 10-15%
   - Trigger: Average daily > 40 kWh

4. **Device Efficiency Upgrade**
   - Description: Replace high-consuming devices with efficient models
   - Estimated Savings: 10-20%
   - Trigger: Device consuming > 40% of total

### Usage Examples

#### Generate Recommendations
```bash
GET /api/recommendations/generate

Response:
{
    "success": true,
    "count": 3,
    "recommendations": [
        {
            "type": "AC Peak Hours",
            "description": "Reduce air conditioner usage during peak hours...",
            "savings": 10.5,
            "priority": "high"
        },
        {
            "type": "Idle Devices",
            "description": "You have 2 idle device(s)...",
            "savings": 5.0,
            "priority": "medium"
        }
    ]
}
```

#### Get All Recommendations
```bash
GET /api/recommendations/all

Response:
{
    "success": true,
    "count": 5,
    "recommendations": [...]
}
```

---

## Real-Time Monitoring

### Features
- Live device status tracking (online/offline/error)
- Current power consumption in watts
- Device activity timestamps
- Status history
- IoT sensor integration support

### Database Model
```python
class DeviceStatus(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    device_id = db.Column(db.Integer, db.ForeignKey('customer_devices.id'))
    is_online = db.Column(db.Boolean, default=True)
    current_power = db.Column(db.Float, default=0)  # in watts
    last_reading = db.Column(db.DateTime)
    status = db.Column(db.String(50), default='idle')  # idle, running, offline
    last_activity = db.Column(db.DateTime)
```

### Status Values
- **idle**: Device online but consuming minimal power
- **running**: Device actively consuming power
- **offline**: Device not responding/disconnected
- **error**: Device malfunction detected

### Usage Examples

#### Get Device Real-Time Status
```bash
GET /api/devices/123/status

Response:
{
    "success": true,
    "device_id": 123,
    "device_name": "Air Conditioner",
    "data": {
        "device_id": 123,
        "is_online": true,
        "current_power": 3500,
        "status": "running",
        "last_reading": "2026-06-01T14:35:22",
        "last_activity": "2026-06-01T14:35:22"
    }
}
```

#### Update Device Status
```python
def update_device_status(device_id, is_online=True, current_power=0):
    """Update from IoT sensor or manual input"""
    # Automatically sets status based on power consumption
    # Logs timestamp for real-time tracking
```

---

## Device Monitoring Panel

### Features
- View all registered devices
- Track device activity and status
- Remove inactive devices
- Filter by category or status
- Bulk operations support

### Admin Panel Features
- See all users' devices
- Device health monitoring
- Inactive device identification
- Multi-user device overview

### Usage Examples

#### Get All Devices
```bash
GET /api/devices/all

Response:
{
    "success": true,
    "count": 5,
    "devices": [
        {
            "id": 1,
            "name": "Air Conditioner",
            "category": "Cooling",
            "watts": 3500,
            "hours_per_day": 8,
            "quantity": 1,
            "is_active": true,
            "status": "running",
            "is_online": true
        },
        {
            "id": 2,
            "name": "Refrigerator",
            "category": "Appliance",
            "watts": 150,
            "hours_per_day": 24,
            "quantity": 1,
            "is_active": true,
            "status": "idle",
            "is_online": true
        }
    ]
}
```

#### Add Device
```bash
POST /api/devices/add
Content-Type: application/json

{
    "name": "Washing Machine",
    "category": "Appliance",
    "watts": 2000,
    "hours_per_day": 1,
    "quantity": 1,
    "notes": "Used every other day"
}

Response:
{
    "success": true,
    "message": "Device added successfully",
    "device_id": 3
}
```

#### Remove Device
```bash
DELETE /api/devices/3/remove

Response:
{
    "success": true,
    "message": "Device removed successfully"
}
```

---

## Multi-Branch Monitoring

### Features (Business Managers)
- Create and manage multiple branches
- Branch A, B, C, etc. support
- Separate energy tracking per branch
- Branch manager assignment
- Comparative branch analytics
- Consolidated reporting

### Database Models
```python
class Branch(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))  # Business manager
    name = db.Column(db.String(120))  # Branch A, B, C
    location = db.Column(db.String(200))
    address = db.Column(db.Text)
    phone = db.Column(db.String(20))
    manager_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    total_devices = db.Column(db.Integer, default=0)
    is_active = db.Column(db.Boolean, default=True)

class BranchEnergyUsage(db.Model):
    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'))
    date = db.Column(db.Date)
    total_usage = db.Column(db.Float, default=0)
    total_cost = db.Column(db.Float, default=0)
    device_count = db.Column(db.Integer, default=0)
```

### Usage Examples

#### Create Branch
```bash
POST /api/branches/create
Content-Type: application/json

{
    "name": "Branch A - Downtown",
    "location": "Nairobi Downtown",
    "address": "123 Main Street",
    "phone": "+254712345678"
}

Response:
{
    "success": true,
    "branch_id": 1,
    "message": "Branch created successfully"
}
```

#### Get All Branches
```bash
GET /api/branches/all

Response:
{
    "success": true,
    "count": 3,
    "branches": [
        {
            "id": 1,
            "name": "Branch A - Downtown",
            "location": "Nairobi Downtown",
            "phone": "+254712345678",
            "total_devices": 45,
            "is_active": true
        },
        {
            "id": 2,
            "name": "Branch B - Westlands",
            "location": "Nairobi Westlands",
            "phone": "+254712345679",
            "total_devices": 38,
            "is_active": true
        }
    ]
}
```

#### Get Branch Analytics
```bash
GET /api/branches/1/analytics

Response:
{
    "success": true,
    "branch_id": 1,
    "branch_name": "Branch A - Downtown",
    "usage_history": [
        {
            "date": "2026-06-01",
            "total_usage": 850.5,
            "total_cost": 102.06,
            "device_count": 45
        },
        {
            "date": "2026-05-31",
            "total_usage": 820.0,
            "total_cost": 98.40,
            "device_count": 45
        }
    ]
}
```

---

## Energy Consumption Reports

### Report Types
1. **Daily Reports** - 24-hour consumption and cost
2. **Weekly Reports** - 7-day aggregated data
3. **Monthly Reports** - Full month analysis

### Report Contents
- Device name and consumption
- Energy used (kWh)
- Cost estimation
- Comparison with previous period
- Trends and patterns
- Recommendations

### Database Model
```python
class ReportGeneration(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'))
    report_type = db.Column(db.String(50))  # daily, weekly, monthly
    period_start = db.Column(db.DateTime)
    period_end = db.Column(db.DateTime)
    total_energy = db.Column(db.Float, default=0)
    total_cost = db.Column(db.Float, default=0)
    file_path = db.Column(db.String(500))
    format = db.Column(db.String(20), default='pdf')
```

### Usage Examples

#### Generate Report
```bash
POST /api/reports/generate
Content-Type: application/json

{
    "type": "monthly",
    "branch_id": null
}

Response:
{
    "success": true,
    "report": {
        "report_id": 42,
        "type": "monthly",
        "period": "2026-06-01 to 2026-06-30",
        "total_energy": 1250.75,
        "total_cost": 150.09,
        "device_count": 8,
        "readings_count": 90
    }
}
```

#### Get All Reports
```bash
GET /api/reports/all?type=monthly

Response:
{
    "success": true,
    "count": 12,
    "reports": [
        {
            "id": 42,
            "type": "monthly",
            "period_start": "2026-06-01T00:00:00",
            "period_end": "2026-06-30T23:59:59",
            "total_energy": 1250.75,
            "total_cost": 150.09,
            "created_at": "2026-06-30T23:45:00"
        }
    ]
}
```

---

## Device Management

### Capabilities
- Add new devices
- Edit device information
- Remove devices
- View device status
- Track device history
- Category management

### Device Categories
- **Cooling**: AC, Fans, Refrigerators
- **Heating**: Heaters, Water heaters
- **Lighting**: Bulbs, LED strips
- **Appliances**: Washing machine, Microwave
- **Entertainment**: TV, Computer
- **Other**: Custom categories

### Supported Device Types
- Air Conditioners
- Refrigerators
- Water Heaters
- Electric Ovens
- Washing Machines
- Dryers
- Dishwashers
- Computers
- Printers
- TVs
- LED Lights
- Ceiling Fans
- Custom Devices

---

## User Roles

### Role-Based Access Control

#### 1. Home Owner (User Type: `home_owner`)
**Permissions:**
- View personal dashboard
- Manage personal devices
- View personal analytics
- Generate personal reports
- Receive personalized recommendations
- Manage alerts

**Features:**
- Real-time consumption tracking
- Cost calculation
- Energy analytics
- Device monitoring
- Report generation
- Settings management

#### 2. Business Manager (User Type: `business_manager`)
**Permissions:**
- Manage multiple branches
- View branch-level analytics
- Manage branch devices
- Generate branch reports
- Manage branch managers
- Comparative branch analysis

**Features:**
- Multi-branch dashboard
- Branch creation and management
- Consolidated reporting
- Device distribution tracking
- Staff management
- Branch performance comparison

#### 3. System Administrator (Role: `admin`)
**Permissions:**
- Access all users' data
- Device monitoring panel
- System configuration
- User management
- Report oversight
- Audit logs

**Features:**
- System-wide analytics
- User activity monitoring
- Device health monitoring
- System diagnostics
- Bulk operations
- Advanced reporting

---

## Database Architecture

### Core Energy Management Tables

```
users (existing) → enhanced with user_type field
├── readings
├── cost_calculations
├── energy_analytics
├── energy_recommendations
├── device_status
└── alert_history

customer_devices (existing) → linked to real-time data
├── iot_data
└── device_status

branches (new - business only)
├── branch_energy_usage
├── user_branch_access
└── report_generations

reports
├── report_generations
└── energy_analytics
```

### New Models Summary

| Model | Purpose | Key Fields |
|-------|---------|------------|
| `Branch` | Multi-business support | name, location, manager_id |
| `CostCalculation` | Cost tracking | kwh, unit_cost, total_cost |
| `EnergyAnalytics` | Analytics data | total_usage, trend, comparison |
| `EnergyRecommendation` | Recommendations | type, description, savings |
| `ReportGeneration` | Report tracking | report_type, total_energy, total_cost |
| `AlertHistory` | Alert tracking | alert_type, severity, message |
| `DeviceStatus` | Real-time status | is_online, current_power, status |
| `BranchEnergyUsage` | Branch summary | total_usage, total_cost, device_count |
| `UserBranchAccess` | Branch permissions | user_id, branch_id, access_level |

---

## API Endpoints

### Cost Calculation Endpoints
- `POST /api/cost/calculate` - Calculate cost from kWh
- `GET /api/cost/daily` - Get today's cost
- `POST /api/cost/period` - Calculate period cost

### Analytics Endpoints
- `GET /api/analytics/overview` - Get analytics overview
- `POST /api/analytics/comparison` - Compare two periods

### Recommendation Endpoints
- `GET /api/recommendations/generate` - Generate recommendations
- `GET /api/recommendations/all` - Get all recommendations

### Device Endpoints
- `GET /api/devices/all` - List all devices
- `POST /api/devices/add` - Add new device
- `GET /api/devices/<id>/status` - Get device status
- `DELETE /api/devices/<id>/remove` - Remove device

### Report Endpoints
- `POST /api/reports/generate` - Generate report
- `GET /api/reports/all` - Get all reports

### Alert Endpoints
- `POST /api/alerts/create` - Create alert
- `GET /api/alerts/all` - Get all alerts
- `PUT /api/alerts/<id>/acknowledge` - Acknowledge alert

### Branch Endpoints (Business Only)
- `GET /api/branches/all` - List branches
- `POST /api/branches/create` - Create branch
- `GET /api/branches/<id>/analytics` - Get branch analytics

### Settings Endpoints
- `GET /api/settings/energy-source` - Get settings
- `POST /api/settings/update` - Update settings

### Dashboard Endpoint
- `GET /dashboard/enhanced` - Enhanced dashboard with all features

---

## System Architecture

### Three-Tier Architecture

```
┌─────────────────────────────────────┐
│      Presentation Layer (UI)         │
│  - Dashboard                         │
│  - Reports                           │
│  - Settings                          │
│  - Device Management                 │
│  - Branch Management (Business)      │
└─────────────────────────────────────┘
                 ↓↑
┌─────────────────────────────────────┐
│      Application Layer (API)         │
│  - RESTful Endpoints                 │
│  - Authentication                    │
│  - Authorization                     │
│  - Business Logic                    │
└─────────────────────────────────────┘
                 ↓↑
┌─────────────────────────────────────┐
│      Data Layer (Database)           │
│  - User Data                         │
│  - Energy Readings                   │
│  - Device Information                │
│  - Analytics & Metrics               │
│  - Reports & History                 │
└─────────────────────────────────────┘
```

### IoT Integration Architecture

```
┌──────────────────┐
│   IoT Sensors    │
│  (Energy Meter)  │
└────────┬─────────┘
         │
         ↓
┌──────────────────┐
│   Backend API    │
│ /update-status   │
└────────┬─────────┘
         │
         ↓
┌──────────────────┐
│   DeviceStatus   │
│  Real-time DB    │
└────────┬─────────┘
         │
         ↓
┌──────────────────┐
│   User Dashboard │
│  (Live Display)  │
└──────────────────┘
```

---

## Implementation Notes

### Non-Functional Requirements Met

✅ **Security**
- Role-based access control
- User data isolation
- Password hashing
- CSRF protection

✅ **Reliability**
- Database transactions
- Error handling
- Graceful degradation
- Data validation

✅ **Fast Response Time**
- Indexed database queries
- Caching support
- Optimized API endpoints
- Minimal data transfers

✅ **Scalability**
- Modular design
- Horizontal scaling ready
- Database normalization
- Efficient queries

✅ **Ease of Use**
- Intuitive API
- Clear error messages
- Comprehensive documentation
- User-friendly features

✅ **Data Accuracy**
- Real-time calculations
- Validated inputs
- Historical tracking
- Audit logging

### Energy Source Configuration

**Previous:** KPLC, Solar Grid  
**Current:** KPLC only  
**Location:** `ecopulse_app.py` line ~90

```python
ENERGY_SOURCES = ('KPLC',)
ENERGY_SOURCE_LABELS = {
    'KPLC': 'KPLC Grid'
}
```

---

## Quick Start Guide

### For Home Owners

1. **Login** to your account
2. **Add Devices** - Go to Device Management
3. **View Dashboard** - See your consumption
4. **Check Recommendations** - Follow energy-saving tips
5. **Review Reports** - Download monthly reports

### For Business Managers

1. **Create Branches** - Add Branch A, B, C
2. **Assign Managers** - Delegate branch management
3. **Add Devices** - Register devices per branch
4. **View Analytics** - Compare branch performance
5. **Generate Reports** - Consolidated reports

### For System Administrators

1. **Access Admin Panel** - System-wide overview
2. **Monitor Devices** - Check all device status
3. **Review Users** - Monitor user activity
4. **Configure System** - Update settings
5. **Audit Logs** - Track all changes

---

## Future Enhancements

- [ ] Mobile app for real-time alerts
- [ ] SMS notifications for critical alerts
- [ ] Machine learning for predictive analytics
- [ ] Integration with utility billing systems
- [ ] Carbon footprint calculation
- [ ] Renewable energy tracking
- [ ] Smart scheduling for optimal energy use
- [ ] Community energy sharing features

---

## Support & Documentation

For detailed API documentation, see:
- `INTEGRATION_GUIDE.md` - Step-by-step integration
- `QUICK_REFERENCE.md` - Quick examples
- `FEATURE_ROADMAP.md` - Technical specifications

---

**End of Documentation**
