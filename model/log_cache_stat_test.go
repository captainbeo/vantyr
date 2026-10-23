package model

import (
	"fmt"
	"strings"
	"testing"

	"github.com/QuantumNous/new-api/common"
	"github.com/glebarez/sqlite"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"gorm.io/gorm"
)

func setupCacheStatTestDB(t *testing.T) {
	t.Helper()
	previousDB, previousLogDB := DB, LOG_DB
	previousMainDatabaseType, previousLogDatabaseType := common.MainDatabaseType(), common.LogDatabaseType()
	common.SetDatabaseTypes(common.DatabaseTypeSQLite, common.DatabaseTypeSQLite)
	dsn := fmt.Sprintf("file:%s?mode=memory&cache=shared", strings.ReplaceAll(t.Name(), "/", "_"))
	db, err := gorm.Open(sqlite.Open(dsn), &gorm.Config{})
	require.NoError(t, err)
	DB, LOG_DB = db, db
	require.NoError(t, db.AutoMigrate(&Log{}))
	sqlDB, err := db.DB()
	require.NoError(t, err)
	sqlDB.SetMaxOpenConns(4)
	t.Cleanup(func() {
		DB, LOG_DB = previousDB, previousLogDB
		common.SetDatabaseTypes(previousMainDatabaseType, previousLogDatabaseType)
		_ = sqlDB.Close()
	})
}

func TestSumUserCacheStats(t *testing.T) {
	setupCacheStatTestDB(t)

	const userId = 42
	otherUserId := 7
	base := int64(1_760_000_000)

	logs := []*Log{
		// In-window consume logs for the target user.
		{UserId: userId, Username: "cache-user", CreatedAt: base + 10, Type: LogTypeConsume, ModelName: "claude-fable-5", PromptTokens: 900, Other: `{"cache_tokens": 100}`},
		{UserId: userId, Username: "cache-user", CreatedAt: base + 20, Type: LogTypeConsume, ModelName: "claude-fable-5", PromptTokens: 50, Other: `{"cache_tokens": 950}`},
		// A consume log with no cache tokens recorded.
		{UserId: userId, Username: "cache-user", CreatedAt: base + 30, Type: LogTypeConsume, ModelName: "claude-fable-5", PromptTokens: 300, Other: `{}`},
		// Malformed JSON in other must count as zero, not fail the query.
		{UserId: userId, Username: "cache-user", CreatedAt: base + 40, Type: LogTypeConsume, ModelName: "claude-fable-5", PromptTokens: 10, Other: `not-json`},
		// Wrong type (not consume): excluded.
		{UserId: userId, Username: "cache-user", CreatedAt: base + 50, Type: LogTypeManage, ModelName: "claude-fable-5", PromptTokens: 777, Other: `{"cache_tokens": 777}`},
		// Outside the window: excluded.
		{UserId: userId, Username: "cache-user", CreatedAt: base - 100, Type: LogTypeConsume, ModelName: "claude-fable-5", PromptTokens: 888, Other: `{"cache_tokens": 888}`},
		// Another user's logs: excluded.
		{UserId: otherUserId, Username: "other-user", CreatedAt: base + 60, Type: LogTypeConsume, ModelName: "claude-fable-5", PromptTokens: 999, Other: `{"cache_tokens": 999}`},
	}
	for _, l := range logs {
		require.NoError(t, LOG_DB.Create(l).Error)
	}

	cacheTokens, promptTokens, err := SumUserCacheStats(userId, base, base+100, "", "", "")
	require.NoError(t, err)
	assert.EqualValues(t, 100+950, cacheTokens)
	assert.EqualValues(t, 900+50+300+10, promptTokens)

	// Model filter narrows the aggregation.
	cacheTokens, promptTokens, err = SumUserCacheStats(userId, base, base+100, "nonexistent-model", "", "")
	require.NoError(t, err)
	assert.Zero(t, cacheTokens)
	assert.Zero(t, promptTokens)

	// Empty result set yields zeros, not an error.
	cacheTokens, promptTokens, err = SumUserCacheStats(userId, base+1000, base+2000, "", "", "")
	require.NoError(t, err)
	assert.Zero(t, cacheTokens)
	assert.Zero(t, promptTokens)
}
