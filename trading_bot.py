import time
import schedule
import requests
import logging
import os
import threading
from datetime import datetime, timedelta
import json
from openai import OpenAI
from utilt import isMarketOpen
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from daily_portfolio_logger import log_daily_portfolio_value, init_daily_logging_sheet

# Configure logging  
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Load API keys and configuration from environment variables
GSHEET_NAME = "Nexus Gate Fund Trading Logs"
GSHEET_URL = "https://docs.google.com/spreadsheets/d/1NBTj_BvWws6lZvcS2BLUem3pNUwa5293AwBPpu5pZeU/edit?usp=sharing"
WORKSHEET_NAME = "Logs"
FINNHUB_API_KEY = os.environ.get("FINNHUB_API_KEY", "") 
Seb_API_key = os.environ.get("sebs_finnhub_api_key", "")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
CREDENTIALS_FILE = "nexusGateFund.json"

# Initialize OpenAI client
client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

# Global variables to store trading data for display
latest_signals = {}
latest_news = []
latest_decision = {"action": "N/A", "rationale": "N/A"}
trading_history = []
bot_status = {"running": False, "last_run": None, "next_run": None}

# Declare a json file that I will use to store the portfolio
PORTFOLIO_FILE = "portfolio.json"

def save_portfolio():
    try:
        with open(PORTFOLIO_FILE, 'w') as file:
            json.dump(portfolio, file, indent=2)
        logger.info("Portfolio saved successfully")
    except Exception as exception:
        logger.error(f"Error saving portfolio: {exception}")

def load_portfolio():
    global portfolio
    if os.path.exists(PORTFOLIO_FILE):
        try:
            with open(PORTFOLIO_FILE, 'r') as file:
                portfolio = json.load(file)
            logger.info("Successfully loaded portfolio")
        except Exception as exception:
            logger.error(f"Failed to load portfolio: {exception}")
    else:
        logger.info("Portfolio file does not exist, using default portfolio")

def update_performance_metrics(trade_data):
    """Update portfolio performance metrics with each trade"""
    global portfolio

    current_date = datetime.now().strftime("%Y-%m-%d")

    # Initialize start date if not set
    if portfolio["performance_metrics"]["start_date"] is None:
        portfolio["performance_metrics"]["start_date"] = current_date

    # Calculate current portfolio value
    current_value = portfolio["portfolio_value"]
    start_value = portfolio["performance_metrics"]["start_value"]

    # Update total return metrics
    portfolio["performance_metrics"]["total_return"] = current_value - start_value
    portfolio["performance_metrics"]["total_return_percentage"] = ((current_value - start_value) / start_value) * 100

    # Track trade performance if this is a trade
    if "action" in trade_data and trade_data["action"] in ["buy", "sell"]:
        portfolio["performance_metrics"]["total_trades"] += 1

        # For sell trades, calculate the return
        if trade_data["action"] == "sell" and "ticker" in trade_data:
            ticker = trade_data["ticker"].lower()
            if ticker in portfolio["positions"]:
                position = portfolio["positions"][ticker]
                if position["shares"] > 0:
                    trade_return = (trade_data["price"] - position["avg_price"]) * trade_data["shares"]

                    # Update best/worst trade tracking
                    if trade_return > portfolio["performance_metrics"]["best_trade"]["return"]:
                        portfolio["performance_metrics"]["best_trade"] = {
                            "ticker": ticker.upper(),
                            "return": trade_return,
                            "date": current_date
                        }

                    if trade_return < portfolio["performance_metrics"]["worst_trade"]["return"]:
                        portfolio["performance_metrics"]["worst_trade"] = {
                            "ticker": ticker.upper(),
                            "return": trade_return,
                            "date": current_date
                        }

                    # Update win rate
                    if trade_return > 0:
                        portfolio["performance_metrics"]["winning_trades"] += 1

                    portfolio["performance_metrics"]["win_rate"] = (
                        portfolio["performance_metrics"]["winning_trades"] / 
                        portfolio["performance_metrics"]["total_trades"] * 100
                    )

    # Add daily return data
    portfolio["performance_metrics"]["daily_returns"].append({
        "date": current_date,
        "value": current_value,
        "return": portfolio["performance_metrics"]["total_return"],
        "return_percentage": portfolio["performance_metrics"]["total_return_percentage"]
    })

    # Keep only last 365 days of daily returns
    if len(portfolio["performance_metrics"]["daily_returns"]) > 365:
        portfolio["performance_metrics"]["daily_returns"] = portfolio["performance_metrics"]["daily_returns"][-365:]

def get_portfolio_growth_projection():
    """Calculate projected portfolio growth to reach $100k target"""
    current_value = portfolio["portfolio_value"]
    start_value = portfolio["performance_metrics"]["start_value"]
    target_value = 100000.0

    if len(portfolio["performance_metrics"]["daily_returns"]) < 2:
        return {
            "current_value": current_value,
            "target_value": target_value,
            "progress_percentage": (current_value / target_value) * 100,
            "days_active": 0,
            "projected_days_to_target": "Insufficient data",
            "required_daily_return": "Calculating..."
        }

    # Calculate average daily return
    daily_returns = portfolio["performance_metrics"]["daily_returns"]
    days_active = len(daily_returns)

    if days_active > 1:
        total_return_pct = portfolio["performance_metrics"]["total_return_percentage"]
        avg_daily_return_pct = total_return_pct / days_active if days_active > 0 else 0

        # Calculate days needed to reach target
        remaining_return_needed = ((target_value - current_value) / current_value) * 100

        if avg_daily_return_pct > 0:
            projected_days_to_target = int(remaining_return_needed / avg_daily_return_pct)
        else:
            projected_days_to_target = "N/A (negative returns)"
    else:
        avg_daily_return_pct = 0
        projected_days_to_target = "Calculating..."

    return {
        "current_value": current_value,
        "target_value": target_value,
        "progress_percentage": (current_value / target_value) * 100,
        "days_active": days_active,
        "avg_daily_return_pct": avg_daily_return_pct,
        "projected_days_to_target": projected_days_to_target,
        "remaining_amount": target_value - current_value
    }

# Portfolio tracking
portfolio = {
    "cash": 10000.0,  # Starting with $10,000 in cash
    "positions": {
        # Core Index & Volatility
        "spy": {"shares": 0, "avg_price": 0},
        "qqq": {"shares": 0, "avg_price": 0},
        "dia": {"shares": 0, "avg_price": 0},
        "iwm": {"shares": 0, "avg_price": 0},
        "vixy": {"shares": 0, "avg_price": 0},
        "uvxy": {"shares": 0, "avg_price": 0},

        # Big Tech
        "aapl": {"shares": 0, "avg_price": 0},
        "msft": {"shares": 0, "avg_price": 0},
        "nvda": {"shares": 0, "avg_price": 0},
        "amzn": {"shares": 0, "avg_price": 0},
        "googl": {"shares": 0, "avg_price": 0},
        "tsla": {"shares": 0, "avg_price": 0},
        "meta": {"shares": 0, "avg_price": 0},

        # Financials & ETFs
        "xlf": {"shares": 0, "avg_price": 0},
        "jpm": {"shares": 0, "avg_price": 0},
        "bac": {"shares": 0, "avg_price": 0},
        "v": {"shares": 0, "avg_price": 0},
        "ma": {"shares": 0, "avg_price": 0},

        # Energy & Commodities
        "gld": {"shares": 0, "avg_price": 0},
        "slv": {"shares": 0, "avg_price": 0},
        "uso": {"shares": 0, "avg_price": 0},
        "xle": {"shares": 0, "avg_price": 0},

        # Leverage ETFs
        "tqqq": {"shares": 0, "avg_price": 0},
        "sqqq": {"shares": 0, "avg_price": 0},
        "soxl": {"shares": 0, "avg_price": 0},
        "soxs": {"shares": 0, "avg_price": 0},

        # Healthcare & Defensive
        "unh": {"shares": 0, "avg_price": 0},
        "jnj": {"shares": 0, "avg_price": 0},
        "pfe": {"shares": 0, "avg_price": 0},
        "xlu": {"shares": 0, "avg_price": 0},
    },
    "history": [],
    "portfolio_value": 10000.0,
    "performance_metrics": {
        "start_date": None,
        "start_value": 10000.0,
        "daily_returns": [],
        "total_return": 0.0,
        "total_return_percentage": 0.0,
        "best_trade": {"ticker": "", "return": 0.0, "date": ""},
        "worst_trade": {"ticker": "", "return": 0.0, "date": ""},
        "win_rate": 0.0,
        "total_trades": 0,
        "winning_trades": 0
    },
}

# Load portfolio on startup
load_portfolio()

# Initialize threading event to control the bot
stop_event = threading.Event()
bot_thread = None

# Setup Google Sheets
def init_sheet():
    """Initialize and return Google Sheet connection"""
    try:
        credentials_file = CREDENTIALS_FILE
        if not os.path.exists(credentials_file):
            # Try alternative credentials files
            alt_files = ['credentials.json', 'nexus-gate-fund-459822-2c37c22b82d7.json']
            found_file = None
            for alt_file in alt_files:
                if os.path.exists(alt_file):
                    found_file = alt_file
                    break
            
            if not found_file:
                logger.warning("No Google credentials file found")
                return None
            
            credentials_file = found_file

        # Extract the spreadsheet ID from the URL
        spreadsheet_id = "1NBTj_BvWws6lZvcS2BLUem3pNUwa5293AwBPpu5pZeU"

        # Set up authentication with service account
        scopes = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]

        logger.info(f"Using credentials file: {credentials_file}")
        creds = ServiceAccountCredentials.from_json_keyfile_name(credentials_file, scopes)
        client_gs = gspread.authorize(creds)

        try:
            # Try opening by ID first (most reliable)
            logger.info(f"Attempting to open spreadsheet by ID: {spreadsheet_id}")
            spreadsheet = client_gs.open_by_key(spreadsheet_id)
            logger.info(f"Successfully opened spreadsheet by ID")
        except Exception as e:
            # If ID fails, try opening by name
            logger.warning(f"Failed to open by ID: {str(e)}, trying by name: {GSHEET_NAME}")
            spreadsheet = client_gs.open(GSHEET_NAME)
            logger.info(f"Successfully opened spreadsheet by name: {GSHEET_NAME}")

        # Try to access the Logs worksheet
        try:
            worksheet = spreadsheet.worksheet(WORKSHEET_NAME)
            logger.info(f"Successfully accessed worksheet: {WORKSHEET_NAME}")
            return worksheet

        except gspread.exceptions.WorksheetNotFound:
            # Create the worksheet if it doesn't exist
            logger.info(f"Worksheet {WORKSHEET_NAME} not found, creating...")
            worksheet = spreadsheet.add_worksheet(title=WORKSHEET_NAME, rows=1000, cols=20)
            logger.info(f"Created new worksheet: {WORKSHEET_NAME}")

            # Set up headers
            header = [
                "Timestamp", "Signal Input", "Trade Action", "Rationale", 
                "Price", "Shares Bought/Sold", "Cash Remaining", 
                "Position Value", "Portfolio Value"
            ]
            worksheet.append_row(header)
            logger.info("Added headers to new worksheet")
            return worksheet

    except Exception as e:
        logger.error(f"Failed to initialize Google Sheet: {str(e)}")
        return None

# Fetch market data from Finnhub for all tickers
def get_market_signals():
    """Fetch real-time market data for all tracked tickers"""
    signals = {}

    # All tracked tickers organized by category
    tickers = [
        # Core Index & Volatility
        "SPY", "QQQ", "DIA", "IWM", "VIXY", "UVXY",

        # Big Tech
        "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "TSLA", "META",

        # Financials & ETFs
        "XLF", "JPM", "BAC", "V", "MA",

        # Energy & Commodities
        "GLD", "SLV", "USO", "XLE",

        # Leverage ETFs
        "TQQQ", "SQQQ", "SOXL", "SOXS",

        # Healthcare & Defensive
        "UNH", "JNJ", "PFE", "XLU"
    ]

    if not FINNHUB_API_KEY:
        logger.warning("FINNHUB_API_KEY not set, using mock data")
        # Return mock data structure
        for ticker in tickers:
            signals[ticker.lower()] = {
                "c": 100.0,  # current price
                "d": 0.0,    # change
                "dp": 0.0,   # percent change
                "h": 100.0,  # high
                "l": 100.0,  # low
                "o": 100.0,  # open
                "pc": 100.0, # previous close
                "t": int(time.time())  # timestamp
            }
        return signals

    logger.info(f"Fetching market data for {len(tickers)} tickers...")

    for i, ticker in enumerate(tickers):
        try:
            # Add minimal delay between API calls to prevent worker timeout
            if i > 0:
                time.sleep(0.02)

            response = requests.get(
                f"https://finnhub.io/api/v1/quote?symbol={ticker}&token={FINNHUB_API_KEY}",
                timeout=10
            )

            if response.status_code == 200:
                signals[ticker.lower()] = response.json()
                logger.debug(f"✓ {ticker}: {signals[ticker.lower()].get('c', 'N/A')}")
            elif response.status_code == 429:
                logger.warning(f"Rate limit exceeded for {ticker}. Skipping to prevent timeout...")
                signals[ticker.lower()] = {"c": "N/A", "error": 429}
            else:
                logger.error(f"Failed to fetch data for {ticker}: {response.status_code}")
                signals[ticker.lower()] = {"c": "N/A", "error": response.status_code}
        except requests.RequestException as e:
            logger.error(f"Request error for {ticker}: {str(e)}")
            signals[ticker.lower()] = {"c": "N/A", "error": str(e)}

    # Log a summary of successful fetches
    successful_fetches = sum(1 for ticker in signals if isinstance(signals[ticker].get("c"), (int, float)) and signals[ticker].get("c") != "N/A")
    logger.info(f"Successfully fetched {successful_fetches} out of {len(tickers)} ticker prices")

    return signals

# Fetch news headlines from Finnhub for all tracked tickers
def get_news_headlines():
    """Fetch the latest news headlines for tracked tickers"""
    headlines = []
    today = datetime.now().strftime('%Y-%m-%d')

    # Check if we have a valid API key first
    if not Seb_API_key:
        logger.warning("Seb_API_key not set, using placeholder news")
        return [
            {
                "headline": "Market news will appear here when connected to Finnhub API",
                "summary": "Set your FINNHUB_API_KEY to enable live news",
                "source": "System",
                "ticker": "SYSTEM",
                "datetime": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
        ]

    # Sample a few tickers for news to avoid rate limits
    sample_tickers = ["SPY", "QQQ", "AAPL", "TSLA", "NVDA"]

    for ticker in sample_tickers:
        try:
            response = requests.get(
                f"https://finnhub.io/api/v1/company-news?symbol={ticker}&from={today}&to={today}&token={Seb_API_key}",
                timeout=15
            )

            if response.status_code == 200:
                news_items = response.json()

                if news_items:
                    for item in news_items[:2]:  # Take up to 2 latest news items per ticker
                        headlines.append({  
                            "headline": item.get("headline", f"News for {ticker}"),
                            "summary": item.get("summary", "No summary available"),
                            "source": item.get("source", "Unknown source"),
                            "ticker": ticker,
                            "datetime": datetime.fromtimestamp(item.get("datetime", 0)).strftime('%Y-%m-%d %H:%M:%S') if item.get("datetime") else datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                        })

        except Exception as e:
            logger.error(f"Error fetching news for {ticker}: {str(e)}")

    return headlines

def calculate_portfolio_value(signals):
    """Calculate the current value of the portfolio"""
    total_value = portfolio["cash"]
    
    for ticker, position in portfolio["positions"].items():
        if position["shares"] > 0:
            current_price = signals.get(ticker, {}).get("c", 0)
            if isinstance(current_price, (int, float)) and current_price > 0:
                total_value += position["shares"] * current_price
    
    portfolio["portfolio_value"] = total_value
    return total_value

def execute_trade(decision, signals):
    """Execute a trade decision and update the portfolio"""
    global portfolio
    
    action = decision.get("action", "HOLD")
    ticker = decision.get("ticker", "").lower()
    
    if action == "HOLD" or not ticker or ticker not in portfolio["positions"]:
        return
    
    current_price = signals.get(ticker, {}).get("c", 0)
    if not isinstance(current_price, (int, float)) or current_price <= 0:
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
            
            # Update performance metrics
            trade_data = {
                "action": "buy",
                "ticker": ticker,
                "price": current_price,
                "shares": shares_to_trade
            }
            update_performance_metrics(trade_data)
            
            logger.info(f"Executed BUY: {shares_to_trade} shares of {ticker.upper()} at ${current_price:.2f}")
    
    elif action == "SELL" and portfolio["positions"][ticker]["shares"] > 0:
        shares_to_sell = min(shares_to_trade, portfolio["positions"][ticker]["shares"])
        proceeds = shares_to_sell * current_price
        
        portfolio["positions"][ticker]["shares"] -= shares_to_sell
        portfolio["cash"] += proceeds
        
        # Reset average price if position is closed
        if portfolio["positions"][ticker]["shares"] == 0:
            portfolio["positions"][ticker]["avg_price"] = 0
        
        # Update performance metrics
        trade_data = {
            "action": "sell",
            "ticker": ticker,
            "price": current_price,
            "shares": shares_to_sell
        }
        update_performance_metrics(trade_data)
        
        logger.info(f"Executed SELL: {shares_to_sell} shares of {ticker.upper()} at ${current_price:.2f}")
    
    # Save portfolio after trade
    save_portfolio()

def generate_trade_decision(signals, news_headlines):
    """Generate trading decision using OpenAI GPT model"""
    global latest_decision
    
    if not client:
        latest_decision = {
            "action": "HOLD",
            "ticker": "",
            "rationale": "OpenAI API key not configured"
        }
        return latest_decision
    
    try:
        # Prepare market data summary
        market_summary = "CURRENT MARKET DATA:\n"
        for ticker, data in signals.items():
            if isinstance(data.get('c'), (int, float)):
                change = data.get('d', 0)
                percent_change = data.get('dp', 0)
                market_summary += f"{ticker.upper()}: ${data['c']:.2f} ({percent_change:+.2f}%)\n"
        
        # Prepare news summary
        news_summary = "\nRELEVANT NEWS:\n"
        for headline in news_headlines[:10]:
            news_summary += f"{headline['ticker']}: {headline['headline']}\n"
        
        # Portfolio context
        portfolio_value = calculate_portfolio_value(signals)
        portfolio_summary = f"\nPORTFOLIO STATUS:\nCash: ${portfolio['cash']:.2f}\nTotal Value: ${portfolio_value:.2f}\n\nCURRENT POSITIONS:\n"
        for ticker, position in portfolio["positions"].items():
            if position["shares"] > 0:
                current_price = signals.get(ticker, {}).get("c", 0)
                if isinstance(current_price, (int, float)) and current_price > 0:
                    position_value = position["shares"] * current_price
                    portfolio_summary += f"{ticker.upper()}: {position['shares']} shares @ ${position['avg_price']:.2f} avg (Current: ${current_price:.2f}, Value: ${position_value:.2f})\n"
        
        available_tickers = [t for t in portfolio["positions"].keys()]
        
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
7. Only use market hours for trading (check if market is open)

AVAILABLE TICKERS: {', '.join([t.upper() for t in available_tickers])}

Market Status: {"OPEN" if isMarketOpen() else "CLOSED"}

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
    """Log trading data to Google Sheets"""
    if not sheet:
        logger.warning("No sheet connection available for logging")
        return
    
    try:
        portfolio_value = calculate_portfolio_value(signals)
        
        # Prepare row data
        row_data = [
            timestamp,
            f"Market signals for {len(signals)} tickers",
            action,
            rationale,
            "",  # Price (filled if specific trade)
            "",  # Shares (filled if specific trade)
            f"${portfolio['cash']:.2f}",
            "",  # Position value (filled if specific trade)
            f"${portfolio_value:.2f}"
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
        
        # Execute trade if decision is not HOLD and market is open
        if latest_decision["action"] != "HOLD" and isMarketOpen():
            execute_trade(latest_decision, latest_signals)
        elif latest_decision["action"] != "HOLD" and not isMarketOpen():
            logger.info("Market is closed, trade will be executed when market opens")
        
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
            "history": trading_history[-10:],
            "status": bot_status,
            "portfolio_value": calculate_portfolio_value(latest_signals)
        }
        
    except Exception as e:
        logger.error(f"Error in trading cycle: {str(e)}")
        return {"error": str(e)}

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