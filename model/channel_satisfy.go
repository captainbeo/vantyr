package model

import (
	"slices"

	"github.com/QuantumNous/new-api/common"
	"github.com/QuantumNous/new-api/dto"
	"github.com/QuantumNous/new-api/setting/ratio_setting"
)

// IsChannelInTopPriorityTier (Vantyr fork, 2026-10-27) reports whether
// channelID is in the highest priority tier among the enabled channels that
// serve this group and model under the request's filters. Session affinity
// uses it so a session is never held on a fallback tier: one failed request on
// the primary used to rebind the session to the backup, and every later
// success there refreshed the binding, so the session never returned (Kiro
// sessions stuck on A6, 2026-10-27). It reports false only when an enabled
// channel with a higher priority is known; anything it cannot compare
// (memory cache off, no candidates, unknown channel) reports true.
func IsChannelInTopPriorityTier(group string, modelName string, channelID int, filters []dto.ChannelFilter) bool {
	if !common.MemoryCacheEnabled || group == "" || modelName == "" || channelID <= 0 {
		return true
	}

	channelSyncLock.RLock()
	defer channelSyncLock.RUnlock()

	channel, ok := channelsIDM[channelID]
	if !ok {
		return true
	}
	ids, _ := filterCandidateIDs(group2model2channels[group][modelName], modelName, filters)
	if len(ids) == 0 {
		normalized := ratio_setting.RoutingMatchModelName(modelName)
		ids, _ = filterCandidateIDs(group2model2channels[group][normalized], modelName, filters)
	}
	for _, id := range ids {
		if candidate, ok := channelsIDM[id]; ok && candidate.GetPriority() > channel.GetPriority() {
			return false
		}
	}
	return true
}

func IsChannelEnabledForGroupModel(group string, modelName string, channelID int) bool {
	if group == "" || modelName == "" || channelID <= 0 {
		return false
	}
	if !common.MemoryCacheEnabled {
		return isChannelEnabledForGroupModelDB(group, modelName, channelID)
	}

	channelSyncLock.RLock()
	defer channelSyncLock.RUnlock()

	if group2model2channels == nil {
		return false
	}

	if isChannelIDInList(group2model2channels[group][modelName], channelID) {
		return true
	}
	normalized := ratio_setting.RoutingMatchModelName(modelName)
	if normalized != "" && normalized != modelName {
		return isChannelIDInList(group2model2channels[group][normalized], channelID)
	}
	return false
}

func IsChannelEnabledForAnyGroupModel(groups []string, modelName string, channelID int) bool {
	if len(groups) == 0 {
		return false
	}
	for _, g := range groups {
		if IsChannelEnabledForGroupModel(g, modelName, channelID) {
			return true
		}
	}
	return false
}

func isChannelEnabledForGroupModelDB(group string, modelName string, channelID int) bool {
	var count int64
	err := DB.Model(&Ability{}).
		Where(commonGroupCol+" = ? and model = ? and channel_id = ? and enabled = ?", group, modelName, channelID, true).
		Count(&count).Error
	if err == nil && count > 0 {
		return true
	}
	normalized := ratio_setting.RoutingMatchModelName(modelName)
	if normalized == "" || normalized == modelName {
		return false
	}
	count = 0
	err = DB.Model(&Ability{}).
		Where(commonGroupCol+" = ? and model = ? and channel_id = ? and enabled = ?", group, normalized, channelID, true).
		Count(&count).Error
	return err == nil && count > 0
}

func isChannelIDInList(list []int, channelID int) bool {
	return slices.Contains(list, channelID)
}
