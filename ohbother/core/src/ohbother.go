package ohbother

import (
	"ohbother/src/config"
	"ohbother/src/receive"
	"ohbother/src/transmit"
	"ohbother/src/utils"
)

// Re-export types from config
type (
	Config        = config.Config
	PacketConfig  = config.PacketConfig
	PcapConfig    = config.PcapConfig
	DebugOptions  = config.DebugOptions
	Logger        = config.Logger
	DefaultLogger = config.DefaultLogger
)

// Re-export config functions
var (
	NewDefaultConfig = config.NewDefaultConfig
	//NewMultiStreamConfig = transmit.NewMultiStreamConfig
	NewDefaultLogger = config.NewDefaultLogger
	LogDebug         = config.LogDebug
	LogInfo          = config.LogInfo
	LogWarn          = config.LogWarn
	LogError         = config.LogError
)

// Re-export types from transmit
type (
	MultiStreamSender = transmit.MultiStreamSender
	PacketSendResult  = transmit.PacketSendResult
	MultiStreamConfig = transmit.MultiStreamConfig
)

// Re-export types from receive
type (
	PacketReceiver           = receive.PacketReceiver
	ContinuousPacketReceiver = receive.ContinuousPacketReceiver
)

var (
	PacketReceiverByTime = receive.PacketReceiverByTime
)

// Re-export utils functions
var (
	ReconstructByteArrays = utils.ReconstructByteArrays
	StoreByteSlice        = utils.StoreByteSlice
	GetByteSlice          = utils.GetByteSlice
	DeleteByteSlice       = utils.DeleteByteSlice
	GetRegistryStats      = utils.GetRegistryStats
	ClearRegistry         = utils.ClearRegistry
)
