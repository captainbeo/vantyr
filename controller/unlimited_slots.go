package controller

import (
	"net/http"

	"github.com/QuantumNous/new-api/common"
	"github.com/QuantumNous/new-api/model"
	"github.com/gin-gonic/gin"
)

// GetUnlimitedUsageInfo serves the "Apply for Unlimited Usage" page: how
// many unlimited-plan slots are taken and the configured total capacity.
// Active count comes from user_subscriptions (status active, not expired)
// across ALL plans that grant the unlimited group — the plan is
// admin-granted, so this number reflects granted slots only.
func GetUnlimitedUsageInfo(c *gin.Context) {
	userId := c.GetInt("id")

	now := common.GetTimestamp()
	var active int64
	if err := model.DB.Model(&model.UserSubscription{}).
		Where("status = ? AND end_time > ?", "active", now).
		Count(&active).Error; err != nil {
		common.ApiError(c, err)
		return
	}

	capacity := common.UnlimitedSlotsCapacity
	if capacity < 0 {
		capacity = 0
	}
	remaining := capacity - int(active)
	if remaining < 0 {
		remaining = 0
	}

	// Whether this user already holds an active unlimited subscription.
	hasActive, err := model.HasActiveUserSubscription(userId)
	if err != nil {
		hasActive = false
	}

	c.JSON(http.StatusOK, gin.H{
		"success": true,
		"data": gin.H{
			"capacity":         capacity,
			"active":           active,
			"remaining":        remaining,
			"user_has_active":  hasActive,
		},
	})
}
