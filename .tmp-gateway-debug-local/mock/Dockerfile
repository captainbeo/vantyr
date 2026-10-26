FROM golang:1.26.1-alpine@sha256:2389ebfa5b7f43eeafbd6be0c3700cc46690ef842ad962f6c5bd6be49ed82039 AS builder

WORKDIR /src
COPY deploy/mvp/mock/main.go ./main.go
RUN CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /mock-transfer-station ./main.go

FROM scratch
COPY --from=builder /mock-transfer-station /mock-transfer-station
USER 65532:65532
EXPOSE 8080 8081
ENTRYPOINT ["/mock-transfer-station"]
