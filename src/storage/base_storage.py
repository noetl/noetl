from abc import ABC, abstractmethod


class BaseStorage(ABC):
    @abstractmethod
    def save(self, key, value):
        pass

    @abstractmethod
    def load(self, key):
        pass
