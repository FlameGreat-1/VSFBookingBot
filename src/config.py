import os
from typing import Dict, Any

from dotenv import load_dotenv
import os

load_dotenv()  

# Visa Type Enum
class AngolaToPortugalVisaType:
    NACIONAL = "Nacional (Long-term Portuguese Visa from Angola)"
    SCHENGEN = "Schengen (Short-term visa for Portugal from Angola)"

config: Dict[str, Any] = {
    # System-wide Configuration
    'app_name': 'VFSBookingBot',
    'app_version': '1.0.0',
    'environment': os.getenv('ENVIRONMENT', 'development'),
    'debug_mode': os.getenv('DEBUG_MODE', 'false').lower() == 'true',

    # VFS Global Website URLs
    'vfs_base_url': 'https://visa.vfsglobal.com/ago/pt/prt',
    'login_url': 'https://visa.vfsglobal.com/ago/pt/prt/login',
    'dashboard_url': 'https://visa.vfsglobal.com/ago/pt/prt/dashboard',
    'book_appointment_url': 'https://visa.vfsglobal.com/ago/pt/prt/book-an-appointment',
    'vfs_api_url': 'https://visa.vfsglobal.com/ago/pt/prt/api',
    'slot_check_url': 'https://visa.vfsglobal.com/ago/pt/prt/check-available-slots',

    # Authentication
    'vfs_username': os.getenv('VFS_USERNAME'),
    'vfs_password': os.getenv('VFS_PASSWORD'),

    # Booking Configuration
    'max_concurrent_bookings': int(os.getenv('MAX_CONCURRENT_BOOKINGS', '5')),
    'rate_limit_per_second': int(os.getenv('RATE_LIMIT_PER_SECOND', '5')),
    'check_interval': int(os.getenv('CHECK_INTERVAL', '300')),  # 5 minutes
    'booking_timeout': int(os.getenv('BOOKING_TIMEOUT', '300')),  # 5 minutes

    # Priority Configuration
    'priority_strategy': 'standard',  # Only using standard strategy for Angola to Portugal
    'slot_types': {
        'NACIONAL': 2,
        'SCHENGEN': 1,
    },

    # Retry Configuration
    'max_retries': int(os.getenv('MAX_RETRIES', '5')),
    'retry_delay': int(os.getenv('RETRY_DELAY', '5')),
    'retry_base_delay': int(os.getenv('RETRY_BASE_DELAY', '5')),
    'retry_max_delay': int(os.getenv('RETRY_MAX_DELAY', '60')),
    'retry_strategy': 'exponential',

    # Health Check Configuration
    'health_check_interval': int(os.getenv('HEALTH_CHECK_INTERVAL', '600')),  # 10 minutes
    'health_check_timeout': int(os.getenv('HEALTH_CHECK_TIMEOUT', '30')),  # 30 seconds
    'health_check_endpoints': ['/api/health', '/api/status'],

    # Logging Configuration
    'log_level': os.getenv('LOG_LEVEL', 'INFO'),
    'log_file': 'vfs_booking_bot.log',
    'log_rotation_period': 'D',
    'log_retention_period': 14,
    'log_max_size': 100 * 1024 * 1024,  # 100 MB
    'log_dir': 'logs',

    # Security Configuration
    'enable_rate_limiting': True,
    'rate_limit_window': int(os.getenv('RATE_LIMIT_WINDOW', '60')),  # 1 minute
    'rate_limit_max_requests': int(os.getenv('RATE_LIMIT_MAX_REQUESTS', '30')),
    'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',

    # Geolocation settings
    'country': 'Angola',
    'destination': 'Portugal',
    'language': 'pt',

    # Feature flags
    'features': {
        'enable_auto_recovery': True,
        'enable_dynamic_prioritization': False,
    },

    # Selenium WebDriver Configuration
    'headless': os.getenv('HEADLESS', 'true').lower() == 'true',
    'implicit_wait': int(os.getenv('IMPLICIT_WAIT', '10')),
    'page_load_timeout': int(os.getenv('PAGE_LOAD_TIMEOUT', '30')),

    # Form Filling Configuration
    'form_fill_delay_min': float(os.getenv('FORM_FILL_DELAY_MIN', '0.5')),
    'form_fill_delay_max': float(os.getenv('FORM_FILL_DELAY_MAX', '1.5')),

    # User Data Management
    'user_data_encryption_key': os.getenv('USER_DATA_ENCRYPTION_KEY'),
    'user_data_file': 'user_data.json',

    # Visa Center Details
    'visa_center': 'Portugal Visa Application Center',
    'visa_center_address': 'Luanda, Angola',

    # Notification Settings
    'enable_notifications': False,
    'notification_email': os.getenv('NOTIFICATION_EMAIL'),

    # Performance Monitoring
    'enable_performance_monitoring': True,
    'performance_log_interval': int(os.getenv('PERFORMANCE_LOG_INTERVAL', '3600')),  # 1 hour

    # Proxy Configuration
    'browsermob_proxy_path': r'C:\Users\USER\browsermob-proxy\browsermob-proxy-2.1.4\bin\browsermob-proxy.bat',
    'use_proxy': False,
    'proxy_address': os.getenv('PROXY_ADDRESS'),
    'proxy_list': os.getenv('PROXY_LIST', '').split(','),

    # Backup Configuration
    'enable_backups': True,
    'backup_interval': int(os.getenv('BACKUP_INTERVAL', '86400')),  # 24 hours
    'backup_retention_days': int(os.getenv('BACKUP_RETENTION_DAYS', '7')),

    # Error Handling
    'error_threshold': int(os.getenv('ERROR_THRESHOLD', '10')),
    'error_cooldown_period': int(os.getenv('ERROR_COOLDOWN_PERIOD', '3600')),  # 1 hour

    # Browser Fingerprinting
    'enable_browser_fingerprinting': True,
    'fingerprint_update_interval': int(os.getenv('FINGERPRINT_UPDATE_INTERVAL', '86400')),  # 24 hours

    # Elasticsearch Configuration (for logging)
    'elasticsearch_node': os.getenv('ELASTICSEARCH_NODE'),
    'elasticsearch_index_prefix': 'vfsbookingbot-logs-',

    # Sentry Configuration (for error tracking)
    'sentry_dsn': os.getenv('SENTRY_DSN'),

    # Prometheus Configuration (for metrics)
    'enable_prometheus_metrics': True,
    'prometheus_port': int(os.getenv('PROMETHEUS_PORT', '9090')),

    # Security Proof Configuration
    'fingerprint_injector_path': os.getenv('FINGERPRINT_INJECTOR_PATH', '/path/to/fingerprint-injector'),

    # Slot Checker Configuration
    'slot_check_frequency': int(os.getenv('SLOT_CHECK_FREQUENCY', '300')),  # 5 minutes
    'slot_types_to_check': ['NACIONAL', 'SCHENGEN'],

    # Form Filler Configuration
    'form_data_schema': {
        'personal_info': ['first_name', 'last_name', 'date_of_birth', 'passport_number'],
        'contact_info': ['email', 'phone_number', 'address'],
        'visa_info': ['visa_type', 'entry_date', 'exit_date']
    },

    # Booking Manager Configuration
    'max_booking_attempts_per_slot': int(os.getenv('MAX_BOOKING_ATTEMPTS_PER_SLOT', '5')),
    'booking_cooldown_period': int(os.getenv('BOOKING_COOLDOWN_PERIOD', '300')),  # 5 minutes

    # User Data Manager Configuration
    'max_users_per_batch': int(os.getenv('MAX_USERS_PER_BATCH', '50')),
    'user_data_update_frequency': int(os.getenv('USER_DATA_UPDATE_FREQUENCY', '3600')),  # 1 hour

    # Login Manager Configuration
    'login_retry_delay': int(os.getenv('LOGIN_RETRY_DELAY', '300')),  # 5 minutes
    'max_login_attempts': int(os.getenv('MAX_LOGIN_ATTEMPTS', '5')),

    # Priority Manager Configuration
    'priority_update_frequency': int(os.getenv('PRIORITY_UPDATE_FREQUENCY', '3600')),  # 1 hour
    'priority_factors': ['visa_type', 'application_date', 'special_circumstances'],

    # Health Check Thresholds
    'health_check_thresholds': {
        'cpu_usage': float(os.getenv('HEALTH_CHECK_CPU_THRESHOLD', '0.9')),
        'memory_usage': float(os.getenv('HEALTH_CHECK_MEMORY_THRESHOLD', '0.9')),
        'disk_usage': float(os.getenv('HEALTH_CHECK_DISK_THRESHOLD', '0.9')),
        'error_rate': float(os.getenv('HEALTH_CHECK_ERROR_RATE_THRESHOLD', '0.1')),
    },

    # Retry Manager Configuration
    'retry_jitter_factor': float(os.getenv('RETRY_JITTER_FACTOR', '0.1')),

    # Security Proof Additional Settings
    'enable_proxy_rotation': os.getenv('ENABLE_PROXY_ROTATION', 'false').lower() == 'true',
    'proxy_rotation_interval': int(os.getenv('PROXY_ROTATION_INTERVAL', '600')),  # 10 minutes

    # VFSBookingBot Main Configuration
    'main_loop_interval': int(os.getenv('MAIN_LOOP_INTERVAL', '60')),  # 1 minute
    'graceful_shutdown_timeout': int(os.getenv('GRACEFUL_SHUTDOWN_TIMEOUT', '30')),  # 30 seconds

    # Additional Monitoring
    'enable_resource_monitoring': True,
    'resource_check_interval': int(os.getenv('RESOURCE_CHECK_INTERVAL', '300')),  # 5 minutes

    # Additional Encryption
    'encryption_key': os.getenv('ENCRYPTION_KEY'),

    # File Paths
    'slot_history_file': 'data/slots_history.json',
    'booking_stats_file': 'data/booking_stats.json',
    'prioritization_history_file': 'data/prioritization_history.json',
    'health_history_dir': 'data/health_history',

    # Polling Configuration
    'polling_interval': int(os.getenv('POLLING_INTERVAL', '300')),  # 5 minutes

    # Security and Fingerprinting
    'fingerprint_injection_enabled': os.getenv('FINGERPRINT_INJECTION_ENABLED', 'true').lower() == 'true',

    # Visa Application Details
    'application_centre': 'Luanda',
    'subcategory': 'Normal',
    'num_applicants': int(os.getenv('NUM_APPLICANTS', '2')),

    # Circuit Breaker Configuration
    'circuit_breaker_options': {
        'failure_threshold': int(os.getenv('CIRCUIT_BREAKER_FAILURE_THRESHOLD', '5')),
        'reset_timeout': int(os.getenv('CIRCUIT_BREAKER_RESET_TIMEOUT', '30')),
    },

    # General Timing
    'wait_time': int(os.getenv('WAIT_TIME', '20')),  # seconds
}
