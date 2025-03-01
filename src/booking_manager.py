import asyncio
import logging
from typing import Dict, Any, List, TYPE_CHECKING


from uuid import uuid4
from time import time
from dataclasses import dataclass
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup
import requests
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from logger import Logger
from health_check import HealthCheck
from security_proof import SecurityProof
from login_manager import LoginManager
from form_filler import FormFiller
from retry_manager import RetryManager
from user_data_manager import UserDataManager


if TYPE_CHECKING:
    from slot_checker import SlotChecker
    from priority_manager import PriorityManager


@dataclass
class BookingData:
    booking_id: str
    passport_number: str
    slot_date: str
    slot_time: str
    appointment_type: str

class BookingManager:
    def __init__(self, config: Dict[str, Any], driver: webdriver.Chrome, 
                 slot_checker: 'SlotChecker', priority_manager: 'PriorityManager'):
        self.config = config
        self.driver = driver
        self.logger = Logger(__name__, config['log_level']).get_logger()
        self.health_check = HealthCheck(config)
        self.security_proof = SecurityProof(driver, config)
        self.login_manager = LoginManager(config)
        self.form_filler = FormFiller(driver, config)
        self.slot_checker = slot_checker
        self.priority_manager = priority_manager
        self.retry_manager = RetryManager(config)
        self.user_data_manager = UserDataManager(config)

        self.booking_stats = {
            "total_attempts": 0,
            "successful_bookings": 0,
            "failed_bookings": 0
        }

    async def initialize(self):
        await self.health_check.initialize()
        await self.security_proof.initialize()
        await self.login_manager.initialize()
        await self.user_data_manager.initialize()
        self.logger.info("BookingManager initialized successfully")

    async def close(self):
        await self.health_check.close()
        await self.security_proof.close()
        await self.login_manager.close()
        await self.user_data_manager.close()
        self.logger.info("BookingManager closed successfully")

    async def book_slot(self, user_data: Dict[str, Any]) -> Dict[str, Any]:
        return await self.retry_manager.retry(self._book_slot, user_data)

    async def _book_slot(self, user_data: Dict[str, Any]) -> Dict[str, Any]:
        booking_id = str(uuid4())
        self.booking_stats["total_attempts"] += 1
        start_time = time()

        try:
            await self.security_proof.apply_security_measures()

            # Navigate to the VFS booking page
            self.driver.get("https://visa.vfsglobal.com/pak/en/zaf/book-appointment")

            # Check login status and login if necessary
            if not await self.login_manager.check_login_status():
                await self.login_manager.login()

            # Verify form filling has been completed
            if not await self.form_filler.verify_form_completion():
                raise Exception("Form filling has not been completed")

            # Get available slots
            available_slots = await self.slot_checker.check_available_slots()
            prioritized_slots = await self.priority_manager.prioritize_slots(available_slots)

            if not prioritized_slots:
                raise Exception("No suitable slots available")

            # Select the best slot
            best_slot = prioritized_slots[0]

            # Pick appointment type
            await self.select_appointment_type(best_slot['type'])

            # Choose a slot
            await self.choose_slot(best_slot)

            # Click Continue
            continue_button = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'Continue')]"))
            )
            continue_button.click()

            # Wait for confirmation
            confirmation = WebDriverWait(self.driver, 20).until(
                EC.presence_of_element_located((By.ID, "booking-confirmation"))
            )

            end_time = time()
            latency = end_time - start_time

            if "Booking Confirmed" in confirmation.text:
                self.logger.info(f"Booking successful: {booking_id}")
                self.booking_stats["successful_bookings"] += 1
                return {"success": True, "booking_id": booking_id, "latency": latency}
            else:
                raise Exception("Booking not confirmed")

        except Exception as e:
            end_time = time()
            latency = end_time - start_time
            self.logger.error(f"Booking error: {str(e)}")
            self.booking_stats["failed_bookings"] += 1
            await self.handle_booking_errors(e, booking_id)
            return {"success": False, "reason": str(e), "booking_id": booking_id, "latency": latency}

    async def select_appointment_type(self, appointment_type: str):
        appointment_type_select = WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "appointment-type"))
        )
        select = Select(appointment_type_select)
        select.select_by_visible_text(appointment_type)

    async def choose_slot(self, slot: Dict[str, Any]):
        choose_slot_button = WebDriverWait(self.driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'Choose a slot')]"))
        )
        choose_slot_button.click()

        # Wait for calendar to appear
        calendar = WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "appointment-calendar"))
        )

        # Select date
        date_element = calendar.find_element(By.XPATH, f"//td[@data-date='{slot['date']}']")
        date_element.click()

        # Wait for time slots to appear
        time_slots = WebDriverWait(self.driver, 10).until(
            EC.presence_of_all_elements_located((By.CLASS_NAME, "time-slot"))
        )

        # Select time
        for time_slot in time_slots:
            if time_slot.text == slot['time']:
                time_slot.click()
                break
        else:
            raise Exception(f"Time slot {slot['time']} not found")

    async def rapid_book_multiple_slots(self) -> List[Dict[str, Any]]:
        all_users = await self.user_data_manager.get_all_users()
        results = []

        for i in range(0, len(all_users), 2):
            session_users = all_users[i:i+2]
            
            # Login and fill forms for the two users
            await self.login_manager.login()
            for user in session_users:
                await self.form_filler.fill_form(user)

            # Book slots for the two users
            for user in session_users:
                result = await self.book_slot(user)
                results.append(result)

            # Logout after processing two users
            await self.login_manager.logout()

        successful_bookings = sum(1 for result in results if result['success'])
        self.logger.info(f"Rapid booking completed: {successful_bookings} successful out of {len(results)} attempts")

        return results

    def get_booking_stats(self) -> Dict[str, Any]:
        total_attempts = self.booking_stats["total_attempts"]
        success_rate = (self.booking_stats["successful_bookings"] / total_attempts * 100) if total_attempts > 0 else 0
        return {
            **self.booking_stats,
            "success_rate": success_rate
        }

    async def verify_booking(self, booking_id: str) -> bool:
        try:
            self.driver.get(f"{self.config['booking_verification_url']}/{booking_id}")
            verification_element = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.ID, "booking-verification"))
            )
            verification_text = verification_element.text
            return "Booking Verified" in verification_text
        except Exception as e:
            self.logger.error(f"Booking verification failed: {str(e)}")
            return False

    async def handle_booking_errors(self, error: Exception, booking_id: str) -> None:
        self.logger.error(f"Booking error occurred for {booking_id}: {str(error)}")
        
        # Record the error in health check
        await self.health_check.record_error("booking", str(error))

        # Implement specific error handling logic here
        if isinstance(error, requests.RequestException):
            self.logger.info(f"Network error occurred. Retrying booking {booking_id}")
            # Implement retry logic
        elif isinstance(error, asyncio.TimeoutError):
            self.logger.info(f"Timeout occurred. Checking system health for booking {booking_id}")
            await self.health_check.perform_health_check()
        else:
            self.logger.info(f"Unexpected error. Notifying admin for booking {booking_id}")
            # Implement admin notification logic

    async def __aenter__(self):
        await self.initialize()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.close()
        if exc_type:
            self.logger.error(f"An error occurred: {exc_type}, {exc}")
            await self.health_check.record_error('booking_manager_exit', str(exc))
