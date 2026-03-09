"""
Main trading system package
"""

from . import core
from . import agents  
from . import system
from . import tests

__version__ = "1.0.0"

__all__ = [
    'core',
    'agents', 
    'system',
    'tests'
]
