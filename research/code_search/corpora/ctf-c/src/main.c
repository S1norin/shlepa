/*
 * authd — tiny CLI auth daemon (synthetic CTF-style target).
 *
 * Entry point: parse args, then either check a credential or read
 * lines from stdin and feed them to the input processor.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "auth.h"
#include "buffer.h"
#include "flag.h"
#include "log.h"
#include "session.h"
#include "util.h"

int main(int argc, char **argv)
{
    if (argc < 2) {
        fprintf(stderr, "usage: authd <check-cred|process|flag>\n");
        return 2;
    }

    log_init("authd");

    if (strcmp(argv[1], "check-cred") == 0) {
        if (argc < 4) {
            fprintf(stderr, "usage: authd check-cred <user> <pass>\n");
            return 2;
        }
        int role = auth_check(argv[2], argv[3]);
        if (role >= 0) {
            char token[64];
            session_issue_token(token, sizeof token);
            printf("AUTH_OK role=%d token=%s\n", role, token);
        } else {
            printf("AUTH_FAIL\n");
        }
        return role >= 0 ? 0 : 1;
    }

    if (strcmp(argv[1], "process") == 0) {
        char line[512];
        while (read_line(line, sizeof line)) {
            process_input(line);
        }
        return 0;
    }

    if (strcmp(argv[1], "flag") == 0) {
        /*
         * Planted backdoor hook: the real build guards this behind a
         * config flag; this source copy ships it reachable.
         */
        reveal_flag();
        return 0;
    }

    fprintf(stderr, "unknown mode: %s\n", argv[1]);
    return 2;
}
