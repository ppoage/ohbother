package ohbother

// PacketSendResult represents the result of sending a packet
type PacketSendResult struct {
	Index      int     // Original position in sequence
	TotalCount int     // Total packets in sequence
	Elapsed    float64 // Elapsed time in seconds
	Error      error   // Any error that occurred
}
