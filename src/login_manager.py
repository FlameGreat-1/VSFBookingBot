import asyncio
import logging
import time
import random
import os
import json
from typing import Dict, Any, Optional
from datetime import datetime, timedelta
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, WebDriverException
from selenium.webdriver.common.action_chains import ActionChains
import undetected_chromedriver as uc
from bs4 import BeautifulSoup
import aiohttp
from aiohttp import ClientSession, ClientResponseError
from cryptography.fernet import Fernet
import cloudscraper

from logger import Logger
from health_check import HealthCheck
from retry_manager import RetryManager


class LoginManager:
    def __init__(self, driver, session, config: Dict[str, Any], logger, retry_manager, security_proof, cloudscraper):
        self.driver = driver
        self.session = session
        self.config = config
        self.logger = logger
        self.health_check = HealthCheck(config)  
        self.retry_manager = retry_manager  
        self.wait_time = config.get('wait_time', 20)
        self.login_url = config['login_url']
        self.dashboard_url = config['dashboard_url']
        self.cipher_suite = Fernet(config['user_data_encryption_key'])
        self.security_proof = security_proof  
        self.slot_checker = None
        self.booking_manager = None
        self.form_filler = None
        self.cloudscraper = cloudscraper  


    async def initialize(self):
        self.session = aiohttp.ClientSession()
        await self.health_check.initialize()
        await self.retry_manager.initialize()

    async def close(self):
        if self.driver:
            self.driver.quit()
            self.logger.info("WebDriver closed")
        if self.session:
            await self.session.close()
        await self.health_check.close()
        await self.retry_manager.close()

    def initialize_driver(self):
        options = uc.ChromeOptions()
        options.add_argument("--start-maximized")
        options.add_argument("--disable-extensions")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument(f"user-agent={self.config['user_agent']}")
        
        if self.config.get('headless', False):
            options.add_argument("--headless")

        try:
            self.driver = uc.Chrome(options=options)
            self.logger.info("Undetected ChromeDriver initialized successfully")
        except WebDriverException as e:
            self.logger.error(f"Failed to initialize Undetected ChromeDriver: {str(e)}")
            raise

    async def wait_and_find_element(self, by, value):
        return await self.retry_manager.retry(
            lambda: WebDriverWait(self.driver, self.wait_time).until(
                EC.presence_of_element_located((by, value))
            )
        )

    async def login(self, email: str, password: str) -> bool:
        return await self.retry_manager.retry(self._login, email, password)

    async def _login(self, email: str, password: str) -> bool:
        if not self.driver:
            self.initialize_driver()

        self.logger.info("Attempting to log in")
        try:
            await self.handle_cloudflare_challenge(self.login_url)
            
            self.driver.get(self.login_url)
            
            email_field = await self.wait_and_find_element(By.ID, "email")
            await self.type_with_random_delay(email_field, email)
            
            password_field = await self.wait_and_find_element(By.ID, "password")
            await self.type_with_random_delay(password_field, password)
            
            sign_in_button = await self.wait_and_find_element(By.XPATH, "//button[contains(text(), 'Sign In')]")
            await self.human_like_click(sign_in_button)
            
            await asyncio.sleep(self.wait_time)
            
            if self.driver.current_url == self.dashboard_url:
                self.logger.info("Login successful")
                
                for cookie in self.driver.get_cookies():
                    await self.session.cookie_jar.update_cookies({cookie['name']: cookie['value']})
                
                await self.save_login_session()
                
                await self.fill_application_details()
                
                return True
            else:
                self.logger.error("Login failed: Unexpected URL after login attempt")
                return False
        except Exception as e:
            self.logger.error(f"Login failed: {str(e)}")
            await self.take_screenshot("login_failure")
            raise

    async def handle_cloudflare_challenge(self, url):
        max_attempts = 3
        for attempt in range(max_attempts):
            try:
                response = await asyncio.to_thread(self.cloudscraper.get, url)

                if response.status_code == 200:
                    self.logger.info("CloudFlare challenge passed")
                    return
            except Exception as e:
                self.logger.warning(f"CloudFlare challenge attempt {attempt + 1} failed: {str(e)}")
                if attempt == max_attempts - 1:
                    self.logger.error("Failed to pass CloudFlare challenge after maximum attempts")
                    await self.take_screenshot("cloudflare_failure")
                    raise
                await asyncio.sleep(random.uniform(2, 5))

    async def human_like_click(self, element):
        await asyncio.to_thread(
            lambda: ActionChains(self.driver).move_to_element(element)
            .pause(random.uniform(0.1, 0.3))
            .click()
            .perform()
        )

    async def type_with_random_delay(self, element, text):
        for char in text:
            await asyncio.to_thread(element.send_keys, char)
            await asyncio.sleep(random.uniform(0.1, 0.3))

    async def take_screenshot(self, name):
        try:
            os.makedirs("screenshots", exist_ok=True)
            screenshot_path = f"screenshots/{name}_{int(time.time())}.png"
            await asyncio.to_thread(self.driver.save_screenshot, screenshot_path)
            self.logger.info(f"Screenshot saved: {screenshot_path}")
        except Exception as e:
            self.logger.error(f"Failed to take screenshot: {str(e)}")

    async def fill_application_details(self):
        try:
            app_centre_select = Select(await self.wait_and_find_element(By.ID, "application_centre"))
            await asyncio.to_thread(app_centre_select.select_by_visible_text, self.config['application_centre'])
            
            category_select = Select(await self.wait_and_find_element(By.ID, "appointment_category"))
            await asyncio.to_thread(category_select.select_by_visible_text, self.config['appointment_category'])
            
            subcategory_select = Select(await self.wait_and_find_element(By.ID, "subcategory"))
            await asyncio.to_thread(subcategory_select.select_by_visible_text, self.config['subcategory'])
            
            continue_button = await self.wait_and_find_element(By.XPATH, "//button[contains(text(), 'Continue')]")
            await self.human_like_click(continue_button)
            
            await asyncio.sleep(self.wait_time)
            
            if "your-details" in self.driver.current_url:
                self.logger.info("Application details filled and navigated to Your Details page")
                
                if self.form_filler:
                    await self.form_filler.fill_details(self.driver)
            else:
                raise Exception("Failed to navigate to Your Details page after filling application details")
                
        except Exception as e:
            self.logger.error(f"Failed to fill application details: {str(e)}")
            await self.take_screenshot("application_details_failure")
            raise

    async def check_login_status(self) -> bool:
        return await self.retry_manager.retry(self._check_login_status)

    async def _check_login_status(self) -> bool:
        try:
            async with self.session.get(self.dashboard_url) as response:
                if response.status == 200:
                    text = await response.text()
                    soup = BeautifulSoup(text, 'html.parser')
                    return bool(soup.find('div', {'class': 'dashboard-content'}))
                else:
                    return False
        except Exception as e:
            self.logger.error(f"Failed to check login status: {str(e)}")
            return False

    async def logout(self):
        return await self.retry_manager.retry(self._logout)

    async def _logout(self):
        try:
            logout_button = await self.wait_and_find_element(By.XPATH, "//button[contains(text(), 'Logout')]")
            await self.human_like_click(logout_button)
            
            await asyncio.sleep(self.wait_time)
            
            if self.login_url in self.driver.current_url:
                self.logger.info("Logout successful")
                self.session.cookie_jar.clear()
            else:
                raise Exception("Failed to logout: Unexpected URL after logout attempt")
        except Exception as e:
            self.logger.error(f"Logout failed: {str(e)}")
            raise

    async def get_page_source(self, url: str) -> str:
        return await self.retry_manager.retry(self._get_page_source, url)

    async def _get_page_source(self, url: str) -> str:
        try:
            async with self.session.get(url) as response:
                response.raise_for_status()
                return await response.text()
        except ClientResponseError as e:
            self.logger.error(f"Failed to get page source for {url}: {str(e)}")
            raise

    def parse_page(self, html: str) -> Dict[str, Any]:
        soup = BeautifulSoup(html, 'html.parser')
        return {
            'title': soup.title.string if soup.title else '',
            'content': soup.get_text(),
        }

    def encrypt_credentials(self, email: str, password: str) -> Dict[str, str]:
        encrypted_email = self.cipher_suite.encrypt(email.encode()).decode()
        encrypted_password = self.cipher_suite.encrypt(password.encode()).decode()
        return {'email': encrypted_email, 'password': encrypted_password}

    def decrypt_credentials(self, encrypted_credentials: Dict[str, str]) -> Dict[str, str]:
        decrypted_email = self.cipher_suite.decrypt(encrypted_credentials['email'].encode()).decode()
        decrypted_password = self.cipher_suite.decrypt(encrypted_credentials['password'].encode()).decode()
        return {'email': decrypted_email, 'password': decrypted_password}

    async def save_login_session(self):
        session_data = {
            'cookies': {cookie.key: cookie.value for cookie in self.session.cookie_jar},
            'headers': dict(self.session.headers),
            'last_login': datetime.now().isoformat()
        }
        encrypted_data = self.cipher_suite.encrypt(json.dumps(session_data).encode()).decode()
        async with aiofiles.open('session_data.enc', 'w') as f:
            await f.write(encrypted_data)

    async def load_login_session(self) -> Optional[Dict[str, Any]]:
        try:
            async with aiofiles.open('session_data.enc', 'r') as f:
                encrypted_data = await f.read()
            decrypted_data = self.cipher_suite.decrypt(encrypted_data.encode()).decode()
            session_data = json.loads(decrypted_data)
            
            last_login = datetime.fromisoformat(session_data['last_login'])
            if datetime.now() - last_login > timedelta(days=1):
                return None

            self.session.cookie_jar.update_cookies(session_data['cookies'])
            self.session.headers.update(session_data['headers'])
            return session_data
        except (FileNotFoundError, json.JSONDecodeError, ValueError):
            return None

    async def refresh_session(self):
        return await self.retry_manager.retry(self._refresh_session)

    async def _refresh_session(self):
        if not await self.check_login_status():
            self.logger.info("Session expired. Logging in again.")
            credentials = await self.load_credentials()
            if credentials:
                await self.login(credentials['email'], credentials['password'])
            else:
                raise Exception("No stored credentials found for session refresh")

    async def load_credentials(self) -> Optional[Dict[str, str]]:
        try:
            async with aiofiles.open('credentials.enc', 'r') as f:
                encrypted_credentials = json.loads(await f.read())
            return self.decrypt_credentials(encrypted_credentials)
        except (FileNotFoundError, json.JSONDecodeError):
            return None

    async def save_credentials(self, email: str, password: str):
        encrypted_credentials = self.encrypt_credentials(email, password)
        async with aiofiles.open('credentials.enc', 'w') as f:
            await f.write(json.dumps(encrypted_credentials))

    async def perform_health_check(self):
        return await self.health_check.check_health()

    def integrate_with_slot_checker(self, slot_checker):
        self.slot_checker = slot_checker
        if self.slot_checker:
            self.slot_checker.set_session(self.session)
            
    def integrate_with_form_filler(self, form_filler):
        self.form_filler = form_filler
        if self.form_filler:
            self.form_filler.set_session(self.session)

    def integrate_with_booking_manager(self, booking_manager):
        self.booking_manager = booking_manager
        if self.booking_manager:
            self.booking_manager.set_session(self.session)

    async def __aenter__(self):
        await self.initialize()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
        if exc_type:
            self.logger.error(f"An error occurred: {exc_type}, {exc_val}")
            return False
        return True
