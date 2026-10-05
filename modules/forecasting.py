"""
Energy Forecasting & Alert Engine
Predicts future energy usage and generates alerts for anomalies
"""
from datetime import datetime, timedelta
import statistics
from enum import Enum

class AlertType(Enum):
    """Types of alerts that can be generated"""
    HIGH_USAGE = 'high_usage'
    BILL_SPIKE = 'bill_spike'
    ANOMALY = 'anomaly'
    DEVICE_FAILURE = 'device_failure'
    THRESHOLD_EXCEEDED = 'threshold_exceeded'

class AlertSeverity(Enum):
    """Alert severity levels"""
    INFO = 'info'
    WARNING = 'warning'
    CRITICAL = 'critical'

class ForecastingEngine:
    """
    Predicts energy usage and generates alerts based on patterns and anomalies
    """
    
    @staticmethod
    def predict_daily_usage(readings, days_ahead=7, user_threshold=None):
        """
        Predict energy usage for next N days
        
        Args:
            readings: Historical energy readings
            days_ahead: Number of days to forecast
            user_threshold: User's energy threshold (kWh)
            
        Returns:
            list: Forecasted daily values
        """
        if not readings or len(readings) < 7:
            return []
        
        # Simple moving average forecast (production would use ARIMA, Prophet, etc.)
        avg_daily = statistics.mean(readings)
        std_dev = statistics.stdev(readings) if len(readings) > 1 else 0
        
        forecast = []
        for day in range(days_ahead):
            future_date = datetime.now().date() + timedelta(days=day+1)
            
            # Add slight day-of-week variation
            day_of_week = future_date.weekday()
            day_factor = 0.95 if day_of_week >= 4 else 1.0  # Weekends typically use less
            
            predicted_usage = avg_daily * day_factor
            risk_level = 'normal'
            
            # Check against threshold
            if user_threshold and predicted_usage > user_threshold:
                risk_level = 'high'
            
            forecast.append({
                'date': future_date.isoformat(),
                'predicted_usage': round(predicted_usage, 2),
                'confidence_interval': [
                    round(predicted_usage - std_dev, 2),
                    round(predicted_usage + std_dev, 2)
                ],
                'confidence_level': 75 - (day * 5),  # Decreases further ahead
                'risk_level': risk_level
            })
        
        return forecast
    
    @staticmethod
    def detect_anomaly(readings, threshold_std_dev=2.0):
        """
        Detect unusual consumption patterns using Z-score method
        
        Args:
            readings: Recent energy readings
            threshold_std_dev: Number of standard deviations to flag as anomaly
            
        Returns:
            dict: Anomaly detection result
        """
        if not readings or len(readings) < 3:
            return {
                'anomaly_detected': False,
                'reason': 'Insufficient data for analysis'
            }
        
        mean = statistics.mean(readings)
        std_dev = statistics.stdev(readings) if len(readings) > 1 else 0
        
        # Compare latest reading to threshold
        latest_reading = readings[-1]
        z_score = (latest_reading - mean) / std_dev if std_dev > 0 else 0
        
        anomaly_detected = abs(z_score) > threshold_std_dev
        
        return {
            'anomaly_detected': anomaly_detected,
            'z_score': round(z_score, 2),
            'threshold': threshold_std_dev,
            'latest_reading': latest_reading,
            'mean': round(mean, 2),
            'std_dev': round(std_dev, 2),
            'severity': AlertSeverity.CRITICAL.value if anomaly_detected else AlertSeverity.INFO.value
        }
    
    @staticmethod
    def send_alert(user_id, alert_type, message, severity='warning', alert_methods=['email']):
        """
        Generate and send alert to user
        
        Args:
            user_id: User identifier
            alert_type: Type of alert
            message: Alert message
            severity: Alert severity level
            alert_methods: How to send alert (email, sms, push, in_app)
            
        Returns:
            dict: Alert creation confirmation
        """
        alert_id = f'ALERT_{user_id}_{int(datetime.now().timestamp())}'
        
        return {
            'success': True,
            'alert_id': alert_id,
            'user_id': user_id,
            'type': alert_type,
            'severity': severity,
            'message': message,
            'methods': alert_methods,
            'created_at': datetime.now().isoformat(),
            'delivery_status': {method: 'pending' for method in alert_methods}
        }
    
    @staticmethod
    def calculate_bill_spike_probability(readings, current_bill, rate_per_kwh):
        """
        Estimate probability and magnitude of bill spike
        
        Args:
            readings: Recent daily readings
            current_bill: Current month's bill amount
            rate_per_kwh: Energy rate (Ksh per kWh)
            
        Returns:
            dict: Bill spike forecast
        """
        if not readings:
            return {
                'spike_probability': 0,
                'estimated_spike_amount': 0,
                'message': 'Insufficient data'
            }
        
        avg_usage = statistics.mean(readings)
        projected_total = avg_usage * 30  # Project for full month
        
        # Calculate based on current trend
        spike_percentage = ((projected_total - avg_usage * 10) / (avg_usage * 10)) * 100
        spike_amount = projected_total * rate_per_kwh - current_bill
        
        # Probability estimation
        if spike_percentage > 30:
            spike_probability = 0.8  # High
        elif spike_percentage > 15:
            spike_probability = 0.5  # Medium
        else:
            spike_probability = 0.1  # Low
        
        return {
            'spike_probability': round(spike_probability, 2),
            'spike_percentage': round(spike_percentage, 2),
            'estimated_spike_amount': round(max(0, spike_amount), 2),
            'projected_monthly_bill': round(projected_total * rate_per_kwh, 2),
            'current_month_bill': current_bill,
            'recommendation': ForecastingEngine._get_spike_recommendation(spike_percentage)
        }
    
    @staticmethod
    def _get_spike_recommendation(spike_percentage):
        """Generate recommendation based on spike probability"""
        if spike_percentage > 30:
            return 'High spike risk! Consider implementing energy conservation measures immediately.'
        elif spike_percentage > 15:
            return 'Moderate increase expected. Monitor usage and adjust consumption if possible.'
        else:
            return 'Expected billing is within normal range.'
    
    @staticmethod
    def predict_peak_hours(readings):
        """
        Identify which hours of day are predicted to have high usage
        
        Args:
            readings: Hourly readings data with timestamps
            
        Returns:
            list: Hours (0-23) sorted by predicted usage
        """
        hourly_avg = {}
        
        # Group readings by hour
        for reading in readings:
            hour = reading.get('hour', 0)
            usage = reading.get('usage', 0)
            
            if hour not in hourly_avg:
                hourly_avg[hour] = []
            hourly_avg[hour].append(usage)
        
        # Calculate average per hour
        predictions = []
        for hour in range(24):
            if hour in hourly_avg:
                avg_usage = statistics.mean(hourly_avg[hour])
            else:
                avg_usage = 0
            
            predictions.append({
                'hour': hour,
                'average_usage': round(avg_usage, 2),
                'is_peak': avg_usage > statistics.mean([v for vals in hourly_avg.values() for v in vals]) if hourly_avg else False
            })
        
        # Sort by usage descending
        predictions.sort(key=lambda x: x['average_usage'], reverse=True)
        return predictions
    
    @staticmethod
    def get_maintenance_alerts(device_data):
        """
        Detect potential device maintenance issues
        
        Args:
            device_data: Device performance metrics
            
        Returns:
            list: Maintenance alerts
        """
        alerts = []
        
        # Check solar panel efficiency
        if device_data.get('device_type') == 'solar_panel':
            efficiency = device_data.get('efficiency', 100)
            if efficiency < 80:
                alerts.append({
                    'type': AlertType.DEVICE_FAILURE.value,
                    'severity': AlertSeverity.WARNING.value,
                    'message': f'Solar panel efficiency dropped to {efficiency}%. Consider cleaning or maintenance.'
                })
        
        # Check device battery
        battery = device_data.get('battery_level', 100)
        if battery < 20:
            alerts.append({
                'type': AlertType.DEVICE_FAILURE.value,
                'severity': AlertSeverity.WARNING.value,
                'message': f'Device battery low ({battery}%). Replace soon to avoid data loss.'
            })
        
        return alerts
    
    @staticmethod
    def create_forecast_report(user_id, monthly_readings, tariff_info):
        """
        Generate comprehensive forecast report
        
        Args:
            user_id: User identifier
            monthly_readings: List of daily readings for current month
            tariff_info: Information about electricity tariffs
            
        Returns:
            dict: Comprehensive forecast report
        """
        weekly_forecast = ForecastingEngine.predict_daily_usage(
            monthly_readings[-7:] if len(monthly_readings) > 7 else monthly_readings,
            days_ahead=7
        )
        
        peak_hours = ForecastingEngine.predict_peak_hours([
            {'hour': i % 24, 'usage': reading}
            for i, reading in enumerate(monthly_readings)
        ])
        
        return {
            'user_id': user_id,
            'report_date': datetime.now().isoformat(),
            'period': 'next_7_days',
            'weekly_forecast': weekly_forecast,
            'peak_hours': peak_hours[:3],  # Top 3 peak hours
            'low_usage_hours': peak_hours[-3:],  # Top 3 low usage hours
            'recommendations': [
                'Shift laundry to off-peak hours (after 9 PM)',
                'Preheat water during low-tariff periods',
                'Use solar energy during daylight peak hours'
            ],
            'estimated_weekly_cost': round(
                sum(f['predicted_usage'] for f in weekly_forecast) * tariff_info.get('rate_per_kwh', 0.15),
                2
            )
        }
