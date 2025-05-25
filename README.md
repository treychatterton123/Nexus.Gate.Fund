# Nexus Gate Fund Trading Bot

An automated trading bot that uses market data, AI decision-making, and Google Sheets logging to execute and track trading strategies.

## Features

- Fetches real-time market data for SPY, QQQ, and VIXY indices every 5 minutes
- Uses OpenAI's GPT-4o model to analyze market signals and generate trading decisions
- Logs all trading signals and decisions to Google Sheets for record-keeping
- Robust error handling for API failures and network issues
- Continuous operation with scheduled runs

## Setup Instructions

### Prerequisites

- Python 3.7+
- Google Cloud Platform Service Account with Google Sheets access
- Finnhub API key
- OpenAI API key

### Environment Variables

Set the following environment variables:

