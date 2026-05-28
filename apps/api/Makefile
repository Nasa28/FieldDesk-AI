.PHONY: fmt fmt-check vet build test tidy quality

GOFILES := $(shell find . -type f -name '*.go' -not -path './tmp/*' -not -path './bin/*' -not -path './dist/*' -not -path './internal/database/db/*')

fmt:
	gofmt -w $(GOFILES)

fmt-check:
	@drift=$$(gofmt -l $(GOFILES)); \
	if [ -n "$$drift" ]; then \
		echo "gofmt required for:"; \
		echo "$$drift"; \
		exit 1; \
	fi

vet:
	go vet ./...

build:
	go build ./...

test:
	go test ./...

tidy:
	go mod tidy

quality: fmt-check vet build test
