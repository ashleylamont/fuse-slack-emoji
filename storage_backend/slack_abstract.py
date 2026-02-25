from abc import ABC, abstractmethod


# class Vehicle(ABC):  # Inherit from ABC to make it an abstract base class
#     @abstractmethod
#     def start_engine(self):
#         pass  # Abstract methods have no implementation
#
#     @abstractmethod
#     def stop_engine(self):
#         pass
#
#     @abstractmethod
#     def accelerate(self):
#         pass
#
#     # Can also define concrete methods with implementation
#     def turn_on_lights(self):
#         print("Lights are on.")

class AbstractSlackInterface(ABC):
    @abstractmethod
    def emoji_list(self) -> list[str]:
        pass

    @abstractmethod
    def admin_emoji_add(self, name: str, image_data: bytes) -> None:
        pass

    @abstractmethod
    def emoji_get_payload(self, emoji_name: str) -> bytes:
        pass