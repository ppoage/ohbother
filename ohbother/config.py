"""
Configuration objects for OhBother packet processing.

This module provides Pythonic wrappers around the underlying Go configuration
structures, with proper type hints and documentation.
"""

from typing import Optional, Union, List, Dict, Any
import ipaddress
from .generated.ohbother import (
    Config as GoConfig,
    PcapConfig as GoPcapConfig,
    PacketConfig as GoPacketConfig,
    DebugOptions as GoDebugOptions,
    MultiStreamConfig as GoMultiStreamConfig, 
    Logger
    
)
from .generated.go import GoClass, HardwareAddr
#from .core import NewMultiStreamConfig 


class PcapConfig:
    """
    Configuration for packet capture settings.
    """
    
    def __init__(
        self,
        interface: str = "",
        snap_len: int = 65535,
        promisc: bool = True, 
        buffer_size: int = 1024 * 1024,
        immediate_mode: bool = True,
        bpf_filter: str = ""
    ):
        """
        Initialize packet capture configuration.
        
        Args:
            interface: Network interface name
            snap_len: Maximum number of bytes to capture per packet
            promisc: Enable promiscuous mode
            buffer_size: Size of the capture buffer in bytes
            immediate_mode: Enable immediate packet delivery
            bpf_filter: Berkeley Packet Filter string
        """
        self._config = GoPcapConfig()
        self.interface = interface
        self.snap_len = snap_len
        self.promisc = promisc
        self.buffer_size = buffer_size
        self.immediate_mode = immediate_mode
        self.bpf_filter = bpf_filter
    
    @property
    def interface(self) -> str:
        """Network interface to use for packet capture."""
        return self._config.Iface
    
    @interface.setter
    def interface(self, value: str) -> None:
        self._config.Iface = value
    
    @property
    def snap_len(self) -> int:
        """Maximum bytes to capture per packet."""
        return self._config.SnapLen
    
    @snap_len.setter
    def snap_len(self, value: int) -> None:
        if not isinstance(value, int) or value <= 0:
            raise ValueError("snap_len must be a positive integer")
        self._config.SnapLen = value
    
    @property
    def promisc(self) -> bool:
        """Whether to enable promiscuous mode."""
        return self._config.Promisc
    
    @promisc.setter
    def promisc(self, value: bool) -> None:
        self._config.Promisc = value
    
    @property
    def buffer_size(self) -> int:
        """Size of capture buffer in bytes."""
        return self._config.BufferSize
    
    @buffer_size.setter
    def buffer_size(self, value: int) -> None:
        if not isinstance(value, int) or value <= 0:
            raise ValueError("buffer_size must be a positive integer")
        self._config.BufferSize = value
    
    @property
    def immediate_mode(self) -> bool:
        """Whether to enable immediate packet delivery."""
        return self._config.ImmediateMode
    
    @immediate_mode.setter
    def immediate_mode(self, value: bool) -> None:
        self._config.ImmediateMode = value
    
    @property
    def bpf_filter(self) -> str:
        """Berkeley Packet Filter expression."""
        return self._config.BPF
    
    @bpf_filter.setter
    def bpf_filter(self, value: str) -> None:
        self._config.BPF = value
        
    def _get_go_object(self) -> GoPcapConfig:
        """Get the underlying Go object."""
        return self._config


class PacketConfig:
    """
    Configuration for packet header information.
    """
    
    def __init__(
        self,
        src_mac: str = "",
        dst_mac: str = "",
        src_ip: str = "",
        dst_ip: str = "",
        src_port: int = 0,
        dst_port: int = 0,
        bpf_filter: str = ""
    ):
        """
        Initialize packet header configuration.
        
        Args:
            src_mac: Source MAC address (format: "xx:xx:xx:xx:xx:xx")
            dst_mac: Destination MAC address (format: "xx:xx:xx:xx:xx:xx") 
            src_ip: Source IP address
            dst_ip: Destination IP address
            src_port: Source UDP port
            dst_port: Destination UDP port
            bpf_filter: Berkeley Packet Filter string
        """
        self._config = GoPacketConfig()
        
        if src_mac:
            self.src_mac = src_mac
        if dst_mac:
            self.dst_mac = dst_mac
        
        self.src_ip = src_ip
        self.dst_ip = dst_ip
        self.src_port = src_port
        self.dst_port = dst_port
        self.bpf_filter = bpf_filter
    
    @property
    def src_mac(self) -> str:
        """Source MAC address."""
        # Convert from Go HardwareAddr to a string representation
        if self._config.SrcMAC:
            mac_bytes = [self._config.SrcMAC[i] for i in range(len(self._config.SrcMAC))]
            return ':'.join(f'{b:02x}' for b in mac_bytes)
        return ""
    
    @src_mac.setter
    def src_mac(self, value: str) -> None:
        if value:
            # Parse MAC address string to HardwareAddr
            mac_bytes = [int(x, 16) for x in value.split(':')]
            hw_addr = HardwareAddr()
            for b in mac_bytes:
                hw_addr.append(b)
            self._config.SrcMAC = hw_addr
    
    @property
    def dst_mac(self) -> str:
        """Destination MAC address."""
        if self._config.DstMAC:
            mac_bytes = [self._config.DstMAC[i] for i in range(len(self._config.DstMAC))]
            return ':'.join(f'{b:02x}' for b in mac_bytes)
        return ""
    
    @dst_mac.setter
    def dst_mac(self, value: str) -> None:
        if value:
            mac_bytes = [int(x, 16) for x in value.split(':')]
            hw_addr = HardwareAddr()
            for b in mac_bytes:
                hw_addr.append(b)
            self._config.DstMAC = hw_addr
    
    @property
    def src_ip(self) -> str:
        """Source IP address."""
        return self._config.SrcIP
    
    @src_ip.setter
    def src_ip(self, value: str) -> None:
        if value:
            # Validate IP address
            try:
                ipaddress.ip_address(value)
                self._config.SrcIP = value
            except ValueError:
                if value:  # Only raise if not empty string
                    raise ValueError(f"Invalid IP address: {value}")
        else:
            self._config.SrcIP = ""
    
    @property
    def dst_ip(self) -> str:
        """Destination IP address."""
        return self._config.DstIP
    
    @dst_ip.setter
    def dst_ip(self, value: str) -> None:
        if value:
            try:
                ipaddress.ip_address(value)
                self._config.DstIP = value
            except ValueError:
                if value:
                    raise ValueError(f"Invalid IP address: {value}")
        else:
            self._config.DstIP = ""
    
    @property
    def src_port(self) -> int:
        """Source UDP port."""
        return self._config.SrcPort
    
    @src_port.setter
    def src_port(self, value: int) -> None:
        if value and (not isinstance(value, int) or value < 0 or value > 65535):
            raise ValueError("Port must be between 0 and 65535")
        self._config.SrcPort = value
    
    @property
    def dst_port(self) -> int:
        """Destination UDP port."""
        return self._config.DstPort
    
    @dst_port.setter
    def dst_port(self, value: int) -> None:
        if value and (not isinstance(value, int) or value < 0 or value > 65535):
            raise ValueError("Port must be between 0 and 65535")
        self._config.DstPort = value
    
    @property
    def bpf_filter(self) -> str:
        """Berkeley Packet Filter expression."""
        return self._config.BPF
    
    @bpf_filter.setter
    def bpf_filter(self, value: str) -> None:
        self._config.BPF = value
        
    def _get_go_object(self) -> GoPacketConfig:
        """Get the underlying Go object."""
        return self._config


class DebugOptions:
    """
    Configuration for debug and logging options.
    """
    
    def __init__(self, enabled: bool = False, level: int = 0, logger: Optional[Logger] = None):
        """
        Initialize debug options.
        
        Args:
            enabled: Whether debugging is enabled
            level: Debug level (higher means more verbose)
            logger: Custom logger implementation
        """
        self._config = GoDebugOptions()
        self.enabled = enabled
        self.level = level
        if logger:
            self.logger = logger
    
    @property
    def enabled(self) -> bool:
        """Whether debug logging is enabled."""
        return self._config.Enabled
    
    @enabled.setter
    def enabled(self, value: bool) -> None:
        self._config.Enabled = value
    
    @property
    def level(self) -> int:
        """Debug verbosity level."""
        return self._config.Level
    
    @level.setter
    def level(self, value: int) -> None:
        if not isinstance(value, int) or value < 0:
            raise ValueError("Debug level must be a non-negative integer")
        self._config.Level = value
    
    @property
    def logger(self) -> Logger:
        """Custom logger implementation."""
        return self._config.Logger
    
    @logger.setter
    def logger(self, value: Logger) -> None:
        if not isinstance(value, GoClass):
            raise TypeError("Logger must be a valid Logger instance")
        self._config.Logger = value
        
    def _get_go_object(self) -> GoDebugOptions:
        """Get the underlying Go object."""
        return self._config


class MultiStreamConfig:
    """
    Configuration for multi-stream packet processing.
    """
    
    def __init__(
        self, 
        packet_workers: int = 4,
        stream_count: int = 1,
        channel_buffer_size: int = 1000,
        report_interval: int = 1000,
        enable_cpu_pinning: bool = False,
        disable_ordering: bool = False,
        turnstile_burst: int = 16,
        enable_metrics: bool = False,
        rate_limit: int = 0  # Added rate_limit parameter
    ):
        """
        Initialize multi-stream configuration.
        
        Args:
            packet_workers: Number of worker threads for packet processing
            stream_count: Number of parallel streams
            channel_buffer_size: Size of internal channel buffers
            report_interval: How often to report progress (packets)
            enable_cpu_pinning: Whether to pin workers to specific CPU cores
            disable_ordering: Whether to disable packet ordering
            turnstile_burst: Burst size for turnstile processing
            enable_metrics: Whether to collect performance metrics
            rate_limit: Rate limit in packets per second (0 = unlimited)
        """
        self._config = GoMultiStreamConfig()
        self.packet_workers = packet_workers
        self.stream_count = stream_count
        self.channel_buffer_size = channel_buffer_size 
        self.report_interval = report_interval       
        self.enable_cpu_pinning = enable_cpu_pinning
        self.disable_ordering = disable_ordering
        self.turnstile_burst = turnstile_burst
        self.enable_metrics = enable_metrics
        self.rate_limit = rate_limit
    
    @property
    def packet_workers(self) -> int:
        """Number of worker threads for packet processing."""
        return self._config.PacketWorkers
    
    @packet_workers.setter
    def packet_workers(self, value: int) -> None:
        if not isinstance(value, int) or value <= 0:
            raise ValueError("packet_workers must be a positive integer")
        self._config.PacketWorkers = value
    
    @property
    def stream_count(self) -> int:
        """Number of parallel streams."""
        return self._config.StreamCount
    
    @stream_count.setter
    def stream_count(self, value: int) -> None:
        if not isinstance(value, int) or value <= 0:
            raise ValueError("stream_count must be a positive integer")
        self._config.StreamCount = value
    
    @property
    def channel_buffer_size(self) -> int:
        """Size of internal channel buffers."""
        return self._config.ChannelBuffers
    
    @channel_buffer_size.setter
    def channel_buffer_size(self, value: int) -> None:
        if not isinstance(value, int) or value <= 0:
            raise ValueError("channel_buffer_size must be a positive integer")
        self._config.ChannelBuffers = value
    
    @property
    def report_interval(self) -> int:
        """How often to report progress (packets)."""
        return self._config.ReportInterval
    
    @report_interval.setter
    def report_interval(self, value: int) -> None:
        if not isinstance(value, int) or value < 0:
            raise ValueError("report_interval must be a non-negative integer")
        self._config.ReportInterval = value
    
    @property
    def enable_cpu_pinning(self) -> bool:
        """Whether to pin workers to specific CPU cores."""
        return self._config.EnableCPUPinning
    
    @enable_cpu_pinning.setter
    def enable_cpu_pinning(self, value: bool) -> None:
        self._config.EnableCPUPinning = value
    
    @property
    def disable_ordering(self) -> bool:
        """Whether to disable packet ordering."""
        return self._config.DisableOrdering
    
    @disable_ordering.setter
    def disable_ordering(self, value: bool) -> None:
        self._config.DisableOrdering = value
        
    @property
    def turnstile_burst(self) -> int:
        """Burst size for turnstile processing."""
        return self._config.TurnstileBurst
    
    @turnstile_burst.setter
    def turnstile_burst(self, value: int) -> None:
        if not isinstance(value, int) or value <= 0:
            raise ValueError("turnstile_burst must be a positive integer")
        self._config.TurnstileBurst = value
    
    @property
    def enable_metrics(self) -> bool:
        """Whether to collect performance metrics."""
        return self._config.EnableMetrics
    
    @enable_metrics.setter
    def enable_metrics(self, value: bool) -> None:
        self._config.EnableMetrics = value
    
    @property
    def rate_limit(self) -> int:
        """Rate limit in packets per second (0 = unlimited)."""
        return self._config.RateLimit
    
    @rate_limit.setter
    def rate_limit(self, value: int) -> None:
        if not isinstance(value, int) or value < 0:
            raise ValueError("rate_limit must be a non-negative integer")
        self._config.RateLimit = value
        
    def _get_go_object(self) -> GoMultiStreamConfig:
        """Get the underlying Go object."""
        return self._config


class Config:
    """
    Main configuration class combining packet and pcap settings.
    """
    
    def __init__(
        self,
        pcap: Optional[PcapConfig] = None,
        packet: Optional[PacketConfig] = None,
        debug: Optional[DebugOptions] = None
    ):
        """
        Initialize combined configuration.
        
        Args:
            pcap: Packet capture configuration
            packet: Packet header configuration
            debug: Debug and logging configuration
        """
        self._config = GoConfig()
        
        # Set defaults if not provided
        self._pcap = pcap or PcapConfig()
        self._packet = packet or PacketConfig()
        self._debug = debug or DebugOptions()
        
        # Set the underlying Go objects
        self._config.Pcap = self._pcap._get_go_object()
        self._config.Packet = self._packet._get_go_object()
        self._config.Debug = self._debug._get_go_object()
    
    @property
    def pcap(self) -> PcapConfig:
        """Packet capture configuration."""
        return self._pcap
    
    @pcap.setter
    def pcap(self, value: PcapConfig) -> None:
        if not isinstance(value, PcapConfig):
            raise TypeError("Expected PcapConfig instance")
        self._pcap = value
        self._config.Pcap = value._get_go_object()
    
    @property
    def packet(self) -> PacketConfig:
        """Packet header configuration."""
        return self._packet
    
    @packet.setter
    def packet(self, value: PacketConfig) -> None:
        if not isinstance(value, PacketConfig):
            raise TypeError("Expected PacketConfig instance")
        self._packet = value
        self._config.Packet = value._get_go_object()
    
    @property
    def debug(self) -> DebugOptions:
        """Debug and logging configuration."""
        return self._debug
    
    @debug.setter
    def debug(self, value: DebugOptions) -> None:
        if not isinstance(value, DebugOptions):
            raise TypeError("Expected DebugOptions instance")
        self._debug = value
        self._config.Debug = value._get_go_object()
    
    def enable_debug(self, level: int = 1) -> None:
        """
        Enable debug logging with specified verbosity.
        
        Args:
            level: Debug verbosity level
        """
        self._config.EnableDebug(level, False)
    
    def disable_debug(self) -> None:
        """Disable debug logging."""
        self._config.DisableDebug(False)
    
    def set_logger(self, logger: Logger) -> None:
        """
        Set a custom logger.
        
        Args:
            logger: Custom logger implementation
        """
        if not isinstance(logger, GoClass):
            raise TypeError("Logger must be a valid Logger instance")
        self._config.SetLogger(logger, False)
    
    def _get_go_object(self) -> GoConfig:
        """Get the underlying Go object."""
        return self._config


def create_default_config(
    interface: str,
    src_mac: str = "",
    dst_mac: str = "",
    src_ip: str = "",
    dst_ip: str = "",
    src_port: int = 0,
    dst_port: int = 0,
    bpf_filter: str = "",
    snap_len: int = 65535,
    promisc: bool = True,
    buffer_size: int = 4 * 1024 * 1024,
    immediate_mode: bool = True
) -> Config:
    """
    Create a default configuration with common settings.
    
    Args:
        interface: Network interface name
        src_mac: Source MAC address (format: "xx:xx:xx:xx:xx:xx")
        dst_mac: Destination MAC address (format: "xx:xx:xx:xx:xx:xx")
        src_ip: Source IP address
        dst_ip: Destination IP address
        src_port: Source UDP port
        dst_port: Destination UDP port
        bpf_filter: Berkeley Packet Filter string
        snap_len: Maximum number of bytes to capture per packet
        promisc: Enable promiscuous mode
        buffer_size: Size of the capture buffer in bytes
        immediate_mode: Enable immediate packet delivery
        
    Returns:
        Config: A fully configured Config object
    """
    # Use the Go function to create a default config
    go_config = NewDefaultConfig(
        interface, src_mac, dst_mac, src_ip, dst_ip, src_port, dst_port,
        bpf_filter, snap_len, promisc, buffer_size, immediate_mode
    )
    
    # Create our Python wrapper objects
    pcap_config = PcapConfig()
    pcap_config._config = go_config.Pcap
    
    packet_config = PacketConfig()
    packet_config._config = go_config.Packet
    
    debug_options = DebugOptions()
    debug_options._config = go_config.Debug
    
    # Create the main config
    config = Config(pcap_config, packet_config, debug_options)
    config._config = go_config
    
    return config


def create_default_multi_stream_config(
    packet_workers: int = 4,
    stream_count: int = 2,
    rate_limit: int = 0,
    channel_buffer_size: int = 1000,
    report_interval: int = 1000,
    enable_metrics: bool = True,
    disable_ordering: bool = False,
    enable_cpu_pinning: bool = False,
    turnstile_burst: int = 16
) -> MultiStreamConfig:
    """
    Create a default multi-stream configuration with sensible defaults.
    
    Args:
        packet_workers: Number of worker threads (default: 4)
        stream_count: Number of parallel streams (default: 2)
        rate_limit: Rate limit in packets per second (0 = unlimited)
        channel_buffer_size: Size of internal channel buffers (default: 1000)
        report_interval: How often to report progress in packets (default: 1000)
        enable_metrics: Whether to collect metrics (default: True)
        disable_ordering: Whether to disable packet ordering (default: False)
        enable_cpu_pinning: Whether to pin workers to CPU cores (default: False)
        turnstile_burst: Burst size for turnstile processing (default: 16)
        
    Returns:
        MultiStreamConfig: A configured MultiStreamConfig object
    """
    config = MultiStreamConfig(
        packet_workers=packet_workers,
        stream_count=stream_count,
        channel_buffer_size=channel_buffer_size,
        report_interval=report_interval,
        enable_cpu_pinning=enable_cpu_pinning,
        disable_ordering=disable_ordering,
        turnstile_burst=turnstile_burst,
        enable_metrics=enable_metrics,
        rate_limit=rate_limit
    )
    
    return config