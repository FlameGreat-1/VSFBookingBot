from flask import Flask, jsonify
import threading
import asyncio
import os
from health_check import HealthCheck
from config import config

# Import the VFSBookingBot
from VSFBookingBot import VFSBookingBot

app = Flask(__name__)
health_checker = HealthCheck(config)

# Create a new event loop for the bot thread
bot_loop = asyncio.new_event_loop()
bot_instance = None

def run_bot():
    """Run the VFSBookingBot in a separate thread with its own event loop"""
    asyncio.set_event_loop(bot_loop)
    global bot_instance
    
    async def start_bot():
        global bot_instance
        bot_instance = VFSBookingBot()
        await bot_instance.initialize()
        await bot_instance.run()
    
    try:
        bot_loop.run_until_complete(start_bot())
    except Exception as e:
        print(f"Bot error: {e}")
    finally:
        bot_loop.close()

@app.route('/api/health_check')
def health_check():
    """Health check endpoint for Render"""
    status = health_checker.get_health_status()
    return jsonify(status), 200 if status['overall'] == 'healthy' else 503

@app.route('/')
def home():
    """Simple home page"""
    return "VFS Booking Bot is running"

if __name__ == '__main__':
    # Start the bot in a background thread
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    
    # Start the Flask server
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)

