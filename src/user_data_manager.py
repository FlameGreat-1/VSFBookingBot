import os
import json
import asyncio
from typing import List, Dict, Any, Optional
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.backends import default_backend
import base64
import aiofiles
import aiohttp
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from logger import Logger
from health_check import HealthCheck
from security_proof import SecurityProof
from retry_manager import RetryManager

class UserDataManager:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.data_file_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'userData.json')
        self.encryption_key = self._derive_key(config['userDataEncryptionKey'])
        self.cipher_suite = Fernet(self.encryption_key)
        self.logger = Logger(__name__, config['log_level']).get_logger()
        self.health_check = HealthCheck(config)
        self.security_proof = SecurityProof(config)
        self.retry_manager = RetryManager(config)
        self.session = None

    def _derive_key(self, password: str) -> bytes:
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=b'UserDataManagerSalt',
            iterations=100000,
            backend=default_backend()
        )
        return base64.urlsafe_b64encode(kdf.derive(password.encode()))

    async def initialize(self):
        self.session = aiohttp.ClientSession()
        await self.health_check.initialize()
        await self.security_proof.initialize()
        self.logger.info("UserDataManager initialized successfully")

    async def close(self):
        if self.session:
            await self.session.close()
        await self.health_check.close()
        await self.security_proof.close()
        self.logger.info("UserDataManager closed successfully")

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        retry=retry_if_exception_type((IOError, json.JSONDecodeError))
    )
    async def load_user_data(self) -> List[Dict[str, Any]]:
        try:
            async with aiofiles.open(self.data_file_path, mode='r') as file:
                encrypted_data = await file.read()
            decrypted_data = self.decrypt(encrypted_data)
            return json.loads(decrypted_data)
        except FileNotFoundError:
            self.logger.warning(f"User data file not found at {self.data_file_path}. Returning empty list.")
            return []
        except (IOError, json.JSONDecodeError) as e:
            self.logger.error(f"Error loading user data: {str(e)}")
            await self.health_check.record_error('load_user_data', str(e))
            raise

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        retry=retry_if_exception_type(IOError)
    )
    async def save_user_data(self, user_data: List[Dict[str, Any]]) -> None:
        try:
            encrypted_data = self.encrypt(json.dumps(user_data))
            os.makedirs(os.path.dirname(self.data_file_path), exist_ok=True)
            async with aiofiles.open(self.data_file_path, mode='w') as file:
                await file.write(encrypted_data)
            self.logger.info(f"User data saved successfully to {self.data_file_path}")
        except IOError as e:
            self.logger.error(f"Error saving user data: {str(e)}")
            await self.health_check.record_error('save_user_data', str(e))
            raise

    async def add_user(self, user: Dict[str, Any]) -> None:
        user_data = await self.load_user_data()
        if any(existing_user['passportNumber'] == user['passportNumber'] for existing_user in user_data):
            self.logger.warning(f"User with passport number {user['passportNumber']} already exists. Skipping.")
            return
        user_data.append(user)
        await self.save_user_data(user_data)
        self.logger.info(f"User {user['firstName']} {user['lastName']} added successfully")

    async def get_user(self, passport_number: str) -> Optional[Dict[str, Any]]:
        user_data = await self.load_user_data()
        user = next((user for user in user_data if user['passportNumber'] == passport_number), None)
        if user:
            self.logger.info(f"User found: {user['firstName']} {user['lastName']}")
        else:
            self.logger.warning(f"User with passport number {passport_number} not found")
        return user

    async def get_all_users(self) -> List[Dict[str, Any]]:
        users = await self.load_user_data()
        formatted_users = []
        for user in users:
            formatted_user = {
                'firstName': user['firstName'],
                'lastName': user['lastName'],
                'gender': user['gender'],
                'dateOfBirth': user['dateOfBirth'],
                'nationality': 'Angola',  # Set to Angola for all users
                'passportNumber': user['passportNumber'],
                'passportExpiryDate': user['passportExpiryDate'],
                'phoneNumber': f"{user['countryCode']}-{user['phoneNumber']}",
                'email': user['email']
            }
            formatted_users.append(formatted_user)
        return formatted_users

    def encrypt(self, text: str) -> str:
        return self.cipher_suite.encrypt(text.encode()).decode()

    def decrypt(self, encrypted_text: str) -> str:
        return self.cipher_suite.decrypt(encrypted_text.encode()).decode()

    async def update_user(self, passport_number: str, updated_data: Dict[str, Any]) -> bool:
        user_data = await self.load_user_data()
        for user in user_data:
            if user['passportNumber'] == passport_number:
                user.update(updated_data)
                await self.save_user_data(user_data)
                self.logger.info(f"User {passport_number} updated successfully")
                return True
        self.logger.warning(f"User with passport number {passport_number} not found for update")
        return False

    async def delete_user(self, passport_number: str) -> bool:
        user_data = await self.load_user_data()
        initial_length = len(user_data)
        user_data = [user for user in user_data if user['passportNumber'] != passport_number]
        if len(user_data) < initial_length:
            await self.save_user_data(user_data)
            self.logger.info(f"User with passport number {passport_number} deleted successfully")
            return True
        self.logger.warning(f"User with passport number {passport_number} not found for deletion")
        return False

    async def backup_user_data(self) -> None:
        user_data = await self.load_user_data()
        backup_file_path = f"{self.data_file_path}.backup"
        encrypted_data = self.encrypt(json.dumps(user_data))
        async with aiofiles.open(backup_file_path, mode='w') as file:
            await file.write(encrypted_data)
        self.logger.info(f"User data backed up to {backup_file_path}")

    async def restore_user_data_from_backup(self) -> None:
        backup_file_path = f"{self.data_file_path}.backup"
        try:
            async with aiofiles.open(backup_file_path, mode='r') as file:
                encrypted_data = await file.read()
            decrypted_data = self.decrypt(encrypted_data)
            user_data = json.loads(decrypted_data)
            await self.save_user_data(user_data)
            self.logger.info(f"User data restored from {backup_file_path}")
        except FileNotFoundError:
            self.logger.error(f"Backup file not found at {backup_file_path}")
        except (IOError, json.JSONDecodeError) as e:
            self.logger.error(f"Error restoring user data from backup: {str(e)}")
            await self.health_check.record_error('restore_backup', str(e))

    async def validate_user_data(self, user: Dict[str, Any]) -> bool:
        required_fields = ['passportNumber', 'firstName', 'lastName', 'dateOfBirth', 'gender', 'nationality', 'passportExpiryDate', 'countryCode', 'phoneNumber', 'email']
        return all(field in user and user[field] for field in required_fields)

    async def get_formatted_user_data(self, passport_number: str) -> Optional[Dict[str, Any]]:
        user = await self.get_user(passport_number)
        if user:
            return {
                'firstName': user['firstName'],
                'lastName': user['lastName'],
                'gender': user['gender'],
                'dateOfBirth': user['dateOfBirth'],
                'nationality': 'Angola',  # Set to Angola for all users
                'passportNumber': user['passportNumber'],
                'passportExpiryDate': user['passportExpiryDate'],
                'phoneNumber': f"{user['countryCode']}-{user['phoneNumber']}",
                'email': user['email']
            }
        return None

    async def __aenter__(self):
        await self.initialize()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.close()
        if exc_type:
            self.logger.error(f"An error occurred: {exc_type}, {exc}")
            await self.health_check.record_error('user_data_manager_exit', str(exc))

