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
   ECOULSE_SMTP_USERNAME=ososinelson4@gmail.com
   ECOULSE_SMTP_PASSWORD=ocvd otrd bmqe btms
   ECOULSE_SMTP_FROM=barongonelson92@gmail.com
   ECOULSE_SMTP_USE_TLS=true
   ```

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
