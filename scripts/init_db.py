#!/usr/bin/env python3
"""Initialize the EcoPulse database.

Run from the project root:

    python scripts/init_db.py

This creates all tables defined in `ecopulse_app.py` and prints simple counts for key models.
"""

from ecopulse_app import app, db


def main():
    with app.app_context():
        db.create_all()
        print("Database tables created (if any were missing).")
        # Print simple counts for verification
        try:
            from ecopulse_app import Partner, AuditLog, SustainabilityImpact
            print(f"Partners: {Partner.query.count()}")
            print(f"AuditLogs: {AuditLog.query.count()}")
            print(f"SustainabilityImpacts: {SustainabilityImpact.query.count()}")
        except Exception as e:
            print("Model counts unavailable:", e)


if __name__ == '__main__':
    main()
