package model

import (
	"fmt"
	"testing"
	"time"

	"github.com/QuantumNous/new-api/common"
	"github.com/QuantumNous/new-api/setting/operation_setting"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"gorm.io/gorm"
)

// referralTestOptions snapshots and restores every global the referral paths
// touch, so tests cannot leak option state into each other.
type referralTestOptions struct {
	quotaForNewUser        int
	quotaForInviter        int
	quotaForInvitee        int
	quotaForInviterTopUp   int
	affTopUpMinAmount      int
	complianceConfirmed    bool
	complianceTermsVersion string
}

func patchReferralTestOptions(t *testing.T, mutate func(*referralTestOptions)) {
	t.Helper()
	previous := referralTestOptions{
		quotaForNewUser:        common.QuotaForNewUser,
		quotaForInviter:        common.QuotaForInviter,
		quotaForInvitee:        common.QuotaForInvitee,
		quotaForInviterTopUp:   common.QuotaForInviterTopUp,
		affTopUpMinAmount:      common.AffTopUpMinAmount,
		complianceConfirmed:    operation_setting.GetPaymentSetting().ComplianceConfirmed,
		complianceTermsVersion: operation_setting.GetPaymentSetting().ComplianceTermsVersion,
	}
	patched := previous
	mutate(&patched)
	common.QuotaForNewUser = patched.quotaForNewUser
	common.QuotaForInviter = patched.quotaForInviter
	common.QuotaForInvitee = patched.quotaForInvitee
	common.QuotaForInviterTopUp = patched.quotaForInviterTopUp
	common.AffTopUpMinAmount = patched.affTopUpMinAmount
	setting := operation_setting.GetPaymentSetting()
	setting.ComplianceConfirmed = patched.complianceConfirmed
	setting.ComplianceTermsVersion = patched.complianceTermsVersion
	t.Cleanup(func() {
		common.QuotaForNewUser = previous.quotaForNewUser
		common.QuotaForInviter = previous.quotaForInviter
		common.QuotaForInvitee = previous.quotaForInvitee
		common.QuotaForInviterTopUp = previous.quotaForInviterTopUp
		common.AffTopUpMinAmount = previous.affTopUpMinAmount
		setting.ComplianceConfirmed = previous.complianceConfirmed
		setting.ComplianceTermsVersion = previous.complianceTermsVersion
	})
}

func enableReferralTestDefaults(t *testing.T) {
	t.Helper()
	patchReferralTestOptions(t, func(o *referralTestOptions) {
		o.complianceConfirmed = true
		o.complianceTermsVersion = operation_setting.CurrentComplianceTermsVersion
	})
}

func createReferralInviter(t *testing.T, affCode string) *User {
	t.Helper()
	inviter := &User{Username: "inviter-" + affCode, Password: "password", AffCode: affCode, AffQuota: 0, AffHistoryQuota: 0}
	if affCode == "" {
		// aff_code is unique; distinct placeholder per inviter.
		inviter.AffCode = fmt.Sprintf("inv%d", time.Now().UnixNano())
	}
	require.NoError(t, DB.Create(inviter).Error)
	return inviter
}

func TestCreateTelegramUserWithTxPersistsInviterWithoutTrial(t *testing.T) {
	truncateTables(t)
	enableReferralTestDefaults(t)
	patchReferralTestOptions(t, func(o *referralTestOptions) {
		o.quotaForNewUser = 500000
	})

	inviter := createReferralInviter(t, "inv1")
	var user *User
	require.NoError(t, DB.Transaction(func(tx *gorm.DB) error {
		var err error
		user, _, err = CreateTelegramUserWithTx(tx, "777001", "tg_user", "TG User", inviter.Id, false)
		return err
	}))

	require.NotNil(t, user)
	assert.NotZero(t, user.Id)
	assert.Equal(t, "777001", user.TelegramId)
	assert.Equal(t, inviter.Id, user.InviterId)
	assert.Equal(t, common.RoleCommonUser, user.Role)
	assert.Equal(t, common.UserStatusEnabled, user.Status)
	assert.NotEmpty(t, user.AffCode)
	assert.Zero(t, referralTestStoredQuota(t, user.Id), "trial credit is granted on login after membership, not at creation")
	assert.False(t, user.TelegramTrialCredited)

	var claim ExternalIdentityClaim
	require.NoError(t, DB.Where("provider = ? AND subject = ?", ExternalIdentityProviderTelegram, "777001").First(&claim).Error)
	assert.Equal(t, user.Id, claim.UserId)

	// The inviter reward is paid post-commit by FinalizeOAuthUserCreation in
	// the controller; this test verifies the persisted referral link only.
	user.FinalizeOAuthUserCreation(inviter.Id)
	var reloadedInviter User
	require.NoError(t, DB.First(&reloadedInviter, inviter.Id).Error)
	assert.Equal(t, inviter.Id, reloadedInviter.Id)
}

func referralTestStoredQuota(t *testing.T, userId int) int {
	t.Helper()
	var stored User
	require.NoError(t, DB.First(&stored, userId).Error)
	return stored.Quota
}

func TestCreateTelegramUserWithTxGrantTrialFlagAwardsCredit(t *testing.T) {
	truncateTables(t)
	enableReferralTestDefaults(t)
	patchReferralTestOptions(t, func(o *referralTestOptions) {
		o.quotaForNewUser = 500000
	})

	var user *User
	var credit int
	require.NoError(t, DB.Transaction(func(tx *gorm.DB) error {
		var err error
		user, credit, err = CreateTelegramUserWithTx(tx, "777002", "tg_user_2", "TG Two", 0, true)
		return err
	}))
	assert.Equal(t, 500000, credit)
	assert.Equal(t, 500000, referralTestStoredQuota(t, user.Id))

	// A rolled-back transaction must leave neither the user nor the credit.
	err := DB.Transaction(func(tx *gorm.DB) error {
		var err error
		_, _, err = CreateTelegramUserWithTx(tx, "777003", "tg_user_3", "TG Three", 0, true)
		if err != nil {
			return err
		}
		return gorm.ErrRecordNotFound // force rollback
	})
	assert.Error(t, err)
	var count int64
	require.NoError(t, DB.Model(&User{}).Where("telegram_id = ?", "777003").Count(&count).Error)
	assert.Zero(t, count)
	var claims int64
	require.NoError(t, DB.Model(&ExternalIdentityClaim{}).Where("subject = ?", "777003").Count(&claims).Error)
	assert.Zero(t, claims)
}

func TestGrantTelegramTrialWithTxIsOncePerUserAndRetryable(t *testing.T) {
	truncateTables(t)
	enableReferralTestDefaults(t)
	patchReferralTestOptions(t, func(o *referralTestOptions) {
		o.quotaForNewUser = 500000
	})

	user := &User{Username: "trial-retry", Password: "password", AffCode: "trial-retry", TelegramId: "777010"}
	require.NoError(t, DB.Create(user).Error)

	// First grant pays.
	var credit int
	require.NoError(t, DB.Transaction(func(tx *gorm.DB) error {
		var err error
		credit, err = GrantTelegramTrialWithTx(tx, user.Id)
		return err
	}))
	assert.Equal(t, 500000, credit)
	assert.Equal(t, 500000, referralTestStoredQuota(t, user.Id))

	// Second grant (e.g. login again after leaving and rejoining) pays nothing.
	require.NoError(t, DB.Transaction(func(tx *gorm.DB) error {
		var err error
		credit, err = GrantTelegramTrialWithTx(tx, user.Id)
		return err
	}))
	assert.Zero(t, credit)
	assert.Equal(t, 500000, referralTestStoredQuota(t, user.Id))

	// Unbinding and rebinding a different Telegram account does not re-earn
	// the trial: the marker is per user, not per Telegram identity.
	require.NoError(t, DB.Transaction(func(tx *gorm.DB) error {
		return ReleaseExternalIdentityWithTx(tx, ExternalIdentityProviderTelegram, user.Id)
	}))
	require.NoError(t, DB.Transaction(func(tx *gorm.DB) error {
		var err error
		credit, err = GrantTelegramTrialWithTx(tx, user.Id)
		return err
	}))
	assert.Zero(t, credit)
}

func TestCreateTelegramUserWithTxRejectsDuplicateTelegramAccount(t *testing.T) {
	truncateTables(t)
	enableReferralTestDefaults(t)

	existing := &User{Username: "tg-existing", Password: "password", TelegramId: "777004"}
	require.NoError(t, DB.Create(existing).Error)
	require.NoError(t, DB.Transaction(func(tx *gorm.DB) error {
		return ClaimExternalIdentityWithTx(tx, ExternalIdentityProviderTelegram, "777004", existing.Id)
	}))

	err := DB.Transaction(func(tx *gorm.DB) error {
		_, _, err := CreateTelegramUserWithTx(tx, "777004", "tg_user_4", "TG Four", 0, true)
		return err
	})
	assert.ErrorIs(t, err, ErrExternalIdentityAlreadyClaimed)
}

func TestCreateTelegramUserWithTxSkipsCreditWhenDisabled(t *testing.T) {
	truncateTables(t)
	enableReferralTestDefaults(t)
	patchReferralTestOptions(t, func(o *referralTestOptions) {
		o.quotaForNewUser = 0
	})

	var user *User
	require.NoError(t, DB.Transaction(func(tx *gorm.DB) error {
		var err error
		user, _, err = CreateTelegramUserWithTx(tx, "777005", "tg_user_5", "TG Five", 0, true)
		return err
	}))
	assert.Zero(t, referralTestStoredQuota(t, user.Id))
}

func TestMaybeGrantAffTopUpBonusPaysInviterOnce(t *testing.T) {
	truncateTables(t)
	enableReferralTestDefaults(t)
	patchReferralTestOptions(t, func(o *referralTestOptions) {
		o.quotaForInviterTopUp = 1500000
		o.affTopUpMinAmount = 20
	})

	inviter := createReferralInviter(t, "inv2")
	referred := &User{Username: "referred-one", Password: "password", InviterId: inviter.Id, AffCode: "referred-one"}
	require.NoError(t, DB.Create(referred).Error)

	var inviterId, bonus int
	require.NoError(t, DB.Transaction(func(tx *gorm.DB) error {
		var err error
		inviterId, bonus, err = maybeGrantAffTopUpBonus(tx, referred.Id, 20*500000)
		return err
	}))
	assert.Equal(t, inviter.Id, inviterId)
	assert.Equal(t, 1500000, bonus)

	var updated User
	require.NoError(t, DB.First(&updated, inviter.Id).Error)
	assert.Equal(t, 1500000, updated.AffQuota)
	assert.Equal(t, 1500000, updated.AffHistoryQuota)
	assert.Equal(t, 0, updated.AffCount, "aff_count counts registrations, not top-up bonuses")

	var marked User
	require.NoError(t, DB.First(&marked, referred.Id).Error)
	assert.True(t, marked.AffTopUpCredited)

	// Second qualifying top-up: no double pay.
	require.NoError(t, DB.Transaction(func(tx *gorm.DB) error {
		var err error
		inviterId, bonus, err = maybeGrantAffTopUpBonus(tx, referred.Id, 50*500000)
		return err
	}))
	assert.Zero(t, inviterId)
	assert.Zero(t, bonus)
	require.NoError(t, DB.First(&updated, inviter.Id).Error)
	assert.Equal(t, 1500000, updated.AffQuota)
}

func TestMaybeGrantAffTopUpBonusBelowThreshold(t *testing.T) {
	truncateTables(t)
	enableReferralTestDefaults(t)
	patchReferralTestOptions(t, func(o *referralTestOptions) {
		o.quotaForInviterTopUp = 1500000
		o.affTopUpMinAmount = 20
	})

	inviter := createReferralInviter(t, "inv3")
	referred := &User{Username: "referred-two", Password: "password", InviterId: inviter.Id, AffCode: "referred-two"}
	require.NoError(t, DB.Create(referred).Error)

	var inviterId, bonus int
	require.NoError(t, DB.Transaction(func(tx *gorm.DB) error {
		var err error
		inviterId, bonus, err = maybeGrantAffTopUpBonus(tx, referred.Id, 10*500000)
		return err
	}))
	assert.Zero(t, inviterId)
	assert.Zero(t, bonus)

	var marked User
	require.NoError(t, DB.First(&marked, referred.Id).Error)
	assert.False(t, marked.AffTopUpCredited)
}

func TestMaybeGrantAffTopUpBonusRequiresInviterAndCompliance(t *testing.T) {
	truncateTables(t)
	// No compliance confirm.
	patchReferralTestOptions(t, func(o *referralTestOptions) {
		o.complianceConfirmed = false
		o.quotaForInviterTopUp = 1500000
	})

	inviter := createReferralInviter(t, "inv4")
	referred := &User{Username: "referred-three", Password: "password", InviterId: inviter.Id, AffCode: "referred-three"}
	require.NoError(t, DB.Create(referred).Error)

	var inviterId, bonus int
	require.NoError(t, DB.Transaction(func(tx *gorm.DB) error {
		var err error
		inviterId, bonus, err = maybeGrantAffTopUpBonus(tx, referred.Id, 20*500000)
		return err
	}))
	assert.Zero(t, inviterId)
	assert.Zero(t, bonus)

	// Uninvited user stays unmarked even with compliance on.
	enableReferralTestDefaults(t)
	uninvited := &User{Username: "referred-four", Password: "password", AffCode: "referred-four"}
	require.NoError(t, DB.Create(uninvited).Error)
	require.NoError(t, DB.Transaction(func(tx *gorm.DB) error {
		var err error
		inviterId, bonus, err = maybeGrantAffTopUpBonus(tx, uninvited.Id, 20*500000)
		return err
	}))
	assert.Zero(t, inviterId)
	assert.Zero(t, bonus)
	var marked User
	require.NoError(t, DB.First(&marked, uninvited.Id).Error)
	assert.False(t, marked.AffTopUpCredited)
}

func TestMaybeGrantAffTopUpBonusSkipsMissingInviterWithoutFailingTopUp(t *testing.T) {
	truncateTables(t)
	enableReferralTestDefaults(t)
	patchReferralTestOptions(t, func(o *referralTestOptions) {
		o.quotaForInviterTopUp = 1500000
	})

	referred := &User{Username: "referred-five", Password: "password", InviterId: 999999, AffCode: "referred-five"}
	require.NoError(t, DB.Create(referred).Error)

	var inviterId, bonus int
	require.NoError(t, DB.Transaction(func(tx *gorm.DB) error {
		var err error
		inviterId, bonus, err = maybeGrantAffTopUpBonus(tx, referred.Id, 20*500000)
		return err
	}))
	assert.Zero(t, inviterId)
	assert.Zero(t, bonus)

	var marked User
	require.NoError(t, DB.First(&marked, referred.Id).Error)
	assert.True(t, marked.AffTopUpCredited, "marker stays flipped so the bonus is never retried")
}

func TestRechargeEpayGrantsAffTopUpBonusExactlyOnce(t *testing.T) {
	truncateTables(t)
	enableReferralTestDefaults(t)
	patchReferralTestOptions(t, func(o *referralTestOptions) {
		o.quotaForInviterTopUp = 1500000
		o.affTopUpMinAmount = 20
	})

	inviter := createReferralInviter(t, "inv5")
	referred := &User{Username: "referred-six", Password: "password", InviterId: inviter.Id, AffCode: "referred-six"}
	require.NoError(t, DB.Create(referred).Error)
	topUp := &TopUp{
		UserId:          referred.Id,
		Amount:          20,
		Money:           20.0,
		TradeNo:         "aff-epay-1",
		PaymentMethod:   PaymentProviderEpay,
		PaymentProvider: PaymentProviderEpay,
		CreateTime:      common.GetTimestamp(),
		Status:          common.TopUpStatusPending,
	}
	require.NoError(t, DB.Create(topUp).Error)

	alreadyDone, err := RechargeEpay(topUp.TradeNo, PaymentProviderEpay, "127.0.0.1")
	require.NoError(t, err)
	assert.False(t, alreadyDone)

	var updated User
	require.NoError(t, DB.First(&updated, inviter.Id).Error)
	assert.Equal(t, 1500000, updated.AffQuota)

	// Replayed webhook: idempotent, no second bonus and no error.
	alreadyDone, err = RechargeEpay(topUp.TradeNo, PaymentProviderEpay, "127.0.0.1")
	require.NoError(t, err)
	assert.True(t, alreadyDone)
	require.NoError(t, DB.First(&updated, inviter.Id).Error)
	assert.Equal(t, 1500000, updated.AffQuota)

	var referredUser User
	require.NoError(t, DB.First(&referredUser, referred.Id).Error)
	assert.Equal(t, 20*500000, referredUser.Quota)
}

func TestRechargeEpayBelowThresholdGrantsNoBonus(t *testing.T) {
	truncateTables(t)
	enableReferralTestDefaults(t)
	patchReferralTestOptions(t, func(o *referralTestOptions) {
		o.quotaForInviterTopUp = 1500000
		o.affTopUpMinAmount = 20
	})

	inviter := createReferralInviter(t, "inv6")
	referred := &User{Username: "referred-seven", Password: "password", InviterId: inviter.Id, AffCode: "referred-seven"}
	require.NoError(t, DB.Create(referred).Error)
	topUp := &TopUp{
		UserId:          referred.Id,
		Amount:          1,
		Money:           1.0,
		TradeNo:         "aff-epay-2",
		PaymentMethod:   PaymentProviderEpay,
		PaymentProvider: PaymentProviderEpay,
		CreateTime:      common.GetTimestamp(),
		Status:          common.TopUpStatusPending,
	}
	require.NoError(t, DB.Create(topUp).Error)

	_, err := RechargeEpay(topUp.TradeNo, PaymentProviderEpay, "127.0.0.1")
	require.NoError(t, err)

	var updated User
	require.NoError(t, DB.First(&updated, inviter.Id).Error)
	assert.Zero(t, updated.AffQuota)
}

func TestManualCompleteTopUpGrantsAffTopUpBonus(t *testing.T) {
	truncateTables(t)
	enableReferralTestDefaults(t)
	patchReferralTestOptions(t, func(o *referralTestOptions) {
		o.quotaForInviterTopUp = 1500000
		o.affTopUpMinAmount = 20
	})

	inviter := createReferralInviter(t, "inv7")
	referred := &User{Username: "referred-eight", Password: "password", InviterId: inviter.Id, AffCode: "referred-eight"}
	require.NoError(t, DB.Create(referred).Error)
	topUp := &TopUp{
		UserId:          referred.Id,
		Amount:          20,
		Money:           20.0,
		TradeNo:         "aff-manual-1",
		PaymentMethod:   PaymentProviderEpay,
		PaymentProvider: PaymentProviderEpay,
		CreateTime:      common.GetTimestamp(),
		Status:          common.TopUpStatusPending,
	}
	require.NoError(t, DB.Create(topUp).Error)

	require.NoError(t, ManualCompleteTopUp(topUp.TradeNo, "127.0.0.1"))
	var updated User
	require.NoError(t, DB.First(&updated, inviter.Id).Error)
	assert.Equal(t, 1500000, updated.AffQuota)

	// Completing an already-successful order pays nothing more.
	require.NoError(t, ManualCompleteTopUp(topUp.TradeNo, "127.0.0.1"))
	require.NoError(t, DB.First(&updated, inviter.Id).Error)
	assert.Equal(t, 1500000, updated.AffQuota)
}
