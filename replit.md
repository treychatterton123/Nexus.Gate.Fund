# Nexus Gate Fund Trading Bot

## Overview

This is an automated trading bot application that combines market data analysis, AI-powered decision making, and real-time portfolio tracking. The system fetches market data for major indices (SPY, QQQ, VIXY, etc.), uses OpenAI's GPT-4o model to analyze market signals, and logs all trading decisions to Google Sheets for record-keeping.

## System Architecture

The application follows a Flask-based web architecture with the following key characteristics:

- **Backend Framework**: Flask with Python 3.11
- **Deployment**: Gunicorn WSGI server on autoscale infrastructure
- **Database**: No traditional database; uses Google Sheets as data persistence layer
- **AI Integration**: OpenAI GPT-4o for trading decision analysis
- **Market Data**: Finnhub API for real-time market data
- **Authentication**: Google Cloud Service Account for Sheets API access

## Key Components

### 1. Flask Web Application (`app.py`)
- Main web interface for monitoring trading bot status
- Dashboard displaying latest market signals, trading decisions, and history
- RESTful API endpoints for market data retrieval
- Real-time status monitoring of bot operations

### 2. Trading Bot Engine (`main.py`)
- Core trading logic with scheduled market data fetching
- OpenAI integration for AI-powered trading decisions
- Google Sheets integration for logging and persistence
- Portfolio tracking with position management
- Supports multiple trading instruments (SPY, QQQ, DIA, VIXY, etc.)

### 3. Market Data Processing
- Real-time data fetching from Finnhub API every 5 minutes
- Market signal analysis and technical indicator calculations
- Caching mechanism to optimize API usage
- Error handling for API failures and network issues

### 4. Portfolio Management
- Virtual portfolio starting with $10,000 cash
- Position tracking for multiple instruments
- Average price calculation for holdings
- Real-time portfolio valuation

## Data Flow

1. **Market Data Acquisition**: Bot fetches real-time market data from Finnhub API
2. **Signal Analysis**: Raw market data is processed to generate trading signals
3. **AI Decision Making**: OpenAI GPT-4o analyzes signals and market conditions
4. **Decision Logging**: All decisions and rationale are logged to Google Sheets
5. **Portfolio Updates**: Virtual portfolio positions are updated based on decisions
6. **Web Dashboard**: Real-time status and data displayed via Flask web interface

## External Dependencies

### APIs and Services
- **Finnhub API**: Market data provider for real-time stock prices and indicators
- **OpenAI API**: GPT-4o model for trading decision analysis
- **Google Sheets API**: Data persistence and logging platform
- **Google Cloud Platform**: Service account authentication

### Key Python Libraries
- **Flask**: Web framework and API server
- **OpenAI**: AI model integration
- **gspread**: Google Sheets API client
- **requests**: HTTP client for API calls
- **schedule**: Task scheduling for automated trading
- **gunicorn**: WSGI HTTP server for production deployment

## Deployment Strategy

The application is configured for deployment on Replit's autoscale infrastructure:

- **Runtime**: Python 3.11 with Nix package management
- **Web Server**: Gunicorn with automatic port binding (5000 → 80)
- **Process Management**: Parallel workflow execution
- **Development Mode**: Auto-reload enabled for development
- **Dependencies**: Managed via pyproject.toml and uv.lock

### Environment Variables Required
- `FINNHUB_API_KEY`: API key for market data access
- `OPENAI_API_KEY`: API key for AI decision making
- `SESSION_SECRET`: Flask session security key

## Changelog

- June 15, 2025. Initial setup

## User Preferences

Preferred communication style: Simple, everyday language.