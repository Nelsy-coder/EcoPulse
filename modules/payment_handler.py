"""
Payment & Subscription Handler
Manages subscription tiers, payments, and feature access
"""
from datetime import datetime, timedelta
from enum import Enum

class SubscriptionTier(Enum):
    """Available subscription tiers"""
    FREE = 'free'
    BASIC = 'basic'
    PRO = 'pro'
    ENTERPRISE = 'enterprise'

class PaymentStatus(Enum):
    """Payment processing status"""
    PENDING = 'pending'
    PROCESSING = 'processing'
    COMPLETED = 'completed'
    FAILED = 'failed'
    REFUNDED = 'refunded'

class PaymentHandler:
    """
    Handles payment processing and subscription management
    """
    
    # Define subscription tiers
    SUBSCRIPTION_TIERS = {
        'free': {
            'name': 'Free Tier',
            'monthly_price': 0,
            'currency': 'Ksh',
            'features': [
                'basic_dashboard',
                'manual_readings',
                'weekly_summary_email',
                'export_pdf'
            ],
            'monthly_data_points': 1000,
            'monthly_reports': 4,
            'support': 'community'
        },
        'basic': {
            'name': 'Basic Plan',
            'monthly_price': 299,
            'currency': 'Ksh',
            'trial_days': 14,
            'features': [
                'all_free_features',
                'real_time_charts',
                'daily_tips',
                'csv_export',
                'mobile_app',
                'device_integration_basic'
            ],
            'monthly_data_points': 10000,
            'monthly_reports': 15,
            'support': 'email'
        },
        'pro': {
            'name': 'Pro Plan',
            'monthly_price': 799,
            'currency': 'Ksh',
            'trial_days': 30,
            'features': [
                'all_basic_features',
                'advanced_analytics',
                'forecasting',
                'community_sharing',
                'custom_alerts',
                'excel_export',
                'priority_email_support',
                '5_device_integration',
                'api_access_limited'
            ],
            'monthly_data_points': 50000,
            'monthly_reports': 50,
            'support': 'priority_email'
        },
        'enterprise': {
            'name': 'Enterprise Plan',
            'monthly_price': 2999,
            'currency': 'Ksh',
            'features': [
                'all_pro_features',
                'unlimited_device_integration',
                'full_api_access',
                'dedicated_account_manager',
                'custom_integrations',
                'priority_phone_support',
                'data_warehouse_export',
                'advanced_reporting',
                'white_label_options',
                'sso_support'
            ],
            'monthly_data_points': 'unlimited',
            'monthly_reports': 'unlimited',
            'support': 'dedicated_manager'
        }
    }
    
    @staticmethod
    def get_subscription_details(tier):
        """
        Get details for a subscription tier
        
        Args:
            tier: Subscription tier name
            
        Returns:
            dict: Tier information
        """
        if tier not in PaymentHandler.SUBSCRIPTION_TIERS:
            return None
        
        tier_info = PaymentHandler.SUBSCRIPTION_TIERS[tier]
        return {
            'tier': tier,
            'name': tier_info['name'],
            'monthly_price': tier_info['monthly_price'],
            'currency': tier_info['currency'],
            'features': tier_info['features'],
            'data_points': tier_info['monthly_data_points'],
            'trial_days': tier_info.get('trial_days', 0),
            'support_level': tier_info['support']
        }
    
    @staticmethod
    def process_payment(user_id, amount, payment_method, subscription_tier):
        """
        Process payment via various methods
        
        Args:
            user_id: User identifier
            amount: Payment amount
            payment_method: Method (mpesa, card, bank_transfer)
            subscription_tier: Subscription tier name
            
        Returns:
            dict: Payment processing result
        """
        # Validate amount
        tier_info = PaymentHandler.SUBSCRIPTION_TIERS.get(subscription_tier)
        if not tier_info:
            return {
                'success': False,
                'error': 'Invalid subscription tier'
            }
        
        expected_amount = tier_info['monthly_price']
        if amount != expected_amount:
            return {
                'success': False,
                'error': f'Amount mismatch. Expected {expected_amount} Ksh'
            }
        
        transaction_id = f"TXN_{user_id}_{int(datetime.now().timestamp())}"
        
        # Route to appropriate payment processor
        if payment_method == 'mpesa':
            result = PaymentHandler._process_mpesa_payment(user_id, amount, transaction_id)
        elif payment_method == 'card':
            result = PaymentHandler._process_card_payment(user_id, amount, transaction_id)
        elif payment_method == 'bank_transfer':
            result = PaymentHandler._process_bank_transfer(user_id, amount, transaction_id)
        else:
            return {
                'success': False,
                'error': f'Unsupported payment method: {payment_method}'
            }
        
        return result
    
    @staticmethod
    def upgrade_subscription(user_id, new_tier):
        """
        Upgrade user to new subscription tier
        
        Args:
            user_id: User identifier
            new_tier: New tier name
            
        Returns:
            dict: Upgrade confirmation
        """
        if new_tier not in PaymentHandler.SUBSCRIPTION_TIERS:
            return {
                'success': False,
                'error': 'Invalid tier name'
            }
        
        tier_info = PaymentHandler.SUBSCRIPTION_TIERS[new_tier]
        
        # Calculate prorated amount if any
        prorated_amount = PaymentHandler._calculate_prorated_amount(user_id, new_tier)
        
        return {
            'success': True,
            'user_id': user_id,
            'new_tier': new_tier,
            'tier_name': tier_info['name'],
            'monthly_price': tier_info['monthly_price'],
            'prorated_charge': prorated_amount,
            'next_billing_date': (datetime.now() + timedelta(days=30)).date().isoformat(),
            'features_activated': tier_info['features'],
            'upgraded_at': datetime.now().isoformat()
        }
    
    @staticmethod
    def downgrade_subscription(user_id, new_tier):
        """
        Downgrade user to lower tier
        
        Args:
            user_id: User identifier
            new_tier: New tier name
            
        Returns:
            dict: Downgrade confirmation
        """
        # Similar to upgrade but with credit calculation
        return {
            'success': True,
            'user_id': user_id,
            'new_tier': new_tier,
            'effective_date': datetime.now().date().isoformat(),
            'credit_issued': 250.0,  # Prorated credit
            'next_billing_date': (datetime.now() + timedelta(days=30)).date().isoformat()
        }
    
    @staticmethod
    def renew_subscription(user_id, subscription_id):
        """
        Handle subscription renewal
        
        Args:
            user_id: User identifier
            subscription_id: Subscription identifier
            
        Returns:
            dict: Renewal status
        """
        return {
            'success': True,
            'subscription_id': subscription_id,
            'user_id': user_id,
            'renewed_at': datetime.now().isoformat(),
            'next_renewal': (datetime.now() + timedelta(days=30)).isoformat(),
            'status': 'active'
        }
    
    @staticmethod
    def cancel_subscription(user_id, subscription_id, reason=None):
        """
        Cancel user subscription
        
        Args:
            user_id: User identifier
            subscription_id: Subscription identifier
            reason: Cancellation reason
            
        Returns:
            dict: Cancellation confirmation
        """
        return {
            'success': True,
            'subscription_id': subscription_id,
            'user_id': user_id,
            'status': 'cancelled',
            'effective_date': datetime.now().date().isoformat(),
            'refund_calculated': 150.0,  # Prorated refund if applicable
            'cancelled_at': datetime.now().isoformat(),
            'reason': reason or 'User initiated'
        }
    
    @staticmethod
    def check_feature_access(user_id, feature_name, user_tier):
        """
        Verify if user has access to specific feature
        
        Args:
            user_id: User identifier
            feature_name: Feature to check
            user_tier: User's current tier
            
        Returns:
            dict: Access result
        """
        tier_features = PaymentHandler.SUBSCRIPTION_TIERS.get(user_tier, {}).get('features', [])
        
        has_access = feature_name in tier_features
        
        return {
            'user_id': user_id,
            'feature': feature_name,
            'tier': user_tier,
            'has_access': has_access,
            'checked_at': datetime.now().isoformat()
        }
    
    @staticmethod
    def generate_invoice(user_id, transaction_id, subscription_id):
        """
        Generate invoice for payment
        
        Args:
            user_id: User identifier
            transaction_id: Transaction identifier
            subscription_id: Subscription identifier
            
        Returns:
            dict: Invoice data
        """
        return {
            'invoice_number': f"INV_{transaction_id[:8]}",
            'user_id': user_id,
            'transaction_id': transaction_id,
            'subscription_id': subscription_id,
            'issued_date': datetime.now().date().isoformat(),
            'due_date': (datetime.now() + timedelta(days=7)).date().isoformat(),
            'amount': 799.00,
            'currency': 'Ksh',
            'items': [
                {
                    'description': 'Pro Plan - Monthly Subscription',
                    'quantity': 1,
                    'unit_price': 799.00,
                    'total': 799.00
                }
            ],
            'subtotal': 799.00,
            'tax': 0,
            'total_amount': 799.00,
            'payment_terms': 'Due on receipt',
            'status': 'issued'
        }
    
    @staticmethod
    def get_billing_history(user_id, limit=10):
        """
        Get user's billing history
        
        Args:
            user_id: User identifier
            limit: Number of records to return
            
        Returns:
            list: Billing records
        """
        # In production, query from database
        history = []
        for i in range(limit):
            date = datetime.now() - timedelta(days=30*i)
            history.append({
                'date': date.date().isoformat(),
                'transaction_id': f'TXN_{i}',
                'description': 'Pro Plan - Monthly',
                'amount': 799.00,
                'status': PaymentStatus.COMPLETED.value,
                'invoice_url': f'/invoices/INV_{i}'
            })
        
        return history
    
    @staticmethod
    def get_usage_stats(user_id, subscription_tier):
        """
        Get current usage against subscription limits
        
        Args:
            user_id: User identifier
            subscription_tier: User's tier
            
        Returns:
            dict: Usage statistics
        """
        tier_info = PaymentHandler.SUBSCRIPTION_TIERS[subscription_tier]
        monthly_limit = tier_info['monthly_data_points']
        
        if monthly_limit == 'unlimited':
            monthly_limit = float('inf')
            usage_percent = 0
        else:
            current_usage = 34567  # Simulated
            usage_percent = (current_usage / monthly_limit) * 100
        
        return {
            'user_id': user_id,
            'tier': subscription_tier,
            'current_month': datetime.now().strftime('%B %Y'),
            'data_points_used': 34567,
            'data_points_limit': monthly_limit,
            'usage_percentage': round(usage_percent, 1),
            'reports_generated': 8,
            'reports_limit': tier_info['monthly_reports'],
            'days_remaining': (datetime.now().replace(day=1) + timedelta(days=32)).replace(day=1) - datetime.now()
        }
    
    @staticmethod
    def _process_mpesa_payment(user_id, amount, transaction_id):
        """Process M-Pesa payment"""
        # In production: call M-Pesa API
        return {
            'success': True,
            'transaction_id': transaction_id,
            'status': PaymentStatus.PENDING.value,
            'message': 'Payment initiated. Awaiting M-Pesa confirmation.',
            'user_id': user_id,
            'amount': amount,
            'timestamp': datetime.now().isoformat()
        }
    
    @staticmethod
    def _process_card_payment(user_id, amount, transaction_id):
        """Process card payment"""
        # In production: call payment gateway (Stripe, PayFast, etc.)
        return {
            'success': True,
            'transaction_id': transaction_id,
            'status': PaymentStatus.COMPLETED.value,
            'message': 'Payment processed successfully',
            'user_id': user_id,
            'amount': amount,
            'timestamp': datetime.now().isoformat()
        }
    
    @staticmethod
    def _process_bank_transfer(user_id, amount, transaction_id):
        """Process bank transfer"""
        return {
            'success': True,
            'transaction_id': transaction_id,
            'status': PaymentStatus.PENDING.value,
            'message': 'Bank transfer initiated. Please verify payment within 24 hours.',
            'user_id': user_id,
            'amount': amount,
            'bank_details': {
                'account_name': 'EcoPulse Kenya Ltd',
                'account_number': '1234567890',
                'bank_code': '003',
                'bank_name': 'Sample Bank'
            },
            'timestamp': datetime.now().isoformat()
        }
    
    @staticmethod
    def _calculate_prorated_amount(user_id, new_tier):
        """Calculate prorated charge for mid-month upgrade"""
        # Simplified: returns sample prorated amount
        return 250.0
