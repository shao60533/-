web: python scripts/check_langgraph_install.py && gunicorn -k gthread -w 1 --threads 4 --timeout 120 --bind 0.0.0.0:$PORT "stock_trading_system.web.app:create_app()"
