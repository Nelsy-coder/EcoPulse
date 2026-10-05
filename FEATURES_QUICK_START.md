# EcoPulse New Features - Quick Start Guide

## 🎯 Customer Features

### Energy Goal Tracker
**Navigate to:** `http://localhost:5000/goals`

1. Click **"Set New Energy Goal"**
2. Choose goal type:
   - Monthly Energy Savings (kWh)
   - Annual Reduction (%)
3. Enter target value and target date
4. Track progress on the dashboard

### Community Forum
**Navigate to:** `http://localhost:5000/forum`

1. Browse existing posts or filter by category
2. Click **"Create Post"** to start a discussion
3. Choose category: Tips, Questions, Experiences
4. Reply to posts to engage with community
5. Posts show likes and reply counts

### AI Chat Assistant
**Navigate to:** `http://localhost:5000/chat`

1. Type your energy-related question
2. AI provides suggestions for energy saving
3. Conversation history displayed in chat window
4. Real-time responses

### Dark/Light Mode
- **Toggle button** in user settings or navbar
- Theme preference saved in session
- Auto-applies to all pages

---

## 📋 Examiner Features

### Rubrics Management
**Navigate to:** `http://localhost:5000/rubrics`

1. Click **"Create Rubric"**
2. Define rubric name and description
3. Add criteria in JSON format:
   ```json
   {
     "efficiency": {
       "weight": 0.4,
       "levels": ["Poor", "Good", "Excellent"]
     },
     "accuracy": {
       "weight": 0.6,
       "levels": ["Poor", "Good", "Excellent"]
     }
   }
   ```
4. Use for evaluating customer submissions

### Comment Templates
**Navigate to:** `http://localhost:5000/templates`

1. Click **"Create Template"**
2. Enter template name and category
3. Add reusable feedback text with placeholders:
   - `{customer_name}`
   - `{reading_value}`
   - `{date}`
4. Quick-apply templates when reviewing

### Performance Analytics
**Navigate to:** `http://localhost:5000/analytics`

1. View all customer performance metrics
2. See metric types: savings, efficiency, consistency
3. Track improvement rates over periods
4. Filter by customer or date range

---

## ⚙️ Admin Features

### Sub-Admin Role Management
**Navigate to:** `http://localhost:5000/sub-admins`

1. Click **"Assign Sub-Admin Role"**
2. Select user and role:
   - Forum Moderator
   - Support Admin
   - Content Admin
   - Analytics Admin
3. Define permissions (JSON):
   ```json
   {
     "forum": ["read", "moderate"],
     "reports": ["view"],
     "users": ["edit"]
   }
   ```
4. Role assigned immediately

### System Health Monitoring
**Navigate to:** `http://localhost:5000/health`

1. View health status of components:
   - Database: Healthy/Warning/Critical
   - Server: Operational status
   - API: Response status
2. Check last check timestamp
3. Review detailed metrics
4. Set up alerts for critical states

### Backup Scheduler
**Navigate to:** `http://localhost:5000/backups`

1. Click **"Create Schedule"**
2. Configure:
   - Schedule name
   - Frequency: Hourly, Daily, Weekly
   - Type: Full or Incremental
   - Retention period (days)
3. Enable/disable schedules
4. View last run timestamp

### Feature Rollout Management
**Navigate to:** `http://localhost:5000/rollouts`

1. Click **"Create Rollout"**
2. Enter feature name and description
3. Set initial rollout percentage (0-100%)
4. Define target users (JSON):
   ```json
   {
     "user_types": ["customer"],
     "departments": ["IT Security"],
     "energy_sources": ["Solar"]
   }
   ```
5. Gradually increase rollout % over time

---

## 🎨 Hero Section Features

### Demo Video
- Embedded on homepage hero section
- Auto-plays overview of EcoPulse
- Informs visitors about platform features

### Real-Time Impact Counters
Displayed on homepage:
- **Total Energy Saved:** Cumulative kWh
- **Users Onboarded:** Active user count
- **Carbon Reduced:** Metric tons CO₂

**Update API (Admin only):**
```bash
POST /api/update_impact_counter/total_energy_saved
Content-Type: application/json

{"value": 150000}
```

### Role-Based Action Buttons
- **Customer Button:** Direct registration link
- **Dashboard Button:** Quick login for existing users
- **Staff Access Dropdown:**
  - Examiner Portal
  - Admin Portal

### Sustainability Pledge Banner
- Fixed at bottom of homepage
- Encouraging commitment message
- Call-to-action button
- Mobile-responsive

---

## 📊 Database Models Quick Reference

### Customer Models
```
EnergyGoal
├── user_id (FK)
├── goal_type (monthly_savings | annual_reduction)
├── target_value (numeric)
├── current_value (numeric)
├── status (active | completed | failed)
└── dates (start, end)

ForumPost
├── user_id (FK)
├── title
├── content
├── category (tips | questions | experiences)
├── likes
└── replies_count

ForumReply
├── post_id (FK)
├── user_id (FK)
├── content
└── likes
```

### Examiner Models
```
Rubric
├── name
├── criteria (JSON)
├── description
└── created_by (FK)

CommentTemplate
├── name
├── content
├── category
└── created_by (FK)

PerformanceAnalytics
├── user_id (FK)
├── metric_type
├── value
├── improvement_rate
└── period
```

### Admin Models
```
SubAdminRole
├── user_id (FK)
├── role_name
├── permissions (JSON)
└── assigned_by (FK)

SystemHealth
├── component
├── status
├── metrics (JSON)
└── last_checked

BackupSchedule
├── name
├── frequency
├── backup_type
├── retention_days
├── is_active
└── dates (last_run, next_run)

FeatureRollout
├── feature_name
├── description
├── rollout_percentage
├── target_users (JSON)
├── is_active
└── created_by (FK)

ImpactCounter
├── metric_name
├── value
├── last_updated
└── update_frequency
```

---

## 🔐 Access Control Matrix

| Route | Customer | Examiner | Admin | Public |
|-------|----------|----------|-------|--------|
| `/goals` | ✅ | ❌ | ❌ | ❌ |
| `/forum` | ✅ | ❌ | ❌ | ❌ |
| `/chat` | ✅ | ❌ | ❌ | ❌ |
| `/rubrics` | ❌ | ✅ | ❌ | ❌ |
| `/templates` | ❌ | ✅ | ❌ | ❌ |
| `/analytics` | ❌ | ✅ | ❌ | ❌ |
| `/sub-admins` | ❌ | ❌ | ✅ | ❌ |
| `/health` | ❌ | ❌ | ✅ | ❌ |
| `/backups` | ❌ | ❌ | ✅ | ❌ |
| `/rollouts` | ❌ | ❌ | ✅ | ❌ |
| `/toggle_theme` | ✅ | ✅ | ✅ | ❌ |
| `/api/impact_counters` | ✅ | ✅ | ✅ | ✅ |

---

## 📝 API Endpoints Summary

### Customer APIs
- `GET /goals` - List goals
- `POST /goals/create` - Create goal
- `POST /goals/<id>/update` - Update progress
- `GET /forum` - Browse forum
- `POST /forum/post` - Create post
- `GET /forum/post/<id>` - View post
- `POST /forum/post/<id>/reply` - Reply
- `POST /api/chat/message` - Chat with AI

### Examiner APIs
- `GET /rubrics` - List rubrics
- `POST /rubrics/create` - Create rubric
- `GET /templates` - List templates
- `POST /templates/create` - Create template
- `GET /analytics` - View analytics

### Admin APIs
- `GET /sub-admins` - List sub-admins
- `POST /sub-admins/create` - Create role
- `GET /health` - System health
- `GET /backups` - List schedules
- `POST /backups/create` - Create schedule
- `GET /rollouts` - List rollouts
- `POST /rollouts/create` - Create rollout
- `GET /api/impact_counters` - Get counters
- `POST /api/update_impact_counter/<metric>` - Update counter

---

## 🚀 Getting Started

1. **First Run:**
   ```bash
   python ecopulse_app.py
   ```
   - Database tables created automatically
   - Sample impact counters initialized
   - Default departments created
   - Test users established

2. **Default Test Accounts:**
   - **Customer:** customer.demo@ecopulse.local / password
   - **Examiner:** examiner.demo@ecopulse.local / password
   - **Admin:** admin.demo@ecopulse.local / password

3. **Access Features:**
   - Navigate to feature routes after login
   - Features appear in user dashboard
   - Mobile-responsive design works on all devices

---

## 💡 Tips & Best Practices

### For Customers
- Set realistic energy goals
- Engage with community for tips
- Use AI chat for personalized advice
- Track progress regularly

### For Examiners
- Create reusable rubrics for efficiency
- Use comment templates to standardize feedback
- Review analytics for insights
- Export reports for documentation

### For Admins
- Schedule regular backups (daily recommended)
- Monitor system health weekly
- Gradually rollout new features (start at 10%)
- Assign moderate roles to trusted staff

---

## 🐛 Troubleshooting

**Features not appearing?**
- Verify user role is set correctly
- Clear browser cache
- Restart Flask application

**Database errors?**
- Check `instance/` folder exists
- Ensure database file has write permissions
- Run `python ecopulse_app.py` to initialize

**Templates not rendering?**
- Verify `base.html` exists in templates folder
- Check Jinja2 variable names match
- Review browser console for JavaScript errors

**Impact counters not updating?**
- Verify counters table created
- Check admin permissions
- Use API endpoint to manually update

---

**Need Help?** Check the FEATURES_ADDED.md for detailed documentation.
