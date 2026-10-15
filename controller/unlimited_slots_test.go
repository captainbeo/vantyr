package controller

import (
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/QuantumNous/new-api/common"
	"github.com/QuantumNous/new-api/model"
	"github.com/glebarez/sqlite"
	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"gorm.io/gorm"
)

// TestGetUnlimitedUsageInfo pins the "Apply for Unlimited Usage" page data:
// remaining = capacity - active subscriptions, floored at 0, plus the
// requesting user's own active flag.
func TestGetUnlimitedUsageInfo(t *testing.T) {
	setupUnlimitedTestDB(t)

	oldCapacity := common.UnlimitedSlotsCapacity
	common.UnlimitedSlotsCapacity = 4
	defer func() { common.UnlimitedSlotsCapacity = oldCapacity }()

	gin.SetMode(gin.TestMode)
	recorder := httptest.NewRecorder()
	ctx, _ := gin.CreateTestContext(recorder)
	ctx.Request = httptest.NewRequest(http.MethodGet, "/api/user/unlimited/info", nil)
	ctx.Set("id", 42)

	GetUnlimitedUsageInfo(ctx)

	require.Equal(t, http.StatusOK, recorder.Code)

	var payload struct {
		Success bool `json:"success"`
		Data    struct {
			Capacity    int  `json:"capacity"`
			Active      int  `json:"active"`
			Remaining   int  `json:"remaining"`
			UserHasFlag bool `json:"user_has_active"`
		} `json:"data"`
	}
	require.NoError(t, common.Unmarshal(recorder.Body.Bytes(), &payload))
	require.True(t, payload.Success)

	// Two active subs in the fixture (user 42 and 51), capacity 4.
	assert.Equal(t, 4, payload.Data.Capacity)
	assert.Equal(t, 2, payload.Data.Active)
	assert.Equal(t, 2, payload.Data.Remaining)
	assert.True(t, payload.Data.UserHasFlag, "user 42 holds an active subscription in the fixture")
}

// TestGetUnlimitedUsageInfoFull pins the floor-at-zero behavior when more
// subscriptions exist than the configured capacity.
func TestGetUnlimitedUsageInfoFull(t *testing.T) {
	setupUnlimitedTestDB(t)

	oldCapacity := common.UnlimitedSlotsCapacity
	common.UnlimitedSlotsCapacity = 1
	defer func() { common.UnlimitedSlotsCapacity = oldCapacity }()

	gin.SetMode(gin.TestMode)
	recorder := httptest.NewRecorder()
	ctx, _ := gin.CreateTestContext(recorder)
	ctx.Request = httptest.NewRequest(http.MethodGet, "/api/user/unlimited/info", nil)
	ctx.Set("id", 42)

	GetUnlimitedUsageInfo(ctx)

	require.Equal(t, http.StatusOK, recorder.Code)

	var payload struct {
		Data struct {
			Remaining int `json:"remaining"`
		} `json:"data"`
	}
	require.NoError(t, common.Unmarshal(recorder.Body.Bytes(), &payload))
	assert.Equal(t, 0, payload.Data.Remaining, "remaining must floor at 0 when active > capacity")
}

func setupUnlimitedTestDB(t *testing.T) {
	t.Helper()
	oldDB := model.DB
	db, err := gorm.Open(sqlite.Open(":memory:"), &gorm.Config{})
	require.NoError(t, err)
	require.NoError(t, db.AutoMigrate(&model.User{}, &model.UserSubscription{}))
	model.DB = db
	common.SetDatabaseTypes(common.DatabaseTypeSQLite, common.DatabaseTypeSQLite)
	t.Cleanup(func() {
		model.DB = oldDB
		sqlDB, dbErr := db.DB()
		if dbErr == nil {
			require.NoError(t, sqlDB.Close())
		}
	})

	now := common.GetTimestamp()
	active := []model.UserSubscription{
		{UserId: 42, PlanId: 1, Status: "active", StartTime: now - 1000, EndTime: now + 100000, Source: "stripe"},
		{UserId: 51, PlanId: 1, Status: "active", StartTime: now - 2000, EndTime: now + 100000, Source: "stripe"},
		{UserId: 61, PlanId: 1, Status: "expired", StartTime: now - 200000, EndTime: now - 1000, Source: "stripe"},
	}
	for i := range active {
		require.NoError(t, model.DB.Create(&active[i]).Error)
	}
}
