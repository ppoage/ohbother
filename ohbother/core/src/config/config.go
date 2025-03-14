package config

import (
	"fmt"
	"net"
	"time"

	"github.com/gopacket/gopacket/pcap"
)

// Config holds both the packet header settings and the pcap settings.
type Config struct {
	Pcap   *PcapConfig
	Packet *PacketConfig
	Debug  DebugOptions // Add this field
}

// PacketConfig holds header information for UDP packets.
type PacketConfig struct {
	SrcMAC  net.HardwareAddr // source MAC address
	DstMAC  net.HardwareAddr // destination MAC address
	SrcIP   string           // source IP (IPv4)
	DstIP   string           // destination IP (IPv4)
	SrcPort int              // source UDP port
	DstPort int              // destination UDP port
	BPF     string           // optional BPF filter (for receive)
}

// PcapConfig holds additional settings for pcap handles.
type PcapConfig struct {
	Iface         string        // network interface (e.g., "en0")
	SnapLen       int32         // snapshot length in bytes
	Promisc       bool          // promiscuous mode
	Timeout       time.Duration // read timeout
	BufferSize    int           // capture buffer size in bytes
	ImmediateMode bool          // immediate mode for low latency
}

// Define a debug options struct
type DebugOptions struct {
	Enabled bool   // Master switch for debug output
	Level   int    // 0=off, 1=errors, 2=warnings, 3=info, 4=verbose
	Logger  Logger // Interface for logging
}

// Define a Logger interface
type Logger interface {
	Debug(format string, args ...interface{})
	Info(format string, args ...interface{})
	Warn(format string, args ...interface{})
	Error(format string, args ...interface{})
}

// Implement a default logger that has a reference to its parent Config
type DefaultLogger struct {
	parentConfig *Config
}

// NewDefaultLogger creates a logger with a reference to its parent Config
func NewDefaultLogger(cfg *Config) *DefaultLogger {
	return &DefaultLogger{
		parentConfig: cfg,
	}
}

func (l *DefaultLogger) Debug(format string, args ...interface{}) {
	if l.parentConfig.Debug.Enabled && l.parentConfig.Debug.Level >= 4 {
		if len(args) > 0 {
			fmt.Printf("[DEBUG] "+format+"\n", args...)
		} else {
			fmt.Printf("[DEBUG] %s\n", format)
		}
	}
}

func (l *DefaultLogger) Info(format string, args ...interface{}) {
	if l.parentConfig.Debug.Enabled && l.parentConfig.Debug.Level >= 3 {
		if len(args) > 0 {
			fmt.Printf("[INFO] "+format+"\n", args...)
		} else {
			fmt.Printf("[INFO] %s\n", format)
		}
	}
}

func (l *DefaultLogger) Warn(format string, args ...interface{}) {
	if l.parentConfig.Debug.Enabled && l.parentConfig.Debug.Level >= 2 {
		if len(args) > 0 {
			fmt.Printf("[WARN] "+format+"\n", args...)
		} else {
			fmt.Printf("[WARN] %s\n", format)
		}
	}
}

func (l *DefaultLogger) Error(format string, args ...interface{}) {
	if l.parentConfig.Debug.Enabled && l.parentConfig.Debug.Level >= 1 {
		if len(args) > 0 {
			fmt.Printf("[ERROR] "+format+"\n", args...)
		} else {
			fmt.Printf("[ERROR] %s\n", format)
		}
	}
}

// NewDefaultConfig creates a new Config using the provided parameters.
// The iface is set only once under the PcapConfig.
func NewDefaultConfig(iface, srcMAC, dstMAC, srcIP, dstIP string, srcPort, dstPort int, bpf string, SnapLen int, Promisc bool, BufferSize int, ImmediateMode bool) (*Config, error) {
	smac, err := net.ParseMAC(srcMAC)
	if err != nil {
		return nil, fmt.Errorf("invalid source MAC: %v", err)
	}
	dmac, err := net.ParseMAC(dstMAC)
	if err != nil {
		return nil, fmt.Errorf("invalid destination MAC: %v", err)
	}
	if net.ParseIP(srcIP) == nil {
		return nil, fmt.Errorf("invalid source IP")
	}
	if net.ParseIP(dstIP) == nil {
		return nil, fmt.Errorf("invalid destination IP")
	}

	cfg := &Config{
		Packet: &PacketConfig{
			SrcMAC:  smac,
			DstMAC:  dmac,
			SrcIP:   srcIP,
			DstIP:   dstIP,
			SrcPort: srcPort,
			DstPort: dstPort,
			BPF:     bpf,
		},
		Pcap: &PcapConfig{
			Iface:         iface,
			SnapLen:       65536,
			Promisc:       true,
			Timeout:       pcap.BlockForever,
			BufferSize:    2 * 1024 * 1024, // 4MB 2_097_152
			ImmediateMode: true,
		},
		Debug: DebugOptions{
			Enabled: false,
			Level:   0,
			// We'll set the Logger later
		},
	}

	// Now create the logger with a reference to the config
	cfg.Debug.Logger = NewDefaultLogger(cfg)

	return cfg, nil
}

// Level 0: Off (no debug output)
// Level 1: Errors only
// Level 2: Warnings and errors
// Level 3: Info, warnings, and errors
// Level 4: Verbose (debug, info, warnings, and errors)
func (cfg *Config) EnableDebug(level int) {
	cfg.Debug.Enabled = true
	cfg.Debug.Level = level

	// Update global debug configuration
	GlobalDebug.Enabled = true
	GlobalDebug.Level = level
	GlobalDebug.Logger = cfg.Debug.Logger

	// Log the change at level 1 (errors) so we can see it even with minimal logging
	if level >= 1 {
		fmt.Printf("[CONFIG] Debug level set to %d\n", level)
	}
}

func (cfg *Config) DisableDebug() {
	cfg.Debug.Enabled = false
}

func (cfg *Config) SetLogger(logger Logger) {
	cfg.Debug.Logger = logger
}

// Add to config.go
var GlobalDebug struct {
	Enabled bool
	Level   int
	Logger  Logger
}

// Add to config.go
func LogDebug(format string, args ...interface{}) {
	if GlobalDebug.Enabled && GlobalDebug.Level >= 4 {
		fmt.Printf("[DEBUG] "+format+"\n", args...)
	}
}

func LogInfo(format string, args ...interface{}) {
	if GlobalDebug.Enabled && GlobalDebug.Level >= 3 {
		fmt.Printf("[INFO] "+format+"\n", args...)
	}
}

func LogWarn(format string, args ...interface{}) {
	if GlobalDebug.Enabled && GlobalDebug.Level >= 2 {
		fmt.Printf("[WARN] "+format+"\n", args...)
	}
}

func LogError(format string, args ...interface{}) {
	if GlobalDebug.Enabled && GlobalDebug.Level >= 1 {
		fmt.Printf("[ERROR] "+format+"\n", args...)
	}
}
