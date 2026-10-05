# EcoPulse Energy Management Dashboard

EcoPulse is a Flask-based energy management application.

## Prerequisites
- Python 3.8+
- A virtual environment (recommended)

## Setup and Installation

1. **Create and activate the virtual environment**
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\activate
   ```

2. **Install dependencies**
   ```powershell
   pip install -r requirements.txt
   ```

3. **Configure Environment Variables**
   The application uses environment variables for real email notifications (SMTP). Copy or create the `smtp.env` file in the project directory:
   ```
   ECOULSE_SMTP_HOST=smtp.gmail.com
   ECOULSE_SMTP_PORT=587
   ECOULSE_SMTP_USERNAME=example@gmail.com
   ECOULSE_SMTP_PASSWORD="your app password."
   ECOULSE_SMTP_FROM=example@gmail.com
   ECOULSE_SMTP_USE_TLS=true
   ```

   Note: staff/admin/examiner logins are handled separately from the public customer login.
   Use the hidden route: `/ops/portal/login-2026` or the alias `/staff/login`.

## Running the Application

You can start the server directly using Python. The application is configured to automatically parse the `smtp.env` file if it exists.

```powershell
python ecopulse_app.py
```

Once started, the application will run locally and be accessible at `http://127.0.0.1:5000`.

## Features
- Interactive Dashboard tracking energy readings
- Cost & Revenue analysis
- Alerts and Threshold visualization for high energy consumption
- SMTP Integration for billing and payment reminders

## Additional Requested Features
User‑Experience Features
- Interactive Dashboard  
- Real‑time charts showing energy usage, savings, and comparisons with past days/weeks.

- Personalized Tips  
- AI‑driven suggestions like “Run laundry at 9 PM to save 15% energy.”

- Mobile Responsiveness  
- Smooth experience on phones and tablets — customers love accessibility.

- Gamification  
- Badges, points, or rewards for reducing consumption.

- Community Sharing  
- Compare your household’s efficiency with neighbors or similar households.

⚡ Technical & Business Features
- IoT Integration  
- Connect smart plugs, meters, or solar panels for live data.

- Forecasting & Alerts  
- Predict high‑usage days and send alerts before bills spike.

- Data Export  
- Allow customers to download CSV/Excel reports for budgeting or audits.

- Secure Accounts  
- Role‑based access, encrypted data, and privacy controls.

- Payment/Subscription Options  
- If you want to monetize, add premium features like advanced analytics or detailed reports.
