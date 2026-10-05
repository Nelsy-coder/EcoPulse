# IoT Device Registration & Admin User Management Features
## EcoPulse Energy Monitoring System

**Implementation Date:** 2025
**Status:** ✅ Complete and Production Ready

---

## 📋 Table of Contents
1. [Overview](#overview)
2. [IoT Device Registration System](#iot-device-registration-system)
3. [Admin User Registration & Approval](#admin-user-registration--approval)
4. [Database Models](#database-models)
5. [API Endpoints](#api-endpoints)
6. [Admin Dashboards](#admin-dashboards)
7. [User Workflows](#user-workflows)
8. [Testing Guide](#testing-guide)

---

## Overview

This implementation adds two major features to EcoPulse:

### 1. **IoT Device Registration & Integration**
- Register IoT devices with MAC address, serial number, and device type
- Generate API keys for device authentication
- Monitor device status and real-time data collection
- Admin approval workflow for devices
- Multi-location support for business owners

### 2. **Admin-Controlled User Registration**
- Users submit registration requests (not direct signup)
- Admin reviews and approves/rejects requests
- Three user types: Home Owner, Business Owner, Administrator
- Role-based permissions and access control
- Automatic user account creation upon approval

---

## IoT Device Registration System

### Features

#### 1. Device Registration
- **User Capability**: Home owners and business owners can register new IoT devices
- **Required Information**:
  - Device name
  - Device type (smart_meter, smart_plug, solar_panel, etc.)
  - MAC address (optional but recommended)
  - Serial number (optional but recommended)
  - Power rating (watts)
  - Usage hours per day
  - Quantity

#### 2. Device Authentication
- **API Key Generation**: Each device receives a unique API key and secret
- **Authentication**: POST requests to data collection endpoint require `X-API-Key` header
- **Status Tracking**: Devices have lifecycle status: pending → active → inactive

#### 3. Real-Time Data Collection
- Devices send energy consumption data via API endpoint
- Data automatically recorded with timestamp
- Device status updated (online/offline, current power)
- Last reading timestamp tracked

#### 4. Device Status Monitoring
- Real-time online/offline status
- Current power consumption
- Last activity timestamp
- Customizable data collection intervals

#### 5. Admin Approval Workflow
- All new devices initially in "pending" status
- Admin dashboard shows pending devices
- One-click approval process
- Device activation upon approval

---

## Admin User Registration & Approval

### Features

#### 1. Registration Request Submission
- **Public Endpoint**: Users can submit requests without authentication
- **User Types**:
  - **Home Owner**: Single-location residential energy monitoring
  - **Business Owner**: Multi-location business energy management
  - **Examiner/Admin**: Staff accounts (admin-created only)

- **Home Owner Fields**:
  - Username, Email, Phone
  - Residential address
  - Meter number (optional)
  - User type confirmation

- **Business Owner Fields**:
  - Username, Email, Phone
  - Business name
  - Business registration number
  - Business type (retail, manufacturing, hospitality, etc.)
  - Number of locations
  - Business address

#### 2. Admin Review Process
- Admin dashboard displays all pending requests
- Detailed view shows all submitted information
- Admin can approve or reject requests
- Optional notes/reason for rejection

#### 3. Automatic Account Creation
- Upon approval, user account automatically created
- Temporary password generated and shared with admin
- User settings initialized
- For business owners: default branch created automatically
- For customers: meter number auto-generated if not provided

#### 4. Permission Management
- Home Owners: Basic monitoring and reporting
- Business Owners: Multi-location management, advanced analytics
- Administrators: Full system access
- Examiners: Review and approval capabilities

---

## Database Models

### 1. IoTDeviceRegistration Model
```python
class IoTDeviceRegistration(db.Model):
    id                      # Primary key
    device_id              # FK to CustomerDevice
    user_id                # FK to User (owner)
    
    # Device Identification
    mac_address            # Unique MAC address
    serial_number          # Unique serial number
    device_type            # Type of device
    manufacturer           # Device manufacturer
    model                  # Device model
    
    # API Authentication
    api_key                # Unique API key for device
    api_secret             # Secure API secret
    is_authenticated       # Authentication status
    authentication_timestamp
    
    # Status & Configuration
    status                 # pending/registered/active/inactive
    is_approved_by_admin   # Admin approval flag
    approved_by            # FK to approver
    approved_at            # Approval timestamp
    
    # Data Collection
    data_collection_enabled
    collection_interval    # In seconds
    last_data_received     # Timestamp of last data
    
    # Firmware
    firmware_version       # Current firmware version
    last_update_check
    last_firmware_update
    
    # Multi-Location
    branch_id              # FK to Branch (for business owners)
    location_name
    
    # Audit
    created_at
    updated_at
    created_by             # FK to User
```

### 2. UserRegistrationRequest Model
```python
class UserRegistrationRequest(db.Model):
    id                           # Primary key
    
    # User Information
    username                     # Requested username
    email                        # Email address
    phone                        # Phone number
    first_name                   # First name
    last_name                    # Last name
    
    # User Classification
    user_type                    # home_owner/business_owner
    requested_role               # customer/examiner/admin
    
    # Business Information
    business_name                # For business owners
    business_registration_number
    business_type
    number_of_locations
    
    # Residential Information
    residential_address
    meter_number
    
    # Approval Workflow
    status                       # pending/approved/rejected/under_review
    submission_date
    review_date
    reviewed_by                  # FK to reviewing admin
    review_notes
    rejection_reason
    
    # Account Creation
    created_user_id              # FK to created User
    account_creation_date
    
    # Verification
    email_verified
    phone_verified
    verification_token
    verification_token_expires
    
    # Permissions
    permissions                  # JSON string of permissions
    feature_tier                 # basic/standard/premium
    
    # Audit
    created_at
    updated_at
    ip_address
    user_agent
```

---

## API Endpoints

### IoT Device Registration APIs

#### 1. Register IoT Device
```
POST /api/iot/register
Content-Type: application/json
Authorization: Bearer <token>

{
  "device_name": "Living Room Smart Meter",
  "device_type": "smart_meter",
  "mac_address": "00:1A:2B:3C:4D:5E",
  "serial_number": "SM12345678",
  "manufacturer": "Siemens",
  "model": "7KT30",
  "watts": 5000,
  "hours_per_day": 24,
  "quantity": 1,
  "notes": "Main meter for whole building"
}

Response:
{
  "success": true,
  "device_id": 1,
  "api_key": "abcd1234efgh5678ijkl9012mnop3456",
  "api_secret": "secret_key_1234567890",
  "status": "pending",
  "message": "IoT device registered. Awaiting admin approval."
}
```

#### 2. Submit IoT Data
```
POST /api/iot/devices/{device_id}/data
Headers:
  X-API-Key: <device_api_key>
Content-Type: application/json

{
  "value": 45.5,
  "unit": "kWh",
  "power": 1200,
  "status": "running"
}

Response:
{
  "success": true,
  "message": "Data received successfully",
  "timestamp": "2025-01-15T10:30:00"
}
```

#### 3. Get Device Status
```
GET /api/iot/devices/{device_id}/status
Authorization: Bearer <token>

Response:
{
  "device_id": 1,
  "device_name": "Living Room Smart Meter",
  "is_online": true,
  "current_power": 1200,
  "device_status": "running",
  "last_reading": "2025-01-15T10:29:30",
  "is_approved": true,
  "registration_status": "active"
}
```

#### 4. Get Device Data History
```
GET /api/iot/devices/{device_id}/history?days=7
Authorization: Bearer <token>

Response:
{
  "device_id": 1,
  "device_name": "Living Room Smart Meter",
  "period_days": 7,
  "records_count": 168,
  "data": [
    {
      "timestamp": "2025-01-15T10:30:00",
      "value": 45.5,
      "unit": "kWh"
    },
    ...
  ]
}
```

#### 5. Get All IoT Devices
```
GET /api/iot/devices
Authorization: Bearer <token>

Response:
{
  "devices": [
    {
      "id": 1,
      "name": "Living Room Smart Meter",
      "category": "smart_meter",
      "watts": 5000,
      "hours_per_day": 24,
      "monthly_kwh": 3600,
      "status": "running",
      "is_online": true,
      "created_at": "2025-01-10T15:00:00"
    }
  ],
  "total_devices": 5
}
```

### Admin User Registration APIs

#### 1. Public: Submit Registration Request
```
POST /api/registration-request
Content-Type: application/json

{
  "username": "john_doe",
  "email": "john@example.com",
  "phone": "+254712345678",
  "first_name": "John",
  "last_name": "Doe",
  "user_type": "home_owner",
  "requested_role": "customer",
  "residential_address": "123 Main St, Nairobi"
}

Response:
{
  "success": true,
  "request_id": 42,
  "status": "pending",
  "message": "Registration request submitted successfully"
}
```

#### 2. Check Registration Request Status
```
GET /api/registration-request/{request_id}/status
(No authentication required)

Response:
{
  "request_id": 42,
  "username": "john_doe",
  "email": "john@example.com",
  "status": "pending",
  "submission_date": "2025-01-15T10:00:00",
  "message": "Your registration request is pending."
}
```

#### 3. Get User Registration Requests (Admin)
```
GET /api/admin/user-registrations?status=pending
Authorization: Admin required

Response:
{
  "registrations": [
    {
      "id": 42,
      "username": "john_doe",
      "email": "john@example.com",
      "user_type": "home_owner",
      "requested_role": "customer",
      "status": "pending",
      "submission_date": "2025-01-15T10:00:00"
    }
  ],
  "total": 3
}
```

#### 4. Get Registration Request Details (Admin)
```
GET /api/admin/user-registrations/{request_id}
Authorization: Admin required

Response:
{
  "id": 42,
  "username": "john_doe",
  "email": "john@example.com",
  "phone": "+254712345678",
  "first_name": "John",
  "last_name": "Doe",
  "user_type": "home_owner",
  "requested_role": "customer",
  "residential_address": "123 Main St, Nairobi",
  "meter_number": null,
  "status": "pending",
  "submission_date": "2025-01-15T10:00:00",
  "email_verified": false,
  "phone_verified": false
}
```

#### 5. Approve Registration Request (Admin)
```
POST /api/admin/user-registrations/{request_id}/approve
Authorization: Admin required

Response:
{
  "success": true,
  "user_id": 123,
  "username": "john_doe",
  "email": "john@example.com",
  "temporary_password": "TempPass1234!",
  "message": "User created successfully. Share temporary password."
}
```

#### 6. Reject Registration Request (Admin)
```
POST /api/admin/user-registrations/{request_id}/reject
Authorization: Admin required
Content-Type: application/json

{
  "reason": "Incomplete business registration information"
}

Response:
{
  "success": true,
  "message": "Registration request rejected"
}
```

#### 7. Admin: Create User Directly
```
POST /api/admin/users/register
Authorization: Admin required
Content-Type: application/json

{
  "username": "new_admin",
  "email": "admin@example.com",
  "password": "SecurePassword123!",
  "role": "admin",
  "user_type": "smart_home",
  "phone_number": "+254712345678"
}

Response:
{
  "success": true,
  "user_id": 124,
  "username": "new_admin",
  "email": "admin@example.com",
  "message": "User created successfully"
}
```

---

## Admin Dashboards

### 1. IoT Device Management Dashboard
**Route:** `/admin/iot-devices`
**Required Role:** Admin

**Features:**
- View all IoT device registrations
- Summary cards showing:
  - Pending devices (awaiting approval)
  - Active devices (collecting data)
  - Total devices
- Device list table with columns:
  - Device name
  - Owner username
  - Serial number
  - MAC address
  - Current status
  - Last reading timestamp
  - Action buttons (Approve, Details)
- Approve pending devices
- View detailed device information

### 2. User Registration Management Dashboard
**Route:** `/admin/user-registrations`
**Required Role:** Admin

**Features:**
- Display pending registration requests
- Summary cards showing:
  - Number of pending requests
  - Approved accounts created
  - Rejected requests
- Pending requests list showing:
  - User name and email
  - User type (home owner/business owner)
  - Business name (if applicable)
  - Submission date
  - Action buttons (Approve, Reject)
- Approve user registrations with one-click
- Reject with reason dialog
- View registration details modal

---

## User Workflows

### IoT Device Registration Workflow

```
1. User Registers Device
   ├─ POST /api/iot/register
   ├─ Device created (status: "pending")
   ├─ API key/secret generated
   └─ Returns pending status

2. Admin Approves Device
   ├─ Admin dashboard shows pending device
   ├─ Admin clicks "Approve"
   ├─ POST /admin/approve_device/{device_id}
   ├─ Device status changes to "active"
   └─ User notified

3. Device Collects Data
   ├─ Device sends data to /api/iot/devices/{device_id}/data
   ├─ Request includes X-API-Key header
   ├─ Data recorded in IoTData table
   ├─ Device status updated
   └─ Timestamp tracked

4. User Monitors Device
   ├─ GET /api/iot/devices/{device_id}/status
   ├─ GET /api/iot/devices/{device_id}/history
   └─ View real-time and historical data
```

### User Registration Request Workflow

```
1. User Submits Registration Request
   ├─ POST /api/registration-request
   ├─ Provide: username, email, user_type
   ├─ Request stored (status: "pending")
   └─ Receive request_id

2. User Checks Status
   ├─ GET /api/registration-request/{request_id}/status
   └─ View current status

3. Admin Reviews Request
   ├─ Admin dashboard shows pending requests
   ├─ Click on request for details
   ├─ Review user information
   └─ Verify all required fields

4. Admin Approves Request
   ├─ Click "Approve" button
   ├─ POST /api/admin/user-registrations/{request_id}/approve
   ├─ User account created automatically
   ├─ Temporary password generated
   └─ Admin receives password to share

5. User Activates Account
   ├─ Login with username and temporary password
   ├─ System prompts password change
   └─ Account now active
```

---

## Testing Guide

### 1. IoT Device Registration Testing

#### Test Case 1: Register Device
```bash
curl -X POST http://localhost:5000/api/iot/register \
  -H "Authorization: Bearer <user_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "device_name": "Test Device",
    "device_type": "smart_meter",
    "mac_address": "00:1A:2B:3C:4D:5E",
    "serial_number": "TEST123",
    "watts": 2000,
    "hours_per_day": 8
  }'
```

#### Test Case 2: Send IoT Data
```bash
curl -X POST http://localhost:5000/api/iot/devices/1/data \
  -H "X-API-Key: <api_key>" \
  -H "Content-Type: application/json" \
  -d '{
    "value": 23.5,
    "unit": "kWh",
    "power": 1500,
    "status": "running"
  }'
```

#### Test Case 3: Get Device Status
```bash
curl -X GET http://localhost:5000/api/iot/devices/1/status \
  -H "Authorization: Bearer <user_token>"
```

### 2. User Registration Testing

#### Test Case 1: Submit Registration Request (Home Owner)
```bash
curl -X POST http://localhost:5000/api/registration-request \
  -H "Content-Type: application/json" \
  -d '{
    "username": "test_user",
    "email": "test@example.com",
    "phone": "+254712345678",
    "user_type": "home_owner",
    "requested_role": "customer",
    "residential_address": "123 Test Street"
  }'
```

#### Test Case 2: Submit Registration Request (Business Owner)
```bash
curl -X POST http://localhost:5000/api/registration-request \
  -H "Content-Type: application/json" \
  -d '{
    "username": "business_user",
    "email": "business@example.com",
    "phone": "+254712345678",
    "user_type": "business_owner",
    "requested_role": "customer",
    "business_name": "Test Business",
    "business_type": "retail",
    "number_of_locations": 2
  }'
```

#### Test Case 3: Check Registration Status
```bash
curl -X GET http://localhost:5000/api/registration-request/1/status
```

#### Test Case 4: Admin Review Requests
```bash
curl -X GET http://localhost:5000/api/admin/user-registrations \
  -H "Authorization: Bearer <admin_token>"
```

#### Test Case 5: Admin Approve Request
```bash
curl -X POST http://localhost:5000/api/admin/user-registrations/1/approve \
  -H "Authorization: Bearer <admin_token>"
```

---

## Integration with Existing Features

### Customer Dashboard Integration
- IoT devices shown in customer dashboard
- Real-time device status indicators
- Device energy consumption analytics
- Device management sections

### Notification System
- When IoT device registered: Notification to user
- When device approved: Email notification to user
- When registration approved: Email with temporary password
- Device data collection errors: Alert to user

### Reporting
- IoT device contributions to total energy usage
- Device-level consumption reports
- Multi-location aggregation for business owners
- Device efficiency comparisons

---

## Security Considerations

### API Key Security
- API keys stored securely in database
- Secrets hashed or encrypted
- Keys rotation capability
- Rate limiting on data endpoints

### User Registration Security
- Email verification required for sensitive operations
- Phone verification optional but recommended
- Temporary passwords expire after first use
- Admin review prevents unauthorized registrations

### Data Privacy
- Device data accessible only to device owner and admins
- Location data secured for business locations
- Business registration information confidential
- Audit trail for all admin actions

---

## Future Enhancements

1. **Firmware Updates**
   - Auto-update capability for IoT devices
   - Firmware version management
   - Rollback capability

2. **Advanced Analytics**
   - Machine learning-based anomaly detection
   - Predictive maintenance alerts
   - Device efficiency scoring

3. **Integration Expansion**
   - Support for more IoT platforms
   - Third-party API integrations
   - Cloud device management

4. **Mobile App**
   - Native mobile app for device management
   - Mobile push notifications
   - Offline data synchronization

---

## Troubleshooting

### Common Issues

**Issue:** API key not recognized
- **Solution:** Verify API key is correct and device is approved

**Issue:** Device data not received
- **Solution:** Check device connection, verify X-API-Key header

**Issue:** Registration request stuck in pending
- **Solution:** Contact system administrator

**Issue:** Cannot approve device
- **Solution:** Ensure logged in as admin, device exists

---

## Support & Documentation

For questions or issues:
1. Review this documentation
2. Check API endpoint specifications
3. Review error messages in logs
4. Contact system administrator

---

**Document Version:** 1.0  
**Last Updated:** 2025-01-15  
**Status:** Production Ready ✅
