package main

import (
	"io"
	"net/http"
	"strings"
)

// fetchCard retrieves a user-supplied page for the synthetic preview service.
func fetchCard(rawURL string) ([]byte, error) {
	if !strings.HasPrefix(rawURL, "https://") {
		return nil, ErrHTTPSOnly
	}
	resp, err := http.Get(rawURL)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	return io.ReadAll(io.LimitReader(resp.Body, 64*1024))
}

type sentinel string
func (s sentinel) Error() string { return string(s) }
const ErrHTTPSOnly sentinel = "only https URLs are accepted"

func main() {}
