import logging
import time
import random
import os
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
import asyncio
import aiohttp
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, ElementClickInterceptedException
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.keys import Keys
from anticaptchaofficial.imagecaptcha import imagecaptcha
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from cryptography.fernet import Fernet

from logger import Logger
from health_check import HealthCheck
from security_proof import SecurityProof
from retry_manager import RetryManager
from user_data_manager import UserDataManager

class FormFiller:
    def __init__(self, driver: webdriver.Chrome, config: Dict[str, Any], user_data_manager: UserDataManager):
        self.driver = driver
        self.config = config
        self.logger = Logger(__name__, config['log_level']).get_logger()
        self.health_check = HealthCheck(config)
        self.security_proof = SecurityProof(driver, config)
        self.retry_manager = RetryManager(config)
        self.user_data_manager = user_data_manager
        self.wait_time = config.get('wait_time', 20)
        self.failed_users = []
        self.session = None
        self.captcha_solver = imagecaptcha()
        self.captcha_solver.set_verbose(1)
        self.captcha_solver.set_key(config['anticaptcha_key'])
        self.cipher_suite = Fernet(config['encryption_key'])

    async def initialize(self):
        self.session = aiohttp.ClientSession()
        await self.health_check.initialize()
        await self.security_proof.initialize()
        self.logger.info("FormFiller initialized successfully")

    async def close(self):
        if self.session:
            await self.session.close()
        await self.health_check.close()
        await self.security_proof.close()
        self.logger.info("FormFiller closed successfully")

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        retry=retry_if_exception_type((TimeoutException, NoSuchElementException, ElementClickInterceptedException))
    )
    async def fill_form(self, user_data: Dict[str, str]) -> bool:
        self.logger.info(f"Starting to fill the form for user: {user_data['firstName']} {user_data['lastName']}")
        try:
            await self.security_proof.apply_security_measures()
            await self.navigate_to_booking_page()
            await self.fill_personal_details(user_data)
            await self.fill_passport_details(user_data)
            await self.fill_contact_details(user_data)
            await self.handle_dynamic_elements()
            await self.submit_form()
            return await self.verify_submission()
        except Exception as e:
            self.logger.error(f"Error filling form for user {user_data['firstName']} {user_data['lastName']}: {str(e)}")
            await self.take_screenshot(f"form_fill_error_{user_data['passportNumber']}")
            await self.health_check.record_error('form_fill', str(e))
            raise

    async def navigate_to_booking_page(self):
        await self.retry_manager.retry(self._navigate_to_booking_page)

    async def _navigate_to_booking_page(self):
        self.driver.get("https://visa.vfsglobal.com/pak/en/zaf/your-details")
        await self.wait_and_find_element(By.XPATH, "//h1[contains(text(), 'Your Details')]")

    async def wait_and_find_element(self, by, value):
        return await self.retry_manager.retry(lambda: WebDriverWait(self.driver, self.wait_time).until(
            EC.presence_of_element_located((by, value))
        ))

    async def fill_personal_details(self, user_data: Dict[str, str]):
        await self.type_with_random_delay(By.ID, "first_name", user_data['firstName'])
        await self.type_with_random_delay(By.ID, "last_name", user_data['lastName'])
        await self.select_option(By.ID, "gender", user_data['gender'])
        await self.fill_date(By.ID, "date_of_birth", user_data['dateOfBirth'])
        await self.select_option(By.ID, "nationality", "Angola")

    async def fill_passport_details(self, user_data: Dict[str, str]):
        await self.type_with_random_delay(By.ID, "passport_number", user_data['passportNumber'])
        await self.fill_date(By.ID, "passport_expiry", user_data['passportExpiryDate'])

    async def fill_contact_details(self, user_data: Dict[str, str]):
        country_code, phone_number = user_data['phoneNumber'].split('-')
        await self.type_with_random_delay(By.ID, "country_code", country_code)
        await self.type_with_random_delay(By.ID, "phone_number", phone_number)
        await self.type_with_random_delay(By.ID, "email", user_data['email'])
        await self.type_with_random_delay(By.ID, "confirm_email", user_data['email'])

    async def fill_date(self, by, locator, date_string):
        date_input = await self.wait_and_find_element(by, locator)
        await self.retry_manager.retry(lambda: date_input.click())
        
        # Parse the date string
        date_obj = datetime.strptime(date_string, "%Y-%m-%d")
        
        # Select year
        year_dropdown = await self.wait_and_find_element(By.CLASS_NAME, "ui-datepicker-year")
        await self.select_option_by_value(year_dropdown, str(date_obj.year))
        
        # Select month
        month_dropdown = await self.wait_and_find_element(By.CLASS_NAME, "ui-datepicker-month")
        await self.select_option_by_value(month_dropdown, str(date_obj.month - 1))  # Month is 0-indexed in datepicker
        
        # Select day
        day_element = await self.wait_and_find_element(By.XPATH, f"//a[text()='{date_obj.day}']")
        await self.retry_manager.retry(lambda: day_element.click())

    async def select_option_by_value(self, select_element, value):
        await self.retry_manager.retry(lambda: Select(select_element).select_by_value(value))

    async def handle_dynamic_elements(self):
        try:
            await self.handle_terms_and_conditions()
            await self.solve_captcha()
            await self.handle_popups()
            await self.handle_security_questions()
        except Exception as e:
            self.logger.error(f"Error handling dynamic elements: {str(e)}")
            await self.health_check.record_error('dynamic_elements', str(e))
            raise

    async def handle_terms_and_conditions(self):
        terms_checkbox = await self.wait_and_find_element(By.ID, "terms_and_conditions")
        if not terms_checkbox.is_selected():
            await self.retry_manager.retry(terms_checkbox.click)

    async def solve_captcha(self):
        captcha_image = await self.wait_and_find_element(By.ID, "captcha_image")
        captcha_image_url = captcha_image.get_attribute("src")

        captcha_text = self.captcha_solver.solve_and_return_solution(captcha_image_url)
        if captcha_text != 0:
            await self.type_with_random_delay(By.ID, "captcha_input", captcha_text)
        else:
            self.logger.error(f"Error solving CAPTCHA: {self.captcha_solver.error_code}")
            await self.health_check.record_error('captcha_solve', self.captcha_solver.error_code)
            raise Exception("Failed to solve CAPTCHA")

    async def handle_popups(self):
        try:
            popup = WebDriverWait(self.driver, 5).until(
                EC.presence_of_element_located((By.CLASS_NAME, "popup"))
            )
            if popup:
                close_button = popup.find_element(By.CLASS_NAME, "close-button")
                await self.retry_manager.retry(close_button.click)
                self.logger.info("Popup detected and closed")
        except TimeoutException:
            pass

    async def submit_form(self):
        submit_button = await self.wait_and_find_element(By.XPATH, "//button[contains(text(), 'Save')]")
        await self.retry_manager.retry(submit_button.click)

    async def verify_submission(self) -> bool:
        try:
            confirmation_element = await self.wait_and_find_element(By.XPATH, "//div[contains(text(), 'Details Saved')]")
            return confirmation_element.is_displayed()
        except TimeoutException:
            self.logger.error("Submission confirmation not found")
            await self.health_check.record_error('submission_verification', "Confirmation not found")
            return False

    async def type_with_random_delay(self, by, locator, text):
        element = await self.wait_and_find_element(by, locator)
        for char in text:
            await self.retry_manager.retry(lambda: element.send_keys(char))
            await asyncio.sleep(random.uniform(0.1, 0.3))

    async def select_option(self, by, locator, value):
        select_element = Select(await self.wait_and_find_element(by, locator))
        await self.retry_manager.retry(lambda: select_element.select_by_visible_text(value))

    async def take_screenshot(self, name):
        try:
            os.makedirs("screenshots", exist_ok=True)
            screenshot_path = f"screenshots/{name}_{int(time.time())}.png"
            self.driver.save_screenshot(screenshot_path)
            self.logger.info(f"Screenshot saved: {screenshot_path}")
        except Exception as e:
            self.logger.error(f"Failed to take screenshot: {str(e)}")

    async def process_all_users(self):
        all_users = await self.user_data_manager.get_all_users()
        processed_count = 0
        
        for user_data in all_users:
            if processed_count >= 2:
                self.logger.info("Two applicants processed. Ending the current session.")
                break
            
            try:
                success = await self.fill_form(user_data)
                if success:
                    self.logger.info(f"Form submitted successfully for user: {user_data['firstName']} {user_data['lastName']}")
                    processed_count += 1
                    if processed_count < 2:
                        await self.add_another_applicant()
                else:
                    self.logger.warning(f"Form submission failed for user: {user_data['firstName']} {user_data['lastName']}")
                    self.failed_users.append(user_data)
            except Exception as e:
                self.logger.error(f"Error processing user {user_data['firstName']} {user_data['lastName']}: {str(e)}")
                self.failed_users.append(user_data)
        
        if processed_count == 2:
            await self.finalize_booking()
        
        if self.failed_users:
            self.logger.warning(f"{len(self.failed_users)} users could not be processed")
            await self.user_data_manager.save_failed_users(self.failed_users)

    async def add_another_applicant(self):
        add_applicant_button = await self.wait_and_find_element(By.XPATH, "//button[contains(text(), 'Add another applicant')]")
        await self.retry_manager.retry(add_applicant_button.click)
        self.logger.info("Added another applicant")

    async def finalize_booking(self):
        continue_button = await self.wait_and_find_element(By.XPATH, "//button[contains(text(), 'Continue')]")
        await self.retry_manager.retry(continue_button.click)
        self.logger.info("Finalized booking and continued to next step")

    async def handle_security_questions(self):
        try:
            security_question = await self.wait_and_find_element(By.ID, "security-question")
            if security_question.is_displayed():
                self.logger.info("Security question detected")
                question_text = security_question.text
                answer = await self.get_security_question_answer(question_text)
                answer_input = await self.wait_and_find_element(By.ID, "security-answer")
                await self.type_with_random_delay(By.ID, "security-answer", answer)
                submit_button = await self.wait_and_find_element(By.ID, "security-submit")
                await self.retry_manager.retry(submit_button.click)
                self.logger.info("Security question answered")
        except TimeoutException:
            self.logger.info("No security question found")
        except Exception as e:
            self.logger.error(f"Failed to handle security questions: {str(e)}")
            await self.health_check.record_error('security_question', str(e))
            raise

    async def handle_unexpected_errors(self):
        try:
            error_message = await self.wait_and_find_element(By.CLASS_NAME, "error-message")
            if error_message.is_displayed():
                error_text = error_message.text
                self.logger.error(f"Unexpected error occurred: {error_text}")
                await self.health_check.record_error('unexpected_error', error_text)
                await self.retry_manager.retry(self.driver.refresh)
                return False
        except TimeoutException:
            return True

    async def __aenter__(self):
        await self.initialize()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.close()
        if exc_type:
            self.logger.error(f"An error occurred: {exc_type}, {exc}")
            await self.health_check.record_error('form_filler_exit', str(exc))

