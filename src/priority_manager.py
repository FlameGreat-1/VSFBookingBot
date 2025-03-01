import asyncio
from typing import List, Dict, Any
from datetime import datetime, timedelta
import json
from dataclasses import dataclass, asdict
from enum import Enum

from logger import Logger
from retry_manager import RetryManager
from security_proof import SecurityProof
from health_check import HealthCheck

class AngolaToPortugalVisaType(Enum):
    NACIONAL = "Nacional (Long-term Portuguese Visa from Angola)"
    SCHENGEN = "Schengen (Short-term visa for Portugal from Angola)"

@dataclass
class Slot:
    id: str
    date: datetime
    type: AngolaToPortugalVisaType
    available_spots: int

@dataclass
class PrioritizationEvent:
    strategy: str
    input_count: int
    output_count: int
    execution_time: float
    timestamp: datetime

class PriorityManager:
    def __init__(self, config: Dict[str, Any], retry_manager: RetryManager, security_proof: SecurityProof):
        self.config = config
        self.logger = Logger(__name__, config['log_level']).get_logger()
        self.retry_manager = retry_manager
        self.security_proof = security_proof
        self.health_check = HealthCheck(config)
        self.prioritization_history: List[PrioritizationEvent] = []

    async def initialize(self):
        await self.health_check.initialize()
        await self.load_prioritization_history()
        self.logger.info("PriorityManager initialized successfully")

    async def close(self):
        await self.health_check.close()
        await self.save_prioritization_history()
        self.logger.info("PriorityManager closed successfully")

    async def prioritize_slots_for_slot_checker(self, slots: List[Slot]) -> List[Slot]:
        """
        This method is called by the SlotChecker to prioritize the available slots.
        It applies security measures, validates slots, and returns prioritized slots.
        """
        self.logger.info(f"SlotChecker requested prioritization for {len(slots)} slots")
        start_time = datetime.now()

        try:
            await self.security_proof.apply_security_measures()
            validated_slots = await self.validate_slots(slots)
            
            prioritized_slots = await self.apply_prioritization_strategy(validated_slots)

            end_time = datetime.now()
            execution_time = (end_time - start_time).total_seconds()

            event = PrioritizationEvent(
                strategy="angola_to_portugal_standard",
                input_count=len(slots),
                output_count=len(prioritized_slots),
                execution_time=execution_time,
                timestamp=end_time
            )
            self.prioritization_history.append(event)

            self.logger.info(f"Prioritization for SlotChecker completed in {execution_time:.2f} seconds")
            await self.health_check.record_success("prioritization")
            return prioritized_slots

        except Exception as e:
            await self.handle_prioritization_error(e)
            return []

    async def apply_prioritization_strategy(self, slots: List[Slot]) -> List[Slot]:
        """
        Applies the prioritization strategy. This method can be easily modified
        to implement different prioritization strategies in the future.
        """
        return sorted(
            slots,
            key=lambda slot: (
                slot.type != AngolaToPortugalVisaType.NACIONAL,
                slot.type != AngolaToPortugalVisaType.SCHENGEN,
                slot.date
            )
        )

    async def prepare_slots_for_booking_manager(self, prioritized_slots: List[Slot]) -> List[Dict[str, Any]]:
        """
        This method prepares the prioritized slots in a format that the BookingManager can use.
        It's called after prioritization to format the data for the BookingManager.
        """
        booking_ready_slots = []
        for slot in prioritized_slots:
            booking_ready_slots.append({
                'id': slot.id,
                'date': slot.date.isoformat(),
                'type': slot.type.value,
                'available_spots': slot.available_spots
            })
        self.logger.info(f"Prepared {len(booking_ready_slots)} slots for BookingManager")
        return booking_ready_slots

    async def get_prioritization_stats(self) -> Dict[str, Any]:
        total_prioritizations = len(self.prioritization_history)
        if total_prioritizations == 0:
            return {
                "total_prioritizations": 0,
                "average_execution_time": 0,
                "last_prioritization": None
            }

        average_execution_time = sum(event.execution_time for event in self.prioritization_history) / total_prioritizations

        return {
            "total_prioritizations": total_prioritizations,
            "average_execution_time": average_execution_time,
            "last_prioritization": asdict(self.prioritization_history[-1])
        }

    async def analyze_slot_trends(self, slots: List[Slot]) -> Dict[str, Any]:
        nacional_count = sum(1 for slot in slots if slot.type == AngolaToPortugalVisaType.NACIONAL)
        schengen_count = sum(1 for slot in slots if slot.type == AngolaToPortugalVisaType.SCHENGEN)
        earliest_slot = min(slots, key=lambda slot: slot.date)
        latest_slot = max(slots, key=lambda slot: slot.date)

        return {
            "total_slots": len(slots),
            "nacional_slots": nacional_count,
            "schengen_slots": schengen_count,
            "earliest_slot_date": earliest_slot.date.isoformat(),
            "latest_slot_date": latest_slot.date.isoformat(),
            "average_slots_per_day": len(slots) / ((latest_slot.date - earliest_slot.date).days + 1)
        }

    async def validate_slots(self, slots: List[Slot]) -> List[Slot]:
        valid_slots = []
        for slot in slots:
            if not isinstance(slot, Slot):
                self.logger.warning(f"Invalid slot type: {type(slot)}")
                continue
            if slot.type not in [AngolaToPortugalVisaType.NACIONAL, AngolaToPortugalVisaType.SCHENGEN]:
                self.logger.warning(f"Invalid visa type for Angola to Portugal: {slot.type}")
                continue
            if slot.available_spots <= 0:
                self.logger.warning(f"Slot {slot.id} has no available spots for Angola to Portugal visa")
                continue
            if slot.date < datetime.now():
                self.logger.warning(f"Slot {slot.id} has a past date")
                continue
            valid_slots.append(slot)
        return valid_slots

    async def handle_prioritization_error(self, error: Exception) -> None:
        self.logger.error(f"Prioritization error occurred: {str(error)}")
        await self.retry_manager.handle_error("prioritization", error)
        await self.health_check.record_error("prioritization", str(error))

    async def save_prioritization_history(self) -> None:
        try:
            history_data = [asdict(event) for event in self.prioritization_history]
            with open(self.config['prioritization_history_file'], 'w') as f:
                json.dump(history_data, f)
            self.logger.info("Prioritization history saved successfully")
        except Exception as e:
            self.logger.error(f"Failed to save prioritization history: {str(e)}")
            await self.health_check.record_error("save_prioritization_history", str(e))

    async def load_prioritization_history(self) -> None:
        try:
            with open(self.config['prioritization_history_file'], 'r') as f:
                history_data = json.load(f)
            self.prioritization_history = [PrioritizationEvent(**event) for event in history_data]
            self.logger.info("Prioritization history loaded successfully")
        except FileNotFoundError:
            self.logger.info("No prioritization history file found. Starting with empty history.")
        except Exception as e:
            self.logger.error(f"Failed to load prioritization history: {str(e)}")
            await self.health_check.record_error("load_prioritization_history", str(e))

    async def cleanup_old_history(self, days: int = 30) -> None:
        cutoff_date = datetime.now() - timedelta(days=days)
        self.prioritization_history = [event for event in self.prioritization_history if event.timestamp > cutoff_date]
        self.logger.info(f"Cleaned up prioritization history older than {days} days")
        await self.save_prioritization_history()

    async def __aenter__(self):
        await self.initialize()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.close()
        if exc_type:
            self.logger.error(f"An error occurred: {exc_type}, {exc}")
            await self.health_check.record_error('priority_manager_exit', str(exc))
