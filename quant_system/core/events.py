from enum import Enum
from typing import Any, Callable, Dict, List
import datetime

class EventType(str, Enum):
    BAR = "BAR"                    # K 线切片事件
    SNAPSHOT = "SNAPSHOT"          # 实时快照事件
    ORDER_SUBMITTED = "ORDER_SUBMITTED"
    ORDER_STATUS = "ORDER_STATUS"  # 订单状态变动事件
    TRADE = "TRADE"                # 成交流水事件
    SIGNAL = "SIGNAL"              # 策略买卖信号事件
    ERROR = "ERROR"

class Event:
    def __init__(self, event_type: EventType, data: Any, timestamp: int = 0):
        self.event_type = event_type
        self.data = data
        self.timestamp = timestamp or int(datetime.datetime.now(datetime.timezone.utc).timestamp() * 1000)

    def __repr__(self) -> str:
        return f"<Event type={self.event_type.value} ts={self.timestamp}>"

class EventBus:
    """轻量级同步/异步解耦事件总线"""
    def __init__(self):
        self._handlers: Dict[EventType, List[Callable[[Event], None]]] = {}

    def subscribe(self, event_type: EventType, handler: Callable[[Event], None]):
        if event_type not in self._handlers:
            self._handlers[event_type] = []
        if handler not in self._handlers[event_type]:
            self._handlers[event_type].append(handler)

    def unsubscribe(self, event_type: EventType, handler: Callable[[Event], None]):
        if event_type in self._handlers and handler in self._handlers[event_type]:
            self._handlers[event_type].remove(handler)

    def publish(self, event: Event):
        if event.event_type in self._handlers:
            for handler in self._handlers[event.event_type]:
                try:
                    handler(event)
                except Exception as e:
                    print(f"[EventBus] Error in handler {handler}: {e}")

    def clear(self):
        self._handlers.clear()

event_bus = EventBus()
