import time
import schedule
import requests
import logging
import os
import threading
from datetime import datetime, timedelta
import json
from flask import Flask, render_template, request, jsonify, redirect, url_for
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
client = OpenAI(api_key=OPENAI_API_KEY)

# Initialize Flask app
app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", "nexus-gate-fund-secret")

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
}

# Initialize threading event to control the bot
stop_event = threading.Event()
bot_thread = None

# Setup Google Sheets
def init_sheet():
    """Initialize and return Google Sheet connection"""
    try:
        # Extract the spreadsheet ID from the URL
        spreadsheet_id = "1oGCqjiWxtZ4fPwSx5na-Ea8NQbpDDRaFV7FdDRen3nQ"
        
        # Set up authentication with service account
        scopes = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        
        # Debug: Show available credentials files
        logger.info(f"Using credentials file: {CREDENTIALS_FILE}")
        
        # Try both possible credentials files
        if os.path.exists(CREDENTIALS_FILE):
            logger.info(f"Found credentials file: {CREDENTIALS_FILE}")
            creds = ServiceAccountCredentials.from_json_keyfile_name("nexus-gate-fund-459822-2c37c22b82d7.json", scopes)
        else:
            # Try alternative credentials file (some users reported this issue)
            logger.warning(f"Credentials file {CREDENTIALS_FILE} not found, trying alternative...")
            try:
                # Try alternative paths if needed
                alt_creds_paths = ['credentials.json', 'nexus-gate-fund-e919d1d677c2.json']
                for alt_path in alt_creds_paths:
                    if os.path.exists(alt_path):
                        logger.info(f"Using alternative credentials file: {alt_path}")
                        creds = ServiceAccountCredentials.from_json_keyfile_name(alt_path, scopes)  # type: ignore
                        break
                else:
                    raise FileNotFoundError("No valid credentials file found")
            except Exception as e:
                logger.error(f"Failed to load alternative credentials: {str(e)}")
                return None
                
        client = gspread.authorize(creds)  # type: ignore
        
        try:
            # Try opening by ID first (most reliable)
            try:
                logger.info(f"Attempting to open spreadsheet by ID: {spreadsheet_id}")
                spreadsheet = client.open_by_key(spreadsheet_id)
                logger.info(f"Successfully opened spreadsheet by ID")
            except Exception as e:
                # If ID fails, try opening by name
                logger.warning(f"Failed to open by ID: {str(e)}, trying by name: {GSHEET_NAME}")
                spreadsheet = client.open(GSHEET_NAME)
                logger.info(f"Successfully opened spreadsheet by name: {GSHEET_NAME}")
            
            # Try to access the Logs worksheet
            try:
                worksheet = spreadsheet.worksheet(WORKSHEET_NAME)
                logger.info(f"Successfully accessed worksheet: {WORKSHEET_NAME}")
                
                # Verify worksheet access by reading first row (headers)
                headers = worksheet.row_values(1)
                logger.info(f"Verified worksheet access. Headers: {headers}")
                
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
                
        except gspread.exceptions.SpreadsheetNotFound:
            logger.error(f"Could not find spreadsheet with ID: {spreadsheet_id} or name: {GSHEET_NAME}")
            return None
            
    except Exception as e:
        logger.error(f"Failed to initialize Google Sheet: {str(e)}")
        return None

def test_sheet_connection():
    """Manually test writing to Google Sheet without touching full logic"""
    try:
        sheet = init_sheet()
        if sheet:
            test_row = ["✅ Test", "Row", "From", "Bot", "At", str(datetime.now())]
            sheet.append_row(test_row)
            print("✅ Google Sheets test append succeeded.")
        else:
            print("❌ init_sheet() returned None — sheet not connected.")
    except Exception as e:
        print(f"❌ Error during test_sheet_connection: {e}")

if __name__ == "__main__":
    test_sheet_connection()
    # app.run(...) ← comment this out for now during test

# Fetch market data from Finnhub for all tickers
def get_market_signals():
    """Fetch real-time market data for all 30 specified tickers"""
    signals = {}
    
    # All 30 tickers organized by category
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
    
    logger.info(f"Fetching market data for {len(tickers)} tickers...")
    
    for ticker in tickers:
        try:
            response = requests.get(
                f"https://finnhub.io/api/v1/quote?symbol={ticker}&token={FINNHUB_API_KEY}",
                timeout=10
            )
            
            if response.status_code == 200:    #if we successfully connect to Finnhub 
                signals[ticker.lower()] = response.json()  #Make the the ticker to be lowercase(APPL -> appl)
                logger.debug(f"✓ {ticker}: {signals[ticker.lower()].get('c', 'N/A')}") # log the current price for debugging purposes
            else:
                logger.error(f"Failed to fetch data for {ticker}: {response.status_code}") #Throw and error saying we can can;t get the data for the ticker
                signals[ticker.lower()] = {"c": "N/A", "error": response.status_code} #Since we dont have the data we cant make the ticker lowercase
        except requests.RequestException as e:
            logger.error(f"Request error for {ticker}: {str(e)}")  # make an exception for timeouts, 
            signals[ticker.lower()] = {"c": "N/A", "error": str(e)}
    
    # Log a summary of successful fetches
    successful_fetches = sum(1 for ticker in signals if signals[ticker].get("c") != "N/A")
    logger.info(f"Successfully fetched {successful_fetches} out of {len(tickers)} ticker prices")
    
    return signals

# Fetch news headlines from Finnhub for all tracked tickers
def get_news_headlines():
    """Fetch the latest news headlines for all 30 tracked tickers"""
    headlines = []
    today = datetime.now().strftime('%Y-%m-%d')  # Use today's date for both from and to as requested
    
    # All 30 tickers organized by category
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
    
    # Check if we have a valid API key first
    if not FINNHUB_API_KEY:
        logger.warning("FINNHUB_API_KEY not set, using placeholder news")
        # Return placeholder news if no API key
        return [
            {
                "headline": "Market news will appear here when connected to Finnhub API",
                "summary": "Set your FINNHUB_API_KEY to enable live news",
                "source": "System",
                "ticker": "SYSTEM",
                "datetime": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
        ]
    
    logger.info(f"Fetching news headlines for {len(tickers)} tickers...")
    
    # Fetch news for each ticker
    for ticker in tickers:
        try:
            logger.info(f"Fetching news for {ticker}...")
            response = requests.get(
                f"https://finnhub.io/api/v1/company-news?symbol={ticker}&from={today}&to={today}&token={FINNHUB_API_KEY}",
                timeout=15
            )
            
            if response.status_code == 200:
                news_items = response.json()
                
                # Take up to 2 latest news items per ticker as requested
                if news_items:
                    # Get up to 2 most recent news items
                    for item in news_items[:2]:
                        # Handle potential missing fields
                        headline = item.get("headline", f"News for {ticker}")
                        if not headline:
                            headline = f"News for {ticker}"
                            
                        summary = item.get("summary", "No summary available")
                        if not summary: 
                            summary = "No summary available"
                            
                        source = item.get("source", "Unknown source")
                        if not source:
                            source = "Unknown source"
                        
                        # Handle potential timestamp issues
                        try:
                            news_datetime = datetime.fromtimestamp(item.get("datetime", 0)).strftime('%Y-%m-%d %H:%M:%S')
                        except:
                            news_datetime = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                        
                        headlines.append({  
                            "headline": headline,
                            "summary": summary,
                            "source": source,
                            "ticker": ticker,
                            "datetime": news_datetime
                        })
                    
                    logger.info(f"Added news for {ticker}")
                else:
                    logger.warning(f"No news items returned for {ticker}")
            else:
                logger.error(f"Failed to fetch news for {ticker}: {response.status_code}")
                
        except requests.RequestException as e:
            logger.error(f"Request error for {ticker} news: {str(e)}")
        
        # Add a small delay to avoid hitting rate limits
        time.sleep(0.1)
    
    # If we have no headlines at all, add a placeholder
    if not headlines:
        logger.warning("No news found for any ticker, adding placeholder")
        headlines = [
            {
                "headline": "No market news available at this time",
                "summary": "Check back later for updates",
                "source": "System",
                "ticker": "SYSTEM",
                "datetime": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
        ]
    else:
        logger.info(f"Successfully fetched a total of {len(headlines)} news items across {len(tickers)} tickers")
    
    return headlines

# Calculate portfolio value based on current prices
def calculate_portfolio_value(signals):
    """Calculate the current value of the portfolio"""
    global portfolio
    
    # Calculate the value of all positions
    position_value = 0.0
    for ticker, position in portfolio["positions"].items():
        if position["shares"] > 0 and ticker in signals and signals[ticker].get("c") != "N/A":
            current_price = float(signals[ticker]["c"])
            position_value += position["shares"] * current_price
    
    # Calculate total portfolio value
    portfolio_value = portfolio["cash"] + position_value
    
    # Update portfolio dictionary
    portfolio["portfolio_value"] = portfolio_value
    
    return {
        "cash": portfolio["cash"],
        "position_value": position_value,
        "portfolio_value": portfolio_value,
    }

# Execute a trade based on the decision
def execute_trade(decision, signals):
    """Execute a trade decision and update the portfolio"""
    global portfolio
    
    # Extract the action (buy/sell/hold)
    action = decision.lower()
    trade_executed = False
    trade_details = {"action": action, "ticker": None, "shares": 0, "price": 0, "total": 0}
    
    # If it's a hold decision, do nothing
    if "hold" in action:
        logger.info("Trade decision is HOLD, no trade executed")
        return trade_executed, trade_details
    
    # Determine the ticker to trade - default to SPY if not specified
    ticker = "spy"  # Default ticker
    
    # Check if any specific ticker is mentioned in the decision
    for possible_ticker in portfolio["positions"].keys():
        if possible_ticker in action:
            ticker = possible_ticker
            break
    
    # Get the current price for the selected ticker
    if ticker in signals and signals[ticker].get("c") != "N/A":
        current_price = float(signals[ticker]["c"])
        
        # Calculate trade size - use 25% of portfolio cash for buys
        if "buy" in action:
            # Calculate number of shares to buy (25% of cash)
            cash_to_use = portfolio["cash"] * 0.25
            shares_to_buy = int(cash_to_use / current_price)
            
            # Ensure at least 1 share is bought if we have enough cash
            if shares_to_buy < 1 and portfolio["cash"] >= current_price:
                shares_to_buy = 1
            
            if shares_to_buy > 0 and portfolio["cash"] >= (shares_to_buy * current_price):
                # Execute the buy
                total_cost = shares_to_buy * current_price
                portfolio["cash"] -= total_cost
                
                # Update position
                if ticker in portfolio["positions"] and portfolio["positions"][ticker]["shares"] > 0:
                    # Calculate new average price
                    old_shares = portfolio["positions"][ticker]["shares"]
                    old_avg_price = portfolio["positions"][ticker]["avg_price"]
                    old_value = old_shares * old_avg_price
                    new_value = old_value + total_cost
                    total_shares = old_shares + shares_to_buy
                    new_avg_price = new_value / total_shares
                    
                    portfolio["positions"][ticker]["shares"] = total_shares
                    portfolio["positions"][ticker]["avg_price"] = new_avg_price
                else:
                    # Create position if it doesn't exist
                    if ticker not in portfolio["positions"]:
                        portfolio["positions"][ticker] = {}
                    
                    portfolio["positions"][ticker]["shares"] = shares_to_buy
                    portfolio["positions"][ticker]["avg_price"] = current_price
                
                trade_executed = True
                trade_details = {
                    "action": "BUY", 
                    "ticker": ticker.upper(),
                    "shares": shares_to_buy,
                    "price": current_price,
                    "total": total_cost
                }
                
                logger.info(f"Bought {shares_to_buy} shares of {ticker.upper()} at ${current_price:.2f}, total: ${total_cost:.2f}")
            else:
                logger.warning(f"Insufficient funds to buy {ticker.upper()} at current price ${current_price:.2f}")
        
        elif "sell" in action:
            # Check if we have any shares of this ticker
            if ticker in portfolio["positions"]:  # Ensure the ticker exists in positions
                shares_owned = portfolio["positions"][ticker]["shares"]
                
                if shares_owned > 0:
                    # Sell 50% of position
                    shares_to_sell = shares_owned // 2
                    # Ensure at least 1 share is sold
                    if shares_to_sell < 1:
                        shares_to_sell = 1
                    
                    # Make sure we don't sell more than we have
                    shares_to_sell = min(shares_to_sell, shares_owned)
                    
                    if shares_to_sell > 0:
                        # Execute the sell
                        total_proceeds = shares_to_sell * current_price
                        portfolio["cash"] += total_proceeds
                        
                        # Update position
                        portfolio["positions"][ticker]["shares"] -= shares_to_sell
                        
                        # If no shares left, clean up the position
                        if portfolio["positions"][ticker]["shares"] <= 0:
                            del portfolio["positions"][ticker]
                        
                        trade_executed = True
                        trade_details = {
                            "action": "SELL", 
                            "ticker": ticker.upper(),
                            "shares": shares_to_sell,
                            "price": current_price,
                            "total": total_proceeds
                        }
                        
                        logger.info(f"Sold {shares_to_sell} shares of {ticker.upper()} at ${current_price:.2f}, proceeds: ${total_proceeds:.2f}")
            else:
                logger.warning(f"Attempted to sell {ticker.upper()} but no position exists")
    
    # Update portfolio history
    if trade_executed:
        portfolio["history"].append({
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "trade": trade_details,
            "portfolio_after": calculate_portfolio_value(signals)
        })
    else:
        # Even for HOLDs, add to history for Google Sheets logging
        portfolio["history"].append({
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "trade": {
                "action": "HOLD",
                "ticker": "NONE",
                "shares": 0,
                "price": 0.00,
                "total": 0.00
            },
            "portfolio_after": calculate_portfolio_value(signals)
        })
    
    return trade_executed, trade_details

# Send to GPT for trading decision with expanded market data and news
def generate_trade_decision(signals, news_headlines):
    """Generate trading decision using OpenAI GPT model with expanded data sources for all 30 tickers"""
    try:
        # Group tickers by category
        ticker_categories = {
            "Core Index & Volatility": ["spy", "qqq", "dia", "iwm", "vixy", "uvxy"],
            "Big Tech": ["aapl", "msft", "nvda", "amzn", "googl", "tsla", "meta"],
            "Financials & ETFs": ["xlf", "jpm", "bac", "v", "ma"],
            "Energy & Commodities": ["gld", "slv", "uso", "xle"],
            "Leverage ETFs": ["tqqq", "sqqq", "soxl", "soxs"],
            "Healthcare & Defensive": ["unh", "jnj", "pfe", "xlu"]
        }
        
        # Prepare market data for the prompt, organized by category
        market_data = "Current Market Data:\n"
        
        # Process each category
        for category, tickers in ticker_categories.items():
            market_data += f"\n{category}:\n"
            for ticker in tickers:
                if ticker in signals:
                    price = signals[ticker].get("c", "N/A")
                    market_data += f"- {ticker.upper()}: {price}\n"
        
        # Prepare news headlines for the prompt - show ticker-specific news for all available tickers
        news_data = ""
        if news_headlines:
            news_data += "\n\nRecent Market News by Ticker:\n"
            
            # Organize news by ticker for a cleaner presentation
            news_by_ticker = {}
            for news in news_headlines:
                ticker = news.get('ticker', 'GENERAL')
                if ticker not in news_by_ticker:
                    news_by_ticker[ticker] = []
                news_by_ticker[ticker].append(news)
            
            # Display news by ticker - limit to 1-2 headlines per ticker as requested
            for ticker, ticker_news in news_by_ticker.items():
                if ticker != "SYSTEM":  # Skip placeholder system messages
                    news_data += f"\n{ticker}:\n"
                    for i, news in enumerate(ticker_news[:2], 1):
                        news_data += f"  {i}. {news['headline']}\n"
        
        # Prepare portfolio data
        portfolio_data = f"""
Current Portfolio:
- Cash: ${portfolio['cash']:.2f}
- Portfolio Value: ${portfolio['portfolio_value']:.2f}
- Holdings: """
        
        has_positions = False
        for ticker, position in portfolio["positions"].items():
            if position["shares"] > 0:
                has_positions = True
                current_price = signals[ticker].get("c", "N/A")
                if current_price != "N/A":
                    position_value = position["shares"] * float(current_price)
                    portfolio_data += f"\n  * {ticker.upper()}: {position['shares']} shares at ${position['avg_price']:.2f} avg (Current value: ${position_value:.2f})"
        
        if not has_positions:
            portfolio_data += "None"
        
        # If we couldn't fetch any market data, cannot generate a decision
        if "N/A" in market_data:
            logger.warning("Some market data is missing, proceeding with available data")
        
        prompt = f"""
        You are Nexus Gate Fund, a real-time AI trading engine.
        
        Current Market Signals:
        {market_data}
        {news_data}
        
        {portfolio_data}
        
        Based on these market signals and news, determine the best trading action.
        
        Notes on the 30 tickers:
        
        Core Index & Volatility:
        - SPY: S&P 500 index ETF
        - QQQ: NASDAQ 100 index ETF
        - DIA: Dow Jones Industrial Average ETF
        - IWM: Russell 2000 Small Cap ETF
        - VIXY: VIX Short-Term Futures ETF (rises with volatility/fear)
        - UVXY: 1.5x Leveraged VIX ETF (higher volatility exposure)
        
        Big Tech:
        - AAPL: Apple Inc.
        - MSFT: Microsoft Corporation
        - NVDA: NVIDIA Corporation
        - AMZN: Amazon.com Inc.
        - GOOGL: Alphabet Inc. (Google)
        - TSLA: Tesla Inc.
        - META: Meta Platforms Inc. (Facebook)
        
        Financials & ETFs:
        - XLF: Financial Sector ETF
        - JPM: JPMorgan Chase & Co.
        - BAC: Bank of America Corp.
        - V: Visa Inc.
        - MA: Mastercard Inc.
        
        Energy & Commodities:
        - GLD: Gold ETF
        - SLV: Silver ETF
        - USO: US Oil Fund ETF
        - XLE: Energy Sector ETF
        
        Leverage ETFs:
        - TQQQ: 3x Daily NASDAQ 100 Bull ETF
        - SQQQ: 3x Daily NASDAQ 100 Bear ETF
        - SOXL: 3x Daily Semiconductor Bull ETF
        - SOXS: 3x Daily Semiconductor Bear ETF
        
        Healthcare & Defensive:
        - UNH: UnitedHealth Group Inc.
        - JNJ: Johnson & Johnson
        - PFE: Pfizer Inc.
        - XLU: Utilities Sector ETF
        
        Consider current portfolio positions and all market data when making your decision.
        If buying, specify which ticker to buy from the 30 available options.
        If selling, specify which ticker to sell from current holdings.
        
        Respond with:
        Action: [Buy/Sell/Hold] [Ticker if applicable]
        Rationale: [One sentence only]
        """

        # The newest OpenAI model is "gpt-4o" which was released May 13, 2024.
        # do not change this unless explicitly requested by the user
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=150
        )
        
        reply = response.choices[0].message.content
        # Make sure we always return a valid string for splitting
        if not reply:
            return "Action: HOLD\nRationale: No response from AI model."
        return reply
        
    except Exception as e:
        logger.error(f"Error generating trade decision: {str(e)}")
        return f"Action: HOLD\nRationale: Error in decision generation: {str(e)}"

# Log output to Google Sheets with expanded portfolio data
def log_to_sheet(sheet, timestamp, signals, action, rationale):
    """Log trading data to Google Sheets with expanded information for all 30 tickers"""
    if not sheet:
        logger.error("Cannot log to sheet: sheet is not initialized")
        return False
    
    try:
        # Calculate portfolio metrics
        portfolio_metrics = calculate_portfolio_value(signals)
        
        # All 30 tickers organized by category
        all_tickers = [
            # Core Index & Volatility
            "spy", "qqq", "dia", "iwm", "vixy", "uvxy",
            
            # Big Tech
            "aapl", "msft", "nvda", "amzn", "googl", "tsla", "meta",
            
            # Financials & ETFs
            "xlf", "jpm", "bac", "v", "ma",
            
            # Energy & Commodities
            "gld", "slv", "uso", "xle",
            
            # Leverage ETFs
            "tqqq", "sqqq", "soxl", "soxs",
            
            # Healthcare & Defensive
            "unh", "jnj", "pfe", "xlu"
        ]
        
        # Create a dictionary of ticker prices for easier handling
        ticker_prices = {}
        for ticker in all_tickers:
            # Get price, defaulting to "N/A" if not available
            price = signals.get(ticker, {}).get("c", "N/A")
            # Convert to string and handle N/A values
            ticker_prices[ticker] = price if price != "N/A" else "0.00"
        
        # Format values for cash and portfolio metrics
        cash_value = "{:.2f}".format(portfolio['cash'])
        position_value = "{:.2f}".format(portfolio_metrics['position_value'])
        portfolio_value = "{:.2f}".format(portfolio_metrics['portfolio_value'])
        
        # Get shares bought/sold information from the most recent trade
        shares_info = "0"
        price_info = "0.00"
        if len(portfolio["history"]) > 0:
            most_recent_trade = portfolio["history"][0]
            if "trade" in most_recent_trade:
                trade_details = most_recent_trade["trade"]
                if "shares" in trade_details and "price" in trade_details:
                    action_prefix = "+" if trade_details["action"] == "BUY" else "-"
                    shares_info = f"{action_prefix}{trade_details['shares']}"
                    price_info = "{:.2f}".format(trade_details["price"])
        
        # Create signal input string with all 30 tickers
        # Group them by category for better readability
        
        # Core Index & Volatility
        core_index = [f"{ticker.upper()}: {ticker_prices[ticker]}" for ticker in ["spy", "qqq", "dia", "iwm", "vixy", "uvxy"]]
        
        # Big Tech
        big_tech = [f"{ticker.upper()}: {ticker_prices[ticker]}" for ticker in ["aapl", "msft", "nvda", "amzn", "googl", "tsla", "meta"]]
        
        # Financials & ETFs
        financials = [f"{ticker.upper()}: {ticker_prices[ticker]}" for ticker in ["xlf", "jpm", "bac", "v", "ma"]]
        
        # Energy & Commodities
        energy = [f"{ticker.upper()}: {ticker_prices[ticker]}" for ticker in ["gld", "slv", "uso", "xle"]]
        
        # Leverage ETFs
        leverage = [f"{ticker.upper()}: {ticker_prices[ticker]}" for ticker in ["tqqq", "sqqq", "soxl", "soxs"]]
        
        # Healthcare & Defensive
        healthcare = [f"{ticker.upper()}: {ticker_prices[ticker]}" for ticker in ["unh", "jnj", "pfe", "xlu"]]
        
        # Combine all categories with separators
        signal_input = "Core: " + ", ".join(core_index) + " | " + \
                       "Tech: " + ", ".join(big_tech) + " | " + \
                       "Fin: " + ", ".join(financials) + " | " + \
                       "Cmdty: " + ", ".join(energy) + " | " + \
                       "Lev: " + ", ".join(leverage) + " | " + \
                       "Health: " + ", ".join(healthcare)
        
        # Prepare row data matching exact specified column order
        row_data = [
            timestamp,                   # Timestamp
            signal_input,                # Signal Input
            action,                      # Trade Action
            rationale,                   # Rationale
            price_info,                  # Price
            shares_info,                 # Shares Bought/Sold
            cash_value,                  # Cash Remaining
            position_value,              # Position Value
            portfolio_value              # Portfolio Value
        ]
        
        # Log the data being written to the spreadsheet
        logger.info(f"Preparing to write data to Google Sheet: {GSHEET_NAME}, worksheet: {WORKSHEET_NAME}")

        print("Appending row:", row_data)
        print("✅ Successfully appended to Google Sheet")
        # Append the row to the spreadsheet
        sheet.append_row(row_data)
        
        # Confirmation message that will be logged after successful append
        success_msg = f"✅ Trade logged successfully to '{GSHEET_NAME}' sheet"
        logger.info(success_msg)
        print(success_msg)
        
        # Add a visible confirmation in console for debugging
        print("\n" + "=" * 50)
        print(f"✅ TRADE LOG SUCCESS:")
        print(f"   - Spreadsheet: {GSHEET_NAME}")
        print(f"   - Worksheet: {WORKSHEET_NAME}")
        print(f"   - Action: {action}")
        print(f"   - Timestamp: {timestamp}")
        print("=" * 50 + "\n")
        
        return True
    except Exception as e:
        error_msg = f"Failed to log to Google Sheet: {str(e)}"
        logger.error(error_msg)
        
        # Add detailed error message for debugging
        print("\n" + "!" * 50)
        print(f"❌ GOOGLE SHEETS ERROR: {str(e)}")
        print(f"   - Attempted spreadsheet: {GSHEET_NAME}")
        print(f"   - Attempted worksheet: {WORKSHEET_NAME}")
        print("!" * 50 + "\n")
        
        return False

# API version for web interface
def run_trading_cycle_api():
    """Execute trading cycle and return data for API use"""
    global latest_signals, latest_news, latest_decision, portfolio
    
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    logger.info(f"Starting API trading cycle at {timestamp}")
    
    try:
        # Initialize Google Sheet connection
        sheet = init_sheet()
        
        # Fetch market signals
        signals = get_market_signals()
        latest_signals = signals
        
        # Fetch news headlines
        news_headlines = get_news_headlines()
        latest_news = news_headlines
        
        # Create signal input string for logging
        signal_input = ", ".join([f"{ticker.upper()}: {data.get('c', 'N/A')}" for ticker, data in signals.items()])
        logger.info(f"Market signals fetched: {signal_input}")
        
        # Generate trading decision
        gpt_output = generate_trade_decision(signals, news_headlines)
        logger.info(f"AI decision generated")
        
        # Parse the decision and rationale - ensure gpt_output is a string
        if not isinstance(gpt_output, str) or not gpt_output:
            gpt_output = "Action: HOLD\nRationale: No valid response from model."
            
        lines = gpt_output.split("\n")
        action_line = next((line for line in lines if line.startswith("Action:")), "Action: HOLD")
        rationale_line = next((line for line in lines if line.startswith("Rationale:")), "Rationale: No specific rationale provided.")
        
        # Extract just the action and rationale text
        action = action_line.replace("Action:", "").strip()
        rationale = rationale_line.replace("Rationale:", "").strip()
        
        # Execute the trade based on the decision
        trade_executed, trade_details = execute_trade(action, signals)
        
        # Recalculate portfolio value after potential trade
        portfolio_metrics = calculate_portfolio_value(signals)
        
        # Log to Google Sheets
        if sheet:
            log_success = log_to_sheet(sheet, timestamp, signals, action, rationale)
            if log_success:
                logger.info(f"Trade logged successfully")
            else:
                logger.warning("Failed to log trade to Google Sheets")
        else:
            logger.error("Google Sheets integration failed: Check credentials and permissions")
            print("❌ Google Sheets integration failed: Unable to initialize connection with spreadsheet")
        
        # Update latest decision
        latest_decision = {"action": action, "rationale": rationale}
        
        # Return the data
        return signals, signal_input, action, rationale
        
    except Exception as e:
        logger.error(f"Error in trading cycle: {str(e)}")
        return {}, "", "HOLD", f"Error in trading cycle: {str(e)}"

# Thread function for web interface
def run_bot_thread(stop_event, update_callback=None):
    """Run the trading bot in a thread with a stop event"""
    logger.info("Bot thread started")
    
    # Run immediately
    try:
        signals, signal_input, action, rationale = run_trading_cycle_api()
        if update_callback:
            update_callback(signals=signals, action=action, rationale=rationale)
    except Exception as e:
        logger.error(f"Error in initial trading cycle: {str(e)}")
    
    # Schedule for every 5 minutes
    next_run = time.time() + 300  # 5 minutes
    
    while not stop_event.is_set():
        current_time = time.time()
        
        if current_time >= next_run:
            try:
                signals, signal_input, action, rationale = run_trading_cycle_api()
                if update_callback:
                    update_callback(signals=signals, action=action, rationale=rationale)
                next_run = current_time + 300  # 5 minutes
            except Exception as e:
                logger.error(f"Error in scheduled trading cycle: {str(e)}")
                next_run = current_time + 60  # retry in 1 minute on error
        
        # Sleep for a short time to prevent high CPU usage
        time.sleep(1)
    
    logger.info("Bot thread stopped")

# Update status callback for the bot thread
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

# Flask routes
@app.route('/')
def index():
    """Render the main dashboard page"""
    return render_template('index.html')

@app.route('/api/market-data')
def market_data():
    """Always fetch latest prices for all 30 tickers"""
    try:
        signals = get_market_signals()
        return jsonify(signals)
    except Exception as e:
        logger.error(f"Error fetching market data: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/decision')
def decision():
    """API endpoint to get the latest trading decision"""
    global latest_decision
    return jsonify(latest_decision)

@app.route('/api/history')
def history():
    """API endpoint to get trading history"""
    global trading_history
    return jsonify(trading_history)

@app.route('/api/status')
def status():
    try:
        global bot_status
        default_status = {
            "running": False,
            "last_run": None,
            "next_run": None
        }
        if not isinstance(bot_status, dict):
            return jsonify(default_status)

        for key in default_status:
            bot_status.setdefault(key, default_status[key])

        return jsonify(bot_status)

    except Exception as e:
        print(f"Error in /api/status: {str(e)}")
        return jsonify({
            "running": False,
            "last_run": "Error",
            "next_run": "Error"
        }), 500

@app.route('/api/run-now', methods=['POST'])
def run_now():
    """API endpoint to trigger an immediate trading cycle"""
    try:
        signals, decision, action, rationale = run_trading_cycle_api()
        
        # Update the global variables
        global latest_signals, latest_decision, trading_history
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
    global bot_thread, bot_status, stop_event
    
    if bot_status["running"]:
        return jsonify({"success": False, "message": "Bot is already running"}), 400
    
    # Reset the stop event
    stop_event.clear()
    
    # Start the bot in a separate thread
    bot_thread = threading.Thread(target=run_bot_thread, args=(stop_event, update_status))
    bot_thread.daemon = True
    bot_thread.start()
    
    # Update status
    bot_status["running"] = True
    bot_status["last_run"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    bot_status["next_run"] = (datetime.now() + timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")
    
    return jsonify({"success": True, "message": "Bot started successfully"})

@app.route('/api/news')
def news():
    """API endpoint to get the latest market news"""
    global latest_news
    if not latest_news:
        try:
            latest_news = get_news_headlines()
        except Exception as e:
            logger.error(f"Error fetching news data: {str(e)}")
    return jsonify(latest_news)

@app.route('/api/portfolio')
def get_portfolio():
    """API endpoint to get the current portfolio status"""
    global portfolio
    return jsonify(portfolio)

@app.route('/api/stop-bot', methods=['POST'])
def stop_bot():
    """API endpoint to stop the trading bot"""
    global bot_status, stop_event
    
    if not bot_status["running"]:
        return jsonify({"success": False, "message": "Bot is not running"}), 400
    
    # Set the stop event to signal the bot thread to exit
    stop_event.set()
    
    # Update status
    bot_status["running"] = False
    bot_status["next_run"] = None
    
    return jsonify({"success": True, "message": "Bot stopped successfully"})

# Main trading function - CLI version
def run_trading_cycle_cli():
    """Execute one complete trading cycle (CLI version)"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    logger.info(f"Starting trading cycle at {timestamp}")
    
    try:
        # Initialize Google Sheet connection
        sheet = init_sheet()
        
        # Fetch market signals
        signals = get_market_signals()
        
        # Fetch news headlines
        news_headlines = get_news_headlines()
        
        # Create signal input string for logging
        signal_input = ", ".join([f"{ticker.upper()}: {data.get('c', 'N/A')}" for ticker, data in signals.items()])
        logger.info(f"Market signals fetched: {signal_input}")
        
        # Generate trading decision
        gpt_output = generate_trade_decision(signals, news_headlines)
        logger.info(f"AI decision generated")
        
        # Parse the decision and rationale - ensure gpt_output is a string
        if not isinstance(gpt_output, str) or not gpt_output:
            gpt_output = "Action: HOLD\nRationale: No valid response from model."
        
        lines = gpt_output.split("\n")
        action_line = next((line for line in lines if line.startswith("Action:")), "Action: HOLD")
        rationale_line = next((line for line in lines if line.startswith("Rationale:")), "Rationale: No specific rationale provided.")
        
        # Extract just the action and rationale text
        action = action_line.replace("Action:", "").strip()
        rationale = rationale_line.replace("Rationale:", "").strip()
        
        # Execute the trade based on the decision
        trade_executed, trade_details = execute_trade(action, signals)
        
        # Log to Google Sheets
        if sheet:
            log_success = log_to_sheet(sheet, timestamp, signals, action, rationale)
            if log_success:
                logger.info(f"Trade logged successfully")
            else:
                logger.warning("Failed to log trade to Google Sheets")
        else:
            logger.error("Google Sheets integration failed: Check credentials and permissions")
            print("❌ Google Sheets integration failed: Unable to initialize connection with spreadsheet")
        
        # Display trade decision
        logger.info(f"[{timestamp}] Trade Decision: {action_line} | {rationale_line}")
        
    except Exception as e:
        logger.error(f"Error in trading cycle: {str(e)}")

# Main CLI entry point (unused with Flask)
def main_cli():
    """Main function to start the trading bot in CLI mode"""
    logger.info("Nexus Gate Fund Trading Bot starting in CLI mode...")
    
    # Check for required API keys
    if not FINNHUB_API_KEY:
        logger.warning("FINNHUB_API_KEY not set. Using demo mode with limited functionality.")
    
    if not OPENAI_API_KEY:
        logger.error("OPENAI_API_KEY not set. AI decision-making will not function properly.")
    
    # Check if credentials file exists
    if not os.path.exists(CREDENTIALS_FILE):
        logger.error(f"Credentials file {CREDENTIALS_FILE} not found. Google Sheets integration will not work.")
    
    # Run an initial trading cycle
    run_trading_cycle_cli()
    
    # Schedule trading cycles every 5 minutes
    schedule.every(5).minutes.do(run_trading_cycle_cli)
    logger.info("Trading cycles scheduled every 5 minutes")
    
    # Keep the script running
    while True:
        try:
            schedule.run_pending()
            time.sleep(1)
        except KeyboardInterrupt:
            logger.info("Trading bot stopped by user")
            break
        except Exception as e:
            logger.error(f"Error in main loop: {str(e)}")
            # Sleep for a minute before retrying
            time.sleep(60)

# For direct execution
if __name__ == "__main__":
    # Run the Flask app
    app.run(host='0.0.0.0', port=5000, debug=True)
