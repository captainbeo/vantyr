package helper

import (
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/QuantumNous/new-api/common"
	"github.com/QuantumNous/new-api/relaykit/types"
	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestEventStreamStarted(t *testing.T) {
	gin.SetMode(gin.TestMode)

	newCtx := func() *gin.Context {
		c, _ := gin.CreateTestContext(httptest.NewRecorder())
		c.Request = httptest.NewRequest(http.MethodPost, "/v1/messages", nil)
		return c
	}

	c := newCtx()
	assert.False(t, EventStreamStarted(c), "nothing written")

	c = newCtx()
	SetEventStreamHeaders(c)
	assert.False(t, EventStreamStarted(c), "SSE headers alone are not on the wire")

	c = newCtx()
	SetEventStreamHeaders(c)
	require.NoError(t, PingEventData(c))
	assert.True(t, EventStreamStarted(c), "a keep-alive commits the 200 event stream")
	assert.False(t, common.ClientContentWritten(c), "but it is not content")

	c = newCtx()
	c.JSON(http.StatusOK, gin.H{"ok": true})
	assert.False(t, EventStreamStarted(c), "a JSON response is not an event stream")
}

func TestStreamErrorFrames(t *testing.T) {
	apiErr := types.WithClaudeError(types.ClaudeError{Type: "api_error", Message: "upstream failed mid-stream"}, http.StatusInternalServerError)

	claude := StreamErrorFrames(types.RelayFormatClaude, apiErr, "resp_x")
	assert.True(t, strings.HasPrefix(claude, "event: error\ndata: {"), claude)
	assert.Contains(t, claude, `"type":"error"`)
	assert.Contains(t, claude, `"message":"upstream failed mid-stream"`)
	assert.True(t, strings.HasSuffix(claude, "\n\n"))

	openaiErr := types.NewOpenAIError(errors.New("upstream failed"), types.ErrorCodeBadResponseStatusCode, http.StatusBadGateway)
	responses := StreamErrorFrames(types.RelayFormatOpenAIResponses, openaiErr, "resp_req1")
	assert.Contains(t, responses, "event: error\ndata: ")
	assert.Contains(t, responses, "event: response.failed\ndata: ")
	assert.Contains(t, responses, `"id":"resp_req1"`)
	assert.Contains(t, responses, `"status":"failed"`)
	assert.True(t, strings.HasSuffix(responses, "\n\n"))

	chat := StreamErrorFrames(types.RelayFormatOpenAI, openaiErr, "resp_x")
	assert.True(t, strings.HasPrefix(chat, `data: {"error":{`), chat)
	assert.True(t, strings.HasSuffix(chat, "\n\n"))
	assert.NotContains(t, chat, "event:")
}

func TestWriteStreamErrorAppendsFrameAfterContent(t *testing.T) {
	gin.SetMode(gin.TestMode)
	recorder := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(recorder)
	c.Request = httptest.NewRequest(http.MethodPost, "/v1/messages", nil)
	SetEventStreamHeaders(c)
	_, _ = c.Writer.Write([]byte("event: message_start\ndata: {}\n\n"))

	apiErr := types.WithClaudeError(types.ClaudeError{Type: "api_error", Message: "boom"}, http.StatusInternalServerError)
	WriteStreamError(c, types.RelayFormatClaude, apiErr)

	body := recorder.Body.String()
	assert.True(t, strings.HasPrefix(body, "event: message_start"))
	assert.True(t, strings.HasSuffix(body, "\n\n"))
	assert.Contains(t, body, "event: error\ndata: ")
	assert.NotContains(t, body, "}{", "no JSON body glued onto the stream")
}
