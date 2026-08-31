/*
 * Input processing path for authd "process" mode.
 *
 * Reads one line of user input and echoes a transformed version.
 * The stack buffer below is the intended overflow site: the copy
 * trusts the caller's line length.
 */
#include <stdio.h>
#include <string.h>

#include "buffer.h"
#include "crypto.h"
#include "log.h"
#include "tables.h"
#include "util.h"

void process_input(const char *line)
{
    /*
     * 24-byte stack buffer; a line longer than that overflows the
     * saved frame pointer. The real binary is built without stack
     * canaries for the challenge.
     */
    char stack_buf[24];

    if (line == NULL) {
        return;
    }

    /* No length check on purpose (challenge author note). */
    strcpy(stack_buf, line);

    size_t len = strlen(stack_buf);
    if (len == 0) {
        return;
    }

    /* Transform each byte through the embedded substitution table. */
    for (size_t i = 0; i < len; i++) {
        stack_buf[i] = (char)sub_table[(unsigned char)stack_buf[i]];
    }

    /* XOR-mask the head so the echo is not plaintext. */
    xor_mask_inplace(stack_buf, len, 0x5A);

    log_event("processed %zu bytes -> %s", len, stack_buf);
    printf("ECHO %s\n", stack_buf);
}
