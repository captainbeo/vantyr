package model

import (
	"testing"

	"github.com/QuantumNous/new-api/common"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

// seedAvoidCache installs a channel cache for one group/model. Each entry is
// {id, priority}; weights are equal so the draw is uniform inside a tier.
func seedAvoidCache(t *testing.T, group, modelName string, channels [][2]int) {
	t.Helper()
	ids := make([]int, 0, len(channels))
	byID := make(map[int]*Channel, len(channels))
	for _, entry := range channels {
		priority := int64(entry[1])
		weight := uint(1)
		byID[entry[0]] = &Channel{Id: entry[0], Status: common.ChannelStatusEnabled, Priority: &priority, Weight: &weight}
		ids = append(ids, entry[0])
	}

	channelSyncLock.Lock()
	previousIDM, previousGroups := channelsIDM, group2model2channels
	previousCache := common.MemoryCacheEnabled
	channelsIDM = byID
	group2model2channels = map[string]map[string][]int{group: {modelName: ids}}
	common.MemoryCacheEnabled = true
	channelSyncLock.Unlock()

	t.Cleanup(func() {
		channelSyncLock.Lock()
		channelsIDM, group2model2channels = previousIDM, previousGroups
		common.MemoryCacheEnabled = previousCache
		channelSyncLock.Unlock()
	})
}

// drawIDs runs the selection many times and returns every id it produced.
func drawIDs(t *testing.T, group, modelName string, retry int, tried []int) map[int]int {
	t.Helper()
	seen := map[int]int{}
	for range 200 {
		channel, err := GetRandomSatisfiedChannelAvoiding(group, modelName, retry, nil, tried)
		require.NoError(t, err)
		require.NotNil(t, channel)
		seen[channel.Id]++
	}
	return seen
}

func TestGetRandomSatisfiedChannelAvoidingSkipsTriedInSameTier(t *testing.T) {
	// Two A6 pins at P20 behind Kiro at P30: the production shape once a model
	// has more than one active merchant.
	seedAvoidCache(t, "default", "claude-opus-5-5", [][2]int{{95, 30}, {47, 20}, {82, 20}})

	// Retry 2 clamps to the last tier. Upstream would hand back 47 about half
	// the time after 47 failed; avoiding must always pick 82.
	seen := drawIDs(t, "default", "claude-opus-5-5", 2, []int{95, 47})
	assert.Equal(t, map[int]int{82: 200}, seen)
}

func TestGetRandomSatisfiedChannelAvoidingFallsToNextTierWithUntried(t *testing.T) {
	seedAvoidCache(t, "default", "m", [][2]int{{1, 30}, {2, 20}, {3, 10}})

	// Retry 1 selects P20, whose only channel was tried: the highest tier
	// that still has an untried channel is P10.
	seen := drawIDs(t, "default", "m", 1, []int{1, 2})
	assert.Equal(t, map[int]int{3: 200}, seen)

	// Retry 1 selects P20 and it is untried: the retry index still decides.
	seen = drawIDs(t, "default", "m", 1, []int{1})
	assert.Equal(t, map[int]int{2: 200}, seen)

	// Retry 2 selects P10, which was tried; P30 has nothing left either, so
	// the highest untried tier is P20.
	seen = drawIDs(t, "default", "m", 2, []int{1, 3})
	assert.Equal(t, map[int]int{2: 200}, seen)
}

func TestGetRandomSatisfiedChannelAvoidingAllTriedKeepsUpstreamBehavior(t *testing.T) {
	seedAvoidCache(t, "default", "m", [][2]int{{1, 30}, {2, 20}, {3, 20}})

	// Every candidate tried: behave exactly like GetRandomSatisfiedChannel and
	// draw from the tier the retry index selects.
	seen := drawIDs(t, "default", "m", 1, []int{1, 2, 3})
	assert.Empty(t, seen[1])
	assert.Positive(t, seen[2])
	assert.Positive(t, seen[3])
}

func TestGetRandomSatisfiedChannelAvoidingNoTriedMatchesUpstream(t *testing.T) {
	seedAvoidCache(t, "default", "m", [][2]int{{1, 30}, {2, 20}})

	assert.Equal(t, map[int]int{1: 200}, drawIDs(t, "default", "m", 0, nil))
	assert.Equal(t, map[int]int{2: 200}, drawIDs(t, "default", "m", 1, nil))
	// The unchanged entry point is the no-tried case.
	channel, err := GetRandomSatisfiedChannel("default", "m", 1, nil)
	require.NoError(t, err)
	assert.Equal(t, 2, channel.Id)
}

func TestGetRandomSatisfiedChannelAvoidingSingleCandidate(t *testing.T) {
	seedAvoidCache(t, "default", "m", [][2]int{{7, 20}})

	// One candidate: it is returned even though it was tried, as upstream does.
	assert.Equal(t, map[int]int{7: 200}, drawIDs(t, "default", "m", 1, []int{7}))
}
