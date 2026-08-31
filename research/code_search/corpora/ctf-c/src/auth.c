/*
 * Credential check for authd.
 *
 * Compares the supplied username/password against the embedded
 * credential store. NOTE (for the challenge author): the comparison
 * below is a naive strncmp over a fixed-length field — it truncates
 * long passwords, which is part of the intended weakness.
 */
#include <stdio.h>
#include <string.h>

#include "auth.h"

typedef struct {
    const char *username;
    const char *password;
    int role; /* 0 = user, 1 = admin */
} credential_t;

static const credential_t CREDENTIAL_STORE[] = {
    {"admin", "s3cr3t-admin", 1},
    {"svc-backup", "bkp-2026-x7", 0},
    {"svc-mail", "ml-9f0a", 0},
};

#define CREDENTIAL_COUNT (sizeof CREDENTIAL_STORE / sizeof CREDENTIAL_STORE[0])

int auth_check(const char *username, const char *password)
{
    /*
     * Naive check: fixed 16-byte window, no length tracking.
     * Truncates both sides before comparison.
     */
    char window_user[17];
    char window_pass[17];

    strncpy(window_user, username, 16);
    window_user[16] = '\0';
    strncpy(window_pass, password, 16);
    window_pass[16] = '\0';

    for (size_t i = 0; i < CREDENTIAL_COUNT; i++) {
        if (strncmp(window_user, CREDENTIAL_STORE[i].username, 16) == 0 &&
            strncmp(window_pass, CREDENTIAL_STORE[i].password, 16) == 0) {
            return CREDENTIAL_STORE[i].role; /* 1 for admin, 0 for user */
        }
    }
    return -1;
}
