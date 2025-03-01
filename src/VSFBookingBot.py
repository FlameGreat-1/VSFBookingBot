import asyncio
import logging
from typing import Dict, Any, List
from datetime import datetime
import aiohttp
import chromedriver_binary 
import chromedriver_autoinstaller
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import random
import os
import json
from cryptography.fernet import Fernet
import cloudscraper
from aiolimiter import AsyncLimiter

# Import all necessary components
from slot_checker import SlotChecker
from booking_manager import BookingManager
from priority_manager import PriorityManager
from health_check import HealthCheck
from retry_manager import RetryManager
from user_data_manager import UserDataManager
from form_filler import FormFiller
from security_proof import SecurityProof
from login_manager import LoginManager
from config import config
from logger import Logger
from populate_user_data import PopulateUserData
from functools import partial

class VFSBookingBot:
    def __init__(self):
        self.config = config
        self.logger = None
        self.session = None
        self.driver = None
        self.slot_checker = None
        self.booking_manager = None
        self.priority_manager = None
        self.health_check = None
        self.retry_manager = None
        self.user_data_manager = None
        self.form_filler = None
        self.security_proof = None
        self.login_manager = None
        self.populate_user_data = None
        self.is_running = False
        self.cloudscraper = None
        self.rate_limiter = AsyncLimiter(self.config['rate_limit_per_second'], 1)
        self.booking_locks = {}

    async def initialize(self):
        self.logger = await Logger(self.config).__aenter__()
        await self.logger.info('Initializing VFS Booking Bot')
        self.validate_config()
        self.session = aiohttp.ClientSession()
        self.driver = await asyncio.to_thread(self.setup_webdriver)
        self.cloudscraper = cloudscraper.create_scraper()

        self.security_proof = SecurityProof(self.driver, self.config, self.cloudscraper)
        self.health_check = HealthCheck(self.config)
        self.retry_manager = RetryManager(self.config, self.health_check, self.security_proof)
        
        self.login_manager = await self.create_login_manager()
        self.priority_manager = await self.create_priority_manager()
        self.slot_checker = await self.create_slot_checker()
        self.booking_manager = await self.create_booking_manager()
        self.form_filler = await self.create_form_filler()
        self.user_data_manager = await self.create_user_data_manager()
        self.populate_user_data = PopulateUserData(self.user_data_manager, self.config)

        await self.setup_event_listeners()
        await self.security_proof.initialize()
        await self.health_check.initialize()
        await self.retry_manager.initialize()
        await self.login_manager.initialize()
        await self.user_data_manager.initialize()
        await self.slot_checker.initialize()
        await self.booking_manager.initialize()
        await self.priority_manager.initialize()
        await self.populate_user_data.run()

    def validate_config(self):
        required_keys = [
            'headless', 'user_agent', 'vfs_username', 'vfs_password',
            'rate_limit_per_second', 'check_interval', 'max_retries',
            'retry_delay', 'health_check_interval', 'log_level'
        ]
        for key in required_keys:
            if key not in self.config:
                raise ValueError(f"Missing required configuration key: {key}")
        
        if not isinstance(self.config['rate_limit_per_second'], int) or self.config['rate_limit_per_second'] <= 0:
            raise ValueError("rate_limit_per_second must be a positive integer")
        
        if not isinstance(self.config['check_interval'], int) or self.config['check_interval'] <= 0:
            raise ValueError("check_interval must be a positive integer")
    

    def setup_webdriver(self):
        chrome_options = Options()
        if self.config['headless']:
            chrome_options.add_argument("--headless")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument(f"user-agent={self.config['user_agent']}")
    
         # Randomize browser fingerprint
        chrome_options.add_argument(f"--window-size={random.randint(1000, 1200)},{random.randint(800, 1000)}")
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option('useAutomationExtension', False)
    
           # Automatically download and install the correct ChromeDriver version
        chromedriver_autoinstaller.install()  # This will check the current Chrome version and install the matching driver
    
        driver = webdriver.Chrome(options=chrome_options)
    
         # Set random viewport size
        driver.set_window_size(random.randint(1000, 1200), random.randint(800, 1000))
    
        return driver

    async def create_login_manager(self):
        return LoginManager(self.driver, self.session, self.config, self.logger, self.retry_manager, self.security_proof, self.cloudscraper)

    async def create_slot_checker(self):
        return SlotChecker(self.driver, self.config, self.priority_manager, self.notify_slots_available)

    async def create_form_filler(self):
        return FormFiller(self.driver, self.config, self.logger, self.retry_manager, self.security_proof)

    async def create_booking_manager(self):
        return BookingManager(self.config, self.driver, self.slot_checker, self.priority_manager)

    async def create_priority_manager(self):
        return PriorityManager(self.config, self.retry_manager, self.security_proof, self.logger)

    async def create_user_data_manager(self):
        return UserDataManager(self.config, self.logger, self.retry_manager)
    
    async def notify_slots_available(self, slots):
        await self.booking_manager.process_available_slots(slots)

    async def setup_event_listeners(self):
        self.health_check.add_listener('health_warning', self.on_health_warning)
        self.booking_manager.add_listener('booking_success', self.on_booking_success)
        self.booking_manager.add_listener('booking_error', self.on_booking_error)
        self.retry_manager.add_listener('retry', self.on_retry)
        self.slot_checker.add_listener('slots_updated', self.on_slots_updated)
        self.slot_checker.add_listener('error', self.on_slot_checker_error)
        self.login_manager.add_listener('login_success', self.on_login_success)
        self.login_manager.add_listener('login_error', self.on_login_error)

    async def on_health_warning(self, status):
        await self.logger.warning('Health check warning', extra=status)
        if status['severity'] == 'critical':
            await self.stop()
            await self.initialize()

    async def on_booking_success(self, data):
        await self.logger.info(f"Booking successful for slot {data['slot'].id}", 
                         extra={'booking_id': data['booking_id'], 'user': data['user_data']['passport_number'], 'latency': data['latency']})
        await self.user_data_manager.update_user_booking_status(data['user_data']['passport_number'], 'booked')

    async def on_booking_error(self, data):
        await self.logger.error(f"Booking failed for slot {data['slot'].id}", 
                          extra={'booking_id': data['booking_id'], 'user': data['user_data']['passport_number'], 'error': str(data['error']), 'latency': data['latency']})
        await self.retry_manager.schedule_retry(self.booking_manager.book_slot, data['slot'], data['user_data'])

    async def on_retry(self, data):
        await self.logger.warning('Retrying operation', extra={'error': str(data['error']), 'attempts': data['attempts'], 'delay': data['delay']})

    async def on_slots_updated(self, slots):
        await self.logger.info(f"New slots available: {len(slots)}")
        prioritized_slots = await self.priority_manager.prioritize_slots(slots)
        if prioritized_slots:
            await self.trigger_booking_process(prioritized_slots)

    async def on_slot_checker_error(self, error):
        await self.logger.error('Error in slot checker', exc_info=error)
        await self.health_check.record_error('slot_checker', str(error))

    async def on_login_success(self, data):
        await self.logger.info('Login successful', extra={'username': data['username']})

    async def on_login_error(self, data):
        await self.logger.error('Login failed', extra={'username': data['username'], 'error': str(data['error'])})
        await self.retry_manager.schedule_retry(self.login_manager.login, data['username'], data['password'])

    async def trigger_booking_process(self, prioritized_slots):
        await self.logger.info(f"Triggering booking process for {len(prioritized_slots)} slots")
        await self.perform_booking_cycle(prioritized_slots)

    async def perform_booking_cycle(self, prioritized_slots=None):
        async with self.health_check.check_health():
            async with self.security_proof.apply_security():
                if not await self.login_manager.check_login_status():
                    await self.login_manager.login(self.config['vfs_username'], self.config['vfs_password'])

                if not prioritized_slots:
                    available_slots = await self.retry_manager.retry(self.slot_checker.check_available_slots)
                    prioritized_slots = await self.priority_manager.prioritize_slots(available_slots)
                
                await self.logger.info(f"Processing {len(prioritized_slots)} prioritized slots")

                if not prioritized_slots:
                    await self.logger.info('No slots available for booking')
                    return

                user_data_list = await self.user_data_manager.get_unbooked_users(limit=2)
                if not user_data_list:
                    await self.logger.warning('No unbooked users available for booking')
                    return

                for user_data in user_data_list:
                    await self.form_filler.fill_form(user_data)
                    await self.form_filler.save_form()

                if len(user_data_list) == 2:
                    await self.form_filler.add_another_applicant()
                    await self.form_filler.fill_form(user_data_list[1])
                    await self.form_filler.save_form()

                await self.form_filler.continue_to_booking()

                for slot in prioritized_slots:
                    async with self.get_booking_lock(slot.id):
                        async with self.rate_limiter:
                            booking_result = await self.booking_manager.book_slot(slot, user_data_list[0])
                            if booking_result['success']:
                                break

                booking_stats = await self.booking_manager.get_booking_stats()
                await self.logger.info('Booking cycle completed', extra=booking_stats)
                await self.health_check.record_booking_cycle(booking_stats)

    def get_booking_lock(self, slot_id):
        if slot_id not in self.booking_locks:
            self.booking_locks[slot_id] = asyncio.Lock()
        return self.booking_locks[slot_id]

    async def run(self):
        await self.logger.info('Starting VFS Booking Bot')
        try:
            await self.initialize()
            self.is_running = True
            await self.health_check.start()
            await self.slot_checker.start_polling()

            while self.is_running:
                try:
                    await self.perform_booking_cycle()
                except aiohttp.ClientError as e:
                    await self.logger.error(f'Network error in main bot loop: {str(e)}', exc_info=e)
                    await self.health_check.record_error('network', str(e))
                except asyncio.TimeoutError as e:
                    await self.logger.error(f'Timeout error in main bot loop: {str(e)}', exc_info=e)
                    await self.health_check.record_error('timeout', str(e))
                except Exception as e:
                    await self.logger.error(f'Unexpected error in main bot loop: {str(e)}', exc_info=e)
                    await self.health_check.record_error('unexpected', str(e))
                
                await asyncio.sleep(self.config['check_interval'])
        except Exception as e:
            await self.logger.critical(f'Fatal error in VFS Booking Bot: {str(e)}', exc_info=e)
        finally:
            await self.stop()

    async def stop(self):
        await self.logger.info('Stopping VFS Booking Bot')
        self.is_running = False
        tasks = [
            self.health_check.stop(),
            self.slot_checker.stop_polling(),
            self.session.close() if self.session else None,
            asyncio.to_thread(self.driver.quit) if self.driver else None,
            self.user_data_manager.close(),
            self.security_proof.cleanup(),
            self.booking_manager.close(),
            self.priority_manager.close(),
            self.logger.close()
        ]
        await asyncio.gather(*[t for t in tasks if t is not None])
        if self.logger:
            await self.logger.__aexit__(None, None, None)
    
    async def __aenter__(self):
        self.logger = Logger(self.config)  # Remove the async context manager usage here
        await self.logger.initialize()  # Add this line to initialize the logger
        await self.logger.info('Initializing VFS Booking Bot')
        await self.initialize()
        return self


    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.stop()
        if exc_type:
            await self.logger.error(f"An error occurred: {exc_type}, {exc_val}")
        if self.logger:
            await self.logger.__aexit__(exc_type, exc_val, exc_tb)
        return False

async def main():
    async with VFSBookingBot() as bot:
        try:
            await bot.run()
        except Exception as error:
            await bot.logger.critical('Fatal error in VFS Booking Bot', exc_info=error)

if __name__ == "__main__":
    asyncio.run(main())
