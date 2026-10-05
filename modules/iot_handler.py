"""
IoT Integration Handler
Manages smart device connections and data ingestion
"""
from datetime import datetime, timedelta
from enum import Enum
import statistics

class DeviceType(Enum):
    """Supported IoT device types"""
    SMART_PLUG = 'smart_plug'
    ENERGY_METER = 'meter'
    SOLAR_PANEL = 'solar_panel'
    WATER_METER = 'water_meter'
    THERMOSTAT = 'thermostat'

class DeviceStatus(Enum):
    """Device connection status"""
    CONNECTED = 'connected'
    DISCONNECTED = 'disconnected'
    ERROR = 'error'
    BATTERY_LOW = 'battery_low'

class IoTHandler:
    """
    Manages IoT device connections, data ingestion, and synchronization
    """
    
    # Supported device platforms
    SUPPORTED_PLATFORMS = {
        'smart_plugs': ['TP-Link Kasa', 'Philips Hue', 'Shelly', 'Meross'],
        'meters': ['Schneider Electric', 'Siemens', 'ABB'],
        'solar': ['SMA', 'Fronius', 'Tesla Powerwall', 'Enphase'],
        'water_meters': ['Aqara', 'Eve Water Guard'],
    }
    
    # Device configurations
    DEVICE_CONFIG = {
        'smart_plug': {
            'poll_interval': 300,  # seconds
            'data_retention': 30,  # days
            'units': 'kWh',
            'accuracy': '±2%'
        },
        'meter': {
            'poll_interval': 3600,  # hourly
            'data_retention': 365,  # 1 year
            'units': 'kWh',
            'accuracy': '±0.5%'
        },
        'solar_panel': {
            'poll_interval': 300,
            'data_retention': 365,
            'units': 'kW',
            'accuracy': '±1%'
        }
    }
    
    @staticmethod
    def register_device(user_id, device_type, device_name, api_key):
        """
        Register a new IoT device for a user
        
        Args:
            user_id: User ID
            device_type: Type of device (smart_plug, meter, solar_panel)
            device_name: Human-readable device name
            api_key: Device API key for authentication
            
        Returns:
            dict: Registration confirmation with device_id
        """
        # Validate API key format
        if not IoTHandler._validate_api_key(api_key):
            return {
                'success': False,
                'error': 'Invalid API key format'
            }
        
        # Verify device connectivity
        if not IoTHandler._verify_device_connection(api_key, device_type):
            return {
                'success': False,
                'error': 'Cannot reach device. Check connection and credentials.'
            }
        
        return {
            'success': True,
            'device_id': f'DEV_{user_id}_{int(datetime.now().timestamp())}',
            'device_name': device_name,
            'device_type': device_type,
            'status': 'connected',
            'registered_at': datetime.now().isoformat()
        }
    
    @staticmethod
    def ingest_live_data(device_id, data_payload):
        """
        Process incoming data from IoT device
        
        Args:
            device_id: Device identifier
            data_payload: Raw data from device {timestamp, value, unit}
            
        Returns:
            dict: Processing result
        """
        # Validate payload
        required_fields = ['timestamp', 'value', 'unit']
        if not all(field in data_payload for field in required_fields):
            return {
                'success': False,
                'error': f'Missing required fields. Expected: {required_fields}'
            }
        
        # Validate data range
        if not IoTHandler._validate_data_range(data_payload['value']):
            return {
                'success': False,
                'error': 'Data value out of valid range'
            }
        
        # Parse and normalize data
        normalized_data = IoTHandler._normalize_data(data_payload)
        
        return {
            'success': True,
            'device_id': device_id,
            'normalized_data': normalized_data,
            'ingested_at': datetime.now().isoformat()
        }
    
    @staticmethod
    def get_device_status(device_id):
        """
        Get current status of a device
        
        Returns:
            dict: Device status information
        """
        return {
            'device_id': device_id,
            'status': DeviceStatus.CONNECTED.value,
            'last_sync': datetime.now().isoformat(),
            'battery_level': 85,  # Percentage for battery-powered devices
            'signal_strength': -45,  # dBm for wireless devices
            'data_points_today': 287,
            'error_count': 0
        }
    
    @staticmethod
    def get_live_readings(device_id, hours=24):
        """
        Get live readings from device for specified time period
        
        Args:
            device_id: Device identifier
            hours: Number of hours to retrieve data for
            
        Returns:
            list: Time-series data points
        """
        readings = []
        base_time = datetime.now() - timedelta(hours=hours)
        
        # Generate sample reading points (in practice, fetch from database)
        for i in range(hours):
            timestamp = base_time + timedelta(hours=i)
            value = 2.5 + (i % 24) * 0.3  # Simulated realistic pattern
            readings.append({
                'timestamp': timestamp.isoformat(),
                'value': round(value, 3),
                'unit': 'kWh'
            })
        
        return {
            'device_id': device_id,
            'period_hours': hours,
            'total_points': len(readings),
            'readings': readings
        }
    
    @staticmethod
    def sync_all_devices(user_id):
        """
        Trigger synchronization for all user devices
        
        Args:
            user_id: User identifier
            
        Returns:
            dict: Sync results
        """
        return {
            'status': 'initiated',
            'user_id': user_id,
            'devices_syncing': 4,
            'sync_started_at': datetime.now().isoformat(),
            'expected_duration_seconds': 30
        }
    
    @staticmethod
    def _validate_api_key(api_key):
        """Validate API key format"""
        # Basic validation - in production would call device API
        return len(api_key) >= 20 and api_key.isalnum()
    
    @staticmethod
    def _verify_device_connection(api_key, device_type):
        """Verify device is reachable and responsive"""
        # In production: actually ping the device/API
        # For now, assume successful
        return True
    
    @staticmethod
    def _validate_data_range(value):
        """Ensure data value is within acceptable range"""
        # For energy: typically 0-50 kW continuous
        return 0 <= value <= 100
    
    @staticmethod
    def _normalize_data(payload):
        """Normalize incoming data to standard format"""
        return {
            'timestamp': payload['timestamp'],
            'value': float(payload['value']),
            'unit': payload['unit'],
            'normalized_unit': 'kWh',
            'normalized_value': float(payload['value']),  # Convert if needed
            'quality': 'good'
        }
    
    @staticmethod
    def get_aggregate_stats(device_id, period='daily'):
        """
        Get aggregated statistics for device readings
        
        Args:
            device_id: Device identifier
            period: Aggregation period (hourly, daily, weekly, monthly)
            
        Returns:
            dict: Statistical summary
        """
        # In production, calculate from actual data
        sample_values = [2.3, 2.5, 2.4, 2.6, 2.8, 3.1, 3.2, 2.9, 2.7, 2.5]
        
        return {
            'device_id': device_id,
            'period': period,
            'average': round(statistics.mean(sample_values), 2),
            'minimum': round(min(sample_values), 2),
            'maximum': round(max(sample_values), 2),
            'median': round(statistics.median(sample_values), 2),
            'std_dev': round(statistics.stdev(sample_values), 3),
            'total': round(sum(sample_values), 2),
        }
    
    @staticmethod
    def detect_device_anomaly(device_id, readings_window=100):
        """
        Detect unusual patterns in device readings
        
        Args:
            device_id: Device identifier
            readings_window: Number of recent readings to analyze
            
        Returns:
            dict: Anomaly detection result
        """
        # In production: use statistical methods (Z-score, IQR)
        return {
            'device_id': device_id,
            'anomaly_detected': False,
            'confidence': 0,
            'message': 'No anomalies detected in recent readings'
        }
    
    @staticmethod
    def remove_device(user_id, device_id):
        """
        Deregister and remove a device
        
        Args:
            user_id: User identifier
            device_id: Device identifier
            
        Returns:
            dict: Removal confirmation
        """
        return {
            'success': True,
            'device_id': device_id,
            'data_retained': True,  # Archive data before deletion
            'removed_at': datetime.now().isoformat()
        }
