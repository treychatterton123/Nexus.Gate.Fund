from datetime import datetime, time
import pytz

def isMarketOpen():
    """Check if the US stock market is currently open"""
    try:
        # Get current time in US Eastern timezone
        eastern = pytz.timezone('US/Eastern')
        now = datetime.now(eastern)
        
        # Market hours: 9:30 AM to 4:00 PM ET, Monday to Friday
        market_open = time(9, 30)
        market_close = time(16, 0)
        
        # Check if it's a weekday (0=Monday, 6=Sunday)
        is_weekday = now.weekday() < 5
        
        # Check if current time is within market hours
        current_time = now.time()
        is_market_hours = market_open <= current_time <= market_close
        
        return is_weekday and is_market_hours
    except Exception as e:
        print(f"Error checking market status: {e}")
        return False