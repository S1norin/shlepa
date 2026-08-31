/*
 * Session token minting.
 *
 * Issues a short opaque token after a successful credential check.
 * The token material is process-local only (no persistence in this
 * source copy).
 */
#include <stdio.h>
#include <time.h>

#include "crypto.h"
#include "session.h"

void session_issue_token(char *out, size_t out_size)
{
    if (out == NULL || out_size < 13) {
        return;
    }

    unsigned int seed = (unsigned int)time(NULL);
    unsigned int h = checksum_bytes(&seed, sizeof seed);

    /* 12 hex chars + NUL. */
    snprintf(out, out_size, "%08x%04x", h, (unsigned int)(h * 2654435761u));
}
