package common

import (
	"net/http/httptest"
	"testing"

	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/assert"
)

func newClientContentContext() (*gin.Context, *httptest.ResponseRecorder) {
	gin.SetMode(gin.TestMode)
	recorder := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(recorder)
	c.Request = httptest.NewRequest("POST", "/v1/messages", nil)
	return c, recorder
}

func TestClientContentWritten(t *testing.T) {
	t.Run("nothing written", func(t *testing.T) {
		c, _ := newClientContentContext()
		assert.False(t, ClientContentWritten(c))
	})

	t.Run("headers flushed with an empty body", func(t *testing.T) {
		c, _ := newClientContentContext()
		c.Writer.WriteHeaderNow()
		assert.False(t, ClientContentWritten(c))
	})

	t.Run("only keep-alive frames", func(t *testing.T) {
		c, _ := newClientContentContext()
		for range 3 {
			frame := []byte("event: ping\ndata: {\"type\":\"ping\"}\n\n")
			n, _ := c.Writer.Write(frame)
			AddKeepAliveBytes(c, n)
		}
		assert.False(t, ClientContentWritten(c), "keep-alives before the first token must still allow a retry")
	})

	t.Run("keep-alive then content", func(t *testing.T) {
		c, _ := newClientContentContext()
		n, _ := c.Writer.Write([]byte(": PING\n\n"))
		AddKeepAliveBytes(c, n)
		_, _ = c.Writer.Write([]byte("event: message_start\ndata: {}\n\n"))
		assert.True(t, ClientContentWritten(c))
	})

	t.Run("content without keep-alive", func(t *testing.T) {
		c, _ := newClientContentContext()
		_, _ = c.Writer.Write([]byte("data: {}\n\n"))
		assert.True(t, ClientContentWritten(c))
	})

	t.Run("nil context", func(t *testing.T) {
		assert.False(t, ClientContentWritten(nil))
		AddKeepAliveBytes(nil, 10)
	})
}
