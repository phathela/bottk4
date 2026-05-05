import os
import logging
import time  # ADD THIS LINE
from flask import Flask, request, jsonify
from dotenv import load_dotenv
from bybit_trader import BybitTrader
from datetime import datetime

load_dotenv()
app = Flask(__name__)
logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

API_KEY = os.getenv('BYBIT_API_KEY', '')
API_SECRET = os.getenv('BYBIT_API_SECRET', '')
WEBHOOK_KEY = os.getenv('WEBHOOK_KEY') or os.getenv('WEBHOOK_SECRET', 'default_webhook_key')
SYMBOL = os.getenv('SYMBOL', 'BTCUSDT')
TESTNET = os.getenv('BYBIT_TESTNET', 'True').lower() == 'true'

trader = BybitTrader(api_key=API_KEY, api_secret=API_SECRET, testnet=TESTNET)

# Simplified state tracking for single indicator
indicator_signals = {
    'last_action': None,
    'last_update': None,
    'trade_active': False,
    'position_side': None
}

def sync_position_state():
    """Query Bybit on startup and align state with the real position."""
    logger.info("=== Startup position sync: querying Bybit for real position state ===")
    try:
        result = trader.sync_position_from_exchange(symbol=SYMBOL)
        indicator_signals['trade_active'] = result['active']
        indicator_signals['position_side'] = result['side']
        if result['active']:
            logger.info(
                f"Startup sync complete — POSITION FOUND: "
                f"trade_active=True, position_side='{result['side']}'"
            )
        else:
            logger.info(
                "Startup sync complete — NO OPEN POSITION: "
                "trade_active=False, position_side=None"
            )
    except Exception as e:
        logger.error(f"Startup position sync failed — bot will start with default state: {str(e)}")

@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok', 'timestamp': datetime.now().isoformat()}), 200

@app.route('/webhook/3commas/a', methods=['POST'])
def webhook_3commas_a():
    """Accept webhook with TradingView/3Commas actions: enter_long, enter_short, exit_long, exit_short"""
    try:
        # Authenticate
        auth_key = request.headers.get('X-Webhook-Key') or request.headers.get('Authorization', '').replace('Bearer ', '')
        if auth_key != WEBHOOK_KEY:
            logger.warning(f"Unauthorized webhook attempt with key: {auth_key}")
            return jsonify({'error': 'Unauthorized'}), 401

        data = request.get_json(force=True, silent=True)
        logger.info(f"Webhook received: {data}")

        if data is None:
            logger.warning("Failed to parse JSON body — missing or invalid Content-Type")
            return jsonify({'error': 'Invalid or missing JSON body'}), 400

        action = data.get('action', '').lower()

        # Normalize TradingView/3Commas action names
        action_map = {
            'enter_long': 'enter_long',
            'enter_short': 'enter_short',
            'exit_long': 'enter_exit_long',
            'exit_short': 'enter_exit_short',
            'close_long': 'enter_exit_long',
            'close_short': 'enter_exit_short',
        }
        normalized_action = action_map.get(action)

        if normalized_action is None:
            logger.warning(f"Unknown action: {action}")
            return jsonify({'error': f'Unknown action: {action}'}), 400

        logger.info(f"Processing action: {action} -> {normalized_action}")
        result = execute_action(normalized_action)
        
        return jsonify({
            'status': 'received',
            'action': action,
            'trade_action': result,
            'indicator_signals': indicator_signals
        }), 200
        
    except Exception as e:
        logger.error(f"Error processing webhook: {str(e)}")
        return jsonify({'error': str(e)}), 500

def execute_action(action):
    """Execute the specified action directly"""
    
    if action == 'enter_long':
        position_side = indicator_signals['position_side']
        if position_side == 'short':
            logger.info("Action: ENTER_LONG — flipping from SHORT to LONG (closing short first)")
            if not trader.close_position(symbol=SYMBOL):
                logger.error("ENTER_LONG flip failed: could not close existing short position")
                return 'ENTER_LONG_FLIP_CLOSE_FAILED'
            indicator_signals['trade_active'] = False
            indicator_signals['position_side'] = None
            logger.info("Short position closed — opening long position")
            if trader.open_position(symbol=SYMBOL, side='Buy'):
                indicator_signals['trade_active'] = True
                indicator_signals['position_side'] = 'long'
                indicator_signals['last_action'] = 'enter_long'
                indicator_signals['last_update'] = datetime.now().isoformat()
                return 'ENTER_LONG_FLIP_SUCCESS'
            else:
                return 'ENTER_LONG_FLIP_OPEN_FAILED'
        elif position_side == 'long':
            logger.info("Action: ENTER_LONG — already in long position, skipping")
            return 'ENTER_LONG_ALREADY_LONG'
        else:
            logger.info("Action: ENTER_LONG — opening long position")
            if trader.open_position(symbol=SYMBOL, side='Buy'):
                indicator_signals['trade_active'] = True
                indicator_signals['position_side'] = 'long'
                indicator_signals['last_action'] = 'enter_long'
                indicator_signals['last_update'] = datetime.now().isoformat()
                return 'ENTER_LONG_SUCCESS'
            else:
                return 'ENTER_LONG_FAILED'
    
    elif action == 'enter_short':
        position_side = indicator_signals['position_side']
        if position_side == 'long':
            logger.info("Action: ENTER_SHORT — flipping from LONG to SHORT (closing long first)")
            if not trader.close_position(symbol=SYMBOL):
                logger.error("ENTER_SHORT flip failed: could not close existing long position")
                return 'ENTER_SHORT_FLIP_CLOSE_FAILED'
            indicator_signals['trade_active'] = False
            indicator_signals['position_side'] = None
            logger.info("Long position closed — opening short position")
            if trader.open_position(symbol=SYMBOL, side='Sell'):
                indicator_signals['trade_active'] = True
                indicator_signals['position_side'] = 'short'
                indicator_signals['last_action'] = 'enter_short'
                indicator_signals['last_update'] = datetime.now().isoformat()
                return 'ENTER_SHORT_FLIP_SUCCESS'
            else:
                return 'ENTER_SHORT_FLIP_OPEN_FAILED'
        elif position_side == 'short':
            logger.info("Action: ENTER_SHORT — already in short position, skipping")
            return 'ENTER_SHORT_ALREADY_SHORT'
        else:
            logger.info("Action: ENTER_SHORT — opening short position")
            if trader.open_position(symbol=SYMBOL, side='Sell'):
                indicator_signals['trade_active'] = True
                indicator_signals['position_side'] = 'short'
                indicator_signals['last_action'] = 'enter_short'
                indicator_signals['last_update'] = datetime.now().isoformat()
                return 'ENTER_SHORT_SUCCESS'
            else:
                return 'ENTER_SHORT_FAILED'
    
    elif action == 'enter_exit_long':
        logger.info("Action: ENTER_EXIT_LONG — closing long position")
        if indicator_signals['position_side'] != 'long':
            logger.warning(f"Cannot close long: no long position open (current: {indicator_signals['position_side']})")
            return 'ENTER_EXIT_LONG_NO_POSITION'
        
        if trader.close_position(symbol=SYMBOL):
            indicator_signals['trade_active'] = False
            indicator_signals['position_side'] = None
            indicator_signals['last_action'] = 'enter_exit_long'
            indicator_signals['last_update'] = datetime.now().isoformat()
            return 'ENTER_EXIT_LONG_SUCCESS'
        else:
            return 'ENTER_EXIT_LONG_FAILED'
    
    elif action == 'enter_exit_short':
        logger.info("Action: ENTER_EXIT_SHORT — closing short position")
        if indicator_signals['position_side'] != 'short':
            logger.warning(f"Cannot close short: no short position open (current: {indicator_signals['position_side']})")
            return 'ENTER_EXIT_SHORT_NO_POSITION'
        
        if trader.close_position(symbol=SYMBOL):
            indicator_signals['trade_active'] = False
            indicator_signals['position_side'] = None
            indicator_signals['last_action'] = 'enter_exit_short'
            indicator_signals['last_update'] = datetime.now().isoformat()
            return 'ENTER_EXIT_SHORT_SUCCESS'
        else:
            return 'ENTER_EXIT_SHORT_FAILED'
    
    return None

@app.route('/status', methods=['GET'])
def status():
    """Get current bot status"""
    try:
        position = None
        balance = 0
        current_price = None
        
        try:
            position = trader.get_position_status(symbol=SYMBOL)
        except Exception as e:
            logger.warning(f"Could not fetch position: {str(e)}")
        
        try:
            balance = trader.get_wallet_balance()
        except Exception as e:
            logger.warning(f"Could not fetch balance: {str(e)}")
        
        try:
            current_price = trader.get_current_price(symbol=SYMBOL)
        except Exception as e:
            logger.warning(f"Could not fetch price: {str(e)}")
        
        return jsonify({
            'timestamp': datetime.now().isoformat(),
            'last_action': indicator_signals['last_action'],
            'trade_active': indicator_signals['trade_active'],
            'position_side': indicator_signals['position_side'],
            'position': position,
            'balance': balance,
            'current_price': current_price,
            'symbol': SYMBOL,
            'testnet': TESTNET
        }), 200
    except Exception as e:
        logger.error(f"Error getting status: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/trade/open', methods=['POST'])
def manual_open_trade():
    """Manual endpoint to open a trade (for testing)"""
    try:
        data = request.get_json() or {}
        side = data.get('side', 'Buy')
        symbol = data.get('symbol', SYMBOL)
        
        if trader.open_position(symbol=symbol, side=side):
            indicator_signals['trade_active'] = True
            indicator_signals['position_side'] = 'long' if side == 'Buy' else 'short'
            indicator_signals['last_action'] = 'manual_open'
            indicator_signals['last_update'] = datetime.now().isoformat()
            return jsonify({'status': 'success', 'action': 'position_opened'}), 200
        else:
            return jsonify({'status': 'failed', 'action': 'position_open_failed'}), 400
    except Exception as e:
        logger.error(f"Error opening trade: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/trade/close', methods=['POST'])
def manual_close_trade():
    """Manual endpoint to close a trade (for testing)"""
    try:
        data = request.get_json() or {}
        symbol = data.get('symbol', SYMBOL)
        
        if trader.close_position(symbol=symbol):
            indicator_signals['trade_active'] = False
            indicator_signals['position_side'] = None
            indicator_signals['last_action'] = 'manual_close'
            indicator_signals['last_update'] = datetime.now().isoformat()
            return jsonify({'status': 'success', 'action': 'position_closed'}), 200
        else:
            return jsonify({'status': 'failed', 'action': 'position_close_failed'}), 400
    except Exception as e:
        logger.error(f"Error closing trade: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/config', methods=['GET'])
def get_config():
    """Get current bot configuration"""
    return jsonify({
        'symbol': SYMBOL,
        'leverage': trader.leverage,
        'balance_usage': trader.balance_usage * 100,
        'stop_loss_percent': trader.stop_loss_percent * 100,
        'stop_loss_price_percent': trader.stop_loss_price_percent * 100,
        'testnet': TESTNET
    }), 200

# Initialize on startup (wrapped so gunicorn doesn't crash if Bybit is unreachable)
try:
    time.sleep(2)  # Wait 2 seconds to avoid Bybit rate limit on startup
    sync_position_state()
    trader.set_leverage(symbol=SYMBOL, leverage=8)  # Explicitly set 8x leverage on Bybit
    logger.info(f"Bot initialized with leverage={trader.leverage}x, balance_usage={trader.balance_usage*100}%")
except Exception as e:
    logger.error(f"Startup init failed (bot running in degraded mode): {str(e)}")

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    app.run(debug=os.getenv('DEBUG', 'False').lower() == 'true', host='0.0.0.0', port=port)
