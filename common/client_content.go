package common

import (
	"sync"
	"sync/atomic"

	"github.com/gin-gonic/gin"
)

// Vantyr fork (2026-10-27): a relay retry must never start once part of an
// answer has reached the client. A retry writes a second response into the
// same stream, so the client receives the failed attempt's partial answer
// followed by another message_start and the backup's full answer (reproduced
// on the production image; live trails 95->82 at 20:33 and 22:08 UTC on
// 2026-10-26). Keep-alive frames are not content: they are written before the
// first token too, and a retry after them is safe. The keep-alive writers in
// relay/helper report their bytes here so the two can be told apart.

const keepAliveBytesKey = "vantyr_keepalive_bytes"

// keepAliveCounterMu guards get-or-create of the per-request counter. Pingers
// run in their own goroutines; this keeps two of them from each creating one.
var keepAliveCounterMu sync.Mutex

func keepAliveCounter(c *gin.Context) *atomic.Int64 {
	keepAliveCounterMu.Lock()
	defer keepAliveCounterMu.Unlock()
	if value, ok := c.Get(keepAliveBytesKey); ok {
		if counter, ok := value.(*atomic.Int64); ok {
			return counter
		}
	}
	counter := &atomic.Int64{}
	c.Set(keepAliveBytesKey, counter)
	return counter
}

// AddKeepAliveBytes records n bytes of keep-alive frames written to the client.
func AddKeepAliveBytes(c *gin.Context, n int) {
	if c == nil || n <= 0 {
		return
	}
	keepAliveCounter(c).Add(int64(n))
}

// ClientContentWritten reports whether anything other than keep-alive frames
// has been written to the client's response body.
func ClientContentWritten(c *gin.Context) bool {
	if c == nil || c.Writer == nil || !c.Writer.Written() {
		return false
	}
	var keepAlive int64
	if value, ok := c.Get(keepAliveBytesKey); ok {
		if counter, ok := value.(*atomic.Int64); ok {
			keepAlive = counter.Load()
		}
	}
	return int64(c.Writer.Size()) > keepAlive
}
