package main

import (
	"crypto/subtle"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"regexp"
	"strings"
	"sync"
	"sync/atomic"
	"time"
)

const (
	maxRequestBytes  = 1 << 20
	maxRequestFields = 128
	stationIDHeader  = "X-Mock-Station-ID"
)

var (
	stationIDPattern = regexp.MustCompile(`^[a-z0-9-]{1,32}$`)
	modelPattern     = regexp.MustCompile(`^[A-Za-z0-9._:-]{1,128}$`)
	secretPattern    = regexp.MustCompile(`^[A-Za-z0-9._~-]{32,128}$`)
)

type station struct {
	id            string
	upstreamModel string
	controlToken  string
	relayToken    string
	unavailable   atomic.Bool
	attempts      attemptCapture
}

type controlRequest struct {
	Mode string `json:"mode"`
}

type attemptCapture struct {
	mu         sync.Mutex
	total      uint64
	authorized uint64
	rejected   uint64
	last       attemptSnapshot
}

type attemptSnapshot struct {
	Path            string `json:"path"`
	Model           string `json:"model,omitempty"`
	Stream          bool   `json:"stream"`
	CredentialValid bool   `json:"credential_valid"`
}

type attemptCaptureResponse struct {
	StationID          string           `json:"station_id"`
	TotalAttempts      uint64           `json:"total_attempts"`
	AuthorizedAttempts uint64           `json:"authorized_attempts"`
	RejectedAttempts   uint64           `json:"rejected_attempts"`
	LastAttempt        *attemptSnapshot `json:"last_attempt"`
}

func main() {
	if len(os.Args) == 2 && os.Args[1] == "--healthcheck" {
		if err := runHealthcheck(); err != nil {
			log.Print(err)
			os.Exit(1)
		}
		return
	}

	configured, err := loadStation()
	if err != nil {
		log.Fatal(err)
	}

	publicServer := &http.Server{
		Addr:              ":8080",
		Handler:           configured.publicHandler(),
		ReadHeaderTimeout: 2 * time.Second,
		ReadTimeout:       5 * time.Second,
		WriteTimeout:      5 * time.Second,
		MaxHeaderBytes:    16 << 10,
	}
	controlServer := &http.Server{
		Addr:              ":8081",
		Handler:           configured.controlHandler(),
		ReadHeaderTimeout: 2 * time.Second,
		ReadTimeout:       3 * time.Second,
		WriteTimeout:      3 * time.Second,
		MaxHeaderBytes:    8 << 10,
	}

	errors := make(chan error, 2)
	go func() { errors <- publicServer.ListenAndServe() }()
	go func() { errors <- controlServer.ListenAndServe() }()
	log.Fatal(<-errors)
}

func loadStation() (*station, error) {
	id := os.Getenv("MOCK_STATION_ID")
	if !stationIDPattern.MatchString(id) {
		return nil, errors.New("MOCK_STATION_ID is invalid")
	}
	model := os.Getenv("MOCK_UPSTREAM_MODEL")
	if !modelPattern.MatchString(model) {
		return nil, errors.New("MOCK_UPSTREAM_MODEL is invalid")
	}
	tokenPath := os.Getenv("MOCK_CONTROL_TOKEN_FILE")
	if tokenPath == "" {
		return nil, errors.New("MOCK_CONTROL_TOKEN_FILE is required")
	}
	token, err := readStationSecret(tokenPath)
	if err != nil {
		return nil, errors.New("mock control secret is unavailable")
	}
	relayTokenPath := os.Getenv("MOCK_RELAY_TOKEN_FILE")
	if relayTokenPath == "" {
		return nil, errors.New("MOCK_RELAY_TOKEN_FILE is required")
	}
	relayToken, err := readStationSecret(relayTokenPath)
	if err != nil {
		return nil, errors.New("mock relay secret is unavailable")
	}
	return &station{id: id, upstreamModel: model, controlToken: token, relayToken: relayToken}, nil
}

func readStationSecret(path string) (string, error) {
	raw, err := os.ReadFile(path)
	if err != nil {
		return "", err
	}
	value := strings.TrimSuffix(string(raw), "\n")
	if !secretPattern.MatchString(value) {
		return "", errors.New("mock secret is invalid")
	}
	return value, nil
}

func (s *station) publicHandler() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /healthz", func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusNoContent)
	})
	mux.HandleFunc("POST /v1/responses", s.handleResponse)
	mux.HandleFunc("POST /v1/responses/compact", s.handleResponse)
	return mux
}

func (s *station) controlHandler() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("PUT /control/mode", s.handleControl)
	mux.HandleFunc("GET /control/attempts", s.handleAttempts)
	return mux
}

func (s *station) handleResponse(w http.ResponseWriter, r *http.Request) {
	w.Header().Set(stationIDHeader, s.id)
	if !authenticateBearer(r.Header.Get("Authorization"), s.relayToken) {
		s.recordAttempt(attemptSnapshot{Path: r.URL.Path})
		w.Header().Set("WWW-Authenticate", "Bearer")
		writeError(w, http.StatusUnauthorized, "unauthorized")
		return
	}
	if r.Header.Get("Content-Type") != "application/json" {
		s.recordAttempt(attemptSnapshot{Path: r.URL.Path, CredentialValid: true})
		writeError(w, http.StatusUnsupportedMediaType, "invalid_content_type")
		return
	}
	r.Body = http.MaxBytesReader(w, r.Body, maxRequestBytes)
	var request map[string]json.RawMessage
	decoder := json.NewDecoder(r.Body)
	if err := decoder.Decode(&request); err != nil {
		s.recordAttempt(attemptSnapshot{Path: r.URL.Path, CredentialValid: true})
		var maxBytesError *http.MaxBytesError
		if errors.As(err, &maxBytesError) {
			writeError(w, http.StatusRequestEntityTooLarge, "request_too_large")
			return
		}
		writeError(w, http.StatusBadRequest, "invalid_request")
		return
	}
	if len(request) == 0 || len(request) > maxRequestFields {
		s.recordAttempt(attemptSnapshot{Path: r.URL.Path, CredentialValid: true})
		writeError(w, http.StatusBadRequest, "invalid_request")
		return
	}
	if err := requireEOF(decoder); err != nil {
		s.recordAttempt(attemptSnapshot{Path: r.URL.Path, CredentialValid: true})
		var maxBytesError *http.MaxBytesError
		if errors.As(err, &maxBytesError) {
			writeError(w, http.StatusRequestEntityTooLarge, "request_too_large")
			return
		}
		writeError(w, http.StatusBadRequest, "invalid_request")
		return
	}
	var requestedModel string
	if rawModel, ok := request["model"]; !ok || json.Unmarshal(rawModel, &requestedModel) != nil || !modelPattern.MatchString(requestedModel) {
		s.recordAttempt(attemptSnapshot{Path: r.URL.Path, CredentialValid: true})
		writeError(w, http.StatusBadRequest, "invalid_request")
		return
	}
	stream := false
	if rawStream, ok := request["stream"]; ok && json.Unmarshal(rawStream, &stream) != nil {
		s.recordAttempt(attemptSnapshot{Path: r.URL.Path, Model: requestedModel, CredentialValid: true})
		writeError(w, http.StatusBadRequest, "invalid_request")
		return
	}
	s.recordAttempt(attemptSnapshot{Path: r.URL.Path, Model: requestedModel, Stream: stream, CredentialValid: true})
	if requestedModel != s.upstreamModel && requestedModel != s.upstreamModel+"-openai-compact" {
		writeError(w, http.StatusBadRequest, "unexpected_model")
		return
	}
	if s.unavailable.Load() {
		writeError(w, http.StatusServiceUnavailable, "upstream_unavailable")
		return
	}
	if stream {
		s.writeStream(w, requestedModel)
		return
	}

	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(map[string]interface{}{
		"id":     "resp_fixture",
		"object": "response",
		"status": "completed",
		"model":  requestedModel,
		"output": []interface{}{},
		"usage": map[string]int{
			"input_tokens": 1, "output_tokens": 1, "total_tokens": 2,
		},
	})
}

func (s *station) writeStream(w http.ResponseWriter, responseModel string) {
	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Cache-Control", "no-cache")
	created := map[string]interface{}{
		"type": "response.created", "sequence_number": 1,
		"response": map[string]interface{}{
			"id": "resp_fixture", "object": "response", "status": "in_progress", "model": responseModel,
		},
	}
	completed := map[string]interface{}{
		"type": "response.completed", "sequence_number": 2,
		"response": map[string]interface{}{
			"id": "resp_fixture", "object": "response", "status": "completed", "model": responseModel,
			"error": nil, "usage": map[string]int{"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
		},
	}
	for _, event := range []map[string]interface{}{created, completed} {
		data, err := json.Marshal(event)
		if err != nil {
			return
		}
		_, _ = fmt.Fprintf(w, "data: %s\n\n", data)
	}
}

func (s *station) handleControl(w http.ResponseWriter, r *http.Request) {
	w.Header().Set(stationIDHeader, s.id)
	if !authenticateBearer(r.Header.Get("Authorization"), s.controlToken) {
		w.Header().Set("WWW-Authenticate", "Bearer")
		writeError(w, http.StatusUnauthorized, "unauthorized")
		return
	}
	if r.Header.Get("Content-Type") != "application/json" {
		writeError(w, http.StatusUnsupportedMediaType, "invalid_content_type")
		return
	}
	r.Body = http.MaxBytesReader(w, r.Body, 128)
	decoder := json.NewDecoder(r.Body)
	decoder.DisallowUnknownFields()
	var request controlRequest
	if err := decoder.Decode(&request); err != nil {
		var maxBytesError *http.MaxBytesError
		if errors.As(err, &maxBytesError) {
			writeError(w, http.StatusRequestEntityTooLarge, "request_too_large")
			return
		}
		writeError(w, http.StatusBadRequest, "invalid_control")
		return
	}
	if err := requireEOF(decoder); err != nil {
		var maxBytesError *http.MaxBytesError
		if errors.As(err, &maxBytesError) {
			writeError(w, http.StatusRequestEntityTooLarge, "request_too_large")
			return
		}
		writeError(w, http.StatusBadRequest, "invalid_control")
		return
	}
	switch request.Mode {
	case "normal":
		s.unavailable.Store(false)
	case "unavailable":
		s.unavailable.Store(true)
	default:
		writeError(w, http.StatusBadRequest, "invalid_control")
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

func (s *station) handleAttempts(w http.ResponseWriter, r *http.Request) {
	w.Header().Set(stationIDHeader, s.id)
	if !authenticateBearer(r.Header.Get("Authorization"), s.controlToken) {
		w.Header().Set("WWW-Authenticate", "Bearer")
		writeError(w, http.StatusUnauthorized, "unauthorized")
		return
	}
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(s.attemptSnapshot())
}

func authenticateBearer(provided string, token string) bool {
	expected := []byte("Bearer " + token)
	return subtle.ConstantTimeCompare([]byte(provided), expected) == 1
}

func (s *station) recordAttempt(attempt attemptSnapshot) {
	s.attempts.mu.Lock()
	defer s.attempts.mu.Unlock()
	s.attempts.total++
	if attempt.CredentialValid {
		s.attempts.authorized++
	} else {
		s.attempts.rejected++
	}
	s.attempts.last = attempt
}

func (s *station) attemptSnapshot() attemptCaptureResponse {
	s.attempts.mu.Lock()
	defer s.attempts.mu.Unlock()
	var last *attemptSnapshot
	if s.attempts.total > 0 {
		copied := s.attempts.last
		last = &copied
	}
	return attemptCaptureResponse{
		StationID: s.id, TotalAttempts: s.attempts.total,
		AuthorizedAttempts: s.attempts.authorized, RejectedAttempts: s.attempts.rejected,
		LastAttempt: last,
	}
}

func requireEOF(decoder *json.Decoder) error {
	var extra interface{}
	err := decoder.Decode(&extra)
	if errors.Is(err, io.EOF) {
		return nil
	}
	if err != nil {
		return err
	}
	return errors.New("request must contain one JSON value")
}

func writeError(w http.ResponseWriter, status int, code string) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(map[string]interface{}{
		"error": map[string]string{"code": code, "message": "mock request failed"},
	})
}

func runHealthcheck() error {
	client := &http.Client{Timeout: time.Second}
	response, err := client.Get("http://127.0.0.1:8080/healthz")
	if err != nil {
		return fmt.Errorf("mock healthcheck failed: %w", err)
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusNoContent {
		return fmt.Errorf("mock healthcheck returned status %d", response.StatusCode)
	}
	return nil
}
