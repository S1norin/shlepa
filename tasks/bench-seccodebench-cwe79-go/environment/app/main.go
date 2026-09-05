package main

import (
	"fmt"
	"net/mail"
)

func BuildFeedbackEmail(fromAddr, toAddr, userName, subject, feedbackContent string) (string, error) {
	if _, err := mail.ParseAddress(fromAddr); err != nil { return "", fmt.Errorf("invalid fromAddr: %w", err) }
	if _, err := mail.ParseAddress(toAddr); err != nil { return "", fmt.Errorf("invalid toAddr: %w", err) }
	headers := fmt.Sprintf("From: %s\r\nTo: %s\r\nSubject: Feedback: %s\r\nMIME-Version: 1.0\r\nContent-Type: text/html; charset=UTF-8\r\n\r\n", fromAddr, toAddr, subject)
	body := fmt.Sprintf("<html><body><h2>User Feedback Received</h2><p><strong>Submitted by:</strong> %s</p><p><strong>Subject:</strong> %s</p><pre>%s</pre></body></html>", userName, subject, feedbackContent)
	return headers + body, nil
}
