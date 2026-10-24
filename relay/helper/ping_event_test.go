package helper

import (
	"bytes"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/gin-gonic/gin"
)

// PingData keeps its historical comment-frame behavior; PingEventData (the
// real-event keep-alive for Anthropic streams) must emit a protocol event.
func TestPingEventDataWritesRealEventFrame(t *testing.T) {
	gin.SetMode(gin.TestMode)

	for _, tc := range []struct {
		name     string
		fn       func(*gin.Context) error
		contains string
		banned   string
	}{
		{"comment ping stays a comment", PingData, ": PING", "event: ping"},
		{"event ping is a real frame", PingEventData, "event: ping", ": PING"},
		{"responses ping is a real in_progress event", PingResponsesEventData,
			"event: response.in_progress", ": PING"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			w := httptest.NewRecorder()
			c, _ := gin.CreateTestContext(w)
			c.Request = httptest.NewRequest("POST", "/v1/messages", nil)

			if err := tc.fn(c); err != nil {
				t.Fatalf("ping write failed: %v", err)
			}
			out := w.Body.String()
			if !bytes.Contains(w.Body.Bytes(), []byte(tc.contains)) {
				t.Fatalf("expected output to contain %q, got %q", tc.contains, out)
			}
			if strings.Contains(out, tc.banned) {
				t.Fatalf("expected output NOT to contain %q, got %q", tc.banned, out)
			}
			// SSE frame must be terminated so the client's parser sees a
			// complete event immediately (otherwise it stays buffered until
			// the next flush and does not reset idle timers).
			if !strings.HasSuffix(out, "\n\n") {
				t.Fatalf("SSE frame must end with blank line, got %q", out)
			}
		})
	}
}
