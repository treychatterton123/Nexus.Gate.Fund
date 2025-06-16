from flask import Flask, render_template, request, jsonify, redirect, url_for
import os
import threading
import logging
import json
import time
from datetime import datetime, timedelta
import trading_bot

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize Flask app
app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", "nexus-gate-fund-secret")

# Initialize threading event to control the bot
stop_event = threading.Event()
bot_thread = None

@app.route('/')
def index():
    """Render the main dashboard page"""
    return render_template('index.html', 
                          signals=trading_bot.latest_signals,
                          decision=trading_bot.latest_decision,
                          history=trading_bot.trading_history,
                          status=trading_bot.bot_status)

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
    try:
        current_time = time.time()
        
        # Check if we have cached data that's less than 1 second old
        if (current_time - market_data_cache["timestamp"]) < 1:
            market_data_cache["request_count"] += 1
            return jsonify({
                "data": market_data_cache["data"],
                "cached": True,
                "cache_age": current_time - market_data_cache["timestamp"],
                "request_count": market_data_cache["request_count"]
            })
        
        # Fetch fresh data from trading bot module
        fresh_signals = trading_bot.get_market_signals()
        
        # Update cache
        market_data_cache["timestamp"] = current_time
        market_data_cache["data"] = fresh_signals
        market_data_cache["request_count"] += 1
        
        return jsonify(fresh_signals)
        
    except Exception as e:
        logger.error(f"Error in market_data endpoint: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/decision')
def decision():
    """API endpoint to get the latest trading decision"""
    return jsonify(trading_bot.latest_decision)

@app.route('/api/history')
def history():
    """API endpoint to get trading history"""
    return jsonify(trading_bot.trading_history)

@app.route('/api/status')
def status():
    """API endpoint to get the bot's status"""
    return jsonify(trading_bot.bot_status)

@app.route('/api/portfolio')
def get_portfolio():
    """API endpoint to get the current portfolio status"""
    try:
        signals = trading_bot.get_market_signals()
        portfolio_value = trading_bot.calculate_portfolio_value(signals)
        
        # Count active positions
        active_positions = sum(1 for pos in trading_bot.portfolio["positions"].values() if pos["shares"] > 0)
        
        return jsonify({
            "cash": trading_bot.portfolio["cash"],
            "total_value": portfolio_value,
            "active_positions": active_positions,
            "positions": {k: v for k, v in trading_bot.portfolio["positions"].items() if v["shares"] > 0}
        })
    except Exception as e:
        logger.error(f"Error getting portfolio: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/run-now', methods=['POST'])
def run_now():
    """API endpoint to trigger an immediate trading cycle"""
    try:
        result = trading_bot.run_trading_cycle_api()
        
        if "error" in result:
            return jsonify({"success": False, "error": result["error"]}), 500
        
        return jsonify({"success": True, "result": result})
        
    except Exception as e:
        logger.error(f"Error in run_now: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/start-bot', methods=['POST'])
def start_bot():
    """API endpoint to start the trading bot"""
    global bot_thread, stop_event
    
    try:
        if bot_thread and bot_thread.is_alive():
            return jsonify({"success": False, "error": "Bot is already running"})
        
        # Reset stop event and start new thread
        stop_event.clear()
        bot_thread = threading.Thread(
            target=trading_bot.run_bot_thread,
            args=(stop_event, trading_bot.update_status)
        )
        bot_thread.daemon = True
        bot_thread.start()
        
        return jsonify({"success": True, "message": "Bot started successfully"})
        
    except Exception as e:
        logger.error(f"Error starting bot: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/stop-bot', methods=['POST'])
def stop_bot():
    """API endpoint to stop the trading bot"""
    global bot_thread, stop_event
    
    try:
        if not bot_thread or not bot_thread.is_alive():
            return jsonify({"success": False, "error": "Bot is not running"})
        
        # Signal the thread to stop
        stop_event.set()
        
        # Wait for thread to finish (with timeout)
        bot_thread.join(timeout=5)
        
        return jsonify({"success": True, "message": "Bot stopped successfully"})
        
    except Exception as e:
        logger.error(f"Error stopping bot: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/news')
def news():
    """API endpoint to get the latest market news"""
    try:
        news_headlines = trading_bot.get_news_headlines()
        return jsonify(news_headlines)
    except Exception as e:
        logger.error(f"Error getting news: {str(e)}")
        return jsonify({"error": str(e)}), 500

def update_status(signals=None, decision=None, action=None, rationale=None):
    """Callback function to update the bot's status and trading data"""
    trading_bot.update_status(signals, decision, action, rationale)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)