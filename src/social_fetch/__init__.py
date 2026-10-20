"""Search public social media and download selected videos on a Linux VM."""
from .client import Client, doctor

__version__ = '0.3.1'
__all__ = ['Client', 'doctor', '__version__']
