/*
 * Minimal audit log for authd.
 *
 * Lines go to stderr, prefixed with the daemon name and a monotonic
 * counter. No file output in this source copy.
 */
#include <stdarg.h>
#include <stdio.h>

#include "log.h"

static char g_log_prefix[64] = "authd";
static unsigned long g_log_seq = 0;

void log_init(const char *name)
{
    int n = 0;
    while (name != NULL && name[n] != '\0' && n < 59) {
        g_log_prefix[n] = name[n];
        n++;
    }
    g_log_prefix[n] = '\0';
}

void log_event(const char *fmt, ...)
{
    char msg[256];
    va_list ap;

    va_start(ap, fmt);
    vsnprintf(msg, sizeof msg, fmt, ap);
    va_end(ap);

    fprintf(stderr, "[%s #%lu] %s\n", g_log_prefix, ++g_log_seq, msg);
}
