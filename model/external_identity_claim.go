package model

import (
	"errors"
	"fmt"
	"strings"
	"time"

	"github.com/QuantumNous/new-api/common"

	"gorm.io/gorm"
	"gorm.io/gorm/clause"
)

const ExternalIdentityProviderTelegram = "telegram"

var ErrExternalIdentityAlreadyClaimed = errors.New("external identity is already claimed")

// ExternalIdentityClaim is the durable ownership record for an identity issued
// by an external provider. The two unique indexes make both the provider
// subject and the user's provider slot single-owner without relying on a
// check-then-update sequence.
type ExternalIdentityClaim struct {
	Id        int64     `json:"id" gorm:"primaryKey"`
	Provider  string    `json:"provider" gorm:"type:varchar(32);not null;uniqueIndex:idx_external_identity_subject,priority:1;uniqueIndex:idx_external_identity_user,priority:1"`
	Subject   string    `json:"subject" gorm:"type:varchar(128);not null;uniqueIndex:idx_external_identity_subject,priority:2"`
	UserId    int       `json:"user_id" gorm:"not null;index;uniqueIndex:idx_external_identity_user,priority:2"`
	CreatedAt time.Time `json:"created_at"`
}

func (ExternalIdentityClaim) TableName() string {
	return "external_identity_claims"
}

// ClaimExternalIdentityWithTx atomically claims a provider subject for one
// user. Repeating the exact mapping is idempotent; every competing subject or
// user is rejected. Ownership is read back instead of trusting RowsAffected,
// whose duplicate-key semantics differ between supported databases.
func ClaimExternalIdentityWithTx(tx *gorm.DB, provider, subject string, userId int) error {
	provider = strings.TrimSpace(provider)
	subject = strings.TrimSpace(subject)
	if tx == nil || provider == "" || subject == "" || userId == 0 {
		return errors.New("external identity claim is invalid")
	}

	claim := ExternalIdentityClaim{Provider: provider, Subject: subject, UserId: userId}
	result := tx.Clauses(clause.OnConflict{DoNothing: true}).Create(&claim)
	if result.Error != nil {
		return result.Error
	}
	var subjectOwner ExternalIdentityClaim
	if err := tx.Where("provider = ? AND subject = ?", provider, subject).First(&subjectOwner).Error; err != nil {
		if errors.Is(err, gorm.ErrRecordNotFound) {
			return ErrExternalIdentityAlreadyClaimed
		}
		return err
	}
	if subjectOwner.UserId != userId {
		return ErrExternalIdentityAlreadyClaimed
	}

	var userClaim ExternalIdentityClaim
	if err := tx.Where("provider = ? AND user_id = ?", provider, userId).First(&userClaim).Error; err != nil {
		return err
	}
	if userClaim.Subject != subject {
		return ErrExternalIdentityAlreadyClaimed
	}
	return nil
}

func ReleaseExternalIdentityWithTx(tx *gorm.DB, provider string, userId int) error {
	provider = strings.TrimSpace(provider)
	if tx == nil || provider == "" || userId == 0 {
		return errors.New("external identity release is invalid")
	}
	return tx.Where("provider = ? AND user_id = ?", provider, userId).
		Delete(&ExternalIdentityClaim{}).Error
}

func GetUserByTelegramID(telegramID string) (*User, error) {
	var user User
	err := DB.Where("telegram_id = ?", telegramID).First(&user).Error
	return &user, err
}

// BindTelegramForSessionWithTx preserves single ownership and the session that
// started the binding. The caller consumes its OAuth flow in this transaction.
// Vantyr: binding a Telegram account no longer grants the trial credit — the
// grant moved to the login path so it can require group membership and be
// retried (GrantTelegramTrialWithTx). Bind only links the identity.
func BindTelegramForSessionWithTx(tx *gorm.DB, identity AuthSessionIdentity, telegramID string) error {
	if err := ValidateAuthSessionWithTx(tx, identity); err != nil {
		return err
	}
	var user User
	if err := tx.Select("id", "quota", "telegram_id").First(&user, identity.UserID).Error; err != nil {
		return err
	}
	if user.TelegramId != "" {
		return ErrExternalIdentityAlreadyClaimed
	}
	if err := ClaimExternalIdentityWithTx(tx, ExternalIdentityProviderTelegram, telegramID, user.Id); err != nil {
		return err
	}
	result := tx.Model(&User{}).Where("id = ? AND (telegram_id = ? OR telegram_id IS NULL)", user.Id, "").Update("telegram_id", telegramID)
	if result.Error != nil {
		return result.Error
	}
	if result.RowsAffected != 1 {
		return ErrExternalIdentityAlreadyClaimed
	}
	return nil
}

// GrantTelegramTrialWithTx pays the $5 Telegram trial once per user account,
// inside the caller's transaction. membership is decided by the controller
// (bot API call) before this runs. The per-user telegram_trial_credited
// marker is the dedup: it survives Telegram unbind/rebind and replaces the
// old one-grant-per-Telegram-account guarantee of the bind path, because a
// user may verify while not yet in the group and claim later. Bounded by
// MaxWalletQuota like the wallet.
func GrantTelegramTrialWithTx(tx *gorm.DB, userId int) (int, error) {
	credit := common.QuotaForNewUser
	if credit <= 0 {
		return 0, nil
	}
	var user User
	if err := tx.Clauses(clause.Locking{Strength: "UPDATE"}).
		Select("id", "quota", "telegram_trial_credited").First(&user, userId).Error; err != nil {
		return 0, err
	}
	if user.TelegramTrialCredited {
		return 0, nil
	}
	if user.Quota > common.MaxWalletQuota-credit {
		return 0, nil
	}
	result := tx.Model(&User{}).Where("id = ? AND telegram_trial_credited = ?", userId, false).
		Update("telegram_trial_credited", true)
	if result.Error != nil {
		return 0, result.Error
	}
	if result.RowsAffected != 1 {
		// Lost the race inside the transaction; treat as already granted.
		return 0, nil
	}
	if err := tx.Model(&User{}).Where("id = ?", userId).Update("quota", gorm.Expr("quota + ?", credit)).Error; err != nil {
		return 0, err
	}
	return credit, nil
}

// CreateTelegramUserWithTx registers a new account directly from a verified
// Telegram widget assertion (Vantyr: Telegram login doubles as registration).
// User creation and the Telegram identity claim are one transaction; the
// trial credit is granted in the same transaction only when the controller
// already confirmed group membership (grantTrial=true), otherwise the user
// claims it on a later login after joining. inviterId must already be
// resolved by the caller; the inviter reward itself is paid post-commit by
// FinalizeOAuthUserCreation, as for other OAuth signups.
func CreateTelegramUserWithTx(tx *gorm.DB, telegramID, username, displayName string, inviterId int, grantTrial bool) (*User, int, error) {
	user := &User{
		Username:    username,
		DisplayName: displayName,
		TelegramId:  telegramID,
		InviterId:   inviterId,
		Role:        common.RoleCommonUser,
		Status:      common.UserStatusEnabled,
	}
	if err := user.InsertWithTx(tx, inviterId); err != nil {
		return nil, 0, err
	}
	if err := ClaimExternalIdentityWithTx(tx, ExternalIdentityProviderTelegram, telegramID, user.Id); err != nil {
		return nil, 0, err
	}
	if grantTrial {
		credit, err := GrantTelegramTrialWithTx(tx, user.Id)
		if err != nil {
			return nil, 0, err
		}
		return user, credit, nil
	}
	return user, 0, nil
}

func releaseAllExternalIdentitiesWithTx(tx *gorm.DB, userId int) error {
	if tx == nil || userId == 0 {
		return errors.New("external identity release is invalid")
	}
	return tx.Where("user_id = ?", userId).Delete(&ExternalIdentityClaim{}).Error
}

// InitializeExternalIdentityClaims imports legacy Telegram bindings after the
// claim table is migrated. Existing duplicate ownership fails migration rather
// than preserving an ambiguous login identity.
func InitializeExternalIdentityClaims() error {
	var users []User
	if err := DB.Unscoped().Select("id", "telegram_id").
		Where("telegram_id <> ?", "").Find(&users).Error; err != nil {
		return err
	}
	return DB.Transaction(func(tx *gorm.DB) error {
		for _, user := range users {
			if err := ClaimExternalIdentityWithTx(tx, ExternalIdentityProviderTelegram, user.TelegramId, user.Id); err != nil {
				return fmt.Errorf("backfill Telegram identity for user %d: %w", user.Id, err)
			}
		}
		return nil
	})
}
