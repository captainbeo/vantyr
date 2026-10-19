package service

import (
	"fmt"
	"strings"
	"testing"

	"github.com/QuantumNous/new-api/common"
	"github.com/QuantumNous/new-api/model"
	"github.com/glebarez/sqlite"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"gorm.io/gorm"
)

func setupGroupCatalogTestDB(t *testing.T) *gorm.DB {
	t.Helper()
	originalDB := model.DB
	originalMain, originalLog := common.MainDatabaseType(), common.LogDatabaseType()
	common.SetDatabaseTypes(common.DatabaseTypeSQLite, common.DatabaseTypeSQLite)
	dsn := fmt.Sprintf("file:%s?mode=memory&cache=shared", strings.ReplaceAll(t.Name(), "/", "_"))
	db, err := gorm.Open(sqlite.Open(dsn), &gorm.Config{})
	require.NoError(t, err)
	require.NoError(t, db.AutoMigrate(&model.Ability{}, &model.Model{}))
	model.DB = db
	model.InitColumnNamesForTest()
	t.Cleanup(func() {
		model.DB = originalDB
		common.SetDatabaseTypes(originalMain, originalLog)
		model.InitColumnNamesForTest()
		sqlDB, err := db.DB()
		if err == nil {
			_ = sqlDB.Close()
		}
	})
	return db
}

// createCatalogModel writes a metadata row. The Status gorm default:1 tag
// turns a zero Status into 1 on Create, so the row is finalized via Updates,
// mirroring Model.Insert.
func createCatalogModel(t *testing.T, db *gorm.DB, name string, status, nameRule int) {
	t.Helper()
	record := model.Model{ModelName: name, Status: status, NameRule: nameRule}
	require.NoError(t, db.Create(&record).Error)
	require.NoError(t, db.Model(&model.Model{}).Where("id = ?", record.Id).
		Updates(map[string]any{"status": status, "name_rule": nameRule}).Error)
}

func TestGetGroupsEnabledModelsHidesDisabledCatalogModels(t *testing.T) {
	db := setupGroupCatalogTestDB(t)
	require.NoError(t, db.Create(&[]model.Ability{
		{Group: "default", Model: "zz-catalog-alias", ChannelId: 1, Enabled: true},
		{Group: "default", Model: "zz-catalog-plain", ChannelId: 1, Enabled: true},
		{Group: "vip", Model: "zz-catalog-vip-alias", ChannelId: 2, Enabled: true},
	}).Error)
	createCatalogModel(t, db, "zz-catalog-alias", 0, model.NameRuleExact)
	createCatalogModel(t, db, "zz-catalog-vip-alias", 0, model.NameRuleExact)

	models := GetGroupsEnabledModels([]string{"default"})
	assert.ElementsMatch(t, []string{"zz-catalog-plain"}, models)

	vipModels := GetGroupsEnabledModels([]string{"vip"})
	assert.Empty(t, vipModels)
}

func TestGetGroupsEnabledModelsKeepsEnabledAndUnlistedModels(t *testing.T) {
	db := setupGroupCatalogTestDB(t)
	require.NoError(t, db.Create(&[]model.Ability{
		{Group: "default", Model: "zz-catalog-enabled-meta", ChannelId: 1, Enabled: true},
		{Group: "default", Model: "zz-catalog-no-meta", ChannelId: 1, Enabled: true},
		{Group: "default", Model: "zz-catalog-prefix-hidden", ChannelId: 1, Enabled: true},
	}).Error)
	createCatalogModel(t, db, "zz-catalog-enabled-meta", 1, model.NameRuleExact)
	createCatalogModel(t, db, "zz-catalog-prefix", 0, model.NameRulePrefix)

	models := GetGroupsEnabledModels([]string{"default"})
	assert.ElementsMatch(t, []string{"zz-catalog-enabled-meta", "zz-catalog-no-meta"}, models)
}
