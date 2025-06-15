import time
import schedule
import requests
import logging
import os
import threading
from datetime import datetime, timedelta
import json
from openai import OpenAI
import gspread
from oauth2client.service_account import ServiceAccountCredentials  # type: ignore

# Configure logging  
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Load API keys and configuration from environment variables
GSHEET_NAME = "Hedge Fund: Nexus Gate Fund Trading Logs"
GSHEET_URL = "https://docs.google.com/spreadsheets/d/1oGCqjiWxtZ4fPwSx5na-Ea8NQbpDDRaFV7FdDRen3nQ/edit#gid=0"
WORKSHEET_NAME = "Logs"
FINNHUB_API_KEY = os.environ.get("FINNHUB_API_KEY", "")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
CREDENTIALS_FILE = "nexus-gate-fund-459822-2c37c22b82d7.json"

# Initialize OpenAI client
client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

# Global variables to store trading data for display
latest_signals = {}
latest_news = []
latest_decision = {"action": "N/A", "rationale": "N/A"}
trading_history = []
bot_status = {"running": False, "last_run": None, "next_run": None}

# Portfolio tracking
portfolio = {
    "cash": 10000.0,  # Starting with $10,000 in cash
    "positions": {
        # Core Index & Volatility
        "spy": {"shares": 0, "avg_price": 0},
        "qqq": {"shares": 0, "avg_price": 0},
        "dia": {"shares": 0, "avg_price": 0},
        "vixy": {"shares": 0, "avg_price": 0},
        "vxx": {"shares": 0, "avg_price": 0},
        "uvxy": {"shares": 0, "avg_price": 0},
        "sqqq": {"shares": 0, "avg_price": 0},
        "spxs": {"shares": 0, "avg_price": 0},
        "tqqq": {"shares": 0, "avg_price": 0},
        "upro": {"shares": 0, "avg_price": 0},
        
        # High-Growth Tech & Innovation
        "arkk": {"shares": 0, "avg_price": 0},
        "arkq": {"shares": 0, "avg_price": 0},
        "arkg": {"shares": 0, "avg_price": 0},
        "arkw": {"shares": 0, "avg_price": 0},
        "arkf": {"shares": 0, "avg_price": 0},
        
        # Commodities & Inflation Hedges
        "gld": {"shares": 0, "avg_price": 0},
        "slv": {"shares": 0, "avg_price": 0},
        "uso": {"shares": 0, "avg_price": 0},
        "uco": {"shares": 0, "avg_price": 0},
        "dba": {"shares": 0, "avg_price": 0},
        
        # International & Emerging Markets
        "eem": {"shares": 0, "avg_price": 0},
        "vea": {"shares": 0, "avg_price": 0},
        "vwo": {"shares": 0, "avg_price": 0},
        "fxi": {"shares": 0, "avg_price": 0},
        "ewj": {"shares": 0, "avg_price": 0},
        
        # Fixed Income & Utilities
        "tlt": {"shares": 0, "avg_price": 0},
        "hyu": {"shares": 0, "avg_price": 0},
        "shy": {"shares": 0, "avg_price": 0},
        "xlp": {"shares": 0, "avg_price": 0},
        "xlu": {"shares": 0, "avg_price": 0}
    }
}

# Tracked tickers for data fetching
TRACKED_TICKERS = list(portfolio["positions"].keys())

def init_sheet():
    """Initialize and return Google Sheet connection"""
    try:
        if not os.path.exists(CREDENTIALS_FILE):
            logger.warning(f"Google credentials file not found: {CREDENTIALS_FILE}")
            return None
            
        scope = ['https://spreadsheets.google.com/feeds',
                'https://www.googleapis.com/auth/drive']
        creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, scope)
        gc = gspread.authorize(creds)
        sheet = gc.open(GSHEET_NAME).worksheet(WORKSHEET_NAME)
        logger.info(f"Successfully connected to Google Sheet: {GSHEET_NAME}")
        return sheet
    except Exception as e:
        logger.error(f"Failed to initialize Google Sheet: {str(e)}")
        return None

def test_sheet_connection():
    """Manually test writing to Google Sheet without touching full logic"""
    try:
        sheet = init_sheet()
        if not sheet:
            return False
        
        # Test write a simple row
        test_row = [
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "TEST",
            "Connection test successful",
            0,
            "System check"
        ]
        
        sheet.append_row(test_row)
        logger.info("Successfully tested Google Sheet connection")
        return True
    except Exception as e:
        logger.error(f"Sheet connection test failed: {str(e)}")
        return False

def get_market_signals():
    """Fetch real-time market data for all 30 specified tickers"""
    signals = {}
    
    if not FINNHUB_API_KEY:
        logger.warning("FINNHUB_API_KEY not set, using mock data")
        # Return mock data structure
        for ticker in TRACKED_TICKERS:
            signals[ticker.upper()] = {
                "price": 100.0,
                "change": 0.0,
                "percent_change": 0.0,
                "volume": 1000000,
                "market_cap": 1000000000,
                "status": "mock_data"
            }
        return signals
    
    try:
        for ticker in TRACKED_TICKERS:
            try:
                # Fetch real-time quote
                quote_url = f"https://finnhub.io/api/v1/quote?symbol={ticker.upper()}&token={FINNHUB_API_KEY}"
                quote_response = requests.get(quote_url, timeout=10)
                quote_data = quote_response.json()
                
                if quote_response.status_code == 200 and 'c' in quote_data:
                    current_price = quote_data.get('c', 0)
                    change = quote_data.get('d', 0)
                    percent_change = quote_data.get('dp', 0)
                    
                    signals[ticker.upper()] = {
                        "price": current_price,
                        "change": change,
                        "percent_change": percent_change,
                        "volume": 0,  # Finnhub basic doesn't include volume in quote
                        "market_cap": 0,
                        "status": "active"
                    }
                else:
                    logger.warning(f"Invalid response for {ticker}: {quote_data}")
                    signals[ticker.upper()] = {
                        "price": 0,
                        "change": 0,
                        "percent_change": 0,
                        "volume": 0,
                        "market_cap": 0,
                        "status": "error"
                    }
            except Exception as e:
                logger.error(f"Error fetching data for {ticker}: {str(e)}")
                signals[ticker.upper()] = {
                    "price": 0,
                    "change": 0,
                    "percent_change": 0,
                    "volume": 0,
                    "market_cap": 0,
                    "status": "error"
                }
            
            # Rate limiting - be respectful to the API
            time.sleep(0.1)
            
    except Exception as e:
        logger.error(f"Error in get_market_signals: {str(e)}")
    
    return signals

def get_news_headlines():
    """Fetch the latest news headlines for all 30 tracked tickers"""
    if not FINNHUB_API_KEY:
        return []
    
    headlines = []
    try:
        for ticker in TRACKED_TICKERS[:5]:  # Limit to first 5 to avoid rate limits
            try:
                # Get company news
                news_url = f"https://finnhub.io/api/v1/company-news?symbol={ticker.upper()}&from={datetime.now().strftime('%Y-%m-%d')}&to={datetime.now().strftime('%Y-%m-%d')}&token={FINNHUB_API_KEY}"
                news_response = requests.get(news_url, timeout=10)
                
                if news_response.status_code == 200:
                    news_data = news_response.json()
                    for article in news_data[:2]:  # Limit to 2 articles per ticker
                        headlines.append({
                            "ticker": ticker.upper(),
                            "headline": article.get('headline', ''),
                            "summary": article.get('summary', '')[:200] + '...' if len(article.get('summary', '')) > 200 else article.get('summary', ''),
                            "url": article.get('url', ''),
                            "datetime": article.get('datetime', 0)
                        })
            except Exception as e:
                logger.error(f"Error fetching news for {ticker}: {str(e)}")
            
            time.sleep(0.2)  # Rate limiting
            
    except Exception as e:
        logger.error(f"Error in get_news_headlines: {str(e)}")
    
    return headlines

def calculate_portfolio_value(signals):
    """Calculate the current value of the portfolio"""
    total_value = portfolio["cash"]
    
    for ticker, position in portfolio["positions"].items():
        if position["shares"] > 0:
            current_price = signals.get(ticker.upper(), {}).get("price", 0)
            if current_price > 0:
                total_value += position["shares"] * current_price
    
    return total_value

def execute_trade(decision, signals):
    """Execute a trade decision and update the portfolio"""
    global portfolio
    
    action = decision.get("action", "HOLD")
    ticker = decision.get("ticker", "").lower()
    
    if action == "HOLD" or not ticker or ticker not in portfolio["positions"]:
        return
    
    current_price = signals.get(ticker.upper(), {}).get("price", 0)
    if current_price <= 0:
        logger.warning(f"Invalid price for {ticker}: {current_price}")
        return
    
    # Calculate trade size (10% of portfolio for simplicity)
    portfolio_value = calculate_portfolio_value(signals)
    trade_value = portfolio_value * 0.1
    shares_to_trade = int(trade_value / current_price)
    
    if action == "BUY" and shares_to_trade > 0:
        cost = shares_to_trade * current_price
        if portfolio["cash"] >= cost:
            # Update position
            current_shares = portfolio["positions"][ticker]["shares"]
            current_avg_price = portfolio["positions"][ticker]["avg_price"]
            
            # Calculate new average price
            if current_shares > 0:
                total_value = (current_shares * current_avg_price) + cost
                total_shares = current_shares + shares_to_trade
                new_avg_price = total_value / total_shares
            else:
                new_avg_price = current_price
                total_shares = shares_to_trade
            
            portfolio["positions"][ticker]["shares"] = total_shares
            portfolio["positions"][ticker]["avg_price"] = new_avg_price
            portfolio["cash"] -= cost
            
            logger.info(f"Executed BUY: {shares_to_trade} shares of {ticker.upper()} at ${current_price:.2f}")
    
    elif action == "SELL" and portfolio["positions"][ticker]["shares"] > 0:
        shares_to_sell = min(shares_to_trade, portfolio["positions"][ticker]["shares"])
        proceeds = shares_to_sell * current_price
        
        portfolio["positions"][ticker]["shares"] -= shares_to_sell
        portfolio["cash"] += proceeds
        
        # Reset average price if position is closed
        if portfolio["positions"][ticker]["shares"] == 0:
            portfolio["positions"][ticker]["avg_price"] = 0
        
        logger.info(f"Executed SELL: {shares_to_sell} shares of {ticker.upper()} at ${current_price:.2f}")

def generate_trade_decision(signals, news_headlines):
    """Generate trading decision using OpenAI GPT model with expanded data sources for all 30 tickers"""
    global latest_decision
    
    if not client:
        latest_decision = {
            "action": "HOLD",
            "ticker": "",
            "rationale": "OpenAI API key not configured"
        }
        return latest_decision
    
    try:
        # Prepare market data summary for all 30 tickers
        market_summary = "CURRENT MARKET DATA:\n"
        for ticker, data in signals.items():
            market_summary += f"{ticker}: ${data['price']:.2f} ({data['percent_change']:+.2f}%)\n"
        
        # Prepare news summary
        news_summary = "\nRELEVANT NEWS:\n"
        for headline in news_headlines[:10]:  # Limit to 10 headlines
            news_summary += f"{headline['ticker']}: {headline['headline']}\n"
        
        # Portfolio context
        portfolio_value = calculate_portfolio_value(signals)
        portfolio_summary = f"\nPORTFOLIO STATUS:\nCash: ${portfolio['cash']:.2f}\nTotal Value: ${portfolio_value:.2f}\n\nCURRENT POSITIONS:\n"
        for ticker, position in portfolio["positions"].items():
            if position["shares"] > 0:
                current_price = signals.get(ticker.upper(), {}).get("price", 0)
                position_value = position["shares"] * current_price if current_price > 0 else 0
                portfolio_summary += f"{ticker.upper()}: {position['shares']} shares @ ${position['avg_price']:.2f} avg (Current: ${current_price:.2f}, Value: ${position_value:.2f})\n"
        
        prompt = f'''You are an expert hedge fund manager for Nexus Gate Fund. Analyze the current market data and make a single trading decision.

{market_summary}
{news_summary}
{portfolio_summary}

TRADING RULES:
1. Only trade ONE ticker per decision
2. Actions: BUY, SELL, or HOLD
3. Consider market trends, volatility, and news sentiment
4. Focus on risk management and portfolio diversification
5. Each trade should be approximately 10% of portfolio value
6. Consider current positions when making decisions

AVAILABLE TICKERS: {', '.join([t.upper() for t in TRACKED_TICKERS])}

Provide your decision in this exact JSON format:
{{
    "action": "BUY/SELL/HOLD",
    "ticker": "TICKER_SYMBOL",
    "rationale": "Brief explanation of your reasoning"
}}'''

        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are a professional hedge fund manager. Always respond with valid JSON only."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.1,
            max_tokens=500
        )
        
        # Parse the response
        decision_text = response.choices[0].message.content
        if decision_text:
            decision_text = decision_text.strip()
        else:
            decision_text = ""
        
        # Try to extract JSON from response
        try:
            # Find JSON in the response
            start_idx = decision_text.find('{')
            end_idx = decision_text.rfind('}') + 1
            if start_idx != -1 and end_idx != 0:
                json_str = decision_text[start_idx:end_idx]
                decision = json.loads(json_str)
            else:
                decision = json.loads(decision_text)
            
            # Validate decision format
            if "action" not in decision or "ticker" not in decision or "rationale" not in decision:
                raise ValueError("Invalid decision format")
            
            # Ensure ticker is lowercase for internal use
            if decision["ticker"]:
                decision["ticker"] = decision["ticker"].lower()
            
            latest_decision = decision
            logger.info(f"Generated decision: {decision}")
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse decision JSON: {decision_text}")
            latest_decision = {
                "action": "HOLD",
                "ticker": "",
                "rationale": f"Failed to parse AI response: {str(e)}"
            }
        
    except Exception as e:
        logger.error(f"Error generating trade decision: {str(e)}")
        latest_decision = {
            "action": "HOLD",
            "ticker": "",
            "rationale": f"Error in decision generation: {str(e)}"
        }
    
    return latest_decision

def log_to_sheet(sheet, timestamp, signals, action, rationale):
    """Log trading data to Google Sheets with expanded information for all 30 tickers"""
    if not sheet:
        logger.warning("No sheet connection available for logging")
        return
    
    try:
        # Create market data summary for the log
        market_data_summary = {}
        for ticker in TRACKED_TICKERS:
            ticker_upper = ticker.upper()
            if ticker_upper in signals:
                signal_data = signals[ticker_upper]
                market_data_summary[ticker_upper] = {
                    "price": signal_data.get("price", 0) if isinstance(signal_data, dict) else 0,
                    "change_percent": signal_data.get("percent_change", 0) if isinstance(signal_data, dict) else 0
                }
        
        # Calculate portfolio value
        portfolio_value = calculate_portfolio_value(signals)
        
        # Prepare row data
        row_data = [
            timestamp,
            action,
            rationale,
            f"${portfolio_value:.2f}",
            json.dumps(market_data_summary),  # Store market data as JSON
            f"${portfolio['cash']:.2f}",
            json.dumps({k: v for k, v in portfolio["positions"].items() if v["shares"] > 0})  # Active positions only
        ]
        
        sheet.append_row(row_data)
        logger.info(f"Successfully logged to sheet: {action} decision")
        
    except Exception as e:
        logger.error(f"Failed to log to sheet: {str(e)}")

def run_trading_cycle_api():
    """Execute trading cycle and return data for API use"""
    global latest_signals, latest_news, latest_decision, trading_history, bot_status
    
    try:
        logger.info("Starting trading cycle...")
        
        # Update status
        bot_status["last_run"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Get market signals
        latest_signals = get_market_signals()
        logger.info(f"Fetched signals for {len(latest_signals)} tickers")
        
        # Get news headlines
        latest_news = get_news_headlines()
        logger.info(f"Fetched {len(latest_news)} news headlines")
        
        # Generate trading decision
        latest_decision = generate_trade_decision(latest_signals, latest_news)
        
        # Execute trade if decision is not HOLD
        if latest_decision["action"] != "HOLD":
            execute_trade(latest_decision, latest_signals)
        
        # Log to Google Sheets
        sheet = init_sheet()
        if sheet:
            log_to_sheet(
                sheet,
                bot_status["last_run"],
                latest_signals,
                latest_decision["action"],
                latest_decision["rationale"]
            )
        
        # Add to trading history
        trading_history.append({
            "timestamp": bot_status["last_run"],
            "action": latest_decision["action"],
            "ticker": latest_decision.get("ticker", "").upper(),
            "rationale": latest_decision["rationale"],
            "portfolio_value": calculate_portfolio_value(latest_signals)
        })
        
        # Keep only last 50 history entries
        if len(trading_history) > 50:
            trading_history = trading_history[-50:]
        
        logger.info("Trading cycle completed successfully")
        
        return {
            "signals": latest_signals,
            "decision": latest_decision,
            "history": trading_history[-10:],  # Return last 10 entries
            "status": bot_status,
            "portfolio_value": calculate_portfolio_value(latest_signals)
        }
        
    except Exception as e:
        logger.error(f"Error in trading cycle: {str(e)}")
        return {"error": str(e)}

# Threading variables
stop_event = threading.Event()
bot_thread = None

def run_bot_thread(stop_event, update_callback=None):
    """Run the trading bot in a thread with a stop event"""
    global bot_status
    
    logger.info("Bot thread started")
    bot_status["running"] = True
    
    while not stop_event.is_set():
        try:
            # Run trading cycle
            result = run_trading_cycle_api()
            
            # Call update callback if provided
            if update_callback and "error" not in result:
                decision_data = result.get("decision", {})
                update_callback(
                    signals=result.get("signals"),
                    decision=decision_data,
                    action=decision_data.get("action") if isinstance(decision_data, dict) else None,
                    rationale=decision_data.get("rationale") if isinstance(decision_data, dict) else None
                )
            
            # Calculate next run time (5 minutes from now)
            next_run = datetime.now() + timedelta(minutes=5)
            bot_status["next_run"] = next_run.strftime("%Y-%m-%d %H:%M:%S")
            
            # Wait for 5 minutes or until stop event is set
            if stop_event.wait(300):  # 300 seconds = 5 minutes
                break
                
        except Exception as e:
            logger.error(f"Error in bot thread: {str(e)}")
            if stop_event.wait(60):  # Wait 1 minute before retrying
                break
    
    bot_status["running"] = False
    bot_status["next_run"] = None
    logger.info("Bot thread stopped")

def update_status(signals=None, decision=None, action=None, rationale=None):
    """Callback function to update the bot's status and trading data"""
    global latest_signals, latest_decision, bot_status
    
    if signals:
        latest_signals = signals
    if decision:
        latest_decision = decision
    if action and rationale:
        latest_decision = {"action": action, "rationale": rationale}
    
    bot_status["last_run"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")