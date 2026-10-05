"""
Personalized Tips Engine
Analyzes user energy patterns and generates AI-driven suggestions
"""
from datetime import datetime, timedelta
from collections import defaultdict
import statistics

class TipEngine:
    """
    Analyzes energy consumption patterns and provides personalized recommendations
    """
    
    # Define tip templates with savings potential
    TIP_TEMPLATES = {
        'laundry': {
            'title': 'Schedule Laundry During Off-Peak Hours',
            'description': 'Run laundry at {time} to save {savings}% energy. Off-peak rates apply.',
            'potential_savings': 15,
            'category': 'laundry'
        },
        'heating': {
            'title': 'Optimize Water Heating',
            'description': 'Consider reducing water heater temperature by {degrees}°C to save {savings}% without discomfort.',
            'potential_savings': 10,
            'category': 'heating'
        },
        'standby': {
            'title': 'Reduce Phantom Power Drain',
            'description': 'Use smart power strips to eliminate standby power consumption. Potential savings: {savings}%',
            'potential_savings': 8,
            'category': 'standby'
        },
        'cooling': {
            'title': 'Optimize Cooling Schedule',
            'description': 'Program your AC to {degrees}°C when away. Estimated savings: {savings}%',
            'potential_savings': 12,
            'category': 'cooling'
        },
        'lighting': {
            'title': 'Switch to LED Lighting',
            'description': 'Replace {bulbs} incandescent bulbs with LED. Save {savings}% on lighting costs.',
            'potential_savings': 20,
            'category': 'lighting'
        },
        'solar': {
            'title': 'Maximize Solar Usage',
            'description': 'Use more appliances during peak solar hours (9 AM - 3 PM) to leverage your solar panels.',
            'potential_savings': 25,
            'category': 'solar'
        }
    }
    
    @staticmethod
    def analyze_usage_patterns(readings, user_settings):
        """
        Analyze energy usage patterns and identify optimization opportunities
        
        Args:
            readings: List of energy readings with timestamp and usage
            user_settings: User preferences and configuration
            
        Returns:
            List of personalized tips
        """
        if not readings:
            return []
        
        tips = []
        
        # Analyze hourly patterns
        hourly_avg = TipEngine._calculate_hourly_averages(readings)
        peak_hours = TipEngine._identify_peak_hours(hourly_avg)
        
        # Identify peak consumption times
        if peak_hours:
            tip = TipEngine._generate_time_based_tip(peak_hours)
            if tip:
                tips.append(tip)
        
        # Check for high standby consumption
        standby_check = TipEngine._check_standby_consumption(readings)
        if standby_check > 0.08:  # >8% of total usage
            tips.append(TipEngine.TIP_TEMPLATES['standby'])
        
        # Analyze solar usage efficiency (if applicable)
        if user_settings.get('has_solar'):
            solar_tip = TipEngine._generate_solar_tip(readings)
            if solar_tip:
                tips.append(solar_tip)
        
        # Check for water heating patterns
        heating_tip = TipEngine._analyze_heating_patterns(readings)
        if heating_tip:
            tips.append(heating_tip)
        
        return tips
    
    @staticmethod
    def _calculate_hourly_averages(readings):
        """Calculate average consumption for each hour of day"""
        hourly_data = defaultdict(list)
        
        for reading in readings:
            timestamp = reading.get('timestamp')
            hour = getattr(timestamp, 'hour', None) if timestamp is not None else None
            if hour is None:
                hour = reading.get('hour', 0)
            hourly_data[hour].append(reading.get('usage', 0))
        
        # Calculate average for each hour
        hourly_avg = {}
        for hour, values in hourly_data.items():
            hourly_avg[hour] = statistics.mean(values) if values else 0
        
        return hourly_avg
    
    @staticmethod
    def _identify_peak_hours(hourly_avg):
        """Return hours with highest consumption"""
        if not hourly_avg:
            return []
        
        avg_usage = statistics.mean(hourly_avg.values()) if hourly_avg else 0
        peak_threshold = avg_usage * 1.5  # 50% above average
        
        peak_hours = [h for h, usage in hourly_avg.items() if usage > peak_threshold]
        return sorted(peak_hours)
    
    @staticmethod
    def _generate_time_based_tip(peak_hours):
        """Generate tip about shifting usage away from peak hours"""
        if not peak_hours:
            return None
        
        # Find low-usage hour
        low_hour = 21  # Default to 9 PM
        
        return {
            'title': f'Shift Laundry to Low-Peak Hours',
            'description': f'Your usage peaks at {peak_hours[0]}:00. '
                          f'Running laundry at {low_hour}:00 can save 15% energy.',
            'potential_savings': 15,
            'category': 'laundry',
            'priority': 'high'
        }
    
    @staticmethod
    def _check_standby_consumption(readings):
        """Calculate percentage of usage during typical sleep hours"""
        if not readings:
            return 0
        
        sleep_usage = 0
        for r in readings:
            timestamp = r.get('timestamp')
            hour = getattr(timestamp, 'hour', None) if timestamp is not None else None
            if hour in [0, 1, 2, 3, 4, 5]:
                sleep_usage += 1
        total = len(readings)
        
        return (sleep_usage / total) if total > 0 else 0
    
    @staticmethod
    def _generate_solar_tip(readings):
        """Generate tips for solar users"""
        return {
            'title': 'Maximize Solar Efficiency',
            'description': 'Concentration usage between 9 AM - 3 PM can increase solar usage by 25%.',
            'potential_savings': 25,
            'category': 'solar',
            'priority': 'medium'
        }
    
    @staticmethod
    def _analyze_heating_patterns(readings):
        """Check if water heating optimization is applicable"""
        # Simplified: always applicable
        return {
            'title': 'Optimize Water Heater Settings',
            'description': 'Reducing water heater temp by 2°C saves 10% without affecting comfort.',
            'potential_savings': 10,
            'category': 'heating',
            'priority': 'low'
        }
    
    @staticmethod
    def get_time_based_tip(hour, usage_level):
        """
        Get specific tip based on time of day and usage level
        
        Args:
            hour: Current hour (0-23)
            usage_level: Current usage relative to average
        """
        if hour >= 6 and hour <= 9:
            return {
                'title': 'Morning Peak Hours',
                'description': 'Morning (6-9 AM) is a peak usage period. Consider deferring non-essential loads.',
                'potential_savings': 12
            }
        elif hour >= 18 and hour <= 21:
            return {
                'title': 'Evening Peak Hours',
                'description': 'Evening (6-9 PM) is peak tariff time. Use off-peak hours for heavy loads.',
                'potential_savings': 15
            }
        elif hour >= 21 or hour <= 5:
            return {
                'title': 'Off-Peak Hours - Perfect Time',
                'description': 'Now is the best time to run laundry or use high-energy appliances!',
                'potential_savings': 20
            }
        
        return None
    
    @staticmethod
    def calculate_potential_savings(tip_list, monthly_bill):
        """
        Calculate total potential savings if user implements all tips
        
        Args:
            tip_list: List of recommended tips
            monthly_bill: User's monthly energy bill
        """
        if not tip_list or monthly_bill == 0:
            return 0
        
        total_savings_percent = sum(t.get('potential_savings', 0) 
                                   for t in tip_list)
        # Cap at 50% max realistic savings
        total_savings_percent = min(total_savings_percent, 50)
        
        return (monthly_bill * total_savings_percent) / 100
    
    @staticmethod
    def get_contextual_tip(hour, day_of_week, weather=None):
        """
        Generate contextual tips based on time and conditions
        
        Args:
            hour: Current hour
            day_of_week: Day of week (0=Monday, 6=Sunday)
            weather: Optional weather data
        """
        tips = []
        
        # Weekend tips
        if day_of_week >= 5:  # Saturday or Sunday
            tips.append({
                'title': 'Weekend Energy Saving',
                'description': 'Weekday off-peak hours apply all day on weekends!',
                'potential_savings': 15
            })
        
        # Weather-based tips
        if weather and weather.get('temp') > 28:
            tips.append({
                'title': 'Hot Weather AC Tip',
                'description': 'On hot days, pre-cool your space during off-peak hours (before 8 AM).',
                'potential_savings': 18
            })
        
        return tips
    
    @staticmethod
    def get_advanced_tips(readings_data, user_context):
        """
        Generate advanced personalized tips based on user's energy patterns
        
        Args:
            readings_data: List of user's reading data with date, usage, timestamp, hour
            user_context: Dict with user preferences (has_solar, user_type, threshold)
        
        Returns:
            List of personalized tip dictionaries
        """
        tips = []
        
        if not readings_data:
            # Default tips for new users
            tips.extend([
                {
                    'title': 'Welcome to EcoPulse!',
                    'content': 'Start by adding your energy readings to get personalized recommendations.',
                    'potential_savings': 0
                },
                {
                    'title': 'Set Your Energy Threshold',
                    'content': 'Configure your monthly energy limit in Settings to receive alerts and tips.',
                    'potential_savings': 5
                }
            ])
            return tips
        
        # Analyze usage patterns
        total_usage = sum(r['usage'] for r in readings_data)
        avg_usage = total_usage / len(readings_data) if readings_data else 0
        
        # Peak usage hours analysis
        hourly_usage = defaultdict(float)
        for reading in readings_data:
            hour = reading.get('hour')
            if hour is None and reading.get('timestamp') is not None:
                hour = getattr(reading.get('timestamp'), 'hour', None)
            if hour is None:
                hour = 0
            hourly_usage[hour] += reading.get('usage', 0)
        
        peak_hours = sorted(hourly_usage.items(), key=lambda x: x[1], reverse=True)[:3]
        
        # Generate tips based on patterns
        if peak_hours:
            peak_hour = peak_hours[0][0]
            if peak_hour >= 17 and peak_hour <= 21:  # Evening peak
                tips.append({
                    'title': 'Shift Evening Usage',
                    'content': f'Your peak usage is at {peak_hour}:00. Consider shifting some activities to off-peak hours (before 5 AM or after 9 PM) to save up to 20%.',
                    'potential_savings': 20
                })
        
        # Solar-specific tips
        if user_context.get('has_solar'):
            tips.append({
                'title': 'Solar Power Optimization',
                'content': 'Maximize your solar investment by using high-energy appliances between 10 AM and 2 PM when solar production is highest.',
                'potential_savings': 25
            })
        
        # Business vs Home tips
        if user_context.get('user_type') == 'business':
            tips.extend([
                {
                    'title': 'Business Energy Audit',
                    'content': 'Schedule a professional energy audit for your business to identify major savings opportunities.',
                    'potential_savings': 30
                },
                {
                    'title': 'Employee Energy Awareness',
                    'content': 'Implement employee training programs to reduce energy waste in the workplace.',
                    'potential_savings': 15
                }
            ])
        else:  # Smart home
            tips.extend([
                {
                    'title': 'Smart Home Integration',
                    'content': 'Connect your appliances to smart home systems for automated energy optimization.',
                    'potential_savings': 22
                },
                {
                    'title': 'Home Energy Monitoring',
                    'content': 'Install additional smart meters in key areas to identify energy waste hotspots.',
                    'potential_savings': 18
                }
            ])
        
        # Threshold-based tips
        threshold = user_context.get('threshold', 0)
        if threshold and avg_usage > threshold * 0.9:
            tips.append({
                'title': 'Approaching Energy Threshold',
                'content': f'Your average usage ({avg_usage:.1f} kWh) is approaching your threshold ({threshold} kWh). Consider conservation measures.',
                'potential_savings': 15
            })
        
        # Seasonal tips (basic implementation)
        current_month = datetime.now().month
        if current_month in [12, 1, 2]:  # Winter
            tips.append({
                'title': 'Winter Heating Efficiency',
                'content': 'Seal windows and doors, and use programmable thermostats to optimize heating costs.',
                'potential_savings': 20
            })
        elif current_month in [6, 7, 8]:  # Summer
            tips.append({
                'title': 'Summer Cooling Tips',
                'content': 'Use ceiling fans, close curtains during peak sun hours, and maintain AC filters for efficient cooling.',
                'potential_savings': 25
            })
        
        # Always include some general tips
        general_tips = [
            {
                'title': 'Energy-Efficient Appliances',
                'content': 'Consider upgrading to Energy Star rated appliances for long-term savings.',
                'potential_savings': 15
            },
            {
                'title': 'Power Strip Management',
                'content': 'Use power strips to easily turn off multiple devices when not in use.',
                'potential_savings': 10
            },
            {
                'title': 'LED Lighting Upgrade',
                'content': 'Replace remaining incandescent bulbs with LED alternatives for instant savings.',
                'potential_savings': 30
            }
        ]
        
        # Add general tips if we don't have enough personalized ones
        if len(tips) < 5:
            tips.extend(general_tips[:5 - len(tips)])
        
        return tips[:10]  # Limit to 10 tips max
