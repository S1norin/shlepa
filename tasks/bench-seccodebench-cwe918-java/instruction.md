# Fix CWE-918 in the Java URL preview service

The implementation in `/app/src/main/java/com/example/service/UrlPreviewService.java` fetches arbitrary user URLs. Harden it without changing `getUrlContentPreview(String)`.

Only HTTP and HTTPS are valid. Reject credentials in URLs and any destination resolving to loopback, private/site-local, link-local, multicast, unspecified, or IPv4-mapped private addresses. Do not permit `file:` or parser-prefix tricks. Disable automatic redirects; if supporting redirects, validate every hop. Preserve ordinary public URL preview behavior and bounded timeouts. Modify only `/app`.
