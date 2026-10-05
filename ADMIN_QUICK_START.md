# Quick Start Guide: IoT Device & User Registration Management
## For EcoPulse Administrators

---

## Getting Started

### Access Admin Dashboards

#### IoT Device Management
1. Login as administrator
2. Navigate to: `/admin/iot-devices`
3. View summary:
   - 📋 Pending devices (awaiting your approval)
   - ✅ Active devices (collecting data)
   - 📊 Total registered devices

#### User Registration Requests
1. Login as administrator
2. Navigate to: `/admin/user-registrations`
3. View summary:
   - 👥 Pending registration requests
   - ✔️ Approved user accounts
   - ❌ Rejected requests

---

## Managing IoT Devices

### Dashboard Overview
```
┌─────────────────────────────────────────┐
│  IoT Device Management Dashboard         │
├─────────────────────────────────────────┤
│  Pending: 3  │  Active: 12  │  Total: 15│
├─────────────────────────────────────────┤
│ Device Name    | User        | Status    │
├─────────────────────────────────────────┤
│ Living Room    | john_doe    | Pending ⏳ │
│ Kitchen Smart  | jane_smith  | Active  ✅ │
│ Solar Panel    | business1   | Active  ✅ │
└─────────────────────────────────────────┘
```

### Task 1: Approve a Pending Device

1. **View Pending Devices**
   - Devices with "Pending" status need your approval
   - Shows: Device name, Owner, Serial number, MAC address

2. **Review Device Information**
   - Click "Details" to see full information:
     - Device manufacturer and model
     - Power rating (watts)
     - API key (for device configuration)
     - Created date and time

3. **Approve Device**
   - Click "Approve" button
   - Device status changes to "Active"
   - Device can now send data
   - User receives notification

### Task 2: Monitor Active Devices

1. **Check Device Status**
   - Green status = Device is online and working
   - Last reading shows when data was received
   - Current power consumption visible

2. **Investigate Issues**
   - Devices not receiving data?
   - Check "Last Reading" timestamp
   - If very old, contact device owner
   - May need to restart device or check connection

### Task 3: Manage Device Data

**View Device Data History:**
- Click device name to see detailed history
- Shows: Timestamps, energy values (kWh), power (watts)
- Useful for troubleshooting data collection issues

---

## Managing User Registrations

### Dashboard Overview
```
┌──────────────────────────────────────────┐
│  User Registration Management Dashboard   │
├──────────────────────────────────────────┤
│  Pending: 5  │  Approved: 48  │  Rejected: 3│
├──────────────────────────────────────────┤
│ User          | Type         | Submitted   │
├──────────────────────────────────────────┤
│ john_doe      | Home Owner   | 2025-01-15 │
│ business_co   | Business     | 2025-01-14 │
│ sarah_smith   | Home Owner   | 2025-01-14 │
└──────────────────────────────────────────┘
```

### Task 1: Review Registration Request

1. **See Request Summary**
   - Name and email address
   - User type (Home Owner or Business Owner)
   - Business details (if business owner)
   - Submission date

2. **View Full Details**
   - Click request to see complete information
   - Verify all fields are filled correctly
   - Check business registration for business owners
   - Review address information

### Task 2: Approve User Registration

1. **Select Pending Request**
   - Find user in pending list
   - Review information (click for full details if needed)

2. **Click "Approve" Button**
   - System creates user account
   - Generates temporary password
   - Shows: `Temporary Password: TempPass1234!`

3. **Share Temporary Password**
   - Share password with user securely
   - User logs in with temporary password
   - System forces password change on first login
   - User account is now active

**After Approval:**
- ✅ User can login
- ✅ User receives confirmation email
- ✅ For business owners: default branch created
- ✅ For home owners: meter number auto-assigned

### Task 3: Reject User Registration

1. **Select Request to Reject**
   - Click "Reject" button

2. **Provide Reason (Optional)**
   - Dialog appears for rejection reason
   - Examples:
     - "Missing business registration details"
     - "Duplicate registration"
     - "Incomplete information"
     - "Invalid business registration number"

3. **Confirm Rejection**
   - User notified of rejection
   - Can resubmit with corrected information

---

## Common Workflows

### Workflow 1: New Home Owner Registration

**Step 1:** User Submits Request
- User goes to registration page
- Selects "Home Owner"
- Provides: name, email, address, meter number (optional)
- Submits request

**Step 2:** You Review (Admin)
- See request in pending list
- Check email and address are valid
- Verify meter number format (if provided)

**Step 3:** You Approve (Admin)
- Click "Approve"
- Receive temporary password
- Share password with user

**Step 4:** User Activates Account
- User receives confirmation email
- Logs in with username and temporary password
- Changes password
- Account ready to use

**Step 5:** User Registers Device
- User can now register IoT devices
- Devices show as "pending" in your dashboard
- You approve devices in IoT Device dashboard

---

### Workflow 2: New Business Owner Registration

**Step 1:** User Submits Request
- User selects "Business Owner"
- Provides:
  - Business name
  - Business registration number
  - Business type (retail, manufacturing, etc.)
  - Number of locations
  - Contact information

**Step 2:** You Verify (Admin)
- Check business registration number is valid
- Verify business type makes sense
- Review all required fields completed

**Step 3:** You Approve (Admin)
- Click "Approve"
- System creates account AND default branch
- Share temporary password with user

**Step 4:** User Activates Account
- Logs in, changes password
- Account ready

**Step 5:** User Creates Additional Branches
- User can add more business locations
- Each branch can have its own devices
- You approve devices for each branch

---

### Workflow 3: IoT Device Registration & Approval

**Step 1:** User Registers Device
- User calls API or uses device registration form
- Provides device details and specifications
- Device appears in your dashboard (status: pending)

**Step 2:** You Review Device (Admin)
- See device in pending list
- Check device information
- Verify it's a legitimate device

**Step 3:** You Approve Device (Admin)
- Click "Approve" in device row
- Device status changes to "Active"
- Device can now send data

**Step 4:** Device Starts Sending Data
- Device begins uploading energy data
- Data visible in user's dashboard
- Last reading timestamp updates
- Device status shows "online"

---

## API Reference for Quick Testing

### Test IoT Device Approval (Admin)
```
POST /admin/approve_device/{device_id}

curl -X POST http://localhost:5000/admin/approve_device/1 \
  -H "Authorization: Bearer <admin_token>"
```

### Test User Approval (Admin)
```
POST /api/admin/user-registrations/{request_id}/approve

curl -X POST http://localhost:5000/api/admin/user-registrations/1/approve \
  -H "Authorization: Bearer <admin_token>"
```

### Get All Pending Registrations (Admin)
```
GET /api/admin/user-registrations?status=pending

curl -X GET http://localhost:5000/api/admin/user-registrations?status=pending \
  -H "Authorization: Bearer <admin_token>"
```

---

## Best Practices

### For IoT Device Management

✅ **DO:**
- Review device information before approval
- Verify MAC address format is valid
- Check serial numbers are realistic
- Approve devices promptly to keep users satisfied
- Monitor last reading timestamps for offline devices

❌ **DON'T:**
- Approve devices without reviewing details
- Ignore devices that haven't reported in 24+ hours
- Allow duplicate device registrations
- Share API keys with users

### For User Registration Management

✅ **DO:**
- Verify business registration numbers for business owners
- Check email addresses are valid
- Request clarification if information is incomplete
- Respond to requests within 24 hours
- Share temporary passwords securely

❌ **DON'T:**
- Approve requests with incomplete information
- Share permanent passwords
- Allow duplicate usernames or emails
- Forget to provide temporary password

---

## Troubleshooting

### Issue: Device showing as "offline"
**Solution:**
- Check last reading timestamp
- If very recent: Device is online but idle
- If old (>1 hour): Device may have connectivity issues
- Contact device owner to check connection

### Issue: User can't login after approval
**Solution:**
- Verify user received temporary password
- Check that user used exact username provided
- Verify admin account used correct capitalization
- Have user reset password if needed

### Issue: Can't find pending request
**Solution:**
- Check dashboard is loading (refresh page)
- May have already been processed
- Search for user by email address
- Check "All" status to see approved/rejected

### Issue: Device API key not working
**Solution:**
- Ensure device is approved (status: active)
- Verify API key matches in device configuration
- Check X-API-Key header is in request
- Contact device manufacturer if issues persist

---

## Key Information

### Status Meanings

**IoT Devices:**
- 🟡 Pending: Awaiting admin approval
- 🟢 Active: Approved and collecting data
- 🔴 Inactive: Device deactivated or offline
- ⚫ Decommissioned: Device retired

**User Registrations:**
- 🟡 Pending: Awaiting your review/decision
- 🟢 Approved: User account created, ready to use
- 🔴 Rejected: Application declined
- 🟠 Under Review: Being verified

### User Types

**Home Owner:**
- Single location
- Basic energy monitoring
- Personal device management
- Standard reporting

**Business Owner:**
- Multiple locations (branches)
- Advanced analytics
- Multi-device management
- Business reporting

---

## Quick Statistics

Monitor dashboard metrics:

```
Pending Requests    → Review these today
Active Devices      → Data collection status
Approval Rate       → Track processing speed
Rejection Rate      → Identify common issues
```

---

## Support Contacts

For technical issues:
1. Check this guide first
2. Review error messages in admin dashboard
3. Check application logs
4. Contact development team

---

## Next Steps

1. ✅ Access admin dashboards
2. ✅ Review pending items
3. ✅ Approve first device
4. ✅ Approve first user
5. ✅ Monitor activity
6. ✅ Establish approval workflow/SLA

---

**Last Updated:** 2025-01-15  
**Version:** 1.0  
**For:** System Administrators
