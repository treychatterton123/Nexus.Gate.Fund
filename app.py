from flask import Flask, render_template, request, jsonify, redirect, url_for
import os
import threading
import logging
import json
import time
from datetime import datetime, timedelta
import main

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize Flask app
app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", "nexus-gate-fund-secret")

# Global variables to store trading data for display
latest_signals = {}
latest_decision = {"action": "N/A", "rationale": "N/A"}
trading_history = []
bot_status = {"running": False, "last_run": None, "next_run": None}

# Initialize threading event to control the bot
stop_event = threading.Event()
bot_thread = None

@app.route('/')
def index():
    """Render the main dashboard page"""
    return render_template('index.html', 
                          signals=latest_signals,
                          decision=latest_decision,
                          history=trading_history,
                          status=bot_status)

# Cache market data in memory with timestamp  
market_data_cache = {
    "timestamp": 0,
    "data": {},
    "request_count": 0
}

@app.route('/api/market-data')
def market_data():
    """API endpoint to get the latest market data with caching for 1-second updates
    
    This optimized endpoint supports high-frequency requests by:
    1. Using in-memory caching
    2. Only fetching fresh data from the source API when needed
    3. Tracking request frequency for monitoring
    """
    global market_data_cache, latest_signals
    
    # Increment request counter
    market_data_cache["request_count"] += 1
    
    # Log request count every 100 requests
    if market_data_cache["request_count"] % 100 == 0:
        logger.info(f"Market data API has been called {market_data_cache['request_count']} times")
    
    # Check if we need to refresh the data (every 1 second max)
    current_time = time.time()
    if current_time - market_data_cache["timestamp"] > 1:  # Only refresh if more than 1 second has passed
        try:
            # Fetch fresh market data
            logger.debug("Fetching fresh market data from Finnhub API")
            fresh_signals = main.get_market_signals()
            
            # Debug: Log the structure of the returned data
            logger.debug(f"Fresh signals received: {len(fresh_signals)} tickers with keys: {list(fresh_signals.keys())[:5]}...")
            
            # Only update if we got valid data
            if fresh_signals and len(fresh_signals) > 0:
                latest_signals = fresh_signals
                market_data_cache["timestamp"] = current_time
                market_data_cache["data"] = fresh_signals
                logger.debug(f"Market data refreshed with {len(fresh_signals)} tickers")
            else:
                logger.warning("Received empty market data from API")
        except Exception as e:
            logger.error(f"Error refreshing market data: {str(e)}")
            # Include stack trace for better debugging
            import traceback
            logger.error(f"Stack trace: {traceback.format_exc()}")
    
    # Return the most up-to-date market data with additional metadata
    if latest_signals and len(latest_signals) > 0:
        # Add metadata to response
        response_data = {
            "_meta": {
                "ticker_count": len(latest_signals),
                "timestamp": int(market_data_cache["timestamp"]),
                "cached": current_time - market_data_cache["timestamp"] > 1
            },
            **latest_signals  # Include all the ticker data
        }
        return jsonify(response_data)
    else:
        # If no data is available, return an informative error
        logger.error("No market data available to return to client")
        return jsonify({
            "error": "No market data available. Please try again later.",
            "_meta": {
                "timestamp": int(current_time),
                "reason": "No tickers available from data source"
            }
        }), 503

@app.route('/api/decision')
def decision():
    """API endpoint to get the latest trading decision"""
    return jsonify(latest_decision)

@app.route('/api/history')
def history():
    """API endpoint to get trading history"""
    return jsonify(trading_history)

@app.route('/api/status')
def status():
    """API endpoint to get the bot's status"""
    try:
        # Create a safe copy with default values in case of missing keys
        safe_status = {
            "running": False,
            "last_run": None,
            "next_run": None
        }
        
        # Only copy values if they exist
        if isinstance(bot_status, dict):
            if "running" in bot_status and isinstance(bot_status["running"], bool):
                safe_status["running"] = bot_status["running"]
            if "last_run" in bot_status:
                safe_status["last_run"] = bot_status["last_run"]
            if "next_run" in bot_status:
                safe_status["next_run"] = bot_status["next_run"]
        
        return jsonify(safe_status)
    except Exception as e:
        # Log error and return fallback status
        logger.error(f"Error in /api/status: {str(e)}")
        return jsonify({
            "running": False,
            "last_run": None,
            "next_run": None,
            "error": "Status API error"
        })

@app.route('/api/run-now', methods=['POST'])
def run_now():
    """API endpoint to trigger an immediate trading cycle"""
    try:
        signals, decision, action, rationale = main.run_trading_cycle_api()
        
        # Update the global variables
        global latest_signals, latest_decision
        latest_signals = signals
        latest_decision = {"action": action, "rationale": rationale}
        
        # Add to history
        trading_history.insert(0, {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "signals": signals,
            "decision": {"action": action, "rationale": rationale}
        })
        
        # Keep history at a reasonable size
        if len(trading_history) > 20:
            trading_history.pop()
            
        return jsonify({"success": True, "message": "Trading cycle executed successfully"})
    except Exception as e:
        logger.error(f"Error running trading cycle: {str(e)}")
        return jsonify({"success": False, "message": f"Error: {str(e)}"}), 500

@app.route('/api/start-bot', methods=['POST'])
def start_bot():
    """API endpoint to start the trading bot"""
    global bot_thread, bot_status
    
    if bot_status["running"]:
        return jsonify({"success": False, "message": "Bot is already running"}), 400
    
    # Reset the stop event
    stop_event.clear()
    
    # Start the bot in a separate thread
    bot_thread = threading.Thread(target=main.run_bot_thread, args=(stop_event, update_status))
    bot_thread.daemon = True
    bot_thread.start()
    
    # Update status
    bot_status["running"] = True
    bot_status["last_run"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    bot_status["next_run"] = (datetime.now() + timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")
    
    return jsonify({"success": True, "message": "Bot started successfully"})

@app.route('/api/stop-bot', methods=['POST'])
def stop_bot():
    """API endpoint to stop the trading bot"""
    global bot_status
    
    if not bot_status["running"]:
        return jsonify({"success": False, "message": "Bot is not running"}), 400
    
    # Set the stop event to signal the bot thread to exit
    stop_event.set()
    
    # Update status
    bot_status["running"] = False
    bot_status["next_run"] = None
    
    return jsonify({"success": True, "message": "Bot stopped successfully"})

def update_status(signals=None, decision=None, action=None, rationale=None):
    """Callback function to update the bot's status and trading data"""
    global latest_signals, latest_decision, bot_status, trading_history
    
    if signals:
        latest_signals = signals
    
    if action and rationale:
        latest_decision = {"action": action, "rationale": rationale}
    
    # Add to history if we have new data
    if signals and action and rationale:
        trading_history.insert(0, {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "signals": signals,
            "decision": {"action": action, "rationale": rationale}
        })
        
        # Keep history at a reasonable size
        if len(trading_history) > 20:
            trading_history.pop()
    
    # Update status timestamps
    bot_status["last_run"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if bot_status["running"]:
        bot_status["next_run"] = (datetime.now() + timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")

# Import models after app is created to avoid circular imports
if __name__ == "__main__":
    # Start the Flask app
    app.run(host='0.0.0.0', port=5000, debug=True)