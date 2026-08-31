/*
 * Small string/line helpers shared across authd.
 */
#include <stdio.h>
#include <string.h>

#include "util.h"

int read_line(char *buf, size_t buf_size)
{
    if (buf == NULL || buf_size == 0) {
        return 0;
    }

    size_t n = 0;
    int c;
    while ((c = getchar()) != EOF) {
        if (c == '\n') {
            break;
        }
        if (n + 1 < buf_size) {
            buf[n++] = (char)c;
        }
    }
    if (c == EOF && n == 0) {
        return 0;
    }
    buf[n] = '\0';
    return 1;
}

char *trim(char *s)
{
    if (s == NULL) {
        return NULL;
    }
    while (*s == ' ' || *s == '\t') {
        s++;
    }
    size_t len = strlen(s);
    while (len > 0 && (s[len - 1] == ' ' || s[len - 1] == '\t')) {
        s[--len] = '\0';
    }
    return s;
}
