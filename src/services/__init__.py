"""Synthetic services for offline evaluation; not connected to the legacy live runner."""
from src.services.domains import CREDENTIALS, WORK_ORDERS
from src.services.environment import ServiceEnvironment

__all__ = ['CREDENTIALS', 'WORK_ORDERS', 'ServiceEnvironment']
