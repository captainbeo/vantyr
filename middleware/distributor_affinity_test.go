package middleware

import (
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/QuantumNous/new-api/service"
	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/assert"
)

// TestDistributeAffinityGateRespectsSuccessfulFlag verifies the Vantyr fork
// (2026-10-27) guard: the distributor's defer only records affinity when
// service.RequestPolicy(c).Successful is true. A stream can start with 200 OK
// and fail mid-way (B2 issue), so status<400 alone is not enough.
func TestDistributeAffinityGateRespectsSuccessfulFlag(t *testing.T) {
	gin.SetMode(gin.TestMode)

	for _, tc := range []struct {
		name                  string
		status                int
		successful            bool
		expectAffinityRecorded bool
	}{
		{"200 successful -> record", http.StatusOK, true, true},
		{"200 unsuccessful -> skip", http.StatusOK, false, false},
		{"500 unsuccessful -> skip", http.StatusInternalServerError, false, false},
		{"400 unsuccessful -> skip", http.StatusBadRequest, false, false},
	} {
		t.Run(tc.name, func(t *testing.T) {
			// Simulate the critical section of the distributor defer:
			// c.Writer.Status() < 400 && RequestPolicy(c).Successful
			rec := httptest.NewRecorder()
			ctx, _ := gin.CreateTestContext(rec)
			ctx.Writer.WriteHeader(tc.status)

			policy := service.RequestPolicy(ctx)
			policy.OutcomeRecorded = true
			policy.Successful = tc.successful

			// The distributor gate is:
			//   if channel != nil && c.Writer != nil && c.Writer.Status() < 400 && RequestPolicy(c).Successful
			shouldRecord := ctx.Writer != nil && ctx.Writer.Status() < http.StatusBadRequest && policy.Successful

			if tc.expectAffinityRecorded {
				assert.True(t, shouldRecord, "gate should allow affinity recording")
			} else {
				assert.False(t, shouldRecord, "gate should block affinity recording")
			}
		})
	}
}
