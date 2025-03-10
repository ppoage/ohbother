"""
OhBother - High Performance Network Packet Processing Library

This library provides high-performance packet processing capabilities using Go
under the hood, with a clean Python interface.
"""

__version__ = "0.0.2"

# Import core functionality
from .generated.ohbother import *
from .generated.go import GoClass, Init as initialize_go

# Import submodules
from . import config
from . import receive
from . import transmit
from . import utilities
from . import benchmark

# Expose key classes and functions at the top level
from .config import (
    Config, 
    PcapConfig,
    PacketConfig,
    DebugOptions,
    MultiStreamConfig,
    create_default_config
)

from .receive import (
    receive_packets_by_count,
    ContinuousPacketReceiver
)

from .transmit import (
    send_packet,
    send_packets,
    PacketSendResult,
    MultiStreamSender,
    PacketSequenceSender
)

# Initialize Go runtime
initialize_go()