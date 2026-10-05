# EcoPulse API Quick Reference

**Last Updated:** June 2026  
**Version:** 1.0  
**Total Endpoints:** 27

---

## API Base URL
```
http://localhost:5000
```

## Authentication
All endpoints require authentication. Add header:
```
Authorization: Bearer {jwt_token}
```

---

## 1. COST CALCULATOR ENDPOINTS

### Calculate Cost from kWh
```http
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

### Get Today's Cost
```http
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

### Calculate Period Cost
```http
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

---

## 2. ANALYTICS ENDPOINTS

### Get Analytics Overview
```http
GET /api/analytics/overview?period=monthly

Parameters:
  period: daily|weekly|monthly (default: monthly)

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
    "comparison_previous": 12.5
  }
}
```

### Compare Two Periods
```http
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

## 3. RECOMMENDATIONS ENDPOINTS

### Generate Recommendations
```http
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
    }
  ]
}
```

### Get All Recommendations
```http
GET /api/recommendations/all

Response:
{
  "success": true,
  "count": 5,
  "recommendations": [...]
}
```

---

## 4. DEVICE MANAGEMENT ENDPOINTS

### Get All Devices
```http
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
    }
  ]
}
```

### Add New Device
```http
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

### Get Device Real-Time Status
```http
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
    "last_reading": "2026-06-01T14:35:22"
  }
}
```

### Remove Device
```http
DELETE /api/devices/3/remove

Response:
{
  "success": true,
  "message": "Device removed successfully"
}
```

---

## 5. REPORTS ENDPOINTS

### Generate Report
```http
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

### Get All Reports
```http
GET /api/reports/all?type=monthly

Parameters:
  type: daily|weekly|monthly (optional)

Response:
{
  "success": true,
  "count": 12,
  "reports": [...]
}
```

---

## 6. ALERTS ENDPOINTS

### Create Alert
```http
POST /api/alerts/create
Content-Type: application/json

{
  "device_id": 1,
  "type": "high_usage",
  "message": "Device consuming more than usual",
  "severity": "high"
}

Response:
{
  "success": true,
  "alert_id": 42,
  "message": "Alert created"
}
```

### Get All Alerts
```http
GET /api/alerts/all

Response:
{
  "success": true,
  "count": 10,
  "alerts": [...]
}
```

### Acknowledge Alert
```http
PUT /api/alerts/42/acknowledge

Response:
{
  "success": true,
  "message": "Alert acknowledged"
}
```

---

## 7. BRANCHES ENDPOINTS (Business Manager Only)

### Get All Branches
```http
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
    }
  ]
}
```

### Create Branch
```http
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

### Get Branch Analytics
```http
GET /api/branches/1/analytics

Response:
{
  "success": true,
  "branch_id": 1,
  "branch_name": "Branch A - Downtown",
  "usage_history": [...]
}
```

---

## 8. SETTINGS ENDPOINTS

### Get Settings
```http
GET /api/settings/energy-source

Response:
{
  "success": true,
  "energy_source": "KPLC",
  "unit_cost": 0.12,
  "currency": "Ksh",
  "threshold": 600
}
```

### Update Settings
```http
POST /api/settings/update
Content-Type: application/json

{
  "unit_cost": 0.15,
  "currency": "Ksh",
  "threshold": 700
}

Response:
{
  "success": true,
  "message": "Settings updated successfully"
}
```

---

## 9. DASHBOARD ENDPOINT

### Get Enhanced Dashboard
```http
GET /dashboard/enhanced

Response:
{
  "dashboard": {
    "user": "john_doe",
    "user_type": "home_owner",
    "total_devices": 8,
    "analytics": {...},
    "today_cost": {
      "kwh": 45.5,
      "cost": 5.46
    },
    "recommendations": [...],
    "recent_alerts": [...]
  }
}
```

---

## Common Error Responses

### Unauthorized
```json
{
  "error": "Unauthorized",
  "status": 401
}
```

### Forbidden (Role-based)
```json
{
  "success": false,
  "error": "Only business managers can access branches"
}
```

### Not Found
```json
{
  "success": false,
  "error": "Device not found"
}
```

### Bad Request
```json
{
  "success": false,
  "error": "Invalid request data"
}
```

---

## HTTP Status Codes

| Code | Meaning | Usage |
|------|---------|-------|
| 200 | OK | Successful GET/PUT |
| 201 | Created | Successful POST (resource created) |
| 400 | Bad Request | Invalid data |
| 401 | Unauthorized | Missing/invalid authentication |
| 403 | Forbidden | Insufficient permissions |
| 404 | Not Found | Resource not found |
| 500 | Server Error | Internal error |

---

## Common Parameters

### Date Format
```
ISO 8601: "2026-06-01T00:00:00"
```

### Period Values
```
daily   - Last 24 hours
weekly  - Last 7 days
monthly - Last 30 days
```

### Severity Levels
```
low     - Non-urgent
medium  - Standard
high    - Important
critical - Urgent
```

### Device Status
```
idle    - Online but low consumption
running - Actively consuming power
offline - Not connected
error   - Malfunction detected
```

---

## Authentication Example

### Login First (Existing endpoint)
```http
POST /login
Content-Type: application/json

{
  "username": "john_doe",
  "password": "password123"
}

Response:
{
  "user_id": 1,
  "username": "john_doe",
  "role": "customer",
  "user_type": "home_owner"
}
```

### Use Session for Subsequent Requests
Most endpoints support both JWT tokens and session-based authentication.

---

## Rate Limiting

No rate limiting currently implemented. Use responsibly in production.

---

## Pagination

Pagination not yet implemented. All results returned in single response.

---

## Filtering

Advanced filtering can be added to most endpoints. Current support:
- `?period=` for analytics
- `?type=` for reports
- `?branch_id=` for reports

---

## Examples Using cURL

### Get Analytics
```bash
curl -X GET "http://localhost:5000/api/analytics/overview?period=monthly" \
  -H "Cookie: session=your_session_id" \
  -H "Content-Type: application/json"
```

### Create Device
```bash
curl -X POST "http://localhost:5000/api/devices/add" \
  -H "Cookie: session=your_session_id" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Washing Machine",
    "category": "Appliance",
    "watts": 2000,
    "hours_per_day": 1,
    "quantity": 1
  }'
```

### Generate Report
```bash
curl -X POST "http://localhost:5000/api/reports/generate" \
  -H "Cookie: session=your_session_id" \
  -H "Content-Type: application/json" \
  -d '{
    "type": "monthly",
    "branch_id": null
  }'
```

---

## WebSocket Support

Not yet implemented. Use polling for real-time updates:

```javascript
// Poll every 5 seconds for device status
setInterval(() => {
  fetch('/api/devices/all')
    .then(r => r.json())
    .then(data => updateUI(data))
}, 5000);
```

---

## Response Format

All successful responses follow this format:
```json
{
  "success": true,
  "data": {...} or [...]
}
```

All error responses include:
```json
{
  "success": false,
  "error": "Error message"
}
```

---

## Best Practices

1. **Error Handling** - Always check `success` field
2. **Caching** - Cache analytics for 5-minute intervals
3. **Batch Operations** - Use multiple requests if needed
4. **Monitoring** - Log API response times
5. **Testing** - Test with sample data first

---

## Support

For issues or questions, refer to:
- FEATURES_COMPREHENSIVE.md - Detailed documentation
- IMPLEMENTATION_CHECKLIST_COMPREHENSIVE.md - Testing guide
- IMPLEMENTATION_SUMMARY.md - Overview

---

**End of Quick Reference**
