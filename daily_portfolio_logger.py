import gspread
from oauth2client.service_account import ServiceAccountCredentials
import os
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

def init_daily_logging_sheet():
    """Initialize daily portfolio logging sheet"""
    try:
        CREDENTIALS_FILE = "nexusGateFund.json"
        if not os.path.exists(CREDENTIALS_FILE):
            # Try alternative credentials files
            alt_files = ['credentials.json', 'nexus-gate-fund-459822-2c37c22b82d7.json']
            for alt_file in alt_files:
                if os.path.exists(alt_file):
                    CREDENTIALS_FILE = alt_file
                    break
            else:
                logger.warning("No Google credentials file found for daily logging")
                return None
        
        scope = ['https://spreadsheets.google.com/feeds',
                'https://www.googleapis.com/auth/drive']
        creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, scope)
        gc = gspread.authorize(creds)
        
        # Try to access the daily logging sheet
        spreadsheet_id = "1NBTj_BvWws6lZvcS2BLUem3pNUwa5293AwBPpu5pZeU"
        spreadsheet = gc.open_by_key(spreadsheet_id)
        
        # Try to get the daily sheet or create it
        try:
            worksheet = spreadsheet.worksheet("Daily_Portfolio")
        except gspread.exceptions.WorksheetNotFound:
            worksheet = spreadsheet.add_worksheet(title="Daily_Portfolio", rows=1000, cols=10)
            # Add headers
            headers = ["Date", "Portfolio Value", "Cash", "Total Return", "Return %", "Best Position", "Worst Position"]
            worksheet.append_row(headers)
        
        return worksheet
    except Exception as e:
        logger.error(f"Failed to initialize daily logging sheet: {str(e)}")
        return None

def log_daily_portfolio_value(portfolio_value, portfolio_data):
    """Log daily portfolio value to Google Sheets"""
    try:
        sheet = init_daily_logging_sheet()
        if not sheet:
            return False
        
        current_date = datetime.now().strftime("%Y-%m-%d")
        
        # Calculate metrics
        cash = portfolio_data.get("cash", 0)
        start_value = portfolio_data.get("performance_metrics", {}).get("start_value", 10000)
        total_return = portfolio_value - start_value
        return_pct = (total_return / start_value) * 100 if start_value > 0 else 0
        
        # Find best and worst positions
        positions = portfolio_data.get("positions", {})
        best_position = "N/A"
        worst_position = "N/A"
        
        row_data = [
            current_date,
            f"${portfolio_value:.2f}",
            f"${cash:.2f}",
            f"${total_return:.2f}",
            f"{return_pct:.2f}%",
            best_position,
            worst_position
        ]
        
        sheet.append_row(row_data)
        logger.info(f"Successfully logged daily portfolio value: ${portfolio_value:.2f}")
        return True
        
    except Exception as e:
        logger.error(f"Failed to log daily portfolio value: {str(e)}")
        return False