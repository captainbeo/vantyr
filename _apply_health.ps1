$path = 'C:\Users\z\Documents\worktrees\commercial-mvp\service\commercial_channel_health.go'
$text = [IO.File]::ReadAllText($path)
$startMarker = '// ResolveCommercialChannelHealthPolicy reads the channel-owned reliability'
$endMarker = '// commercialHealthProbeLeaseSeconds projects'
$start = $text.IndexOf($startMarker)
$end = $text.IndexOf($endMarker)
if ($start -lt 0 -or $end -le $start) { throw 'resolver markers not found' }
$replacement = @'
type commercialChannelHealthPolicyRow struct {
	Version                 int64
	StreamMaxDurationMS     int
	NonstreamTotalTimeoutMS int
	WindowSeconds           int
	BucketSeconds           int
	DegradedErrorRateBPS    int
	OpenErrorRateBPS        int
	DegradedP95MS           int
	RecoveryP95MS           int
	MinimumSamples          int
	ConsecutiveFailureLimit int
	CooldownSeconds         int
	RecoverySuccesses       int
	LatencyBucketBoundsMS   string
}

// parseCommercialInt32ArrayText parses PostgreSQL's text representation for a
// one-dimensional integer array without relying on the driver's array scanner.
func parseCommercialInt32ArrayText(value string) ([]int32, error) {
	value = strings.TrimSpace(value)
	if len(value) < 2 || value[0] != '{' || value[len(value)-1] != '}' {
		return nil, ErrCommercialChannelHealthInvalid
	}
	contents := strings.TrimSpace(value[1 : len(value)-1])
	if contents == "" {
		return []int32{}, nil
	}
	parts := strings.Split(contents, ",")
	if len(parts) > commercialHealthMaxBounds {
		return nil, ErrCommercialChannelHealthInvalid
	}
	parsed := make([]int32, len(parts))
	for index, part := range parts {
		part = strings.TrimSpace(part)
		if part == "" {
			return nil, ErrCommercialChannelHealthInvalid
		}
		number, err := strconv.ParseInt(part, 10, 32)
		if err != nil {
			return nil, ErrCommercialChannelHealthInvalid
		}
		parsed[index] = int32(number)
	}
	return parsed, nil
}

// ResolveCommercialChannelHealthPolicy reads the channel-owned reliability
// policy. A missing or malformed policy keeps static routing in place rather
// than inventing defaults.
func ResolveCommercialChannelHealthPolicy(channel *model.Channel) (CommercialChannelHealthPolicy, error) {
	if channel == nil || !channel.CommercialChannel || channel.ReliabilityPolicyID == nil || model.DB == nil || channel.ConfigVersion <= 0 {
		return CommercialChannelHealthPolicy{}, ErrCommercialChannelHealthUnavailable
	}
	// Select only the scalar fields used by the health evaluator. The pgx
	// database/sql path can expose integer[] values as text, which cannot be
	// scanned directly into pgtype.FlatArray; cast the bounds to text and parse
	// the bounded PostgreSQL representation explicitly.
	var row commercialChannelHealthPolicyRow
	if err := model.DB.Table("channel_reliability_policies").
		Select(
			"version, stream_max_duration_ms, nonstream_total_timeout_ms, window_seconds, bucket_seconds,"+
				"degraded_error_rate_bps, open_error_rate_bps, degraded_p95_ms, recovery_p95_ms,"+
				"minimum_samples, consecutive_failure_limit, cooldown_seconds, recovery_successes,"+
				"CAST(latency_bucket_bounds_ms AS TEXT) AS latency_bucket_bounds_ms",
		).
		Where("id = ? AND channel_id = ?", *channel.ReliabilityPolicyID, channel.Id).
		Take(&row).Error; err != nil {
		return CommercialChannelHealthPolicy{}, ErrCommercialChannelHealthUnavailable
	}
	bounds, err := parseCommercialInt32ArrayText(row.LatencyBucketBoundsMS)
	if err != nil {
		return CommercialChannelHealthPolicy{}, ErrCommercialChannelHealthCorrupt
	}
	policy := CommercialChannelHealthPolicy{
		WindowSeconds:           row.WindowSeconds,
		BucketSeconds:           row.BucketSeconds,
		DegradedErrorRateBPS:    row.DegradedErrorRateBPS,
		OpenErrorRateBPS:        row.OpenErrorRateBPS,
		DegradedP95MS:           row.DegradedP95MS,
		RecoveryP95MS:           row.RecoveryP95MS,
		MinimumSamples:          row.MinimumSamples,
		ConsecutiveFailureLimit: row.ConsecutiveFailureLimit,
		CooldownSeconds:         row.CooldownSeconds,
		RecoverySuccesses:       row.RecoverySuccesses,
		LatencyBucketBoundsMS:   bounds,
		Version:                 row.Version,
	}
	policy.ProbeLeaseSeconds = commercialHealthProbeLeaseSeconds(row.StreamMaxDurationMS, row.NonstreamTotalTimeoutMS)
	if err := validateCommercialChannelHealthPolicy(policy); err != nil {
		return CommercialChannelHealthPolicy{}, ErrCommercialChannelHealthCorrupt
	}
	return policy, nil
}

'@
$text = $text.Substring(0, $start) + $replacement + $text.Substring($end)
[IO.File]::WriteAllText($path, $text, (New-Object Text.UTF8Encoding($false)))