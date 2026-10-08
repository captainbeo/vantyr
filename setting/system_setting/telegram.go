package system_setting

import (
	"strings"

	"github.com/QuantumNous/new-api/setting/config"
)

type TelegramSettings struct {
	ClientID     string `json:"client_id"`
	ClientSecret string `json:"client_secret"`

	// Vantyr: trial-credit gate. The $5 trial is granted only when the
	// verified Telegram account is a member of this Telegram group.
	// Empty chat id disables the membership gate (trial on verification
	// alone). Stored as text to accept both -100… numeric ids and @usernames.
	TrialGroupChatID string `json:"trial_group_chat_id"`
}

var telegramSettings TelegramSettings

func init() {
	config.GlobalConfig.Register("telegram", &telegramSettings)
}

func GetTelegramSettings() *TelegramSettings {
	return &telegramSettings
}

func (s *TelegramSettings) IsConfigured() bool {
	return strings.TrimSpace(s.ClientID) != "" && strings.TrimSpace(s.ClientSecret) != ""
}
