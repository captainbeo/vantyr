package main

import (
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/stretchr/testify/require"
)

const testControlToken = "abcdefghijklmnopqrstuvwxyzABCDEF0123456789"
const testRelayToken = "0123456789abcdefghijklmnopqrstuvwxyzABCDEF"

func TestRelayRequiresItsOwnCredentialAndCapturesNoSecret(t *testing.T) {
	controlPath := writeTestSecret(t, "control", testControlToken)
	relayPath := writeTestSecret(t, "relay", testRelayToken)
	t.Setenv("MOCK_STATION_ID", "primary")
	t.Setenv("MOCK_UPSTREAM_MODEL", "fixture-model")
	t.Setenv("MOCK_CONTROL_TOKEN_FILE", controlPath)
	t.Setenv("MOCK_RELAY_TOKEN_FILE", relayPath)
	configured, err := loadStation()
	require.NoError(t, err)

	wrong := httptest.NewRequest(http.MethodPost, "/v1/responses", strings.NewReader(`{"model":"fixture-model"}`))
	wrong.Header.Set("Content-Type", "application/json")
	wrong.Header.Set("Authorization", "Bearer "+testControlToken)
	wrongResponse := httptest.NewRecorder()
	configured.publicHandler().ServeHTTP(wrongResponse, wrong)
	require.Equal(t, http.StatusUnauthorized, wrongResponse.Code)

	valid := httptest.NewRequest(http.MethodPost, "/v1/responses", strings.NewReader(`{"model":"fixture-model","stream":false}`))
	valid.Header.Set("Content-Type", "application/json")
	valid.Header.Set("Authorization", "Bearer "+testRelayToken)
	validResponse := httptest.NewRecorder()
	configured.publicHandler().ServeHTTP(validResponse, valid)
	require.Equal(t, http.StatusOK, validResponse.Code)

	captureRequest := httptest.NewRequest(http.MethodGet, "/control/attempts", nil)
	captureRequest.Header.Set("Authorization", "Bearer "+testControlToken)
	captureResponse := httptest.NewRecorder()
	configured.controlHandler().ServeHTTP(captureResponse, captureRequest)
	require.Equal(t, http.StatusOK, captureResponse.Code)
	var capture struct {
		StationID          string `json:"station_id"`
		TotalAttempts      uint64 `json:"total_attempts"`
		AuthorizedAttempts uint64 `json:"authorized_attempts"`
		RejectedAttempts   uint64 `json:"rejected_attempts"`
		LastAttempt        struct {
			Model           string `json:"model"`
			CredentialValid bool   `json:"credential_valid"`
		} `json:"last_attempt"`
	}
	require.NoError(t, json.Unmarshal(captureResponse.Body.Bytes(), &capture))
	require.Equal(t, "primary", capture.StationID)
	require.Equal(t, uint64(2), capture.TotalAttempts)
	require.Equal(t, uint64(1), capture.AuthorizedAttempts)
	require.Equal(t, uint64(1), capture.RejectedAttempts)
	require.Equal(t, "fixture-model", capture.LastAttempt.Model)
	require.True(t, capture.LastAttempt.CredentialValid)
	require.NotContains(t, captureResponse.Body.String(), testControlToken)
	require.NotContains(t, captureResponse.Body.String(), testRelayToken)
}

func TestAttemptCaptureStartsEmptyWithoutInventingRequestMetadata(t *testing.T) {
	configured := configuredTestStation()
	request := httptest.NewRequest(http.MethodGet, "/control/attempts", nil)
	request.Header.Set("Authorization", "Bearer "+testControlToken)
	response := httptest.NewRecorder()

	configured.controlHandler().ServeHTTP(response, request)

	require.Equal(t, http.StatusOK, response.Code)
	require.JSONEq(t, `{"station_id":"primary","total_attempts":0,"authorized_attempts":0,"rejected_attempts":0,"last_attempt":null}`, response.Body.String())
}

func writeTestSecret(t *testing.T, name string, value string) string {
	t.Helper()
	path := filepath.Join(t.TempDir(), name)
	require.NoError(t, os.WriteFile(path, []byte(value), 0o600))
	return path
}

func configuredTestStation() *station {
	return &station{id: "primary", upstreamModel: "fixture-model", controlToken: testControlToken, relayToken: testRelayToken}
}

func TestHealthIsDetailFree(t *testing.T) {
	configured := configuredTestStation()
	request := httptest.NewRequest(http.MethodGet, "/healthz", nil)
	response := httptest.NewRecorder()
	configured.publicHandler().ServeHTTP(response, request)
	require.Equal(t, http.StatusNoContent, response.Code)
	require.Empty(t, response.Body.String())
	require.Empty(t, response.Header().Get("X-Mock-Station-ID"))
}

func TestControlRequiresTokenAndChangesOnlyAllowlistedMode(t *testing.T) {
	configured := configuredTestStation()

	unauthorized := httptest.NewRequest(http.MethodPut, "/control/mode", strings.NewReader(`{"mode":"unavailable"}`))
	unauthorized.Header.Set("Content-Type", "application/json")
	unauthorizedResponse := httptest.NewRecorder()
	configured.controlHandler().ServeHTTP(unauthorizedResponse, unauthorized)
	require.Equal(t, http.StatusUnauthorized, unauthorizedResponse.Code)
	require.Equal(t, configured.id, unauthorizedResponse.Header().Get("X-Mock-Station-ID"))
	require.Equal(t, "Bearer", unauthorizedResponse.Header().Get("WWW-Authenticate"))

	setMode := httptest.NewRequest(http.MethodPut, "/control/mode", strings.NewReader(`{"mode":"unavailable"}`))
	setMode.Header.Set("Content-Type", "application/json")
	setMode.Header.Set("Authorization", "Bearer "+testControlToken)
	setModeResponse := httptest.NewRecorder()
	configured.controlHandler().ServeHTTP(setModeResponse, setMode)
	require.Equal(t, http.StatusNoContent, setModeResponse.Code)
	require.Equal(t, configured.id, setModeResponse.Header().Get("X-Mock-Station-ID"))
	require.True(t, configured.unavailable.Load())

	invalid := httptest.NewRequest(http.MethodPut, "/control/mode", strings.NewReader(`{"mode":"redirect","url":"http://example.invalid"}`))
	invalid.Header.Set("Content-Type", "application/json")
	invalid.Header.Set("Authorization", "Bearer "+testControlToken)
	invalidResponse := httptest.NewRecorder()
	configured.controlHandler().ServeHTTP(invalidResponse, invalid)
	require.Equal(t, http.StatusBadRequest, invalidResponse.Code)
	require.Equal(t, configured.id, invalidResponse.Header().Get("X-Mock-Station-ID"))
	require.True(t, configured.unavailable.Load())
}

func TestRelayModeIsDeterministicAndBounded(t *testing.T) {
	configured := configuredTestStation()

	normal := httptest.NewRequest(http.MethodPost, "/v1/responses", strings.NewReader(`{"model":"fixture-model","input":"hello"}`))
	normal.Header.Set("Content-Type", "application/json")
	normal.Header.Set("Authorization", "Bearer "+testRelayToken)
	normalResponse := httptest.NewRecorder()
	configured.publicHandler().ServeHTTP(normalResponse, normal)
	require.Equal(t, http.StatusOK, normalResponse.Code)
	require.Equal(t, configured.id, normalResponse.Header().Get("X-Mock-Station-ID"))
	require.Contains(t, normalResponse.Body.String(), `"model":"fixture-model"`)
	require.NotContains(t, normalResponse.Body.String(), configured.id)

	configured.unavailable.Store(true)
	unavailable := httptest.NewRequest(http.MethodPost, "/v1/responses", strings.NewReader(`{"model":"fixture-model"}`))
	unavailable.Header.Set("Content-Type", "application/json")
	unavailable.Header.Set("Authorization", "Bearer "+testRelayToken)
	unavailableResponse := httptest.NewRecorder()
	configured.publicHandler().ServeHTTP(unavailableResponse, unavailable)
	require.Equal(t, http.StatusServiceUnavailable, unavailableResponse.Code)
	require.Equal(t, configured.id, unavailableResponse.Header().Get("X-Mock-Station-ID"))
	require.NotContains(t, unavailableResponse.Body.String(), configured.id)

	oversized := httptest.NewRequest(http.MethodPost, "/v1/responses", strings.NewReader(`{"input":"`+strings.Repeat("a", maxRequestBytes)+`"}`))
	oversized.Header.Set("Content-Type", "application/json")
	oversized.Header.Set("Authorization", "Bearer "+testRelayToken)
	oversizedResponse := httptest.NewRecorder()
	configured.publicHandler().ServeHTTP(oversizedResponse, oversized)
	require.Equal(t, http.StatusRequestEntityTooLarge, oversizedResponse.Code)
	require.Equal(t, configured.id, oversizedResponse.Header().Get("X-Mock-Station-ID"))
	require.Contains(t, oversizedResponse.Body.String(), `"code":"request_too_large"`)
}

func TestBothStationsReturnContractedJSONAndSSEFixtures(t *testing.T) {
	for _, test := range []struct {
		id    string
		model string
	}{
		{id: "primary", model: "primary-fixture-model"},
		{id: "secondary", model: "secondary-fixture-model"},
	} {
		t.Run(test.id, func(t *testing.T) {
			configured := &station{id: test.id, upstreamModel: test.model, controlToken: testControlToken, relayToken: testRelayToken}

			jsonRequest := httptest.NewRequest(http.MethodPost, "/v1/responses", strings.NewReader(`{"model":"`+test.model+`","stream":false}`))
			jsonRequest.Header.Set("Content-Type", "application/json")
			jsonRequest.Header.Set("Authorization", "Bearer "+testRelayToken)
			jsonResponse := httptest.NewRecorder()
			configured.publicHandler().ServeHTTP(jsonResponse, jsonRequest)
			require.Equal(t, http.StatusOK, jsonResponse.Code)
			require.Equal(t, "application/json", jsonResponse.Header().Get("Content-Type"))
			require.Equal(t, test.id, jsonResponse.Header().Get(stationIDHeader))
			var jsonFixture struct {
				Model  string `json:"model"`
				Status string `json:"status"`
			}
			require.NoError(t, json.Unmarshal(jsonResponse.Body.Bytes(), &jsonFixture))
			require.Equal(t, test.model, jsonFixture.Model)
			require.Equal(t, "completed", jsonFixture.Status)

			sseRequest := httptest.NewRequest(http.MethodPost, "/v1/responses", strings.NewReader(`{"model":"`+test.model+`","stream":true}`))
			sseRequest.Header.Set("Content-Type", "application/json")
			sseRequest.Header.Set("Authorization", "Bearer "+testRelayToken)
			sseResponse := httptest.NewRecorder()
			configured.publicHandler().ServeHTTP(sseResponse, sseRequest)
			require.Equal(t, http.StatusOK, sseResponse.Code)
			require.Equal(t, "text/event-stream", sseResponse.Header().Get("Content-Type"))
			require.Equal(t, test.id, sseResponse.Header().Get(stationIDHeader))

			var eventTypes []string
			for _, block := range strings.Split(strings.TrimSpace(sseResponse.Body.String()), "\n\n") {
				require.True(t, strings.HasPrefix(block, "data: "))
				var frame struct {
					Type     string `json:"type"`
					Response struct {
						Model string `json:"model"`
					} `json:"response"`
				}
				require.NoError(t, json.Unmarshal([]byte(strings.TrimPrefix(block, "data: ")), &frame))
				eventTypes = append(eventTypes, frame.Type)
				require.Equal(t, test.model, frame.Response.Model)
			}
			require.Equal(t, []string{"response.created", "response.completed"}, eventTypes)

			compactModel := test.model + "-openai-compact"
			compactRequest := httptest.NewRequest(http.MethodPost, "/v1/responses/compact", strings.NewReader(`{"model":"`+compactModel+`"}`))
			compactRequest.Header.Set("Content-Type", "application/json")
			compactRequest.Header.Set("Authorization", "Bearer "+testRelayToken)
			compactResponse := httptest.NewRecorder()
			configured.publicHandler().ServeHTTP(compactResponse, compactRequest)
			require.Equal(t, http.StatusOK, compactResponse.Code)

			capture := configured.attemptSnapshot()
			require.Equal(t, uint64(3), capture.TotalAttempts)
			require.Equal(t, uint64(3), capture.AuthorizedAttempts)
			require.Equal(t, uint64(0), capture.RejectedAttempts)
			require.NotNil(t, capture.LastAttempt)
			require.False(t, capture.LastAttempt.Stream)
			require.Equal(t, compactModel, capture.LastAttempt.Model)
		})
	}
}

func TestRelayRejectsMoreThanContractedPropertyLimit(t *testing.T) {
	configured := configuredTestStation()
	body := strings.Builder{}
	body.WriteByte('{')
	for index := 0; index < 129; index++ {
		if index > 0 {
			body.WriteByte(',')
		}
		body.WriteString(`"field`)
		body.WriteString(fmt.Sprint(index))
		body.WriteString(`":true`)
	}
	body.WriteByte('}')

	request := httptest.NewRequest(http.MethodPost, "/v1/responses", strings.NewReader(body.String()))
	request.Header.Set("Content-Type", "application/json")
	request.Header.Set("Authorization", "Bearer "+testRelayToken)
	response := httptest.NewRecorder()
	configured.publicHandler().ServeHTTP(response, request)
	require.Equal(t, http.StatusBadRequest, response.Code)
	require.Equal(t, configured.id, response.Header().Get("X-Mock-Station-ID"))
}

func TestControlRejectsOversizedBodyWithIdentity(t *testing.T) {
	configured := configuredTestStation()
	request := httptest.NewRequest(http.MethodPut, "/control/mode", strings.NewReader(`{"mode":"`+strings.Repeat("a", 129)+`"}`))
	request.Header.Set("Content-Type", "application/json")
	request.Header.Set("Authorization", "Bearer "+testControlToken)
	response := httptest.NewRecorder()
	configured.controlHandler().ServeHTTP(response, request)
	require.Equal(t, http.StatusRequestEntityTooLarge, response.Code)
	require.Equal(t, configured.id, response.Header().Get("X-Mock-Station-ID"))
}

func TestRelayRejectsOversizedTrailingBytesWithIdentity(t *testing.T) {
	configured := configuredTestStation()
	body := `{"model":"fixture-model"}` + strings.Repeat(" ", maxRequestBytes)
	request := httptest.NewRequest(http.MethodPost, "/v1/responses", strings.NewReader(body))
	request.Header.Set("Content-Type", "application/json")
	request.Header.Set("Authorization", "Bearer "+testRelayToken)
	response := httptest.NewRecorder()

	configured.publicHandler().ServeHTTP(response, request)

	require.Equal(t, http.StatusRequestEntityTooLarge, response.Code)
	require.Equal(t, configured.id, response.Header().Get("X-Mock-Station-ID"))
	require.Contains(t, response.Body.String(), `"code":"request_too_large"`)
}

func TestControlRejectsOversizedTrailingBytesWithoutMutation(t *testing.T) {
	configured := configuredTestStation()
	body := `{"mode":"unavailable"}` + strings.Repeat(" ", 128)
	request := httptest.NewRequest(http.MethodPut, "/control/mode", strings.NewReader(body))
	request.Header.Set("Content-Type", "application/json")
	request.Header.Set("Authorization", "Bearer "+testControlToken)
	response := httptest.NewRecorder()

	configured.controlHandler().ServeHTTP(response, request)

	require.Equal(t, http.StatusRequestEntityTooLarge, response.Code)
	require.Equal(t, configured.id, response.Header().Get("X-Mock-Station-ID"))
	require.Contains(t, response.Body.String(), `"code":"request_too_large"`)
	require.False(t, configured.unavailable.Load())
}
