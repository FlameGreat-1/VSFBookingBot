import random
import time
import string
import hashlib
import requests
from selenium import webdriver
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.keys import Keys
from fake_useragent import UserAgent
from browsermobproxy import Server
from PIL import Image
import numpy as np
from scipy.interpolate import interp1d
import cv2
import undetected_chromedriver as uc
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
import asyncio
from logger import Logger

class SecurityProof:
    def __init__(self, driver, config, cloudscraper):
        self.driver = driver
        self.config = config
        self.cloudscraper = cloudscraper  
        self.logger = Logger(config).create_logger()
        self.user_agent = UserAgent()
        self.proxy_server = Server(config['browsermob_proxy_path'])
        self.proxy_server.start()
        self.proxy = self.proxy_server.create_proxy()
        self.fingerprint_injector = FingerprintInjector()
        self.last_action_time = time.time()

    async def initialize(self):
        self.logger.info("Initializing SecurityProof")
        await self.setup_driver()
        await self.apply_initial_security_measures()

    async def setup_driver(self):
        options = webdriver.ChromeOptions()
        options.add_argument(f'user-agent={self.randomize_user_agent()}')
        options.add_argument('--proxy-server={0}'.format(self.proxy.proxy))
        options.add_argument('--disable-blink-features=AutomationControlled')
        
        # Use undetected_chromedriver to bypass detection
        self.driver = await asyncio.to_thread(uc.Chrome, options=options)
        
        # Inject custom fingerprint
        await asyncio.to_thread(self.fingerprint_injector.inject_fingerprint, self.driver)

    async def apply_initial_security_measures(self):
        await self.randomize_user_agent()
        await self.mimic_browser_fingerprint()
        await self.avoid_detection_patterns()
        await self.use_proxy_rotation()

    async def randomize_user_agent(self):
        new_user_agent = self.user_agent.random
        await asyncio.to_thread(self.driver.execute_cdp_cmd, 'Network.setUserAgentOverride', {"userAgent": new_user_agent})
        self.logger.info(f"User agent randomized: {new_user_agent}")

    async def add_random_delays(self, min_delay=0.5, max_delay=3.0):
        delay = random.uniform(min_delay, max_delay)
        await asyncio.sleep(delay)

    async def simulate_human_typing(self, element, text):
        for char in text:
            await asyncio.to_thread(element.send_keys, char)
            await asyncio.sleep(random.uniform(0.05, 0.2))
            if random.random() < 0.03:  # 3% chance of typo
                await asyncio.to_thread(element.send_keys, Keys.BACKSPACE)
                await asyncio.sleep(random.uniform(0.1, 0.3))
                await asyncio.to_thread(element.send_keys, char)
            if random.random() < 0.02:  # 2% chance of pause
                await asyncio.sleep(random.uniform(0.5, 1.5))

    async def generate_human_like_mouse_movement(self, start_point, end_point, num_points=100):
        def add_noise(coords, noise_level=5):
            return [coord + random.uniform(-noise_level, noise_level) for coord in coords]

        x = np.linspace(start_point[0], end_point[0], num_points)
        y = np.linspace(start_point[1], end_point[1], num_points)

        # Add curvature
        x_mid = (start_point[0] + end_point[0]) / 2
        y_mid = (start_point[1] + end_point[1]) / 2 + random.uniform(-100, 100)
        xp = [start_point[0], x_mid, end_point[0]]
        yp = [start_point[1], y_mid, end_point[1]]
        x = np.linspace(start_point[0], end_point[0], num_points)
        curve = interp1d(xp, yp, kind='quadratic')
        y = curve(x)

        # Add noise
        coords = list(zip(x, y))
        noisy_coords = [add_noise(coord) for coord in coords]

        return noisy_coords

    async def simulate_human_mouse_movement(self, element):
        action = ActionChains(self.driver)
        start_point = (0, 0)
        end_point = await asyncio.to_thread(lambda: (element.location['x'], element.location['y']))
        movement_path = await self.generate_human_like_mouse_movement(start_point, end_point)

        for point in movement_path:
            await asyncio.to_thread(action.move_by_offset, point[0] - start_point[0], point[1] - start_point[1])
            start_point = point
            await asyncio.sleep(random.uniform(0.001, 0.003))

        await asyncio.to_thread(action.perform)

    async def vary_request_patterns(self):
        await asyncio.sleep(random.uniform(1, 5))
        
        requests_order = ['css', 'js', 'images']
        random.shuffle(requests_order)
        for req_type in requests_order:
            await asyncio.to_thread(self.driver.execute_script, f"load{req_type.capitalize()}()")

    async def use_proxy_rotation(self):
        proxy_list = self.config['proxy_list']
        new_proxy = random.choice(proxy_list)
        self.proxy.proxy = new_proxy
        await asyncio.to_thread(self.driver.get, self.driver.current_url)
        self.logger.info(f"Rotated to new proxy: {new_proxy}")

    async def mimic_browser_fingerprint(self):
        await asyncio.to_thread(self.fingerprint_injector.inject_fingerprint, self.driver)
        self.logger.info("Browser fingerprint mimicked")

    async def avoid_detection_patterns(self):
        await asyncio.to_thread(self.driver.delete_all_cookies)
        await self.add_random_cookies()
        await self.randomize_local_storage()
        await self.simulate_browser_behavior()

    async def add_random_cookies(self):
        for _ in range(random.randint(3, 7)):
            name = ''.join(random.choices(string.ascii_letters + string.digits, k=8))
            value = hashlib.md5(str(time.time()).encode()).hexdigest()
            await asyncio.to_thread(self.driver.add_cookie, {'name': name, 'value': value})

    async def randomize_local_storage(self):
        for _ in range(random.randint(2, 5)):
            key = ''.join(random.choices(string.ascii_letters + string.digits, k=8))
            value = ''.join(random.choices(string.ascii_letters + string.digits, k=16))
            await asyncio.to_thread(self.driver.execute_script, f"localStorage.setItem('{key}', '{value}');")

    async def simulate_browser_behavior(self):
        await asyncio.to_thread(self.driver.execute_script, "window.scrollTo(0, document.body.scrollHeight/2);")
        await asyncio.sleep(random.uniform(1, 3))
        await asyncio.to_thread(self.driver.execute_script, "window.scrollTo(0, 0);")

        original_handle = self.driver.current_window_handle
        await asyncio.to_thread(self.driver.execute_script, "window.open('');")
        await asyncio.to_thread(self.driver.switch_to.window, self.driver.window_handles[-1])
        await asyncio.sleep(random.uniform(2, 5))
        await asyncio.to_thread(self.driver.close)
        await asyncio.to_thread(self.driver.switch_to.window, original_handle)

    async def apply_all_security_measures(self):
        await self.randomize_user_agent()
        await self.add_random_delays()
        await self.vary_request_patterns()
        await self.mimic_browser_fingerprint()
        await self.avoid_detection_patterns()
        await self.use_proxy_rotation()

    async def perform_action(self, action_func, *args, **kwargs):
        await self.apply_all_security_measures()
        result = await action_func(*args, **kwargs)
        self.last_action_time = time.time()
        return result

    async def wait_for_element(self, by, value, timeout=10):
        try:
            element = await asyncio.to_thread(
                WebDriverWait(self.driver, timeout).until,
                EC.presence_of_element_located((by, value))
            )
            return element
        except Exception as e:
            self.logger.error(f"Error waiting for element: {str(e)}")
            return None

    async def safe_click(self, element):
        await self.simulate_human_mouse_movement(element)
        await asyncio.to_thread(element.click)

    async def safe_send_keys(self, element, text):
        await self.simulate_human_mouse_movement(element)
        await self.simulate_human_typing(element, text)

    async def check_for_security_challenges(self):
        if "captcha" in await asyncio.to_thread(lambda: self.driver.page_source.lower()):
            await self.handle_captchas()

        # Check for other security challenges here
        # For example, checking for unusual redirects, blocked messages, etc.

    async def cleanup(self):
        self.logger.info("Cleaning up SecurityProof")
        await asyncio.to_thread(self.driver.quit)
        await asyncio.to_thread(self.proxy_server.stop)

    async def __aenter__(self):
        await self.initialize()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.cleanup()

class FingerprintInjector:
    def inject_fingerprint(self, driver):
        # No-op: This stub doesn't modify the driver.
        pass

