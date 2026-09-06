#ifndef AUTHD_SESSION_H
#define AUTHD_SESSION_H

#include <stddef.h>

/* Mint a short opaque token into out (needs >= 13 bytes). */
void session_issue_token(char *out, size_t out_size);

#endif /* AUTHD_SESSION_H */
