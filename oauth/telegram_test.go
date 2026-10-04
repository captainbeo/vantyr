package oauth

import (
	"net/url"
	"testing"

	"github.com/QuantumNous/new-api/setting/system_setting"
	"github.com/stretchr/testify/assert"
)

func TestTelegramAuthorizationURLCarriesOrigin(t *testing.T) {
	telegramSettings := system_setting.GetTelegramSettings()
	originalServerAddress := system_setting.ServerAddress
	defer func() {
		system_setting.ServerAddress = originalServerAddress
		telegramSettings.ClientID = ""
	}()

	telegramSettings.ClientID = "8655936058"
	system_setting.ServerAddress = "https://vantyr.xyz"

	flow := &TelegramOAuthFlow{
		CodeVerifier: "verifier",
		ClientID:     telegramSettings.ClientID,
		RedirectURI:  "https://vantyr.xyz/oauth/telegram",
	}

	parsed, err := url.Parse(flow.AuthorizationURL("state-token"))
	assert.NoError(t, err)
	assert.Equal(t, "/auth", parsed.Path)
	query := parsed.Query()
	assert.Equal(t, "https://vantyr.xyz", query.Get("origin"))
	assert.Equal(t, "8655936058", query.Get("client_id"))
	assert.Equal(t, "https://vantyr.xyz/oauth/telegram", query.Get("redirect_uri"))
	assert.Equal(t, "S256", query.Get("code_challenge_method"))
	assert.NotEmpty(t, query.Get("code_challenge"))
}
