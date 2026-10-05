"""
Gamification System
Badge earning, points system, and leaderboard tracking
"""
from datetime import datetime, timedelta
from enum import Enum

class BadgeType(Enum):
    """Badge categories"""
    ACHIEVEMENT = 'achievement'
    MILESTONE = 'milestone'
    STREAK = 'streak'
    SPECIAL = 'special'

class GamificationEngine:
    """
    Manages badges, points, achievements, and leaderboards
    """
    
    # Badge definitions
    BADGES = {
        'eco_warrior': {
            'name': 'Eco Warrior',
            'description': 'Total energy savings exceeded 100 kWh',
            'icon': '🌍',
            'category': BadgeType.ACHIEVEMENT.value,
            'condition': lambda stats: stats['total_savings_kwh'] > 100,
            'rarity': 'uncommon'
        },
        'energy_saver': {
            'name': 'Energy Saver',
            'description': 'Achieved 20% monthly energy reduction',
            'icon': '⚡',
            'category': BadgeType.ACHIEVEMENT.value,
            'condition': lambda stats: stats['monthly_reduction_percent'] > 20,
            'rarity': 'rare'
        },
        'night_owl': {
            'name': 'Night Owl',
            'description': 'Used over 60% of power during off-peak hours',
            'icon': '🌙',
            'category': BadgeType.ACHIEVEMENT.value,
            'condition': lambda stats: stats['off_peak_percentage'] > 60,
            'rarity': 'uncommon'
        },
        'solar_champion': {
            'name': 'Solar Champion',
            'description': 'Achieved 80% solar energy usage',
            'icon': '☀️',
            'category': BadgeType.ACHIEVEMENT.value,
            'condition': lambda stats: stats['solar_percentage'] > 80,
            'rarity': 'epic'
        },
        'consistency_king': {
            'name': 'Consistency King',
            'description': 'Stayed below daily target for 30 consecutive days',
            'icon': '👑',
            'category': BadgeType.STREAK.value,
            'condition': lambda stats: stats['consecutive_days_below_target'] > 30,
            'rarity': 'legendary'
        },
        'weekend_warrior': {
            'name': 'Weekend Warrior',
            'description': 'Used more energy on weekends than weekdays',
            'icon': '🎮',
            'category': BadgeType.ACHIEVEMENT.value,
            'condition': lambda stats: stats['weekend_kwh'] > stats['weekday_kwh'],
            'rarity': 'rare'
        },
        'early_bird': {
            'name': 'Early Bird',
            'description': 'Completed 10 energy-saving tasks before 8 AM',
            'icon': '🌅',
            'category': BadgeType.ACHIEVEMENT.value,
            'condition': lambda stats: stats['early_morning_actions'] > 10,
            'rarity': 'uncommon'
        },
        'data_detective': {
            'name': 'Data Detective',
            'description': 'Exported and analyzed 5+ reports',
            'icon': '🔍',
            'category': BadgeType.ACHIEVEMENT.value,
            'condition': lambda stats: stats['reports_exported'] > 5,
            'rarity': 'uncommon'
        },
        'community_star': {
            'name': 'Community Star',
            'description': 'Ranked in top 10% of community leaderboard',
            'icon': '⭐',
            'category': BadgeType.ACHIEVEMENT.value,
            'condition': lambda stats: stats['leaderboard_percentile'] > 90,
            'rarity': 'legendary'
        },
        'first_step': {
            'name': 'First Step',
            'description': 'Completed first energy reading',
            'icon': '👣',
            'category': BadgeType.MILESTONE.value,
            'condition': lambda stats: stats['readings_submitted'] >= 1,
            'rarity': 'common'
        },
        'week_wonder': {
            'name': 'Week Wonder',
            'description': 'Logged readings for 7 consecutive days',
            'icon': '✨',
            'category': BadgeType.STREAK.value,
            'condition': lambda stats: stats['consecutive_logging_days'] >= 7,
            'rarity': 'uncommon'
        },
        'month_maven': {
            'name': 'Month Maven',
            'description': 'Maintained consistent logging for 30 days',
            'icon': '📊',
            'category': BadgeType.STREAK.value,
            'condition': lambda stats: stats['consecutive_logging_days'] >= 30,
            'rarity': 'rare'
        },
    }
    
    # Point reward system
    POINT_RULES = {
        'daily_below_target': 10,           # Report usage below target
        'weekly_improvement': 25,           # Week-on-week improvement
        'tip_implemented': 15,              # Implement a suggested tip
        'data_shared': 20,                  # Share consumption report
        'milestone_reached': 50,            # Reach consumption milestone
        'first_reading': 5,                 # Submit first reading
        'streak_7days': 35,                 # 7-day logging streak
        'streak_30days': 100,               # 30-day logging streak
        'report_generated': 10,             # Generate export report
        'goal_achieved': 40,                # Reach energy savings goal
        'community_contribution': 15,       # Share in community
        'iot_device_added': 30,             # Connect IoT device
        'profile_complete': 20,             # Complete profile
    }
    
    @staticmethod
    def get_user_badges(user_stats):
        """
        Determine which badges user has earned
        
        Args:
            user_stats: User statistics dictionary
            
        Returns:
            list: Earned badges
        """
        earned_badges = []
        
        for badge_id, badge_info in GamificationEngine.BADGES.items():
            try:
                if badge_info['condition'](user_stats):
                    earned_badges.append({
                        'id': badge_id,
                        'name': badge_info['name'],
                        'description': badge_info['description'],
                        'icon': badge_info['icon'],
                        'rarity': badge_info['rarity'],
                        'category': badge_info['category'],
                        'earned_at': datetime.now().isoformat()
                    })
            except (KeyError, TypeError):
                # Stats don't contain required fields for this badge
                continue
        
        return earned_badges
    
    @staticmethod
    def calculate_user_points(user_id, activities):
        """
        Calculate total points from user activities
        
        Args:
            user_id: User identifier
            activities: List of completed activities
            
        Returns:
            dict: Points calculation breakdown
        """
        points_breakdown = {}
        total_points = 0
        
        for activity in activities:
            activity_type = activity.get('type')
            
            if activity_type in GamificationEngine.POINT_RULES:
                points = GamificationEngine.POINT_RULES[activity_type]
                points_breakdown[activity_type] = points_breakdown.get(activity_type, 0) + points
                total_points += points
        
        # Bonus multiplier for consistency
        if points_breakdown.get('daily_below_target', 0) > 20:
            consistency_bonus = int(total_points * 0.1)  # 10% bonus
            total_points += consistency_bonus
            points_breakdown['consistency_bonus'] = consistency_bonus
        
        return {
            'total_points': total_points,
            'this_month': GamificationEngine._calculate_monthly_points(activities),
            'breakdown': points_breakdown,
            'updated_at': datetime.now().isoformat()
        }
    
    @staticmethod
    def _calculate_monthly_points(activities):
        """Calculate points earned this month"""
        current_year = datetime.now().year
        current_month = datetime.now().month
        
        monthly_activities = [
            a for a in activities
            if a.get('date').year == current_year and
               a.get('date').month == current_month
        ]
        
        points = 0
        for activity in monthly_activities:
            activity_type = activity.get('type')
            if activity_type in GamificationEngine.POINT_RULES:
                points += GamificationEngine.POINT_RULES[activity_type]
        
        return points
    
    @staticmethod
    def get_leaderboard(limit=100, leaderboard_type='monthly'):
        """
        Get user leaderboard
        
        Args:
            limit: Number of top users to return
            leaderboard_type: 'monthly', 'all_time', or 'week'
            
        Returns:
            list: Top users ranked by points
        """
        # In production, query from database
        leaderboard = [
            {
                'rank': i + 1,
                'username': f'user_{i}',
                'points': 1000 - (i * 25),
                'badges': len(GamificationEngine.BADGES) - i,
                'score': 100 - (i * 2)
            }
            for i in range(min(limit, 100))
        ]
        
        return {
            'leaderboard_type': leaderboard_type,
            'period': GamificationEngine._get_period_label(leaderboard_type),
            'updated_at': datetime.now().isoformat(),
            'entries': leaderboard
        }
    
    @staticmethod
    def get_user_rank(user_id, leaderboard_type='monthly'):
        """
        Get user's rank in leaderboard
        
        Returns:
            dict: User's ranking information
        """
        # In production, calculate from database
        return {
            'user_id': user_id,
            'rank': 15,
            'total_users': 1000,
            'percentile': 98,
            'points': 750,
            'badges_earned': 8,
            'leaderboard_type': leaderboard_type
        }
    
    @staticmethod
    def get_user_achievements(user_id):
        """
        Get user's achievement summary
        
        Args:
            user_id: User identifier
            
        Returns:
            dict: Achievement stats and progress
        """
        return {
            'user_id': user_id,
            'total_badges': 8,
            'total_points': 750,
            'level': GamificationEngine._calculate_level(750),
            'progress_to_next_level': 45,
            'streaks': {
                'current_logging_streak': 15,
                'longest_logging_streak': 45,
                'current_savings_streak': 8
            },
            'milestones': [
                {'name': 'First 100 kWh Saved', 'achieved': True, 'achieved_date': '2024-03-15'},
                {'name': 'First 1000 Points', 'achieved': True, 'achieved_date': '2024-04-01'},
                {'name': 'First Badge earned', 'achieved': True, 'achieved_date': '2024-01-20'},
                {'name': 'Leaderboard Top 50', 'achieved': False, 'progress': 65},
            ]
        }
    
    @staticmethod
    def add_activity(user_id, activity_type, details=None):
        """
        Log user activity for points calculation
        
        Args:
            user_id: User identifier
            activity_type: Type of activity
            details: Additional details about activity
            
        Returns:
            dict: Activity confirmation
        """
        if activity_type not in GamificationEngine.POINT_RULES:
            return {
                'success': False,
                'error': f'Unknown activity type: {activity_type}'
            }
        
        points_earned = GamificationEngine.POINT_RULES[activity_type]
        
        return {
            'success': True,
            'user_id': user_id,
            'activity_type': activity_type,
            'points_earned': points_earned,
            'recorded_at': datetime.now().isoformat(),
            'total_points': 750 + points_earned  # Simulated
        }
    
    @staticmethod
    def _calculate_level(points):
        """Calculate user level from points"""
        # Simple linear scaling: 100 points = 1 level
        return max(1, int(points / 100))
    
    @staticmethod
    def _get_period_label(leaderboard_type):
        """Get human-readable period label"""
        labels = {
            'weekly': 'This Week',
            'monthly': 'This Month',
            'all_time': 'All Time'
        }
        return labels.get(leaderboard_type, 'Recent')
    
    @staticmethod
    def send_badge_notification(user_id, badge_id):
        """
        Send notification when user earns badge
        
        Args:
            user_id: User identifier
            badge_id: Badge identifier
            
        Returns:
            dict: Notification confirmation
        """
        badge = GamificationEngine.BADGES.get(badge_id)
        
        if not badge:
            return {'success': False, 'error': 'Badge not found'}
        
        return {
            'success': True,
            'user_id': user_id,
            'badge_id': badge_id,
            'badge_name': badge['name'],
            'notification_message': f"🎉 Congratulations! You earned the '{badge['name']}' badge!",
            'sent_at': datetime.now().isoformat()
        }
