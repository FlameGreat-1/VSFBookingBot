import logging
import time
import random
import os
from typing import Dict, Any, List, Optional, TYPE_CHECKING
from datetime import datetime, timedelta
import json
import asyncio
import aiohttp
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, ElementClickInterceptedException
from selenium.webdriver.common.action_chains import ActionChains

from logger import Logger
from health_check import HealthCheck
from security_proof import SecurityProof
from retry_manager import RetryManager

if TYPE_CHECKING:
    from priority_manager import PriorityManager
    from booking_manager import BookingManager
    from VFSBookingBot import VFSBookingBot

class SlotChecker:
    def __init__(self, driver: webdriver.Chrome, config: Dict[str, Any], 
                 priority_manager: 'PriorityManager', 
                 booking_manager: 'BookingManager', 
                 vfs_booking_bot: 'VFSBookingBot'):
        self.driver = driver
        self.config = config
        self.logger = Logger(__name__, config['log_level']).get_logger()
        self.wait_time = config.get('wait_time', 20)
        self.url = config['slot_check_url']
        self.polling_interval = config.get('polling_interval', 300)
        self.priority_manager = priority_manager
        self.booking_manager = booking_manager
        self.vfs_booking_bot = vfs_booking_bot
        self.captcha_solver = imagecaptcha()
        self.captcha_solver.set_verbose(1)
        self.captcha_solver.set_key(config['anticaptcha_key'])
        self.last_check_time = None
        self.slots_history = []
        self.session = None
        self.health_check = HealthCheck(config)
        self.security_proof = SecurityProof(driver, config)
        self.retry_manager = RetryManager(config)

    async def initialize(self):
        self.session = aiohttp.ClientSession()
        await self.health_check.initialize()
        await self.security_proof.initialize()
        self.logger.info("SlotChecker initialized successfully")

    async def close(self):
        if self.session:
            await self.session.close()
        await self.health_check.close()
        await self.security_proof.close()
        self.logger.info("SlotChecker closed successfully")

    async def check_available_slots(self) -> List[Dict[str, Any]]:
        return await self.retry_manager.retry(self._check_available_slots)

    async def _check_available_slots(self) -> List[Dict[str, Any]]:
        self.logger.info("Checking for available slots")
        try:
            await self.security_proof.apply_security_measures()
            await self.navigate_to_slot_selection()
            slots = await self.extract_slot_information()
            self.last_check_time = datetime.now()
            self.slots_history.append({"timestamp": self.last_check_time, "slots": slots})
            await self.save_slots_history()
            await self.health_check.record_success("slot_check")
            return slots
        except Exception as e:
            self.logger.error(f"Error checking for slots: {str(e)}")
            await self.take_screenshot("slot_check_error")
            await self.health_check.record_error("slot_check", str(e))
            raise

    async def navigate_to_slot_selection(self):
        self.logger.info("Navigating to slot selection page")
        
        async with self.session.get(self.url) as response:
            if response.status == 200:
                html = await response.text()
                soup = BeautifulSoup(html, 'html.parser')
                
                if "login" in str(response.url).lower():
                    await self.login_if_necessary(soup)
                
                visa_type_select = soup.find('select', {'id': 'visaType'})
                visa_type_options = visa_type_select.find_all('option')
                visa_type_value = next(option['value'] for option in visa_type_options if option.text == self.config['visa_type'])
                
                applicants_select = soup.find('select', {'id': 'noOfApplicants'})
                applicants_options = applicants_select.find_all('option')
                applicants_value = next(option['value'] for option in applicants_options if option.text == str(self.config['num_applicants']))
                
                form_data = {
                    'visaType': visa_type_value,
                    'noOfApplicants': applicants_value,
                }
                
                async with self.session.post(f"{self.url}/submit", data=form_data) as submit_response:
                    if submit_response.status != 200 or "select-appointment" not in str(submit_response.url).lower():
                        raise Exception("Failed to navigate to slot selection page")
                
                self.logger.info("Successfully navigated to slot selection page")
            else:
                raise Exception(f"Failed to load slot selection page. Status code: {response.status}")

    async def login_if_necessary(self, soup: BeautifulSoup):
        self.logger.info("Login page detected. Attempting to log in.")
        
        login_form = soup.find('form', {'id': 'loginForm'})
        if not login_form:
            raise Exception("Login form not found")
        
        login_url = login_form.get('action')
        csrf_token = login_form.find('input', {'name': 'csrf_token'})['value']
        
        captcha_image_url = soup.find('img', {'id': 'captchaImage'})['src']
        captcha_solution = await self.solve_captcha(captcha_image_url)
        
        login_data = {
            'email': self.config['vfs_email'],
            'password': self.config['vfs_password'],
            'csrf_token': csrf_token,
            'captcha': captcha_solution
        }
        
        async with self.session.post(login_url, data=login_data) as response:
            if response.status != 200 or "dashboard" not in str(response.url).lower():
                raise Exception("Login failed")
        
        self.logger.info("Successfully logged in")

    async def extract_slot_information(self) -> List[Dict[str, Any]]:
        self.logger.info("Extracting slot information")
        slots = []
        current_month = datetime.now().strftime("%B %Y")
        
        async with self.session.get(f"{self.url}/get_slots") as response:
            if response.status == 200:
                slot_data = await response.json()
                for date, times in slot_data.items():
                    for time in times:
                        slot = {
                            'date': date,
                            'time': time,
                            'type': self.config['visa_type'],
                            'timestamp': datetime.now().isoformat()
                        }
                        slots.append(slot)
            else:
                raise Exception(f"Failed to fetch slot information. Status code: {response.status}")
        
        self.logger.info(f"Extracted {len(slots)} available slots")
        return slots

    async def solve_captcha(self, captcha_image_url: str) -> str:
        solution = await asyncio.to_thread(self.captcha_solver.solve_and_return_solution, captcha_image_url)
        if solution == 0:
            raise Exception(f"Failed to solve CAPTCHA: {self.captcha_solver.error_code}")
        return solution

    async def take_screenshot(self, name: str):
        try:
            os.makedirs("screenshots", exist_ok=True)
            screenshot_path = f"screenshots/{name}_{int(time.time())}.png"
            await asyncio.to_thread(self.driver.save_screenshot, screenshot_path)
            self.logger.info(f"Screenshot saved: {screenshot_path}")
        except Exception as e:
            self.logger.error(f"Failed to take screenshot: {str(e)}")

    async def save_slots_history(self):
        try:
            os.makedirs("data", exist_ok=True)
            with open("data/slots_history.json", "w") as f:
                json.dump(self.slots_history, f, default=str)
        except Exception as e:
            self.logger.error(f"Failed to save slots history: {str(e)}")

    async def start_polling(self):
        while True:
            try:
                await self.security_proof.apply_security_measures()
                slots = await self.check_available_slots()
                prioritized_slots = await self.priority_manager.prioritize_slots(slots)
                self.logger.info(f"Found {len(slots)} available slots, {len(prioritized_slots)} prioritized")
                
                if prioritized_slots:
                    await self.trigger_booking_process(prioritized_slots)
                
            except Exception as e:
                self.logger.error(f"Error during slot checking: {str(e)}")
                await self.health_check.record_error("slot_polling", str(e))
            
            await self.random_delay()

    async def random_delay(self):
        base_delay = self.polling_interval
        jitter = random.uniform(-30, 30)  # Add/subtract up to 30 seconds
        delay = max(base_delay + jitter, 60)  # Ensure minimum 1 minute delay
        await asyncio.sleep(delay)

    async def trigger_booking_process(self, prioritized_slots: List[Dict[str, Any]]) -> bool:
        self.logger.info(f"Triggering booking process for {len(prioritized_slots)} slots")
        
        for slot in prioritized_slots:
            try:
                # Trigger VFSBot to start the booking process
               
                await self.vfs_booking_bot.start_booking_process(slot)

                # Wait for booking result
                
                booking_result = await self.vfs_booking_bot.get_booking_result()

                if booking_result['success']:
                    self.logger.info(f"Successfully booked slot: {slot}")
                    await self.health_check.record_success("booking")
                    return True  # Exit after successful booking
                else:
                    self.logger.warning(f"Failed to book slot: {slot}. Reason: {booking_result['reason']}")
            
            except Exception as e:
                self.logger.error(f"Error during booking process: {str(e)}")
                await self.health_check.record_error("booking", str(e))
        
        return False  # Return False if no slot was successfully booked

    async def handle_dynamic_content(self):
        try:
            await asyncio.to_thread(
                WebDriverWait(self.driver, self.wait_time).until,
                EC.presence_of_element_located((By.ID, "dynamic-content"))
            )
            
            dynamic_element = self.driver.find_element(By.ID, "dynamic-content")
            dynamic_text = dynamic_element.text
            
            processed_content = await self.process_dynamic_content(dynamic_text)
            
            await self.update_slot_information(processed_content)
            
            self.logger.info("Successfully handled and processed dynamic content")
        except Exception as e:
            self.logger.error(f"Error handling dynamic content: {str(e)}")
            await self.health_check.record_error("dynamic_content", str(e))
            raise

    async def process_dynamic_content(self, content: str) -> Dict[str, Any]:
        try:
            lines = content.split('\n')
            
            processed_data = {
                'available_dates': [],
                'special_notices': [],
                'visa_types': set()
            }
            
            for line in lines:
                if line.startswith('Date:'):
                    processed_data['available_dates'].append(line.split('Date:')[1].strip())
                elif line.startswith('Notice:'):
                    processed_data['special_notices'].append(line.split('Notice:')[1].strip())
                elif line.startswith('Visa Type:'):
                    processed_data['visa_types'].add(line.split('Visa Type:')[1].strip())
            
            processed_data['visa_types'] = list(processed_data['visa_types'])
            
            return processed_data
        except Exception as e:
            self.logger.error(f"Error processing dynamic content: {str(e)}")
            await self.health_check.record_error("process_dynamic_content", str(e))
            raise

    async def update_slot_information(self, processed_content: Dict[str, Any]):
        try:
            new_slots = []
            for date in processed_content['available_dates']:
                for visa_type in processed_content['visa_types']:
                    slot = {
                        'date': date,
                        'type': visa_type,
                        'timestamp': datetime.now().isoformat()
                    }
                    new_slots.append(slot)
            
            self.slots_history.append({
                "timestamp": datetime.now(),
                "slots": new_slots,
                "special_notices": processed_content['special_notices']
            })
            
            await self.save_slots_history()
            
            self.logger.info(f"Updated slot information with {len(new_slots)} new slots")
        except Exception as e:
            self.logger.error(f"Error updating slot information: {str(e)}")
            await self.health_check.record_error("update_slot_information", str(e))
            raise

    async def handle_popup(self):
        try:
            popup = await asyncio.to_thread(
                WebDriverWait(self.driver, 5).until,
                EC.presence_of_element_located((By.ID, "popup-container"))
            )
            
            if popup:
                close_button = popup.find_element(By.CLASS_NAME, "close-button")
                await asyncio.to_thread(close_button.click)
                self.logger.info("Popup detected and closed")
        except TimeoutException:
            pass
        except Exception as e:
            self.logger.error(f"Error handling popup: {str(e)}")
            await self.health_check.record_error("handle_popup", str(e))

    async def refresh_session(self):
        try:
            await self.session.close()
            self.session = aiohttp.ClientSession()
            self.logger.info("Session refreshed successfully")
        except Exception as e:
            self.logger.error(f"Error refreshing session: {str(e)}")
            await self.health_check.record_error("refresh_session", str(e))
            raise

    async def __aenter__(self):
        await self.initialize()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.close()
